"""Разбор набора Cliopatria: границы государств 1600–1885 годов.

Сети в тестах нет. Набор — GeoJSON во вложенном zip, поэтому образец
собирается здесь же, в том виде, в каком его отдаёт Zenodo.

Проверяется то, на чём сбор держится: сверка перечня архива с размером и
CRC32 из кода, отбор строк по рамке лет и по охвату РИ/СССР, передача
границы CShapes с 1886 года без обрезки годов и ссылки, по которым запись
проверяется.
"""

import json
import zipfile
import zlib
from io import BytesIO

import pytest

from histctx.registry import BY_SLUG
from histctx.sources import cliopatria
from histctx.sources.cliopatria import (
    MEMBER, MEMBER_CRC, MEMBER_SIZE, NAMES_RU, STATE_BORDERS_EARLY, CliopatriaError,
    boundary, check_fields, check_listing, collection, overlaps, read_member,
    rounded_geometry, select, states, untranslated,
)

# Квадрат в охвате РИ/СССР (`geo.BBOX_RU`) и квадрат в Южной Америке.
IN_FRAME = [[30.0, 50.0], [40.0, 50.0], [40.0, 60.0], [30.0, 60.0], [30.0, 50.0]]
OUT_OF_FRAME = [[-50.0, -20.0], [-40.0, -20.0], [-40.0, -10.0], [-50.0, -10.0],
                [-50.0, -20.0]]


def row(name, start, end, ring=IN_FRAME, **extra):
    props = {"Name": name, "FromYear": start, "ToYear": end, "Area": 1234.6,
             "Type": "POLITY", "Wikipedia": "Russian Empire", "Wikidata": "Q34266",
             "SeshatID": "", "Components": "", "MemberOf": ""}
    props.update(extra)
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


# Пять строк: московская до рамки, две в рамке (последняя заходит за 1885 год),
# бразильская вне охвата и объединение в скобках со своим составом.
ROWS = [
    row("Tsardom of Russia", 1550, 1599, Wikidata="Q186096"),
    row("Tsardom of Russia", 1600, 1601, Wikidata="Q186096"),
    row("Russian Empire", 1885, 1894),
    row("Empire of Brazil", 1822, 1889, ring=OUT_OF_FRAME, Wikidata="Q217230"),
    row("(Habsburg Monarchy)", 1600, 1618, Components="Habsburg Monarchy",
        Wikipedia="Habsburg monarchy", Wikidata="Q66504140", SeshatID="at_habsburg_1"),
]


def build_member(tmp_path, feats=None, name="cliopatria_polities_only_v021.geojson"):
    path = tmp_path / "cliopatria.geojson.zip"
    data = {"type": "FeatureCollection", "features": ROWS if feats is None else feats}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, json.dumps(data))
    return path


def test_member_is_read_into_features(tmp_path):
    feats = read_member(build_member(tmp_path))
    assert len(feats) == 5
    assert feats[1]["properties"]["Name"] == "Tsardom of Russia"


def test_redesigned_dataset_stops_the_harvest(tmp_path):
    """Переделают набор — сбор падает с внятным сообщением, а не выдаёт пусто."""
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(CliopatriaError, match="zip"):
        read_member(bad)
    with pytest.raises(CliopatriaError, match="один .geojson"):
        read_member(build_member(tmp_path, name="readme.txt"))
    with pytest.raises(CliopatriaError, match="ни одной строки"):
        read_member(build_member(tmp_path, feats=[]))
    with pytest.raises(CliopatriaError, match="FromYear"):
        check_fields([{"properties": {"Name": "Russian Empire"}}])


def test_listing_is_checked_against_the_code():
    good = {"entries": [{"key": MEMBER, "size": MEMBER_SIZE, "crc": MEMBER_CRC}]}
    assert check_listing(good) == []
    changed = {"entries": [{"key": MEMBER, "size": MEMBER_SIZE + 1, "crc": 1}]}
    problems = check_listing(changed)
    assert len(problems) == 2 and "размер" in problems[0] and "CRC32" in problems[1]
    moved = {"entries": [{"key": "other/cliopatria.geojson.zip"}]}
    assert "other/cliopatria.geojson.zip" in check_listing(moved)[0]


