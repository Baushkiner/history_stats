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
    COUNTRIES, LABEL_LANGS, USER_AGENT, WORLD, SparqlClient, SparqlError,
    _point, _qid, _year, collect_layer, dedupe, details_query, ids_query,
    rows_to_records, stage1_plan,
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


def test_object_opened_after_the_period_keeps_a_sane_interval():
    """Регрессия: станция 2018 года не должна получить срок «2018–1960».

    Открытый конец дотягивается до 1960 года, но только вперёд. Пока даты
    объектов брались из одной P571, такие записи были редкостью; с датой
    официального открытия (P1619) их стало много — метро и позднесоветские
    станции датированы почти все.
    """
    rows = [_row(item="http://www.wikidata.org/entity/Q7", itemLabel="Станция",
                 coord="Point(37.6 55.7)", start="2018-03-01T00:00:00Z")]
    r = rows_to_records(rows, SPEC)[0]
    assert (r.year_from, r.year_to) == (2018, 2018)
    assert not r.overlaps_years(1800, 1960), "к факту XIX века она не подходит"


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
    for name in ("churches", "settlements_wd", "railway_stations"):
        assert mod.parse_query(ROOT / "queries" / f"{name}.rq")["kind"] == "object"


def test_railway_stations_ask_for_more_than_the_station_class():
    """Остановка на дороге называется в Викиданных пятью разными классами.

    `wdt:P279*` вытягивает подклассы сам, поэтому объявлять отдельно нужно
    только то, до чего этот путь не доходит. Живой запрос показал, что не
    доходит он до остановочного пункта, разъезда, сортировочной станции и
    вокзала: у сортировочной связь со станцией есть, но не лучшего ранга,
    а `wdt:` показывает только лучший. Без этих четырёх у села рядом
    с дорогой станции бы не нашлось; тест держит список, чтобы его не
    сократили обратно «для простоты».
    """
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "railway_stations.rq")
    assert meta["scope"] == "country"
    assert {q for q, _ in meta["qids"]} == {
        "Q55488", "Q55678", "Q784159", "Q519608", "Q1339195"}


def test_monasteries_declare_the_class_transitive_closure_misses():
    """Скит объявлен отдельной строкой — замыкание по монастырю его не берёт.

    Проверено живьём запросом `?c wdt:P279* wd:Q44613`: лавра, дацан и
    православный монастырь — подклассы Q44613 и приходят сами, а скит
    (Q1693568) стоит вне этой ветви. Тело файла при `@scope country` сбором
    не используется, но расходиться с заголовком не должно: по нему слой
    собирают руками.
    """
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "monasteries.rq")
    assert meta["scope"] == "country"
    declared = {q for q, _ in meta["qids"]}
    assert {"Q44613", "Q1693568"} <= declared
    for qid in declared:
        assert qid in meta["sparql"], f"класс {qid} объявлен, но не попал в тело запроса"


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


