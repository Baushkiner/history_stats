"""Разбор справочника «Освобождение городов» (1985) с soldat.ru.

Сети в тестах нет: страница собрана из настоящих статей справочника, урезанных
до первых строк перечня частей, и закодирована в cp1251, как на сайте. В ней
все трудные случаи, найденные при разборе шести страниц: три периода у
Барвенкова, «Частично захвачен к …» у Наро-Фоминска, две части Риги,
«Оккупирована»/«Освобождена» у станицы, опечатка «Оккупиройан», статья «БАР»
без выделения, статья «БЕЛЫЙ», склеенная с концом «БЕЛЬЦЫ», взятый город
Восточной Пруссии, освобождённый без даты оккупации город Закарпатья,
пометки области и «ныне часть». Кандидаты в точку — строки ответа SPARQL
и объекты GeoNames, написанные вручную.
"""

import datetime as dt

import pytest

from histctx.schema import SCOPE_POINT
from histctx.sources.occupation import (
    CATEGORY_CAPTURE, CATEGORY_LIBERATION, CATEGORY_OCCUPATION, CATEGORY_PARTIAL,
    EXPECTED_HEADINGS, OCCUPATION_CITIES, PAGES, City, Entry, OccupationError, ParsedEntry,
    by_clause, candidates_from_rows, check_chronicle, check_grunewald, check_headings,
    chronicle, geonames_index, grunewald_status, latin_key, lookup_names, name_variants,
    nominatives, page_text, parse_entry, parse_pages, period_records, periods, place_city,
    see_reference, split_entries, title_case,
)

PAGE = """<html><head><title>Освобождение городов</title></head><body>
<p>&nbsp;</p>
<h1>Освобождение городов</h1>
<h2>СССР</h2>
<table><tr><td><div align="center"><b>А - В</b></div></td></tr></table>
<p><font size="+1">АБРЕНЕ (ПЫТАЛОВО)</font>. Оккупирован 5 июля 1941 г. Освобожден
  22 июля 1944 г. войсками 3 ПрибФ в ходе Псковско-Островской операции:<br>
  <b>54 А</b> - 123 ск (генерал-майор Вержбицкий Виктор Антонович) в составе:
  56 сд (генерал-майор Буньков Степан Михайлович).</p>
<p><font size="+1">БАРВЕНКОВО</font>. Оккупирован 24 октября 1941 г. Освобожден 23 января
  1942 г. войсками ЮЗФ в ходе Барвенково-Лозовской операции: 57 А - 351 сд.
  Оккупирован 18 мая 1942 г. Освобожден 6 февраля 1943 г. войсками ЮЗФ в ходе
  Донбасской операции: 6 А. Оккупирован 28 февраля 1943 г. Освобожден 10 сентября
  1943 г. войсками ЮЗФ в ходе Донбасской операции: 6 А.</p>
<p>БАР. Оккупирован 16 июля 1941 г. Освобожден 25 марта 1944 г. войсками 1 УФ в ходе
  Проскуровско-Черновицкой операции: 38 А - 305 сд (полковник Васильев Александр).</p>
<p><font size="+1">БЕЛЬЦЫ</font>. Оккупирован 7 июля 1941 г. Освобожден 26 марта 1944 г.
  войсками 2 УФ в ходе Уманско-Ботошанской операции: 52 А. Войскам, участвовавшим
  в боях, объявлена благодарность и в Москве дан салют 24 артиллерийскими залпами
  из 324 орудий-БЕЛЫЙ. Оккупирован 4 октября 1941 г. Освобожден 10 марта 1943 г.
  войсками КалФ в ходе Ржевско-Вяземской операции: 41 А - 93 сд.</p>
<p><font size="+1">БЕРЕГОВО</font>. Освобожден 26 октября 1944 г. войсками 4 УФ в ходе
  Карпатско-Ужгородской операции: 17 гв. ск (генерал-майор Гастилович Антон Иосифович).</p>
<p><font size="+1">БЕЖИЦА</font>, ныне часть Брянска. Оккупирован 6 октября 1941 г.
  Освобожден 17 сентября 1943 г. войсками БрФ в ходе Брянской операции: 11 А.</p>
<p><font size="+1">ГАЙСИН</font>. Оккупирован 25 июля 1941 г. Освобожден 18 ноября 1943 г,
  2-й партизанской бригадой (Кондратюк Анатолий Герасимович). Оккупирован 19 ноября
  1943 г. Освобожден 14 марта 1944 г. войсками 2 УФ в ходе Уманско-Ботошанской
  операции; 13 А - часть сил 389 сд (полковник Колобов Леонид Александрович).</p>
<p><font size="+1">ГОРОДОК</font> (Витебская область). Оккупирован 10 июля 1941 г.
  Освобожден 24 декабря 1943 г. войсками 1 ПрибФ в ходе Городокской операции: 11 гв. А.</p>
<p><font size="+1">НАРО-ФОМИНСК</font>. Частично захвачен к 22 октября 1941 г. Освобожден
  26 декабря 1941 г. войсками ЗапФ в ходе контрнаступления под Москвой: 33 А.</p>
<p><font size="+1">ПЫТАЛОВО</font>, см. АБРЕНЕ.</p>
<p><font size="+1">ПЯТИГОРСК</font>. Оккупиройан 10 августа 1942 г. Освобожден 11 января
  1943 г. войсками ЗакФ (СГВ) в ходе Северо-Кавказской операции: 37 А.</p>
<p><font size="+1">РИГА</font>. Оккупирован 1 июля 1941 г. Восточная часть города
  освобождена 13 октября 1944 г., западная - 15 октября 1944 г. войсками 3 ПрибФ
  и 2 ПрибФ в ходе Рижской операции. 3 ПрибФ: 67 А.</p>
<p><font size="+1">РОСТОВ-на-ДОНУ</font>. Оккупирован 21 ноября 1941 г. Освобожден
  29 ноября 1941 г. войсками ЮФ в ходе Ростовской операции: 9 А.</p>
<p><font size="+1">ТАЦИНСКАЯ</font>, станица (ТАЦИНСКИЙ). Оккупирована 16 июля 1942 г.
  Освобождена 24 декабря 1942 г. войсками ЮЗФ в ходе Среднедонской операции: 1 гв. А.
  Оккупирована 28 декабря 1942 г. Освобождена 15 января 1943 г. войсками ЮЗФ: 5 ТА.</p>
<p><font size="+1">ТИЛЬЗИТ (СОВЕТСК)</font>. Городом овладели 20 января 1945 г. войска 3 БФ
  в ходе Инстербургско-Кёнигсбергской операции: 43 А.</p>
<p><font size="+1">ТОЙОХАРА (ЮЖНО-САХАЛИНСК).</font> Освобожден 25 августа 1945 г. войсками
  2 ДВФ в ходе Южно-Сахалинской операции: 16 А.</p>
<p>&nbsp;</p>
<p><a href="../">Назад</a></p>
<p>РЕКЛАМА. Оккупирован 1 января 1941 г.</p>
</body></html>
"""

