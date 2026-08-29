"""Разбор ответа Викиданных о переименованиях населённых мест.

Сети в тестах нет: образец снят с живого ответа второй ступени
(`names_query`) 23.08.2026 и урезан до пяти мест. Значения — названия,
языки, годы, координаты, идентификаторы заявлений — стоят как пришли; узлы
ответа собирает `_node`, иначе файл был бы нечитаем.

Пять мест взяты не случайно, каждое отвечает за свою беду в данных:

* **Верхняя Пышма** — цепочка из трёх названий: Медный Рудник, Пышма,
  Верхняя Пышма. Проверяется, что выходит два переименования, а не одно;
* **Светогорск** — рядом с русским «Энсо» стоит финское «Enso» с тем же
  годом начала. Это одно название на двух языках, а не два названия;
* **Ялта** — переименована в Красноармейск и обратно в пределах 1921 года,
  а украинское и белорусское написания стоят вовсе без дат;
* **Донское** — прежнее название только с датой конца, немецкое написание
  рядом. Год начала неизвестен, и это должно быть видно в записи;
* **Краснознаменск** — Викиданные говорят разом, что Голицыно-2 стал
  Краснознаменском в 1977 году и что он же стал им в 1994-м.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.periods import PRECISION_OPEN  # noqa: E402
from histctx.registry import BY_SLUG  # noqa: E402
from histctx.sources.renamed import (  # noqa: E402
    NAMES_CHUNK_SIZE, chain_language, collect, dedupe, group_rows, ids_query,
    name_chain, names_query, rows_to_records,
)

SPEC = BY_SLUG["renamed_places"]

WD = "http://www.wikidata.org/entity/"


def _node(value, lang=None, kind="literal"):
    node = {"type": kind, "value": value}
    if lang:
        node["xml:lang"] = lang
    return node


def _row(qid, label, coord, admin, type_, statement, prop, name, lang,
         start=None, end=None, article=None):
    """Одна строка ответа SPARQL — так, как её отдаёт сервис."""
    row = {
        "item": _node(WD + qid, kind="uri"),
        "itemLabel": _node(label, "ru"),
        "coord": _node(coord),
        "adminLabel": _node(admin, "ru"),
        "typeLabel": _node(type_, "ru"),
        "st": _node(WD + "statement/" + statement, kind="uri"),
        "prop": _node(WD + prop, kind="uri"),
        "name": _node(name, lang),
    }
    if article:
        row["article"] = _node(article, kind="uri")
    if start:
        row["start"] = _node(start)
    if end:
        row["end"] = _node(end)
    return row


VP = ("Q133037", "Верхняя Пышма", "Point(60.583333333 56.966666666)")
SV = ("Q15306", "Светогорск", "Point(28.858333333 61.108333333)")
YA = ("Q128499", "Ялта", "Point(34.155277777 44.499444444)")
DO = ("Q1014331", "Донское", "Point(19.966666666 54.9375)")
KR = ("Q155615", "Краснознаменск", "Point(37.041666666 55.6)")

ROWS = [
    # Верхняя Пышма: три названия подряд. P131 многозначен — область, уезд и
    # городской округ приходят каждый своей строкой, отсюда повторы.
    *[_row(*VP, admin, "город", "Q133037-9ea898c6", "P1448", "Медный Рудник",
           "ru", "1854-07-06T00:00:00Z", "1938-01-01T00:00:00Z",
           "https://ru.wikipedia.org/wiki/Верхняя_Пышма")
      for admin in ("Свердловская область", "Екатеринбургский уезд",
                    "Городской округ Верхняя Пышма")],
    _row(*VP, "Свердловская область", "город", "Q133037-5d4e0b78", "P1448",
         "Пышма", "ru", "1938-01-01T00:00:00Z", "1946-02-22T00:00:00Z"),
    _row(*VP, "Свердловская область", "административно-территориальная единица России",
         "Q133037-a5e997ab", "P1448", "Верхняя Пышма", "ru", "1946-02-22T00:00:00Z"),

    # Светогорск: «Энсо» и финское «Enso» — одно название, оба с 1887 года.
    _row(*SV, "Светогорское городское поселение", "город", "Q15306-C0AA17D6",
         "P1448", "Энсо", "ru", "1887-01-01T00:00:00Z", "1949-01-01T00:00:00Z"),
    _row(*SV, "Светогорское городское поселение", "город", "Q15306-fa2b7d47",
         "P1448", "Enso", "fi", "1887-01-01T00:00:00Z"),
    _row(*SV, "Светогорское городское поселение", "город", "Q15306-6A025063",
         "P1448", "Светогорск", "ru", "1949-01-01T00:00:00Z"),

    # Ялта: Красноармейском она побыла с января по август 1921 года.
    _row(*YA, "Ялтинский район", "город", "Q128499-0d53a2a0", "P1448",
         "Красноармейск", "ru", "1921-01-20T00:00:00Z", "1921-08-25T00:00:00Z"),
    _row(*YA, "Ялтинский район", "город", "Q128499-156fdf2e", "P1448",
         "Ялта", "ru", "1921-08-25T00:00:00Z"),
    _row(*YA, "Ялтинский район", "город", "Q128499-b1448150", "P1448",
         "Ялта", "uk"),
    _row(*YA, "Ялтинский район", "город", "Q128499-a6a74695", "P1705",
         "Yalta", "crh"),

    # Донское: у прежнего названия известен только год конца.
    _row(*DO, "Светлогорский район", "посёлок городского типа России",
         "Q1014331-78c057a7", "P1448", "Гросс-Диршкайм", "ru",
         end="1946-01-01T00:00:00Z"),
    _row(*DO, "Светлогорский район", "посёлок городского типа России",
         "Q1014331-87c866b9", "P1448", "Groß Dirschkeim", "de",
         end="1946-01-01T00:00:00Z"),
    _row(*DO, "Светлогорский район", "посёлок городского типа России",
         "Q1014331-b5789577", "P1448", "Донское", "ru", "1946-01-01T00:00:00Z"),

    # Краснознаменск: одно и то же переименование записано дважды и с разными
    # годами — 1977 и 1994.
    _row(*KR, "Одинцовский район", "город", "Q155615-1", "P1448",
         "Голицыно-2", "ru", end="1977-01-01T00:00:00Z"),
    _row(*KR, "Одинцовский район", "город", "Q155615-2", "P1448",
         "Краснознаменск", "ru", "1977-01-01T00:00:00Z"),
    _row(*KR, "Одинцовский район", "город", "Q155615-3", "P1448",
         "Голицыно-2", "ru", end="1994-01-01T00:00:00Z"),
    _row(*KR, "Одинцовский район", "город", "Q155615-4", "P1448",
         "Краснознаменск", "ru", "1994-01-01T00:00:00Z"),
]


def records(rows=None, **kwargs):
    return dedupe(rows_to_records(rows if rows is not None else ROWS, SPEC, **kwargs))


def by_title(title, rows=None):
    return [r for r in records(rows) if r.title == title]


def test_chain_of_three_names_gives_two_renamings():
    """Медный Рудник → Пышма → Верхняя Пышма — это два разных факта."""
    got = [r for r in records() if r.source_id.startswith("Q133037:")]
    assert [r.title for r in got] == ["Медный Рудник → Пышма", "Пышма → Верхняя Пышма"]
    assert [(r.year_from, r.year_to) for r in got] == [(1854, 1938), (1938, 1946)]
    assert all(r.mappable and r.usable for r in got)


def test_old_name_is_in_front_and_years_are_the_years_of_that_name():
    """Искать будут по старому названию, и год факта должен попадать в срок."""
    rec = by_title("Медный Рудник → Пышма")[0]
    assert rec.title.startswith("Медный Рудник")
    assert rec.overlaps_years(1899, 1899), "запись 1899 года должна подходить"
    assert not rec.overlaps_years(1940, 1940)
    assert rec.extra["old_name"] == "Медный Рудник"
    assert rec.extra["new_name"] == "Пышма"
    assert rec.extra["renamed_year"] == 1938
    assert rec.summary == ("Медный Рудник: название с 1854 по 1938 год, "
                           "затем Пышма; ныне Верхняя Пышма.")
    assert rec.period_raw == "1854–1938"
    assert rec.date_precision == "year" and not rec.date_approx


def test_place_and_time_are_filled_from_the_answer():
    rec = by_title("Медный Рудник → Пышма")[0]
    assert (round(rec.lat, 4), round(rec.lon, 4)) == (56.9667, 60.5833)
    # Из нескольких значений P131 в губернию идёт то, в котором она узнаётся,
    # а уезд собирается из всех — он и есть рабочая единица поиска в архиве.
    assert rec.region == "Свердловская область"
    assert rec.district == "Екатеринбургский уезд"
    assert rec.category == "город"
    assert rec.url.startswith("https://ru.wikipedia.org/")
    assert rec.layer == "renamed_places" and rec.license.startswith("CC0")


def test_current_name_is_named_when_it_differs_from_the_new_one():
    """Между старым названием и нынешним бывает третье — его надо назвать."""
    rec = by_title("Медный Рудник → Пышма")[0]
    assert rec.extra["current_name"] == "Верхняя Пышма"
    assert "ныне Верхняя Пышма" in rec.summary
    # У последнего переименования нынешнее название и есть новое: повторять
    # его второй раз в описании незачем.
    assert "ныне" not in by_title("Пышма → Верхняя Пышма")[0].summary


def test_foreign_spelling_of_the_same_name_is_not_a_renaming():
    """Финское «Enso» — то же название, что «Энсо», а не следующее за ним."""
    got = [r for r in records() if r.source_id.startswith("Q15306:")]
    assert [r.title for r in got] == ["Энсо → Светогорск"]
    assert got[0].extra["name_variants"] == ["Enso"]
    assert (got[0].year_from, got[0].year_to) == (1887, 1949)


def test_spelling_without_dates_does_not_become_a_name_of_its_own():
    """Украинское и крымскотатарское написания стоят без дат — это варианты."""
    got = [r for r in records() if r.source_id.startswith("Q128499:")]
    assert [r.title for r in got] == ["Красноармейск → Ялта"]
    assert got[0].extra.get("name_variants") is None


def test_name_that_lasted_less_than_a_year_keeps_its_year():
    """Ялта побыла Красноармейском с января по август 1921 года."""
    rec = by_title("Красноармейск → Ялта")[0]
    assert (rec.year_from, rec.year_to) == (1921, 1921)
    assert rec.period_raw == "1921"
    assert rec.summary == "Красноармейск: название 1921 года, затем Ялта."
    assert rec.date_precision == "year"


def test_unknown_beginning_widens_the_interval_and_says_so():
    """Год начала неизвестен — интервал расширяется, а не сужается."""
    rec = by_title("Гросс-Диршкайм → Донское")[0]
    assert (rec.year_from, rec.year_to) == (1800, 1946)
    # Измерен только конец, начало взято из рамки проекта — открытый срок.
    assert rec.date_approx and rec.date_precision == PRECISION_OPEN
    assert rec.period_raw == "до 1946"
    assert rec.extra["name_variants"] == ["Groß Dirschkeim"]


def test_contradicting_years_are_marked_and_kept():
    """Ничего не удаляется молча: спорное помечается и остаётся."""
    got = [r for r in records() if r.source_id.startswith("Q155615:")]
    assert len(got) == 2
    assert {r.confidence for r in got} == {"dates_disputed"}
    assert {r.extra["renamed_year"] for r in got} == {1977, 1994}
    assert all(r.confidence == "ok"
               for r in records() if not r.source_id.startswith("Q155615:"))


def test_renaming_back_and_forth_is_not_a_contradiction():
    """Прикумск становился Будённовском дважды — и оба раза по-настоящему."""
    rows = [
        _row("Q141975", "Будённовск", "Point(44.15 44.783)", "Ставропольский край",
             "город", "Q141975-1", "P1448", "Прикумск", "ru",
             "1921-01-01T00:00:00Z", "1935-01-01T00:00:00Z"),
        _row("Q141975", "Будённовск", "Point(44.15 44.783)", "Ставропольский край",
             "город", "Q141975-2", "P1448", "Будённовск", "ru",
             "1935-01-01T00:00:00Z", "1957-01-01T00:00:00Z"),
        _row("Q141975", "Будённовск", "Point(44.15 44.783)", "Ставропольский край",
             "город", "Q141975-3", "P1448", "Прикумск", "ru",
             "1957-01-01T00:00:00Z", "1973-01-01T00:00:00Z"),
        _row("Q141975", "Будённовск", "Point(44.15 44.783)", "Ставропольский край",
             "город", "Q141975-4", "P1448", "Будённовск", "ru",
             "1973-01-01T00:00:00Z"),
    ]
    got = records(rows)
    assert [r.period_raw for r in got] == ["1921–1935", "1935–1957", "1957–1973"]
    assert all(r.confidence == "ok" for r in got)


def test_duplicated_rows_do_not_double_the_record():
    """Многозначные P131 и P31 множат строки — записей от этого не прибавляется."""
    assert len(records(ROWS + ROWS)) == len(records())
    assert len({r.uid for r in records()}) == len(records())


def test_place_outside_the_country_is_skipped():
    rows = [_row("Q1", "Ла-Плата", "Point(-57.95 -34.92)", "Буэнос-Айрес", "город",
                 "Q1-1", "P1448", "Тольоса", "ru", end="1900-01-01T00:00:00Z")]
    assert records(rows) == []
    assert len(records(rows, require_bbox=False)) == 1


def test_place_without_a_second_name_gives_nothing():
    """Одно название и никакого преемника — переименования нет."""
    rows = [_row("Q2", "Кириллов", "Point(38.38 59.86)", "Вологодская область",
                 "город", "Q2-1", "P1448", "Кириллов", "ru", "1776-01-01T00:00:00Z")]
    assert records(rows) == []


def test_the_language_of_the_chain_is_russian_when_there_is_one():
    statements = list(group_rows(ROWS)["Q15306"].statements.values())
    assert chain_language(statements) == "ru"
    assert [link["name"] for link in name_chain(statements)] == ["Энсо", "Светогорск"]


def test_the_chain_falls_back_to_the_language_that_is_there():
    """Названий по-русски нет вовсе — цепочка строится по тому, что есть."""
    rows = [
        _row("Q3", "Rapla", "Point(24.79 58.99)", "Рапламаа", "город",
             "Q3-1", "P1448", "Rappel", "et", end="1938-01-01T00:00:00Z"),
        _row("Q3", "Rapla", "Point(24.79 58.99)", "Рапламаа", "город",
             "Q3-2", "P1448", "Rapla", "et", "1938-01-01T00:00:00Z"),
    ]
    assert chain_language(list(group_rows(rows)["Q3"].statements.values())) == "et"
    assert [r.title for r in records(rows)] == ["Rappel → Rapla"]


def test_one_russian_name_without_dates_does_not_erase_a_foreign_chain():
    """На прибалтийской карточке русское название стоит почти всегда.

    Если предпочесть русский язык по одному его наличию, датированная
    эстонская цепочка уйдёт в варианты, и место молча выпадет из слоя.
    """
    rows = [
        _row("Q3", "Rapla", "Point(24.79 58.99)", "Рапламаа", "город",
             "Q3-0", "P2561", "Рапла", "ru"),
        _row("Q3", "Rapla", "Point(24.79 58.99)", "Рапламаа", "город",
             "Q3-1", "P1448", "Rappel", "et", end="1938-01-01T00:00:00Z"),
        _row("Q3", "Rapla", "Point(24.79 58.99)", "Рапламаа", "город",
             "Q3-2", "P1448", "Rapla", "et", "1938-01-01T00:00:00Z"),
    ]
    assert chain_language(list(group_rows(rows)["Q3"].statements.values())) == "et"
    assert [r.title for r in records(rows)] == ["Rappel → Rapla"]


def test_name_without_dates_is_the_present_one_and_not_the_first():
    """«Волгоград» без дат — нынешнее название, а не бывшее до Царицына.

    Заявление без дат сортируется в конец цепочки. Поставленное в начало,
    оно порождает переименование, которого никогда не было:
    «Волгоград → Царицын, до 1589 года».
    """
    place = ("Q914", "Волгоград", "Point(44.516667 48.716667)")
    rows = [
        _row(*place, "Волгоградская область", "город", "Q914-0", "P2561",
             "Волгоград", "ru"),
        _row(*place, "Волгоградская область", "город", "Q914-1", "P1448",
             "Царицын", "ru", "1589-01-01T00:00:00Z", "1925-04-10T00:00:00Z"),
        _row(*place, "Волгоградская область", "город", "Q914-2", "P1448",
             "Сталинград", "ru", "1925-04-10T00:00:00Z", "1961-11-10T00:00:00Z"),
        _row(*place, "Волгоградская область", "город", "Q914-3", "P1448",
             "Волгоград", "ru", "1961-11-10T00:00:00Z"),
    ]
    got = records(rows)
    assert [r.title for r in got] == ["Царицын → Сталинград", "Сталинград → Волгоград"]
    assert [(r.year_from, r.year_to) for r in got] == [(1589, 1925), (1925, 1961)]
    assert got[0].region == "Волгоградская область"


def test_two_names_ending_in_one_year_stay_two_names():
    """Ялта кончилась 20 января 1921 года, Красноармейск — 25 августа того же.

    Свести их в одно звено по общему году конца значит потерять первое
    переименование и приписать Красноармейску чужой срок.
    """
    rows = [
        _row(*YA, "Ялтинский район", "город", "Q128499-x", "P1448", "Ялта", "ru",
             "1838-01-01T00:00:00Z", "1921-01-20T00:00:00Z"),
        _row(*YA, "Ялтинский район", "город", "Q128499-0d53a2a0", "P1448",
             "Красноармейск", "ru", "1921-01-20T00:00:00Z", "1921-08-25T00:00:00Z"),
        _row(*YA, "Ялтинский район", "город", "Q128499-156fdf2e", "P1448",
             "Ялта", "ru", "1921-08-25T00:00:00Z"),
    ]
    got = records(rows)
    assert [r.title for r in got] == ["Ялта → Красноармейск", "Красноармейск → Ялта"]
    assert [r.period_raw for r in got] == ["1838–1921", "1921"]


def test_republic_beats_a_municipal_district_in_the_region_field():
    """Подбор контекста идёт по республике и области, а не по городскому округу."""
    rows = [
        _row("Q4", "Адыгейск", "Point(39.19 44.88)", "Республика Адыгея", "город",
             "Q4-1", "P1448", "Теучежск", "ru", end="1990-01-01T00:00:00Z"),
        _row("Q4", "Адыгейск", "Point(39.19 44.88)", "Городской округ Адыгейск",
             "город", "Q4-1", "P1448", "Теучежск", "ru", end="1990-01-01T00:00:00Z"),
    ]
    rec = records(rows)[0]
    assert rec.region == "Республика Адыгея"
    assert rec.title == "Теучежск → Адыгейск"


def test_second_coordinate_does_not_move_the_record():
    """У места бывает два значения P625; выбор не должен зависеть от порядка строк."""
    rows = [
        _row("Q5", "Донское", "Point(19.966666666 54.9375)", "Светлогорский район",
             "посёлок", "Q5-1", "P1448", "Гросс-Диршкайм", "ru",
             end="1946-01-01T00:00:00Z"),
        _row("Q5", "Донское", "Point(19.97 54.94)", "Светлогорский район",
             "посёлок", "Q5-1", "P1448", "Гросс-Диршкайм", "ru",
             end="1946-01-01T00:00:00Z"),
    ]
    straight = records(rows)
    reversed_ = records(list(reversed(rows)))
    assert len(straight) == 1
    assert [r.uid for r in straight] == [r.uid for r in reversed_]
    assert (straight[0].lat, straight[0].lon) == (54.9375, 19.966666666)


def test_queries_ask_for_what_the_parsing_needs():
    """Запрос и разбор должны говорить об одном и том же."""
    ids = ids_query("Q159")
    assert "wd:Q159" in ids and "pq:P582" in ids and "DISTINCT" in ids
    # Первая ступень должна оставаться дешёвой: ни классов, ни меток.
    assert "wdt:P279*" not in ids and "wikibase:label" not in ids

    names = names_query(["Q133037", "Q15306"])
    assert "wd:Q133037" in names and "wd:Q15306" in names
    for part in ("pq:P580", "pq:P582", "wikibase:claim", "wikibase:statementProperty",
                 "FILTER EXISTS", "wd:Q486972"):
        assert part in names, part
    assert NAMES_CHUNK_SIZE <= 1000


class _FakeClient:
    """Клиент SPARQL без сети: отвечает на первую ступень и на вторую."""

    def __init__(self, ids, rows):
        self.ids, self.rows, self.asked = ids, rows, []

    def query(self, sparql, use_cache=True):
        self.asked.append(sparql)
        if sparql.startswith("SELECT DISTINCT ?item"):
            return [{"item": _node(WD + qid, kind="uri")} for qid in self.ids]
        return self.rows


def test_two_stage_collection_asks_the_second_stage_about_the_first():
    """Ступени должны быть связаны: чем ответила первая, о том спрашивает вторая."""
    client = _FakeClient(["Q133037", "Q15306"], ROWS)
    got = collect(client, SPEC, countries=(("Q159", "Россия"),), chunk_size=500)
    assert len(client.asked) == 2
    assert "wd:Q159" in client.asked[0]
    assert "wd:Q133037" in client.asked[1] and "wd:Q15306" in client.asked[1]
    assert [r.title for r in got][:3] == [
        "Медный Рудник → Пышма", "Пышма → Верхняя Пышма", "Энсо → Светогорск"]
    assert len({r.uid for r in got}) == len(got)


def test_probe_takes_only_the_first_places():
    """Проба не должна ходить за подробностями по всему списку."""
    client = _FakeClient(["Q133037", "Q15306"], ROWS)
    collect(client, SPEC, countries=(("Q159", "Россия"),), max_objects=1)
    assert "wd:Q15306" not in client.asked[1]


def test_layer_is_described_in_registry():
    assert "renamed_places" in BY_SLUG
    assert SPEC.group == "admin" and SPEC.source == "Викиданные"
