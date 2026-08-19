"""Разбор итогов переписей 1897 и 1926 годов из набора heiDATA.

Сети в тестах нет: строки таблицы урезаны до нескольких столбцов, но структура
у них та же, что в наборе. Проверяется, что из чисел собирается пригодная
запись, что охват у неё губернский, а не точечный, и что нерасшифрованные
столбцы остаются кодом, а не превращаются в выдуманный народ.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.schema import SCOPE_REGION  # noqa: E402
from histctx.sources.admin_gis import (  # noqa: E402
    ADMIN_GIS, CENSUS_1897, CENSUS_1926, boundaries_geojson, build_summary,
    census_records, group_columns, top_groups,
)

TIFLIS = {
    "NAMERUS": "Тифлисская губерния", "NAMEENG": "Tiflis guberniya",
    "AREAV": 34125.5, "POPALL": 1051032, "POPCITY": 220000, "POPRUR": 831032,
    "LANGEORGIA": 460000, "LANARMENIA": 200000, "LANTATAR": 105000, "LANVRUS": 50000,
    "RELORT": 590000, "RELARMG": 210000, "RELMOHAMME": 190000,
    "ESTPEASANT": 860000, "ESTPHILIST": 102000, "ESTHEREDIT": 29000,
}

CHERKESSK = {
    "NameRUS": "Черкесская АО", "NameENG": "Cherkess AO", "Id": 12,
    "AreaV": 3000.0, "PopALL": 36996.0,
    "Kabardians": 12200.0, "Beskesek_A": 11100.0, "Nogai": 6300.0,
    "Turks": 500.0,
}

FEATURE_1897 = {"type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[44.0, 41.0]]]},
                "properties": TIFLIS}


def test_census_row_becomes_a_regional_record():
    rec = census_records([FEATURE_1897], CENSUS_1897)[0]
    assert rec.title == "Тифлисская губерния: итоги переписи 1897 года"
    assert rec.scope == SCOPE_REGION
    assert rec.regions == ["Тифлисская губерния"]
    assert (rec.year_from, rec.year_to) == (1897, 1897)
    assert rec.layer == ADMIN_GIS.slug
    assert rec.source_id == "1897:Тифлисская губерния"


def test_regional_record_has_no_point_on_purpose():
    """Событие относится ко всей губернии: центроид полигона врал бы о месте."""
    rec = census_records([FEATURE_1897], CENSUS_1897)[0]
    assert not rec.has_point
    assert rec.is_territorial and rec.usable
    assert not rec.mappable


def test_summary_is_built_from_numbers():
    text = build_summary(TIFLIS, CENSUS_1897)
    assert "1 051 032 жителей" in text
    assert "родной язык: грузинский — 44%" in text
    assert "вероисповедание: православные — 56%" in text
    assert "сословие: крестьяне — 82%" in text


def test_whole_table_is_kept_in_extra():
    """Три крупнейшие группы — в описание, вся раскладка — в запись целиком."""
    rec = census_records([FEATURE_1897], CENSUS_1897)[0]
    assert rec.extra["census"]["LANVRUS"] == 50000
    assert "CC BY 4.0" in rec.extra["citation"]
    assert rec.url.endswith("doi:10.11588/DATA/10064")


def test_sections_take_their_own_columns():
    assert set(group_columns(TIFLIS, CENSUS_1897, "REL")) == {"RELORT", "RELARMG", "RELMOHAMME"}
    # У 1926 года раздел один, и в него идёт всё, кроме описания самой единицы.
    nations = group_columns(CHERKESSK, CENSUS_1926, "")
    assert "Kabardians" in nations and "NameRUS" not in nations and "PopALL" not in nations


def test_unknown_column_stays_a_code():
    """Часть столбцов 1926 года переведена машинно — угадывать народ нельзя."""
    top = top_groups(CHERKESSK, group_columns(CHERKESSK, CENSUS_1926, ""), 1926)
    assert [name for name, _ in top] == ["кабардинцы", "Beskesek_A", "ногайцы"]


def test_turks_of_1926_are_not_called_turks():
    """В переписи 1926 года «тюрки» — учётное название азербайджанцев."""
    top = top_groups({"Turks": 100.0}, ["Turks"], 1926)
    assert top == [("тюрки (азербайджанцы)", 100.0)]


def test_boundaries_carry_the_licence_and_citation():
    collection = boundaries_geojson([FEATURE_1897], CENSUS_1897)
    assert collection["type"] == "FeatureCollection"
    assert "CC BY 4.0" in collection["license"]
    assert "heidata" in collection["url"]
    assert collection["features"][0]["properties"]["NAMERUS"] == "Тифлисская губерния"


def test_unit_without_a_name_is_skipped():
    assert census_records([{"properties": {"POPALL": 100}}], CENSUS_1897) == []


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    assert BY_SLUG[ADMIN_GIS.slug].status == "harvested"
    assert "CC BY 4.0" in BY_SLUG[ADMIN_GIS.slug].license
