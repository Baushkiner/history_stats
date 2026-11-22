"""Разбор метаданных Russian Military Topographic Map Collection (Aardvark, OpenGeoMetadata).

Сети в тестах нет: записи листов — JSON-файлы репозитория `big-ten`, и
образцы собраны здесь же, с полями и написаниями листов коллекции 01d-03
(коммит ea9ebd9f от 18.11.2026).

Проверяется то, на чём слой держится: рамка листа и её центр, годы из
`gbl_dateRange_drsim` (и оценка у листов «n.d.»), масштаб, номенклатура во
всех встретившихся видах — кириллический двойник пояса, строчная буква,
литеры четвертей, имя в скобках, — грифы и штамп «Captured map», ссылки на
GeoTIFF и IIIF, отбор записей коллекции из папки.
"""

import json

import pytest

from histctx.registry import BY_SLUG, HARVESTED
from histctx.sources.topo_maps import (
    COLLECTION_DIR, TOPO_MAPS, TopoMapsError, centroid, doc_to_record, ensure_repo,
    envelope, marks, parse_title, read_collection, references, scale, scale_label, years,
)

RIGHTS = [
    "The maps in the Russian Military Topographic Map Collection are in the public domain.",
    "Rights Statement: http://rightsstatements.org/page/NoC-US/1.0/.",
]


def sheet(**over):
    doc = {
        "dct_title_s": "P-36-134-A Хиттолово (Khittolovo, Russia)",
        "dct_alternative_sm": ["Не подлежит оглашению"],
        "dct_description_sm": ["Modern area represented: Khittolovo, Leningrad oblast, "
                               "Russia; Scale =1:50,000; Не подлежит оглашению"],
        "dct_publisher_sm": ["Управление военных топографов"],
        "dct_temporal_sm": ["1895-1934"],
        "dct_issued_s": "1895",
        "gbl_indexYear_im": ["1895"],
        "gbl_dateRange_drsim": ["[1895 TO 1934]"],
        "dcat_bbox": "ENVELOPE(30.5,30.75,60.333,60.167)",
        "locn_geometry": "ENVELOPE(30.5,30.75,60.333,60.167)",
        "dcat_centroid": "60.25,30.625",
        "dct_isPartOf_sm": ["01d-00", "01d-03"],
        "dct_rights_sm": RIGHTS,
        "dct_references_s": json.dumps({
            "http://lccn.loc.gov/sh85035852": "https://iucat.iu.edu/catalog/5020131",
            "http://schema.org/url": "http://purl.dlib.indiana.edu/iudl/images/VAC9619/VAC9619-002945",
            "http://schema.org/downloadUrl": [
                {"url": "https://datacore.iu.edu/concern/data_sets/gx41mj60r", "label": "GeoTIFF"}],
            "http://iiif.io/api/presentation#manifest":
                "https://digitalcollections.iu.edu/concern/images/c821hw08f/manifest",
        }),
        "id": "VAC9619-002945",
        "dct_identifier_sm": ["http://purl.dlib.indiana.edu/iudl/images/VAC9619/VAC9619-002945",
                              "G7000 s50 .S68 sheet P-36-134-A"],
    }
    doc.update(over)
    return doc


def test_envelope_is_turned_into_a_geojson_bbox():
    assert envelope("ENVELOPE(30.5,30.75,60.333,60.167)") == (30.5, 60.167, 30.75, 60.333)
    assert envelope("ENVELOPE(32.500, 33.000, 63.000, 62.337)") == (32.5, 62.337, 33.0, 63.0)
    assert envelope("POLYGON((1 2,3 4))") is None
    assert envelope("ENVELOPE(30,31,95,60)") is None


def test_centroid_falls_back_to_the_middle_of_the_bbox():
    assert centroid(sheet()) == (60.25, 30.625)
    lat, lon = centroid(sheet(dcat_centroid=""))
    assert (round(lat, 3), round(lon, 3)) == (60.25, 30.625)
    assert centroid(sheet(dcat_centroid="", dcat_bbox="", locn_geometry="")) == (None, None)


def test_years_come_from_the_date_range():
    assert years(sheet()) == (1895, 1934, "1895-1934", False)
    one = sheet(dct_temporal_sm=["1935"], gbl_dateRange_drsim=["[1935 TO 1935]"])
    assert years(one) == (1935, 1935, "1935", False)
    nd = sheet(dct_issued_s="n.d.", dct_temporal_sm=["between 1880 and 1942"],
               gbl_dateRange_drsim=["[1880 TO 1942]"])
    assert years(nd) == (1880, 1942, "between 1880 and 1942", True)
    bare = sheet(dct_temporal_sm=["1903"], gbl_dateRange_drsim=[])
    assert years(bare)[:2] == (1903, 1903)
    assert years(sheet(dct_temporal_sm=[], dct_issued_s=None, gbl_dateRange_drsim=[]))[:2] == \
        (None, None)


def test_scale():
    assert scale(sheet()) == 50000 and scale_label(50000) == "1:50 000"
    assert scale(sheet(dct_description_sm=["Scale =1:100,000"])) == 100000
    assert scale(sheet(dct_description_sm=["Modern area represented: Estonia"])) is None


