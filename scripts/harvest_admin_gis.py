#!/usr/bin/env python3
"""Сбор границ и итогов переписей 1897 и 1926 годов: heiDATA и RISTAT.

    python3 scripts/harvest_admin_gis.py --check    # что в наборах, без записи файлов
    python3 scripts/harvest_admin_gis.py --build    # полигоны и записи в data/out

Наборы два, и они дополняют друг друга, а не дублируют:

* **heiDATA, «Transcultural Empire»** (CC BY 4.0) — 99 губерний 1897 года и
  67 союзных единиц 1926-го **с итогами переписи**: язык, вера, сословие,
  народность. Уездов в нём нет;
* **RISTAT, Russian Empire Historical GIS Maps** (CC0) — 824 уезда и
  103 губернии 1897 года **без чисел**, зато до уезда.

Права выяснены по карточкам наборов: CC BY 4.0 требует указания авторства,
CC0 не требует ничего, но авторы просят ссылаться. Ссылка, идентификатор и
цитата проставляются в каждый выходной файл и в каждую запись.

На выходе:

* `boundaries/boundaries_1897.geojson`, `boundaries/boundaries_1926.geojson` —
  полигоны heiDATA с полной таблицей переписи в свойствах;
* `boundaries/provinces_1897.geojson`, `boundaries/districts_1897.geojson` —
  губернии и уезды RISTAT. Всё это подложка карты и к схеме контекста не
  приводится (`docs/HARVEST.md`, раздел «Границы»), поэтому лежит отдельным
  каталогом, а не рядом со слоями в `geojson/`;
* `jsonl/admin_1897_gis.jsonl` — записи схемы с охватом «губерния»: итоги
  переписи для подбора контекста по названию губернии и году.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_feature_collection, write_jsonl
from histctx.sources.admin_gis import (
    ADMIN_GIS, CENSUSES, HeiDataError, boundaries_geojson, build_summary,
    census_records, load_census, unit_name,
)
from histctx.sources.ristat import (
    FILES, RISTAT_BOUNDARIES, RistatError, collection, load, named,
)

CACHE = ROOT / "data" / "cache" / "boundaries"


def check(cache_dir: Path) -> int:
    for year, census in CENSUSES.items():
        feats = load_census(census, cache_dir=cache_dir)
        print(f"Перепись {year}: единиц {len(feats)}")
        kinds = {}
        for feature in feats:
            kind = (feature.get("geometry") or {}).get("type")
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"  геометрия: {kinds}")
        names = [unit_name(f.get('properties') or {}, census) for f in feats]
        missing = sum(1 for n in names if not n)
        print(f"  без названия: {missing}")
        print(f"  столбцов в таблице: {len(feats[0].get('properties') or {})}")
        for feature in feats[:2]:
            props = feature.get("properties") or {}
            print(f"  — {unit_name(props, census)}")
            print(f"    {build_summary(props, census)}")
        records = census_records(feats, census)
        usable = sum(1 for r in records if r.usable)
        print(f"  записей схемы: {len(records)}, годных для подбора: {usable}\n")

    for boundaries in FILES:
        feats = load(boundaries, cache_dir)
        print(f"RISTAT, {boundaries.title} 1897: полигонов {len(feats)}, "
              f"подписано по-русски {named(feats, boundaries)}")
        sample = (feats[0].get("properties") or {})
        print(f"  поля: {sorted(sample)}")
        print(f"  пример: {sample.get(boundaries.name_field)}\n")

    print("Наборы читаются, разбор работает — можно запускать --build.")
    return 0


def build(out_dir: Path, cache_dir: Path) -> int:
    records = []
    for year, census in CENSUSES.items():
        feats = load_census(census, cache_dir=cache_dir)
        path = out_dir / "boundaries" / f"boundaries_{year}.geojson"
        n = write_feature_collection(boundaries_geojson(feats, census), path)
        print(f"Перепись {year}: {n} полигонов → {path.relative_to(ROOT)}")
        records.extend(census_records(feats, census))

    for boundaries in FILES:
        feats = load(boundaries, cache_dir)
        path = out_dir / "boundaries" / f"{boundaries.key}.geojson"
        n = write_feature_collection(collection(feats, boundaries), path)
        print(f"RISTAT, {boundaries.title}: {n} полигонов → {path.relative_to(ROOT)}")

    if not records:
        print("Записи не собраны.", file=sys.stderr)
        return 1
    write_jsonl(records, out_dir / "jsonl" / f"{ADMIN_GIS.slug}.jsonl")
    print(f"Записей схемы: {len(records)} (охват «губерния», без точки).")
    print(f"«{RISTAT_BOUNDARIES.title}» записей схемы не дают: это подложка карты.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="показать, что в наборе")
    ap.add_argument("--build", action="store_true", help="записать полигоны и записи")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанные файлы набора")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")

    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.out, args.cache)
    except HeiDataError as exc:
        print(f"heiDATA: {exc}", file=sys.stderr)
        return 1
    except RistatError as exc:
        print(f"RISTAT: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
