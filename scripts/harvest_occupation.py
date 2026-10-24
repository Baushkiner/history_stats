#!/usr/bin/env python3
"""Сбор слоя оккупации и освобождения городов: справочник 1985 года на soldat.ru.

    python3 scripts/harvest_occupation.py --check    # живой запрос, сверка, разбор, без записи
    python3 scripts/harvest_occupation.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) заново скачивает оглавление справочника и шесть страниц
раздела СССР с приложением 2 («Хроника освобождения городов»), сверяет число
статей на каждой странице с записанным в `sources/occupation.py`, разбирает
статьи в периоды, сверяет даты освобождения с хроникой, сводит города
с точками Викиданных и GeoNames и сверяет периоды с набором Grunewald
(Harvard Dataverse, CC0). Расхождение в числе статей — остановка, а не
подгонка: страницы переверстали или поправили текст.

Права. Издание 1985 года; права на текст не выяснены. Сайт требует активную
ссылку на использованную страницу — она стоит в `url` каждой записи. Берутся
город, даты, область из пометки справочника и короткая справка «чьими
войсками и в ходе какой операции»; перечни частей с командирами не берутся.

На выходе:

* `geojson/occupation_cities.geojson` — записи с точкой города;
* `occupation_cities.json` — записи, которым точки не нашлось: в репозиторий
  идут оба файла, `jsonl/` в `.gitignore`;
* `jsonl/occupation_cities.jsonl` — слой целиком.

Нужны `data/out/geojson/settlements.geojson` и `data/out/name_variants.json`
(GeoNames, лежат в репозитории) — второй источник точек после Викиданных.
Страницы и набор Grunewald кэшируются в `data/raw/occupation_cities/`,
ответы Викиданных — в `data/cache/occupation_cities/`.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.occupation import (
    ARCHIVE, BASE_URL, CHRONICLE_PAGE, CITATION, GRUNEWALD_FILE_URL, GRUNEWALD_SIZE, GRUNEWALD_URL,
    OCCUPATION_CITIES, PAGES, OccupationError, check_chronicle, check_grunewald,
    check_headings, chronicle, cross_check, fetch, geonames_index, grunewald_rows,
    heading_counts, lookup_names, parse_entry, parse_pages, period_records, periods,
    place_city, see_reference, wikidata_candidates,
)
from histctx.sources.wikidata import SparqlClient, SparqlError

CACHE = ROOT / "data" / "raw" / "occupation_cities"
WD_CACHE = ROOT / "data" / "cache" / "occupation_cities"
SETTLEMENTS = ROOT / "data" / "out" / "geojson" / "settlements.geojson"
VARIANTS = ROOT / "data" / "out" / "name_variants.json"
GRUNEWALD_FILE = "grunewald_barbarossa.xlsx"


def download_pages(cache: Path, *, refresh: bool) -> dict[str, bytes]:
    """Шесть страниц СССР и хроника — из кэша или с сайта."""
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for page in (*PAGES, CHRONICLE_PAGE):
        path = cache / page
        if refresh or not path.exists():
            path.write_bytes(fetch(BASE_URL + page))
        out[page] = path.read_bytes()
    return out


def download_grunewald(cache: Path, *, refresh: bool) -> Path:
    path = cache / GRUNEWALD_FILE
    if refresh or not path.exists():
        data = fetch(GRUNEWALD_FILE_URL)
        if len(data) != GRUNEWALD_SIZE or not data.startswith(b"PK\x03\x04"):
            raise OccupationError(f"набор Grunewald: пришло {len(data)} байт, ожидалось "
                                  f"{GRUNEWALD_SIZE} (книга xlsx) — набор переиздан?")
        path.write_bytes(data)
    return path


def check_index() -> list[str]:
    """Оглавление: ссылки на шесть страниц СССР и архив на месте."""
    html = fetch(BASE_URL).decode("cp1251", errors="replace")
    links = set(re.findall(r'href="([^"]+)"', html))
    problems = [f"в оглавлении нет ссылки на {p}" for p in (PAGES[0], ARCHIVE)
                if p not in links]
    first = fetch(BASE_URL + PAGES[0]).decode("cp1251", errors="replace")
    sub = set(re.findall(r'href="(1-ssr-\d\.html)"', first))
    missing = set(PAGES[1:]) - sub
    if missing:
        problems.append(f"на {PAGES[0]} нет ссылок на {sorted(missing)}")
    return problems


def load_geonames() -> dict:
    for path in (SETTLEMENTS, VARIANTS):
        if not path.exists():
            raise OccupationError(f"нет {path.relative_to(ROOT)} — GeoNames нужен как второй "
                                  "источник точек (scripts/harvest_geonames.py)")
    features = json.loads(SETTLEMENTS.read_text(encoding="utf-8"))["features"]
    variants = json.loads(VARIANTS.read_text(encoding="utf-8")).get("items") or {}
    return geonames_index(features, variants)


def collect(cache: Path, *, refresh: bool) -> dict:
    """Всё собранное разом — одно и то же для проверки и для сборки."""
    pages = download_pages(cache, refresh=refresh)
    counts = heading_counts({p: pages[p] for p in PAGES})
    problems = check_headings(counts)
    if problems:
        raise OccupationError("число статей разошлось с записанным:\n  " + "\n  ".join(problems))
    entries = parse_pages({p: pages[p] for p in PAGES})
    refs = [e for e in entries if see_reference(e)]
    parsed = [parse_entry(e) for e in entries if not see_reference(e)]

    gn = load_geonames()
    client = SparqlClient(cache_dir=WD_CACHE)
    wd = wikidata_candidates(client, lookup_names(p.city for p in parsed))
    records, placements = [], []
    for p in parsed:
        place = place_city(p, wd, gn)
        cross_check(place, gn, p.city)
        placements.append((p, place))
        records.extend(period_records(p, place))
    return {"counts": counts, "entries": entries, "refs": refs, "parsed": parsed,
            "records": records, "placements": placements,
            "chronicle": check_chronicle(parsed, chronicle(pages[CHRONICLE_PAGE]))}


def report(got: dict, grunewald: dict | None) -> None:
    parsed, records = got["parsed"], got["records"]
    print(f"Статей: {len(got['entries'])} — с датами {len(parsed)}, отсылок «см.» "
          f"{len(got['refs'])}")
    for page, n in got["counts"].items():
        print(f"  {page}: {n}")
    kinds = collections.Counter(e.kind for p in parsed for e in p.events)
    print("События: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    per = collections.Counter(len(periods(p)[0]) for p in parsed)
    print("Периодов в статье: " + ", ".join(f"{k} — у {v}" for k, v in sorted(per.items())))
    unparsed = [(p.city.label, u) for p in parsed for u in p.unparsed]
    problems = [(p.city.label, x) for p in parsed for x in periods(p)[1]]
    print(f"  дат, которые не прочитались: {len(unparsed)}; непарных событий: {len(problems)}")
    for label, x in unparsed + problems:
        print(f"    {label}: {x}")

    print(f"\nЗаписей: {len(records)}")
    for cat, n in collections.Counter(r.category for r in records).most_common():
        print(f"  {n:>5}  {cat}")
    multi = [p for p in parsed if len([x for x in periods(p)[0] if x.of > 1]) > 1]
    print(f"  городов с несколькими периодами оккупации: {len(multi)}")

    ch = got["chronicle"]
    print(f"\nХроника освобождения (приложение 2): {ch['chronicle']} упоминаний, "
          f"с городом раздела СССР сведено {ch['found']}, дата совпала у {ch['agree']}")
    for line in ch["differ"]:
        print(f"    не совпало: {line}")

    placements = got["placements"]
    placed = [pl for _, pl in placements if pl.candidate]
    print(f"\nТочка города: {len(placed)} из {len(placements)} статей "
          f"({100 * len(placed) / len(placements):.1f}%)")
    src = collections.Counter(pl.candidate.source for pl in placed)
    print("  " + ", ".join(f"{k}: {v}" for k, v in src.items()))
    print(f"  по другому названию Викиданных: "
          f"{sum(1 for pl in placed if not pl.candidate.main)}; часть другого города "
          f"(place_level): {sum(1 for pl in placed if pl.part_of)}; выбрано вручную: "
          f"{sum(1 for pl in placed if 'вручную' in pl.how)}")
    rivals = [(p, pl) for p, pl in placements if pl.rivals]
    print(f"  с городом-тёзкой в полосе (выбран больший или по области): {len(rivals)}")
    near = [pl.check_km for _, pl in placements if pl.check_km is not None]
    print(f"  сверка с GeoNames: тёзка в пределах 5 км у {sum(1 for d in near if d <= 5)} "
          f"из {len(near)}")
    for p, pl in placements:
        if not pl.candidate:
            print(f"    без точки: {p.city.label} — {pl.how}")

    if grunewald:
        print(f"\nНабор Grunewald ({GRUNEWALD_URL}, CC0): строк {grunewald['rows']}, "
              f"сведено с городами справочника {grunewald['matched']}, "
              f"не противоречат {grunewald['agree']}, противоречат "
              f"{len(grunewald['disagree'])}, без утверждения {grunewald['no_claim']}")
        for line in grunewald["disagree"]:
            print(f"    {line}")
        print(f"  не сведено ({len(grunewald['unmatched'])}): "
              + ", ".join(sorted(set(grunewald["unmatched"]))))

    print("\n  примеры:")
    for rec in records[:2] + [r for r in records if r.category != records[0].category][:3]:
        print(f"    {rec.title}\n      {rec.summary}")


def check(cache: Path) -> int:
    print(CITATION)
    print(f"Оглавление: {BASE_URL}")
    problems = check_index()
    if problems:
        print("Оглавление расходится с ожидаемым — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"  ссылки на {', '.join(PAGES)} и архив {ARCHIVE} на месте")
    got = collect(cache, refresh=True)
    grunewald = check_grunewald(got["parsed"],
                                grunewald_rows(download_grunewald(cache, refresh=True)))
    report(got, grunewald)
    print("\nСтраницы на месте, число статей сходится, разбор работает — можно запускать "
          "--build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    got = collect(cache, refresh=False)
    records = got["records"]
    if not records:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = OCCUPATION_CITIES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(records, geo, layer_title=OCCUPATION_CITIES.title)
    # Записи без точки — файлом `<слой>.json`: без него они жили бы только
    # в `jsonl/`, который в репозиторий не идёт.
    off_map = [r for r in records if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{OCCUPATION_CITIES.title}: без точки")
    else:
        json_path.unlink(missing_ok=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(records, jsonl)
    print(f"Собрано {len(records)} записей по {len(got['parsed'])} статьям: на карте {n}, "
          f"без точки {len(off_map)}.")
    for path in (geo, json_path if off_map else None, jsonl):
        if path:
            print(f"  файл: {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} КБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="живой запрос к сайту, сверка числа статей, разбор и сверки")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанные страницы и набор Grunewald")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except (OccupationError, SparqlError) as exc:
        print(f"Сбор остановлен: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