CHRONICLE = """<html><body><h1>Освобождение городов</h1><h2>Приложение 2</h2>
<p>Хроника освобождения городов</p>
<p><b>1941 год</b></p>
<p>29 ноября - Ростов-на-Дону. 26 декабря - Наро-Фоминск.</p>
<p><b>1942 год</b></p>
<p>23 января - Барвенково.</p>
<p><b>1943 год</b></p>
<p>7 февраля - Азов. 10 сентября - Барвенково (вторично).</p>
<p><b>1944 год</b></p>
<p>22 июля - Абрене (Пыталово). 26 октября - Берегово. 27 октября - Ужгород.</p>
<p>Назад</p></body></html>
"""


@pytest.fixture(scope="module")
def entries():
    return split_entries(page_text(PAGE.encode("cp1251")), "1-ssr-1.html")


@pytest.fixture(scope="module")
def parsed(entries):
    return {e.heading: parse_entry(e) for e in entries if not see_reference(e)}


def test_headings_include_unmarked_and_glued_entries(entries):
    headings = [e.heading for e in entries]
    assert "БАР" in headings, "статья без выделения названия"
    assert "БЕЛЫЙ" in headings, "статья, склеенная с концом «БЕЛЬЦЫ»"
    assert "РЕКЛАМА" not in headings, "после «Назад» разбор не идёт"
    beltsy = next(e for e in entries if e.heading == "БЕЛЬЦЫ")
    assert "4 октября 1941" not in beltsy.text
    assert len(entries) == 17


def test_see_reference_is_not_an_article(entries):
    refs = {e.heading: see_reference(e) for e in entries if see_reference(e)}
    assert refs == {"ПЫТАЛОВО": "АБРЕНЕ"}


