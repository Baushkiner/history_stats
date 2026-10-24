"""Рамка РИ/СССР по полигонам, а не по прямоугольнику.

Общее сито слоёв — прямоугольник `geo.BBOX_RU` (35–82° с. ш., от 18° в. д.).
Для большинства слоёв его хватает: отсекаются Мартиника и Сенегал, а что
попало в прямоугольник лишнего, теряется в общем числе. Для слоя, почти
целиком лежащего в нынешней Польше, прямоугольник мимо цели в обе стороны.
Он пропускает Краков, Тарнов, Жешув (Галиция, Австрия) и Вармию с Мазурами
(Восточная Пруссия), а режет по 18-му меридиану не только Великопольшу и
Силезию, которые империей не были, но и запад Калишской губернии, которая
была. На приходах это не мелочь: из 7 400 польских приходов со своей
координатой в губерниях 1897 года лежат 2 708, остальные 4 692 — Галиция,
прусская часть и земли, отошедшие Польше в 1945 году.

Поэтому рамка здесь — полигоны, и все они уже лежат в проекте:

* губернии переписи 1897 года (`provinces_1897.geojson`) — Царство Польское,
  Великое княжество Финляндское и вся империя по губерниям. Точка внутри
  получает губернию в поле `region`;
* из CShapes 2.0 (`state_borders.geojson`), за все даты разом, — Россия
  (СССР) и четыре государства, целиком вышедших из империи: Финляндия,
  Эстония, Латвия, Литва. Это то, что было империей или СССР, но не
  губерниями 1897 года: Галиция с Львовом, Буковина, Закарпатье,
  Калининград, Аландские острова. Губернии у точки тогда нет, но рамку она
  проходит. Польша между войнами в список не входит: с ней в рамку пришла
  бы Галиция.

Контуры обоих наборов грубые у моря: финский приход на острове или на самом
берегу (Ларсмо, Уусикаупунки, Кустави) оказывается в воде, вне любого
полигона. Такой точке ищется берег — восемь направлений на 0,05°, 0,1°, 0,2°
и 0,3° — и решает первая же суша: губерния, рамка или чужое государство.
Запись помечается `extra["frame"] = "по берегу"`. Точку внутри чужого
государства так не двигают никогда: краковский приход лежит в Австро-
Венгрии, а не в воде, и к Келецкой губернии не подтянется.

Запись вне рамки не выбрасывается: она получает пометку `outside_bbox`
(«координаты вне территории РИ/СССР») и остаётся в выгрузке. Отчёт её в
«годно для подбора» не считает, на карте она видна. Правило проекта —
спорное помечается, а не удаляется молча, — а приход в Кракове не спорный,
но соседний: туда уходили на заработки и оттуда брали жён.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from .geo import in_bbox
from .schema import ContextRecord
from .sources.ghcn import Provinces

PROVINCES_FILE = "provinces_1897.geojson"
STATES_FILE = "state_borders.geojson"
# Так Россия и СССР называются в `state_borders.geojson` (CShapes, gwcode 365):
# один код на империю, РСФСР и Союз, по полигону на каждое изменение границ.
RUSSIA = "Россия (Советский Союз)"
# Государства, целиком лежащие на земле империи: что внутри них в любой
# год, то было и губерниями. Польши здесь нет — её межвоенные границы
# захватывают Галицию.
FRAME_STATES = frozenset({RUSSIA, "Финляндия", "Эстония", "Латвия", "Литва"})

OUTSIDE = "outside_bbox"

# Ширина полосы широты в индексе рёбер, градусы.
BAND = 0.1
# Шаги поиска берега для точки в море, градусы, и направления.
SHORE_STEPS = (0.05, 0.1, 0.2, 0.3)
_DIRECTIONS = tuple((math.sin(k * math.pi / 4), math.cos(k * math.pi / 4)) for k in range(8))


class Banded:
    """Многоугольник с рёбрами, разложенными по полосам широты.

    Губернию по точке находит `ghcn.Provinces` — губернии мелкие, и рамки
    фигуры хватает, чтобы перебрать немногих. Россия так не перебирается:
    в `state_borders.geojson` она семнадцатью фигурами по датам границ, в
    каждой около 21 000 вершин, и точку в Кракове, лежащую внутри рамки всех
    семнадцати, пришлось бы сверять со всеми 360 000 рёбрами. Живой сбор
    приходов потратил на это пять минут (312 секунд на 7 884 точки), с
    полосами — секунду.

    Луч из точки пересекает только рёбра, захватывающие её широту, поэтому
    рёбра раскладываются по полосам в 0,1° и проверяются только из своей
    полосы. Правило чёт-нечет — то же, что в `ghcn._in_ring`: дырки и
    острова одной фигуры учитываются сами, без разбора колец по ролям.
    """

    def __init__(self, rings: Iterable[list]) -> None:
        self.bands: dict[int, list[tuple[float, float, float, float]]] = {}
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if y1 == y2:
                    continue
                lo, hi = (y1, y2) if y1 < y2 else (y2, y1)
                for band in range(math.floor(lo / BAND), math.floor(hi / BAND) + 1):
                    self.bands.setdefault(band, []).append((x1, y1, x2, y2))

    def contains(self, lat: float, lon: float) -> bool:
        inside = False
        for x1, y1, x2, y2 in self.bands.get(math.floor(lat / BAND), ()):
            if (y1 > lat) != (y2 > lat):
                if lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
        return inside


def _rings(geometry: dict) -> list:
    """Все кольца фигуры одним списком; точки — пары (долгота, широта)."""
    kind = geometry.get("type")
    if kind == "Polygon":
        polygons = [geometry.get("coordinates") or []]
    elif kind == "MultiPolygon":
        polygons = geometry.get("coordinates") or []
    else:
        return []
    return [[(float(p[0]), float(p[1])) for p in ring]
            for polygon in polygons for ring in polygon if ring]


def load_states(path: Path) -> list[tuple[bool, Banded]]:
    """Все государства CShapes: (входит ли в рамку, фигура)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    shapes = [((f.get("properties") or {}).get("state") in FRAME_STATES,
               Banded(_rings(f.get("geometry") or {})))
              for f in payload.get("features", [])]
    if not any(framed for framed, _ in shapes):
        raise ValueError(f"{path}: нет ни одной фигуры «{RUSSIA}»")
    return shapes


