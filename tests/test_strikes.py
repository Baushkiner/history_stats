"""Разбор свода рабочих конфликтов 1895–1904 годов.

Сети в тестах нет: образец снят с ингестированного TSV набора IISH
(hdl:10622/LSCGBO) и урезан до нескольких строк — обычная стачка, конфликт
сразу по трём губерниям, строка с уездом вместо губернии и стачка, перешедшая
на 1905 год. Проверяется разбор и отдельно то, что спорные строки остаются в
данных с пометкой, а не выбрасываются.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources.strikes import (  # noqa: E402
    STRIKES, StrikesError, check_columns, conflict_kind, normalize_province,
    parse_int, parse_provinces, record_years, row_to_record, rows_to_records,
)

# Строки набора как есть: числа приходят строками с дробной частью, причины и
# требования — кодовым текстом по-английски.
ROWS = [
    {
        "Date1ORG": "01.01.", "Number": "1.0",
        "Startday": "1", "Startday2": "1", "Startmonth": "1.0",
        "Endday": "5", "Endmonth": "1.0", "BeginYear": "1895.0", "EndYear": "1895.0",
        "Province": "Пермская",
        "LocationofFactory": "Красноуфимский уезд, пос.Михайловский завод",
        "NameofFactory": "Михайловский железоделательный з-д",
        "Theeconomicsector": "8. Metallurgy", "Typeofconflict": "Strike",
        "DurationofStrike": "5.0", "NumberofStrikers": "800.0",
        "Numberofallworkers": "980.0",
        "Demands1": "13. To dismiss masters", "Demands2": "32. To change factory regulations",
        "Outcome": "Unknown", "Police/army": "", "SourceReferences": "1895. Вып.I. 1992. Стр.52.",
    },
    {
        "Date1ORG": "12.05.", "Number": "77.0",
        "Startday": "12", "Startday2": "12", "Startmonth": "5.0",
        "BeginYear": "1899.0", "EndYear": "1899.0",
        "Province": "Архангельская, Вологодская, Олонецкая",
        "LocationofFactory": "лесные промыслы", "NameofFactory": "",
        "Theeconomicsector": "19. Various branches", "Typeofconflict": "Unrest",
        "Cause1": "01. Low wages", "Outcome": "Lost", "Police/army": "Yes",
        "SourceReferences": "1899. Вып.II. Стр.14.",
    },
    {
        "Number": "12.0", "Startmonth": "3.0", "BeginYear": "1901.0", "EndYear": "1901.0",
        "Province": "Белостокский уезд, мест.Супросль",
        "LocationofFactory": "мест.Супросль", "NameofFactory": "суконная ф-ка",
        "Theeconomicsector": "3. Wool processing", "Typeofconflict": "Collective strike",
        "Outcome": "Victory", "Police/army": "", "SourceReferences": "1901. Вып.I. Стр.9.",
    },
    {
        "Number": "300.0", "Startmonth": "12.0", "BeginYear": "1904.0", "EndYear": "1905.0",
        "Province": "[Бакинская]", "LocationofFactory": "Баку", "NameofFactory": "нефтепромыслы",
        "Theeconomicsector": "14. Mining", "Typeofconflict": "General strike",
        "Outcome": "Settled", "Police/army": "Yes", "SourceReferences": "1904. Вып.III. Стр.71.",
    },
]


def test_columns_are_checked_before_parsing():
    """Набор переделали — сбор останавливается, а не выдаёт пустой слой."""
    with pytest.raises(StrikesError) as exc:
        check_columns(["Province", "NameofFactory"])
    assert "BeginYear" in str(exc.value)


def test_numbers_come_as_floats_in_strings():
    assert parse_int("1895.0") == 1895
    assert parse_int(" 800 ") == 800
    assert parse_int("") is None
    assert parse_int("нет") is None


def test_province_becomes_a_territory_name():
    assert normalize_province("Пермская") == "Пермская губерния"
    assert normalize_province("Терская обл.") == "Терская область"
    assert normalize_province("[Варшавская]") == "Варшавская губерния"
    assert normalize_province("Область Войска Донского") == "Область Войска Донского"
    # Два написания одной территории сводятся к одному: иначе Область Войска
    # Донского распалась бы на две при подборе.
    assert normalize_province("Област Войска Донского") == "Область Войска Донского"


def test_a_district_is_not_passed_off_as_a_province():
    assert normalize_province("Белостокский уезд, мест.Супросль") is None
    assert normalize_province("Екатеринослав") is None


def test_several_provinces_are_kept_as_a_list():
    """Промыслы шли по трём губерниям — схема это держит, терять незачем."""
    assert parse_provinces("Архангельская, Вологодская, Олонецкая") == [
        "Архангельская губерния", "Вологодская губерния", "Олонецкая губерния",
    ]
    # Но только если каждая часть — губерния.
    assert parse_provinces("Белостокский уезд, мест.Супросль") == []


def test_conflict_kind_is_translated_and_unknown_values_survive():
    assert conflict_kind("Secret meeting, mayovka") == "Тайная сходка, маёвка"
    assert conflict_kind("Something new") == "Something new"
    assert conflict_kind("") is None


def test_dates_and_precision():
    assert record_years(ROWS[0]) == (1895, 1895, "day")
    assert record_years(ROWS[2]) == (1901, 1901, "month")


def test_record_is_territorial_and_usable():
    rec = row_to_record(ROWS[0])
    assert rec.layer == STRIKES.slug
    assert rec.scope == "region"
    assert rec.region == "Пермская губерния"
    assert rec.district == "Красноуфимский уезд"
    assert rec.usable and not rec.has_point
    assert rec.title.startswith("Стачка: Михайловский")
    assert "участвовали 800 из 980 рабочих" in rec.summary
    assert rec.url == STRIKES.url
    assert rec.license.startswith("CC0")


def test_police_and_demands_go_to_extra():
    rec = row_to_record(ROWS[1])
    assert rec.extra["police_or_army"] is True
    assert rec.extra["causes"] == ["01. Low wages"]
    assert rec.regions == [
        "Архангельская губерния", "Вологодская губерния", "Олонецкая губерния",
    ]


def test_unparsed_province_is_marked_not_dropped():
    """Правило репозитория: спорное помечается и остаётся в данных."""
    records = rows_to_records(ROWS)
    assert len(records) == len(ROWS)
    bad = [r for r in records if r.confidence == "province_unparsed"]
    assert len(bad) == 1
    assert bad[0].extra["province_raw"] == "Белостокский уезд, мест.Супросль"
    assert bad[0].place_text  # место не потеряно, просто не сведено к губернии


def test_strike_running_into_1905_is_not_an_error():
    """Стачка, начатая в декабре 1904-го, кончалась в 1905-м — это не сбой."""
    rec = row_to_record(ROWS[3])
    assert (rec.year_from, rec.year_to) == (1904, 1905)
    assert rec.confidence == "ok"
    assert rec.region == "Бакинская губерния"


def test_uid_is_stable_between_runs():
    first = row_to_record(ROWS[0]).uid
    second = row_to_record(dict(ROWS[0])).uid
    assert first == second
