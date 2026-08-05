#!/usr/bin/env python3
"""Погодные аномалии из ряда метеонаблюдений.

    # что в файле и разбирается ли он
    python3 scripts/harvest_weather.py --probe data/raw/meteo/moscow.csv \
        --map "STATION=station_id,YEAR=year,MONTH=month,TAVG=tavg,PRCP=prcp"

    # собрать слои
    python3 scripts/harvest_weather.py --build data/raw/meteo/*.csv \
        --source "ВНИИГМИ-МЦД, meteo.ru" --url http://meteo.ru/data

Скрипт не ходит в сеть: он принимает уже скачанные ряды. Разделение
намеренное — форматов у метеоданных много, а «что считать засухой» одно
и живёт в `histctx.sources.weather`.

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.io_formats import write_geojson, write_records_json  # noqa: E402
from histctx.sources.weather import (  # noqa: E402
    MIN_YEARS_FOR_BASELINE, WEATHER_REGIONS, WEATHER_STATIONS, Z_THRESHOLD,
    WeatherError, find_anomalies, read_series, region_records, station_records,
)


def parse_map(text: str | None) -> dict:
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
    return 0


def build(paths: list[Path], mapping: dict, *, source: str, url: str | None,
          license: str | None, out_dir: Path, threshold: float) -> int:
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
        n = write_geojson(points, out_dir / "geojson" / f"{WEATHER_STATIONS.slug}.geojson",
                          layer_title=WEATHER_STATIONS.title)
        print(f"  geojson/{WEATHER_STATIONS.slug}.geojson: {n} точек")
    if regions:
        write_records_json(regions, out_dir / f"{WEATHER_REGIONS.slug}.json",
                           title=WEATHER_REGIONS.title)
        print(f"  {WEATHER_REGIONS.slug}.json: {len(regions)} записей по губерниям")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", nargs="+", type=Path, metavar="FILE")
    ap.add_argument("--build", nargs="+", type=Path, metavar="FILE")
    ap.add_argument("--map", dest="mapping", help="соответствие колонок: «ГОД=year,МЕСЯЦ=month»")
    ap.add_argument("--source", default="ряд метеонаблюдений",
                    help="как назвать источник в записях — попадёт в выгрузку")
    ap.add_argument("--url", default=None, help="ссылка на источник ряда")
    ap.add_argument("--license", default=None, help="права на ряд")
    ap.add_argument("--threshold", type=float, default=Z_THRESHOLD,
                    help="порог аномалии в единицах σ")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.probe and not args.build:
        ap.error("укажите --probe или --build")

    mapping = parse_map(args.mapping)
    try:
        if args.probe:
            return probe(args.probe, mapping, args.threshold)
        return build(args.build, mapping, source=args.source, url=args.url,
                     license=args.license, out_dir=args.out, threshold=args.threshold)
    except WeatherError as exc:
        print(f"Ряд не разобран: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Нет файла: {exc.filename}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
