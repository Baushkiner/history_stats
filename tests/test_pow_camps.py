"""Разбор слоя лагерей военнопленных с карты dekoder.

Сети в тестах нет. Страница карты — Next.js: данные лежат кусками
`self.__next_f.push([1, "…"])`, внутри — слои карты с `spreadsheetId`,
`layerProps` и `preloadedGeojson`. Образец ниже собран так же: два слоя
подряд, чтобы проверить, что точки берутся у своего слоя, а не у соседа.

Проверяется то, на чём слой держится: склейка кусков страницы, точки своего
слоя и номер листа-источника, адреса карточек из карты сайта, поля описания
(«Lager Nr.», «District», «Zeit»), разбор времени во всех встретившихся
написаниях, рамка войны у лагерей без времени, заголовок по-русски, точка
«$NaN» — запись без точки, а не потеря.
"""

import json

import pytest

from histctx.registry import BY_SLUG
from histctx.sources.pow_camps import (
    CARD_PREFIX, LAYER_ID, MAP_URL, POW_CAMPS, DekoderError, camp_number, card_urls,
    description_fields, layer_block, parse_time, payload_text, records, title_for, war_frame,
)

DESC_352 = ("![]()\n\n**Lager Nr.:** Stalag 352\n\n**District:** Reichskommissariat "
            "Ostland [Estland, Lettland, Litauen, Weißrußland, Rußland]\n\n**Zeit:** "
            "9.1941-7.1944\n\n**Quelle:** [Moosburg.org](https://moosburg.org/info/stalag/"
            "laglist.html)")

POW_FEATURES = [
    {"type": "Feature", "properties": {"id": 7, "name_de": "Minsk", "category": "Stalag",
                                       "description_de": DESC_352},
     "geometry": {"type": "Point", "coordinates": [27.5615, 53.9045]}},
    {"type": "Feature", "properties": {"id": 8, "name_de": "Bobruisk", "category": "Dulag",
                                       "description_de": "**Lager Nr.:** Dulag 131\n\n"
                                                         "**Zeit:** 1941"},
     "geometry": {"type": "Point", "coordinates": [29.2214, 53.1384]}},
    {"type": "Feature", "properties": {"id": 9, "name_de": "Gnaschwitz", "category": "Res-Laz",
                                       "description_de": None},
     "geometry": {"type": "Point", "coordinates": ["$NaN", "$NaN"]}},
]
MURDER_FEATURES = [
    {"type": "Feature", "properties": {"id": 0, "name_en": "Yama", "country": "Belorussia"},
     "geometry": {"type": "Point", "coordinates": [27.55, 53.90]}},
]


def _page(*, layers=None) -> str:
    """Страница карты: данные двумя кусками, слои в том порядке, как у dekoder."""
    layers = layers or [("murder-sites", "1mAj:murder_sites:A,B", MURDER_FEATURES),
                        (LAYER_ID, "1zzV:Sheet1:A,B,C,D,E,F", POW_FEATURES)]
    parts = []
    for layer_id, sheet, feats in layers:
        parts.append(
            '{"spreadsheetId":"%s","geojsonUrl":"","layerProps":{"id":"%s","source":"%s"},'
            '"isInteractive":true,"preloadedGeojson":%s,"scriptProps":"$undefined"}'
            % (sheet, layer_id, layer_id,
               json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False)))
    text = "5:[" + ",".join(parts) + "]"
    half = len(text) // 2
    return ("<html><body><script>self.__next_f.push([1,%s])</script>"
            "<script>self.__next_f.push([1,%s])</script></body></html>"
            % (json.dumps(text[:half], ensure_ascii=False),
               json.dumps(text[half:], ensure_ascii=False)))


SITEMAP = (
    b'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/'
    b'sitemap/0.9"><url><loc>https://war.dekoder.org/de/map/pow_camps/minsk-7</loc></url>'
    b'<url><loc>https://war.dekoder.org/de/map/pow_camps/bobruisk-8</loc></url>'
    b'<url><loc>https://war.dekoder.org/de/map/murder-sites/yama-1457</loc></url></urlset>'
)


class _Names:
    """Указатель написаний на одно место: Бобруйск."""

    def lookup(self, name, lat, lon):
        return "Бобруйск" if name == "Bobruisk" else None


def test_layer_is_registered_with_rights_in_words():
    assert BY_SLUG["pow_camps"] is POW_CAMPS
    assert POW_CAMPS.status == "harvested"
    assert "права не выяснены" in POW_CAMPS.license
    assert POW_CAMPS.group == "military"


def test_payload_is_glued_from_all_chunks():
    text = payload_text(_page())
    assert '"layerProps":{"id":"pow_camps"' in text
    with pytest.raises(DekoderError):
        payload_text("<html>без данных</html>")


