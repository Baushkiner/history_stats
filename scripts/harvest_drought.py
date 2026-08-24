#!/usr/bin/env python3
"""Сбор слоя засух по годичным кольцам (NOAA Paleoclimatology).

    python3 scripts/harvest_drought.py --probe     # что в наборе, без записи файлов
    python3 scripts/harvest_drought.py --build     # собрать слой в data/out

    # второй атлас — Европа и Средиземноморье, ради западной кромки:
    # то, что покрывает основной набор, из него выбрасывается, а файл
    # получает своё имя (drought_atlas_owda.geojson)
    python3 scripts/harvest_drought.py --build --dataset owda

    # полная картина вместо одних экстремальных засух
    python3 scripts/harvest_drought.py --build --threshold -3

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--probe`
печатает то, что в файлах набора лежит на самом деле — узлы сетки, шапку
матрицы, годы, пропуски — и разбирает пробную выгрузку. Слой большой и
однообразный: если набор переедет или сменит формат, пустую или сдвинутую на
колонку выгрузку потом не отыскать.

В слой идёт не погода, а отклонение от нормы: обычный год — шум, который
вытеснит на карте всё остальное. Порог берётся со шкалы Палмера (−3 — сильная
засуха, −4 — экстремальная) и меняется ключом `--threshold`; почему по
умолчанию −4, объяснено в `src/histctx/sources/drought.py`.

Права. Данные NOAA — общественное достояние; карточка набора просит ссылаться
на публикацию и на страницу набора, поэтому цитата и ссылка стоят в каждой
записи (и один раз на уровне слоя в GeoJSON).
"""

from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.io_formats import write_geojson, write_jsonl  # noqa: E402
from histctx.sources.drought import (  # noqa: E402
    DATASETS, DEFAULT_DATASET, DROUGHT_ATLAS, THRESHOLD, YEAR_FROM, YEAR_TO,
    Atlas, DroughtError, check_atlas, edge_points, episodes_to_records,
    find_episodes, load, read_grid, read_matrix, usable_points,
)

CACHE = ROOT / "data" / "cache" / "drought"


def fringe_only(args) -> tuple:
    """Что выбросить из второго набора, чтобы не удвоить перекрытие.

    Атласы накладываются друг на друга, и в общей полосе точнее основной
    (у ERDA это сказано в самой статье про OWDA). Поэтому второй набор берётся
    только кромкой — тем, до чего основной не дотянулся. Ключ `--whole`
    отменяет обрезку: слой тогда собирается из одного этого набора.
    """
    if args.dataset == DEFAULT_DATASET or args.whole:
        return None, ""
    primary = DATASETS[DEFAULT_DATASET]
    return primary.bbox, (f"берётся только кромка за пределами набора "
                          f"{primary.title}: в перекрытии он точнее")


def open_atlas(args) -> Atlas:
    """Атлас из сети (с кэшем) или из заранее скачанных файлов."""
    dataset = DATASETS[args.dataset]
    if args.grid or args.matrix:
        if not (args.grid and args.matrix):
            raise SystemExit("--grid и --matrix задаются вместе: сетка и матрица")
        points = read_grid(args.grid.read_text(encoding="utf-8-sig").splitlines())
        years, series = read_matrix(args.matrix.read_text(encoding="utf-8-sig").splitlines(),
                                    year_from=args.year_from, year_to=args.year_to)
        atlas = Atlas(dataset=dataset, points=points, years=years, series=series)
        check_atlas(atlas)
        return atlas
    return load(dataset, cache_dir=None if args.no_cache else args.cache,
                year_from=args.year_from, year_to=args.year_to)


