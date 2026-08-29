"""Минимальное чтение шейпфайла: полигоны и таблица атрибутов.

Зачем свой разбор. Границы приходят в формате ESRI Shapefile, а разбирать его
умеют geopandas, fiona и pyshp — три зависимости с компилируемыми колёсами
ради одной операции «прочитать полигоны и подписи к ним». Проект держится на
стандартной библиотеке (см. `pyproject.toml`: pandas и openpyxl — и всё),
поэтому здесь ровно то, что нужно, и ничего больше.

Что поддерживается: типы Polygon (5), PolygonZ (15), PolygonM (25) и Point
(1, 11, 21). Всё остальное — линии, мультиточки — вызывает ошибку, а не
молчаливый пропуск: если источник сменит геометрию, это надо заметить.

Формат описан в «ESRI Shapefile Technical Description» (1998). Две ловушки,
на которых разбор обычно ломается:

* заголовки файла и записей — с обратным порядком байт, а содержимое
  записей — с прямым;
* направление обхода кольца — это не мелочь: по часовой стрелке идёт внешняя
  граница, против — дырка внутри неё. GeoJSON различает их так же, поэтому
  кольца группируются по направлению, а не сваливаются в один список.
"""

from __future__ import annotations

import struct
from typing import Any, Optional

SHP_MAGIC = 9994

NULL_SHAPE = 0
POINT_TYPES = (1, 11, 21)
POLYGON_TYPES = (5, 15, 25)

# Координаты пишутся с точностью 6 знаков — это около 10 см на местности
# и вдвое меньший файл, чем полная двойная точность.
COORD_PRECISION = 6


class ShapefileError(RuntimeError):
    """Файл не шейпфайл или содержит геометрию, которую мы не разбираем."""


def read_shapes(data: bytes) -> list[Optional[dict]]:
    """Геометрии из .shp в виде GeoJSON-объектов; пустая запись — None."""
    if len(data) < 100:
        raise ShapefileError("файл короче заголовка шейпфайла (100 байт)")
    magic = struct.unpack(">i", data[0:4])[0]
    if magic != SHP_MAGIC:
        raise ShapefileError(f"не шейпфайл: сигнатура {magic}, ожидалась {SHP_MAGIC}")

    shapes: list[Optional[dict]] = []
    offset, end = 100, len(data)
    while offset + 8 <= end:
        _, content_words = struct.unpack(">ii", data[offset:offset + 8])
        offset += 8
        content = data[offset:offset + content_words * 2]
        offset += content_words * 2
        shapes.append(_shape(content))
    return shapes


def _shape(content: bytes) -> Optional[dict]:
    if len(content) < 4:
        return None
    kind = struct.unpack("<i", content[0:4])[0]
    if kind == NULL_SHAPE:
        return None
    if kind in POINT_TYPES:
        x, y = struct.unpack("<dd", content[4:20])
        return {"type": "Point", "coordinates": [_r(x), _r(y)]}
    if kind not in POLYGON_TYPES:
        raise ShapefileError(
            f"тип геометрии {kind} не разбирается; здесь ждали полигоны или точки"
        )
    return _polygon(content)


def _polygon(content: bytes) -> Optional[dict]:
    num_parts, num_points = struct.unpack("<ii", content[36:44])
    if num_parts <= 0 or num_points <= 0:
        return None
    parts = struct.unpack(f"<{num_parts}i", content[44:44 + 4 * num_parts])
    start = 44 + 4 * num_parts
    flat = struct.unpack(f"<{2 * num_points}d", content[start:start + 16 * num_points])

    rings = []
    bounds = list(parts) + [num_points]
    for i in range(num_parts):
        first, last = bounds[i], bounds[i + 1]
        ring = [[_r(flat[2 * j]), _r(flat[2 * j + 1])] for j in range(first, last)]
        if len(ring) >= 4:
            rings.append(ring)
    if not rings:
        return None

    polygons = _group_rings(rings)
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _group_rings(rings: list[list]) -> list[list]:
    """Кольцо по часовой стрелке начинает новый полигон, против — дырку в нём."""
    polygons: list[list] = []
    for ring in rings:
        if is_clockwise(ring) or not polygons:
            polygons.append([ring])
        else:
            polygons[-1].append(ring)
    return polygons


def is_clockwise(ring: list) -> bool:
    """Знак площади по формуле трапеций: положительный — обход по часовой."""
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        area += (x2 - x1) * (y2 + y1)
    return area > 0


def _r(value: float) -> float:
    return round(value, COORD_PRECISION)


def read_dbf(data: bytes, encoding: Optional[str] = None) -> list[dict]:
    """Таблица атрибутов .dbf построчно.

    Кодировку можно назвать явно; без неё пробуется UTF-8, а при неудаче —
    CP1251: русские шейпфайлы чаще всего в ней. Файл .cpg, в котором
    кодировка объявлена, лежит рядом с .dbf и сюда не передаётся — тот, кто
    его прочтёт, передаст значение параметром.
    """
    if len(data) < 32:
        raise ShapefileError("файл короче заголовка dbf")
    count, header_len, record_len = struct.unpack("<IHH", data[4:12])

    fields = []
    offset = 32
    while offset < header_len and data[offset] not in (0x0D, 0x00):
        raw = data[offset:offset + 32]
        name = raw[0:11].split(b"\x00")[0].decode("ascii", "replace")
        fields.append((name, chr(raw[11]), raw[16], raw[17]))
        offset += 32

    rows = []
    for i in range(count):
        start = header_len + i * record_len
        record = data[start:start + record_len]
        if len(record) < record_len or record[0:1] == b"*":   # запись помечена удалённой
            continue
        pos, row = 1, {}
        for name, kind, size, decimals in fields:
            row[name] = _value(record[pos:pos + size], kind, decimals, encoding)
            pos += size
        rows.append(row)
    return rows


def _value(raw: bytes, kind: str, decimals: int, encoding: Optional[str]) -> Any:
    text = _decode(raw, encoding).strip()
    if not text:
        return None
    if kind in ("N", "F"):
        try:
            return float(text) if decimals or "." in text else int(text)
        except ValueError:
            return None
    if kind == "L":
        return text.upper() in ("Y", "T")
    return text


def _decode(raw: bytes, encoding: Optional[str]) -> str:
    if encoding:
        return raw.decode(encoding, "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace")


def features(shapes: list[Optional[dict]], rows: list[dict]) -> list[dict]:
    """Сшивает геометрию с атрибутами: в шейпфайле они связаны по порядку."""
    if len(shapes) != len(rows):
        raise ShapefileError(
            f"геометрий {len(shapes)}, строк таблицы {len(rows)} — файлы не пара"
        )
    out = []
    for geometry, props in zip(shapes, rows):
        if geometry is None:
            continue
        out.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {k: v for k, v in props.items() if v is not None},
        })
    return out
