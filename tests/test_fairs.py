"""Слой «Ярмарки и торги»: заголовок запроса и разбор ответа.

Сети в тестах нет: образец — четыре строки, снятые с живой пробы
`python3 scripts/harvest.py --probe --layer fairs` 23.08.2026 и урезанные до
нужных полей. Взяты нарочно разные случаи: ярмарка с датой, гостиный двор
XVII века, торговое здание без даты и объект, у которого класс говорит одно,
а название другое.

Главное, что здесь удерживается, — директива `@filter ?item wdt:P31 ?cls`.
Без неё первая ступень идёт через `wdt:P279*`, а замыкание по классу
«ярмарка» живой сервис не выполняет: 504 через 65 секунд. Тест не ходит в
сеть и проверить время не может, поэтому проверяет причину: что запрос
первой ступени по-прежнему прижат к прямому классу.
"""

import importlib.util
from pathlib import Path

from histctx.registry import BY_SLUG
from histctx.sources.wikidata import (
    OPEN_END_YEAR, dedupe, ids_query, rows_to_records,
)

ROOT = Path(__file__).resolve().parents[1]

QUERY = ROOT / "queries" / "fairs.rq"

# Образец ответа второй ступени (details_query), урезанный до полей, которые
# читает rows_to_records.
ROWS = [
    {
        "item": {"value": "http://www.wikidata.org/entity/Q2371326"},
        "itemLabel": {"value": "Нижегородская ярмарка"},
        "coord": {"value": "Point(43.960930555 56.328433333)"},
        "start": {"value": "1817-01-01T00:00:00Z"},
        "adminLabel": {"value": "Нижний Новгород"},
        # У ярмарки несколько значений P31, и первым приходит совсем не то,
        # ради чего она собрана. Название и ссылка важнее ярлыка класса.
        "typeLabel": {"value": "бизнес-центр"},
        "article": {"value": "https://ru.wikipedia.org/wiki/Нижегородская_ярмарка"},
        "description": {"value": "Бывший торговый центр Российской империи."},
    },
    {
        "item": {"value": "http://www.wikidata.org/entity/Q4146500"},
        "itemLabel": {"value": "Гостиный двор (Архангельск)"},
        "coord": {"value": "Point(40.511111111 64.539166666)"},
        "start": {"value": "1684-01-01T00:00:00Z"},
        "adminLabel": {"value": "Архангельск"},
        "typeLabel": {"value": "памятник архитектуры"},
        "article": {"value": "https://ru.wikipedia.org/wiki/Гостиный_двор_(Архангельск)"},
    },
    # Тот же объект второй строкой: у него два значения P31, и ступень
    # подробностей возвращает его дважды.
    {
        "item": {"value": "http://www.wikidata.org/entity/Q4146500"},
        "itemLabel": {"value": "Гостиный двор (Архангельск)"},
        "coord": {"value": "Point(40.511111111 64.539166666)"},
        "start": {"value": "1684-01-01T00:00:00Z"},
        "adminLabel": {"value": "Архангельск"},
        "typeLabel": {"value": "гостиный двор"},
    },
    {
        "item": {"value": "http://www.wikidata.org/entity/Q104542621"},
        "itemLabel": {"value": "Ярмарочные гуляния на Адмиралтейском лугу"},
        "coord": {"value": "Point(30.309444444 59.936944444)"},
        "adminLabel": {"value": "Санкт-Петербург"},
        "typeLabel": {"value": "ярмарка"},
    },
]


_META = None


