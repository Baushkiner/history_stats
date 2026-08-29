"""Погодные аномалии: что считается выходящим за норму и как это попадает в слой.

Ряды здесь синтетические и намеренно простые: проверяется расчёт, а не
качество конкретного источника. Главное свойство — обычный год в слой не
попадает: иначе карта заполнится записями «в 1873 году была погода».
"""

from pathlib import Path

import pytest

from histctx.schema import SCOPE_REGION
from histctx.sources.weather import (
    WEATHER_REGIONS, WEATHER_STATIONS, Observation, WeatherError, find_anomalies,
    read_series, region_records, station_records,
)

ROOT = Path(__file__).resolve().parents[1]

NORMAL_T = {1: -10.0, 2: -9.0, 3: -3.0, 4: 5.0, 5: 12.0, 6: 17.0,
            7: 19.0, 8: 17.0, 9: 11.0, 10: 4.0, 11: -3.0, 12: -8.0}
NORMAL_P = {m: 50.0 for m in range(1, 13)}


def series(years, *, station="A", region="Самарская губерния", lat=53.2, lon=50.15,
           dry_years=(), hot_years=(), cold_winters=()):
    """Ровный ряд, в котором отдельные годы намеренно испорчены."""
    out = []
    for year in years:
        for month in range(1, 13):
            # Небольшой год-к-году разброс: без него σ ряда определяется одним
            # испорченным годом и любое отклонение выглядит исключительным.
            t = NORMAL_T[month] + ((year % 5) - 2) * 0.7
            p = NORMAL_P[month] * (1 + ((year % 7) - 3) * 0.05)
            if year in dry_years and month in (4, 5, 6, 7, 8):
                p = 12.0
            if year in hot_years and month in (6, 7, 8):
                t += 6.0
            if year in cold_winters and month in (12, 1, 2):
                t -= 9.0
            out.append(Observation(station_id=station, name="Станция", region=region,
                                   lat=lat, lon=lon, year=year, month=month, tavg=t, prcp=p))
    return out


YEARS = range(1880, 1911)


def test_dry_year_is_found():
    found = find_anomalies(series(YEARS, dry_years=(1891,)))
    assert 1891 in found
    assert found[1891][0].kind == "засуха"
    assert found[1891][0].z < 0


def test_normal_years_produce_nothing():
    """Год без отклонения — не событие: в слое ему делать нечего."""
    assert find_anomalies(series(YEARS)) == {}


def test_hot_summer_and_cold_winter_are_separate_kinds():
    kinds = {a.kind for year in find_anomalies(series(YEARS, hot_years=(1901,)))
             for a in find_anomalies(series(YEARS, hot_years=(1901,)))[year]}
    assert "жаркое лето" in kinds
    cold = find_anomalies(series(YEARS, cold_winters=(1893,)))
    assert cold and "суровая зима" in {a.kind for a in cold[1893]}


def test_short_series_gives_no_anomalies():
    """По пяти годам «норма» описывает эти пять лет, а не климат."""
    assert find_anomalies(series(range(1880, 1886), dry_years=(1884,))) == {}


def test_threshold_is_adjustable():
    """Порог задаётся вызывающим: на плотных рядах его приходится поднимать."""
    obs = series(YEARS, dry_years=(1891,))
    z = abs(find_anomalies(obs)[1891][0].z)
    assert find_anomalies(obs, threshold=z + 0.5) == {}


def test_small_deviation_is_not_a_drought():
    """Ровный ряд: самый сухой год выпадает по σ, но по величине это не засуха."""
    mild = [o for o in series(YEARS)]
    mild = [o.__class__(**{**o.__dict__, "prcp": o.prcp * 0.9})
            if o.year == 1891 and o.month in (4, 5, 6, 7, 8) else o for o in mild]
    assert 1891 not in find_anomalies(mild)


# --- записи единой схемы ---------------------------------------------------

def test_station_record_is_a_point_with_a_year():
    recs = station_records(series(YEARS, dry_years=(1891,)), source="тест")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.layer == WEATHER_STATIONS.slug
    assert (rec.year_from, rec.year_to) == (1891, 1891)
    assert rec.mappable and rec.usable
    assert rec.category == "засуха"
    assert rec.source_id == "A:1891"
    assert "мм" in rec.summary and "1891" in rec.summary


def test_station_without_coordinates_is_skipped():
    obs = [Observation(station_id="B", year=o.year, month=o.month, tavg=o.tavg, prcp=o.prcp)
           for o in series(YEARS, dry_years=(1891,))]
    assert station_records(obs, source="тест") == []


def test_station_outside_russia_is_skipped():
    obs = series(YEARS, dry_years=(1891,), lat=52.52, lon=13.40)
    assert station_records(obs, source="тест") == []
    assert station_records(obs, source="тест", require_bbox=False)


