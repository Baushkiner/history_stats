"""Разбор наборов KUL geo-ecclesiae: храмы около 1772 года и по схематизмам 1936–1939.

Сети в тестах нет. Образец — объекты самих наборов (CC BY-SA 4.0 и
CC BY-NC 4.0) в том виде, в каком их отдаёт GeoJSON записей Zenodo:
MultiPoint из одной точки с высотой 0, поля по-польски, сокращения как есть.

Проверяется то, на чём слои держатся: сверка файла с именем, размером и md5
из кода, годы документов из поля `source` (только перед «r.», вне скобок,
в пределах XVIII века), интервал «около 1772 года», расширенный ими, тип
храма и его приход, годы и сканы схематизмов, своя фраза описания, точка в
WGS84 и в Web Mercator, храм с двумя точками и рамка: губерния 1897 года,
СССР без губернии и Галиция с `outside_bbox`.
"""

import hashlib
import json
import math

import pytest

from histctx.frame import OUTSIDE, Frame
from histctx.sources import geo_ecclesiae
from histctx.sources.geo_ecclesiae import (
    CHURCHES_1772_FILE, CHURCHES_1938_FILE, CHURCHES_PL_1772, CHURCHES_PL_1938,
    REQUIRED_1772, REQUIRED_1938, SLICE_YEAR, Dataset, GeoEcclesiaeError, check_manifest,
    church_years, document_years, feature_to_record, feature_to_record_1938, point_of,
    read_features, records_1772, records_1938, unknown_types, web_mercator_to_wgs84,
)


def feature(lon, lat, **props):
    base = {"OBJECTID": 1, "ob_id": 1, "diocese": "Wilno", "adeaconry": "Wilno",
            "deanery": "Troki", "type": "świątynia główna", "pl_type": "miasto",
            "pl_name": "Troki", "pl_name_de": None, "pl_name_v": None, "pal_name": "troc",
            "material": "mr", "patronage": "k", "kind": None, "title": "Imię NMP",
            "parish": None, "source": "Synodus, s. 145, 1744 r.; ANV. 143, k. 6, 1774 r.",
            "comment": ""}
    base.update(props)
    return {"type": "Feature", "id": base["OBJECTID"],
            "geometry": {"type": "MultiPoint", "coordinates": [[lon, lat, 0]]},
            "properties": base}


FEATURES = [
    feature(24.934, 54.652, ob_id=5001),
    # Филия в Галиции: в рамку РИ/СССР не входит, но остаётся в слое.
    feature(22.0107245087044, 49.6994260999444, ob_id=3057, diocese="Przemyśl",
            adeaconry="Brzozów", deanery="Brzozów", type="świątynia pomocnicza",
            pl_name="Brzozów", pal_name="rus", material="dr", patronage="mk", kind="kłs",
            title="Zofia M, Barbara PM", parish="Brzozów",
            source="AAPrz. AV175, s. 47, 1745 r.; ib. AV163, k. 817v, ok. 1750 r.",
            comment="wieś"),
    # Львов: СССР в 1945–1991 годах, губернии 1897 года нет.
    feature(24.0336983931089, 49.8380715261453, ob_id=3089, diocese="Lwów",
            adeaconry="Lwów", deanery="Lwów", type="świątynia pomocnicza", pl_name="Lwów",
            pal_name="rus", material=None, patronage=None, title=None, parish=None,
            source="SG. IV, s. 279 (wezw. z 1801 r.)"),
]


def payload(features=None, crs="EPSG:4326"):
    return json.dumps({"type": "FeatureCollection",
                       "crs": {"type": "name", "properties": {"name": crs}},
                       "features": FEATURES if features is None else features},
                      ensure_ascii=False).encode("utf-8")


# --- запись на Zenodo --------------------------------------------------------

def test_manifest_is_checked_against_the_code():
    good = [{"key": CHURCHES_1772_FILE.key, "size": CHURCHES_1772_FILE.size,
             "checksum": f"md5:{CHURCHES_1772_FILE.md5}"}]
    assert check_manifest(good, CHURCHES_1772_FILE) == []
    changed = [{"key": CHURCHES_1772_FILE.key, "size": 1, "checksum": "md5:00"}]
    problems = check_manifest(changed, CHURCHES_1772_FILE)
    assert len(problems) == 2 and "размер" in problems[0] and "сумма" in problems[1]
    assert "есть: other.gpkg" in check_manifest([{"key": "other.gpkg"}], CHURCHES_1772_FILE)[0]


