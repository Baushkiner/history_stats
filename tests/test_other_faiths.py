"""Слой «Мечети, синагоги, кирхи, костёлы» и его граница со слоем `churches`.

Сети здесь нет: строение классов снято с Викиданных 23.08.2026 и лежит
константой ниже. Проверяется то, из-за чего слой раньше не собирался вовсе
(объявленные названия классов), и то, что разделение костёлов и кирх между
двумя слоями не оставляет ни задвоений, ни дыр.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources.wikidata import ids_query  # noqa: E402

CHRISTIAN = "Q16970"

# Образец: Q-номер -> (русское название, родители по P279). Снято одним
# запросом `wbgetentities` к www.wikidata.org, лишние родители («культовое
# сооружение», «здание») опущены — здесь важна дорога к христианскому храму.
# Названия — те же, что вернула сверка `--check` живьём.
CLASSES = {
    "Q32815": ("мечеть", ()),
    "Q34627": ("синагога", ()),
    "Q140454931": ("католический храм", (CHRISTIAN,)),
    "Q1088552": ("костёл", ("Q140454931",)),
    "Q56242063": ("протестантский храм", (CHRISTIAN,)),
    "Q56242275": ("лютеранский храм", ("Q56242063",)),
    # Ради него всё и затевалось: в файле он стоял с `?` вместо названия.
    "Q1129743": ("филиальная церковь", ("Q1088552",)),
    "Q55876909": ("католический приходской храм", ("Q1088552", "Q317557")),
    "Q56242215": ("католический собор", ("Q1088552",)),
    "Q33232008": ("грекокатолический храм", ("Q12825271",)),
    "Q12825271": ("восточнокатолический храм", ("Q1088552",)),
    "Q317557": ("приходской храм", (CHRISTIAN,)),
    CHRISTIAN: ("христианский храм", ()),
}


def ancestors(qid):
    """Все классы, до которых достаёт `wdt:P279*` от данного."""
    seen, queue = set(), [qid]
    while queue:
        current = queue.pop()
        for parent in CLASSES.get(current, ("", ()))[1]:
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)
    return seen


class FakeClient:
    """Отвечает на запрос названий классов образцом вместо сети."""

    def query(self, sparql, use_cache=True):
        asked = set(re.findall(r"wd:(Q\d+)", sparql))
        return [
            {"item": {"value": f"http://www.wikidata.org/entity/{qid}"},
             "itemLabel": {"value": name}}
            for qid, (name, _) in CLASSES.items() if qid in asked
        ]


_MODULE = None
_METAS = {}


def _harvest_module():
    global _MODULE
    if _MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "harvest_mod", ROOT / "scripts" / "harvest.py")
        _MODULE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MODULE)
    return _MODULE


def _meta(name):
    if name not in _METAS:
        _METAS[name] = _harvest_module().parse_query(ROOT / "queries" / f"{name}.rq")
    return _METAS[name]


def _declared(name):
    return {qid for qid, _ in _meta(name)["qids"]}


def _excluded_from_churches():
    return set(re.findall(r"wd:(Q\d+)", " ".join(_meta("churches")["filters"])))


def test_declared_names_are_the_ones_wikidata_returns():
    """Сверка `--check` должна проходить на записанных названиях классов.

    Тест не заменяет живую сверку (она была пройдена 23.08.2026), а держит
    файл и образец вместе: поправят название в `.rq`, не тронув образец, —
    тест покажет расхождение, а не живой сервис посреди сбора.
    """
    mod = _harvest_module()
    assert mod.check_queries(FakeClient(), [_meta("other_faiths")]), "сверка не прошла"


def test_no_query_declares_a_placeholder_instead_of_a_name():
    """`?` вместо названия останавливал сверку, а с ней и сбор всех слоёв.

    Цена такой опечатки — весь `--all`, а не один слой: `harvest.py` отменяет
    сбор целиком, если сверка не прошла хоть на одном Q-номере.
    """
    mod = _harvest_module()
    for path in sorted((ROOT / "queries").glob("*.rq")):
        for qid, label in mod.parse_query(path)["qids"]:
            assert label not in {"?", ""}, f"{path.name}: {qid} объявлен без названия"


def test_layer_collects_all_four_confessions_from_its_title():
    """Название слоя обещает четыре конфессии — все четыре должны собираться."""
    declared = _declared("other_faiths")
    assert {"Q32815", "Q34627"} <= declared, "нет мечети или синагоги"
    assert "Q1088552" in declared, "нет костёла, хотя он в названии слоя"
    assert "Q56242275" in declared, "нет лютеранского храма (кирхи)"


def test_scope_is_country_for_both_neighbouring_layers():
    """Рамочный сбор против живого сервиса не выполняется — только по странам."""
    for name in ("other_faiths", "churches"):
        assert _meta(name)["scope"] == "country", name


def test_snapshot_covers_every_declared_class():
    """Иначе проверки ниже молча пропустят новый класс."""
    unknown = _declared("other_faiths") - CLASSES.keys()
    assert not unknown, (
        f"классы {sorted(unknown)} объявлены в other_faiths.rq, но их строения "
        "нет в образце CLASSES — допишите родителей по P279"
    )


def test_churches_gives_up_exactly_what_this_layer_takes():
    """Граница между слоями: что собирается здесь, там должно быть исключено.

    Католический и протестантский храм — подклассы Q16970, который собирает
    `churches`. Класс, объявленный здесь, но не исключённый там, задвоится;
    исключённый там, но не объявленный здесь, пропадёт из обоих слоёв.
    """
    christian = {qid for qid in _declared("other_faiths")
                 if CHRISTIAN in ancestors(qid)}
    assert christian, "христианских классов в слое нет — сужать churches незачем"
    assert christian == _excluded_from_churches(), (
        "разошлись списки классов: собирается здесь "
        f"{sorted(christian)}, исключено в churches {sorted(_excluded_from_churches())}"
    )


def test_non_christian_classes_are_not_excluded_from_churches():
    """Мечеть и синагога подклассами христианского храма не являются.

    Лишний класс в `@filter` — это лишний обход иерархии на каждом объекте
    самого большого слоя, и ничего взамен.
    """
    for qid in ("Q32815", "Q34627"):
        assert CHRISTIAN not in ancestors(qid), qid
    assert not ({"Q32815", "Q34627"} & _excluded_from_churches())


def test_dropped_class_is_still_collected_by_its_parents():
    """Q1129743 убран из объявлений, но не из сбора — иначе это была бы потеря.

    «Филиальная церковь» оказалась подклассом костёла, то есть уже лежит
    внутри собираемого католического поддерева. Проверяется именно это, а не
    само по себе отсутствие Q-номера в файле.
    """
    assert "Q1129743" not in _declared("other_faiths")
    assert ancestors("Q1129743") & _declared("other_faiths"), (
        "филиальная церковь больше ни к чему не приписана — её надо вернуть "
        "в объявления, иначе слой её потеряет"
    )


def test_catholic_subtree_needs_no_extra_declarations():
    """Католические подклассы собираются через `wdt:P279*`, объявлять не нужно."""
    declared = _declared("other_faiths")
    for qid in ("Q55876909", "Q56242215", "Q12825271", "Q33232008"):
        assert ancestors(qid) & declared, f"{qid} ({CLASSES[qid][0]}) выпадает из сбора"


def test_orthodox_parishes_stay_in_churches():
    """Сужение не должно задеть обычный приходской храм."""
    assert CHRISTIAN in ancestors("Q317557")
    assert not (ancestors("Q317557") | {"Q317557"}) & _excluded_from_churches()


def test_churches_filter_makes_a_valid_query():
    """Директива `@filter` попадает в тело запроса первой ступени как есть.

    Ошибка в этой строке ломает не сверку, а сам сбор — и уже на живом
    сервисе. Синтаксис проверяется разбором, без сети.
    """
    rdflib = pytest.importorskip("rdflib", reason="разбор SPARQL: rdflib из dev-набора")
    from rdflib.plugins.sparql import prepareQuery

    meta = _meta("churches")
    sparql = ids_query([qid for qid, _ in meta["qids"]], "Q159", meta["filters"])
    assert "NOT EXISTS" in sparql, "сужение churches не попало в запрос"
    prepareQuery(sparql, initNs={
        "wd": rdflib.Namespace("http://www.wikidata.org/entity/"),
        "wdt": rdflib.Namespace("http://www.wikidata.org/prop/direct/"),
    })
