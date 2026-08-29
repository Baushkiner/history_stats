"""Слои событий: откуда берутся координата и государство.

Сети в тестах нет: образец ответа — константа ниже, снятая с ответа
`query.wikidata.org` на запрос подробностей. Проверяется то, ради чего
запросы событий переписаны, — что событие без своей `P625` всё-таки встаёт
на карту по месту события и что при этом видно, откуда взята точка.

Разбор дат событий проверяется в `test_wikidata.py`; здесь только география
и отбор по государству.
"""

import importlib.util
from pathlib import Path

from histctx.schema import LayerSpec
from histctx.sources.wikidata import (
    COUNTRIES, HISTORICAL_COUNTRIES, SETTLEMENT, collect_layer, details_query,
    ids_query, rows_to_records,
)

ROOT = Path(__file__).resolve().parents[1]

SPEC = LayerSpec(slug="uprisings", title="Восстания", group="hardship",
                 source="Викиданные", license="CC0")

# Образец второй ступени: две настоящие записи Викиданных.
# Восстание декабристов — своя координата есть (Сенатская площадь);
# Чумной бунт — своей координаты нет, `P276` указывает на Москву, и точка
# приходит уже подставленной запросом, а `?coordSource` говорит откуда.
ROWS = [
    {
        "item": {"value": "http://www.wikidata.org/entity/Q126306"},
        "itemLabel": {"value": "Восстание декабристов"},
        "coord": {"value": "Point(30.3022 59.9364)"},
        "coordSource": {"value": "own"},
        "start": {"value": "1825-12-26T00:00:00Z"},
        "typeLabel": {"value": "восстание"},
    },
    {
        "item": {"value": "http://www.wikidata.org/entity/Q4518057"},
        "itemLabel": {"value": "Чумной бунт"},
        "coord": {"value": "Point(37.6156 55.7522)"},
        "coordSource": {"value": "place"},
        "start": {"value": "1771-09-15T00:00:00Z"},
        "typeLabel": {"value": "восстание"},
    },
]


def test_event_without_own_coordinate_is_marked_place_level():
    """Координата места события — это `place_level`, а не «ок».

    Точка Чумного бунта — центр Москвы, а не Кремль и не Чудов монастырь.
    Запись на карту идёт, но выдавать её за место события нельзя.
    """
    by_title = {r.title: r for r in rows_to_records(ROWS, SPEC, kind="event")}

    assert by_title["Восстание декабристов"].confidence == "ok"
    bunt = by_title["Чумной бунт"]
    assert bunt.confidence == "place_level"
    assert (round(bunt.lat, 4), round(bunt.lon, 4)) == (55.7522, 37.6156)
    # Событие не тянется до конца периода: у бунта один год.
    assert (bunt.year_from, bunt.year_to) == (1771, 1771)


def test_objects_are_never_marked_place_level():
    """У зданий `?coordSource` не спрашивается — метка не должна появляться."""
    rows = [{"item": {"value": "http://www.wikidata.org/entity/Q649"},
             "itemLabel": {"value": "Церковь Ильи Пророка"},
             "coord": {"value": "Point(39.8938 57.6261)"}}]
    assert rows_to_records(rows, SPEC)[0].confidence == "ok"


def test_event_queries_take_the_coordinate_of_the_place():
    """У события своей `P625` часто нет: она берётся через `P276`."""
    ids = ids_query(["Q124734"], "Q34266", kind="event")
    assert "wdt:P276" in ids
    assert "wdt:P17 wd:Q34266" in ids
    # Первая ступень должна остаться дешёвой и без OPTIONAL — отсюда UNION.
    assert "OPTIONAL" not in ids

    details = details_query(["Q1"], "event")
    assert "wdt:P276" in details
    assert "?coordSource" in details


def test_coordinate_is_borrowed_only_from_a_settlement():
    """Регрессия: `P276` сплошь и рядом указывает на губернию.

    У Кыштымского волнения там Пермская губерния, у Лучайского бунта —
    Виленская. Точка в середине губернии выглядит на карте достоверно и
    врёт, поэтому занимать координату разрешено только у населённого пункта.
    """
    for query in (ids_query(["Q124734"], "Q34266", kind="event"),
                  details_query(["Q1"], "event")):
        assert f"wdt:P31/wdt:P279* wd:{SETTLEMENT}" in query
        # P131 — всегда административная единица, её брать нельзя вовсе.
        assert "wdt:P131 ?place" not in query


