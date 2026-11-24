"""Разбор списков колоний Odessa Digital Library.

Сети в тестах нет. Списки — текст с колонками фиксированной ширины: у трёх
под шапкой линейка из дефисов, у крымского — только слова заголовка. Образцы
ниже собраны по тем же позициям колонок, что в файлах odessa3.org
(24.11.2026), строки — настоящие строки списков.

Проверяется то, на чём слой держится: границы колонок по линейке и по
заголовку, конец таблицы у Поволжья (линейка перед примечаниями), перенос
строки у меннонитского списка, коды конфессий и ссылок, губерния по самому
списку у записей без точки, поиск точки в GRSL — по имени, по умлауту, по году
и району среди нескольких кандидатов, отказ от точки при расхождении года.
"""

from histctx.registry import BY_SLUG
from histctx.sources.colony_lists_odessa3 import (
    BY_KEY, COLONY_LISTS, LAYER_ID, GrslIndex, parse_list, records, region_of, religions_of,
    spans_from_dashes, volga_refs,
)

VOLGA_COLS = [0, 30, 54, 72, 78, 91, 95, 116, 121, 126]
ODESSA_COLS = [0, 29, 73, 91, 110, 121, 144]
MENNO_COLS = [0, 30, 50, 60, 93]
CRIMEA_COLS = [0, 37, 54, 62, 69, 78]


def _row(cols, *cells, right=()):
    """Строка по позициям колонок; `right` — номера колонок, прижатых вправо."""
    line = ""
    for i, cell in enumerate(cells):
        start = cols[i]
        if i in right and i + 1 < len(cols):
            cell = cell.rjust(cols[i + 1] - start - 1)
        line = line.ljust(start) + cell
    return line.rstrip()


def _rule(cols, width=8):
    line = ""
    for start, end in zip(cols, cols[1:] + [cols[-1] + width + 2]):
        line = line.ljust(start) + "-" * (end - start - 1)
    return line


HEADER = ("Volga Area Villages (Heinle)\n\n        Copyright 1996, Ray Heinle\n\n"
          "V O L G A   A R E A   V I L L A G E S\n"
          + "-" * 50 + "\n\n")

VOLGA = "\n".join([
    HEADER.rstrip("\n"),
    "German                        Russian                 Group/",
    _rule(VOLGA_COLS),
    _row(VOLGA_COLS, "Kratzke", "Potshennoye", "Frank", "B", "1767", "E", "", "", "137",
         "s152,b351,g81"),
    _row(VOLGA_COLS, "Schilling", "", "Krasny-Kut", "W", "", "", "", "", "", "s158"),
    _row(VOLGA_COLS, "Schilling", "Sosnowka", "Balzer", "B", "1764", "E", "", "1773", "429",
         "s158,g81,b352"),
    _row(VOLGA_COLS, "Weisental", "", "", "B", "1852", "", "", "", "",
         "Abandoned after a few years"),
    "",
    "",
    "-" * 50,
    "NOTES:",
    "Seite refers to which side of the Volga River the colony was on, also region.",
    "          B=Bergseite (West or mountain side)",
])

ODESSA = "\n".join([
    "Odessa Area Villages (B. Gutenberg)",
    "German Name                  Other Name(s)",
    _rule(ODESSA_COLS),
    _row(ODESSA_COLS, "Alexanderhilf", "Alexejeweka", "Grossliebental", "Owidiopol",
         "1804/05", "Evangelical"),
    _row(ODESSA_COLS, "Adaja", "Tichin-Kut"),
])

