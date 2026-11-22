#!/usr/bin/env python3
"""Сбор слоя погромов 1903–1906 годов: таблица American Jewish Year Book, т. 8.

    python3 scripts/harvest_pogroms_1903.py --check    # скачать, разобрать, свести, без записи
    python3 scripts/harvest_pogroms_1903.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) заново скачивает набранную таблицу (Museum of Family History)
и текстовый слой скана книги (archive.org), сверяет таблицу с напечатанным —
254 строки подряд, годы 1903–1906, все даты разбираются, — разбирает
дополнительный список ноября 1905 года, сводит города с точками Викиданных и
GeoNames внутри губерний 1897 года и печатает, что не свелось. Расхождение с
напечатанным — остановка, а не подгонка.

Права. Книга 1906 года — общественное достояние в США; набранная таблица —
«Copyright © 2009 Museum of Family History»: из неё берутся только данные
книги, ссылка в каждой записи ведёт на скан.

На выходе:

* `geojson/pogroms_1903.geojson` — записи с точкой города;
* `pogroms_1903.json` — записи, которым точки не нашлось: в репозиторий
  идут оба файла, `jsonl/` в `.gitignore`;
* `jsonl/pogroms_1903.jsonl` — слой целиком.

Нужны `data/out/boundaries/provinces_1897.geojson` (губерния — рамка поиска
города и поле `region`), `data/out/geojson/settlements.geojson` и
`data/out/name_variants.json` (GeoNames, лежат в репозитории). Таблица и
текст скана кэшируются в `data/raw/pogroms_1903/`, ответы Викиданных — в
`data/cache/pogroms_1903/`.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.ghcn import Provinces
from histctx.sources.pogroms_1903 import (
    GUBERNIAS, POGROMS_1903, SCAN_ID, TABLE_URL, TEXT_URL, Locator, PogromsError,
    build_records, cached, check_table, geonames_places, lookup_names, parse_supplement,
    parse_table, skeleton_index, wikidata_places, wikidata_query,
)
from histctx.sources.wikidata import SparqlClient, SparqlError

CACHE = ROOT / "data" / "raw" / "pogroms_1903"
WD_CACHE = ROOT / "data" / "cache" / "pogroms_1903"
SETTLEMENTS = ROOT / "data" / "out" / "geojson" / "settlements.geojson"
VARIANTS = ROOT / "data" / "out" / "name_variants.json"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
TABLE_FILE = "ajc-yb-v08-pogroms.htm"
TEXT_FILE = f"{SCAN_ID}_djvu.txt"


def load_sources(cache: Path, *, refresh: bool) -> tuple[list, list]:
    rows = parse_table(cached(TABLE_URL, cache / TABLE_FILE, refresh=refresh))
    text = cached(TEXT_URL, cache / TEXT_FILE, refresh=refresh).decode("utf-8", "replace")
    return rows, parse_supplement(text)


def make_locator() -> Locator:
    provinces = Provinces.load(BOUNDARIES / "provinces_1897.geojson")
    client = SparqlClient(cache_dir=WD_CACHE)
    names = lookup_names()
    rows = []
    for i in range(0, len(names), 80):
        rows.extend(client.query(wikidata_query(names[i:i + 80])))
    wd = wikidata_places(rows)
    features = json.loads(SETTLEMENTS.read_text(encoding="utf-8"))["features"]
    variants = json.loads(VARIANTS.read_text(encoding="utf-8")).get("items", {})
    gn = skeleton_index(geonames_places(features, variants))
    return Locator(provinces, wd, gn)


def collect(cache: Path, *, refresh: bool) -> tuple[list, list, list, dict]:
    rows, supplement = load_sources(cache, refresh=refresh)
    problems = check_table(rows)
    if problems:
        raise PogromsError("таблица не сошлась с напечатанным: " + "; ".join(problems))
    unknown = sorted({r.gubernia for r in rows if r.gubernia and r.gubernia not in GUBERNIAS})
    if unknown:
        raise PogromsError(f"губернии без соответствия 1897 году: {unknown}")
    recs = build_records(rows, supplement, make_locator())
    frame = Frame.load(BOUNDARIES)
    with_point = [r for r in recs if r.has_point]
    # Губерния в записи — та, что названа таблицей: она и есть свидетельство
    # источника. Полигон 1897 года на реках-границах груб (Бендеры у него
    # в Херсонской губернии), и его губерния, если она другая, идёт в extra.
    documented = {r.uid: r.region for r in with_point}
    counts = frame.mark(with_point)
    for rec in with_point:
        named = documented.get(rec.uid)
        if named and rec.region != named:
            rec.extra["province_by_point"] = rec.region or "вне губерний 1897 года"
            rec.region = named
    return rows, supplement, recs, counts


def report(rows: list, supplement: list, recs: list, counts) -> None:
    table = [r for r in recs if not r.source_id.startswith("ajyb8:suppl")]
    extra = [r for r in recs if r.source_id.startswith("ajyb8:suppl")]
    print(f"Таблица: {len(rows)} строк; по годам "
          + ", ".join(f"{y} — {n}" for y, n in sorted(collections.Counter(
              r.year for r in rows).items())))
    print(f"  дата до дня у {sum(1 for r in table if r.date_precision == 'day')}, "
          f"до месяца у {sum(1 for r in table if r.date_precision == 'month')}, "
          f"только год у {sum(1 for r in table if r.date_precision == 'year')}")
    print(f"  с точкой {sum(1 for r in table if r.has_point)}, без точки "
          f"{sum(1 for r in table if not r.has_point)}; губерния не названа у "
          f"{sum(1 for r in rows if not r.gubernia)}")
    how = collections.Counter((r.extra.get("place_match") or "").split(",")[0] for r in table)
    print("  как найдены:", ", ".join(f"{k} — {n}" for k, n in how.most_common()))
    killed = sum(r.extra.get("killed") or 0 for r in table)
    print(f"  убитых по строкам ущерба {killed}, строк с числом убитых "
          f"{sum(1 for r in table if r.extra.get('killed') is not None)}")
    print(f"Дополнительный список ноября 1905 года: {len(supplement)} названий, "
          f"записей {len(extra)}, с точкой {sum(1 for r in extra if r.has_point)}")
    print("Рамка:", ", ".join(f"{k} — {v}" for k, v in counts.items()))
    missing = [f"№ {r.extra['table_number']} {r.extra['town_1906']} "
               f"({r.extra.get('gubernia_1906') or '—'})" for r in table if not r.has_point]
    print(f"\nБез точки ({len(missing)}): " + "; ".join(missing))
    print("\nПримеры:")
    for rec in table[:3] + [r for r in table if r.extra.get("table_number") in (242, 250)]:
        print(f"  {rec.title}: {rec.summary} — {rec.extra.get('place_match')}, "
              f"{rec.lat}, {rec.lon}, {rec.region}")


def check(cache: Path) -> int:
    rows, supplement, recs, counts = collect(cache, refresh=True)
    report(rows, supplement, recs, counts)
    print("\nТаблица разбирается, города сводятся — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    rows, supplement, recs, counts = collect(cache, refresh=False)
    slug = POGROMS_1903.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=POGROMS_1903.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{POGROMS_1903.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{POGROMS_1903.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} КБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="скачать, сверить, разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except (PogromsError, SparqlError) as exc:
        print(f"Погромы 1903–1906: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
