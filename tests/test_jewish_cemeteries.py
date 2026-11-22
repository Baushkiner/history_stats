"""Разбор карточек обследования ESJF: еврейские кладбища.

Сети в тестах нет. Карточка собирается здесь же, с той разметкой, что у сайта
на 22.11.2026: `srv-info-item` → подпись в `text-block-7` и значение в
`srv-right`, заголовок в `h1.h1-inside`, ниже — исторический очерк.

Проверяется то, на чём слой держится: что из карт сайта берутся только
карточки и что закрытое `robots.txt` не запрашивается; что разбор читает
поля, а не очерк; годы надгробий по правилу открытого срока; число надгробий
и периметр из полей словами; русская подпись места только по совпадению
имени; что в записи нет пересказа очерка.
"""

import pytest

from histctx.registry import BY_SLUG, EXTERNAL, HARVESTED
from histctx.sources import jewish_cemeteries as jc
from histctx.sources.jewish_cemeteries import (
    JEWISH_CEMETERIES, OPEN_END_YEAR, OPEN_START_YEAR, EsjfError, RussianNames,
    card_slug, card_to_record, check_card, condition_ru, dating, gps_point,
    gravestone_count, parse_card, parse_sitemap, perimeter_metres, tombstone_year,
    url_allowed, yes_no,
)

OVERVIEW = ("The exact period of the cemetery’s establishment is unknown. However, it "
            "appears on Russian topographical maps of the 1880s.")


def item(label, value, cls="srv-right"):
    return (f'<div class="srv-info-item"><div class="srv-left">'
            f'<div class="text-block-7">{label}</div><div class="srv-inf-dots"></div></div>'
            f'<div class="{cls}">\n\t\t{value}\t\t</div></div>')


def card_html(**over):
    fields = {
        "Country": "Ukraine", "Region": "Rivne", "District": "Volodymyrets",
        "Settlement": "Stara Rafalivka",
        "Site address": "Starting at the intersection of T1808 and Vyshneva Street…",
        "GPS coordinates": "51.371301, 25.867334",
        "Perimeter length": "232 metres",
        "Is the cemetery demolished": "no",
        "Type and height of existing fence": "No fence",
        "Preservation condition": "Fenced and protected Jewish cemetery",
        "General site condition": "Most of the gravestones were damaged by locals.",
        "Number of existing gravestones": "40. According to locals, excavators dug up graves.",
        "Date of oldest tombstone": "1921",
        "Date of newest tombstone": "1939",
        "Urgency of erecting a fence": "High",
        "Land ownership": "Property of local community",
        "Preserved construction on site": "",
        "Drone surveys": "No",
    }
    fields.update(over)
    rows = "".join(
        item(k, v, "srv-right srv-info-item-gps-text-block" if k == "GPS coordinates"
             else "srv-right")
        for k, v in fields.items() if v is not None)
    return (
        "<html><head><title>Stara Rafalivka New Jewish Cemetery &#8211; ESJF Surveys</title>"
        '</head><body><h1 data-w-id="x" style="opacity:0" class="h1-inside">'
        "Stara Rafalivka New Jewish Cemetery</h1>"
        f"{rows}"
        '<h2 class="h2 srv">Historical overview</h2>'
        f'<div class="text-survs w-richtext"><p>{OVERVIEW}</p></div></body></html>'
    )


URL = "https://www.esjf-cemeteries.org/survey/stara-rafalivka-new-jewish-cemetery/"

NAMES = {
    "1": {"title": "Старая Рафаловка", "lat": 51.37, "lon": 25.87,
          "names": ["Stara Rafalivka", "Staraya Rafalovka", "Rafałówka"]},
    "2": {"title": "Вараш", "lat": 51.35, "lon": 25.85, "names": ["Varash", "Kuznetsovsk"]},
}


def test_partial_layer_says_so_in_its_card():
    # Сайт отвечает сборщику страницей защиты: слой собран из того, что успело
    # лечь в кэш, и карточка слоя говорит об этом словами (замер 22.11.2026).
    assert BY_SLUG["jewish_cemeteries"] is JEWISH_CEMETERIES
    assert JEWISH_CEMETERIES in HARVESTED and JEWISH_CEMETERIES not in EXTERNAL
    assert JEWISH_CEMETERIES.status == "harvested"
    assert JEWISH_CEMETERIES.expected_rows < jc.EXPECTED_CARDS
    assert "неполным" in JEWISH_CEMETERIES.description
    assert JEWISH_CEMETERIES.group == "faith"
    assert "права не выяснены" in JEWISH_CEMETERIES.license
    assert "договорённост" in JEWISH_CEMETERIES.license


