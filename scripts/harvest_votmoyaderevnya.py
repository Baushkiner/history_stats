#!/usr/bin/env python3
"""Сбор слоя малочисленных селений России с сайта «Вот моя деревня».

    python3 scripts/harvest_votmoyaderevnya.py --check            # проба: один субъект
    python3 scripts/harvest_votmoyaderevnya.py --fetch            # полный обход API
    python3 scripts/harvest_votmoyaderevnya.py --fetch --gaps     # и номера вне разделов
    python3 scripts/harvest_votmoyaderevnya.py --build            # записи в data/out

Данные отдаёт JSON-API сайта (`/api/categories.php`,
`/api/category-settlements.php`, `/api/settlement-details-v2.php` — устройство
в `histctx.sources.votmoyaderevnya`). Обход: всё дерево разделов, селения тех
разделов, где они есть, и карточка каждого селения — ради точки, пути
разделов и численности. Одно соединение, пауза в секунду, отступ на 429/5xx;
каждый ответ ложится в `data/raw/votmoyaderevnya/`, и прерванный обход
продолжается с места повторным `--fetch`. `--refresh` скачивает заново.

`--check` проходит дерево одного субъекта (по умолчанию Тульская область,
id 4 — там селений больше всего) и печатает отчёт, ничего не записывая.
`--build` строит слой из кэша; чего в кэше нет, докачивает тем же обходом,
так что после полного `--fetch` в сеть он не ходит.

Права. «© 2025 … Все права защищены»; собрано с согласия владельцев,
полученного владельцем проекта (сообщено 24.11.2026). Тексты рубрик и снимки
в слой не идут.

На выходе:

* `geojson/settlements_vmd.geojson` — селения с точкой;
* `settlements_vmd.json` — селения без точки, `confidence = no_coords`;
* `jsonl/settlements_vmd.jsonl` — слой целиком (в `.gitignore`).

Губерния 1897 года по точке ставится в `extra.province_1897`, если в
репозитории лежат `data/out/boundaries/provinces_1897.geojson` и
`state_borders.geojson`.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.votmoyaderevnya import (
    SETTLEMENTS_VMD, Client, VmdError, records, walk_categories,
)

CACHE = ROOT / "data" / "raw" / "votmoyaderevnya"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
# Сколько номеров карточек перебрать за наибольшим найденным (`--gaps`).
GAP_TAIL = 50


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def crawl(client: Client, root: int | None = None,
          gaps: bool = False) -> tuple[list, list[dict]]:
    """Дерево разделов (от `root` или целиком), списки селений и карточки.

    `gaps` — сверх дерева перебрать номера карточек от 1 до наибольшего
    найденного (плюс запас): селение, отвязанное от раздела, в списки не
    попадает, а карточка у него может быть. Отсутствующий номер отвечает
    `success: false`, и этот ответ тоже ложится в кэш.
    """
    nodes = list(walk_categories(client, root))
    log(f"  разделов: {len(nodes)}, с селениями: {sum(1 for n in nodes if n.settlements)}; "
        f"запросов {client.requests}, из кэша {client.hits}")
    ids: dict[int, int] = {}
    for node in nodes:
        if node.settlements <= 0:
            continue
        for s in client.settlements(node.id):
            ids.setdefault(int(s["id"]), node.id)
    log(f"  селений в списках: {len(ids)}; запросов {client.requests}, из кэша {client.hits}")
    cards = []
    for i, sid in enumerate(sorted(ids), 1):
        card = client.details(sid)
        if card is not None:
            cards.append(card)
        if i % 100 == 0:
            log(f"  карточек {i}/{len(ids)}; запросов {client.requests}")
    if gaps and ids:
        extra = 0
        for sid in range(1, max(ids) + GAP_TAIL + 1):
            if sid in ids:
                continue
            card = client.details(sid)
            if card is not None:
                cards.append(card)
                extra += 1
        log(f"  перебор номеров до {max(ids) + GAP_TAIL}: карточек вне списков {extra}")
    elif root is None:
        # Карточки вне списков, найденные прежним `--gaps`, берутся из кэша.
        for path in sorted((client.cache / "details").glob("*.json")):
            if path.stem.isdigit() and int(path.stem) not in ids:
                card = client.details(int(path.stem))
                if card is not None:
                    cards.append(card)
    return nodes, cards


def mark_provinces(recs: list) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    if not (BOUNDARIES / "provinces_1897.geojson").exists():
        log("  контуров губерний 1897 года нет — extra.province_1897 не ставится")
        return counts
    from histctx.frame import Frame
    frame = Frame.load(BOUNDARIES)
    for r in recs:
        if not r.has_point:
            continue
        _inside, province, _ = frame.place(r.lat, r.lon)
        if province:
            r.extra["province_1897"] = province
            counts["в губерниях 1897 года"] += 1
        else:
            counts["вне губерний 1897 года"] += 1
    return counts


def report(nodes: list, recs: list, provinces: collections.Counter) -> None:
    declared = sum(n.settlements for n in nodes)
    print(f"Разделов: {len(nodes)}; селений по счётчикам разделов: {declared}; "
          f"карточек разобрано: {len(recs)}")
    by_depth = collections.Counter(len(n.path) for n in nodes)
    print("  разделы по глубине: " + ", ".join(f"{d}: {c}" for d, c in sorted(by_depth.items())))
    print(f"  с точкой: {sum(r.has_point for r in recs)}; без точки: "
          f"{sum(not r.has_point for r in recs)}")
    dated = [r for r in recs if "date_source" not in r.extra]
    print(f"  с годом основания: {len(dated)}")
    print(f"  с прежними названиями: {sum(1 for r in recs if r.extra.get('former_names'))}")
    print(f"  недействующих: {sum(1 for r in recs if r.extra['status'] == 'недействующий')}")
    print(f"  с численностью по годам: {sum(1 for r in recs if r.extra.get('population'))}")
    print(f"  с заполненными рубриками: {sum(1 for r in recs if r.extra.get('rubrics'))}")
    for what, n in provinces.most_common():
        print(f"  {what}: {n}")
    print("  субъекты:")
    for name, n in collections.Counter(r.region for r in recs).most_common(15):
        print(f"    {n:>6}  {name}")
    print("  типы:")
    for name, n in collections.Counter(r.category for r in recs).most_common(12):
        print(f"    {n:>6}  {name}")
    print("  примеры с годом:")
    for r in dated[:8]:
        print(f"    {r.year_from}  {r.title}  [{r.place_text}]")


def build(recs: list, out_dir: Path) -> int:
    slug = SETTLEMENTS_VMD.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=SETTLEMENTS_VMD.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{SETTLEMENTS_VMD.title}: без точки",
                           hoist_shared=True)
    elif json_path.exists():
        json_path.unlink()
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{SETTLEMENTS_VMD.title}»: {len(recs)} записей, на карте {n}, "
          f"без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} КБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="проба на одном субъекте, отчёт без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="полный обход API в кэш")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--region", type=int, default=4,
                    help="id раздела для --check (по умолчанию 4, Тульская область)")
    ap.add_argument("--gaps", action="store_true",
                    help="перебрать номера карточек между найденными (селения вне разделов)")
    ap.add_argument("--refresh", action="store_true", help="скачать ответы заново")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    client = Client(args.cache, refresh=args.refresh, log=log)
    try:
        if args.check and not (args.fetch or args.build):
            nodes, cards = crawl(client, args.region)
        else:
            nodes, cards = crawl(client, gaps=args.gaps)
    except VmdError as exc:
        print(f"votmoyaderevnya: {exc}", file=sys.stderr)
        print("Обход прерван; повторный запуск продолжит из кэша.", file=sys.stderr)
        return 1
    recs = records(cards)
    if not recs:
        print("Ни одной карточки не разобрано: проверьте ответы API.", file=sys.stderr)
        return 1
    provinces = mark_provinces(recs)
    report(nodes, recs, provinces)
    if args.build:
        return build(recs, args.out)
    if args.check:
        print("\nAPI отвечает, разбор работает — можно запускать --fetch и --build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
