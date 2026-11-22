"""Слои атласа Пядышева (Imperiia): селения, укрепления, храмы, заводы, линии, полигоны.

Сети в тестах нет. Образцы — объекты сервисов в том виде, в каком их отдаёт
сервер (22.11.2026), вместе с испорченной кодировкой поля `Name_Rs`.
"""

from histctx.sources.atlas_1820 import (
    ADMIN_BOUNDARIES_1820, AREA_KINDS, ECONOMY_1820, FAITH_1820, FORTIFICATIONS_1820,
    LINE_KINDS, POINT_KINDS, RECORD_LAYERS, ROADS_1820, SETTLEMENTS_1820, area_feature,
    check_count, check_point_layer, feature_to_record, fix_mojibake, line_feature, records,
    russian_name,
)
from histctx.sources.imperiia import cyrillic

KINDS = {kind.key: kind for kind in POINT_KINDS}


def broken(text: str) -> str:
    """Так сервер отдаёт кириллицу: UTF-8, прочитанный как latin-1."""
    return text.encode("utf-8").decode("latin-1")


SELO = {"attributes": {"Cat_Rus_Tr": 8, "Name_Rs": broken("Аврамово"),
                       "Category": "village (selo)", "Placename": "Avramovo", "UnitID": 58,
                       "Prov_name": "Kazanskaia", "GazID": 21, "Admin_3rd": "Tsarevokokshajsk",
                       "Gub_ID": 42, "Source": "Piadyshev Atlas 039", "ObjectId": 1},
        "geometry": {"x": 47.9, "y": 56.6}}
TOWN = {"attributes": {"Placename": "Ufa", "GazID": 3712, "Source": "Piadyshev Atlas 050",
                       "District": "Ufa", "Province": "Orenburgskaia", "ObjectId": 1},
        "geometry": {"x": 55.95, "y": 54.73}}


def test_russian_name_is_repaired_or_transliterated():
    assert fix_mojibake(broken("Прочной Окоп")) == "Прочной Окоп"
    assert fix_mojibake("Уфа") == "Уфа" and fix_mojibake(None) == ""
    assert russian_name(SELO["attributes"]) == ("Аврамово", True)
    assert russian_name(TOWN["attributes"]) == ("Уфа", False)
    # «неизвестно» в наборе — не название.
    assert russian_name({"Name_Rs": broken("неизвестно"), "Placename": "neizvestno"})[1] is False


def test_transliteration_of_endings():
    assert cyrillic("Orenburgskaia guberniia") == "Оренбургская губерния"
    assert cyrillic("Feodosiia") == "Феодосия"


def test_village_with_native_name():
    rec = feature_to_record(SELO, KINDS["selo"])
    assert rec.layer == SETTLEMENTS_1820.slug and rec.group == "admin"
    assert rec.title == "Село Аврамово (Avramovo)" and rec.category == "село или слобода"
    assert (rec.year_from, rec.year_to) == (1820, 1827)
    assert rec.place_text == "Avramovo, Tsarevokokshajsk, Kazanskaia"
    assert "лист 39" in rec.summary and "как в наборе" in rec.summary
    assert "выборка" in rec.summary
    assert rec.extra["name_source"] == "набор" and rec.extra["gaz_id"] == 21
    assert rec.mappable


def test_town_from_the_other_field_layout():
    rec = feature_to_record(TOWN, KINDS["provincial_town"])
    assert rec.title == "Губернский город Уфа (Ufa)"
    assert rec.place_text == "Ufa, Ufa, Orenburgskaia"
    assert "обратная транслитерация" in rec.summary and "выборка" not in rec.summary
    assert rec.extra["name_source"] == "транслитерация"


def test_other_layers_and_special_cases():
    fortress = {"attributes": {"Cat_Rus_Tr": 19, "Name_Rs": broken("Св. Николая"),
                               "Category": "fortress", "Placename": "Sv. Nikolaia",
                               "Prov_name": "Kavkazskaia", "GazID": 271,
                               "Admin_3rd": "Stavropol", "Source": "Piadyshev Atlas 044",
                               "ObjectId": 1}, "geometry": {"x": 41.0, "y": 45.3}}
    rec = feature_to_record(fortress, KINDS["fortress"])
    assert rec.layer == FORTIFICATIONS_1820.slug and rec.group == "military"
    assert rec.title == "Крепость Св. Николая (Sv. Nikolaia)"

    mosque = {"attributes": {"Name_Rs": broken("неизвестно"), "Placename": "neizvestno",
                             "Prov_name": "Omskaia", "GazID": 7496, "Admin_3rd": "Omsk",
                             "Source": "Piadyshev Atlas 054", "ObjectId": 1},
              "geometry": {"x": 73.0, "y": 54.9}}
    rec = feature_to_record(mosque, KINDS["mosque"])
    assert rec.layer == FAITH_1820.slug and rec.title == "Мечеть без названия"

    customs = {"attributes": {"Placename": "Feodosiia", "GazID": 16062, "Cat_Code": 2,
                              "Source": "Piadyshev Atlas 025", "District": "Feodosiia",
                              "Province": "Tavricheskaia", "ObjectId": 2},
               "geometry": {"x": 35.38, "y": 45.03}}
    rec = feature_to_record(customs, KINDS["customs"])
    assert rec.layer == ECONOMY_1820.slug and rec.title == "Таможня Феодосия (Feodosiia)"
    assert "уездный город" in rec.summary

    walled = {"attributes": {"Cat_Rus_Tr": 35, "Name_Rs": broken("Тарки"),
                             "Category": "small fortified town", "Placename": "Tarki",
                             "Prov_name": "Gruziia", "GazID": 377, "Admin_3rd": "Tarki",
                             "Source": "Piadyshev Atlas 045", "ObjectId": 1},
              "geometry": {"x": 47.5, "y": 42.95}}
    assert feature_to_record(walled, KINDS["walled_town"]).category == "малый укреплённый город"


