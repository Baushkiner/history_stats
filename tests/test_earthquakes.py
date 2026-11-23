"""Разбор и сведение каталогов землетрясений: NOAA NCEI, EMCA, GEM.

Сети в тестах нет. Образцы — строки ответов Hazard Service NOAA (землетрясения,
цунами, набеги) с их полями, CSV EMCA с «NA» и CSV GEM с однородной Mw, а
рамка — два квадрата губерний, Россия и соседнее государство.

Проверяется то, на чём слой держится: разбор полей и магнитуд, сведение
каталогов в одно событие (и то, что афтершоки не слипаются), юлианская дата
для метрики, место события — рамка, море у берега, соседняя земля у границы,
вдали — и правила отбора, цунами при землетрясении и набеги, сверка файлов
и кэш ответов NOAA.
"""

import datetime as dt
import hashlib
import json

import pytest

from histctx.registry import BY_SLUG
from histctx.schema import ContextRecord
from histctx.sources import earthquakes as eq
from histctx.sources.earthquakes import (
    EARTHQUAKES, GEM_KEY, GEM_MD5, GEM_SIZE, KIND_ABROAD, KIND_FRAME, KIND_OFF, KIND_SEA,
    EarthquakesError, Event, NoaaClient, Placement, Spot, build, cached_file,
    check_gem_manifest, cluster, date_text, emca_events, gem_events, gregorian_to_julian,
    keep_spot, losses, match_score, noaa_events, runup_wanted,
)


def test_layer_is_registered_as_harvested():
    assert BY_SLUG["earthquakes"] is EARTHQUAKES
    assert EARTHQUAKES.status == "harvested" and EARTHQUAKES.expected_rows
    assert "общественное достояние" in EARTHQUAKES.license
    assert "CC BY-SA 4.0" in EARTHQUAKES.license


# --- разбор каталогов -------------------------------------------------------------

NOAA_ITEMS = [
    {"id": 3080, "year": 1887, "month": 6, "day": 8, "locationName": "KAZAKHSTAN:  ALMA-ATA",
     "latitude": 43.1, "longitude": 76.8, "eqDepth": 20, "eqMagnitude": 7.3, "eqMagMs": 7.3,
     "intensity": 10, "deaths": 332, "deathsAmountOrder": 3, "housesDestroyedAmountOrder": 4,
     "country": "KAZAKHSTAN"},
    {"id": 1047, "year": 1667, "month": 11, "locationName": "AZERBAIJAN:  SHEMAKHA (SAMAXI)",
     "latitude": 40.6, "longitude": 48.6, "eqMagnitude": 6.9, "eqMagMs": 6.9,
     "deathsTotal": 80000, "country": "AZERBAIJAN"},
    {"id": 1, "year": 1500, "latitude": 40.0, "longitude": 48.0},       # до рамки лет
    {"id": 2, "year": 1900, "latitude": None, "longitude": 48.0},       # без точки
]


def test_noaa_events_fields_and_magnitude_type():
    events = {e.source_id: e for e in noaa_events(NOAA_ITEMS)}
    assert set(events) == {"3080", "1047"}
    verny = events["3080"]
    assert (verny.year, verny.month, verny.day, verny.precision) == (1887, 6, 8, "day")
    assert verny.magnitude == 7.3 and verny.mag_type == "Ms"
    assert verny.fields["deaths"] == 332 and verny.fields["intensity"] == 10
    assert events["1047"].precision == "month" and events["1047"].iso() == "1667-11"


EMCA_CSV = ('"id","year","month","day","hour","min","sec","lat","lon","fdepth","mlh"\n'
            "5000,1887,6,9,4,35,NA,43.1,76.9,20,7.3\n"
            "5001,1650,NA,NA,NA,NA,NA,40.6,48.6,10,6\n"
            "5002,-250,NA,NA,NA,NA,NA,42.7,77.5,20,6.7\n")


def test_emca_events_read_na_as_unknown():
    events = emca_events(EMCA_CSV)
    assert [e.source_id for e in events] == ["5000", "5001"]
    assert events[0].mag_type == "MLH" and events[0].day == 9
    assert events[1].month is None and events[1].precision == "year"


def test_emca_without_needed_columns_is_an_error():
    with pytest.raises(EarthquakesError, match="mlh"):
        emca_events('"id","year","lat","lon"\n1,1900,40,50\n')


