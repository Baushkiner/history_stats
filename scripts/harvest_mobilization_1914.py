#!/usr/bin/env python3
"""Сбор слоя мобилизации 1914–1916 годов: пакет Дауэра и Маркевича (Harvard Dataverse).

    python3 scripts/harvest_mobilization_1914.py --check    # перечень по API, сверка, разбор
    python3 scripts/harvest_mobilization_1914.py --build    # записи в data/out

Первый запуск — проверочный: `--check` (он же `--probe`) сверяет перечень
файлов, размеры и лицензию с записанным в `sources/mobilization_1914.py`,
скачивает таблицу в `data/raw/mobilization_1914/`, проверяет колонки,
разбирает её и печатает, сколько уездов сошлось с уездами 1897 года RISTAT
и какие нет. Расхождение с перечнем — остановка.

Права: CC0 1.0 (карточка набора); ссылка на набор стоит в каждой записи.

На выходе `mobilization_1914.json` (в репозиторий) и `jsonl/` (в `.gitignore`):
запись на уезд, охват «уезд внутри губернии», без точки.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_jsonl, write_records_json
from histctx.sources.dataverse import DataverseError, cached, check_manifest, fetch_manifest
from histctx.sources.mobilization_1914 import (
    DATASET_URL, DOI, FILES, LICENSE_NAME, MOBILIZATION_1914, PANEL, SHARE_MAX,
    MobilizationError, load, records,
)
from histctx.sources.uezd_names import RistatDistricts

CACHE = ROOT / "data" / "raw" / "mobilization_1914"
DISTRICTS_1897 = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"


def collect(cache_dir: Path, districts_path: Path) -> tuple[list, list, RistatDistricts]:
    if not districts_path.exists():
        raise MobilizationError(f"нет справочника уездов 1897 года: {districts_path}. Сначала "
                                "`python3 scripts/harvest_admin_gis.py --build`")
    index = RistatDistricts.load(districts_path)
    rows = load(cached(PANEL, cache_dir, error=MobilizationError))
    return rows, records(rows, index), index


def check(cache_dir: Path, districts_path: Path) -> int:
    print(f"Карточка набора: {DATASET_URL}")
    manifest = fetch_manifest(DOI, error=MobilizationError)
    print(f"Версия {manifest['version']}, лицензия {manifest['license']}; файлов "
          f"{len(manifest['files'])}, в перечне сборщика {len(FILES)}")
    problems = check_manifest(manifest, FILES, license_name=LICENSE_NAME)
    if problems:
        print("\nПеречень в коде расходится с набором — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    rows, recs, index = collect(cache_dir, districts_path)
    print(f"  {PANEL.file_id}  {PANEL.cache_name}  {PANEL.download_size} байт  сходится")
    print(f"\n{PANEL.cache_name}: строк {len(rows)}, колонок {len(rows[0])}; уездов "
          f"{len({r.get('iddistrict') for r in rows})}, губерний "
          f"{len({r.get('province_latin') for r in rows})}")
    print(f"Записей: {len(recs)}")
    for category, n in collections.Counter(r.category for r in recs).most_common():
        print(f"  {n:>5}  {category}")
    print(f"  порог правдоподобия: доля призванных от 0 до {SHARE_MAX:.0%} сельского "
          "населения 1912 года")
    provinces = collections.Counter(r.region for r in recs)
    unknown = [r.extra.get("province_latin") for r in recs if not r.region]
    print(f"  губерний по-русски: {len(provinces)}; не переведено: {sorted(set(unknown))}")
    how = collections.Counter(r.extra.get("ristat_match") or "нет пары" for r in recs)
    print("Сверка с уездами 1897 года RISTAT: " + ", ".join(f"{k} {v}" for k, v in
                                                          how.most_common()))
    for rec in recs:
        if rec.extra.get("ristat_match") in ("fuzzy", "prefix"):
            print(f"    {rec.extra['ristat_match']:<6} {rec.extra['district_latin']!r:<34} → "
                  f"{rec.district}")
    for rec in recs:
        if rec.confidence == "district_unmatched":
            print(f"    без пары: {rec.place_text}")
    print("\n  примеры:")
    for rec in recs[:2] + [r for r in recs if r.region == "Тульская губерния"][:1]:
        print(f"    {rec.title}\n      {rec.summary}")
    print("\nНабор на месте, перечень сходится, разбор работает — можно запускать --build.")
    return 0


def build(cache_dir: Path, out_dir: Path, districts_path: Path) -> int:
    _, recs, _ = collect(cache_dir, districts_path)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    path = out_dir / f"{MOBILIZATION_1914.slug}.json"
    write_records_json(recs, path, title=MOBILIZATION_1914.title)
    write_jsonl(recs, out_dir / "jsonl" / f"{MOBILIZATION_1914.slug}.jsonl")
    unmatched = sum(1 for r in recs if r.confidence == "district_unmatched")
    print(f"{MOBILIZATION_1914.slug}: {len(recs)} записей (без пары в RISTAT: {unmatched}) → "
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
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache, args.districts)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.districts)
    except (MobilizationError, DataverseError) as exc:
        print(f"Набор Dataverse: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