def probe(atlas: Atlas, threshold: float, exclude_bbox: tuple = None,
          clip_note: str = "") -> int:
    dataset = atlas.dataset
    print(f"Набор: {dataset.title}")
    print(f"  карточка: {dataset.study_url}")
    print(f"  сетка:    {dataset.grid_url}")
    print(f"  матрица:  {dataset.matrix_url}")
    print(f"  охват:    {dataset.extent}")
    print(f"  годы набора: {dataset.span[0]}–{dataset.span[1]}")

    lats = [p.lat for p in atlas.points.values()]
    lons = [p.lon for p in atlas.points.values()]
    print(f"\nУзлов сетки: {len(atlas.points)}, шаг {dataset.step}°")
    print(f"  широта:  {min(lats)}…{max(lats)}")
    print(f"  долгота: {min(lons)}…{max(lons)}")
    first = atlas.points[min(atlas.points)]
    print(f"  первый узел: №{first.number}  {first.lat}, {first.lon}")

    edge = edge_points(atlas.points, dataset.step)
    print(f"  на краю сетки (меньше восьми соседей): {len(edge)} — "
          f"{100 * len(edge) / len(atlas.points):.0f}%")

    print(f"\nСтрок матрицы прочитано: {len(atlas.years)} "
          f"({atlas.years[0]}–{atlas.years[-1]}), колонок {len(atlas.series)}")
    numbers = sorted(atlas.series)[:8]
    print(f"  номера узлов в шапке: {numbers} …")
    sample_year = atlas.years[len(atlas.years) // 2]
    position = atlas.years.index(sample_year)
    values = [round(atlas.series[n][position], 2) for n in numbers]
    print(f"  строка за {sample_year} год: {values} …")

    gaps = sum(1 for column in atlas.series.values()
               for value in column if math.isnan(value))
    print(f"  значений: {len(atlas.years) * len(atlas.series)}, "
          f"из них пропусков: {gaps}")

    # Считать долю засушливых узлов-лет надо от тех узлов, которые в слой и
    # пойдут: у OWDA половина сетки лежит западнее нашей рамки.
    taken = usable_points(atlas, exclude_bbox=exclude_bbox)
    print(f"\nВ охвате карты и в слое: {len(taken)} узлов из {len(atlas.points)}"
          + (f" — {clip_note}" if clip_note else ""))
    total = len(atlas.years) * len(taken)

    episodes = find_episodes(atlas, threshold=threshold, exclude_bbox=exclude_bbox,
                             year_from=atlas.years[0], year_to=atlas.years[-1])
    dry_years = sum(len(e.values) for e in episodes)
    print(f"При пороге PDSI ≤ {threshold}: узлов-лет {dry_years} "
          f"({100 * dry_years / max(total, 1):.1f}% их значений), эпизодов {len(episodes)}")
    if not episodes:
        print("  Ни одной засухи не отобрано: проверьте порог и годы.")
        return 1

    by_century = collections.Counter((e.year_from - 1) // 100 + 1 for e in episodes)
    print("  по векам:")
    for century, count in sorted(by_century.items()):
        print(f"    {century:>3} в.  {count}")
    kinds = collections.Counter(e.category for e in episodes)
    for kind, count in kinds.most_common():
        print(f"    {count:>7}  {kind}")

    records = episodes_to_records(episodes, dataset, edge=edge)
    print(f"\nРазобрано записей: {len(records)}")
    print("  примеры:")
    for rec in records[:5]:
        print(f"    {rec.period_raw:>9}  {rec.lat:.2f},{rec.lon:.2f}  {rec.title}")
    print(f"\n  {records[0].summary}")
    print("\nПоля на месте, разбор работает — можно запускать --build.")
    print(f"Покрытие: {dataset.extent}. Там, где атласа нет, слой молчит — "
          "это не «засух не было».")
    return 0


def build(atlas: Atlas, args, exclude_bbox: tuple = None, clip_note: str = "") -> int:
    episodes = find_episodes(atlas, threshold=args.threshold, exclude_bbox=exclude_bbox,
                             year_from=args.year_from, year_to=args.year_to)
    edge = edge_points(atlas.points, atlas.dataset.step)
    records = episodes_to_records(episodes, atlas.dataset, edge=edge)
    if not records:
        print("Ничего не собрано: при таком пороге и окне лет засух не нашлось.",
              file=sys.stderr)
        return 1

    # Имя файла зависит от набора: собрать OWDA поверх ERDA под одним именем
    # значило бы молча подменить слой другим, вдвое меньшим.
    name = DROUGHT_ATLAS.slug if args.dataset == DEFAULT_DATASET \
        else f"{DROUGHT_ATLAS.slug}_{args.dataset}"
    out_dir = args.out
    n = write_geojson(records, out_dir / "geojson" / f"{name}.geojson",
                      layer_title=DROUGHT_ATLAS.title, hoist_shared=True)
    write_jsonl(records, out_dir / "jsonl" / f"{name}.jsonl")

    at_edge = sum(1 for r in records if r.confidence == "grid_edge")
    years = [r.year_from for r in records]
    print(f"Собрано {len(records)} записей, на карту пойдут {n}. Файл {name}.geojson")
    print(f"  годы: {min(years)}–{max(r.year_to for r in records)}, "
          f"порог PDSI ≤ {args.threshold}")
    print(f"  на краю сетки атласа (помечены confidence=grid_edge): {at_edge}")
    print(f"  покрытие: {atlas.dataset.extent}")
    if clip_note:
        print(f"  {clip_note}; чтобы собрать набор целиком, добавьте --whole")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true",
                    help="что в наборе на самом деле, без записи файлов")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--dataset", default=DEFAULT_DATASET, choices=sorted(DATASETS),
                    help="какой атлас брать: erda — до Урала, owda — Европа")
    ap.add_argument("--whole", action="store_true",
                    help="не обрезать второй набор по кромке основного")
    ap.add_argument("--threshold", type=float, default=THRESHOLD,
                    help="порог засухи по шкале Палмера: −3 сильная, −4 экстремальная")
    ap.add_argument("--year-from", type=int, default=YEAR_FROM)
    ap.add_argument("--year-to", type=int, default=YEAR_TO)
    ap.add_argument("--grid", type=Path, default=None,
                    help="таблица узлов сетки из файла, а не из сети")
    ap.add_argument("--matrix", type=Path, default=None,
                    help="матрица PDSI из файла, а не из сети")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда складывать скачанные файлы набора")
    ap.add_argument("--no-cache", action="store_true", help="не сохранять скачанное")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.probe and not args.build:
        ap.error("укажите --probe или --build")

    try:
        atlas = open_atlas(args)
        exclude_bbox, clip_note = fringe_only(args)
        if args.probe:
            code = probe(atlas, args.threshold, exclude_bbox, clip_note)
            if code or not args.build:
                return code
        return build(atlas, args, exclude_bbox, clip_note)
    except DroughtError as exc:
        print(f"Атлас засух: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Нет файла: {exc.filename}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
