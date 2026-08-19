"""Слой границ RISTAT: описание, лицензия и оформление выгрузки.

Сети здесь нет и качать ничего не надо: разбор GeoPackage проверяется
в `test_geopackage.py`, а тут — то, что выгрузка уносит с собой права
и ссылку на источник.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources.ristat import (  # noqa: E402
    CITATION, DISTRICTS, FILES, PROVINCES, RISTAT_BOUNDARIES, collection, named,
)

FEATS = [
    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[26.8, 64.5]]]},
     "properties": {"Name_RU": "Кемский", "prov_RU": "Архангельская губерния"}},
    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[40.5, 64.5]]]},
     "properties": {"Name_ENG": "Onega"}},
]


def test_collection_carries_the_licence_and_the_source():
    out = collection(FEATS, DISTRICTS)
    assert out["type"] == "FeatureCollection"
    assert out["name"] == "districts_1897"
    assert "CC0" in out["license"]
    assert "ristat.org" in out["citation"]
    assert out["url"].startswith("https://datasets.iisg.amsterdam/")
    assert len(out["features"]) == 2


def test_unnamed_units_are_counted_not_hidden():
    """Полигон без русского названия остаётся в файле, но виден в отчёте."""
    assert named(FEATS, DISTRICTS) == 1
    assert len(collection(FEATS, DISTRICTS)["features"]) == 2


def test_both_files_of_the_set_are_described():
    assert [b.key for b in FILES] == ["provinces_1897", "districts_1897"]
    assert PROVINCES.name_field == "prov_RU" and DISTRICTS.name_field == "Name_RU"
    assert {b.file_id for b in FILES} == {10335, 10336}


def test_citation_names_the_authors():
    assert "Kessler" in CITATION and "Markevich" in CITATION


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    spec = BY_SLUG[RISTAT_BOUNDARIES.slug]
    assert spec.status == "harvested"
    assert "CC0" in spec.license
    assert "уезд" in spec.description
