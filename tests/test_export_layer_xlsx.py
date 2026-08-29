"""Выгрузка слоя единой схемы в XLSX.

Живого слоя тут нет — образец собран из тех же полей, что пишут сборщики.
Проверяется то, ради чего выгрузка и заведена: постоянные поля не повторяются
в каждой строке, а качество слоя меряется по данным — записи без датировки,
вне рамки проекта и позже её верхней границы считаются и помечаются, а не
выбрасываются.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl")

from histctx.xlsx_style import FONT  # noqa: E402


def _module():
    path = ROOT / "scripts" / "export_layer_xlsx.py"
    spec = importlib.util.spec_from_file_location("export_layer_xlsx", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xl = _module()


def _feature(uid, title, *, lon=37.6, lat=55.7, category="тюрьма",
             year_from=1937, year_to=1938, region="Москва", **props):
    body = {
        "uid": uid, "layer": "repressions", "layer_title": "Места репрессий",
        "group": "hardship", "title": title, "category": category,
        "place_text": "Москва", "region": region,
        "year_from": year_from, "year_to": year_to,
        "date_precision": "part", "date_approx": False,
        "period_raw": f"{year_from}–{year_to}",
        "url": "https://example.org/x", "source": "Викиданные",
        "source_id": uid, "license": "CC0 (Викиданные)", "confidence": "ok",
    }
    body.update(props)
    return {"type": "Feature", "id": uid,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": body}


def _layer(tmp_path, features, name="Места репрессий"):
    path = tmp_path / "repressions.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "name": name,
                                "features": features}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def test_записи_помечаются_рамкой_периодом_и_датировкой(tmp_path):
    rows, header = xl.load("repressions", _layer(tmp_path, [
        _feature("a", "Бутырка"),
        _feature("b", "Современная колония", year_from=2015, year_to=2015),
        _feature("c", "Без даты", year_from=None, year_to=None),
        _feature("d", "Париж", lon=2.35, lat=48.85),
    ]))
    by = {r["title"]: r for r in rows}
    assert by["Бутырка"]["in_frame"] == "да"
    assert by["Бутырка"]["in_period"] == "да"
    assert by["Современная колония"]["in_period"] == "нет"   # позже 1960
    assert by["Без даты"]["has_date"] == "нет"
    assert by["Без даты"]["in_period"] == "нет даты"
    assert by["Париж"]["in_frame"] == "нет"                  # вне BBOX_RU
    assert header["name"] == "Места репрессий"


def test_постоянные_поля_уходят_из_таблицы_в_описание(tmp_path):
    rows, _ = xl.load("repressions", _layer(tmp_path, [
        _feature("a", "Первая"), _feature("b", "Вторая"),
    ]))
    columns, constant = xl.split_columns(rows)
    # У всего слоя один источник и одна лицензия — незачем повторять их построчно.
    assert "Источник" in constant and "Лицензия" in constant
    assert "source" not in columns and "license" not in columns
    # А то, что различается, остаётся колонкой.
    assert "title" in columns and "uid" in columns
    # Пустых у всего слоя полей в таблице нет.
    assert "quote" not in columns and "actor" not in columns


def test_оговорки_считаются_по_данным(tmp_path):
    rows, _ = xl.load("repressions", _layer(tmp_path, [
        _feature("a", "С датой"),
        _feature("b", "Без даты", year_from=None, year_to=None),
        _feature("c", "Без губернии", region=None),
        _feature("d", "Париж", lon=2.35, lat=48.85),
    ]))
    columns, _ = xl.split_columns(rows)
    measured = dict(xl.measure(rows, columns))
    assert measured["Записей в слое"] == "4"
    assert measured["Записей без датировки"].startswith("1 из 4")
    assert measured["Записей вне рамки проекта"].startswith("1 из 4")
    assert measured["Записей без губернии или области"].startswith("1 из 4")


def test_классы_отбора_читаются_из_запроса():
    """Читателю важно, по какому признаку запись попала в слой."""
    classes = xl.query_classes("repressions")
    assert any("Q40357" in c for c in classes)          # тюрьма
    assert any("Q66307429" in c for c in classes)       # место массового убийства
    assert xl.query_classes("такого-слоя-нет") == []


def test_книга_собирается_с_тремя_листами(tmp_path):
    rows, header = xl.load("repressions", _layer(tmp_path, [
        _feature("a", "Бутырка"),
        _feature("b", "Париж", lon=2.35, lat=48.85, category="братская могила"),
        _feature("c", "Без даты", year_from=None, year_to=None),
    ]))
    columns, constant = xl.split_columns(rows)
    spec = next(s for s in xl.ALL_LAYERS if s.slug == "repressions")
    out = xl.build(rows, columns, constant, spec, header, tmp_path / "book.xlsx")

    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Записи", "Сводка", "Об источнике"]

    zs = wb["Записи"]
    assert zs.max_row == 4                      # шапка и три записи
    head = [c.value for c in zs[1]]
    assert head[0] == "№"
    assert {"В рамке проекта", "Датировка есть", "В периоде проекта"} <= set(head)
    assert "Источник" not in head               # постоянное поле в таблицу не идёт

    total = wb["Сводка"]
    labels = [r[0].value for r in total.iter_rows(min_col=1, max_col=1)]
    assert "Записей" in labels and "Вне рамки проекта" in labels
    assert any(str(r[0].value).startswith("=")
               for r in total.iter_rows(min_col=2, max_col=2))

    about = [r[0].value for r in wb["Об источнике"].iter_rows(min_col=1, max_col=1)]
    assert "Отобрано по классам источника" in about
    # Оговорка выводится только там, где она по делу: в этом слое без даты одна.
    assert "Записей без датировки" in about
    assert "Записей вне рамки проекта" in about


def test_шрифт_по_умолчанию_доходит_до_ячеек(tmp_path):
    """Стиль книги ставится ради скорости — проверяем, что он не теряется.

    Ячейка без своего оформления ссылается на `cellXfs[0]`, а тот жёстко
    указывает `fontId="0"`. Правки одного лишь именованного стиля «Normal»
    ячейкам не видны: в файле оставался Calibri, хотя openpyxl показывал Arial.
    """
    rows, header = xl.load("repressions", _layer(tmp_path, [_feature("a", "Бутырка")]))
    columns, constant = xl.split_columns(rows)
    out = xl.build(rows, columns, constant, None, header, tmp_path / "book.xlsx")

    ws = openpyxl.load_workbook(out)["Записи"]
    assert ws["B2"].font.name == FONT
    assert ws["B2"].font.size == 10

    # Читаем сам файл, а не обёртку: нулевой шрифт списка должен быть наш.
    import re
    import zipfile
    styles = zipfile.ZipFile(out).read("xl/styles.xml").decode("utf-8")
    fonts = re.search(r"<fonts.*?</fonts>", styles, re.S).group(0)
    first = re.findall(r"<font>.*?</font>", fonts, re.S)[0]
    assert FONT in first and "Calibri" not in first
