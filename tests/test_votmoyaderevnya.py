"""Разбор и обход базы «Вот моя деревня» (votmoyaderevnya.ru).

Сети в тестах нет. API сайта подменено словарём ответов: дерево разделов
«Области → Тульская область → Кимовский район → Сельское поселение» и
муниципальный округ, у которого селения висят прямо на нём, без поселений.
Ответы взяты по образцу живых (ноябрь 2026 года), с сокращениями.

Проверяется то, на чём слой держится: обход дерева только там, где есть
дети, запрос селений только там, где они есть, кэш с продолжением, повтор на
503, прежние названия из скобок, год основания строкой, рубрика
«Админпринадлежность» по периодам, первое упоминание вместо года основания,
рамка проекта у селений без дат, селение без точки — запись, а не потеря.
"""

import io
import json
import urllib.error

import pytest

from histctx.registry import BY_SLUG
from histctx.sources import votmoyaderevnya as vmd
from histctx.sources.votmoyaderevnya import (
    API, LAYER_ID, SETTLEMENTS_VMD, Client, VmdError, admin_history, admin_path,
    founded_year, record, records, split_name, walk_categories,
)


def _cat(id_, name, children=0, settlements=0):
    return {"id": id_, "name": name, "slug": "x", "description": "", "sort_order": 1,
            "children_count": children, "settlements_count": settlements}


def _ok(data):
    return {"success": True, "data": data}


BREAD = [{"id": 3, "name": "Области", "parent_id": None},
         {"id": 4, "name": "Тульская область", "parent_id": 3},
         {"id": 5, "name": "Кимовский район", "parent_id": 4},
         {"id": 22, "name": "Сельское поселение Новольвовское", "parent_id": 5}]

ADMIN_HTML = (
    "<p>1676-1708 - Русское царство, Венёвский уезд, Есенецкий стан.&nbsp;</p>"
    "<p>1796-1861 - Российская империя, Тульская губерния, Венёвский уезд.</p>"
    "<p>1861-1916 - Российская империя, Тульская губерния, Венёвский уезд, "
    "Холтобинская волость. ... 2008-н.в. - Российская Федерация, Тульская область "
    ", Городской округ Новомосковск .</p>"
)


def _card(sid, name, *, year=None, lat="54.041773", lon="38.598465", status="active",
          kind="деревня", rubrics=(), population=(), bread=BREAD, gallery=()):
    return _ok({
        "settlement": {"id": sid, "category_id": bread[-1]["id"], "name": name,
                       "status": status, "custom_status": kind, "year_founded": year,
                       "latitude": lat, "longitude": lon, "description": None,
                       "category_name": bread[-1]["name"]},
        "breadcrumb": bread,
        "rubrics": [{"id": i, "title": t, "content": c, "sort_order": i}
                    for i, (t, c) in enumerate(rubrics)],
        "gallery": list(gallery),
        "population": list(population),
    })


MO_BREAD = [{"id": 3, "name": "Области", "parent_id": None},
            {"id": 8, "name": "Московская область", "parent_id": 3},
            {"id": 163, "name": "Муниципальный округ Серебряные Пруды", "parent_id": 8}]

