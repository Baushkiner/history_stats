"""Кирхшпили, уезды и мызы Эстляндии и северной Лифляндии до 1917 года: WFS Maa- ja Ruumiamet.

Зачем. Метрическая книга в Эстляндии и северной Лифляндии велась по
кирхшпилю (kihelkond) — лютеранскому приходу, который был и церковной, и
земской единицей. Деревня в метрике названа по мызе, к которой относилась
(«Kammeri küla, Kambja kihelkond»), а мыза — по кирхшпилю. Чтобы от деревни
предка дойти до книг, нужны границы кирхшпилей и точки мыз на одну дату — и
то и другое Земельный департамент Эстонии (с 2025 года Maa- ja Ruumiamet,
прежде Maa-amet) отдаёт открытым WFS «Ajalooline haldusjaotus».

Откуда. `teenus.maaamet.ee/ows/wms-ajalooline-haldus` — MapServer, 117
слоёв исторического деления. Нужны пять, все «kuni 1917» (до 1917 года):

* `kihelkond_1917` — 106 кирхшпилей полигонами: название (NIMI), уезд
  (MAAKOND) и губерния (KUBERMANG);
* `maakond_1917` — 9 уездов, `kubermang` — 2 губернии;
* `moisakeskus` — 2 513 мызных центров точками: эстонское и немецкое имя,
  тип мызы, кирхшпиль, главная мыза, первое упоминание («teateid 1469»),
  ссылки на регистр памятников, Mõisaportaal и регистр природы;
* `moisamaad` — 1 232 полигона мызных земель с той же заметкой, иногда
  длиннее («Teateid 1518; Liideti 1932 Hummuli mõisaga»).

Каждый слой приходит одним запросом GetFeature в GML 3.2 (сервер отдаёт
`numberMatched` целиком, постраничный обход не нужен). Координаты — в
L-EST97 (EPSG:3301), порядок осей «север, восток». **Сервер принимает
`srsName=EPSG:4326` и подписывает ответ как 4326, но координаты оставляет
в L-EST97** — проверено 04.11.2026 на WFS 2.0.0 и 1.1.0, в GML и в GeoJSON.
Поэтому сбор просит родную систему, а обратную проекцию Ламберта (2SP,
GRS80) считает сам (`lest97_to_wgs84`); тест сверяет её с PROJ и с мызой
Палмсе, чьи координаты известны независимо. Разбор GML — стандартной
библиотекой.

Что выходит:

* подложка `boundaries/parishes_ee_1917.geojson` — 106 кирхшпилей в WGS84
  с уездом и губернией по-эстонски и по-русски и с представительной точкой;
  сводку метрических книг прихода в неё дописывает сборщик из открытых
  данных Национального архива (`sources/rahvusarhiiv.py`);
* слой `manors_ee` — мызы точками с кирхшпилем, типом, первым упоминанием и
  ссылками.

Чего не берётся: волости 1922 и 1938 годов и сельсоветы 1959 года — тот же
сервис, но другая эпоха (записаны в журнал дискавери); полигоны мызных
земель в подложку не идут — из них берётся только заметка о мызе.

Права. «Teenus on tasuta»; условия картографических сервисов Maa- ja
Ruumiamet разрешают делать выписки и производные, публиковать и
распространять их со ссылкой на происхождение — название набора, дату
выписки и имя ведомства. Права на исторические единицы 1917–1989 годов, по
описанию сервиса, принадлежат Национальному архиву (Rahvusarhiiv). Ссылка
стоит в каждой записи и в шапке подложки.
"""

from __future__ import annotations

import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..io_formats import feature_collection
from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..periods import PRECISION_OPEN, Period, parse_period
from ..schema import ContextRecord, LayerSpec, clean_text

WFS_URL = "https://teenus.maaamet.ee/ows/wms-ajalooline-haldus"
CAPABILITIES_URL = f"{WFS_URL}?service=wfs&version=2.0.0&request=GetCapabilities"
TERMS_URL = ("https://geoportaal.maaamet.ee/est/Teenused/WMS-teenused/"
             "Maa-ameti-kaarditeenuste-kasutustingimused-p24.html")
DATASET_URL = "https://andmed.eesti.ee/"

SOURCE = "Maa- ja Ruumiamet (Земельный департамент Эстонии), WFS «Ajalooline haldusjaotus»"
LICENSE = (
    "условия картографических сервисов Maa- ja Ruumiamet: сервис бесплатный, выписки и "
    "производные, публикация и распространение разрешены со ссылкой на происхождение "
    "(название набора, дата выписки, Maa- ja Ruumiamet); права на исторические единицы "
    "1917–1989 годов, по описанию сервиса, принадлежат Rahvusarhiiv (Национальный архив "
    "Эстонии)"
)
CITATION = (
    "Ajalooline haldusjaotus (kihelkond, maakond, kubermang, mõisad kuni 1917). "
    f"Maa- ja Ruumiamet, WFS {WFS_URL}, väljavõte 04.11.2026"
)

