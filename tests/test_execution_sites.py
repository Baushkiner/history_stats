"""Места массовых расстрелов: карта Yahad – In Unum и атлас Литвы.

Сети в тестах нет. Ответ карты, профиль села и сценарий атласа собраны
здесь же в той разметке, что у сайтов на 22.11.2026.

Проверяется то, на чём слой держится: точки «soon online» без профиля
остаются в слое с рамкой оккупации; из профиля берутся факты таблицы и дата
с шифром акта ЧГК, а выдержки, свидетельства и имена — нет; даты атласа до
дня; сведение атласа с Yahad по ссылке профиля и по расстоянию, каждая
сторона один раз; несколько мест одного села нумеруются.
"""

import json

import pytest

from histctx.registry import BY_SLUG, HARVESTED
from histctx.sources.execution_sites import (
    EXECUTION_SITES, HAL_ITEM, LINK_KM, MATCH_KM, YAHAD_MAP, ExecutionSitesError, HalPlace,
    Point, check_profile, check_profiles, en_dates, hal_dating, hal_town, match_hal,
    map_degrees, occupation_frame, parse_hal, parse_points, parse_profile, period_years,
    place_kind_ru,
    records, soviet_archive_ref, victims_estimate, victims_group, victims_ru, villages,
)
from histctx.sources.russian_names import RussianNames

POINTS = [
    {"pending": "0", "u": "#village/oleksandriya-rivne-ukraine.1", "t": "Oleksandriya",
     "p": "Ukraine", "date": None, "img": "/x.jpg", "lat": "50.438240", "lng": "26.192360",
     "s": "2"},
    {"pending": "0", "u": "#village/seredzius-kaunas-lithuania.1041", "t": "Seredžius",
     "p": "Lithuania", "date": "2014", "img": "", "lat": "55.047700", "lng": "23.251820",
     "s": "1"},
    {"pending": "0", "u": "#village/seredzius-kaunas-lithuania.1041", "t": "Seredžius",
     "p": "Lithuania", "date": "2014", "img": "", "lat": "55.051000", "lng": "23.258000",
     "s": "1"},
    {"pending": "1", "u": "", "t": "Batyatychi", "p": "Ukraine", "date": "2004",
     "img": "", "lat": "50.075500", "lng": "24.202400", "s": "1"},
    {"pending": "1", "u": "", "t": "Nowhere", "p": "Poland", "date": None,
     "img": "", "lat": "", "lng": "", "s": "1"},
]

WITNESS = "Zoya T., born in 1927, remembers: the German soldiers burned the synagogue"
QUOTE = "1,080 people of Jewish nationality were shot in the forest"


def profile_html(*, heading="Execution of Jews in Oleksandriya", sites=1, dl=None,
                 soviet=None, hal_item=None):
    dl = dl if dl is not None else [
        ("Kind of place before:", "Forest"), ("Memorials:", "Yes"),
        ("Period of occupation:", "1941-1944"), ("Total number of victims:", "Over 1,000")]
    rows = "".join(f"<dt>{a}</dt>\n<dd>{b}</dd>\n" for a, b in dl)
    soviet = soviet if soviet is not None else (
        f"<h3>Soviet archives</h3><p>“{QUOTE} […]”. [Act drawn up by State Extraordinary "
        "Commission on December 6 ,1944; RG 22.022M:Fond 7021, Opis 71, Delo 41]</p>")
    hal = (f'<h3>Holocaust Atlas of Lithuania</h3><div class="rte"><p><a href="http://www.'
           f'holocaustatlas.lt/EN/#a_atlas/search//page/1/item/{hal_item}/">Go</a></p></div>'
           if hal_item else "")
    return (
        '<div class="titre"><h1><span class="nom">Oleksandriya</span> | '
        '<span class="region">Rivne</span></h1></div>'
        f'<div id="village_texte"><h2>{heading}</h2>'
        f'<p class="nb_sites">{sites} Killing site(s)</p>'
        f'<dl class="clearfix">{rows}</dl>'
        f"<h3>Witness interview</h3><p>{WITNESS}</p>"
        f"{soviet}"
        '<h3>Historical note</h3><div class="rte"><p>Oleksandriya is located about 13 km '
        "northwest of Rivne.</p></div>"
        f"{hal}"
        "<h3>Nearby villages</h3></div>"
    )


