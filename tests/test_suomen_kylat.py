"""Разбор «Suomen kylät 1540–1940»: деревни Финляндии и их приходы.

Сети в тестах нет. Образец — строки самого набора (версия 1, CC BY 4.0) с
его шапкой, разделителем «;», кавычками, BOM и переводами строк CRLF.

Проверяется то, на чём слой держится: перевод координат из ETRS-TM35FIN
(сверено с PROJ), приход по годам вместе с «?» и «x», годы записи — первое
упоминание, оценка конца, «9999» и колонка позже конца, — пометки
`no_coords` и `after_1960`, своя фраза описания и рамка: губерния, дальний
берег для шхер и решение по самому набору у границы.
"""

import hashlib
import json

import pytest

from histctx.frame import Frame
from histctx.geo import haversine_km
from histctx.schema import ContextRecord
from histctx.sources import suomen_kylat
from histctx.sources.suomen_kylat import (
    CSV_KEY, CSV_MD5, CSV_SIZE, FRAME_BY_PARISH, FRAME_SHORE, LAST_COLUMN_YEAR, OUTSIDE,
    VILLAGES_FI, SuomenKylatError, check_manifest, listed_in_frame, mark_frame, parish,
    parish_runs, read_rows, records, row_to_record, tm35fin_to_wgs84, village_title,
    years_of,
)

HEADER = ('"id";"x";"y";"nimi";"nimi_2";"nimi_muu";"start";"end";"v1550";"v1600";"v1650";'
          '"v1700";"v1750";"v1800";"v1850";"v1900";"v1950";"v2000";"v2023";"rekisteritunnus";'
          '"rekisterikunta2013";"rekisterikyla2013";"placeid";"wikidata";"ysopaikka";'
          '"bebyggelsenamn";"heraldica";"df";"asutus1560luv";"maara";"karttapaikka"')
LINES = [
    # Перестала быть деревней около 1899 года, приход — Taivassalo.
    '10001;208248;6731970;"Utamaa";"Utamaa";"Uthema; Uusimaa";1540;1899;"Taivassalo";'
    '"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";;;;;;;;;;;;;;'
    '1,01;10;"https://asiointi.maanmittauslaitos.fi/karttapaikka/?lang=fi&n=6731970&e=208248"',
    # Деревня и сейчас; старое написание другое.
    '10006;207504;6726732;"Hylkilä";"Hylkilax";;1540;9999;"Taivassalo";"Taivassalo";'
    '"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";'
    '"Taivassalo";"Taivassalo";"833-410";"TAIVASSALO";"HYLKILÄ";'
    '"http://paikkatiedot.fi/so/1000772/10299184";"https://www.wikidata.org/wiki/Q123";;;'
    '"https://heraldica.narc.fi/toimija.html?id=16503";;1,06;12;""',
    # Без координаты.
    '10023;;;"Pyöli";"Böle";;1540;1599;"Taivassalo";;;;;;;;;;;;;;;;;;;;2,01;3;',
    # Известна только по данным 2023 года.
    '10092;200321;6735560;"Isokorpi 2";"Isokorpi";;2023;9999;;;;;;;;;;;"Uusikaupunki";'
    '"895-500";"UUSIKAUPUNKI";"ISOKORPI";;;;;;;;0;""',
    # «Перестала» в 1539 году, а в 1550-м числится в приходе.
    '14122;324407;6747036;"Mustiala 2";"Mustiala";;1539;1539;"Lehijärvi";;;;;;;;;;;;;;;;;;;;;0;""',
    # Отошла к СССР: «x» в колонке 1950 года.
    '16065;550155;6709854;"Hämäläinen";"Hämäläinen";"Hämälä";1558;1944;;"Virolahti";'
    '"Virolahti";"Virolahti";"Virolahti";"Virolahti";"Virolahti";"Virolahti";"x";;;;;;;;;;;;'
    '194,01;0;""',
    # Несверенные значения: «Vehmaa?», «Vehmaa??».
    '10128;207644;6729701;"Inkeranta";"Ingeranta";"Ingiranda";1540;9999;"Vehmaa";"Vehmaa";'
    '"Vehmaa";"Vehmaa";"Vehmaa?";"Vehmaa??";"Taivassalo";"Taivassalo";"Taivassalo";"Taivassalo";'
    '"Taivassalo";"833-412";"TAIVASSALO";"INKERANTA";"http://paikkatiedot.fi/so/1000772/10299548";'
    ';;;"https://heraldica.narc.fi/toimija.html?id=13066";;5,01;16;""',
]


