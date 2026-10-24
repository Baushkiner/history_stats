"""Разбор набора по голоду 1891–1892 годов (Harvard Dataverse, В. Чарныш).

Сети в тестах нет: строки сняты с ингестированных TSV набора и урезаны до
нужных колонок. Четыре уезда главной таблицы — с помощью, без помощи, с
пустыми колонками помощи и без пары в справочнике границ, — губерния с
испорченной кодировкой, строки панели с холерой и сверхсмертностью и
перечень файлов. Проверяется, что записи территориальные и без точки, что
названия русские, что границы лет и период помощи прочитаны, что
неразобранное остаётся в данных с пометкой и что исходные колонки лежат
в `extra`.
"""

from pathlib import Path

import pytest

from histctx.geo import region_key
from histctx.schema import SCOPE_REGION
from histctx.sources.famine_1891 import (
    CATEGORY_CHOLERA, CATEGORY_EXCESS, CATEGORY_NO_RELIEF, CATEGORY_PROVINCE, CATEGORY_RELIEF,
    CATEGORY_UNKNOWN, DISTRICTS, DISTRICTS_BY_PROVINCE, FILES, MONTH_COLUMNS, MONTHS, PROVINCES,
    RISTAT_DISTRICT_SPELLING, WORK, DistrictIndex, FamineError, ProvinceIndex,
    boundaries_geojson, check_columns, check_identity, check_manifest, cholera_records,
    decode_province, district_name, excess_records, excess_threshold, monthly_relief,
    onset_by_share, panel_records, period_text, province_from_table, province_name,
    province_records, relief_period, row_to_record, rows_to_records,
)

ROOT = Path(__file__).resolve().parents[1]
DISTRICTS_1897 = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"
PROVINCES_1897 = ROOT / "data" / "out" / "boundaries" / "provinces_1897.geojson"


def _months(*values: float) -> dict:
    return {column: ("" if v is None else str(v)) for column, v in zip(MONTH_COLUMNS, values)}


# Елецкий уезд Орловской губернии: помощь с ноября 1891 по июль 1892 года.
ELETS = {
    "ter_ID": "33", "gub_name": "Orel", "uezd_name": "Elets", "gub_code": "26",
    "long": "38.501686", "lat": "52.5537", "OnReliefTot": "902203", "onrelief_max.x": "71.7",
    "onrelief_avg": "43.1", "onset_mo": "6", "endrelief_mo": "13", "reliefmonths": "9",
    "TotPop": "232742", "railDist": "5.140303", "LoanSowBreadPud91": "0",
    "LoanSowBreadPud92": "19273", "LoanFoodBreadPud": "681154",
    "LoanFoodBreadPudState": "681154", "HarvestMean91": "1.25", "Myers.0_109": "12.3",
    **_months(0, 0, 0, 0, 2122, 5950, 117684, 137499, 166957, 140296, 121055, 117986, 39104, 0),
}

# Болховский уезд той же губернии: на помощи никого, но ссуды выданы.
BOLKHOV = {
    "ter_ID": "205", "gub_name": "Orel", "uezd_name": "Bolkhov", "long": "36.0", "lat": "53.44",
    "OnReliefTot": "0", "onrelief_max.x": "", "onset_mo": "", "reliefmonths": "0",
    "TotPop": "112691", "railDist": "36.125847", "LoanSowBreadPud91": "0",
    "LoanSowBreadPud92": "44400", "LoanFoodBreadPud": "48102", "LoanFoodBreadPudState": "29448",
    **_months(*([0] * 14)),
}

# Жиздринский уезд Калужской губернии: колонки помощи пусты вовсе.
ZHIZDRA = {
    "ter_ID": "32", "gub_name": "Kaluga", "uezd_name": "Zhizdra", "long": "34.73756",
    "lat": "53.806491", "OnReliefTot": "", "onrelief_max.x": "", "onset_mo": "",
    "reliefmonths": "", "TotPop": "221961", "railDist": "62.564157",
    "LoanSowBreadPud91": "320", "LoanSowBreadPud92": "218138", "LoanFoodBreadPud": "290502",
    "LoanFoodBreadPudState": "124545", **_months(*([None] * 14)),
}

