"""Солнечные затмения: разбор каталога NASA и геометрия полосы.

Сети и файла эфемерид в тестах нет. Векторы Солнца и Луны на два момента
затмения 19 августа 1887 года сняты с эфемерид JPL DE440 (экватор даты,
километры, с поправкой на ход света) — на них проверяется то, что известно
независимо: в Клину затмение было полным, в Москве — нет.
"""

import datetime as dt

import numpy as np
import pytest

from histctx.sources.eclipses import (
    CREDIT, GAMMA_TOLERANCE, SOLAR_ECLIPSES, Eclipse, EclipseError, Visibility, axis_point,
    circumstances, gamma_of, gmst, julian_day, observer_xyz, parse_catalog, precession_matrix,
    province_nodes, rotate_z, to_geodetic, to_records,
)

# Строки каталога — как на странице NASA: номер и дата обёрнуты ссылками.
def _row(number, date_text, ymd, rest):
    year = ymd[:4]
    return (f'<a href="../5MCSEmap/1801-1900/{year}-{ymd[4:6]}-{ymd[6:]}.gif" target="MAP">'
            f'{number}</a>  <a href="../SEsearch/SEsearchmap.php?Ecl={ymd}" target="GMAP">'
            f'{date_text}</a>  {rest}')


def _tail(time, saros, kind, gamma, rest):
    return (f'{time}     -6  -1390  <a href="../SEsaros/SEsaros{saros}.html" target="SAROS">'
            f'{saros}</a>   {kind}   p-  <a href="../SEsearch/SEdata.php?Ecl=1" target="BES">'
            f'{gamma}</a>  {rest}')


ROWS = "\n".join([
    _row("09250", "1887 Feb 22", "18870222",
         _tail("21:33:04", 138, "A", "-0.6040", "0.9232  46S 127W  53  362  08m01s")),
    _row("09251", "1887 Aug 19", "18870819",
         _tail("05:32:05", 143, "T", " 0.6312", "1.0518  51N 112E  51  221  03m50s")),
    # У частного затмения нет ни ширины полосы, ни длительности.
    _row("09252", "1888 Feb 11", "18880211",
         _tail("23:38:15", 148, "P", "-1.2684", "0.5029  71S  36W   0             ")),
])

# 19 августа 1887 года: середина полной фазы в Клину (−4550 с от наибольшей
# фазы) и сама наибольшая фаза.
KLIN = dict(sun=[-125249015.75724784, 77961812.34466384, 33824396.239163235],
            moon=[-298513.5999593541, 189912.0081973117, 86262.89165226223],
            theta=0.5461491819192056)
GREATEST = dict(sun=[-125322869.91501763, 77859238.81471364, 33779900.042743936],
                moon=[-301167.2454578598, 185948.8066460926, 85032.83183012823],
                theta=0.8779404521463419)


def at(moment, lats, lons):
    points, up = observer_xyz(np.array(lats), np.array(lons))
    return circumstances(np.array(moment["sun"]), np.array(moment["moon"]),
                         rotate_z(points, moment["theta"]), rotate_z(up, moment["theta"]))


def test_catalog_rows_are_parsed_with_and_without_a_path():
    annular, total, partial = parse_catalog(ROWS)
    assert total.number == "09251" and total.date == dt.date(1887, 8, 19)
    assert (total.kind, total.gamma, total.delta_t) == ("T", 0.6312, -6.0)
    assert (total.lat, total.lon, total.width_km, total.duration) == (51.0, 112.0, 221.0,
                                                                      "03m50s")
    assert (annular.lat, annular.lon) == (-46.0, -127.0) and annular.central
    assert partial.kind == "P" and not partial.central and partial.width_km is None
    assert total.map_url.endswith("/5MCSEmap/1801-1900/1887-08-19.gif")


def test_broken_row_is_an_error_not_a_gap():
    with pytest.raises(EclipseError):
        parse_catalog(ROWS.replace("1887 Aug 19", "1887 Zzz 19"))


def test_time_scales():
    assert julian_day(dt.date(2000, 1, 1)) == 2451545.0
    eclipse = parse_catalog(ROWS)[1]
    # 05:32:05 TD — за 6 ч 28 мин до полудня.
    assert eclipse.jd_tt == pytest.approx(julian_day(eclipse.date) - 0.5 + 19925 / 86400)
    # Звёздное время в эпоху J2000 — 18 ч 41 мин 50,5 с.
    assert float(gmst(2451545.0)) == pytest.approx(np.radians(280.46061837))
    matrix = precession_matrix(eclipse.jd_tt)
    assert np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-12)
    # За 112 лет равноденствие ушло на полтора градуса.
    assert np.degrees(np.arccos(matrix[0, 0])) == pytest.approx(1.57, abs=0.05)


