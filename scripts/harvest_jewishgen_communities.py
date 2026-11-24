#!/usr/bin/env python3
"""Сбор слоя еврейских общин с подчинением по эпохам из JewishGen Communities.

    python3 scripts/harvest_jewishgen_communities.py --check    # затравка «Pinsk» и одна губерния
    python3 scripts/harvest_jewishgen_communities.py --fetch    # обход волной, с продолжением
    python3 scripts/harvest_jewishgen_communities.py --build    # слой из кэша

Собрано с согласия владельца (сообщено владельцем проекта 24.11.2026).
Карточка общины `community.php` закрыта входом по учётной записи; сборщик
её не запрашивает и берёт строки выдачи поиска `jgcd.php`. Обход: затравка —
поиск по названию столицы в каждой стране формы (`SEEDS`), дальше — запросы
«все общины губернии c. 1900» и «воеводства c. 1930» по ссылкам, которые
встретились в выдаче, пока новые не кончатся. Пауза — две секунды
(`Crawl-delay: 2`). Каждый ответ ложится в
`data/raw/jewishgen_communities/` (в `.gitignore`) сжатым gzip; очередь
восстанавливается из кэша, так что оборванный обход продолжается тем же
вызовом.

На выходе:

* `geojson/jewishgen_communities.geojson` — до трёх записей на общину, в репозиторий;
* `jewishgen_communities.json` — без точки, если есть;
* `jsonl/jewishgen_communities.jsonl` — слой целиком (в `.gitignore`).
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
from histctx.sources.jewishgen_communities import (
    JEWISHGEN_COMMUNITIES, PAUSE, SEARCH_URL, SEEDS, JewishGenError, page_links, parse_rows,
    query_key, query_url, records, result_count, seed_form,
)
from histctx.sources.polite import PoliteClient, ProtectionError, cache_read, cache_write
from histctx.sources.russian_names import RussianNames

CACHE = ROOT / "data" / "raw" / "jewishgen_communities"
OUT = ROOT / "data" / "out"
BOUNDARIES = OUT / "boundaries"
NAMES = OUT / "name_variants.json"
LOGIN_MARKS = ("/Auth0/login.php", "cf-challenge", "challenge-platform")


def get(cl, cache: Path, name: str, url: str, data=None) -> str:
    path = cache / "pages" / f"{name}.html.gz"
    text = cache_read(path)
    if text is not None:
        return text
    if cl is None:
        raise JewishGenError(f"нет {path} в кэше (--offline)")
    raw = cl.fetch(url, data)
    text = raw.decode("utf-8", errors="replace")
    if any(mark in text[:5000] for mark in LOGIN_MARKS):
        raise ProtectionError(f"{url}: вместо выдачи — вход или проверка на бота")
    if "sr-table" not in text and "matches" not in text:
        raise JewishGenError(f"{url}: в ответе нет таблицы выдачи")
    cache_write(path, raw)
    return text


def crawl(cl, cache: Path, *, limit=None, seeds=SEEDS) -> dict:
    """Обход волной; без сети (`cl is None`) — только по кэшу."""
    pages: dict[str, str] = {}
    queue: list[tuple[str, str, dict | None]] = []
    for town, country in seeds:
        form = seed_form(town, country)
        queue.append((f"seed_{query_key(form)}", SEARCH_URL, form))
    seen = {name for name, _, _ in queue}
    fetched = 0
    while queue:
        name, url, data = queue.pop(0)
        cached_before = (cache / "pages" / f"{name}.html.gz").exists()
        if not cached_before and cl is None:
            continue
        if not cached_before and limit is not None and fetched >= limit:
            continue
        try:
            text = get(cl, cache, name, url, data)
        except JewishGenError as exc:
            print(f"  {exc}", file=sys.stderr, flush=True)
            continue
        if not cached_before:
            fetched += 1
            if fetched % 25 == 0:
                print(f"  запросов {fetched}, страниц {len(pages)}, в очереди {len(queue)}",
                      flush=True)
        pages[name] = text
        for params in page_links(text):
            key = query_key(params)
            if key not in seen:
                seen.add(key)
                queue.append((key, query_url(params), None))
    return pages


def collect(pages: dict) -> tuple[dict, collections.Counter]:
    communities, sizes = {}, collections.Counter()
    for name, text in pages.items():
        rows = parse_rows(text)
        sizes[name] = len(rows)
        total = result_count(text)
        if total is not None and len(rows) < total:
            print(f"  {name}: выдача говорит {total}, строк {len(rows)}", file=sys.stderr)
        for c in rows:
            communities.setdefault(c.usbgn, c)
    return communities, sizes


def check(cache: Path, pause: float) -> int:
    cl = PoliteClient(pause=pause, error=JewishGenError)
    pages = crawl(cl, cache, limit=2, seeds=SEEDS[:1])
    communities, sizes = collect(pages)
    print(f"Страниц: {len(pages)}, общин: {len(communities)}")
    for c in list(communities.values())[:3]:
        print(f"  {c.usbgn}: {c.name}, {c.country}; {c.lat}, {c.lon}")
        for era, unit in c.eras.items():
            print(f"      c. {era}: {unit}")
    names = RussianNames.load(NAMES) if NAMES.exists() else None
    for rec in records(list(communities.values())[:1], names=names):
        print(f"  → {rec.title}; {rec.year_from}–{rec.year_to}; {rec.summary}")
    print(f"\nЗапросов: {cl.requests}. Выдача читается — можно --fetch.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    pages = crawl(None, cache)
    communities, sizes = collect(pages)
    if not communities:
        print("В кэше нет выдачи: сначала --fetch", file=sys.stderr)
        return 1
    names = RussianNames.load(NAMES) if NAMES.exists() else None
    recs = records(communities.values(), names=names)
    marks = Frame.load(BOUNDARIES).mark(recs)
    print(f"Страниц выдачи: {len(pages)}; общин: {len(communities)}; записей: {len(recs)}")
    print("  рамка:", dict(marks))
    print("  страны ныне:", collections.Counter(c.country for c in communities.values())
          .most_common(12))
    print("  государства c. 1900:", collections.Counter(
        (c.eras.get("1900") or {}).get("country") for c in communities.values()).most_common(8))
    slug = JEWISHGEN_COMMUNITIES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=JEWISHGEN_COMMUNITIES.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{JEWISHGEN_COMMUNITIES.title}: без точки",
                           hoist_shared=True)
    write_jsonl(recs, out_dir / "jsonl" / f"{slug}.jsonl")
    (cache / "summary.json").write_text(json.dumps(
        {"pages": len(pages), "communities": len(communities), "records": len(recs)},
        ensure_ascii=False), encoding="utf-8")
    print(f"\n«{JEWISHGEN_COMMUNITIES.title}»: {len(recs)} записей, на карте {n}, "
          f"без точки {len(off_map)}")
    print(f"  → {geo.relative_to(ROOT)} ({geo.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="--fetch: не больше N запросов")
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    if args.pause < PAUSE:
        ap.error(f"пауза не меньше {PAUSE:g} с (Crawl-delay сайта)")
    try:
        if args.check:
            return check(args.cache, args.pause)
        if args.fetch:
            cl = PoliteClient(pause=args.pause, error=JewishGenError)
            pages = crawl(cl, args.cache, limit=args.limit)
            communities, _ = collect(pages)
            print(f"Страниц выдачи: {len(pages)}; общин: {len(communities)}; запросов: "
                  f"{cl.requests}, повторов: {cl.backoffs}")
        if args.build:
            return build(args.cache, args.out)
        return 0
    except ProtectionError as exc:
        print(f"JewishGen: {exc} — обход остановлен", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; скачанное лежит в кэше, повторный вызов продолжит.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
