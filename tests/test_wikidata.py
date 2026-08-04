"""Тесты разбора ответов Викиданных и заголовков запросов.

Сеть здесь не нужна: проверяется только преобразование данных.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.schema import LayerSpec  # noqa: E402
from histctx.sources.wikidata import (  # noqa: E402
    USER_AGENT, SparqlClient, _point, _qid, _year, rows_to_records,
)

SPEC = LayerSpec(slug="churches", title="Храмы", group="faith", source="Викиданные", license="CC0")


def _harvest_module():
    spec = importlib.util.spec_from_file_location("harvest_mod", ROOT / "scripts" / "harvest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_user_agent_is_ascii():
    """Заголовки HTTP кодируются latin-1: кириллица в User-Agent роняет запрос."""
    USER_AGENT.encode("latin-1")


@pytest.mark.parametrize("wkt,lat,lon", [
    ("Point(37.6173 55.7558)", 55.7558, 37.6173),
    ("Point(-61.02 14.64)", 14.64, -61.02),
    ("не точка", None, None),
    (None, None, None),
])
def test_point_returns_lat_lon_order(wkt, lat, lon):
    """В WKT порядок «долгота широта», в схеме — наоборот."""
    assert _point(wkt) == (lat, lon)


@pytest.mark.parametrize("value,expected", [
    ("1861-01-01T00:00:00Z", 1861),
    ("1900-12-31T00:00:00Z", 1900),
    ("-0500-01-01T00:00:00Z", None),   # вне диапазона 1000..2100
    ("мусор", None),
    (None, None),
])
def test_year_from_wikidata_date(value, expected):
    assert _year(value) == expected


def test_qid_extraction():
    assert _qid("http://www.wikidata.org/entity/Q649") == "Q649"
    assert _qid("http://example.org/nope") is None
    assert _qid(None) is None


def _row(**kw):
    row = {k: {"value": v} for k, v in kw.items() if v is not None}
    return row


def test_rows_to_records_basic():
    rows = [_row(item="http://www.wikidata.org/entity/Q649",
                 itemLabel="Церковь Ильи Пророка",
                 coord="Point(39.8938 57.6261)",
                 start="1650-01-01T00:00:00Z",
                 adminLabel="Ярославская губерния")]
    recs = rows_to_records(rows, SPEC)
    assert len(recs) == 1
    r = recs[0]
    assert r.title == "Церковь Ильи Пророка"
    assert (round(r.lat, 4), round(r.lon, 4)) == (57.6261, 39.8938)
    assert r.year_from == 1650
    assert r.source_id == "Q649"
    assert r.layer == "churches"


def test_rows_without_coords_are_dropped():
    assert rows_to_records([_row(itemLabel="Без координат")], SPEC) == []


def test_rows_outside_bbox_are_dropped():
    rows = [_row(item="http://www.wikidata.org/entity/Q1", itemLabel="Мартиника",
                 coord="Point(-61.02 14.64)")]
    assert rows_to_records(rows, SPEC) == []
    # но с выключенной проверкой границ запись остаётся
    assert len(rows_to_records(rows, SPEC, require_bbox=False)) == 1


def test_open_ended_dating_gets_upper_bound():
    """Здание основано и не упразднено — иначе оно выпадет из подбора по времени."""
    rows = [_row(item="http://www.wikidata.org/entity/Q2", itemLabel="Храм",
                 coord="Point(37.6 55.7)", start="1800-01-01T00:00:00Z")]
    r = rows_to_records(rows, SPEC)[0]
    assert r.year_from == 1800
    assert r.year_to == 1960
    assert r.date_approx is True


def test_event_with_open_end_stays_in_its_year():
    """Регрессия: холера 1848 года не должна тянуться до 1960 года.

    Правило «основан и не упразднён — значит, существует до конца периода»
    верно для здания и губительно для события: эпидемия с одной датой
    оказывалась подходящей к любому факту следующих ста лет.
    """
    rows = [_row(item="http://www.wikidata.org/entity/Q4", itemLabel="Холера",
                 coord="Point(37.6 55.7)", start="1848-01-01T00:00:00Z")]
    r = rows_to_records(rows, SPEC, kind="event")[0]
    assert (r.year_from, r.year_to) == (1848, 1848)
    assert r.date_precision == "year"
    assert r.date_approx is False
    # В источнике конца нет — так и записано; числовые границы это наше решение.
    assert r.period_raw == "с 1848"


def test_event_with_only_end_date():
    rows = [_row(item="http://www.wikidata.org/entity/Q5", itemLabel="Восстание",
                 coord="Point(37.6 55.7)", end="1774-01-01T00:00:00Z")]
    r = rows_to_records(rows, SPEC, kind="event")[0]
    assert (r.year_from, r.year_to) == (1774, 1774)


def test_object_dating_unchanged_by_event_mode():
    rows = [_row(item="http://www.wikidata.org/entity/Q6", itemLabel="Храм",
                 coord="Point(37.6 55.7)", start="1800-01-01T00:00:00Z")]
    assert rows_to_records(rows, SPEC)[0].year_to == 1960


def test_event_queries_declare_kind_and_ask_for_event_dates():
    """Слои событий должны спрашивать P580/P582/P585, а не P571/P576."""
    mod = _harvest_module()
    for name in ("epidemics", "uprisings", "disasters"):
        meta = mod.parse_query(ROOT / "queries" / f"{name}.rq")
        assert meta["kind"] == "event", name
        assert "P585" in meta["sparql"] and "P580" in meta["sparql"], name
        assert "wdt:P571" not in meta["sparql"], name


def test_kind_defaults_to_object_for_places():
    mod = _harvest_module()
    for name in ("churches", "settlements", "railway_stations"):
        assert mod.parse_query(ROOT / "queries" / f"{name}.rq")["kind"] == "object"


def test_url_falls_back_to_wikidata():
    rows = [_row(item="http://www.wikidata.org/entity/Q3", itemLabel="Храм",
                 coord="Point(37.6 55.7)")]
    assert rows_to_records(rows, SPEC)[0].url == "https://www.wikidata.org/wiki/Q3"


# --- заголовки файлов запросов -------------------------------------------

def test_all_queries_parse_and_declare_qids():
    mod = _harvest_module()
    files = sorted((ROOT / "queries").glob("*.rq"))
    assert files, "каталог queries/ пуст"
    for path in files:
        meta = mod.parse_query(path)
        assert meta["sparql"].startswith("SELECT"), path.name
        assert meta["qids"], f"{path.name}: не объявлен ни один @qid"
        assert meta["layer"], path.name
        # Постраничный сбор добавляет LIMIT сам — в шаблоне его быть не должно.
        assert "LIMIT" not in meta["sparql"].upper(), path.name


def test_every_query_layer_is_registered():
    """Слой из запроса должен быть описан в registry.py, иначе сбор пропустит его."""
    from histctx.registry import BY_SLUG

    mod = _harvest_module()
    for path in sorted((ROOT / "queries").glob("*.rq")):
        layer = mod.parse_query(path)["layer"]
        assert layer in BY_SLUG, f"{path.name}: слой «{layer}» отсутствует в registry.py"


def test_qid_label_comparison():
    mod = _harvest_module()
    assert mod._same("церковное здание", "церковное здание")
    assert mod._same("мечеть", "Мечеть")
    assert not mod._same("мечеть", "синагога")


def test_paged_query_rejects_template_with_limit():
    client = SparqlClient(cache_dir=None)
    with pytest.raises(ValueError):
        list(client.query_paged("SELECT ?x WHERE { ?x ?y ?z } LIMIT 10"))