def test_object_without_point_or_name():
    no_point = {"attributes": dict(SELO["attributes"]), "geometry": None}
    assert feature_to_record(no_point, KINDS["selo"]).confidence == "no_coords"
    assert records([SELO, {"attributes": {}}], KINDS["selo"]) and \
        len(records([SELO, {"attributes": {}}], KINDS["selo"])) == 1


def test_same_gazetteer_id_in_two_services_gives_two_uids():
    a = feature_to_record(SELO, KINDS["selo"])
    b = feature_to_record(SELO, KINDS["derevnia"])
    assert a.uid != b.uid


def test_line_is_simplified_and_typed():
    kind = next(k for k in LINE_KINDS if k.key == "post_road")
    feature = {"attributes": {"TYPE": "Postal Road", "SHEET": "Atlas 011", "LengthKm": 22.34},
               "geometry": {"paths": [[[30.0, 55.0], [30.5, 55.00001], [31.0, 55.0]]]}}
    out = line_feature(feature, kind)
    assert out["geometry"] == {"type": "LineString", "coordinates": [[30.0, 55.0], [31.0, 55.0]]}
    assert out["properties"]["type"] == "почтовая дорога"
    assert out["properties"]["atlas_sheet"] == 11 and out["properties"]["length_km"] == 22.3
    assert line_feature({"attributes": {}, "geometry": {"paths": []}}, kind) is None
    canal = next(k for k in LINE_KINDS if k.key == "canal")
    named = line_feature({"attributes": {"NAME": "Berezinskoj canal"},
                          "geometry": {"paths": [[[28.0, 54.0], [28.5, 54.5]]]}}, canal)
    assert named["properties"]["name_latin"] == "Berezinskoj canal"
    unnamed = line_feature({"attributes": {"NAME": "?"},
                            "geometry": {"paths": [[[28.0, 54.0], [28.5, 54.5]]]}}, canal)
    assert "name" not in unnamed["properties"]


def test_area_gets_both_names_and_parent():
    province = next(k for k in AREA_KINDS if k.key == "guberniia")
    ring = [[50.0, 52.0], [50.0, 53.0], [51.0, 53.0], [51.0, 52.0], [50.0, 52.0]]
    out = area_feature({"attributes": {"Name_trs": "Orenburgskaia guberniia", "SheetID": 50,
                                       "AreaSqKm": 384715.4, "GazID": 13417,
                                       "AdminType": "guberniia"},
                        "geometry": {"rings": [ring]}}, province)
    props = out["properties"]
    assert props["name"] == "Оренбургская губерния" and props["type"] == "губерния"
    assert props["level"] == "province" and props["area_km2"] == 384715
    assert out["geometry"]["type"] == "Polygon"
    uezd = next(k for k in AREA_KINDS if k.key == "uezd")
    out = area_feature({"attributes": {"Name_trs": "Buzuluk", "Admin_2nd": "Orenburgskaia",
                                       "Source": "Piadyshev Atlas 050"},
                        "geometry": {"rings": [ring]}}, uezd)
    assert out["properties"]["province"] == "Оренбургская"
    assert out["properties"]["atlas_sheet"] == 50
    assert area_feature({"attributes": {}, "geometry": {"rings": []}}, uezd) is None


def test_service_checks():
    kind = KINDS["selo"]
    info = {"geometryType": "esriGeometryPoint",
            "fields": [{"name": n} for n in ("Placename", "Prov_name", "Admin_3rd", "Source",
                                             "GazID")]}
    assert check_point_layer(info, kind, kind.count) == []
    other = {"geometryType": "esriGeometryPoint",
             "fields": [{"name": n} for n in ("Placename", "Province", "District", "Source",
                                              "GazID")]}
    assert check_point_layer(other, kind, kind.count) == []
    assert check_point_layer({"geometryType": "esriGeometryPoint", "fields": []}, kind, 1)
    line = LINE_KINDS[0]
    assert check_count(line, line.count, "esriGeometryPolyline", "esriGeometryPolyline") == []
    assert check_count(line, line.count - 1, "esriGeometryPolygon", "esriGeometryPolyline")


def test_layer_cards_add_up():
    by_layer = {}
    for kind in POINT_KINDS:
        by_layer[kind.spec.slug] = by_layer.get(kind.spec.slug, 0) + kind.count
    for spec in RECORD_LAYERS:
        assert spec.expected_rows == by_layer[spec.slug], spec.slug
    assert len({k.key for k in POINT_KINDS}) == len(POINT_KINDS)
    assert not ROADS_1820.gives_records and not ADMIN_BOUNDARIES_1820.gives_records
    assert ADMIN_BOUNDARIES_1820.expected_rows == sum(k.count for k in AREA_KINDS)
