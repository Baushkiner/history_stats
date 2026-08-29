#!/usr/bin/env python3
"""Погодные аномалии из ряда метеонаблюдений.

    # забрать месячные ряды GHCN с NOAA и привести их к общему виду
    python3 scripts/harvest_weather.py --fetch

    # что в файле и разбирается ли он
    python3 scripts/harvest_weather.py --probe data/raw/meteo/ghcn.csv

    # собрать слои
    python3 scripts/harvest_weather.py --build data/raw/meteo/ghcn.csv \
        --source "GHCN-M v4, NOAA NCEI" --license "данные NOAA — общественное достояние"

Три шага — три разные работы, и они намеренно разделены. `--fetch` знает про
GHCN и ни про что больше; `--probe` и `--build` не знают ни про какой источник
и принимают любой ряд, приведённый к общему виду. Форматов у метеоданных
много, а «что считать засухой» одно — оно живёт в `histctx.sources.weather`
и от источника не зависит.

Общий формат ряда (колонки; порядок неважен, имена задаются ключом --map):

    station_id  код станции
    name        название станции
    lat, lon    координаты станции
    region      губерния или область — по ней строится территориальный слой
    year, month год и месяц наблюдения
    tavg        средняя температура месяца, °C
    prcp        сумма осадков за месяц, мм
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from _paths import ROOT

from histctx.io_formats import write_geojson, write_records_json
from histctx.sources import ghcn
from histctx.sources.weather import (
    MIN_YEARS_FOR_BASELINE, WEATHER_REGIONS, WEATHER_STATIONS, Z_THRESHOLD,
    WeatherError, find_anomalies, read_series, region_records, station_records,
)

# Куда ложатся скачанные архивы и приведённый ряд. В репозиторий они не идут:
# архивы GHCN весят сотни мегабайт и пересобираются одной командой.
METEO_DIR = ROOT / "data" / "raw" / "meteo"
SERIES_PATH = METEO_DIR / "ghcn.csv"


def parse_map(text: Optional[str]) -> dict:
    """«ГОД=year,МЕСЯЦ=month» -> {'ГОД': 'year', 'МЕСЯЦ': 'month'}."""
    if not text:
        return {}
    out = {}
    for pair in text.split(","):
        src, _, dst = pair.partition("=")
        if not dst:
            raise SystemExit(f"--map: ожидалось «колонка=поле», получено {pair!r}")
        out[src.strip()] = dst.strip()
    return out


def parse_years(text: str) -> tuple[int, int]:
    """«1800-1960» -> (1800, 1960)."""
    first, _, last = text.partition("-")
    try:
        years = (int(first), int(last))
    except ValueError:
        # `from None`: читателю нужен разбор ключа, а не питоновский ValueError.
        raise SystemExit(f"--years: ожидалось «1800-1960», получено {text!r}") from None
    if years[0] > years[1]:
        raise SystemExit(f"--years: {years[0]} позже {years[1]}")
    return years


def fetch(series_path: Path, *, cache_dir: Path, years: tuple[int, int],
          provinces_path: Optional[Path], flavour: str, refresh: bool) -> int:
    """Забирает месячные ряды GHCN и пишет их в приведённом виде."""
    provinces = None
    if provinces_path is not None:
        provinces = ghcn.Provinces.load(provinces_path)
        print(f"губернии: {len(provinces)} полигонов из {provinces_path}")
    else:
        print("губернии не подставляются: слой по губерниям не построится")

    rows, stats = ghcn.collect(cache_dir, years=years, provinces=provinces,
                               flavour=flavour, refresh=refresh, log=print)
    if not rows:
        print("Из GHCN не пришло ни одного наблюдения — сбор остановлен.", file=sys.stderr)
        return 1

    written = ghcn.write_series(rows, series_path)
    print(f"\n{series_path}: {written} наблюдений")
    print(f"  станций: {stats['stations']}, из них с губернией: "
          f"{stats['stations_with_region']} в {stats['regions']} губерниях")
    print(f"  наблюдений с губернией: {stats['rows_with_region']}")
    print(f"  температура: {stats['tavg']}, осадки: {stats['prcp']}")
    print(f"  права: {ghcn.LICENSE}")
    print(f"  как ссылаться: {ghcn.CITATION}")
    # Права у погоды записываются при сборе, а не в спецификации слоя: ряд
    # может быть любой. Поэтому команда печатается целиком — вместе с тем,
    # что мы про права GHCN выяснили.
    print("\nДальше — проба и сборка:\n"
          f"  python3 scripts/harvest_weather.py --probe {series_path}\n"
          f"  python3 scripts/harvest_weather.py --build {series_path} \\\n"
          f'      --source "{ghcn.SOURCE}" \\\n'
          f'      --url "{ghcn.PRODUCT_URL}" \\\n'
          f'      --license "{ghcn.LICENSE}"')
    return 0


def probe(paths: list[Path], mapping: dict, threshold: float) -> int:
    for path in paths:
        print(f"\n{path}")
        obs = read_series(path, mapping)
        years = sorted({o.year for o in obs})
        stations = sorted({o.station_id for o in obs})
        regions = sorted({o.region for o in obs if o.region})
        print(f"  наблюдений: {len(obs)}")
        print(f"  станций: {len(stations)} ({', '.join(stations[:5])}"
              f"{'…' if len(stations) > 5 else ''})")
        print(f"  годы: {years[0]}–{years[-1]}, всего {len(years)}")
        named = ", ".join(regions[:5]) or "нет — территориальный слой не построится"
        print(f"  губернии в файле: {len(regions)} ({named})")
        with_t = sum(1 for o in obs if o.tavg is not None)
        with_p = sum(1 for o in obs if o.prcp is not None)
        print(f"  с температурой: {with_t}, с осадками: {with_p}")
        if len(years) < MIN_YEARS_FOR_BASELINE:
            print(f"  ряд короче {MIN_YEARS_FOR_BASELINE} лет — норма по нему недостоверна, "
                  "аномалии считаться не будут")
            continue
        anomalies = find_anomalies(obs, threshold=threshold)
        print(f"  лет с аномалией: {len(anomalies)}")
        for year, items in sorted(anomalies.items())[:5]:
            print(f"    {year}: " + ", ".join(f"{a.kind} ({a.z:+.1f}σ)" for a in items))
        if len(stations) > 1:
            # Проба считает по файлу целиком, а в файле со многими станциями
            # состав станций год от года меняется — и ранние годы выпадают
            # из «нормы» просто потому, что тогда мерила другая треть страны.
            # В слое норма считается по каждой станции отдельно; здесь это
            # обзор формата, а не результат сбора.
            print("    (по файлу целиком: в слое норма считается по каждой станции "
                  "и по каждой губернии отдельно)")
    return 0


def build(paths: list[Path], mapping: dict, *, source: str, url: Optional[str],
          license: Optional[str], out_dir: Path, threshold: float) -> int:
    observations = []
    for path in paths:
        observations += read_series(path, mapping)
    print(f"Наблюдений прочитано: {len(observations)} из {len(paths)} файлов")

    points = station_records(observations, source=source, url=url, license=license,
                             threshold=threshold)
    regions = region_records(observations, source=source, url=url, license=license,
                             threshold=threshold)
    if not points and not regions:
        print("Аномалий не найдено: ряд короткий или без сезонных данных.", file=sys.stderr)
        return 1

    if points:
        # Слой станций — тысячи точек, у которых слой, источник и права
        # одинаковы. Вынесенные на уровень коллекции, они экономят треть файла;
        # для слоя, который никому ещё не отдавали, это можно решить сразу.
        n = write_geojson(points, out_dir / "geojson" / f"{WEATHER_STATIONS.slug}.geojson",
                          layer_title=WEATHER_STATIONS.title, hoist_shared=True)
        print(f"  geojson/{WEATHER_STATIONS.slug}.geojson: {n} точек")
    if regions:
        write_records_json(regions, out_dir / f"{WEATHER_REGIONS.slug}.json",
                           title=WEATHER_REGIONS.title)
        print(f"  {WEATHER_REGIONS.slug}.json: {len(regions)} записей по губерниям")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true",
                    help="забрать месячные ряды GHCN с NOAA и привести их к общему виду")
    ap.add_argument("--probe", nargs="+", type=Path, metavar="FILE")
    ap.add_argument("--build", nargs="+", type=Path, metavar="FILE")
    ap.add_argument("--map", dest="mapping", help="соответствие колонок: «ГОД=year,МЕСЯЦ=month»")
    ap.add_argument("--series", type=Path, default=SERIES_PATH,
                    help="куда положить приведённый ряд GHCN")
    ap.add_argument("--cache", type=Path, default=METEO_DIR,
                    help="где держать скачанные архивы GHCN")
    ap.add_argument("--years", default=f"{ghcn.YEARS[0]}-{ghcn.YEARS[1]}",
                    help="окно лет для ряда GHCN: норма считается по нему же")
    ap.add_argument("--regions", type=Path, default=ROOT / ghcn.PROVINCES_PATH,
                    help="полигоны губерний, по которым станция получает губернию")
    ap.add_argument("--no-regions", action="store_true",
                    help="собрать ряд без губерний: слой по губерниям тогда не построится")
    ap.add_argument("--adjusted", action="store_true",
                    help="брать выровненный по соседям ряд температуры (qcf) вместо измеренного")
    ap.add_argument("--refresh", action="store_true",
                    help="перекачать архивы GHCN, даже если они уже скачаны")
    ap.add_argument("--source", default="ряд метеонаблюдений",
                    help="как назвать источник в записях — попадёт в выгрузку")
    ap.add_argument("--url", default=None, help="ссылка на источник ряда")
    ap.add_argument("--license", default=None, help="права на ряд")
    ap.add_argument("--threshold", type=float, default=Z_THRESHOLD,
                    help="порог аномалии в единицах σ")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.fetch and not args.probe and not args.build:
        ap.error("укажите --fetch, --probe или --build")

    mapping = parse_map(args.mapping)
    try:
        if args.fetch:
            return fetch(args.series, cache_dir=args.cache, years=parse_years(args.years),
                         provinces_path=None if args.no_regions else args.regions,
                         flavour="qcf" if args.adjusted else "qcu", refresh=args.refresh)
        if args.probe:
            return probe(args.probe, mapping, args.threshold)
        return build(args.build, mapping, source=args.source, url=args.url,
                     license=args.license, out_dir=args.out, threshold=args.threshold)
    except ghcn.GhcnError as exc:
        print(f"GHCN не забрался: {exc}", file=sys.stderr)
        return 1
    except WeatherError as exc:
        print(f"Ряд не разобран: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Нет файла: {exc.filename}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
