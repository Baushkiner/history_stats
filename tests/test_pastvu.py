"""Разбор ответа PastVu.

Сети до api.pastvu.com в тестах нет и быть не должно: проверяется разбор
ответа, а не сервис. Образец ниже снят с живого ответа `photo.getByBounds`
23 августа 2026 года — рамка у Иверских ворот в Москве, 649 снимков, взяты
три: с диапазоном лет, с точным годом и без поля `dir`. Записи приведены как
есть, включая служебное `__v` и подпись `?s=` в пути к файлу.

Заодно здесь проверяется, что при несовпадении полей сбор падает с внятным
сообщением, а не тихо выдаёт пусто.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources.pastvu import (  # noqa: E402
    PASTVU_PHOTOS, YEAR_MAX, PastVuClient, PastVuError, bounds_param,
    check_photo_fields, grid, in_requested_bbox, photos_to_records,
)

# Образец ответа photo.getByBounds — снят с живого сервиса, не с документации.
PHOTOS = [
    {"cid": 1772024, "__v": 0, "dir": "s",
     "file": "c/t/6/ct6ychhyzsw9kr8hfk.jpg?s=f1ef063c69",
     "geo": [55.755945, 37.617868], "title": "Иверские ворота",
     "year": 1893, "year2": 1896},
    {"cid": 7885, "geo": [55.755919, 37.61781],
     "file": "f/c/7/fc72b4e28db2355066283d0560158ede.jpg", "dir": "s",
     "title": "Воскресенские ворота", "year": 1929, "year2": 1929},
    {"cid": 1223424, "__v": 0, "geo": [55.755598, 37.617564],
     "file": "v/y/q/vyqy3gav0c6brt5adh.jpg",
     "title": "Исторический музей. Хранение группы металлов. Стеллаж с медной утварью",
     "year": 1938, "year2": 1938},
]


def test_photo_becomes_record():
    rec = photos_to_records(PHOTOS)[1]
    assert (rec.lat, rec.lon) == (55.755919, 37.61781)
    assert (rec.year_from, rec.year_to) == (1929, 1929)
    assert rec.title == "Воскресенские ворота"
    assert rec.layer == PASTVU_PHOTOS.slug
    assert rec.source_id == "7885"
    assert rec.url == "https://pastvu.com/p/7885"
    assert rec.date_precision == "year" and not rec.date_approx
    assert rec.mappable and rec.usable


def test_image_is_not_linked_directly():
    """Права на снимки принадлежат авторам: прямой ссылки на файл слой не даёт."""
    for rec in photos_to_records(PHOTOS):
        assert rec.image_url is None
    # Путь к файлу сохраняется как есть, вместе с подписью `?s=`: по нему
    # снимок можно найти, если условия когда-нибудь выяснятся.
    assert photos_to_records(PHOTOS)[0].extra["file"] == \
        "c/t/6/ct6ychhyzsw9kr8hfk.jpg?s=f1ef063c69"


def test_range_of_years_is_marked_approximate():
    """Интервал у снимка назван автором: точность — год, приблизительность —
    в `date_approx`. «Часть века» здесь была неправдой: 1893–1896 не половина
    столетия, а четыре названных года."""
    rec = photos_to_records(PHOTOS)[0]
    assert (rec.year_from, rec.year_to) == (1893, 1896)
    assert rec.date_approx and rec.date_precision == "year"
    assert rec.period_raw == "1893–1896"


def test_reversed_years_are_put_in_order():
    rec = photos_to_records([{"cid": 9, "geo": [55.7, 37.6], "year": 1910, "year2": 1890}])[0]
    assert (rec.year_from, rec.year_to) == (1890, 1910)


def test_photo_without_year_is_skipped():
    """Снимок без датировки не подберётся ни к какому факту — он лишний."""
    photos = PHOTOS + [{"cid": 3, "geo": [55.7, 37.6], "file": "x/y/z.jpg", "title": "Без года"}]
    assert [rec.source_id for rec in photos_to_records(photos)] == \
        [str(p["cid"]) for p in PHOTOS]


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
    assert len(photos_to_records(PHOTOS + PHOTOS)) == len(PHOTOS)


def test_missing_required_field_stops_the_harvest():
    """Сервис переименовал поле — это ошибка сбора, а не пустой слой."""
    with pytest.raises(PastVuError) as exc:
        check_photo_fields([{"cid": 1, "coords": [55.7, 37.6], "year": 1900}])
    assert "geo" in str(exc.value)


def test_year_is_required_too():
    """Без датировки слой бесполезен целиком: пропажу `year` надо заметить сразу."""
    with pytest.raises(PastVuError) as exc:
        check_photo_fields([{"cid": 1, "geo": [55.7, 37.6], "date": "1900"}])
    assert "year" in str(exc.value)


def test_field_missing_in_one_photo_is_not_an_error():
    """У отдельного снимка поля может не быть; проверяется вся выборка."""
    check_photo_fields([{"cid": 1, "geo": [55.7, 37.6]}] + PHOTOS)


def test_empty_answer_is_not_an_error():
    check_photo_fields([])
    assert photos_to_records([]) == []


# --- разговор с сервисом ---------------------------------------------------

def test_clusters_instead_of_photos_stop_the_harvest():
    """На мелком зуме сервис отдаёт кластеры: собрать их нельзя, молчать нельзя."""
    client = PastVuClient()
    client.call = lambda method, params: {"z": 12, "photos": [],
                                          "clusters": [{"c": 500}, {"c": 12}]}
    with pytest.raises(PastVuError) as exc:
        client.photos_in_bbox((55.0, 37.0, 56.0, 38.0))
    assert "кластер" in str(exc.value).lower()


def test_service_error_is_shown_as_it_came():
    """Ошибку сервис отдаёт телом, а не кодом HTTP: показываем его сообщение."""
    client = PastVuClient()
    client._request = lambda url: {"type": "ApplicationError",
                                   "code": "UNHANDLED_ERROR",
                                   "message": "A server error occurred"}
    with pytest.raises(PastVuError) as exc:
        client.call("photo.getByBounds", {})
    assert "A server error occurred" in str(exc.value)


def test_count_adds_up_cluster_counters():
    """Объём считается по счётчикам кластеров — без выгрузки самих снимков."""
    client = PastVuClient()
    client.call = lambda method, params: {"z": 6, "clusters": [{"c": 100}, {"c": 7}]}
    assert client.count_in_bbox((55.0, 37.0, 56.0, 38.0)) == 107


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


def test_bounds_are_sent_lat_first():
    """Порядок осей — «широта, долгота»: проверено на живом сервисе."""
    assert bounds_param((55.0, 37.0, 56.0, 38.0)) == [[55.0, 37.0], [56.0, 38.0]]


def test_bounds_do_not_touch_the_antimeridian():
    """Рамка, упирающаяся в 180-й меридиан, валит сервис — отступаем от края."""
    (_, west), (_, east) = bounds_param((60.0, -180.0, 72.0, 180.0))
    assert -180.0 < west < -179.999
    assert 179.999 < east < 180.0


def test_answer_is_filtered_by_requested_bbox():
    bbox = (55.0, 37.0, 56.0, 38.0)
    assert in_requested_bbox(55.5, 37.5, bbox)
    assert not in_requested_bbox(55.5, 39.0, bbox)


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    assert PASTVU_PHOTOS.slug in BY_SLUG
    assert "права" in BY_SLUG[PASTVU_PHOTOS.slug].license.lower()


# --- журнал обхода ---------------------------------------------------------
# Обход всей страны — часы и сотни тысяч записей. Всё, что ниже, проверяет
# одно: собранное не теряется и не подменяется молча.

def _harvest_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "harvest_pastvu_mod", ROOT / "scripts" / "harvest_pastvu.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _journal(tmp_path, **kw):
    mod = _harvest_module()
    head = {"bboxes": [(55.0, 37.0, 56.0, 38.0)], "step": 1.0,
            "year_to": YEAR_MAX, "cells": 1}
    head.update(kw)
    return mod, mod.Journal(tmp_path, **head)


def test_journal_returns_the_same_records(tmp_path):
    """Запись, прошедшая через журнал, не меняется: то же место, годы, extra."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.write(photos_to_records(PHOTOS))
    journal.close()

    back = list(journal.records())
    same = photos_to_records(PHOTOS)
    assert [r.uid for r in back] == [r.uid for r in same]
    assert [(r.lat, r.lon, r.year_from, r.year_to) for r in back] == \
        [(r.lat, r.lon, r.year_from, r.year_to) for r in same]
    assert back[0].extra == same[0].extra
    assert all(r.image_url is None for r in back)


