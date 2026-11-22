#!/usr/bin/env python3
"""Сбор слоя еврейских кладбищ из обследования ESJF (esjf-cemeteries.org).

    python3 scripts/harvest_jewish_cemeteries.py --check   # robots.txt, карты сайта, пять карточек
    python3 scripts/harvest_jewish_cemeteries.py --fetch   # все карточки в кэш, с продолжением
    python3 scripts/harvest_jewish_cemeteries.py --build   # собрать слой из кэша

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
читает `robots.txt` (`/wp-json/` и адреса с параметрами закрыты — сборщик их
не запрашивает), забирает пять карт сайта, сверяет число карточек с замером
22.11.2026 и разбирает пять карточек из разных концов списка: подписи полей,
на которых держится разбор, должны быть на месте. Файлы слоя `--check` не
пишет, карты сайта и карточки кладёт в кэш.

`--fetch` складывает карточки в `data/raw/jewish_cemeteries/cards/` (в
`.gitignore`); оборванный обход продолжается тем же вызовом, `--limit`
делит его на заходы, `--refresh` перечитывает карты сайта (карточки — нет).

**Полный обход ждёт договорённости с ESJF** (info@esjf-cemeteries.org). Перед
сайтом стоит защита хостинга: на частые запросы вместо карточки приходит
страница проверки «Захищена сторінка» с кодом 429. Замер 22.11.2026: при
запросе раз в три секунды — отказ через раз, после серии отказов при паузе в
шесть секунд проходят четыре карточки за пять минут. Страницу проверки
сборщик не решает и подпись не меняет; после пяти отказов подряд он
останавливается (`ProtectionError`), а не ждёт часами. `--build` собирает слой
только из полного кэша; `--build --partial` — из того, что успело лечь в кэш
(22.11.2026 — 40 карточек из 4 276: повторный обход с паузой в секунду
добавлял около карточки в минуту и был остановлен).

`--build` разбирает кэш (`--offline` — без докачки), ставит губернию 1897 года
и пометку `outside_bbox` по полигонам `data/out/boundaries` и пишет:

* `geojson/jewish_cemeteries.geojson` — в репозиторий;
* `jewish_cemeteries.json` — карточки без координаты, тоже в репозиторий;
* `jsonl/jewish_cemeteries.jsonl` — в `.gitignore`.

Права. «Copyright — All Rights Reserved — ESJF», лицензии нет: берутся факты —
точка, место, годы надгробий, состояние, число надгробий — и ссылка на
карточку; очерки, описания и снимки остаются на сайте.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.jewish_cemeteries import (
    EXPECTED_CARDS, JEWISH_CEMETERIES, PAUSE, SITEMAPS, Client, EsjfError, RussianNames,
    card_cache_name, card_slug, check_card, parse_card, parse_sitemap, records, url_allowed,
)

CACHE = ROOT / "data" / "raw" / "jewish_cemeteries"
OUT = ROOT / "data" / "out"
BOUNDARIES = OUT / "boundaries"
NAMES = OUT / "name_variants.json"


def sitemap_name(url: str) -> str:
    return "sitemaps/" + url.rsplit("/", 1)[-1]


def open_client(cache: Path, pause: float) -> tuple[Client, object]:
    client = Client(cache_dir=cache, pause=pause)
    robots = client.robots()
    for url in (*SITEMAPS, SITEMAPS[0].rsplit("/", 1)[0] + "/survey/fastiv-jewish-cemetery/"):
        if not url_allowed(url, robots):
            raise EsjfError(f"robots.txt закрывает {url}: сбор не идёт")
    if url_allowed(SITEMAPS[0].rsplit("/", 1)[0] + "/wp-json/wp/v2/survey", robots):
        raise EsjfError("robots.txt больше не закрывает /wp-json/ — сверьте правила руками")
    print(f"robots.txt: карты сайта и карточки открыты, /wp-json/ и адреса с параметрами "
          f"закрыты; пауза от {client.pause:g} с")
    return client, robots


def load_index(client: Client, *, refresh: bool) -> list[tuple[str, str]]:
    entries = []
    for url in SITEMAPS:
        xml = client.cached(sitemap_name(url), url, refresh=refresh)
        part = parse_sitemap(xml)
        print(f"  {url.rsplit('/', 1)[-1]}: {len(part)} карточек")
        entries.extend(part)
    seen, out = set(), []
    for url, lastmod in entries:
        if url not in seen:
            seen.add(url)
            out.append((url, lastmod))
    print(f"Карточек в картах сайта: {len(out)} (при сборе 22.11.2026 — {EXPECTED_CARDS})")
    if not out:
        raise EsjfError("в картах сайта нет ни одной карточки: разметку поменяли")
    return out


def check(cache: Path, pause: float, sample: int) -> int:
    client, robots = open_client(cache, pause)
    index = load_index(client, refresh=True)
    step = max(1, len(index) // sample)
    names = RussianNames.load(NAMES) if NAMES.exists() else None
    for url, lastmod in index[::step][:sample]:
        slug = card_slug(url)
        if not url_allowed(url, robots):
            print(f"  {slug}: закрыт robots.txt — пропущен")
            continue
        card = parse_card(client.cached(card_cache_name(slug), url))
        check_card(card, slug)
        rec = records([(url, card, lastmod)], names=names)[0]
        print(f"  {slug}: {rec.title}; {rec.lat}, {rec.lon}")
        print(f"      {rec.period_raw!r} → {rec.year_from}–{rec.year_to} ({rec.date_precision}); "
              f"{rec.category}")
    print(f"\nЗапросов: {client.requests}, отказов 429: {client.refusals}, пауза теперь "
          f"{client.pause:g} с. Поля на месте — можно запускать --fetch и --build.")
    return 0


def fetch(cache: Path, pause: float, *, refresh: bool, limit=None) -> list[tuple[str, str]]:
    client, robots = open_client(cache, pause)
    index = load_index(client, refresh=refresh)
    todo = [(u, m) for u, m in index if not (cache / card_cache_name(card_slug(u))).exists()]
    print(f"В кэше карточек: {len(index) - len(todo)}, докачать: {len(todo)}", flush=True)
    for i, (url, _) in enumerate(todo[:limit] if limit else todo, 1):
        if not url_allowed(url, robots):
            print(f"  {url}: закрыт robots.txt — пропущен")
            continue
        client.cached(card_cache_name(card_slug(url)), url)
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}; отказов 429: {client.refusals}, пауза {client.pause:g} с",
                  flush=True)
    return index


def load_cards(cache: Path, index: list[tuple[str, str]]) -> tuple[list, list[str]]:
    cards, missing = [], []
    for url, lastmod in index:
        slug = card_slug(url)
        path = cache / card_cache_name(slug)
        if not path.exists():
            missing.append(slug)
            continue
        card = parse_card(path.read_text(encoding="utf-8"))
        check_card(card, slug)
        cards.append((url, card, lastmod))
    return cards, missing


def offline_index(cache: Path) -> list[tuple[str, str]]:
    entries, seen = [], set()
    for url in SITEMAPS:
        path = cache / sitemap_name(url)
        if not path.exists():
            raise EsjfError(f"нет {path}: сначала --check или --fetch")
        for u, m in parse_sitemap(path.read_text(encoding="utf-8")):
            if u not in seen:
                seen.add(u)
                entries.append((u, m))
    return entries


def build(cache: Path, out_dir: Path, pause: float, *, offline: bool, refresh: bool,
          partial: bool = False) -> int:
    index = offline_index(cache) if offline else fetch(cache, pause, refresh=refresh)
    cards, missing = load_cards(cache, index)
    if missing and not partial:
        print(f"Карточек нет в кэше: {len(missing)} ({', '.join(missing[:5])}…) — слой не "
              "собирается неполным; запустите --fetch ещё раз или соберите --partial",
              file=sys.stderr)
        return 1
    if missing:
        # Защита сайта остановила обход: слой собирается из того, что успело лечь
        # в кэш, и печатает, сколько карточек осталось за ним.
        print(f"Неполный слой (--partial): карточек в кэше {len(cards)} из {len(index)}, "
              f"не хватает {len(missing)}")
    names = RussianNames.load(NAMES) if NAMES.exists() else None
    recs = records(cards, names=names)
    frame = Frame.load(BOUNDARIES)
    marks = frame.mark(recs)
    report(recs, marks)

    slug = JEWISH_CEMETERIES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=JEWISH_CEMETERIES.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{JEWISH_CEMETERIES.title}: без точки",
                           hoist_shared=True)
    write_jsonl(recs, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"\n«{JEWISH_CEMETERIES.title}»: {len(recs)} записей, на карте {n}, без точки "
          f"{len(off_map)}")
    for path in (geo, json_path if off_map else None):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def report(recs: list, marks: dict) -> None:
    print(f"\nЗаписей: {len(recs)}; с точкой: {sum(1 for r in recs if r.has_point)}; "
          f"с датировкой: {sum(1 for r in recs if r.has_time)}")
    print("  рамка:", dict(marks))
    print("  точность дат:", dict(collections.Counter(r.date_precision for r in recs)))
    print("  страны:", dict(collections.Counter(r.extra.get("country") for r in recs)
                            .most_common()))
    print("  состояние:")
    for name, count in collections.Counter(r.category for r in recs).most_common(12):
        print(f"    {count:>5}  {name}")
    dated = [r for r in recs if r.has_time]
    if dated:
        print(f"  годы надгробий: {min(r.year_from for r in dated)}–"
              f"{max(r.year_to for r in dated)}")
    ru = sum(1 for r in recs if r.extra.get("settlement_en")
             and not r.title.endswith(r.extra["settlement_en"]))
    print(f"  подпись по-русски из указателя написаний: {ru}")
    gubernia = collections.Counter(r.region for r in recs if r.region)
    print(f"  в губерниях 1897 года: {sum(gubernia.values())}; чаще всего: "
          f"{gubernia.most_common(6)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="robots.txt, карты сайта и пять карточек — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="все карточки в кэш")
    ap.add_argument("--build", action="store_true", help="собрать слой в data/out")
    ap.add_argument("--offline", action="store_true", help="собирать только из кэша")
    ap.add_argument("--partial", action="store_true",
                    help="--build: собрать из того, что есть в кэше, если обход остановлен")
    ap.add_argument("--refresh", action="store_true", help="перечитать карты сайта")
    ap.add_argument("--limit", type=int, default=None, help="--fetch: не больше N карточек")
    ap.add_argument("--sample", type=int, default=5, help="--check: сколько карточек")
    ap.add_argument("--pause", type=float, default=PAUSE, help="начальная пауза, с")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check:
            return check(args.cache, args.pause, args.sample)
        if args.fetch and not args.build:
            index = fetch(args.cache, args.pause, refresh=args.refresh, limit=args.limit)
            cards, missing = load_cards(args.cache, index)
            print(f"Разобрано карточек из кэша: {len(cards)}; не хватает: {len(missing)}")
            return 0
        return build(args.cache, args.out, args.pause, offline=args.offline,
                     refresh=args.refresh, partial=args.partial)
    except EsjfError as exc:
        print(f"ESJF: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; уже скачанное лежит в кэше, повторный вызов продолжит.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