API_RESPONSES = {
    "categories.php": _ok([_cat(3, "Области", children=2), _cat(9, "Края")]),
    "categories.php?parent_id=3": _ok([_cat(4, "Тульская область", children=1),
                                       _cat(8, "Московская область", children=1)]),
    "categories.php?parent_id=4": _ok([_cat(5, "Кимовский район", children=1)]),
    "categories.php?parent_id=5": _ok([_cat(22, "Сельское поселение Новольвовское",
                                            settlements=2)]),
    "categories.php?parent_id=8": _ok([_cat(163, "Муниципальный округ Серебряные Пруды",
                                            settlements=1)]),
    "category-settlements.php?category_id=22": _ok([
        {"id": 3, "name": "Кукуй (Белколодезь + Великое Поле)", "status": "active",
         "custom_status": "деревня", "year_founded": "1676"},
        {"id": 34, "name": "Каркадиново (Красное, Слободка)", "status": "active",
         "custom_status": "село", "year_founded": None}]),
    "category-settlements.php?category_id=163": _ok([
        {"id": 401, "name": "Выселки", "status": "inactive", "custom_status": "хутор",
         "year_founded": None}]),
    "settlement-details-v2.php?id=3": _card(
        3, "Кукуй (Белколодезь + Великое Поле)", year="1676",
        rubrics=[("История деревни", "<p>Текст</p>"), ("Топоним", ""),
                 ("Админпринадлежность в разные периоды", ADMIN_HTML)],
        population=[{"year": 1710, "population": 160}, {"year": 2026, "population": 12}],
        gallery=[{"id": 18, "image_path": "uploads/gallery/a.jpeg"}]),
    "settlement-details-v2.php?id=34": _card(
        34, "Каркадиново (Красное, Слободка)", kind="село",
        rubrics=[("История деревни", ""), ("Топоним", "&nbsp; ")]),
    "settlement-details-v2.php?id=401": _card(
        401, "Выселки", kind="хутор", status="inactive", lat=None, lon=None, bread=MO_BREAD,
        population=[{"year": 1859, "population": 40}]),
}


class FakeApi:
    def __init__(self, responses=API_RESPONSES, fail=None):
        self.responses = responses
        self.calls = []
        self.fail = dict(fail or {})

    def __call__(self, url):
        assert url.startswith(API + "/"), url
        key = url[len(API) + 1:]
        self.calls.append(key)
        if self.fail.get(key):
            self.fail[key] -= 1
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        if key not in self.responses:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return json.dumps(self.responses[key], ensure_ascii=False).encode("utf-8")


def _client(tmp_path, api=None):
    return Client(tmp_path / "cache", pause=0, opener=api or FakeApi())


def _crawl(client):
    nodes = list(walk_categories(client))
    cards = []
    for node in nodes:
        if node.settlements:
            for s in client.settlements(node.id):
                cards.append(client.details(int(s["id"])))
    return nodes, cards


# --- обход и кэш -------------------------------------------------------------


def test_walk_asks_children_only_where_they_are(tmp_path):
    api = FakeApi()
    nodes = list(walk_categories(_client(tmp_path, api)))
    assert [n.id for n in nodes] == [3, 4, 5, 22, 8, 163, 9]
    assert "categories.php?parent_id=9" not in api.calls  # у «Краёв» детей нет
    assert "categories.php?parent_id=22" not in api.calls
    leaf = next(n for n in nodes if n.id == 22)
    assert leaf.path == ("Области", "Тульская область", "Кимовский район",
                         "Сельское поселение Новольвовское")
    assert leaf.settlements == 2


def test_cache_resumes_without_network(tmp_path):
    api = FakeApi()
    _crawl(_client(tmp_path, api))
    first = len(api.calls)
    again = FakeApi()
    client = _client(tmp_path, again)
    nodes, cards = _crawl(client)
    assert first == 10 and again.calls == []
    assert client.hits == 10 and len(cards) == 3


def test_retry_on_503(tmp_path, monkeypatch):
    monkeypatch.setattr(vmd.time, "sleep", lambda s: None)
    api = FakeApi(fail={"categories.php": 2})
    client = _client(tmp_path, api)
    assert [c["id"] for c in client.categories(None)] == [3, 9]
    assert api.calls.count("categories.php") == 3


def test_404_is_an_error_not_an_empty_layer(tmp_path):
    with pytest.raises(VmdError):
        _client(tmp_path).categories(999)


def test_missing_card_answers_500_and_is_cached(tmp_path):
    """Нет карточки — сайт отвечает кодом 500 с `success: false`; это ответ, не сбой."""
    body = json.dumps({"success": False, "error": "Населённый пункт не найден"},
                      ensure_ascii=False).encode("utf-8")
    calls = []

    def opener(url):
        calls.append(url)
        raise urllib.error.HTTPError(url, 500, "err", {}, io.BytesIO(body))

    client = Client(tmp_path / "cache", pause=0, opener=opener)
    assert client.details(7) is None
    assert client.details(7) is None
    assert len(calls) == 1


