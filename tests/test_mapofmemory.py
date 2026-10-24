"""Слой мест захоронений из «Некрополя террора и ГУЛАГа» (en.mapofmemory.org).

Образцы — фрагменты настоящих страниц, снятых 24.10.2026: точки с главной
(`Drupal.settings.yandexViews.markers`) и поля карточек 42-18 и 62-11. Справки,
подписи к снимкам и имена в образцы не взяты — их не берёт и разбор.
"""

import pytest

from histctx.sources.mapofmemory import (
    BURIAL_SITES_TERROR, Marker, MapOfMemoryError, burial_period, card_to_record, check_card,
    check_cards, english_period, mark_neighbours, parse_card, parse_markers, split_marks,
)

_BALLOON = (
    '<a class=\\u0022grid_12 balloon_wrap\\u0022 href=\\u0022{code}\\u0022 target=\\u0022_blank'
    '\\u0022>\\n  <div class=\\u0022grid_3 balloon_img\\u0022><img src=\\u0022x.jpg\\u0022 '
    '/></div>\\n  <div class=\\u0022grid_9 balloon_context\\u0022>\\n    <div class=\\u0022'
    'balloon_name\\u0022>{name}</div>\\n    <div class=\\u0022balloon_adr\\u0022><p>{adr}</p>'
    '\\n</div>\\n  </div>\\n</a>'
)


def _marker_json(lat, lng, code, name, adr):
    balloon = _BALLOON.format(code=code, name=name, adr=adr)
    return (f'{{"lat":{lat},"lng":{lng},"icon":"","icolor":"","url":"{balloon}",'
            f'"title":"","description":"{balloon}"}}')


INDEX = (
    '<script>\n<!--//--><![CDATA[//><!--\njQuery.extend(Drupal.settings, {"basePath":"\\/",'
    '"yandexViews":{"markers":['
    + _marker_json(53.708949, 40.062894, "62-11",
                   "Ryazhsk Transit prison [C] Execution &amp; burial site",
                   "Ryazan Region, Ryazhsky district,&nbsp;Ryazhsk")
    + ","
    + _marker_json(55.7136, 84.8869, "42-18",
                   "YURGA cemetery [C]* &quot;Victims of War&quot; complex: "
                   "Deported Germans &amp; others [P]",
                   "Kemerovo Region, Yurga, Mashinostroiteli Street")
    + '],"mapCenter":"","mapZoom":4,"mapClusterer":true}});\n//--><!]]>\n</script>'
)

CARD_42_18 = """
<span class="card">Card</span><h2 class="card_no"> №42-18</h2>
<div class="field field-name-field-nane field-type-text field-label-hidden">
    <div class="field-items">
          <div class="field-item  omega even">YURGA cemetery [C]* &quot;Victims of War&quot;
          complex: Deported Germans &amp; others [P]</div>
      </div>
</div>
<div class="field field-name-field-data-zahoron-text field-type-text field-label-above">
      <div class="field-label grid_4 alpha text-right">Date of burial</div>
    <div class="field-items">
          <div class="field-item  omega even">1940s [2003] </div>
      </div>
</div>
<div class="field field-name-field-maps-data-test field-type-text-long field-label-above">
      <div class="field-label grid_4 alpha text-right">Address</div>
    <div class="field-items">
          <div class="field-item  omega even">Kemerovo Region, Yurga, Mashinostroiteli Street</div>
      </div>
</div>
<div class="field field-name-field-tipologia field-type-list-text field-label-inline clearfix">
      <div class="field-label grid_4 alpha text-right">Type of burial</div>
    <div class="field-items">
          <div class="field-item  omega even">Camp (prison) burial ground</div>
          <div class="field-item  omega odd">Deportees’ graveyard</div>
      </div>
</div>
<div class="field field-name-field-harakter-isp field-type-list-text field-label-inline clearfix">
      <div class="field-label grid_4 alpha text-right">Current use</div>
    <div class="field-items">
          <div class="field-item  omega even">Cultural and/or educational purposes</div>
          <div class="field-item  omega odd">Ceremonial events</div>
      </div>
</div>
<div class="field field-name-field-systemohran-kategor field-type-list-text clearfix">
      <div class="field-label grid_4 alpha text-right">Protected status</div>
    <div class="field-items">
          <div class="field-item  omega even">Regional / Republican</div>
      </div>
</div>
<div class="field field-name-field-istorich-text field-type-text-long field-label-above">
      <div class="field-label grid_4 alpha text-right">Background</div>
    <div class="field-items">
          <div class="field-item  omega even"><p>(справка не взята в образец)</p></div>
      </div>
</div>
"""