HAL_JS = (
    "/* id,x,y,zoom,title,summary */\nvar markers = new Array();\n"
    "markers[0] = new Array(135,55.079500,23.419700,8,'Mass Murder of the Jews of Seredžius',"
    "'On August 28, 1941, 193 Jews were shot.');\n"
    "markers[1] = new Array(12,55.512233,25.125800,8,'Mass killing of the Jews of Anykščiai',"
    "'At the end of June, 1941, Jewish men were shot. On August 29, 1941, women were shot. ');\n"
    "markers[2] = new Array(21,54.1702,25.1695,8,'Mass Murder of the (Elderly) Jews of "
    "Eišiškės','The elderly Jewish population was murdered near the catholic cemetery');\n"
    "markers[3] = new Array(81,56.17,22.09,8,'Mass Murder of the Jews at Seda',"
    "'The first Jews of Seda were murdered at the end of June, 1941.');\n"
)


def test_layer_is_registered_as_harvested():
    assert BY_SLUG["execution_sites"] is EXECUTION_SITES
    assert EXECUTION_SITES in HARVESTED
    assert EXECUTION_SITES.group == "military"
    assert "права не выяснены" in EXECUTION_SITES.license


def test_points_keep_pending_and_broken_coordinates():
    points = parse_points(json.dumps(POINTS))
    assert len(points) == 5
    first = points[0]
    assert (first.slug, first.village, first.band, first.pending) == (
        "oleksandriya-rivne-ukraine", 1, 2, False)
    pending = points[3]
    assert pending.pending and pending.village is None and pending.trip_year == 2004
    # Невозможная координата не выбрасывается и не правится: точки нет, исходник есть.
    broken = parse_points(json.dumps([{**POINTS[0], "lat": "531.299011", "lng": "34.215611"}]))[0]
    assert broken.lat is None and broken.coords_raw == "531.299011, 34.215611"
    assert villages(points) == [1, 1041]


@pytest.mark.parametrize("raw,degrees", [
    ("50.438240", 50.7304),          # 50° 43,824′ — Олександрия, как её ставит карта
    ("26.192360", 26.3206),
    ("55.047700", 55.0795),
    ("0.000000", 0.0),
    ("50.4382", None),               # не шесть знаков — не запись карты
    ("47.999999", None),             # 99,999 минуты
    ("", None),
    (None, None),
])
def test_map_degrees(raw, degrees):
    assert map_degrees(raw) == degrees


def test_points_are_read_as_degrees_and_minutes():
    first = parse_points(json.dumps(POINTS))[0]
    assert (first.lat, first.lon) == (50.7304, 26.3206)
    for raw in ("531.299011", "0.000000"):
        broken = parse_points(json.dumps([{**POINTS[0], "lat": raw, "lng": "0.000000"}]))[0]
        assert broken.lat is None and broken.coords_raw == f"{raw}, 0.000000"


def test_points_answer_of_another_shape_stops_the_build():
    with pytest.raises(ExecutionSitesError):
        parse_points("[]")
    with pytest.raises(ExecutionSitesError, match="нет полей"):
        parse_points(json.dumps([{"t": "x"}]))


def test_profile_facts_are_read_and_quotes_are_not():
    p = parse_profile(profile_html())
    check_profile(p, 1)
    assert (p["name"], p["region"], p["sites"]) == ("Oleksandriya", "Rivne", 1)
    assert p["fields"]["period of occupation"] == "1941-1944"
    assert p["fields"]["total number of victims"] == "Over 1,000"
    assert p["soviet_archive"] == {"kind": "акт", "date": "1944-12-06",
                                   "ref": "RG 22.022M:Fond 7021, Opis 71, Delo 41"}
    assert p["archives"] == ["soviet"]
    assert WITNESS not in json.dumps(p, ensure_ascii=False)
    assert QUOTE not in json.dumps(p, ensure_ascii=False)


