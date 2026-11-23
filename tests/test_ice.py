"""Ледостав и вскрытие (NSIDC G01377): разбор таблиц, норма, запись.

Сети в тестах нет — сборщик и сам в неё не ходит. Образцы — строки двух
таблиц набора с их шапками.
"""

import datetime as dt

import pytest

from histctx.oldstyle import both_styles, old_style
from histctx.sources.ice import (
    ICE_PHENOLOGY, MIN_SEASONS, REQUIRED_SEASONS, REQUIRED_SITES, SIZES, IceError, classify,
    local_file, offset, read_sites, read_table, records, site_coords,
)

SITES_CSV = (
    "lakecode,lakename,lakeorriver,continent,country,state,latitude,longitude,"
    "lat_decimal,lon_decimal,contributor,comments\n"
    "NG3,ANGARA RIVER,R,A,RUSSIA,,52 18 N,104 16 E,52.3,104.27,GRANIN,-999\n"
    "VSV42,LAKE LOVOZERO,L,A,RUSSIA,,67.59,35.05,67.59,35.05,VUGLINSKY,-999\n"
    "VSV30,LAKE BOLSHIE CHANY,L,A,RUSSIA,,55.33,60.54,55.33,60.54,VUGLINSKY,-999\n"
    "KK1,LAKE KALLAVESI (4079),L,E,FINLAND,,62 54,27 41,62.9,27.68,KORHONEN,-999\n"
    "US1,LAKE MENDOTA,L,N,UNITED STATES,WI,43 6 N,89 25 W,43.1,-89.42,MAGNUSON,-999\n"
).encode("latin-1")


def season(code, name, label, on, off, country="RUSSIA", froze="Y"):
    cells = [code, name, "R", label]
    for date in (on, off):
        cells += [str(x) for x in date] if date else ["-999", "-999", "-999"]
    return ",".join(cells + ["-999", "52.3", "104.27", country, froze, ""])


HEADER = ("lakecode,lakename,lakeorriver,season,iceon_year,iceon_month,iceon_day,iceoff_year,"
          "iceoff_month,iceoff_day,duration,latitude,longitude,country,froze,comments")


def angara_rows(years=range(1880, 1900), late=None):
    rows = []
    for year in years:
        off = (year, 4, 10) if year != late else (year, 4, 28)
        rows.append(season("NG3", "ANGARA RIVER", f"{year - 1}-{str(year)[2:]}",
                           (year, 1, 12), off))
    return rows


def tables(season_lines):
    sites = read_table(SITES_CSV, REQUIRED_SITES - {"x"}, "sites")
    seasons = read_table(("\n".join([HEADER] + season_lines) + "\n").encode("latin-1"),
                         REQUIRED_SEASONS, "seasons")
    return sites, seasons


def test_old_style_goes_through_julian_day_number():
    assert old_style(dt.date(1887, 8, 19)) == (1887, 8, 7)
    # 1900 год високосный только по старому стилю: разница меняется с 12 на 13 дней.
    assert old_style(dt.date(1900, 3, 13)) == (1900, 2, 29)
    assert old_style(dt.date(1900, 3, 14)) == (1900, 3, 1)
    assert both_styles(dt.date(1700, 1, 10)) == "10 января 1700 года (31 декабря 1699 года ст. ст.)"
    assert both_styles(dt.date(1918, 2, 14)) == "14 февраля 1918 года"
    assert both_styles(dt.date(1887, 8, 19), russia=False) == "19 августа 1887 года"


def test_table_without_a_required_column_stops():
    with pytest.raises(IceError):
        read_table(b"lakecode,lakename\nA,B\n", REQUIRED_SEASONS, "seasons")


