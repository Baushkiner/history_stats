"""Разбор Germans from Russia Settlement Locations: немецкие колонии и поселения.

Сети в тестах нет. Вкладки листа «GRSL-All Colonies» и сводный лист
«Complete» приходят таблицами CSV — образцы собраны здесь же, с теми же
многострочными заголовками и теми же написаниями, что у листов 22.11.2026.

Проверяется то, на чём слой держится: список вкладок со страницы листа,
год основания во всех встретившихся написаниях, кириллица в скобках —
чья она, немецкого имени или нынешнего, — тип колонии и конфессия,
сведение вкладок с «Complete» без дублей, открытый срок и пометки записей.
"""

import csv
import io

import pytest

from histctx.registry import BY_SLUG, HARVESTED
from histctx.sources import german_colonies as gc
from histctx.sources.german_colonies import (
    GERMAN_COLONIES, GermanColoniesError, assign_cyrillic, current_name, kind_of, merge,
    parse_tabs, parse_year, read_complete, read_tab, records, religions, row_to_record,
    split_names, year_label,
)

HEAD = [
    "Colony Group", "Ancestral Name(s)", "Other Names \nand Spellings",
    "District, Parish and/or City of Authority", "Area, Governorate, Oblast",
    "Country at time of Founding (assumed*)", "Latitude", "Longitude", "Current Name(s)",
    "Current Country", "Year Founded", "Mother / Daughter / Chutor Colony",
    "Religions (primary*)", "Plat Map", "Cemetery", "Notes", "Sources . . . . . .",
    "GOV-ID", "Wikidata", "GeoNames ID\nPermanent Link", "Last Update",
    "@id Historic Place\nGRSL", "Historic.Place\nGRSL, DEU",
]


def link(lat, lon, key):
    return (f"https://www.historic.place/themes/GRSL/index.html?zoom=13&lat={lat}&lon={lon}"
            f"&pid=KdSa&select=n{key}&pins={lon}!{lat}")


