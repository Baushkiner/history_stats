"""Железные дороги по срезам 1850–1970 годов: HGISE, Марти-Хеннеберг (Льейда).

Зачем этот слой. «Пошёл на заработки», «переехал в город», «призван и
отправлен» — всё это в конце XIX века решалось тем, есть ли рядом железная
дорога и с какого времени. Хронология участков МПС (istmat) даёт годы, но не
линии; Викиданные — линии без формы. Набор HGISE даёт именно форму сети, но
не год открытия: состояние каждого отрезка на 1850, 1890, 1930, 1970, 2000 и
2010 годы.

Набор. HGISE — Historical GIS of Europe, Университет Льейды (Х. Марти-
Хеннеберг, М. Морильяс-Торне): база железных дорог Европы 1830–2010 годов,
состояние линий по десятилетиям. В открытом доступе — не вся серия, а
допматериалы к главе «The Expansion of Railways in Europe» (Springer, 2023,
doi:10.1007/978-3-031-21731-9_4): zip на 21 МБ, в нём `Europe_railways.gpkg`
— 13 600 отрезков, 298 170 км, проекция ETRS89-LAEA (EPSG:3035), поля
`TYPE_1850` … `TYPE_2010` и длина. Десятилетней серии в сети нет: на сайте
проекта она выложена картинками, данные — по запросу у проекта.

Сколько взято. Отрезок берётся, если его середина — в рамке РИ/СССР
(`frame.Frame`). Восточная граница набора — около 31° в. д.: Европейской
России, Белоруссии и Украины в нём нет, из империи — Финляндия, Эстония,
Латвия, Литва, восток Царства Польского и западная окраина Белоруссии и
Украины в межвоенных границах.

Обозначения состояния — как в наборе: `ML` — основная линия (так набор
описан в статье Морильяса-Торне, 2012: основная сеть нормальной колеи, в
Финляндии и Прибалтике — своей колеи), `NE` — линии нет. Остальные коды
(`SL`, `FO`, `FL`, `UL`) расшифровки в наборе не имеют и сохраняются как есть.

Годы. Года открытия в наборе нет, и выдумывать его нельзя: отрезок, которого
нет в 1850 году и который есть в 1890-м, открыт **между 1851 и 1890 годами**
— так и записано (`opened_from`, `opened_to`). То же с закрытием. Это грубо,
но честно; поточнее — хронология istmat по названиям станций.

Права. «© 2023 The Author(s), under exclusive license to Springer Nature»,
открытой лицензии нет; согласие владельца сообщено владельцем проекта
24.11.2026. Слой — подложка (`boundaries/railways_hgise.geojson`), записей
не даёт: у линии нет точки, по которой подбирается контекст.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from ..schema import LayerSpec
from .huri import simplify

ZIP_URL = ("https://static-content.springer.com/esm/chp%3A10.1007%2F978-3-031-21731-9_4/"
           "MediaObjects/504586_1_En_4_MOESM2_ESM.zip")
MEMBER = "Data/Europe_railways.gpkg"
MEMBER_SIZE = 7147520
TABLE = "Europe_railways"
CHAPTER_DOI = "10.1007/978-3-031-21731-9_4"
PROJECT_URL = "https://europa.udl.cat/projects/european-railways/"

SNAPSHOTS = (1850, 1890, 1930, 1970, 2000, 2010)
FIELDS = {f"TYPE_{y}" for y in SNAPSHOTS} | {"Length_km"}
# Срезы, которые идут в слой: 2000 и 2010 годы — за горизонтом проекта, но
# закрытие линии до 1970 года без них не отличить от «есть и сейчас».
YEAR_LIMIT = 1970
STATE_RU = {"ML": "основная линия", "NE": "линии нет"}
ABSENT = "NE"

LICENSE = (
    "© 2023 The Author(s), under exclusive license to Springer Nature (допматериалы к главе "
    "J. Martí-Henneberg, «The Expansion of Railways in Europe»): открытой лицензии нет; "
    "собрано с согласия владельца, полученного владельцем проекта (сообщено 24.11.2026)"
)
SOURCE = ("HGISE (Historical GIS of Europe), Университет Льейды: Х. Марти-Хеннеберг, "
          "М. Морильяс-Торне; допматериалы Springer к главе «The Expansion of Railways in "
          "Europe» (2023)")
CITATION = (
    "Martí-Henneberg, J. The Expansion of Railways in Europe. In: Railways and the "
    "Transformation of Europe, Springer, 2023, doi:10.1007/978-3-031-21731-9_4, "
    "Supplementary material 2 (Europe_railways.gpkg)"
)

RAILWAYS_HGISE = LayerSpec(
    slug="railways_hgise",
    title="Железные дороги на 1850, 1890, 1930 и 1970 годы (HGISE)",
    group="economy",
    source=SOURCE, license=LICENSE,
    description=(
        "Была ли здесь железная дорога и с какого времени: отрезки сети по срезам 1850, "
        "1890, 1930 и 1970 годов (и 2000, 2010 — чтобы видеть закрытие) по базе HGISE — "
        "Финляндия, Прибалтика, Царство Польское, запад Белоруссии и Украины. Года "
        "открытия в наборе нет: «открыта между 1851 и 1890 годами». Подложка "
        "(`boundaries/railways_hgise.geojson`), записей не даёт. Европейской России в "
        "наборе нет — граница около 31° в. д."
    ),
    url=PROJECT_URL, status="harvested", expected_rows=344, gives_records=False,
)

# Допуск упрощения, градусы (около 100 м): база собрана по картам Европы.
TOLERANCE = 0.001
DIGITS = 4


class RailwaysError(RuntimeError):
    """Архив не достался или набор пришёл не в том виде."""


# --- ETRS89-LAEA (EPSG:3035) → широта и долгота --------------------------------

# Параметры EPSG:3035: центр 52° с. ш., 10° в. д., ложные восток и север,
# эллипсоид GRS80. Формулы — обратная азимутальная равновеликая проекция
# Ламберта на эллипсоиде (IOGP, Guidance Note 7-2, 3.2.2.1). Датум ETRS89
# отличается от WGS84 на десятки сантиметров — для карты XIX века неважно.
_A = 6378137.0
_F = 1 / 298.257222101
_LAT0, _LON0 = math.radians(52.0), math.radians(10.0)
_FE, _FN = 4321000.0, 3210000.0
_E2 = 2 * _F - _F * _F
_E = math.sqrt(_E2)


def _q(phi: float) -> float:
    s = math.sin(phi)
    return (1 - _E2) * (s / (1 - _E2 * s * s)
                        - (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s)))


_QP = _q(math.pi / 2)
_BETA0 = math.asin(_q(_LAT0) / _QP)
_RQ = _A * math.sqrt(_QP / 2)
_D = _A * (math.cos(_LAT0) / math.sqrt(1 - _E2 * math.sin(_LAT0) ** 2)) / (
    _RQ * math.cos(_BETA0))


def laea_to_lonlat(easting: float, northing: float) -> tuple[float, float]:
    """(восток, север) EPSG:3035 → (долгота, широта) в градусах."""
    x, y = easting - _FE, northing - _FN
    rho = math.hypot(x / _D, _D * y)
    if rho == 0:
        return math.degrees(_LON0), math.degrees(_LAT0)
    c = 2 * math.asin(min(1.0, rho / (2 * _RQ)))
    beta = math.asin(math.cos(c) * math.sin(_BETA0)
                     + _D * y * math.sin(c) * math.cos(_BETA0) / rho)
    lon = _LON0 + math.atan2(x * math.sin(c), _D * rho * math.cos(_BETA0) * math.cos(c)
                             - _D * _D * y * math.sin(_BETA0) * math.sin(c))
    e4, e6 = _E2 * _E2, _E2 * _E2 * _E2
    lat = (beta + (_E2 / 3 + 31 * e4 / 180 + 517 * e6 / 5040) * math.sin(2 * beta)
           + (23 * e4 / 360 + 251 * e6 / 3780) * math.sin(4 * beta)
           + (761 * e6 / 45360) * math.sin(6 * beta))
    return math.degrees(lon), math.degrees(lat)


# --- годы ------------------------------------------------------------------

def states(props: dict) -> dict:
    """{год: код состояния} по полям `TYPE_<год>`; пустое поле — линии нет."""
    return {y: (str(props.get(f"TYPE_{y}") or ABSENT).strip().upper() or ABSENT)
            for y in SNAPSHOTS}


def window(present: dict, *, opening: bool) -> Optional[tuple[Optional[int], int]]:
    """Между какими срезами линия появилась (или исчезла).

    `present` — {год: есть ли линия}. Для открытия: первый срез с линией и
    предыдущий без неё → (предыдущий + 1, первый); есть уже в 1850 году →
    (None, 1850): «не позже 1850». Для закрытия: последний срез с линией и
    следующий без неё → (последний + 1, следующий); дожила до 2010 — None.
    """
    years = list(SNAPSHOTS)
    have = [y for y in years if present[y]]
    if not have:
        return None
    if opening:
        first = have[0]
        i = years.index(first)
        return (years[i - 1] + 1 if i else None, first)
    last = have[-1]
    i = years.index(last)
    if i == len(years) - 1:
        return None
    return (last + 1, years[i + 1])


def period_text(span: Optional[tuple[Optional[int], int]], what: str) -> Optional[str]:
    """(1851, 1890) → «открыта между 1851 и 1890 годами»; (None, 1850) → «… не позже 1850»."""
    if span is None:
        return None
    a, b = span
    return f"{what} не позже {b} года" if a is None else f"{what} между {a} и {b} годами"


# --- отрезки ---------------------------------------------------------------

def _project(line: list) -> list:
    return [[round(c, DIGITS) for c in laea_to_lonlat(x, y)] for x, y in line]


def _parts(geometry: dict) -> list:
    kind = (geometry or {}).get("type")
    if kind == "LineString":
        return [geometry["coordinates"]]
    if kind == "MultiLineString":
        return list(geometry["coordinates"])
    raise RailwaysError(f"геометрия {kind}: ждали линии")


def middle(parts: list) -> tuple[float, float]:
    """(широта, долгота) средней вершины самой длинной части — по ней ставится рамка."""
    longest = max(parts, key=len)
    lon, lat = longest[len(longest) // 2]
    return lat, lon


def segment_feature(feature: dict, place) -> Optional[dict]:
    """Отрезок набора → линия подложки, если середина в рамке и линия была до 1970 года.

    `place(lat, lon)` → (в рамке ли, губерния 1897 года или None, …) — `Frame.place`.
    """
    props = feature.get("properties") or {}
    st = states(props)
    present = {y: st[y] != ABSENT for y in SNAPSHOTS}
    if not any(present[y] for y in SNAPSHOTS if y <= YEAR_LIMIT):
        return None
    parts = [_project(p) for p in _parts(feature.get("geometry"))]
    parts = [simplify(p, TOLERANCE) for p in parts if len(p) >= 2]
    parts = [p for p in parts if len(p) >= 2]
    if not parts:
        return None
    lat, lon = middle(parts)
    inside, province = place(lat, lon)[:2]
    if not inside:
        return None
    opened, closed = window(present, opening=True), window(present, opening=False)
    out = {"opened_from": opened[0], "opened_to": opened[1],
           "opened": period_text(opened, "открыта")}
    if closed:
        out.update(closed_from=closed[0], closed_to=closed[1],
                   closed=period_text(closed, "закрыта"))
    for y in SNAPSHOTS:
        out[f"state_{y}"] = st[y]
    first = st[opened[1]]
    out["type"] = STATE_RU.get(first, f"код набора {first}")
    if province:
        out["region"] = province
    length = props.get("Length_km")
    if length:
        out["length_km"] = round(float(length), 2)
    geometry = ({"type": "LineString", "coordinates": parts[0]} if len(parts) == 1
                else {"type": "MultiLineString", "coordinates": parts})
    return {"type": "Feature", "geometry": geometry,
            "properties": {k: v for k, v in out.items() if v is not None}}


def segments(features: Iterable[dict], place) -> list[dict]:
    return [f for f in (segment_feature(x, place) for x in features) if f is not None]
