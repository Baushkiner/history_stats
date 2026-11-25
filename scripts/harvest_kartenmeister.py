#!/usr/bin/env python3
"""Сбор слоя мест Восточной Пруссии в нашей рамке из указателя Kartenmeister.

    python3 scripts/harvest_kartenmeister.py --check            # первая страница списка и пять карточек
    python3 scripts/harvest_kartenmeister.py --fetch            # список и все карточки в кэш, с продолжением
    python3 scripts/harvest_kartenmeister.py --build [--partial] # слой из кэша

Собрано с согласия владельца (сообщено владельцем проекта 24.11.2026).
Сайт по https обрывает соединение, по http отвечает; `robots.txt` нет.
Запросы — одним соединением, пауза от секунды (`--pause`), при 429/5xx она
растёт. Список мест — форма `Results.asp` по нынешней области (Kaliningrad,
Klaip), по 100 мест на страницу, около 180 страниц; карточка — на каждое
место, около 18 000 запросов (5–6 часов). Всё ложится в
`data/raw/kartenmeister/` (в `.gitignore`) сжатым gzip, и оборванный обход
продолжается тем же вызовом; `--limit` делит его на заходы.

`--build` без `--partial` собирает слой только из полного кэша; с
`--partial` — из того, что есть, и печатает, сколько карточек не хватает.

На выходе:

* `geojson/kartenmeister.geojson` — места с точкой, в репозиторий;
* `kartenmeister.json` — места без точки, если есть;
* `jsonl/kartenmeister.jsonl` — слой целиком (в `.gitignore`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.kartenmeister import (
    CARD_URL, ENCODING, EXPECTED, KARTENMEISTER, PAGE_SIZE, PAUSE, SEARCH_URL, TODAY_PROVINCES,
    Entry, KartenmeisterError, check_card, page_url, parse_card, parse_results, records,
    search_form,
)
from histctx.sources.polite import PoliteClient, cache_read, cache_write
from histctx.sources.russian_names import RussianNames

CACHE = ROOT / "data" / "raw" / "kartenmeister"
OUT = ROOT / "data" / "out"
BOUNDARIES = OUT / "boundaries"
NAMES = OUT / "name_variants.json"


def client(pause: float) -> PoliteClient:
    return PoliteClient(pause=pause, encoding=ENCODING, error=KartenmeisterError)


def cached(cl: PoliteClient, path: Path, url: str, data=None, *, refresh: bool = False) -> str:
    text = None if refresh else cache_read(path, ENCODING)
    if text is None:
        raw = cl.fetch(url, data)
        cache_write(path, raw)
        text = raw.decode(ENCODING, errors="replace")
    return text


def load_index(cl: PoliteClient, cache: Path, *, refresh: bool = False,
               first_only: bool = False) -> list[Entry]:
    entries: dict[int, Entry] = {}
    for prov in TODAY_PROVINCES:
        page1 = cached(cl, cache / "index" / f"{prov}_1.html.gz", SEARCH_URL, search_form(prov),
                       refresh=refresh)
        total, rows = parse_results(page1)
        if total is None:
            raise KartenmeisterError(f"{prov}: в ответе формы нет числа мест — разметку поменяли")
        pages = -(-total // PAGE_SIZE)
        print(f"  {prov}: {total} мест (замер — {EXPECTED.get(prov)}), страниц {pages}", flush=True)
        for row in rows:
            entries.setdefault(row.cit_num, row)
        if first_only:
            continue
        for page in range(2, pages + 1):
            text = cached(cl, cache / "index" / f"{prov}_{page}.html.gz", page_url(prov, page),
                          refresh=refresh)
            _, rows = parse_results(text)
            if not rows:
                raise KartenmeisterError(f"{prov}, страница {page}: мест нет")
            for row in rows:
                entries.setdefault(row.cit_num, row)
    return sorted(entries.values(), key=lambda e: e.cit_num)


def card_path(cache: Path, cit_num: int) -> Path:
    return cache / "cards" / f"{cit_num // 1000:03d}" / f"{cit_num}.html.gz"


def get_card(cl: PoliteClient, cache: Path, cit_num: int) -> dict:
    card = parse_card(cached(cl, card_path(cache, cit_num), CARD_URL.format(cit_num)))
    check_card(card, cit_num)
    return card


def check(cache: Path, pause: float, sample: int) -> int:
    cl = client(pause)
    index = load_index(cl, cache, first_only=True)
    names = RussianNames.load(NAMES) if NAMES.exists() else None
    step = max(1, len(index) // sample)
    for entry in index[::step][:sample]:
        rec = records([(entry.cit_num, get_card(cl, cache, entry.cit_num))], names=names)[0]
        print(f"  {entry.cit_num}: {rec.title}; {rec.lat}, {rec.lon}; {rec.year_from}–{rec.year_to}")
        print(f"      {rec.summary}")
    print(f"\nЗапросов: {cl.requests}, повторов: {cl.backoffs}. Поля на месте — можно --fetch.")
    return 0


def fetch(cache: Path, pause: float, *, refresh: bool, limit=None) -> list[Entry]:
    cl = client(pause)
    index = load_index(cl, cache, refresh=refresh)
    todo = [e for e in index if not card_path(cache, e.cit_num).exists()]
    print(f"Мест в списке: {len(index)}; карточек в кэше {len(index) - len(todo)}, "
          f"докачать {len(todo)}", flush=True)
    for i, entry in enumerate(todo[:limit] if limit else todo, 1):
        try:
            get_card(cl, cache, entry.cit_num)
        except KartenmeisterError as exc:
            print(f"  {exc}", file=sys.stderr, flush=True)
        if i % 200 == 0:
            print(f"  {i}/{len(todo)}; повторов {cl.backoffs}, пауза {cl.pause:g} с", flush=True)
    return index


def offline_index(cache: Path) -> list[Entry]:
    entries: dict[int, Entry] = {}
    for path in sorted((cache / "index").glob("*.html.gz")):
        for row in parse_results(cache_read(path, ENCODING))[1]:
            entries.setdefault(row.cit_num, row)
    if not entries:
        raise KartenmeisterError(f"нет списка мест в {cache / 'index'}: сначала --fetch")
    return sorted(entries.values(), key=lambda e: e.cit_num)


def build(cache: Path, out_dir: Path, *, partial: bool) -> int:
    index = offline_index(cache)
    cards, missing = [], []
    for entry in index:
        text = cache_read(card_path(cache, entry.cit_num), ENCODING)
        if text is None:
            missing.append(entry.cit_num)
            continue
        card = parse_card(text)
        if "German Name" not in card:
            missing.append(entry.cit_num)
            continue
        cards.append((entry.cit_num, card))
    if missing and not partial:
        print(f"Карточек нет в кэше: {len(missing)} — слой не собирается неполным; "
              "запустите --fetch ещё раз или соберите --partial", file=sys.stderr)
        return 1
    if missing:
        print(f"Неполный слой (--partial): карточек {len(cards)} из {len(index)}, "
              f"не хватает {len(missing)}")
    names = RussianNames.load(NAMES) if NAMES.exists() else None
    recs = records(cards, names=names)
    marks = Frame.load(BOUNDARIES).mark(recs)
    report(recs, marks)
    slug = KARTENMEISTER.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=KARTENMEISTER.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{KARTENMEISTER.title}: без точки",
                           hoist_shared=True)
    write_jsonl(recs, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"\n«{KARTENMEISTER.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def report(recs: list, marks: dict) -> None:
    print(f"Записей: {len(recs)}; с точкой: {sum(1 for r in recs if r.has_point)}")
    print("  рамка:", dict(marks))
    print("  нынешняя область:", dict(collections.Counter(
        r.extra.get("province_today") for r in recs).most_common(6)))
    print("  с лютеранским приходом 1905 года:",
          sum(1 for r in recs if r.extra.get("parish_lutheran_1905")))
    print("  с населением по годам:", sum(1 for r in recs if r.extra.get("population")))
    print("  подпись по-русски из указателя написаний:",
          sum(1 for r in recs if r.extra.get("name_local")
              and not r.title.endswith(r.extra["name_local"])))
    print("  крейсы:", collections.Counter(r.district for r in recs).most_common(8))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="перечитать список мест")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    if args.pause < 1.0:
        ap.error("пауза не меньше секунды")
    try:
        if args.check:
            return check(args.cache, args.pause, args.sample)
        if args.fetch:
            fetch(args.cache, args.pause, refresh=args.refresh, limit=args.limit)
        if args.build:
            return build(args.cache, args.out, partial=args.partial)
        return 0
    except KartenmeisterError as exc:
        print(f"Kartenmeister: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; скачанное лежит в кэше, повторный вызов продолжит.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
