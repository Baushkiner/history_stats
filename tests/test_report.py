"""Отчёт о качестве: `scripts/build_core.py`.

Отчёт описывает всю выгрузку, а не пять слоёв из `data/raw`. Значит, он
читает `data/out` — и проверять надо ровно то, на чём такое чтение ломается:
одна и та же запись, лежащая сразу в двух форматах, и разные записи, у
которых совпал `uid`.
"""

import json
from pathlib import Path

from build_core import add_harvested, build_report, _registry_gaps
from histctx.io_formats import (
    read_layers, read_records_json, write_geojson, write_jsonl, write_records_json,
)
from histctx.schema import ContextRecord

ROOT = Path(__file__).resolve().parents[1]


def record(**kwargs) -> ContextRecord:
    base = dict(layer="churches", layer_title="Храмы и церкви", group="faith",
                title="Никольская церковь", lat=59.8571429, lon=38.3714286,
                year_from=1802, year_to=1802, date_precision="year",
                source="Викиданные", license="CC0 (Викиданные)")
    base.update(kwargs)
    return ContextRecord(**base)


def test_the_same_record_in_two_formats_is_counted_once(tmp_path):
    """Слой лежит и в `geojson/`, и в `jsonl/` — это один слой, а не два.

    В GeoJSON координата округлена до шести знаков, в JSONL лежит как есть.
    Без приведения к одному виду запись двоилась, и слой в отчёте вырастал
    вдвое.
    """
    rec = record()
    write_geojson([rec], tmp_path / "geojson" / "churches.geojson")
    write_jsonl([rec], tmp_path / "jsonl" / "churches.jsonl")

    layers, specs = {}, {}
    assert add_harvested(layers, specs, tmp_path, skip=set()) == 1
    assert len(layers["churches"]) == 1


def test_records_sharing_a_uid_both_survive(tmp_path):
    """Совпал идентификатор, а записи разные — остаются обе.

    У пяти материалов бюро Тенишева `uid` считается по одинаковым полям при
    разном описании. Схлопнуть их молча — потерять свидетельство.
    """
    first = record(layer="tenishev", summary="о свадебном обряде")
    second = record(layer="tenishev", summary="о престольном празднике")
    assert first.uid == second.uid

    write_jsonl([first, second], tmp_path / "jsonl" / "tenishev.jsonl")
    layers, specs = {}, {}
    assert add_harvested(layers, specs, tmp_path, skip=set()) == 2

    report = build_report(layers, specs)
    assert "## Совпавшие идентификаторы" in report


def test_skip_leaves_out_layers_already_built(tmp_path):
    """Свои слои пересобраны из data/raw и второй раз читаться не должны."""
    rec = record()
    write_geojson([rec], tmp_path / "geojson" / "churches.geojson")
    layers, specs = {}, {}
    assert add_harvested(layers, specs, tmp_path, skip={rec.uid}) == 0
    assert layers == {}


def test_records_json_is_read_and_foreign_json_is_not(tmp_path):
    """События без точки лежат в `*.json` рядом; указатель написаний — тоже."""
    rec = record(layer="harvest_prices", layer_title="Урожайность и хлебные цены",
                 group="economy", lat=None, lon=None, scope="region",
                 regions=["Вятская губерния"], title="Сбор ржи, 1891")
    write_records_json([rec], tmp_path / "harvest_prices.json", title="Цены")
    (tmp_path / "name_variants.json").write_text(
        json.dumps({"name": "Указатель", "places": 2, "items": {"1": {"title": "Тарту"}}},
                   ensure_ascii=False), encoding="utf-8")

    assert len(read_records_json(tmp_path / "name_variants.json")) == 0
    records = read_layers(tmp_path)
    assert [r.layer for r in records] == ["harvest_prices"]
    assert records[0].regions == ["Вятская губерния"]


def test_dedupe_off_keeps_everything(tmp_path):
    rec = record()
    write_geojson([rec], tmp_path / "geojson" / "churches.geojson")
    write_jsonl([rec], tmp_path / "jsonl" / "churches.jsonl")
    assert len(read_layers(tmp_path, dedupe=True)) == 1
    assert len(read_layers(tmp_path, dedupe=False)) == 2


def test_boundary_layers_are_not_reported_as_missing():
    """Границы записей схемы не дают — несобранным слоем их считать нельзя."""
    gaps = {spec.slug for spec in _registry_gaps({})}
    assert "admin_boundaries_1897" not in gaps
    assert "state_borders" not in gaps
    assert "labour_conflicts" in gaps
