"""Кирхшпили и мызы до 1917 года: WFS Maa- ja Ruumiamet «Ajalooline haldusjaotus».

Образцы — фрагменты настоящих ответов GetFeature от 04.11.2026: мыза Палмсе
(`moisakeskus.2310`) целиком и кирхшпиль Рухну (`kihelkond_1917.65`) с
кольцом, сокращённым до шести вершин. Эталон проекции — PROJ 9 (pyproj 3.8),
посчитан один раз; в зависимости проекта pyproj не входит.
"""

import pytest

from histctx.periods import PRECISION_OPEN
from histctx.sources.maaamet import (
    COUNTY_UEZD, GOVERNORATES, LAYER_HORIZON, MANOR_LAYER, MANORS_EE, PARISH_BOUNDARIES_EE,
    PARISH_LAYER, Area, Feature, MaaametError, WfsLayer, build_parishes, check_layer,
    estonian_period, geojson_geometry, lest97_pair, lest97_to_wgs84, manor_period,
    manor_record, parish_feature, parse_capabilities, parse_gml, point_on_surface,
    polygon_area, wgs84_to_lest97,
)

HEAD = (
    '<?xml version=\'1.0\' encoding="UTF-8" ?>\n<wfs:FeatureCollection\n'
    '   xmlns:ms="http://mapserver.gis.umn.edu/mapserver"\n'
    '   xmlns:gml="http://www.opengis.net/gml/3.2"\n'
    '   xmlns:wfs="http://www.opengis.net/wfs/2.0"\n'
    '   timeStamp="2026-11-04T17:58:24" numberMatched="1" numberReturned="1">\n'
)

PALMSE = HEAD + """
    <wfs:member>
      <ms:moisakeskus gml:id="moisakeskus.2310">
        <ms:msGeometry>
          <gml:Point gml:id="moisakeskus.2310.1" srsName="urn:ogc:def:crs:EPSG::3301">
            <gml:pos>6598854.112399 610746.006400</gml:pos>
          </gml:Point>
        </ms:msGeometry>
        <ms:SKS_NIMI>Palms</ms:SKS_NIMI>
        <ms:NIMI>Palmse</ms:NIMI>
        <ms:ALIAS></ms:ALIAS>
        <ms:TYYP>eramõis</ms:TYYP>
        <ms:KIHELKOND>Kadrina</ms:KIHELKOND>
        <ms:MAAKOND>Viru</ms:MAAKOND>
        <ms:KUBERMANG>Eestimaa</ms:KUBERMANG>
        <ms:MARKUS>teateid 1510</ms:MARKUS>
        <ms:PEAMOIS></ms:PEAMOIS>
        <ms:TAPSUS>peahoone</ms:TAPSUS>
        <ms:URL_MUINAS>https://register.muinas.ee/public.php?menuID=monument&amp;action=view&amp;id=15893</ms:URL_MUINAS>
        <ms:URL_EELIS></ms:URL_EELIS>
        <ms:URL_MOISAP>http://mois.ee/viru/palmse.shtml</ms:URL_MOISAP>
      </ms:moisakeskus>
    </wfs:member>
</wfs:FeatureCollection>
"""

# Рухну: настоящий фрагмент, кольцо сокращено до шести вершин (север, восток).
RUHNU = HEAD + """
    <wfs:member>
      <ms:kihelkond_1917 gml:id="kihelkond_1917.65">
        <ms:msGeometry>
          <gml:Polygon gml:id="kihelkond_1917.65.1" srsName="urn:ogc:def:crs:EPSG::3301">
            <gml:exterior>
              <gml:LinearRing>
                <gml:posList srsDimension="2">6405886.218502 456792.533595
                6404401.316644 456628.850142 6404669.598622 455869.517805
                6405303.809938 454781.163523 6409654.579003 453156.410787
                6405886.218502 456792.533595</gml:posList>
              </gml:LinearRing>
            </gml:exterior>
          </gml:Polygon>
        </ms:msGeometry>
        <ms:NIMI>Ruhnu</ms:NIMI>
        <ms:MAAKOND>Saare</ms:MAAKOND>
        <ms:KUBERMANG>Liivimaa</ms:KUBERMANG>
      </ms:kihelkond_1917>
    </wfs:member>
</wfs:FeatureCollection>
"""


# --- проекция ----------------------------------------------------------------

def test_projection_origin_is_the_false_origin():
    lat, lon = lest97_to_wgs84(500000, 6375000)
    assert lat == pytest.approx(57.51755393055556, abs=1e-10)
    assert lon == pytest.approx(24.0, abs=1e-10)