def test_simple_pair(parsed):
    p = parsed["АБРЕНЕ (ПЫТАЛОВО)"]
    assert p.city.name == "Абрене" and p.city.modern == "Пыталово"
    (period,), problems = periods(p)
    assert not problems
    assert period.category == CATEGORY_OCCUPATION
    assert period.start.date == dt.date(1941, 7, 5)
    assert period.end.date == dt.date(1944, 7, 22)
    assert period.clause == "войсками 3 ПрибФ в ходе Псковско-Островской операции"


def test_three_occupations_are_three_periods(parsed):
    plist, problems = periods(parsed["БАРВЕНКОВО"])
    assert not problems
    assert [(p.number, p.of) for p in plist] == [(1, 3), (2, 3), (3, 3)]
    assert [p.end.date.isoformat() for p in plist] == ["1942-01-23", "1943-02-06",
                                                       "1943-09-10"]


def test_partial_capture_by_date(parsed):
    (period,), _ = periods(parsed["НАРО-ФОМИНСК"])
    assert period.category == CATEGORY_PARTIAL
    assert period.start.approx, "«к 22 октября» — не позднее этого дня"
    assert period.start.date == dt.date(1941, 10, 22)


def test_riga_ends_with_the_last_part(parsed):
    (period,), _ = periods(parsed["РИГА"])
    assert period.end.date == dt.date(1944, 10, 15)
    assert "13 октября" in period.end.note
    assert period.clause == "войсками 3 ПрибФ и 2 ПрибФ в ходе Рижской операции"


def test_feminine_forms_and_village_note(parsed):
    p = parsed["ТАЦИНСКАЯ"]
    assert p.city.modern == "Тацинский" and p.city.note == "станица"
    plist, problems = periods(p)
    assert not problems and len(plist) == 2


def test_ocr_typo_in_keyword(parsed):
    (period,), _ = periods(parsed["ПЯТИГОРСК"])
    assert period.start.date == dt.date(1942, 8, 10)


def test_capture_and_liberation_without_start(parsed):
    (capture,), _ = periods(parsed["ТИЛЬЗИТ (СОВЕТСК)"])
    assert capture.category == CATEGORY_CAPTURE and capture.start is None
    (liberation,), _ = periods(parsed["БЕРЕГОВО"])
    assert liberation.category == CATEGORY_LIBERATION
    assert liberation.end.date == dt.date(1944, 10, 26)


def test_qualifiers(parsed):
    assert parsed["ГОРОДОК"].city.region == "Витебская область"
    bezhitsa = parsed["БЕЖИЦА"].city
    assert bezhitsa.part_of == "Брянска" and "Брянск" in bezhitsa.part_of_names()
    assert parsed["РОСТОВ-на-ДОНУ"].city.name == "Ростов-на-Дону"
    assert parsed["ТОЙОХАРА (ЮЖНО-САХАЛИНСК)."].city.modern == "Южно-Сахалинск"


def test_clause_never_carries_the_unit_list(parsed):
    plist, _ = periods(parsed["ГАЙСИН"])
    assert plist[0].clause is None, "освобождён партизанами — справки «войсками» нет"
    assert plist[1].clause == "войсками 2 УФ в ходе Уманско-Ботошанской операции"
    assert by_clause(" войсками 4 УФ - 17 гв ск (генерал-майор Гастилович)") == \
        "войсками 4 УФ"


def test_title_case_and_names():
    assert title_case("ВЕЛИКИЕ ЛУКИ") == "Великие Луки"
    assert title_case("КАМЕНЕЦ-ПОДОЛЬСКИЙ") == "Каменец-Подольский"
    assert nominatives("Горловки")[1:] == ["Горловка"]
    assert "Севастополь" in nominatives("Севастополя")
    assert "Артёмовск" in name_variants("Артемовск")


def test_heading_counts_are_checked():
    counts = dict(EXPECTED_HEADINGS)
    assert check_headings(counts) == []
    counts[PAGES[0]] -= 1
    assert len(check_headings(counts)) == 1
    with pytest.raises(OccupationError):
        parse_pages({PAGES[0]: PAGE.encode("cp1251")})


def test_chronicle_crosscheck(parsed):
    chron = chronicle(CHRONICLE.encode("cp1251"))
    assert (dt.date(1943, 9, 10), "Барвенково") in chron
    result = check_chronicle(parsed.values(), chron)
    # Азов и Ужгород в образце статей нет; остальное сходится день в день.
    assert result["found"] == 6 and result["agree"] == 6
    assert result["differ"] == []


