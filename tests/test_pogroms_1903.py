"""Разбор таблицы погромов 1903–1906 годов (American Jewish Year Book, т. 8).

Сети в тестах нет: таблица — образец в той же вёрстке, что у перепечатки
Museum of Family History (строка года отдельной строкой, у строки погрома
девять ячеек), дополнительный список — абзац текстового слоя скана с
переносом по слогам.

Проверяется то, на чём слой держится: сверка с напечатанным (254 строки
подряд), разбор дат с «?», числа населения, убитые и раненые из строки ущерба,
ключ латинских написаний, поиск города только внутри губернии (и у её края,
где полигон 1897 года груб), записи и их права.
"""

import dataclasses

import pytest

from histctx.registry import BY_SLUG, HARVESTED
from histctx.sources import pogroms_1903 as pg
from histctx.sources.pogroms_1903 import (
    GUBERNIAS, POGROMS_1903, TABLE_PAGE_URL, TOWNS_RU, Locator, Place, Placement,
    PogromsError, Row, build_records, casualties, check_table, number, parse_date,
    parse_supplement, parse_table, precision, skeleton, table_record, wikidata_places,
)


def tr(*cells):
    return "<tr>" + "".join(f"<td><p>{c}</p></td>" for c in cells) + "</tr>"


TABLE = "\n".join([
    "<table>",
    tr("1.", "2.", "3.", "4.", "5.", "6.", "7.", "&nbsp;", "8."),
    tr("&nbsp;", "1903", "&nbsp;", "", "", "", "", "", ""),
    tr("1", "April 19", "KISHINEFF", "Bessarabia", "147,962", "50,000",
       "47 Jews killed; 424 wounded; 700 houses burned.", "", "Agitation by Krushevan."),
    tr("2", "May ?", "Batsha", "Bessarabia", "", "", "", "", ""),
    tr("&nbsp;", "1905", "&nbsp;", "", "", "", "", "", ""),
    tr("3", "Oct.26", "Lyutsin", "Vitebsk", "3,929", "", "", "", ""),
    tr("4", "? ?", "Lappy", "", "", "", "", "", ""),
    "</table>",
])

SUPPLEMENT = """
SUPPLEMENTARY LIST OF TOWNS IN WHICH POGROMS
OCCURRED, NOVEMBER, 1905

(Hither the date of the pogrom, or the location, etc., of the
town could not be determined.)

Amur, Ataki, Kroy-
evez, Kronstadt, Reval, Tiflis.

THE GUBERNIAS IN WHICH POGROMS OCCURRED
"""


@pytest.fixture
def rows():
    return parse_table(TABLE.encode("utf-8"))


def test_layer_is_registered_as_harvested():
    assert BY_SLUG["pogroms_1903"] is POGROMS_1903
    assert POGROMS_1903 in HARVESTED
    assert "общественное достояние" in POGROMS_1903.license
    assert POGROMS_1903.group == "hardship"


def test_table_rows_carry_their_year(rows):
    assert [r.number for r in rows] == [1, 2, 3, 4]
    assert [r.year for r in rows] == [1903, 1903, 1905, 1905]
    first = rows[0]
    assert (first.town, first.gubernia) == ("KISHINEFF", "Bessarabia")
    assert (first.population, first.jewish_population) == (147962, 50000)
    assert first.remarks == "Agitation by Krushevan."


def test_row_before_any_year_is_an_error():
    html = "<table>" + tr("1", "April 19", "X", "Y", "", "", "", "", "") + "</table>"
    with pytest.raises(PogromsError):
        parse_table(html.encode("utf-8"))


def test_dates_with_unknown_day_or_month():
    assert parse_date("April 19") == (4, 19)
    assert parse_date("Oct.26") == (10, 26)
    assert parse_date("May  ?") == (5, None)
    assert parse_date("Sep. 4") == (9, 4)
    assert parse_date("? ?") == (None, None)
    assert precision(4, 19) == "day" and precision(5, None) == "month"
    assert precision(None, None) == "year"


def test_check_table_compares_with_print(rows):
    problems = check_table(rows)
    assert any("254" in p for p in problems)          # в образце четыре строки
    gap = [r for r in rows if r.number != 2]
    assert any("подряд" in p for p in check_table(gap))


def test_numbers_and_casualties():
    assert number("147,962") == 147962
    assert number("") is None and number("?") is None
    assert casualties("47 Jews killed; 424 wounded; 700 houses burned") == (47, 424)
    assert casualties("8 killed; 19 injured.") == (8, 19)
    assert casualties("200 Jews killed; 700 injured; 169 shops") == (200, 700)
    assert casualties("Many Jews killed and wounded.") == (None, None)


def test_supplement_list_is_split_and_hyphenation_joined():
    names = parse_supplement(SUPPLEMENT)
    assert names == ["Amur", "Ataki", "Kroyevez", "Kronstadt", "Reval", "Tiflis"]
    with pytest.raises(PogromsError):
        parse_supplement("no list here")


def test_skeleton_matches_old_and_new_spellings():
    assert skeleton("Kishineff") == skeleton("Kishinev") == skeleton("Kischinew")
    assert skeleton("Smiela") == skeleton("Smila")
    assert skeleton("Tchernigov") == skeleton("Chernigov")
    assert skeleton("Кременчуг") == skeleton("Krementchug")
    # Двойные буквы сводятся до выброса гласных: это разные сёла.
    assert skeleton("Tatarinovka") != skeleton("Troyanovka")


