"""Слой мест репрессий: заголовок запроса и разбор ответа.

Сети в тестах нет: образец ответа — константа ниже, снята с пробы
`python3 scripts/harvest.py --probe --layer repressions` и урезана до
четырёх объектов.

Проверяется не только разбор. Главное в этом слое — граница с уже собранным
`gulag_camps`: лагерь есть там, здесь его быть не должно. Граница держится не
сверкой после сбора (у записей `gulag_camps` нет Q-номеров, сверять нечем), а
выбором классов до него — и вот это тесты и стерегут.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.registry import BY_SLUG  # noqa: E402
from histctx.sources.wikidata import ids_query, rows_to_records  # noqa: E402

QUERY = ROOT / "queries" / "repressions.rq"

# Классы лагерей: их собирает «Карта ГУЛАГа», и в этом слое им не место.
CAMP_CLASSES = ("Q2403977", "Q152081")


def _meta():
    spec = importlib.util.spec_from_file_location("harvest_mod", ROOT / "scripts" / "harvest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_query(QUERY)


def _row(**kw):
    return {k: {"value": v} for k, v in kw.items() if v is not None}


# Образец ответа второй ступени: тюрьма с открытой датировкой, тюрьма с
# обеими датами, расстрельный полигон и урочище за пределами России.
ROWS = [
    _row(item="http://www.wikidata.org/entity/Q190595",
         itemLabel="Орловский централ",
         coord="Point(36.0651 52.9789)",
         start="1840-01-01T00:00:00Z",
         adminLabel="Орловская область",
         typeLabel="тюрьма",
         description="тюрьма в Орле"),
    _row(item="http://www.wikidata.org/entity/Q1128882",
         itemLabel="Сухановская особорежимная тюрьма",
         coord="Point(37.6660 55.5370)",
         start="1938-01-01T00:00:00Z",
         end="1953-01-01T00:00:00Z",
         adminLabel="Московская область",
         typeLabel="тюрьма"),
    _row(item="http://www.wikidata.org/entity/Q1018007",
         itemLabel="Бутовский полигон",
         coord="Point(37.5947 55.5311)",
         adminLabel="Москва",
         typeLabel="братская могила",
         description="место массовых расстрелов жертв политических репрессий"),
    _row(item="http://www.wikidata.org/entity/Q9708",
         itemLabel="Куропаты",
         coord="Point(27.6478 53.9989)",
         typeLabel="место массового убийства",
         description="массовые захоронения репрессированных во время Большого террора"),
]


# --- заголовок запроса ----------------------------------------------------

def test_header_declares_country_scope_and_object_kind():
    """Сбор в две ступени, датировка — как у объекта.

    Тюрьма и полигон существуют во времени: у них P571/P576, и открытый конец
    у них осмыслен. Депортация — событие, но в слой она не идёт вовсе: у неё
    нет координаты. См. пояснение в заголовке `queries/repressions.rq`.
    """
    meta = _meta()
    assert meta["layer"] == "repressions"
    assert meta["scope"] == "country"
    assert meta["kind"] == "object"
    assert meta["qids"], "не объявлен ни один класс"


def test_camp_classes_are_not_declared():
    """Лагеря собраны «Картой ГУЛАГа» — повторять их отсюда нельзя."""
    declared = {qid for qid, _ in _meta()["qids"]}
    assert declared.isdisjoint(CAMP_CLASSES), declared & set(CAMP_CLASSES)


def test_stage_one_query_shuts_the_door_on_camps():
    """Мало не объявить класс лагеря: элемент бывает и тюрьмой, и лагерем сразу.

    Такой элемент пришёл бы через дерево подклассов тюрьмы, поэтому запрет
    стоит явной строкой в первой ступени.
    """
    meta = _meta()
    query = ids_query([qid for qid, _ in meta["qids"]], "Q159", meta["filters"])
    assert "FILTER NOT EXISTS" in query
    assert "wd:Q2403977" in query


def test_mass_graves_are_sifted_by_words_about_repression():
    """Братских могил в наших границах тысячи, и почти все — воинские.

    Взять класс целиком значило бы подменить слой репрессий слоем солдатских
    захоронений, поэтому у Q734271 стоит словесное сито. Сито касается только
    его: тюрьма нужна любая.
    """
    filters = " ".join(_meta()["filters"])
    assert "wd:Q734271" in filters
    assert "REGEX" in filters
    for word in ("репресс", "террор", "расстрел"):
        assert word in filters, word
    assert "wd:Q40357" not in filters, "тюрьмы просеивать не нужно"


def test_filter_relies_on_the_engine_variable_cls():
    """Сито держится на переменной `?cls`, и это надо стеречь.

    Её объявляет движок строкой `VALUES ?cls` в `ids_query`. Переименуй он
    её — SPARQL не упадёт: сравнение с несвязанной переменной даёт ошибку,
    `ошибка || EXISTS{…}` даёт ложь, и сито расширится со «братских могил» на
    все классы разом. Слой при этом соберётся, просто окажется вчетверо
    меньше и без тюрем — поломка, которую видно только глазами.
    """
    assert "VALUES ?cls" in ids_query(["Q40357"], "Q159")


# --- разбор ответа --------------------------------------------------------

def test_sample_rows_become_records():
    recs = rows_to_records(ROWS, BY_SLUG["repressions"])
    assert [r.title for r in recs] == [
        "Орловский централ", "Сухановская особорежимная тюрьма",
        "Бутовский полигон", "Куропаты",
    ]
    assert all(r.layer == "repressions" for r in recs)
    assert all(r.url and r.source_id for r in recs)


def test_prison_that_was_never_closed_reaches_the_end_of_the_period():
    """Тюрьма 1840 года стояла и в 1930-м — иначе она выпадет из подбора."""
    rec = rows_to_records(ROWS, BY_SLUG["repressions"])[0]
    assert (rec.year_from, rec.year_to) == (1840, 1960)
    assert rec.date_approx is True


def test_prison_with_both_dates_keeps_them():
    rec = rows_to_records(ROWS, BY_SLUG["repressions"])[1]
    assert (rec.year_from, rec.year_to) == (1938, 1953)


def test_place_without_dates_stays_in_the_layer():
    """У полигона дат в Викиданных нет, но точка на карте от этого не лишняя.

    Запись остаётся и помечается отсутствием датировки — выбрасывать её
    нечего ради: без неё на месте Бутова была бы пустота.
    """
    rec = rows_to_records(ROWS, BY_SLUG["repressions"])[2]
    assert rec.year_from is None and rec.year_to is None
    assert rec.has_time is False
    assert rec.date_precision == "unknown"


def _gulag_features():
    path = ROOT / "data" / "out" / "geojson" / "gulag_camps.geojson"
    if not path.exists():  # pragma: no cover — слой пересобирается отдельно
        return []
    return [f for f in json.loads(path.read_text(encoding="utf-8"))["features"]
            if f.get("geometry", {}).get("type") == "Point"]


def test_layers_do_not_share_objects():
    """Ни одна запись не ведёт на «Карту ГУЛАГа»: источники не пересекаются.

    Это и есть вся защита от дубля — она стоит до сбора, в выборе классов,
    а не после него.
    """
    for rec in rows_to_records(ROWS, BY_SLUG["repressions"]):
        assert "gulagmap.ru" not in (rec.url or ""), rec.title
        assert "икиданны" in rec.source or "ikidata" in rec.source.lower(), rec.source


def test_a_shared_coordinate_is_not_a_duplicate():
    """Совпадение точки с `gulag_camps` бывает — и дублем не является.

    В Орле лагерь принудительных работ 1919–1922 годов помещался в здании
    губернской каторжной тюрьмы, поэтому «Карта ГУЛАГа» и Викиданные дают
    почти одну и ту же точку. Записи при этом разные: тюрьма стоит с 1840
    года, лагерное управление занимало её три года. Выбрасывать вторую по
    совпадению координаты нельзя — потеряется ровно то, ради чего слои и
    собраны: одна запись объясняет здание, другая этап.

    Тест сторожит не отсутствие совпадений, а то, что совпавшие записи
    остаются различимыми: у них разные источники, ссылки и сроки.
    """
    features = _gulag_features()
    if not features:  # pragma: no cover
        return
    rec = rows_to_records(ROWS, BY_SLUG["repressions"])[0]
    near = [f for f in features
            if abs(f["geometry"]["coordinates"][1] - rec.lat) < 0.01
            and abs(f["geometry"]["coordinates"][0] - rec.lon) < 0.01]
    assert near, "образец подобран так, чтобы совпадение было видно"
    for f in near:
        props = f["properties"]
        assert props["url"] != rec.url
        assert props["source"] != rec.source
        assert props["title"] != rec.title


# --- права ----------------------------------------------------------------

def test_rights_are_named_not_postponed():
    """Слой собирается из одних Викиданных, значит лицензия у него одна — CC0.

    Пока в `registry.py` стояло «уточняется по каждому источнику», это была
    не осторожность, а отложенное решение: источник в итоге один.
    """
    spec = BY_SLUG["repressions"]
    assert "CC0" in spec.license
    assert "уточня" not in spec.license.lower()
