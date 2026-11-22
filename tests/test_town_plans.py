"""Разбор каталога Imperiia «PSZ Town Plans»: регулярные планы городов 1766–1831.

Сети в тестах нет. Образец — предметы Omeka Classic в том виде, в каком их
отдаёт `/api/items?item_type=38`: элементы Dublin Core и Item Type Metadata,
город и губерния латиницей с кириллицей в скобках, геолокации отдельным
списком со ссылкой на предмет.

Проверяется то, на чём слой держится: поля и подписи по-русски, год плана и
редакция, точка из геолокаций, губерния 1897 года по полигонам (и по
соседству, когда точка в устье), пометка `check`, когда наместничество плана
и губерния точки не сходятся, — с кандидатом-тёзкой из GeoNames, — и чтение
страниц из кэша без сети.
"""

import json

import pytest

from histctx.frame import Frame
from histctx.registry import BY_SLUG
from histctx.schema import ContextRecord
from histctx.sources import town_plans
from histctx.sources.town_plans import (
    ITEM_PAGE, TOWN_PLANS, TownPlansError, bilingual, element_texts, fetch_all, fill_points,
    geolocations_by_item, mark_frame, plan_record, plan_year, records, stem,
)


def element(name, text, element_set="Item Type Metadata"):
    return {"html": False, "text": text, "element_set": {"name": element_set},
            "element": {"name": name}}


def item(item_id, town, province, year, number="99", edition="first", **more):
    texts = [
        element("Title", f"Plan of the town of {town}", "Dublin Core"),
        element("Subject", "urban history", "Dublin Core"),
        element("Description", "Аннотация проекта — в слой не идёт.", "Dublin Core"),
        element("Plan Date", year),
        element("Town", town),
        element("Province", province),
        element("Plan Number", number),
        element("Plan Edition", edition),
        element("Feature Diversity", more.pop("diversity", "low")),
        element("UUID", "92f9be92-b11c-4306-b72d-be1c36a41480", "IIIF Item Metadata"),
    ]
    if "orientation" in more:
        texts.append(element("Plan Orientation", more.pop("orientation")))
    return {"id": item_id, "element_texts": texts, "collection": {"id": 44}}


ITEMS = [
    item(3128, "Yekaterinoslav (Екатеринослав)",
         "Yekaterinoslav Province (Екатеринославская губерния)", "1817", "99",
         orientation="south"),
    item(3129, "Kharkov (Харьков)", "Kharkov Province (Харьковское наместничество)",
         "1786", "368"),
    item(3130, "Kharkov (Харьков)", "Kharkov Province (Харьковское наместничество)",
         "1822", "369", edition="second", diversity="high"),
    item(3131, "Ardatov (Ардатов)", "Nizhegorod Province (Нижегородская губерния)",
         "1781", "188"),
    item(3132, "Nowhere (Нигде)", "Nowhere Province (Нигдейская губерния)", "без даты"),
    item(3133, "Saint Petersburg (Санкт-Петербург)",
         "Saint Petersburg Province (Санктпетербургская губерния)", "1831", "2"),
]
GEOS = [
    {"id": 55, "latitude": 48.47, "longitude": 34.96, "item": {"id": 3128}},
    {"id": 56, "latitude": 50.0, "longitude": 36.25, "item": {"id": 3129}},
    {"id": 57, "latitude": 50.0, "longitude": 36.25, "item": {"id": 3130}},
    # Точка у одноимённого Ардатова в соседней губернии — ошибка источника.
    {"id": 58, "latitude": 54.84, "longitude": 46.24, "item": {"id": 3131}},
    {"id": 59, "latitude": "не число", "longitude": 1, "item": {"id": 3132}},
]


@pytest.fixture
def recs():
    return {r.source_id: r for r in records(ITEMS, GEOS)}


def test_layer_is_registered_as_harvested():
    assert BY_SLUG["town_plans"] is TOWN_PLANS
    assert TOWN_PLANS.status == "harvested" and TOWN_PLANS.expected_rows
    assert "общественное достояние" in TOWN_PLANS.license
    assert "не копируются" in TOWN_PLANS.license


def test_fields_and_bilingual_names():
    fields = element_texts(ITEMS[0])
    assert fields["Plan Date"] == "1817" and fields["Plan Number"] == "99"
    assert bilingual("Yekaterinoslav (Екатеринослав)") == ("Yekaterinoslav", "Екатеринослав")
    assert bilingual("Orenburg Province (Оренбургская (губерния))")[0].startswith("Orenburg")
    assert bilingual("Kazan") == ("Kazan", None)
    assert bilingual(None) == (None, None)
    assert plan_year("1786") == 1786 and plan_year("ок. 1829 г.") == 1829
    assert plan_year("без даты") is None


def test_record_is_a_fact_with_a_link(recs):
    rec = recs["3129"]
    assert rec.title == "Регулярный план: Харьков, 1786"
    assert rec.category == "регулярный план города"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1786, 1786, "year")
    assert rec.place_text == "Харьков, Харьковское наместничество"
    assert rec.url == ITEM_PAGE.format(3129)
    assert "план № 368" in rec.summary and "первая редакция" in rec.summary
    assert rec.confidence == "place_level"
    assert rec.extra["province_at_plan"] == "Харьковское наместничество"
    assert rec.extra["town_latin"] == "Kharkov"
    # Аннотация проекта в запись не попадает.
    assert "Аннотация" not in rec.summary
    assert "вторая редакция" in recs["3130"].summary
    assert recs["3128"].extra["orientation"] == "south"