# Уезд, которого среди уездов 1897 года нет: написание известно, пары нет.
STRAY = {**ELETS, "ter_ID": "900", "gub_name": "Kaluga", "uezd_name": "Elets"}
# Написание, которого словарь не знает.
UNKNOWN = {**ELETS, "ter_ID": "901", "uezd_name": "Novyi Gorod"}

ROWS = [ELETS, BOLKHOV, ZHIZDRA, STRAY, UNKNOWN]


def _feature(province: str, name: str, ristat_id: str) -> dict:
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]},
            "properties": {"prov_RU": province, "Name_RU": name, "RISTAT_ID": ristat_id}}


INDEX = DistrictIndex([
    _feature("Орловская губерния", "Елецкий", "1897_51"),
    _feature("Орловская губерния", "Болховский", "1897_51"),
    _feature("Калужская губерния", "Жиздринский", "1897_29"),
    _feature("Калужская губерния", "Малоярославский", "1897_29"),
])


def test_columns_are_checked_before_parsing():
    """Набор переиздали с другими именами — сбор останавливается."""
    with pytest.raises(FamineError) as exc:
        check_columns(["ter_ID", "gub_name"], ("ter_ID", "OnReliefTot"), "главная таблица")
    assert "OnReliefTot" in str(exc.value)


def test_manifest_is_compared_by_id_name_and_size():
    """Перечень файлов в коде сверяется с ответом API, а не принимается на веру."""
    manifest = [{"id": f.file_id, "name": f.name, "size": f.size} for f in FILES]
    manifest.append({"id": 1, "name": "cross_sectional_final.R", "size": 30304})
    assert check_manifest(manifest) == []
    manifest[0] = {**manifest[0], "size": manifest[0]["size"] + 1}
    problems = check_manifest(manifest[1:])
    assert len(problems) == 1 and "в наборе нет" in problems[0]
    problems = check_manifest(manifest)
    assert len(problems) == 1 and "размер" in problems[0]


def test_names_are_translated_by_closed_dictionaries():
    assert province_name("Orel") == "Орловская губерния"
    assert province_name("Tavrida") == province_name("Taurida") == "Таврическая губерния"
    assert district_name("Elets") == "Елецкий уезд"
    assert district_name("Starobel'sk") == "Старобельский уезд"
    assert district_name("Novyi Gorod") is None
    assert province_name("Atlantis") is None


def test_month_numbering_starts_in_july_1891():
    """Отсчёт onset_mo/endrelief_mo установлен по данным, а не угадан.

    Четырнадцать помесячных колонок идут с июля 1891 по август 1892 года.
    При «июль 1891 = 1» авторский onset_mo совпадает с первым ненулевым
    месяцем у 127 уездов из 175, при «июнь = 1» — ни у одного; endrelief_mo
    совпадает с последним ненулевым у 172. Остаток объясняет сноска статьи:
    кампания считается начатой с месяца, когда на помощи больше 1%
    населения, — так сходится 170 уездов из 175. У Ельца помощь началась
    в ноябре 1891-го с 2 122 человек (0,9%), а onset_mo = 6 — декабрь.
    """
    assert MONTHS[0][1:] == (1891, 7) and MONTHS[-1][1:] == (1892, 8)
    assert len(MONTHS) == 14
    values = monthly_relief(ELETS)
    assert relief_period(values) == (5, 13)
    assert period_text((5, 13)) == "ноябрь 1891 — июль 1892"
    assert onset_by_share(values, 232742) == 6 == int(float(ELETS["onset_mo"]))
    assert relief_period([0.0] * 14) is None
    assert monthly_relief(ZHIZDRA) is None