def test_request_retries_a_truncated_response(monkeypatch):
    """Оборванный на полуслове ответ — сетевая беда, а не отказ разбора.

    Живой случай: на второй ступени сбора соединение закрылось, не дописав
    последний кусок, и `IncompleteRead` уронил всю пробу. До `json.loads`
    дело не доходит, поэтому перехват ошибок разбора такое не ловит.
    """
    import http.client
    import io

    from histctx.sources import wikidata as wd

    class _Resp(io.BytesIO):
        headers: dict = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"{\"results\":")
        return _Resp(b'{"results": {"bindings": [{"item": {"value": "Q1"}}]}}')

    monkeypatch.setattr(wd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(wd.time, "sleep", lambda _: None)

    rows = SparqlClient(cache_dir=None).query("SELECT ?item WHERE { ?item ?p ?o }")
    assert len(calls) == 2, "первый ответ оборвался — должен быть повтор"
    assert rows == [{"item": {"value": "Q1"}}]


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


def test_ids_query_without_country_drops_the_p17_condition():
    """`@scope class`: отбор ведёт класс, условие по государству лишнее.

    У исторической единицы деления P17 указывает на историческое государство
    (Российская империя, РСФСР, СССР), а у части объектов не указан вовсе, —
    отбор по нынешним государствам-преемникам такой слой не соберёт.
    """
    q = ids_query(["Q86622"], None)
    assert "wdt:P17" not in q
    assert "wdt:P31/wdt:P279* ?cls" in q
    # Условие класса и координаты должны остаться одним связным выражением.
    assert "?cls ;\n        wdt:P625 ?coord ." in q


def test_stage1_without_country_asks_one_class_at_a_time():
    """Без опоры на P17 планировщик не тянет несколько классов сразу.

    Замер на живом сервисе: девять классов одним запросом — HTTP 504 через
    65 секунд, тот же отбор по одному классу — 0.6 секунды.
    """
    plan = stage1_plan(["Q86622", "Q687121"], WORLD)
    assert [step[0] for step in plan] == [["Q86622"], ["Q687121"]]
    assert all(step[1] is None for step in plan)
    # А с отбором по государству классы по-прежнему спрашиваются разом.
    by_country = stage1_plan(["Q86622", "Q687121"], COUNTRIES)
    assert len(by_country) == len(COUNTRIES)
    assert by_country[0][0] == ["Q86622", "Q687121"]


def test_collect_layer_over_world_walks_classes_then_asks_details():
    client = _FakeClient(
        [[_id_row("Q1")], [_id_row("Q2")],
         [_row(item="http://www.wikidata.org/entity/Q1", itemLabel="Клинский уезд",
               coord="Point(36.7 56.3)", start="1781-01-01T00:00:00Z",
               end="1929-01-01T00:00:00Z"),
          _row(item="http://www.wikidata.org/entity/Q2", itemLabel="Круговская волость",
               coord="Point(36.9 56.1)")]]
    )
    recs = collect_layer(client, ["Q1364324", "Q687121"], SPEC, countries=WORLD)
    assert len(client.asked) == 3, "по запросу на класс плюс один на подробности"
    assert all("wdt:P17" not in q for q in client.asked[:2])
    assert ("Клинский уезд", 1781, 1929) in [(r.title, r.year_from, r.year_to) for r in recs]
    assert "wd:Q1 wd:Q2" in client.asked[-1], "подробности спрашиваются одним чанком"


def test_admin_units_query_is_narrowed_to_historical_classes():
    """Слой деления не должен набрать нынешние муниципалитеты.

    Прежний вариант объявлял один общий класс Q56061 («административно-
    территориальная единица»), под который попадает и нынешнее сельское
    поселение, и требовал известной даты учреждения — а её нет у 549 из 655
    волостей Российской империи.
    """
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "admin_units.rq")
    qids = {qid for qid, _ in meta["qids"]}
    assert meta["scope"] == "class"
    assert "Q56061" not in qids, "общий класс заменён списком узких"
    assert {"Q86622", "Q1364324", "Q687121"} <= qids, "губерния, уезд, волость"
    assert mod.layer_countries(meta) == WORLD
    # Отсекается не «без даты учреждения», а «все даты учреждения позже 1960».
    filters = " ".join(meta["filters"])
    assert "<= 1960" in filters and "NOT EXISTS" in filters


def test_admin_units_body_repeats_the_declared_filter():
    """Тело файла повторяет директиву @filter — копиям положено сходиться.

    Сбором тело не пользуется (`@scope class`), поэтому разойтись они могут
    незаметно: правку внесли в одну копию, а вторая осталась прежней.
    """
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "admin_units.rq")
    assert meta["filters"], "условие объявлено директивами @filter"
    for line in meta["filters"]:
        assert line in meta["sparql"], line


def test_unknown_scope_is_refused(tmp_path):
    """Опечатка в @scope иначе тихо откатывает слой к телу файла.

    А тело у переведённых слоёв оставлено ручным вариантом на малой рамке:
    вместо ошибки получился бы правдоподобный, но неверный сбор.
    """
    mod = _harvest_module()
    broken = tmp_path / "typo.rq"
    broken.write_text("# @layer typo\n# @scope clas\n# @qid Q1 нечто\n"
                      "SELECT ?item WHERE { ?item ?p ?o }\n", encoding="utf-8")
    with pytest.raises(ValueError):
        mod.parse_query(broken)