def sample_bytes(lines=LINES, header=HEADER) -> bytes:
    return ("﻿" + "\r\n".join([header, *lines]) + "\r\n").encode("utf-8")


@pytest.fixture
def rows():
    return read_rows(sample_bytes())


@pytest.fixture
def by_id(rows):
    return {r.source_id: r for r in records(rows)}


# --- координаты --------------------------------------------------------------

# Опорные точки посчитаны PROJ 9.8.1 (EPSG:4258 → EPSG:3067): восток, север и
# широта, долгота, из которых они получены.
PROJ_POINTS = [
    (385611.317, 6672118.380, 60.1699, 24.9384),   # Хельсинки
    (595450.757, 6731712.728, 60.7096, 28.7490),   # Выборг
    (107579.582, 6683261.170, 60.0973, 19.9348),   # Мариехамн, 380 км от осевого
    (501073.511, 7755602.683, 69.9079, 27.0280),   # Утсйоки
]


@pytest.mark.parametrize("easting, northing, lat, lon", PROJ_POINTS)
def test_tm35fin_matches_proj_to_a_centimetre(easting, northing, lat, lon):
    got_lat, got_lon = tm35fin_to_wgs84(easting, northing)
    assert haversine_km(lat, lon, got_lat, got_lon) * 1000 < 0.01


def test_central_meridian_at_sixty_degrees():
    # На осевом меридиане север — длина дуги меридиана, умноженная на 0,9996:
    # до 60° на GRS80 это 6 654 072,819 м.
    lat, lon = tm35fin_to_wgs84(500_000, 0.9996 * 6_654_072.819)
    assert lat == pytest.approx(60.0, abs=1e-7)
    assert lon == pytest.approx(27.0, abs=1e-9)


# --- чтение и сверка ----------------------------------------------------------

def test_table_is_read_with_bom_semicolons_and_crlf(rows):
    assert len(rows) == len(LINES)
    assert rows[0]["id"] == "10001"           # BOM не прилип к первой колонке
    assert rows[1]["nimi"] == "Hylkilä"
    assert rows[0]["nimi_muu"] == "Uthema; Uusimaa"


def test_redesigned_table_stops_the_harvest():
    with pytest.raises(SuomenKylatError, match="v1850"):
        read_rows(sample_bytes(header=HEADER.replace('"v1850"', '"v1851"')))
    with pytest.raises(SuomenKylatError, match="пуста"):
        read_rows(sample_bytes(lines=[]))
    with pytest.raises(SuomenKylatError, match="UTF-8"):
        read_rows("id;x\n1;ä".encode("cp1252"))


def test_manifest_is_checked_against_the_code():
    good = [{"key": CSV_KEY, "size": CSV_SIZE, "checksum": f"md5:{CSV_MD5}"}]
    assert check_manifest(good) == []
    problems = check_manifest([{"key": CSV_KEY, "size": 1, "checksum": "md5:00"}])
    assert len(problems) == 2 and "размер" in problems[0] and "сумма" in problems[1]
    assert "есть: Suomen_kylat_v2.csv" in check_manifest([{"key": "Suomen_kylat_v2.csv"}])[0]


def test_table_of_another_version_is_not_cached(tmp_path, monkeypatch):
    payload = b"csv bytes"
    monkeypatch.setattr(suomen_kylat, "fetch_bytes", lambda url, **kw: payload)
    with pytest.raises(SuomenKylatError, match="ожидалось"):
        suomen_kylat.cached_csv(tmp_path)
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(suomen_kylat, "CSV_SIZE", len(payload))
    monkeypatch.setattr(suomen_kylat, "CSV_MD5", hashlib.md5(payload).hexdigest())
    assert suomen_kylat.cached_csv(tmp_path).read_bytes() == payload


# --- приходы по годам ----------------------------------------------------------

