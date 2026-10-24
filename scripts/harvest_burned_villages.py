#!/usr/bin/env python3
"""Сбор слоя сожжённых деревень Белоруссии 1941–1944 годов: набор Жукова и база НАРБ.

    python3 scripts/harvest_burned_villages.py --check          # набор: перечень, файлы, сверка
    python3 scripts/harvest_burned_villages.py --probe          # то же + проба НАРБ на 40 карточках
    python3 scripts/harvest_burned_villages.py --narb-all       # полный обход карточек НАРБ (часы)
    python3 scripts/harvest_burned_villages.py --build          # записи в data/out

Проверочный первый запуск обязателен. `--check` запрашивает список файлов
набора по API Dataverse и сверяет имена, идентификаторы и размеры с
перечнем в `sources/burned_villages.py`; скачивает главную таблицу
(5 МБ) в `data/raw/burned_villages_by/`; проходит помесячный файл (291 МБ)
потоком из сети и кладёт рядом выжимку `months_scan.json` — месяцы
с ненулевыми числами; сверяет суммы по месяцам с итогами главной таблицы
и названия после починки кодировки. Разошлось — остановка, а не подгонка.

`--probe` добавляет пробу базы НАРБ: читает `robots.txt`, собирает адреса
карточек из sitemap, запрашивает `--sample` карточек, равномерно
разнесённых по алфавиту, проверяет, что формат карточки прежний, и
печатает долю карточек, сведённых с деревнями набора. Карточки ложатся в
кэш `narb_cards.jsonl` и повторно не запрашиваются.

`--narb-all` обходит все карточки из sitemap — около 9 400, при паузе
в секунду и обрывах соединения это 8–10 часов. Обход можно прерывать:
кэш дописывается построчно, повторный запуск продолжает с места.

`--build` пишет то, что есть в кэше: деревни набора (с карточкой НАРБ,
если сведена) и карточки без пары. Полный обход для сборки не обязателен —
без него у части деревень нет даты словами и архивного шифра.

На выходе:

* `geojson/burned_villages_by.geojson` — деревни, чья координата в наборе
  одна на деревню: точки карты;
* `burned_villages_by.json` — деревни, чью точку набор делит с другими
  (координата геокодера — не деревня), и карточки НАРБ без пары: охват
  «район в области», без точки;
* `jsonl/burned_villages_by.jsonl` — всё вместе; в репозиторий не идёт.

Права: набор Жукова — CC0 1.0; база НАРБ условий не заявляет — права не
выяснены, берутся факты и ссылка на карточку.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.burned_villages import (
    BURNED_VILLAGES, CONFIDENCE_SHARED, DATASET_URL, FILES, MONTHS_FILE, NARB_URL,
    REQUIRED_VILLAGES, VILLAGES, BurnedVillagesError, CardCache, NarbClient, all_card_urls,
    build_records, cached_villages, check_columns, check_manifest, check_scan,
    fetch_cards, fetch_manifest, match_cards, months_scan, point_mates, read_villages,
    spread_sample,
)

CACHE = ROOT / "data" / "raw" / "burned_villages_by"


def load_villages(cache_dir: Path) -> list[dict]:
    rows = read_villages(cached_villages(cache_dir))
    check_columns(rows[0].keys() if rows else [], REQUIRED_VILLAGES, VILLAGES.name)
    return rows


def check(cache_dir: Path, refresh: bool) -> int:
    print(f"Карточка набора: {DATASET_URL}")
    manifest = fetch_manifest()
    print(f"Файлов в наборе по API: {len(manifest)}; нужных сборщику: {len(FILES)}")
    problems = check_manifest(manifest)
    if problems:
        print("\nПеречень в коде расходится с набором — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    for file in FILES:
        print(f"  {file.file_id}  {file.name:<34} {file.size:>10} байт  сходится")

    villages = load_villages(cache_dir)
    print(f"\n{VILLAGES.name}: строк {len(villages)}, колонок {len(villages[0])}")
    print(f"{MONTHS_FILE.name}: проход потоком"
          + (" (заново)" if refresh else " (или выжимка из кэша, если она есть)"))
    scan = months_scan(cache_dir, refresh=refresh)
    print(f"  строк {scan.rows}, колонок {len(scan.header)}, месяцы {scan.yrmo_min}–"
          f"{scan.yrmo_max}, деревень {len(scan.names)}")
    print(f"  строк «деревня-месяц» с ненулевыми числами: "
          f"{sum(len(m) for m in scan.months.values())}")
    print(f"  повторы строк схлопнуты: {scan.duplicates} (VID {', '.join(scan.duplicate_vids)})")
    problems = check_scan(scan, villages)
    if problems:
        print("\nПомесячный файл не сходится с главной таблицей — сбор остановлен:",
              file=sys.stderr)
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("  суммы по месяцам сходятся с итогами у всех деревень, названия после "
          "починки кодировки совпали")

    by_count = collections.Counter(
        len([m for m in scan.months.get(v["VID"], []) if any(m[1:])]) for v in villages)
    print("  деревень по числу месяцев с акциями: "
          + ", ".join(f"{k}: {n}" for k, n in sorted(by_count.items())))

    mates = point_mates(villages)
    alone = sum(1 for v in villages if not mates[v["VID"]])
    points = len({(v["LAT"], v["LONG"]) for v in villages})
    print(f"\nТочек в наборе {points} на {len(villages)} деревень; точка — сама деревня у "
          f"{alone}, у {len(villages) - alone} она общая с деревней другого названия "
          f"или района (пойдут без точки, confidence={CONFIDENCE_SHARED})")

    records, _ = build_records(villages, scan)
    print(f"\nЗаписей: {len(records)}")
    for category, count in collections.Counter(r.category for r in records).most_common():
        print(f"  {count:>5}  {category}")
    years = collections.Counter(r.year_from for r in records)
    print("  по году начала: " + ", ".join(f"{y}: {n}" for y, n in sorted(years.items())))
    print("\n  примеры:")
    for rec in [r for r in records if "Хатынь" in r.title][:1] + records[:2]:
        print(f"    {rec.title}")
        print(f"      {rec.summary}")
    return 0


def probe_narb(cache_dir: Path, sample: int, pause: float) -> int:
    client = NarbClient(pause=pause)
    disallow = client.load_robots()
    print(f"\nБаза НАРБ: {NARB_URL}")
    print("  robots.txt закрывает: " + ", ".join(disallow))
    urls = all_card_urls(client)
    print(f"  карточек в sitemap: {len(urls)}")
    cache = CardCache(cache_dir / "narb_cards.jsonl")
    picked = spread_sample(urls, sample)
    added = fetch_cards(client, picked, cache)
    print(f"  проба: {len(picked)} карточек, равномерно по алфавиту; запрошено новых "
          f"{added}, обрывов соединения {client.resets} на {client.requests} запросов")
    cards = [cache.cards[u] for u in picked]
    villages = load_villages(cache_dir)
    matched, stats = match_cards(villages, cards)
    share = len(matched) / len(cards) if cards else 0
    print(f"  сведено с деревнями набора: {len(matched)} из {len(cards)} ({share:.0%})")
    for key in ("название, район и числа", "название и район",
                "название и числа, район другой", "район и числа, название другое",
                "неоднозначно", "без пары"):
        if stats.get(key):
            print(f"    {stats[key]:>4}  {key}")
    dated = [c for c in cards if c.get("date")]
    print(f"  дата словами есть у {len(dated)}, архивный шифр — у "
          f"{sum(1 for c in cards if c.get('sources'))}")
    unmatched = [c for c in cards if c["url"] not in {m[0]['url'] for m in matched.values()}]
    if unmatched:
        print("  без пары (первые 10):")
        for c in unmatched[:10]:
            print(f"    {c.get('name')} — {c.get('rayon_prewar')} / {c.get('rayon')}, "
                  f"дворов {c.get('houses_destroyed')}, погибших {c.get('people_killed')}, "
                  f"{c.get('date')}")
    print(f"  в кэше карточек: {len(cache.cards)} из {len(urls)}; полный обход — --narb-all")
    return 0


def narb_all(cache_dir: Path, pause: float, limit: int) -> int:
    client = NarbClient(pause=pause)
    client.load_robots()
    urls = all_card_urls(client)
    cache = CardCache(cache_dir / "narb_cards.jsonl")
    todo = [u for u in urls if u not in cache]
    if limit:
        todo = todo[:limit]
    print(f"Карточек в sitemap {len(urls)}, в кэше {len(cache.cards)}, запросить {len(todo)}")

    def progress(n: int, card: dict) -> None:
        if n % 100 == 0:
            print(f"  {n}/{len(todo)}  {card.get('name')}  (обрывов {client.resets})",
                  flush=True)

    added = fetch_cards(client, todo, cache, progress=progress)
    print(f"Запрошено {added}, в кэше {len(cache.cards)} из {len(urls)}")
    return 0


def build(cache_dir: Path, out_dir: Path) -> int:
    villages = load_villages(cache_dir)
    scan = months_scan(cache_dir)
    problems = check_scan(scan, villages)
    if problems:
        print("Выжимка помесячного файла не сходится с главной таблицей — запустите "
              "--check заново:", *problems[:5], sep="\n  ", file=sys.stderr)
        return 1
    cache = CardCache(cache_dir / "narb_cards.jsonl")
    records, stats = build_records(villages, scan, cache.cards.values())

    out_dir.mkdir(parents=True, exist_ok=True)
    slug = BURNED_VILLAGES.slug
    points = [r for r in records if r.has_point]
    others = [r for r in records if not r.has_point]
    n = write_geojson(points, out_dir / "geojson" / f"{slug}.geojson",
                      layer_title=BURNED_VILLAGES.title, hoist_shared=True)
    write_records_json(others, out_dir / f"{slug}.json", title=BURNED_VILLAGES.title)
    write_jsonl(records, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"Собрано {len(records)} записей: {n} точкой, {len(others)} без точки "
          f"(из них {sum(1 for r in others if r.confidence == CONFIDENCE_SHARED)} — "
          f"точка набора общая с другой деревней).")
    if cache.cards:
        print(f"  карточек НАРБ в кэше {len(cache.cards)}, сведено с набором "
              f"{stats.get('сведено', 0)}, без пары (записи без точки) "
              f"{len(cache.cards) - stats.get('сведено', 0)}")
    for path in (out_dir / "geojson" / f"{slug}.geojson", out_dir / f"{slug}.json"):
        print(f"  {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
              f"{path.stat().st_size / 1_048_576:.1f} МБ")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="сверить набор с перечнем, пройти помесячный файл, показать разбор")
    ap.add_argument("--probe", action="store_true",
                    help="--check и проба базы НАРБ на --sample карточках")
    ap.add_argument("--narb-all", action="store_true",
                    help="обойти все карточки НАРБ из sitemap (часы; продолжается с места)")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--refresh", action="store_true",
                    help="пройти помесячный файл заново, даже если выжимка есть")
    ap.add_argument("--sample", type=int, default=40, help="карточек НАРБ в пробе")
    ap.add_argument("--limit", type=int, default=0,
                    help="для --narb-all: запросить не больше стольких карточек")
    ap.add_argument("--pause", type=float, default=1.0,
                    help="пауза между запросами к db.narb.by, секунд")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()

    if not (args.check or args.probe or args.narb_all or args.build):
        ap.error("укажите --check, --probe, --narb-all или --build")

    try:
        if args.check or args.probe:
            code = check(args.cache, args.refresh)
            if code:
                return code
            if args.probe:
                code = probe_narb(args.cache, args.sample, args.pause)
                if code:
                    return code
        if args.narb_all:
            code = narb_all(args.cache, args.pause, args.limit)
            if code:
                return code
        if args.build:
            return build(args.cache, args.out)
        return 0
    except BurnedVillagesError as exc:
        print(f"Сожжённые деревни: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; разобранные карточки остались в кэше.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
