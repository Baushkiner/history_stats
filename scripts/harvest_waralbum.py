#!/usr/bin/env python3
"""Сбор слоя фотографий войны 1939–1945 годов из «Военного альбома» (waralbum.ru).

    python3 scripts/harvest_waralbum.py --check            # карта сайта и 30 страниц, отчёт — без записи слоя
    python3 scripts/harvest_waralbum.py --fetch            # все страницы снимков в кэш (около 30 часов; продолжает с места)
    python3 scripts/harvest_waralbum.py --fetch --limit N  # следующие N страниц
    python3 scripts/harvest_waralbum.py --build            # слой из кэша в data/out

Адреса снимков — из карты сайта (`sitemap1.xml`, `sitemap2.xml`); со страницы
снимка берётся блок с заголовком, подписью, источником, рубриками и
«Информацией о фото» (см. `histctx.sources.waralbum`). Блоки ложатся в
`data/raw/waralbum/pages.jsonl`, номера из карты сайта — в `ids.json`;
повторный запуск продолжает с первой нескачанной страницы. Одно соединение,
пауза секунда после ответа, отступ на 429 и 5xx.

Слой собирается из того, что есть в кэше: пока обход не закончен, он
неполон, и `--build` об этом пишет.

Собрано с согласия владельца, полученного владельцем проекта (сообщено
24.11.2026). Снимки не копируются: в записи — ссылка на страницу снимка и на
его копию на сайте.

На выходе:

* `geojson/photos_waralbum.geojson` — снимки с точкой населённого пункта
  (`place_level`), губерния 1897 года в `region`, вне рамки — `outside_bbox`;
* `photos_waralbum.json` — снимки без точки: `no_coords` и `outside_bbox`
  по стране в «Месте съемки»;
* `jsonl/photos_waralbum.jsonl` — слой целиком (в `.gitignore`).

Указатель мест — слои `occupation_cities`, `city_population`,
`renamed_places`, `settlements` в `data/out/geojson/` (лежат в репозитории).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.photo_common import Fetcher, FetchError
from histctx.sources.waralbum import (
    WARALBUM, Gazetteer, WaralbumError, fetch_pages, load_pages, parse_fragment, records,
    sitemap_ids,
)

CACHE = ROOT / "data" / "raw" / "waralbum"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
GEOJSON = ROOT / "data" / "out" / "geojson"


def collect(cache: Path) -> tuple[list, dict]:
    photos, broken = [], 0
    for pid, frag in load_pages(cache):
        photo = parse_fragment(pid, frag) if frag else None
        if photo is None:
            broken += 1
            continue
        photos.append(photo)
    recs, skipped = records(photos, Gazetteer.load(GEOJSON))
    frame = Frame.load(BOUNDARIES).mark(recs)
    ids_path = cache / "ids.json"
    total = len(json.loads(ids_path.read_text(encoding="utf-8"))) if ids_path.exists() else None
    return recs, {"pages": len(photos) + broken, "broken": broken, "skipped": skipped,
                  "frame": frame, "total": total, "photos": photos}


def report(recs: list, meta: dict) -> None:
    print(f"«{WARALBUM.title}»: страниц в кэше {meta['pages']} из {meta['total']}, "
          f"без блока снимка {meta['broken']}")
    print(f"  записей {len(recs)}")
    for what, n in meta["skipped"].items():
        print(f"  отброшено ({what}): {n}")
    for what, n in collections.Counter(r.confidence for r in recs).most_common():
        print(f"  {what}: {n}")
    for what, n in meta["frame"].most_common():
        print(f"  {what}: {n}")
    photos = meta["photos"]
    print(f"  с местом {sum(1 for p in photos if p.place)}, со временем "
          f"{sum(1 for p in photos if p.time)}, с автором {sum(1 for p in photos if p.author)}")
    print("  точность даты:")
    for name, n in collections.Counter(r.date_precision for r in recs).most_common():
        print(f"    {n:>7}  {name}")
    print("  места без точки чаще всего:")
    for name, n in collections.Counter(r.place_text for r in recs
                                       if r.confidence == "no_coords").most_common(10):
        print(f"    {n:>7}  {name}")
    for rec in [r for r in recs if r.has_point][:5]:
        print(f"    {rec.period_raw:>12}  {rec.title[:60]}  [{rec.place_text} → {rec.region}]")


def build(recs: list, meta: dict, out_dir: Path) -> int:
    slug = WARALBUM.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=WARALBUM.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{WARALBUM.title}: без точки",
                           hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{WARALBUM.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    if meta["total"] and meta["pages"] < meta["total"]:
        print(f"  НЕПОЛНЫЙ СЛОЙ: пройдено {meta['pages']} страниц из {meta['total']}; "
              "продолжить: --fetch")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="карта сайта и 30 страниц, отчёт — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="страницы снимков в кэш, с продолжением")
    ap.add_argument("--limit", type=int, help="сколько страниц скачать в этот запуск")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check or args.fetch:
            fetcher = Fetcher(pause=1.0, timeout=90)
            ids = sitemap_ids(fetcher, args.cache)
            print(f"снимков в карте сайта: {len(ids)}")
            limit = args.limit if args.fetch else 30
            fetch_pages(ids, args.cache, fetcher, limit=limit)
    except (WaralbumError, FetchError) as exc:
        print(f"waralbum: {exc}", file=sys.stderr)
        return 1
    recs, meta = collect(args.cache)
    if not recs:
        print("Ни одного снимка не разобрано: проверьте разметку страниц.", file=sys.stderr)
        return 1
    if args.check or args.fetch:
        report(recs, meta)
    if args.build:
        return build(recs, meta, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