def test_region_record_is_territorial():
    obs = (series(YEARS, station="A", dry_years=(1891,))
           + series(YEARS, station="B", lat=53.4, lon=50.4, dry_years=(1891,)))
    recs = region_records(obs, source="тест")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.layer == WEATHER_REGIONS.slug
    assert rec.scope == SCOPE_REGION
    assert rec.regions == ["Самарская губерния"]
    assert not rec.has_point and rec.usable
    assert "осреднено по 2 станциям" in rec.summary


def test_single_station_does_not_speak_for_a_whole_province():
    assert region_records(series(YEARS, dry_years=(1891,)), source="тест") == []


def rescaled(observations, factor):
    """Тот же ряд, но станция суше: другое место, а не другая погода."""
    return [o.__class__(**{**o.__dict__, "prcp": o.prcp * factor}) for o in observations]


def test_a_station_that_appears_late_does_not_invent_a_drought():
    """Состав станций меняется — губернская норма от этого зависеть не должна.

    Сухая станция, открытая в 1906 году, роняет простое среднее по губернии
    вдвое, и вся вторая половина ряда становится «засухой». Погоды в этом нет:
    поменялось не небо, а список тех, кто мерил.
    """
    old = series(YEARS, station="A")
    new = rescaled(series(range(1906, 1911), station="B", lat=53.4, lon=50.4), 0.2)
    assert region_records(old + new, source="тест") == []


def test_real_drought_survives_the_correction():
    """Приведение к общей базе убирает разницу мест, а не отклонение года."""
    obs = (series(YEARS, station="A", dry_years=(1891,))
           + rescaled(series(YEARS, station="B", lat=53.4, lon=50.4, dry_years=(1891,)), 0.2))
    recs = region_records(obs, source="тест")
    assert [r.year_from for r in recs] == [1891]
    assert recs[0].category == "засуха"


def test_year_with_one_station_is_kept_but_marked():
    """Ничего не выбрасывается молча: за XIX век другой записи не будет вовсе."""
    obs = (series(YEARS, station="A", dry_years=(1891,))
           + series(range(1900, 1911), station="B", lat=53.4, lon=50.4))
    recs = region_records(obs, source="тест")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.year_from == 1891 and rec.confidence == "thin_coverage"
    assert "одна станция" in rec.summary
    assert rec.extra["stations"] == 1 and rec.extra["stations_total"] == 2


def test_station_count_is_the_one_of_that_year():
    """«Осреднено по 89 станциям» в 1844 году — неправда, если мерила одна."""
    obs = (series(YEARS, station="A", dry_years=(1891,))
           + series(YEARS, station="B", lat=53.4, lon=50.4, dry_years=(1891,))
           + series(range(1905, 1911), station="C", lat=53.5, lon=50.5))
    rec = region_records(obs, source="тест")[0]
    assert rec.extra["stations"] == 2 and rec.extra["stations_total"] == 3
    assert "осреднено по 2 станциям" in rec.summary


def test_source_and_license_reach_the_record():
    recs = station_records(series(YEARS, dry_years=(1891,)), source="meteo.ru",
                           url="http://meteo.ru/data", license="по условиям источника")
    assert recs[0].source == "meteo.ru"
    assert recs[0].url == "http://meteo.ru/data"
    assert recs[0].license == "по условиям источника"


# --- чтение приведённого ряда ----------------------------------------------

def write_csv(tmp_path, text):
    path = tmp_path / "series.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_read_series_with_column_mapping(tmp_path):
    path = write_csv(tmp_path, "СТ,ГОД,МЕС,Т,ОС\nМск,1891,7,21.5,10\n")
    obs = read_series(path, {"СТ": "station_id", "ГОД": "year", "МЕС": "month",
                             "Т": "tavg", "ОС": "prcp"})
    assert obs[0].station_id == "Мск" and obs[0].year == 1891
    assert obs[0].tavg == 21.5 and obs[0].prcp == 10.0


def test_missing_columns_stop_the_harvest(tmp_path):
    path = write_csv(tmp_path, "станция,температура\nМск,21.5\n")
    with pytest.raises(WeatherError) as exc:
        read_series(path)
    assert "--map" in str(exc.value)


def test_gaps_in_meteo_series_are_not_values(tmp_path):
    path = write_csv(tmp_path, "station_id,year,month,tavg,prcp\nA,1891,7,-9999,\n")
    obs = read_series(path)
    assert obs[0].tavg is None and obs[0].prcp is None


def test_rows_with_broken_dates_are_skipped_but_file_is_not(tmp_path):
    path = write_csv(tmp_path, "station_id,year,month,tavg\nA,,7,20\nA,1891,7,20\n")
    assert len(read_series(path)) == 1
