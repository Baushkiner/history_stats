"""Книга по лагерям ГУЛАГа: разбор слоя и сборка листов.

Сети и живого слоя тут нет — образец собран вручную из тех же полей, что
пишет `scripts/harvest_gulag.py --build`. Проверяется то, чего нет в общей
выгрузке: вид работ, вынутый обратно из описания, наибольшая численность
мимо нулей и соседство мест одного управления, на которое опирается счёт
управлений в сводке.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl")


def _module():
    """Скрипт лежит не в пакете — грузим по пути."""
    path = ROOT / "scripts" / "export_gulag_xlsx.py"
    spec = importlib.util.spec_from_file_location("export_gulag_xlsx", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xl = _module()


def _feature(uid, title, source_id, *, lon=37.6, lat=55.7, category="Исправительно-трудовые лагеря",
             summary="Исправительно-трудовые лагеря; вид работ — лесозаготовки; "
                     "справка и источники — на карточке проекта.",
             prisoners=None, year_from=1938, year_to=1940, confidence="ok", **props):
    body = {
        "uid": uid, "layer": "gulag_camps", "title": title, "category": category,
        "place_text": "Архангельская область, город Котлас", "region": "Архангельская область",
        "year_from": year_from, "year_to": year_to, "date_precision": "part",
        "date_approx": True, "period_raw": f"{year_from}–{year_to}", "summary": summary,
        "url": "https://gulagmap.ru/camp1", "source": "Карта ГУЛАГа", "source_id": source_id,
        "license": "права не выяснены", "confidence": confidence,
        "extra": {"prisoners": prisoners or {}, "camp_region": "Европейский Север"},
    }
    body.update(props)
    return {"type": "Feature", "id": uid,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": body}


def _layer(tmp_path, features):
    path = tmp_path / "gulag_camps.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               ensure_ascii=False), encoding="utf-8")
    return path


def test_вид_работ_вынимается_из_описания():
    assert xl._activity("Особые лагеря; вид работ — лесозаготовки; "
                        "справка и источники — на карточке проекта.") == "лесозаготовки"
    # Описание без вида работ — не повод подставить соседнюю часть фразы.
    assert xl._activity("Лагерные пункты; справка и источники — на карточке проекта.") is None
    assert xl._activity(None) is None


def test_наибольшая_численность_считается_мимо_нулей_и_пропусков():
    peak, year = xl._peak({"1947": 357, "1948": 2099, "1949": None, "1950": 0})
    assert (peak, year) == (2099, 1948)
    # Нулей и пропусков в карточке хватает: за численность они не считаются.
    assert xl._peak({"1950": 0, "1951": None}) == (None, None)
    assert xl._peak({}) == (None, None)


def test_id_управления_отделяется_от_id_места():
    assert xl._camp_id("149:448") == 149
    assert xl._camp_id(None) is None


def test_места_одного_управления_идут_подряд(tmp_path):
    """Счёт управлений в сводке опирается на соседство строк, а не на пересчёт."""
    path = _layer(tmp_path, [
        _feature("a", "Северо-Двинский ИТЛ", "10:2", year_from=1940),
        _feature("b", "Амурский ИТЛ", "20:1"),
        _feature("c", "Северо-Двинский ИТЛ", "10:1", year_from=1938),
    ])
    rows = xl.load(path)
    assert [r["title"] for r in rows] == ["Амурский ИТЛ", "Северо-Двинский ИТЛ",
                                          "Северо-Двинский ИТЛ"]
    # Внутри управления — по возрастанию лет: где стоял раньше, где потом.
    assert [r["year_from"] for r in rows[1:]] == [1938, 1940]


def test_пустой_слой_останавливает_выгрузку(tmp_path):
    with pytest.raises(SystemExit):
        xl.load(_layer(tmp_path, []))


def test_книга_собирается_с_четырьмя_листами(tmp_path):
    path = _layer(tmp_path, [
        _feature("a", "Амурский ИТЛ", "20:1", prisoners={"1938": 1200, "1939": 0}),
        _feature("b", "Северо-Двинский ИТЛ", "10:1", category=None,
                 summary="Лагерные пункты; справка и источники — на карточке проекта.",
                 confidence="unpublished_source"),
    ])
    out = xl.build(xl.load(path), tmp_path / "book.xlsx")
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Лагеря", "Численность по годам", "Сводка", "Об источнике"]

    camps = wb["Лагеря"]
    assert camps.max_row == 3
    head = [c.value for c in camps[1]]
    assert head[:4] == ["№", "Название", "Тип лагеря", "Вид работ"]
    assert camps["D2"].value == "лесозаготовки"
    assert camps["S2"].value == "да" and camps["S3"].value == "нет"
    # Полнота строки — формула, а не вписанное число: книга остаётся живой.
    assert camps["O2"].value.startswith("=COUNT('Численность по годам'!")

    stats = wb["Численность по годам"]
    assert [c.value for c in stats[1]][3:5] == ["1918", "1919"]
    year = {c.value: i for i, c in enumerate(stats[1], start=1)}
    # Ноль в отчёте и отсутствие числа — разные вещи, и в ячейках тоже.
    assert stats.cell(row=2, column=year["1938"]).value == 1200
    assert stats.cell(row=2, column=year["1939"]).value == 0
    assert stats.cell(row=2, column=year["1940"]).value is None

    total = wb["Сводка"]
    written = [row[0].value for row in total.iter_rows(min_col=1, max_col=1)]
    assert "Лагерных управлений" in written
    assert "(не указано)" in written           # тип есть не у всех, и это видно
    assert any(str(row[0].value).startswith("=")
               for row in total.iter_rows(min_col=2, max_col=2))
    assert "Права" in [row[0].value for row in
                       wb["Об источнике"].iter_rows(min_col=1, max_col=1)]


def test_подозрительное_число_помечается_а_не_выбрасывается(tmp_path):
    """Правило репозитория: спорное остаётся в данных, но с пометкой."""
    path = _layer(tmp_path, [
        _feature("a", "Бамлаг", "1:1", prisoners={"1938": 200907}),
        _feature("b", "Новый лагерь", "2:1", confidence="unpublished_source",
                 prisoners={"1939": 456789}),
        _feature("c", "Скромный лагерь", "3:1", confidence="unpublished_source",
                 prisoners={"1939": 1000}),
    ])
    rows = xl.load(path)
    ceiling = xl._published_peak(rows)
    assert ceiling == 200907
    flagged = [r["title"] for r in rows if xl._suspicious(r, ceiling)]
    assert flagged == ["Новый лагерь"]

    wb = openpyxl.load_workbook(xl.build(rows, tmp_path / "book.xlsx"))
    camps = wb["Лагеря"]
    line = {camps[f"B{i}"].value: i for i in range(2, camps.max_row + 1)}
    assert camps[f"M{line['Новый лагерь']}"].comment is not None
    assert camps[f"M{line['Новый лагерь']}"].value == 456789   # число на месте
    assert camps[f"M{line['Бамлаг']}"].comment is None
    assert camps[f"M{line['Скромный лагерь']}"].comment is None
