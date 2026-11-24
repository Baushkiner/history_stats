"""Разбор слоя исторических синагог Европы (historicsynagogueseurope.org).

Сети в тестах нет. Страница карты несёт все точки строкой `predata`: записи
через `||||`, поля через `;;` — образец ниже взят из живой страницы (две
записи). Карточка здания — пары «подпись — значение» в разметке Index of
Jewish Art; часть полей спрятана в HTML-комментарий. Проверяется разбор
точек, полей карточки, года постройки во всех встретившихся написаниях,
открытый срок до горизонта и граница по полю «Period» без года постройки.
"""

import pytest

from histctx.registry import BY_SLUG
from histctx.sources.historic_synagogues import (
    HISTORIC_SYNAGOGUES, HORIZON, SynagoguesError, building_dating, dating, parse_card,
    parse_map, records,
)

MAP = ("<script>; var predata = '54.425011;;25.933603;;cemerety_chapel_blue;;104;;Great "
       "Synagogue in Oshmiany, Belarus;;8832;;;;,2,;;1;; Brick ;; Storage ;; C (Poor) ;; "
       "4 (International)||||59.924679;;30.291748;;normal;;24;;Choral Synagogue in St. "
       "Petersburg, Russia;;14448;;,31,;;,277,;;0;; Brick ;;Synagogue ;; B (Fair) ;; "
       "4 (International)||||';\nfunction initMap() {}</script>")


def _line(field: str, label: str, value: str, hidden: bool = False) -> str:
    block = (f'<div id="line_mhs" >\n <div class="hb6-mhs browser-line-title" '
             f'id="{field}_104">{label}</div>\n <div class=" zgcollector cell-mhs"  '
             f'id="{field}_104">{value}</div><hr>\n</div>\n')
    return f"<!--{block}" if hidden else block


CARD = "".join([
    _line("ntl", "Name/Title", 'Great Synagogue in Oshmiany <span class="zgscollector">'
                               '| Unknown</span>'),
    _line("date", "Building Date", "1902"),
    _line("date", "Synagogue active dates", ""),
    _line("maker_name", "Architect/ Maker ", 'Unknown <span class="zgscollector">(Unknown)'
                                             '</span>'),
    _line("community", " Community ", "<a href='?mode=treefriend&id=2'>Ashkenazi</a> <br /> "
                                      '<span class="zgscollector">| </span>'),
    _line("location", "Location", "<a href='?x'>Belarus</a> | <a href='?y'>Hrodzienskaia "
                                  "vobl.</a> | <a href='?z'>Ashmiany / Oshmiany</a> <br />"),
    _line("period", "Period", "<a href='?p'>Russian Empire</a><a href='?p'>Russian Empire</a>",
          hidden=True),
])


def test_layer_is_registered_with_rights_in_words():
    assert BY_SLUG["historic_synagogues"] is HISTORIC_SYNAGOGUES
    assert "согласия владельца" in HISTORIC_SYNAGOGUES.license


def test_map_points():
    points = parse_map(MAP)
    assert [p.id for p in points] == [104, 24]
    p = points[0]
    assert (p.lat, p.lon) == (54.425011, 25.933603)
    assert p.name == "Great Synagogue in Oshmiany, Belarus"
    assert p.at_risk and not points[1].at_risk
    assert (p.material, p.usage, p.condition, p.significance) == (
        "Brick", "Storage", "C (Poor)", "4 (International)")


def test_map_without_predata_is_an_error():
    with pytest.raises(SynagoguesError):
        parse_map("<html>карта переехала</html>")


def test_card_fields_including_hidden_ones():
    card = parse_card(CARD)
    assert card["Name/Title"] == "Great Synagogue in Oshmiany"
    assert card["Building Date"] == "1902"
    assert "Synagogue active dates" not in card
    assert "Architect/ Maker" not in card
    assert card["Community"] == "Ashkenazi"
    assert card["Location"] == "Belarus | Hrodzienskaia vobl. | Ashmiany / Oshmiany"
    assert card["Period"] == "Russian Empire"


@pytest.mark.parametrize("raw, expected", [
    ("1902", (1902, 1902, "year", False)),
    ("1765-1767", (1765, 1767, "year", False)),
    ("1890s", (1890, 1899, "decade", False)),
    ("ca. 1850", (1850, 1850, "year", True)),
    ("18??", (1800, 1899, "century", True)),
    ("19th century", (1801, 1900, "century", False)),
    ("End of the 18th century", (1767, 1800, "part", True)),
    ("Unknown", None),
    (None, None),
])
def test_building_date(raw, expected):
    assert building_dating(raw) == expected


def test_open_end_to_the_horizon_and_period_fallback():
    d = dating({"Building Date": "1902"})
    assert (d.year_from, d.year_to, d.precision) == (1902, HORIZON, "open")
    d = dating({"Building Date": "1998-2000"})
    assert (d.year_from, d.year_to, d.precision) == (1998, 2000, "year")
    d = dating({"Period": "Russian Empire"})
    assert (d.year_from, d.year_to, d.precision, d.approx) == (1772, 1917, "era", True)
    assert dating({}).precision == "unknown"


def test_record():
    point = parse_map(MAP)[0]
    rec = records([(point, parse_card(CARD))])[0]
    assert rec.title == "Great Synagogue in Oshmiany"
    assert rec.category == "синагога; ныне склад"
    assert (rec.year_from, rec.year_to) == (1902, HORIZON)
    assert "материал: кирпич" in rec.summary and "под угрозой" in rec.summary
    assert "состояние: C — плохое" in rec.summary
    assert rec.url.endswith("browser.php?mode=set&id=104")
    assert rec.actor is None
    assert rec.confidence == "ok"


def test_record_without_card_keeps_the_point():
    point = parse_map(MAP)[1]
    rec = records([(point, None)])[0]
    assert rec.title == "Choral Synagogue in St. Petersburg, Russia"
    assert rec.date_precision == "unknown"
    assert rec.extra["card"] == "нет в кэше"
