"""Разбор набора GeoPolHist: статус территорий мира 1816–1960 годов.

Сети в тестах нет. Набор — три CSV в архиве-снимке репозитория médialab,
поэтому образец собирается здесь же, с тем же корнем каталога и теми же
колонками, что у версии 202603.

Проверяется то, на чём слой держится: сверка файла с размером и md5 из кода,
отбор строк по рамке лет (и строк с началом «?»), подписи из своего словаря —
территория, статус существительным и суверен в именительном, — точка как
условный центр и записи без точки, ссылка на полигон CShapes по номеру.
"""

import hashlib
import zipfile
from collections import Counter

import pytest

from histctx.registry import BY_SLUG
from histctx.sources import geopolhist
from histctx.sources.geopolhist import (
    ARCHIVE_KEY, ARCHIVE_MD5, ARCHIVE_SIZE, CODE_MISMATCH, ENTITIES, STATUS_DEFS,
    STATUS_RU, STATUS_SUMMARY, STATUSES, TERRITORY_STATUS, GeoPolHistError, check_manifest,
    overlaps, read_archive, records, status_summary, status_title, unknown_statuses,
    untranslated, wikidata_url, year,
)
from histctx.sources.geopolhist_names import NAMES_RU

ROOT = "medialab-GeoPolHist-e6f3f17"

ENTITY_HEAD = ("GPH_code,GPH_name,continent,wikidata,wikidata_alt1,wikidata_alt2,"
               "wikidata_alt3,notes,lat,lng")
ENTITY_ROWS = [
    "0,League of Nations,World,https://www.wikidata.org/wiki/Q38130,,,,,,",
    "365,Russia (USSR),Europe,http://www.wikidata.org/entity/Q159,,,,,60,90",
    "710,People's Republic of China (China),Asia,http://www.wikidata.org/entity/Q148,,,,,35,103",
    "711,Manchukuo,Asia,http://www.wikidata.org/entity/Q141835,,,,,44,125",
    "7133,Harbin,Asia,https://www.wikidata.org/wiki/Q42956,,,,,45.75,126.63333333333",
    "291,Danzig (Free City of Danzig),Europe,http://www.wikidata.org/entity/Q1792,,,,,54.35,18.65",
    "290,Poland,Europe,http://www.wikidata.org/entity/Q36,,,,,52,19",
    "1101,Quita Sueno Bank,America,http://www.wikidata.org/entity/Q1,,,,,14.2,-81.1",
    "100,Colombia (New Granada) (Gran Colombia),America,http://www.wikidata.org/entity/Q739,,,,,4,-72",
    "9999,Atlantis,Europe,,,,,,,",
]
STATUS_HEAD = "GPH_code,GPH_name,start_year,end_year,GPH_status,sovereign_GPH_code"
STATUS_ROWS = [
    "7133,Harbin,1816,1896,Part of,710",
    "7133,Harbin,1896,1952,Leased to,365",
    "7133,Harbin,1952,2022,Part of,710",
    "291,Danzig (Free City of Danzig),1920,1939,Mandated to,0",
    "290,Poland,1816,1816,Dissolved into,291",
    "290,Poland,1918,1939,Sovereign,",
    "711,Manchukuo,1932,1945,Sovereign (limited),",
    "1101,Quita Sueno Bank,?,1981,Claimed by,100",
    "9999,Atlantis,1800,1810,Sovereign,",            # до рамки слоя
    "9999,Atlantis,1961,1990,Sovereign,",            # после неё
    "9999,Atlantis,1930,1940,Ruled by dragons,",     # статус, которого нет в словаре
    "0,League of Nations,1920,1945,International,",
]
DEFS = "GPH_status,slug,group,priority_order,COW_status,UN_status,definition\n" + "\n".join(
    f"{s},x,,0,,,def" for s in STATUS_RU)


