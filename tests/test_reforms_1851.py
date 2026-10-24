"""Волнения 1851–1871 годов и уезд после реформ (пакет Dower, Finkel, Gehlbach, Nafziger).

Сети нет. Строки сняты с `event_data_replication.dta` и
`variables_replication.dta` как есть: все события Елецкого уезда
(masterid 255) за 1858–1864 годы, одно из них — общее для шести уездов,
строка переменных Елецкого уезда и пустая строка Ясского уезда. Проверяется,
что записи «уезд-год» без точки, что роды действий посчитаны, что текст
говорит числами пакета и что уезд сведён с RISTAT.
"""

import pytest

from histctx.schema import SCOPE_REGION
from histctx.sources.reforms_1851 import (
    CATEGORY_COMMUNES, CATEGORY_LARGE, CATEGORY_LOCAL, CATEGORY_REDEMPTION, CATEGORY_SCHOOLS,
    CATEGORY_SERFS, CATEGORY_ZEMSTVO_1864, CATEGORY_ZEMSTVO_1883, DATASET_URL, FILES,
    PEASANT_UNREST, REFORMS_UEZD, REQUIRED_VARIABLES, Places, ReformsError, check_columns,
    group_events, reforms_records, serfs_record, shared_events, unrest_records,
    zemstvo_1883_record,
)
from histctx.sources.uezd_names import RistatDistricts


def _event(accessid, year, *codes, large=0, tsgaor=0, masterid=255, coded=True):
    row = {"masterid": masterid, "accessid": accessid, "startyear": year, "large": large,
           "a_large": large if coded else None, "a_tsgaor": tsgaor if coded else None,
           "a": 1 if coded else None}
    for code in codes:
        row[code] = 1
        row[code[:2]] = 1
    return row


ELETS_EVENTS = [
    _event(682, 1858, "ar2"),
    _event(822, 1858, "ar2", "ar7", "at36", large=1),
    _event(831, 1858, "ar2", tsgaor=1),
    _event(1013, 1859, "ar10", large=1, tsgaor=1),
    _event(1452, 1860, "ac13"),
    _event(1617, 1861, "ar2", "ar7", tsgaor=1),
    _event(2745, 1862, "ar2"),
    _event(3258, 1864, "ar2", "at23", "at36"),
]
# Событие 1013 записано в шести уездах; здесь — ещё в одном.
ELSEWHERE = [_event(1013, 1859, "ar10", large=1, tsgaor=1, masterid=256)]
# Без кода действия: статья такие строки не считает.
UNCODED = [{"masterid": 255, "accessid": 4000, "startyear": 1853, "at20": 1, "large": 0}]

ELETS = {
    "masterid": 255, "province": "Orlov", "uezd": "Eletskii", "maleserfs_1857": 35168,
    "femaleserfs_1857": 35563, "bushenmalepop1858": 100821, "bushenfemalepop1858": 102399,
    "serfperc1": 0.34805136919021606, "householdserfs_1859": 6735,
    "barshchinaserfs_1859": 24014.6796875, "obrokserfs_1859": 4402.31982421875,
    "redeemingcommunes_1877": 230, "redeemingsouls_1877": 18970, "obligatedcommunes_1877": 170,
    "obligatedsouls_1877": 10668, "curia1reps_1864": 33, "curia2reps_1864": 10,
    "curia3reps_1864": 28, "peasantrepresentation_1864": 39.43661880493164,
    "peasantuglasnye3rdcuria_1883": 20, "totaluglasnye3rdcuria_1883": 28,
    "zeducexp1883": 14171, "zmedicalexp1883": 42306, "ztotalexp1883": 114369,
    "schools_1860": 8, "totalschools1880": 52, "boysenrolled1880": 2358,
    "girlsenrolled1880": 150, "communes_1893": 529, "communesettlements_1893": 571,
    "communehhs_1893": 34721, "communelandlesshhs_1893": 743, "bushendataissues1858": None,
    "latitude": 52.6, "longitude": 38.5,
}
IASSKII = {"masterid": 26, "province": "Bessarabia", "uezd": "Iasskii",
           **{k: None for k in REQUIRED_VARIABLES if k not in ("masterid", "province", "uezd")}}
JOIN = [{"province_name": "Orlov", "uezd_name": "Eletskii", "masterid": "255", "gis_id": "1"},
        {"province_name": "", "uezd_name": "Dinaburgskii", "masterid": "460", "gis_id": ""}]

INDEX = RistatDistricts([
    {"properties": {"Distr_ID": 461, "Name_RU": "Елецкий", "Name_ENG": "Eletskii",
                    "prov_RU": "Орловская губерния", "RISTAT_ID": "1897_51"}},
    {"properties": {"Distr_ID": 349, "Name_RU": "Белецкий", "Name_ENG": "Beletskii",
                    "prov_RU": "Бессарабская губерния", "RISTAT_ID": "1897_07"}},
    {"properties": {"Distr_ID": 520, "Name_RU": "Двинский", "Name_ENG": "Dvinskii",
                    "prov_RU": "Витебская губерния", "RISTAT_ID": "1897_92"}},
])
PLACES = Places([ELETS, IASSKII], JOIN, INDEX)


@pytest.fixture(scope="module")
def unrest():
    return unrest_records(ELETS_EVENTS + ELSEWHERE + UNCODED, PLACES)


def test_files_and_layers_are_declared():
    assert {f.name for f in FILES} >= {"event_data_replication.dta", "variables_replication.tab",
                                       "UezdJoin.tab"}
    assert PEASANT_UNREST.status == REFORMS_UEZD.status == "harvested"
    assert "CC0" in PEASANT_UNREST.license and PEASANT_UNREST.url == DATASET_URL