def test_record_is_territorial_without_a_point():
    """Координаты набора — уездный город; точка на нём врала бы о месте голода."""
    rec = row_to_record(ELETS, INDEX)
    assert rec.scope == SCOPE_REGION
    assert not rec.has_point and rec.is_territorial and rec.usable
    assert rec.region == "Орловская губерния"
    assert rec.regions == ["Орловская губерния"]
    assert rec.district == "Елецкий уезд"
    assert rec.place_text == "Елецкий уезд, Орловская губерния"
    assert rec.title == "Елецкий уезд Орловской губернии: голод 1891–1892 годов"
    assert rec.extra["famine"]["lat"] == 52.5537 and rec.extra["famine"]["long"] == 38.501686


def test_years_and_relief_period():
    rec = row_to_record(ELETS, INDEX)
    assert (rec.year_from, rec.year_to) == (1891, 1892)
    assert rec.date_precision == "month"
    assert rec.period_raw == "ноябрь 1891 — июль 1892"
    assert rec.work == WORK
    # Без месяцев период — годы голода, точность — год.
    assert row_to_record(BOLKHOV, INDEX).period_raw == "1891–1892"
    assert row_to_record(BOLKHOV, INDEX).date_precision == "year"


def test_category_follows_the_relief_total():
    assert row_to_record(ELETS, INDEX).category == CATEGORY_RELIEF
    assert row_to_record(BOLKHOV, INDEX).category == CATEGORY_NO_RELIEF
    assert row_to_record(ZHIZDRA, INDEX).category == CATEGORY_UNKNOWN


def test_summary_is_built_from_understood_columns_only():
    text = row_to_record(ELETS, INDEX).summary
    assert "в пике (март 1892) 166 957 человек — 72% населения" in text
    assert "9 месяцев, с ноября 1891 по июль 1892" in text
    assert "продовольственные ссуды 681 154 пуда, из них от казны 681 154 пуда" in text
    assert "население 232 742 человек" in text.lower()
    assert "до железной дороги 5 км" in text
    # Урожай и индекс Майерса остаются числом в extra, в текст не идут.
    assert "1.25" not in text and "Майерс" not in text
    assert row_to_record(ELETS, INDEX).extra["famine"]["HarvestMean91"] == 1.25
    assert row_to_record(ELETS, INDEX).extra["famine"]["Myers.0_109"] == 12.3


def test_district_without_relief_is_kept_and_says_so():
    """Уезд в наборе — уже факт, что его обследовали; выбрасывать нечего."""
    text = row_to_record(BOLKHOV, INDEX).summary
    assert text.startswith("Людей на продовольственной помощи в своде не учтено")
    assert "семенные ссуды 44 400 пудов (1892)" in text.lower()
    empty = row_to_record(ZHIZDRA, INDEX).summary
    assert empty.startswith("Помесячных сведений о числе людей на помощи в наборе нет")


def test_district_is_matched_inside_its_province():
    rec = row_to_record(ELETS, INDEX)
    assert rec.confidence == "ok"
    assert rec.extra["RISTAT_ID"] == "1897_51"
    assert INDEX.find("Орловская губерния", "Елецкий уезд") == "1897_51"
    # Сравнение идёт через region_key, а не по равенству строк.
    assert INDEX.find("Орловской губернии", "Елецкий") == "1897_51"
    # Написание RISTAT отличается от исторического — сверка знает об этом.
    assert INDEX.find("Калужская губерния", "Малоярославецкий уезд") == "1897_29"
    assert INDEX.find("Калужская губерния", "Елецкий уезд") is None


def test_unmatched_district_is_marked_not_dropped():
    """Правило репозитория: спорное помечается и остаётся в данных."""
    records = rows_to_records(ROWS, INDEX)
    assert len(records) == len(ROWS)
    bad = {r.source_id: r for r in records if r.confidence == "district_unmatched"}
    assert set(bad) == {"900", "901"}
    stray = bad["900"]
    assert stray.district == "Елецкий уезд" and stray.region == "Калужская губерния"
    assert "RISTAT_ID" not in stray.extra and stray.usable
    unknown = bad["901"]
    assert unknown.district is None
    assert unknown.place_text == "Novyi Gorod (уезд, написание набора), Орловская губерния"
    assert unknown.extra["famine"]["uezd_name"] == "Novyi Gorod"
    assert INDEX.candidates("Калужская губерния") == ["Жиздринский", "Малоярославский"]