@pytest.mark.parametrize("title, nom, name, modern", [
    ("P-36-134-A Хиттолово (Khittolovo, Russia)", "P-36-134-A", "Хиттолово",
     "Khittolovo, Russia"),
    ("O-34-56-Б-Г Керузе (Estonia)", "O-34-56-Б-Г", "Керузе", "Estonia"),
    ("O-36-52-Б (Ryshevo, Russia)", "O-36-52-Б", None, "Ryshevo, Russia"),
    ("О-36-1-В Красное Село (Krasnoye Selo, Russia)", "O-36-1-В", "Красное Село",
     "Krasnoye Selo, Russia"),                                 # «О» кириллицей
    ("n-37-2-А-Б Воскресенск (Voskresensk, Russia)", "N-37-2-А-Б", "Воскресенск",
     "Voskresensk, Russia"),
    ("L-53-117 (Ключи) (Bay Jigit, Russia)", "L-53-117", "Ключи", "Bay Jigit, Russia"),
    ("N-34-66-Б-в Бартенштайн (Bartoszyce, Poland (North side of the city))", "N-34-66-Б-в",
     "Бартенштайн", "Bartoszyce, Poland (North side of the city)"),
    ("L-36-29,30,41,42 (Mykolayiv, Ukraine)", "L-36-29,30,41,42", None, "Mykolayiv, Ukraine"),
    ("N-37-93-В", "N-37-93-В", None, None),
])
def test_title_in_every_shape(title, nom, name, modern):
    assert parse_title(title) == (nom, name, modern)


def test_title_with_an_impossible_zone_is_kept_whole():
    assert parse_title("Т-36-2-Г Усвяты (Usvyata, Russia)") == \
        (None, "Т-36-2-Г Усвяты (Usvyata, Russia)", None)


def test_grifs_and_captured_stamp():
    assert marks(sheet(dct_alternative_sm=["Не подлежит оглашению; Captured map"])) == \
        (["Не подлежит оглашению"], True)
    assert marks(sheet(dct_alternative_sm=["Для cлужебного пользования"])) == \
        (["Для служебного пользования"], False)                # «c» латинская
    assert marks(sheet(dct_alternative_sm=[])) == ([], False)


def test_references():
    refs = references(sheet())
    assert refs["purl"].endswith("VAC9619-002945")
    assert refs["geotiff"] == "https://datacore.iu.edu/concern/data_sets/gx41mj60r"
    assert refs["iiif"].endswith("/manifest")
    assert references(sheet(dct_references_s="not json")) == {}


def test_sheet_record():
    rec = doc_to_record(sheet())
    assert rec.title == "Лист P-36-134-A «Хиттолово», 1:50 000, 1895–1934"
    assert rec.category == "1:50 000"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1895, 1934, "year")
    assert rec.period_raw == "1895-1934" and not rec.date_approx
    assert (rec.lat, rec.lon) == (60.25, 30.625)
    assert rec.confidence == "sheet_center"
    assert rec.extra["bbox"] == [30.5, 60.167, 30.75, 60.333]
    assert rec.extra["nomenclature"] == "P-36-134-A" and rec.extra["scale"] == 50000
    assert rec.extra["grif"] == ["Не подлежит оглашению"]
    assert rec.extra["call_number"] == "G7000 s50 .S68 sheet P-36-134-A"
    assert rec.actor == "Управление военных топографов"
    assert rec.url == "http://purl.dlib.indiana.edu/iudl/images/VAC9619/VAC9619-002945"
    assert "60,17–60,33° с. ш., 30,50–30,75° в. д." in rec.summary
    assert rec.place_text == "Khittolovo, Leningrad oblast, Russia"
    assert rec.source_id == "VAC9619-002945" and rec.layer == TOPO_MAPS.slug


def test_sheet_without_a_name_borrows_the_modern_place():
    rec = doc_to_record(sheet(dct_title_s="O-36-52-Б (Ryshevo, Russia)",
                              dct_temporal_sm=["1930"], gbl_dateRange_drsim=["[1930 TO 1930]"]))
    assert rec.title == "Лист O-36-52-Б «Ryshevo», 1:50 000, 1930"


def test_estimated_years_are_marked_approximate():
    rec = doc_to_record(sheet(dct_issued_s="n.d.", dct_temporal_sm=["between 1880 and 1942"],
                              gbl_dateRange_drsim=["[1880 TO 1942]"]))
    assert rec.date_approx and (rec.year_from, rec.year_to) == (1880, 1942)


def test_collection_is_picked_from_the_folder(tmp_path):
    folder = tmp_path / COLLECTION_DIR
    folder.mkdir(parents=True)
    (folder / "VAC9619-002945.json").write_text(json.dumps(sheet()), encoding="utf-8")
    (folder / "other.json").write_text(json.dumps(sheet(dct_isPartOf_sm=["01d-00"])),
                                       encoding="utf-8")
    docs = read_collection(tmp_path)
    assert [d["id"] for d in docs] == ["VAC9619-002945"]
    (folder / "VAC9619-002945.json").unlink()
    with pytest.raises(TopoMapsError):
        read_collection(tmp_path)


def test_existing_clone_is_used_as_is(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / COLLECTION_DIR).mkdir(parents=True)
    assert ensure_repo(tmp_path) == tmp_path
    broken = tmp_path / "broken"
    (broken / ".git").mkdir(parents=True)
    with pytest.raises(TopoMapsError, match=COLLECTION_DIR):
        ensure_repo(broken)


def test_layer_is_described_in_registry():
    spec = BY_SLUG["topo_maps"]
    assert spec is TOPO_MAPS and spec in HARVESTED
    assert spec.status == "harvested" and spec.expected_rows == 4132
    assert "общественное достояние" in spec.license and "не выяснены" in spec.license