def test_markers_come_from_drupal_settings():
    markers = parse_markers(INDEX)
    assert [m.code for m in markers] == ["62-11", "42-18"]
    first = markers[0]
    assert (first.lat, first.lon) == (53.708949, 40.062894)
    assert first.name == "Ryazhsk Transit prison [C] Execution & burial site"
    assert first.address == "Ryazan Region, Ryazhsky district, Ryazhsk"


def test_page_without_markers_stops_the_harvest():
    with pytest.raises(MapOfMemoryError):
        parse_markers("<html><body>maintenance</body></html>")


def test_card_fields_are_lists_and_background_is_not_read():
    card = parse_card(CARD_42_18)
    check_card(card, "42-18")
    assert card["card_no"] == "42-18"
    assert card["date"] == ["1940s [2003]"]
    assert card["burial_type"] == ["Camp (prison) burial ground", "Deportees’ graveyard"]
    assert card["current_use"] == ["Cultural and/or educational purposes", "Ceremonial events"]
    assert "istorich-text" in card["fields"]
    assert not any("справка" in str(v) for k, v in card.items() if k != "fields")


def test_field_missing_on_one_card_is_a_gap_not_a_new_markup():
    """У 14-12 нет типа захоронения: запись остаётся, сбор не встаёт."""
    full = parse_card(CARD_42_18)
    gap = parse_card(CARD_42_18.replace("field-name-field-tipologia", "field-name-field-other"))
    check_card(gap, "42-18")
    assert check_cards({"42-18": full, "14-12": gap}) == {"tipologia": ["14-12"]}
    rec = card_to_record(parse_markers(INDEX)[1], gap)
    assert rec.category is None


def test_field_missing_on_every_card_stops_the_harvest():
    gap = parse_card(CARD_42_18.replace("field-name-field-tipologia", "field-name-field-other"))
    with pytest.raises(MapOfMemoryError):
        check_cards({"42-18": gap, "14-12": gap})


def test_card_without_a_name_stops_the_harvest():
    card = parse_card(CARD_42_18.replace("field-name-field-nane", "field-name-field-other"))
    with pytest.raises(MapOfMemoryError):
        check_card(card, "42-18")


def test_card_number_must_match_its_address():
    with pytest.raises(MapOfMemoryError):
        check_card(parse_card(CARD_42_18), "42-19")


@pytest.mark.parametrize("raw, expected", [
    ("1937", (1937, 1937, "year")),
    ("1930–1932", (1930, 1932, "year")),
    ("1937-38", (1937, 1938, "year")),
    ("1940s–1950s", (1940, 1959, "decade")),
    ("1940s-1950s", (1940, 1959, "decade")),
    ("1930s", (1930, 1939, "decade")),
    ("1931-1950s", (1931, 1959, "decade")),
    ("late 1930s", (1937, 1939, "decade")),
    ("early 1940s", (1940, 1943, "decade")),
    ("mid-1930s", (1934, 1936, "decade")),
    ("November 1941", (1941, 1941, "month")),
    ("Spring 1942", (1942, 1942, "season")),
    ("Oct. 1941 [June 1991]", (1941, 1941, "month")),
    ("11 September 1941", (1941, 1941, "day")),
    ("1923, 1930s-1950s", (1923, 1959, "decade")),
    ("Dec. 1935; Feb. 1938", (1935, 1938, "month")),
    ("mid-1940 to 1950s", (1944, 1959, "decade")),
    ("late 1920s-early 1940s", (1927, 1943, "decade")),
    ("1940s to mid 1950s", (1940, 1956, "decade")),
])
def test_english_burial_dates(raw, expected):
    period = burial_period(raw)
    assert (period.year_from, period.year_to, period.precision) == expected


