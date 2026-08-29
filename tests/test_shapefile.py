"""Чтение шейпфайла без внешних зависимостей.

Образцы собираются здесь же: файл пишется по спецификации ESRI и тут же
читается разбором. Так проверяется не «получилось что-то», а именно те два
места, где разбор обычно ломается, — обратный порядок байт в заголовках
и направление обхода кольца.
"""

import struct
from pathlib import Path

import pytest

from histctx.sources.shapefile import (
    ShapefileError, features, is_clockwise, read_dbf, read_shapes,
)

ROOT = Path(__file__).resolve().parents[1]

# Квадрат по часовой стрелке — внешняя граница; вложенный против часовой — дырка.
SQUARE_CW = [[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0], [0.0, 0.0]]
HOLE_CCW = [[2.0, 2.0], [4.0, 2.0], [4.0, 4.0], [2.0, 4.0], [2.0, 2.0]]
FAR_CW = [[20.0, 20.0], [20.0, 25.0], [25.0, 25.0], [25.0, 20.0], [20.0, 20.0]]


def build_shp(shapes: list[list[list]], shape_type: int = 5) -> bytes:
    """Собирает .shp из колец: заголовки — big-endian, содержимое — little."""
    body = b""
    for number, rings in enumerate(shapes, 1):
        points = [pt for ring in rings for pt in ring]
        parts, offset = [], 0
        for ring in rings:
            parts.append(offset)
            offset += len(ring)
        content = (
            struct.pack("<i", shape_type)
            + struct.pack("<4d", 0, 0, 0, 0)
            + struct.pack("<ii", len(parts), len(points))
            + struct.pack(f"<{len(parts)}i", *parts)
            + struct.pack(f"<{2 * len(points)}d", *[c for pt in points for c in pt])
        )
        body += struct.pack(">ii", number, len(content) // 2) + content

    header = (
        struct.pack(">i", 9994) + b"\x00" * 20
        + struct.pack(">i", (100 + len(body)) // 2)
        + struct.pack("<ii", 1000, shape_type)
        + struct.pack("<8d", 0, 0, 0, 0, 0, 0, 0, 0)
    )
    return header + body


def build_dbf(fields: list[tuple], rows: list[list]) -> bytes:
    """Собирает .dbf: (имя, тип, длина, знаков после запятой) и строки."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(f[2] for f in fields)
    out = struct.pack("<BBBBIHH", 3, 124, 1, 1, len(rows), header_len, record_len)
    out += b"\x00" * 20
    for name, kind, size, decimals in fields:
        out += name.encode("ascii").ljust(11, b"\x00")
        out += kind.encode("ascii") + b"\x00" * 4
        out += bytes([size, decimals]) + b"\x00" * 14
    out += b"\x0d"
    for row in rows:
        out += b" "
        for (_, _, size, _), value in zip(fields, row):
            out += str(value).encode("utf-8")[:size].ljust(size, b" ")
    return out


def test_polygon_is_read_back():
    shapes = read_shapes(build_shp([[SQUARE_CW]]))
    assert len(shapes) == 1
    assert shapes[0]["type"] == "Polygon"
    assert shapes[0]["coordinates"][0][0] == [0.0, 0.0]
    assert shapes[0]["coordinates"][0][2] == [10.0, 10.0]


def test_hole_stays_inside_its_polygon():
    """Кольцо против часовой — дырка, а не второй полигон."""
    shape = read_shapes(build_shp([[SQUARE_CW, HOLE_CCW]]))[0]
    assert shape["type"] == "Polygon"
    assert len(shape["coordinates"]) == 2


def test_second_outer_ring_starts_a_new_polygon():
    shape = read_shapes(build_shp([[SQUARE_CW, HOLE_CCW, FAR_CW]]))[0]
    assert shape["type"] == "MultiPolygon"
    assert [len(poly) for poly in shape["coordinates"]] == [2, 1]


def test_direction_of_a_ring_is_read_by_signed_area():
    assert is_clockwise(SQUARE_CW)
    assert not is_clockwise(HOLE_CCW)
    assert not is_clockwise(SQUARE_CW[::-1])


def test_point_shapefile_is_read_too():
    data = build_shp([[[[37.6173, 55.7558]]]], shape_type=1)
    # У точки содержание другое: тип и пара координат сразу за ним.
    body = struct.pack("<i", 1) + struct.pack("<dd", 37.6173, 55.7558)
    data = data[:100] + struct.pack(">ii", 1, len(body) // 2) + body
    assert read_shapes(data)[0] == {"type": "Point", "coordinates": [37.6173, 55.7558]}


def test_unknown_geometry_stops_the_read():
    """Сменится геометрия — это надо заметить, а не пропустить молча."""
    with pytest.raises(ShapefileError, match="3"):
        read_shapes(build_shp([[SQUARE_CW]], shape_type=3))
    with pytest.raises(ShapefileError, match="сигнатура"):
        read_shapes(b"\x00" * 120)


def test_dbf_rows_are_read_with_types():
    data = build_dbf(
        # Длина поля в dbf считается в байтах: кириллица в UTF-8 берёт по два.
        [("NAMERUS", "C", 48, 0), ("POPALL", "N", 10, 0), ("AREAV", "N", 12, 1)],
        [["Тифлисская губерния", 1051032, 34125.5], ["Пустая", "", ""]],
    )
    rows = read_dbf(data, "utf-8")
    assert rows[0] == {"NAMERUS": "Тифлисская губерния", "POPALL": 1051032, "AREAV": 34125.5}
    assert rows[1] == {"NAMERUS": "Пустая", "POPALL": None, "AREAV": None}


def test_geometry_and_table_are_matched_by_order():
    shapes = read_shapes(build_shp([[SQUARE_CW], [FAR_CW]]))
    rows = read_dbf(build_dbf([("NAMERUS", "C", 20, 0)], [["Первая"], ["Вторая"]]), "utf-8")
    feats = features(shapes, rows)
    assert [f["properties"]["NAMERUS"] for f in feats] == ["Первая", "Вторая"]
    with pytest.raises(ShapefileError, match="не пара"):
        features(shapes, rows[:1])