def test_archive_kinds_ignore_letter_case():
    page = profile_html(soviet="<h3>Polish Archives</h3><p>x</p>"
                               "<h3>Moldovan/Romanian Archives</h3><p>y</p>")
    assert parse_profile(page)["archives"] == ["polish", "moldovan/romanian"]


def test_stub_profile_passes_but_a_set_without_tables_stops_the_build():
    stub = parse_profile(profile_html(dl=[], soviet=""))
    check_profile(stub, 1475)                     # заготовка: название есть, таблицы нет
    full = parse_profile(profile_html())
    assert check_profiles({1: full, 1475: stub}) == [1475]
    with pytest.raises(ExecutionSitesError, match="ни в одном"):
        check_profiles({1475: stub, 1476: stub})
    with pytest.raises(ExecutionSitesError, match="названия"):
        check_profile(parse_profile(profile_html().replace('class="nom"', 'class="x"')), 7)


@pytest.mark.parametrize("fragment,expected", [
    ("<p>“…”. [Act n°34 drawn up by Soviet Extraordinary Commission (ChGK) on January 10, "
     "1945; RG 22.002M: GARF 7021-96-82]</p>",
     {"kind": "акт", "date": "1945-01-10", "number": "34",
      "ref": "RG 22.002M: GARF 7021-96-82"}),
    ("<p>“…” [Report of the Extraordinary State Commission of the crimes committed by the "
     "German-fascist occupiers in Chernelytsia District, drawn up on May 17th, 1945; "
     "RG22.002M: 7021-73-20]</p>",
     {"kind": "акт", "date": "1945-05-17", "ref": "RG22.002M: 7021-73-20"}),
    ("<p>“…” [Act of Soviet extraordinary commission, drawn up in 1944; "
     "RG-22.002M/7021-75/87]</p>",
     {"kind": "акт", "date": "1944", "ref": "RG-22.002M/7021-75/87"}),
    ("<p>“…” [Act of the Soviet extraordinary commission, RG-22.002M.7021-54/1241]</p>",
     {"kind": "акт", "ref": "RG-22.002M.7021-54/1241"}),
    ("<p>“…” [RG-22.002M/7021-60/285]</p>",
     {"kind": "документ", "ref": "RG-22.002M/7021-60/285"}),
    ("<p>“…” [today Chyzhove]</p>", None),
    ("<p>No bracketed reference here.</p>", None),
    (None, None),
])
def test_soviet_archive_ref(fragment, expected):
    assert soviet_archive_ref(fragment) == expected


def test_names_before_the_archive_code_never_reach_the_layer():
    got = soviet_archive_ref(
        "<p>“…” [Deposition of David Z., a Jewish survivor, drawn up on October 11, 1944 in "
        "Buchach; RG-22.002M.7021-75/371]</p>")
    assert got == {"kind": "показания", "date": "1944-10-11", "ref": "RG-22.002M.7021-75/371"}
    blob = json.dumps(soviet_archive_ref(
        "<p>[From the testimony of a Jewish survivor, Maria Blaivas, daughter of Leib, given "
        "to the State Soviet Extraordinary Commission in April 1945; GARF 7021-60-281, "
        "pp. 21-23]</p>"), ensure_ascii=False)
    assert "Blaivas" not in blob and "Leib" not in blob and "GARF 7021-60-281" in blob


def test_en_dates_ordinals_order_and_impossible_days():
    assert en_dates("On August 28, 1941 and 2nd of September 1941") == [
        (1941, 8, 28), (1941, 9, 2)]
    assert en_dates("February 31, 1942") == []
    assert en_dates("November 3, 1941Troops") == [(1941, 11, 3)]


@pytest.mark.parametrize("text,ru", [
    ("Over 1,000", "более 1 000"),
    ("About 475", "около 475"),
    ("Circa 1,500", "около 1 500"),
    ("At least 1.300", "не менее 1 300"),
    ("Between 150 and 250", "от 150 до 250"),
    ("More than 40", "более 40"),
    ("Several dozen", "несколько десятков"),
    ("Several hundred", "несколько сотен"),
    ("193", "193"),
    ("Approximately 400 Jews", "около 400"),
    ("ca. 2,000", "около 2 000"),
    ("From 640 to 1,800", "от 640 до 1 800"),
    ("Between 5,800- and 9,000", "от 5 800 до 9 000"),
    ("About a dozen", "около десятка"),
    ("96 or 97", "96 или 97"),
    ("Uknown", "неизвестно"),
    ("Hard to say, maybe a lot", None),
    (None, None),
])
def test_victims_ru(text, ru):
    assert victims_ru(text) == ru


