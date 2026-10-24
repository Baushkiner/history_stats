"""Мобилизация 1914–1916 годов по уездам (пакет Dower, Markevich).

Сети нет. Строки сняты с `LMMM_district_farmtype.dta` как есть (только
нужные колонки): Тульский уезд, Верхнеднепровский уезд с отрицательной
оценкой числа призванных и Иманский уезд Приморской области, созданный
после 1897 года. Проверяется, что запись — одна на уезд, без точки, что доля
призванных и посевы посчитаны, что неправдоподобная оценка не пересказана
долей и что уезд без пары остаётся с пометкой.
"""

import pytest

from histctx.schema import SCOPE_REGION
from histctx.sources.mobilization_1914 import (
    CATEGORY_NO_DATA, CATEGORY_OK, CATEGORY_SUSPECT, DATASET_URL, MOBILIZATION_1914,
    MobilizationError, check_columns, district_facts, province_name, records,
)
from histctx.sources.uezd_names import RistatDistricts


def _rows(did, district, province, mobilized, rpop, grains):
    """grains: {(год, commune): посевы}; mobiliz2 стоит только в строках 1916 года."""
    return [{"iddistrict": did, "district_latin": district, "province_latin": province,
             "commune": commune, "year": year, "mobiliz2": mobilized if year == 1916 else 0,
             "rpop1912": rpop, "agrains": area}
            for (year, commune), area in grains.items()]


TULA = _rows(678, "1. Tul'skij", "Tul'skaya", 7.827000141143799, 123.9, {
    (1913, 0): 18.081968307495117, (1913, 1): 39.9254150390625,
    (1914, 0): 17.706148147583008, (1914, 1): 36.532108306884766,
    (1916, 0): 6.878379821777344, (1916, 1): 49.43999481201172})
VERKHNEDNEPROVSK = _rows(150, "4. Verhne-dneprovskij", "Ekaterinoslavskaya", -15.597999572753906,
                         298.1, {(1913, 0): 268.93963623046875, (1913, 1): 156.0472412109375,
                                 (1916, 0): 67.47171020507812, (1916, 1): 252.99459838867188})
IMAN = _rows(482, "2. Imanskij", "Primorskaya", 17.45199966430664, 91.8, {
    (1913, 0): 0.4391849935054779, (1913, 1): 54.8402214050293,
    (1916, 0): 0.16059750318527222, (1916, 1): 38.69744110107422})
NO_DATA = _rows(900, "1. Tul'skij", "Tul'skaya", None, 123.9, {(1913, 0): 1.0, (1913, 1): None})

INDEX = RistatDistricts([
    {"properties": {"Distr_ID": 448, "Name_RU": "Тульский", "Name_ENG": "Tulskii",
                    "prov_RU": "Тульская губерния", "RISTAT_ID": "1897_84"}},
    {"properties": {"Distr_ID": 498, "Name_RU": "Верхне-днепровский",
                    "Name_ENG": "Verkhne-Dneprovskii", "prov_RU": "Екатеринославская губерния",
                    "RISTAT_ID": "1897_21"}},
    {"properties": {"Distr_ID": 700, "Name_RU": "Уссурийская", "Name_ENG": "Ussuriiskaia",
                    "prov_RU": "Приморская область", "RISTAT_ID": "1897_60"}},
])


@pytest.fixture(scope="module")
def recs():
    return {r.source_id: r for r in records(TULA + VERKHNEDNEPROVSK + IMAN + NO_DATA, INDEX)}


def test_layer_card():
    assert MOBILIZATION_1914.group == "military" and MOBILIZATION_1914.status == "harvested"
    assert "CC0" in MOBILIZATION_1914.license


def test_one_record_per_district_without_point(recs):
    assert set(recs) == {"678", "150", "482", "900"}
    for rec in recs.values():
        assert rec.scope == SCOPE_REGION and not rec.has_point
        assert (rec.year_from, rec.year_to) == (1914, 1916)
        assert rec.work == "Первая мировая война: мобилизация" and rec.url == DATASET_URL


def test_share_and_grain_area(recs):
    tula = recs["678"]
    assert tula.title == "Тульский уезд Тульской губернии: мобилизация 1914–1916 годов"
    assert tula.category == CATEGORY_OK and tula.confidence == "ok"
    assert "призвано в армию 7 827 человек — 6,3% сельского населения 1912 года (123,9 тыс.)" \
        in tula.summary
    assert "58 тыс. га в 1913 году, 56,3 тыс. га в 1916 году (−3%)" in tula.summary
    assert tula.extra["mobiliz2_thousands"] == 7.827
    assert tula.extra["ristat_distr_id"] == "448" and tula.extra["ristat_match"] == "exact"


def test_implausible_estimate_is_not_told_as_share(recs):
    rec = recs["150"]
    assert rec.category == CATEGORY_SUSPECT
    assert "−15,6 тыс." in rec.summary and "неправдоподобна" in rec.summary
    assert "%" not in rec.summary.split(".")[0]
    assert rec.district == "Верхне-днепровский уезд"


def test_new_district_stays_with_mark(recs):
    rec = recs["482"]
    assert rec.confidence == "district_unmatched" and rec.district is None
    assert rec.region == "Приморская область"
    assert rec.place_text == "Imanskij (уезд, написание набора), Приморская область"
    assert "19,0% сельского населения" in rec.summary


def test_missing_mobilization_and_half_missing_grain(recs):
    rec = recs["900"]
    assert rec.category == CATEGORY_NO_DATA
    assert "посевы" not in rec.summary.lower()       # одна из двух строк пуста — суммы нет
    facts = district_facts(NO_DATA)
    assert facts["mobilized"] is None and facts["grain_area"] == {}


def test_province_names():
    assert province_name("KHar'kovskaya", None) is None   # без справочника — не угадывать
    assert province_name("S.-Peterburgskaya", None) == "Санкт-Петербургская губерния"
    assert province_name("Batumskaya", INDEX) == "Батумская область"
    assert province_name("Tul'skaya", INDEX) == "Тульская губерния"


def test_missing_columns_stop_the_harvest():
    with pytest.raises(MobilizationError, match="mobiliz2"):
        check_columns(["iddistrict", "district_latin"])
