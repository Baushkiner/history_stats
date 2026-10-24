"""Разбор сервера карт HURI MAPA: районы УССР, перепись 1926 года, Подолия.

Сети в тестах нет: атрибуты сняты с ответов `maps-huri-ws.net` 24.10.2026 и
урезаны до нужных колонок; геометрия — маленькие кольца в том порядке
обхода, в каком их отдаёт ArcGIS. Проверяется сверка перечня слоёв с
сервером, перевод дат и полей двух схем, упрощение и ориентация колец,
записи переписи (территориальные, без точки, губерния 1897 года по полигону,
пустые единицы остаются) и записи Подолии (открытый срок у живого села,
только год упоминания у пустоши, «тепер не існує» — не имя).
"""

from pathlib import Path

import pytest

from histctx.registry import BY_SLUG, HARVESTED
from histctx.schema import SCOPE_POINT, SCOPE_REGION
from histctx.sources.huri import (
    ADMIN_UKRAINE, CENSUS_1926, PODILLYA, SLICES, RaionIndex, admin_properties,
    census_records, check_admin_service, check_layer, epoch_date, esri_polygon,
    nationality_counts, okruha_names, podillya_records, representative_point, same_features,
    share_mismatches, simplify, slice_features, to_number,
)

ROOT = Path(__file__).resolve().parents[1]
PROVINCES_1897 = ROOT / "data" / "out" / "boundaries" / "provinces_1897.geojson"

SLICE_1937 = next(s for s in SLICES if s.layer_id == 2)
SLICE_1932_10 = next(s for s in SLICES if s.layer_id == 18)
CENTERS_1922 = next(s for s in SLICES if s.layer_id == 34)

# Спартаковский район на 15 января 1937 года (слой 2).
SPARTAKIVKA_1937 = {
    "OBJECTID": 3, "REGION": "Одеська", "ADM_Type": "район", "ADM_Seat": "Спартаківка",
    "ENG_Name": "Spartakivka", "UKR_Name": "Спартаківський", "RUS_Name": "Спартаковский",
    "MAP_Name": "Спартаківський", "LABEL": "Спартаківський район",
    "NOTES": "нац. німецький; кол. Грос-Лібентальський",
    "START_D": -1040169600000, "END_Date": -978393600000, "RAY_Master": "Ray-1937-01-3",
}

# Скадовский район на 25 октября 1932 года (слой 18): другая схема полей.
SKADOVSK_1932 = {
    "OBJECTID": 1, "Region": "Одеська", "LABEL": " ", "End_Date": -1159920000000, "Id": 1,
    "TYPE": "район", "NAME_UA": "Скадівський", "NAME_RUS": "Скадовский",
    "NAME_LAT": "Skadivskyi", "DATE": -1173484800000, "COMMENT": " ",
    "Master_rai": "Rai-1932-10-1",
}

# Центр повита «в январе 1922 года» (слой 34) с датами среза 1928 года.
HENICHESK_1922 = {
    "OBJECTID": 1, "REGION": "Запорізька", "UKR_Name": "Генічеськ", "RUS_Name": "Геническ",
    "ENG_Name": "Henichesk", "START_D": -1305849600000, "END_Date": -1192492800000,
    "ADM_Type": "повцентр", "NOTES": "також Геничеськ або Геничеське",
    "ADM_Master": "Adm-1928-08-2", "HISTORIC": "Геничеське", "PRESENT": "Генічеськ",
}

_ZERO = {f"{code}_{suffix}": 0 for code in ("Ukr", "Rus", "Jew", "Pol", "Ger", "Bel", "Mol",
                                            "Gre", "Tat", "Arm")
         for suffix in ("male", "female", "both")}