def tab_csv(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(HEAD)
    for row in rows:
        values = dict.fromkeys(HEAD, "")
        values.update(row)
        writer.writerow([values[h] for h in HEAD])
    writer.writerow([""] * len(HEAD))           # пустая строка в конце листа
    return buf.getvalue()


SCHILLING = {
    "Colony Group": "Volga Colonies", "Ancestral Name(s)": "Schilling",
    "Other Names \nand Spellings": "Sosnovka, [Шиллинг]",
    "District, Parish and/or City of Authority": "Balzer, Talovka (P)",
    "Area, Governorate, Oblast": "Volga, Saratov Governorate",
    "Country at time of Founding (assumed*)": "Russia", "Latitude": "51.1879",
    "Longitude": "45.7845", "Current Name(s)": "Sosnovka, Saratov, Russia",
    "Current Country": "Russia", "Year Founded": "1764",
    "Mother / Daughter / Chutor Colony": "Mother", "Religions (primary*)": "Protestant",
    "@id Historic Place\nGRSL": "457845511879",
    "Historic.Place\nGRSL, DEU": link("51.1879", "45.7845", "457845511879"),
}
ROSENHEIM = {
    "Colony Group": "Beresan Colonies", "Ancestral Name(s)": "Rosenheim",
    "Other Names \nand Spellings": "Kolobatino, [Колобатино/Росенхеим]",
    "Area, Governorate, Oblast": "Odessa, Kherson Governorate", "Latitude": "46.8476",
    "Longitude": "31.5060", "Current Name(s)": "Kalabatyne, Mykolaiv, Ukraine",
    "Year Founded": "1896", "Mother / Daughter / Chutor Colony": "Daughter",
    "Religions (primary*)": "Catholic*, Mennonite",
    "Wikidata": "https://www.wikidata.org/wiki/Q4191370",
    "@id Historic Place\nGRSL": "315060468476",
}
ABBARTEN = {
    "Colony Group": "East Prussia - Königsberg", "Ancestral Name(s)": "Abbarten",
    "Other Names \nand Spellings": "Prudy, [Аббартен / Пруды]",
    "Area, Governorate, Oblast": "Königsberg Governorate", "Latitude": "54.4265",
    "Longitude": "20.9330", "Current Name(s)": "Prudy, Kaliningrad, Russia",
    "Year Founded": "unknown", "@id Historic Place\nGRSL": "209330544265",
}
ABAKLI = {
    "Colony Group": "Crimean Colonies", "Ancestral Name(s)": "Abakli Tama",
    "Other Names \nand Spellings": "Abakli, Abakly",
    "Area, Governorate, Oblast": "Crimean Peninsula, Taurida Governorate",
    "Latitude": "45.7825", "Longitude": "34.1200",
    "Current Name(s)": "Defunct. Village no longer exists. Formerly known as Abakly.",
    "Year Founded": "1884", "Mother / Daughter / Chutor Colony": "Daughter",
    "@id Historic Place\nGRSL": "341200457825",
}


def parsed(row, tab="Volga"):
    return read_tab(tab_csv([row]), tab)[0]


# --- список вкладок ------------------------------------------------------------

def test_tabs_are_read_from_the_htmlview_page():
    html = ('items.push({name: "Astrakhan", pageUrl: "https:\\/\\/docs.google.com\\/x", '
            'gid: "1422585376",initialSheet: ("1422585376" == gid)});'
            'items.push({name: "Crimea (Krim)", pageUrl: "https:\\/\\/y", gid: "870481885",'
            'initialSheet: false});')
    assert parse_tabs(html) == [("Astrakhan", "1422585376"), ("Crimea (Krim)", "870481885")]
    with pytest.raises(GermanColoniesError):
        parse_tabs("<html>Sign in</html>")


def test_sheets_are_cached_and_resumed(tmp_path, monkeypatch):
    calls = []
    html = 'items.push({name: "Volga", pageUrl: "u", gid: "17",initialSheet: true});'

    def fake(url, **_):
        calls.append(url)
        if url.endswith("/htmlview"):
            return html
        if "sheet=Complete" in url:
            return "t\nh\n"
        return tab_csv([SCHILLING])

    monkeypatch.setattr(gc, "fetch_text", fake)
    tabs, complete = gc.cached_sheets(tmp_path, pause=0)
    assert [t[:2] for t in tabs] == [("Volga", "17")] and complete == "t\nh\n"
    assert len(calls) == 3
    gc.cached_sheets(tmp_path, pause=0)           # второй раз — из кэша
    assert len(calls) == 3
    (tmp_path / "tabs" / "17.csv").write_text("")  # оборванная вкладка докачивается
    gc.cached_sheets(tmp_path, pause=0)
    assert len(calls) == 4


# --- поля --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, year, kind, approx, settlers", [
    ("1764", 1764, "year", False, False),
    ("1748/49", 1748, "year", True, False),
    ("1790-1835", 1790, "year", True, False),
    ("1784-86", 1784, "year", True, False),
    ("1749 (see notes)", 1749, "year", False, True),
    ("1749  (see notes)", 1749, "year", False, True),
    ("after 1865", 1865, "year", True, False),
    ("before 1864", 1864, "year", True, False),
    ("1820s", 1820, "decade", True, False),
    ("1880's (see notes)", 1880, "decade", True, True),
    ("9th century", 801, "century", True, False),
    ("unknown", None, None, False, False),
    ("Unknown", None, None, False, False),
    ("", None, None, False, False),
])
def test_year_founded_in_every_spelling(raw, year, kind, approx, settlers):
    info = parse_year(raw)
    assert (info["year"], info["kind"], info["approx"], info["settlers"]) == \
        (year, kind, approx, settlers)


@pytest.mark.parametrize("raw, label", [
    ("1764", "1764"), ("1790-1835", "1790–1835"), ("1784-86", "1784–1786"),
    ("1748/9", "1748–1749"), ("after 1865", "после 1865"), ("before 1864", "до 1864"),
    ("1820s", "1820-е"), ("9th century", "IX век"), ("1749 (see notes)", "1749"),
    ("unknown", None),
])
def test_year_label(raw, label):
    assert year_label(raw) == label


def test_names_split_into_latin_variants_and_cyrillic():
    assert split_names("Prudy, [Аббартен / Пруды]") == (["Prudy"], ["Аббартен", "Пруды"])
    assert split_names("Abakli, Abakly") == (["Abakli", "Abakly"], [])
    variants, cyr = split_names("Birkenfeldt, [Биркенхоф / Kustarnikowo / Кустарниково]")
    assert variants == ["Birkenfeldt", "Kustarnikowo"] and cyr == ["Биркенхоф", "Кустарниково"]


