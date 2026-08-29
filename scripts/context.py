#!/usr/bin/env python3
"""Показывает исторический контекст вокруг факта.

    python3 scripts/context.py --lat 59.86 --lon 38.37 --year 1899
    python3 scripts/context.py --lat 54.78 --lon 32.05 --year 1812 --radius 30
    python3 scripts/context.py --lat 56.33 --lon 44.0 --year 1861 --json

Читает собранные слои из data/out. Полезно и как проверка данных: сразу
видно, что реально показывается пользователю рядом с конкретным фактом.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.enrich import ContextEngine, Fact
from histctx.io_formats import read_context
from histctx.schema import ContextRecord


def load_records(out_dir: Path) -> list[ContextRecord]:
    """Читает выгрузку из data/out.

    Разбор форматов — `histctx.io_formats`: тем же чтением пользуется отчёт о
    качестве, и расходиться им нельзя.
    """
    return read_context(out_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--year", type=int, help="год факта; без него подбор идёт только по месту")
    ap.add_argument("--region", help="губерния факта: «Самарская губерния». "
                                     "Без неё определяется по ближайшим записям")
    ap.add_argument("--no-territorial", action="store_true",
                    help="не показывать события без точки: ревизии, реформы, голод")
    ap.add_argument("--radius", type=float, default=50.0, help="радиус, км")
    ap.add_argument("--window", type=int, default=25, help="окно по годам")
    ap.add_argument("--layer", action="append", help="ограничить слоем (можно повторять)")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--per-layer", type=int, default=4, help="не более N записей на слой")
    ap.add_argument("--json", action="store_true", help="выдать JSON вместо таблицы")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    records = load_records(args.out)
    if not records:
        print(f"Нет собранных данных в {args.out}. Запустите scripts/build_core.py.",
              file=sys.stderr)
        return 1

    engine = ContextEngine(records)
    fact = Fact(lat=args.lat, lon=args.lon, year=args.year, region=args.region)
    matches = engine.find(
        fact,
        radius_km=args.radius, year_window=args.window,
        layers=args.layer, limit=args.limit, per_layer_cap=args.per_layer,
        include_territorial=not args.no_territorial,
    )
    region, region_source = engine.resolve_region(fact)

    if args.json:
        print(json.dumps({
            "fact": {"lat": args.lat, "lon": args.lon, "year": args.year,
                     "region": region, "region_source": region_source},
            "summary": engine.summarize(matches),
            "matches": [{
                "score": m.score, "distance_km": m.distance_km,
                "year_gap": m.year_gap, "reasons": list(m.reasons),
                "record": m.record.to_row(),
            } for m in matches],
        }, ensure_ascii=False, indent=2))
        return 0

    where = f"{args.lat}, {args.lon}"
    when = args.year if args.year is not None else "год не задан"
    print(f"\nКонтекст вокруг факта: {where}, {when}")
    print(f"Губерния: {region or 'не определена'} ({region_source})"
          + ("" if region else " — губернские события пропущены, задайте --region"))
    print(f"В индексе {len(engine)} записей, из них {len(engine.territorial)} без точки; "
          f"найдено {len(matches)} (радиус {args.radius:g} км, окно {args.window} лет)\n")

    if not matches:
        print("Ничего не найдено. Попробуйте увеличить --radius или --window.")
        return 0

    for m in matches:
        r = m.record
        years = f"{r.year_from}–{r.year_to}" if r.has_time else "без даты"
        print(f"  [{m.score:.2f}] {(r.layer_title or r.layer)[:28]:30s} "
              f"{years:>12s}  {(r.title or '')[:52]}")
        print(f"         {m.explain()}")
        if r.url:
            print(f"         {r.url}")
    print()
    for layer, cnt in engine.summarize(matches)["by_layer"].items():
        print(f"  {cnt:3d}  {layer}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