GEM_CSV = ("eventID,Agency,year,month,day,hour,second,longitude,latitude,depth,magnitude,"
           "magType,magAgency,minute\n"
           "16957848,GEM24,1905,4,4,0,59.0,76.916,32.597,20.0,7.93752,Mw,ISCGEM,49\n"
           "610326271,GEM24,1911,1,3,23,25.0,77.0,43.0,25.0,8.1,Mw,ISCGEM,25\n"
           "cmt_x,GCMT_upd,2024,12,31,23,20.0,-70.62,-20.18,35.0,5.19,Mw,GCMT,13\n")


def test_gem_events_select_years_and_frame_rectangle():
    events = gem_events(GEM_CSV)
    # Кангра 1905 года (32,6° с. ш.) — вне прямоугольника охвата, 2024 год — вне лет.
    assert [e.source_id for e in events] == ["610326271"]
    assert events[0].mag_type == "Mw" and events[0].magnitude == 8.1


# --- сведение ----------------------------------------------------------------------

def ev(catalog, sid, year, month=None, day=None, lat=43.0, lon=77.0, m=None):
    return Event(catalog=catalog, source_id=sid, year=year, month=month, day=day, lat=lat,
                 lon=lon, magnitude=m)


def test_match_score_by_date_and_distance():
    a = ev("NOAA", "1", 1911, 1, 3, 43.0, 77.0, 8.0)
    assert match_score(a, ev("GEM", "2", 1911, 1, 4, 43.5, 77.5, 8.1)) is not None
    assert match_score(a, ev("GEM", "2", 1911, 1, 6, 43.0, 77.0)) is None      # три дня
    assert match_score(a, ev("GEM", "2", 1911, 1, 3, 46.0, 77.0)) is None      # 330 км
    assert match_score(a, ev("NOAA", "2", 1911, 1, 3)) is None                # один каталог
    assert match_score(ev("NOAA", "1", 1650, lat=40.6, lon=48.6, m=6.9),
                       ev("EMCA", "2", 1650, lat=40.6, lon=48.6, m=4.0)) is None  # магнитуды


def test_cluster_merges_one_event_per_catalog():
    groups = cluster([
        ev("NOAA", "n1", 1911, 1, 3, m=8.0), ev("EMCA", "e1", 1911, 1, 3, m=8.2),
        ev("GEM", "g1", 1911, 1, 4, lat=43.2, m=8.1),
        # Два толчка одного года без даты у NOAA и один у EMCA: EMCA встаёт к одному.
        ev("NOAA", "n2", 1671, lat=40.6, lon=48.6, m=5.0),
        ev("NOAA", "n3", 1671, lat=40.6, lon=48.6, m=5.1),
        ev("EMCA", "e2", 1671, lat=40.61, lon=48.6, m=5.0),
    ])
    as_ids = sorted(tuple(e.source_id for e in g) for g in groups)
    assert ("n1", "e1", "g1") in as_ids
    assert sum(1 for g in groups if any(e.source_id in ("n2", "n3") for e in g)) == 2
    assert sum(len(g) for g in groups) == 6


# --- даты ----------------------------------------------------------------------------

def test_julian_date_for_the_metric_book():
    assert gregorian_to_julian(dt.date(1887, 6, 9)) == (1887, 5, 28)
    assert gregorian_to_julian(dt.date(1700, 3, 11)) == (1700, 2, 29)   # юлианский високос
    assert gregorian_to_julian(dt.date(1918, 2, 13)) == (1918, 1, 31)
    assert date_text(ev("NOAA", "1", 1887, 6, 9)) == "9 июня 1887 года (28 мая по старому стилю)"
    assert date_text(ev("NOAA", "1", 1889, 1, 12)) == (
        "12 января 1889 года (31 декабря 1888 года по старому стилю)")
    assert date_text(ev("GEM", "1", 1948, 10, 6)) == "6 октября 1948 года"
    assert date_text(ev("EMCA", "1", 1650, 11)) == "ноябрь 1650 года"
    assert date_text(ev("EMCA", "1", 1650)) == "1650 год"


def test_losses_use_numbers_then_orders():
    assert losses({"deaths": 332, "housesDestroyedAmountOrderTotal": 4,
                   "damageAmountOrder": 3}) == [
        "погибших — 332", "разрушено домов — больше тысячи", "ущерб тяжёлый ($5–25 млн)"]
    assert losses({"deathsAmountOrder": 1}) == ["погибших — до 50"]


# --- место -------------------------------------------------------------------------------

