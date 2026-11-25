#!/usr/bin/env python3
"""Сбор слоя «История России в фотографиях» (russiainphoto.ru).

    python3 scripts/harvest_russiainphoto.py --check    # две страницы каталога и карта одной рамки, отчёт
    python3 scripts/harvest_russiainphoto.py --fetch    # весь каталог и вся карта в кэш (часы; продолжает с места)
    python3 scripts/harvest_russiainphoto.py --build    # слой из кэша в data/out

Три ступени, все через адреса, которыми пользуется само приложение сайта
(см. `histctx.sources.russiainphoto`):

1. каталог — `/search/ajax/?page=N&page_size=1000`, 216 запросов;
2. карта — `/rest/front/map-grid/` по рамкам, до одиночных ячеек и ячеек
   в 5 знаков геохеша (около 5 км);
3. ячейки, где снимков больше одного, — `/search/ajax/?geohash=…`.

Ответы ложатся в `data/raw/russiainphoto/` (catalog, grid, cells — сжатый
JSON); повторный запуск берёт готовое из кэша. `--build` сети не трогает:
обход карты повторяется по кэшу, и оборванный обход даёт то, что успел
(отчёт пишет, сколько рамок и ячеек не пройдено). Снимкам вне карты точка
ставится по месту текстом — указатель мест слоёв `occupation_cities`,
`city_population`, `renamed_places`, `settlements` (`waralbum.Gazetteer`). Одно соединение, пауза
секунда после ответа, отступ на 429 и 5xx.

Собрано с согласия владельца, полученного владельцем проекта (сообщено
24.11.2026). Снимки не копируются: в записи — ссылка на страницу снимка и на
уменьшенную копию на сервере сайта.

На выходе:

* `geojson/photos_russiainphoto.geojson` — снимки с точкой на карте сайта
  и годом до 1960-го включительно; губерния 1897 года в `region`, вне рамки
  РИ/СССР — `confidence = outside_bbox`;
* `photos_russiainphoto.json` — снимки без точки (`no_coords`), с местом
  съёмки текстом в `place_text`;
* `jsonl/photos_russiainphoto.jsonl` — слой целиком (в `.gitignore`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.photo_common import Fetcher, FetchError
from histctx.sources.waralbum import Gazetteer
from histctx.sources.russiainphoto import (
    RUSSIAINPHOTO, cached_grid, catalog_items, crawl_grid, fetch_catalog, fetch_cells,
    load_leaves, points, records, save_leaves, world_tiles,
)

CACHE = ROOT / "data" / "raw" / "russiainphoto"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
GEOJSON = ROOT / "data" / "out" / "geojson"
# Рамка проверки: Тверская губерния с краем Московской — города, сёла и
# одиночные снимки вперемешку, обход на пару сотен запросов.
CHECK_RECT = (57.5, 34.0, 56.5, 36.0)


def collect(cache: Path, *, check: bool, fetch: bool) -> tuple[list, dict]:
    fetcher = Fetcher(pause=1.0, timeout=120)
    meta: dict = {}
    leaves_path = cache / ("leaves_check.json.gz" if check and not fetch else "leaves.json.gz")
    if check or fetch:
        meta["total"] = fetch_catalog(cache, fetcher, limit_pages=None if fetch else 2)
        # Плитка за плиткой: листья и ячейки каждой плитки сохраняются сразу,
        # и оборванный обход теряет не больше одной плитки (ответы карты
        # всё равно в кэше).
        leaves: dict = {}
        get_grid = cached_grid(cache, fetcher)
        for tile in (reversed(world_tiles()) if fetch else [CHECK_RECT]):
            leaves.update(crawl_grid(tile, get_grid))
            save_leaves(leaves, leaves_path)
            fetch_cells(list(leaves.values()), cache, fetcher)
            print(f"  плитка {tile}: листьев всего {len(leaves)}, запросов {fetcher.requests}",
                  flush=True)
        meta["requests"] = fetcher.requests
    if check and not fetch:
        leaves = load_leaves(leaves_path)
    else:
        # Слой собирается из кэша карты без сети: обход повторяется по
        # сохранённым ответам, и оборванная плитка даёт то, что успела.
        offline = cached_grid(cache, None)
        leaves = {}
        for tile in reversed(world_tiles()):
            leaves.update(crawl_grid(tile, offline))
        meta["grid_missing"] = offline.missing
        meta["cells_missing"] = sum(1 for l in leaves.values() if l.count > 1 and not (
            cache / "cells" / f"{l.geohash}.json.gz").exists())
    pts = points(leaves, cache)
    meta.update(leaves=len(leaves), mapped=len(pts),
                on_map=sum(l.count for l in leaves.values()))
    items = list(catalog_items(cache))
    meta["items"] = len(items)
    recs, skipped = records(items, pts, gaz=Gazetteer.load(GEOJSON))
    meta["skipped"] = skipped
    meta["frame"] = Frame.load(BOUNDARIES).mark(recs)
    return recs, meta


def report(recs: list, meta: dict) -> None:
    print(f"«{RUSSIAINPHOTO.title}»: в каталоге сайта {meta.get('total', '—')}, "
          f"прочитано {meta['items']}; запросов в этот запуск {meta.get('requests', 0)}")
    print(f"  карта: листьев {meta['leaves']}, снимков на них {meta['on_map']}, "
          f"сведено с номером {meta['mapped']}")
    if "grid_missing" in meta:
        print(f"  не пройдено: рамок карты {meta['grid_missing']}, "
              f"ячеек без списка снимков {meta['cells_missing']}")
    print(f"  записей {len(recs)}, с точкой {sum(1 for r in recs if r.has_point)}")
    for what, n in meta["skipped"].items():
        print(f"  отброшено ({what}): {n}")
    for what, n in meta["frame"].most_common():
        print(f"  {what}: {n}")
    print("  точность даты:")
    for name, n in collections.Counter(r.date_precision for r in recs).most_common():
        print(f"    {n:>7}  {name}")
    print("  места чаще всего:")
    for name, n in collections.Counter(r.place_text for r in recs).most_common(8):
        print(f"    {n:>7}  {name}")
    for rec in [r for r in recs if r.has_point][:5]:
        print(f"    {rec.period_raw:>12}  {rec.title[:60]}  [{rec.place_text}; {rec.region}]")


def build(recs: list, out_dir: Path) -> int:
    slug = RUSSIAINPHOTO.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=RUSSIAINPHOTO.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{RUSSIAINPHOTO.title}: без точки",
                           hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{RUSSIAINPHOTO.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="две страницы каталога и карта одной рамки, отчёт — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="весь каталог и вся карта в кэш")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        recs, meta = collect(args.cache, check=args.check, fetch=args.fetch)
    except FetchError as exc:
        print(f"russiainphoto: {exc}", file=sys.stderr)
        return 1
    if not recs:
        print("Ни одного снимка не разобрано: проверьте выдачу сайта.", file=sys.stderr)
        return 1
    report(recs, meta)
    if args.build:
        return build(recs, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