PARISH_BOUNDARIES_EE = LayerSpec(
    slug="parishes_ee_1917",
    title="Кирхшпили Эстляндии и северной Лифляндии до 1917 года",
    group="faith",
    source=f"{SOURCE}, kihelkond_1917",
    license=LICENSE,
    description=(
        "106 кирхшпилей (лютеранских приходов) полигонами на 1917 год с уездом и губернией, "
        "плюс сводка метрических книг прихода из открытых данных Национального архива. "
        "Отвечает, к какому приходу относилась деревня или мыза — то есть в какой книге "
        "искать запись о предке."
    ),
    url=CAPABILITIES_URL,
    status="harvested",
    expected_rows=106,
    gives_records=False,
)

MANORS_EE = LayerSpec(
    slug="manors_ee",
    title="Мызы Эстляндии и северной Лифляндии до 1917 года",
    group="admin",
    source=f"{SOURCE}, moisakeskus и moisamaad",
    license=LICENSE,
    description=(
        "2 513 мызных центров с эстонским и немецким именем, типом мызы, кирхшпилем и "
        "первым упоминанием. Отвечает на средний шаг цепочки «деревня → мыза → кирхшпиль»: "
        "деревня в метрике названа по мызе, а мыза лежит в приходе, книги которого и надо "
        "смотреть."
    ),
    url=CAPABILITIES_URL,
    status="harvested",
    expected_rows=2513,
)

# Горизонт слоя мыз. Слои сервера называются «… kuni 1917» — состояние до
# 1917 года, и это рамка источника, а не дата упразднения мызы (её источник
# не даёт; у большинства мыз это земельная реформа 1919 года). Второй конец
# записи берётся отсюда и помечается `open`.
LAYER_HORIZON = 1917


class MaaametError(RuntimeError):
    """Сервис не ответил или ответил не в том виде, какой записан в коде."""


# --- слои сервиса ----------------------------------------------------------
# Записаны в коде и сверяются с сервисом на --check: имя, заголовок, поля,
# число объектов. Разошлось — остановка: набор переиздали, и прежде чем
# собирать, надо понять, что в нём поменялось.

@dataclass(frozen=True)
class WfsLayer:
    name: str                 # имя без приставки `ms:`
    title: str                # заголовок слоя в GetCapabilities, дословно
    count: int                # число объектов, измеренное 04.11.2026
    fields: frozenset         # поля, на которых держится разбор
    geometry: str             # polygon | point


PARISH_LAYER = WfsLayer("kihelkond_1917", "Kihelkond kuni 1917", 106,
                        frozenset({"NIMI", "MAAKOND", "KUBERMANG"}), "polygon")
COUNTY_LAYER = WfsLayer("maakond_1917", "Maakond kuni 1917", 9,
                        frozenset({"NIMI", "KUBERMANG"}), "polygon")
GOVERNORATE_LAYER = WfsLayer("kubermang", "Kubermang kuni 1917", 2,
                             frozenset({"NIMI"}), "polygon")
MANOR_LAYER = WfsLayer("moisakeskus", "Mõisad kuni 1917", 2513,
                       frozenset({"NIMI", "SKS_NIMI", "TYYP", "KIHELKOND", "MARKUS",
                                  "URL_MUINAS", "URL_MOISAP"}), "point")
MANOR_LAND_LAYER = WfsLayer("moisamaad", "Mõisamaa kuni 1917", 1232,
                            frozenset({"NIMI", "SKS_NIMI", "KIHELKOND", "MARKUS"}), "polygon")
LAYERS = (PARISH_LAYER, COUNTY_LAYER, GOVERNORATE_LAYER, MANOR_LAYER, MANOR_LAND_LAYER)

# Уезды 1917 года по-эстонски → уезды переписи 1897 года, как они названы в
# `districts_1897.geojson` (RISTAT). Соответствие один к одному: эстонский
# maakond и есть бывший Kreis. Губернии — так же.
COUNTY_UEZD = {
    "Harju": "Ревельский уезд", "Lääne": "Гапсальский уезд", "Viru": "Везенбергский уезд",
    "Järva": "Вейсенштейнский уезд", "Tartu": "Юрьевский уезд", "Viljandi": "Феллинский уезд",
    "Pärnu": "Перновский уезд", "Võru": "Верроский уезд", "Saare": "Эзельский уезд",
}
GOVERNORATES = {"Eestimaa": "Эстляндская губерния", "Liivimaa": "Лифляндская губерния"}

