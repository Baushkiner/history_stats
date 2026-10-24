#!/usr/bin/env python3
"""Сбор слоя голода 1891–1892 годов по уездам: набор В. Чарныш (Harvard Dataverse).

    python3 scripts/harvest_famine_1891.py --check    # список файлов по API, сверка, скачать
    python3 scripts/harvest_famine_1891.py --build    # записи и полигоны в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) запрашивает список файлов набора по API Dataverse, сверяет
имена, идентификаторы и размеры с перечнем в `sources/famine_1891.py`,
скачивает файлы в `data/raw/famine_1891/`, печатает колонки и число строк,
разбирает их в записи и перечисляет уезды, которым не нашлось пары среди
уездов 1897 года RISTAT. Расхождение с перечнем — остановка, а не молчаливая
подгонка: набор переиздали, и прежде чем собирать, надо понять, что в нём
изменилось.

Права. Карточка набора — CC0 1.0: брать можно всё, ссылка на набор стоит
в каждой записи по условию 4 раздела «Каталог открыт» (`docs/CATALOG.md`).

На выходе:

* `jsonl/famine_1891.jsonl` — записи четырёх видов, охват «регион», без
  точки: 216 уездов главной таблицы, 24 губернии, холера 1892 года по уездам
  панели и годы со сверхсмертностью не ниже полутора сигм; в репозиторий
  не идёт;
* `boundaries/famine_1891_districts.geojson` — полигоны 216 уездов главной
  таблицы с русскими названиями, парой в RISTAT и главными числами помощи:
  подложка карты, лежит рядом с границами 1897 года и в репозиторий идёт.

Сверка с уездами 1897 года требует `data/out/boundaries/districts_1897.geojson`
и `provinces_1897.geojson` (собираются `harvest_admin_gis.py --build` и лежат
в репозитории). Без них сбор останавливается: записать слой без сверки
значило бы оставить несовпавшие уезды без пометки.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_feature_collection, write_jsonl
from histctx.sources.famine_1891 import (
    DATASET_URL, FAMINE_1891, FILES, MAIN, PANEL, PROVINCES_FILE, REQUIRED_MAIN, REQUIRED_PANEL,
    REQUIRED_PROVINCES, WORK_YEARS, DistrictIndex, FamineError, ProvinceIndex,
    boundaries_geojson, cached, check_columns, check_manifest, fetch_manifest, load_shapes,
    panel_records, province_records, read_table, rows_to_records,
)

CACHE = ROOT / "data" / "raw" / "famine_1891"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
DISTRICTS_1897 = BOUNDARIES / "districts_1897.geojson"
PROVINCES_1897 = BOUNDARIES / "provinces_1897.geojson"


def load_indexes(districts_path: Path, provinces_path: Path) -> tuple[DistrictIndex, ProvinceIndex]:
    for path in (districts_path, provinces_path):
        if not path.exists():
            raise FamineError(
                f"нет справочника границ 1897 года: {path}. Сначала "
                "`python3 scripts/harvest_admin_gis.py --build` — без него уезды не сверить"
            )
    return DistrictIndex.load(districts_path), ProvinceIndex.load(provinces_path)


def collect(cache_dir: Path, districts_path: Path, provinces_path: Path) -> dict:
    """Всё собранное разом — одно и то же для проверки и для сборки."""
    districts, provinces = load_indexes(districts_path, provinces_path)

    rows = read_table(cached(MAIN, cache_dir))
    check_columns(rows[0].keys() if rows else [], REQUIRED_MAIN, MAIN.name)
    district_records = rows_to_records(rows, districts)

    province_rows = read_table(cached(PROVINCES_FILE, cache_dir))
    check_columns(province_rows[0].keys() if province_rows else [], REQUIRED_PROVINCES,
                  PROVINCES_FILE.name)
    province_recs = province_records(province_rows, provinces)

    panel_rows = read_table(cached(PANEL, cache_dir))
    check_columns(panel_rows[0].keys() if panel_rows else [], REQUIRED_PANEL, PANEL.name)
    cholera, excess, stats = panel_records(panel_rows, districts)

    return {
        "districts": district_records, "provinces": province_recs,
        "cholera": cholera, "excess": excess, "panel_stats": stats,
        "panel_rows": len(panel_rows), "panel_columns": len(panel_rows[0]) if panel_rows else 0,
        "index": districts, "shapes": load_shapes(cache_dir),
    }


def _report_unmatched(records: list, index: DistrictIndex) -> None:
    unmatched = [r for r in records if r.confidence == "district_unmatched"]
    print(f"  пара в RISTAT 1897 найдена у {len(records) - len(unmatched)} из {len(records)}")
    if unmatched:
        print("  без пары — остаются в данных с пометкой district_unmatched:")
        for rec in unmatched:
            known = ", ".join(index.candidates(rec.region)) or "губерния не найдена"
            print(f"    {rec.place_text}  (в справочнике: {known})")


def check(cache_dir: Path, districts_path: Path, provinces_path: Path) -> int:
    print(f"Карточка набора: {DATASET_URL}")
    manifest = fetch_manifest()
    print(f"Файлов в наборе по API: {len(manifest)}; нужных сборщику: {len(FILES)}")
    problems = check_manifest(manifest)
    if problems:
        print("\nПеречень в коде расходится с набором — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print("  Разберитесь, что изменилось, и поправьте FILES в sources/famine_1891.py.",
              file=sys.stderr)
        return 1
    for file in FILES:
        path = cached(file, cache_dir)
        print(f"  {file.file_id}  {file.name:<26} {path.stat().st_size:>9} байт  сходится")

    rows = read_table(cache_dir / MAIN.name)
    columns = list(rows[0]) if rows else []
    print(f"\n{MAIN.name}: строк {len(rows)}, колонок {len(columns)}")
    print("  колонки:", ", ".join(columns[:12]), "…")
    province_rows = read_table(cache_dir / PROVINCES_FILE.name)
    print(f"{PROVINCES_FILE.name}: строк {len(province_rows)}, колонок "
          f"{len(province_rows[0]) if province_rows else 0}")

    got = collect(cache_dir, districts_path, provinces_path)
    print(f"{PANEL.name}: строк {got['panel_rows']}, колонок {got['panel_columns']}")

    districts = got["districts"]
    print(f"\nЗаписей по уездам: {len(districts)} (охват «уезд внутри губернии», без точки)")
    for category, count in collections.Counter(r.category for r in districts).most_common():
        print(f"  {count:>5}  {category}")
    print(f"  губерний: {len({r.region for r in districts if r.region})}, "
          f"период помощи прочитан по месяцам у "
          f"{sum(1 for r in districts if r.date_precision == 'month')}")
    _report_unmatched(districts, got["index"])

    provinces = got["provinces"]
    print(f"\nЗаписей по губерниям: {len(provinces)}")
    bad = [r for r in provinces if r.confidence != "ok"]
    print(f"  названия восстановлены из двойной кодировки, сверены с provinces_1897: "
          f"{len(provinces) - len(bad)} из {len(provinces)}")
    for rec in bad:
        print(f"    не нашлась среди губерний 1897 года: {rec.region}")

    stats = got["panel_stats"]
    print(f"\nПанель 1885–1896: тождество est_em = est_cdr − cdr_pred проверено на "
          f"{stats['identity_rows']} строках, расхождение до {stats['identity_max_diff']:.1e}")
    print(f"  σ сверхсмертности по всей панели {stats['sigma']:.3f} на тысячу, "
          f"порог 1,5σ = {stats['threshold']:.3f}")
    cholera, excess = got["cholera"], got["excess"]
    died = f"{sum(r.extra['famine'].get('cholera_deaths', 0) for r in cholera):,}"
    print(f"  холера 1892 года: {len(cholera)} уездов с умершими, "
          f"всего умерших {died.replace(',', ' ')}")
    _report_unmatched(cholera, got["index"])
    by_year = collections.Counter(r.year_from for r in excess)
    print(f"  сверхсмертность не ниже порога: {len(excess)} записей «уезд-год», по годам: "
          + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())))
    print(f"  поле work «{FAMINE_1891.title.split(':')[0]}» несут записи за "
          f"{WORK_YEARS[0]}–{WORK_YEARS[1]} годы: "
          f"{sum(1 for r in excess if r.work)} из {len(excess)}")
    _report_unmatched(excess, got["index"])

    shapes = got["shapes"]
    ids = {r.source_id for r in districts}
    found = sum(1 for f in shapes if str((f.get('properties') or {}).get('ter_id')) in ids)
    print(f"\nПолигонов в DistrictMap.shp: {len(shapes)}, из них с уездом главной таблицы: "
          f"{found} из {len(ids)}")

    print("\n  примеры:")
    for rec in districts[:2] + cholera[:1] + excess[:1]:
        print(f"    {rec.title}")
        print(f"      {rec.summary}")
    print("\nНабор на месте, перечень сходится, разбор работает — можно запускать --build.")
    return 0


def build(cache_dir: Path, out_dir: Path, districts_path: Path, provinces_path: Path) -> int:
    got = collect(cache_dir, districts_path, provinces_path)
    districts = got["districts"]
    records = districts + got["provinces"] + got["cholera"] + got["excess"]
    if not districts:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "jsonl" / f"{FAMINE_1891.slug}.jsonl"
    write_jsonl(records, jsonl)
    unmatched = sum(1 for r in records if r.confidence == "district_unmatched")
    print(f"Собрано {len(records)} записей (охват «регион», без точки): "
          f"{len(districts)} по уездам, {len(got['provinces'])} по губерниям, "
          f"{len(got['cholera'])} — холера 1892 года, {len(got['excess'])} — "
          f"сверхсмертность за год (порог {got['panel_stats']['threshold']:.2f} на тысячу).")
    print(f"  уездов без пары в RISTAT 1897 (остались в данных): {unmatched}")
    print(f"  файл: {jsonl.relative_to(ROOT)}")

    collection = boundaries_geojson(got["shapes"], districts)
    path = out_dir / "boundaries" / "famine_1891_districts.geojson"
    n = write_feature_collection(collection, path, compact=True)
    print(f"Полигонов уездов: {n} → {path.relative_to(ROOT)} "
          f"({path.stat().st_size / 1_048_576:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить набор с перечнем, скачать, показать колонки и разбор")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанные файлы набора")
    ap.add_argument("--districts", type=Path, default=DISTRICTS_1897,
                    help="уезды 1897 года RISTAT для сверки")
    ap.add_argument("--provinces", type=Path, default=PROVINCES_1897,
                    help="губернии 1897 года RISTAT для сверки")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")

    try:
        if args.check:
            code = check(args.cache, args.districts, args.provinces)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.districts, args.provinces)
    except FamineError as exc:
        print(f"Набор Dataverse: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