def test_sitemap_gives_only_survey_cards():
    xml = (
        '<?xml version="1.0"?><urlset>'
        f"<url><loc>{URL}</loc><lastmod>2024-03-29T13:23:59+00:00</lastmod></url>"
        "<url><loc>https://www.esjf-cemeteries.org/about/</loc></url>"
        "<url><loc>https://www.esjf-cemeteries.org/survey/fastiv-jewish-cemetery/</loc></url>"
        "</urlset>")
    got = parse_sitemap(xml)
    assert got == [(URL, "2024-03-29T13:23:59+00:00"),
                   ("https://www.esjf-cemeteries.org/survey/fastiv-jewish-cemetery/", None)]


def test_card_slug_refuses_anything_but_a_card():
    assert card_slug(URL) == "stara-rafalivka-new-jewish-cemetery"
    for bad in ("https://www.esjf-cemeteries.org/survey/",
                "https://www.esjf-cemeteries.org/survey/a/b/",
                "https://www.esjf-cemeteries.org/survey/x/?p=1"):
        with pytest.raises(EsjfError):
            card_slug(bad)


def test_closed_paths_are_never_requested():
    # robots.txt сайта: Disallow: /wp-json/ и /*? — разборщик шаблонов не понимает.
    assert not url_allowed("https://www.esjf-cemeteries.org/wp-json/wp/v2/survey/4797")
    assert not url_allowed(URL + "?lang=uk")
    assert url_allowed(URL)


def test_card_fields_are_read_and_overview_is_not():
    card = parse_card(card_html())
    check_card(card, "x")
    assert card["title"] == "Stara Rafalivka New Jewish Cemetery"
    assert card["country"] == "Ukraine" and card["settlement"] == "Stara Rafalivka"
    assert card["gps"] == "51.371301, 25.867334"
    assert card["oldest"] == "1921" and card["newest"] == "1939"
    # Пустое поле («Preserved construction on site») — отсутствующее.
    assert "Preserved construction on site" in card["labels"]
    assert not any(OVERVIEW[:30] in str(v) for v in card.values())


def test_card_without_required_labels_stops_the_build():
    card = parse_card(card_html(**{"GPS coordinates": None}))
    with pytest.raises(EsjfError, match="GPS coordinates"):
        check_card(card, "stara")


def test_gps_point():
    assert gps_point("51.371301, 25.867334") == (51.371301, 25.867334)
    assert gps_point("50,08836; 29,92844") == (50.08836, 29.92844)
    assert gps_point("N/A") == (None, None)
    assert gps_point(None) == (None, None)


@pytest.mark.parametrize("text,year", [
    ("1906", 1906),
    ("At least 1856/5616. Requires additional research.", 1856),
    ("Requires additional research", None),
    ("N/A", None),
    ("", None),
    ("19th century", None),
    ("5650", None),
])
def test_tombstone_year(text, year):
    assert tombstone_year(text) == year


@pytest.mark.parametrize("text,count", [
    ("Around 500", 500),
    ("40. According to locals, excavators dug up multiple graves.", 40),
    ("About 1,500 gravestones", 1500),
    ("No tombstones preserved.", 0),
    ("None", 0),
    ("Several", None),
    (None, None),
])
def test_gravestone_count(text, count):
    assert gravestone_count(text) == count


def test_perimeter_and_yes_no():
    assert perimeter_metres("540 metres") == 540
    assert perimeter_metres("261 мetres") == 261
    assert perimeter_metres(None) is None
    assert yes_no("yes") is True and yes_no("no") is False and yes_no("") is None