# Типы мыз (поле TYYP) — закрытый словарь сервиса на 04.11.2026. Незнакомый
# тип не теряется: идёт в категорию как есть.
MANOR_TYPES = {
    "eramõis": "частная (рыцарская) мыза",
    "karjamõis": "мыза-фольварк",
    "kõrvalmõis": "побочная мыза",
    "kirikumõis": "пасторат (церковная мыза)",
    "riigimõis": "казённая мыза",
    "poolmõis": "полумыза",
    "linnamõis": "городская мыза",
    "metsamõis": "лесная мыза",
}
# Кирхшпиль в поле KIHELKOND мызы назван иначе, чем полигон того же
# кирхшпиля: «Pärnu Elisabethi» — сельский приход Пярну, в слое кирхшпилей
# он «Pärnu». Без этого 32 мызы выглядели бы стоящими не в своём приходе.
PARISH_NAME_ALIASES = {"Pärnu Elisabethi": "Pärnu"}
# Насколько точно стоит точка мызы (поле TAPSUS).
MANOR_PRECISION = {
    "peahoone": "главное здание",
    "peahoone ase": "место главного здания",
    "mõisasüda": "мызный центр",
    "määramata": "не определено",
}


# --- L-EST97 → WGS84 ------------------------------------------------------
# Коническая равноугольная проекция Ламберта с двумя стандартными
# параллелями (EPSG:3301), эллипсоид GRS80. Датум ETRS89 от WGS84 отличается
# на дециметры — для карты приходов это ноль.

_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_E = math.sqrt(_E2)
_LAT1 = math.radians(59 + 20 / 60)
_LAT2 = math.radians(58.0)
_LAT0 = math.radians(57.51755393055556)
_LON0 = math.radians(24.0)
_X0, _Y0 = 500000.0, 6375000.0


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - _E2 * s * s)


def _t(phi: float) -> float:
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - _E * s) / (1 + _E * s)) ** (_E / 2)


_N = (math.log(_m(_LAT1)) - math.log(_m(_LAT2))) / (math.log(_t(_LAT1)) - math.log(_t(_LAT2)))
_AF = _A * _m(_LAT1) / (_N * _t(_LAT1) ** _N)
_R0 = _AF * _t(_LAT0) ** _N


def lest97_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """L-EST97 (восток `x`, север `y`, метры) → (широта, долгота) в градусах."""
    dx, dy = x - _X0, _R0 - (y - _Y0)
    r = math.copysign(math.hypot(dx, dy), _N)
    t = (r / _AF) ** (1 / _N)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(20):
        s = math.sin(phi)
        nxt = math.pi / 2 - 2 * math.atan(t * ((1 - _E * s) / (1 + _E * s)) ** (_E / 2))
        if abs(nxt - phi) < 1e-12:
            phi = nxt
            break
        phi = nxt
    return math.degrees(phi), math.degrees(math.atan2(dx, dy) / _N + _LON0)


def wgs84_to_lest97(lat: float, lon: float) -> tuple[float, float]:
    """Обратное к `lest97_to_wgs84`: нужно тестам и для точек городов."""
    r = _AF * _t(math.radians(lat)) ** _N
    theta = _N * (math.radians(lon) - _LON0)
    return _X0 + r * math.sin(theta), _Y0 + _R0 - r * math.cos(theta)


# Рамка L-EST97 по EPSG с запасом: север 6,30–6,70 млн м, восток 0,30–0,80
# млн м. Пара вне неё — не L-EST97: сервер перепроецировал или поменял оси.
_NORTHING = (6.30e6, 6.70e6)
_EASTING = (3.0e5, 8.0e5)


def lest97_pair(a: float, b: float) -> tuple[float, float]:
    """Пара из GML → (восток, север). Порядок осей определяется по величине.

    В Эстонии север всегда больше шести миллионов метров, восток — меньше
    миллиона, поэтому перепутать оси нельзя, а угадывать их по `srsName`
    незачем: сервер подписывает ответ системой, в которой его не отдаёт.
    """
    north, east = (a, b) if a > b else (b, a)
    if not (_NORTHING[0] <= north <= _NORTHING[1] and _EASTING[0] <= east <= _EASTING[1]):
        raise MaaametError(
            f"координата ({a}, {b}) не похожа на L-EST97: сервис отдал другую систему "
            "координат — проверьте srsName и поправьте разбор, а не подгоняйте его"
        )
    return east, north


# --- разбор GML -------------------------------------------------------------

_MS = "{http://mapserver.gis.umn.edu/mapserver}"
_WFS = "{http://www.opengis.net/wfs/2.0}"
_GML = "{http://www.opengis.net/gml/3.2}"
_OWS = "{http://www.opengis.net/ows/1.1}"


@dataclass
class Feature:
    """Объект слоя: атрибуты и геометрия в L-EST97 (x — восток, y — север).

    `polygons` — список полигонов, каждый — список колец, первое внешнее.
    """

    fid: str
    props: dict
    polygons: list = field(default_factory=list)
    point: Optional[tuple] = None

    def get(self, name: str) -> Optional[str]:
        return self.props.get(name)


