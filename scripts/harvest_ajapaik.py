#!/usr/bin/env python3
"""Сбор слоя старых фотографий Ajapaik (ajapaik.ee).

    python3 scripts/harvest_ajapaik.py --check     # три страницы API, разбор, отчёт — без записи слоя
    python3 scripts/harvest_ajapaik.py --fetch     # весь обход в кэш (часы; продолжает с места)
    python3 scripts/harvest_ajapaik.py --build     # слой из кэша в data/out

Обход — `GET /api/v1/album/nearest/` от центра Таллина страницами по 500 до
первой страницы без координат (см. `histctx.sources.ajapaik`). Страницы
ложатся в `data/raw/ajapaik/nearest/` сжатыми, только с полями слоя; повторный
запуск берёт готовые из кэша и продолжает со следующей. Одно соединение,
пауза секунда после ответа, отступ на 429 и 5xx.

Собрано с согласия владельца, полученного владельцем проекта (сообщено
24.11.2026). Снимки не копируются: в записи — ссылка на страницу снимка и
на его уменьшенную копию на сервере Ajapaik.

На выходе:

* `geojson/photos_ajapaik.geojson` — снимки с точкой и годом до 1960-го
  включительно; губерния 1897 года в `region`, вне рамки РИ/СССР —
  `confidence = outside_bbox`;
* `jsonl/photos_ajapaik.jsonl` — то же построчно (в `.gitignore`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl
from histctx.sources.ajapaik import AJAPAIK, AjapaikError, fetch_pages, load_pages, records
from histctx.sources.photo_common import FetchError

CACHE = ROOT / "data" / "raw" / "ajapaik"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"


def report(recs: list, skipped: dict, frame: collections.Counter) -> None:
    print(f"«{AJAPAIK.title}»: записей {len(recs)}")
    for what, n in skipped.items():
        print(f"  отброшено ({what}): {n}")
    for what, n in frame.most_common():
        print(f"  {what}: {n}")
    print("  точность даты:")
    for name, n in collections.Counter(r.date_precision for r in recs).most_common():
        print(f"    {n:>7}  {name}")
    print("  по десятилетиям:")
    for dec, n in sorted(collections.Counter(r.year_from // 10 * 10 for r in recs).items()):
        print(f"    {dec}-е  {n}")
    print(f"  год из подписи: {sum(1 for r in recs if r.extra.get('date_from'))}")
    print(f"  с автором: {sum(1 for r in recs if r.actor)}")
    for rec in recs[:5]:
        print(f"    {rec.period_raw:>12}  {rec.title[:70]}  [{rec.region or rec.confidence}]")


def build(recs: list, out_dir: Path) -> int:
    slug = AJAPAIK.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=AJAPAIK.title, hoist_shared=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{AJAPAIK.title}»: {len(recs)} записей, на карте {n}")
    for path in (geo, jsonl):
        print(f"  → {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="три страницы API, разбор, отчёт — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="весь обход в кэш, с продолжением")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check or args.fetch:
            pages = fetch_pages(args.cache, limit_pages=None if args.fetch else 3)
            print(f"страниц в кэше: {pages}")
    except (AjapaikError, FetchError) as exc:
        print(f"Ajapaik: {exc}", file=sys.stderr)
        return 1
    recs, skipped = records(load_pages(args.cache))
    if not recs:
        print("Ни одного снимка не разобрано: проверьте ответ API.", file=sys.stderr)
        return 1
    frame = Frame.load(BOUNDARIES).mark(recs)
    if args.check or args.fetch:
        report(recs, skipped, frame)
    if args.build:
        return build(recs, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
