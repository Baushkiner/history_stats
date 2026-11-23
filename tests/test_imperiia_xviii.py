"""Города 1727 года по Кирилову и уезды по ревизиям (слои Imperiia): только факты.

Сети в тестах нет. Образцы — объекты сервисов в том виде, в каком их отдаёт
сервер (23.11.2026).
"""

from histctx.sources.imperiia_xviii import (
    KIRILOV, KIRILOV_FIELDS, REVISIONS, REVISIONS_UEZD, TOWNS_1727, check_item, check_layer,
    kirilov_record, kirilov_records, revision_record, revision_records,
)

NOVGOROD = {"attributes": {"KID": 16, "Guberniia": "Novgorod", "Location": "Novgorod",
                           "Status": "capital", "Ch_Mnstrs": 834, "Govt_srvnt": 41,
                           "Offcrs_sol": 52, "eparchies": 1, "Monasterie": 98,
                           "Orth_chs": 736, "Zavodov": 2, "geo_river": "Volkhova"},
            "geometry": {"x": 31.27, "y": 58.52}}
TEREK = {"attributes": {"KID": 257, "Guberniia": "Astrakhanskaia", "Location": "Terek",
                        "Status": "pripisnyj", "Govt_srvnt": 0, "Offcrs_sol": 0,
                        "eparchies": 0, "Monasterie": 0, "Orth_chs": 0, "Zavodov": 0},
         "geometry": {"x": 44.15, "y": 43.48}}
TULA = {"attributes": {"GorID": 120, "Location": "Aleksin", "Region": "Central Industrial",
                       "Guberniia": "Tul'skaia", "Uezd__coun": "Aleksin", "First_Revi": 64754,
                       "Second_Rev": 66156, "Third_Revi": 70478},
        "geometry": {"x": 37.06, "y": 54.51}}
FIRST, SECOND, THIRD = REVISIONS


def test_kirilov_town_counts_are_told_as_town_with_its_district():
    rec = kirilov_record(NOVGOROD)
    assert rec.layer == TOWNS_1727.slug
    assert rec.title == "Новгород (Novgorod) в 1727 году: 736 церквей"
    assert rec.category == "церкви и монастыри"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1727, 1727, "year")
    assert "за городом с его округой числится: 736 церквей, 98 монастырей, 41 приказный " \
           "служитель, 52 офицера и солдата, 2 завода" in rec.summary
    assert "архиерейская кафедра" in rec.summary and "Волхова" in rec.summary
    # Название провинции остаётся в написании набора, регистр не трогается.
    assert "провинция в наборе — Novgorod" in rec.summary
    assert rec.extra["churches"] == 736 and rec.extra["bishopric"] is True
    assert rec.url == KIRILOV.url and rec.mappable


def test_town_without_numbers_is_kept():
    rec = kirilov_record(TEREK)
    assert rec.category == "без церквей в описании"
    assert "чисел за ним в наборе нет" in rec.summary
    assert rec.title.endswith("церквей не показано")
    assert kirilov_record({"attributes": {"Location": ""}, "geometry": None}) is None
    assert len(kirilov_records([NOVGOROD, TEREK, {"attributes": {}}])) == 2


def test_revision_is_uezd_population_at_the_town_point():
    rec = revision_record(TULA, FIRST)
    assert rec.layer == REVISIONS_UEZD.slug
    assert rec.title == "Алексин (Aleksin), уезд: I ревизия — 64 754 человек"
    assert (rec.year_from, rec.year_to) == (1719, 1724) and not rec.date_approx
    assert rec.confidence == "place_level"
    assert "число относится ко всему уезду" in rec.summary
    assert rec.extra["population"] == 64754 and rec.extra["revision"] == "1"
    assert revision_record(TULA, SECOND).extra["population"] == 66156


def test_third_slice_is_widened_not_guessed():
    rec = revision_record(TULA, THIRD)
    assert (rec.year_from, rec.year_to) == (1762, 1785) and rec.date_approx
    assert "какая из двух стоит в таблице, не установлено" in rec.summary
    assert rec.period_raw == "в наборе: «3rd revision, 1781»"


def test_zero_means_no_data():
    hetmanate = {"attributes": {"GorID": 1, "Location": "Chernigov", "Guberniia": "Hetmanate",
                                "Uezd__coun": "Chernigov", "First_Revi": 0,
                                "Third_Revi": 203112}, "geometry": {"x": 31.29, "y": 51.5}}
    assert revision_record(hetmanate, FIRST) is None
    assert len(revision_records([hetmanate, TULA], THIRD)) == 2
    a, b = revision_record(TULA, FIRST), revision_record(TULA, SECOND)
    assert a.uid != b.uid


def test_rights_are_stated_as_facts_only():
    for spec in (TOWNS_1727, REVISIONS_UEZD):
        assert "только факты" in spec.license and "не выпущен" in spec.license
        assert spec.status == "harvested" and spec.expected_rows


def test_service_checks_stop_on_access_note():
    info = {"geometryType": "esriGeometryPoint",
            "fields": [{"name": n} for n in KIRILOV_FIELDS]}
    assert check_layer(info, KIRILOV, KIRILOV_FIELDS, KIRILOV.count) == []
    assert check_layer(info, KIRILOV, KIRILOV_FIELDS | {"Нет"}, KIRILOV.count - 1)
    ok = {"owner": "koneill_worldmap", "access": "public", "description": "Kirilov"}
    assert check_item(ok, KIRILOV) == []
    noted = dict(ok, description="This layer is provisional… contact the editor for access")
    assert any("не собирается" in p for p in check_item(noted, KIRILOV))
