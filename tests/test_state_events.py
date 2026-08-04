"""Тесты подборки территориальных событий и подбора контекста по губернии.

Данные проверяются как код: битая дата или губерния, которой нет ни в одном
событии, — это ошибка сборки, а не мелкая неточность в таблице.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.adapters.state_events import (  # noqa: E402
    CATEGORIES, DEFAULT_PATH, STATE_EVENTS, YEAR_MAX, YEAR_MIN, DatasetError, load_state_events,
)
from histctx.enrich import ContextEngine, Fact  # noqa: E402
from histctx.geo import region_key, same_region  # noqa: E402
from histctx.schema import SCOPE_REGION, SCOPE_STATE, ContextRecord  # noqa: E402

EVENTS = load_state_events()


def point(**kw) -> ContextRecord:
    base = dict(layer="tenishev", layer_title="Тенишев", title="Село", lat=53.2, lon=50.15,
                year_from=1897, year_to=1901, source="test", region="Самарская губерния")
    base.update(kw)
    return ContextRecord(**base)


def event(**kw) -> ContextRecord:
    base = dict(layer="state_events", layer_title="События", title="Событие",
                scope=SCOPE_STATE, year_from=1890, year_to=1895, source="test",
                place_text="Российская империя")
    base.update(kw)
    return ContextRecord(**base)


# --- целостность подборки -------------------------------------------------

def test_dataset_is_not_empty():
    assert len(EVENTS) >= 60, "подборка событий подозрительно мала"


def test_every_event_is_dated_and_usable():
    for rec in EVENTS:
        assert rec.has_time, rec.title
        assert YEAR_MIN <= rec.year_from <= rec.year_to <= YEAR_MAX, rec.title
        assert rec.usable, rec.title


def test_events_have_no_coordinates():
    """Точка у такого события была бы выдумкой: голод не случается в точке."""
    assert not any(rec.has_point for rec in EVENTS)


def test_scope_matches_regions():
    for rec in EVENTS:
        assert rec.scope in (SCOPE_STATE, SCOPE_REGION), rec.title
        assert bool(rec.regions) is (rec.scope == SCOPE_REGION), rec.title


def test_categories_are_closed_list():
    assert {rec.category for rec in EVENTS} <= set(CATEGORIES)


def test_every_category_is_used():
    """Пустая категория в списке — либо забытые события, либо лишняя строка."""
    assert {rec.category for rec in EVENTS} == set(CATEGORIES)


def test_summaries_explain_what_to_look_for():
    for rec in EVENTS:
        assert rec.summary and len(rec.summary) > 40, rec.title
    with_documents = [rec for rec in EVENTS if "Что искать в архиве" in (rec.summary or "")]
    assert len(with_documents) >= len(EVENTS) - 5


def test_uids_and_source_ids_are_unique():
    assert len({rec.uid for rec in EVENTS}) == len(EVENTS)
    assert len({rec.source_id for rec in EVENTS}) == len(EVENTS)


def test_layer_fields_come_from_spec():
    for rec in EVENTS:
        assert rec.layer == STATE_EVENTS.slug
        assert rec.group == "state"
        assert rec.license


def test_urls_point_to_wikipedia():
    for rec in EVENTS:
        if rec.url:
            assert rec.url.startswith("https://ru.wikipedia.org/wiki/"), rec.title


def test_key_events_are_present():
    """Опоры периода: без них слой бесполезен для генеалогии."""
    titles = " | ".join(rec.title for rec in EVENTS)
    for needle in ("X ревизия", "Отмена крепостного права", "Всеобщая воинская повинность",
                   "Первая всеобщая перепись", "Голод 1891", "Раскулачивание"):
        assert needle in titles, needle


def test_broken_dataset_is_rejected(tmp_path):
    import json

    payload = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    payload["events"][0]["years"] = [1900, 1850]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DatasetError):
        load_state_events(broken)


def test_region_scope_without_regions_is_rejected(tmp_path):
    import json

    payload = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    payload["events"][0]["scope"] = "region"
    payload["events"][0]["regions"] = []
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DatasetError):
        load_state_events(broken)


# --- сопоставление территорий --------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Самарская губерния", "Самарская область"),
    ("Область войска Донского", "Донская область"),
    ("Нижегородская губерния", "Нижегородской губернии"),
    ("Казахская ССР", "Казахская АССР"),
    ("Самарская губ.", "Самарская область"),
])
def test_same_region_ignores_unit_and_case(a, b):
    assert same_region(a, b)


@pytest.mark.parametrize("a,b", [
    ("Самарская губерния", "Саратовская губерния"),
    ("Вятская губерния", None),
])
def test_different_regions_do_not_match(a, b):
    assert not same_region(a, b)


def test_region_key_of_empty_value():
    assert region_key(None) is None
    assert region_key("  ") is None


# --- подбор событий без точки --------------------------------------------

def test_state_event_matches_anywhere():
    eng = ContextEngine([event(title="Воинская повинность", year_from=1874, year_to=1917)])
    ms = eng.find(Fact(lat=53.2, lon=50.15, year=1890))
    assert [m.record.title for m in ms] == ["Воинская повинность"]
    assert ms[0].distance_km is None and ms[0].territorial


def test_region_event_needs_matching_region():
    rec = event(title="Голод", scope=SCOPE_REGION, regions=["Самарская губерния"],
                year_from=1891, year_to=1892)
    eng = ContextEngine([rec])
    assert eng.find(Fact(lat=53.2, lon=50.15, year=1891, region="Самарская губерния"))
    assert not eng.find(Fact(lat=53.2, lon=50.15, year=1891, region="Вятская губерния"))


def test_region_is_inferred_from_nearby_records():
    """Губерния не задана, но соседние записи знают, где мы находимся."""
    rec = event(title="Голод", scope=SCOPE_REGION, regions=["Самарская губерния"],
                year_from=1891, year_to=1892)
    eng = ContextEngine([rec, point(region="Самарская губерния")])
    fact = Fact(lat=53.2, lon=50.15, year=1891)
    assert eng.resolve_region(fact) == ("Самарская губерния", "по ближайшим записям")
    assert any(m.record.title == "Голод" for m in eng.find(fact))


def test_region_event_skipped_when_region_unknown():
    """Приписать факту чужую губернию хуже, чем не показать событие."""
    rec = event(title="Голод", scope=SCOPE_REGION, regions=["Самарская губерния"],
                year_from=1891, year_to=1892)
    eng = ContextEngine([rec])
    assert eng.find(Fact(lat=53.2, lon=50.15, year=1891)) == []


def test_explicit_region_wins_over_inferred():
    eng = ContextEngine([point(region="Вятская губерния")])
    fact = Fact(lat=53.2, lon=50.15, year=1900, region="Самарская губерния")
    assert eng.resolve_region(fact) == ("Самарская губерния", "задана")


def test_year_window_applies_to_territorial_events():
    eng = ContextEngine([event(title="Далёкое", year_from=1700, year_to=1701)])
    assert eng.find(Fact(lat=53.2, lon=50.15, year=1900), year_window=25) == []


def test_named_region_outranks_whole_state():
    """Губерния названа поимённо — это точнее, чем «действовало везде»."""
    records = [
        event(title="Голод", scope=SCOPE_REGION, regions=["Самарская губерния"],
              year_from=1891, year_to=1892),
        event(title="Указ", year_from=1891, year_to=1892),
    ]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=53.2, lon=50.15, year=1891, region="Самарская губерния"))
    assert [m.record.title for m in ms] == ["Голод", "Указ"]


def test_point_outranks_state_event_at_equal_time():
    """Запись рядом с местом полезнее указа, действовавшего по всей стране."""
    records = [point(year_from=1891, year_to=1891), event(year_from=1891, year_to=1891)]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=53.2, lon=50.15, year=1891))
    assert ms[0].record.layer == "tenishev"


def test_territorial_can_be_switched_off():
    eng = ContextEngine([event(year_from=1891, year_to=1892)])
    assert eng.find(Fact(lat=53.2, lon=50.15, year=1891), include_territorial=False) == []


def test_summary_counts_territorial_and_ignores_them_in_distance():
    records = [point(year_from=1891, year_to=1891), event(year_from=1891, year_to=1891)]
    eng = ContextEngine(records)
    ms = eng.find(Fact(lat=53.2, lon=50.15, year=1891))
    summary = eng.summarize(ms)
    assert summary["territorial"] == 1
    assert summary["nearest_km"] is not None


def test_per_layer_cap_applies_to_events():
    records = [event(title=f"событие {i}", year_from=1891, year_to=1892) for i in range(5)]
    eng = ContextEngine(records)
    assert len(eng.find(Fact(lat=53.2, lon=50.15, year=1891), per_layer_cap=2)) == 2


def test_real_dataset_answers_a_real_fact():
    """Венчание в Самарской губернии в 1891 году — голод должен быть первым."""
    eng = ContextEngine(EVENTS)
    ms = eng.find(Fact(lat=53.2, lon=50.15, year=1891, region="Самарская губерния"),
                  year_window=5, limit=5)
    assert ms and ms[0].record.title.startswith("Голод 1891")


def test_regions_survive_export_round_trip():
    rec = event(title="Голод", scope=SCOPE_REGION, regions=["Самарская губерния", "Вятская губерния"])
    assert rec.to_row()["regions"] == "Самарская губерния; Вятская губерния"
