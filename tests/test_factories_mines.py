"""Экономические слои: заводы и рудники.

Сети в тестах нет: образец ответа — константа ниже. Названия, координаты и
даты в ней настоящие, из живой пробы `harvest.py --probe` по России;
Q-номера условные — разбору важен только их вид.

Проверяется то, ради чего слои переписаны: сбор идёт по государствам
(`@scope country`), даты берутся как у объектов (P571/P576), а классы двух
слоёв не пересекаются — иначе одна и та же шахта попала бы и в заводы,
и в рудники.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.schema import LayerSpec  # noqa: E402
from histctx.sources.wikidata import (  # noqa: E402
    dedupe, details_query, ids_query, rows_to_records,
)

FACTORIES = LayerSpec(slug="factories", title="Заводы и фабрики", group="economy",
                      source="Викиданные", license="CC0")
MINES = LayerSpec(slug="mines", title="Рудники, копи, промыслы", group="economy",
                  source="Викиданные", license="CC0")


def _row(**kw):
    return {k: {"value": v} for k, v in kw.items() if v is not None}


# Образец ответа второй ступени: закрытый завод, действующий завод,
# месторождение без дат, рудник с двумя значениями P31 и рудник за рамкой
# РИ/СССР (Витватерсранд) — его разбор обязан отбросить.
ROWS = [
    _row(item="http://www.wikidata.org/entity/Q101",
         itemLabel="Александровский завод полупроводниковых приборов",
         coord="Point(38.709 56.393)",
         start="1959-01-01T00:00:00Z", end="2011-01-01T00:00:00Z",
         adminLabel="Владимирская область", typeLabel="завод",
         article="https://ru.wikipedia.org/wiki/АЗПП"),
    _row(item="http://www.wikidata.org/entity/Q102",
         itemLabel="Электровыпрямитель", coord="Point(45.176 54.196)",
         start="1944-01-01T00:00:00Z",
         adminLabel="Мордовия", typeLabel="завод"),
    _row(item="http://www.wikidata.org/entity/Q103",
         itemLabel="Агаповское месторождение", coord="Point(59.121 53.321)",
         adminLabel="Челябинская область",
         typeLabel="месторождение полезных ископаемых"),
    _row(item="http://www.wikidata.org/entity/Q104",
         itemLabel="Путиловский", coord="Point(31.397 59.855)",
         start="1712-01-01T00:00:00Z", typeLabel="рудник"),
    _row(item="http://www.wikidata.org/entity/Q104",
         itemLabel="Путиловский", coord="Point(31.397 59.855)",
         start="1712-01-01T00:00:00Z", typeLabel="объект культурного наследия"),
    _row(item="http://www.wikidata.org/entity/Q105",
         itemLabel="Витватерсранд", coord="Point(27.0 -26.2)",
         typeLabel="золотой рудник"),
    _row(item="http://www.wikidata.org/entity/Q106",
         itemLabel="Ботуобинская", coord="Point(117.055 65.001)",
         start="2015-01-01T00:00:00Z", typeLabel="рудник"),
]


def _harvest_module():
    spec = importlib.util.spec_from_file_location("harvest_mod", ROOT / "scripts" / "harvest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _meta(layer):
    return _harvest_module().parse_query(ROOT / "queries" / f"{layer}.rq")


# --- заголовки запросов ---------------------------------------------------

def test_both_layers_are_collected_by_country():
    """Рамка `wikibase:box` поверх дерева классов против сервиса не работает."""
    for layer in ("factories", "mines"):
        assert _meta(layer)["scope"] == "country", layer


def test_both_layers_stay_objects_not_events():
    """У завода есть основание и закрытие: даты берутся из P571/P576."""
    for layer in ("factories", "mines"):
        meta = _meta(layer)
        assert meta["kind"] == "object", layer
        sparql = details_query([q for q, _ in meta["qids"]], meta["kind"])
        assert "wdt:P571" in sparql and "wdt:P576" in sparql, layer
        assert "P585" not in sparql, layer


def test_declared_roots_are_in_place():
    """Q-номера корней проверены живой сверкой: «фабрика» и «рудник»."""
    assert "Q83405" in dict(_meta("factories")["qids"])
    assert "Q820477" in dict(_meta("mines")["qids"])


def test_the_two_layers_do_not_declare_the_same_class():
    """Слабая часть проверки на пересечение — та, что видна без сети.

    Настоящее пересечение возникает не от одинакового корня, а от общего
    потомка: класс, лежащий под корнями обоих слоёв, привёл бы одну шахту
    в оба. По дереву это проверено живьём (запросом по `wdt:P279*`, общих
    потомков нет) и на пробе по России: 330 заводов, 414 рудников, общих
    Q-номеров ноль. Здесь остаётся сторож на случай, когда в оба файла
    впишут один и тот же `@qid`.
    """
    factories = {q for q, _ in _meta("factories")["qids"]}
    mines = {q for q, _ in _meta("mines")["qids"]}
    assert factories and mines
    assert not (factories & mines), factories & mines


def test_ids_query_covers_every_declared_class():
    """Первая ступень собирает ровно то, что объявлено директивами @qid."""
    for layer in ("factories", "mines"):
        classes = [q for q, _ in _meta(layer)["qids"]]
        sparql = ids_query(classes, "Q159")
        for qid in classes:
            assert f"wd:{qid}" in sparql, (layer, qid)
        assert "wikibase:box" not in sparql, layer


# --- разбор ответа --------------------------------------------------------

def test_closed_factory_keeps_both_dates():
    rec = rows_to_records(ROWS[:1], FACTORIES)[0]
    assert (rec.year_from, rec.year_to) == (1959, 2011)
    assert rec.date_approx is False
    assert rec.period_raw == "1959–2011"
    assert rec.category == "завод"
    assert rec.region == "Владимирская область"


def test_working_factory_gets_the_upper_bound_of_the_period():
    """Завод основан и не закрыт — иначе он выпал бы из подбора по времени."""
    rec = rows_to_records(ROWS[1:2], FACTORIES)[0]
    assert (rec.year_from, rec.year_to) == (1944, 1960)
    assert rec.date_approx is True


def test_undated_deposit_is_kept():
    """У месторождения P571 обычно нет: датировано 9% слоя.

    Выбрасывать недатированное нельзя — место работы остаётся местом
    работы, а год ему подставит не сбор, а исследователь.
    """
    rec = rows_to_records(ROWS[2:3], MINES)[0]
    assert rec.year_from is None and rec.year_to is None
    assert rec.date_precision == "unknown"
    assert rec.has_point
    assert rec.title == "Агаповское месторождение"


def test_second_p31_does_not_double_the_mine():
    """Рудник — ещё и памятник: P31 многозначен, строк приходит две."""
    recs = rows_to_records(ROWS[3:5], MINES)
    assert len(recs) == 2
    assert len(dedupe(recs)) == 1


def test_mine_outside_the_empire_is_dropped():
    """Витватерсранд — рудник, но не наш: рамка остаётся вторым ситом."""
    assert rows_to_records(ROWS[5:6], MINES) == []


def test_late_mine_does_not_get_an_inverted_period():
    """Регрессия: промысел моложе 1960 года выворачивал интервал наизнанку.

    Открытая дата объекта дотягивается до конца интересующего периода, и
    для рудника 2015 года это давало «год от 2015, год до 1960»: подбор по
    времени не находил его даже в его собственном году, а в выгрузку он всё
    равно попадал — с датировкой, которой не бывает.
    """
    rec = rows_to_records(ROWS[6:7], MINES)[0]
    assert rec.year_from == 2015
    assert rec.year_to >= rec.year_from
    assert rec.overlaps_years(2015, 2015)


def test_whole_sample_parses_into_the_expected_layers():
    factories = dedupe(rows_to_records(ROWS[:2], FACTORIES))
    mines = dedupe(rows_to_records(ROWS[2:], MINES))
    assert [r.layer for r in factories] == ["factories", "factories"]
    assert [r.layer for r in mines] == ["mines", "mines", "mines"]
    assert all(r.url for r in factories + mines)
