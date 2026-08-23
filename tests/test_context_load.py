"""Сборка индекса контекста из выгрузки: `scripts/context.py`.

Проверяется чтение того, что реально лежит в `data/out`: слои с вынесенными
на уровень коллекции свойствами, территориальные записи без координат и
чужие файлы, которые в каталог слоёв попасть не должны, но попадают.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from context import load_records  # noqa: E402


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    # Слой с вынесенными свойствами: у фич нет ни `layer`, ни лицензии.
    write(out / "geojson" / "settlements.geojson", {
        "type": "FeatureCollection",
        "layer": {"layer": "settlements", "layer_title": "Населённые места",
                  "group": "admin", "license": "CC BY 4.0"},
        "features": [{"type": "Feature", "id": "settlements:1",
                      "geometry": {"type": "Point", "coordinates": [38.37, 59.85]},
                      "properties": {"uid": "settlements:1", "title": "Кириллов"}}],
    })
    # Обычный слой: всё лежит в свойствах фичи.
    write(out / "geojson" / "gulag_camps.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "id": "gulag_camps:1",
                      "geometry": {"type": "Point", "coordinates": [40.53, 64.54]},
                      "properties": {"uid": "gulag_camps:1", "layer": "gulag_camps",
                                     "title": "Северо-Двинский ИТЛ",
                                     "year_from": 1940, "year_to": 1942}}],
    })
    return out


def test_layer_with_hoisted_properties_is_read(tmp_path):
    """Без обратной склейки такой слой не читается вовсе — на этом падал сбор."""
    records = load_records(build_out(tmp_path))
    settlement = [r for r in records if r.uid == "settlements:1"][0]
    assert settlement.layer == "settlements"
    assert settlement.layer_title == "Населённые места"
    assert settlement.license == "CC BY 4.0"


def test_boundaries_do_not_pretend_to_be_records(tmp_path):
    """Полигон границ в каталоге слоёв не должен ронять подбор."""
    out = build_out(tmp_path)
    write(out / "geojson" / "districts_1897.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "geometry": {"type": "Polygon",
                                   "coordinates": [[[26.8, 64.5], [26.9, 64.6],
                                                    [27.0, 64.5], [26.8, 64.5]]]},
                      "properties": {"Name_RU": "Кемский"}}],
    })
    records = load_records(out)
    assert len(records) == 2
    assert all(r.has_point for r in records)


def test_records_without_a_point_are_picked_up_from_jsonl(tmp_path):
    """Губернские итоги переписи в GeoJSON не попадают: у них нет координаты."""
    out = build_out(tmp_path)
    path = out / "jsonl" / "admin_1897_gis.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        json.dumps({"uid": "admin:1", "layer": "admin_1897_gis", "scope": "region",
                    "title": "Новгородская губерния: итоги переписи 1897 года",
                    "regions": "Новгородская губерния", "year_from": 1897,
                    "year_to": 1897}, ensure_ascii=False),
        # Повтор точечной записи из GeoJSON — он не должен удвоиться.
        json.dumps({"uid": "gulag_camps:1", "layer": "gulag_camps",
                    "title": "Северо-Двинский ИТЛ", "lat": 64.54, "lon": 40.53,
                    "year_from": 1940, "year_to": 1942}, ensure_ascii=False),
    ]), encoding="utf-8")

    records = load_records(out)
    assert len(records) == 3
    census = [r for r in records if r.uid == "admin:1"][0]
    assert census.is_territorial and not census.has_point
    assert census.regions == ["Новгородская губерния"]
    assert census.usable


def test_context_jsonl_wins_when_it_exists(tmp_path):
    out = build_out(tmp_path)
    (out / "context.jsonl").write_text(
        json.dumps({"uid": "one", "layer": "state_events", "title": "X ревизия",
                    "scope": "state", "year_from": 1857, "year_to": 1859},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    records = load_records(out)
    assert [r.uid for r in records] == ["one"]