def test_download_keeps_nothing_that_does_not_match(tmp_path, monkeypatch):
    """Оборванный или подменённый файл не должен лечь в кэш."""
    payload = b"x" * 10

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cliopatria.urllib.request, "urlopen",
                        lambda *a, **k: Response(payload))
    dest = tmp_path / "member.zip"
    with pytest.raises(CliopatriaError, match="ожидалось"):
        cliopatria.download(dest)
    assert not dest.exists() and not dest.with_suffix(".zip.part").exists()

    monkeypatch.setattr(cliopatria, "MEMBER_SIZE", len(payload))
    monkeypatch.setattr(cliopatria, "MEMBER_CRC", zlib.crc32(payload))
    assert cliopatria.download(dest).read_bytes() == payload


def test_row_is_matched_against_the_layer_window():
    assert overlaps({"FromYear": 1600, "ToYear": 1601})
    assert overlaps({"FromYear": 1429, "ToYear": 1771})     # началась до рамки
    assert overlaps({"FromYear": 1885, "ToYear": 1894})     # кончилась после
    assert not overlaps({"FromYear": 1550, "ToYear": 1599})
    assert not overlaps({"FromYear": 1886, "ToYear": 1894})  # это уже CShapes
    assert not overlaps({"FromYear": "1600", "ToYear": 1601})


def test_polity_outside_the_frame_is_dropped(tmp_path):
    picked = select(read_member(build_member(tmp_path)))
    assert states(picked) == ["(Габсбургская монархия)", "Российская империя",
                              "Русское царство"]
    assert len(select(read_member(build_member(tmp_path)), region_only=False)) == 4


def test_years_are_kept_and_the_handover_is_marked():
    """Годы набора не обрезаются: пометка говорит, где граница дальше."""
    props = boundary(ROWS[2])["properties"]
    assert (props["year_from"], props["year_to"]) == (1885, 1894)
    assert props["continues_in"] == "state_borders"
    assert "continues_in" not in boundary(ROWS[1])["properties"]


def test_row_points_at_what_it_was_taken_from():
    props = boundary(ROWS[4])["properties"]
    assert props["wikidata"] == "https://www.wikidata.org/wiki/Q66504140"
    assert props["wikipedia"] == "https://en.wikipedia.org/wiki/Habsburg_monarchy"
    assert props["components"] == ["Habsburg Monarchy"]
    assert props["seshat_id"] == ["at_habsburg_1"]
    assert props["kind"] == "polity" and props["area_km2"] == 1235
    # Пустые поля в файл не идут.
    assert "member_of" not in props


def test_relation_rows_are_kept_and_labelled():
    rel = row("(Alliance between Papal States and Spanish Empire)", 1600, 1601,
              Type="RELATION")
    props = boundary(rel)["properties"]
    assert props["kind"] == "relation"
    assert props["state"] == "(Союз Папской области и Испанской империи)"


def test_unknown_name_goes_as_is():
    props = boundary(row("Empire of Brazil", 1822, 1889))["properties"]
    assert props["state"] == props["state_en"] == "Empire of Brazil"
    assert untranslated([{"properties": props}]) == ["Empire of Brazil"]


def test_coordinates_are_rounded_without_losing_rings():
    geom = {"type": "MultiPolygon", "coordinates": [[[
        [30.00012, 50.00049], [30.00014, 50.00051], [40.0004, 50.0], [40.0, 60.0],
        [30.00012, 50.00049]]]]}
    ring = rounded_geometry(geom)["coordinates"][0][0]
    assert ring == [[30.0, 50.0], [30.0, 50.001], [40.0, 50.0], [40.0, 60.0],
                    [30.0, 50.0]]
    # Кольцо, которое округление схлопнуло бы, остаётся как было.
    tiny = {"type": "Polygon", "coordinates": [[[30.0001, 50.0001], [30.0002, 50.0001],
                                                [30.0002, 50.0002], [30.0001, 50.0001]]]}
    assert rounded_geometry(tiny) == tiny


def test_collection_carries_rights_and_citation(tmp_path):
    coll = collection(select(read_member(build_member(tmp_path))))
    assert coll["name"] == "state_borders_early"
    assert coll["period"] == "1600–1885" and coll["continues_in"] == "state_borders"
    assert "CC BY 4.0" in coll["license"] and "CC BY 4.0" in coll["citation"]
    assert coll["url"].startswith("https://doi.org/10.5281/zenodo.")


def test_layer_is_registered_as_a_basemap():
    assert BY_SLUG["state_borders_early"] is STATE_BORDERS_EARLY
    assert STATE_BORDERS_EARLY.gives_records is False
    assert STATE_BORDERS_EARLY.status == "harvested"


def test_dictionary_has_no_untranslated_duplicates():
    """Ключ словаря — английское название набора, значение — русское."""
    for en, ru in NAMES_RU.items():
        assert ru and ru != en, en