def _meta():
    """Разбирает заголовок один раз: `harvest.py` при загрузке правит sys.path."""
    global _META
    if _META is None:
        spec = importlib.util.spec_from_file_location(
            "harvest_mod", ROOT / "scripts" / "harvest.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _META = mod.parse_query(QUERY)
    return _META


def test_header_declares_the_classes_that_were_verified_live():
    meta = _meta()
    assert meta["layer"] == "fairs"
    assert meta["scope"] == "country"
    # Здание, а не событие: у гостиного двора и крытого рынка даты лежат
    # в P571/P576.
    assert meta["kind"] == "object"
    assert dict(meta["qids"]) == {
        "Q288514": "ярмарка",
        "Q2386997": "гостиный двор",
        "Q2080521": "крытый рынок",
    }


def test_first_stage_is_pinned_to_the_direct_class():
    """Регрессия: без прижатия к прямому классу сбор упирается в лимит.

    Замыкание `wdt:P279*` по «ярмарке» уводит в дерево нынешних выставок и
    мероприятий; 23.08.2026 первая ступень по одной России отдала 504 через
    65 секунд, а тот же запрос без «ярмарки» прошёл за доли секунды.
    """
    meta = _meta()
    sparql = ids_query([q for q, _ in meta["qids"]], "Q159", meta["filters"])
    assert "?item wdt:P31 ?cls ." in sparql
    # Замыкание из шаблона никуда не делось — прижатие работает поверх него.
    assert "wdt:P31/wdt:P279* ?cls" in sparql


def test_first_stage_drops_what_was_founded_after_the_period():
    """Рынок 1989 года получил бы границы «с 1989 по 1960» — перевёрнутые.

    Открытый конец у объекта дотягивается до `OPEN_END_YEAR`, поэтому позднее
    основание отсекается на первой ступени. Объект без даты основания
    остаётся: неизвестная дата — не поздняя дата.
    """
    meta = _meta()
    sparql = ids_query([q for q, _ in meta["qids"]], "Q159", meta["filters"])
    assert "OPTIONAL { ?item wdt:P571 ?founded . }" in sparql
    assert "!BOUND(?founded)" in sparql
    # Порог берётся из движка, а не переписывается числом: разъедутся — запрос
    # будет резать по одному году, а разбор дотягивать до другого.
    assert f"YEAR(?founded) <= {OPEN_END_YEAR}" in sparql
    # «Дата неизвестна» приходит из Викиданных пустым узлом, `YEAR()` на нём
    # даёт ошибку, а ошибка в SPARQL отбрасывает строку — то есть молча
    # выкидывала бы как раз тот случай, который мы договорились оставлять.
    assert "!isLiteral(?founded)" in sparql


def test_sample_response_becomes_records():
    spec = BY_SLUG["fairs"]
    records = dedupe(rows_to_records(ROWS, spec))
    assert len(records) == 3, "объект с двумя значениями P31 должен остаться одним"

    by_id = {r.source_id: r for r in records}
    fair = by_id["Q2371326"]
    assert fair.layer == "fairs"
    assert fair.year_from == 1817
    # Ярмарка не упразднена — существует до конца интересующего периода.
    assert fair.year_to == OPEN_END_YEAR
    assert fair.date_approx is True
    assert fair.region == "Нижний Новгород"
    assert round(fair.lat, 3) == 56.328 and round(fair.lon, 3) == 43.961

    dvor = by_id["Q4146500"]
    assert dvor.year_from == 1684
    assert dvor.url.startswith("https://ru.wikipedia.org/")


def test_undated_trade_place_survives_with_a_coordinate():
    """Без даты запись всё равно нужна: место торга на карте — уже ответ."""
    spec = BY_SLUG["fairs"]
    records = {r.source_id: r for r in rows_to_records(ROWS, spec)}
    guliania = records["Q104542621"]
    assert guliania.year_from is None and guliania.year_to is None
    assert guliania.date_precision == "unknown"
    assert guliania.lat is not None and guliania.lon is not None
    # Ссылки на статью у объекта нет — остаётся ссылка на Викиданные.
    assert guliania.url == "https://www.wikidata.org/wiki/Q104542621"


def test_layer_is_registered_with_a_measured_estimate():
    """Оценка объёма у этого слоя не круглая цифра, а живой счёт."""
    spec = BY_SLUG["fairs"]
    assert spec.title == "Ярмарки и торги"
    assert spec.group == "economy"
    assert 40 <= spec.expected_rows <= 200, spec.expected_rows
