"""Полигоны → сетка: какой клетке какой полигон принадлежит.

Нужно двум сборщикам. Оценки HYDE лежат сеткой 5′, а запись слоя — уезд: надо
знать, какие клетки в него входят. У затмений наоборот: губерния проверяется
по узлам сетки внутри неё. Перебор «каждая точка в каждом полигоне» для
полумиллиона клеток и 145 тысяч вершин на чистом питоне идёт минуты; построчная
заливка на numpy — секунды.
"""

from __future__ import annotations

import math
from typing import Sequence


def rings_of(geometry: dict) -> list:
    """Все кольца полигона или мультиполигона, внешние и дыры вперемешку."""
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        return list(coords)
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def rasterize(geometries: Sequence[dict], *, lat_max: float, lon_min: float, cell: float,
              n_rows: int, n_cols: int):
    """Номер полигона для каждой клетки сетки (−1 — ни один).

    Сетка задана северо-западным углом, шагом и размером; строки идут с севера
    на юг. Заливка по правилу чётности: для широты центра строки ищутся
    пересечения всех рёбер полигона, клетки с центром между парами пересечений
    — внутри. Дыры учитываются тем же правилом. Клетку, попавшую в два
    полигона (общая граница), получает первый.

    Долгота в сетке непрерывна и может уходить за 180° — так в полигонах
    RISTAT записана Чукотка. Вершины с долготой заметно западнее сетки
    сдвигаются на 360°.
    """
    import numpy as np

    index = np.full((n_rows, n_cols), -1, dtype=np.int32)
    row_lats = lat_max - cell * (np.arange(n_rows) + 0.5)
    for number, geometry in enumerate(geometries):
        x1s, y1s, x2s, y2s = [], [], [], []
        for ring in rings_of(geometry):
            pts = np.asarray(ring, dtype=np.float64)[:, :2]
            if len(pts) < 3:
                continue
            x1s.append(pts[:-1, 0])
            y1s.append(pts[:-1, 1])
            x2s.append(pts[1:, 0])
            y2s.append(pts[1:, 1])
        if not x1s:
            continue
        x1, y1 = np.concatenate(x1s), np.concatenate(y1s)
        x2, y2 = np.concatenate(x2s), np.concatenate(y2s)
        x1 = np.where(x1 < lon_min - 5, x1 + 360, x1)
        x2 = np.where(x2 < lon_min - 5, x2 + 360, x2)
        low, high = min(y1.min(), y2.min()), max(y1.max(), y2.max())
        first = max(0, int(math.floor((lat_max - high) / cell)))
        last = min(n_rows, int(math.ceil((lat_max - low) / cell)) + 1)
        for row in range(first, last):
            lat = row_lats[row]
            crossing = (y1 <= lat) != (y2 <= lat)
            if not crossing.any():
                continue
            xs = np.sort(x1[crossing] + (lat - y1[crossing]) * (x2[crossing] - x1[crossing])
                         / (y2[crossing] - y1[crossing]))
            for a, b in zip(xs[0::2], xs[1::2]):
                start = max(0, int(math.ceil((a - lon_min) / cell - 0.5)))
                stop = min(n_cols, int(math.floor((b - lon_min) / cell - 0.5)) + 1)
                if stop > start:
                    segment = index[row, start:stop]
                    segment[segment < 0] = number
    return index