def test_no_year_no_record_and_no_point_is_flagged(recs):
    assert "3132" not in recs
    assert plan_record(ITEMS[4], (50.0, 30.0)) is None, "без года плана записи нет"
    assert recs["3133"].confidence == "no_coords" and not recs["3133"].has_point
    assert geolocations_by_item(GEOS) == {
        3128: (48.47, 34.96), 3129: (50.0, 36.25), 3130: (50.0, 36.25), 3131: (54.84, 46.24)}


def test_records_are_sorted_by_year():
    years = [r.year_from for r in records(ITEMS, GEOS)]
    assert years == sorted(years)


# --- рамка ----------------------------------------------------------------------

def _square(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def _frame(tmp_path):
    provinces = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"prov_RU": "Харьковская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(35.0, 49.0, 38.0, 51.0)}},
        {"type": "Feature", "properties": {"prov_RU": "Екатеринославская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(33.0, 47.0, 35.0, 49.0)}},
        {"type": "Feature", "properties": {"prov_RU": "Нижегородская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(42.0, 55.0, 45.0, 56.0)}},
        {"type": "Feature", "properties": {"prov_RU": "Симбирская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(45.0, 54.0, 48.0, 55.0)}},
    ]}
    states = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"state": "Россия (Советский Союз)"},
         "geometry": {"type": "Polygon", "coordinates": _square(30.0, 46.0, 50.0, 57.0)}},
        {"type": "Feature", "properties": {"state": "Румыния"},
         "geometry": {"type": "Polygon", "coordinates": _square(20.0, 44.0, 29.0, 48.0)}},
    ]}
    (tmp_path / "provinces_1897.geojson").write_text(json.dumps(provinces), encoding="utf-8")
    (tmp_path / "state_borders.geojson").write_text(json.dumps(states), encoding="utf-8")
    return Frame.load(tmp_path)


def town(title, lat, lon):
    return ContextRecord(layer="settlements", title=title, lat=lat, lon=lon, category="город")


def test_frame_province_check_and_namesake(tmp_path, recs):
    towns = [town("Ардатов", 55.24, 43.10), town("Ардатов", 54.85, 46.24)]
    counts = mark_frame(recs.values(), _frame(tmp_path), towns)
    assert recs["3129"].region == "Харьковская губерния"
    assert "check" not in recs["3129"].extra, "наместничество и губерния — одна основа"
    ardatov = recs["3131"]
    assert ardatov.region == "Симбирская губерния"
    assert "Нижегородская губерния" in ardatov.extra["check"]
    assert "одноимённое место в губернии плана: Ардатов, 55.2400, 43.1000" in \
        ardatov.extra["check"]
    assert (ardatov.lat, ardatov.lon) == (54.84, 46.24), "точка источника не двигается"
    assert counts["без точки"] == 1
    assert counts["губерния точки не совпала с наместничеством плана"] == 1


def test_frame_finds_province_nearby_and_marks_outside(tmp_path):
    near = ContextRecord(layer="town_plans", title="Регулярный план: Устье, 1784",
                         lat=51.1, lon=36.0, extra={"province_at_plan": "Харьковское"})
    outside = ContextRecord(layer="town_plans", title="Регулярный план: Яссы, 1800",
                            lat=47.0, lon=27.5)
    counts = mark_frame([near, outside], _frame(tmp_path))
    assert near.region == "Харьковская губерния"
    assert near.extra["frame"] == "губерния по соседству"
    assert outside.confidence == "outside_bbox" and outside.region is None
    assert counts["вне рамки РИ/СССР"] == 1


def test_stem_ignores_hyphens_and_case():
    assert stem("Санктпетербургская губерния") == stem("Санкт-Петербургская губерния")
    assert stem("Харьковское наместничество") == stem("Харьковская губерния")
    assert stem(None) == ""


def test_missing_point_is_filled_only_by_a_single_namesake_in_the_province(tmp_path):
    frame = _frame(tmp_path)
    plan = ContextRecord(layer="town_plans", title="Регулярный план: Чугуев, 1780",
                         extra={"province_at_plan": "Харьковское наместничество",
                                "town_ru": "Чугуев"})
    twice = ContextRecord(layer="town_plans", title="Регулярный план: Ардатов, 1781",
                          extra={"province_at_plan": "Нижегородская губерния",
                                 "town_ru": "Ардатов"})
    towns = [town("Чугуев", 49.83, 36.69), town("Чугуев", 54.5, 46.5),
             town("Ардатов", 55.24, 43.10), town("Ардатов", 55.3, 43.2)]
    assert fill_points([plan, twice], frame, towns) == 1
    assert (plan.lat, plan.lon) == (49.83, 36.69), "тёзка в Симбирской губернии не подходит"
    assert plan.extra["point"].startswith("GeoNames") and plan.confidence == "place_level"
    assert not twice.has_point, "два тёзки в губернии плана — точку не угадываем"


# --- сеть: кэш ------------------------------------------------------------------

def test_fetch_reads_pages_from_cache_without_network(tmp_path, monkeypatch):
    def no_network(url, **kw):
        raise AssertionError(f"сеть не нужна: {url}")
    monkeypatch.setattr(town_plans, "_get", no_network)
    page1 = [{"id": i} for i in range(50)]
    page2 = [{"id": 50}]
    (tmp_path / "items_item_type-38_p1.json").write_text(json.dumps(page1), encoding="utf-8")
    (tmp_path / "items_item_type-38_p2.json").write_text(json.dumps(page2), encoding="utf-8")
    got = fetch_all("items", "item_type=38", tmp_path, pause=0)
    assert [x["id"] for x in got] == list(range(51))


def test_api_message_is_an_error(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *a):
            return json.dumps({"message": 'The "item_sets" resource is unavailable.'}).encode()

    monkeypatch.setattr(town_plans.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(TownPlansError, match="unavailable"):
        town_plans._get("https://example.invalid/api/item_sets")
