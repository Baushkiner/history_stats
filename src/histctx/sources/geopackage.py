"""Минимальное чтение GeoPackage: полигоны и атрибуты слоя.

GeoPackage — это файл SQLite с оговорённой раскладкой таблиц, а геометрия в
нём лежит двоичным полем: короткий заголовок «GP» и следом обычный WKB.
И sqlite3, и struct есть в стандартной библиотеке, поэтому чтение обходится
без geopandas и fiona — как и чтение шейпфайла рядом (`shapefile.py`).

Разбирается то, что встречается в границах: Polygon и MultiPolygon. Точки и
линии в этих наборах не встречаются, и вместо тихого пропуска на них
поднимается ошибка — сменившуюся геометрию надо заметить.

Спецификации: OGC GeoPackage 1.3 (раздел 2.1.3, формат BLOB) и OGC Simple
Features (WKB).
"""

from __future__ import annotations

import sqlite3
import struct
from typing import Optional

WKB_POLYGON = 3
WKB_MULTIPOLYGON = 6

# Столько же знаков, сколько у шейпфайла: около 10 см на местности.
COORD_PRECISION = 6


class GeoPackageError(RuntimeError):
    """Файл не GeoPackage или содержит геометрию, которую мы не разбираем."""


def layers(path) -> list[tuple[str, str]]:
    """Слои файла: `(таблица, столбец геометрии)`."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        try:
            rows = con.execute(
                "select table_name, column_name from gpkg_geometry_columns"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise GeoPackageError(f"{path}: не читается как GeoPackage ({exc})") from exc
    if not rows:
        raise GeoPackageError(f"{path}: в файле нет слоёв с геометрией")
    return [(str(t), str(c)) for t, c in rows]


def read_features(path, table: Optional[str] = None,
                  geom_column: Optional[str] = None) -> list[dict]:
    """Слой целиком в виде списка GeoJSON-фич."""
    found = layers(path)
    if table is None:
        table, geom_column = found[0]
    elif geom_column is None:
        geom_column = dict(found).get(table)
        if geom_column is None:
            raise GeoPackageError(f"{path}: в файле нет слоя {table!r}")

    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(f'select * from "{table}"').fetchall()

    out = []
    for row in rows:
        data = dict(row)
        blob = data.pop(geom_column, None)
        # `fid` — счётчик строк самого файла, к содержанию отношения не имеет.
        data.pop("fid", None)
        geometry = parse_geometry(blob) if blob else None
        if geometry is None:
            continue
        out.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {k: v for k, v in data.items() if v is not None and v != ""},
        })
    return out


def parse_geometry(blob: bytes) -> Optional[dict]:
    """Разбирает поле геометрии GeoPackage: заголовок «GP», затем WKB."""
    if len(blob) < 8 or blob[0:2] != b"GP":
        raise GeoPackageError("поле геометрии не начинается сигнатурой GP")
    flags = blob[3]
    envelope = (flags >> 1) & 0x07
    # Размер необязательной рамки: 0 — нет, 1 — четыре числа, дальше с Z и M.
    sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope not in sizes:
        raise GeoPackageError(f"неизвестный код рамки в заголовке: {envelope}")
    offset = 8 + sizes[envelope]
    if (flags >> 4) & 0x01:      # пустая геометрия — это не ошибка
        return None
    # Младший бит флагов — порядок байт заголовка, и он здесь ни при чём:
    # рамку мы не читаем, а у WKB свой байт порядка в самом начале (см. `_wkb`).
    geometry, _ = _wkb(blob, offset)
    return geometry


def _wkb(data: bytes, offset: int) -> tuple[dict, int]:
    byte_order = data[offset]
    endian = "<" if byte_order == 1 else ">"
    kind = struct.unpack_from(f"{endian}I", data, offset + 1)[0]
    offset += 5

    if kind == WKB_POLYGON:
        rings, offset = _rings(data, offset, endian)
        return {"type": "Polygon", "coordinates": rings}, offset
    if kind == WKB_MULTIPOLYGON:
        count = struct.unpack_from(f"{endian}I", data, offset)[0]
        offset += 4
        polygons = []
        for _ in range(count):
            polygon, offset = _wkb(data, offset)
            polygons.append(polygon["coordinates"])
        return {"type": "MultiPolygon", "coordinates": polygons}, offset
    raise GeoPackageError(
        f"тип геометрии WKB {kind} не разбирается; здесь ждали полигоны"
    )


def _rings(data: bytes, offset: int, endian: str) -> tuple[list, int]:
    count = struct.unpack_from(f"{endian}I", data, offset)[0]
    offset += 4
    rings = []
    for _ in range(count):
        points = struct.unpack_from(f"{endian}I", data, offset)[0]
        offset += 4
        flat = struct.unpack_from(f"{endian}{2 * points}d", data, offset)
        offset += 16 * points
        rings.append([[round(flat[2 * i], COORD_PRECISION),
                       round(flat[2 * i + 1], COORD_PRECISION)] for i in range(points)])
    return rings, offset
