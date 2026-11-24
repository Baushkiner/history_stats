#!/usr/bin/env python3
"""Сбор слоёв XVIII века из Imperiia: Кирилов 1727, ревизии, дворы 1719, уезды 1766.

    python3 scripts/harvest_imperiia_xviii.py --check    # сверка двенадцати сервисов, разбор
    python3 scripts/harvest_imperiia_xviii.py --build    # слои в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) читает карточки
двенадцати сервисов (владелец, доступ), их поля и число объектов, сверяет с
записанным в `sources/imperiia_xviii.py`, выгружает объекты в
`data/raw/imperiia/` и показывает разбор. Шесть из них — вторая серия слоёв
1727 года (нумерация `GorID`: сводный «Guberniia (as town clusters)» и
отдельные слои служителей, военных, заводов, монастырей, кафедр); из неё в
слой Кирилова добавляются города, которых нет в основном слое, а расхождения
отдельных слоёв со сводным печатаются.

Права: автор эти слои для скачивания не выпускала; 23.11.2026 взяли только
факты, 24.11.2026 владелец проекта сообщил о согласии владельца — так и
записано в `license`.

На выходе `geojson/towns_1727_kirilov.geojson`,
`geojson/revisions_uezd_towns.geojson`, `geojson/households_1719.geojson` и
`geojson/uezd_population_1766.geojson` — все в репозиторий. Губерния 1897
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
    CLUSTER_FIELDS, CLUSTERS, GORID_LAYERS, HOUSEHOLD_FIELDS, HOUSEHOLDS, HOUSEHOLDS_1719,
    KIRILOV, KIRILOV_FIELDS, POPULATION_1766, POPULATION_1766_FIELDS, REVISION_FIELDS,
    REVISIONS, REVISIONS_UEZD, TOWNS_1727, UEZD_POPULATION_1766, check_item, check_layer,
    gorid_mismatches, gorid_records, gorid_towns, household_records, kirilov_records,
    population_1766_records, revision_records,
)

CACHE = ROOT / "data" / "raw" / "imperiia"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
SERVICES = ([(KIRILOV, KIRILOV_FIELDS)]
            + [(r.service, REVISION_FIELDS | {r.field}) for r in REVISIONS]
            + [(HOUSEHOLDS, HOUSEHOLD_FIELDS), (POPULATION_1766, POPULATION_1766_FIELDS),
               (CLUSTERS, CLUSTER_FIELDS)]
            + [(service, {"GorID", "Location", "Guberniia", field})
               for service, field in GORID_LAYERS])


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


def collect(cache: Path) -> list:
    """[(слой, записи, счёт рамки)] — по порядку слоёв."""
    revisions = []
    for revision in REVISIONS:
        revisions += revision_records(load(cache, revision.service), revision)
    kirilov = load(cache, KIRILOV)
    clusters = load(cache, CLUSTERS)
    separate = {field: load(cache, service) for service, field in GORID_LAYERS}
    extra_towns = gorid_records(gorid_towns(clusters, separate), kirilov)
    layers = [(TOWNS_1727, kirilov_records(kirilov) + extra_towns),
              (REVISIONS_UEZD, revisions),
              (HOUSEHOLDS_1719, household_records(load(cache, HOUSEHOLDS))),
              (UEZD_POPULATION_1766, population_1766_records(load(cache, POPULATION_1766)))]
    try:
        frame = Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise ImperiiaError(f"рамку взять неоткуда ({exc}): нужны границы из "
                            f"{BOUNDARIES.relative_to(ROOT)} — см. docs/HARVEST.md") from exc
    # Пометку `place_level` рамка не трогает: она ставит только `outside_bbox`.
    return [(spec, recs, frame.mark(recs)) for spec, recs in layers]


def report(layers: list, cache: Path) -> None:
    separate = {field: load(cache, service) for service, field in GORID_LAYERS}
    mismatches = gorid_mismatches(load(cache, CLUSTERS), separate)
    print(f"Вторая серия 1727 года: расхождений отдельных слоёв со сводным — "
          f"{len(mismatches)}")
    for line in mismatches[:10]:
        print(f"  {line}")
    for spec, recs, counts in layers:
        print(f"\n«{spec.title}»: {len(recs)} записей")
        for what, n in collections.Counter(r.category for r in recs).most_common():
            print(f"  {n:>4}  {what}")
        for what, n in counts.most_common():
            print(f"  {what}: {n}")
        for key in ("churches", "monasteries", "officials", "officers_soldiers", "factories",
                    "households", "yasak"):
            if recs and key in recs[0].extra:
                print(f"  всего {key}: {sum(r.extra[key] for r in recs)}")
        if spec is REVISIONS_UEZD or spec is UEZD_POPULATION_1766:
            by = collections.Counter()
            for r in recs:
                by[r.category] += r.extra["population"]
            for what, total in by.items():
                print(f"  сумма, {what}: {total:,}".replace(",", " "))
        second = sum(1 for r in recs if r.extra.get("series") == "GorID")
        if second:
            print(f"  из второй серии 1727 года (GorID): {second}")
        print(f"  повторов uid: {len(recs) - len({r.uid for r in recs})}")
        watch = [r for r in recs if r.extra["name_latin"] in ("Moskva", "Kostroma", "Penza")]
        for rec in (watch or recs)[:3]:
            print(f"    {rec.title} [{rec.region or 'вне губерний 1897 года'}]\n"
                  f"      {rec.summary}")


def check(cache: Path) -> int:
    problems = fetch(cache, Client(pause_sec=0.3))
    if problems:
        print("Сервисы Imperiia расходятся с записанным в коде — сбор остановлен:",
              file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("Сервисы на месте: владелец, доступ, поля и число объектов сходятся.")
    report(collect(cache), cache)
    print("\nРазбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    for spec, recs, counts in collect(cache):
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