def test_parish_value_keeps_the_doubt_and_drops_the_cession_mark():
    assert parish("Vehmaa??") == ("Vehmaa", True)
    assert parish("Taivassalo") == ("Taivassalo", False)
    assert parish("Ii") == ("Ii", False)              # приход из двух букв — приход
    assert parish("x") == (None, False)               # отошло к СССР — не приход
    assert parish("") == (None, False)


def test_runs_join_equal_parishes_and_break_on_gaps():
    row = {"v1550": "A", "v1600": "A?", "v1650": "", "v1700": "A", "v1750": "B",
           "v1800": "B", "v1850": "x", "v1900": "B"}
    assert parish_runs(row) == [
        ("A", 1550, 1600, True),      # «A?» — тот же приход, но под вопросом
        ("A", 1700, 1700, False),     # пропуск в 1650 году разрывает ряд
        ("B", 1750, 1800, False),
        ("B", 1900, 1900, False),     # «x» тоже разрывает
    ]


# --- записи --------------------------------------------------------------------

def test_one_record_per_village_with_layer_card(by_id):
    assert len(by_id) == len(LINES)
    rec = by_id["10001"]
    assert rec.layer == VILLAGES_FI.slug and rec.group == "admin"
    assert rec.url == VILLAGES_FI.url and rec.license == VILLAGES_FI.license
    assert rec.lat == pytest.approx(60.617, abs=1e-3) and rec.lon == pytest.approx(21.666, abs=1e-3)


def test_years_first_mention_and_estimated_end(by_id):
    utamaa = by_id["10001"]
    assert (utamaa.year_from, utamaa.year_to) == (1540, 1899)
    assert utamaa.date_approx and utamaa.date_precision == "year"
    assert utamaa.period_raw == "1540–1899" and utamaa.category == "бывшая деревня"
    alive = by_id["10006"]
    assert (alive.year_from, alive.year_to) == (1540, LAST_COLUMN_YEAR)
    assert not alive.date_approx and alive.period_raw == "1540–9999"
    assert alive.category == "деревня"


def test_parish_column_after_the_end_widens_the_record(rows):
    row = next(r for r in rows if r["id"] == "14122")
    assert years_of(row) == (1539, 1550, True)
    assert row_to_record(row).period_raw == "1539–1539"   # исходная запись не тронута


def test_empty_start_and_end_fall_back_to_parish_columns():
    row = {"id": "1", "x": "", "y": "", "nimi": "Kylä", "nimi_2": "", "start": "",
           "end": "", "v1600": "Ii", "v1700": "Ii?"}
    assert years_of(row) == (1600, 1700, True)
    rec = row_to_record(row)
    assert rec.period_raw == "?–?" and rec.category is None
    assert "Первое упоминание в наборе не указано" in rec.summary
    assert "когда перестала быть деревней, в наборе не указано" in rec.summary
    nothing = row_to_record({"id": "2", "x": "1", "y": "1", "nimi": "Kylä", "start": "",
                             "end": ""})
    assert (nothing.year_from, nothing.year_to) == (None, None)
    assert nothing.confidence == "no_date" and nothing.date_precision == "unknown"


def test_marks_instead_of_drops(by_id):
    assert by_id["10023"].confidence == "no_coords" and not by_id["10023"].has_point
    assert by_id["10092"].confidence == "after_1960"
    assert by_id["10092"].year_from == 2023
    assert by_id["10001"].confidence == "ok"


def test_title_shows_the_old_spelling_but_not_the_register_number(rows):
    by = {r["id"]: r for r in rows}
    assert village_title(by["10006"]) == "Hylkilä (Hylkilax)"
    assert village_title(by["10092"]) == "Isokorpi 2"
    assert village_title(by["10001"]) == "Utamaa"


def test_extra_keeps_the_source_values(by_id):
    extra = by_id["10128"].extra
    assert extra["parish"]["1750"] == "Vehmaa?" and extra["parish"]["1800"] == "Vehmaa??"
    assert extra["parish"]["2023"] == "Taivassalo"
    assert extra["name_old"] == "Ingeranta" and extra["name_variants"] == ["Ingiranda"]
    assert by_id["10006"].extra["wikidata"] == "https://www.wikidata.org/wiki/Q123"
    assert by_id["10006"].extra["nls_place"].startswith("http://paikkatiedot.fi/")
    assert by_id["16065"].extra["parish"]["1950"] == "x"


