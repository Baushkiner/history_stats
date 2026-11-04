"""Слой гетто и лагерей: карта USHMM, перечень ZRBG, перечень BEG и сведение.

Образцы — фрагменты настоящих данных, снятых 04.11.2026: места томов карты
(«Fastov», «Klooga», «Baranowicze» с точкой в 273 км от города), строки
таблицы ZRBG в виде слов с рамками и линий сетки, строки CALS-таблицы
приложения 6. DV-BEG. Примечаний ZRBG с числами убитых в образцах нет — их не
берёт и разбор; имён людей нет ни в источниках, ни в слое.
"""

import datetime as dt
import json

import pytest

from histctx.sources import beg_camps, ghettos_camps as gc, ushmm, zrbg

# --- карта USHMM -----------------------------------------------------------------

VOL2 = json.dumps({
    "countries": ["Ukraine", "Belarus"],
    "camp_types": {"Ghetto": {"N/A": 1}},
    "places": [
        {"Name": "Fastov", "Type": "Ghetto", "Subtype": "N/A", "Latitude": "50.0833",
         "Longitude": "29.9167", "country": "Ukraine", "_id": 207},
        {"Name": "Baranowicze", "Type": "Ghetto", "Subtype": "N/A", "Latitude": "55.3411",
         "Longitude": "27.8612", "country": "Belarus", "_id": 24},
        {"Name": "Terezín", "Type": "Ghetto", "Subtype": "N/A", "Latitude": "NULL",
         "Longitude": "14.167", "country": "Czech Republic", "_id": 1},
    ],
}, ensure_ascii=False).encode("utf-8")


def test_volume_is_read_as_utf8_and_keeps_places_without_point():
    places, problems = ushmm.parse_volume(VOL2, 2)
    assert [p.name for p in places] == ["Fastov", "Baranowicze", "Terezín"]
    assert places[0].key == "ushmm:2:207" and places[0].lat == 50.0833
    assert places[2].lat is None and "Terezín" in problems[0]


def test_volume_without_required_fields_stops():
    raw = json.dumps({"places": [{"Title": "x"}]}).encode()
    with pytest.raises(ushmm.UshmmError, match="поправьте разбор"):
        ushmm.parse_volume(raw, 1)


def test_category_and_map_link():
    p = ushmm.Place(volume=1, pid=369, name="Klooga", type="Concentration Camp",
                    subtype="Subcamp", country="Estonia", lat=59.3197, lon=24.2112)
    assert ushmm.category(p) == "подлагерь концлагеря SS"
    stalag = ushmm.Place(4, 1, "STALAG 352", "Wehrmacht Prisoner of War Camp (POW Camp)",
                         "Stalag (Mannschaftsstammlager)", "Belarus", 53.9, 27.5)
    assert ushmm.category(stalag) == "лагерь военнопленных вермахта: шталаг"
    url = ushmm.place_url(p)
    assert url.startswith("https://muse.jhu.edu/ushmm/map?volume=1")
    assert "open_name=Klooga" in url and "open_subtype=Subcamp" in url
    odd = ushmm.Place(3, 2, "X", "Unheard Camp", "N/A", "France", 1.0, 1.0)
    assert ushmm.category(odd) == "Unheard Camp"
    assert ushmm.untranslated([odd]) == ["тип «Unheard Camp»"]


# --- перечень ZRBG: слова и сетка ---------------------------------------------------

def _w(x0, y0, text, width=40.0):
    return zrbg.Word(x0, y0, x0 + width, y0 + 9.0, text)


# Колонки как в перечне (линии сетки по x) и три строки таблицы на странице.
COLS = [10.7, 41.0, 126.0, 214.9, 266.2, 329.2, 401.2, 635.2, 779.2, 833.4]


def test_bbox_words_are_read_per_page():
    xhtml = ('<doc><page width="595" height="842"><word xMin="20.2" yMin="47.7" '
             'xMax="31.3" yMax="56.7">Nr.</word><word xMin="76.1" yMin="47.7" xMax="90.7" '
             'yMax="56.7">Ort:</word></page><page width="595" height="842">'
             '<word xMin="1" yMin="2" xMax="3" yMax="4">Lw&#243;w</word></page></doc>')
    pages = zrbg.bbox_words(xhtml)
    assert [len(p) for p in pages] == [2, 1]
    assert pages[1][0].text == "Lwów"