# --- точка города ---------------------------------------------------------------

def _row(name, qid, lat, lon, *, main=True, types=("город",), pop=None, anc=()):
    out = []
    for t in types:
        for a in anc or (None,):
            row = {"name": {"value": name},
                   "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                   "coord": {"value": f"Point({lon} {lat})"},
                   "main": {"value": "1" if main else "0"},
                   "typeLabel": {"value": t}}
            if pop:
                row["pop"] = {"value": str(pop)}
            if a:
                row["ancLabel"] = {"value": a}
            out.append(row)
    return out


def _parsed(heading, text, page="1-ssr-1.html"):
    return parse_entry(Entry(page, heading, text))


WD = candidates_from_rows(
    _row("Новороссийск", "Q15174", 44.72, 37.77, pop=340000, anc=("Краснодарский край",))
    + _row("Новороссийск", "Q48256", 48.45, 34.98, main=False, pop=980000,
           anc=("Днепропетровская область",))
    + _row("Галич", "Q134375", 58.38, 42.35, pop=15000, anc=("Костромская область",))
    + _row("Галич", "Q170123", 49.12, 24.72, pop=6000, anc=("Ивано-Франковская область",))
    + _row("Городок", "Q910000", 55.46, 29.99, pop=13000, anc=("Витебская область",))
    + _row("Городок", "Q920000", 49.78, 23.65, pop=16000, anc=("Львовская область",))
    + _row("Макаров", "Q2641614", 50.46, 29.81, pop=10000, anc=("Киевская область",))
    + _row("Макаров", "Q196000", 48.63, 142.78, pop=6000, anc=("Сахалинская область",))
    + _row("Приморск", "Q760230", 46.73, 36.35, pop=11000, anc=("Запорожская область",))
    + _row("Приморск", "Q183223", 54.73, 20.0, pop=1400, anc=("Калининградская область",))
    + _row("Горловка", "Q157260", 48.3, 38.05, pop=240000, anc=("Донецкая область",))
    + _row("Комсомольск", "Q998227", 49.01, 33.64, pop=50000, anc=("Полтавская область",))
    + _row("Великие Луки", "Q13029566", 53.01, 26.05, types=("деревня в беларуси",), pop=310)
    + _row("Кингисепп", "Q4220746", 59.37, 28.6, types=("железнодорожная станция",))
)

GN = geonames_index([
    {"geometry": {"coordinates": [30.54377, 56.34063]},
     "properties": {"title": "Великие Луки", "source_id": "476077",
                    "extra": {"population_modern": 103149}}},
    {"geometry": {"coordinates": [28.61409, 59.37627]},
     "properties": {"title": "Кингисеп", "source_id": "548602",
                    "extra": {"population_modern": 48000}}},
], {"548602": {"names": ["Kingisepp"]}})

OCC = "Оккупирован 1 июля 1941 г. Освобожден 1 июля 1944 г. войсками ЗапФ: 1 А."


def test_label_beats_other_name():
    place = place_city(_parsed("НОВОРОССИЙСК", OCC), WD, GN)
    assert place.candidate.ident == "Q15174", "Новороссийск — не Днепр 1796–1802 годов"


def test_zone_excludes_unoccupied_namesake():
    place = place_city(_parsed("ГАЛИЧ", OCC), WD, GN)
    assert place.candidate.ident == "Q170123", "Галич Костромской области не оккупировался"


def test_region_from_the_book_decides():
    text = "(Львовская область). " + OCC
    place = place_city(_parsed("ГОРОДОК", text), WD, GN)
    assert place.candidate.ident == "Q920000"


def test_sakhalin_zone_and_capture_regions():
    sakhalin = _parsed("СИРИТОРИ (МАКАРОВ)",
                       "Освобожден 22 августа 1945 г. войсками 2 ДВФ: 16 А.")
    assert place_city(sakhalin, WD, GN).candidate.ident == "Q196000"
    prussia = _parsed("ФИШХАУЗЕН (ПРИМОРСК)",
                      "Городом овладели 17 апреля 1945 г. войска 3 БФ: 39 А.")
    assert place_city(prussia, WD, GN).candidate.ident == "Q183223"


