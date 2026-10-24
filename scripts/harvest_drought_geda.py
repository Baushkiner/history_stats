#!/usr/bin/env python3
"""Сбор засух по годичным кольцам за пределами ERDA: Great Eurasian Drought Atlas.

    pip install h5py                                       # только для этого сборщика
    python3 scripts/harvest_drought_geda.py --check        # сверка с Zenodo, без записи слоя
    python3 scripts/harvest_drought_geda.py --check --compare-erda   # + сверка с ERDA
    python3 scripts/harvest_drought_geda.py --build        # слой в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) запрашивает карточку записи по API Zenodo и сверяет имя,
размер и md5 файла и лицензию с записанным в `sources/drought_geda.py`;
скачивает файл в `data/raw/geda/` (226 МБ, в репозиторий не идёт); печатает
оси, единицу и пропуски; проводит узлы через сито — рамка проекта, охват ERDA,
территория РИ/СССР — и печатает, сколько отсеяно и почему; разбирает
пробную выгрузку. Расхождение с записанным — остановка, а не подгонка.

`--compare-erda` сверяет GEDA с ERDA на их общих 4259 узлах: корреляция
рядов и сигма, которая в GEDA встречается так же часто, как засуха данной
силы в ERDA. Из этой сверки выведены порог и шкала слова в слое — с ней их
можно перепроверить на новом выпуске набора.

Права. CC BY 4.0: брать можно всё, ссылка на авторов и набор стоит в каждой
записи (и один раз на уровне слоя в GeoJSON).

Границы РИ/СССР берутся из `data/out/boundaries/state_borders.geojson`
(`scripts/harvest_cshapes.py --build`, лежит в репозитории). Без них сбор
останавливается: иначе в слой попали бы Китай и Монголия.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.geo import in_bbox
from histctx.io_formats import write_geojson, write_jsonl
from histctx.sources.drought import ERDA, YEAR_FROM, YEAR_TO, find_episodes
from histctx.sources.drought import load as load_erda
from histctx.sources.drought_geda import (
    DOI_URL, DROUGHT_ATLAS_GEDA, FILE_NAME, GEDA, RECORD_API, THRESHOLD, GedaError,
    Territory, agreement, cached, check_record, episodes_to_records, fetch_record,
    make_keep, open_netcdf, read_atlas, sigma_class,
)

CACHE = ROOT / "data" / "raw" / "geda"
ERDA_CACHE = ROOT / "data" / "cache" / "drought"
BORDERS = ROOT / "data" / "out" / "boundaries" / "state_borders.geojson"


def open_file(args) -> Path:
    if args.file:
        return args.file
    return cached(args.cache)


def load_layer(args):
    """Файл → сито узлов → атлас. Одно и то же для проверки и для сборки."""
    cube = open_netcdf(open_file(args))
    territory = Territory.load(args.borders)
    foreign = Territory.load(args.borders, others=True)
    atlas, reasons = read_atlas(cube, keep=make_keep(territory, foreign=foreign),
                                year_from=args.year_from, year_to=args.year_to)
    return cube, territory, atlas, reasons


def check(args) -> int:
    print(f"Запись на Zenodo: {DOI_URL}")
    if args.file:
        print(f"  файл задан руками ({args.file}) — карточку и md5 не сверяю")
    else:
        record = fetch_record()
        files = record.get("files") or []
        print(f"  API: {RECORD_API}; файлов {len(files)}, лицензия "
              f"{((record.get('metadata') or {}).get('license') or {}).get('id')}")
        problems = check_record(record)
        if problems:
            print("\nКарточка расходится с записанным в коде — сбор остановлен:",
                  file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            return 1
        path = cached(args.cache)
        print(f"  {FILE_NAME}: {path.stat().st_size} байт, размер и md5 сходятся")

    cube, territory, atlas, reasons = load_layer(args)
    print(f"\nФайл: {cube.comment}")
    print(f"  оси: годы {cube.years[0]}–{cube.years[-1]} ({len(cube.years)}), "
          f"широта {cube.lats[0]}…{cube.lats[-1]} ({len(cube.lats)}), "
          f"долгота {cube.lons[0]}…{cube.lons[-1]} ({len(cube.lons)}); единица — {cube.units}")
    print(f"  граница РИ/СССР: {len(territory)} периодов России из {args.borders.name}")

    print(f"\nУзлы рамки проекта за {args.year_from}–{args.year_to} годы:")
    for reason, count in reasons.most_common():
        print(f"  {count:>6}  {reason}")
    zones = collections.Counter(_zone(p.lat, p.lon) for p in atlas.points.values())
    for zone, count in zones.most_common():
        print(f"           {count:>6} — {zone}")

    total = len(atlas.points) * len(atlas.years)
    print(f"\nУзлов-лет в слое: {total}")
    for limit in sorted({THRESHOLD, args.threshold, -2.0, -3.0}):
        episodes = find_episodes(atlas, threshold=limit, year_from=args.year_from,
                                 year_to=args.year_to)
        dry = sum(len(e.values) for e in episodes)
        mark = "  ← порог" if limit == args.threshold else ""
        print(f"  ≤ {limit:+.1f}σ: узлов-лет {dry} ({100 * dry / max(total, 1):.2f}%), "
              f"эпизодов {len(episodes)}{mark}")

    episodes = find_episodes(atlas, threshold=args.threshold, year_from=args.year_from,
                             year_to=args.year_to)
    if not episodes:
        print("Ни одной засухи не отобрано: проверьте порог и годы.", file=sys.stderr)
        return 1
    by_century = collections.Counter((e.year_from - 1) // 100 + 1 for e in episodes)
    print("  по векам: " + ", ".join(f"{c} в. — {n}" for c, n in sorted(by_century.items())))
    kinds = collections.Counter(sigma_class(e.worst) for e in episodes)
    print("  по силе: " + ", ".join(f"{k} — {n}" for k, n in kinds.most_common()))
    years = collections.Counter(y for e in episodes for y in range(e.year_from, e.year_to + 1))
    print("  годы с наибольшим числом узлов: "
          + ", ".join(f"{y} ({n})" for y, n in years.most_common(10)))

    records = episodes_to_records(episodes[:5])
    print("\n  примеры:")
    for rec in records:
        print(f"    {rec.period_raw:>9}  {rec.lat:.2f},{rec.lon:.2f}  {rec.title}")
    print(f"\n  {records[0].summary}")

    if args.compare_erda:
        compare(args, cube)
    print("\nНабор на месте, оси и единица сходятся, сито работает — можно запускать --build.")
    return 0


def compare(args, cube) -> None:
    """GEDA против ERDA на общих узлах: из этого выведены порог и шкала словами."""
    erda = load_erda(ERDA, cache_dir=ERDA_CACHE, year_from=args.year_from,
                     year_to=args.year_to)
    inside, _ = read_atlas(cube, keep=lambda lat, lon: None if in_bbox(lat, lon, ERDA.bbox)
                           else "вне ERDA", year_from=args.year_from, year_to=args.year_to)
    by_place = {(round(p.lat, 2), round(p.lon, 2)): n for n, p in inside.points.items()}
    if inside.years != erda.years:
        raise GedaError("годы ERDA и GEDA в окне не совпадают — сравнивать нечего")
    pairs = []
    for number, point in erda.points.items():
        twin = by_place.get((round(point.lat, 2), round(point.lon, 2)))
        if twin is not None:
            pairs.append((erda.series[number], inside.series[twin]))
    got = agreement(pairs)
    print(f"\nСверка с ERDA за {args.year_from}–{args.year_to} годы: общих узлов {got.nodes} "
          f"из {len(erda.points)}, узлов-лет {got.pairs}")
    print(f"  корреляция рядов (медиана по узлам): {got.median_r:.2f}")
    for limit, (share, sigma, hit) in sorted(got.levels.items()):
        print(f"  ERDA ≤ {limit:+.0f}: {100 * share:.2f}% узлов-лет; в GEDA так же часто "
              f"≤ {sigma:+.2f}σ; совпало по узлу и году {100 * hit:.1f}%")


def build(args) -> int:
    _, _, atlas, reasons = load_layer(args)
    episodes = find_episodes(atlas, threshold=args.threshold, year_from=args.year_from,
                             year_to=args.year_to)
    records = episodes_to_records(episodes)
    if not records:
        print("Ничего не собрано: при таком пороге и окне лет засух не нашлось.",
              file=sys.stderr)
        return 1
    name = DROUGHT_ATLAS_GEDA.slug
    path = args.out / "geojson" / f"{name}.geojson"
    n = write_geojson(records, path, layer_title=DROUGHT_ATLAS_GEDA.title, hoist_shared=True)
    write_jsonl(records, args.out / "jsonl" / f"{name}.jsonl")
    print(f"Собрано {len(records)} записей, на карту пойдут {n}. Файл {path.name}, "
          f"{path.stat().st_size / 1e6:.1f} МБ")
    print(f"  узлов в слое: {reasons['в слое']}, годы {args.year_from}–{args.year_to}, "
          f"порог {args.threshold:+.1f}σ")
    print(f"  покрытие: {GEDA.extent}")
    return 0


def _zone(lat: float, lon: float) -> str:
    if lon > ERDA.bbox[3]:
        return "восточнее 62° в. д. (Сибирь, Дальний Восток, Казахстан, Средняя Азия)"
    if lon < ERDA.bbox[1]:
        return "западнее 22° в. д. (Царство Польское)"
    if lat < ERDA.bbox[0]:
        return "южнее 41° с. ш. (Закавказье, Закаспий)"
    return "севернее 71.5° с. ш."


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверка с Zenodo и пробный разбор, без записи слоя")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--compare-erda", action="store_true",
                    help="при проверке сверить GEDA с ERDA на общих узлах")
    ap.add_argument("--threshold", type=float, default=THRESHOLD,
                    help="порог засухи в сигмах (по умолчанию −2.5)")
    ap.add_argument("--year-from", type=int, default=YEAR_FROM)
    ap.add_argument("--year-to", type=int, default=YEAR_TO)
    ap.add_argument("--file", type=Path, default=None,
                    help=f"заранее скачанный {FILE_NAME} вместо сети")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда скачивается файл набора")
    ap.add_argument("--borders", type=Path, default=BORDERS,
                    help="границы государств CShapes (GeoJSON)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    if args.threshold >= 0:
        ap.error("порог засухи — отрицательная сигма, например −2.5")

    try:
        if args.check:
            code = check(args)
            if code or not args.build:
                return code
        return build(args)
    except GedaError as exc:
        print(f"GEDA: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Нет файла: {exc.filename}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