def test_layer_block_takes_own_points_and_sheet():
    feats, sheet = layer_block(payload_text(_page()))
    assert [f["properties"]["id"] for f in feats] == [7, 8, 9]
    assert sheet == "1zzV:Sheet1:A,B,C,D,E,F"
    murder, _ = layer_block(payload_text(_page()), "murder-sites")
    assert [f["properties"]["id"] for f in murder] == [0]


def test_layer_block_complains_when_layer_is_gone():
    page = _page(layers=[("murder-sites", "x", MURDER_FEATURES)])
    with pytest.raises(DekoderError):
        layer_block(payload_text(page))


def test_card_urls_keep_only_pow_camps():
    urls = card_urls(SITEMAP)
    assert urls == {7: CARD_PREFIX + "minsk-7", 8: CARD_PREFIX + "bobruisk-8"}


def test_description_fields_strip_markdown_links():
    fields = description_fields(DESC_352)
    assert fields["Lager Nr."] == "Stalag 352"
    assert fields["Zeit"] == "9.1941-7.1944"
    assert fields["Quelle"] == "Moosburg.org"
    assert description_fields(None) == {}


@pytest.mark.parametrize("zeit,expected", [
    ("9.1939-4.1945", (1939, 1945, "month", False)),
    ("7.1940-10.1940", (1940, 1940, "month", False)),
    ("1941-9.1942", (1941, 1942, "year", False)),
    ("1942", (1942, 1942, "year", False)),
    ("5.1942", (1942, 1942, "month", False)),
    ("6.1942-", (1942, 1945, "open", False)),          # открытый конец — до 1945 года
    ("-1/3.1944", (1939, 1944, "open", True)),         # открытое начало, месяц неточен
    ("-12.1944-", (1944, 1944, "month", True)),        # известен в декабре 1944-го
    ("1.1943(-1944)", (1943, 1944, "year", True)),       # точность — грубейшая из двух
    ("9.1939-1945", (1939, 1945, "year", False)),
    ("1941-?", (1941, 1941, "year", True)),
])
def test_parse_time(zeit, expected):
    d = parse_time(zeit)
    assert (d.year_from, d.year_to, d.precision, d.approx) == expected
    assert d.raw == zeit


def test_parse_time_without_year_is_none_and_war_frame_marks_itself():
    assert parse_time("") is None
    assert parse_time("unbekannt") is None
    frame = war_frame()
    assert (frame.year_from, frame.year_to, frame.precision, frame.approx) == (
        1939, 1945, "era", True)
    assert frame.source == "рамка войны"


@pytest.mark.parametrize("lager_nr,number", [
    ("Stalag 352", "352"), ("Dulag 131", "131"), ("Frontstalag 150", "150"),
    ("Oflag XIII B", "XIII B"), ("Stalag I B", "I B"), (None, None),
])
def test_camp_number(lager_nr, number):
    assert camp_number(lager_nr) == number


def test_title_is_russian_type_number_and_place():
    assert title_for("Stalag", "352", "Минск") == "Шталаг 352 — Минск"
    assert title_for("Res-Laz", None, "Gnaschwitz") == "Резервный лазарет — Gnaschwitz"
    assert title_for("Неведомое", None, "X") == "Неведомое — X"


def test_records_carry_facts_link_and_dates():
    feats, sheet = layer_block(payload_text(_page()))
    recs = {r.extra["dekoder_id"]: r for r in records(feats, urls=card_urls(SITEMAP),
                                                       names=_Names(), sheet=sheet)}
    minsk = recs[7]
    assert minsk.title == "Шталаг 352 — Minsk"
    assert (minsk.year_from, minsk.year_to, minsk.date_precision) == (1941, 1944, "month")
    assert minsk.url == CARD_PREFIX + "minsk-7"
    assert minsk.confidence == "place_level"
    assert minsk.extra["lager_nr"] == "Stalag 352"
    assert minsk.extra["sheet"] == sheet
    assert "Reichskommissariat Ostland" in minsk.place_text
    assert minsk.summary.startswith("Шталаг — основной лагерь")
    assert recs[8].title == "Дулаг 131 — Бобруйск", "русское имя — из указателя написаний"


def test_camp_without_point_and_time_stays_with_war_frame():
    feats, _ = layer_block(payload_text(_page()))
    rec = {r.extra["dekoder_id"]: r for r in records(feats)}[9]
    assert not rec.has_point
    assert rec.confidence == "no_coords"
    assert (rec.year_from, rec.year_to, rec.date_precision, rec.date_approx) == (
        1939, 1945, "era", True)
    assert rec.extra["date_source"] == "рамка войны"
    assert rec.url == MAP_URL, "нет карточки — ссылка на саму карту"
    assert "время в перечне не указано" in rec.summary