def test_summary_is_our_own_phrase(by_id):
    assert by_id["10128"].summary == (
        "Деревня прихода Vehmaa (1550–1800?), Taivassalo (1850–1950); сейчас — община "
        "Taivassalo. Первое упоминание — 1540, деревня существует и сейчас.")
    assert by_id["10001"].summary == (
        "Деревня прихода Taivassalo (1550–1850). Первое упоминание — 1540; по оценке "
        "составителей, перестала быть деревней в 1899 году.")
    assert by_id["16065"].summary.endswith("к 1950 году земля отошла к СССР.")
    assert "приход до 1950 года в наборе не указан" in by_id["10092"].summary
    # Место — последний приход до горизонта, а не нынешняя община.
    assert by_id["10128"].place_text == "Taivassalo"
    assert by_id["10092"].place_text == "Uusikaupunki"


# --- рамка ---------------------------------------------------------------------

def _square(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def _frame(tmp_path):
    """Губерния на материке, Финляндия чуть шире неё, Швеция к западу, к югу — море."""
    provinces = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"prov_RU": "Нюландская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(24.0, 60.0, 26.0, 61.0)}},
    ]}
    states = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"state": "Финляндия"},
         "geometry": {"type": "Polygon", "coordinates": _square(23.5, 60.0, 26.0, 61.0)}},
        {"type": "Feature", "properties": {"state": "Швеция"},
         "geometry": {"type": "Polygon", "coordinates": _square(20.0, 60.0, 23.0, 61.0)}},
    ]}
    (tmp_path / "provinces_1897.geojson").write_text(json.dumps(provinces), encoding="utf-8")
    (tmp_path / "state_borders.geojson").write_text(json.dumps(states), encoding="utf-8")
    return Frame.load(tmp_path)


def village(lat, lon, parish_by_year=None):
    return ContextRecord(layer="villages_fi", title="t", lat=lat, lon=lon,
                         extra={"parish": parish_by_year or {}})


def test_frame_puts_province_far_shore_and_dataset_verdict(tmp_path):
    recs = {
        "province": village(60.5, 25.0),
        "frame": village(60.5, 23.7),
        # В море в 0,4° от финской суши: `frame.py` ищет берег до 0,3°.
        "skerry": village(59.62, 25.0),
        # Грубый контур отдал точку Швеции, а набор держит её в финской общине.
        "border": village(60.5, 22.9, {"1900": "Tornio", "2023": "Tornio"}),
        # Шведская деревня под финским именем прихода: Övertorneå — «Ylitornio».
        "sweden": village(60.5, 21.0, {"1850": "Ylitornio"}),
        "no point": ContextRecord(layer="villages_fi", title="t"),
    }
    counts = mark_frame(recs.values(), _frame(tmp_path))
    assert recs["province"].region == "Нюландская губерния"
    assert recs["frame"].region is None and recs["frame"].confidence == "ok"
    assert recs["skerry"].region == "Нюландская губерния"
    assert recs["skerry"].extra["frame"] == FRAME_SHORE
    assert recs["border"].confidence == "ok" and recs["border"].region is None
    assert recs["border"].extra["frame"] == FRAME_BY_PARISH
    assert recs["sweden"].confidence == OUTSIDE, "чужая суша не двигается"
    assert "frame" not in recs["sweden"].extra
    assert counts["без точки"] == 1 and counts["вне рамки РИ/СССР"] == 1
    assert counts["в губерниях 1897 года"] == 2


def test_dataset_frame_rule_needs_finland_after_the_war():
    assert listed_in_frame({"1950": "x"})              # отошедшие земли — СССР
    assert listed_in_frame({"2023": "Tornio"})
    assert listed_in_frame({"1950": "Pello"})
    # Приход XIX века не решает: так записаны и шведские деревни долины Торнио.
    assert not listed_in_frame({"1850": "Ylitornio", "1900": "Ylitornio"})
    assert not listed_in_frame({"1550": "Tornio", "1800": "Tornio"})
    assert not listed_in_frame({})