def _square(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def _boundaries(tmp_path):
    provinces = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"prov_RU": "Семиреченская область"},
         "geometry": {"type": "Polygon", "coordinates": _square(74.0, 42.0, 80.0, 46.0)}},
    ]}
    states = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"state": "Россия (Советский Союз)", "year_from": 1886,
                                           "year_to": 1991},
         "geometry": {"type": "Polygon", "coordinates": _square(70.0, 42.0, 82.0, 50.0)}},
        {"type": "Feature", "properties": {"state": "Китай", "year_from": 1886, "year_to": 1960},
         "geometry": {"type": "Polygon", "coordinates": _square(70.0, 36.0, 82.0, 42.0)}},
    ]}
    (tmp_path / "provinces_1897.geojson").write_text(json.dumps(provinces), encoding="utf-8")
    (tmp_path / "state_borders.geojson").write_text(json.dumps(states), encoding="utf-8")
    return tmp_path


@pytest.fixture
def place(tmp_path):
    towns = [ContextRecord(layer="settlements", title="Алматы", lat=43.25, lon=76.9,
                           category="город")]
    base = Placement.load(_boundaries(tmp_path), tmp_path / "нет.geojson")
    return Placement(base.frame, base.states, towns)


def test_place_frame_sea_abroad_and_far(place):
    inside = place.place(43.1, 76.9, 1887)
    assert inside.kind == KIND_FRAME and inside.province == "Семиреченская область"
    # Восточнее всех фигур — вода, суша рамки в ~75–100 км.
    sea = place.place(46.0, 83.0, 1911)
    assert sea.kind == KIND_SEA and 50 <= sea.km <= 100
    abroad = place.place(41.6, 76.0, 1902)
    assert abroad.kind == KIND_ABROAD and abroad.state == "Китай" and abroad.km <= 50
    far = place.place(37.0, 76.0, 1902)
    assert far.kind == KIND_OFF and far.state == "Китай"
    assert place.town(43.2, 76.9) == ("Алматы", pytest.approx(5.6, abs=0.5))


def test_keep_rules_at_sea_and_across_the_border():
    gem = [ev("GEM", "g", 1952, 11, 5, m=5.6)]
    assert keep_spot(Spot(KIND_FRAME, "x", 0), gem)
    assert not keep_spot(Spot(KIND_SEA, None, 100), gem), "M 5,6 в 100 км от берега — нет"
    assert keep_spot(Spot(KIND_SEA, None, 20), gem)
    assert keep_spot(Spot(KIND_SEA, None, 120), [ev("GEM", "g", 1952, 11, 5, m=7.2)])
    assert keep_spot(Spot(KIND_SEA, None, 140), [ev("NOAA", "n", 1952, 11, 5)])
    assert not keep_spot(Spot(KIND_ABROAD, None, 60, state="Иран"), [ev("EMCA", "e", 1900,
                                                                       m=5.0)])
    assert keep_spot(Spot(KIND_ABROAD, None, 20, state="Иран"), [ev("EMCA", "e", 1900, m=4.0)])
    assert keep_spot(Spot(KIND_ABROAD, None, 90, state="Иран"), [ev("EMCA", "e", 1900, m=6.3)])
    assert not keep_spot(Spot(KIND_OFF, None, None), [ev("NOAA", "n", 1900)])


# --- сборка ----------------------------------------------------------------------------------

