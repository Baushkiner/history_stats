"""Разбор ответа PastVu.

Сети до api.pastvu.com в тестах нет и быть не должно: проверяется разбор
ответа, а не сервис. Образец ответа собран по документации сервиса
(docs.pastvu.com/dev/api) — ровно поэтому здесь же проверяется, что при
несовпадении полей сбор падает с внятным сообщением, а не тихо выдаёт пусто.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources.pastvu import (  # noqa: E402
    PASTVU_PHOTOS, YEAR_MAX, PastVuError, bounds_param, check_photo_fields, grid,
    in_requested_bbox, photos_to_records,
)

# Образец ответа photo.getByBounds: поля по документации сервиса.
PHOTOS = [
    {"cid": 1, "file": "a/b/one.jpg", "title": "Никольская улица", "dir": "n",
     "geo": [55.7558, 37.6173], "year": 1900, "year2": 1900},
    {"cid": 2, "file": "a/b/two.jpg", "title": "Вид на Кремль",
     "geo": [55.7520, 37.6175], "year": 1890, "year2": 1910},
]


def test_photo_becomes_record():
    rec = photos_to_records(PHOTOS)[0]
    assert (rec.lat, rec.lon) == (55.7558, 37.6173)
    assert (rec.year_from, rec.year_to) == (1900, 1900)
    assert rec.title == "Никольская улица"
    assert rec.layer == PASTVU_PHOTOS.slug
    assert rec.source_id == "1"
    assert rec.url == "https://pastvu.com/p/1"
    assert rec.mappable and rec.usable


def test_image_is_not_linked_directly():
    """Права на снимки принадлежат авторам: прямой ссылки на файл слой не даёт."""
    for rec in photos_to_records(PHOTOS):
        assert rec.image_url is None
    assert photos_to_records(PHOTOS)[0].extra["file"] == "a/b/one.jpg"


def test_range_of_years_is_marked_approximate():
    rec = photos_to_records(PHOTOS)[1]
    assert (rec.year_from, rec.year_to) == (1890, 1910)
    assert rec.date_approx and rec.date_precision == "part"
    assert rec.period_raw == "1890–1910"


def test_reversed_years_are_put_in_order():
    rec = photos_to_records([{"cid": 9, "geo": [55.7, 37.6], "year": 1910, "year2": 1890}])[0]
    assert (rec.year_from, rec.year_to) == (1890, 1910)


def test_photo_without_year_is_skipped():
    """Снимок без датировки не подберётся ни к какому факту — он лишний."""
    assert photos_to_records([{"cid": 3, "geo": [55.7, 37.6]}]) == []


def test_photo_without_coordinates_is_skipped():
    assert photos_to_records([{"cid": 4, "geo": None, "year": 1900}]) == []
    assert photos_to_records([{"cid": 5, "geo": [0, 0], "year": 1900}]) == []


def test_photo_outside_russia_is_skipped():
    berlin = [{"cid": 6, "geo": [52.52, 13.40], "year": 1900}]
    assert photos_to_records(berlin) == []
    assert len(photos_to_records(berlin, require_bbox=False)) == 1


def test_later_photos_are_cut_by_year_max():
    late = [{"cid": 7, "geo": [55.7, 37.6], "year": 1975, "year2": 1980}]
    assert photos_to_records(late) == []
    spanning = [{"cid": 8, "geo": [55.7, 37.6], "year": 1950, "year2": 1990}]
    assert photos_to_records(spanning)[0].year_to == YEAR_MAX


def test_duplicates_by_cid_collapse():
    assert len(photos_to_records(PHOTOS + PHOTOS)) == 2


def test_missing_required_field_stops_the_harvest():
    """Сервис переименовал поле — это ошибка сбора, а не пустой слой."""
    with pytest.raises(PastVuError) as exc:
        check_photo_fields([{"cid": 1, "coords": [55.7, 37.6], "year": 1900}])
    assert "geo" in str(exc.value)


def test_empty_answer_is_not_an_error():
    check_photo_fields([])
    assert photos_to_records([]) == []


# --- нарезка территории ----------------------------------------------------

def test_grid_covers_the_whole_bbox():
    bbox = (55.0, 37.0, 56.0, 38.0)
    cells = list(grid(bbox, 0.5))
    assert len(cells) == 4
    assert min(c[0] for c in cells) == 55.0
    assert max(c[2] for c in cells) == 56.0
    assert max(c[3] for c in cells) == 38.0


def test_grid_does_not_run_past_the_edge():
    cells = list(grid((55.0, 37.0, 55.7, 37.7), 0.5))
    assert all(c[2] <= 55.7 and c[3] <= 37.7 for c in cells)


def test_grid_rejects_zero_step():
    with pytest.raises(ValueError):
        list(grid((55.0, 37.0, 56.0, 38.0), 0))


def test_bounds_are_sent_as_lon_lat():
    """Порядок осей — как в GeoJSON: сначала долгота. Перепутать легко."""
    assert bounds_param((55.0, 37.0, 56.0, 38.0)) == [[37.0, 55.0], [38.0, 56.0]]


def test_answer_is_filtered_by_requested_bbox():
    bbox = (55.0, 37.0, 56.0, 38.0)
    assert in_requested_bbox(55.5, 37.5, bbox)
    assert not in_requested_bbox(55.5, 39.0, bbox)


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    assert PASTVU_PHOTOS.slug in BY_SLUG
    assert "права" in BY_SLUG[PASTVU_PHOTOS.slug].license.lower()