# Перепись: Скадовский район (строки «2», «4» — у части народностей колонка
# строковая), Мангушский (делит RAY_Master с Новоселовским, греческое
# большинство), Черняховский («1,596» чехов) и Одесский горсовет (нули).
SKADOVSK_1926 = {
    "OBJECTID_1": 2, "REGION": "Херсонська", "ADM_Type": "район", "ADM_Seat": "Скадівськ",
    "ENG_Name": "Skadivsk", "UKR_Name": "Скадiвський", "RUS_Name": "Скадовский",
    "NOTES": "також Скадівський", "LABEL": "Скадiвський район", "START_D": -1351900800000,
    "RAY_Master": "Ray-1927-01-0",
    "All_male": 16001, "All_female": 17615, "All_both": 33616,
    "Ukr_male": 12838, "Ukr_female": 14129, "Ukr_both": 26967, "Ukr_to_All_both": 80.2207,
    "Rus_male": 2698, "Rus_female": 3037, "Rus_both": 5735, "Rus_to_All_both": 17.0603,
    "Jew_male": 163, "Jew_female": 174, "Jew_both": 337, "Jew_to_All_both": 1.0025,
    "Mol_male": 179, "Mol_female": 149, "Mol_both": 328,
    "Cze_male": "2", "Cze_female": "3", "Cze_both": "5", "Cze_to_All_both": 0.01487,
    "Gre_both": 0, "Gyp_both": None, "Bul_male": "4", "Bul_female": "0", "Bul_both": "4",
    "Majority": "Ukr",
}
MANHUSH_1926 = {
    "OBJECTID_1": 502, "REGION": "Маріупільська", "ADM_Type": "район", "ADM_Seat": "Ялта",
    "UKR_Name": "Мангушський", "RUS_Name": "Мангушский", "LABEL": "Новоселівський район",
    "NOTES": " ", "START_D": -1351900800000, "RAY_Master": "Ray-1927-01-31",
    "All_male": 8731, "All_female": 9667, "All_both": 18398,
    "Ukr_male": 1851, "Ukr_female": 2064, "Ukr_both": 3915,
    "Rus_male": 585, "Rus_female": 559, "Rus_both": 1144,
    "Gre_male": 6222, "Gre_female": 7001, "Gre_both": 13223, "Majority": "Gre",
}
CHERNIAKHIV_1926 = {
    "OBJECTID_1": 490, "REGION": "Волинська", "ADM_Type": "район", "UKR_Name": "Черняхівський",
    "RUS_Name": "Черняховский", "RAY_Master": "Ray-1927-01-375",
    "All_both": 51243, "Ukr_both": 41559, "Ger_both": 3167, "Jew_both": 2335,
    "Cze_male": "778", "Cze_female": "818", "Cze_both": "1,596", "Cze_to_All_both": 4.42399,
}
ODESA_COUNCIL_1926 = {
    "OBJECTID_1": 7, "REGION": "Одеська", "ADM_Type": "міськрада", "ADM_Seat": "Одеса",
    "UKR_Name": "Одеська", "RUS_Name": "Одесский", "LABEL": "Одеська міськрада",
    "RAY_Master": "Ray-1927-01-501", "All_male": 0, "All_female": 0, "All_both": 0,
    "Majority": "Non", **_ZERO,
}

OKRUHAS_1927 = {"features": [{"attributes": a} for a in (
    {"UKR_Name": "Херсонська", "RUS_Name": "Херсонский", "ADM_Type": "округа",
     "LABEL": "Херсонська округа"},
    {"UKR_Name": "Маріупольська", "RUS_Name": "Мариупольский", "ADM_Type": "округа",
     "LABEL": "Маріупільська округа"},
    {"UKR_Name": "Харківська", "RUS_Name": "Харковский", "ADM_Type": "округа",
     "LABEL": "Харківська округа"},
    {"UKR_Name": "Молдавська", "RUS_Name": "Молдавская", "ADM_Type": "АСРР",
     "LABEL": "Молдавська АСРР"},
)]}

PODILLYA_ROWS = [
    {"OBJECTID": 1, "name_historic_ukr": "Агдашов", "name_historic_eng": "Agdashov",
     "name_modern_ukr": "Серебрія", "name_modern_eng": "Serebria",
     "type_placename__ukr": "село", "date_start": 1448, "date_end": None,
     "ptoperty_type": "кор. вл.", "povit_middle_ages_modern_ukr": "Кам'янецький",
     "y_Latitude": 48.457876, "x_Longitude": 27.723954},
    {"OBJECTID": 23, "name_historic_ukr": "Берладка", "name_modern_ukr": "Петрівка",
     "type_placename__ukr": "село", "date_start": 1411, "date_end": "1430",
     "ptoperty_type": None, "povit_middle_ages_modern_ukr": None,
     "y_Latitude": 48.507086, "x_Longitude": 27.951373},
    {"OBJECTID": 184, "name_historic_ukr": "Кам'янець",
     "name_modern_ukr": "Кам'янець-Подільський", "type_placename__ukr": "місто",
     "date_start": None, "date_end": "1370", "ptoperty_type": "кор. вл.",
     "y_Latitude": 48.675293, "x_Longitude": 26.572617},
    {"OBJECTID": 26, "name_historic_ukr": "Бласковці (Блашковці)",
     "name_modern_ukr": "тепер не існує", "type_placename__ukr": "село",
     "date_start": 1424, "date_end": None, "ptoperty_type": "дід. вл.",
     "povit_middle_ages_modern_ukr": "Червоногродський",
     "y_Latitude": 48.687273, "x_Longitude": 25.646532},
    {"OBJECTID": 505, "name_historic_ukr": "Чубаровиці", "name_modern_ukr": "Чабарівка",
     "type_placename__ukr": "пустка", "date_start": 1411, "date_end": "1430",
     "y_Latitude": 49.082244, "x_Longitude": 26.123223},
]


