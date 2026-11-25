"""Города 1727 года по Кирилову и уезды по ревизиям (слои Imperiia, с согласия владельца).

Сети в тестах нет. Образцы — объекты сервисов в том виде, в каком их отдаёт
сервер (23.11.2026).
"""

from histctx.sources.imperiia_xviii import (
    CLUSTERS, HOUSEHOLDS_1719, KIRILOV, KIRILOV_FIELDS, REVISIONS, REVISIONS_UEZD, TOWNS_1727,
    UEZD_POPULATION_1766, check_item, check_layer, gorid_mismatches, gorid_records,
    gorid_towns, household_record, household_records,
    kirilov_record, kirilov_records, population_1766_record, population_1766_records,
    revision_record, revision_records,
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


def test_rights_state_the_owner_consent():
    for spec in (TOWNS_1727, REVISIONS_UEZD, HOUSEHOLDS_1719, UEZD_POPULATION_1766):
        assert "не выпущен" in spec.license and "согласия владельца" in spec.license
        assert "24.11.2026" in spec.license
        assert spec.status == "harvested" and spec.expected_rows


def test_service_checks_no_longer_stop_on_access_note():
    info = {"geometryType": "esriGeometryPoint",
            "fields": [{"name": n} for n in KIRILOV_FIELDS]}
    assert check_layer(info, KIRILOV, KIRILOV_FIELDS, KIRILOV.count) == []
    assert check_layer(info, KIRILOV, KIRILOV_FIELDS | {"Нет"}, KIRILOV.count - 1)
    ok = {"owner": "koneill_worldmap", "access": "public", "description": "Kirilov"}
    assert check_item(ok, KIRILOV) == []
    # Согласие владельца получено (24.11.2026): оговорка о доступе сбор не держит.
    noted = dict(ok, description="This layer is provisional… contact the editor for access")
    assert check_item(noted, CLUSTERS) == []
    assert check_item(dict(ok, owner="someone"), CLUSTERS)


# Вторая серия 1727 года: сводный слой и отдельные, нумерация GorID.
ZEMLIANSK = {"attributes": {"GorID": 162, "Location": "Zemliansk", "Guberniia": "Voronezhskaia",
                            "Status": "pripisnyj", "State_serv": 3, "Officers__": 0,
                            "Monasterie": 0, "Orthodox_c": 23, "Bishopric": 0, "Factories": 0},
             "geometry": {"x": 38.74, "y": 51.91}}
NOVGOROD_GOR = {"attributes": {"GorID": 16, "Location": "Novgorod", "Guberniia": "Novgorod",
                               "Status": "capital", "State_serv": 41, "Officers__": 52,
                               "Monasterie": 98, "Orthodox_c": 736, "Bishopric": 1,
                               "Factories": 2}, "geometry": {"x": 31.27, "y": 58.52}}
DMITREEV = {"attributes": {"GorID": 254, "Location": "Dmitreev", "Guberniia": "Astrakhanskaia",
                           "Status": "pripisnyj", "Bishopric": 0}, "geometry": {"x": 52.4, "y": 53.9}}
EMPTY = {"attributes": {"GorID": 0, "Location": None, "Guberniia": None, "Bishopric": 0},
         "geometry": None}


def test_second_series_adds_only_towns_missing_from_kirilov_layer():
    towns = gorid_towns([ZEMLIANSK, NOVGOROD_GOR], {"Bishopric": [DMITREEV, EMPTY]})
    assert sorted(towns) == [16, 162, 254]
    recs = gorid_records(towns, [NOVGOROD])
    assert [r.source_id for r in recs] == ["kirilov-gor:162", "kirilov-gor:254"]
    zem = recs[0]
    assert zem.layer == TOWNS_1727.slug and zem.url == CLUSTERS.url
    assert zem.title == "Землянск (Zemliansk) в 1727 году: 23 церкви"
    assert "3 приказных служителя" in zem.summary
    assert "этого города нет" in zem.summary and zem.extra["series"] == "GorID"
    # Город только из отдельного слоя: чисел нет, запись остаётся.
    assert recs[1].category == "без церквей в описании"


def test_separate_layers_are_checked_against_the_summary_layer():
    officials = {"attributes": dict(ZEMLIANSK["attributes"], State_serv=4), "geometry": None}
    assert gorid_mismatches([ZEMLIANSK], {"State_serv": [officials]}) == [
        "Zemliansk: State_serv 4 ≠ 3"]
    assert gorid_mismatches([ZEMLIANSK], {"State_serv": [ZEMLIANSK]}) == []


KOSTROMA = {"attributes": {"GorID": 72, "Location": "Kostroma", "Guberniia": "Moskovskaia",
                           "Province_1": "Kostroma",
                           "goroda_I_u": "Kostroma, Buj, Sudislav, Liubim, Kaduj",
                           "dvorov": 36184, "iasachnykh": None, "note": None},
            "geometry": {"x": 40.93, "y": 57.77}}
PENZA = {"attributes": {"GorID": 245, "Location": "Penza", "Guberniia": "Kazan",
                        "Province_1": "Penza", "goroda_I_u": "Penza with Ramzaev area",
                        "dvorov": 316, "iasachnykh": 5604, "note": None},
         "geometry": {"x": 45.0, "y": 53.2}}


def test_households_given_for_several_towns_at_once():
    rec = household_record(KOSTROMA)
    assert rec.layer == HOUSEHOLDS_1719.slug
    assert rec.title == "Кострома (Kostroma): I ревизия — 36 184 двора"
    assert rec.category == "несколько городов вместе"
    assert "36 184 податных двора" in rec.summary
    assert "Число дано на несколько городов сразу: Кострома, Буй, Судислав, Любим, Кадуй" \
        in rec.summary
    assert (rec.year_from, rec.year_to) == (1719, 1724) and rec.confidence == "place_level"
    assert rec.extra["households"] == 36184 and rec.extra["yasak"] == 0


def test_yasak_payers_are_counted_separately():
    rec = household_record(PENZA)
    assert rec.category == "город с уездом"
    assert "316 податных дворов, ясачных — 5 604" in rec.summary
    assert "В источнике: Penza with Ramzaev area" in rec.summary
    only_yasak = {"attributes": dict(PENZA["attributes"], dvorov=0), "geometry": None}
    rec = household_record(only_yasak)
    assert rec.title.endswith("5 604 ясачных") and rec.confidence == "no_coords"


def test_not_recorded_gives_no_record():
    terek = {"attributes": {"GorID": 257, "Location": "Terek", "Guberniia": "Astrakhan",
                            "Province_1": "Astrakhan", "goroda_I_u": "Terek", "dvorov": 0,
                            "iasachnykh": None, "note": "not recorded"},
             "geometry": {"x": 44.15, "y": 43.48}}
    assert household_record(terek) is None
    assert len(household_records([terek, KOSTROMA, PENZA])) == 2


def test_population_1766_says_the_unit_is_not_named():
    feature = {"attributes": {"GorID": 245, "Location": "Penza", "Guberniia": "Kazanskaia",
                              "Provintsii": "Penzenskaia", "Uezdnye_go": "Penza",
                              "Uezd_pop": 167788}, "geometry": {"x": 45.0, "y": 53.2}}
    rec = population_1766_record(feature)
    assert rec.layer == UEZD_POPULATION_1766.slug
    assert rec.title == "Пенза (Penza), уезд около 1766 года: 167 788"
    assert (rec.year_from, rec.year_to) == (1766, 1766) and rec.date_approx
    assert "единица счёта не названа" in rec.summary
    assert rec.category == "уезд в провинции" and rec.extra["population"] == 167788
    # «na» и пусто в поле провинции — провинции нет; ноль — нет данных.
    astrakhan = {"attributes": dict(feature["attributes"], Provintsii="na", Uezd_pop=3599),
                 "geometry": feature["geometry"]}
    assert population_1766_record(astrakhan).category == "уезд без провинции"
    empty = {"attributes": dict(feature["attributes"], Uezd_pop=0), "geometry": None}
    assert population_1766_record(empty) is None
    assert len(population_1766_records([feature, astrakhan, empty])) == 2
