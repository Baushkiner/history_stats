"""Свой разборщик файлов R: формат XDR, собранный в тесте вручную.

Сети и R в тестах нет. Байты собираются тем же способом, каким их пишет
`serialize.c`: флаги, длина, значения, атрибуты парами с тегами. Проверяется
то, на чём держится набор Rozenas, Zhukov: таблица с фактором и пропусками,
ссылка на уже встреченный символ, объект S4 `SpatialPolygonsDataFrame` с
полигоном и дыркой, сжатие gzip и отказ на чужом формате.
"""

import gzip
import struct

import pytest

from histctx.sources.rserial import (
    RDataError, data_frame, proj4, read_rdata, read_rds, sp_polygons,
)

NIL = struct.pack(">i", 254)
UTF8 = 1 << 3


def _flags(kind, *, attr=False, tag=False, obj=False, levels=0):
    return struct.pack(">i", kind | (obj << 8) | (attr << 9) | (tag << 10) | (levels << 12))


def _char(text):
    if text is None:
        return _flags(9) + struct.pack(">i", -1)
    raw = text.encode("utf-8")
    return _flags(9, levels=UTF8) + struct.pack(">i", len(raw)) + raw


class Writer:
    """Минимальный сериализатор. Символ пишется целиком каждый раз: порядок,
    в котором тест собирает куски, не совпадает с порядком байтов в потоке, и
    номер ссылки посчитать здесь нельзя. Ссылки проверяются отдельным тестом."""

    def sym(self, name):
        return _flags(1) + _char(name)

    def attrs(self, pairs):
        out = b""
        for tag, value in pairs:
            out += _flags(2, tag=True) + self.sym(tag) + value
        return out + NIL

    def vector(self, kind, payload, n, attrs=None, obj=False):
        head = _flags(kind, attr=bool(attrs), obj=obj) + struct.pack(">i", n) + payload
        return head + (self.attrs(attrs) if attrs else b"")

    def ints(self, values, attrs=None, obj=False):
        payload = b"".join(struct.pack(">i", -2147483648 if v is None else v) for v in values)
        return self.vector(13, payload, len(values), attrs, obj)

    def reals(self, values, attrs=None):
        payload = b"".join(struct.pack(">d", float("nan") if v is None else v) for v in values)
        return self.vector(14, payload, len(values), attrs)

    def lgl(self, values):
        return self.vector(10, b"".join(struct.pack(">i", int(v)) for v in values), len(values))

    def strs(self, values, attrs=None):
        return self.vector(16, b"".join(_char(v) for v in values), len(values), attrs)

    def vec(self, items, attrs=None, obj=False):
        return self.vector(19, b"".join(items), len(items), attrs, obj)

    def s4(self, attrs):
        return _flags(25, attr=True, obj=True) + self.attrs(attrs)


def _rdata(objects: dict, w: Writer) -> bytes:
    body = b""
    for name, value in objects.items():
        body += _flags(2, tag=True) + w.sym(name) + value
    header = b"RDX2\nX\n" + struct.pack(">iii", 2, 0x040000, 0x020300)
    return header + body + NIL


def _frame(w: Writer, columns: dict, nrows: int, classes=("data.frame",)):
    return w.vec(list(columns.values()), attrs=[
        ("names", w.strs(list(columns))),
        ("row.names", w.ints([-2147483648, -nrows])),
        ("class", w.strs(list(classes))),
    ], obj=True)


def test_data_frame_with_factor_missing_values_and_symbol_reference():
    w = Writer()
    factor = w.ints([2, 1, None], attrs=[("levels", w.strs(["Вінницька", "Київська"])),
                                         ("class", w.strs(["factor"]))], obj=True)
    frame = _frame(w, {
        "NAME_2_1933": w.strs(["Антонінський район", "Барський район", None]),
        "NAME_1_1933": factor,
        "FAMINE_TOTAL": w.reals([9834.0, None, 451.0]),
        "ID_1": w.ints([10, 24, None]),
    }, 3)
    objects = read_rdata(_rdata({"data": frame}, w))
    assert list(objects) == ["data"]
    columns = data_frame(objects["data"])
    assert columns["NAME_2_1933"] == ["Антонінський район", "Барський район", None]
    assert columns["NAME_1_1933"] == ["Київська", "Вінницька", None]
    assert columns["FAMINE_TOTAL"] == [9834.0, None, 451.0]
    assert columns["ID_1"] == [10, 24, None]
    assert objects["data"].classes == ["data.frame"]