@pytest.mark.parametrize("x, y, lat, lon", [
    (542000, 6589000, 59.436750698, 24.740141531),      # Таллин
    (659000, 6474000, 58.377480241, 26.718410320),      # Тарту
    (369032.10, 6377141.33, 57.517620924, 21.814405408),  # юго-западный угол EPSG:3301
])
def test_projection_matches_proj(x, y, lat, lon):
    got = lest97_to_wgs84(x, y)
    assert got == pytest.approx((lat, lon), abs=1e-8)


def test_palmse_manor_lands_where_it_stands():
    """Палмсе по независимому источнику — 59°30′46″ с. ш., 25°57′22″ в. д."""
    feature = parse_gml(PALMSE.encode(), "moisakeskus")[0]
    lat, lon = lest97_to_wgs84(*feature.point)
    assert lat == pytest.approx(59.5128, abs=5e-4)
    assert lon == pytest.approx(25.9561, abs=5e-4)


def test_projection_round_trip():
    for lat, lon in ((58.3801, 26.7224), (59.4372, 24.7453), (57.7769, 26.047)):
        x, y = wgs84_to_lest97(lat, lon)
        assert lest97_to_wgs84(x, y) == pytest.approx((lat, lon), abs=1e-9)


def test_axis_order_is_read_by_magnitude():
    assert lest97_pair(6598854.1, 610746.0) == (610746.0, 6598854.1)
    assert lest97_pair(610746.0, 6598854.1) == (610746.0, 6598854.1)


def test_degrees_labelled_as_lest97_stop_the_harvest():
    # Сервер подписывает ответ как EPSG:4326, не перепроецируя; а если однажды
    # начнёт перепроецировать — разбор должен остановиться, а не нарисовать
    # Эстонию у берегов Африки.
    with pytest.raises(MaaametError, match="L-EST97"):
        lest97_pair(58.39, 23.95)


# --- GML ------------------------------------------------------------------------

def test_point_feature_is_parsed_with_its_fields():
    feature = parse_gml(PALMSE.encode(), "moisakeskus")[0]
    assert feature.fid == "moisakeskus.2310"
    assert feature.get("NIMI") == "Palmse" and feature.get("SKS_NIMI") == "Palms"
    assert feature.get("ALIAS") is None          # пустой тег — пусто, а не ""
    assert feature.get("URL_MUINAS").endswith("action=view&id=15893")
    assert feature.point == (610746.0064, 6598854.112399)


def test_polygon_feature_is_parsed_in_metres():
    feature = parse_gml(RUHNU.encode(), "kihelkond_1917")[0]
    assert feature.get("NIMI") == "Ruhnu" and feature.get("KUBERMANG") == "Liivimaa"
    (rings,) = feature.polygons
    assert len(rings) == 1 and len(rings[0]) == 6
    assert rings[0][0] == (456792.533595, 6405886.218502)


def test_multisurface_with_hole_keeps_every_ring():
    data = HEAD + """<wfs:member><ms:kihelkond_1917 gml:id="k.1"><ms:msGeometry>
      <gml:MultiSurface srsName="urn:ogc:def:crs:EPSG::3301">
       <gml:surfaceMember><gml:Polygon>
        <gml:exterior><gml:LinearRing><gml:posList>6400000 500000 6400000 510000
          6410000 510000 6410000 500000 6400000 500000</gml:posList></gml:LinearRing></gml:exterior>
        <gml:interior><gml:LinearRing><gml:posList>6404000 504000 6404000 506000
          6406000 506000 6406000 504000 6404000 504000</gml:posList></gml:LinearRing></gml:interior>
       </gml:Polygon></gml:surfaceMember>
       <gml:surfaceMember><gml:Polygon>
        <gml:exterior><gml:LinearRing><gml:posList>6420000 500000 6420000 501000
          6421000 501000 6421000 500000 6420000 500000</gml:posList></gml:LinearRing></gml:exterior>
       </gml:Polygon></gml:surfaceMember>
      </gml:MultiSurface></ms:msGeometry><ms:NIMI>Proov</ms:NIMI></ms:kihelkond_1917>
    </wfs:member></wfs:FeatureCollection>"""
    feature = parse_gml(data.encode(), "kihelkond_1917")[0]
    assert [len(p) for p in feature.polygons] == [2, 1]
    assert polygon_area(feature.polygons[0]) == pytest.approx(1e8 - 4e6)


def test_service_exception_is_reported_as_source_error():
    report = ('<?xml version="1.0"?><ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">'
              '<ows:Exception><ows:ExceptionText>msWFSGetFeature(): typename invalid'
              '</ows:ExceptionText></ows:Exception></ows:ExceptionReport>')
    with pytest.raises(MaaametError, match="typename invalid"):
        parse_gml(report.encode(), "kihelkond_1917")


