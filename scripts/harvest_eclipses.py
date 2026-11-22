#!/usr/bin/env python3
"""Сбор слоя солнечных затмений по губерниям (каталог NASA, эфемериды JPL DE440).

    python3 scripts/harvest_eclipses.py --check    # каталог, эфемериды, сверка, три затмения
    python3 scripts/harvest_eclipses.py --build    # все затмения 1601–1960 → data/out

Первый запуск — проверочный. `--check` (он же `--probe`) скачивает четыре
страницы каталога NASA и файл эфемерид (114 МБ) в `data/raw/eclipses/`,
разбирает каталог, сверяет расчёт с каталогом на трёх затмениях, путь которых
известен по газетам и отчётам экспедиций (1887, 1914, 1936), и печатает
губернии. `--build` считает все центральные затмения — около 590, 10–15 минут —
и сверяет гамму каждого с каталогом: расхождение больше допуска — затмение в
слой не идёт и названо в отчёте.

Нужен пакет `jplephem` — только этой команде. Права: каталог NASA —
с указанием «Eclipse Predictions by Fred Espenak (NASA's GSFC)», эфемериды
JPL — общественное достояние.

На выходе `solar_eclipses.json` (в репозиторий) и `jsonl/solar_eclipses.jsonl`.
Нужен `data/out/boundaries/provinces_1897.geojson`.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_jsonl, write_records_json
from histctx.sources.eclipses import (
    GAMMA_TOLERANCE, SOLAR_ECLIPSES, SPANS, YEARS, EclipseError, Ephemeris, cached_catalog,
    cached_ephemeris, load_provinces, parse_catalog, province_nodes, to_records, visibility,
)

CACHE = ROOT / "data" / "raw" / "eclipses"
PROVINCES_1897 = ROOT / "data" / "out" / "boundaries" / "provinces_1897.geojson"
# Затмения, путь которых известен независимо: 1887 — Клин (полёт Менделеева),
# Вильна, Пермь, а Москва осталась у самого края; 1914 — Рига, Минск, Киев,
# Феодосия; 1936 — Туапсе, Оренбург, Омск, Красноярск, Хабаровск.
KNOWN = {
    dt.date(1887, 8, 19): {"Тверская губерния", "Виленская губерния", "Пермская губерния",
                           "Московская губерния"},
    dt.date(1914, 8, 21): {"Лифляндская губерния", "Минская губерния", "Киевская губерния",
                           "Таврическая губерния"},
    dt.date(1936, 6, 19): {"Черноморская губерния", "Оренбургская губерния",
                           "Енисейская губерния", "Приморская область"},
}


def load_catalog(cache: Path) -> list:
    eclipses = []
    for span in SPANS:
        rows = parse_catalog(cached_catalog(span, cache))
        if len(rows) < 200:
            raise EclipseError(f"каталог {span}: разобрано {len(rows)} строк — страница "
                               "устроена иначе, чем записано в коде")
        eclipses += rows
    return [e for e in eclipses if YEARS[0] <= e.date.year <= YEARS[1]]


def prepare(cache: Path, provinces: Path):
    catalog = load_catalog(cache)
    ephemeris = Ephemeris(cached_ephemeris(cache))
    nodes = province_nodes(load_provinces(provinces))
    return catalog, ephemeris, nodes


def check(cache: Path, provinces: Path) -> int:
    catalog, ephemeris, nodes = prepare(cache, provinces)
    kinds = collections.Counter(e.kind for e in catalog)
    print(f"Каталог NASA, {YEARS[0]}–{YEARS[1]}: затмений {len(catalog)} — "
          + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(f"Узлов сетки в губерниях 1897 года: {len(nodes.lat)}, губерний {len(nodes.names)}")
    failed = 0
    for date, expected in KNOWN.items():
        eclipse = next(e for e in catalog if e.date == date)
        seen = visibility(ephemeris, eclipse, nodes)
        print(f"\n{date}: гамма по каталогу {eclipse.gamma}, по расчёту {seen.gamma:.4f}; "
              f"точка наибольшей фазы по каталогу {eclipse.lat}, {eclipse.lon}, по расчёту "
              f"{seen.greatest[0]:.1f}, {seen.greatest[1]:.1f}")
        for rec in to_records(eclipse, seen):
            print(f"  {rec.title}\n    {rec.summary[:700]}")
        missing = expected - set(seen.central)
        if missing or abs(seen.gamma - eclipse.gamma) > GAMMA_TOLERANCE:
            failed += 1
            print(f"  НЕ СХОДИТСЯ: в полосе нет {sorted(missing)}", file=sys.stderr)
    if failed:
        print("\nРасчёт расходится с известными затмениями — сбор остановлен.", file=sys.stderr)
        return 1
    print("\nКаталог разбирается, расчёт сходится с каталогом и с известными затмениями — "
          "можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path, provinces: Path) -> int:
    catalog, ephemeris, nodes = prepare(cache, provinces)
    central = [e for e in catalog if e.central]
    recs, rejected, worst = [], [], 0.0
    for n, eclipse in enumerate(central, 1):
        seen = visibility(ephemeris, eclipse, nodes)
        delta = abs(seen.gamma - eclipse.gamma)
        worst = max(worst, delta)
        if delta > GAMMA_TOLERANCE:
            rejected.append((eclipse, seen.gamma))
            continue
        recs += to_records(eclipse, seen)
        if n % 50 == 0:
            print(f"  {n} из {len(central)}: {eclipse.date}, записей {len(recs)}", flush=True)
    print(f"Центральных затмений в каталоге: {len(central)}; наибольшее расхождение гаммы "
          f"с каталогом: {worst:.4f} (допуск {GAMMA_TOLERANCE})")
    for eclipse, gamma in rejected:
        print(f"  не взято: {eclipse.date} — гамма по каталогу {eclipse.gamma}, по расчёту "
              f"{gamma:.4f}", file=sys.stderr)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    print(f"Записей: {len(recs)}")
    for what, count in collections.Counter(r.category for r in recs).most_common():
        print(f"  {count:>4}  {what}")
    by_century = collections.Counter((r.year_from - 1) // 100 + 1 for r in recs)
    print("  по векам: " + ", ".join(f"{k} — {v}" for k, v in sorted(by_century.items())))
    seen_provinces = collections.Counter(
        name for r in recs if not r.category.startswith("частное") for name in r.regions)
    print("  чаще всего в полосе: "
          + ", ".join(f"{k} — {v}" for k, v in seen_provinces.most_common(6)))
    slug = SOLAR_ECLIPSES.slug
    path = out_dir / f"{slug}.json"
    write_records_json(recs, path, title=SOLAR_ECLIPSES.title, hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    for p in (path, jsonl):
        print(f"  → {p.relative_to(ROOT)} ({p.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="каталог, эфемериды, сверка на трёх известных затмениях")
    ap.add_argument("--build", action="store_true", help="посчитать все затмения, записать слой")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--provinces", type=Path, default=PROVINCES_1897)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache, args.provinces)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.provinces)
    except EclipseError as exc:
        print(f"Затмения: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
