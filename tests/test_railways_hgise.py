"""Железные дороги HGISE: проекция, окна открытия и отбор по рамке. Сети в тестах нет."""

import pytest

from histctx.sources.railways_hgise import (
    RAILWAYS_HGISE, RailwaysError, laea_to_lonlat, period_text, segment_feature, segments,
    states, window,
)


def test_laea_inverse_matches_the_epsg_example():
    # IOGP, Guidance Note 7-2: 50° с. ш., 5° в. д. → E 3962799,45, N 2999718,85.
    lon, lat = laea_to_lonlat(3962799.45, 2999718.85)
    assert lon == pytest.approx(5.0, abs=1e-6) and lat == pytest.approx(50.0, abs=1e-6)
    assert laea_to_lonlat(4321000.0, 3210000.0) == (10.0, 52.0)


def _present(**codes):
    st = states({f"TYPE_{y}": codes.get(f"y{y}", "NE")
                 for y in (1850, 1890, 1930, 1970, 2000, 2010)})
    return {y: c != "NE" for y, c in st.items()}


def test_opening_is_a_window_between_snapshots_not_a_year():
    present = _present(y1890="ML", y1930="ML", y1970="ML")
    assert window(present, opening=True) == (1851, 1890)
    assert window(present, opening=False) == (1971, 2000)
    assert period_text((1851, 1890), "открыта") == "открыта между 1851 и 1890 годами"
    early = _present(y1850="ML", y1890="ML", y1930="ML", y1970="ML", y2000="ML", y2010="ML")
    assert window(early, opening=True) == (None, 1850)
    assert window(early, opening=False) is None
    assert period_text((None, 1850), "открыта") == "открыта не позже 1850 года"
    assert window(_present(), opening=True) is None


def _feature(**codes):
    # Отрезок около Вильны в EPSG:3035 (две точки) и состояния по срезам.
    props = {f"TYPE_{y}": codes.get(f"y{y}", "NE") for y in (1850, 1890, 1930, 1970, 2000,
                                                             2010)}
    props["Length_km"] = 12.345
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "MultiLineString",
                         "coordinates": [[[5309000.0, 3620000.0], [5312000.0, 3625000.0],
                                          [5316000.0, 3628000.0]]]}}


def inside(lat, lon):
    return (20 <= lon <= 180, "Виленская губерния" if lon > 25 else None, False)


def test_segment_in_frame_becomes_a_line_with_states():
    feat = segment_feature(_feature(y1890="ML", y1930="SL", y1970="ML", y2000="ML",
                                    y2010="ML"), inside)
    props = feat["properties"]
    assert feat["geometry"]["type"] == "LineString"
    lon, lat = feat["geometry"]["coordinates"][0]
    assert 25 < lon < 26 and 54 < lat < 55
    assert props["opened"] == "открыта между 1851 и 1890 годами"
    assert (props["opened_from"], props["opened_to"]) == (1851, 1890)
    assert "closed" not in props and props["state_1930"] == "SL"
    assert props["type"] == "основная линия" and props["region"] == "Виленская губерния"
    assert props["length_km"] == 12.35


def test_segments_outside_frame_or_after_1970_are_dropped():
    assert segment_feature(_feature(y1890="ML"), lambda lat, lon: (False, None, False)) is None
    assert segment_feature(_feature(y2000="ML", y2010="ML"), inside) is None
    assert len(segments([_feature(y1890="ML"), _feature()], inside)) == 1
    with pytest.raises(RailwaysError):
        segment_feature({"properties": {"TYPE_1890": "ML"},
                         "geometry": {"type": "Point", "coordinates": [0, 0]}}, inside)


def test_layer_is_an_underlay_with_rights_in_words():
    assert not RAILWAYS_HGISE.gives_records and RAILWAYS_HGISE.status == "harvested"
    assert "Springer" in RAILWAYS_HGISE.license and "24.11.2026" in RAILWAYS_HGISE.license
