#!/usr/bin/env python3
"""Сбор слоя «Метрические книги в описях архивов Украины» из Викитеки («Архів»).

    python3 scripts/harvest_wikisource_arkhiv.py --check   # дамп, оглавление, опись, сверка с API
    python3 scripts/harvest_wikisource_arkhiv.py --fetch   # потоки дампа в кэш, с продолжением
    python3 scripts/harvest_wikisource_arkhiv.py --build   # докачать недостающее и собрать слой

Страницы берутся не через API, а из дампа `dumps.wikimedia.org/ukwikisource`
(`pages-articles-multistream`): по оглавлению видно, в каких сжатых потоках
лежат страницы пространства «Архів», и только эти потоки забираются
запросами Range — около девяноста запросов вместо двухсот тысяч страниц.
Почему так и что берётся — шапка `src/histctx/sources/wikisource_arkhiv.py`.

Проверочный первый запуск обязателен. `--check` находит последний готовый
дамп (`dumpstatus.json`), забирает оглавление (3,4 МБ, сверка md5), считает
страницы пространства 116, забирает один поток с описью ДАЖО ф. 1 оп. 80 и
разбирает её, а затем сверяет разбор с живой страницей через API
(`maxlag=5`, `net.USER_AGENT`). Колонок описи нет, дел меньше ожидаемого,
села Бобли в описи не нашлось — остановка с объяснением, а не подгонка.

`--fetch` складывает оглавление и потоки в `data/raw/wikisource_arkhiv/<дата>/`
(в `.gitignore`); оборванная докачка продолжается тем же вызовом — кусок,
уже лежащий в кэше с верным размером, повторно не запрашивается.

`--build` разбирает кэш и пишет:

* `data/out/metric_books_ua.json` — записи без точки (уезд и губерния вместо
  координаты), `write_records_json`;
* `data/out/geojson/metric_books_ua.geojson` — записи, у которых село
  надёжно нашлось на карте (указатель написаний GeoNames внутри уезда);
* `data/out/jsonl/metric_books_ua.jsonl` — весь слой (в `.gitignore`).

Права. Тексты Викитеки — CC BY-SA 4.0. Берутся метаданные дел — шифр,
название дела, уезд, годы, листы — со ссылкой на страницу описи; сканы и
аннотации остаются на Викитеке, имён людей в слое нет.
"""

from __future__ import annotations

import argparse
import bz2
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.ghcn import GhcnError, Provinces
from histctx.sources.wikisource_arkhiv import (
    METRIC_BOOKS_UA, NS_ARCHIVE, NS_PREFIX, SAMPLE_PAGE, ArkhivError, Client, Dump, Harvest,
    Page, UezdResolver, VillageIndex, build_entries, collect, entry_to_record, inventory_items,
    iter_pages, md5_of, parse_dumpstatus, parse_index, parse_inventory, read_chunk,
    stream_ranges,
)

CACHE = ROOT / "data" / "raw" / "wikisource_arkhiv"
OUT = ROOT / "data" / "out"
DISTRICTS = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"
NAME_VARIANTS = ROOT / "data" / "out" / "name_variants.json"

# Что должно найтись в описи-образце (замер 04.11.2026, дамп 20261101): 189
# дел, у дел 1–189 колонки «№ | Назва | Повіт | Роки | Аркушів», дело 4 —
# «Метричні книги церкви с. Бобли Ковельського повіту, 1840–1865».
SAMPLE_MIN_ROWS = 180
SAMPLE_VILLAGE = "Бобли"
# Страниц в пространстве «Архів» в дампе 20261101 — 213 563; описей с
# метрическими книгами — около 1 550. Меньше половины — дамп не тот.
MIN_ARCHIVE_PAGES = 100_000


def dump_dir(cache: Path, dump: Dump) -> Path:
    return cache / dump.date