def test_gubernia_names_point_to_1897_provinces():
    assert GUBERNIAS["Zhitomir"] == "Волынская губерния"
    assert GUBERNIAS["Crimea"] == GUBERNIAS["Taurida"] == "Таврическая губерния"
    assert GUBERNIAS["District of the Don"] == "Земля войска Донского"
    assert TOWNS_RU["Ekaterinoslav"] == ("Екатеринослав", "Днепр")


class FakeProvinces:
    """Две «губернии»-прямоугольника вместо полигонов 1897 года."""

    def __init__(self):
        self._areas = [
            ("Бессарабская губерния", [], (26.0, 45.0, 29.4, 48.5)),
            ("Херсонская губерния", [], (29.4, 45.0, 34.0, 49.0)),
        ]

    def region_for(self, lat, lon):
        for name, _, (lon_min, lat_min, lon_max, lat_max) in self._areas:
            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                return name
        return None


def place(ident, title, lat, lon, *, town=True, pop=10000, source="wikidata", names=()):
    return Place(source, ident, title, lat, lon, pop, town, list(names))


@pytest.fixture
def locator():
    wd = {
        "кишинев": [place("Q21197", "Кишинёв", 47.02, 28.83, pop=600000)],
        # Бендеры у полигона 1897 года — за Днестром, в Херсонской губернии.
        "бендеры": [place("Q192176", "Бендеры", 46.83, 29.48)],
        "березовка": [place("Q1", "Березовка", 47.2, 30.9, town=False, pop=5),
                      place("Q2", "Березовка", 55.8, 30.5, town=False, pop=15)],
    }
    gn = {skeleton("Bunitchi"): [place("629471", "Буничи", 46.5, 28.0, source="geonames")]}
    return Locator(FakeProvinces(), wd, gn)


def test_locate_inside_named_province(locator):
    found = locator.locate(["Кишинёв"], ["Kishineff"], "Бессарабская губерния")
    assert found.place.ident == "Q21197" and found.how == "Викиданные, «Кишинёв»"
    assert locator.locate(["Кишинёв"], [], "Херсонская губерния").place is None


def test_locate_at_the_edge_when_polygon_is_coarse(locator):
    found = locator.locate(["Бендеры"], ["Bender"], "Бессарабская губерния")
    assert found.place.ident == "Q192176"
    assert "у края губернии" in found.how


def test_locate_by_latin_spelling_in_geonames(locator):
    found = locator.locate([], ["Bunitchi"], "Бессарабская губерния")
    assert found.place.ident == "629471" and "GeoNames" in found.how


def test_without_province_only_a_single_candidate(locator):
    assert locator.locate(["Кишинёв"], [], None).place.ident == "Q21197"
    assert locator.locate(["Березовка"], [], None).place is None


def test_wikidata_rows_keep_settlements_only():
    rows = [
        {"name": {"value": "Смела"}, "item": {"value": "http://www.wikidata.org/entity/Q219595"},
         "coord": {"value": "Point(31.8667 49.2167)"}, "typeLabel": {"value": "город"},
         "pop": {"value": "67000"}},
        {"name": {"value": "Смела"}, "item": {"value": "http://www.wikidata.org/entity/Q9"},
         "coord": {"value": "Point(30 50)"}, "typeLabel": {"value": "река"}},
    ]
    places = wikidata_places(rows)
    assert [p.ident for p in places["смела"]] == ["Q219595"]
    assert places["смела"][0].town and places["смела"][0].population == 67000


def test_table_record(rows):
    rec = table_record(rows[0], Placement(place("Q21197", "Кишинёв", 47.02, 28.83),
                                          "Викиданные, «Кишинёв»"))
    assert rec.title == "Погром — Кишинёв, 1903"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1903, 1903, "day")
    assert rec.period_raw == "April 19 1903"
    assert rec.region == "Бессарабская губерния"
    assert rec.confidence == "place_level" and rec.url == TABLE_PAGE_URL
    assert rec.extra["killed"] == 47 and rec.extra["wounded"] == 424
    assert rec.extra["table_number"] == 1 and rec.extra["town_1906"] == "KISHINEFF"
    assert "убито 47, ранено 424" in rec.summary
    # Разряды — пробелом, а запятая перед «евреев» остаётся запятой.
    assert "население города 147 962, евреев 50 000" in rec.summary
    assert rec.license == POGROMS_1903.license

    lost = table_record(rows[1], Placement(None, "не найден"))
    assert lost.title == "Погром — Batsha, 1903"
    assert lost.date_precision == "month" and lost.confidence == "no_coords"
    assert lost.region == "Бессарабская губерния" and not lost.has_point


def test_build_records_adds_supplement(rows, locator):
    recs = build_records(rows, ["Reval", "Amur", "Reval"], locator)
    table = [r for r in recs if not r.source_id.startswith("ajyb8:suppl")]
    extra = [r for r in recs if r.source_id.startswith("ajyb8:suppl")]
    assert len(table) == 4 and len(extra) == 2           # повтор «Reval» не удваивается
    reval = next(r for r in extra if r.place_text == "Reval")
    assert reval.title == "Погром — Ревель, ноябрь 1905"
    assert reval.date_precision == "month" and reval.date_approx
    amur = next(r for r in extra if r.place_text == "Amur")
    assert amur.confidence == "no_coords" and "не опознан" in amur.extra["place_match"]


def test_date_of_reads_day_back(rows):
    rec = table_record(rows[0], Placement(None, "не найден"))
    assert pg.date_of(rec).isoformat() == "1903-04-19"
    rec2 = table_record(rows[3], Placement(None, "не найден"))
    assert pg.date_of(rec2) is None


def test_row_dataclass_is_frozen():
    row = Row(1, 1903, "April 19", "X", "Y", None, None, "", "")
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.number = 2  # type: ignore[misc]
