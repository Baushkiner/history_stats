"""Разбор форматов GHCN: что мы берём из NOAA и чего не берём.

Сети здесь нет и быть не должно: строки GHCN собираются теми же правилами
фиксированной ширины, что описаны в readme набора, и проверяется разбор,
а не доступность NOAA. Правила ширины вынесены в две вспомогательные
функции — если NOAA поменяет формат, эти функции и станут местом правки.
"""

import json
from pathlib import Path

import pytest

from histctx.sources import ghcn
from histctx.sources.weather import COLUMNS, read_series

ROOT = Path(__file__).resolve().parents[1]


def inv_line(station_id, lat, lon, name, elev=100.0):
    """Строка реестра станций: ID 1-11, широта 13-20, долгота 22-30, имя 39-68."""
    return (f"{station_id:<11} {lat:>8.4f} {lon:>9.4f} {elev:>6.1f} {name:<30}")


def dat_line(station_id, year, values, element="TAVG", qc_flags=None):
    """Строка данных температуры: 12 значений по 5 знаков, за каждым три флага."""
    flags = qc_flags or [" "] * 12
    out = f"{station_id:<11}{year:04d}{element}"
    for value, qc in zip(values, flags):
        out += f"{value:>5d} {qc}k"
    return out


def prcp_line(station_id, name, lat, lon, year, month, value, qc=" "):
    """Строка файла осадков: та же фиксированная ширина, что в readme набора."""
    return (f"{station_id:<11}," + f'"{name}"'.rjust(40) + ","
            + f"{lat:>9.4f}," + f"{lon:>10.4f}," + f"{-23.0:>8.1f},"
            + f"{year:04d}{month:02d}," + f"{value:>6d}, ,{qc},R,098994")


SAMARA = inv_line("RSM00028900", 53.2000, 50.1500, "SAMARA")
BERLIN = inv_line("GMM00010384", 52.5200, 13.4000, "BERLIN_TEMPELHOF")
BEIJING = inv_line("CHM00054511", 39.9300, 116.2800, "BEIJING")


# --- реестр станций и отбор по границам ------------------------------------

def test_inventory_is_read_by_column_positions():
    stations = ghcn.parse_inventory([SAMARA])
    station = stations["RSM00028900"]
    assert (station.lat, station.lon) == (53.2, 50.15)
    assert station.name == "Samara"


def test_broken_inventory_line_does_not_stop_the_rest():
    """В реестре 27 тысяч станций: одна битая строка — не повод бросать сбор."""
    stations = ghcn.parse_inventory(["мусор", SAMARA])
    assert list(stations) == ["RSM00028900"]


def test_only_stations_of_the_empire_are_taken():
    """Отбор идёт по стране и по общей рамке охвата, а не по одной из них."""
    stations = ghcn.parse_inventory([SAMARA, BERLIN, BEIJING])
    assert stations["RSM00028900"].in_empire
    assert not stations["GMM00010384"].in_empire        # не та страна
    assert not stations["CHM00054511"].in_empire        # в рамку попадает, но Китай


def test_finland_and_poland_are_inside_the_empire():
    """До 1917 года это губернии империи, и метрики оттуда в родословных обычны."""
    stations = ghcn.parse_inventory([
        inv_line("FIE00142080", 60.1700, 24.9400, "HELSINKI"),
        inv_line("PLM00012375", 52.1600, 20.9700, "WARSZAWA"),
    ])
    assert all(station.in_empire for station in stations.values())


# --- температура -----------------------------------------------------------

def tavg_stations():
    return ghcn.parse_inventory([SAMARA])


def test_tavg_values_are_hundredths_of_a_degree():
    line = dat_line("RSM00028900", 1891, [-1000] + [2050] * 11)
    readings = list(ghcn.parse_tavg([line], stations=tavg_stations()))
    assert readings[0].value == -10.0 and readings[1].value == 20.5
    assert len(readings) == 12