def test_bracketed_year_is_not_the_burial_period():
    """«1940s [2003]»: в скобках — позднейшее событие, а не годы захоронений."""
    assert english_period("1940s [2003]") == "1940-е"
    period = burial_period("1940s [2003]")
    assert (period.year_from, period.year_to) == (1940, 1949)


def test_only_a_bracketed_year_means_no_burial_date():
    """«[1994]» — год перезахоронения, а годы самих захоронений не названы."""
    assert not burial_period("[1994]").ok
    rec = card_to_record(parse_markers(INDEX)[1],
                         parse_card(CARD_42_18.replace("1940s [2003]", "[1994]")))
    assert rec.confidence == "no_date"
    assert rec.extra["date_bracket"] == ["1994"]


def test_approximate_markers_survive_translation():
    period = burial_period("c. 1937")
    assert (period.year_from, period.year_to, period.approx) == (1937, 1937, True)


def test_marks_from_the_key_page_are_split_off():
    title, marks = split_marks("Skopin {c}** Cemetery at NKVD special hospital")
    assert title == "Skopin Cemetery at NKVD special hospital"
    assert marks == ["{c}**"]


def test_record_keeps_facts_and_a_link():
    marker = parse_markers(INDEX)[1]
    rec = card_to_record(marker, parse_card(CARD_42_18))
    assert rec.layer == BURIAL_SITES_TERROR.slug
    assert rec.group == "hardship"
    assert rec.title == 'YURGA cemetery "Victims of War" complex: Deported Germans & others'
    assert (rec.year_from, rec.year_to) == (1940, 1949)
    assert rec.period_raw == "1940s [2003]"
    assert rec.category == ("лагерное (тюремное) кладбище; "
                            "кладбище спецпоселенцев и депортированных")
    assert rec.url == "https://en.mapofmemory.org/42-18"
    assert rec.source_id == "42-18"
    assert rec.license.startswith("права не выяснены")
    assert rec.confidence == "ok"
    assert rec.extra["marks"] == ["[C]*", "[P]"]
    assert rec.extra["protected"] == ["Regional / Republican"]
    assert rec.extra["date_bracket"] == ["2003"]
    assert "охраняется как памятник регионального значения" in rec.summary


def test_undated_card_is_kept_and_flagged():
    card = parse_card(CARD_42_18.replace("1940s [2003]", "nk"))
    rec = card_to_record(parse_markers(INDEX)[1], card)
    assert rec.year_from is None
    assert rec.confidence == "no_date"


def test_neighbours_are_marked_not_removed():
    marker = Marker(code="1-01", lat=60.0, lon=30.0, name="A", address=None)
    rec = card_to_record(marker, parse_card(CARD_42_18))
    far = card_to_record(Marker(code="1-02", lat=61.0, lon=30.0, name="B", address=None),
                         parse_card(CARD_42_18))
    others = {"repressions": [(60.005, 30.0, "repressions:x", "Полигон")]}
    counts = mark_neighbours([rec, far], others, radius_km=2.0)
    assert counts == {"repressions": 1}
    assert rec.extra["near"]["repressions"]["uid"] == "repressions:x"
    assert rec.extra["near"]["repressions"]["km"] == pytest.approx(0.56, abs=0.01)
    assert "near" not in far.extra
