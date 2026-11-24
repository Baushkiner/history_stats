"""Разбор слоя мест Восточной Пруссии из указателя Kartenmeister.

Сети в тестах нет. Образцы ниже повторяют разметку сайта: страница списка
`Results.asp` (число мест и строки «место — крейс») и карточка `City.asp`
— таблица, где подпись поля в ячейке серого цвета, значение — в голубой.
Проверяется то, на чём слой держится: число мест и номера карточек из
списка, поля карточки с переносами в подписи, координата до минуты, приход
«D» как заглушка, население по годам, справка без контактов кураторов,
датировка по годам карточки и рамка у карточки без годов.
"""

from histctx.registry import BY_SLUG
from histctx.sources.kartenmeister import (
    GERMAN_ERA, KARTENMEISTER, check_card, location, page_url, parish, parse_card,
    parse_results, population, records, remark_years, remarks, search_form,
)

RESULTS = """
<font face="Arial" size="3"><b>There are <u>16303</u>
            records that match your search criteria.</b></font>
        <tr bgcolor="#66CCFF">
          <td width="250"><b><font face=Arial size=2><a
             href="City.asp?CitNum=3528">Ackmonienen, Kirchspiel Enzuhnen
             </a></font></b>
          </td>
          <td width="200"><b><font face="Arial" size="2">Stallup\xf6nen</font></b>
          </td>
        </tr>
        <tr bgcolor="#C4ECFF">
          <td width="250"><b><font face=Arial size=2><a
             href="City.asp?CitNum=48901">Gumbinnen
             </a></font></b>
          </td>
          <td width="200"><b><font face="Arial" size="2">Gumbinnen</font></b>
          </td>
        </tr>
<a href='results.asp?pg=2&p=100&amp;s5=Kaliningrad'>Next 100</a>
"""


def _row(label: str, value: str) -> str:
    return (f'<tr><td width="150" bgcolor="#CCCCCC"><font face="Arial" size="2"><b>{label}'
            f'</b></font></td>\n<td width="300" bgcolor="#66CCFF"><font face="Arial"\n'
            f' size="2">{value}</font></td></tr>\n')


CARD = "".join([
    _row("German \n                Name", "Gumbinnen"),
    _row("Alternate \n                Name 1:", "Killigkehmen"),
    _row("Polish/Russian   \n                  Name", "Gusev"),
    _row("Kreis/County", "Gumbinnen"),
    _row("Residents of Jewish Faith", "106"),
    _row("German \n              Province", "Ostpreussen"),
    _row("Today's \n                Province", "Kaliningrad Oblast"),
    _row("Location", "East 22\xb012' North 54\xb035'"),
    _row("Lutheran \n              Parish", "Gumbinnen 1905"),
    _row("Catholic \n                 Parish", "Norutschatschen 1905"),
    _row("Standesamt/Civil \n                Registry", "Gumbinnen 1905"),
    _row("Population By Year/Einwohner", "\n1782: 4798<br>\n1905: 13914<br>\n1939: 24534<br>\n"),
    _row("Remarks", "Shows in 1785  266 Feuerstellen and is classified as: Immediat-Stadt. "
                    "Kreisbetreuer:  Herr Muster  muster@example.de"),
])

BARE = "".join([
    _row("German \n                Name", "Abbarten, Ziegelei"),
    _row("Polish/Russian   \n                  Name", "More Research Needed"),
    _row("Kreis/County", "Bartenstein"),
    _row("Location", "East 0\xb000' North 0\xb000'"),
    _row("Lutheran \n              Parish", "D"),
])


def test_layer_is_registered_with_rights_in_words():
    assert BY_SLUG["kartenmeister"] is KARTENMEISTER
    assert KARTENMEISTER.status == "harvested"
    assert "согласия владельца" in KARTENMEISTER.license


def test_results_page_gives_total_and_card_numbers():
    total, rows = parse_results(RESULTS)
    assert total == 16303
    assert [(r.cit_num, r.name, r.kreis) for r in rows] == [
        (3528, "Ackmonienen, Kirchspiel Enzuhnen", "Stallupönen"),
        (48901, "Gumbinnen", "Gumbinnen")]


def test_search_goes_by_todays_province():
    assert search_form("Kaliningrad")["provincepo"] == "Kaliningrad"
    assert page_url("Klaip", 3).endswith("results.asp?pg=3&p=100&s5=Klaip")


def test_card_fields_with_broken_labels():
    card = parse_card(CARD)
    check_card(card, 48901)
    assert card["German Name"] == "Gumbinnen"
    assert card["Today's Province"] == "Kaliningrad Oblast"
    assert card["Alternate Name 1:"] == "Killigkehmen"
    assert population(card["Population By Year/Einwohner"]) == {1782: 4798, 1905: 13914,
                                                               1939: 24534}


def test_location_to_the_minute_and_zero_is_no_point():
    assert location("East 22°12' North 54°35'") == (54.5833, 22.2)
    assert location("East 0°00' North 0°00'") == (None, None)
    assert location(None) == (None, None)


def test_parish_placeholder_and_year():
    assert parish("Gumbinnen 1905") == "Gumbinnen"
    assert parish("D") is None


def test_remarks_lose_curator_contacts():
    text = remarks("Shows in 1785  266 Feuerstellen. Kreisbetreuer: Herr X x@y.de")
    assert "Kreisbetreuer" not in text and "@" not in text
    assert remark_years("Shows in 1785 7 Feuerstellen. In 1818 293 Feuerstellen") == {1785, 1818}


def test_record_from_full_card():
    rec = records([(48901, parse_card(CARD))])[0]
    assert rec.title == "Gumbinnen — Gusev"
    assert (rec.lat, rec.lon) == (54.5833, 22.2)
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1782, 1939, "year")
    assert rec.district == "Gumbinnen"
    assert rec.extra["parish_lutheran_1905"] == "Gumbinnen"
    assert rec.extra["parish_catholic_1905"] == "Norutschatschen"
    assert rec.extra["population"]["1905"] == 13914
    assert "лютеранский приход Gumbinnen" in rec.summary
    assert rec.url.endswith("City.asp?CitNum=48901")
    assert "muster" not in rec.extra["remarks"]


def test_card_without_years_gets_the_gazetteer_frame():
    rec = records([(59842, parse_card(BARE))])[0]
    assert rec.title == "Abbarten, Ziegelei"
    assert not rec.has_point and rec.confidence == "no_coords"
    assert (rec.year_from, rec.year_to) == GERMAN_ERA
    assert rec.date_precision == "era" and rec.date_approx
    assert rec.extra["date_source"] == "рамка указателя"
    assert "parish_lutheran_1905" not in rec.extra


class _Names:
    def lookup(self, name, lat, lon):
        return "Гусев" if name == "Gusev" else None


def test_russian_label_from_name_index():
    rec = records([(48901, parse_card(CARD))], names=_Names())[0]
    assert rec.title == "Gumbinnen — Гусев"
