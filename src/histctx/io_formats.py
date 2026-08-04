"""Выгрузка слоёв в GeoJSON и XLSX."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from .schema import COLUMNS, COLUMNS_RU, ContextRecord


def write_geojson(records: Iterable[ContextRecord], path: Path, *, layer_title: str = "") -> int:
    """Пишет FeatureCollection. Записи без координат пропускаются."""
    feats = [r.to_feature() for r in records if r.has_point]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "name": layer_title or path.stem,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3/CRS84"}},
        "features": feats,
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return len(feats)


def write_xlsx(records: Sequence[ContextRecord], path: Path, *, sheet_name: str = "Данные",
               russian_headers: bool = True) -> int:
    """Пишет XLSX с русскими заголовками, как в текущих выгрузках проекта."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31] or "Данные"

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