MENNO = "\n".join([
    "Mennonite Villages in Russia - Index (T. Janzen)",
    "Village Name                  Russian Name        Year      Government  District",
    "                                                  Founded",
    _rule(MENNO_COLS, 28),
    _row(MENNO_COLS, "Adelsheim", "Dolinovka", "1869-72", "Ekaterinoslav", "Yazykovo",
         right=(2,)),
    _row(MENNO_COLS, "Andreyevka"),
    _row(MENNO_COLS, "(same as Gnadental)", "", "1882", "Samara",
         "daughter colony of Am Trakt and Alt-Samara", right=(2,)),
    _row(MENNO_COLS, "Volodyevka", "", "1904", "Kherson", "Pachtdorf", right=(2,)),
    "(daughter colony of ",
    "   Altonau, Molotschna) ",
    _row(MENNO_COLS, "Halbstadt", "", "1804", "Taurida", "Molotschna", right=(2,)),
    _row(MENNO_COLS, "Rosenthal", "", "1790", "Ekaterinoslav", "Chortitza", right=(2,)),
])

CRIMEA = "\n".join([
    "Crimea Area Villages (Wahl)",
    "C R I M E A   A R E A   V I L L A G E S",
    "",
    _row(CRIMEA_COLS, "VILLAGE", "DISTRICT", "YEAR", "AREA", "REF", "REMARKS"),
    "",
    _row(CRIMEA_COLS, "Zuerichtal", "", "1804", "Crimea", "ST - 98", "ev"),
    _row(CRIMEA_COLS, "Abakln", "", "", "Crimea", "SP", "Hochheim Leased Villages:"),
])


def _feature(uid, lon, lat, group, name_de, year=None, name_ru=None, religion=None,
             authority=None, place_text=None):
    return {"type": "Feature", "id": uid,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"uid": uid, "year_from": year, "place_text": place_text,
                           "extra": {"group": group, "name_de": name_de, "name_ru": name_ru,
                                     "religions_en": religion, "authority": authority}}}


GRSL = GrslIndex.from_features([
    _feature("g:kratzke", 45.5, 51.0, "Поволжье", "Kratzke", 1767, "Крацке"),
    _feature("g:schilling", 46.0, 50.9, "Поволжье", "Schilling", 1764, "Шиллинг"),
    _feature("g:schilling2", 48.0, 50.0, "Поволжье", "Schilling", 1850),
    # Три Гальбштадта: Молочна, Березань и Сибирь — развести годом.
    _feature("g:halb-m", 35.4, 47.3, "Молочна", "Halbstadt", 1804, "Гальбштадт", "Mennonite"),
    _feature("g:halb-b", 31.0, 47.1, "Березань", "Halbstadt", 1869, "Гальбштадт", "Catholic"),
    _feature("g:halb-s", 78.0, 53.0, "Сибирь", "Halbstadt", 1908, "Гальбштадт", "Mennonite"),
    _feature("g:zuerich", 34.6, 45.2, "Крым", "Zürichtal", 1805, "Цюрихталь"),
    _feature("g:rosenthal", 35.0, 47.8, "Хортица", "Rosenthal", 1927, None, "Mennonite"),
    _feature("g:alexhilf", 30.4, 46.4, "Гросслибенталь", "Alexanderhilf", 1805, "Александергильф"),
])


def test_spans_from_dashes():
    spans = spans_from_dashes(_rule(MENNO_COLS))
    assert [a for a, _ in spans] == MENNO_COLS
    assert spans[-1][1] > 1000


def test_volga_table_stops_before_notes_and_keeps_duplicates():
    rows = parse_list(VOLGA, BY_KEY["volga"])
    assert [r["name"] for r in rows] == ["Kratzke", "Schilling", "Schilling", "Weisental"]
    schilling = rows[2]
    assert schilling["name_ru"] == "Sosnowka" and schilling["side"] == "B"
    assert schilling["census"] == "1773" and schilling["population"] == "429"
    assert volga_refs(schilling["remarks"]) == (["s158", "g81", "b352"], None)
    assert volga_refs(rows[3]["remarks"]) == ([], "Abandoned after a few years")
    assert religions_of(rows[0], BY_KEY["volga"]) == ["лютеране"]