def load_dump(client: Client, cache: Path, date: str | None) -> Dump:
    """Дамп по дате или последний готовый; `dumpstatus.json` кладётся в кэш."""
    if date:
        path = cache / date / "dumpstatus.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = client.get_json(f"https://dumps.wikimedia.org/ukwikisource/{date}/"
                                      "dumpstatus.json")
        dump = parse_dumpstatus(payload, date)
        if dump is None:
            raise ArkhivError(f"в дампе {date} multistream не готов")
    else:
        dump = client.latest_dump()
        payload = None
    path = cache / dump.date / "dumpstatus.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = payload or client.get_json(
            f"https://dumps.wikimedia.org/ukwikisource/{dump.date}/dumpstatus.json")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return dump


def offline_dump(cache: Path, date: str | None) -> Dump:
    dates = [date] if date else sorted((p.name for p in cache.glob("2*") if p.is_dir()),
                                       reverse=True)
    for d in dates:
        path = cache / d / "dumpstatus.json"
        if path.exists():
            dump = parse_dumpstatus(json.loads(path.read_text(encoding="utf-8")), d)
            if dump:
                return dump
    raise ArkhivError(f"в {cache} нет дампа с dumpstatus.json: сначала --fetch")


def load_index(client: Client | None, cache: Path, dump: Dump) -> list:
    """Оглавление дампа: из кэша или из сети, со сверкой md5."""
    path = dump_dir(cache, dump) / dump.index.name
    if not path.exists():
        if client is None:
            raise ArkhivError(f"нет {path}: сначала --fetch")
        data = client.get(dump.index.url)
        if md5_of(data) != dump.index.md5:
            raise ArkhivError(f"{dump.index.name}: md5 не сходится с dumpstatus.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    elif md5_of(path.read_bytes()) != dump.index.md5:
        raise ArkhivError(f"{path}: md5 не сходится с dumpstatus.json — удалите файл")
    with bz2.open(path, "rt", encoding="utf-8") as fh:
        return parse_index(fh)


def range_path(cache: Path, dump: Dump, start: int, end: int) -> Path:
    return dump_dir(cache, dump) / "streams" / f"{start:012d}-{end:012d}.bz2"


def fetch_ranges(client: Client | None, cache: Path, dump: Dump, ranges: list) -> list[Path]:
    """Куски дампа в кэш; уже лежащие с верным размером не запрашиваются."""
    paths = []
    todo = [(a, b) for a, b in ranges
            if not (range_path(cache, dump, a, b).exists()
                    and range_path(cache, dump, a, b).stat().st_size == b - a)]
    total = sum(b - a for a, b in todo)
    if todo:
        if client is None:
            raise ArkhivError(f"в кэше нет {len(todo)} кусков дампа: запустите --fetch")
        print(f"Докачать кусков: {len(todo)} из {len(ranges)}, {total / 1e6:.1f} МБ")
    for i, (a, b) in enumerate(todo, 1):
        path = range_path(cache, dump, a, b)
        data = client.get(dump.pages.url, byte_range=(a, b))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        if i % 10 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}", flush=True)
    for a, b in ranges:
        paths.append(range_path(cache, dump, a, b))
    return paths


def summarize_index(entries: list, dump: Dump) -> list:
    archive = [e for e in entries if e.title.startswith(NS_PREFIX)]
    ranges = stream_ranges(entries, dump.pages.size)
    depth = collections.Counter(e.title.count("/") for e in archive)
    print(f"Страниц в дампе: {len(entries)}, в пространстве «Архів»: {len(archive)} "
          f"(архив/фонд — {depth[1]}, опись — {depth[2]}, дело — {depth[3]})")
    print(f"Кусков Range: {len(ranges)}, {sum(b - a for a, b in ranges) / 1e6:.1f} МБ из "
          f"{dump.pages.size / 1e6:.1f}")
    if len(archive) < MIN_ARCHIVE_PAGES:
        raise ArkhivError(f"в оглавлении {len(archive)} страниц «Архів», ожидалось больше "
                          f"{MIN_ARCHIVE_PAGES}: дамп не тот или пространство переименовано")
    return ranges