def test_journal_drops_a_torn_tail(tmp_path):
    """Процесс убили на полуслове: хвост отбрасывается, остальное цело."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.write(photos_to_records(PHOTOS))
    journal.close()
    with journal.rows_path.open("a", encoding="utf-8") as fh:
        fh.write('{"uid": "photos_pastvu:oborv')

    seen, kept = journal.repair()
    assert kept == len(PHOTOS)
    assert len(list(journal.records())) == len(PHOTOS)


def test_journal_does_not_cut_records_after_a_broken_line(tmp_path):
    """Испорчена строка в середине — чинить вслепую нельзя, там дальше собранное."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.write(photos_to_records(PHOTOS))
    journal.close()
    lines = journal.rows_path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = "{битая строка\n"
    journal.rows_path.write_text("".join(lines), encoding="utf-8")

    with pytest.raises(SystemExit):
        journal.repair()
    kept_lines = journal.rows_path.read_text(encoding="utf-8").splitlines(keepends=True)
    assert kept_lines == lines


def test_journal_refuses_to_start_over_silently(tmp_path):
    """Незаконченный обход мог стоить суток — молча поверх него не пишут."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.write(photos_to_records(PHOTOS))
    journal.close()

    _, again = _journal(tmp_path)
    with pytest.raises(SystemExit) as exc:
        again.open(resume=False, restart=False)
    assert "--resume" in str(exc.value)


def test_journal_refuses_to_continue_another_walk(tmp_path):
    """Другой шаг или другая рамка — другой обход: продолжение дало бы дыры."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.mark((55.0, 37.0, 56.0, 38.0))
    journal.close()

    _, other = _journal(tmp_path, step=0.5)
    with pytest.raises(SystemExit) as exc:
        other.open(resume=True, restart=False)
    assert "дыр" in str(exc.value)


