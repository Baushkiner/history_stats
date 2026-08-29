"""Слой населённых мест: отбор, названия и то, чего в наборе нет.

Пакет `geonamescache` в тестах не нужен: проверяется отбор и приведение к
схеме, а не наличие набора на диске.
"""

import json
from pathlib import Path

from histctx.io_formats import write_geojson
from histctx.sources.geonames import (
    SETTLEMENTS, pick_russian_name, select, size_of, to_records,
)

ROOT = Path(__file__).resolve().parents[1]


def city(**kw) -> dict:
    base = dict(geonameid=1, name="Buguruslan", latitude=53.65, longitude=52.43,
                countrycode="RU", population=52000, admin1code="12",
                alternatenames=["Buguruslan", "Бугуруслан"])
    base.update(kw)
    return base


# --- отбор ------------------------------------------------------------------

def test_only_countries_of_the_former_empire():
    assert list(select([city()]))
    assert not list(select([city(countrycode="CN", latitude=39.9, longitude=116.4)]))


def test_points_outside_the_map_frame_are_dropped():
    assert not list(select([city(latitude=48.85, longitude=2.35, countrycode="PL")]))


def test_broken_coordinates_are_dropped():
    assert not list(select([city(latitude=None, longitude=None)]))
    assert not list(select([city(latitude=0, longitude=0)]))


def test_extra_population_threshold():
    assert not list(select([city(population=800)], min_population=1000))
    assert list(select([city(population=1200)], min_population=1000))


# --- приведение к схеме ------------------------------------------------------

def test_russian_name_wins_over_latin():
    rec = to_records([city()])[0]
    assert rec.title == "Бугуруслан"
    assert rec.extra["name_latin"] == "Buguruslan"


def test_latin_name_is_kept_when_there_is_no_cyrillic():
    rec = to_records([city(alternatenames=["Zaritap", "Զարիթափ"], name="Zaritap")])[0]
    assert rec.title == "Zaritap"
    assert "name_latin" not in rec.extra


def test_record_is_a_point_without_a_date():
    """Года основания в наборе нет, и выдумывать его нельзя."""
    rec = to_records([city()])[0]
    assert rec.has_point and not rec.has_time
    assert rec.date_precision == "unknown"
    assert not rec.mappable          # для карты по времени не годится
    assert not rec.usable            # в подборе участвует как место, не как событие


def test_region_is_left_empty_on_purpose():
    """Код единицы есть, справочника названий нет: приписать наугад нельзя."""
    rec = to_records([city()])[0]
    assert rec.region is None
    assert rec.extra["admin1code"] == "12"


def test_attribution_is_in_every_record():
    rec = to_records([city()])[0]
    assert rec.url == "https://www.geonames.org/1"
    assert rec.source_id == "1"
    assert "CC BY 4.0" in rec.license


def test_duplicates_by_geonameid_collapse():
    assert len(to_records([city(), city()])) == 1


def test_size_bands():
    assert size_of(1_000_000) == "город"
    assert size_of(12_000) == "малый город"
    assert size_of(3_000) == "посёлок"
    assert size_of(600) == "село"


def test_pick_russian_name_ignores_latin_and_other_scripts():
    assert pick_russian_name({"alternatenames": ["Kyiv", "Київ", "Киев"]}) in {"Київ", "Киев"}
    assert pick_russian_name({"alternatenames": ["Kyiv", "Κίεβο", "キエフ"]}) is None


def test_layer_is_marked_as_harvested():
    from histctx.registry import BY_SLUG, HARVESTED

    assert SETTLEMENTS in HARVESTED
    assert BY_SLUG["settlements"].status == "harvested"


# --- выгрузка большого слоя ---------------------------------------------------

def test_shared_properties_are_hoisted_once(tmp_path):
    """У семнадцати тысяч точек общие свойства — больше половины файла."""
    records = to_records([city(geonameid=1), city(geonameid=2, name="Samara",
                                                  alternatenames=["Самара"], population=1_100_000)])
    path = tmp_path / "settlements.geojson"
    write_geojson(records, path, layer_title="Населённые места", hoist_shared=True)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["layer"]["source"] == SETTLEMENTS.source
    assert payload["layer"]["license"] == SETTLEMENTS.license
    for feat in payload["features"]:
        assert "source" not in feat["properties"]
        assert "license" not in feat["properties"]
        # Различающееся остаётся на месте.
        assert feat["properties"]["title"]
        assert feat["properties"]["category"]


def test_hoisting_is_off_by_default(tmp_path):
    """Формат уже отданных слоёв молча меняться не должен."""
    path = tmp_path / "plain.geojson"
    write_geojson(to_records([city()]), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "layer" not in payload
    assert payload["features"][0]["properties"]["source"] == SETTLEMENTS.source


# --- написания названий -------------------------------------------------------

def test_name_variants_collect_other_spellings():
    """Село в метрике названо иначе, чем на карте: Дерпт, Юрьев, Тарту."""
    from histctx.sources.geonames import name_variants

    out = name_variants([city(geonameid=588335, name="Tartu", alternatenames=[
        "Dorpat", "Derpt", "Yur'yev", "Tartu", "Тарту"])])
    item = out["588335"]
    assert item["title"] == "Тарту"
    assert "Dorpat" in item["names"] and "Yur'yev" in item["names"]
    # Заголовок в списке написаний не повторяется.
    assert "Тарту" not in item["names"]


def test_name_variants_drop_scripts_useless_for_russian_documents():
    from histctx.sources.geonames import name_variants

    out = name_variants([city(alternatenames=["Бугуруслан", "Buguruslan", "ブグルスラン", "布古鲁斯兰"])])
    assert out["1"]["names"] == ["Buguruslan"]


def test_name_variants_are_capped_per_place():
    from histctx.sources.geonames import name_variants

    many = [f"Name{i}" for i in range(40)]
    out = name_variants([city(alternatenames=["Бугуруслан", *many])], max_per_place=5)
    assert len(out["1"]["names"]) == 5


def test_place_without_other_spellings_is_skipped():
    from histctx.sources.geonames import name_variants

    assert name_variants([city(alternatenames=["Бугуруслан"])]) == {}


def test_name_variants_keep_coordinates_for_lookup():
    from histctx.sources.geonames import name_variants

    item = name_variants([city()])["1"]
    assert (item["lat"], item["lon"]) == (53.65, 52.43)