def test_cyrillic_is_assigned_to_the_name_it_spells():
    assert assign_cyrillic(["Шиллинг"], "Schilling", "Sosnovka") == ("Шиллинг", None)
    assert assign_cyrillic(["Кошкарево"], "Schilling", "Koshkarevo") == (None, "Кошкарево")
    assert assign_cyrillic(["Колобатино", "Росенхеим"], "Rosenheim", "Kalabatyne") == \
        ("Росенхеим", "Колобатино")
    assert assign_cyrillic([], "Halbstadt", None) == (None, None)


def test_current_name_and_defunct_places():
    assert current_name("Sosnovka, Saratov, Russia") == \
        ("Sosnovka", "Sosnovka, Saratov, Russia", False)
    assert current_name("Koshkarevo, Omskaya, Russia (see notes)")[0] == "Koshkarevo"
    name, full, defunct = current_name("Defunct. Village no longer exists. Formerly known as X.")
    assert name is None and defunct and full.startswith("Defunct")
    assert current_name("") == (None, None, False)


def test_kind_of_place():
    assert kind_of({"Mother / Daughter / Chutor Colony": "Mother"}) == "Материнская колония"
    assert kind_of({"Mother / Daughter / Chutor Colony": "Daughter, Chutor"}) == "Хутор"
    assert kind_of({"Mother / Daughter / Chutor Colony": "Chutor, (#1, 2, 3, & 4)"}) == "Хутор"
    assert kind_of({"_tab": "East_Prussia-Gumbinnen"}) == "Поселение"
    assert kind_of({"_tab": "Banat"}) == "Колония"


def test_religions_mark_the_primary_one():
    assert religions("Catholic*, Mennonite") == ["католики (основная)", "меннониты"]
    assert religions("Protestamt") == ["протестанты"]
    assert religions("Chutor") == []


# --- листы -------------------------------------------------------------------------

def test_tab_headers_are_matched_after_collapsing_whitespace():
    rows = read_tab(tab_csv([SCHILLING, ROSENHEIM]), "Volga")
    assert len(rows) == 2                         # пустая строка пропущена
    assert rows[0]["Other Names and Spellings"] == "Sosnovka, [Шиллинг]"
    assert rows[0]["_tab"] == "Volga"


def test_tab_without_a_needed_column_is_an_error():
    text = tab_csv([SCHILLING]).replace("Year Founded", "Year")
    with pytest.raises(GermanColoniesError, match="Year Founded"):
        read_tab(text, "Volga")


COMPLETE = (
    '"Germans from Russia and Eastern Europe Settlement Locations","","","","","",""\n'
    '"Ancestral Name(s)","Other Names \nand Spellings","Current Name(s)",'
    '"Area, Governorate, Oblast","Year Founded","Historic.Place GRSL\nTorgau, DE-SN",""\n'
    '"Ancestral Name(s)","Other Names \nand Spellings","Current Name(s)",'
    '"Area, Governorate, Oblast","Year Founded","Historic.Place GRSL\nTorgau, DE-SN",""\n'
    f'"Schilling","Sosnovka, [Шиллинг]","Sosnovka, Saratov, Russia","Volga, Saratov Governorate",'
    f'"1765","{link("51.1879", "45.7845", "457845511879")}",""\n'
    f'"Elbing","Elbląg, [Эльблонг]","Elbląg, Warmia-Mazury, Poland","Danzig Governorate",'
    f'"1466 (see notes)","{link("54.1561", "19.4045", "194045541561")}",""\n'
)


def test_complete_sheet_is_read_with_its_two_header_rows():
    rows = read_complete(COMPLETE)
    assert [r["Ancestral Name(s)"] for r in rows] == ["Schilling", "Elbing"]
    assert rows[1]["Latitude"] == "54.1561" and rows[1]["Longitude"] == "19.4045"
    assert rows[1]["@id Historic Place GRSL"] == "194045541561"
    with pytest.raises(GermanColoniesError):
        read_complete('"x"\n"a","b","c","d","e","f"\n"1","2","3","4","5","6"\n')


