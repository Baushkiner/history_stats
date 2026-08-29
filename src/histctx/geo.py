"""География: проверка координат, расстояния и извлечение губернии из текста."""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional

# Охват Российской империи и СССР максимального размера, с запасом.
# Точки вне этой рамки для генеалогического контекста почти всегда шум:
# в текущем файле сражений так отсекаются Мартиника, Сенегал, Гваделупа.
BBOX_RU = (35.0, 18.0, 82.0, 180.0)   # (lat_min, lon_min, lat_max, lon_max)

# Чукотка заходит за 180-й меридиан, и её долгота отрицательна. Без этой
# добавки восток страны отсекался бы вместе с колониальными сюжетами.
BBOX_RU_EAST = (60.0, -180.0, 72.0, -168.0)

EARTH_R_KM = 6371.0088

_RE_REGION = re.compile(
    r"\b([А-ЯЁ][а-яё\-]+(?:ая|ое|ий|ой|ья))\s+"
    r"(губерн\w*|област\w*|кра\w*|окру\w*|намес\w*|войск\w*)",
    re.UNICODE,
)
_RE_DISTRICT = re.compile(
    r"\b([А-ЯЁ][а-яё\-]+(?:ий|ой|ый))\s+(уезд\w*|район\w*|стан\w*|волост\w*)",
    re.UNICODE,
)


def valid_coords(lat, lon) -> bool:
    """Координаты существуют и не являются нулевым островом."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(la) or math.isnan(lo):
        return False
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return False
    # (0,0) в Гвинейском заливе — почти всегда потерянное значение.
    return not (abs(la) < 1e-6 and abs(lo) < 1e-6)


def in_bbox(lat: float, lon: float, bbox: Optional[tuple] = None) -> bool:
    """Попадает ли точка в охват РИ/СССР (или в переданную рамку)."""
    if bbox is not None:
        la_min, lo_min, la_max, lo_max = bbox
        return la_min <= lat <= la_max and lo_min <= lon <= lo_max
    return _within(lat, lon, BBOX_RU) or _within(lat, lon, BBOX_RU_EAST)


def _within(lat: float, lon: float, bbox: tuple) -> bool:
    la_min, lo_min, la_max, lo_max = bbox
    return la_min <= lat <= la_max and lo_min <= lon <= lo_max


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по большому кругу в километрах."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


# Женский род: «в Костромской губернии» -> «Костромская губерния». Без этого
# одна и та же губерния попадает в данные двумя написаниями и считается дважды.
_FEM_NOMINATIVE = {"ой": "ая", "ою": "ая", "ую": "ая", "ей": "яя", "ею": "яя", "юю": "яя"}
_FEMININE_UNITS = {"губерния", "область", "волость"}


def extract_region(text: Optional[str]) -> Optional[str]:
    """Достаёт «Нижегородская губерния» из «Нижегородская губерния (Сергач), Заволжье»."""
    if not text:
        return None
    m = _RE_REGION.search(str(text))
    if not m:
        return None
    kind = m.group(2).lower()
    base = {"губерн": "губерния", "област": "область", "кра": "край",
            "окру": "округ", "намес": "наместничество", "войск": "войско"}
    for pref, word in base.items():
        if kind.startswith(pref):
            return f"{_nominative(m.group(1), word)} {word}"
    return f"{m.group(1)} {m.group(2)}"


def _nominative(adjective: str, unit: str) -> str:
    """Согласует прилагательное с приведённым к именительному падежу словом.

    Только для женского рода: у «край» и «округ» окончание «-ой» само по себе
    именительное («Донской»), и трогать его нельзя.
    """
    if unit not in _FEMININE_UNITS:
        return adjective
    ending = _FEM_NOMINATIVE.get(adjective[-2:].lower())
    return adjective[:-2] + ending if ending else adjective


# Слова, обозначающие тип единицы. Для сопоставления территорий они лишние:
# одно и то же место называлось губернией, потом округом, потом областью.
_UNIT_WORDS = {
    "губерния", "губернии", "губ", "область", "области", "обл",
    "край", "края", "округ", "округа", "наместничество", "наместничества",
    "войско", "войска", "республика", "республики", "асср", "сср",
    "уезд", "уезда", "район", "района",
}
# Окончания прилагательных: «Самарская» и «Самарской» — одна и та же губерния.
# Только короткие окончания: если снимать «ская» целиком, «Донская область» и
# «Область войска Донского» дадут разные ключи и перестанут совпадать.
_RE_ADJ_TAIL = re.compile(r"(ого|ому|ыми|ими|ая|яя|ое|ее|ые|ие|ый|ий|ой|ей|ую|юю|ых|их|ья|ье)$")


def region_key(name: Optional[str]) -> Optional[str]:
    """Ключ для сопоставления территорий.

    «Самарская губерния», «Самарская область» и «Самарская губ.» дают один
    ключ: за полтора века тип единицы менялся чаще, чем сама территория, и
    для подбора контекста важно название, а не то, как её назвали в бумаге.
    """
    if not name:
        return None
    text = re.sub(r"[^а-яёa-z\s-]", " ", str(name).lower().replace("ё", "е"))
    words = [w for w in text.split() if w and w not in _UNIT_WORDS]
    stems = [_RE_ADJ_TAIL.sub("", w) or w for w in words]
    return " ".join(stems) or None


def same_region(a: Optional[str], b: Optional[str]) -> bool:
    """Одна ли это территория с точностью до типа единицы и падежа."""
    ka, kb = region_key(a), region_key(b)
    return bool(ka) and ka == kb


def extract_district(text: Optional[str]) -> Optional[str]:
    """Достаёт «Сергачский уезд», если он назван в тексте."""
    if not text:
        return None
    m = _RE_DISTRICT.search(str(text))
    if not m:
        return None
    kind = m.group(2).lower()
    base = {"уезд": "уезд", "район": "район", "стан": "стан", "волост": "волость"}
    for pref, word in base.items():
        if kind.startswith(pref):
            return f"{m.group(1)} {word}"
    return None


class SpatialIndex:
    """Сетка 1°×1° для быстрого поиска ближайших записей.

    Полноценный R-дерево здесь избыточно: на сотнях тысяч точек простая
    решётка даёт нужную скорость и не тянет зависимостей.
    """

    def __init__(self, records: Iterable) -> None:
        self._cells: dict[tuple[int, int], list] = {}
        self.size = 0
        for rec in records:
            if not getattr(rec, "has_point", False):
                continue
            key = (int(math.floor(rec.lat)), int(math.floor(rec.lon)))
            self._cells.setdefault(key, []).append(rec)
            self.size += 1

    def near(self, lat: float, lon: float, radius_km: float) -> list:
        """Записи в радиусе, отсортированные по расстоянию. Возвращает (запись, км)."""
        # 1° широты ≈ 111 км; по долготе делим на cos(широты).
        dlat = radius_km / 111.0
        coslat = max(math.cos(math.radians(lat)), 0.01)
        dlon = radius_km / (111.0 * coslat)
        out = []
        lat_lo, lat_hi = int(math.floor(lat - dlat)), int(math.floor(lat + dlat))
        lon_lo, lon_hi = int(math.floor(lon - dlon)), int(math.floor(lon + dlon))
        for la in range(lat_lo, lat_hi + 1):
            for lo in range(lon_lo, lon_hi + 1):
                for rec in self._cells.get((la, lo), ()):
                    d = haversine_km(lat, lon, rec.lat, rec.lon)
                    if d <= radius_km:
                        out.append((rec, d))
        out.sort(key=lambda t: t[1])
        return out
