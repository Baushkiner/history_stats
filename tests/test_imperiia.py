"""Почтовые станции атласа Пядышева (Imperiia): разбор объектов сервиса ArcGIS.

Сети в тестах нет. Образцы — объекты сервисов `Post_stations` и `Post_houses`
в том виде, в каком их отдаёт сервер (22.11.2026).
"""

from histctx.sources.imperiia import (
    HOUSES, POST_STATIONS, REQUIRED_FIELDS, STATIONS, check_item, check_layer, cyrillic,
    feature_to_record, records, settlement_type, sheet_number,
)

STATION = {
    "attributes": {"Cat_Rus_Tr": 4, "Placename": "Zhirmony", "UnitID": 571,
                   "Prov_name": "Grodnenskaia", "GazID": 2998, "CountUz": 1,
                   "Admin_3rd": "Lida", "Gub_ID": 30, "Source": "Piadyshev Atlas 004",
                   "PostType": 1, "ObjectId": 2332},
    "geometry": {"x": 25.175646523887607, "y": 54.0484695800646},
}
HOUSE = {
    "attributes": {"Cat_Rus_Tr": 11, "Placename": "Kopan'skaia", "UnitID": 99,
                   "Prov_name": "Kavkazskaia", "GazID": 246, "CountUz": 1,
                   "Admin_3rd": "Black Sea Cossack Host", "Gub_ID": 41,
                   "Source": "Piadyshev Atlas 044", "PostType": 2, "ObjectId": 1},
    "geometry": {"x": 38.4, "y": 46.1},
}


def test_reverse_transliteration_reads_like_russian():
    assert cyrillic("Zhirmony") == "Жирмоны"
    assert cyrillic("Usol'e") == "Усолье"
    assert cyrillic("Gumnishchi") == "Гумнищи"
    assert cyrillic("Ust' Sysol'sk") == "Усть Сысольск"
    assert cyrillic("Ianychi") == "Янычи"
    # «и» после гласной в конце слова — «й».
    assert cyrillic("Staroi Sundyr") == "Старой Сундыр"
    assert cyrillic("") == "" and cyrillic(None) == ""


def test_sheet_and_settlement_type():
    assert sheet_number("Piadyshev Atlas 059") == 59
    assert sheet_number("") is None
    assert settlement_type(9) == "деревня"
    # Коды, которые не удалось расшифровать, остаются числом, а не догадкой.
    assert settlement_type(12) is None


def test_station_becomes_a_dated_point():
    rec = feature_to_record(STATION, STATIONS)
    assert rec.layer == POST_STATIONS.slug
    assert rec.title == "Почтовая станция Жирмоны (Zhirmony)"
    assert rec.category == "станция в селении"
    assert (rec.lat, rec.lon) == (54.04847, 25.17565)
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1820, 1827, "year")
    assert rec.place_text == "Zhirmony, Lida, Grodnenskaia"
    assert "лист 4" in rec.summary and "малый город" in rec.summary
    assert rec.extra["atlas_sheet"] == 4 and rec.extra["gaz_id"] == 2998
    assert rec.url and rec.license.startswith("CC BY-NC-SA 4.0")
    assert rec.mappable


def test_post_house_is_told_apart_from_a_station():
    rec = feature_to_record(HOUSE, HOUSES)
    assert rec.title.startswith("Почтовый двор Копаньская")
    assert rec.category == "почтовый двор при дороге"
    assert "Отдельно стоящий почтовый двор" in rec.summary
    # Один и тот же GazID в двух сервисах не должен дать один uid.
    assert rec.source_id.startswith("house:")


def test_object_without_point_is_kept_and_marked():
    feature = {"attributes": dict(STATION["attributes"]), "geometry": None}
    rec = feature_to_record(feature, STATIONS)
    assert rec.confidence == "no_coords" and not rec.has_point
    assert feature_to_record({"attributes": {}, "geometry": None}, STATIONS) is None
    assert len(records([STATION, {"attributes": {}}], STATIONS)) == 1


def test_service_checks_stop_the_harvest_on_drift():
    info = {"geometryType": "esriGeometryPoint",
            "fields": [{"name": name} for name in REQUIRED_FIELDS]}
    assert check_layer(info, STATIONS, STATIONS.count) == []
    assert any("объектов" in p for p in check_layer(info, STATIONS, 3000))
    broken = {"geometryType": "esriGeometryPolyline", "fields": [{"name": "Placename"}]}
    problems = check_layer(broken, STATIONS, STATIONS.count)
    assert any("геометрия" in p for p in problems) and any("нет полей" in p for p in problems)
    assert check_item({"owner": "koneill_worldmap", "access": "public"}) == []
    assert check_item({"owner": "koneill_worldmap", "access": "private"})


def test_layer_card():
    assert POST_STATIONS.status == "harvested" and POST_STATIONS.expected_rows == 4144
    assert STATIONS.count + HOUSES.count == POST_STATIONS.expected_rows