def test_details_query_asks_for_everything_rows_to_records_reads():
    q = details_query(["Q1", "Q2"])
    assert "VALUES ?item { wd:Q1 wd:Q2 }" in q
    for var in ("?itemLabel", "?coord", "?start", "?end", "?adminLabel",
                "?typeLabel", "?article", "?image", "?description"):
        assert var in q, var
    assert "SERVICE wikibase:label" in q
    # Сортировка на второй ступени не нужна и стоит дорого.
    assert "ORDER BY" not in q


def test_label_service_asks_local_languages_after_russian():
    """Русский первым, языки территории следом — иначе слой теряет названия.

    С одними «ru,en» сервис возвращал голый Q-номер каждой восьмой записи:
    у волынской церкви или латвийского имения русской подписи может не быть
    вовсе. Порядок при этом важен не меньше состава: русский и английский
    стоят первыми, поэтому подписанному по-русски объекту список названия
    не меняет.
    """
    langs = LABEL_LANGS.split(",")
    assert langs[:2] == ["ru", "en"], LABEL_LANGS
    # Языки territории, где велись метрические книги наших губерний.
    for lang in ("uk", "be", "pl", "lt", "lv", "et", "fi", "hy", "ka", "az"):
        assert lang in langs, f"{lang}: язык территории потерялся из списка"
    assert len(langs) == len(set(langs)), "повтор в списке языков"

    from histctx.sources.renamed import names_query
    for sparql in (details_query(["Q1"]), names_query(["Q1"])):
        assert f'wikibase:language "{LABEL_LANGS}"' in sparql


def test_details_query_switches_dates_for_events():
    obj, event = details_query(["Q1"]), details_query(["Q1"], "event")
    assert "wdt:P571" in obj and "P585" not in obj
    assert "P585" in event and "wdt:P571" not in event


def test_details_query_falls_back_to_the_opening_date():
    """У объекта спрашивается и дата основания, и дата открытия.

    Регрессия слоя станций: одной P571 датировано 6% объектов по России,
    с P1619 — 65%. Порядок в COALESCE важен: основание главнее открытия,
    P1619 подставляется только там, где P571 пуста.
    """
    obj = details_query(["Q1"])
    assert "wdt:P1619" in obj
    assert "COALESCE(?founded, ?opened)" in obj
    assert "?start" in obj, "разбор ответа читает именно ?start"
    # У события своя пара свойств: дату открытия ему подставлять не за что.
    assert "wdt:P1619" not in details_query(["Q1"], "event")


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


def test_truncated_gzip_is_retried_not_fatal():
    """Регрессия: обрыв сжатого ответа ронял сбор целиком.

    Сервис обрывает ответ, не уложившись в свой лимит времени. Без сжатия
    это неполный JSON, со сжатием — оборванный поток gzip, а он приходит
    как BadGzipFile, EOFError или IncompleteRead. Ни одно из трёх не
    наследует URLError, поэтому раньше такая ошибка проходила мимо повторов
    и убивала обход всех семнадцати стран из-за одной.
    """
    import gzip as _gzip
    import http.client as _http
    import urllib.error

    for exc in (_gzip.BadGzipFile("оборван"), EOFError(),
                _http.IncompleteRead(b"", 10)):
        assert not isinstance(exc, urllib.error.URLError), type(exc).__name__

    client = SparqlClient(cache_dir=None, max_retries=2, timeout=1)
    calls = []

    def boom(sparql):
        calls.append(sparql)
        raise _gzip.BadGzipFile("ответ оборван на середине")

    client._request = boom
    with pytest.raises(_gzip.BadGzipFile):
        client.query("SELECT ?x WHERE { ?x ?y ?z }", use_cache=False)
    assert len(calls) == 1, "query() ошибку не глотает — её ловит _request"


def test_probe_limits_an_unconverted_query():
    """Проба слоя на @scope box не должна повторять падающий запрос целиком."""
    mod = _harvest_module()
    meta = {"scope": "box", "kind": "object", "qids": [("Q1", "класс")],
            "filters": [], "sparql": "SELECT ?item WHERE { ?item ?p ?o }",
            "layer": "проба", "title": "Проба"}
    client = _FakeClient([[]])
    mod.collect(client, meta, SPEC, paged=False, page_size=5000, max_objects=25)
    assert "LIMIT 25" in client.asked[0]


