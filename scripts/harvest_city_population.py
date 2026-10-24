#!/usr/bin/env python3
"""Сбор слоя населения городов 1800–1959 годов: пакет Буггле и Нафцигера (Harvard Dataverse).

    python3 scripts/harvest_city_population.py --check    # перечень по API, сверка, разбор
    python3 scripts/harvest_city_population.py --build    # точки в data/out/geojson

Первый запуск — проверочный: `--check` (он же `--probe`) сверяет перечень
файлов, размер архива и лицензию с записанным в `sources/city_population.py`,
скачивает архив (26,6 МБ) в `data/raw/city_population/`, читает из него
панель городов, проверяет восстановление населения из логарифма по второй
таблице пакета и печатает, как сошлись названия с GeoNames и уезды с RISTAT.

Права: CC0 1.0 (карточка набора); названия — GeoNames (CC BY 4.0).

Нужны `data/out/geojson/settlements.geojson` (`harvest_geonames.py --build`) и
`data/out/boundaries/districts_1897.geojson` (`harvest_admin_gis.py --build`).
На выходе `geojson/city_population.geojson` (в репозиторий) и `jsonl/`.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl
from histctx.net import fetch_bytes
from histctx.sources.city_population import (
    ARCHIVE, CITY_POPULATION, CROSS_MEMBER, DATASET_URL, DOI, FILES, LICENSE_NAME, PANEL_MEMBER,
    ALT_NAMES_URL, CityPopulationError, candidate_ids, check_against_cross_section,
    check_columns, countries_by_name, load_alt_names, name_stats, read_member, records,
    settlements_index,
)
from histctx.sources.dataverse import DataverseError, cached, check_manifest, fetch_manifest
from histctx.sources.uezd_names import RistatDistricts

CACHE = ROOT / "data" / "raw" / "city_population"
DISTRICTS_1897 = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"
SETTLEMENTS = ROOT / "data" / "out" / "geojson" / "settlements.geojson"


def collect(cache_dir: Path, districts_path: Path, settlements_path: Path) -> dict:
    for path, how in ((districts_path, "harvest_admin_gis.py --build"),
                      (settlements_path, "harvest_geonames.py --build")):
        if not path.exists():
            raise CityPopulationError(f"нет {path}. Сначала `python3 scripts/{how}`")
    archive = cached(ARCHIVE, cache_dir, error=CityPopulationError)
    rows = read_member(archive, PANEL_MEMBER)
    check_columns(rows[0].keys() if rows else [])
    districts = RistatDistricts.load(districts_path)
    settlements = settlements_index(settlements_path)
    ids, countries = candidate_ids(rows, settlements)
    codes = countries_by_name()
    paths = []
    for country in sorted(countries):
        code = codes.get(country)
        if code is None:
            raise CityPopulationError(f"страна {country!r} не знает кода GeoNames")
        paths.append(alt_names(code, cache_dir))
    names_ru = load_alt_names(paths, ids)
    recs = records(rows, districts, settlements, names_ru)
    return {"archive": archive, "rows": rows, "records": recs, "countries": countries,
            "names_ru": names_ru, "candidates": ids}


def alt_names(code: str, cache_dir: Path) -> Path:
    """`alternatenames/XX.zip` GeoNames — один раз, дальше из кэша."""
    path = cache_dir / f"alternatenames_{code}.zip"
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch_bytes(ALT_NAMES_URL.format(code=code), error=CityPopulationError))
    return path


def check(cache_dir: Path, districts_path: Path, settlements_path: Path) -> int:
    print(f"Карточка набора: {DATASET_URL}")
    manifest = fetch_manifest(DOI, error=CityPopulationError)
    print(f"Версия {manifest['version']}, лицензия {manifest['license']}; файлов "
          f"{len(manifest['files'])}, в перечне сборщика {len(FILES)}")
    problems = check_manifest(manifest, FILES, license_name=LICENSE_NAME)
    if problems:
        print("\nПеречень в коде расходится с набором — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    got = collect(cache_dir, districts_path, settlements_path)
    print(f"  {ARCHIVE.file_id}  {ARCHIVE.name}  {ARCHIVE.size} байт  сходится")
    rows = got["rows"]
    print(f"\ncity_pop_panel.dta: строк {len(rows)}, колонок {len(rows[0])}; городов "
          f"{len({r['city_id'] for r in rows})}")
    by_year = collections.Counter(r["year"] for r in rows if r.get("log_pop") is not None)
    print("  с населением по годам: " + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())))
    cross = read_member(got["archive"], CROSS_MEMBER)
    found, equal = check_against_cross_section(rows, cross)
    print(f"  exp(log_pop) против целых чисел city_pop_cross_section.dta (1897): нашлось по "
          f"координате {found} из {len(cross)}, совпало до человека {equal}")
    recs = got["records"]
    print(f"\nЗаписей «город-год» до 1960 года: {len(recs)}")
    for category, n in sorted(collections.Counter(r.category for r in recs).items()):
        print(f"  {n:>5}  {category}")
    print(f"\nМест GeoNames в 10 км от городов: {len(got['candidates'])}, страны: "
          f"{', '.join(sorted(got['countries']))}; с русским именем в выгрузке "
          f"alternatenames: {sum(1 for v in got['names_ru'].values() if v.get('name'))}")
    stats = name_stats(recs)
    print("Названия по GeoNames (городов): " + ", ".join(f"{k} {v}" for k, v in
                                                        sorted(stats.items())))
    how = collections.Counter()
    seen = set()
    for rec in recs:
        cid = rec.extra["city_id"]
        if cid in seen:
            continue
        seen.add(cid)
        how[rec.extra.get("ristat_match") or "нет пары"] += 1
    print("Уезд города в RISTAT 1897: " + ", ".join(f"{k} {v}" for k, v in how.most_common()))
    print("\n  примеры:")
    shown = set()
    for rec in recs:
        kind = rec.extra["name_match"]["how"]
        if kind in shown:
            continue
        shown.add(kind)
        print(f"    [{kind}] {rec.title}\n      {rec.summary}")
    print("\nНабор на месте, перечень сходится, разбор работает — можно запускать --build.")
    return 0


def build(cache_dir: Path, out_dir: Path, districts_path: Path, settlements_path: Path) -> int:
    recs = collect(cache_dir, districts_path, settlements_path)["records"]
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    path = out_dir / "geojson" / f"{CITY_POPULATION.slug}.geojson"
    n = write_geojson(recs, path, layer_title=CITY_POPULATION.title, hoist_shared=True)
    write_jsonl(recs, out_dir / "jsonl" / f"{CITY_POPULATION.slug}.jsonl")
    uncertain = sum(1 for r in recs if r.confidence == "name_uncertain")
    print(f"{CITY_POPULATION.slug}: {n} точек (название ненадёжно: {uncertain}) → "
          f"{path.relative_to(ROOT)} ({path.stat().st_size / 1_048_576:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить набор с перечнем, скачать, показать разбор")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--districts", type=Path, default=DISTRICTS_1897)
    ap.add_argument("--settlements", type=Path, default=SETTLEMENTS)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache, args.districts, args.settlements)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.districts, args.settlements)
    except (CityPopulationError, DataverseError) as exc:
        print(f"Набор Dataverse: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
