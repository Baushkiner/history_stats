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
    COUNTRIES, USER_AGENT, SparqlClient, SparqlError, _point, _qid, _year,
    collect_layer, dedupe, details_query, ids_query, rows_to_records,
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
    """Слои событий должны спрашивать P580/P582/P585, а не P571/P576.

    При `@scope country` запрос строит движок, поэтому проверяется то, что
    он построит, а не тело файла: файл в этом случае сбором не используется.
    """
    mod = _harvest_module()
    for name in ("epidemics", "uprisings", "disasters"):
        meta = mod.parse_query(ROOT / "queries" / f"{name}.rq")
        assert meta["kind"] == "event", name
        sparql = (details_query(["Q1"], "event") if meta["scope"] == "country"
                  else meta["sparql"])
        assert "P585" in sparql and "P580" in sparql, name
        assert "wdt:P571" not in sparql, name


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


# --- сбор в две ступени ---------------------------------------------------
#
# Сети здесь по-прежнему нет: вместо клиента подставляется заглушка, которая
# отвечает заранее заготовленными строками. Проверяется то, ради чего сбор
# переписан, — что рамка заменена отбором по государству и что дорогие
# соединения выполняются на готовом списке Q-номеров.

class _FakeClient:
    """Отвечает по очереди из списка и запоминает, о чём его спросили."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []

    def query(self, sparql, *, use_cache=True):
        self.asked.append(sparql)
        if not self.answers:
            return []
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _id_row(qid):
    return {"item": {"value": f"http://www.wikidata.org/entity/{qid}"},
            "coord": {"value": "Point(37.6 55.7)"}}


def test_ids_query_asks_by_country_not_by_box():
    """Рамка убрана: именно она не давала запросу выполниться."""
    q = ids_query(["Q16970"], "Q159")
    assert "wdt:P17 wd:Q159" in q
    assert "wikibase:box" not in q
    assert "wdt:P31/wdt:P279* ?cls" in q
    # Первая ступень должна остаться дешёвой: ни меток, ни OPTIONAL.
    assert "SERVICE wikibase:label" not in q
    assert "OPTIONAL" not in q


def test_ids_query_takes_several_classes_and_extra_filters():
    q = ids_query(["Q32815", "Q34627"], "Q212", ["FILTER(YEAR(?start) <= 1960)"])
    assert "wd:Q32815 wd:Q34627" in q
    assert "FILTER(YEAR(?start) <= 1960)" in q


def test_details_query_asks_for_everything_rows_to_records_reads():
    q = details_query(["Q1", "Q2"])
    assert "VALUES ?item { wd:Q1 wd:Q2 }" in q
    for var in ("?itemLabel", "?coord", "?start", "?end", "?adminLabel",
                "?typeLabel", "?article", "?image", "?description"):
        assert var in q, var
    assert "SERVICE wikibase:label" in q
    # Сортировка на второй ступени не нужна и стоит дорого.
    assert "ORDER BY" not in q


def test_details_query_switches_dates_for_events():
    obj, event = details_query(["Q1"]), details_query(["Q1"], "event")
    assert "wdt:P571" in obj and "P585" not in obj
    assert "P585" in event and "wdt:P571" not in event


def test_dedupe_drops_rows_multiplied_by_p31_and_p131():
    """Многозначные P31/P131 множат строки: у объекта их бывает несколько."""
    rows = [_row(item="http://www.wikidata.org/entity/Q9", itemLabel="Храм",
                 coord="Point(37.6 55.7)", typeLabel=kind)
            for kind in ("церковь", "объект культурного наследия")]
    recs = rows_to_records(rows, SPEC)
    assert len(recs) == 2 and recs[0].uid == recs[1].uid
    assert len(dedupe(recs)) == 1


def test_dedupe_survives_a_second_coordinate():
    """Регрессия: две координаты у одного объекта давали две точки на карте.

    `uid` считается в том числе от широты и долготы, поэтому по нему такой
    объект не схлопывается. На живом сборе храмов это давало 11 976 записей
    на 11 877 объектов — сотню лишних точек.
    """
    rows = [_row(item="http://www.wikidata.org/entity/Q9", itemLabel="Храм",
                 coord=point)
            for point in ("Point(37.6 55.7)", "Point(37.61 55.71)")]
    recs = rows_to_records(rows, SPEC)
    assert len({r.uid for r in recs}) == 2, "разные координаты — разные uid"
    assert len(dedupe(recs)) == 1, "но объект Викиданных один"


def test_collect_layer_walks_countries_then_asks_details():
    client = _FakeClient(
        [[_id_row("Q1")], [_id_row("Q2")]]                      # две страны
        + [[]] * (len(COUNTRIES) - 2)                            # остальные пусты
        + [[_row(item="http://www.wikidata.org/entity/Q1", itemLabel="Храм",
                 coord="Point(37.6 55.7)", start="1650-01-01T00:00:00Z"),
            _row(item="http://www.wikidata.org/entity/Q2", itemLabel="Собор",
                 coord="Point(39.9 57.6)")]]
    )
    recs = collect_layer(client, ["Q16970"], SPEC)

    assert len(client.asked) == len(COUNTRIES) + 1, "по запросу на страну плюс один на подробности"
    assert {r.title for r in recs} == {"Храм", "Собор"}
    assert "wd:Q1 wd:Q2" in client.asked[-1], "подробности спрашиваются одним чанком"


def test_collect_layer_does_not_ask_the_same_object_twice():
    """Объект, попавший в две страны, собирается один раз."""
    client = _FakeClient([[_id_row("Q1")], [_id_row("Q1")]]
                         + [[]] * (len(COUNTRIES) - 2) + [[]])
    collect_layer(client, ["Q16970"], SPEC)
    assert client.asked[-1].count("wd:Q1") == 1


def test_collect_layer_survives_a_failing_country():
    """Потерять область плохо, потерять весь слой хуже — но молчать нельзя."""
    said = []
    client = _FakeClient([SparqlError("504")] + [[_id_row("Q1")]]
                         + [[]] * (len(COUNTRIES) - 2)
                         + [[_row(item="http://www.wikidata.org/entity/Q1",
                                  itemLabel="Храм", coord="Point(37.6 55.7)")]])
    recs = collect_layer(client, ["Q16970"], SPEC, progress=said.append)
    assert len(recs) == 1
    assert any("ОШИБКА" in line for line in said)


def test_collect_layer_chunks_long_lists():
    ids = [[_id_row(f"Q{i}") for i in range(2500)]]
    client = _FakeClient(ids + [[]] * (len(COUNTRIES) - 1) + [[], [], []])
    collect_layer(client, ["Q16970"], SPEC, chunk_size=1000)
    details = client.asked[len(COUNTRIES):]
    assert len(details) == 3, "2500 объектов — три чанка по тысяче"
