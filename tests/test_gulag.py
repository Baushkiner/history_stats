"""Разбор ответа «Карты ГУЛАГа».

Сети в тестах нет: образец ответа снят с https://gulagmap.ru/api/camps и
урезан до нескольких карточек. Проверяется разбор — и отдельно то, что слой
берёт факты и не тащит за собой авторскую справку музея.
"""

from pathlib import Path

import pytest

from histctx.sources.gulag import (
    GULAG_CAMPS, GulagError, camp_title, camps_to_records, check_camp_fields,
    peak_prisoners, reference_titles, split_years, statistics_years,
)

ROOT = Path(__file__).resolve().parents[1]

REFS = {
    "types": {1: "Исправительно-трудовые лагеря", 8: "Лагеря ГУПВИ"},
    "activities": {7: "Горнодобывающая промышленность"},
    "regions": {4: "Лагеря Колымы (Якутия, Магаданский край, Чукотка)"},
}

# Образец: карточка с одним местом, карточка с двумя (управление переезжало)
# и неопубликованная карточка.
CAMPS = [
    {
        "id": 149,
        "title": {"ru": "Джугджурский ИТЛ", "en": "Dzhugdzhursky ITL"},
        "subTitles": {"ru": "Джугджурлаг", "en": "Dzhugdzhurlag"},
        "description": {"ru": "## История лагеря\nДжугджурский ИТЛ действовал с 7 июня "
                              "1947 года по 29 апреля 1953 года, его управление "
                              "располагалось в Якутске."},
        "published": {"ru": True, "en": True, "de": False},
        "typeId": 1, "activityId": 7, "regionId": 4,
        "locations": [{
            "id": 448,
            "geometry": {"type": "Point", "coordinates": [129.732555, 62.028098]},
            "description": {"ru": "1947-1953 Якутская АССР (ныне – Республика Саха), "
                                  "город Якутск"},
            "statistics": [{"year": 1947, "prisonersCount": 357},
                           {"year": 1948, "prisonersCount": 2099},
                           {"year": 1950, "prisonersCount": 0},
                           {"year": 1949, "prisonersCount": None}],
        }],
    },
    {
        "id": 500,
        "title": {"ru": "Северо-Двинский ИТЛ"},
        "subTitles": {"ru": ""},
        "published": {"ru": True, "en": False, "de": False},
        "typeId": 1, "activityId": None, "regionId": None,
        "locations": [
            {"id": 900, "geometry": {"type": "Point", "coordinates": [46.7, 61.25]},
             "description": {"ru": "1938-1940 Архангельская область, город Котлас"},
             "statistics": []},
            {"id": 901, "geometry": {"type": "Point", "coordinates": [40.53, 64.54]},
             "description": {"ru": "1940-1942 Архангельская область, город Архангельск"},
             "statistics": []},
        ],
    },
    {
        "id": 777,
        "title": {"ru": "Черновицкий лагерь ГУПВИ"},
        "subTitles": {"ru": ""},
        "published": {"ru": False, "en": False, "de": False},
        "typeId": 8, "activityId": None, "regionId": None,
        "locations": [{"id": 950,
                       "geometry": {"type": "Point", "coordinates": [25.93, 48.29]},
                       "description": {"ru": "1945 Черновицкая область"},
                       "statistics": [{"year": 1945, "prisonersCount": 1200}]}],
    },
]


def test_camp_becomes_record():
    rec = camps_to_records(CAMPS, REFS)[0]
    assert (rec.lat, rec.lon) == (62.028098, 129.732555)
    assert (rec.year_from, rec.year_to) == (1947, 1953)
    assert rec.title == "Джугджурский ИТЛ (Джугджурлаг)"
    assert rec.category == "Исправительно-трудовые лагеря"
    assert rec.layer == GULAG_CAMPS.slug
    assert rec.source_id == "149:448"
    assert rec.url == "https://gulagmap.ru/camp149"
    assert rec.place_text == "Якутская АССР (ныне – Республика Саха), город Якутск"
    assert rec.mappable and rec.usable


def test_authors_note_is_not_copied():
    """Условие 3: факты берём, чужое изложение — нет.

    Справка карточки — авторский текст музея. В записи её быть не должно ни
    в `summary`, ни в `quote`: за ней запись отсылает на gulagmap.ru.
    """
    rec = camps_to_records(CAMPS, REFS)[0]
    assert rec.quote is None
    assert "действовал с 7 июня" not in (rec.summary or "")
    assert "наибольшая учтённая численность — 2\u00a0099 человек в 1948 году" in rec.summary
    assert rec.url.startswith("https://gulagmap.ru/")
    # Фотографии карточек — права архивов и музея, ссылкой их тоже не делаем.
    assert rec.image_url is None