class Box:
    """Справочник губерний на прямоугольниках — вместо полигонов 1897 года."""

    def __init__(self, *areas):
        self.areas = areas

    def region_for(self, lat, lon):
        for name, (lat0, lon0, lat1, lon1) in self.areas:
            if lat0 <= lat <= lat1 and lon0 <= lon <= lon1:
                return name
        return None


def _square(lon0, lat0, lon1, lat1, *, clockwise=True):
    ring = [[lon0, lat0], [lon0, lat1], [lon1, lat1], [lon1, lat0], [lon0, lat0]]
    return ring if clockwise else ring[::-1]


def _payload(*rows):
    return {"features": [{"attributes": dict(row)} for row in rows]}


# --- сверка с сервером ------------------------------------------------------

def test_service_listing_is_compared_by_id_and_name():
    listing = {"layers": [{"id": s.layer_id, "name": s.name} for s in SLICES]}
    assert check_admin_service(listing) == []
    listing["layers"][1]["name"] = "Raions on 1 January 1937"
    problems = check_admin_service(listing)
    assert len(problems) == 1 and "Raions on 15 January 1937" in problems[0]


def test_layer_is_checked_for_name_fields_and_count():
    info = {"name": "Raions on 15 January 1937",
            "fields": [{"name": n} for n in ("OBJECTID", "UKR_Name", "RUS_Name", "ENG_Name",
                                              "ADM_Type", "START_D")]}
    required = {"OBJECTID", "UKR_Name", "RUS_Name", "ENG_Name", "ADM_Type", "START_D"}
    assert check_layer(info, name=info["name"], required=required, count=525,
                       actual_count=525) == []
    problems = check_layer(info, name=info["name"], required=required | {"END_Date"},
                           count=525, actual_count=524)
    assert any("END_Date" in p for p in problems) and any("524" in p for p in problems)


def test_slices_are_unique_and_duplicates_point_at_a_real_slice():
    ids = [s.layer_id for s in SLICES]
    assert len(ids) == len(set(ids))
    by_id = {s.layer_id: s for s in SLICES}
    for item in SLICES:
        if item.duplicate_of is not None:
            twin = by_id[item.duplicate_of]
            assert twin.level == item.level and twin.duplicate_of is None


def test_duplicate_slice_is_detected_down_to_the_vertex():
    a = {"features": [{"attributes": {"OBJECTID": 1}, "geometry": {"rings": [[[1, 2]]]}}]}
    b = {"features": [{"attributes": {"OBJECTID": 1}, "geometry": {"rings": [[[1, 2]]]}}]}
    assert same_features(a, b)
    b["features"][0]["geometry"]["rings"][0][0][0] = 1.0001
    assert not same_features(a, b)


# --- подложка ----------------------------------------------------------------

def test_dates_are_read_as_utc_days():
    assert epoch_date(-1040169600000) == "1937-01-15"
    assert epoch_date(-1351900800000) == "1927-03-01"
    assert epoch_date(None) is None


def test_master_schema_properties():
    props = admin_properties(SPARTAKIVKA_1937, SLICE_1937)
    assert props["as_of"] == "1937-01-15" and props["level"] == "raion"
    assert props["name_ru"] == "Спартаковский" and props["seat"] == "Спартаківка"
    assert props["start"] == "1937-01-15" and props["end"] == "1938-12-31"
    assert props["notes"].startswith("нац. німецький")
    assert props["id"] == "Ray-1937-01-3"
    assert "dates_conflict" not in props


def test_1932_schema_is_mapped_to_the_same_names_and_blanks_dropped():
    props = admin_properties(SKADOVSK_1932, SLICE_1932_10)
    assert props["name_uk"] == "Скадівський" and props["name_en"] == "Skadivskyi"
    assert props["start"] == "1932-10-25" and props["end"] == "1933-03-31"
    assert props["id"] == "Rai-1932-10-1" and props["kind"] == "район"
    assert "label" not in props and "notes" not in props