def test_period_victims_group_and_place_kind():
    assert period_years("1941-1944") == (1941, 1944)
    assert period_years("1941 - 1945") == (1941, 1945)
    assert period_years("unknown") is None
    assert victims_estimate("Over 1,000") == 1000
    assert victims_estimate("Circa 1,500") == 1500
    assert victims_estimate("Several dozen") is None
    assert victims_estimate("At least 1.300") == 1300
    assert victims_estimate("Between 150 and 250") == 150
    assert victims_group("Execution of Jews in X") == "расстрел евреев"
    assert victims_group("Execution of Roma in X") == "расстрел рома (цыган)"
    assert victims_group("Executions of Jews and Roma around X") == "расстрел евреев и рома"
    assert victims_group("Execution of civilians") == "массовый расстрел"
    assert place_kind_ru("Forest") == "лес"
    assert place_kind_ru("Forest (1); cemeteries  (2)") == "лес; кладбище"
    assert place_kind_ru("3 clay pits near the brickyards") == "карьер"
    assert place_kind_ru("Ravine near the road") == "овраг"
    assert place_kind_ru("Silo pits (1); Ravine (2)") == "силосная яма; овраг"
    assert place_kind_ru("Multiple different places") is None


def test_hal_markers_and_dates():
    places = parse_hal(HAL_JS)
    assert [p.id for p in places] == [135, 12, 21, 81]
    day = hal_dating(places[0].summary)
    assert (day.year_from, day.precision, day.iso) == (1941, "day", "1941-08-28")
    # Два расстрела: в конце июня без числа и 29 августа — точность месяц, обе даты в raw.
    two = hal_dating(places[1].summary)
    assert (two.precision, two.year_from, two.raw, two.iso) == ("month", 1941,
                                                                "06.1941, 29.08.1941", None)
    days = hal_dating("Shot on September 9, 1941 and on October 2, 1941.")
    assert (days.precision, days.raw, days.iso) == ("day", "09.09.1941, 02.10.1941", None)
    assert hal_dating(places[2].summary) is None
    month = hal_dating(places[3].summary)
    assert (month.year_from, month.precision) == (1941, "month")
    with pytest.raises(ExecutionSitesError):
        parse_hal("var markers = new Array();")


def test_hal_town():
    assert hal_town("Mass Murder of the Jews of Molėtai") == "Molėtai"
    assert hal_town("Mass Murder of the (Elderly) Jews of Eišiškės") == "Eišiškės"
    assert hal_town("Mass Murder of the Jewish Men in Tytuvėnai forest") == "Tytuvėnai"
    assert hal_town("Mass Murder of the Jews near Butrimonys (1st site) ") == "Butrimonys"
    assert hal_town("Mass Murder of the Jews from Semeliškės, Vievis and Žasliai") == "Semeliškės"
    assert hal_town("Mass Murder of Communists, Soviet Activists and Jews from Ignalina next "
                    "to Ilgis Lake") == "Ignalina"
    assert hal_town("Mass Murder of the Jews from Kudirkos Naumiestis in Paražniai woods") \
        == "Kudirkos Naumiestis"
    assert hal_town("Mass Murder of the Jews of Pasvalys and Surrounding Areas") == "Pasvalys"
    assert hal_town("Alytus and Sorrounding Areas") is None
    assert hal_town("Kaunas IX Fort") == "Kaunas"
    assert hal_town("Šiauliai ghetto") == "Šiauliai"
    assert hal_town("Mass Murder of the Jews near the Jewish Cemetery") is None
    assert hal_town("Something else entirely") is None