def test_events_grouped_by_district_and_year():
    groups = group_events(ELETS_EVENTS)
    assert sorted(groups) == [(255, 1858), (255, 1859), (255, 1860), (255, 1861), (255, 1862),
                              (255, 1864)]
    assert len(groups[(255, 1858)]) == 3
    assert shared_events(ELETS_EVENTS + ELSEWHERE) == {1013}


def test_unrest_records_are_territorial_district_years(unrest):
    elets = [r for r in unrest if r.extra["masterid"] == 255]
    assert len(elets) == 7                       # шесть лет с кодом и 1853 год без кода
    for rec in elets:
        assert rec.scope == SCOPE_REGION and not rec.has_point
        assert rec.region == "Орловская губерния" and rec.district == "Елецкий уезд"
        assert rec.regions == ["Орловская губерния"]
        assert rec.year_from == rec.year_to and rec.date_precision == "year"
        assert rec.work == "Крестьянское движение в России"
        assert rec.extra["ristat_distr_id"] == "461" and rec.confidence == "ok"
        assert rec.url == DATASET_URL


def test_unrest_summary_counts_kinds(unrest):
    rec = next(r for r in unrest if r.extra["masterid"] == 255 and r.year_from == 1858)
    assert rec.title == "Елецкий уезд Орловской губернии: крестьянские волнения 1858 года"
    assert rec.category == CATEGORY_LARGE
    assert rec.extra["unrest"] == {"events": 3, "kinds": {"ar": 3, "at": 1}, "large": 1,
                                   "tsgaor": 1, "uncoded": 0, "shared": 0}
    assert "записала в уезде 3 выступления" in rec.summary
    assert "отказ от повинностей, выкупа или условий освобождения — 3" in rec.summary
    assert "захват, насилие" in rec.summary and "— 1" in rec.summary
    assert rec.extra["codes"] == {"ar2": 3, "ar7": 1, "at36": 1}
    assert rec.extra["access_ids"] == [682, 822, 831]


def test_unrest_shared_and_uncoded_events_are_said(unrest):
    shared = next(r for r in unrest if r.extra["masterid"] == 255 and r.year_from == 1859)
    assert "записаны сразу в нескольких уездах — 1" in shared.summary
    complaint = next(r for r in unrest if r.extra["masterid"] == 255 and r.year_from == 1860)
    assert complaint.category == CATEGORY_LOCAL and "жалоба властям — 1" in complaint.summary
    uncoded = next(r for r in unrest if r.year_from == 1853)
    assert uncoded.extra["unrest"]["uncoded"] == 1
    assert "без кода действия" in uncoded.summary


def test_dinaburg_district_without_province_is_vitebsk():
    place = PLACES.get(460)
    assert place.province == "Витебская губерния" and place.district == "Динабургский уезд"
    assert place.distr_id == "520" and place.how == "manual"


def test_reforms_records_for_elets():
    recs = reforms_records([ELETS, IASSKII], PLACES)
    # У Ясского уезда в пакете пусто — записей нет, а не записи с нулями.
    assert {r.extra["masterid"] for r in recs} == {255}
    by = {r.category: r for r in recs}
    assert set(by) == {CATEGORY_SERFS, CATEGORY_REDEMPTION, CATEGORY_ZEMSTVO_1864,
                       CATEGORY_ZEMSTVO_1883, CATEGORY_SCHOOLS, CATEGORY_COMMUNES}
    serfs = by[CATEGORY_SERFS]
    assert (serfs.year_from, serfs.year_to) == (1857, 1859)
    assert serfs.work == "Отмена крепостного права"
    assert "70 731 крепостной" in serfs.summary
    assert "203 220 человек" in serfs.summary and "крепостные — 35%" in serfs.summary
    assert "на барщине 68%, на оброке 13%, дворовых 19%" in serfs.summary
    redemption = by[CATEGORY_REDEMPTION]
    assert redemption.work == "Выкупная операция" and redemption.year_from == 1877
    assert "230 сельских обществ (18 970 душ)" in redemption.summary
    assert "170 (10 668 душ) — 36% душ" in redemption.summary
    zemstvo = by[CATEGORY_ZEMSTVO_1864]
    assert "71 гласный" in zemstvo.summary and "от сельских обществ 28 — 39% мест" in \
        zemstvo.summary
    z83 = by[CATEGORY_ZEMSTVO_1883]
    assert "28 гласных, из них крестьян 20" in z83.summary
    assert "На народное образование ушло 12% расходов уездного земства, на медицину 37%" \
        in z83.summary
    assert z83.extra["columns"]["ztotalexp1883"] == 114369
    schools = by[CATEGORY_SCHOOLS]
    assert "52 сельские начальные школы (в 1860 году — 8)" in schools.summary
    communes = by[CATEGORY_COMMUNES]
    assert "529 сельских обществ в 571 селении, 34 721 двор" in communes.summary
    assert "безземельных 743 (2,1%)" in communes.summary
    for rec in recs:
        assert rec.scope == SCOPE_REGION and not rec.has_point
        assert rec.district == "Елецкий уезд" and rec.extra["uezd_lat_lon"] == [52.6, 38.5]


def test_zero_serfs_and_broken_shares():
    north = {**ELETS, "maleserfs_1857": 0, "femaleserfs_1857": 0,
             "bushendataissues1858": "Bushen pop data wrong"}
    built = serfs_record(north)
    assert "крепостных в уезде не числилось" in built[6]
    assert "пометка составителей" in built[6]
    broken = zemstvo_1883_record({**ELETS, "zeducexp1883": 200000})
    assert "в текст не пересказываются" in broken[6]


def test_missing_columns_stop_the_harvest():
    with pytest.raises(ReformsError, match="masterid"):
        check_columns(["province", "uezd"], ("masterid", "province"), "variables")
