#!/usr/bin/env python3
"""Сбор почтовых станций и почтовых дворов 1820-х годов (Imperiia, ArcGIS Online).

    python3 scripts/harvest_post_stations.py --check    # сверка сервисов и разбора
    python3 scripts/harvest_post_stations.py --build    # слой в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) читает карточки двух
сервисов (владелец, открытый доступ), описание слоёв (точки, поля) и число
объектов, сверяет с записанным в `sources/imperiia.py`, выгружает объекты в
`data/raw/imperiia/` и показывает разбор. Расхождение — остановка.

Права: CC BY-NC-SA 4.0 (сайт проекта и карточка набора на Dataverse). Файл
на Dataverse закрыт гостевой книгой и не запрашивается — см. описание модуля.

На выходе `geojson/post_stations_1820.geojson` (в репозиторий) и
`jsonl/post_stations_1820.jsonl` (в `.gitignore`). Губерния 1897 года — по
полигонам `data/out/boundaries` (`harvest_admin_gis.py --build`).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl
from histctx.sources.ghcn import GhcnError
from histctx.sources.imperiia import (
    ITEM_URL, POST_STATIONS, SERVICES, Client, ImperiiaError, check_item, check_layer, records,
)

CACHE = ROOT / "data" / "raw" / "imperiia"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"


def load_frame() -> Frame:
    try:
        return Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise ImperiiaError(
            f"рамку взять неоткуда ({exc}). Нужны {BOUNDARIES.relative_to(ROOT)}/"
            "provinces_1897.geojson и state_borders.geojson — см. docs/HARVEST.md") from exc


def fetch(cache: Path, client: Client) -> list[str]:
    """Сверяет сервисы и кладёт объекты в кэш. Возвращает расхождения."""
    problems = []
    for service in SERVICES:
        problems += [f"{service.name}: {p}" for p in
                     check_item(client.get_url(ITEM_URL.format(item=service.item)))]
        problems += check_layer(client.layer_info(service), service, client.count(service))
    if problems:
        return problems
    cache.mkdir(parents=True, exist_ok=True)
    for service in SERVICES:
        features = client.query_all(service)
        if len(features) != service.count:
            return [f"{service.name}: выгружено {len(features)}, в коде {service.count}"]
        (cache / f"{service.name}.json").write_text(
            json.dumps(features, ensure_ascii=False), encoding="utf-8")
    return []


def collect(cache: Path) -> tuple[list, collections.Counter]:
    recs = []
    for service in SERVICES:
        path = cache / f"{service.name}.json"
        if not path.exists():
            raise ImperiiaError(f"нет {path.relative_to(ROOT)}: сначала --check")
        recs += records(json.loads(path.read_text(encoding="utf-8")), service)
    counts = load_frame().mark(recs)
    return recs, counts


def report(recs: list, counts: collections.Counter) -> None:
    print(f"Записей: {len(recs)}")
    for what, n in collections.Counter(r.category for r in recs).most_common():
        print(f"  {n:>5}  {what}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    print("  тип селения:")
    kinds = collections.Counter(
        r.extra.get("settlement_type") or f"код {r.extra.get('settlement_code')}" for r in recs)
    for what, n in kinds.most_common():
        print(f"    {n:>5}  {what}")
    print("  губерний 1897 года со станциями: "
          f"{len({r.region for r in recs if r.region})}")
    print("  образцы:")
    for rec in recs[::397][:11]:
        print(f"    {rec.title} [{rec.region or 'вне губерний 1897 года'}]")


def check(cache: Path) -> int:
    problems = fetch(cache, Client())
    if problems:
        print("Сервисы Imperiia расходятся с записанным в коде — сбор остановлен:",
              file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("Сервисы на месте: владелец, доступ, поля и число объектов сходятся.")
    recs, counts = collect(cache)
    report(recs, counts)
    print("\nРазбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    recs, counts = collect(cache)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = POST_STATIONS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=POST_STATIONS.title, hoist_shared=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{POST_STATIONS.title}»: {len(recs)} записей, на карте {n}")
    for what, count in counts.most_common():
        print(f"  {what}: {count}")
    for path in (geo, jsonl):
        print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить сервисы, выгрузить объекты, показать разбор")
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
    except ImperiiaError as exc:
        print(f"Imperiia: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
