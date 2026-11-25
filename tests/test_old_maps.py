"""Каталог старых привязанных карт: Retromap, ЭтоМесто, SLUB. Сети в тестах нет.

Образцы — ответы сайтов в том виде, в каком они приходили 24.11.2026.
"""

from histctx.sources.old_maps import (
    OLD_MAPS, coverage, etomesto_page, etomesto_record, etomesto_rows, etomesto_sections,
    parse_bounds, retromap_mcodes, retromap_record, retromap_records, retromap_years,
    slub_query, slub_record, slub_records,
)

JS = ("var dbase_cache = 'ca00q091775 ca00q081855 ca00r1016002 aa99w0020090 "
      "ca00q091775 ee00o091797.jpg';\nloc('Майкоп',2,'1419028',171,'Адыгея');")

MOSCOW_1855 = {
    "n": "1855 План Столичнаго города Москвы 1:25K ",
    "bounds": "55.6574478,37.4317932,55.8329163,37.8218079",
    "caption": "План столичного города Москвы и окрестностей / Сост. М. Рудольф. - 1:25200, "
               "300 саж. в дюйме. - М, 1855.",
    "keywords": "карты с иллюстрациями", "t": "2301",
}


def test_mcodes_skip_online_maps_and_repeats():
    assert retromap_mcodes(JS) == ["091775", "081855", "1016002", "091797"]


def test_year_is_taken_from_the_title_then_from_the_code():
    assert retromap_years("1855 План Москвы", "081855") == (1855, 1855, "План Москвы")
    assert retromap_years("1941-45 Схема", "061941") == (1941, 1945, "Схема")
    assert retromap_years("XVII век Военные слободы Москвы", "1216501") == (
        1601, 1700, "Военные слободы Москвы")
    assert retromap_years("План Москвы А. Чаянова", "1016002") == (
        1600, 1600, "План Москвы А. Чаянова")


def test_retromap_record_is_a_frame_with_year_scale_and_link():
    rec = retromap_record("081855", MOSCOW_1855)
    assert rec.layer == OLD_MAPS.slug
    assert rec.title == "План Столичнаго города Москвы, 1855"
    assert (rec.year_from, rec.year_to) == (1855, 1855)
    assert rec.extra["scale"] == 25000 and rec.extra["bbox"] == [37.4318, 55.6574, 37.8218,
                                                                  55.8329]
    assert rec.confidence == "sheet_center" and 55.7 < rec.lat < 55.8
    assert rec.url == "https://retromap.ru/081855"
    assert rec.category == "план города или местности"
    assert "масштаб 1:25 000" in rec.summary and "Москва, XIX век" in rec.summary
    assert "не скопирована" in rec.summary and "согласия владельца" in rec.license
    assert rec.extra["caption"].startswith("План столичного")


def test_century_title_is_a_century():
    rec = retromap_record("1216501", dict(MOSCOW_1855, n="XVII век Военные слободы Москвы"))
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1601, 1700, "century")


def test_late_or_undated_maps_are_not_taken():
    assert retromap_record("051971", dict(MOSCOW_1855, n="1971 Карта области")) is None
    assert len(retromap_records({"081855": MOSCOW_1855,
                                 "0519711": dict(MOSCOW_1855, n="1971 Карта")})) == 1


def test_bounds_of_the_whole_earth_are_no_frame():
    assert parse_bounds("-85,-180,85,180") is None
    assert parse_bounds("55,37,56,38") == (37.0, 55.0, 38.0, 56.0)
    assert coverage((20.0, 50.0, 40.0, 60.0)) == "обзорная карта"


SLUB_HIT = {"_id": "oai:de:slub-dresden:vk:id-10010323", "_source": {
    "map_id": "oai:de:slub-dresden:vk:id-10010323", "map_scale": 100000, "map_type": "tk",
    "title": "Kretinga u. Šatriai in Litauen", "title_long": "Karte des westlichen Russlands",
    "permalink": "https://www.deutschefotothek.de/documents/obj/70300002",
    "online_resources": [{"url": "https://wms.kartenforum.slub-dresden.de/map/10010323",
                          "type": "WMS"}],
    "geometry": {"type": "Polygon", "coordinates": [[[20.83, 55.75], [21.37, 55.75],
                                                     [21.37, 56.0], [20.83, 56.0],
                                                     [20.83, 55.75]]]},
    "time_period_start": "1906-01-01", "time_period_end": "1906-12-31"}}


def test_slub_record_and_query():
    rec = slub_record(SLUB_HIT)
    assert rec.title == "Kretinga u. Šatriai in Litauen, 1906"
    assert rec.extra["bbox"] == [20.83, 55.75, 21.37, 56.0]
    assert rec.extra["map_type"] == "tk" and rec.extra["scale"] == 100000
    assert rec.source_id == "slub:id-10010323" and "Fotothek" in rec.license
    late = {"_source": dict(SLUB_HIT["_source"], time_period_start="1985-01-01")}
    assert len(slub_records({"hits": {"hits": [SLUB_HIT, late]}})) == 1
    q = slub_query((18.0, 35.0, 180.0, 82.0))
    shape = q["query"]["bool"]["filter"][0]["geo_shape"]["geometry"]["shape"]
    assert shape["coordinates"] == [[18.0, 82.0], [180.0, 35.0]]


LIST_HTML = (
    '<a href=/belarus/catalog.php>Б</a> <a href="/kazan/catalog.php">К</a>'
    '<tr><td><a href=/map-belarus_minsk_minskaya-guberniya-1850/ class=bb>'
    '<big>Карта Минской губернии 1850 г.</big></a></div></td><td><B>'
    '<a href=/russia/maps.php?god=1850 class=bb rel=nofollow>1850</a></B></td>')
MAP_HTML = (
    "<title>Карта Минской губернии середины XIX века - Это Место</title>"
    "var cxmap=27.556490\nvar cymap=53.903934\nvar mapID = 11185;"
    "'&map=11185&city=102&year=1850&tip=3';"
    "<div class=read style=\"max-width: 1200px;\">\nКарту Минской губернии составил и издал "
    "Яков Кузнецов. Масштаб 20 верст в дюйме.\n\n<p>")


def test_etomesto_list_and_page_are_parsed():
    assert etomesto_sections(LIST_HTML) == ["belarus", "kazan"]
    rows = etomesto_rows(LIST_HTML)
    assert rows == [{"slug": "belarus_minsk_minskaya-guberniya-1850",
                     "title": "Карта Минской губернии 1850 г.", "year": 1850}]
    page = etomesto_page(MAP_HTML)
    assert page["title"] == "Карта Минской губернии середины XIX века"
    assert (page["year"], page["map_id"], page["lat"]) == (1850, "11185", 53.903934)
    rec = etomesto_record(rows[0]["slug"], dict(rows[0], section="belarus"), page)
    assert rec.title == "Карта Минской губернии середины XIX века, 1850"
    assert rec.confidence == "place_level" and "bbox" not in rec.extra
    assert "Яков Кузнецов" in rec.summary and "центр раздела" in rec.summary
    assert rec.url == "https://etomesto.ru/map-belarus_minsk_minskaya-guberniya-1850/"
    # Нынешний исторический атлас — год изображаемый, не год карты.
    assert etomesto_record("atlas_russia-history_1600", rows[0], page) is None