def test_file_address_encodes_polish_letters():
    url = CHURCHES_1772_FILE.content_url
    assert url.startswith("https://zenodo.org/api/records/20743455/files/%C5%9Awi%C4%85tynie_1772")
    assert url.endswith("/content") and url.isascii()
    assert CHURCHES_1772_FILE.url == "https://doi.org/10.5281/zenodo.20743455"


def test_file_of_another_version_is_not_cached(tmp_path, monkeypatch):
    data = b"geojson bytes"
    monkeypatch.setattr(geo_ecclesiae, "fetch_bytes", lambda url, **kw: data)
    stale = Dataset("1", "Świątynie.geojson", 999, "00")
    with pytest.raises(GeoEcclesiaeError, match="ожидалось"):
        geo_ecclesiae.cached_file(stale, tmp_path)
    assert not list(tmp_path.iterdir())
    fresh = Dataset("1", "Świątynie.geojson", len(data), hashlib.md5(data).hexdigest())
    path = geo_ecclesiae.cached_file(fresh, tmp_path)
    assert path.name == "zenodo_1.geojson" and path.read_bytes() == data


# --- чтение ------------------------------------------------------------------

def test_features_are_read_and_checked():
    features, crs = read_features(payload(), REQUIRED_1772)
    assert len(features) == len(FEATURES) and crs == "EPSG:4326"
    broken = [feature(1, 1)]
    del broken[0]["properties"]["parish"]
    with pytest.raises(GeoEcclesiaeError, match="parish"):
        read_features(payload(broken), REQUIRED_1772)
    with pytest.raises(GeoEcclesiaeError, match="нет объектов"):
        read_features(payload([]), REQUIRED_1772)
    with pytest.raises(GeoEcclesiaeError, match="не разбирается"):
        read_features(b"<html>", REQUIRED_1772)


def test_points_in_wgs84_and_web_mercator():
    assert point_of({"type": "MultiPoint", "coordinates": [[24.9, 54.6, 0]]}) == (54.6, 24.9)
    assert point_of({"type": "Point", "coordinates": [24.9, 54.6]}) == (54.6, 24.9)
    assert point_of({"type": "Polygon", "coordinates": []}) == (None, None)
    assert point_of(None) == (None, None)
    # Граница Web Mercator: квадрат ±20 037 508,34 м — это ±85,0511° широты.
    lat, lon = web_mercator_to_wgs84(20037508.342789244, 20037508.342789244)
    assert lat == pytest.approx(85.0511287798, abs=1e-9) and lon == pytest.approx(180.0)
    # Туда и обратно через прямую формулу: Вильно.
    r = 6_378_137.0
    x = r * math.radians(25.2797)
    y = r * math.log(math.tan(math.pi / 4 + math.radians(54.6872) / 2))
    assert point_of({"type": "Point", "coordinates": [x, y]}, web_mercator=True) == (
        pytest.approx(54.6872, abs=1e-9), pytest.approx(25.2797, abs=1e-9))


def test_web_mercator_crs_is_recognised():
    r = 6_378_137.0
    moved = [feature(r * math.radians(24.934), r * math.log(math.tan(
        math.pi / 4 + math.radians(54.652) / 2)))]
    features, crs = read_features(payload(moved, crs="urn:ogc:def:crs:EPSG::3857"),
                                  REQUIRED_1772)
    rec = records_1772(features, crs)[0]
    assert rec.lat == pytest.approx(54.652, abs=1e-9) and rec.lon == pytest.approx(24.934)


# --- датировка ---------------------------------------------------------------

@pytest.mark.parametrize("source, years", [
    ("AAPrz. AV175, s. 47, 1745 r.; ib. AV163, k. 817v, ok. 1750 r.", [1745, 1750]),
    ("ANV. 120, k. 468, 1773-1774 r.", [1773, 1774]),
    ("AAWr. IIb 228, 1768, 1787 r.; ib. IIb 12a, nr 26, 1781 r.", [1768, 1781, 1787]),
    # Год постройки в скобках и номер схематизма без «r.» — не годы документов.
    ("Schem. 1857, s. 116 (kł wyb. w 1538 r.)", []),
    # «BCz. 1775» — шифр рукописи, «1783 (1755) r.» — год со скобкой.
    ("BCz. 1775, 479 (dok. fund. 1519 r.); Synodus, s. 146, 1744 r.", [1744]),
    ("AKK. AV54, s. 616, 1783 (1755) r.", [1783]),
    # Страница 1960 перед годом и литература XX века — вне XVIII века.
    ("BCz. 1775, s. 1960, 1700 r.; DP. 1977 r., s. 363.", [1700]),
    ("AAB. AV. bs, 1828, 1829 r.; Connotatio, s. 65, 1520 r.", []),
    ("SG. IV, s. 461", []),
    (None, []),
])
def test_document_years_come_from_the_source_field(source, years):
    assert document_years(source) == years


