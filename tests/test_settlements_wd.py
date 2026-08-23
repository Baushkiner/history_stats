"""Населённые места из Викиданных как второй источник к слою GeoNames.

Сети в тестах нет: образец ответа — константа ниже, снята с второй ступени
сбора (`details_query`) и урезана до трёх объектов.

Проверяется не столько разбор, сколько развод двух источников с одним
названием. Слой `settlements` уже собран из GeoNames и лежит в
`data/out/geojson/settlements.geojson`; запрос к Викиданным раньше объявлял
тот же slug — и сбор по нему затёр бы собранный файл, а записям проставил бы
лицензию GeoNames вместо CC0. Тесты держат границу: slug разный, права
разные, датировка на месте.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.registry import BY_SLUG  # noqa: E402
from histctx.sources.wikidata import ids_query, rows_to_records  # noqa: E402

QUERY = ROOT / "queries" / "settlements_wd.rq"

# Образец ответа второй ступени: село с годом основания, город с основанием
# и упразднением (вошёл в черту другого) и объект с двумя значениями P31 —
# такие строки множатся и схлопываются дедупликацией по Q-номеру.
ROWS = [
    {
        "item": {"value": "http://www.wikidata.org/entity/Q1770"},
        "itemLabel": {"value": "Кимры"},
        "coord": {"value": "Point(37.35 56.87)"},
        "start": {"value": "1546-01-01T00:00:00Z"},
        "adminLabel": {"value": "Тверская область"},
        "typeLabel": {"value": "город"},
        "description": {"value": "город в Тверской области России"},
    },
    {
        "item": {"value": "http://www.wikidata.org/entity/Q2079"},
        "itemLabel": {"value": "Молога"},
        "coord": {"value": "Point(38.75 58.2)"},
        "start": {"value": "1149-01-01T00:00:00Z"},
        "end": {"value": "1940-01-01T00:00:00Z"},
        "adminLabel": {"value": "Ярославская губерния"},
        "typeLabel": {"value": "город"},
    },
    {
        "item": {"value": "http://www.wikidata.org/entity/Q2079"},
        "itemLabel": {"value": "Молога"},
        "coord": {"value": "Point(38.75 58.2)"},
        "start": {"value": "1149-01-01T00:00:00Z"},
        "end": {"value": "1940-01-01T00:00:00Z"},
        "adminLabel": {"value": "Ярославская губерния"},
        "typeLabel": {"value": "затопленный населённый пункт"},
    },
]


def _meta():
    spec = importlib.util.spec_from_file_location("harvest_mod", ROOT / "scripts" / "harvest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_query(QUERY)


def test_query_declares_its_own_layer():
    """Запрос не должен писать в слой GeoNames: файл по slug'у один."""
    meta = _meta()
    assert meta["layer"] == "settlements_wd"
    assert meta["layer"] != BY_SLUG["settlements"].slug
    others = {p.stem for p in (ROOT / "queries").glob("*.rq")}
    assert "settlements" not in others, "запрос с таким именем снова затрёт слой GeoNames"


def test_two_sources_keep_their_own_rights():
    """Условие 3 каталога: у записи стоит её собственный источник и лицензия."""
    geonames, wikidata = BY_SLUG["settlements"], BY_SLUG["settlements_wd"]
    assert "GeoNames" in geonames.source and "икиданны" in wikidata.source
    assert geonames.license != wikidata.license
    assert "CC0" in wikidata.license


def test_query_asks_for_a_founding_date():
    """Слой нужен ради датировки — без P571 запись здесь не нужна вовсе."""
    meta = _meta()
    assert meta["scope"] == "country", "рамка РИ/СССР против живого сервиса не выполняется"
    assert any("wdt:P571" in f for f in meta["filters"]), "не задано требование даты"
    assert any("1960" in f for f in meta["filters"]), "нет верхней границы периода"


def test_class_stays_narrower_than_human_settlement():
    """Регрессия: класс «населённый пункт» целиком сервис не отдаёт.

    Замеры 23.08.2026 по России: с требованием P571 ответ обрывается на
    25 367-й строке, с подсказкой оптимизатору — 504, без замыкания по
    подклассам — 502. Слой собирается по узкому классу, и вернуть сюда
    Q486972 значит снова получить пустой слой. Подробности — в заголовке
    самого запроса.
    """
    classes = [q for q, _ in _meta()["qids"]]
    assert classes, "не объявлен ни один класс"
    assert "Q486972" not in classes, "широкий класс не собирается — см. заголовок запроса"


def test_first_stage_binds_start_itself():
    """Первая ступень `?start` не связывает: обе строки идут из `@filter`."""
    query = ids_query([q for q, _ in _meta()["qids"]], "Q159", _meta()["filters"])
    assert "wdt:P571 ?start" in query
    assert "FILTER(YEAR(?start) <= 1960)" in query
    # Дешевизна первой ступени — условие её выполнимости.
    assert "OPTIONAL" not in query and "SERVICE" not in query


def test_records_carry_the_year_and_the_wikidata_licence():
    recs = rows_to_records(ROWS, BY_SLUG["settlements_wd"])
    assert len(recs) == 3
    assert all(r.year_from for r in recs), "запись без года основания слою не нужна"
    assert all(r.layer == "settlements_wd" for r in recs)
    assert all("CC0" in r.license for r in recs)

    kimry = next(r for r in recs if r.title == "Кимры")
    # Место основано и не упразднено — существует до конца интересующего периода.
    assert (kimry.year_from, kimry.year_to) == (1546, 1960)
    mologa = next(r for r in recs if r.title == "Молога")
    assert (mologa.year_from, mologa.year_to) == (1149, 1940)
    assert mologa.period_raw == "1149–1940"


def test_coordinate_and_title_are_there_to_merge_with_geonames():
    """Сводить два слоя нечем, если у записи нет ни точки, ни названия."""
    for rec in rows_to_records(ROWS, BY_SLUG["settlements_wd"]):
        assert rec.lat and rec.lon
        assert rec.title and not rec.title.startswith("Q")
