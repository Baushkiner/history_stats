"""Каталог слоёв как код.

Список источников открыт — любой релевантный можно добавить, — но условия
приёмки из `docs/CATALOG.md` проверяются здесь, а не остаются пожеланием
в тексте. Слой без записанного статуса прав или без ссылки на источник —
это не «почти готово», это незаконченная работа. Сами по себе невыясненные
права слою не мешают: по условию 3 они ограничивают глубину выгрузки, а не
приём источника, — но записаны должны быть.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.registry import (  # noqa: E402
    ALL_LAYERS, BY_SLUG, CURATED, EXTERNAL, HARVESTED, PLANNED,
)
from histctx.schema import GROUPS  # noqa: E402

RE_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")

# Формулировки, которые ничего не сообщают о правах. «Права не выяснены,
# берём факты и ссылку» — законный статус: он говорит, как со слоем
# обращаться. «Уточняется» не говорит ничего и отложено на потом.
EMPTY_ANSWERS = {"уточняется", "неизвестно", "?", "-", "нет данных"}


def test_slugs_are_unique_and_machine_readable():
    assert len(BY_SLUG) == len(ALL_LAYERS), "повторяющийся slug"
    for spec in ALL_LAYERS:
        assert RE_SLUG.match(spec.slug), spec.slug


def test_every_layer_has_a_title_and_a_group():
    for spec in ALL_LAYERS:
        assert spec.title, spec.slug
        assert spec.group in GROUPS, f"{spec.slug}: неизвестная группа {spec.group!r}"


def test_every_layer_says_what_it_explains():
    """Слой без описания невозможно оценить: он либо нужен, либо нет."""
    for spec in ALL_LAYERS:
        assert spec.description and len(spec.description) > 40, spec.slug


def test_rights_are_stated_in_words():
    """Условие приёмки: статус прав записан словами, а не отложен.

    Проверяется, что поле сообщает, как обращаться со слоем, — «нужна
    договорённость» и «права не выяснены» проходят наравне с названием
    лицензии. Не проходит только пустая отговорка.
    """
    for spec in ALL_LAYERS:
        assert spec.license, spec.slug
        assert spec.license.strip().lower() not in EMPTY_ANSWERS, spec.slug


def test_external_layers_point_at_their_source():
    """Условие приёмки: до источника можно дойти."""
    for spec in EXTERNAL:
        assert spec.source, spec.slug
        assert spec.url or len(spec.source) > 20, (
            f"{spec.slug}: нет ни ссылки, ни внятного названия источника"
        )


def test_statuses_are_from_a_closed_list():
    for spec in ALL_LAYERS:
        assert spec.status in {"planned", "harvested", "curated"}, spec.slug
    assert all(s.status == "curated" for s in CURATED)
    assert all(s.status == "harvested" for s in HARVESTED)


def test_catalog_is_not_only_wikidata():
    """Страховка от возврата к каталогу из одних Викиданных.

    Доля Викиданных здесь намеренно не ограничивается: подгонять её, добавляя
    слои ради счётчика, — ровно та ошибка, от которой тест должен защищать.
    Проверяется другое: что источники разных видов есть и что они закрывают
    разные группы, а не одну.
    """
    assert len(EXTERNAL) >= 5
    other_groups = {s.group for s in ALL_LAYERS if "икиданны" not in s.source}
    assert len(other_groups) >= 3, other_groups


# Слои, объявленные в каталоге, но пока не собираемые ничем. Список ведётся
# явно и должен сокращаться, а не пополняться незаметно: объявить слой и не
# дать способа его собрать — это обещание, а не работа.
AWAITING_COLLECTOR = {
    # Викиданные: слой описан, запрос ещё не написан.
    "renamed_places", "famines", "repressions", "estates",
    # Внешние проекты: нужен разбор формата, а для части — договорённость.
    "photos_russiainphoto", "gulag_camps", "admin_1897_gis", "state_borders",
    "weather_chronicles", "drought_atlas", "harvest_prices",
}


def test_planned_layers_are_covered_by_queries_or_a_collector():
    """У запланированного слоя есть либо запрос, либо сборщик, либо отметка."""
    queries = {p.stem for p in (ROOT / "queries").glob("*.rq")}
    collectors = {"photos_pastvu", "weather_stations", "weather_regions"}
    known = queries | collectors | AWAITING_COLLECTOR
    for spec in PLANNED + EXTERNAL:
        assert spec.slug in known, (
            f"{spec.slug}: нет ни запроса в queries/, ни сборщика, ни отметки об ожидании"
        )


def test_awaiting_list_does_not_outlive_its_layers():
    """Слой собрали — строку из списка ожидания надо убрать."""
    stale = AWAITING_COLLECTOR - {s.slug for s in ALL_LAYERS}
    assert not stale, f"в списке ожидания слои, которых нет в каталоге: {stale}"