def test_observer_on_the_ellipsoid():
    xyz, up = observer_xyz(np.array([0.0, 90.0]), np.array([0.0, 0.0]))
    assert xyz[0, 0] == pytest.approx(6378.137) and xyz[1, 2] == pytest.approx(6356.752, abs=1e-3)
    assert np.allclose(up[1], [0, 0, 1], atol=1e-12)


def test_klin_was_total_and_moscow_was_not():
    magnitude, central, altitude = at(KLIN, [56.33, 55.75, 59.94], [36.73, 37.62, 30.31])
    # Клин: полная фаза, Солнце невысоко над горизонтом на востоке.
    assert central[0] and magnitude[0] > 1.0 and 0 < np.degrees(altitude[0]) < 25
    # Москва осталась у самого края полосы: фаза 0,99, но не полная.
    assert not central[1] and 0.99 < magnitude[1] < 1.0
    # Петербург — частное затмение.
    assert not central[2] and 0.8 < magnitude[2] < 0.95


def test_gamma_and_greatest_point_agree_with_the_catalog():
    sun, moon = np.array(GREATEST["sun"]), np.array(GREATEST["moon"])
    total = parse_catalog(ROWS)[1]
    assert abs(gamma_of(sun, moon) - total.gamma) < GAMMA_TOLERANCE
    lat, lon = to_geodetic(axis_point(sun, moon), GREATEST["theta"])
    assert lat == pytest.approx(total.lat, abs=1.0) and lon == pytest.approx(total.lon, abs=1.0)
    # Точка под осью тени — центральная фаза, Солнце высоко.
    magnitude, central, altitude = at(GREATEST, [lat], [lon])
    assert central[0] and np.degrees(altitude[0]) == pytest.approx(51, abs=1.5)


def test_axis_misses_the_earth():
    sun, moon = np.array(GREATEST["sun"]), np.array(GREATEST["moon"])
    assert axis_point(sun, moon + np.array([0.0, 0.0, 8000.0])) is None


def test_nodes_merge_two_polygons_of_one_province():
    def box(lon0, lat0, lon1, lat1, name):
        return {"properties": {"prov_RU": name}, "geometry": {
            "type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1],
                                                [lon0, lat1], [lon0, lat0]]]}}

    nodes = province_nodes([box(40, 41, 41, 42, "Тифлисская губерния вкл. Закатальский округ"),
                            box(41, 41, 42, 42, "Тифлисская губерния без Закатальского округа"),
                            box(50, 50, 51, 51, "Самарская губерния")])
    assert nodes.names == ["Самарская губерния", "Тифлисская губерния"]
    assert len(nodes.lat) == 3 * 16
    assert (nodes.province == 1).sum() == 32


def test_records_split_path_and_deep_partial():
    total = parse_catalog(ROWS)[1]
    seen = Visibility(
        central={"Тверская губерния": {"ut": "04:19", "local": "06:47", "duration_s": 150},
                 "Виленская губерния": {"ut": "04:23", "local": "06:05", "duration_s": 140}},
        deep={"Рязанская губерния": 0.991}, track=[[26.43, 54.88], [37.94, 56.71]],
        gamma=0.6312, order=["Виленская губерния", "Тверская губерния"])
    path, deep = to_records(total, seen)
    assert path.title == "Полное солнечное затмение 19 августа 1887 года (7 августа ст. ст.)"
    assert path.category == "полное" and path.scope == "region"
    assert path.regions == ["Виленская губерния", "Тверская губерния"]
    assert "Тверская — около 6:47 утра, до 2 мин 30 с" in path.summary
    assert CREDIT in path.summary and path.extra["track"]
    assert (path.year_from, path.year_to, path.date_precision) == (1887, 1887, "day")
    assert path.usable and path.url.endswith("1887-08-19.gif")
    assert deep.regions == ["Рязанская губерния"]
    assert deep.category.startswith("частное глубокое") and "Рязанская (0,991)" in deep.summary
    assert path.uid != deep.uid
    # Тень прошла мимо: записей нет.
    assert to_records(total, Visibility()) == []


def test_narrow_path_is_flagged():
    hybrid = Eclipse(number="1", date=dt.date(1912, 4, 17), time="11:34:22", delta_t=13.0,
                     saros=137, kind="H", kind_raw="H", gamma=0.528, magnitude=1.0003,
                     lat=38.0, lon=-11.0, width_km=1.0, duration="00m02s")
    seen = Visibility(central={"Санкт-Петербургская губерния": {
        "ut": "12:30", "local": "14:31", "duration_s": 10}},
        order=["Санкт-Петербургская губерния"])
    rec = to_records(hybrid, seen)[0]
    assert rec.extra["narrow_path"] and "Полоса узкая" in rec.summary
    assert rec.category.startswith("гибридное")


def test_layer_card():
    assert SOLAR_ECLIPSES.status == "harvested" and SOLAR_ECLIPSES.expected_rows
    assert "Fred Espenak" in SOLAR_ECLIPSES.license