def _coords(text: Optional[str]) -> list[tuple[float, float]]:
    values = [float(v) for v in (text or "").split()]
    if len(values) % 2:
        raise MaaametError(f"нечётное число координат в posList ({len(values)})")
    return [lest97_pair(values[i], values[i + 1]) for i in range(0, len(values), 2)]


def _ring(element) -> list[tuple[float, float]]:
    pos_list = element.find(f".//{_GML}posList")
    if pos_list is not None:
        return _coords(pos_list.text)
    return [p for pos in element.iter(f"{_GML}pos") for p in _coords(pos.text)]


def _polygon(element) -> list[list[tuple[float, float]]]:
    rings = []
    for part in ("exterior", "interior"):
        for boundary in element.findall(f"{_GML}{part}"):
            ring = _ring(boundary)
            if len(ring) >= 4:
                rings.append(ring)
    return rings


def parse_gml(data: bytes, layer: str) -> list[Feature]:
    """Ответ GetFeature (GML 3.2) → объекты слоя `layer`.

    Сервисная ошибка (`ows:ExceptionReport`) пересказывается ошибкой
    источника, а не падает на поиске объектов.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise MaaametError(f"{layer}: ответ не разбирается как XML ({exc})") from exc
    if root.tag == f"{_OWS}ExceptionReport":
        text = " ".join(t.strip() for t in root.itertext() if t.strip())
        raise MaaametError(f"{layer}: сервис ответил ошибкой: {text[:300]}")
    out = []
    for member in root.iter(f"{_WFS}member"):
        node = member.find(f"{_MS}{layer}")
        if node is None:
            continue
        props, polygons, point = {}, [], None
        for child in node:
            name = child.tag[len(_MS):] if child.tag.startswith(_MS) else None
            if name is None:
                continue
            if name == "msGeometry":
                for geom in child:
                    if geom.tag == f"{_GML}Point":
                        coords = _ring(geom)
                        point = coords[0] if coords else None
                    else:
                        found = ([geom] if geom.tag == f"{_GML}Polygon"
                                 else list(geom.iter(f"{_GML}Polygon")))
                        polygons.extend(r for r in (_polygon(p) for p in found) if r)
            else:
                props[name] = clean_text(child.text)
        out.append(Feature(fid=node.get(f"{_GML}id") or "", props=props,
                           polygons=polygons, point=point))
    return out


def parse_capabilities(data: bytes) -> dict[str, str]:
    """GetCapabilities → {имя слоя без `ms:`: заголовок}."""
    root = ET.fromstring(data)
    wfs = "{http://www.opengis.net/wfs/2.0}"
    out = {}
    for ft in root.iter(f"{wfs}FeatureType"):
        name = (ft.findtext(f"{wfs}Name") or "").split(":")[-1]
        out[name] = (ft.findtext(f"{wfs}Title") or "").strip()
    return out


def parse_hits(data: bytes) -> Optional[int]:
    """Ответ GetFeature с `resultType=hits` → число объектов слоя."""
    m = re.search(rb'numberMatched="(\d+)"', data)
    return int(m.group(1)) if m else None


def check_layer(layer: WfsLayer, features: list[Feature], matched: Optional[int] = None) -> None:
    """Число объектов, поля и геометрия совпадают с записанным в коде.

    `matched` — число объектов из ответа `resultType=hits`: проба смотрит
    два объекта слоя, а не скачивает его целиком.
    """
    count = len(features) if matched is None else matched
    if count != layer.count:
        raise MaaametError(
            f"{layer.name}: {count} объектов, а не {layer.count} (замер 04.11.2026) — "
            "набор переиздан; посмотрите, что изменилось, и поправьте WfsLayer.count"
        )
    seen = set().union(*(f.props.keys() for f in features)) if features else set()
    missing = sorted(layer.fields - seen)
    if missing:
        raise MaaametError(f"{layer.name}: нет полей {missing}; есть {sorted(seen)}")
    if layer.geometry == "point":
        bad = [f.fid for f in features if f.point is None]
    else:
        bad = [f.fid for f in features if not f.polygons]
    if bad:
        raise MaaametError(f"{layer.name}: у {len(bad)} объектов нет геометрии ({bad[:5]})")


# --- геометрия в метрах -----------------------------------------------------

def ring_area(ring: list) -> float:
    """Площадь кольца по формуле Гаусса, со знаком (против часовой — плюс)."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2


def polygon_area(rings: list) -> float:
    """Площадь полигона: внешнее кольцо минус дырки, м²."""
    if not rings:
        return 0.0
    return abs(ring_area(rings[0])) - sum(abs(ring_area(r)) for r in rings[1:])