def test_part_of_city_falls_back_to_the_whole():
    p = _parsed("КОМСОМОЛЬСК", ", ныне часть Горловки. " + OCC)
    place = place_city(p, WD, GN)
    assert place.part_of and place.candidate.ident == "Q157260", \
        "полтавский Комсомольск дальше 25 км от Горловки — не он"
    (rec,) = period_records(p, place)
    assert rec.confidence == "place_level"


def test_geonames_town_beats_wikidata_village_and_override():
    assert place_city(_parsed("ВЕЛИКИЕ ЛУКИ", OCC), WD, GN).candidate.ident == "476077"
    kingisepp = _parsed("КИНГИСЕПП", "(Ленинградская область). " + OCC)
    assert place_city(kingisepp, WD, GN).candidate.ident == "548602"


def test_unplaced_city_stays_without_point():
    p = _parsed("РИБШЕВО", OCC)
    place = place_city(p, WD, GN)
    assert place.candidate is None
    (rec,) = period_records(p, place)
    assert rec.confidence == "no_coords" and not rec.has_point and rec.has_time


def test_lookup_names_cover_modern_wartime_and_part_of():
    cities = [City("X", "Сталино", modern="Донецк"), City("Y", "Бежица", part_of="Брянска")]
    names = lookup_names(cities)
    assert {"Сталино", "Донецк", "Бежица", "Брянск"} <= set(names)


# --- записи -------------------------------------------------------------------

def test_records_carry_dates_link_and_no_unit_list(parsed):
    p = parsed["БАРВЕНКОВО"]
    place = place_city(p, WD, GN)
    recs = period_records(p, place)
    assert len(recs) == 3
    rec = recs[1]
    assert rec.layer == OCCUPATION_CITIES.slug and rec.group == "military"
    assert rec.scope == SCOPE_POINT
    assert (rec.year_from, rec.year_to) == (1942, 1943)
    assert rec.date_precision == "day"
    assert rec.url == "https://www.soldat.ru/spravka/freedom/1-ssr-1.html"
    assert rec.extra["occupied"] == "1942-05-18" and rec.extra["liberated"] == "1943-02-06"
    assert rec.extra["period_number"] == 2 and rec.extra["periods_total"] == 3
    assert "Второй из трёх" in rec.summary
    assert "351 сд" not in (rec.summary or "") + (rec.period_raw or "")
    assert len({r.uid for r in recs}) == 3


def test_partial_record_says_no_later_than(parsed):
    (rec,) = period_records(parsed["НАРО-ФОМИНСК"], place_city(parsed["НАРО-ФОМИНСК"], {}, {}))
    assert rec.category == CATEGORY_PARTIAL and rec.date_approx
    assert "не позднее" in rec.summary


# --- сверка с набором Grunewald -------------------------------------------------

def test_grunewald_status():
    assert grunewald_status("Under Axis Control by November 19, 1942") == "axis"
    assert grunewald_status("Under Axis Control before Start of Operation Barbarossa") == "axis"
    assert grunewald_status("Recaptured by Soviet forces by April 10, 1942") == "soviet"
    assert grunewald_status("Still under Soviet control and site of active fighting "
                            "between Soviet and Axis forces by December 5, 1941") == "soviet"
    assert grunewald_status("Under Red Army Control July 4, 1943") == "soviet"


def test_grunewald_check(parsed):
    rows = [
        {"sheet": "Battle of Moscow", "place": "Naro Fominsk", "date": dt.date(1941, 12, 5),
         "note": "Under Axis Control by December 5, 1941"},
        {"sheet": "Battle of Moscow", "place": "Naro Fominsk", "date": dt.date(1942, 1, 10),
         "note": "Recaptured by Soviet forces by January 10, 1942"},
        {"sheet": "Operation Barbarossa", "place": "Rostov", "date": dt.date(1941, 12, 5),
         "note": "Under Axis Control by December 5, 1941"},
        {"sheet": "Battle of Moscow", "place": "Moscow", "date": dt.date(1941, 12, 5),
         "note": "Under Soviet Control at December 5, 1941"},
    ]
    result = check_grunewald(list(parsed.values()), rows)
    assert result["matched"] == 3 and result["agree"] == 2
    assert len(result["disagree"]) == 1 and "Ростов" in result["disagree"][0]
    assert result["unmatched"] == ["Moscow"]
    assert latin_key("Белёв") == latin_key("Belev")


def test_parsed_entry_type(parsed):
    assert all(isinstance(p, ParsedEntry) for p in parsed.values())