def test_dates_from_another_slice_are_flagged_not_rewritten():
    props = admin_properties(HENICHESK_1922, CENTERS_1922)
    assert props["as_of"] == "1922-01-01"
    assert props["start"] == "1928-08-15"
    assert props["dates_conflict"] is True
    assert props["historic"] == "Геничеське" and props["present"] == "Генічеськ"


def test_rings_are_reoriented_and_holes_attached():
    outer = _square(30.0, 46.0, 31.0, 47.0, clockwise=True)
    hole = _square(30.4, 46.4, 30.6, 46.6, clockwise=False)
    geometry = esri_polygon({"rings": [outer, hole]}, tolerance=0.0)
    assert geometry["type"] == "Polygon"
    shell, inner = geometry["coordinates"]
    area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(shell, shell[1:]))
    assert area > 0, "внешнее кольцо в GeoJSON — против часовой"
    assert len(inner) == 5


def test_two_outer_rings_make_a_multipolygon():
    rings = [_square(30, 46, 31, 47), _square(32, 46, 33, 47)]
    assert esri_polygon({"rings": rings})["type"] == "MultiPolygon"


def test_simplification_drops_collinear_points_and_never_loses_a_unit():
    line = [[0, 0], [0.5, 0.0001], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert [0.5, 0.0001] not in simplify(line, 0.001)
    tiny = _square(30.0, 46.0, 30.0004, 46.0004)
    geometry = esri_polygon({"rings": [tiny]}, tolerance=0.01, digits=4)
    assert geometry is not None, "схлопнутое кольцо берётся без упрощения"


def test_slice_features_keep_centers_as_points():
    payload = {"features": [{"attributes": HENICHESK_1922,
                             "geometry": {"x": 34.788247190, "y": 46.174773729}}]}
    feature = slice_features(payload, CENTERS_1922)[0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [34.78825, 46.17477]}


def test_representative_point_is_inside_a_horseshoe():
    # Подкова: центроид приходится на вырез, точка обязана лечь на полосу.
    ring = [[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3], [0, 0]]
    lat, lon = representative_point({"type": "Polygon", "coordinates": [ring]})
    assert not (1 < lon < 2 and lat > 1)


# --- перепись 1926 года -------------------------------------------------------

def test_numbers_in_text_columns_are_read():
    assert to_number("1,596") == 1596
    assert to_number(" ") is None
    assert to_number(0) == 0


def test_okruha_names_cover_both_spellings_and_fix_typos():
    names = okruha_names(OKRUHAS_1927)
    assert names["Херсонська"] == "Херсонский округ"
    assert names["Маріупільська"] == names["Маріупольська"] == "Мариупольский округ"
    assert names["Харківська"] == "Харьковский округ"
    assert names["Молдавська"] == "Молдавская АССР"


def _index():
    shapes = {
        ("Ray-1927-01-0", "Скадiвський"):
            esri_polygon({"rings": [_square(32.5, 45.9, 33.4, 46.4)]}),
        ("Ray-1927-01-31", "Мангушський"):
            esri_polygon({"rings": [_square(37.2, 46.9, 37.5, 47.1)]}),
    }
    return RaionIndex(shapes=shapes, okruhas=okruha_names(OKRUHAS_1927))


def test_census_record_is_territorial_with_the_1897_province():
    provinces = Box(("Таврическая губерния", (45.0, 32.0, 46.6, 36.0)),
                    ("Екатеринославская губерния", (46.6, 33.0, 49.0, 39.0)))
    skadovsk, manhush = census_records(_payload(SKADOVSK_1926, MANHUSH_1926), _index(),
                                       provinces)
    assert skadovsk.scope == SCOPE_REGION and not skadovsk.has_point
    assert skadovsk.title == "Скадовский район (Херсонский округ): перепись 1926 года"
    assert skadovsk.region == "Таврическая губерния"
    assert skadovsk.regions == ["Таврическая губерния"]
    assert skadovsk.district == "Скадовский район"
    assert (skadovsk.year_from, skadovsk.year_to) == (1926, 1926)
    assert skadovsk.usable
    assert manhush.region == "Екатеринославская губерния"
    assert manhush.title.startswith("Мангушский район (Мариупольский округ)")
    assert skadovsk.uid != manhush.uid


def test_census_summary_and_extra_are_built_from_counts():
    rec = census_records(_payload(SKADOVSK_1926), _index(), None)[0]
    assert "33 616 человек" in rec.summary
    assert "16 001 муж." in rec.summary
    assert "Украинцы — 80%, русские — 17%, евреи — 1%" in rec.summary
    counts = rec.extra["census_1926"]
    assert counts["болгары"] == {"м": 4, "ж": 0, "оба": 4}
    assert "греки" not in counts and "цыгане" not in counts
    assert rec.extra["majority"] == "украинцы"
    assert rec.extra["raion"]["ray_master"] == "Ray-1927-01-0"
    assert "OBJECTID_1%3D2" in rec.url and rec.url.startswith("https://maps-huri-ws.net/")
    assert rec.license == CENSUS_1926.license and "права не выяснены" in rec.license


def test_empty_unit_is_kept_and_says_so():
    rec = census_records(_payload(ODESA_COUNCIL_1926))[0]
    assert rec.title.startswith("Одесский горсовет")
    assert rec.category == "перепись 1926 года: числа не заполнены"
    assert "не заполнены" in rec.summary
    assert "majority" not in rec.extra


def test_unit_without_a_province_is_marked_not_dropped():
    rec = census_records(_payload(SKADOVSK_1926), _index(), Box())[0]
    assert rec.region is None and rec.confidence == "region_unmatched"


def test_share_column_is_compared_with_counts():
    counts = nationality_counts(CHERNIAKHIV_1926)
    assert counts["чехи"] == {"м": 778, "ж": 818, "оба": 1596}
    assert share_mismatches(_payload(CHERNIAKHIV_1926)) == {"Cze": 1}
    assert share_mismatches(_payload(SKADOVSK_1926)) == {}


@pytest.mark.skipif(not PROVINCES_1897.exists(), reason="нет полигонов 1897 года")
def test_real_1897_polygons_put_skadovsk_into_taurida():
    from histctx.sources.ghcn import Provinces

    provinces = Provinces.load(PROVINCES_1897)
    rec = census_records(_payload(SKADOVSK_1926), _index(), provinces)[0]
    assert rec.region == "Таврическая губерния"


# --- Подолия -------------------------------------------------------------------

def _podillya():
    return {r.source_id: r for r in podillya_records(_payload(*PODILLYA_ROWS))}


def test_living_village_gets_an_open_term_from_its_first_mention():
    rec = _podillya()["podillya:1"]
    assert rec.scope == SCOPE_POINT and rec.has_point
    assert rec.title == "Агдашов (ныне Серебрія): первое упоминание"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1448, 1960, "open")
    assert rec.period_raw == "первое упоминание 1448 г., существует поныне"
    assert "королевское владение" in rec.summary and rec.category == "село"


