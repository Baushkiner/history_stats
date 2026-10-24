"""Голод 1932–1933 годов по районам и губернская смертность 1871–1914 годов.

Сети в тестах нет: строки сняты с таблиц пакета Маркевича, Науменко, Цянь
(`districts.dta`, `provinces.dta`) и с `main_data.Rdata` набора Rozenas,
Zhukov и урезаны до нужных колонок; ряд губернской смертности построен
искусственно, чтобы порог считался в уме. Проверяется: точка района — его
центроид и помечена; тождество сверхсмертности держит разбор; неполный учёт
смертей помечен, а не выброшен; регион — запись без точки; районы двух
наборов сводятся по координате и названию; годы сверхсмертности губернии
отбираются полутора сигмами; перечни файлов сверяются.
"""

import io

import pytest

from histctx.schema import SCOPE_POINT, SCOPE_REGION
from histctx.sources.famine_1891 import WORK as WORK_1891
from histctx.sources.famine_1891 import ProvinceIndex
from histctx.sources.famine_1933 import (
    ARCHIVE, CATEGORY_1933_ONLY, CATEGORY_CZAR, CATEGORY_EXCESS, CATEGORY_NO_DATA,
    CATEGORY_REGION, CATEGORY_RZ, CONFIDENCE_CENTROID, CONFIDENCE_GAP, CZAR_PROVINCES,
    DATASET_URL, REGIONS, RZ_LICENSE, RZ_MAIN, RZ_URL, WORK, FamineError, RayonIndex,
    boundaries_geojson, check_columns, check_identity, check_rz_manifest,
    check_zenodo_manifest, czar_records, district_pairs, district_records, district_title,
    match_datasets, name_key, read_stata_rows, region_records, rz_records, rz_share,
)
from histctx.sources.ghcn import Provinces, _bounds, _polygons


def _district(district_id, name, year, mortality, excess=None, **extra):
    return {"district_id": district_id, "district_name": name, "province_id": 26,
            "province_name": "Украина", "year": year, "xcoord": 29.549391,
            "ycoord": 48.30484, "mortality": mortality, "excess_mortality_1933": excess,
            "rmortality": None, "umortality": None, "pop": None, "rpop": None,
            "urbanization": None, "main_sample": 1, **extra}


# Бершадский район: 19,0 на тысячу в 1928 году, 73,5 — в 1933-м.
BERSHAD_1928 = _district(4, "Бершадский", 1928, 0.019033, 0.054462, pop=89221)
BERSHAD_1933 = _district(4, "Бершадский", 1933, 0.073495, 0.054462, pop=110987,
                         rmortality=0.076372, umortality=0.040631)
# Казбековский район Дагестана: 0,08 умерших на тысячу в 1928 году — неполный учёт.
KAZBEK_1928 = {**_district(290032, "Казбековский", 1928, 0.0000802, 0.0072268),
               "province_name": "Дагестанская АССР", "xcoord": 46.6, "ycoord": 43.0}
KAZBEK_1933 = {**KAZBEK_1928, "year": 1933, "mortality": 0.007307}
# Таймырский национальный округ: за 1928 год смертности нет, за 1933 — 0,18 на тысячу.
TAIMYR_1928 = {**_district(400094, "Таймырский нац окр", 1928, None),
               "province_name": "Восточная Сибирь", "xcoord": 95.0, "ycoord": 72.0}
TAIMYR_1933 = {**TAIMYR_1928, "year": 1933, "mortality": 0.000179}
# Район, который есть только в строке 1933 года, без смертности вовсе.
LONELY_1933 = {**_district(460000, "Селемджинский", 1933, None),
               "province_name": "Дальне-Восточный край", "xcoord": 132.0, "ycoord": 52.5}

ROWS = [BERSHAD_1928, BERSHAD_1933, KAZBEK_1928, KAZBEK_1933, TAIMYR_1928, TAIMYR_1933,
        LONELY_1933]


def _square(lon, lat, half=0.2):
    return {"type": "Polygon", "coordinates": [[
        [lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half],
        [lon - half, lat + half], [lon - half, lat - half]]]}


PODOLIA = Provinces([("Подольская губерния", _polygons(_square(29.5, 48.3, 1.0)),
                      _bounds(_polygons(_square(29.5, 48.3, 1.0))))])


def _by_id(records):
    return {r.extra["famine_1933"]["district_id"]: r for r in records}


def test_district_record_is_a_marked_centroid_with_numbers_in_words():
    recs = _by_id(district_records(ROWS, PODOLIA))
    bershad = recs[4]
    assert bershad.scope == SCOPE_POINT
    assert (bershad.lat, bershad.lon) == (48.30484, 29.549391)
    assert bershad.confidence == CONFIDENCE_CENTROID
    assert "центроид" in bershad.extra["point"]
    assert bershad.category == CATEGORY_EXCESS
    assert bershad.district == "Бершадский район"
    assert bershad.region == REGIONS["Украина"] == "Украинская ССР"
    assert (bershad.year_from, bershad.year_to, bershad.work) == (1933, 1933, WORK)
    assert bershad.summary.startswith("В 1933 году умерло 73,5 на тысячу жителей при 19,0 "
                                      "в 1928-м: на 54,5 больше")
    assert "сельская смертность 76,4, городская 40,6" in bershad.summary
    assert "110 987 человек" in bershad.summary
    assert bershad.extra["province_1897"] == "Подольская губерния"
    assert bershad.extra["famine_1933"]["1928"]["pop"] == 89221
    assert bershad.url == DATASET_URL