def test_matching_link_first_then_distance_one_to_one():
    points = [Point("A", "Lithuania", 55.0790, 23.4195, 1, False, "a", 1041),
              Point("A", "Lithuania", 55.0850, 23.4300, 1, False, "a", 1041),
              Point("B", "Lithuania", 55.5130, 25.1260, 1, False, "b", 7)]
    profiles = {1041: {"hal_item": 135}, 7: {}}
    far_link = HalPlace(135, 55.12, 23.47, "t", "")   # ~6 км: только по ссылке
    near = HalPlace(12, 55.512233, 25.125800, "t", "")
    alien = HalPlace(99, 54.0, 21.0, "t", "")
    got = match_hal(points, profiles, [far_link, near, alien])
    assert got[2] == 12
    assert list(got.values()).count(135) == 1
    assert 99 not in got.values()
    assert MATCH_KM < LINK_KM


def test_records_merge_number_and_frame():
    points = parse_points(json.dumps(POINTS))
    profiles = {
        1: parse_profile(profile_html()),
        1041: parse_profile(profile_html(heading="Execution of Jews in Seredžius",
                                         soviet="", hal_item=135, dl=[
                                             ("Period of occupation:", "1941-1944"),
                                             ("Total number of victims:", "193")])),
    }
    places = parse_hal(HAL_JS)
    names = RussianNames({"1": {"title": "Александрия", "lat": 50.73, "lon": 26.34,
                                "names": ["Oleksandriya", "Aleksandriya"]}})
    recs = records(points, profiles, places, names=names)
    # 4 точки Yahad + 3 места атласа, не сведённые с Yahad.
    # 5 точек Yahad (одна без координаты) + 3 места атласа, не сведённые с Yahad.
    assert len(recs) == 8
    nowhere = recs[4]
    assert nowhere.lat is None and nowhere.confidence == "no_coords"
    assert (nowhere.year_from, nowhere.year_to) == (1939, 1945)   # рамка Польши
    ukr = recs[0]
    assert ukr.title == "Место расстрела — Александрия"
    assert (ukr.year_from, ukr.year_to, ukr.date_precision) == (1941, 1944, "year")
    assert ukr.extra["soviet_archive"]["date"] == "1944-12-06"
    assert "акт ЧГК от 1944-12-06" in ukr.summary
    assert ukr.extra["victims_min"] == 1000 and ukr.extra["memorial"] is True
    assert ukr.extra["place_before"] == "лес"
    assert ukr.url == "https://www.yahadmap.org/en/#village/oleksandriya-rivne-ukraine.1"
    lt1, lt2 = recs[1], recs[2]
    assert lt1.title.endswith("(1 из 2)") and lt2.title.endswith("(2 из 2)")
    merged = [r for r in (lt1, lt2) if "holocaust_atlas_lt" in r.extra]
    assert len(merged) == 1
    assert merged[0].date_precision == "day"
    assert merged[0].extra["holocaust_atlas_lt"]["url"] == HAL_ITEM.format(id=135)
    assert merged[0].extra["source_set"] == "yahad+hal"
    pending = recs[3]
    assert pending.extra["pending"] is True and pending.url == YAHAD_MAP
    assert (pending.year_from, pending.year_to, pending.date_precision) == (1941, 1944, "era")
    assert pending.date_approx and "рамка оккупации" in pending.period_raw
    hal_only = [r for r in recs if r.extra.get("source_set") == "hal"]
    assert {r.source_id for r in hal_only} == {"hal:12", "hal:21", "hal:81"}
    undated = next(r for r in hal_only if r.source_id == "hal:21")
    assert undated.date_precision == "era" and undated.date_approx
    for rec in recs:
        blob = json.dumps(rec.to_row(), ensure_ascii=False) + json.dumps(rec.extra,
                                                                        ensure_ascii=False)
        assert WITNESS not in blob and QUOTE not in blob
        assert "Zoya" not in blob


def test_occupation_frame_by_country():
    pl = occupation_frame("Poland")
    assert (pl.year_from, pl.year_to, pl.precision, pl.approx) == (1939, 1945, "era", True)
    unknown = occupation_frame(None)
    assert (unknown.year_from, unknown.year_to) == (1939, 1945)