class Frame:
    """Губернии 1897 года плюс земли империи и СССР по CShapes за все годы."""

    def __init__(self, provinces: Provinces, states: list[tuple[bool, Banded]]) -> None:
        self.provinces = provinces
        self.states = states

    @classmethod
    def load(cls, boundaries_dir: Path) -> "Frame":
        boundaries_dir = Path(boundaries_dir)
        return cls(Provinces.load(boundaries_dir / PROVINCES_FILE),
                   load_states(boundaries_dir / STATES_FILE))

    def _land(self, lat: float, lon: float) -> tuple[Optional[bool], Optional[str]]:
        """Чья это земля: (в рамке ли, губерния) или (None, None) — вода."""
        province = self.provinces.region_for(lat, lon)
        if province:
            return True, province
        hits = [framed for framed, shape in self.states if shape.contains(lat, lon)]
        if not hits:
            return None, None
        return any(hits), None

    def place(self, lat: float, lon: float) -> tuple[bool, Optional[str], bool]:
        """(в рамке ли, губерния 1897 года или None, найдена ли по берегу)."""
        province = self.provinces.region_for(lat, lon)
        if province:
            return True, province, False
        # Губернии проверяются раньше прямоугольника, и это не случайность:
        # Калишская губерния заходит западнее 18-го меридиана, до 17,6° в. д.,
        # и восемнадцать её приходов прямоугольник отсёк бы. Для государств
        # из CShapes он годится как быстрое «нет»: рамка в него вписана.
        if not in_bbox(lat, lon):
            return False, None, False
        framed, _ = self._land(lat, lon)
        if framed is not None:
            return framed, None, False
        for step in SHORE_STEPS:
            for dy, dx in _DIRECTIONS:
                framed, province = self._land(lat + dy * step, lon + dx * step)
                if framed is not None:
                    return framed, province, True
        return False, None, False

    def mark(self, records: Iterable[ContextRecord]) -> Counter:
        """Проставляет губернию и пометку `outside_bbox`. Возвращает счёт.

        `region` у записей Викиданных — подпись P131, а у прихода это его
        село или город, не губерния. Здесь поле получает губернию 1897 года
        или остаётся пустым, а подпись P131 остаётся в `place_text`.
        """
        counts: Counter = Counter()
        for rec in records:
            if not rec.has_point:
                counts["без точки"] += 1
                continue
            inside, province, shore = self.place(rec.lat, rec.lon)
            rec.region = province
            if shore:
                rec.extra["frame"] = "по берегу"
                counts["из них найдены по берегу"] += 1
            if province:
                counts["в губерниях 1897 года"] += 1
            elif inside:
                counts["в рамке, вне губерний 1897 года"] += 1
            else:
                rec.confidence = OUTSIDE
                counts["вне рамки РИ/СССР"] += 1
        return counts