def test_extra_keeps_source_columns_and_every_record_links_to_the_dataset():
    for rec in rows_to_records(ROWS, INDEX):
        assert rec.url == "https://doi.org/10.7910/DVN/Q4DMKK"
        assert rec.license.startswith("CC0 1.0")
        assert rec.extra["famine"]["ter_ID"] == int(rec.source_id)
        assert "citation" in rec.extra
    elets = row_to_record(ELETS, INDEX).extra["famine"]
    assert elets["OnReliefMar1892"] == 166957 and "OnReliefJuly1891" in elets
    # Пустые колонки в extra не идут: пустота — не ноль.
    assert "OnReliefTot" not in row_to_record(ZHIZDRA, INDEX).extra["famine"]


def test_uid_is_stable_between_runs():
    assert row_to_record(ELETS, INDEX).uid == row_to_record(dict(ELETS), INDEX).uid


# --- губернские итоги -------------------------------------------------------

# Строки Province_Mortality.tab как они приходят из файла: UTF-8, прочитанный
# как latin-1. У Саратовской внутри кириллицы стоит латинская «a».
SARATOV_RAW = "Ð¡Ð°Ñ\x80Ð°Ñ\x82Ð¾Ð²Ñ\x81ÐºaÑ\x8f"
ASTRAKHAN_RAW = "Ð\x90Ñ\x81Ñ\x82Ñ\x80Ð°Ñ\x85Ð°Ð½Ñ\x8c"
RIAZAN_RAW = "Ð\xa0Ñ\x8fÐ·Ð°Ð½Ñ\x81ÐºÐ°Ñ\x8f"

PROVINCE_ROWS = [
    {"Gubernia": SARATOV_RAW, "ExcessMortalityV1": "49", "ExcessMortalityV2": "58",
     "AidPctPop": "41", "HarvestPC": "4.65", "AvgLoanPP": "3.28"},
    {"Gubernia": ASTRAKHAN_RAW, "ExcessMortalityV1": "89", "ExcessMortalityV2": "91",
     "AidPctPop": "0", "HarvestPC": "2", "AvgLoanPP": "0"},
    {"Gubernia": RIAZAN_RAW, "ExcessMortalityV1": "16", "ExcessMortalityV2": "24",
     "AidPctPop": "", "HarvestPC": "9.05", "AvgLoanPP": "2.08"},
]

PROVINCE_INDEX = ProvinceIndex(["Саратовская губерния", "Астраханская губерния",
                                "Рязанская губерния"])


def test_double_encoded_province_names_are_restored():
    """Строка прошла через latin-1; внутри неё NEL и неразрывный пробел — это
    байты кириллицы, и чистить их как пробелы нельзя."""
    assert decode_province(SARATOV_RAW) == "Саратовская"
    assert decode_province(RIAZAN_RAW) == "Рязанская"
    assert province_from_table(SARATOV_RAW) == "Саратовская губерния"
    assert province_from_table(ASTRAKHAN_RAW) == "Астраханская губерния"
    assert province_from_table("Самарская") == "Самарская губерния"


def test_latin_letter_inside_cyrillic_is_normalized():
    assert "a" not in decode_province(SARATOV_RAW)
    assert region_key(province_from_table(SARATOV_RAW)) == region_key("Саратовская губерния")


def test_province_records_are_territorial_and_keep_the_raw_name():
    records = province_records(PROVINCE_ROWS, PROVINCE_INDEX)
    assert [r.region for r in records] == ["Саратовская губерния", "Астраханская губерния",
                                           "Рязанская губерния"]
    saratov = records[0]
    assert saratov.scope == SCOPE_REGION and not saratov.has_point and saratov.usable
    assert saratov.category == CATEGORY_PROVINCE
    assert (saratov.year_from, saratov.year_to) == (1891, 1892)
    assert saratov.work == WORK and saratov.url.endswith("Q4DMKK")
    assert saratov.confidence == "ok"
    # Исходная строка хранится escape-записью: внутри неё NEL и байты C1,
    # которые в построчном JSON ломают чтение.
    assert saratov.extra["province_raw"] == SARATOV_RAW.encode("unicode_escape").decode("ascii")
    assert "\\x80" in saratov.extra["province_raw"]
    assert saratov.extra["famine"]["Gubernia"] == "Саратовская"
    assert "41% населения" in saratov.summary
    # Единица сверхсмертности не выяснена: число остаётся в extra, в тексте его нет.
    assert saratov.extra["famine"]["ExcessMortalityV1"] == 49
    assert "49" not in saratov.summary
    assert "не числилось (0%)" in records[1].summary
    assert "не указана" in records[2].summary


