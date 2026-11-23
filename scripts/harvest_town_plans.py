#!/usr/bin/env python3
"""Сбор слоя регулярных планов городов 1766–1831 из каталога Imperiia (Гарвард).

    python3 scripts/harvest_town_plans.py --check    # скачать, разобрать, отчёт — без записи
    python3 scripts/harvest_town_plans.py --build    # записи в data/out

Проверочный первый запуск обязателен: `--check` забирает из API Omeka все
предметы типа «PSZ Town Plans» и геолокации сайта (около двадцати страниц,
пауза 1 с), разбирает поля и показывает, сколько планов, городов и лет, у
скольких есть точка и в какую губернию 1897 года она легла.

Права. На сайте не заявлены; «Книга чертежей и рисунков» ПСЗ 1839 года —
общественное достояние. Берутся факты со ссылкой на страницу предмета.

На выходе:

* `geojson/town_plans.geojson` — планы с точкой города;
* `town_plans.json` — планы без точки (если такие есть): оба в репозиторий;
* `jsonl/town_plans.jsonl` — слой целиком (`jsonl/` в `.gitignore`).

Нужны `data/out/boundaries/provinces_1897.geojson` и `state_borders.geojson`
(рамка и губерния по точке) и `data/out/geojson/settlements.geojson`
(одноимённые города для пометки `check`) — лежат в репозитории.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import read_geojson, write_geojson, write_jsonl, write_records_json
from histctx.sources.ghcn import GhcnError
from histctx.sources.town_plans import (
    TOWN_PLANS, TownPlansError, fetch, fill_points, mark_frame, records,
)

CACHE = ROOT / "data" / "raw" / "town_plans"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
SETTLEMENTS = ROOT / "data" / "out" / "geojson" / "settlements.geojson"

# Города, по которым разбор проверяется глазами: планировались дважды,
# губернский центр, город вне нынешней России.
WATCH = ("Харьков", "Нижний Новгород", "Санкт-Петербург", "Екатеринослав", "Тверь",
         "Смоленск", "Ардатов")


def load_frame() -> Frame:
    try:
        return Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise TownPlansError(
            f"рамку взять неоткуда ({exc}). Нужны {BOUNDARIES.relative_to(ROOT)}/"
            "provinces_1897.geojson и state_borders.geojson — см. docs/HARVEST.md") from exc


def collect(cache: Path):
    items, geos = fetch(cache)
    recs = records(items, geos)
    towns = read_geojson(SETTLEMENTS) if SETTLEMENTS.exists() else []
    frame = load_frame()
    filled = fill_points(recs, frame, towns)
    counts = mark_frame(recs, frame, towns)
    if filled:
        counts["точка из GeoNames (у Imperiia её нет)"] = filled
    return items, geos, recs, counts


def report(items, geos, recs, counts) -> None:
    print(f"Предметов «PSZ Town Plans»: {len(items)}; геолокаций на сайте: {len(geos)}")
    towns = {(r.extra.get("town_ru"), r.extra.get("town_latin")) for r in recs}
    print(f"Записей: {len(recs)}, городов: {len(towns)}")
    years = sorted(r.year_from for r in recs)
    print(f"  годы планов: {years[0]}–{years[-1]}")
    for what, n in sorted(counts.items()):
        print(f"  {what}: {n}")
    by_decade = collections.Counter(y // 10 * 10 for y in years)
    print("  по десятилетиям: " + ", ".join(f"{d}-е — {n}" for d, n in sorted(by_decade.items())))
    print("  редакции: " + ", ".join(f"{k} — {n}" for k, n in collections.Counter(
        r.extra.get("edition") for r in recs).most_common()))
    print(f"  наместничеств и губерний на момент плана: "
          f"{len({r.extra.get('province_at_plan') for r in recs})}")
    regions = collections.Counter(r.region for r in recs if r.region)
    print(f"  губерний 1897 года: {len(regions)}; чаще всего: "
          + ", ".join(f"{k} — {n}" for k, n in regions.most_common(6)))
    flagged = [r for r in recs if "check" in r.extra]
    print(f"\n  с пометкой check ({len(flagged)}), где назван одноимённый город:")
    for rec in flagged:
        if "одноимённое" in rec.extra["check"]:
            print(f"    {rec.title}: {rec.extra['check']}")
    print("\n  образцы:")
    for town in WATCH:
        for rec in (r for r in recs if r.title.startswith(f"Регулярный план: {town},")):
            print(f"    {rec.title} [{rec.region or rec.confidence}]: {rec.summary[:200]}")


def check(cache: Path) -> int:
    items, geos, recs, counts = collect(cache)
    if not recs:
        print("Ни одного плана не разобрано: проверьте разбор.", file=sys.stderr)
        return 1
    report(items, geos, recs, counts)
    print("\nКаталог читается, разбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    _, _, recs, _ = collect(cache)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = TOWN_PLANS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=TOWN_PLANS.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{TOWN_PLANS.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{TOWN_PLANS.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.2f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="скачать и разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть ответы API")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except TownPlansError as exc:
        print(f"Планы городов: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