def in_rings(x: float, y: float, rings: list) -> bool:
    """Точка внутри полигона: правило чёт-нечет по всем кольцам сразу."""
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def bounds(polygons: list) -> tuple[float, float, float, float]:
    xs = [x for rings in polygons for ring in rings for x, _ in ring]
    ys = [y for rings in polygons for ring in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def contains(polygons: list, x: float, y: float, box: Optional[tuple] = None) -> bool:
    box = box or bounds(polygons)
    if not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
        return False
    return any(in_rings(x, y, rings) for rings in polygons)


def _centroid(ring: list) -> Optional[tuple[float, float]]:
    a = ring_area(ring)
    if abs(a) < 1e-9:
        return None
    cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return cx / (6 * a), cy / (6 * a)


def point_on_surface(polygons: list) -> tuple[float, float]:
    """Представительная точка: внутри фигуры, по возможности в её центре.

    Берётся наибольшая часть (у прибрежного кирхшпиля — материк, а не
    остров). Если центр тяжести этой части лежит внутри неё — он и есть
    точка. Если нет (подкова, вытянутый берег), проводится горизонталь через
    центр и берётся середина самого широкого внутреннего отрезка — так же
    поступает `ST_PointOnSurface`. Точка всегда внутри: на карте приход не
    окажется в соседнем.
    """
    rings = max(polygons, key=polygon_area)
    c = _centroid(rings[0])
    if c is not None and in_rings(c[0], c[1], rings):
        return c
    xs_box = bounds([rings])
    y = c[1] if c is not None else (xs_box[1] + xs_box[3]) / 2
    for shift in (0.0, 0.1, -0.1, 0.2, -0.2, 0.3, -0.3):
        yy = y + shift * (xs_box[3] - xs_box[1])
        cuts = sorted(
            x1 + (yy - y1) * (x2 - x1) / (y2 - y1)
            for ring in rings
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])
            if (y1 > yy) != (y2 > yy)
        )
        spans = [(cuts[i], cuts[i + 1]) for i in range(0, len(cuts) - 1, 2)]
        if spans:
            left, right = max(spans, key=lambda s: s[1] - s[0])
            return (left + right) / 2, yy
    raise MaaametError("у фигуры не нашлось внутренней точки")


@dataclass
class Area:
    """Полигон с готовой рамкой — для частых проверок «точка внутри»."""

    name: str
    polygons: list
    box: tuple
    feature: Optional[Feature] = None

    @classmethod
    def of(cls, feature: Feature, name: Optional[str] = None) -> "Area":
        return cls(name or feature.get("NIMI") or feature.fid, feature.polygons,
                   bounds(feature.polygons), feature)

    def contains(self, x: float, y: float) -> bool:
        return contains(self.polygons, x, y, self.box)


def area_at(areas: Iterable[Area], x: float, y: float) -> Optional[Area]:
    for area in areas:
        if area.contains(x, y):
            return area
    return None


# --- кирхшпили ----------------------------------------------------------------

@dataclass
class Parish:
    """Кирхшпиль 1917 года: всё, что подложке и слою книг нужно знать о нём."""

    name: str
    county_src: Optional[str]       # MAAKOND, как в источнике
    county: Optional[str]           # уезд 1917 года по полигону maakond_1917
    governorate_src: Optional[str]  # KUBERMANG, как в источнике
    polygons: list                  # L-EST97
    x: float                        # представительная точка, L-EST97
    y: float
    lat: float
    lon: float
    area_km2: float
    fid: str = ""

    @property
    def uezd(self) -> Optional[str]:
        return COUNTY_UEZD.get(self.county or "")

    @property
    def region(self) -> Optional[str]:
        return GOVERNORATES.get(self.governorate_src or "")


def build_parishes(parish_features: list[Feature], county_features: list[Feature]) -> list[Parish]:
    """Кирхшпили с представительной точкой и уездом по полигону 1917 года.

    Уезд берётся из слоя уездов, а не из поля MAAKOND: у четырёх кирхшпилей
    Хийумаа там стоит «Hiiu», а такого уезда до 1946 года не было — остров
    входил в Гапсальский (Läänemaa). Поле источника остаётся в `county_src`.
    """
    counties = [Area.of(f) for f in county_features]
    out = []
    for feature in parish_features:
        x, y = point_on_surface(feature.polygons)
        lat, lon = lest97_to_wgs84(x, y)
        county = area_at(counties, x, y)
        out.append(Parish(
            name=feature.get("NIMI") or feature.fid,
            county_src=feature.get("MAAKOND"),
            county=county.name if county else None,
            governorate_src=feature.get("KUBERMANG"),
            polygons=feature.polygons,
            x=x, y=y, lat=round(lat, 6), lon=round(lon, 6),
            area_km2=round(sum(polygon_area(r) for r in feature.polygons) / 1e6, 1),
            fid=feature.fid,
        ))
    return out


