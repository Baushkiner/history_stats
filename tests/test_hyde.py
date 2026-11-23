"""Оценки HYDE по уездам: окно сетки, заливка полигонов, записи.

Сети в тестах нет. Сетка набора — 4320 × 2160 клеток; образец собирается
здесь же: нули и одна строка со значениями, шапка — как в файлах набора.
"""

import json

import numpy as np
import pytest

from histctx.sources.hyde import (
    ARCHIVE_ID, ARCHIVE_NAME, ARCHIVE_SIZE, CELL, COL0, LAT_MAX, LICENSE_NAME, LON_MIN, N_COLS,
    N_ROWS, NCOLS, NROWS, POPULATION_HYDE, ROW0, YEARS, Estimate, HydeError, Unit, aggregate,
    build_records, cell_areas, check_header, check_manifest, density_class, member_name,
    rasterize, read_window, unit_records, units_from,
)
from histctx.sources.raster import rasterize as rasterize_grid

HEADER = ("ncols 4320\r\nnrows 2160\r\nxllcorner -180.0\r\nyllcorner -90.0\r\n"
          "cellsize 0.0833333\r\nNODATA_value -9999.0\r\n")


def grid_bytes(cells: dict) -> bytes:
    """Сетка набора: всюду NODATA, в `cells[(строка, столбец)]` — значение."""
    blank = " ".join(["-9999.0"] * NCOLS)
    lines = [blank] * NROWS
    by_row = {}
    for (row, col), value in cells.items():
        by_row.setdefault(row, {})[col] = value
    for row, cols in by_row.items():
        values = ["-9999.0"] * NCOLS
        for col, value in cols.items():
            values[col] = str(value)
        lines[row] = " ".join(values)
    return (HEADER + "\r\n".join(lines) + "\r\n").encode("ascii")


def square(lon0, lat0, lon1, lat1):
    return {"type": "Polygon",
            "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1],
                             [lon0, lat0]]]}


def test_member_names_follow_the_archive_layout():
    assert member_name("population", 1900) == "baseline/asc/1900AD_pop/popc_1900AD.asc"
    assert member_name("cropland", 1700) == "baseline/asc/1700AD_lu/cropland1700AD.asc"
    assert YEARS[0] == 1700 and YEARS[-1] == 1960 and len(YEARS) == 27


def test_header_of_another_grid_stops_the_harvest():
    check_header(HEADER.encode("ascii"))
    with pytest.raises(HydeError):
        check_header(HEADER.replace("4320", "8640").encode("ascii"))


def test_window_is_cut_and_wrapped_past_180():
    # Клетка у Москвы (55,79° с. ш., 37,62° в. д.) и клетка на Чукотке за 180°.
    moscow = (int((90 - 55.79) / CELL), int((37.62 + 180) / CELL))
    chukotka = (int((90 - 66.0) / CELL), int((-175.0 + 180) / CELL))
    window = read_window(grid_bytes({moscow: 1500.0, chukotka: 7.0}))
    assert window.shape == (N_ROWS, N_COLS)
    assert window[moscow[0] - ROW0, moscow[1] - COL0] == 1500.0
    # −175° = 185° в непрерывной долготе окна.
    assert window[chukotka[0] - ROW0, int((185.0 - LON_MIN) / CELL)] == 7.0
    # NODATA в сумму не идёт.
    assert window.sum() == 1507.0


def test_rasterize_respects_holes_and_first_owner():
    outer = square(30.0, 50.0, 31.0, 51.0)
    outer["coordinates"].append(square(30.25, 50.25, 30.75, 50.75)["coordinates"][0])
    index = rasterize_grid([outer, square(30.0, 50.0, 32.0, 51.0)], lat_max=52.0,
                           lon_min=29.0, cell=0.25, n_rows=12, n_cols=16)
    # Первый полигон — квадрат 4 × 4 клетки с дырой 2 × 2.
    assert (index == 0).sum() == 12
    # Дыру и восточную половину получает второй: всего он накрыл бы 32 клетки.
    assert (index == 1).sum() == 32 - 12
    assert index[0, 0] == -1


