"""Погода как контекст факта: от ряда наблюдений к объяснению.

Зачем. Запись «умер в июле 1891 года» сама по себе ничего не объясняет.
Рядом же лежит факт: лето 1891 года в Поволжье было засушливым, осадков
выпало вдвое меньше нормы — отсюда неурожай, отсюда голод, отсюда всплеск
смертей в третьей части метрической книги. Погода — не украшение карты,
а причина половины того, что в этой книге записано.

Что здесь есть и чего нет. Модуль не ходит в сеть и ничего не скачивает:
он принимает **приведённый к общему виду ряд наблюдений** и превращает его
в записи единой схемы. Скачивание и разбор конкретного формата — дело
`scripts/harvest_weather.py`, и оно намеренно отделено: форматов у метеоданных
много, а логика «что считать засухой» одна.

Два слоя на выходе:

* `weather_stations` — точки: станция и год, когда там случилось что-то
  выходящее за норму. Привязка честная, до станции.
* `weather_regions` — территориальные записи: то же самое, усреднённое по
  губернии. Нужны, потому что станций до 1880-х годов единицы, а губерния
  у факта из метрики известна почти всегда.

Обычные годы в слой не идут. Год без аномалии — это шум: на карте он
вытеснит собой то, что действительно объясняет факт.
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..geo import in_bbox, valid_coords
from ..schema import SCOPE_REGION, LayerSpec, clean_text

WEATHER_STATIONS = LayerSpec(
    slug="weather_stations",
    title="Погодные аномалии по станциям",
    group="hardship",
    source="ряды метеонаблюдений, приведённые к общему виду",
    license="зависит от источника ряда — записывается при сборе",
    description=(
        "Годы, когда на станции было заметно суше, холоднее или дождливее нормы. "
        "Объясняет неурожай, падёж скота и всплеск смертности в метрических книгах."
    ),
    status="planned",
)

WEATHER_REGIONS = LayerSpec(
    slug="weather_regions",
    title="Погодные аномалии по губерниям",
    group="hardship",
    source="ряды метеонаблюдений, усреднённые по губернии",
    license="зависит от источника ряда — записывается при сборе",
    description=(
        "То же, что и по станциям, но осреднённое по губернии: до 1880-х годов "
        "станций единицы, а губерния у факта из метрики известна почти всегда."
    ),
    status="planned",
)

# Колонки приведённого ряда. Это и есть «общий формат» для погоды: любой
# источник — meteo.ru, GHCN, реанализ — сначала переводится в него.
COLUMNS = ("station_id", "name", "lat", "lon", "region", "year", "month", "tavg", "prcp")

# Сезоны в номерах месяцев. Зима считается по календарным месяцам одного
# года: январь и февраль текущего плюс декабрь его же. Для аномалии этого
# достаточно, а «зима 1890/91» в подписи всё равно пишется словами.
WINTER, SPRING, SUMMER = (12, 1, 2), (3, 4, 5), (6, 7, 8)
GROWING = (4, 5, 6, 7, 8)          # вегетационный период: он решает урожай

# Насколько год должен отличаться от нормы, чтобы попасть в слой.
# Порог в единицах стандартного отклонения ряда: 1.5σ — примерно один год
# из пятнадцати.
Z_THRESHOLD = 1.5

# Одного порога в сигмах мало. Отклонение в σ измеряет, насколько год
# необычен для этой станции, но ничего не говорит о величине: в ровном ряду
# самый сухой год всё равно окажется «выпадающим», даже если осадков было
# на четверть меньше обычного. Поэтому к каждому виду добавлен абсолютный
# порог — то, что человек и называет засухой или суровой зимой.
#   ratio — доля от нормы (для осадков), delta — отклонение в °C.
ABSOLUTE = {
    "засуха": ("ratio", 0.75),
    "дождливое лето": ("ratio", 1.30),
    "суровая зима": ("delta", -2.0),
    "холодное лето": ("delta", -1.5),
    "жаркое лето": ("delta", 1.5),
}

# Короче этого ряда норма считается недостоверной: по пяти годам «норма»
# описывает эти пять лет, а не климат.
MIN_YEARS_FOR_BASELINE = 15


class WeatherError(ValueError):
    """Ряд наблюдений не годится для расчёта."""


@dataclass(frozen=True)
class Observation:
    """Одно месячное наблюдение приведённого ряда."""

    station_id: str
    year: int
    month: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    name: Optional[str] = None
    region: Optional[str] = None
    tavg: Optional[float] = None      # средняя температура месяца, °C
    prcp: Optional[float] = None      # сумма осадков за месяц, мм


@dataclass(frozen=True)
class Anomaly:
    """Отклонение года от нормы по одному показателю."""

    kind: str            # «засуха», «суровая зима», ...
    z: float             # отклонение в единицах σ
    value: float
    norm: float
    unit: str

    @property
    def strength(self) -> str:
        a = abs(self.z)
        return "исключительная" if a >= 3 else "сильная" if a >= 2 else "заметная"


def read_series(path: Path, mapping: Optional[dict] = None) -> list[Observation]:
    """Читает приведённый ряд из CSV.

    `mapping` переименовывает колонки источника в наши: {"СТАНЦИЯ": "station_id"}.
    Строки с непонятной датой пропускаются молча — в метеорядах пропуски
    обычное дело, — а вот файл без нужных колонок останавливает сбор.
    """
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t ")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(fh, dialect=dialect))

    if not rows:
        raise WeatherError(f"{path.name}: пустой файл")

    renamed = [_rename(row, mapping or {}) for row in rows]
    missing = [c for c in ("station_id", "year", "month") if c not in renamed[0]]
    if missing:
        raise WeatherError(
            f"{path.name}: нет обязательных колонок {missing}; "
            f"в файле: {sorted(k for k in renamed[0] if k)}. "
            "Задайте соответствие колонок ключом --map."
        )

    out = []
    for row in renamed:
        year, month = _int(row.get("year")), _int(row.get("month"))
        if year is None or month is None or not 1 <= month <= 12:
            continue
        lat, lon = _float(row.get("lat")), _float(row.get("lon"))
        if not valid_coords(lat, lon):
            lat = lon = None
        out.append(Observation(
            station_id=clean_text(row.get("station_id")) or "?",
            name=clean_text(row.get("name")),
            region=clean_text(row.get("region")),
            lat=lat, lon=lon, year=year, month=month,
            tavg=_float(row.get("tavg")), prcp=_float(row.get("prcp")),
        ))
    if not out:
        raise WeatherError(f"{path.name}: ни одной строки с разобранной датой")
    return out


def find_anomalies(observations: Iterable[Observation], *,
                   threshold: float = Z_THRESHOLD,
                   min_years: int = MIN_YEARS_FOR_BASELINE) -> dict[int, list[Anomaly]]:
    """Считает норму по самому ряду и возвращает годы, выпавшие из неё.

    Норма берётся из ряда, а не из климатического периода 1961–1990: наш
    интерес — 1800–1960 годы, и норма, посчитанная по более поздним данным,
    сдвинула бы все оценки. Плата за это — требование к длине ряда.
    """
    by_year: dict[int, dict[int, Observation]] = {}
    for obs in observations:
        by_year.setdefault(obs.year, {})[obs.month] = obs
    if len(by_year) < min_years:
        return {}

    series = {
        "засуха": _season_series(by_year, GROWING, "prcp", how="sum"),
        "дождливое лето": _season_series(by_year, SUMMER, "prcp", how="sum"),
        "суровая зима": _season_series(by_year, WINTER, "tavg", how="mean"),
        "холодное лето": _season_series(by_year, SUMMER, "tavg", how="mean"),
        "жаркое лето": _season_series(by_year, SUMMER, "tavg", how="mean"),
    }
    # Знак: у засухи, суровой зимы и холодного лета аномалия отрицательная.
    direction = {"засуха": -1, "суровая зима": -1, "холодное лето": -1,
                 "дождливое лето": +1, "жаркое лето": +1}
    units = {"засуха": "мм", "дождливое лето": "мм",
             "суровая зима": "°C", "холодное лето": "°C", "жаркое лето": "°C"}

    out: dict[int, list[Anomaly]] = {}
    for kind, values in series.items():
        if len(values) < min_years:
            continue
        norm = statistics.fmean(values.values())
        sigma = statistics.pstdev(values.values())
        if sigma <= 0:
            continue
        for year, value in values.items():
            z = (value - norm) / sigma
            if math.copysign(1, z) != direction[kind] or abs(z) < threshold:
                continue
            if not _is_big_enough(kind, value, norm):
                continue
            out.setdefault(year, []).append(
                Anomaly(kind=kind, z=round(z, 2), value=round(value, 1),
                        norm=round(norm, 1), unit=units[kind])
            )
    for year in out:
        out[year].sort(key=lambda a: -abs(a.z))
    return out


def station_records(observations: Iterable[Observation], *, source: str, url: Optional[str] = None,
                    license: Optional[str] = None, require_bbox: bool = True,
                    threshold: float = Z_THRESHOLD) -> list:
    """Точечный слой: станция и год с аномалией."""
    by_station: dict[str, list[Observation]] = {}
    for obs in observations:
        by_station.setdefault(obs.station_id, []).append(obs)

    out = []
    for station_id, rows in by_station.items():
        point = next((o for o in rows if o.lat is not None), None)
        if point is None:
            continue
        if require_bbox and not in_bbox(point.lat, point.lon):
            continue
        place = point.name or station_id
        for year, anomalies in sorted(find_anomalies(rows, threshold=threshold).items()):
            out.append(WEATHER_STATIONS.new_record(
                title=f"{anomalies[0].kind.capitalize()} {year} года: {place}",
                category=anomalies[0].kind,
                lat=point.lat, lon=point.lon,
                place_text=place,
                region=point.region,
                year_from=year, year_to=year,
                date_precision="year",
                period_raw=str(year),
                summary=_summary(place, year, anomalies),
                source=source, license=license or WEATHER_STATIONS.license, url=url,
                source_id=f"{station_id}:{year}",
                extra={"anomalies": [a.__dict__ for a in anomalies]},
            ))
    return out


def region_records(observations: Iterable[Observation], *, source: str, url: Optional[str] = None,
                   license: Optional[str] = None, min_stations: int = 2,
                   threshold: float = Z_THRESHOLD) -> list:
    """Территориальный слой: губерния и год с аномалией.

    Губерния берётся из самого ряда, а не из полигонов: границы в проекте
    служат подложкой карты, и тянуть ради усреднения геометрию незачем.
    """
    by_region: dict[str, list[Observation]] = {}
    for obs in observations:
        if obs.region:
            by_region.setdefault(obs.region, []).append(obs)

    out = []
    for region, rows in sorted(by_region.items()):
        stations = {o.station_id for o in rows}
        if len(stations) < min_stations:
            continue
        for year, anomalies in sorted(find_anomalies(_average_by_month(rows),
                                                     threshold=threshold).items()):
            out.append(WEATHER_REGIONS.new_record(
                title=f"{anomalies[0].kind.capitalize()} {year} года: {region}",
                category=anomalies[0].kind,
                scope=SCOPE_REGION,
                place_text=region,
                regions=[region],
                year_from=year, year_to=year,
                date_precision="year",
                period_raw=str(year),
                summary=_summary(region, year, anomalies, stations=len(stations)),
                source=source, license=license or WEATHER_REGIONS.license, url=url,
                source_id=f"{region}:{year}",
                extra={"anomalies": [a.__dict__ for a in anomalies], "stations": len(stations)},
            ))
    return out


def _is_big_enough(kind: str, value: float, norm: float) -> bool:
    """Отсекает «аномалии», ничтожные по величине: ровный ряд не даёт засухи."""
    how, limit = ABSOLUTE[kind]
    if how == "ratio":
        if norm <= 0:
            return False
        return value <= limit * norm if limit < 1 else value >= limit * norm
    return value - norm <= limit if limit < 0 else value - norm >= limit


def _average_by_month(rows: list[Observation]) -> list[Observation]:
    """Сводит несколько станций губернии в один ряд помесячных средних."""
    buckets: dict[tuple[int, int], list[Observation]] = {}
    for obs in rows:
        buckets.setdefault((obs.year, obs.month), []).append(obs)
    out = []
    for (year, month), group in buckets.items():
        out.append(Observation(
            station_id=group[0].region or "регион",
            region=group[0].region,
            year=year, month=month,
            tavg=_mean([o.tavg for o in group]),
            prcp=_mean([o.prcp for o in group]),
        ))
    return out


def _season_series(by_year: dict, months: tuple, field: str, *, how: str) -> dict[int, float]:
    """Сезонный показатель по годам; год без полного сезона пропускается."""
    out = {}
    for year, by_month in by_year.items():
        values = [getattr(by_month[m], field) for m in months if m in by_month]
        values = [v for v in values if v is not None]
        if len(values) < len(months):
            continue
        out[year] = sum(values) if how == "sum" else statistics.fmean(values)
    return out


def _summary(place: str, year: int, anomalies: list[Anomaly], stations: int | None = None) -> str:
    lead = anomalies[0]
    words = {
        "засуха": f"осадков за апрель–август {lead.value} мм при норме {lead.norm} мм",
        "дождливое лето": f"осадков за лето {lead.value} мм при норме {lead.norm} мм",
        "суровая зима": f"средняя температура зимы {lead.value} °C при норме {lead.norm} °C",
        "холодное лето": f"средняя температура лета {lead.value} °C при норме {lead.norm} °C",
        "жаркое лето": f"средняя температура лета {lead.value} °C при норме {lead.norm} °C",
    }
    head = f"{place}, {year} год: {lead.strength} {lead.kind} — {words[lead.kind]}"
    extra = []
    if len(anomalies) > 1:
        extra.append("в том же году " + ", ".join(a.kind for a in anomalies[1:]))
    if stations:
        extra.append(f"осреднено по {stations} станциям губернии")
    tail = ("Для родословной это объяснение неурожая, падежа скота и всплеска "
            "смертности в метрической книге за этот и следующий год.")
    return "; ".join([head, *extra]) + ". " + tail


def _rename(row: dict, mapping: dict) -> dict:
    return {mapping.get(k, mapping.get((k or "").strip(), k)): v for k, v in row.items()}


def _mean(values) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return statistics.fmean(clean) if clean else None


def _int(value) -> Optional[int]:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _float(value) -> Optional[float]:
    text = str(value).strip() if value is not None else ""
    # В метеорядах пропуск часто пишут как -9999, 9999 или пустую строку.
    if not text or text in {"-9999", "9999", "-999.9", "NA", "NaN"}:
        return None
    try:
        out = float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None
    return None if abs(out) >= 999 else out
