"""Метрические книги приходов: открытые данные Rahvusarhiiv (apeEAD XML).

Образцы — фрагменты настоящих файлов каталога от 04.11.2026: шапка и восемь
единиц описания фонда «EELK Kambja kogudus» (`RA_EAA1255.xml`, снимок от
31.01.2020) — распоряжение консистории о метрических книгах, сводная
метрика за 1719–1793 годы, три погодовые книги (одна — без скана, для
проверки счёта), книга рождений, персональная книга с перечнем мыз и книга
причастников; плюс кусок страницы листинга.
"""

import pytest

from histctx.sources.maaamet import Feature, Parish, wgs84_to_lest97
from histctx.sources.rahvusarhiiv import (
    FILE_URL, KIND_BIRTHS, KIND_COMMUNION, KIND_METRICAL, KIND_PERSONAL, PARISH_REGISTERS_EE,
    Head, Match, ParishIndex, Unit, book_entry, fond_books, fond_confession, fond_record,
    format_ranges, gaps, is_candidate, listing_pages, parish_place, parish_summary, parse_fond,
    parse_head, parse_listing, unit_kind, unit_years, year_ranges,
)

LISTING = """
<tr class="odd"><td><a href="/apps/opendata/zip2/RA_EAA1255.xml">RA_EAA1255.xml</a>
<a href="/apps/opendata/zip2/RA_EAAT-13.xml">RA_EAAT-13.xml</a>
<a href="/apps/opendata/zip2/EAA_M4.xml">EAA_M4.xml</a> </td></tr>
<li class="page"><a href="/apps/opendata/index.php/site/index?page=2">2</a></li>
<li class="last"><a href="/apps/opendata/index.php/site/index?page=379">&gt;&gt;</a></li>
"""

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<ead xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns="urn:isbn:1-931666-22-9" audience="external">
   <eadheader countryencoding="iso3166-1" dateencoding="iso8601">
      <eadid identifier="EE-RA_EAA.1255" countrycode="EE" mainagencycode="EE-RA"
             url="http://ais.ra.ee/index.php?module=202&amp;op=4&amp;tyyp=2&amp;kokku=1&amp;id=200100000846">EAA.1255</eadid>
      <filedesc>
         <titlestmt>
            <titleproper encodinganalog="245">EELK Kambja kogudus<lb/>Evangelisch-Lutherische \
St Martini und St Marien Kirche in zu Kamby</titleproper>
         </titlestmt>
      </filedesc>
   </eadheader>
   <archdesc level="fonds" type="inventory" encodinganalog="3.1.4">
      <did>
         <unitid encodinganalog="3.1.1" type="call number">EAA.1255</unitid>
         <unitdate calendar="gregorian" era="ce" normal="1677-01-01/1947-12-31"
                   encodinganalog="3.1.3">1677-1947</unitdate>
         <unittitle encodinganalog="3.1.2">EELK Kambja kogudus</unittitle>
      </did>
