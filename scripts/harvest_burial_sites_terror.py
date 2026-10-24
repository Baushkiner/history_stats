#!/usr/bin/env python3
"""Сбор слоя мест захоронений из «Некрополя террора и ГУЛАГа» (en.mapofmemory.org).

    python3 scripts/harvest_burial_sites_terror.py --probe   # robots.txt, главная, три карточки
    python3 scripts/harvest_burial_sites_terror.py --fetch   # всё в кэш, с продолжением
    python3 scripts/harvest_burial_sites_terror.py --build   # докачать недостающее и собрать

Проверочный первый запуск обязателен, как у остальных сборщиков. `--probe`
читает `robots.txt` (закрытые пути не обходятся, пауза — не короче
`Crawl-delay`), забирает главную, сверяет число точек с замером 24.10.2026
(411) и разбирает три карточки: поля, на которых держится разбор, должны
быть на месте. Расхождение — остановка, а не подгонка. Файлы `--probe`
не пишет.

`--fetch` складывает главную и 411 карточек в `data/raw/mapofmemory/`
(в `.gitignore`). При паузе в 10 секунд это около 70 минут; оборванный обход
продолжается тем же вызовом — карточки, уже лежащие в кэше, повторно не
запрашиваются. `--refresh` перечитывает главную (карточки — нет).

`--build` разбирает кэш (недостающие карточки докачивает, если не задан
`--offline`), помечает точки, рядом с которыми в радиусе `--near-km` есть
точка слоя `repressions` или `gulag_camps`, и пишет:

* `geojson/burial_sites_terror.geojson` — в репозиторий;
* `jsonl/burial_sites_terror.jsonl` — в `.gitignore`, как у остальных слоёв.

Права. Условий использования сайт не публикует — права не выяснены. Берутся
факты — координата, датировка, тип, адрес — и ссылка на карточку; справки,
подписи к снимкам и сами снимки остаются на сайте, имён людей в слое нет.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl
from histctx.sources.ghcn import PROVINCES_PATH, GhcnError, Provinces
from histctx.sources.mapofmemory import (
    BURIAL_SITES_TERROR, CARD_URL, EXPECTED_MARKERS, INDEX_URL, Client, MapOfMemoryError,
    allowed, card_cache_name, card_to_record, check_card, check_cards, mark_neighbours, parse_card,
    parse_markers,
)

CACHE = ROOT / "data" / "raw" / "mapofmemory"
OUT = ROOT / "data" / "out"
INDEX_CACHE = "index.html"

# Радиус, в котором точка другого слоя считается «тем же местом» — решение
# по данным, обоснование в docs/HARVEST.md.
NEAR_KM = 1.0
NEIGHBOUR_LAYERS = ("repressions", "gulag_camps")


def open_client(cache: Path, pause: float):
    client = Client(cache_dir=cache, pause=pause)
    robots = client.robots()
    for url in (INDEX_URL, CARD_URL.format(code="59-01")):
        if not allowed(robots, url):
            raise MapOfMemoryError(f"robots.txt закрывает {url}: сбор не идёт")
    print(f"robots.txt: главная и карточки открыты, пауза {client.pause:g} с")
    return client, robots


def check_markers(markers: list) -> None:
    codes = [m.code for m in markers]
    dupes = [c for c, n in collections.Counter(codes).items() if n > 1]
    print(f"Точек на главной: {len(markers)} (при проверке 24.10.2026 — {EXPECTED_MARKERS}); "
          f"различных кодов: {len(set(codes))}")
    if dupes:
        print(f"  повторяются коды: {dupes[:10]}")
    if len(markers) != EXPECTED_MARKERS:
        raise MapOfMemoryError(
            f"точек {len(markers)}, а не {EXPECTED_MARKERS}: состав карты изменился — "
            "посмотрите, что добавилось, и поправьте EXPECTED_MARKERS"
        )
    lats = [m.lat for m in markers]
    lons = [m.lon for m in markers]
    print(f"  широта {min(lats):.2f}–{max(lats):.2f}, долгота {min(lons):.2f}–{max(lons):.2f}")


def probe(cache: Path, pause: float, sample: int) -> int:
    client, robots = open_client(cache, pause)
    markers = parse_markers(client.get(INDEX_URL))
    check_markers(markers)
    step = max(1, len(markers) // sample)
    for marker in markers[::step][:sample]:
        url = CARD_URL.format(code=marker.code)
        if not allowed(robots, url):
            print(f"  {marker.code}: закрыт robots.txt — пропущен")
            continue
        card = parse_card(client.get(url))
        check_card(card, marker.code)
        rec = card_to_record(marker, card)
        print(f"  {marker.code}: {rec.title[:60]}")
        print(f"      дата {rec.period_raw!r} → {rec.year_from}–{rec.year_to} "
              f"({rec.date_precision}); тип: {rec.category}")
    print("\nПоля на месте, разбор работает — можно запускать --fetch и --build.")
    return 0


def fetch(cache: Path, pause: float, *, refresh: bool, limit=None) -> tuple[list, dict]:
    """Главная и карточки в кэш; уже скачанное не запрашивается заново."""
    client, robots = open_client(cache, pause)
    markers = parse_markers(client.cached(INDEX_CACHE, INDEX_URL, refresh=refresh))
    check_markers(markers)
    todo = [m for m in markers if not (cache / card_cache_name(m.code)).exists()]
    print(f"В кэше карточек: {len(markers) - len(todo)}, докачать: {len(todo)}")
    for i, marker in enumerate(todo[:limit] if limit else todo, 1):
        url = CARD_URL.format(code=marker.code)
        if not allowed(robots, url):
            print(f"  {marker.code}: закрыт robots.txt — пропущен")
            continue
        client.cached(card_cache_name(marker.code), url)
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    return markers, load_cards(cache, markers)


def load_cards(cache: Path, markers: list) -> dict:
    cards = {}
    for marker in markers:
        path = cache / card_cache_name(marker.code)
        if path.exists():
            card = parse_card(path.read_text(encoding="utf-8"))
            check_card(card, marker.code)
            cards[marker.code] = card
    for name, codes in check_cards(cards).items():
        print(f"  поля {name!r} нет у {len(codes)} карточек: {', '.join(codes[:10])} — "
              "записи остаются с пустым полем")
    return cards


def load_neighbours(out_dir: Path) -> dict:
    others = {}
    for layer in NEIGHBOUR_LAYERS:
        path = out_dir / "geojson" / f"{layer}.geojson"
        if not path.exists():
            print(f"  нет {path}: сверка с {layer} пропущена")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        others[layer] = [
            (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0],
             f.get("id"), (f.get("properties") or {}).get("title"))
            for f in payload.get("features", []) if (f.get("geometry") or {}).get("type") == "Point"
        ]
    return others


def build(cache: Path, out_dir: Path, pause: float, *, offline: bool, refresh: bool,
          near_km: float) -> int:
    if offline:
        index = cache / INDEX_CACHE
        if not index.exists():
            raise MapOfMemoryError(f"нет {index}: сначала --fetch")
        markers = parse_markers(index.read_text(encoding="utf-8"))
        check_markers(markers)
        cards = load_cards(cache, markers)
    else:
        markers, cards = fetch(cache, pause, refresh=refresh)
    missing = [m.code for m in markers if m.code not in cards]
    if missing:
        print(f"Карточек нет в кэше: {len(missing)} ({', '.join(missing[:10])}…) — "
              "слой не собирается неполным; запустите --fetch ещё раз", file=sys.stderr)
        return 1

    try:
        provinces = Provinces.load(ROOT / PROVINCES_PATH)
    except GhcnError as exc:
        print(f"  губернии 1897 года не подставлены: {exc}")
        provinces = None
    records = [card_to_record(m, cards[m.code], provinces=provinces) for m in markers]
    counts = mark_neighbours(records, load_neighbours(out_dir), radius_km=near_km)
    report(records, counts, near_km)

    n = write_geojson(records, out_dir / "geojson" / f"{BURIAL_SITES_TERROR.slug}.geojson",
                      layer_title=BURIAL_SITES_TERROR.title)
    write_jsonl(records, out_dir / "jsonl" / f"{BURIAL_SITES_TERROR.slug}.jsonl")
    print(f"\nСобрано {len(records)} записей, на карту пойдут {n}.")
    return 0


def report(records: list, counts: dict, near_km: float) -> None:
    dated = [r for r in records if r.has_time]
    print(f"\nЗаписей: {len(records)}; с датировкой: {len(dated)}; "
          f"с губернией 1897 года: {sum(1 for r in records if r.region)}")
    if dated:
        print(f"  годы: {min(r.year_from for r in dated)}–{max(r.year_to for r in dated)}")
    print("  точность датировки:",
          dict(collections.Counter(r.date_precision for r in records).most_common()))
    print("  достоверность:",
          dict(collections.Counter(r.confidence for r in records).most_common()))
    undated = [r for r in records if not r.has_time]
    for rec in undated[:20]:
        print(f"    без даты: {rec.source_id} {rec.period_raw!r}")
    print("  по типам:")
    for kind, n in collections.Counter(r.category for r in records).most_common():
        print(f"    {n:>4}  {kind}")
    for layer, n in counts.items():
        print(f"  рядом (до {near_km:g} км) точка слоя {layer}: {n}")
    if len(counts) > 1:
        both = sum(1 for r in records if len((r.extra or {}).get("near", {})) == len(counts))
        print(f"  рядом с обоими слоями: {both}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", "--check", dest="probe", action="store_true",
                    help="robots.txt, главная и три карточки — без записи файлов")
    ap.add_argument("--fetch", action="store_true", help="главная и карточки в кэш")
    ap.add_argument("--build", action="store_true", help="собрать слой в data/out")
    ap.add_argument("--offline", action="store_true", help="собирать только из кэша")
    ap.add_argument("--refresh", action="store_true", help="перечитать главную страницу")
    ap.add_argument("--limit", type=int, default=None, help="--fetch: не больше N карточек")
    ap.add_argument("--sample", type=int, default=3, help="--probe: сколько карточек разобрать")
    ap.add_argument("--pause", type=float, default=10.0,
                    help="пауза между запросами, с (не короче Crawl-delay)")
    ap.add_argument("--near-km", type=float, default=NEAR_KM)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not (args.probe or args.fetch or args.build):
        ap.error("укажите --probe, --fetch или --build")
    try:
        if args.probe:
            return probe(args.cache, args.pause, args.sample)
        if args.fetch and not args.build:
            markers, cards = fetch(args.cache, args.pause, refresh=args.refresh, limit=args.limit)
            print(f"Разобрано карточек из кэша: {len(cards)} из {len(markers)}")
            return 0
        return build(args.cache, args.out, args.pause, offline=args.offline,
                     refresh=args.refresh, near_km=args.near_km)
    except MapOfMemoryError as exc:
        print(f"Некрополь: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; уже скачанное лежит в кэше, повторный вызов продолжит.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
