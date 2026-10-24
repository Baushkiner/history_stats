#!/usr/bin/env python3
"""Сбор с сервера карт HURI MAPA: районы УССР 1922–1937, перепись 1926 года, Подолия.

    python3 scripts/harvest_huri.py --check    # сверка с сервером, скачать, показать разбор
    python3 scripts/harvest_huri.py --build    # подложка и записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) спрашивает у сервера перечень слоёв `master_admin`, поля и
число объектов каждого слоя, сверяет их с записанным в `sources/huri.py`,
скачивает слои в `data/raw/huri/`, проверяет, что срез «1 April 1933» всё ещё
копия среза 15 декабря 1933 года, и печатает разбор. Расхождение — остановка,
а не подгонка: сервис переиздали, и прежде чем собирать, надо понять, что в
нём поменялось.

Права. Сервер условий не публикует (copyrightText «HURI»): права не
выяснены, берутся факты — названия, даты, числа, границы — со ссылкой на
сервис в каждой записи и в каждом файле.

На выходе:

* `boundaries/ukraine_admin_1922_1937.geojson` — полигоны восьми срезов
  деления УССР (губернии и повиты 1922, округа и районы 1927 и 1928, районы
  и области 1932–1937), упрощённые и округлённые; подложка карты, в
  репозиторий идёт;
* `boundaries/ukraine_centers_1922_1937.geojson` — центры единиц тех же
  срезов, у части — историческое и нынешнее название;
* `census_1926_raion.json` и `jsonl/census_1926_raion.jsonl` — перепись 1926
  года по 625 районам, охват «район», без точки;
* `geojson/podillya_settlements.geojson` и `jsonl/podillya_settlements.jsonl`
  — 536 поселений Подолии с первым упоминанием.

Губерния 1897 года у районов переписи и у поселений Подолии — по полигонам
RISTAT (`data/out/boundaries/provinces_1897.geojson`, `districts_1897.geojson`,
собираются `harvest_admin_gis.py --build` и лежат в репозитории). Без них сбор
останавливается.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import (
    write_feature_collection, write_geojson, write_jsonl, write_records_json,
)
from histctx.sources.ghcn import GhcnError, Provinces
from histctx.sources.huri import (
    ADMIN_SERVICE, ADMIN_UKRAINE, CENSUS_1926, CENSUS_OKRUHAS_LAYER, CENSUS_RAIONS_LAYER,
    ETHNIC_COUNT, ETHNIC_LAYER, ETHNIC_LAYER_NAME, ETHNIC_SERVICE, PODILLYA,
    PODILLYA_COUNT, PODILLYA_LAYER, PODILLYA_LAYER_NAME, PODILLYA_SERVICE, REQUIRED_ETHNIC,
    REQUIRED_FIELDS, REQUIRED_PODILLYA, SLICES, Client, HuriError, boundaries_collection,
    census_records, check_admin_service, check_layer, podillya_records, raion_index,
    same_features, share_mismatches, slice_features,
)

CACHE = ROOT / "data" / "raw" / "huri"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
PROVINCES_1897 = BOUNDARIES / "provinces_1897.geojson"
DISTRICTS_1897 = BOUNDARIES / "districts_1897.geojson"

ADMIN_FILE = "ukraine_admin_1922_1937.geojson"
CENTERS_FILE = "ukraine_centers_1922_1937.geojson"


# --- скачивание ------------------------------------------------------------

def cached_layer(client: Client, cache_dir: Path, service: str, layer: int, *,
                 geometry: bool = True, refresh: bool = False) -> dict:
    """Слой целиком из кэша, а нет его — с сервера."""
    path = cache_dir / f"{service.split('/')[-2]}_{layer}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    payload = client.query_all(service, layer, geometry=geometry)
    if (payload.get("spatialReference") or {}).get("wkid") not in (None, 4326):
        raise HuriError(f"{service}/{layer}: координаты пришли не в WGS 84 "
                        f"({payload['spatialReference']})")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def load_all(client: Client, cache_dir: Path, *, refresh: bool = False) -> dict:
    admin = {item.layer_id: cached_layer(client, cache_dir, ADMIN_SERVICE, item.layer_id,
                                         refresh=refresh)
             for item in SLICES}
    ethnic = cached_layer(client, cache_dir, ETHNIC_SERVICE, ETHNIC_LAYER, geometry=False,
                          refresh=refresh)
    podillya = cached_layer(client, cache_dir, PODILLYA_SERVICE, PODILLYA_LAYER, refresh=refresh)
    return {"admin": admin, "ethnic": ethnic, "podillya": podillya}


def load_reference(provinces_path: Path, districts_path: Path) -> tuple[Provinces, Provinces]:
    for path in (provinces_path, districts_path):
        if not path.exists():
            raise HuriError(f"нет справочника границ 1897 года: {path}. Сначала "
                            "`python3 scripts/harvest_admin_gis.py --build`")
    try:
        return (Provinces.load(provinces_path),
                Provinces.load(districts_path, field="Name_RU"))
    except GhcnError as exc:
        raise HuriError(str(exc)) from exc


# --- разбор ----------------------------------------------------------------

def collect(data: dict, provinces: Provinces, districts: Provinces) -> dict:
    admin = data["admin"]
    duplicates = [item for item in SLICES if item.duplicate_of is not None
                  and not same_features(admin[item.layer_id], admin[item.duplicate_of])]
    if duplicates:
        names = ", ".join(f"{item.layer_id} «{item.name}»" for item in duplicates)
        raise HuriError(f"срезы {names} больше не копия своих пар — в сервисе появились "
                        "данные на 1 апреля 1933 года; разберитесь и поправьте SLICES")

    polygons, centers = [], []
    for item in SLICES:
        if item.duplicate_of is not None:
            continue
        feats = slice_features(admin[item.layer_id], item)
        (centers if item.level == "center" else polygons).extend(feats)

    index = raion_index(admin[CENSUS_RAIONS_LAYER], admin[CENSUS_OKRUHAS_LAYER])
    census = census_records(data["ethnic"], index, provinces)
    podillya = podillya_records(data["podillya"], provinces, districts)
    return {"polygons": polygons, "centers": centers, "census": census,
            "podillya": podillya, "index": index}


# --- проверка --------------------------------------------------------------

def check(client: Client, cache_dir: Path, provinces_path: Path, districts_path: Path,
          refresh: bool) -> int:
    info = client.get(ADMIN_SERVICE)
    print(f"{ADMIN_SERVICE}: «{info.get('serviceDescription')}», "
          f"copyrightText «{info.get('copyrightText')}», "
          f"maxRecordCount {info.get('maxRecordCount')}")
    problems = check_admin_service(info)
    for item in SLICES:
        layer = client.get(f"{ADMIN_SERVICE}/{item.layer_id}")
        count = client.get(f"{ADMIN_SERVICE}/{item.layer_id}/query", where="1=1",
                           returnCountOnly="true").get("count")
        problems += check_layer(layer, name=item.name, required=REQUIRED_FIELDS[item.schema],
                                count=item.count, actual_count=count)
    for service, layer_id, name, required, count in (
            (ETHNIC_SERVICE, ETHNIC_LAYER, ETHNIC_LAYER_NAME, REQUIRED_ETHNIC, ETHNIC_COUNT),
            (PODILLYA_SERVICE, PODILLYA_LAYER, PODILLYA_LAYER_NAME, REQUIRED_PODILLYA,
             PODILLYA_COUNT)):
        layer = client.get(f"{service}/{layer_id}")
        actual = client.get(f"{service}/{layer_id}/query", where="1=1",
                            returnCountOnly="true").get("count")
        print(f"{service}/{layer_id}: «{layer.get('name')}», объектов {actual}, "
              f"copyrightText «{layer.get('copyrightText')}»")
        problems += check_layer(layer, name=name, required=required, count=count,
                                actual_count=actual)
    if problems:
        print("\nПеречень в коде расходится с сервером — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print("  Разберитесь, что изменилось, и поправьте SLICES и REQUIRED_* "
              "в sources/huri.py.", file=sys.stderr)
        return 1
    print(f"Слоёв master_admin в коде {len(SLICES)}: имена, поля и число объектов сходятся.")

    data = load_all(client, cache_dir, refresh=refresh)
    provinces, districts = load_reference(provinces_path, districts_path)
    got = collect(data, provinces, districts)

    print("\nСрезы деления (копии 1 апреля 1933 года пропущены, проверено: совпадают "
          "с 15 декабря 1933 года до вершины):")
    raw_vertices = 0
    for item in SLICES:
        if item.duplicate_of is not None:
            continue
        feats = [f for f in got["polygons"] + got["centers"] if f["properties"]["layer"] ==
                 item.layer_id]
        vertices = sum(len(ring) for f in data["admin"][item.layer_id]["features"]
                       for ring in (f.get("geometry") or {}).get("rings") or [])
        raw_vertices += vertices
        dates = collections.Counter((f["properties"].get("start"), f["properties"].get("end"))
                                    for f in feats)
        conflict = sum(1 for f in feats if f["properties"].get("dates_conflict"))
        empty = sum(1 for f in feats if not f["geometry"])
        print(f"  {item.as_of}  {item.level:<6} {len(feats):>4}  вершин {vertices:>7}  "
              f"даты {dict(dates)}" + (f"  даты из чужого среза: {conflict}" if conflict else "")
              + (f"  без геометрии: {empty}" if empty else ""))
    kept = sum(_vertices(f["geometry"]) for f in got["polygons"])
    print(f"  вершин полигонов: {raw_vertices} на сервере, {kept} после упрощения")

    census = got["census"]
    filled = [r for r in census if r.extra.get("census_1926")]
    total = sum(r.extra["census_1926"]["всего"]["оба"] for r in filled)
    print(f"\nПерепись 1926 года: записей {len(census)}, с числами {len(filled)}, "
          f"население в сумме {total:,}".replace(",", " "))
    no_region = [r.title for r in census if not r.region]
    print(f"  губерния 1897 года по полигону района найдена у "
          f"{len(census) - len(no_region)} из {len(census)}")
    for title in no_region:
        print(f"    без губернии: {title}")
    no_okruha = [r.title for r in census if "(" not in r.title]
    if no_okruha:
        print(f"  без русского названия округа: {no_okruha}")
    rest = [r.extra["census_1926"]["всего"]["оба"]
            - sum(row["оба"] for label, row in r.extra["census_1926"].items() if label != "всего")
            for r in filled]
    print(f"  «всего» минус сумма четырнадцати народностей: от {min(rest)} до {max(rest)}"
          f" (прочие народности)")
    print(f"  колонка доли расходится с числами (> 0,01 п.п.): "
          f"{share_mismatches(data['ethnic'])}")
    print(f"  по губерниям 1897 года: "
          f"{dict(collections.Counter(r.region for r in census).most_common())}")

    podillya = got["podillya"]
    print(f"\nПоселения Подолии: {len(podillya)}; по датировке "
          f"{dict(collections.Counter(r.date_precision for r in podillya))}")
    print(f"  первое упоминание: {min(r.year_from for r in podillya if r.year_from)}–"
          f"{max(r.extra['first_mention'][1] or r.year_from for r in podillya if r.year_from)}")
    print(f"  с губернией 1897 года: {sum(1 for r in podillya if r.region)}, "
          f"по губерниям {dict(collections.Counter(r.region for r in podillya))}")
    renamed = sum(1 for r in podillya
                  if r.extra.get("name_historic_uk") != r.extra.get("name_modern_uk"))
    print(f"  историческое название отличается от нынешнего: {renamed}")
    print(f"  координат нет: {sum(1 for r in podillya if not r.has_point)}")

    print("\n  примеры:")
    for rec in census[:2] + podillya[:2]:
        print(f"    {rec.title}  [{rec.region}]")
        print(f"      {rec.summary}")
    print("\nСервер отвечает, перечень сходится, разбор работает — можно запускать --build.")
    return 0


def _vertices(geometry) -> int:
    if not geometry:
        return 0
    polygons = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                else [geometry["coordinates"]])
    return sum(len(ring) for polygon in polygons for ring in polygon)


# --- сборка ----------------------------------------------------------------

def build(client: Client, cache_dir: Path, out_dir: Path, provinces_path: Path,
          districts_path: Path) -> int:
    data = load_all(client, cache_dir)
    provinces, districts = load_reference(provinces_path, districts_path)
    got = collect(data, provinces, districts)
    if not got["polygons"] or not got["census"]:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    for name, feats in ((ADMIN_FILE, got["polygons"]), (CENTERS_FILE, got["centers"])):
        path = out_dir / "boundaries" / name
        n = write_feature_collection(boundaries_collection(feats, path.stem), path, compact=True)
        print(f"{n} объектов → {path.relative_to(ROOT)} "
              f"({path.stat().st_size / 1_048_576:.1f} МБ)")

    census = got["census"]
    write_records_json(census, out_dir / f"{CENSUS_1926.slug}.json", title=CENSUS_1926.title)
    write_jsonl(census, out_dir / "jsonl" / f"{CENSUS_1926.slug}.jsonl")
    print(f"Перепись 1926 года: {len(census)} записей (охват «район», без точки) → "
          f"{CENSUS_1926.slug}.json и jsonl/{CENSUS_1926.slug}.jsonl")

    podillya = got["podillya"]
    n = write_geojson(podillya, out_dir / "geojson" / f"{PODILLYA.slug}.geojson",
                      layer_title=PODILLYA.title)
    write_jsonl(podillya, out_dir / "jsonl" / f"{PODILLYA.slug}.jsonl")
    print(f"Поселения Подолии: {len(podillya)} записей, на карту {n} → "
          f"geojson/{PODILLYA.slug}.geojson")
    print(f"«{ADMIN_UKRAINE.title}» записей схемы не даёт: это подложка карты.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить сервер с перечнем, скачать, показать разбор")
    ap.add_argument("--build", action="store_true", help="собрать подложку и записи")
    ap.add_argument("--refresh", action="store_true",
                    help="на --check скачать слои заново, а не брать из кэша")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--provinces", type=Path, default=PROVINCES_1897)
    ap.add_argument("--districts", type=Path, default=DISTRICTS_1897)
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")

    client = Client()
    try:
        if args.check:
            code = check(client, args.cache, args.provinces, args.districts, args.refresh)
            if code or not args.build:
                return code
        return build(client, args.cache, args.out, args.provinces, args.districts)
    except HuriError as exc:
        print(f"HURI MAPA: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