def test_moved_administration_gives_a_record_per_place():
    """Управление, переехавшее из Котласа в Архангельск, — две точки, не одна."""
    recs = [r for r in camps_to_records(CAMPS, REFS) if r.source_id.startswith("500:")]
    assert len(recs) == 2
    assert {r.year_from for r in recs} == {1938, 1940}
    assert {r.district or r.region for r in recs} == {"Архангельская область"}
    assert all("одно из мест размещения управления" in r.summary for r in recs)


def test_unpublished_card_is_kept_but_marked():
    """Ничего не выбрасывается молча: неопубликованное помечается и остаётся."""
    rec = [r for r in camps_to_records(CAMPS, REFS) if r.source_id.startswith("777:")][0]
    assert rec.confidence == "unpublished_source"
    assert all(r.confidence == "ok"
               for r in camps_to_records(CAMPS, REFS) if not r.source_id.startswith("777:"))
    assert len(camps_to_records(CAMPS, REFS, include_unpublished=False)) == 3


def test_years_are_read_from_the_head_of_the_place():
    assert split_years("1947-1953 Якутская АССР, город Якутск") == (
        1947, 1953, "Якутская АССР, город Якутск")
    assert split_years("1945 Черновицкая область") == (1945, 1945, "Черновицкая область")
    assert split_years("1930–1932 гг. Коми АО")[:2] == (1930, 1932)
    assert split_years("1953-1947 Якутск")[:2] == (1947, 1953)
    assert split_years("Место без датировки") == (None, None, "Место без датировки")


def test_years_fall_back_to_the_years_of_headcount():
    """Датировки в описании нет, но численность по годам есть — берём по ней."""
    camp = {"id": 5, "title": {"ru": "Лагерь без дат"}, "subTitles": {"ru": ""},
            "published": {"ru": True}, "typeId": 1,
            "locations": [{"id": 1, "geometry": {"type": "Point", "coordinates": [60.0, 55.0]},
                           "description": {"ru": "Свердловская область"},
                           "statistics": [{"year": 1943, "prisonersCount": 10},
                                          {"year": 1946, "prisonersCount": 20}]}]}
    rec = camps_to_records([camp], REFS)[0]
    assert (rec.year_from, rec.year_to) == (1943, 1946)
    assert rec.date_approx


def test_zero_headcount_is_not_a_peak():
    """Ноль в карточке значит «сведений нет», а не «в лагере никого не было»."""
    assert peak_prisoners(CAMPS[0]["locations"][0]) == (2099, 1948)
    assert peak_prisoners({"statistics": [{"year": 1950, "prisonersCount": 0}]}) == (None, None)
    assert statistics_years(CAMPS[0]["locations"][0]) == [1947, 1948, 1949, 1950]


def test_place_without_point_or_year_is_skipped():
    camp = {"id": 7, "title": {"ru": "Лагерь"}, "subTitles": {"ru": ""},
            "published": {"ru": True}, "typeId": 1,
            "locations": [{"id": 1, "geometry": None,
                           "description": {"ru": "1930-1931 Коми АО"}, "statistics": []},
                          {"id": 2, "geometry": {"type": "Point", "coordinates": [50.0, 60.0]},
                           "description": {"ru": "Место без датировки"}, "statistics": []}]}
    assert camps_to_records([camp], REFS) == []


def test_point_outside_the_country_is_skipped():
    camp = {"id": 8, "title": {"ru": "Лагерь"}, "subTitles": {"ru": ""},
            "published": {"ru": True}, "typeId": 1,
            "locations": [{"id": 1, "geometry": {"type": "Point", "coordinates": [-58.4, -34.6]},
                           "description": {"ru": "1930-1931 Буэнос-Айрес"}, "statistics": []}]}
    assert camps_to_records([camp], REFS) == []
    assert len(camps_to_records([camp], REFS, require_bbox=False)) == 1


def test_title_keeps_the_short_name_once():
    assert camp_title(CAMPS[0]) == "Джугджурский ИТЛ (Джугджурлаг)"
    assert camp_title({"title": {"ru": "Севлаг"}, "subTitles": {"ru": "севлаг"}}) == "Севлаг"
    assert camp_title({"title": {"ru": ""}, "subTitles": {"ru": "Севлаг"}}) == "Севлаг"


def test_reference_is_read_by_id():
    assert reference_titles([{"id": 1, "title": {"ru": "Особые лагеря"}},
                             {"id": 2, "title": {"ru": ""}}]) == {1: "Особые лагеря"}


def test_broken_answer_stops_the_harvest():
    """Переименуют поля — сбор должен упасть с внятным сообщением, а не выдать пусто."""
    with pytest.raises(GulagError):
        check_camp_fields([])
    with pytest.raises(GulagError, match="locations"):
        check_camp_fields([{"id": 1, "title": {"ru": "Лагерь"}}])


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    assert GULAG_CAMPS.slug in BY_SLUG
    assert BY_SLUG[GULAG_CAMPS.slug].status == "harvested"