def build_archive(tmp_path, *, entities=None, statuses=None, defs=DEFS, root=ROOT):
    path = tmp_path / "GeoPolHist-202603.zip"
    tables = {
        ENTITIES: "\n".join([ENTITY_HEAD, *(ENTITY_ROWS if entities is None else entities)]),
        STATUSES: "\n".join([STATUS_HEAD, *(STATUS_ROWS if statuses is None else statuses)]),
        STATUS_DEFS: defs,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{root}/README.md", "# GeoPolHist dataset")
        for name, text in tables.items():
            archive.writestr(f"{root}/data/{name}", text)
    return path


@pytest.fixture
def recs(tmp_path):
    return records(read_archive(build_archive(tmp_path)), polygon_codes={290, 291, 711})


def by_title(recs):
    return {r.title: r for r in recs}


def test_archive_is_read_into_three_tables(tmp_path):
    tables = read_archive(build_archive(tmp_path))
    assert len(tables[ENTITIES]) == len(ENTITY_ROWS)
    assert tables[STATUSES][1]["GPH_status"] == "Leased to"
    assert len(tables[STATUS_DEFS]) == len(STATUS_RU)


def test_redesigned_dataset_stops_the_harvest(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(GeoPolHistError, match="zip"):
        read_archive(bad)
    with pytest.raises(GeoPolHistError, match="sovereign_GPH_code"):
        read_archive(_without_column(tmp_path))
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr(f"{ROOT}/README.md", "")
    with pytest.raises(GeoPolHistError, match="data/GeoPolHist_entities.csv"):
        read_archive(empty)


def _without_column(tmp_path):
    path = tmp_path / "nocol.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{ROOT}/data/{ENTITIES}", "\n".join([ENTITY_HEAD, *ENTITY_ROWS]))
        archive.writestr(f"{ROOT}/data/{STATUSES}",
                         "GPH_code,GPH_name,start_year,end_year,GPH_status\n1,a,1900,1910,Sovereign")
        archive.writestr(f"{ROOT}/data/{STATUS_DEFS}", DEFS)
    return path


def test_manifest_is_checked_against_the_code():
    good = [{"key": ARCHIVE_KEY, "size": ARCHIVE_SIZE, "checksum": f"md5:{ARCHIVE_MD5}"}]
    assert check_manifest(good) == []
    changed = [{"key": ARCHIVE_KEY, "size": 1, "checksum": "md5:00"}]
    problems = check_manifest(changed)
    assert len(problems) == 2 and "размер" in problems[0] and "сумма" in problems[1]
    assert "есть: other.zip" in check_manifest([{"key": "other.zip"}])[0]


def test_archive_of_another_version_is_not_cached(tmp_path, monkeypatch):
    payload = b"zip bytes"
    monkeypatch.setattr(geopolhist, "fetch_bytes", lambda url, **kw: payload)
    with pytest.raises(GeoPolHistError, match="ожидалось"):
        geopolhist.cached_archive(tmp_path)
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(geopolhist, "ARCHIVE_SIZE", len(payload))
    monkeypatch.setattr(geopolhist, "ARCHIVE_MD5", hashlib.md5(payload).hexdigest())
    assert geopolhist.cached_archive(tmp_path).read_bytes() == payload


def test_rows_are_matched_against_the_layer_window():
    assert year("1896") == 1896 and year("?") is None and year("") is None
    assert overlaps({"start_year": "1816", "end_year": "1896"})
    assert overlaps({"start_year": "1952", "end_year": "2022"})
    assert not overlaps({"start_year": "1800", "end_year": "1810"})
    assert not overlaps({"start_year": "1961", "end_year": "1990"})
    assert overlaps({"start_year": "?", "end_year": "1981"})      # начало — от 1816 года
    assert not overlaps({"start_year": "?", "end_year": "?"})


def test_window_keeps_years_as_in_the_dataset(recs):
    assert "Atlantis — суверенное государство" not in by_title(recs)
    harbin = sorted((r.year_from, r.year_to) for r in recs if r.place_text == "Harbin")
    assert harbin == [(1816, 1896), (1896, 1952), (1952, 2022)], \
        "конец 2022 года не обрезается по рамке"
    assert len(recs) == 10      # девять своих строк и одна со статусом не из словаря


def test_title_names_the_status_and_the_sovereign(recs):
    harbin = by_title(recs)["Харбин — аренда: Россия (СССР)"]
    assert harbin.category == "аренда" and harbin.actor == "Россия (СССР)"
    assert harbin.summary == "1896–1952: аренда; арендатор — Россия (СССР). По GeoPolHist"
    assert harbin.place_text == "Harbin" and harbin.source_id == "7133"
    assert harbin.url == "https://doi.org/10.5281/zenodo.19252806"
    assert harbin.extra["status_en"] == "Leased to"
    assert harbin.extra["sovereign_en"] == "Russia (USSR)"
    assert harbin.extra["wikidata"] == "https://www.wikidata.org/wiki/Q42956"
    danzig = by_title(recs)["Данциг (вольный город) — мандат: Лига Наций"]
    assert danzig.summary.startswith("1920–1939: мандат; мандатарий — Лига Наций")
    assert by_title(recs)["Польша — суверенное государство"].actor is None


def test_dissolution_is_an_event_of_one_year(recs):
    poland = by_title(recs)["Польша — упразднение: Данциг (вольный город)"]
    assert poland.year_from == poland.year_to == 1816
    assert poland.summary.startswith("1816: упразднение; правопреемник — ")


def test_unknown_start_is_taken_from_the_dataset_horizon(recs):
    bank = by_title(recs)["Банка Кита-Суэньо — притязания: Колумбия (Новая Гранада, "
                          "Великая Колумбия)"]
    assert bank.year_from == 1816 and bank.year_to == 1981
    assert bank.date_precision == "open"
    assert bank.period_raw == "?–1981"


def test_point_is_the_territory_center_and_pointless_records_stay(recs):
    harbin = by_title(recs)["Харбин — аренда: Россия (СССР)"]
    assert harbin.has_point and harbin.confidence == "territory_center"
    league = by_title(recs)["Лига Наций — международная организация"]
    assert not league.has_point and league.confidence == "no_coords"


def test_record_points_at_the_cshapes_polygon_by_code(recs):
    titles = by_title(recs)
    assert titles["Польша — суверенное государство"].extra["state_borders_gwcode"] == 290
    assert "state_borders_gwcode" not in titles["Харбин — аренда: Россия (СССР)"].extra
    # 711 у CShapes — Тибет, а у GeoPolHist — Маньчжоу-го: ссылки быть не должно.
    manchukuo = titles["Маньчжоу-го — ограниченный суверенитет"]
    assert 711 in CODE_MISMATCH and "state_borders_gwcode" not in manchukuo.extra


def test_unknown_status_and_name_go_as_is(tmp_path):
    tables = read_archive(build_archive(tmp_path))
    assert unknown_statuses(tables) == ["Ruled by dragons"]
    assert untranslated(tables) == ["Atlantis"]
    rec = [r for r in records(tables) if r.extra["status_en"] == "Ruled by dragons"][0]
    assert rec.title == "Atlantis — Ruled by dragons" and rec.category == "Ruled by dragons"


def test_uids_are_unique(recs):
    assert len({r.uid for r in recs}) == len(recs)


def test_summary_without_a_sovereign_keeps_only_the_status():
    assert status_summary("Leased to", None, "1900") == "1900: аренда. По GeoPolHist"
    assert status_summary("Sovereign", "Франция", "1900") \
        == "1900: суверенное государство; связь — Франция. По GeoPolHist"
    assert status_title("Тува", "Protectorate of", "Россия (СССР)") \
        == "Тува — протекторат: Россия (СССР)"


def test_wikidata_links_are_brought_to_one_form():
    assert wikidata_url("http://www.wikidata.org/entity/Q30") == "https://www.wikidata.org/wiki/Q30"
    assert wikidata_url("https://www.wikidata.org/wiki/Q42956") \
        == "https://www.wikidata.org/wiki/Q42956"
    assert wikidata_url("") is None


def test_status_dictionaries_cover_the_twenty_statuses():
    assert len(STATUS_RU) == 20 and set(STATUS_SUMMARY) == set(STATUS_RU)
    for status, template in STATUS_SUMMARY.items():
        assert template, status


def test_names_dictionary_translates_and_never_merges_two_territories():
    for en, ru in NAMES_RU.items():
        assert ru and ru != en, en
    clashes = [ru for ru, n in Counter(NAMES_RU.values()).items() if n > 1]
    assert clashes == []


def test_anachronism_rule_puts_the_country_first():
    """Маньчжурия 1850 года не должна оказаться «в составе КНР»."""
    assert NAMES_RU["People's Republic of China (China)"].startswith("Китай")
    assert NAMES_RU["Egypt Arab Republic (Egypt)"].startswith("Египет")
    # «нынешнее (прежнее)» не трогается: это не строй, а название страны.
    assert NAMES_RU["Sri Lanka (Ceylon)"] == "Шри-Ланка (Цейлон)"
    assert NAMES_RU["Kamerun"] == "Германский Камерун"


def test_layer_is_registered_and_gives_records():
    assert BY_SLUG["territory_status"] is TERRITORY_STATUS
    assert TERRITORY_STATUS.gives_records is True
    assert TERRITORY_STATUS.status == "harvested"
    assert "CC BY 4.0" in TERRITORY_STATUS.license


def test_csv_with_bom_is_read(tmp_path):
    """Таблицы, сохранённые с BOM, не должны терять первую колонку."""
    path = tmp_path / "bom.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{ROOT}/data/{ENTITIES}",
                         ("﻿" + "\n".join([ENTITY_HEAD, *ENTITY_ROWS])).encode("utf-8"))
        archive.writestr(f"{ROOT}/data/{STATUSES}", "\n".join([STATUS_HEAD, *STATUS_ROWS]))
        archive.writestr(f"{ROOT}/data/{STATUS_DEFS}", DEFS)
    tables = read_archive(path)
    assert "GPH_code" in tables[ENTITIES][0]