def test_grid_from_rects_turns_the_page_and_adds_up_row_segments():
    # Страница повёрнута на 90°: строка таблицы — тонкая по x PDF. Линия
    # строки нарисована двумя кусками по 412 пт — вместе это вся ширина.
    rects = [(163.56, 10.49, 0.48, 823.14), (182.4, 10.49, 0.48, 412.0),
             (182.4, 422.49, 0.48, 411.0), (210.6, 10.49, 0.48, 823.0),
             (164.0, 10.7, 18.0, 0.48), (164.0, 41.0, 18.0, 0.48), (1, 1, 30, 30)]
    rows, cols = zrbg.grid_from_rects(rects)
    assert rows == [163.8, 182.6, 210.8]
    assert cols == []          # колонки короче 50 пт — не линии сетки
    with pytest.raises(zrbg.ZrbgError, match="90°"):
        zrbg.grid_from_rects(rects, rotate=0)


def _page(rows, words):
    table, loose = zrbg.page_cells(words, rows, COLS)
    return table, loose


def test_words_go_into_cells_and_lines_in_reading_order():
    rows = [42.8, 61.7, 99.5, 127.6]
    words = [
        _w(20, 47.8, "Nr."), _w(76, 47.8, "Ort:"), _w(140, 47.8, "Gebiet:"),
        _w(220, 47.8, "Eröffnung:"), _w(272, 47.8, "Liquidierung:"),
        _w(336, 47.8, "Deportationen:"), _w(490, 47.8, "Bemerkungen:"),
        _w(693, 47.8, "Quelle:"), _w(785, 43.0, "Datum"), _w(785, 52.0, "der Ergänzung"),
        # запись 5614: название в две строки, даты одной строкой
        _w(17, 75.0, "5614", 18), _w(55, 66.0, "Aboltsy"), _w(98, 66.0, "[Bel]", 20),
        _w(55, 75.0, "(Oboltsy"), _w(98, 75.0, "[Rus])", 20),
        _w(132, 70.0, "Reichskommissariat"), _w(132, 79.0, "Weißruthenien"),
        _w(220.6, 75.0, "14.08.1941"), _w(277.7, 75.0, "04.06.1942"),
        _w(646, 75.0, "Encyclopedia", 60), _w(786, 75.0, "24.03.2009"),
        # запись без номера в середине страницы (как Szydlowiec)
        _w(55, 110.0, "Szydlowiec"), _w(140, 110.0, "Distrikt Radom"),
        _w(220.6, 110.0, "01.09.1940"), _w(277.7, 110.0, "13.01.1943"),
        # номер страницы — вне сетки
        _w(825, 561.0, "2", 5),
    ]
    table, loose = _page(rows, words)
    assert [w.text for w in loose] == ["2"]
    assert table[0][0] == ["Nr."]
    assert table[1][1] == ["Aboltsy [Bel]", "(Oboltsy [Rus])"]
    assert table[1][3] == ["14.08.1941"] and table[1][4] == ["04.06.1942"]
    assert table[2][0] == [] and table[2][1] == ["Szydlowiec"]


def _row(nr="", place="", terr="", opened="", liq="", remarks=""):
    cells = [[x] if x else [] for x in (nr, place, terr, opened, liq, "", remarks, "", "")]
    return cells


HEAD = [[x] for x in zrbg.HEADER]


def test_row_split_by_page_break_is_glued_but_a_numberless_record_is_not():
    page1 = [HEAD, _row("5613", "Abaujszanto,", "Ungarn,", "16.04.1944", "13.07.1944"),
             _row("2123", "Antonowka,", "Reichskommissariat", "05.09.1941", "31.12.1941")]
    # первая строка следующей страницы — хвост названия и территории, без номера
    page2 = [HEAD, [[], ["Antonivka)"], ["Ukraine (1941-1944)"], [], [], [], [], [], []],
             _row("1604", "Szydlow", "Distrikt Radom", "01.01.1942", "01.10.1942"),
             _row("", "Szydlowiec", "Distrikt Radom", "01.09.1940", "13.01.1943")]
    entries = zrbg.table_entries([page1, page2])
    assert len(entries) == 4
    assert entries[1].continued and entries[1].cells[1] == ["Antonowka,", "Antonivka)"]
    assert entries[3].cells[0] == [] and not entries[3].continued