def test_capabilities_give_layer_titles():
    caps = ('<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"><wfs:FeatureTypeList>'
            '<wfs:FeatureType><wfs:Name>ms:kihelkond_1917</wfs:Name>'
            '<wfs:Title>Kihelkond kuni 1917</wfs:Title></wfs:FeatureType>'
            '</wfs:FeatureTypeList></wfs:WFS_Capabilities>')
    assert parse_capabilities(caps.encode()) == {"kihelkond_1917": PARISH_LAYER.title}


def test_layer_check_stops_on_a_different_count_or_missing_field():
    features = parse_gml(RUHNU.encode(), "kihelkond_1917")
    with pytest.raises(MaaametError, match="106"):
        check_layer(PARISH_LAYER, features)
    small = WfsLayer("kihelkond_1917", "x", 1, frozenset({"NIMI", "VALD"}), "polygon")
    with pytest.raises(MaaametError, match="VALD"):
        check_layer(small, features)
    check_layer(WfsLayer("kihelkond_1917", "x", 1, frozenset({"NIMI"}), "polygon"), features)


# --- геометрия ------------------------------------------------------------------

def test_point_on_surface_stays_inside_a_horseshoe():
    # Подкова: центр тяжести лежит в вырезе, вне фигуры.
    ring = [(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30), (0, 0)]
    x, y = point_on_surface([[ring]])
    assert Area("u", [[ring]], (0, 0, 30, 30)).contains(x, y)
    assert not (10 < x < 20 and y > 10)


def test_point_on_surface_takes_the_mainland_not_the_islet():
    big = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    islet = [(200, 200), (201, 200), (201, 201), (200, 201), (200, 200)]
    x, y = point_on_surface([[islet], [big]])
    assert 0 < x < 100 and 0 < y < 100


def test_geojson_geometry_is_lon_lat_and_closed():
    feature = parse_gml(RUHNU.encode(), "kihelkond_1917")[0]
    geometry = geojson_geometry(feature.polygons)
    ring = geometry["coordinates"][0]
    assert geometry["type"] == "Polygon" and ring[0] == ring[-1]
    lon, lat = ring[0]
    assert 23.0 < lon < 23.4 and 57.7 < lat < 57.9      # Рухну


def _square_feature(fid, name, x0, y0, size, **props):
    ring = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)]
    return Feature(fid=fid, props={"NIMI": name, **props}, polygons=[[ring]])


def test_parish_county_comes_from_the_1917_county_polygon():
    """У кирхшпилей Хийумаа в поле MAAKOND «Hiiu» — такого уезда до 1946 года не было."""
    parish = _square_feature("kihelkond_1917.1", "Käina", 420000, 6500000, 1000,
                             MAAKOND="Hiiu", KUBERMANG="Eestimaa")
    county = _square_feature("maakond_1917.0", "Lääne", 400000, 6480000, 50000,
                             KUBERMANG="Eestimaa")
    (result,) = build_parishes([parish], [county])
    assert result.county == "Lääne" and result.county_src == "Hiiu"
    assert result.uezd == COUNTY_UEZD["Lääne"] == "Гапсальский уезд"
    assert result.region == GOVERNORATES["Eestimaa"] == "Эстляндская губерния"
    props = parish_feature(result, registers=[{"fond": "EAA.1"}], manors=3)["properties"]
    assert props["county_src"] == "Hiiu" and props["manors"] == 3
    assert props["registers"] == [{"fond": "EAA.1"}]
    assert props["point"] == [result.lon, result.lat]


# --- мызы -----------------------------------------------------------------------

@pytest.mark.parametrize("note, expected", [
    ("teateid 1469", "1469"),
    ("Teateid 1436; aastast 1876 Landstelle", "1436"),
    ("rajatud 17. sajandil", "17 в."),
    ("rajatud 17. sajandi 1. poolel", "первая половина 17 в."),
    ("teateid 16. sajandi keskelt", "середина 16 в."),
    ("rajatud 16. sajandi lõpul - 17 sajandi algul", "конец 16 в. — начало 17 в."),
    ("rajatud 1426 ja 1497 vahel", "1426–1497"),
    ("Rajatud 1426. ja 1497. a vahel", "1426–1497"),
    ("rajatud 1840-ndail", "1840-е"),
    ("rajatud umbes 1700", "около 1700"),
    ("eraldatud Räpinast 1600 ja 1630 vahel", "1600–1630"),
    ("poolmõis, eraldatud Salajõest 1816", "1816"),
    ("Mõis loodi 1748 aastal, kui see eraldati Luke mõisast", "1748"),
])
def test_estonian_first_mention_is_said_in_russian(note, expected):
    assert estonian_period(note) == expected


