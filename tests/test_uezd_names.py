"""Сверка уездов латиницей с уездами 1897 года RISTAT и общий разбор Dataverse.

Сети нет: признаки уездов — строки справочника `districts_1897.geojson`
(Distr_ID, Name_RU, Name_ENG, prov_RU, RISTAT_ID как есть), написания —
из трёх пакетов: Нафцигера («Eletskii», «Iasskii»), Дауэра и Маркевича
(«1. Tul'skij», «2. Aleksevskij», «4. Verhne-dneprovskij»).
"""

from histctx.sources.dataverse import DatasetFile, check_manifest
from histctx.sources.uezd_names import (
    NAFZIGER_DISTRICTS, NAFZIGER_PROVINCES, RistatDistricts, genitive, latin_key, resolve,
    translit, unit_name,
)


def _feature(distr_id, name_ru, name_eng, province, ristat_id):
    return {"type": "Feature", "geometry": None,
            "properties": {"Distr_ID": distr_id, "Name_RU": name_ru, "Name_ENG": name_eng,
                           "prov_RU": province, "RISTAT_ID": ristat_id}}


FEATURES = [
    _feature(448, "Тульский", "Tulskii", "Тульская губерния", "1897_84"),
    _feature(440, "Алексинский", "Aleksinskii", "Тульская губерния", "1897_84"),
    _feature(444, "Епифанский", "Epifanskii", "Тульская губерния", "1897_84"),
    _feature(445, "Ефремовский", "Efremovskii", "Тульская губерния", "1897_84"),
    _feature(461, "Елецкий", "Eletskii", "Орловская губерния", "1897_51"),
    _feature(349, "Белецкий", "Beletskii", "Бессарабская губерния", "1897_07"),
    _feature(498, "Верхне-днепровский", "Verkhne-Dneprovskii", "Екатеринославская губерния",
             "1897_21"),
    _feature(544, "Донской 2-й", "Donskoi 2-I", "Земля войска Донского", "1897_13"),
    _feature(551, "Донской 1-й", "Donskoi 1-I", "Земля войска Донского", "1897_13"),
    _feature(547, "Ростовский", "Rostovskii", "Земля войска Донского", "1897_13"),
    _feature(100, "Ростовский", "Rostovskii", "Ярославская губерния", "1897_97"),
    _feature(77, "Архангельская", "Arkhangelskaia", "Архангельская губерния", "1897_04"),
    _feature(3, "Кюменский\r\n", "Kymi", "Выборгская губерния", "1897_99"),
]
INDEX = RistatDistricts(FEATURES)


def test_key_removes_transliteration_differences():
    # ГОСТ пакета о мобилизации, Библиотека Конгресса у Нафцигера и RISTAT,
    # кириллица справочника — один ключ.
    assert latin_key("1. Arhangel'skaja") == latin_key("Arkhangel'skii") \
        == latin_key("Архангельский")
    assert latin_key("4. Carevskij") == latin_key("Tsarevskii") == latin_key("Царевский")
    assert latin_key("12. Chegirinskij") != latin_key("Chigirinskii")   # опечатка — не ключ
    assert latin_key("15. Wigrovskij") == latin_key("Щигровский")       # w — это щ
    assert latin_key("10 Plonskij") == latin_key("Plonskii")             # номер без точки
    assert translit("Щёлково") == "shchelkovo"


def test_district_is_identified_by_distr_id_not_ristat_id():
    # RISTAT_ID в справочнике один на губернию — уезда он не различает.
    tula = INDEX.match("Тульская губерния", "1. Tul'skij")
    alexin = INDEX.match("Тульская губерния", "Aleksinskii")
    assert tula.district.ristat_id == alexin.district.ristat_id == "1897_84"
    assert tula.district.distr_id == "448" and alexin.district.distr_id == "440"


