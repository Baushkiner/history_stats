#!/usr/bin/env python3
"""Сбор слоя населённых мест из GeoNames.

    pip install geonamescache
    python3 scripts/harvest_geonames.py --probe
    python3 scripts/harvest_geonames.py --build

Сети не требует: набор приходит вместе с пакетом. Это единственный слой,
который удалось собрать в закрытом окружении, — реестр пакетов открыт там,
где закрыты сайты источников.

Данные GeoNames распространяются под CC BY 4.0: ссылка на источник
обязательна и проставляется в каждой записи.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.io_formats import write_geojson, write_jsonl  # noqa: E402
from histctx.sources.geonames import (  # noqa: E402
    COUNTRIES, SETTLEMENTS, GeoNamesError, load_cities, pick_russian_name, select, to_records,
)


def probe(dataset: str, min_population: int) -> int:
    cities = load_cities(dataset)
    print(f"Набор {dataset}: {len(cities)} записей всего")
    selected = list(select(cities, min_population=min_population))
    print(f"В странах бывшей РИ/СССР и в рамке карты: {len(selected)}")

    by_country = Counter(c["countrycode"] for c in selected)
    for code, count in by_country.most_common():
        print(f"  {COUNTRIES.get(code, code):12} {count}")

    with_russian = sum(1 for c in selected if pick_russian_name(c))
    print(f"\nС кириллическим названием: {with_russian} "
          f"({100 * with_russian / max(len(selected), 1):.0f}%)")
    print("Года основания в наборе нет ни у одной записи — слой идёт без датировки.")

    for rec in to_records(selected[:5]):
        print(f"  {rec.lat:.4f},{rec.lon:.4f}  {rec.title}  ({rec.category})")
    return 0


def build(dataset: str, min_population: int, out_dir: Path) -> int:
    cities = load_cities(dataset)
    selected = list(select(cities, min_population=min_population))
    records = to_records(selected)
    if not records:
        print("Ничего не отобрано.", file=sys.stderr)
        return 1

    n = write_geojson(records, out_dir / "geojson" / f"{SETTLEMENTS.slug}.geojson",
                      layer_title=SETTLEMENTS.title, hoist_shared=True)
    write_jsonl(records, out_dir / "jsonl" / f"{SETTLEMENTS.slug}.jsonl")
    sizes = Counter(r.category for r in records)
    print(f"Собрано {len(records)} населённых мест, на карту пойдут {n}.")
    for size, count in sizes.most_common():
        print(f"  {size}: {count}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="что в наборе, без записи файлов")
    ap.add_argument("--build", action="store_true", help="собрать слой")
    ap.add_argument("--dataset", default="cities500",
                    choices=("cities500", "cities1000", "cities5000", "cities15000"),
                    help="порог населения в самом наборе GeoNames")
    ap.add_argument("--min-population", type=int, default=0,
                    help="дополнительный порог при отборе")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.probe and not args.build:
        ap.error("укажите --probe или --build")
    try:
        if args.probe:
            return probe(args.dataset, args.min_population)
        return build(args.dataset, args.min_population, args.out)
    except GeoNamesError as exc:
        print(f"GeoNames: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