def test_dating_follows_the_open_term_rule():
    both = dating("1921", "1939")
    assert (both.year_from, both.year_to, both.precision, both.approx) == (1921, 1939,
                                                                           "year", False)
    swapped = dating("1939", "1921")
    assert (swapped.year_from, swapped.year_to) == (1921, 1939)
    oldest = dating("1906", "N/A")
    assert (oldest.year_from, oldest.year_to, oldest.precision) == (1906, OPEN_END_YEAR, "open")
    assert oldest.approx
    newest = dating("Requires additional research", "At least 1856/5616.")
    assert (newest.year_from, newest.year_to, newest.precision) == (OPEN_START_YEAR, 1856,
                                                                    "open")
    late = dating("2001", None)
    assert (late.year_from, late.year_to) == (2001, 2001)
    none = dating(None, "N/A")
    assert none.year_from is None and none.precision == "unknown"
    assert "новейшее надгробие: N/A" in none.raw


def test_condition_dictionary_and_unknown_value():
    assert condition_ru("Demolished and overbuilt Jewish cemetery") == "снесено и застроено"
    assert condition_ru("Something new") == "Something new"
    assert condition_ru(None) is None


def test_russian_name_only_when_the_name_matches():
    names = RussianNames(NAMES)
    assert names.lookup("Stara Rafalivka", 51.3713, 25.8673) == "Старая Рафаловка"
    # Рядом есть Вараш, но имя другое — чужим именем село не подписывается.
    assert names.lookup("Mala Rafalivka", 51.36, 25.86) is None
    # Имя совпало, но место далеко — тоже нет.
    assert names.lookup("Stara Rafalivka", 50.0, 30.0) is None


def test_record_takes_facts_and_link_only():
    rec = card_to_record(URL, parse_card(card_html()), lastmod="2024-03-29",
                         names=RussianNames(NAMES))
    assert rec.layer == "jewish_cemeteries"
    assert rec.title == "Еврейское кладбище — Старая Рафаловка"
    assert (rec.lat, rec.lon) == (51.371301, 25.867334)
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1921, 1939, "year")
    assert rec.category == "огорожено и охраняется"
    assert rec.url == URL and rec.source_id == "stara-rafalivka-new-jewish-cemetery"
    assert rec.extra["gravestones"] == 40 and rec.extra["perimeter_m"] == 232
    assert rec.extra["demolished"] is False and rec.extra["country"] == "Ukraine"
    assert rec.extra["settlement_en"] == "Stara Rafalivka"
    assert "Украина" in rec.summary and "1921–1939" in rec.summary
    # Ни очерка, ни описания состояния словами, ни адреса.
    text = " ".join(str(v) for v in (rec.summary, rec.place_text, rec.extra))
    assert "topographical maps" not in text
    assert "excavators" not in text and "Vyshneva" not in text
    assert rec.license == JEWISH_CEMETERIES.license


def test_record_without_point_or_name_index():
    rec = card_to_record(URL, parse_card(card_html(**{"GPS coordinates": "unknown"})))
    assert rec.lat is None and rec.confidence == "no_coords"
    assert rec.title == "Еврейское кладбище — Stara Rafalivka"
    demolished = card_to_record(URL, parse_card(card_html(**{
        "Number of existing gravestones": "No tombstones preserved.",
        "Preservation condition": "Demolished Jewish cemetery that has not been built over",
        "Is the cemetery demolished": "yes",
        "Date of oldest tombstone": "N/A", "Date of newest tombstone": "N/A"})))
    assert demolished.extra["gravestones"] == 0 and demolished.extra["demolished"] is True
    assert "надгробий не сохранилось" in demolished.summary
    assert demolished.date_precision == "unknown"


def test_client_starts_from_the_measured_pause(tmp_path):
    client = jc.Client(cache_dir=tmp_path)
    assert client.pause == jc.PAUSE >= 6.0
    assert jc.COOLDOWN >= 60


def test_protection_stops_the_crawl_instead_of_waiting_for_hours(tmp_path):
    import email.message
    import urllib.error

    client = jc.Client(cache_dir=tmp_path, max_refusals_in_row=3)
    exc = urllib.error.HTTPError("u", 429, "Too Many Requests", email.message.Message(), None)
    assert client.refused("u", exc) == jc.COOLDOWN
    assert client.refused("u", exc) == jc.COOLDOWN
    assert client.pause > jc.PAUSE
    with pytest.raises(jc.ProtectionError, match="договорённость"):
        client.refused("u", exc)
    assert issubclass(jc.ProtectionError, EsjfError)