"""


def _unit(code, normal, text, title, scan=True):
    dao = (f'<dao xlink:href="http://www.ra.ee/dgs/_purl.php?shc={code}&amp;lng=eng" '
           'xlink:title="See document" xlink:role="UNSPECIFIED"/>') if scan else ""
    return (f'<c level="file"><did><unitid type="call number">{code}</unitid>'
            f'<unitdate normal="{normal}">{text}</unitdate>'
            f'<unittitle type="est">{title}</unittitle>{dao}</did></c>')


def _section(level, title, *children):
    return (f'<c level="{level}"><did><unitid type="call number">EAA.1255</unitid>'
            f'<unittitle type="est">{title}</unittitle></did>{"".join(children)}</c>')


FOND = (HEAD + '<dsc type="othertype"><c level="fonds"><did><unitid>EAA.1255</unitid>'
        '<unittitle type="est">EELK Kambja kogudus</unittitle></did>'
        + _section("fonds", "I Pastori kantselei",
                   _section("series", "1. Seadusandlikud aktid",
                            _unit("EAA.1255.1.34", "1820-01-01/1830-12-31", "1820-1830",
                                  "Liivimaa Ülemkonsistooriumi korraldused Kambja kogudusele "
                                  "paranduste tegemise asjus meetrikaraamatutes, abielulahutuste "
                                  "ja muis asjus", scan=False)),
                   _section("series", "4. Kirikuraamatud ja nimistud",
                            _section("subseries", "4.1 Sünni-, abielu- ja surmameetrika",
                                     _unit("EAA.1255.2.1", "1719-01-01/1793-12-31", "1719-1793",
                                           "Sünni-, abielu-, surmameetrika ja andmed koguduse "
                                           "tegevuse kohta"),
                                     _unit("EAA.1255.1.108", "1834-01-01/1834-12-31", "1834",
                                           "Meetrikaraamat"),
                                     _unit("EAA.1255.1.109", "1835-01-01/1835-12-31", "1835",
                                           "Meetrikaraamat", scan=False),
                                     _unit("EAA.1255.1.111", "1837-01-01/1837-12-31", "1837",
                                           "Meetrikaraamat")),
                            _section("subseries", "4.2 Sündinute nimistud",
                                     _unit("EAA.1255.1.526", "1892-01-01/1906-12-31", "1892-1906",
                                           "Sündinute ja ristitute nimekiri")),
                            _section("subseries", "4.5 Armulaualiste nimistud",
                                     _unit("EAA.1255.1.140", "1834-01-01/1846-12-31", "1834-1846",
                                           "Armulaualiste raamat")),
                            _section("subseries", "4.7 Personaalraamatud",
                                     _unit("EAA.1255.1.514", "1845-01-01/1881-12-31", "1845-1881",
                                           "Personaalraamat. Kriimanni, Vana-Kuuste, "
                                           "Vastse-Kuuste"))))
        + "</c></dsc></archdesc></ead>")


# --- листинг и шапка ------------------------------------------------------------

def test_listing_gives_file_names_and_page_count():
    assert parse_listing(LISTING) == ["RA_EAA1255.xml", "RA_EAAT-13.xml", "EAA_M4.xml"]
    assert listing_pages(LISTING) == 379


def test_candidates_are_numbered_fonds_of_the_historical_and_tallinn_archives():
    assert is_candidate("RA_EAA1255.xml") and is_candidate("RA_TLA31.xml")
    # Советские фонды тех же архивов: за префиксом буква, а не номер.
    assert not is_candidate("RA_EAAT-13.xml") and not is_candidate("EAA_M4.xml")
    assert not is_candidate("RA_ERA1749.xml")


def test_head_is_read_from_a_truncated_file():
    head = parse_head("RA_EAA1255.xml", HEAD.encode()[:2000])
    assert head.code == "EAA.1255"
    assert head.title == "EELK Kambja kogudus"
    assert head.title_alt.startswith("Evangelisch-Lutherische") and head.title_alt.endswith("Kamby")
    assert head.dates == "1677-1947"
    assert head.ais_url.startswith("http://ais.ra.ee/") and "&amp;" not in head.ais_url
    assert head.url == FILE_URL.format(name="RA_EAA1255.xml")


@pytest.mark.parametrize("title, confession", [
    ("EELK Kambja kogudus", "лютеранский"),
    ("EELK Narva rootsi-soome kogudus", "лютеранский"),
    ("Tartu Uspenski õigeusu kogudus", "православный"),
    ("Tartu Rooma-Katoliku kogudus", "католический"),
    ("Kasepää vanausuliste kogudus", "старообрядческий"),
    ("Eestimaa Evangeeliumi Luteri Usu Konsistoorium", None),   # не приход
    ("Tallinna Oleviste kiriku taastamise ehituskomitee", None),
    ("Tartu Baptisti kogudus", None),                          # без признака — в отчёт сбора
])
def test_confession_is_read_from_the_fond_title(title, confession):
    assert fond_confession(title) == confession


# --- фонд и книги ---------------------------------------------------------------

def test_fond_is_parsed_with_units_and_sections():
    fond = parse_fond(FOND.encode())
    assert fond.code == "EAA.1255" and fond.title == "EELK Kambja kogudus"
    assert fond.title_alt.endswith("zu Kamby") and fond.dates == "1677-1947"
    assert len(fond.units) == 8
    unit = next(u for u in fond.units if u.code == "EAA.1255.1.108")
    assert (unit.year_from, unit.year_to) == (1834, 1834)
    assert unit.scan_url == "http://www.ra.ee/dgs/_purl.php?shc=EAA.1255.1.108&lng=eng"
    assert unit.path[-2:] == ("4. Kirikuraamatud ja nimistud",
                              "4.1 Sünni-, abielu- ja surmameetrika")


def test_books_are_told_from_papers_about_books():
    fond = parse_fond(FOND.encode())
    kinds = {u.code: unit_kind(u) for u in fond.units}
    assert kinds["EAA.1255.1.34"] is None                 # распоряжение о книгах
    assert kinds["EAA.1255.2.1"] == KIND_METRICAL
    assert kinds["EAA.1255.1.108"] == KIND_METRICAL
    assert kinds["EAA.1255.1.526"] == KIND_BIRTHS
    assert kinds["EAA.1255.1.140"] == KIND_COMMUNION
    assert kinds["EAA.1255.1.514"] == KIND_PERSONAL


def test_flat_inventory_still_finds_a_metrical_book():
    # Опись без разделов: вид книги — по названию.
    assert unit_kind(Unit("EAA.1.1.1", "Meetrikaraamat", 1850, 1850, "1850", None)) == KIND_METRICAL
    assert unit_kind(Unit("EAA.1.1.2", "Sünnimeetrika", 1850, 1860, "", None)) == KIND_BIRTHS
    # «Список умерших» среди ревизских списков — не книга прихода.
    revision = ("5. Revisjoni- ja ümberkirjutuslehed. Registrid ja nimekirjad",)
    assert unit_kind(Unit("EAA.1.1.3", "Surnute nimistu", 1850, 1860, "", None, revision)) is None


@pytest.mark.parametrize("normal, text, years", [
    ("1834-01-01/1834-12-31", "1834", (1834, 1834)),
    ("1719-01-01/1793-12-31", "1719-1793", (1719, 1793)),
    ("1890/1885", "", (1885, 1890)),
    (None, "11.07.1822-21.02.1918", (1822, 1918)),
    (None, "17s", (None, None)),
])
def test_unit_years(normal, text, years):
    assert unit_years(normal, text) == years


def test_year_ranges_merge_and_show_gaps():
    units = [Unit("a", None, 1719, 1793, None, None), Unit("b", None, 1834, 1834, None, None),
             Unit("c", None, 1835, 1835, None, None), Unit("d", None, 1837, 1837, None, None),
             Unit("e", None, None, None, None, None)]
    ranges = year_ranges(units)
    assert ranges == [(1719, 1793), (1834, 1835), (1837, 1837)]
    assert format_ranges(ranges) == "1719–1793, 1834–1835, 1837"
    assert format_ranges(gaps(ranges)) == "1794–1833, 1836"


def test_book_entry_keeps_the_title_only_when_it_says_something():
    fond = parse_fond(FOND.encode())
    books = fond_books(fond)
    entries = {e["shc"]: e for e in (book_entry(u, k) for u, k in books.metrical + books.other)}
    assert entries["EAA.1255.1.108"] == {
        "shc": "EAA.1255.1.108", "kind": KIND_METRICAL, "years": "1834",
        "scan": "http://www.ra.ee/dgs/_purl.php?shc=EAA.1255.1.108&lng=eng"}
    assert "scan" not in entries["EAA.1255.1.109"]
    assert entries["EAA.1255.1.514"]["title"].endswith("Vastse-Kuuste")


# --- сведение с кирхшпилем ---------------------------------------------------------

@pytest.mark.parametrize("title, place", [
    ("EELK Kambja kogudus", "Kambja"),
    ("EELK Tartu Maarja kogudus", "Tartu Maarja"),
    ("Tartu Uspenski õigeusu kogudus", "Tartu Uspenski"),
    ("EELK Järva-Peetri kogudus", "Järva-Peetri"),
])
def test_place_is_cut_out_of_the_fond_title(title, place):
    assert parish_place(title) == place


def _parish(name, lat, lon, **kw):
    x, y = wgs84_to_lest97(lat, lon)
    ring = [(x - 8000, y - 8000), (x + 8000, y - 8000), (x + 8000, y + 8000),
            (x - 8000, y + 8000), (x - 8000, y - 8000)]
    return Parish(name=name, county_src=kw.get("county", "Tartu"), county=kw.get("county", "Tartu"),
                  governorate_src="Liivimaa", polygons=[[ring]], x=x, y=y, lat=lat, lon=lon,
                  area_km2=256.0)


@pytest.fixture
def index():
    parishes = [_parish("Kambja", 58.24, 26.70), _parish("Tartu-Maarja", 58.38, 26.72),
                _parish("Peetri", 58.80, 25.85, county="Järva")]
    manor = Feature(fid="moisakeskus.1", props={"NIMI": "Kärsa", "KIHELKOND": "Kambja",
                                                 "KUBERMANG": "Liivimaa", "MAAKOND": "Tartu"},
                    point=wgs84_to_lest97(58.25, 26.71))
    return ParishIndex.build(parishes, [manor])


def test_rural_parish_is_matched_by_name(index):
    match = index.match("EELK Kambja kogudus")
    assert match.kind == "кирхшпиль" and match.parish == "Kambja"
    assert (match.lat, match.lon) == (58.24, 26.70)
    assert match.region == "Лифляндская губерния" and match.district == "Юрьевский уезд"
    assert "не храм" in match.note
    assert index.match("EELK Tartu Maarja kogudus").parish == "Tartu-Maarja"


def test_town_parish_gets_the_town_point_and_the_parish_it_lies_in(index):
    match = index.match("EELK Tartu Jaani kogudus")
    assert match.kind == "город" and match.town == "Tartu"
    assert match.parish == "Tartu-Maarja"            # город лежит в полигоне кирхшпиля
    assert (match.lat, match.lon) == (58.3801, 26.7224)


def test_town_outside_the_parish_polygons_keeps_its_own_region(index):
    match = index.match("EELK Valga Jaani kogudus")
    assert match.kind == "город" and match.parish is None
    assert match.region == "Лифляндская губерния" and match.district == "Валкский уезд"


def test_single_name_matched_only_by_a_manor_is_flagged(index):
    # В наборе только мызы: одноимённая деревня в другом уезде возможна.
    match = index.match("Kärsa õigeusu kogudus")
    assert match.kind == "мыза по имени" and match.manor == "Kärsa" and match.parish == "Kambja"
    assert "тёзка" in match.note


def test_unknown_place_is_kept_unmatched(index):
    match = index.match("EELK Loksa kogudus")
    assert match.kind == "не сведён" and match.lat is None and match.place == "Loksa"


# --- запись --------------------------------------------------------------------------

def test_fond_record_carries_years_codes_and_scans(index):
    fond = parse_fond(FOND.encode())
    head = parse_head("RA_EAA1255.xml", HEAD.encode())
    rec = fond_record(head, "лютеранский", fond, index.match(fond.title))
    assert rec.layer == PARISH_REGISTERS_EE.slug
    assert rec.title == "Метрические книги прихода Kambja (EELK Kambja kogudus)"
    assert rec.category == "лютеранский приход"
    assert (rec.year_from, rec.year_to) == (1719, 1906) and rec.date_precision == "year"
    assert rec.period_raw == "1719–1793, 1834–1835, 1837, 1892–1906"
    assert rec.confidence == "parish_centroid" and rec.url == head.url
    assert rec.source_id == "EAA.1255"
    metrical = rec.extra["metrical"]
    assert metrical == {"units": 5, "scans": 4, "years": "1719–1793, 1834–1835, 1837, 1892–1906",
                        "gaps": "1794–1833, 1836, 1838–1891"}
    assert rec.extra["other_books"][KIND_PERSONAL] == {"units": 1, "scans": 1, "years": "1845–1881"}
    assert rec.extra["point"].startswith("центр территории кирхшпиля Kambja")
    assert len(rec.extra["books"]) == 7
    assert "5 метрических книг за 1719–1906 годы" in rec.summary
    summary = parish_summary(rec)
    assert summary == {"fond": "EAA.1255", "title": "EELK Kambja kogudus",
                       "confession": "лютеранский", "books": 5, "scans": 4,
                       "years": "1719–1793, 1834–1835, 1837, 1892–1906", "url": head.url}


def test_fond_without_metrical_books_stays_undated():
    fond = parse_fond(FOND.encode())
    fond.units = [u for u in fond.units if unit_kind(u) not in (KIND_METRICAL, KIND_BIRTHS)]
    head = Head("RA_EAA1255.xml", "EAA.1255", "EELK Kambja kogudus", None, None)
    rec = fond_record(head, "лютеранский", fond, Match(kind="не сведён", place="Kambja"))
    assert rec.year_from is None and rec.confidence == "no_registers"
    assert rec.title.startswith("Фонд прихода Kambja")
    assert "метрических книг в описи нет" in rec.summary


def test_layer_is_declared_for_the_registry():
    assert PARISH_REGISTERS_EE.group == "faith" and PARISH_REGISTERS_EE.status == "harvested"
    assert "CC0" in PARISH_REGISTERS_EE.license and "CC BY-SA" in PARISH_REGISTERS_EE.license
    assert len(PARISH_REGISTERS_EE.description) > 40
    assert PARISH_REGISTERS_EE.expected_rows == 322      # сбор 04.11.2026


def test_parish_named_otherwise_in_1917_goes_through_the_alias(index):
    match = index.match("EELK Järva-Peetri kogudus")
    assert match.kind == "кирхшпиль" and match.parish == "Peetri"


def test_volost_qualifier_points_to_the_place(index):
    # «Jaama» — четыре мызы в разных кирхшпилях; уточнение «Kambja vallas» решает.
    assert parish_place("EAÕK Jaama kogudus Kambja vallas") == "Jaama"
    match = index.match("EAÕK Jaama kogudus Kambja vallas")
    assert match.kind == "кирхшпиль" and match.parish == "Kambja"


def test_double_name_prefers_the_manor_standing_in_the_named_parish(index):
    match = index.match("EAÕK Kambja-Kärsa kogudus")
    assert match.kind == "мыза" and match.manor == "Kärsa" and match.parish == "Kambja"


def test_double_name_led_by_a_parish_goes_to_that_parish(index):
    # «Võnnu-Kärsa»: единственная мыза Kärsa стоит в другом кирхшпиле.
    match = index.match("EAÕK Peetri-Kärsa kogudus")
    assert match.kind == "кирхшпиль" and match.parish == "Peetri"


def test_double_name_with_quarrelling_halves_stays_unmatched_with_candidates(index):
    # «Seli-Tõstamaa» и «Pootsi-Kõpu»: кирхшпиль назван второй, мыза — в другом.
    match = index.match("EAÕK Kärsa-Peetri kogudus")
    assert match.kind == "не сведён" and match.lat is None
    assert match.candidates == ["кирхшпиль Peetri", "мыза Kärsa (кирхшпиль Kambja)"]


def test_two_halves_naming_manors_of_one_parish_agree():
    # «Haanja-Plaani»: обе мызы стоят в Рыуге — два независимых имени согласны.
    parishes = [_parish("Rõuge", 57.73, 26.92)]
    manors = [Feature(fid=f"moisakeskus.{i}", props={"NIMI": name, "KIHELKOND": "Rõuge"},
                      point=wgs84_to_lest97(57.73 + d, 26.92 + d))
              for i, (name, d) in enumerate((("Haanja", 0.01), ("Plaani", -0.01)))]
    match = ParishIndex.build(parishes, manors).match("EAÕK Haanja-Plaani kogudus")
    assert match.kind == "мыза" and match.manor == "Haanja" and match.parish == "Rõuge"


def test_town_fond_summary_says_it_is_a_town_parish(index):
    from histctx.sources.rahvusarhiiv import summary_order
    fond = parse_fond(FOND.encode())
    head = parse_head("RA_EAA1255.xml", HEAD.encode())
    def summary(title):
        return parish_summary(fond_record(head, "лютеранский", fond, index.match(title)))

    town, own = summary("EELK Tartu Jaani kogudus"), summary("EELK Tartu Maarja kogudus")
    assert town["match"] == "город" and town["town"] == "Tartu" and "match" not in own
    assert sorted([town, own], key=summary_order) == [own, town]


@pytest.mark.parametrize("title, code, confession", [
    ("Tallinna Niguliste Kogudus", "TLA.31", "лютеранский"),
    ("Tallinna Toomkogudus", "TLA.237", "лютеранский"),         # «kogudus» в конце слова
    ("Harju - Madise kogudus", "TLA.1", "лютеранский"),
    ("Tallinna Niguliste Kogudus", "EAA.31", None),             # вне TLA вывода нет
    ("Tallinna Eesti Pühavaimu Koguduse Laulu ja Muusika Selts", "TLA.21", None),
    ("Tallinna juudi kogudus", "TLA.999", "иудейский"),
    ("91. jalaväe Dvinski polgu kiriku kogudus", "TLA.1445", "православный"),
    ("Tallinna Saksa-Prantsuse Evangeelse Reformeeritud Kiriku Kogudus", "TLA.1469",
     "реформатский"),
    ("Tallinna Oleviste Koguduse Poeg- ja Tütarlaste Vaestekool", "TLA.877", None),
    ("Tallinna Aleksander Nevski Peakiriku Koguduse Hoolekanne", "TLA.1339", None),
    ("Tallinna Allika Baptistikogudus", "TLA.1473", None),
])
def test_tallinn_city_archive_names_lutheran_parishes_without_a_sign(title, code, confession):
    assert fond_confession(title, code) == confession


def test_tla_parish_record_says_its_confession_is_inferred(index):
    fond = parse_fond(FOND.encode())
    fond.title, fond.code = "Harju - Madise kogudus", "TLA.1"
    head = Head("RA_TLA1.xml", "TLA.1", "Harju - Madise kogudus", None, None)
    rec = fond_record(head, "лютеранский", fond, index.match(fond.title))
    assert rec.extra["confession_from"].startswith("в названии фонда TLA")
    assert parish_place("Harju - Madise kogudus") == "Harju - Madise"


def test_military_church_confession_is_marked_as_inferred():
    from histctx.sources.rahvusarhiiv import TLA_MILITARY_NOTE, confession_note
    assert confession_note("91. jalaväe Dvinski polgu kiriku kogudus", "TLA.1445") \
        == TLA_MILITARY_NOTE
    assert confession_note("EELK Kambja kogudus", "EAA.1255") is None


def test_russian_metrical_book_title_is_a_metrical_book():
    title = ("Метрическая книга о родившихся, браком сочетавшихся и умерших 91 пехотного "
             "Двинского полка.")
    assert unit_kind(Unit("TLA.1445.1.1", title, 1867, 1867, "1867", None)) == KIND_METRICAL


def test_jewish_community_is_called_a_community(index):
    fond = parse_fond(FOND.encode())
    fond.title, fond.code = "Tartu Juudiusu kogudus", "EAA.5413"
    head = Head("RA_EAA5413.xml", "EAA.5413", "Tartu Juudiusu kogudus", None, None)
    assert parish_place(fond.title) == "Tartu"
    rec = fond_record(head, "иудейский", fond, index.match(fond.title))
    assert rec.category == "иудейская община" and rec.extra["match"] == "город"
    assert rec.title == "Метрические книги общины Tartu (Tartu Juudiusu kogudus)"
    assert rec.summary.startswith("Иудейская община Tartu:")


@pytest.mark.parametrize("title, place", [
    ("Eesti Apostliku Õigeusu Kiriku Tallinna Kaasani Kogudus", "Tallinna Kaasani"),
    ("Rooma-Katoliku Kiriku Tallinna Peeter-Pauli Kogudus", "Tallinna Peeter-Pauli"),
    ("Eesti Evangeelse Luterliku Kiriku Tallinna Pauluse Kogudus", "Tallinna Pauluse"),
    ("Vene Vanausuliste Tallinna Kogudus", "Tallinna"),
])
def test_church_name_in_front_is_not_the_place(title, place):
    assert parish_place(title) == place


def test_petseri_lies_outside_estland_and_livland(index):
    match = index.match("EELK Petseri kogudus")
    assert match.kind == "город" and match.parish is None
    assert match.region == "Псковская губерния"
