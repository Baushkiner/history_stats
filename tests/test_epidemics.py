"""Тесты подборки вспышек эпидемий.

Подборка ведётся вручную, и проверяется она как код: битая дата, болезнь вне
перечня или точка без указания, откуда взята координата, — ошибка сборки,
а не мелкая неточность в таблице.
"""

import json
from collections import Counter

import pytest

from histctx.adapters.epidemics import (
    DEFAULT_PATH, DISEASES, EPIDEMICS, YEAR_MAX, YEAR_MIN, DatasetError, format_count,
    load_epidemics,
)
from histctx.geo import in_bbox
from histctx.registry import BY_SLUG, CURATED
from histctx.schema import SCOPE_POINT, SCOPE_REGION

RECORDS = load_epidemics()
PAYLOAD = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))


# --- целостность подборки -------------------------------------------------

def test_layer_is_registered_as_curated():
    assert BY_SLUG["epidemics"] is EPIDEMICS
    assert EPIDEMICS in CURATED
    # Запрос Викиданных живёт на своём slug и выгрузку подборки не затирает.
    assert BY_SLUG["epidemics_wd"].status == "harvested"


def test_layer_is_actually_filled():
    """Слой эпидемий долго стоял с одной записью; пустым он не вернётся."""
    assert len(RECORDS) >= 200
    mapped = [r for r in RECORDS if r.has_point]
    assert len(mapped) >= 150


def test_every_record_is_dated_inside_the_frame():
    for rec in RECORDS:
        assert rec.has_time, rec.title
        assert YEAR_MIN <= rec.year_from <= rec.year_to <= YEAR_MAX, rec.title


def test_every_record_can_be_checked():
    """Каждая вспышка ведёт на страницу, где её можно проверить."""
    for rec in RECORDS:
        assert rec.url and rec.url.startswith("https://"), rec.title
        assert rec.source, rec.title
        assert rec.license, rec.title


def test_diseases_come_from_the_closed_list():
    assert set(PAYLOAD["diseases"]) == set(DISEASES)
    for rec in RECORDS:
        assert rec.category in DISEASES, rec.title
        assert rec.extra["disease"] == rec.category


def test_points_say_where_the_coordinate_comes_from():
    """Координата — у населённого пункта, а не у очага, и это видно в записи."""
    for rec in RECORDS:
        if rec.has_point:
            assert rec.extra.get("coord_source"), rec.title
            assert rec.confidence == "place_level", rec.title
            assert in_bbox(rec.lat, rec.lon), rec.title


def test_unlocated_points_are_kept_and_marked():
    """Разъезд или хутор, которого нет на нынешней карте, не выбрасывается."""
    unlocated = [r for r in RECORDS if r.scope == SCOPE_POINT and not r.has_point]
    assert unlocated
    assert all(r.confidence == "no_coords" for r in unlocated)


def test_region_records_name_their_provinces():
    regional = [r for r in RECORDS if r.scope == SCOPE_REGION]
    assert regional
    for rec in regional:
        assert rec.regions and not rec.has_point, rec.title
        assert len(rec.regions) == len(set(rec.regions)), rec.title


def test_ids_and_uids_are_unique():
    ids = Counter(r.source_id for r in RECORDS)
    assert not [k for k, n in ids.items() if n > 1]
    uids = Counter(r.uid for r in RECORDS)
    assert not [k for k, n in uids.items() if n > 1]


def test_counts_are_written_into_the_summary():
    """Число умерших видно и в описании, а не только в служебном поле."""
    for rec in RECORDS:
        deaths = rec.extra.get("deaths")
        if deaths is not None:
            assert f"мерло {format_count(deaths)}." in rec.summary, rec.title


# --- проверки при чтении --------------------------------------------------

def test_large_counts_are_grouped_like_russian_text():
    assert format_count(9999) == "9999"
    assert format_count(10000) == "10 000"
    assert format_count(128000) == "128 000"


def _broken(tmp_path, **changes):
    payload = json.loads(json.dumps(PAYLOAD))
    payload["outbreaks"] = [dict(payload["outbreaks"][0], **changes)]
    for key, value in list(payload["outbreaks"][0].items()):
        if value is None:
            del payload["outbreaks"][0][key]
    path = tmp_path / "epidemics.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("changes, message", [
    ({"disease": "лихорадка"}, "неизвестная болезнь"),
    ({"years": [1850, 1840]}, "начало позже конца"),
    ({"years": [1500, 1501]}, "вне периода"),
    ({"source": "неизвестно"}, "не описан в sources"),
    ({"coord_source": None, "lat": 55.0, "lon": 37.0}, "откуда взята координата"),
    ({"deaths": -3}, "целым неотрицательным"),
    ({"precision": "почти"}, "точность даты"),
])
def test_broken_record_is_rejected(tmp_path, changes, message):
    with pytest.raises(DatasetError, match=message):
        load_epidemics(_broken(tmp_path, **changes))


def test_region_record_without_province_is_rejected(tmp_path):
    path = _broken(tmp_path, scope="region", regions=[], region=None,
                   lat=None, lon=None, coord_source=None)
    with pytest.raises(DatasetError, match="не названа губерния"):
        load_epidemics(path)


def test_point_outside_the_frame_is_kept_and_marked(tmp_path):
    rec, = load_epidemics(_broken(tmp_path, lat=48.85, lon=2.35, coord_source="проба"))
    assert rec.confidence == "outside_bbox"