def test_implausibly_low_mortality_is_marked_not_dropped():
    recs = _by_id(district_records(ROWS))
    assert recs[290032].confidence == CONFIDENCE_GAP
    assert "учёт смертей неполон" in recs[290032].summary
    assert recs[400094].confidence == CONFIDENCE_GAP
    assert recs[400094].category == CATEGORY_1933_ONLY
    assert recs[400094].district == "Таймырский национальный округ"
    assert recs[460000].category == CATEGORY_NO_DATA
    assert len(recs) == 4


def test_identity_of_excess_mortality_is_enforced():
    stats = check_identity(district_pairs(ROWS))
    assert stats["identity_rows"] == 2
    broken = [{**BERSHAD_1928}, {**BERSHAD_1933, "excess_mortality_1933": 0.04}]
    with pytest.raises(FamineError):
        district_records(broken)


def test_district_titles():
    assert district_title("Янаульский") == "Янаульский район"
    assert district_title("Карагушевский (Стерлибашевский)") == \
        "Карагушевский район (Стерлибашевский)"
    assert district_title("Москва гс") == "Москва горсовет"
    assert district_title("Артемовский  гс") == "Артемовский горсовет"
    assert district_title("Ямало-Ненецкий нац окр") == "Ямало-Ненецкий национальный округ"
    assert district_title("Сахалинская обл") == "Сахалинская область"
    assert district_title("Приволжский улус") == "Приволжский улус"
    assert district_title("Богородский II") == "Богородский II"
    assert district_title(".") is None


UKRAINE = [{"id": 26, "name": "Украина", "year": y, "dead": d, "pop": p} for y, d, p in (
    (1897, None, 23430407.0), (1928, 495700.0, None), (1932, 668579.0, None),
    (1933, 1861034.0, 31369287.0), (1934, 462037.0, None), (1959, None, 41869046.0))]


def test_region_record_has_no_point_and_keeps_the_series():
    [rec] = region_records(UKRAINE)
    assert rec.scope == SCOPE_REGION and not rec.has_point
    assert rec.regions == ["Украинская ССР"]
    assert rec.category == CATEGORY_REGION
    assert (rec.year_from, rec.year_to) == (1932, 1933)
    assert rec.summary.startswith("В 1933 году умерло 1 861 034 человека — в 3,8 раза больше, "
                                  "чем в 1928-м (495 700)")
    assert "1932 — 668 579, 1934 — 462 037" in rec.summary
    assert rec.extra["famine_1933"]["dead"] == {"1928": 495700, "1932": 668579,
                                                 "1933": 1861034, "1934": 462037}
    # Население за 1897 и 1959 годы лежит в ряду, но умерших вне 1923–1940 нет.
    assert "1959" in rec.extra["famine_1933"]["pop"]


BALAKLIIA = {
    "ID": "177", "NAME_1_1933": "Харківська", "NAME_2_1933": "Балаклійський район",
    "NAME_2_1933_LAT": "Balaklíjsʹkij rajon", "ID_2_1933": 239, "LONG": 36.905535,
    "LAT": 49.47732, "FAMINE_TOTAL": 28651, "FAMINE_URBAN": 981, "FAMINE_RURAL": 27996,
    "POP1933_TOTAL": 208175, "POP1933_URBAN": 21219, "POP1933_RURAL": 193196,
    "C1926_TOTAL": 153089,
}
BERSHAD_RZ = {**BALAKLIIA, "ID": "3", "NAME_1_1933": "Вінницька",
              "NAME_2_1933": "Бершадський район", "LONG": 29.55, "LAT": 48.3}


def test_rz_record_carries_its_own_source_and_license():
    [rec] = rz_records([BALAKLIIA], {"177": [293]})
    assert rec.category == CATEGORY_RZ
    assert (rec.lat, rec.lon) == (49.47732, 36.905535)
    assert rec.region == "Харьковская область"
    assert (rec.year_from, rec.year_to, rec.work) == (1932, 1934, WORK)
    assert rec.license == RZ_LICENSE and rec.url == RZ_URL
    assert "28 651 человек: в сёлах 27 996, в городах 981" in rec.summary
    assert "12,1%" in rec.summary
    assert rz_share(BALAKLIIA) == pytest.approx(100 * 28651 / (28651 + 208175))
    assert rec.extra["mnq_district_ids"] == [293]
    assert "LONG" not in rec.extra["famine_1933_rz"]