def test_timeout_is_not_retried_five_times():
    """Регрессия: 504 повторялся пятикратно и бил по общему адресу.

    Лимит времени повтором не лечится — тяжёлый запрос лёгким не станет.
    Пока повторов было пять, один упёршийся запрос отбирал попытки у
    соседних слоёв: адрес, с которого мы приходим, у всех один.
    """
    import urllib.error

    client = SparqlClient(cache_dir=None, max_retries=5)
    calls = []

    def timeout(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError("url", 504, "Gateway Timeout", {}, None)

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = timeout
    try:
        with pytest.raises(SparqlError, match="дробить"):
            client.query("SELECT ?x WHERE { ?x ?y ?z }", use_cache=False)
    finally:
        urllib.request.urlopen = original
    assert len(calls) == 2, f"504 должен обрываться на второй попытке, было {len(calls)}"
# --- усадьбы: владелец как признак места ----------------------------------
#
# Сети здесь нет: образец ответа — константа ниже. Слой усадеб единственный,
# кто спрашивает владельца (P127), и проверяется ровно то, ради чего сделана
# правка движка: имя попадает в запись усадьбы, отдельной записи о человеке
# не возникает, а остальные слои своего запроса не меняют.

# Образец ступени 2 для усадьбы: двух владельцев подзапрос свернул в одно
# значение, поэтому строка у объекта одна.
ESTATE_ROWS = [
    {
        "item": {"value": "http://www.wikidata.org/entity/Q1990932"},
        "itemLabel": {"value": "Берново"},
        "coord": {"value": "Point(34.7517 56.8069)"},
        "start": {"value": "1760-01-01T00:00:00Z"},
        "adminLabel": {"value": "Старицкий район"},
        "typeLabel": {"value": "усадьба"},
        "description": {"value": "усадьба в Тверской области"},
        "owners": {"value": "Вульфы; Иван Иванович Вульф"},
    },
]

ESTATES = LayerSpec(slug="estates", title="Усадьбы и имения", group="economy",
                    source="Викиданные", license="CC0")


def test_owner_lands_in_actor_not_in_a_separate_record():
    """Владелец — признак усадьбы, а не запись о человеке.

    Персоналии проект отдельными записями не собирает: он описывает
    обстановку. Но до 1861 года имение ищут через владельца, поэтому имя
    хранится полем той же записи — там же, где автор у литературного места.
    """
    recs = rows_to_records(ESTATE_ROWS, ESTATES)
    assert len(recs) == 1, "владельцы не должны множить записи"
    rec = recs[0]
    assert rec.actor == "Вульфы; Иван Иванович Вульф"
    assert rec.title == "Берново"
    assert rec.layer == "estates"


def test_rows_without_owner_leave_actor_empty():
    """Ответ без ?owners — обычный слой; поле просто пустое."""
    rows = [_row(item="http://www.wikidata.org/entity/Q7", itemLabel="Храм",
                 coord="Point(37.6 55.7)")]
    assert rows_to_records(rows, SPEC)[0].actor is None


def test_details_query_asks_for_owner_only_when_told():
    """Остальным слоям P127 не нужен, и текст их запроса меняться не должен.

    Текст запроса — ключ дискового кэша: лишний пробел обнулил бы кэш всех
    уже собранных слоёв.
    """
    plain = details_query(["Q1"])
    assert "P127" not in plain and "?owners" not in plain
    assert details_query(["Q1"], "object") == plain

    with_owner = details_query(["Q1"], with_owner=True)
    assert "p:P127" in with_owner and "?owners" in with_owner


def test_owner_takes_every_rank_but_the_deprecated_one():
    """`wdt:P127` отдал бы только высший ранг — и потерял бы прежних владельцев.

    Там, где нынешний владелец (музей, район) помечен предпочтительным, род,
    которому усадьба принадлежала до 1861 года, из `wdt:` не виден. Для
    генеалогии нужен именно он, поэтому берутся все утверждения, кроме
    отклонённых.
    """
    sparql = details_query(["Q1"], with_owner=True)
    assert "wdt:P127" not in sparql
    assert "p:P127 ?ownerStatement" in sparql and "ps:P127 ?owner" in sparql
    assert "wikibase:DeprecatedRank" in sparql


def test_owner_subquery_is_bounded_by_the_same_values():
    """Подзапрос без VALUES считал бы владельцев по всем Викиданным."""
    sparql = details_query(["Q1", "Q2"], with_owner=True)
    inner = sparql.split("GROUP_CONCAT")[1]
    assert "VALUES ?item { wd:Q1 wd:Q2 }" in inner
    assert "GROUP BY ?item" in inner


def test_collect_layer_passes_owner_flag_through():
    client = _FakeClient([[_id_row("Q1")]] + [[]] * (len(COUNTRIES) - 1) + [[]])
    collect_layer(client, ["Q64627814"], ESTATES, with_owner=True)
    assert "p:P127" in client.asked[-1]
    # Первая ступень остаётся дешёвой: владелец там не спрашивается.
    assert "P127" not in client.asked[0]


def test_estates_query_declares_owner_and_country_scope():
    mod = _harvest_module()
    meta = mod.parse_query(ROOT / "queries" / "estates.rq")
    assert meta["scope"] == "country"
    assert meta["kind"] == "object", "усадьба — объект, даты P571/P576"
    assert meta["owner"] == "P127"
    declared = {qid for qid, _ in meta["qids"]}
    # Городской особняк, дворец и замок — не усадьбы; разбор в шапке файла.
    assert declared.isdisjoint({"Q1802963", "Q16560", "Q23413"})
    assert declared == {"Q12292478", "Q879050"}, (
        "Корни слоя замерены живьём: вместе они укладываются в лимит службы "
        "(Польша 63 с), а лишний корень роняет запрос по России целиком — "
        "и страна теряется вся. Прежде чем добавлять @qid, замерьте. "
        "Разбор с числами — в шапке queries/estates.rq"
    )


# Описки в директиве проверяются на настоящем файле, а не на собранном руками
# словаре: ошибиться можно и в разборе заголовка, и тогда самодельный словарь
# этого не покажет.

def _rq(tmp_path, header: str) -> dict:
    path = tmp_path / "probe.rq"
    path.write_text(header + "\nSELECT ?item WHERE { ?item wdt:P31 wd:Q1 }\n",
                    encoding="utf-8")
    return _harvest_module().parse_query(path)


def test_owner_directive_is_rejected_where_it_would_do_nothing(tmp_path):
    """При `@scope box` движок в запрос ничего не добавляет.

    Молча собрать слой без владельцев хуже, чем остановиться: пустое поле
    читается как «в Викиданных владелец не указан».
    """
    mod = _harvest_module()
    meta = _rq(tmp_path, "# @layer x\n# @qid Q1 класс\n# @owner P127")
    assert meta["scope"] == "box"
    assert any("@scope country" in line for line in mod.check_directives(meta))


def test_owner_directive_rejects_another_property(tmp_path):
    """`@owner P126` — почти наверняка описка, а не замысел."""
    mod = _harvest_module()
    meta = _rq(tmp_path, "# @layer x\n# @scope country\n# @qid Q1 класс\n# @owner P126")
    assert any("P127" in line for line in mod.check_directives(meta))
    with pytest.raises(SparqlError, match="P127"):
        mod.collect(_FakeClient([[]]), meta, SPEC, paged=False, page_size=10)


def test_directive_without_a_value_does_not_pass_for_a_comment(tmp_path):
    """`# @owner` без значения — описка, а не комментарий.

    Прежний разбор требовал пробела и значения, поэтому такая строка молча
    оставалась комментарием: слой собирался без владельцев, и отличить это
    от «в Викиданных владельца нет» было нельзя.
    """
    mod = _harvest_module()
    meta = _rq(tmp_path, "# @layer x\n# @scope country\n# @qid Q1 класс\n# @owner")
    assert meta["owner"] == ""
    assert mod.check_directives(meta), "пустая директива должна вызывать жалобу"


def test_layers_without_the_directive_are_not_bothered(tmp_path):
    meta = _rq(tmp_path, "# @layer x\n# @scope country\n# @qid Q1 класс")
    assert _harvest_module().check_directives(meta) == []


def test_all_shipped_queries_pass_the_directive_check():
    mod = _harvest_module()
    for path in sorted((ROOT / "queries").glob("*.rq")):
        meta = mod.parse_query(path)
        assert mod.check_directives(meta) == [], path.name
