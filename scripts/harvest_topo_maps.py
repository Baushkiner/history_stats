#!/usr/bin/env python3
"""Сбор слоя топографических карт из Russian Military Topographic Map Collection (IU).

    python3 scripts/harvest_topo_maps.py --check             # клон, разбор, отчёт
    python3 scripts/harvest_topo_maps.py --build             # записи в data/out
    python3 scripts/harvest_topo_maps.py --check --refresh   # подтянуть новый коммит
    python3 scripts/harvest_topo_maps.py --check --repo ПУТЬ # готовый клон big-ten

Метаданные листов лежат в репозитории OpenGeoMetadata/big-ten (формат
Aardvark), и проверочный первый запуск начинается с него: `--check` делает
частичный разрежённый клон — `git clone --depth 1 --filter=blob:none
--sparse` и `sparse-checkout` одной папки `metadata-aardvark/Maps/01d-00`,
около 30 МБ вместо 190, — в `data/raw/topo_maps/big-ten/`, читает записи
коллекции 01d-03, ставит губернию 1897 года по центру листа и показывает, что
пришло: листы по масштабам, десятилетиям и издателям, что без года, что вне
рамки, хеш коммита. Клон остаётся в кэше: `--build` и повторный `--check`
берут его как есть, `--refresh` подтягивает последний коммит, `--repo`
указывает на уже готовый клон (полный или разрежённый — всё равно).
Анонимное чтение публичного репозитория идёт через git; API GitHub не
нужен.

Права. Карты — общественное достояние (NoC-US); лицензии метаданных в
репозитории нет — берутся рамка, годы, номенклатура, масштаб и ссылки.

На выходе:

* `geojson/topo_maps.geojson` — листы с центром, `confidence = sheet_center`
  (вне рамки РИ/СССР — `outside_bbox`, без года — `no_date`); в шапке
  коллекции — репозиторий и коммит, из которого собран слой (`source_version`);
* `jsonl/topo_maps.jsonl` — слой целиком (в `.gitignore`).

Нужны `data/out/boundaries/provinces_1897.geojson` (RISTAT) и
`state_borders.geojson` (CShapes) — оба лежат в репозитории.
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
from histctx.sources.ghcn import GhcnError
from histctx.sources.topo_maps import (
    COLLECTION_DIR, COLLECTION_ID, REPO_URL, TOPO_MAPS, TopoMapsError, ensure_repo,
    read_collection, records, repo_commit,
)

CACHE = ROOT / "data" / "raw" / "topo_maps" / "big-ten"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"

# Листы, по которым видно, ради чего слой собран: лист с интервалом лет,
# лист без имени, лист за пределами рамки, Варшава.
WATCH = ("VAC9619-002945", "VAC9619-002496", "VAC9619-001693", "VAC9619-002946")


def load_frame() -> Frame:
    try:
        return Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise TopoMapsError(
            f"рамку взять неоткуда ({exc}). Нужны {BOUNDARIES.relative_to(ROOT)}/"
            "provinces_1897.geojson и state_borders.geojson — см. docs/HARVEST.md") from exc


def collect(repo: Path, *, refresh: bool = False, given: bool = False):
    if not given:
        ensure_repo(repo, refresh=refresh)
    elif not (repo / COLLECTION_DIR).is_dir():
        raise TopoMapsError(f"{repo}: в клоне нет папки {COLLECTION_DIR}")
    commit, date = repo_commit(repo)
    docs = read_collection(repo)
    recs = records(docs)
    counts = load_frame().mark(recs)
    return commit, date, docs, recs, counts


def report(commit, date, docs, recs, counts) -> None:
    print(f"OpenGeoMetadata/big-ten, коммит {commit[:12]} от {date}: записей коллекции "
          f"{COLLECTION_ID} — {len(docs)}")
    print(f"Записей слоя: {len(recs)}; с точкой: {sum(1 for r in recs if r.has_point)}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    print("  пометки:")
    for what, n in collections.Counter(r.confidence for r in recs).most_common():
        print(f"    {n:>6}  {what}")
    print("  масштабы: " + ", ".join(f"{k} — {n}" for k, n in
                                     collections.Counter(r.category for r in recs).most_common()))
    decades = collections.Counter((r.year_from // 10 * 10) for r in recs if r.year_from)
    print("  десятилетия по первому году: " + ", ".join(
        f"{d}-е — {n}" for d, n in sorted(decades.items())))
    ranged = sum(1 for r in recs if r.year_from is not None and r.year_to != r.year_from)
    print(f"  с интервалом лет: {ranged}; без года: "
          f"{sum(1 for r in recs if r.year_from is None)}")
    print("  издатели, чаще всего:")
    for name, n in collections.Counter(r.actor for r in recs if r.actor).most_common(8):
        print(f"    {n:>6}  {name}")
    print(f"  с GeoTIFF: {sum(1 for r in recs if r.extra.get('geotiff'))}; с IIIF: "
          f"{sum(1 for r in recs if r.extra.get('iiif'))}; со штампом «Captured map»: "
          f"{sum(1 for r in recs if r.extra.get('captured'))}; с грифом: "
          f"{sum(1 for r in recs if r.extra.get('grif'))}")
    no_nom = [r for r in recs if not r.extra.get("nomenclature")]
    if no_nom:
        print(f"  без номенклатуры в заголовке ({len(no_nom)}): "
              + "; ".join(r.work or "?" for r in no_nom[:8]))
    print("  губернии 1897 года, чаще всего:")
    for name, n in collections.Counter(r.region for r in recs if r.region).most_common(12):
        print(f"    {n:>6}  {name}")
    print("\n  образцы:")
    by_id = {r.source_id: r for r in recs}
    for key in WATCH:
        rec = by_id.get(key)
        if rec is not None:
            print(f"    {rec.title} [{rec.region or rec.confidence}]")
            print(f"      {rec.summary}")


def check(repo: Path, refresh: bool, given: bool) -> int:
    data = collect(repo, refresh=refresh, given=given)
    if not data[3]:
        print("Ни одного листа не разобрано: проверьте разбор.", file=sys.stderr)
        return 1
    report(*data)
    print("\nМетаданные читаются, разбор работает — можно запускать --build.")
    return 0


def build(repo: Path, out_dir: Path, refresh: bool, given: bool) -> int:
    commit, date, _, recs, counts = collect(repo, refresh=refresh, given=given)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = TOPO_MAPS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=TOPO_MAPS.title, hoist_shared=True)
    # Из какого коммита собран слой — в шапку коллекции, а не в каждую запись:
    # у всех четырёх тысяч листов он один.
    payload = json.loads(geo.read_text(encoding="utf-8"))
    payload["source_version"] = {"repository": REPO_URL, "path": COLLECTION_DIR,
                                 "commit": commit, "date": date}
    geo.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{TOPO_MAPS.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{TOPO_MAPS.title}»: {len(recs)} листов, на карте {n}, без точки {len(off_map)}; "
          f"коммит {commit[:12]} от {date}")
    for what, count in counts.most_common():
        print(f"  {what}: {count}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", "--fetch", dest="check", action="store_true",
                    help="клонировать (если нужно), разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--refresh", action="store_true",
                    help="подтянуть последний коммит репозитория метаданных")
    ap.add_argument("--repo", type=Path, default=None,
                    help="готовый клон OpenGeoMetadata/big-ten (иначе — data/raw/topo_maps)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    repo, given = (args.repo, True) if args.repo else (CACHE, False)
    try:
        if args.check:
            code = check(repo, args.refresh, given)
            if code or not args.build:
                return code
            args.refresh = False
        return build(repo, args.out, args.refresh, given)
    except TopoMapsError as exc:
        print(f"Топокарты: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