def test_numbers_and_lines():
    assert zrbg.main_numbers("5613 (5010)") == ["5613"]
    assert zrbg.old_numbers("3801( 3877)") == ["3877"]
    assert zrbg.main_numbers("(7060) 5932") == ["5932"]
    assert zrbg.join_lines(["Distrikt Lublin (1939-", "1944)"]) == "Distrikt Lublin (1939-1944)"
    assert zrbg.join_lines(["Alsoszopor (Supuru", "de Jos)"]) == "Alsoszopor (Supuru de Jos)"


@pytest.mark.parametrize("raw, iso, precision, approx", [
    ("14.08.1941", "1941-08-14", "day", False),
    ("01. 09.1941", "1941-09-01", "day", False),
    ("16.04 1944", "1944-04-16", "day", False),
    ("01.01..1940", "1940-01-01", "day", False),
    ("24. Juli 1941", "1941-07-24", "day", False),
    ("Ende Mai 1944", "1944-05", "month", True),
    ("Sep 41", "1941-09", "month", False),
    ("??.??.1942", "1942", "year", False),
    ("1942", "1942", "year", False),
    ("131.12.1942", "1942-12-31", "day", True),
    ("31.12.19441", "1944-12-31", "day", True),
    ("01.09.1941 (in Anlehnung an das Ghetto Wilna Nr.2480)", "1941-09-01", "day", True),
    ("30.06.1943 [7]", "1943-06-30", "day", False),
])
def test_dates_of_the_list(raw, iso, precision, approx):
    day = zrbg.parse_day(raw)
    assert (day.iso(), day.precision, day.approx) == (iso, precision, approx)


@pytest.mark.parametrize("raw", ["./.", "./", "?", "", None])
def test_no_date(raw):
    assert zrbg.parse_day(raw) is None


def test_territory_today_region_and_names():
    assert zrbg.territory_countries(
        "Reichskommissariat Ostland (1941-1944), Generalbezirk Weißruthenien, heute "
        "Gebiet Vitebsk") == {"Belarus", "Lithuania"}
    assert zrbg.territory_countries("Ungarn, Operationszone I; heute: Ukraine, Gebiet "
                                    "Zakarpattya") == {"Ukraine"}
    assert zrbg.territory_countries("Transnistrien") == {"Ukraine", "Moldova"}
    assert zrbg.territory_countries("Japan") == set()
    assert zrbg.today_region("Reichskommissariat Ukraine (1941-1944), heute Gebiet Kyjiw") \
        == "Kyjiw"
    # область без «heute» — военных лет, нынешней она не считается
    assert zrbg.today_region("Russland, Gebiet Kalinin") is None
    assert zrbg.region_hint("Russland, Gebiet Kalinin") == "Kalinin"
    assert zrbg.place_names("Aboltsy [Bel] (Oboltsy [Rus], Oboltzi [Yid], Obolce [Pol])") \
        == ["Aboltsy", "Oboltsy", "Oboltzi", "Obolce"]
    assert zrbg.place_names("Balsoi Caranica [Balsaia-Caranica, Balschaja Karanika]") \
        == ["Balsoi Caranica", "Balsaia-Caranica", "Balschaja Karanika"]
    assert zrbg.place_names("Czerwinsk (nad Wisla, an der Weichsel)") == ["Czerwinsk"]
    assert zrbg.place_names("Mosonmagyarovar [Hun, seit 1939] (Moson [Hun, vor 1939])") \
        == ["Mosonmagyarovar", "Moson"]


def test_remarks_give_flags_not_text():
    assert zrbg.remark_flags("kein Ghetto i. S. d. ZRBG: ZAL") == {
        "not_ghetto": True, "not_ghetto_kind": "лагерь принудительного труда"}
    assert zrbg.remark_flags("kein Ghetto i. S. d. ZRBG: Vernichtungslager bis Befreiung")[
        "not_ghetto_kind"] == "лагерь уничтожения"
    assert zrbg.remark_flags("kein Hinweis auf ein Ghetto i. S. d. ZRBG") == {
        "no_evidence": True}
    assert zrbg.remark_flags("Offenes Ghetto") == {"open_ghetto": True}
    flags = zrbg.remark_flags("Das Liquidierungsdatum wurde vom benachbarten Ghetto Nr. "
                              "5137 übernommen")
    assert flags == {"borrowed": True}