def test_missing_and_flagged_values_are_not_values():
    """Пропуск и забракованное контролем качества значением не считаются."""
    values = [ghcn.MISSING] + [2050] * 11
    flags = [" ", "O"] + [" "] * 10          # O — статистический выброс
    line = dat_line("RSM00028900", 1891, values, qc_flags=flags)
    readings = list(ghcn.parse_tavg([line], stations=tavg_stations()))
    assert [r.month for r in readings] == list(range(3, 13))


def test_years_outside_the_window_are_not_read():
    """Норма считается по самому ряду: потепление последних десятилетий её сдвинет."""
    lines = [dat_line("RSM00028900", year, [500] * 12) for year in (1891, 1995)]
    readings = list(ghcn.parse_tavg(lines, stations=tavg_stations()))
    assert {r.year for r in readings} == {1891}


def test_other_stations_and_other_elements_are_skipped():
    lines = [dat_line("RSM00028900", 1891, [500] * 12, element="TMAX"),
             dat_line("GMM00010384", 1891, [500] * 12)]
    assert list(ghcn.parse_tavg(lines, stations=tavg_stations())) == []


# --- осадки ----------------------------------------------------------------

def test_prcp_values_are_tenths_of_a_millimetre():
    line = prcp_line("RSM00034880", "ASTRAKHAN'", 46.27, 48.03, 1891, 7, 1029)
    (station, reading), = ghcn.parse_prcp([line])
    assert reading.value == 102.9
    assert (reading.year, reading.month) == (1891, 7)
    assert station.name == "Astrakhan'" and station.lat == 46.27


def test_trace_precipitation_is_zero_and_not_a_gap():
    """«След осадков» — это ноль с оговоркой: дождь был, измерить нечего."""
    line = prcp_line("RSM00034880", "ASTRAKHAN'", 46.27, 48.03, 1891, 7, ghcn.TRACE)
    (_, reading), = ghcn.parse_prcp([line])
    assert reading.value == 0.0


def test_prcp_gaps_and_flagged_values_are_dropped():
    lines = [prcp_line("RSM00034880", "ASTRAKHAN'", 46.27, 48.03, 1891, 7, ghcn.MISSING),
             prcp_line("RSM00034880", "ASTRAKHAN'", 46.27, 48.03, 1891, 8, 1029, qc="O")]
    assert list(ghcn.parse_prcp(lines)) == []


def test_line_cut_before_the_quality_flag_is_dropped():
    """Обрезанная строка не должна читаться как выдержавшая контроль качества.

    Флаг стоит на 99-м знаке, значение — раньше. Строка, оборванная между
    ними, даёт значение и пустой флаг: по виду — проверенное измерение,
    на деле — обрывок файла.
    """
    line = prcp_line("RSM00034880", "ASTRAKHAN'", 46.27, 48.03, 1891, 7, 1029)
    cut = line[:98]
    assert len(cut) > 96, "обрезаем именно там, где значение уже прочитано, а флаг ещё нет"
    assert ghcn.to_int(cut[90:96]) == 1029
    assert list(ghcn.parse_prcp([cut])) == []


def test_comma_inside_the_station_name_does_not_shift_columns():
    """Файл выглядит как CSV, но по readme это фиксированная ширина.

    Разбор по запятым сломался бы ровно здесь — и сломался бы молча, сдвинув
    год и значение на колонку.
    """
    line = prcp_line("RSM00028900", "SAMARA, VOLGA", 53.2, 50.15, 1891, 7, 500)
    (station, reading), = ghcn.parse_prcp([line])
    assert station.name == "Samara, Volga"
    assert (reading.year, reading.month, reading.value) == (1891, 7, 50.0)


# --- губерния по координате ------------------------------------------------