def test_polygon_east_of_180_is_filled():
    index = rasterize([square(181.0, 65.0, 183.0, 66.0)])
    rows, cols = np.nonzero(index == 0)
    assert len(rows) == 12 * 24
    assert LON_MIN + CELL * (cols.min() + 0.5) > 181.0


def test_cell_area_shrinks_to_the_north():
    areas = cell_areas()
    assert areas[0] < areas[-1]
    # На 60° с. ш. клетка 5′ — около 43 км².
    assert areas[int((LAT_MAX - 60) / CELL)] == pytest.approx(42.9, abs=0.5)


def test_density_classes():
    assert density_class(0.3).startswith("почти не заселён")
    assert density_class(4.9).startswith("редко")
    assert density_class(60).startswith("заселён очень плотно")


def test_unit_records_tell_estimate_from_fact():
    unit = Unit(key="12", name="Кирилловский уезд", province="Новгородская губерния")
    series = {1890: Estimate(60000.0, 300.0, 150.0), 1900: Estimate(66000.0, 345.0, 150.0)}
    recs = unit_records(unit, 15000.0, 350, series)
    assert [r.year_from for r in recs] == [1890, 1900]
    first, last = recs
    assert first.title == ("Кирилловский уезд, Новгородская губерния: заселённость и распашка "
                           "около 1890 года")
    assert (first.year_to, first.date_precision) == (1899, "decade")
    assert (last.year_to, last.date_precision) == (1900, "year")
    assert first.scope == "region" and first.regions == ["Новгородская губерния"]
    assert first.district == "Кирилловский уезд" and first.date_approx
    assert first.category.startswith("редко заселён")
    assert "4,0 чел./км²" in first.summary and "Пашня — 2,0% площади" in first.summary
    assert "(+10% за 10 лет)" in last.summary
    assert "не данные учёта" in first.summary
    assert first.extra == {"population": 60000, "density_per_km2": 4.0, "cropland_share": 0.02,
                           "grazing_share": 0.01, "area_km2": 15000}
    assert first.usable and first.uid != last.uid
    # Уезд, в который не попало ни одной клетки, записей не даёт.
    assert unit_records(unit, 0.0, 0, series) == []


def test_build_records_sums_cells_inside_the_polygon():
    index = rasterize([square(30.0, 50.0, 31.0, 51.0)])
    population = np.zeros((N_ROWS, N_COLS), dtype=np.float32)
    population[index == 0] = 10.0
    population[0, 0] = 999.0                       # вне полигона
    zeros = np.zeros_like(population)
    assert aggregate(index, population, 1)[0] == 1440.0
    recs = build_records([Unit("1", "Уезд", "Губерния")], index,
                         {1800: {"population": population, "cropland": zeros,
                                 "grazing": zeros}})
    assert len(recs) == 1 and recs[0].extra["population"] == 1440


def test_units_take_district_id_not_province_id():
    features = [{"properties": {"Distr_ID": 3, "Name_RU": "Улеоский", "RISTAT_ID": "1897_86",
                                "prov_RU": "Улеаборгская губерния"}}]
    unit = units_from(features)[0]
    assert unit.key == "3" and unit.province == "Улеаборгская губерния"
    assert unit.name.endswith("уезд")


def test_manifest_check():
    def payload(**changes):
        file = {"label": ARCHIVE_NAME, "dataFile": {"id": ARCHIVE_ID, "filesize": ARCHIVE_SIZE}}
        file["dataFile"].update(changes)
        return json.dumps({"data": {"latestVersion": {
            "license": {"name": LICENSE_NAME}, "files": [file]}}}).encode()

    assert check_manifest(payload()) == []
    assert any("размер" in p for p in check_manifest(payload(filesize=1)))
    assert check_manifest(b"not json")


def test_layer_card():
    assert POPULATION_HYDE.status == "harvested"
    assert POPULATION_HYDE.expected_rows == 824 * len(YEARS)
    assert "не учёт" in POPULATION_HYDE.description