def test_province_outside_the_reference_is_marked():
    rows = [{"Gubernia": "Ð¢Ð¾Ð±Ð¾Ð»Ñ\x8cÑ\x81ÐºÐ°Ñ\x8f", "AidPctPop": ""}]
    rec = province_records(rows, PROVINCE_INDEX)[0]
    assert rec.region == "Тобольская губерния" and rec.confidence == "region_unmatched"
    assert province_records(rows, ProvinceIndex(["Тобольская губерния"]))[0].confidence == "ok"


# --- полигоны ---------------------------------------------------------------

def test_boundaries_take_only_districts_of_the_table():
    shapes = [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[38, 52]]]},
         "properties": {"ter_id": "33", "uezd_name": "Elets"}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[20, 60]]]},
         "properties": {"ter_id": "418", "uezd_name": "Uleaborg"}},
    ]
    collection = boundaries_geojson(shapes, rows_to_records([ELETS, BOLKHOV], INDEX))
    assert collection["name"] == "famine_1891_districts"
    assert collection["license"].startswith("CC0 1.0") and "Charnysh" in collection["citation"]
    assert collection["url"] == "https://doi.org/10.7910/DVN/Q4DMKK"
    assert len(collection["features"]) == 1
    props = collection["features"][0]["properties"]
    assert props["uezd"] == "Елецкий уезд" and props["province"] == "Орловская губерния"
    assert props["RISTAT_ID"] == "1897_51" and props["relief_months"] == 9
    assert props["relief_period"] == "ноябрь 1891 — июль 1892"
    assert props["loan_food_pud"] == 681154 and props["relief_share_max_pct"] == 71.7


# --- панель 1885–1896 годов -------------------------------------------------

# Строки time-series-dataset.tab: Николаевский уезд Самарской губернии в
# 1892 году (холера и сверхсмертность), Эзельский уезд в 1885-м (ни того, ни
# другого), Ростовский округ Войска Донского (единица — округ, тёзка в
# Ярославской) и Елецкий уезд в 1891-м — сверхсмертность в год неурожая.
NIKOLAEV_1892 = {
    "ter_id": "492", "year": "1892", "nameg": "Samara", "name": "Nikolaev",
    "births_m": "11605", "births_f": "10768", "deaths_m": "18408", "deaths_f": "17925",
    "cholera_cases": "12367", "cholera_deaths": "5110", "est_cbr": "45.41911123",
    "est_cdr": "73.75911001", "cdr_pred": "47.31705774", "est_em": "26.44205227",
    "long": "49.39561842", "lat": "52.04757772", "relief": "1", "famine": "1", "famine2": "1",
}
EZEL_1885 = {
    "ter_id": "0", "year": "1885", "nameg": "Livland", "name": "Ezel'",
    "births_m": "870", "births_f": "804", "deaths_m": "649", "deaths_f": "630",
    "cholera_cases": "", "cholera_deaths": "", "est_cdr": "22.81158593",
    "cdr_pred": "23.07517064", "est_em": "-0.263584705", "relief": "0", "famine": "0",
}
ROSTOV_1892 = {
    "ter_id": "562", "year": "1892", "nameg": "Don Cossacks", "name": "Rostov",
    "births_m": "7497", "births_f": "7251", "deaths_m": "12091", "deaths_f": "9766",
    "cholera_cases": "12887", "cholera_deaths": "6443", "est_cdr": "62.44500314",
    "cdr_pred": "33.24429321", "est_em": "29.20070994", "famine": "1",
}
ELETS_1891 = {
    "ter_id": "33", "year": "1891", "nameg": "Orel", "name": "Elets",
    "births_m": "8043", "births_f": "7505", "deaths_m": "7067", "deaths_f": "6890",
    "cholera_cases": "", "cholera_deaths": "", "est_cdr": "52.85481116",
    "cdr_pred": "43.61718369", "est_em": "9.237627476", "relief": "1", "famine": "0",
}
# Высокая сверхсмертность за пределами голодных лет: поле work ей не положено.
EZEL_1888 = {**EZEL_1885, "year": "1888", "est_cdr": "40.0", "cdr_pred": "23.0", "est_em": "17.0"}