def test_entry_marks_rule_dates_and_borrowed_liquidation():
    raw = zrbg.RawEntry(page=3, cells=[
        ["3509"], ["Andreliszky"], ["Reichskommissariat", "Ostland (1941-1944),",
                                    "Generalbezirk Litauen"],
        ["02.08.1941"], ["25.03.1943"], [],
        ["Das Liquidierungsdatum wurde vom benachbarten Ghetto Nr.", "5137 übernommen"],
        ["Kossoy"], ["09.11.2009"]])
    e = zrbg.parse_entry(raw)
    assert e.nr == "3509" and e.name == "Andreliszky"
    assert e.rule == ["opened"]                 # 02.08.1941 — дата «Остланда»
    assert e.liquidated.approx and not e.opened.approx
    assert e.countries == {"Lithuania", "Belarus"}
    assert e.key == "zrbg:3509:andreliszky"


# --- перечень BEG ----------------------------------------------------------------------

BEG_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<dokumente><norm><metadaten><enbez>§ 1</enbez></metadaten></norm>
<norm><metadaten><jurabk>BEGDV 6</jurabk><enbez>Anlage</enbez></metadaten>
<textdaten><text><Content><table><tgroup cols="4">
<colspec colname="col1"/><colspec colname="col2"/><colspec colname="col3"/>
<colspec colname="col4"/>
<thead><row><entry>Lfd. Nr.</entry><entry namest="col2" nameend="col3">KZ</entry>
<entry>Hauptlager</entry></row></thead>
<tbody>
<row><entry> </entry><entry namest="col2" nameend="col3"><B>K</B></entry><entry> </entry></row>
<row><entry morerows="1">705</entry>
  <entry namest="col2" nameend="col3">Kauen = Kaunas/Litauen,</entry>
  <entry> </entry></row>
<row><entry> </entry><entry>15.9.1943 bis 18.8.1944</entry><entry> </entry></row>
<row><entry>720</entry>
  <entry namest="col2" nameend="col3">Kaunas, siehe Kauen</entry>
  <entry> </entry></row>
<row><entry morerows="2">13</entry>
  <entry namest="col2" nameend="col3">Altenburg/Thüringen,</entry>
  <entry>Ravensbrück,</entry></row>
<row><entry morerows="1"> </entry>
  <entry>bis 12.4.1945 (Frauenlager)</entry>
  <entry>ab 1.9.1944</entry></row>
<row><entry>27.11.1944 bis 12.4.1945 (Männerlager)</entry><entry>Buchenwald</entry></row>
<row><entry>1221</entry>
  <entry namest="col2" nameend="col3">Riga, Balastdamm, 18.8.1943 bis 7.8.1944</entry>
  <entry>Riga-Kaiserwald</entry></row>
<row><entry>741</entry>
  <entry namest="col2" nameend="col3">Klooga/Estland, 15.9.1943 bis 19.9.1944</entry>
  <entry>Vaivara</entry></row>
<row><entry>1010</entry>
  <entry namest="col2" nameend="col3">Murru/Estland</entry>
  <entry> </entry></row>
