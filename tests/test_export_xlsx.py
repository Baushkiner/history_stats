"""Выгрузка собранного слоя в таблицу: `scripts/export_xlsx.py`.

Проверяется то, ради чего команда и написана: слой берётся с диска, а не
собирается заново, и в таблице оказывается ровно то, что лежало в выгрузке.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from export_xlsx import available_layers, read_layer  # noqa: E402
from histctx.io_formats import write_xlsx  # noqa: E402
from histctx.schema import COLUMNS_RU  # noqa: E402


def build_out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    geo = out / "geojson" / "disasters.geojson"
    geo.parent.mkdir(parents=True, exist_ok=True)
    geo.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "disasters:1",
            "geometry": {"type": "Point", "coordinates": [39.2, 51.67]},
            "properties": {"uid": "disasters:1", "layer": "disasters",
                           "layer_title": "Пожары, наводнения, катастрофы",
                           "title": "Пожар в Воронеже", "category": "городской пожар",
                           "year_from": 1773, "year_to": 1773, "date_approx": True,
                           "license": "CC0 (Викиданные)"},
        }],
    }, ensure_ascii=False), encoding="utf-8")

    # Событие без точки: в GeoJSON его нет по определению, и без второго
    # прохода по jsonl слой ушёл бы в таблицу неполным.
    jsonl = out / "jsonl" / "disasters.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text("\n".join([
        # Тот же пожар, что и в geojson: оба файла пишет один сбор, и запись
        # в них одна и та же — в таблицу она должна попасть один раз.
        json.dumps({"uid": "disasters:1", "layer": "disasters", "title": "Пожар в Воронеже",
                    "category": "городской пожар", "lat": 51.67, "lon": 39.2,
                    "year_from": 1773, "year_to": 1773, "date_approx": True},
                   ensure_ascii=False),
        json.dumps({"uid": "disasters:2", "layer": "disasters", "scope": "region",
                    "title": "Наводнение", "regions": "Самарская губерния; Казанская губерния",
                    "year_from": 1908, "year_to": 1908}, ensure_ascii=False),
    ]), encoding="utf-8")
    return out


def test_layer_is_read_from_both_files_without_duplicates(tmp_path):
    records, used = read_layer(build_out(tmp_path), "disasters")
    assert [r.uid for r in records] == ["disasters:1", "disasters:2"]
    # Запись с точкой пришла из jsonl первой; повтор из geojson отсеян по uid.
    assert len(used) == 1 and used[0].startswith("jsonl/disasters.jsonl")
    assert records[1].regions == ["Самарская губерния", "Казанская губерния"]


def test_foreign_layers_do_not_leak_into_the_sheet(tmp_path):
    out = build_out(tmp_path)
    path = out / "jsonl" / "uprisings.jsonl"
    path.write_text(json.dumps({"uid": "uprisings:1", "layer": "uprisings",
                                "title": "Чумной бунт"}, ensure_ascii=False), encoding="utf-8")
    records, _ = read_layer(out, "disasters")
    assert all(r.layer == "disasters" for r in records)
    assert "uprisings" in available_layers(out)


def test_written_table_says_the_same_as_the_layer(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    out = build_out(tmp_path)
    records, _ = read_layer(out, "disasters")
    # Слой читается с диска, а не собирается заново: сети команде не нужно.
    path = out / "xlsx" / "disasters.xlsx"
    assert write_xlsx(records, path, sheet_name="Пожары, наводнения, катастрофы") == 2

    ws = openpyxl.load_workbook(path).active
    header = [c.value for c in ws[1]]
    assert header[:5] == [COLUMNS_RU[c] for c in ("uid", "layer", "layer_title", "group", "title")]
    row = dict(zip(header, [c.value for c in ws[2]]))
    assert row["Название"] == "Пожар в Воронеже"
    # Булево в таблице — словом, перечень губерний — строкой «А; Б».
    assert row["Дата приблизительна"] == "да"
    regions = dict(zip(header, [c.value for c in ws[3]]))["Затронутые губернии"]
    assert regions == "Самарская губерния; Казанская губерния"