def test_mennonite_wrapped_lines():
    rows = parse_list(MENNO, BY_KEY["mennonite"])
    names = [r["name"] for r in rows]
    assert names == ["Adelsheim", "Andreyevka (same as Gnadental)", "Volodyevka", "Halbstadt",
                     "Rosenthal"]
    assert rows[0]["year"] == "1869-72" and rows[0]["place"] == "Ekaterinoslav"
    assert rows[1]["year"] == "1882" and "Am Trakt" in rows[1]["colony"]
    assert rows[2]["colony"] == "Pachtdorf (daughter colony of Altonau, Molotschna)"
    assert region_of(rows[1], BY_KEY["mennonite"]) == "Самарская губерния"


def test_crimea_columns_from_header():
    rows = parse_list(CRIMEA, BY_KEY["crimea"])
    assert [r["name"] for r in rows] == ["Zuerichtal", "Abakln"]
    assert rows[0]["ref"] == "ST - 98" and rows[0]["year"] == "1804"
    assert religions_of(rows[0], BY_KEY["crimea"]) == ["лютеране"]


def test_records_match_grsl():
    recs = records({"volga": VOLGA, "odessa": ODESSA, "mennonite": MENNO, "crimea": CRIMEA},
                   GRSL)
    by = {(r.extra["list"], r.extra["line"]): r for r in recs}
    assert len(recs) == 4 + 2 + 5 + 2
    kratzke = next(r for r in recs if r.extra["name_de"] == "Kratzke")
    assert (kratzke.lat, kratzke.lon) == (51.0, 45.5)
    assert kratzke.title == "Колония Крацке (Kratzke), осн. 1767"
    assert kratzke.year_from == 1767 and kratzke.year_to == 1960
    assert kratzke.date_precision == "open" and kratzke.confidence == "ok"
    assert kratzke.extra["grsl"] == "g:kratzke"
    # Два Шиллинга в GRSL: строка с годом — по году, без года — без точки.
    schillings = [r for r in recs if r.extra["name_de"] == "Schilling"]
    assert [s.extra.get("grsl") for s in schillings] == [None, "g:schilling"]
    assert schillings[0].extra["grsl_match"] == "несколько мест GRSL"
    assert schillings[0].region == "Самарская губерния"    # луговая сторона
    assert "население в 1773 году — 429" in schillings[1].summary
    # Гальбштадт меннонитского списка — Молочна, а не Березань и не Сибирь.
    halb = next(r for r in recs if r.extra["name_de"] == "Halbstadt")
    assert halb.extra["grsl"] == "g:halb-m"
    # Умлаут: Zuerichtal списка — Zürichtal GRSL; год расходится на год — точка берётся.
    zuerich = next(r for r in recs if r.extra["name_de"] == "Zuerichtal")
    assert zuerich.extra["grsl"] == "g:zuerich" and zuerich.extra["grsl_year"] == 1805
    # Rosenthal Хортицы 1790 и Rosenthal GRSL 1927 — разные сёла: точки нет.
    rosen = next(r for r in recs if r.extra["name_de"] == "Rosenthal")
    assert rosen.lat is None and rosen.extra["grsl_candidate"] == "g:rosenthal"
    assert rosen.extra["grsl_match"] == "год расходится с GRSL"
    assert rosen.region == "Екатеринославская губерния"
    # Без точки и без года — запись остаётся.
    adaja = next(r for r in recs if r.extra["name_de"] == "Adaja")
    assert adaja.confidence == "no_coords" and adaja.region == "Херсонская губерния"
    assert adaja.date_precision == "unknown"
    assert all(r.layer == LAYER_ID and r.url.startswith("https://www.odessa3.org/") for r in recs)
    assert len(by) == len(recs)


def test_records_without_grsl_have_no_points():
    recs = records({"crimea": CRIMEA})
    assert all(r.lat is None and r.confidence == "no_coords" for r in recs)
    assert recs[0].region == "Таврическая губерния"


def test_registry():
    spec = BY_SLUG[LAYER_ID]
    assert spec is COLONY_LISTS and spec.status == "harvested"
    assert "согласия владельца" in spec.license