def test_tabs_are_the_base_and_complete_adds_only_the_missing():
    tab_rows = read_tab(tab_csv([SCHILLING, ROSENHEIM]), "Volga")
    rows, counts = merge(tab_rows, read_complete(COMPLETE))
    assert counts["в обоих листах"] == 1 and counts["только в «Complete»"] == 1
    assert counts["только во вкладках"] == 1 and counts["год расходится"] == 1
    recs = {r.source_id: r for r in records(rows)}
    assert recs["457845511879"].extra["complete_year"] == "1765"
    elbing = recs["194045541561"]
    assert elbing.extra["sheet"] == "complete" and elbing.extra["group"] == "Данцигская губерния"
    assert elbing.title == "Колония Эльблонг (Elbląg), с 1466"


# --- записи --------------------------------------------------------------------------

def test_colony_with_a_year_gets_an_open_term():
    rec = row_to_record(parsed(SCHILLING))
    assert rec.title == "Материнская колония Шиллинг (Sosnovka), осн. 1764"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1764, 1960, "open")
    assert rec.period_raw == "с 1764" and not rec.date_approx
    assert rec.confidence == "ok" and rec.has_point
    assert rec.category == "Материнская колония"
    assert rec.extra["name_de"] == "Schilling" and rec.extra["name_ru"] == "Шиллинг"
    assert rec.extra["authority"] == "Balzer, Talovka (P)"
    assert "конфессия — протестанты" in rec.summary
    assert "сейчас — Sosnovka, Saratov, Russia" in rec.summary
    assert rec.url.startswith("https://www.historic.place/")
    assert rec.layer == GERMAN_COLONIES.slug and "CC BY-SA 4.0" in rec.license


def test_both_cyrillic_spellings_land_in_the_title():
    rec = row_to_record(parsed(ROSENHEIM, "Beresan"))
    assert rec.title == "Дочерняя колония Росенхеим (Колобатино), осн. 1896"
    assert rec.extra["current_name_ru"] == "Колобатино"
    assert rec.extra["wikidata"] == "Q4191370"
    assert rec.extra["group"] == "Березань"


def test_place_without_a_year_stays_as_an_index_entry():
    rec = row_to_record(parsed(ABBARTEN, "East_Prussia-Königsberg"))
    assert rec.title == "Поселение Аббартен (Пруды)"
    assert rec.year_from is None and rec.date_precision == "unknown"
    assert rec.confidence == "no_date" and rec.period_raw == "unknown"


def test_defunct_colony_is_marked_not_dropped():
    rec = row_to_record(parsed(ABAKLI, "Crimea (Krim)"))
    assert rec.title == "Дочерняя колония Abakli Tama (не существует), осн. 1884"
    assert rec.extra["defunct"] is True and "сейчас места нет" in rec.summary


def test_settlers_year_is_not_called_a_founding():
    row = dict(SCHILLING, **{"Year Founded": "1749 (see notes)"})
    rec = row_to_record(parsed(row))
    assert rec.title.endswith(", с 1749")
    assert rec.extra["year_is_settlers"] is True
    assert "первые немецкие колонисты — 1749" in rec.summary


def test_colony_keeping_its_name_gets_no_brackets():
    row = dict(SCHILLING, **{"Ancestral Name(s)": "Halbstadt",
                             "Other Names \nand Spellings": "[Гальбштадт]",
                             "Current Name(s)": "Halbstadt, Altai Kri, Russia"})
    assert row_to_record(parsed(row)).title == "Материнская колония Гальбштадт, осн. 1764"


def test_marks_without_point_and_after_the_horizon():
    no_point = row_to_record(parsed(dict(SCHILLING, Latitude="", Longitude="")))
    assert no_point.confidence == "no_coords" and not no_point.has_point
    late = row_to_record(parsed(dict(SCHILLING, **{"Year Founded": "1975"})))
    assert late.confidence == "after_1960" and late.year_to == 1975


def test_layer_is_described_in_registry():
    spec = BY_SLUG["german_colonies"]
    assert spec is GERMAN_COLONIES and spec in HARVESTED
    assert spec.status == "harvested" and spec.expected_rows == 19452
    assert "CC BY-SA 4.0" in spec.license
