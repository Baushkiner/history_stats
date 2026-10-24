#!/usr/bin/env python3
"""Сбор слоя голода 1932–1933 годов по районам и губернской смертности 1871–1914 годов.

    python3 scripts/harvest_famine_1933.py --check    # перечни файлов, сверка, скачать, разобрать
    python3 scripts/harvest_famine_1933.py --build    # записи и полигоны в data/out

Источники:

* пакет воспроизведения А. Маркевича, Н. Науменко, Н. Цянь «The Causes of
  Ukrainian Famine Mortality, 1932–33» на Zenodo (запись 10983057, архив
  `v3.zip`; права — «Other (Attribution)»): районы 1934 года, регионы
  1932 года, губернии 1871–1914 годов;
* набор A. Rozenas, Y. Zhukov «Mass Repression and Political Loyalty» на
  Harvard Dataverse (CC0 1.0): `main_data.Rdata` — полигоны 386 районов УССР
  1933 года и потери от голода по оценке атласа MAPA.

Проверочный первый запуск обязателен. `--check` (он же `--probe`) берёт
перечень файлов записи Zenodo с `/api/records/10983057/files` (этот путь
robots.txt Zenodo разрешает) и перечень набора Dataverse по его API, сверяет
имена, размеры и контрольные суммы с записанными в
`sources/famine_1933.py`, скачивает файлы в `data/raw/famine_1933/`,
печатает число строк и колонок, проверяет тождество сверхсмертности, сводит
районы двух наборов и показывает примеры записей. Расхождение с перечнем —
остановка, а не подгонка.

На выходе (`--build`):

* `geojson/famine_1933.geojson` — точки: 2 020 районов пакета (центроид
  района) и 386 районов УССР из набора Rozenas, Zhukov (точка подписи
  полигона);
* `famine_1933.json` — 27 записей по регионам без точки: умершие по годам;
* `mortality_1871_1914.json` — годы сверхсмертности по 50 губерниям;
* `boundaries/famine_1933_ukr_rayons.geojson` — полигоны 386 районов УССР
  1933 года с потерями от голода;
* `jsonl/famine_1933.jsonl`, `jsonl/mortality_1871_1914.jsonl` — то же
  построчно, в репозиторий не идут.

Губерния 1897 года по центроиду района и сверка губерний таблицы czar
требуют `data/out/boundaries/provinces_1897.geojson`
(`harvest_admin_gis.py --build`, лежит в репозитории).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import (
    write_feature_collection, write_geojson, write_jsonl, write_records_json,
)
from histctx.sources.famine_1891 import ProvinceIndex
from histctx.sources.famine_1933 import (
    ARCHIVE, CONFIDENCE_GAP, DATASET_URL, FAMINE_1933, MEMBERS, MORTALITY_1871_1914, RZ_MAIN,
    RZ_URL, FamineError, RayonIndex, boundaries_geojson, cached_archive, cached_rz,
    check_columns, check_identity, check_rz_manifest, check_zenodo_manifest, czar_records,
    district_pairs, district_records, fetch_rz_manifest, fetch_zenodo_manifest,
    match_datasets, read_archive, read_rz, region_records, rz_records,
)
from histctx.sources.ghcn import Provinces

CACHE = ROOT / "data" / "raw" / "famine_1933"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
PROVINCES_1897 = BOUNDARIES / "provinces_1897.geojson"


def collect(cache_dir: Path, provinces_path: Path) -> dict:
    """Всё собранное разом — одно и то же для проверки и для сборки."""
    if not provinces_path.exists():
        raise FamineError(f"нет справочника губерний 1897 года: {provinces_path}. Сначала "
                          "`python3 scripts/harvest_admin_gis.py --build`")
    gub_polygons = Provinces.load(provinces_path)
    gub_index = ProvinceIndex.load(provinces_path)

    tables = read_archive(cached_archive(cache_dir))
    for name, rows in tables.items():
        check_columns(rows[0].keys() if rows else [], name)
    rz_rows, rz_geometry = read_rz(cached_rz(cache_dir))

    identity = check_identity(district_pairs(tables["districts"]))
    districts = district_records(tables["districts"], gub_polygons)
    regions = region_records(tables["provinces"])
    match = match_datasets(districts, rz_rows, RayonIndex(rz_geometry))
    rayons = rz_records(rz_rows, match["pairs"])
    czar, czar_stats = czar_records(tables["czar"], gub_index)
    return {
        "tables": tables, "rz_rows": rz_rows, "rz_geometry": rz_geometry,
        "identity": identity, "districts": districts, "regions": regions,
        "rayons": rayons, "match": match, "czar": czar, "czar_stats": czar_stats,
    }


def _print_manifests() -> int:
    print(f"Пакет Маркевича, Науменко, Цянь: {DATASET_URL}")
    zenodo = fetch_zenodo_manifest()
    print("  файлы записи Zenodo: " + ", ".join(f"{m['key']} ({m['size']} байт)"
                                               for m in zenodo))
    problems = check_zenodo_manifest(zenodo)
    print(f"Набор Rozenas, Zhukov: {RZ_URL}")
    rz = fetch_rz_manifest()
    print(f"  файлов в наборе по API: {len(rz)}; нужен один — {RZ_MAIN.name}")
    problems += check_rz_manifest(rz)
    if problems:
        print("\nПеречень в коде расходится с источником — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print("  Разберитесь, что изменилось, и поправьте ARCHIVE/RZ_MAIN в "
              "sources/famine_1933.py.", file=sys.stderr)
        return 1
    print(f"  {ARCHIVE.key}: {ARCHIVE.size} байт, {ARCHIVE.checksum} — сходится")
    print(f"  {RZ_MAIN.name}: {RZ_MAIN.size} байт, md5 {RZ_MAIN.md5} — сходится")
    return 0


def check(cache_dir: Path, provinces_path: Path) -> int:
    code = _print_manifests()
    if code:
        return code
    got = collect(cache_dir, provinces_path)
    tables = got["tables"]
    print()
    for name, (member, size) in MEMBERS.items():
        rows = tables[name]
        print(f"{member} ({size} байт): строк {len(rows)}, колонок {len(rows[0]) if rows else 0}")
    print(f"{RZ_MAIN.name}: строк {len(got['rz_rows'])}, полигонов {len(got['rz_geometry'])}")

    identity = got["identity"]
    print(f"\nТождество excess_mortality_1933 = mortality 1933 − 1928 проверено на "
          f"{identity['identity_rows']} районах, расхождение до "
          f"{identity['identity_max_diff']:.1e}")

    districts = got["districts"]
    print(f"\nРайоны пакета: {len(districts)} точек (центроид района), регионов "
          f"{len({r.region for r in districts})}")
    for category, count in collections.Counter(r.category for r in districts).most_common():
        print(f"  {count:>5}  {category}")
    gaps = [r for r in districts if r.confidence == CONFIDENCE_GAP]
    print(f"  меньше 5 умерших на тысячу (registration_gap): {len(gaps)}")
    with_gub = sum(1 for r in districts if r.extra.get("province_1897"))
    print(f"  губерния 1897 года по центроиду найдена у {with_gub} из {len(districts)}")
    print(f"Регионы: {len(got['regions'])} записей без точки")

    match = got["match"]
    print(f"\nСверка с районами УССР 1933 года (Rozenas, Zhukov): "
          f"{match['mnq_inside']} из {match['mnq_ukraine']} районов Украины в пакете "
          f"попали центроидом в полигон набора")
    if match["mnq_outside"]:
        print("  вне полигонов: " + ", ".join(str(n) for n in match["mnq_outside"]))
    print(f"  районов набора с парой: {match['rz_matched']} из {match['rz_total']}, "
          f"из них один к одному {match['rz_one_to_one']}, у "
          f"{match['names_agree']} пар совпал ключ названия; вторым проходом по названию "
          f"разведено {match['rz_by_name']}")
    rz_names = {str(r["ID"]): r["NAME_2_1933"] for r in got["rz_rows"]}
    print(f"  в один полигон легли несколько районов 1934 года: {len(match['rz_many'])}")
    for ident, ids in match["rz_many"].items():
        print(f"    {rz_names.get(ident)}: district_id {', '.join(str(i) for i in ids)}")
    print(f"  районов набора без пары: {len(match['rz_unmatched'])} — "
          + ", ".join(str(rz_names.get(i)) for i in match["rz_unmatched"]))
    rz_total = sum(r.extra['famine_1933_rz'].get('FAMINE_TOTAL', 0) for r in got["rayons"])
    print(f"  потери FAMINE_TOTAL по 386 районам: {rz_total:,.0f}".replace(",", " "))

    czar, stats = got["czar"], got["czar_stats"]
    print(f"\nГубернии 1871–1914: строк со смертностью {stats['rows']}, σ превышения над "
          f"трендом {stats['sigma']:.3f} на тысячу, порог 1,5σ = {stats['threshold']:.3f}")
    for gap in stats["gaps"]:
        print(f"  ноль умерших — пропуск, в тренд не идёт: {gap['gubernia_en']} {gap['year']}")
    by_year = collections.Counter(r.year_from for r in czar)
    print(f"  записей «губерния-год»: {len(czar)}; по годам: "
          + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())))
    bad = [r for r in czar if r.confidence != "ok"]
    print(f"  губерний без пары среди губерний 1897 года: {len(bad)}")

    print("\n  примеры:")
    for rec in districts[:1] + [r for r in districts if r.region == "Украинская ССР"][:1] \
            + got["regions"][-1:] + got["rayons"][:1] + czar[:1]:
        print(f"    {rec.title}")
        print(f"      {rec.summary}")
    print("\nНаборы на месте, перечни сходятся, разбор работает — можно запускать --build.")
    return 0


def build(cache_dir: Path, out_dir: Path, provinces_path: Path) -> int:
    got = collect(cache_dir, provinces_path)
    points = got["districts"] + got["rayons"]
    territorial = got["regions"]
    records = points + territorial
    czar = got["czar"]
    if not got["districts"]:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    geo = out_dir / "geojson" / f"{FAMINE_1933.slug}.geojson"
    n = write_geojson(points, geo, layer_title=FAMINE_1933.title, hoist_shared=True)
    json_path = out_dir / f"{FAMINE_1933.slug}.json"
    write_records_json(territorial, json_path, title=FAMINE_1933.title)
    write_jsonl(records, out_dir / "jsonl" / f"{FAMINE_1933.slug}.jsonl")
    print(f"{FAMINE_1933.slug}: {len(records)} записей — {len(got['districts'])} районов "
          f"пакета и {len(got['rayons'])} районов УССР точками, {len(territorial)} регионов "
          "без точки")
    print(f"  {geo.relative_to(ROOT)}: {n} точек ({geo.stat().st_size / 1_048_576:.1f} МБ)")
    print(f"  {json_path.relative_to(ROOT)}")

    czar_path = out_dir / f"{MORTALITY_1871_1914.slug}.json"
    write_records_json(czar, czar_path, title=MORTALITY_1871_1914.title)
    write_jsonl(czar, out_dir / "jsonl" / f"{MORTALITY_1871_1914.slug}.jsonl")
    print(f"{MORTALITY_1871_1914.slug}: {len(czar)} записей «губерния-год» "
          f"(порог {got['czar_stats']['threshold']:.2f} на тысячу) → "
          f"{czar_path.relative_to(ROOT)}")

    collection = boundaries_geojson(got["rz_geometry"], got["rayons"])
    path = out_dir / "boundaries" / "famine_1933_ukr_rayons.geojson"
    n = write_feature_collection(collection, path, compact=True)
    print(f"Полигонов районов УССР 1933 года: {n} → {path.relative_to(ROOT)} "
          f"({path.stat().st_size / 1_048_576:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить наборы с перечнем, скачать, показать разбор")
    ap.add_argument("--build", action="store_true", help="собрать слои в файлы")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанные файлы наборов")
    ap.add_argument("--provinces", type=Path, default=PROVINCES_1897,
                    help="губернии 1897 года RISTAT: губерния по центроиду и сверка названий")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")

    try:
        if args.check:
            code = check(args.cache, args.provinces)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.provinces)
    except FamineError as exc:
        print(f"Голод 1932–1933 годов: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