def test_match_kinds():
    assert INDEX.match("Тульская губерния", "1. Tul'skij").how == "exact"
    assert INDEX.match("Орловская губерния", "Eletskii").how == "exact"
    # Опечатка пакета о мобилизации сводится с запасом над соседями.
    fuzzy = INDEX.match("Тульская губерния", "6. Enifanskij")
    assert fuzzy.how == "fuzzy" and fuzzy.district.name == "Епифанский"
    # Обрезанное название — по префиксу, если такой уезд в губернии один.
    prefix = INDEX.match("Тульская губерния", "4. Efremov")
    assert prefix.how == "prefix" and prefix.district.name == "Ефремовский"
    assert INDEX.match("Екатеринославская губерния", "4. Verhne-dneprovskij").how == "exact"


def test_match_stays_inside_the_province():
    # Ростовский есть и в Ярославской, и в Донской области.
    assert INDEX.match("Ярославская губерния", "Rostovskii").district.distr_id == "100"
    assert INDEX.match("Область Войска Донского", "Rostovskii").district.distr_id == "547"
    assert INDEX.match("Тульская губерния", "Eletskii") is None
    assert INDEX.match("Несуществующая губерния", "Eletskii") is None


def test_by_name_tells_numbered_don_districts_apart():
    # У «Донской 1-й» и «Донской 2-й» один region_key — цифры он выбрасывает.
    first = INDEX.by_name("Область Войска Донского", "Донской 1-й")
    second = INDEX.by_name("Область Войска Донского", "Донской 2-й")
    assert first.district.distr_id == "551" and second.district.distr_id == "544"


def test_resolve_manual_and_unmatched():
    # Ясский уезд переименован в Бельцкий в 1887 году: запись — под именем пакета.
    manual = NAFZIGER_DISTRICTS[("Bessarabia", "Iasskii")]
    place = resolve(INDEX, "Бессарабская губерния", "Iasskii", manual=manual)
    assert place.district == "Ясский уезд" and place.distr_id == "349"
    assert place.how == "manual" and place.confidence == "ok"
    assert place.head == "Ясский уезд Бессарабской губернии"
    # Без пары — латиница с пометкой, а не выдуманное название.
    stray = resolve(INDEX, "Тульская губерния", "Nevedomskij")
    assert stray.district is None and stray.confidence == "district_unmatched"
    assert stray.place_text == "Nevedomskij (уезд, написание набора), Тульская губерния"


def test_names_and_cases():
    assert unit_name("Елецкий", "Орловская губерния") == "Елецкий уезд"
    assert unit_name("Ростовский", "Область Войска Донского") == "Ростовский округ"
    assert unit_name("Архангельская", "Архангельская губерния") == "Архангельский уезд"
    assert genitive("Акмолинская область") == "Акмолинской области"
    assert genitive("Область Войска Донского") == "Области Войска Донского"
    assert INDEX.by_id["3"].name == "Кюменский"
    assert NAFZIGER_PROVINCES["Zemlia voiska donskogo"] == "Область Войска Донского"
    don = resolve(INDEX, "Область Войска Донского", "Rostovskii")
    assert don.head == "Ростовский округ Области Войска Донского"


def test_manifest_check_reports_every_difference():
    expected = [DatasetFile(1, "a.tab", 10, original_size=12), DatasetFile(2, "b.dta", 5)]
    manifest = {"license": "CC0 1.0", "files": [
        {"id": 1, "name": "a.tab", "size": 10, "original_size": 12},
        {"id": 2, "name": "b.dta", "size": 5, "original_size": None}]}
    assert check_manifest(manifest, expected, license_name="CC0 1.0") == []
    changed = {"license": "CC BY 4.0", "files": [
        {"id": 1, "name": "a.tab", "size": 10, "original_size": 13}]}
    problems = check_manifest(changed, expected, license_name="CC0 1.0")
    assert len(problems) == 3
    assert any("лицензия" in p for p in problems)
    assert any("исходника" in p for p in problems)
    assert any("b.dta" in p for p in problems)
    assert expected[0].url.endswith("?format=original") and expected[0].download_size == 12
    assert not expected[1].url.endswith("?format=original")
