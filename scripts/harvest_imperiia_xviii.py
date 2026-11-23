#!/usr/bin/env python3
"""Сбор двух слоёв XVIII века из Imperiia: города 1727 года по Кирилову и уезды по ревизиям.

    python3 scripts/harvest_imperiia_xviii.py --check    # сверка четырёх сервисов, разбор
    python3 scripts/harvest_imperiia_xviii.py --build    # слои в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) читает карточки
четырёх сервисов (владелец, доступ, нет ли в описании оговорки о доступе по
запросу), их поля и число объектов, сверяет с записанным в
`sources/imperiia_xviii.py`, выгружает объекты в `data/raw/imperiia/` и
показывает разбор.

Права: автор эти слои для скачивания не выпускала — берутся только факты
(место, год, числа) со ссылкой на слой; решение владельца проекта, 23.11.2026.

На выходе `geojson/towns_1727_kirilov.geojson` и
`geojson/revisions_uezd_towns.geojson` — оба в репозиторий. Губерния 1897
года — по полигонам `data/out/boundaries`.
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
from histctx.sources.imperiia import ITEM_URL, Client, ImperiiaError
from histctx.sources.imperiia_xviii import (
    KIRILOV, KIRILOV_FIELDS, REVISION_FIELDS, REVISIONS, REVISIONS_UEZD, TOWNS_1727,
    check_item, check_layer, kirilov_records, revision_records,
)

CACHE = ROOT / "data" / "raw" / "imperiia"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
SERVICES = [(KIRILOV, KIRILOV_FIELDS)] + [(r.service, REVISION_FIELDS | {r.field})
                                          for r in REVISIONS]


def fetch(cache: Path, client: Client) -> list[str]:
    problems = []
    for service, required in SERVICES:
        problems += check_item(client.get_url(ITEM_URL.format(item=service.item)), service)
        problems += check_layer(client.layer_info(service), service, required,
                                client.count(service))
    if problems:
        return problems
    cache.mkdir(parents=True, exist_ok=True)
    for service, _ in SERVICES:
        features = client.query_all(service)
        if len(features) != service.count:
            return [f"{service.name}: выгружено {len(features)}, в коде {service.count}"]
        (cache / f"{service.name}.json").write_text(
            json.dumps(features, ensure_ascii=False), encoding="utf-8")
    return []


def load(cache: Path, service) -> list:
    path = cache / f"{service.name}.json"
    if not path.exists():
        raise ImperiiaError(f"нет {path.relative_to(ROOT)}: сначала --check")
    return json.loads(path.read_text(encoding="utf-8"))


def collect(cache: Path):
    towns = kirilov_records(load(cache, KIRILOV))
    revisions = []
    for revision in REVISIONS:
        revisions += revision_records(load(cache, revision.service), revision)
    try:
        frame = Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise ImperiiaError(f"рамку взять неоткуда ({exc}): нужны границы из "
                            f"{BOUNDARIES.relative_to(ROOT)} — см. docs/HARVEST.md") from exc
    # Пометку `place_level` у ревизий рамка не трогает: она ставит только `outside_bbox`.
    return towns, frame.mark(towns), revisions, frame.mark(revisions)


def report(towns, town_counts, revisions, revision_counts) -> None:
    print(f"«{TOWNS_1727.title}»: {len(towns)} записей")
    for what, n in collections.Counter(r.category for r in towns).most_common():
        print(f"  {n:>4}  {what}")
    for what, n in town_counts.most_common():
        print(f"  {what}: {n}")
    for key in ("churches", "monasteries", "officials", "officers_soldiers", "factories"):
        print(f"  всего {key}: {sum(r.extra[key] for r in towns)}")
    print(f"  архиерейских кафедр: {sum(1 for r in towns if r.extra['bishopric'])}")
    for rec in sorted(towns, key=lambda r: -r.extra["churches"])[:3] + towns[:2]:
        print(f"    {rec.title} [{rec.region or 'вне губерний 1897 года'}]\n      {rec.summary}")
    print(f"\n«{REVISIONS_UEZD.title}»: {len(revisions)} записей")
    for what, n in collections.Counter(r.category for r in revisions).most_common():
        total = sum(r.extra["population"] for r in revisions if r.category == what)
        print(f"  {n:>4}  {what}: всего {total:,}".replace(",", " "))
    for what, n in revision_counts.most_common():
        print(f"  {what}: {n}")
    for rec in [r for r in revisions if r.extra["name_latin"] in ("Moskva", "Kazan")]:
        print(f"    {rec.title}")
    print(f"      {revisions[-1].summary}")


def check(cache: Path) -> int:
    problems = fetch(cache, Client(pause_sec=0.3))
    if problems:
        print("Сервисы Imperiia расходятся с записанным в коде — сбор остановлен:",
              file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("Сервисы на месте: владелец, доступ, поля и число объектов сходятся.")
    report(*collect(cache))
    print("\nРазбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    towns, town_counts, revisions, revision_counts = collect(cache)
    for spec, recs, counts in ((TOWNS_1727, towns, town_counts),
                               (REVISIONS_UEZD, revisions, revision_counts)):
        if not recs:
            print(f"{spec.slug}: ничего не собрано.", file=sys.stderr)
            return 1
        geo = out_dir / "geojson" / f"{spec.slug}.geojson"
        n = write_geojson(recs, geo, layer_title=spec.title, hoist_shared=True)
        write_jsonl(recs, out_dir / "jsonl" / f"{spec.slug}.jsonl")
        print(f"«{spec.title}»: {len(recs)} записей, на карте {n}")
        for what, count in counts.most_common():
            print(f"  {what}: {count}")
        print(f"  → {geo.relative_to(ROOT)} ({geo.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить сервисы, выгрузить объекты, показать разбор")
    ap.add_argument("--build", action="store_true", help="записать слои в data/out")
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
