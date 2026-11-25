#!/usr/bin/env python3
"""Сбор слоя списков колоний Odessa Digital Library (odessa3.org).

    python3 scripts/harvest_colony_lists_odessa3.py --check    # скачать, разобрать, отчёт
    python3 scripts/harvest_colony_lists_odessa3.py --build    # записи в data/out

Запросов четыре — по файлу на список (`collections/refs/link/volgavl.txt`,
`odessavl.txt`, `crimeavl.txt`, `menvil.txt`, вместе около 240 КБ), с паузой
полторы секунды. Ответы ложатся в `data/raw/colony_lists_odessa3/`; повторный
запуск берёт их из кэша, `--refresh` скачивает заново. robots.txt библиотеки
закрывает `/collections/`, а шапка каждого списка запрещает перепубликацию
без разрешения: собрано с согласия владельца, полученного владельцем проекта
(сообщено 24.11.2026), и берутся только факты со ссылкой на файл списка.

Точки — из слоя `german_colonies` (GRSL): нужен
`data/out/geojson/german_colonies.geojson`; без него все записи пойдут без
точки. Губерния 1897 года и рамка — `data/out/boundaries/`.

На выходе:

* `geojson/colony_lists_odessa3.geojson` — строки списков с точкой GRSL;
* `colony_lists_odessa3.json` — строки без точки (`no_coords`), с губернией
  по самому списку;
* `jsonl/colony_lists_odessa3.jsonl` — слой целиком (в `.gitignore`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.colony_lists_odessa3 import (
    COLONY_LISTS, LISTS, GrslIndex, Odessa3Error, fetch_lists, match_counts, records,
)

CACHE = ROOT / "data" / "raw" / "colony_lists_odessa3"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
GRSL = ROOT / "data" / "out" / "geojson" / "german_colonies.geojson"

# Сёла, по которым видно, ради чего слой собран: Крацке и Шиллинг на Волге,
# Гальбштадт Молочны, Цюрихталь в Крыму, Либенталь под Одессой.
WATCH = ("Kratzke", "Schilling", "Halbstadt", "Zuerichtal", "Grossliebental")


def collect(cache: Path, refresh: bool) -> tuple[list, dict]:
    texts = fetch_lists(cache, refresh=refresh)
    grsl = None
    if GRSL.exists():
        grsl = GrslIndex.load(GRSL)
    else:
        print(f"  {GRSL.relative_to(ROOT)} нет — точек не будет. Соберите слой: "
              "python3 scripts/harvest_german_colonies.py --build", file=sys.stderr)
    recs = records(texts, grsl)
    counts = Frame.load(BOUNDARIES).mark(recs)
    return recs, {"frame": counts, "sizes": {k: len(v) for k, v in texts.items()}}


def report(recs: list, meta: dict) -> None:
    print(f"Слой {COLONY_LISTS.slug}: записей {len(recs)}")
    per_list = collections.Counter(r.extra["list"] for r in recs)
    for spec in LISTS:
        print(f"  {spec.title} ({spec.compiler}): {per_list[spec.key]} строк, "
              f"{meta['sizes'].get(spec.key, 0) / 1024:.0f} КБ")
    print("  точка GRSL:")
    for (lst, how), n in sorted(match_counts(recs).items()):
        print(f"    {lst:<10} {how:<26} {n:>5}")
    with_year = [r for r in recs if r.extra.get("grsl") and r.year_from]
    differ = [r for r in with_year if r.extra.get("grsl_year")]
    print(f"  год основания у найденных в GRSL: сходится или у GRSL нет — "
          f"{len(with_year) - len(differ)}, расходится (до 10 лет) — {len(differ)}")
    for what, n in meta["frame"].most_common():
        print(f"  {what}: {n}")
    for name, n in collections.Counter(r.confidence for r in recs).most_common():
        print(f"    {n:>5}  {name}")
    print("  примеры:")
    for name in WATCH:
        for rec in [r for r in recs if r.extra.get("name_de") == name][:3]:
            print(f"    {rec.title}  [{rec.region or '—'}; GRSL: {rec.extra.get('grsl_match')}]")


def build(recs: list, out_dir: Path) -> int:
    slug = COLONY_LISTS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=COLONY_LISTS.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    write_records_json(off_map, json_path, title=f"{COLONY_LISTS.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{COLONY_LISTS.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path, jsonl):
        print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="скачать, разобрать, напечатать отчёт — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--refresh", action="store_true", help="скачать списки заново")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        recs, meta = collect(args.cache, args.refresh)
    except Odessa3Error as exc:
        print(f"odessa3: {exc}", file=sys.stderr)
        return 1
    if not recs:
        print("Ни одной строки не разобрано: проверьте разметку списков.", file=sys.stderr)
        return 1
    if args.check:
        report(recs, meta)
        if not args.build:
            print("\nСписки читаются, разбор работает — можно запускать --build.")
            return 0
    return build(recs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