@pytest.mark.parametrize("note", [
    "Eeru mõisa kinnistu liideti 1907",      # присоединение земель — не начало
    "Kammeri karjamõis; sama ka 1867 plaanil (EAA 3781-1-139)",
    "kuulus Padise mõisa koosseisu",
    "teateid 15S8",                          # опечатка в источнике — не угадываем
    None,
])
def test_notes_without_a_start_give_no_date(note):
    assert estonian_period(note) is None
    assert not manor_period(note).ok


def _areas_for(feature):
    x, y = feature.point
    parish = _square_feature("kihelkond_1917.9", "Kadrina", x - 500, y - 500, 1000)
    county = _square_feature("maakond_1917.3", "Viru", x - 5000, y - 5000, 10000)
    return [Area.of(parish)], [Area.of(county)]


def test_manor_record_has_a_measured_start_and_the_source_horizon_as_end():
    feature = parse_gml(PALMSE.encode(), "moisakeskus")[0]
    parishes, counties = _areas_for(feature)
    rec = manor_record(feature, parishes=parishes, counties=counties, lands=[])
    assert rec.layer == MANORS_EE.slug and rec.title == "Palmse (Palms)"
    assert (rec.year_from, rec.year_to) == (1510, LAYER_HORIZON)
    assert rec.date_precision == PRECISION_OPEN and rec.period_raw == "teateid 1510"
    assert rec.extra["year_to_from"].startswith("рамка слоя")
    assert rec.extra["first_mention"] == [1510, 1510]
    assert rec.category == "частная (рыцарская) мыза"
    assert rec.region == "Эстляндская губерния" and rec.district == "Везенбергский уезд"
    assert rec.extra["parish"] == "Kadrina" and "parish_mismatch" not in rec.extra
    assert rec.extra["moisaportaal"] == "http://mois.ee/viru/palmse.shtml"
    assert "featureID=moisakeskus.2310" in rec.url and rec.source_id == "moisakeskus.2310"
    assert rec.confidence == "ok"
    assert rec.lat == pytest.approx(59.512786, abs=1e-5)


def test_manor_without_note_takes_the_land_note_or_stays_undated():
    feature = parse_gml(PALMSE.encode(), "moisakeskus")[0]
    feature.props["MARKUS"] = None
    parishes, counties = _areas_for(feature)
    rec = manor_record(feature, parishes=parishes, counties=counties, lands=[])
    assert rec.confidence == "no_date" and rec.year_from is None
    x, y = feature.point
    land = _square_feature("moisamaad.7", "Palmse", x - 100, y - 100, 200,
                           MARKUS="Teateid 1510; majoraat")
    rec = manor_record(feature, parishes=parishes, counties=counties, lands=[Area.of(land)])
    assert rec.year_from == 1510 and rec.extra["note_from"] == "moisamaad"
    assert rec.extra["land_wfs_id"] == "moisamaad.7"


def test_layers_are_declared_for_the_registry():
    assert PARISH_BOUNDARIES_EE.gives_records is False
    assert PARISH_BOUNDARIES_EE.expected_rows == PARISH_LAYER.count == 106
    assert MANORS_EE.expected_rows == MANOR_LAYER.count == 2513
    for spec in (PARISH_BOUNDARIES_EE, MANORS_EE):
        assert spec.status == "harvested" and len(spec.description) > 40
        assert "Rahvusarhiiv" in spec.license and "ссылк" in spec.license


def test_hits_answer_gives_the_count_without_features():
    data = (HEAD.replace('numberMatched="1" numberReturned="1"',
                         'numberMatched="1232" numberReturned="0"') + "</wfs:FeatureCollection>")
    from histctx.sources.maaamet import parse_hits
    assert parse_hits(data.encode()) == 1232
    features = parse_gml(RUHNU.encode(), "kihelkond_1917")
    check_layer(WfsLayer("kihelkond_1917", "x", 1232, frozenset({"NIMI"}), "polygon"),
                features, matched=1232)


def test_manor_land_feature_keeps_names_and_note():
    from histctx.sources.maaamet import manor_land_feature
    land = _square_feature("moisamaad.7", "Palmse", 610000, 6598000, 2000, SKS_NIMI="Palms",
                           KIHELKOND="Kadrina", KUBERMANG="Eestimaa", MARKUS="Teateid 1510")
    feat = manor_land_feature(land)
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"] == {"name": "Palmse", "name_de": "Palms", "parish": "Kadrina",
                                  "governorate": "Eestimaa", "region": "Эстляндская губерния",
                                  "note": "Teateid 1510", "wfs_id": "moisamaad.7"}