def province_file(tmp_path, name="Самарская губерния"):
    """Квадрат вокруг Самары с дыркой посередине — дырка проверяет разбор колец."""
    square = [[[49.0, 52.0], [51.0, 52.0], [51.0, 54.0], [49.0, 54.0], [49.0, 52.0]]]
    hole = [[49.9, 52.9], [50.1, 52.9], [50.1, 53.1], [49.9, 53.1], [49.9, 52.9]]
    payload = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {ghcn.PROVINCE_NAME_FIELD: name},
        "geometry": {"type": "Polygon", "coordinates": square + [hole]},
    }]}
    path = tmp_path / "provinces.geojson"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_province_is_found_by_coordinates(tmp_path):
    provinces = ghcn.Provinces.load(province_file(tmp_path))
    assert provinces.region_for(53.2, 50.15) == "Самарская губерния"
    assert provinces.region_for(53.0, 50.0) is None      # в дырке
    assert provinces.region_for(55.75, 37.6) is None     # за рамкой


def test_two_halves_of_one_province_are_one_province(tmp_path):
    """«Тифлисская губерния вкл. Закатальский округ» и «без» — одна губерния.

    В наборе переписи это два наложенных полигона. Оговорка нужна карте,
    а усреднению погоды она разрезала бы губернию надвое.
    """
    path = province_file(tmp_path, name="Тифлисская губерния вкл. Закатальский округ")
    provinces = ghcn.Provinces.load(path)
    assert provinces.region_for(53.2, 50.15) == "Тифлисская губерния"


def test_missing_boundaries_say_what_to_do(tmp_path):
    with pytest.raises(ghcn.GhcnError) as exc:
        ghcn.Provinces.load(tmp_path / "нет-такого.geojson")
    assert "--no-regions" in str(exc.value)


# --- приведённый ряд -------------------------------------------------------

def test_series_row_joins_temperature_and_precipitation(tmp_path):
    """Температура и осадки одной станции сходятся в одну строку ряда.

    Идентификатор станции у обоих наборов GHCN общий — сопоставлять их по
    координатам не нужно, и это главная причина, почему взяты именно они.
    """
    stations = tavg_stations()
    readings = [
        ghcn.Reading("RSM00028900", 1891, 7, "tavg", 21.5),
        ghcn.Reading("RSM00028900", 1891, 7, "prcp", 10.0),
        ghcn.Reading("RSM00028900", 1891, 8, "prcp", 12.0),
    ]
    rows = ghcn.series_rows(readings, stations,
                            provinces=ghcn.Provinces.load(province_file(tmp_path)))
    assert [row["month"] for row in rows] == [7, 8]
    assert rows[0]["tavg"] == 21.5 and rows[0]["prcp"] == 10.0
    assert rows[1]["tavg"] == ""            # температуры за август нет — и не выдумываем
    assert rows[0]["region"] == "Самарская губерния"


def test_written_series_is_read_back_by_the_common_reader(tmp_path):
    """Выход сборщика — обычный приведённый ряд: `--probe` и `--build` про GHCN не знают."""
    rows = ghcn.series_rows(
        [ghcn.Reading("RSM00028900", 1891, 7, "tavg", 21.5),
         ghcn.Reading("RSM00028900", 1891, 7, "prcp", 10.0)],
        tavg_stations())
    path = tmp_path / "ghcn.csv"
    assert ghcn.write_series(rows, path) == 1
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLUMNS)

    observations = read_series(path)
    assert observations[0].station_id == "RSM00028900"
    assert observations[0].tavg == 21.5 and observations[0].prcp == 10.0
    assert observations[0].region is None


# --- адрес архива осадков --------------------------------------------------

def test_newest_archive_is_taken_from_the_listing():
    """Постоянной ссылки «latest» у осадков нет — имя архива несёт дату сборки."""
    listing = ('<a href="..">Parent</a>'
               '<a href="ghcn-m_v4.00.00_prcp_s16970101_e20260630_c20260701.tar.gz">a</a>'
               '<a href="ghcn-m_v4.00.00_prcp_s16970101_e20260731_c20260804.tar.gz">b</a>')
    assert ghcn.newest_archive(listing).endswith("_c20260804.tar.gz")


def test_empty_listing_stops_the_harvest():
    with pytest.raises(ghcn.GhcnError):
        ghcn.newest_archive("<html>ничего похожего на архив</html>")