def geojson_geometry(polygons: list, digits: int = 5) -> dict:
    """Полигоны L-EST97 → GeoJSON (долгота, широта), 5 знаков — около метра."""
    def ring(r):
        pts = []
        for x, y in r:
            lat, lon = lest97_to_wgs84(x, y)
            pts.append([round(lon, digits), round(lat, digits)])
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return pts

    shapes = [[ring(r) for r in rings] for rings in polygons]
    if len(shapes) == 1:
        return {"type": "Polygon", "coordinates": shapes[0]}
    return {"type": "MultiPolygon", "coordinates": shapes}


def parish_feature(parish: Parish, registers: Optional[list] = None,
                   manors: Optional[int] = None) -> dict:
    """Кирхшпиль → GeoJSON-фича подложки.

    `registers` — сводки фондов прихода из открытых данных Национального
    архива (их собирает `rahvusarhiiv.parish_summary`); `manors` — сколько
    мызных центров слоя `manors_ee` лежит в кирхшпиле.
    """
    props = {
        "name": parish.name,
        "county": parish.county,
        "uezd": parish.uezd,
        "governorate": parish.governorate_src,
        "region": parish.region,
        "point": [parish.lon, parish.lat],
        "area_km2": parish.area_km2,
        "wfs_id": parish.fid,
    }
    if parish.county_src and parish.county_src != parish.county:
        props["county_src"] = parish.county_src
    if manors is not None:
        props["manors"] = manors
    props["registers"] = registers or []
    return {"type": "Feature", "geometry": geojson_geometry(parish.polygons),
            "properties": props}


def boundaries_collection(feats: list[dict]) -> dict:
    return feature_collection(
        PARISH_BOUNDARIES_EE.slug, feats, license=LICENSE, source=PARISH_BOUNDARIES_EE.source,
        citation=CITATION, url=CAPABILITIES_URL,
        extra={
            "period": "kuni 1917",
            "point_note": ("point — представительная точка полигона (центр территории "
                           "кирхшпиля), а не церковь"),
            "registers_source": ("Rahvusarhiiv, avaandmed (apeEAD, snapshot 31.01.2020), "
                                 "https://www.ra.ee/apps/opendata/"),
        },
    )


def manor_land_feature(feature: Feature) -> dict:
    """Полигон мызных земель → GeoJSON-фича (подложка по ключу `--manor-lands`).

    С ним деревня с координатой сводится к мызе точкой в полигоне, а не
    ближайшим мызным центром. Замер 04.11.2026: мызные земли в среднем
    (медиана) тянутся на 13,6 км, и у 617 полигонов из 1 232 ближайший к
    внутренней точке мызный центр носит другое имя — по ближайшему центру
    деревня в половине случаев досталась бы соседу.
    """
    props = {
        "name": feature.get("NIMI"),
        "name_de": feature.get("SKS_NIMI"),
        "aliases": feature.get("ALIAS"),
        "parish": feature.get("KIHELKOND"),
        "governorate": feature.get("KUBERMANG"),
        "region": GOVERNORATES.get(feature.get("KUBERMANG") or ""),
        "type": feature.get("TYYP"),
        "note": feature.get("MARKUS"),
        "wfs_id": feature.fid,
    }
    return {"type": "Feature", "geometry": geojson_geometry(feature.polygons),
            "properties": {k: v for k, v in props.items() if v}}


def manor_lands_collection(feats: list[dict]) -> dict:
    return feature_collection(
        "manor_lands_ee_1917", feats, license=LICENSE, source=f"{SOURCE}, moisamaad",
        citation=CITATION, url=CAPABILITIES_URL, extra={"period": "kuni 1917"})


# --- мызы ----------------------------------------------------------------------

_ET_PARTS = {"algul": "начало", "alguses": "начало", "algusest": "начало",
             "keskel": "середина", "keskelt": "середина",
             "lõpul": "конец", "lõpus": "конец", "lõpust": "конец"}
_ET_HALVES = {"1": "первая половина", "2": "вторая половина"}
_RE_CENTURY = re.compile(
    r"(\d{1,2})\.\s*sajandi(?:l|st|\s+(?:(\d)\.\s*(?:poolel|poolest|veerandil|veerandist)"
    r"|(algul|alguses|algusest|keskel|keskelt|lõpul|lõpus|lõpust)))?")
_RE_YEAR = re.compile(r"\b(1[0-9]{3})\b")
# Слова, которыми заметка называет начало: «teateid» (известия), «rajatud»
# (основана), «eraldatud» (выделена из другой мызы), «asutatud» (учреждена),
# «loodi» (создана), «mainitud» (упомянута).
_RE_START = re.compile(r"\b(?:teateid|rajatud|eraldatud|asutatud|loodi|loodud|mainitud)\b")
_RE_DECADE = re.compile(r"\b(1[0-9]{2}0)-?ndail")