def test_coordinates_degrees_minutes_and_known_error():
    sites = {row["lakecode"]: row for row in read_table(SITES_CSV, set(), "sites")}
    assert site_coords(sites["NG3"]) == (52.3, 104.27, "decimal")
    lat, lon, how = site_coords(sites["VSV42"])
    # 67.59 в своде Вуглинского — 67°59′, а не 67,59°.
    assert how == "degmin" and lat == pytest.approx(67.9833, abs=1e-3)
    assert lon == pytest.approx(35.0833, abs=1e-3)
    assert site_coords(sites["VSV30"]) == (None, None, "none")


def test_only_frame_countries_and_winters_up_to_horizon():
    lines = angara_rows(range(1950, 1965)) + [
        season("US1", "LAKE MENDOTA", "1899-00", (1899, 12, 20), (1900, 4, 5),
               country="UNITED STATES")]
    sites = read_sites(*tables(lines))
    assert [s.code for s in sites] == ["NG3"]
    assert [s.winter for s in sites[0].seasons] == list(range(1950, 1961))


def test_norm_needs_enough_winters():
    short = read_sites(*tables(angara_rows(range(1890, 1890 + MIN_SEASONS - 1))))[0]
    assert short.norm_off is None
    recs = records([short])
    assert recs[0].category == "сроки без нормы" and "Ряд короткий" in recs[0].summary
    full = read_sites(*tables(angara_rows()))[0]
    assert full.norm_off == offset(dt.date(1890, 4, 10), 1890)


def test_late_breakup_is_named_and_dated_in_both_styles():
    site = read_sites(*tables(angara_rows(late=1891)))[0]
    rec = next(r for r in records([site]) if r.source_id == "NG3:1890-91")
    assert rec.title == "Ангара (Иркутск): зима 1890/91"
    assert rec.category == "позднее вскрытие"
    assert "Вскрытие 28 апреля 1891 года (16 апреля ст. ст.), на 18 дней позже обычного" \
        in rec.summary
    assert "Подо льдом 106 дней" in rec.summary
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1891, 1891, "day")
    assert rec.extra["ice_off"] == "1891-04-28" and rec.extra["ice_off_delta_days"] == 18
    assert rec.mappable and rec.confidence == "ok"


def test_ice_on_in_autumn_belongs_to_next_winter():
    lines = [season("KK1", "LAKE KALLAVESI (4079)", "1899-00", (1899, 11, 25), (1900, 5, 14),
                    country="FINLAND")]
    rec = records(read_sites(*tables(lines)))[0]
    assert (rec.year_from, rec.year_to) == (1899, 1900)
    # Финляндия жила по новому стилю: старый не пишется.
    assert "ст. ст." not in rec.summary
    assert rec.title.endswith("зима 1899/00")


def test_site_with_wrong_coords_is_kept_without_a_point():
    lines = [season("VSV30", "LAKE BOLSHIE CHANY", "1940-41", (1940, 10, 26), (1941, 5, 18))]
    rec = records(read_sites(*tables(lines)))[0]
    assert rec.confidence == "no_coords" and not rec.has_point
    assert "Точки нет" in rec.summary and rec.title.startswith("Озеро Большие Чаны")


def test_classification():
    assert classify(None, 12, "Y", True) == "позднее вскрытие"
    assert classify(None, -10, "Y", True) == "раннее вскрытие"
    assert classify(-15, 3, "Y", True) == "ранний ледостав"
    assert classify(2, 3, "Y", True) == "обычные сроки"
    assert classify(None, None, "N", True) == "не замерзало"


def test_collector_reads_local_files_only(tmp_path):
    name = next(iter(SIZES))
    with pytest.raises(IceError) as err:
        local_file(name, tmp_path)
    assert "robots.txt" in str(err.value)
    (tmp_path / name).write_bytes(b"x")
    with pytest.raises(IceError):
        local_file(name, tmp_path)


def test_layer_card():
    assert ICE_PHENOLOGY.status == "harvested" and ICE_PHENOLOGY.expected_rows
    assert "ссылка" in ICE_PHENOLOGY.license
