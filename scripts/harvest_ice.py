#!/usr/bin/env python3
"""Сбор слоя ледостава и вскрытия рек и озёр (NSIDC, набор G01377).

    python3 scripts/harvest_ice.py --check    # сверить две таблицы, показать разбор
    python3 scripts/harvest_ice.py --build    # слой в data/out

В сеть команда не ходит. Таблицы `liag_freeze_thaw_table.csv` и
`liag_physical_character_table.csv` скачиваются руками со страницы набора
(https://nsidc.org/data/g01377/versions/1, «HTTPS File System») и кладутся в
`data/raw/nsidc_ice/`: `robots.txt` файлового хоста NSIDC закрывает его
целиком, и автоматического сбора оттуда проект не ведёт.

Первый запуск — проверочный. `--check` (он же `--probe`) сверяет размер и
колонки таблиц с записанным в `sources/ice.py`, считает обычные сроки по
постам и показывает разбор.

Права: условие NSIDC — ссылка на набор; она стоит в каждой записи.

На выходе `geojson/ice_phenology.geojson`, `ice_phenology.json` (зимы поста
без точки) — оба в репозиторий — и `jsonl/ice_phenology.jsonl`. Губерния 1897
года — по полигонам `data/out/boundaries`.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.ghcn import GhcnError
from histctx.sources.ice import (
    ICE_PHENOLOGY, REQUIRED_SEASONS, REQUIRED_SITES, SEASONS_FILE, SITES_FILE, IceError,
    local_file, read_sites, read_table, records, summary_counts,
)

CACHE = ROOT / "data" / "raw" / "nsidc_ice"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
WATCH = ("NG3:1899-00", "NG3:1811-12", "NG1:1890-91", "VSV38:1941-42", "VSV30:1940-41")


def collect(cache: Path) -> tuple[list, list, collections.Counter]:
    site_rows = read_table(local_file(SITES_FILE, cache).read_bytes(), REQUIRED_SITES,
                           SITES_FILE)
    season_rows = read_table(local_file(SEASONS_FILE, cache).read_bytes(), REQUIRED_SEASONS,
                             SEASONS_FILE)
    sites = read_sites(site_rows, season_rows)
    recs = records(sites)
    try:
        counts = Frame.load(BOUNDARIES).mark(recs)
    except (GhcnError, OSError, ValueError) as exc:
        raise IceError(f"рамку взять неоткуда ({exc}): нужны границы из "
                       f"{BOUNDARIES.relative_to(ROOT)} — см. docs/HARVEST.md") from exc
    return sites, recs, counts


def report(sites: list, recs: list, counts: collections.Counter) -> None:
    print(f"Постов: {len(sites)}, зим (записей): {len(recs)}")
    for what, n in sorted(summary_counts(sites).items()):
        print(f"  {what}: {n}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    with_norm = sum(1 for s in sites if s.norm_on is not None or s.norm_off is not None)
    print(f"  постов с нормой: {with_norm}; без нормы (короткий ряд): {len(sites) - with_norm}")
    print(f"  координаты: {dict(collections.Counter(s.coords for s in sites))}")
    by_century = collections.Counter(f"{(r.year_to - 1) // 100 + 1} век" for r in recs)
    print("  по векам: " + ", ".join(f"{k} — {v}" for k, v in sorted(by_century.items())))
    print("  категории:")
    for what, n in collections.Counter(r.category for r in recs).most_common():
        print(f"    {n:>5}  {what}")
    print("  самые длинные ряды:")
    for site in sorted(sites, key=lambda s: -len(s.seasons))[:6]:
        print(f"    {site.title}: {len(site.seasons)} зим, "
              f"{site.seasons[0].winter}–{site.seasons[-1].winter}")
    print("  образцы:")
    by_id = {r.source_id: r for r in recs}
    for key in WATCH:
        rec = by_id.get(key)
        if rec is not None:
            print(f"    {rec.title} [{rec.category}; {rec.region or 'губернии нет'}]\n"
                  f"      {rec.summary}")


def check(cache: Path) -> int:
    sites, recs, counts = collect(cache)
    if not recs:
        print("Ни одной зимы не разобрано: проверьте разбор.", file=sys.stderr)
        return 1
    report(sites, recs, counts)
    print("\nТаблицы на месте, размеры и колонки сходятся — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    _, recs, counts = collect(cache)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = ICE_PHENOLOGY.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=ICE_PHENOLOGY.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{ICE_PHENOLOGY.title}: без координаты")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{ICE_PHENOLOGY.title}»: {len(recs)} записей, на карте {n}, "
          f"без координаты {len(off_map)}")
    for what, count in counts.most_common():
        print(f"  {what}: {count}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить таблицы, показать разбор")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except IceError as exc:
        print(f"NSIDC: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
