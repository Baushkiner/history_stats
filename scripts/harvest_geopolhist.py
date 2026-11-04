#!/usr/bin/env python3
"""Сбор слоя статусов территорий мира 1816–1960 из GeoPolHist (Sciences Po, Zenodo).

    python3 scripts/harvest_geopolhist.py --check    # сверка, разбор, без записи слоя
    python3 scripts/harvest_geopolhist.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков: `--check`
сверяет перечень файлов записи Zenodo с размером и md5, записанными в коде,
скачивает архив (1,3 МБ, кладётся в `data/raw/geopolhist/`), разбирает три
таблицы и показывает, сколько строк статуса попало в рамку, у скольких есть
точка и какие названия и статусы остались без русской подписи.

Права. Карточка версии 202603 — CC BY 4.0 (в `datapackage.json` архива —
ODbL 1.0). Берутся факты — статус, суверен, годы — со ссылкой на набор;
русские подписи — словарь проекта (`sources/geopolhist_names.py`).

На выходе:

* `geojson/territory_status.geojson` — записи с точкой: условный центр
  территории, `confidence = territory_center`;
* `territory_status.json` — записи единиц без точки, `confidence = no_coords`:
  в репозиторий идут оба файла, `jsonl/` в `.gitignore`;
* `jsonl/territory_status.jsonl` — слой целиком.

Нужен `data/out/boundaries/state_borders.geojson` (CShapes, лежит в
репозитории): по нему записи крупных единиц получают номер полигона,
к которому карта может приложить их статус.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.geopolhist import (
    ENTITIES, STATUSES, TERRITORY_STATUS, VERSION, YEAR_MAX, YEAR_MIN, GeoPolHistError,
    cached_archive, check_manifest, fetch_manifest, polygon_codes, read_archive, records,
    unknown_statuses, untranslated,
)

CACHE = ROOT / "data" / "raw" / "geopolhist"
BORDERS = ROOT / "data" / "out" / "boundaries" / "state_borders.geojson"

# Территории, по которым видно, ради чего слой собран: то, чего не рисуют
# границы государств, — и то, где статус менялся у самой империи.
WATCH = ("Harbin", "Lüshun Port (Port Arthur)", "Kwangtung Territory",
         "Tuvan People's Republic", "Memel", "Danzig (Free City of Danzig)",
         "Bokhara", "Alaska", "Finland", "Moldova (Bessarabia) (Moldavian Republic)")


def load_codes() -> set[int]:
    if not BORDERS.exists():
        print(f"  {BORDERS.relative_to(ROOT)} нет — записи останутся без номера "
              "полигона. Соберите границы: python3 scripts/harvest_cshapes.py --build",
              file=sys.stderr)
        return set()
    return polygon_codes(BORDERS)


def report(tables: dict, recs: list) -> None:
    entities, statuses = tables[ENTITIES], tables[STATUSES]
    print(f"Единиц в наборе: {len(entities)}, строк статуса: {len(statuses)}")
    print(f"В рамке {YEAR_MIN}–{YEAR_MAX}: {len(recs)} строк у "
          f"{len({r.source_id for r in recs})} единиц")
    with_point = [r for r in recs if r.has_point]
    print(f"  с точкой (условный центр территории): {len(with_point)}; без точки: "
          f"{len(recs) - len(with_point)}")
    print(f"  с началом «?» (взято от {YEAR_MIN} года, точность open): "
          f"{sum(1 for r in recs if r.date_precision == 'open')}")
    linked = [r for r in recs if "state_borders_gwcode" in r.extra]
    print(f"  с номером полигона CShapes: {len(linked)} строк у "
          f"{len({r.source_id for r in linked})} единиц")

    print("\n  статусы:")
    for name, count in collections.Counter(r.category for r in recs).most_common():
        print(f"    {count:>5}  {name}")
    print("  суверены, чаще всего:")
    sovereigns = collections.Counter(r.actor for r in recs if r.actor)
    for name, count in sovereigns.most_common(12):
        print(f"    {count:>5}  {name}")

    missing = untranslated(tables)
    if missing:
        # Не ошибка: подпись пойдёт по-английски. Но словарь стоит дополнить.
        print(f"  без русского названия ({len(missing)}): {', '.join(missing)}")
    strange = unknown_statuses(tables)
    if strange:
        print(f"  статусы без перевода ({len(strange)}): {', '.join(strange)}")

    print("\n  то, чего не рисуют границы государств:")
    for name in WATCH:
        for rec in (r for r in recs if r.place_text == name):
            print(f"    {rec.year_from}–{rec.year_to}  {rec.title}")


def check(cache: Path) -> int:
    problems = check_manifest(fetch_manifest())
    if problems:
        print(f"GeoPolHist {VERSION}: файл на Zenodo не тот, что записан в коде:",
              file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"GeoPolHist {VERSION}: перечень файлов записи на Zenodo сходится с кодом.")
    tables = read_archive(cached_archive(cache))
    recs = records(tables, polygon_codes=load_codes())
    if not recs:
        print("Ни одна строка не попала в рамку: проверьте разбор.", file=sys.stderr)
        return 1
    report(tables, recs)
    print("\nНабор читается, разбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    tables = read_archive(cached_archive(cache))
    recs = records(tables, polygon_codes=load_codes())
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = TERRITORY_STATUS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    # Права, источник и ссылка у всех записей одни — они выносятся на уровень
    # коллекции, как у остальных слоёв, собранных после 2026 года.
    n = write_geojson(recs, geo, layer_title=TERRITORY_STATUS.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{TERRITORY_STATUS.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{TERRITORY_STATUS.title}»: {len(recs)} записей, на карте {n}, "
          f"без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить, скачать, разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть архив набора")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except GeoPolHistError as exc:
        print(f"GeoPolHist: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