def test_finished_walk_is_not_repeated_by_accident(tmp_path):
    """Законченный обход отличается от прерванного: иначе выдадим вчерашнее за сегодняшнее."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.mark((55.0, 37.0, 56.0, 38.0))
    journal.close()
    journal.mark_finished()

    _, again = _journal(tmp_path)
    with pytest.raises(SystemExit) as exc:
        again.open(resume=True, restart=False)
    assert "--restart" in str(exc.value)


def test_restart_puts_the_old_journal_aside(tmp_path):
    """Ничего не удаляется молча: прошлый журнал переименовывается, а не стирается."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.write(photos_to_records(PHOTOS))
    journal.close()

    _, again = _journal(tmp_path)
    done, seen, kept = again.open(resume=False, restart=True)
    again.close()
    assert (done, seen, kept) == (set(), set(), 0)
    assert list(tmp_path.glob("*.jsonl.*"))


def test_journal_header_is_written_once(tmp_path):
    """Обрыв на первой клетке не должен добавлять второй заголовок."""
    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.close()

    _, again = _journal(tmp_path)
    done, _, _ = again.open(resume=True, restart=False)
    again.close()
    assert done == set()
    assert len(journal.cells_path.read_text(encoding="utf-8").splitlines()) == 1


def test_layer_properties_are_hoisted_out_of_features(tmp_path):
    """Права и название слоя — один раз на слой, а не у каждой из сотен тысяч точек."""
    import json

    mod, journal = _journal(tmp_path)
    journal.open(resume=False, restart=False)
    journal.write(photos_to_records(PHOTOS))
    journal.close()

    path = tmp_path / "layer.geojson"
    n = mod._write_geojson_stream(journal.records, path, layer_title=PASTVU_PHOTOS.title)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert n == len(payload["features"]) == len(PHOTOS)
    assert payload["layer"]["license"] == PASTVU_PHOTOS.license
    assert payload["layer"]["source"] == PASTVU_PHOTOS.source
    assert "license" not in payload["features"][0]["properties"]
    assert payload["features"][0]["properties"]["url"].startswith("https://pastvu.com/p/")