def estonian_period(text: Optional[str]) -> Optional[str]:
    """Первая фраза заметки о мызе → датировка по-русски для `parse_period`.

    «teateid 1469» → «1469», «rajatud 17. sajandi 1. poolel» → «первая
    половина 17 в.», «rajatud 1426 ja 1497 vahel» → «1426–1497»,
    «rajatud 1840-ndail» → «1840-е», «rajatud umbes 1700» → «около 1700»,
    «eraldatud Räpinast 1600 ja 1630 vahel» → «1600–1630». Второй разборщик
    датировок проекту не нужен: достаточно сказать общему те же слова
    по-русски. Неразобранное возвращается как None, и запись помечается.
    """
    s = clean_text(text)
    if not s:
        return None
    first = s.split(";")[0].lower()
    # Год в заметке — не всегда начало: «Eeru mõisa kinnistu liideti 1907»
    # (земли присоединены в 1907 году), «sama ka 1867 plaanil» (есть на плане
    # 1867 года). Началом считается только фраза со словом о начале:
    # известия, основание, выделение из другой мызы.
    if not _RE_START.search(first):
        return None
    approx = "umbes" in first
    decade = _RE_DECADE.search(first)
    if decade:
        return ("около " if approx else "") + f"{decade.group(1)}-е"
    between = re.search(r"(1[0-9]{3})\.?\s+ja\s+(1[0-9]{3})\.?(?:\s*a\.?)?\s+vahel", first)
    if between:
        return f"{between.group(1)}–{between.group(2)}"
    span = re.search(r"\b(1[0-9]{3})\s*-\s*(1[0-9]{3})\b", first)
    if span:
        return f"{span.group(1)}–{span.group(2)}"
    century = _RE_CENTURY.search(first)
    year = _RE_YEAR.search(first)
    if century and (not year or century.start() < year.start()):
        n = int(century.group(1))
        half, part = century.group(2), century.group(3)
        tail = re.search(r"-\s*(\d{1,2})\.?\s*sajandi\s+(algul|alguses)", first[century.end():])
        if half and "veerand" in first[century.start():century.end()]:
            # Четверть века общий разборщик не знает; огрубляем до половины —
            # интервал расширяется, а не сужается.
            return f"{_ET_HALVES['1' if int(half) <= 2 else '2']} {n} в."
        if half:
            return f"{_ET_HALVES.get(half, '')} {n} в.".strip()
        if part:
            word = _ET_PARTS[part]
            if tail:
                return f"{word} {n} в. — начало {int(tail.group(1))} в."
            return f"{word} {n} в."
        return f"{n} в."
    if year:
        return ("около " if approx else "") + year.group(1)
    return None


def manor_period(note: Optional[str]) -> Period:
    """Первое упоминание мызы как `Period`; пусто — `unknown`."""
    raw = "" if note is None else str(note)
    text = estonian_period(note)
    if text is None:
        return Period(None, None, "unknown", False, raw)
    period = parse_period(text)
    return Period(period.year_from, period.year_to, period.precision, period.approx, raw)


def wfs_feature_url(layer: str, fid: str) -> str:
    """Ссылка на объект в самом сервисе: тот же GetFeature по номеру объекта."""
    query = urllib.parse.urlencode({
        "service": "wfs", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"ms:{layer}", "featureID": fid,
    })
    return f"{WFS_URL}?{query}"