def check(cache: Path, date: str | None) -> int:
    client = Client()
    dump = load_dump(client, cache, date)
    print(f"Дамп {dump.date}: страницы {dump.pages.size / 1e6:.1f} МБ, оглавление "
          f"{dump.index.size / 1e6:.1f} МБ (md5 {dump.index.md5})")
    entries = load_index(client, cache, dump)
    summarize_index(entries, dump)

    by_title = {e.title: e for e in entries}
    sample = by_title.get(SAMPLE_PAGE)
    if sample is None:
        raise ArkhivError(f"в оглавлении нет {SAMPLE_PAGE}: описи переименованы")
    offsets = sorted({e.offset for e in entries})
    nxt = offsets[offsets.index(sample.offset) + 1]
    pages = list(iter_pages(read_chunk(client.get(dump.pages.url,
                                                  byte_range=(sample.offset, nxt)))))
    page = next((p for p in pages if p.title == SAMPLE_PAGE), None)
    if page is None:
        raise ArkhivError(f"{SAMPLE_PAGE} не нашлась в своём потоке: оглавление не сходится")
    inv = parse_inventory(page)
    report_sample("дамп", inv)
    if inv is None or len(inv.rows) < SAMPLE_MIN_ROWS:
        raise ArkhivError(f"{SAMPLE_PAGE}: строк {len(inv.rows) if inv else 0}, ожидалось не "
                          f"меньше {SAMPLE_MIN_ROWS} — разметку описи поменяли")
    items = inventory_items(inv)
    if not any(it.subject.settlement == SAMPLE_VILLAGE for it in items):
        raise ArkhivError(f"{SAMPLE_PAGE}: среди дел нет села {SAMPLE_VILLAGE} — разбор "
                          "названий дел сломан")
    resolver = UezdResolver.load(DISTRICTS)
    for entry in build_entries(Harvest(inventories={inv.code: inv}))[:3]:
        rec = entry_to_record(entry, resolver, dump_date=dump.date)
        print(f"  {rec.title}\n      {rec.region} / {rec.district}; {rec.period_raw}; "
              f"дела {rec.extra.get('cases', '')[:80]}")

    try:
        live = client.api_page(SAMPLE_PAGE)
    except ArkhivError as exc:
        print(f"API: сверка не удалась ({exc}) — разбор дампа проверен, сверка с живой "
              "страницей отложена")
        live = None
    if live is not None:
        live_inv = parse_inventory(Page(SAMPLE_PAGE, NS_ARCHIVE, 0, "", live))
        report_sample("API", live_inv)
        if live_inv is None or abs(len(live_inv.rows) - len(inv.rows)) > 5:
            print("  API и дамп расходятся больше чем на пять строк: опись правили после "
                  "дампа — соберите со свежим дампом")
    print("\nДамп, оглавление и разбор описи на месте — можно запускать --fetch и --build.")
    return 0


def report_sample(where: str, inv) -> None:
    if inv is None:
        print(f"{where}: {SAMPLE_PAGE} — не опись")
        return
    cols = collections.Counter(k for row in inv.rows for k in row)
    print(f"{where}: {inv.title} «{inv.name}», {inv.years}; строк {len(inv.rows)}; колонки "
          f"{dict(cols.most_common())}")


def fetch(cache: Path, date: str | None) -> tuple[Dump, list[Path]]:
    client = Client()
    dump = load_dump(client, cache, date)
    entries = load_index(client, cache, dump)
    ranges = summarize_index(entries, dump)
    return dump, fetch_ranges(client, cache, dump, ranges)


