#!/usr/bin/env python3
"""Сбор остальных слоёв атласа Пядышева 1820–1827 годов (Imperiia, ArcGIS Online).

    python3 scripts/harvest_atlas_1820.py --check    # сверка 35 сервисов, выгрузка, разбор
    python3 scripts/harvest_atlas_1820.py --build    # четыре слоя и три подложки в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) читает описание и
число объектов каждого сервиса, сверяет с записанным в
`sources/atlas_1820.py`, выгружает объекты в `data/raw/imperiia/` (то, что уже
лежит и сходится по числу, второй раз не качается) и показывает разбор.
Расхождение — остановка. Почтовые станции — отдельной командой,
`harvest_post_stations.py`.

Права: CC BY-NC-SA 4.0 (сайт проекта и карточка набора на Dataverse).

На выходе, всё в репозиторий:

* `geojson/settlements_1820.geojson`, `fortifications_1820.geojson`,
  `faith_sites_1820.geojson`, `economy_sites_1820.geojson` — записи;
* `boundaries/roads_1820.geojson` — дороги, каналы и укреплённые линии;
* `boundaries/boundaries_1820.geojson`, `boundaries/districts_1820.geojson` —
  губернии и уезды 1820-х годов.

Губерния 1897 года у записей — по полигонам `data/out/boundaries`.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import (
    feature_collection, write_feature_collection, write_geojson, write_jsonl,
)
from histctx.sources.atlas_1820 import (
    ADMIN_BOUNDARIES_1820, AREA_KINDS, CITATION, GALLERY_URL, LINE_KINDS, POINT_KINDS,
    RECORD_LAYERS, ROADS_1820, area_feature, check_count, check_point_layer, line_feature,
    records,
)
from histctx.sources.ghcn import GhcnError
from histctx.sources.imperiia import Client, ImperiiaError

CACHE = ROOT / "data" / "raw" / "imperiia"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"


def cache_file(cache: Path, kind) -> Path:
    return cache / f"{kind.service}.json"


def load(cache: Path, kind) -> list:
    path = cache_file(cache, kind)
    if not path.exists():
        raise ImperiiaError(f"нет {path.relative_to(ROOT)}: сначала --check")
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(cache: Path, client: Client) -> list[str]:
    """Сверяет сервисы и кладёт объекты в кэш. Возвращает расхождения."""
    problems = []
    for kind in POINT_KINDS:
        problems += check_point_layer(client.layer_info(kind), kind, client.count(kind))
    for kinds, geometry in ((LINE_KINDS, "esriGeometryPolyline"),
                            (AREA_KINDS, "esriGeometryPolygon")):
        for kind in kinds:
            info = client.layer_info(kind)
            problems += check_count(kind, client.count(kind), info.get("geometryType"),
                                    geometry)
    if problems:
        return problems
    cache.mkdir(parents=True, exist_ok=True)
    for kind in POINT_KINDS + LINE_KINDS + AREA_KINDS:
        path = cache_file(cache, kind)
        if path.exists() and len(json.loads(path.read_text(encoding="utf-8"))) == kind.count:
            continue
        # Уезды — полмиллиона вершин: страницами поменьше, чтобы ответ не рвался.
        features = client.query_all(kind, page=500 if kind in AREA_KINDS else 2000)
        if len(features) != kind.count:
            return [f"{kind.service}: выгружено {len(features)}, в коде {kind.count}"]
        path.write_text(json.dumps(features, ensure_ascii=False), encoding="utf-8")
        print(f"  выгружено: {kind.service} — {len(features)}", flush=True)
    return []


def collect(cache: Path):
    by_layer: dict[str, list] = {spec.slug: [] for spec in RECORD_LAYERS}
    for kind in POINT_KINDS:
        by_layer[kind.spec.slug] += records(load(cache, kind), kind)
    try:
        frame = Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise ImperiiaError(f"рамку взять неоткуда ({exc}): нужны границы из "
                            f"{BOUNDARIES.relative_to(ROOT)} — см. docs/HARVEST.md") from exc
    counts = {slug: frame.mark(recs) for slug, recs in by_layer.items()}
    lines = [f for kind in LINE_KINDS for f in
             (line_feature(x, kind) for x in load(cache, kind)) if f]
    areas = [f for kind in AREA_KINDS for f in
             (area_feature(x, kind) for x in load(cache, kind)) if f]
    return by_layer, counts, lines, areas


def report(by_layer, counts, lines, areas) -> None:
    for spec in RECORD_LAYERS:
        recs = by_layer[spec.slug]
        print(f"\n«{spec.title}»: {len(recs)} записей")
        for what, n in collections.Counter(r.category for r in recs).most_common():
            print(f"  {n:>5}  {what}")
        for what, n in counts[spec.slug].most_common():
            print(f"  {what}: {n}")
        names = collections.Counter(r.extra["name_source"] for r in recs)
        print(f"  название: из набора — {names['набор']}, транслитерация — "
              f"{names['транслитерация']}")
        dup = len(recs) - len({r.uid for r in recs})
        print(f"  повторов uid: {dup}")
        for rec in recs[::max(1, len(recs) // 5)][:5]:
            print(f"    {rec.title} [{rec.region or 'вне губерний 1897 года'}]")
    kinds = collections.Counter(f["properties"]["type"] for f in lines)
    km = collections.Counter()
    for f in lines:
        km[f["properties"]["type"]] += f["properties"].get("length_km", 0)
    print(f"\nЛиний: {len(lines)}")
    for what, n in kinds.most_common():
        print(f"  {n:>5}  {what}, {km[what]:.0f} км")
    levels = collections.Counter(f["properties"]["level"] for f in areas)
    print(f"Полигонов: {len(areas)} — " + ", ".join(f"{k} {v}" for k, v in levels.items()))
    for f in [a for a in areas if a["properties"]["level"] == "province"][::16]:
        p = f["properties"]
        print(f"    {p['name']} ({p['name_latin']}) — {p['type']}")


def check(cache: Path) -> int:
    problems = fetch(cache, Client(pause_sec=0.3))
    if problems:
        print("Сервисы Imperiia расходятся с записанным в коде — сбор остановлен:",
              file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("Сервисы на месте: геометрия, поля и число объектов сходятся.")
    report(*collect(cache))
    print("\nРазбор работает — можно запускать --build.")
    return 0


def _collection(name: str, feats: list, spec) -> dict:
    return feature_collection(name, feats, license=spec.license, source=spec.source,
                              citation=CITATION, url=GALLERY_URL,
                              extra={"period": "1820–1827"})


def build(cache: Path, out_dir: Path) -> int:
    by_layer, counts, lines, areas = collect(cache)
    written = []
    for spec in RECORD_LAYERS:
        recs = by_layer[spec.slug]
        if not recs:
            print(f"{spec.slug}: ничего не собрано.", file=sys.stderr)
            return 1
        geo = out_dir / "geojson" / f"{spec.slug}.geojson"
        n = write_geojson(recs, geo, layer_title=spec.title, hoist_shared=True)
        write_jsonl(recs, out_dir / "jsonl" / f"{spec.slug}.jsonl")
        print(f"«{spec.title}»: {len(recs)} записей, на карте {n}")
        for what, count in counts[spec.slug].most_common():
            print(f"  {what}: {count}")
        written.append(geo)
    boundaries = out_dir / "boundaries"
    provinces = [f for f in areas if f["properties"]["level"] == "province"]
    districts = [f for f in areas if f["properties"]["level"] == "district"]
    for name, feats, spec in (("roads_1820", lines, ROADS_1820),
                              ("boundaries_1820", provinces, ADMIN_BOUNDARIES_1820),
                              ("districts_1820", districts, ADMIN_BOUNDARIES_1820)):
        path = boundaries / f"{name}.geojson"
        n = write_feature_collection(_collection(name, feats, spec), path, compact=True)
        print(f"{name}: {n} объектов")
        written.append(path)
    for path in written:
        print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
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
