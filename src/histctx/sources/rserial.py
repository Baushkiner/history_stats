"""Чтение файлов R (`.RData`, `.rds`) без R и без сторонних пакетов.

Зачем свой разборщик. Пакеты воспроизведения статей на Harvard Dataverse
часто лежат только в формате R: так устроен набор Rozenas и Zhukov по голоду
1932–1933 годов, где полигоны районов УССР и потери от голода — один объект
`SpatialPolygonsDataFrame` пакета `sp`. Пакет `rdata` с PyPI это читает, но
тянет за собой xarray и свежий pandas ради одного файла; формат же простой и
описан в исходниках R (`src/main/serialize.c`), как у шейпфайла и GeoPackage,
для которых в проекте тоже свои разборщики.

Что умеет. Формат XDR (буква `X` в заголовке) версий 2 и 3, сжатие gzip,
bzip2 и xz, векторы всех базовых типов, списки и пары, атрибуты, символы и
ссылки на них, объекты S4, окружения и компактные ALTREP-последовательности
(ими R пишет `row.names` и `1:n`). Чего не умеет — байткод и внешние
указатели: в файлах данных их не бывает, и встретив такое, разбор
останавливается с названием типа, а не читает мусор дальше.

Что на выходе. `RObject(kind, value, attributes)`: у вектора `value` — список
значений (`None` вместо NA), у пары — список `(тег, значение)`, у S4 — пусто,
всё содержимое в атрибутах. Символ — `RSymbol`, NULL — `None`. Две функции
сверху переводят частые случаи: `data_frame` — таблицу в колонки (факторы
становятся подписями), `sp_polygons` — полигоны `sp` в геометрию GeoJSON.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import math
import struct
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


class RDataError(ValueError):
    """Файл не в том формате или в нём то, чего разбор не умеет."""


class RSymbol(str):
    """Имя R: тег пары, имя атрибута, класс в ALTREP."""


@dataclass
class RObject:
    kind: str                       # "integer", "double", "list", "pairlist", "S4", …
    value: Any = None
    attributes: dict = field(default_factory=dict)

    def attr(self, name: str, default=None):
        return self.attributes.get(name, default)

    @property
    def classes(self) -> list[str]:
        cls = self.attributes.get("class")
        return list(cls.value) if isinstance(cls, RObject) else []


# Коды типов из serialize.c.
_NIL, _SYM, _LIST, _CLO, _ENV, _PROM, _LANG = 0, 1, 2, 3, 4, 5, 6
_SPECIAL, _BUILTIN, _CHAR, _LGL = 7, 8, 9, 10
_INT, _REAL, _CPLX, _STR, _DOT, _ANY, _VEC, _EXPR = 13, 14, 15, 16, 17, 18, 19, 20
_BCODE, _EXTPTR, _WEAKREF, _RAW, _S4 = 21, 22, 23, 24, 25

_ALTREP, _ATTRLIST, _ATTRLANG = 238, 239, 240
_BASEENV, _EMPTYENV = 241, 242
_GENERICREF, _CLASSREF, _PERSIST, _PACKAGE, _NAMESPACE = 245, 246, 247, 248, 249
_BASENAMESPACE, _MISSINGARG, _UNBOUND, _GLOBALENV, _NILVALUE, _REF = 250, 251, 252, 253, 254, 255

_PAIRS = {_LIST: "pairlist", _LANG: "language", _CLO: "closure", _PROM: "promise",
          _DOT: "dots", _ATTRLIST: "pairlist", _ATTRLANG: "language"}
_VECTORS = {_LGL: "logical", _INT: "integer", _REAL: "double", _CPLX: "complex",
            _STR: "character", _VEC: "list", _EXPR: "expression", _RAW: "raw"}
_ENVIRONMENTS = {_GLOBALENV: "R_GlobalEnv", _BASEENV: "base", _EMPTYENV: "R_EmptyEnv",
                 _BASENAMESPACE: "namespace:base"}

_NA_INT = -2147483648


def _is_na_real(value: float) -> bool:
    """NA_real_ в R — NaN с полезной нагрузкой 1954; обычный NaN — не NA.

    Для данных различие не нужно — обе пустоты становятся None, — но функция
    названа честно, чтобы не путать читателя.
    """
    return math.isnan(value)


def _decompress(raw: bytes) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if raw[:3] == b"BZh":
        return bz2.decompress(raw)
    if raw[:6] == b"\xfd7zXZ\x00":
        return lzma.decompress(raw)
    return raw


class _Reader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos
        self.refs: list = []

    # --- примитивы --------------------------------------------------------

    def _take(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.data):
            raise RDataError(f"файл оборван: нужно {n} байт на позиции {self.pos}")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def int(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def ints(self, n: int) -> tuple:
        return struct.unpack(f">{n}i", self._take(4 * n)) if n else ()

    def doubles(self, n: int) -> tuple:
        return struct.unpack(f">{n}d", self._take(8 * n)) if n else ()

    def length(self) -> int:
        n = self.int()
        if n == -1:
            upper, lower = self.int(), self.int()
            n = (upper << 32) + lower
        return n

    def string(self) -> Optional[str]:
        """CHARSXP после флагов: длина и байты; -1 — NA."""
        n = self.int()
        if n == -1:
            return None
        return self._take(n).decode("utf-8", errors="replace")

    # --- объекты ----------------------------------------------------------

    def item(self):
        flags = self.int()
        kind = flags & 0xFF
        has_attr = bool(flags & (1 << 9))
        has_tag = bool(flags & (1 << 10))

        if kind == _NILVALUE:
            return None
        if kind == _REF:
            index = flags >> 8 or self.int()
            try:
                return self.refs[index - 1]
            except IndexError as exc:
                raise RDataError(f"ссылка на объект №{index}, которого нет") from exc
        if kind in _ENVIRONMENTS:
            return RObject("environment", _ENVIRONMENTS[kind])
        if kind in (_MISSINGARG, _UNBOUND):
            return None
        if kind in (_PACKAGE, _NAMESPACE, _PERSIST):
            if self.int() != 0:
                raise RDataError("неизвестный вид списка строк")
            names = [self.item_string() for _ in range(self.int())]
            obj = RObject("namespace" if kind == _NAMESPACE else "package", names)
            self.refs.append(obj)
            return obj
        if kind == _SYM:
            name = RSymbol(self.item_string() or "")
            self.refs.append(name)
            return name
        if kind == _ENV:
            obj = RObject("environment", {})
            self.refs.append(obj)
            self.int()                       # locked
            self.item()                      # enclos
            frame = self.item()
            self.item()                      # hashtab
            attrs = self.item()
            if isinstance(frame, RObject) and frame.kind == "pairlist":
                obj.value = dict(frame.value)
            if isinstance(attrs, RObject):
                obj.attributes = _attr_dict(attrs)
            return obj
        if kind in _PAIRS:
            return self._pairlist(kind, flags, has_attr, has_tag)
        if kind == _CHAR:
            return self.string()
        if kind in _VECTORS:
            obj = RObject(_VECTORS[kind], self._vector(kind))
        elif kind == _S4:
            obj = RObject("S4")
        elif kind == _ALTREP:
            return self._altrep()
        else:
            raise RDataError(f"тип R с кодом {kind} разбор не читает")
        if has_attr:
            obj.attributes = _attr_dict(self.item())
        return obj

    def item_string(self) -> Optional[str]:
        value = self.item()
        if value is not None and not isinstance(value, str):
            raise RDataError("ожидалась строка R")
        return value

    def _pairlist(self, kind: int, flags: int, has_attr: bool, has_tag: bool) -> RObject:
        """Пары читаются циклом, а не рекурсией: список в тысячу элементов —
        это тысяча вложенных CDR, и рекурсия упёрлась бы в предел Python."""
        head = RObject(_PAIRS[kind], [])
        first = True
        while True:
            attrs = self.item() if has_attr else None
            tag = self.item() if has_tag else None
            value = self.item()
            head.value.append((tag, value))
            if first and isinstance(attrs, RObject):
                head.attributes = _attr_dict(attrs)
            first = False
            flags = self.int()
            kind = flags & 0xFF
            if kind == _NILVALUE:
                return head
            if kind not in _PAIRS:
                # Хвост пары — не пара (так бывает у языковых объектов):
                # дочитываем его как обычный объект и кладём последним.
                self.pos -= 4
                head.value.append((None, self.item()))
                return head
            has_attr = bool(flags & (1 << 9))
            has_tag = bool(flags & (1 << 10))

    def _vector(self, kind: int) -> list:
        n = self.length()
        if kind in (_LGL, _INT):
            values = self.ints(n)
            if kind == _LGL:
                return [None if v == _NA_INT else bool(v) for v in values]
            return [None if v == _NA_INT else v for v in values]
        if kind == _REAL:
            return [None if _is_na_real(v) else v for v in self.doubles(n)]
        if kind == _CPLX:
            values = self.doubles(2 * n)
            return [complex(values[i], values[i + 1]) for i in range(0, 2 * n, 2)]
        if kind == _RAW:
            return list(self._take(n))
        if kind == _STR:
            out = []
            for _ in range(n):
                flags = self.int()
                if flags & 0xFF != _CHAR:
                    raise RDataError("в векторе строк не строка")
                out.append(self.string())
            return out
        return [self.item() for _ in range(n)]

    def _altrep(self):
        """Компактные последовательности и обёртки — то, что R пишет сам."""
        info = self.item()
        state = self.item()
        attrs = self.item()
        cls = info.value[0][1] if isinstance(info, RObject) and info.value else None
        if cls == "compact_intseq":
            n, start, step = state.value
            obj = RObject("integer", [int(start + i * step) for i in range(int(n))])
        elif cls == "compact_realseq":
            n, start, step = state.value
            obj = RObject("double", [start + i * step for i in range(int(n))])
        elif cls and cls.startswith("wrap_"):
            obj = state.value[0] if isinstance(state, RObject) else state
        elif cls == "deferred_string":
            source = state.value[0][1] if isinstance(state, RObject) else None
            values = source.value if isinstance(source, RObject) else []
            obj = RObject("character", [None if v is None else _number_text(v) for v in values])
        else:
            raise RDataError(f"ALTREP-класс {cls!r} разбор не читает")
        if isinstance(attrs, RObject) and attrs.kind == "pairlist":
            obj.attributes = _attr_dict(attrs)
        return obj


def _number_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _attr_dict(obj) -> dict:
    if not isinstance(obj, RObject) or obj.kind != "pairlist":
        return {}
    return {str(tag): value for tag, value in obj.value if tag is not None}


def _header(data: bytes) -> int:
    """Позиция после заголовка. `RDX2`/`RDX3` — файл `save()`, без них — `saveRDS()`."""
    pos = 0
    if data[:5] in (b"RDX2\n", b"RDX3\n"):
        pos = 5
    if data[pos:pos + 2] != b"X\n":
        kind = data[pos:pos + 2]
        raise RDataError(f"поддерживается только формат XDR (X), в файле {kind!r}")
    pos += 2
    version = struct.unpack(">i", data[pos:pos + 4])[0]
    pos += 12                          # версия формата, версия R, минимальная версия
    if version == 3:
        n = struct.unpack(">i", data[pos:pos + 4])[0]
        pos += 4 + n                   # кодировка сеанса, записавшего файл
    elif version != 2:
        raise RDataError(f"версия сериализации {version} не поддерживается")
    return pos


def read_rdata(raw: bytes) -> dict:
    """`.RData`: объекты по именам, как их сохранил `save()`."""
    data = _decompress(raw)
    if data[:5] not in (b"RDX2\n", b"RDX3\n"):
        raise RDataError("не файл .RData: нет заголовка RDX2/RDX3")
    top = _Reader(data, _header(data)).item()
    if not isinstance(top, RObject) or top.kind != "pairlist":
        raise RDataError("в .RData наверху не перечень объектов")
    return {str(tag): value for tag, value in top.value}


def read_rds(raw: bytes):
    """`.rds`: один объект без имени."""
    data = _decompress(raw)
    return _Reader(data, _header(data)).item()


# --- частые виды объектов ----------------------------------------------------

def data_frame(obj: RObject) -> dict[str, list]:
    """`data.frame` → {колонка: значения}. Фактор становится подписями уровней."""
    if not isinstance(obj, RObject) or obj.kind != "list":
        raise RDataError("ожидалась таблица data.frame")
    names = obj.attr("names")
    if not isinstance(names, RObject):
        raise RDataError("у таблицы нет имён колонок")
    out = {}
    for name, column in zip(names.value, obj.value):
        out[name] = column_values(column)
    return out


def column_values(column) -> list:
    if not isinstance(column, RObject):
        return []
    levels = column.attr("levels")
    if "factor" in column.classes and isinstance(levels, RObject):
        labels = levels.value
        return [None if v is None else labels[v - 1] for v in column.value]
    return list(column.value)


def _rings(polygons: RObject) -> list[tuple[bool, list]]:
    out = []
    for polygon in polygons.value:
        coords = polygon.attr("coords")
        hole = polygon.attr("hole")
        if not isinstance(coords, RObject):
            continue
        values = coords.value
        n = len(values) // 2
        # Матрица R хранится по столбцам: сначала все долготы, потом широты.
        ring = [[values[i], values[n + i]] for i in range(n)]
        out.append((bool(hole.value[0]) if isinstance(hole, RObject) else False, ring))
    return out


def _owners(rings: list, comment: Optional[str]) -> list[int]:
    """Чьё кольцо: 0 — внешнее, k — дырка в k-м (с единицы), как пишет `sp`.

    Пометка `comment` у объекта Polygons ставится `rgeos`; если её нет,
    дырка отдаётся предыдущему внешнему кольцу.
    """
    if comment:
        parts = comment.split()
        if len(parts) == len(rings) and all(p.isdigit() for p in parts):
            return [int(p) for p in parts]
    owners, last = [], 0
    for i, (hole, _) in enumerate(rings, start=1):
        if hole and last:
            owners.append(last)
        else:
            owners.append(0)
            last = i
    return owners


def sp_polygons(obj: RObject) -> Iterator[tuple[str, dict]]:
    """`SpatialPolygons[DataFrame]` пакета `sp` → (ID полигона, геометрия GeoJSON)."""
    if not isinstance(obj, RObject) or obj.kind != "S4":
        raise RDataError("ожидался объект S4 пакета sp")
    polygons = obj.attr("polygons")
    if not isinstance(polygons, RObject):
        raise RDataError("у объекта нет слота polygons")
    for item in polygons.value:
        ident = item.attr("ID")
        ident = ident.value[0] if isinstance(ident, RObject) else None
        rings = _rings(item.attr("Polygons"))
        comment = item.attr("comment")
        comment = comment.value[0] if isinstance(comment, RObject) and comment.value else None
        owners = _owners(rings, comment)
        parts: dict[int, list] = {}
        order = []
        for i, ((_, ring), owner) in enumerate(zip(rings, owners), start=1):
            if owner == 0:
                parts[i] = [ring]
                order.append(i)
            elif owner in parts:
                parts[owner].append(ring)
        polys = [parts[i] for i in order]
        if len(polys) == 1:
            geometry = {"type": "Polygon", "coordinates": polys[0]}
        else:
            geometry = {"type": "MultiPolygon", "coordinates": polys}
        yield ident, geometry


def proj4(obj: RObject) -> Optional[str]:
    """Строка проекции объекта `sp` — чтобы проверить, что это долгота и широта."""
    crs = obj.attr("proj4string") if isinstance(obj, RObject) else None
    args = crs.attr("projargs") if isinstance(crs, RObject) else None
    return args.value[0] if isinstance(args, RObject) and args.value else None