def build(cache: Path, out_dir: Path, date: str | None, *, offline: bool, points: bool) -> int:
    if offline:
        dump = offline_dump(cache, date)
        entries = load_index(None, cache, dump)
        paths = fetch_ranges(None, cache, dump, summarize_index(entries, dump))
    else:
        dump, paths = fetch(cache, date)
    harvest = Harvest()
    for i, path in enumerate(paths, 1):
        collect(iter_pages(read_chunk(path.read_bytes())), harvest)
        if i % 20 == 0:
            print(f"  разобрано кусков {i}/{len(paths)}", flush=True)
    print(f"Страниц «Архів»: {harvest.pages}; описей с метрическими книгами: "
          f"{len(harvest.inventories)}; дел с «Содержанием»: "
          f"{sum(len(v) for v in harvest.contents.values())}; фондов: {len(harvest.fond_names)}")
    entries = build_entries(harvest)
    resolver = UezdResolver.load(DISTRICTS)
    villages = None
    if points:
        try:
            districts = Provinces.load(DISTRICTS, field="Distr_ID")
            items = json.loads(NAME_VARIANTS.read_text(encoding="utf-8"))["items"]
            villages = VillageIndex(items, districts)
        except (GhcnError, FileNotFoundError, KeyError) as exc:
            print(f"  точки сёл не ставятся: {exc}")
    records = [entry_to_record(e, resolver, fond_names=harvest.fond_names, villages=villages,
                               dump_date=dump.date) for e in entries]
    report(records)

    slug = METRIC_BOOKS_UA.slug
    territorial = [r for r in records if not r.has_point]
    located = [r for r in records if r.has_point]
    # Около двадцати тысяч записей без точки: общие свойства выносятся в
    # шапку файла и отступы не пишутся — 30 МБ вместо 42 (см. io_formats).
    n_json = write_records_json(territorial, out_dir / f"{slug}.json", title=METRIC_BOOKS_UA.title,
                                hoist_shared=True, compact=True)
    n_geo = write_geojson(located, out_dir / "geojson" / f"{slug}.geojson",
                          layer_title=METRIC_BOOKS_UA.title, hoist_shared=True)
    write_jsonl(records, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"\nСобрано {len(records)} записей: без точки {n_json} ({slug}.json), с точкой села "
          f"{n_geo} (geojson/{slug}.geojson); весь слой — jsonl/{slug}.jsonl.")
    return 0


def report(records: list) -> None:
    dated = [r for r in records if r.has_time]
    print(f"\nЗаписей: {len(records)}; с датировкой: {len(dated)}; с губернией 1897 года: "
          f"{sum(1 for r in records if r.region)}; с уездом 1897 года: "
          f"{sum(1 for r in records if r.extra.get('district_match') not in (None, 'interwar'))}"
          f"; с точкой села: {sum(1 for r in records if r.has_point)}")
    if dated:
        print(f"  годы: {min(r.year_from for r in dated)}–{max(r.year_to for r in dated)}")
    print("  достоверность:",
          dict(collections.Counter(r.confidence for r in records).most_common()))
    print("  сведение уезда:",
          dict(collections.Counter(r.extra.get("district_match") for r in records).most_common()))
    print("  по видам:", dict(collections.Counter(r.category for r in records).most_common()))
    print("  по архивам:",
          dict(collections.Counter(r.extra["archive"] for r in records).most_common()))
    cases = sum(r.extra.get("n_cases", 0) for r in records)
    print(f"  дел в записях (с повторами по приходам сводных томов): {cases}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="дамп, оглавление, опись-образец и сверка с API — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="оглавление и потоки дампа в кэш")
    ap.add_argument("--build", action="store_true", help="собрать слой в data/out")
    ap.add_argument("--offline", action="store_true", help="собирать только из кэша")
    ap.add_argument("--dump", default=None, help="дата дампа (20261101); по умолчанию последний")
    ap.add_argument("--no-points", action="store_true", help="не ставить точки сёл")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check:
            return check(args.cache, args.dump)
        if args.fetch and not args.build:
            dump, paths = fetch(args.cache, args.dump)
            print(f"Дамп {dump.date}: в кэше {len(paths)} кусков")
            return 0
        return build(args.cache, args.out, args.dump, offline=args.offline,
                     points=not args.no_points)
    except ArkhivError as exc:
        print(f"Викитека «Архів»: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; скачанное лежит в кэше, повторный вызов продолжит.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
