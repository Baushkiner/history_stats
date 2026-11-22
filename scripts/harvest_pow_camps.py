#!/usr/bin/env python3
"""Сбор слоя лагерей военнопленных вермахта 1939–1945 годов с карты dekoder.

    python3 scripts/harvest_pow_camps.py --check    # скачать, разобрать, отчёт — без записи слоя
    python3 scripts/harvest_pow_camps.py --build    # записи в data/out

Запросов два: главная страница карты `war.dekoder.org/de/map` (около 2 МБ —
в ней точки всех слоёв карты) и `sitemap-map.xml` (адреса карточек лагерей).
Оба ответа ложатся в `data/raw/pow_camps/`; `--build` и повторный `--check`
берут их из кэша, `--refresh` скачивает заново. robots.txt сайта —
`Allow: /`.

Права не выяснены: условий карта не заявляет. Берутся факты — тип и номер
лагеря, место, время, военный округ — и ссылка на карточку лагеря на карте;
первоисточник перечня — Moosburg.org («Stalag list»).

На выходе:

* `geojson/pow_camps.geojson` — лагеря с точкой, `confidence = place_level`
  (точка — город или посёлок лагеря), губерния 1897 года в `region`, вне
  рамки РИ/СССР — `outside_bbox`;
* `pow_camps.json` — лагеря без точки, `confidence = no_coords`;
* `jsonl/pow_camps.jsonl` — слой целиком (в `.gitignore`).

Нужны `data/out/boundaries/provinces_1897.geojson` и `state_borders.geojson`
(рамка) и `data/out/name_variants.json` (русские названия мест) — все лежат в
репозитории.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.pow_camps import (
    LAYER_ID, MAP_URL, POW_CAMPS, SITEMAP_URL, DekoderError, card_urls, fetch_page,
    layer_block, payload_text, records,
)
from histctx.sources.russian_names import RussianNames

CACHE = ROOT / "data" / "raw" / "pow_camps"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
VARIANTS = ROOT / "data" / "out" / "name_variants.json"

# Лагеря, по которым видно, ради чего слой собран: номера из карточек
# советских военнопленных и лагеря в Восточной Пруссии.
WATCH = ("Stalag 352", "Dulag 131", "Stalag 342", "Stalag 326", "Stalag I B")


def cached(url: str, name: str, cache: Path, refresh: bool) -> bytes:
    path = cache / name
    if path.exists() and not refresh:
        return path.read_bytes()
    for attempt in range(3):
        try:
            data = fetch_page(url)
            break
        except DekoderError as exc:
            if attempt == 2:
                raise
            print(f"  {url}: {exc}; повтор через 5 с", file=sys.stderr)
            time.sleep(5)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    time.sleep(1)
    return data


def collect(cache: Path, refresh: bool) -> tuple[list, dict]:
    html = cached(MAP_URL, "map_de.html", cache, refresh).decode("utf-8", "replace")
    features, sheet = layer_block(payload_text(html))
    urls = card_urls(cached(SITEMAP_URL, "sitemap-map.xml", cache, refresh))
    names = RussianNames.load(VARIANTS) if VARIANTS.exists() else None
    if names is None:
        print(f"  {VARIANTS.relative_to(ROOT)} нет — подписи останутся немецкими",
              file=sys.stderr)
    recs = records(features, urls=urls, names=names, sheet=sheet)
    counts = Frame.load(BOUNDARIES).mark(recs)
    return recs, {"features": len(features), "urls": len(urls), "sheet": sheet,
                  "frame": counts}


def report(recs: list, meta: dict) -> None:
    print(f"Слой {LAYER_ID} на карте: {meta['features']} точек; карточек в карте сайта: "
          f"{meta['urls']}; лист-источник: {meta['sheet']}")
    with_point = [r for r in recs if r.has_point]
    print(f"  записей {len(recs)}, с точкой {len(with_point)}, без точки "
          f"{len(recs) - len(with_point)}")
    print(f"  с карточкой dekoder: {sum(1 for r in recs if '/pow_camps/' in (r.url or ''))}")
    for what, n in meta["frame"].most_common():
        print(f"  {what}: {n}")
    print("  типы:")
    for name, n in collections.Counter(r.category for r in recs).most_common():
        print(f"    {n:>5}  {name}")
    print("  время:")
    for name, n in collections.Counter(r.date_precision for r in recs).most_common():
        print(f"    {n:>5}  {name}")
    russian = sum(1 for r in recs if r.title.split(" — ")[-1] != r.extra.get("name_de"))
    print(f"  по-русски подписано: {russian}")
    print("  примеры:")
    for nr in WATCH:
        for rec in (r for r in recs if r.extra.get("lager_nr") == nr):
            print(f"    {rec.year_from}–{rec.year_to}  {rec.title}  [{rec.region or '—'}]")


def build(recs: list, out_dir: Path) -> int:
    slug = POW_CAMPS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=POW_CAMPS.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{POW_CAMPS.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{POW_CAMPS.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="скачать, разобрать, напечатать отчёт — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--refresh", action="store_true", help="скачать страницы заново")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        recs, meta = collect(args.cache, args.refresh)
    except DekoderError as exc:
        print(f"dekoder: {exc}", file=sys.stderr)
        return 1
    if not recs:
        print("Ни одного лагеря не разобрано: проверьте разметку карты.", file=sys.stderr)
        return 1
    if args.check:
        report(recs, meta)
        if not args.build:
            print("\nКарта читается, разбор работает — можно запускать --build.")
            return 0
    return build(recs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