def test_slice_is_widened_by_eighteenth_century_documents():
    assert church_years("AAPrz. AV160, k. 24v, 1727 r.; ib. AV169, 1744 r.") == (
        1727, SLICE_YEAR, [1727, 1744])
    assert church_years("Synodus, 1744 r.; ib. 1797 r.") == (1744, 1797, [1744, 1797])
    assert church_years("SG. II, s. 318") == (SLICE_YEAR, SLICE_YEAR, [])


# --- записи ------------------------------------------------------------------

@pytest.fixture
def recs():
    return records_1772(FEATURES)


def test_main_church_record(recs):
    troki = recs[0]
    assert troki.layer == CHURCHES_PL_1772.slug and troki.group == "faith"
    assert troki.title == "Troki — Imię NMP"
    assert troki.category == "главный храм прихода"
    assert (troki.year_from, troki.year_to) == (1744, 1774)
    assert troki.date_approx and troki.date_precision == "year"
    assert troki.period_raw == "ok. 1772"
    assert troki.source_id == "5001" and troki.url == CHURCHES_PL_1772.url
    assert troki.summary == (
        "Troki (город): около 1772 года — главный храм прихода. Диоцез Wilno, "
        "архидиаконат Wilno, деканат Troki. Годы документов в источнике: 1744, 1774.")
    assert "parish" not in troki.extra


def test_filial_church_keeps_its_parish_and_codes_as_is(recs):
    brzozow = recs[1]
    assert brzozow.category == "вспомогательный храм (филия, часовня)"
    assert brzozow.title == "Brzozów — Zofia M, Barbara PM"
    assert "филия или часовня) прихода Brzozów" in brzozow.summary
    extra = brzozow.extra
    assert extra["parish"] == "Brzozów" and extra["deanery"] == "Brzozów"
    assert extra["archdeaconry"] == "Brzozów" and extra["diocese"] == "Przemyśl"
    assert extra["palatinate"] == "rus" and extra["material"] == "dr"
    assert extra["patronage"] == "mk" and extra["kind"] == "kłs"
    assert extra["sources"].startswith("AAPrz. AV175")
    assert extra["source_years"] == [1745, 1750] and extra["comment"] == "wieś"


def test_church_without_dedication_or_parish(recs):
    lwow = recs[2]
    assert lwow.title == "Lwów — вспомогательный храм (филия, часовня)"
    assert "приход в наборе не указан" in lwow.summary
    # Год в скобках («wezw. z 1801 r.») срез не растягивает.
    assert (lwow.year_from, lwow.year_to) == (SLICE_YEAR, SLICE_YEAR)
    assert "source_years" not in lwow.extra and "Годы документов" not in lwow.summary


def test_unknown_church_type_is_reported():
    assert unknown_types(FEATURES) == []
    assert unknown_types([feature(1, 1, type="kaplica prywatna")]) == ["kaplica prywatna"]


# --- рамка -------------------------------------------------------------------

def _square(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def test_frame_marks_galicia_and_keeps_lviv(tmp_path, recs):
    provinces = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"prov_RU": "Виленская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(24.0, 54.0, 26.0, 55.5)}}]}
    states = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"state": "Россия (Советский Союз)"},
         "geometry": {"type": "Polygon", "coordinates": _square(23.5, 49.5, 25.0, 50.3)}},
        {"type": "Feature", "properties": {"state": "Австро-Венгрия"},
         "geometry": {"type": "Polygon", "coordinates": _square(18.5, 49.0, 23.4, 50.29)}}]}
    (tmp_path / "provinces_1897.geojson").write_text(json.dumps(provinces), encoding="utf-8")
    (tmp_path / "state_borders.geojson").write_text(json.dumps(states), encoding="utf-8")
    counts = Frame.load(tmp_path).mark(recs)
    troki, brzozow, lwow = recs
    assert troki.region == "Виленская губерния" and troki.confidence == "ok"
    assert brzozow.confidence == OUTSIDE and brzozow.region is None
    assert lwow.confidence == "ok" and lwow.region is None
    assert counts["вне рамки РИ/СССР"] == 1 and counts["в губерниях 1897 года"] == 1


def test_records_are_built_one_per_church():
    recs = [feature_to_record(f) for f in FEATURES]
    assert len({r.uid for r in recs}) == len(FEATURES)
    assert all(r.has_point and r.has_time for r in recs)


# --- срез 1936–1939 годов -------------------------------------------------------

