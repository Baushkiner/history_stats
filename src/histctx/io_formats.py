"""Выгрузка слоёв в GeoJSON и XLSX."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from .schema import COLUMNS, COLUMNS_RU, ContextRecord


# Свойства, одинаковые у всех записей слоя: название слоя, источник, права.
# У слоя в тысячу точек они занимают место, у слоя в семнадцать тысяч —
# больше половины файла.
HOISTABLE = ("layer", "layer_title", "group", "source", "license", "confidence",
             "date_precision", "date_approx")


def write_geojson(records: Iterable[ContextRecord], path: Path, *, layer_title: str = "",
                  hoist_shared: bool = False) -> int:
    """Пишет FeatureCollection. Записи без координат пропускаются.

    `hoist_shared` выносит свойства, одинаковые у всех записей, на уровень
    коллекции — в поле `layer`. Для больших слоёв это разница в разы, но
    читателю файла нужно знать про это поле, поэтому по умолчанию выключено:
    молча менять формат уже отданных слоёв нельзя.
    """
    feats = [r.to_feature() for r in records if r.has_point]
    shared = _shared_properties(feats) if hoist_shared else {}
    for feat in feats:
        for key in shared:
            feat["properties"].pop(key, None)

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "name": layer_title or path.stem,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3/CRS84"}},
        "features": feats,
    }
    if shared:
        # Читается как «свойства слоя»: то же самое, что было бы у каждой
        # точки, вынесенное один раз.
        payload["layer"] = shared
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return len(feats)


def _shared_properties(feats: Sequence[dict]) -> dict:
    """Свойства из HOISTABLE, значение которых одинаково во всех записях."""
    if not feats:
        return {}
    first = feats[0]["properties"]
    out = {}
    for key in HOISTABLE:
        if key not in first:
            continue
        value = first[key]
        if all(f["properties"].get(key, _MISSING) == value for f in feats):
            out[key] = value
    return out


_MISSING = object()


def write_records_json(records: Iterable[ContextRecord], path: Path, *, title: str = "") -> int:
    """Пишет записи без геометрии одним JSON-массивом.

    Нужен для событий, у которых нет точки: голод по губерниям, ревизия,
    воинская повинность. В GeoJSON их не положить, а карте они нужны —
    лентой времени рядом с фактом.
    """
    rows = []
    for rec in records:
        # Пустые поля опускаются, как и в GeoJSON: у события без точки их
        # заведомо много, и файл читается вдвое легче.
        row = {k: v for k, v in rec.to_row().items() if v is not None and v != ""}
        if rec.regions:
            row["regions"] = list(rec.regions)
        if rec.extra:
            row["extra"] = rec.extra
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"name": title or path.stem, "count": len(rows), "records": rows}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return len(rows)


def write_xlsx(records: Sequence[ContextRecord], path: Path, *, sheet_name: str = "Данные",
               russian_headers: bool = True) -> int:
    """Пишет XLSX с русскими заголовками, как в текущих выгрузках проекта."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    # Через ту же очистку, что и многолистовая выгрузка: openpyxl запрещает
    # в имени листа `[]:*?/\`, и на двоеточии сбор падал уже после того, как
    # записал GeoJSON, — слой собран, а команда вернула ошибку. Названия
    # слоёв пишут люди, и двоеточие в них дело обычное.
    ws.title = _safe_sheet(sheet_name, wb) if sheet_name else "Данные"

    headers = [COLUMNS_RU[c] if russian_headers else c for c in COLUMNS]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"

    for rec in records:
        row = rec.to_row()
        ws.append([_cell(row.get(c)) for c in COLUMNS])

    widths = {"title": 42, "summary": 70, "quote": 70, "url": 45, "place_text": 34,
              "period_raw": 26, "work": 34, "actor": 26, "layer_title": 26, "uid": 24}
    for i, col in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(col, 15)

    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{ws.max_row}"
    wb.save(path)
    return ws.max_row - 1


def write_xlsx_multi(sheets: dict[str, Sequence[ContextRecord]], path: Path,
                     russian_headers: bool = True) -> dict[str, int]:
    """Пишет несколько слоёв в один файл — по вкладке на слой."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    counts: dict[str, int] = {}
    headers = [COLUMNS_RU[c] if russian_headers else c for c in COLUMNS]

    for name, records in sheets.items():
        ws = wb.create_sheet(title=_safe_sheet(name, wb))
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        for rec in records:
            row = rec.to_row()
            ws.append([_cell(row.get(c)) for c in COLUMNS])
        widths = {"title": 42, "summary": 70, "quote": 70, "url": 45, "place_text": 34,
                  "period_raw": 26, "work": 34, "actor": 26, "layer_title": 26, "uid": 24}
        for i, col in enumerate(COLUMNS, start=1):
            ws.column_dimensions[get_column_letter(i)].width = widths.get(col, 15)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{ws.max_row}"
        counts[name] = ws.max_row - 1

    wb.save(path)
    return counts


def write_jsonl(records: Iterable[ContextRecord], path: Path) -> int:
    """Построчный JSON — удобен для загрузки в базу и для диффов в git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            row = rec.to_row()
            if rec.extra:
                row["extra"] = rec.extra
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _cell(value):
    if isinstance(value, bool):
        return "да" if value else "нет"
    return value


def _safe_sheet(name: str, wb) -> str:
    base = "".join(ch for ch in str(name) if ch not in "[]:*?/\\")[:31] or "Слой"
    title, i = base, 2
    while title in wb.sheetnames:
        suffix = f"_{i}"
        title = base[: 31 - len(suffix)] + suffix
        i += 1
    return title
