"""Общее у адаптеров исходных таблиц проекта.

Литературные места, материалы Тенишева, сражения и снимки Прокудина-Горского
ведутся вручную в разных книгах XLSX, но колонки координат у всех названы
одинаково — «Широта (lat)» и «Долгота (lon)», — и читались они четырьмя
одинаковыми кусками кода. Кусок один, потому что и правило одно: без
координат запись остаётся, но помечается, а точка вне охвата РИ/СССР не
выбрасывается, а получает свою пометку — ничего не удаляется молча.
"""

from __future__ import annotations

from typing import Optional

from ..geo import in_bbox, valid_coords

LAT_COLUMN = "Широта (lat)"
LON_COLUMN = "Долгота (lon)"


def coords(row) -> tuple[Optional[float], Optional[float], str]:
    """Координаты строки таблицы и оценка: `(широта, долгота, confidence)`.

    `no_coords` — координат нет вовсе; `outside_bbox` — точка есть, но лежит
    вне охвата Российской империи и СССР; `ok` — годится для карты.
    Координата вне рамки возвращается как есть: запись с ней остаётся
    в данных, а решение принимает тот, кто её читает.
    """
    lat, lon = row.get(LAT_COLUMN), row.get(LON_COLUMN)
    if not valid_coords(lat, lon):
        return None, None, "no_coords"
    lat, lon = float(lat), float(lon)
    return lat, lon, "ok" if in_bbox(lat, lon) else "outside_bbox"