def feature_1938(coords, **props):
    base = {"OBJECTID": 1, "fid": 1, "id": 594, "pl_name": "Kleszczele", "pl_name_v": None,
            "title": "Zygmunt Kr", "deanery": "Bielsk Podlaski", "diocese": "Pińsk",
            "material_type": None,
            "comments": "material_type: Hałaburda cz. V t. 1 s. 143: [brak informacji]",
            "location_g": "OSM", "location_i": None,
            "location_w": "https://www.wikidata.org/wiki/Q16569305",
            "schem_1_date": "1938",
            "schem_1": "https://geo-ecclesiae.kul.pl/skany/schematyzmy/pinsk_1938/0057.jpg",
            "schem_2_date": "1939",
            "schem_2": "https://geo-ecclesiae.kul.pl/skany/schematyzmy/pinsk_1939/0057.jpg"}
    base.update(props)
    return {"type": "Feature", "id": base["OBJECTID"],
            "geometry": {"type": "MultiPoint", "coordinates": coords},
            "properties": base}


def test_parish_church_of_1938_links_the_schematism_scan():
    features, _ = read_features(payload([feature_1938([[23.3277739, 52.5736384, 0]])]),
                                REQUIRED_1938)
    rec = feature_to_record_1938(features[0])
    assert rec.layer == CHURCHES_PL_1938.slug and rec.group == "faith"
    assert rec.title == "Kleszczele — Zygmunt Kr" and rec.category == "приходской храм"
    assert (rec.year_from, rec.year_to) == (1938, 1939)
    assert rec.date_precision == "year" and not rec.date_approx
    assert rec.period_raw == "1938; 1939" and rec.source_id == "594"
    # Ссылка записи — скан страницы схематизма, первоисточник; второй — в extra.
    assert rec.url.endswith("pinsk_1938/0057.jpg")
    assert rec.extra["schematism_2"].endswith("pinsk_1939/0057.jpg")
    assert rec.extra["schematism_year"] == 1938 and rec.extra["schematism_2_year"] == 1939
    assert rec.extra["wikidata"].endswith("Q16569305")
    assert rec.extra["deanery"] == "Bielsk Podlaski" and rec.extra["diocese"] == "Pińsk"
    assert rec.summary == ("Kleszczele: латинский приходской храм в схематизмах диоцеза "
                           "Pińsk 1938 и 1939 годов. Деканат Bielsk Podlaski.")
    assert rec.confidence == "ok"


def test_schematism_years_order_and_placeholders():
    older = feature_to_record_1938(feature_1938([[24.03, 49.84, 0]], schem_2_date="1936"))
    assert (older.year_from, older.year_to) == (1936, 1938)
    single = feature_to_record_1938(feature_1938(
        [[24.03, 49.84, 0]], schem_2_date=None, schem_2=None))
    assert (single.year_from, single.year_to) == (1938, 1938)
    assert "схематизме диоцеза Pińsk 1938 года" in single.summary
    assert "schematism_2" not in single.extra
    blank = feature_to_record_1938(feature_1938(
        [[24.03, 49.84, 0]], pl_name="Remel", title="[brak informacji]",
        material_type="[brak kościoła]"))
    assert blank.title == "Remel — приходской храм"
    assert "dedication" not in blank.extra and "material" not in blank.extra


def test_church_with_two_points_is_flagged_not_moved():
    rec = feature_to_record_1938(feature_1938(
        [[24.1818772141083, 48.9947771606234, 0], [26.0979618519378, 48.6998796103049, 0]],
        pl_name="Krzywcze"))
    assert rec.confidence == "multiple_points"
    assert (rec.lat, rec.lon) == (48.9947771606234, 24.1818772141083)
    assert rec.extra["points"] == [[48.994777, 24.181877], [48.69988, 26.097962]]


def test_records_1938_read_web_mercator():
    r = 6_378_137.0
    x, y = r * math.radians(23.3278), r * math.log(math.tan(
        math.pi / 4 + math.radians(52.5736) / 2))
    features, crs = read_features(payload([feature_1938([[x, y]])], crs="EPSG:3857"),
                                  REQUIRED_1938)
    rec = records_1938(features, crs)[0]
    assert rec.lat == pytest.approx(52.5736, abs=1e-9)
    assert rec.lon == pytest.approx(23.3278, abs=1e-9)


def test_1938_file_is_pinned_to_its_record():
    assert CHURCHES_1938_FILE.record == "18944997"
    assert CHURCHES_PL_1938.url == "https://doi.org/10.5281/zenodo.18944997"
    assert CHURCHES_1938_FILE.content_url.isascii()