def test_datasets_are_matched_by_coordinate_then_by_name():
    # Бершадский центроид внутри полигона Бершадського району; соседний район
    # 1934 года («Джулинский») лёг центроидом туда же, а его собственный
    # район 1933 года остался без пары — второй проход отдаёт его по названию.
    julyn_rz = {**BALAKLIIA, "ID": "12", "NAME_2_1933": "Джулинський район",
                "LONG": 29.0, "LAT": 48.6}
    julyn = _district(12, "Джулинский", 1933, 0.05, None)
    julyn_28 = _district(12, "Джулинский", 1928, None)
    districts = district_records(ROWS + [julyn_28, julyn])
    index = RayonIndex({"3": _square(29.55, 48.3, 0.3), "12": _square(28.0, 48.6, 0.3)})
    match = match_datasets(districts, [BERSHAD_RZ, julyn_rz], index)
    assert match["mnq_ukraine"] == 2
    assert match["pairs"] == {"3": [4], "12": [12]}
    assert match["rz_by_name"] == 1
    recs = _by_id(districts)
    assert recs[4].extra["rz_rayon"]["matched_by"] == "coordinate"
    assert recs[12].extra["rz_rayon"]["matched_by"] == "name"
    assert match["names_agree"] == 2
    assert name_key("Чечільницький (Ободівський) район") == name_key("Чечельникский")
    assert name_key("ім. Дзержинського район") == name_key("Дзержинский")


def test_boundaries_keep_only_rayons_with_records():
    recs = rz_records([BALAKLIIA], {"177": [293]})
    geometry = {"177": _square(36.9, 49.47712345678), "999": _square(30, 50)}
    collection = boundaries_geojson(geometry, recs)
    [feature] = collection["features"]
    assert feature["id"] == recs[0].uid
    assert feature["properties"]["famine_total"] == 28651
    assert feature["properties"]["oblast_ru"] == "Харьковская область"
    assert feature["geometry"]["coordinates"][0][0] == [36.7, 49.277123]
    assert collection["license"] == RZ_LICENSE


def _czar(gub, gub_id, spike_year=None, zero_year=None):
    rows = []
    for year in range(1885, 1905):
        rate = 40.0 - 0.3 * (year - 1885)
        if year == spike_year:
            rate += 25.0
        pop = 2_000_000
        dead = 0.0 if year == zero_year else rate * pop / 1000
        rows.append({"gub_id": gub_id, "gubernia_en": gub, "year": year, "pop": pop,
                     "dead": dead, "grain": 1000.0, "xcoord": 50.0, "ycoord": 53.0})
    return rows


def test_czar_excess_years_by_one_and_a_half_sigma():
    rows = (_czar("Samarskaya", 1, spike_year=1892) + _czar("Donskoe Voysko", 2)
            + _czar("Tulskaya", 3, zero_year=1890))
    index = ProvinceIndex(["Самарская губерния", "Земля войска Донского", "Тульская губерния"])
    records, stats = czar_records(rows, index)
    assert [(r.region, r.year_from) for r in records] == [("Самарская губерния", 1892)]
    rec = records[0]
    assert rec.category == CATEGORY_CZAR and rec.scope == SCOPE_REGION and not rec.has_point
    assert rec.work == WORK_1891           # 1891–1893 — голод 1891–1892 годов
    assert rec.confidence == "ok"
    assert rec.extra["excess_per_1000"] > stats["threshold"]
    # Ноль умерших — пропуск, а не ноль смертей: в тренд не идёт, но виден в проверке.
    assert [(g["gubernia_en"], g["year"]) for g in stats["gaps"]] == [("Tulskaya", 1890)]
    assert stats["rows"] == 59
    assert index.find(CZAR_PROVINCES["Donskoe Voysko"]) == "Земля войска Донского"
    assert len(CZAR_PROVINCES) == 50


def test_manifests_are_checked_and_mismatch_stops():
    good = [{"key": "v2.zip", "size": 12757853, "checksum": "md5:x"},
            {"key": ARCHIVE.key, "size": ARCHIVE.size, "checksum": ARCHIVE.checksum}]
    assert check_zenodo_manifest(good) == []
    assert check_zenodo_manifest(good[:1])
    assert check_zenodo_manifest([{**good[1], "size": 1}])
    assert check_zenodo_manifest(good + [{"key": "v4.zip", "size": 1, "checksum": "md5:y"}])
    rz = [{"id": RZ_MAIN.file_id, "name": RZ_MAIN.name, "size": RZ_MAIN.size, "md5": RZ_MAIN.md5}]
    assert check_rz_manifest(rz) == []
    assert check_rz_manifest([{**rz[0], "md5": "0"}])
    assert check_rz_manifest([])


def test_columns_and_stata_reading():
    with pytest.raises(FamineError):
        check_columns(["district_id", "year"], "districts")
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame({"district_id": [4, 5], "mortality": [0.019033, float("nan")],
                          "district_name": ["Бершадский", "Барский"]})
    frame["mortality"] = frame["mortality"].astype("float32")
    buffer = io.BytesIO()
    frame.to_stata(buffer, write_index=False, version=118)
    rows = read_stata_rows(buffer.getvalue())
    assert rows[0] == {"district_id": 4, "mortality": 0.019033, "district_name": "Бершадский"}
    assert rows[1]["mortality"] is None