# --- разбор ------------------------------------------------------------------


def test_split_name():
    assert split_name("Каркадиново (Красное, Слободка)") == ("Каркадиново",
                                                             ["Красное", "Слободка"])
    assert split_name("Кукуй (Белколодезь + Великое Поле)") == ("Кукуй",
                                                                ["Белколодезь", "Великое Поле"])
    assert split_name("Весёлый Луг") == ("Весёлый Луг", [])
    assert split_name("Юдино (1-е) (Старое)") == ("Юдино (1-е) (Старое)", [])


def test_founded_year():
    assert founded_year("1572") == 1572
    assert founded_year("1678 г.") == 1678
    assert founded_year(1850) == 1850
    assert founded_year("XVII в.") is None
    assert founded_year(None) is None


def test_admin_history_periods():
    rows = admin_history([{"title": "Админпринадлежность в разные периоды",
                           "content": ADMIN_HTML}])
    assert rows[0] == {"from": 1676, "to": 1708,
                       "unit": "Русское царство, Венёвский уезд, Есенецкий стан"}
    assert rows[2]["unit"].endswith("Холтобинская волость")
    assert rows[-1] == {"from": 2008, "to": None,
                        "unit": "Российская Федерация, Тульская область, "
                                "Городской округ Новомосковск"}
    assert admin_history([{"title": "История", "content": ADMIN_HTML}]) == []


def test_admin_path_drops_top_kind():
    assert admin_path(BREAD) == ["Тульская область", "Кимовский район",
                                 "Сельское поселение Новольвовское"]


def test_records(tmp_path):
    _, cards = _crawl(_client(tmp_path))
    recs = {r.source_id: r for r in records(cards)}
    assert list(recs) == ["3", "34", "401"]

    kukuy = recs["3"]
    assert kukuy.layer == LAYER_ID and kukuy.title == "деревня Кукуй"
    assert (kukuy.year_from, kukuy.year_to, kukuy.date_precision) == (1676, 1960, "open")
    assert not kukuy.date_approx and "date_source" not in kukuy.extra
    assert kukuy.region == "Тульская область" and kukuy.district == "Кимовский район"
    assert kukuy.url == "https://votmoyaderevnya.ru/settlement.html?id=3"
    assert kukuy.extra["former_names"] == ["Белколодезь", "Великое Поле"]
    assert kukuy.extra["population"] == {"1710": 160, "2026": 12}
    assert kukuy.extra["rubrics"] == ["История деревни", "Админпринадлежность в разные периоды"]
    assert kukuy.extra["photos"] == 1
    assert "в 1897 г.: Российская империя, Тульская губерния, Венёвский уезд, " \
           "Холтобинская волость" in kukuy.summary
    assert kukuy.confidence == "ok" and kukuy.has_point

    plain = recs["34"]
    assert (plain.year_from, plain.year_to, plain.date_precision) == (1600, 1960, "era")
    assert plain.date_approx and plain.extra["date_source"] == "рамка проекта"
    assert "rubrics" not in plain.extra  # пустые и «&nbsp;» не считаются

    gone = recs["401"]
    assert gone.category == "хутор (недействующее)"
    assert gone.extra["status"] == "недействующий"
    assert (gone.year_from, gone.date_precision) == (1859, "open")
    assert gone.extra["date_source"] == "первое упоминание в карточке"
    assert gone.confidence == "no_coords" and not gone.has_point
    assert gone.region == "Московская область" and gone.district.startswith("Муниципальный")


def test_uid_is_stable(tmp_path):
    _, cards = _crawl(_client(tmp_path))
    assert [r.uid for r in records(cards)] == [r.uid for r in records(cards)]


def test_layer_is_registered():
    spec = BY_SLUG[LAYER_ID]
    assert spec is SETTLEMENTS_VMD and spec.status == "harvested"
    assert "согласия" in spec.license
