#!/usr/bin/env python3
"""Сбор слоя заселённости и распашки уездов по десятилетиям (HYDE 3.2.1, DANS).

    python3 scripts/harvest_hyde.py --check    # карточка набора, одна сетка, разбор
    python3 scripts/harvest_hyde.py --build    # все 81 сетка и слой в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) сверяет карточку
набора на станции данных DANS (лицензия, имя и размер архива), читает
оглавление архива по Range, берёт сетки одного года (1900), раскладывает их
по уездам 1897 года и показывает разбор. `--build` добирает остальные годы:
81 сетка, около 660 МБ сжатых, 4–6 минут; окна сеток кладутся в
`data/raw/hyde/` и второй раз не скачиваются.

Нужен пакет `inflate64` (архив сжат Deflate64) — только этой команде.
Права: CC0 1.0 (карточка набора); readme набора называет CC BY 3.0.

На выходе `population_landuse_hyde.json` (в репозиторий) и
`jsonl/population_landuse_hyde.jsonl`. Нужен
`data/out/boundaries/districts_1897.geojson` (`harvest_admin_gis.py --build`).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_jsonl, write_records_json
from histctx.sources.hyde import (
    ARCHIVE_NAME, DOI_URL, POPULATION_HYDE, VARIABLES, YEARS, Archive, HydeError,
    build_records, check_manifest, coverage, fetch_manifest, load_grid, rasterize, units_from,
)

CACHE = ROOT / "data" / "raw" / "hyde"
DISTRICTS_1897 = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"
WATCH = ("Кирилловский уезд", "Московский уезд", "Барнаульский округ", "Полтавский уезд")


def load_units(path: Path):
    if not path.exists():
        raise HydeError(f"нет справочника уездов 1897 года: {path}. Сначала "
                        "`python3 scripts/harvest_admin_gis.py --build`")
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    return units_from(features), rasterize([f.get("geometry") or {} for f in features])


def collect(cache: Path, districts: Path, years, *, network: bool):
    units, index = load_units(districts)
    missing = [(v, y) for y in years for v in VARIABLES
               if not (cache / f"{v}_{y}.npy").exists()]
    archive = None
    if missing:
        if not network:
            raise HydeError(f"в кэше нет {len(missing)} сеток — запустите без --offline")
        archive = Archive()
    grids = {}
    for year in years:
        grids[year] = {var: load_grid(cache, var, year, archive) for var in VARIABLES}
        if archive is not None:
            print(f"  {year}: сетки на месте (запросов к архиву: {archive.file.requests})",
                  flush=True)
    return units, index, build_records(units, index, grids)


def report(units, index, recs) -> None:
    for what, n in coverage(units, index).items():
        print(f"  {what}: {n}")
    print(f"Записей: {len(recs)}; годы {min(r.year_from for r in recs)}–"
          f"{max(r.year_to for r in recs)}")
    for year in sorted({r.year_from for r in recs}):
        total = sum(r.extra["population"] for r in recs if r.year_from == year)
        crop = sum(r.extra["cropland_share"] * r.extra["area_km2"]
                   for r in recs if r.year_from == year)
        print(f"  {year}: население уездов {total / 1e6:.1f} млн, пашня {crop / 1e3:.0f} тыс. км²")
    print("  категории:")
    for what, n in collections.Counter(r.category for r in recs).most_common():
        print(f"    {n:>5}  {what}")
    print("  образцы:")
    for name in WATCH:
        for rec in [r for r in recs if r.district == name][:40:13]:
            print(f"    {rec.title}\n      {rec.summary}")


def check(cache: Path, districts: Path) -> int:
    print(f"Карточка набора: {DOI_URL}")
    problems = check_manifest(fetch_manifest())
    if problems:
        print("Набор расходится с записанным в коде — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"Лицензия, имя и размер архива {ARCHIVE_NAME} сходятся.")
    units, index, recs = collect(cache, districts, (1900,), network=True)
    if not recs:
        print("Ни одной записи: проверьте разбор.", file=sys.stderr)
        return 1
    report(units, index, recs)
    print("\nАрхив читается, сетка та, разбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path, districts: Path, *, network: bool) -> int:
    units, index, recs = collect(cache, districts, YEARS, network=network)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    report(units, index, recs)
    slug = POPULATION_HYDE.slug
    path = out_dir / f"{slug}.json"
    write_records_json(recs, path, title=POPULATION_HYDE.title, hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    for p in (path, jsonl):
        print(f"  → {p.relative_to(ROOT)} ({p.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить карточку набора, взять один год, показать разбор")
    ap.add_argument("--build", action="store_true", help="собрать все годы и записать слой")
    ap.add_argument("--offline", action="store_true", help="--build только из кэша, без сети")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--districts", type=Path, default=DISTRICTS_1897)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache, args.districts)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.districts, network=not args.offline)
    except HydeError as exc:
        print(f"HYDE: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