PANEL = [NIKOLAEV_1892, EZEL_1885, ROSTOV_1892, ELETS_1891, EZEL_1888]

PANEL_INDEX = DistrictIndex([
    _feature("Самарская губерния", "Николаевский", "1897_60"),
    _feature("Лифляндская губерния", "Эзельский", "1897_41"),
    _feature("Земля войска Донского", "Ростовский", "1897_24"),
    _feature("Ярославская губерния", "Ростовский", "1897_99"),
    _feature("Орловская губерния", "Елецкий", "1897_51"),
])


def test_identity_is_checked_before_the_unit_goes_into_text():
    """est_em = est_cdr − cdr_pred — смертей на тысячу; сходится до 1e-8."""
    checked, worst = check_identity(PANEL)
    assert checked == 5 and worst < 1e-6
    broken = {**NIKOLAEV_1892, "est_em": "30"}
    with pytest.raises(FamineError) as exc:
        check_identity([broken])
    assert "на тысячу" in str(exc.value)


def test_threshold_is_one_and_a_half_sigma_over_the_whole_panel():
    """σ — выборочное стандартное отклонение по всем строкам, не по прошедшим порог.

    По живой панели 22.10.2026: σ = 4,738 на тысячу, порог 7,107, по нему
    419 строк «уезд-год», из них 139 за 1892 год.
    """
    sigma, threshold = excess_threshold([0.0, 0.0, 10.0, 10.0])
    assert round(sigma, 4) == 5.7735 and round(threshold, 4) == 8.6603
    with pytest.raises(FamineError):
        excess_threshold([1.0])


def test_cholera_record_is_only_made_where_people_died():
    records = cholera_records(PANEL, PANEL_INDEX)
    assert [r.source_id for r in records] == ["492:1892:cholera", "562:1892:cholera"]
    rec = records[0]
    assert rec.category == CATEGORY_CHOLERA and rec.scope == SCOPE_REGION and not rec.has_point
    assert rec.title == "Николаевский уезд Самарской губернии: холера 1892 года"
    assert rec.region == "Самарская губерния" and rec.district == "Николаевский уезд"
    assert (rec.year_from, rec.year_to) == (1892, 1892) and rec.period_raw == "1892"
    assert rec.work == WORK and rec.url.endswith("Q4DMKK")
    assert rec.summary == ("Холера 1892 года: заболели 12\u00a0367, умерли 5\u00a0110 человек — "
                           "14% всех смертей в уезде за год (36\u00a0333).")
    assert rec.extra["famine"]["cholera_cases"] == 12367 and rec.extra["RISTAT_ID"] == "1897_60"


def test_don_okrug_is_named_by_its_province_and_matched_as_zemlia():
    """«Rostov» есть и в Ярославской, и на Дону: ключ словаря — губерния с уездом.
    Войско Донское делилось на округа, а справочник RISTAT зовёт его землёй."""
    assert district_name("Rostov", "Don Cossacks") == "Ростовский округ"
    assert district_name("Rostov", "Iaroslavl'") == "Ростовский уезд"
    assert district_name("Rostov") == "Ростовский уезд"
    assert ("Don Cossacks", "Novocherkassk") in DISTRICTS_BY_PROVINCE
    rec = cholera_records([ROSTOV_1892], PANEL_INDEX)[0]
    assert rec.district == "Ростовский округ" and rec.region == "Область Войска Донского"
    assert "умерли 6\u00a0443 человека — 29% всех смертей" in rec.summary
    tiny = cholera_records([{**ROSTOV_1892, "cholera_deaths": "2", "cholera_cases": "4"}],
                           PANEL_INDEX)[0]
    assert "умерли 2 человека — менее 0,1% всех смертей" in tiny.summary
    assert rec.title == "Ростовский округ Области Войска Донского: холера 1892 года"
    assert rec.confidence == "ok" and rec.extra["RISTAT_ID"] == "1897_24"