def test_object_queries_are_left_alone():
    """Слои зданий не должны измениться: их правят ещё семнадцать задач."""
    ids = ids_query(["Q16970"], "Q159")
    assert "wdt:P276" not in ids
    assert "wdt:P625 ?coord ." in ids

    details = details_query(["Q1"])
    assert "wdt:P276" not in details
    assert "?coordSource" not in details


def test_historical_states_are_real_and_distinct():
    """Список исторических государств не должен пересекаться с нынешним."""
    assert dict(HISTORICAL_COUNTRIES)["Q34266"] == "Российская империя"
    assert not ({q for q, _ in HISTORICAL_COUNTRIES}
                & {q for q, _ in COUNTRIES})


def _harvest_module():
    spec = importlib.util.spec_from_file_location(
        "harvest_events_mod", ROOT / "scripts" / "harvest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_event_layers_are_bounded_by_the_period_of_interest():
    """Слои событий обязаны сузиться по дате — иначе их топит современность.

    Живая проба бедствий по одной России дала 216 записей, из них до 1961
    года — 19: остальное теракты, стрельба в школах и заказные убийства
    девяностых. Класс при этом объявлен верно, лишнее отсекается по дате.
    """
    mod = _harvest_module()
    for name in ("disasters", "epidemics", "uprisings"):
        meta = mod.parse_query(ROOT / "queries" / f"{name}.rq")
        assert meta["scope"] == "country", name
        assert meta["kind"] == "event", name
        joined = " ".join(meta["filters"])
        assert "P585" in joined and "YEAR(?when) <= 1960" in joined, name
        # Директивы должны доходить до запроса первой ступени.
        built = ids_query([q for q, _ in meta["qids"]], "Q34266",
                          meta["filters"], meta["kind"])
        assert "YEAR(?when) <= 1960" in built, name


class _FakeClient:
    """Отвечает по очереди из списка и запоминает, о чём его спросили."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []

    def query(self, sparql, *, use_cache=True):
        self.asked.append(sparql)
        return self.answers.pop(0) if self.answers else []


def _id_row(qid):
    return {"item": {"value": f"http://www.wikidata.org/entity/{qid}"},
            "coord": {"value": "Point(37.6 55.7)"}}


def test_collect_layer_walks_historical_states_too():
    """Регрессия: восстание декабристов терялось на отборе по государству.

    У него `P17` — «Российская империя», и обход по одним нынешним
    государствам его не находил.
    """
    client = _FakeClient([[]] * len(COUNTRIES)
                         + [[_id_row("Q126306")]]
                         + [[]] * (len(HISTORICAL_COUNTRIES) - 1)
                         + [ROWS[:1]])
    recs = collect_layer(client, ["Q124734"], SPEC, kind="event",
                         history=HISTORICAL_COUNTRIES)

    assert len(client.asked) == len(COUNTRIES) + len(HISTORICAL_COUNTRIES) + 1
    assert "wd:Q34266" in client.asked[len(COUNTRIES)]
    assert [r.title for r in recs] == ["Восстание декабристов"]


def test_collect_layer_leaves_object_layers_at_seventeen_countries():
    """Без `history` обход прежний — ровно семнадцать государств."""
    client = _FakeClient([[]] * len(COUNTRIES))
    assert collect_layer(client, ["Q16970"], SPEC) == []
    assert len(client.asked) == len(COUNTRIES)


def test_probe_of_an_event_layer_asks_a_historical_state():
    """Проба слоя событий по нынешней России ничего не значит.

    У события `P17` указывает на государство времён события, поэтому проба
    берёт Российскую империю — и по-прежнему ровно одно государство, то есть
    два обращения к сервису.
    """
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "uprisings.rq")
    client = _FakeClient([[_id_row("Q126306")], ROWS[:1]])

    assert mod.probe(client, meta, SPEC) == 0
    assert len(client.asked) == 2
    assert f"wdt:P17 wd:{HISTORICAL_COUNTRIES[0][0]}" in client.asked[0]


def test_empty_collection_does_not_overwrite_a_previous_export(tmp_path):
    """Пустой результат не должен затирать прошлую удачную выгрузку.

    Ошибка на каждом государстве даёт ноль записей, и запись такого слоя
    подменила бы данные пустотой — молча и с кодом успеха.
    """
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "uprisings.rq")
    client = _FakeClient([])   # каждое государство отвечает пусто

    assert mod.harvest(client, meta, SPEC, tmp_path, False, 5000) == 0
    assert not list(tmp_path.rglob("*.geojson"))