def test_repeated_symbol_is_read_by_reference():
    """R пишет символ один раз, дальше — ссылкой на номер в таблице встреченных."""
    w = Writer()
    first = _flags(2, tag=True) + w.sym("x") + w.ints([1])
    second = _flags(2, tag=True) + struct.pack(">i", 255 | (1 << 8)) + w.ints([2])
    header = b"RDX2\nX\n" + struct.pack(">iii", 2, 0x040000, 0x020300)
    with pytest.raises(RDataError):
        read_rdata(header + _flags(2, tag=True) + struct.pack(">i", 255 | (5 << 8)) + NIL)
    pairs = read_rdata(header + first + second + NIL)
    # Оба объекта названы «x»: второй имя взял ссылкой, словарь оставил последний.
    assert pairs == {"x": pairs["x"]} and pairs["x"].value == [2]


def _polygon(w, coords, hole=False):
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    matrix = w.reals(xs + ys, attrs=[("dim", w.ints([len(coords), 2]))])
    return w.s4([("labpt", w.reals([xs[0], ys[0]])), ("hole", w.lgl([hole])),
                 ("coords", matrix), ("class", w.strs(["Polygon"]))])


def _spdf(w):
    outer = [(30.0, 50.0), (31.0, 50.0), (31.0, 51.0), (30.0, 51.0), (30.0, 50.0)]
    hole = [(30.4, 50.4), (30.6, 50.4), (30.6, 50.6), (30.4, 50.4)]
    island = [(32.0, 50.0), (32.5, 50.0), (32.5, 50.5), (32.0, 50.0)]
    first = w.s4([("Polygons", w.vec([_polygon(w, outer), _polygon(w, hole, hole=True)])),
                  ("ID", w.strs(["0"])), ("comment", w.strs(["0 1"])),
                  ("class", w.strs(["Polygons"]))])
    second = w.s4([("Polygons", w.vec([_polygon(w, outer), _polygon(w, island)])),
                   ("ID", w.strs(["1"])), ("class", w.strs(["Polygons"]))])
    frame = _frame(w, {"ID": w.strs(["0", "1"]), "FAMINE_TOTAL": w.reals([100.0, 200.0])}, 2)
    crs = w.s4([("projargs", w.strs(["+proj=longlat +datum=WGS84 +no_defs"])),
                ("class", w.strs(["CRS"]))])
    return w.s4([("data", frame), ("polygons", w.vec([first, second])),
                 ("proj4string", crs), ("class", w.strs(["SpatialPolygonsDataFrame"]))])


def test_sp_polygons_become_geojson_with_holes_and_parts():
    w = Writer()
    raw = gzip.compress(_rdata({"data": _spdf(w)}, w))
    data = read_rdata(raw)["data"]
    assert data.kind == "S4"
    assert "longlat" in proj4(data)
    assert data_frame(data.attr("data"))["FAMINE_TOTAL"] == [100.0, 200.0]
    shapes = dict(sp_polygons(data))
    assert set(shapes) == {"0", "1"}
    # Матрица R по столбцам: первая точка — (30, 50), а не (30, 31).
    assert shapes["0"]["type"] == "Polygon"
    assert shapes["0"]["coordinates"][0][0] == [30.0, 50.0]
    assert len(shapes["0"]["coordinates"]) == 2           # внешнее кольцо и дырка
    assert shapes["1"]["type"] == "MultiPolygon"
    assert len(shapes["1"]["coordinates"]) == 2


def test_rds_and_foreign_formats():
    w = Writer()
    body = w.ints([1, 2, 3])
    rds = b"X\n" + struct.pack(">iii", 2, 0x040000, 0x020300) + body
    assert read_rds(rds).value == [1, 2, 3]
    with pytest.raises(RDataError):
        read_rdata(b"RDA2\nA\n2\n")                       # текстовый формат не читается
    with pytest.raises(RDataError):
        read_rdata(rds)                                   # .rds — не .RData
    with pytest.raises(RDataError):
        read_rdata(b"RDX2\nX\n" + struct.pack(">iii", 2, 0, 0) + _flags(22))