def test_excess_record_is_made_above_the_threshold_only():
    records = excess_records(PANEL, PANEL_INDEX, threshold=7.107)
    assert [r.source_id for r in records] == [
        "492:1892:excess", "562:1892:excess", "33:1891:excess", "0:1888:excess",
    ]
    rec = records[0]
    assert rec.category == CATEGORY_EXCESS and rec.year_from == 1892 and not rec.has_point
    assert rec.summary.startswith("Смертность 1892 года — 73,8 на тысячу населения при "
                                  "ожидаемых 47,3: сверх обычного 26,4 на тысячу "
                                  "(порог слоя 7,1)")
    assert rec.summary.endswith("Умерло 36\u00a0333 человека; родилось 22\u00a0373; "
                                "от холеры умерло 5\u00a0110.")
    assert rec.extra["excess_threshold"] == {"sigma_factor": 1.5, "value": 7.107}
    assert rec.extra["famine"]["famine"] == 1 and rec.extra["famine"]["relief"] == 1


def test_work_is_carried_only_in_the_famine_years():
    """Сверхсмертность 1888 года в Лифляндии с голодом 1891 года не сводится."""
    by_id = {r.source_id: r for r in excess_records(PANEL, PANEL_INDEX, threshold=7.107)}
    assert by_id["33:1891:excess"].work == WORK
    assert by_id["492:1892:excess"].work == WORK
    assert by_id["0:1888:excess"].work is None
    # Переменные регрессии статьи остаются в extra и в категорию не идут.
    assert by_id["33:1891:excess"].category == CATEGORY_EXCESS
    assert by_id["33:1891:excess"].extra["famine"]["famine"] == 0


def test_panel_records_check_identity_and_compute_the_threshold():
    cholera, excess, stats = panel_records(PANEL, PANEL_INDEX)
    assert stats["identity_rows"] == 5 and stats["identity_max_diff"] < 1e-6
    assert round(stats["sigma"], 3) == round(excess_threshold(
        [26.44205227, -0.263584705, 29.20070994, 9.237627476, 17.0])[0], 3)
    assert len(cholera) == 2 and all(r.year_from >= 1891 for r in excess)


# --- словари против справочника границ в репозитории ------------------------

@pytest.mark.skipif(not DISTRICTS_1897.exists(), reason="нет districts_1897.geojson")
def test_every_dictionary_district_is_spelled_as_in_ristat():
    """Каждое прилагательное словаря есть среди уездов 1897 года — с поправкой
    на три написания, в которых справочник расходится с историческим."""
    index = DistrictIndex.load(DISTRICTS_1897)
    known = {district for _, district in index.by_key}
    missing = []
    for name in set(DISTRICTS.values()) | set(DISTRICTS_BY_PROVINCE.values()):
        adjective = name.replace(" округ", "")
        spelled = RISTAT_DISTRICT_SPELLING.get(adjective, adjective)
        if region_key(spelled) not in known:
            missing.append(name)
    assert not missing, missing


@pytest.mark.skipif(not PROVINCES_1897.exists(), reason="нет provinces_1897.geojson")
def test_every_dictionary_province_is_in_the_1897_reference():
    index = ProvinceIndex.load(PROVINCES_1897)
    missing = [name for name in set(PROVINCES.values()) if not index.find(name)]
    assert not missing, missing


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG, HARVESTED

    spec = BY_SLUG["famine_1891"]
    assert spec.status == "harvested" and spec in HARVESTED
    assert spec.license.startswith("CC0 1.0") and spec.url == "https://doi.org/10.7910/DVN/Q4DMKK"
