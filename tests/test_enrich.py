"""Тесты подбора контекста и вспомогательной географии."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histctx.enrich import ContextEngine, Fact, _year_gap  # noqa: E402
from histctx.geo import extract_district, extract_region, haversine_km, in_bbox, valid_coords  # noqa: E402
from histctx.normalize import (  # noqa: E402
    looks_like_military_unit, looks_like_person, normalize_genre, normalize_war, years_from_title,
)
from histctx.schema import ContextRecord  # noqa: E402


def rec(**kw) -> ContextRecord:
    base = dict(layer="test", layer_title="Тест", title="Запись", lat=55.0, lon=37.0,
                year_from=1900, year_to=1900, source="test")
    base.update(kw)
    return ContextRecord(**base)


# --- разрыв во времени ---------------------------------------------------

def test_year_gap_overlap_is_zero():
    assert _year_gap(rec(year_from=1890, year_to=1910), (1900, 1900)) == 0


def test_year_gap_record_before_fact():
    # Запись 1880-1885, факт 1900 -> разрыв 15 лет.
    assert _year_gap(rec(year_from=1880, year_to=1885), (1900, 1900)) == 15


def test_year_gap_record_after_fact():
    # Запись 1920-1930, факт 1900 -> разрыв 20 лет.
    assert _year_gap(rec(year_from=1920, year_to=1930), (1900, 1900)) == 20


def test_year_gap_never_negative():
    """Регрессия: перепутанные ветки давали отрицательный разрыв,
    из-за чего фильтр по годам не срабатывал, а score уходил выше 1."""
    for yf, yt in [(1500, 1500), (1800, 1850), (1990, 2000), (1899, 1901)]:
        gap = _year_gap(rec(year_from=yf, year_to=yt), (1900, 1900))
        assert gap >= 0, (yf, yt, gap)


def test_year_gap_unknown_date():
    assert _year_gap(rec(year_from=None, year_to=None), (1900, 1900)) is None


# --- ранжирование --------------------------------------------------------

def test_score_within_bounds_and_ordering():
    records = [
        rec(title="здесь и тогда", lat=55.0, lon=37.0, year_from=1900, year_to=1900),
        rec(title="здесь, но раньше", lat=55.0, lon=37.0, year_from=1880, year_to=1881),
        rec(title="далеко, но тогда", lat=55.4, lon=37.0, year_from=1900, year_to=1900),
    ]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=55.0, lon=37.0, year=1900), radius_km=60, year_window=25)
    assert ms, "ожидались совпадения"
    assert all(0.0 <= m.score <= 1.0 for m in ms)
    assert ms[0].record.title == "здесь и тогда"
    assert ms == sorted(ms, key=lambda m: (-m.score, m.distance_km))


def test_year_window_filters_out_distant_events():
    eng = ContextEngine([rec(title="слишком рано", year_from=1700, year_to=1700)])
    assert eng.find(Fact(lat=55.0, lon=37.0, year=1900), year_window=25) == []


def test_radius_filters_out_distant_places():
    eng = ContextEngine([rec(title="другой край", lat=60.0, lon=37.0)])
    assert eng.find(Fact(lat=55.0, lon=37.0, year=1900), radius_km=50) == []


def test_broad_dating_ranks_below_precise():
    records = [
        rec(title="точно", year_from=1900, year_to=1900),
        rec(title="весь век", year_from=1801, year_to=1900),
    ]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=55.0, lon=37.0, year=1900), radius_km=50, year_window=25)
    assert ms[0].record.title == "точно"


def test_undated_ranks_below_dated_match():
    records = [
        rec(title="с датой", lat=55.01, lon=37.0, year_from=1900, year_to=1900),
        rec(title="без даты", lat=55.0, lon=37.0, year_from=None, year_to=None),
    ]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=55.0, lon=37.0, year=1900), radius_km=50, year_window=25)
    assert ms[0].record.title == "с датой"


def test_not_an_event_excluded_by_default():
    eng = ContextEngine([rec(title="12-я армия", confidence="not_an_event")])
    assert len(eng) == 0


def test_per_layer_cap():
    records = [rec(layer="a", title=f"a{i}", lat=55.0 + i / 1000) for i in range(5)]
    records += [rec(layer="b", title=f"b{i}", lat=55.0 + i / 1000) for i in range(5)]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=55.0, lon=37.0, year=1900), radius_km=50, per_layer_cap=2)
    assert sum(1 for m in ms if m.record.layer == "a") == 2
    assert sum(1 for m in ms if m.record.layer == "b") == 2


def test_fact_without_year_still_returns_context():
    eng = ContextEngine([rec(title="что-то рядом")])
    assert eng.find(Fact(lat=55.0, lon=37.0, year=None), radius_km=50)


# --- география -----------------------------------------------------------

def test_haversine_known_distance():
    # Москва — Санкт-Петербург, около 634 км.
    d = haversine_km(55.7558, 37.6173, 59.9343, 30.3351)
    assert 620 < d < 650


@pytest.mark.parametrize("lat,lon,ok", [
    (55.0, 37.0, True), (0, 0, False), (None, 37.0, False),
    ("55.0", "37.0", True), ("abc", "37.0", False), (95.0, 37.0, False),
])
def test_valid_coords(lat, lon, ok):
    assert valid_coords(lat, lon) is ok


def test_bbox_rejects_colonial_theatre():
    """Мартиника и Сенегал из файла сражений — не наш контекст."""
    assert not in_bbox(14.64, -61.02)     # Мартиника
    assert not in_bbox(14.69, -17.44)     # Сенегал
    assert in_bbox(55.75, 37.61)          # Москва


@pytest.mark.parametrize("text,region", [
    ("Нижегородская губерния (Васильсурск, Сергач), Заволжье", "Нижегородская губерния"),
    ("Кубанская область, Северный Кавказ", "Кубанская область"),
    ("Вологодская губерния", "Вологодская губерния"),
    ("просто текст без региона", None),
    (None, None),
])
def test_extract_region(text, region):
    assert extract_region(text) == region


def test_extract_district():
    assert extract_district("Нижегородская губерния, Сергачский уезд") == "Сергачский уезд"


# --- нормализация --------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("повесть (хотя в издательстве эту книгу причисляют к жанру автофикшен-романа)", "повесть"),
    ("очерки, рассказы", "очерки"),
    ("этнография", "этнография"),
    ("мемуары", "воспоминания"),
    ("путевые записки", "путевые заметки"),
])
def test_normalize_genre(raw, expected):
    assert normalize_genre(raw) == expected


def test_normalize_war_merges_split_labels():
    """В исходном файле одна война записана двумя строками — 251 и 202 записи."""
    a = normalize_war("Великая Отечественная война 1941–1945")
    b = normalize_war("Великая Отечественная война")
    assert a == b


@pytest.mark.parametrize("title,is_unit", [
    ("389-я пехотная дивизия (вермахт)", True),
    ("10-я воздушная армия (СССР)", True),
    ("Громов (канонерская лодка)", True),
    ("Смоленское сражение (1812)", False),
    ("Бой под Ляховом", False),
    ("Осада Кром", False),
])
def test_looks_like_military_unit(title, is_unit):
    assert looks_like_military_unit(title) is is_unit


@pytest.mark.parametrize("title,is_person", [
    ("Петлюра, Симон Васильевич", True),
    ("Кузьменко, Галина Андреевна", True),
    ("Смоленское сражение (1812)", False),
    ("Осада Риги (1656)", False),
])
def test_looks_like_person(title, is_person):
    assert looks_like_person(title) is is_person


@pytest.mark.parametrize("title,expected", [
    ("Осада Смоленска (1613—1617)", (1613, 1617)),
    ("Осада Риги (1656)", (1656, 1656)),
    ("Бой под Ляховом", (None, None)),
    ("Что-то (123)", (None, None)),
])
def test_years_from_title(title, expected):
    assert years_from_title(title) == expected


# --- схема ---------------------------------------------------------------

def test_uid_is_stable():
    a, b = rec(title="Одно и то же"), rec(title="Одно и то же")
    assert a.uid == b.uid


def test_uid_differs_by_content():
    assert rec(title="А").uid != rec(title="Б").uid


def test_feature_has_lon_lat_order():
    f = rec(lat=55.0, lon=37.0).to_feature()
    assert f["geometry"]["coordinates"] == [37.0, 55.0]