def test_build_merges_catalogs_tsunami_and_runups(place):
    quakes = [dict(NOAA_ITEMS[0], tsunamiEventId=77)]
    tsunamis = [
        {"id": 77, "year": 1887, "month": 6, "day": 8, "latitude": 43.1, "longitude": 76.8,
         "maxWaterHeight": 2.5, "eventValidity": 4, "causeCode": 1, "earthquakeEventId": 3080},
        {"id": 78, "year": 1900, "latitude": 43.0, "longitude": 77.0, "eventValidity": -1},
        {"id": 79, "year": 1910, "month": 3, "day": 1, "latitude": 43.0, "longitude": 78.0,
         "eventValidity": 3, "causeCode": 6, "locationName": "LAKE"},
    ]
    runups = [
        {"id": 900, "tsunamiEventId": 77, "year": 1887, "month": 6, "day": 8, "latitude": 43.24,
         "longitude": 76.91, "runupHt": 3.0, "deaths": 2, "locationName": "VERNYI SHORE",
         "doubtful": "n"},
        {"id": 901, "tsunamiEventId": 77, "year": 1887, "latitude": 43.3, "longitude": 77.0,
         "runupHt": 0.2, "doubtful": "n"},
    ]
    emca = emca_events(EMCA_CSV)
    result = build(quakes, tsunamis, runups, emca, [], place)
    by_kind = {}
    for rec in result.records:
        by_kind.setdefault(rec.category, []).append(rec)
    quake = by_kind["землетрясение и цунами"][0]
    assert quake.title == "Землетрясение и цунами M 7,3 — Алматы"
    assert quake.region == "Семиреченская область" and quake.confidence == "ok"
    assert quake.date_precision == "day" and (quake.year_from, quake.year_to) == (1887, 1887)
    assert "8 июня 1887 года (27 мая по старому стилю)" in quake.summary
    assert "погибших — 332" in quake.summary and "волна до 2,5 м" in quake.summary
    assert "EMCA — 7,3 MLH" in quake.summary
    assert quake.url.endswith("/earthquake/event-more-info/3080")
    assert quake.license == ("общественное достояние (данные NOAA NCEI); "
                             "CC BY-SA 4.0 (EMCA, GFZ Potsdam)")
    assert [c["catalog"] for c in quake.extra["catalogs"]] == ["NOAA", "EMCA"]
    assert quake.extra["tsunami_id"] == 77
    # Цунами без землетрясения — своя запись; ошибочная запись NOAA — мимо.
    assert [r.extra["tsunami_id"] for r in by_kind["цунами"]] == [79]
    assert "извержение вулкана" in by_kind["цунами"][0].summary
    assert result.counts["цунами: ошибочная запись NOAA (validity −1), не взято"] == 1
    # Набег: волна 3 м — запись, 20 см без жертв — нет.
    runup = by_kind["набег цунами"]
    assert len(runup) == 1 and runup[0].title == "Набег цунами — Алматы"
    assert runup[0].url.endswith("/runup-more-info/900")
    # Шемаха EMCA 1650 года без пары — своя запись вне рамки квадратов: вдали.
    assert result.counts["не взято: вдали"] == 1


def test_runup_wanted():
    assert runup_wanted({"runupHt": 2.0})
    assert runup_wanted({"runupHt": 0.3, "deaths": 1})
    assert not runup_wanted({"runupHt": 0.3})
    assert not runup_wanted({"runupHt": 10, "doubtful": "y"})


# --- файлы и сеть ---------------------------------------------------------------------------

def test_gem_manifest_check():
    good = [{"key": GEM_KEY, "size": GEM_SIZE, "checksum": f"md5:{GEM_MD5}"}]
    assert check_gem_manifest(good) == []
    bad = [{"key": GEM_KEY, "size": 1, "checksum": "md5:0"}]
    assert len(check_gem_manifest(bad)) == 2
    assert "нет" in check_gem_manifest([{"key": "other.zip"}])[0]


def test_cached_file_checks_size_and_md5(tmp_path, monkeypatch):
    data = b"catalog"
    md5 = hashlib.md5(data).hexdigest()
    monkeypatch.setattr(eq, "fetch_bytes", lambda url, **kw: data)
    assert cached_file(tmp_path, "c.zip", "https://x/c.zip", len(data), md5) == data
    assert (tmp_path / "c.zip").read_bytes() == data
    monkeypatch.setattr(eq, "fetch_bytes", lambda url, **kw: pytest.fail("из кэша"))
    assert cached_file(tmp_path, "c.zip", "https://x/c.zip", len(data), md5) == data
    with pytest.raises(EarthquakesError, match="ожидалось"):
        monkeypatch.setattr(eq, "fetch_bytes", lambda url, **kw: b"other")
        cached_file(tmp_path, "d.zip", "https://x/d.zip", len(data), md5)


def test_noaa_client_pages_cache_and_pause(tmp_path, monkeypatch):
    calls, sleeps = [], []
    pages = {1: {"items": [{"id": 1}], "totalPages": 2}, 2: {"items": [{"id": 2}],
                                                              "totalPages": 2}}

    def fake_get(url, **kw):
        calls.append(url)
        page = int(url.rsplit("page=", 1)[1])
        return pages[page]

    monkeypatch.setattr(eq, "_get_json", fake_get)
    monkeypatch.setattr(eq.time, "sleep", lambda s: sleeps.append(s))
    client = NoaaClient(tmp_path, pause=60, log=lambda s: None)
    items = client.all_items("earthquakes", "rect", {"minYear": 1600})
    assert [i["id"] for i in items] == [1, 2] and len(calls) == 2
    assert sleeps and sleeps[0] > 50, "вторая страница ждёт паузу из robots.txt"
    again = NoaaClient(tmp_path, pause=60, log=lambda s: None)
    assert [i["id"] for i in again.all_items("earthquakes", "rect", {"minYear": 1600})] == [1, 2]
    assert len(calls) == 2 and again.requests == 0, "повторный запуск — из кэша"