</tbody></tgroup></table></Content></text></textdaten></norm></dokumente>
""".encode("utf-8")


def test_cals_grid_follows_morerows_and_merged_columns():
    rows = beg_camps.table_rows(BEG_XML)
    assert rows[1] == ["705", "Kauen = Kaunas/Litauen,", ""]
    assert rows[2] == ["", "15.9.1943 bis 18.8.1944", ""]
    # строка, где номер и левая колонка заняты сверху, начинается с текста сроков
    assert rows[6] == ["", "27.11.1944 bis 12.4.1945 (Männerlager)", "Buchenwald"]


def test_entries_periods_names_and_references():
    entries = beg_camps.entries(BEG_XML)
    by_nr = {e.nr: e for e in entries}
    assert [e.nr for e in entries] == ["705", "720", "13", "1221", "741", "1010"]
    kauen = by_nr["705"]
    assert kauen.names == ["Kauen", "Kaunas"] and kauen.region == "Litauen"
    assert kauen.periods[0].start == dt.date(1943, 9, 15)
    assert by_nr["720"].is_reference and by_nr["720"].see == "Kauen"
    alt = by_nr["13"]
    assert [p.note for p in alt.periods] == ["Frauenlager", "Männerlager"]
    assert alt.main_camp == "Ravensbrück, ab 1.9.1944 Buchenwald"
    start, end, start_known, end_known = alt.interval()
    # у женского лагеря начала нет — начало записи неизвестно
    assert not start_known and end_known and end == dt.date(1945, 4, 12)
    riga = by_nr["1221"]
    assert riga.place == "Riga" and riga.detail == "Balastdamm"
    assert riga.head == "Riga, Balastdamm"
    assert by_nr["1010"].frame_hint and not by_nr["1010"].periods


def test_periods_three_forms():
    got = beg_camps.parse_periods("Ampfing, bis 2.5.1945 (Lager V und VI, Männer) "
                                  "ab 13.1.1945 (Lager V, Frauen) 1.6.1942 - 20.4.1945")
    assert [(p.start, p.end, p.note) for p in got] == [
        (None, dt.date(1945, 5, 2), "Lager V und VI, Männer"),
        (dt.date(1945, 1, 13), None, "Lager V, Frauen"),
        (dt.date(1942, 6, 1), dt.date(1945, 4, 20), None)]


def test_reference_aliases_go_to_their_target():
    entries = beg_camps.entries(BEG_XML)
    kauen = next(e for e in entries if e.nr == "705")
    assert kauen.aliases == []      # «Kaunas» уже среди написаний самой записи
    raws = [beg_camps.RawEntry("885", ["Lublin/Polen, Gartenstraße 12, 1.10.1941 bis "
                                       "24.7.1944"], []),
            beg_camps.RawEntry("886", ["Lublin/Polen, Alter Flughafen, 22.10.1943 bis "
                                       "24.7.1944"], ["Lublin"]),
            beg_camps.RawEntry("903", ["Majdanek, siehe Lublin"], [])]
    parsed = [beg_camps.parse_entry(r) for r in raws]
    target = beg_camps.resolve("Lublin", [e for e in parsed if not e.is_reference])
    assert target.nr == "885"       # без главного лагеря — сам главный


# --- сведение ------------------------------------------------------------------------

def test_name_key_brings_spellings_together():
    k = gc.name_key
    assert k("Baranowitschi") == k("Baranovichi") == k("Барановичи") == "baranovici"
    assert k("Korzec") == k("Корец")
    assert k("Balanovca") == k("Balanovka")
    assert gc.core_key("Brześć Litewski") == gc.core_key("Brzesc Kujawski") == "bresc"
    assert gc.core_key("Stary Dashev") == gc.compact(k("Dashev"))


def test_ushmm_names():
    assert gc.ushmm_names("Kauen Main Camp (Kaunas, Kovno, Kowno, Slobodka)")[:2] == (
        "Kauen", ["Kauen", "Kaunas", "Kovno", "Kowno", "Slobodka"])
    main, parts, full = gc.ushmm_names("Radom (Radom (Szkolna Street))")
    assert main == "Radom" and "Szkolna Street" in parts
    assert gc.ushmm_names("Gomel’ (Vitebsk Oblast’)")[1] == ["Gomel’"]
    assert gc.ushmm_specific("Kottern / Fischen") == ["Fischen"]
    assert "Breslau I" in gc.ushmm_names("Breslau I")[2]


def _place(vol, pid, name, country, lat, lon, typ="Ghetto", sub="N/A"):
    return ushmm.Place(vol, pid, name, typ, sub, country, lat, lon)


def _zentry(nr, names, territory, opened="01.09.1941", liq="01.12.1941", page=1):
    raw = zrbg.RawEntry(page=page, cells=[[nr], [", ".join(names)], [territory], [opened],
                                          [liq], [], [], [], []])
    return zrbg.parse_entry(raw)


def test_zrbg_goes_to_the_ghetto_with_the_same_name_and_country():
    places = [_place(2, 207, "Fastov", "Ukraine", 50.08, 29.92),
              _place(2, 300, "Fastov", "Poland", 52.0, 21.0)]
    e = _zentry("3628", ["Fastov"], "Reichskommissariat Ukraine (1941-1944), heute Gebiet Kyjiw",
                "05.09.1941", "01.12.1941")
    matched, unmatched, ambiguous = gc.match_zrbg(places, [e])
    assert list(matched) == ["ushmm:2:207"] and not unmatched and not ambiguous
    assert matched["ushmm:2:207"].how == "ZRBG: главное название, страна сверена"


def test_zrbg_namesakes_in_one_country_stay_unmatched_but_marked():
    places = [_place(2, 1, "Gomel’ (Gomel’ Oblast’)", "Belarus", 52.4, 31.0),
              _place(2, 2, "Gomel’ (Vitebsk Oblast’)", "Belarus", 55.3, 28.8)]
    e = _zentry("3652", ["Gomel"], "Reichskommissariat Ostland (1941-1944), Generalbezirk "
                                   "Weißruthenien")
    matched, unmatched, ambiguous = gc.match_zrbg(places, [e])
    assert ambiguous and ambiguous[0][1] == ["ushmm:2:1", "ushmm:2:2"]
    assert all(m.ambiguous == [e.key] and not m.entries for m in matched.values())
    # область в скобках карты разводит тёзок
    e2 = _zentry("5057", ["Homyel", "Gomel"],
                 "Reichskommissariat Ostland, heute: Belarus, Gebiet Gomel")
    matched, _, ambiguous = gc.match_zrbg(places, [e2])
    assert not ambiguous and matched["ushmm:2:1"].entries == [e2]


def test_zrbg_dates_rule_dates_and_open_end():
    frame = gc.Frame(1941, 1944, gc.DATE_OCCUPATION, "рамка оккупации территории: Украина")
    e = _zentry("3628", ["Fastov"], "Reichskommissariat Ukraine (1941-1944)",
                "05.09.1941", "01.12.1941")
    d = gc.zrbg_dating([e], frame)
    assert (d.year_from, d.year_to, d.precision, d.approx) == (1941, 1941, "day", True)
    e2 = _zentry("1331", ["Czernice"], "Preußen (Provinz Ostpreußen)", "?", "21.08.1942")
    d2 = gc.zrbg_dating([e2], frame)
    assert (d2.year_from, d2.year_to, d2.precision) == (1941, 1942, "open")
    assert "второй конец" in d2.raw
    inverted = _zentry("5700", ["Berezki"], "Transnistrien", "30.08.1941", "30.03.1941")
    d3 = gc.zrbg_dating([inverted], frame)
    assert d3.extra["dates_inverted"] and d3.approx


def test_beg_matching_by_full_name_alias_and_main_camp():
    places = [_place(1, 1007, "Riga (Balastdamm)", "Latvia", 56.95, 24.08,
                     "Concentration Camp", "Subcamp"),
              _place(1, 1008, "Riga (Dünawerke)", "Latvia", 56.99, 24.11,
                     "Concentration Camp", "Subcamp"),
              _place(1, 440, "Lublin Main Camp (Majdanek)", "Poland", 51.22, 22.6,
                     "Concentration Camp", "Main Camp"),
              _place(1, 439, "Lublin (Alter Flughafen)", "Poland", 51.25, 22.57,
                     "Concentration Camp", "Subcamp"),
              _place(1, 391, "Königsberg", "Russia", 54.72, 20.5, "Concentration Camp",
                     "Subcamp"),
              _place(1, 392, "Königsberg (Neumark)", "Poland", 52.88, 14.13,
                     "Concentration Camp", "Subcamp")]
    entries = [beg_camps.parse_entry(beg_camps.RawEntry(nr, [text], [main] if main else []))
               for nr, text, main in (
                   ("1221", "Riga, Balastdamm, 18.8.1943 bis 7.8.1944", "Riga-Kaiserwald"),
                   ("885", "Lublin/Polen, Gartenstraße 12, 1.10.1941 bis 24.7.1944", ""),
                   ("886", "Lublin/Polen, Alter Flughafen, 22.10.1943 bis 24.7.1944", ""),
                   ("755", "Königsberg/Ostpreußen, 19.8.1944 bis 15.1.1945", "Stutthof"))]
    entries[1].aliases = ["Majdanek"]
    matched, unmatched, ambiguous = gc.match_beg(places, entries)
    got = {key: [e.nr for e in m.entries] for key, m in matched.items() if m.entries}
    assert got == {"ushmm:1:1007": ["1221"], "ushmm:1:440": ["885"],
                   "ushmm:1:439": ["886"], "ushmm:1:391": ["755"]}
    assert not unmatched and not ambiguous


def test_beg_dates_with_one_known_end_are_open():
    frame = gc.Frame(1941, 1944, gc.DATE_OCCUPATION, "рамка оккупации территории: Эстония")
    e = beg_camps.parse_entry(beg_camps.RawEntry("52a", ["Auvere/Estland, ab 15.9.1943"],
                                                 ["Vaivara"]))
    d = gc.beg_dating([e], frame)
    assert (d.year_from, d.year_to, d.precision) == (1943, 1944, "open")
    full = beg_camps.parse_entry(beg_camps.RawEntry("741", [
        "Klooga/Estland, 15.9.1943 bis 19.9.1944"], ["Vaivara"]))
    assert gc.beg_dating([full], frame).precision == "day"
    assert gc.beg_dating([beg_camps.parse_entry(
        beg_camps.RawEntry("1010", ["Murru/Estland"], []))], frame) is None


CITY = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [29.9167, 50.0667]},
        "properties": {"uid": "occupation_cities:x", "category": "оккупация",
                       "place_text": "Фастов", "year_from": 1941, "year_to": 1943,
                       "extra": {"occupied": "1941-07-23", "liberated": "1943-11-07"}}}


def test_frames_city_territory_war_and_volume():
    cities = gc.occupation_frames([CITY])
    f = gc.place_frame(inside=True, country="Ukraine", lat=50.08, lon=29.92, volume=2,
                       cities=cities)
    assert (f.year_from, f.year_to, f.kind) == (1941, 1943, gc.DATE_OCCUPATION)
    assert "Фастов" in f.raw and dict(f.extra)["city"] == "Фастов"
    f = gc.place_frame(inside=True, country="Latvia", lat=56.5, lon=21.0, volume=1,
                       cities=cities)
    assert (f.year_from, f.year_to) == (1941, 1945)
    f = gc.place_frame(inside=True, country="Russia", lat=54.7, lon=20.5, volume=4,
                       cities=cities)
    assert (f.year_from, f.kind) == (1939, gc.DATE_WAR)
    f = gc.place_frame(inside=False, country="Germany", lat=51.0, lon=11.0, volume=1,
                       cities=cities)
    assert (f.year_from, f.year_to, f.kind) == (1933, 1945, gc.DATE_VOLUME)


def _geo(*items):
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
              "properties": {"title": title, "source_id": gid,
                             "extra": {"country": country, "population_modern": pop,
                                       "name_latin": latin}}}
             for gid, title, latin, country, lat, lon, pop, _ in items]
    variants = {gid: {"names": names} for gid, *_, names in items}
    return gc.geonames_index(feats, variants)


# Слой settlements и указатель написаний, как в data/out: у Барановичей среди
# написаний есть польское, у Фастова — русское латиницей.
GEO = _geo(("630429", "Барановичи", "Baranovichi", "Белоруссия", 53.1327, 26.0139, 170039,
            ["Baranavichy", "Baranowicze"]),
           ("629634", "Брест", "Brest", "Белоруссия", 52.0975, 23.6877, 300715, ["Brest"]),
           ("709248", "Фастив", "Fastiv", "Украина", 50.0761, 29.9177, 49400, ["Fastov"]),
           ("703448", "Киев", "Kyiv", "Украина", 50.4547, 30.5238, 2797553, ["Kiev", "Kyjiw"]))


def inside_frame(lat, lon):
    return True, "Киевская губерния" if lat < 51 else "Минская губерния", False


def test_record_with_zrbg_dates_city_label_and_geonames_check():
    cities = gc.occupation_frames([CITY])
    fastov = _place(2, 207, "Fastov", "Ukraine", 50.0833, 29.9167)
    e = _zentry("3628", ["Fastov"], "Reichskommissariat Ukraine (1941-1944), heute Gebiet Kyjiw",
                "05.09.1941", "01.12.1941", page=36)
    built = gc.build_records([fastov], [e], [], geo_index=GEO, cities=cities,
                             frame_place=inside_frame)
    rec = built.records[0]
    assert rec.title == "Fastov (Фастов)"     # подпись — из справочника, а не «Фастив»
    assert rec.category == "гетто" and rec.region == "Киевская губерния"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1941, 1941, "day")
    assert rec.extra["date_source"] == "ZRBG" and rec.extra["zrbg"][0]["nr"] == "3628"
    assert rec.extra["geonames"]["name"] == "Фастив" and rec.confidence == "ok"
    assert rec.work == "Великая Отечественная война"
    assert "правовая" in rec.summary and rec.url.startswith(ushmm.MAP_URL)


def test_point_far_from_its_town_is_marked_not_moved():
    bar = _place(2, 24, "Baranowicze", "Belarus", 55.3411, 27.8612)
    e = _zentry("5007", ["Baranowitschi", "Baranovichi", "Baranowicze"],
                "Reichskommissariat Ostland (Weißruthenien); heute: Belarus, Gebiet Brest",
                "02.08.1941", "30.11.1943")
    built = gc.build_records([bar], [e], [], geo_index=GEO, cities=[],
                             frame_place=inside_frame)
    rec = built.records[0]
    assert rec.confidence == gc.CONF_SUSPECT
    assert (rec.lat, rec.lon) == (55.3411, 27.8612)
    assert rec.extra["geonames_far"]["name"] == "Барановичи"
    assert rec.extra["geonames_far"]["km"] > 250
    assert rec.extra["date_source"] == "ZRBG"


def test_false_match_is_undone_by_territory():
    # Radomysl nad Sanem из дистрикта Краков — не житомирский Радомышль
    radomyshl = _place(2, 700, "Radomyshl’", "Ukraine", 50.5, 29.23)
    e = _zentry("1531", ["Radomysl nad Sanem", "Radomysl"],
                "Generalgouvernement, Distrikt Krakau (1939-1944)", "01.06.1942", "02.11.1942")
    built = gc.build_records([radomyshl], [e], [], geo_index=GEO, cities=[],
                             frame_place=inside_frame)
    assert built.zrbg_rejected and built.zrbg_rejected[0][1] == "ushmm:2:700"
    ghetto, own = built.records
    assert ghetto.extra["date_source"] == gc.DATE_OCCUPATION and ghetto.date_approx
    assert own.source_id == e.key and own.category == "гетто (по перечню ZRBG)"


def test_unmatched_entries_are_kept_without_point():
    beg_only = beg_camps.parse_entry(beg_camps.RawEntry(
        "1464", ["Treblinka II, Kreis Sokolow bei Warschau, 1.6.1942 bis 30.11.1943"], []))
    silesia = beg_camps.parse_entry(beg_camps.RawEntry(
        "1336", ["Schwarzheide/Brandenburg, 5.7.1944 bis 16.4.1945"], ["Sachsenhausen"]))
    not_ghetto = _zentry("7235", ["Maly Trostinec"], "Reichskommissariat Ostland, Weißrussland",
                         "./.", "./.")
    not_ghetto.flags = zrbg.remark_flags("kein Ghetto i. S. d. ZRBG: Vernichtungslager")
    built = gc.build_records([], [not_ghetto], [beg_only, silesia], geo_index=GEO, cities=[],
                             frame_place=inside_frame)
    by_id = {r.source_id: r for r in built.records}
    tre = by_id["beg:1464"]
    assert not tre.has_point and tre.confidence == "no_coords"
    assert (tre.year_from, tre.year_to, tre.date_precision) == (1942, 1943, "day")
    assert tre.place_text == "Treblinka II, Kreis Sokolow bei Warschau"
    assert by_id["beg:1336"].confidence == "outside_bbox"
    mt = by_id[not_ghetto.key]
    assert mt.category == "лагерь уничтожения (по перечню ZRBG — не гетто)"
    assert mt.extra["date_source"] == gc.DATE_OCCUPATION and mt.date_precision == "era"


def test_outside_frame_point_is_marked_and_dated_by_volume():
    buchenwald = _place(1, 100, "Abteroda", "Germany", 50.9, 10.07, "Concentration Camp",
                        "Subcamp")
    e = beg_camps.parse_entry(beg_camps.RawEntry("1", ["Abteroda, Kreis Eisenach",
                                                       "bis 8.4.1945"], ["Buchenwald"]))
    built = gc.build_records([buchenwald], [], [e], geo_index=GEO, cities=[],
                             frame_place=lambda lat, lon: (False, None, False))
    rec = built.records[0]
    assert rec.confidence == "outside_bbox" and rec.region is None
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1933, 1945, "open")
    assert rec.work == "Вторая мировая война"