def test_mention_range_and_upper_bound_are_read():
    rows = _podillya()
    assert rows["podillya:23"].year_from == 1411
    assert "1411–1430 гг." in rows["podillya:23"].summary
    kamianets = rows["podillya:184"]
    assert kamianets.year_from == 1370 and kamianets.category == "город"
    assert "не позже 1370 г." in kamianets.period_raw


def test_vanished_place_has_no_modern_name_and_no_open_term():
    rec = _podillya()["podillya:26"]
    assert "ныне" not in rec.title
    assert "ныне не существует" in rec.summary
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1424, 1424, "year")
    assert rec.extra["gone"] is True


def test_wasteland_keeps_only_the_mention_interval():
    rec = _podillya()["podillya:505"]
    assert rec.category == "пустошь"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1411, 1430, "year")


def test_podillya_takes_province_and_district_from_the_reference():
    provinces = Box(("Подольская губерния", (48.0, 26.0, 50.0, 30.0)))
    districts = Box(("Могилевский", (48.0, 27.5, 49.0, 28.5)))
    rec = podillya_records(_payload(PODILLYA_ROWS[0]), provinces, districts)[0]
    assert rec.region == "Подольская губерния"
    assert rec.district == "Могилевский уезд"


# --- реестр --------------------------------------------------------------------

def test_layers_are_registered_as_harvested():
    for spec in (ADMIN_UKRAINE, CENSUS_1926, PODILLYA):
        assert BY_SLUG[spec.slug] is spec
        assert spec in HARVESTED and spec.status == "harvested"
        assert "права не выяснены" in spec.license
        assert spec.url.startswith("https://maps-huri-ws.net/")
    assert ADMIN_UKRAINE.gives_records is False
    assert CENSUS_1926.gives_records and PODILLYA.gives_records