def manor_record(feature: Feature, *, parishes: list[Area], counties: list[Area],
                 lands: list[Area], spec: LayerSpec = MANORS_EE) -> ContextRecord:
    """Мызный центр → запись схемы.

    Датировка: первое упоминание — измеренный конец, второй — горизонт слоя
    источника («kuni 1917»), поэтому точность `open`. Когда мыза упразднена,
    источник не говорит, и конец не выдумывается: он виден в `extra` как
    взятый из рамки. Заметки у мызного центра нет — берётся заметка
    полигона мызных земель с тем же именем, внутри которого стоит точка.
    Нет нигде — запись остаётся без даты (`no_date`).
    """
    x, y = feature.point
    lat, lon = lest97_to_wgs84(x, y)
    name = feature.get("NIMI")
    german = feature.get("SKS_NIMI")
    if name and name.lower() == "teadmata":
        name = None
    title = name or german or "мыза без названия"
    if name and german:
        title = f"{name} ({german})"

    land = next((a for a in lands if a.contains(x, y)
                 and (a.feature.get("NIMI") or "").lower() == (feature.get("NIMI") or "").lower()),
                None)
    note = feature.get("MARKUS")
    note_from = "moisakeskus"
    if not note and land is not None and land.feature.get("MARKUS"):
        note, note_from = land.feature.get("MARKUS"), "moisamaad"
    period = manor_period(note)

    parish_src = feature.get("KIHELKOND")
    parish_geo = area_at(parishes, x, y)
    county = area_at(counties, x, y)
    kind = feature.get("TYYP")

    extra: dict = {"wfs_id": feature.fid, "parish_src": parish_src}
    if parish_geo is not None:
        extra["parish"] = parish_geo.name
        if parish_src and PARISH_NAME_ALIASES.get(parish_src, parish_src) != parish_geo.name:
            extra["parish_mismatch"] = True
    if german:
        extra["name_de"] = german
    if feature.get("ALIAS"):
        extra["aliases"] = feature.get("ALIAS")
    if kind:
        extra["type_et"] = kind
    if feature.get("PEAMOIS"):
        extra["main_manor"] = feature.get("PEAMOIS")
    precision = feature.get("TAPSUS")
    if precision:
        extra["point_precision"] = MANOR_PRECISION.get(precision, precision)
    for key, field_name in (("muinas", "URL_MUINAS"), ("moisaportaal", "URL_MOISAP"),
                            ("eelis", "URL_EELIS")):
        if feature.get(field_name):
            extra[key] = feature.get(field_name)
    if note:
        extra["note_from"] = note_from
    if land is not None:
        extra["land_wfs_id"] = land.feature.fid
        if land.feature.get("MARKUS") and land.feature.get("MARKUS") != note:
            extra["land_note"] = land.feature.get("MARKUS")

    confidence = "ok"
    year_from = year_to = None
    precision_out = "unknown"
    if period.ok:
        year_from = period.year_from
        year_to = max(LAYER_HORIZON, year_from)
        precision_out = PRECISION_OPEN
        extra["first_mention"] = [period.year_from, period.year_to]
        extra["first_mention_precision"] = period.precision
        extra["year_to_from"] = "рамка слоя источника «Mõisad kuni 1917»"
    else:
        confidence = "no_date"

    return spec.new_record(
        title=title,
        category=MANOR_TYPES.get((kind or "").lower(), kind) if kind != "andmed puuduvad" else None,
        lat=round(lat, 6), lon=round(lon, 6),
        place_text=", ".join(p for p in (parish_src and f"кирхшпиль {parish_src}",
                                         county and f"уезд {county.name}") if p) or None,
        region=GOVERNORATES.get(feature.get("KUBERMANG") or ""),
        district=COUNTY_UEZD.get(county.name) if county else None,
        year_from=year_from, year_to=year_to,
        date_precision=precision_out,
        date_approx=bool(period.approx),
        period_raw=note,
        summary=manor_summary(kind, parish_src, period, note),
        url=wfs_feature_url(MANOR_LAYER.name, feature.fid),
        source_id=feature.fid,
        confidence=confidence,
        extra=extra,
    )


def manor_summary(kind: Optional[str], parish: Optional[str], period: Period,
                  note: Optional[str]) -> str:
    """Своя фраза из полей: тип, кирхшпиль, первое упоминание."""
    parts = []
    label = MANOR_TYPES.get((kind or "").lower())
    parts.append(label.capitalize() if label else "Мыза")
    if parish:
        parts[-1] += f" в кирхшпиле {parish}"
    if period.ok:
        if period.year_from == period.year_to:
            parts.append(f"первое упоминание или основание — {period.year_from} год")
        else:
            parts.append(f"первое упоминание или основание — {period.year_from}–"
                         f"{period.year_to} годы")
    elif note:
        parts.append("заметка источника без даты")
    else:
        parts.append("датировки в источнике нет")
    return "; ".join(parts) + "."


# --- сеть ------------------------------------------------------------------------

class Client:
    """GetFeature и GetCapabilities: подпись, пауза, повтор на 429/5xx.

    Слоёв пять, и каждый приходит одним запросом — пауза здесь не ради
    объёма, а по условиям сервиса: Maa- ja Ruumiamet следит за нагрузкой и
    закрывает адреса, которые мешают другим.
    """

    def __init__(self, *, pause_sec: float = 3.0, attempts: int = 4, timeout: int = 300) -> None:
        self.pause_sec = pause_sec
        self.attempts = attempts
        self.timeout = timeout
        self._last = 0.0
        self.requests = 0

    def get(self, url: str) -> bytes:
        error: Optional[Exception] = None
        for attempt in range(self.attempts):
            self._last = wait_for_pause(self._last, self.pause_sec)
            self.requests += 1
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES:
                    raise MaaametError(f"{url}: HTTP {exc.code}") from exc
                error = exc
            except (urllib.error.URLError, OSError) as exc:
                error = exc
            time.sleep(self.pause_sec * (attempt + 1))
        raise MaaametError(f"{url}: не ответил за {self.attempts} попыток ({error})")

    def capabilities(self) -> bytes:
        return self.get(CAPABILITIES_URL)

    def layer(self, layer: WfsLayer, **params) -> bytes:
        """Слой целиком одним запросом (`count=2` — проба, `resultType=hits` — число)."""
        query = urllib.parse.urlencode({"service": "wfs", "version": "2.0.0",
                                        "request": "GetFeature", "typeNames": f"ms:{layer.name}",
                                        **params})
        return self.get(f"{WFS_URL}?{query}")
