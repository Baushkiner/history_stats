"""Солнечные затмения по губерниям, 1600–1960: каталог NASA и расчёт по эфемеридам JPL.

Зачем этот слой. Полное затмение — событие, которое помнили поколениями и
записывали на полях метрических книг и в летописях приходов: «в сей день
в десятом часу утра сделалась тьма». Оно привязано к месту с точностью до
десятков вёрст и ко времени — до минуты. Слой отвечает на вопрос «видели ли
в этой губернии в этом году, как днём погасло солнце» и даёт дату по обоим
стилям и час по местному солнечному времени.

Из чего собран. Перечень затмений — «Five Millennium Catalog of Solar
Eclipses» (Ф. Эспенак и Ж. Меёс, NASA GSFC): дата, время наибольшей фазы,
тип, гамма, ΔT. Воспроизведение разрешено с указанием «Eclipse Predictions by
Fred Espenak (NASA's GSFC)». Полос затмений в машинном виде у NASA нет:
страницы с элементами Бесселя за годы до 1901-го не отвечают (служба
`SEdata.php` падает с ошибкой базы), таблицы полос есть только с 1901 года.
Поэтому полоса **считается здесь**: положения Солнца, Луны и Земли берутся из
эфемерид JPL DE440 (общественное достояние, 1550–2650 годы), а дальше —
геометрия.

Как считается. На каждый момент берутся барицентрические положения с
поправкой на время хода света: Солнце — где оно было, когда свет вышел, Луна
— когда свет прошёл мимо неё, наблюдатель — в момент наблюдения. Векторы
переводятся из J2000 в экватор даты (прецессия IAU 1976), Земля поворачивается
на звёздное время по UT1 = TT − ΔT, где ΔT взят из каталога. Для точки на
эллипсоиде WGS-84 считаются угловые радиусы Солнца и Луны и расстояние между
их центрами: центральная фаза — когда один диск целиком внутри другого, фаза
затмения — доля солнечного диаметра, закрытая Луной. Нутация и рефракция не
учитываются: это сотни метров на земле, а сетка точек — четверть градуса.

Проверка расчёта каталогом. У каждого затмения расчёт сверяется с двумя
числами каталога, которые от него не зависят: гаммой (наименьшее расстояние
оси тени от центра Земли) и точкой наибольшей фазы. Расхождение печатает
`--check`; затмение, у которого гамма разошлась больше допуска, в слой не
идёт, а попадает в отчёт.

Что в записи. Губернии 1897 года (полигоны RISTAT), в которых была видна
центральная фаза — полная или кольцеобразная, — и отдельно губернии, где фаза
превысила `DEEP_PARTIAL`: там солнце не погасло, но день заметно померк.
Охват записи — губернии (`scope = region`), точки у неё нет; осевая линия тени
лежит в `extra.track` — её можно нарисовать. Губерния названа, если в полосу
попал хотя бы один узел сетки 0,25° внутри неё: узкая полоса (гибридное
затмение, 5–20 км) может пройти между узлами — такое затмение помечено.
За пределами губерний 1897 года (Галиция, Закарпатье, Восточная Пруссия)
слой молчит.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..net import fetch_bytes
from ..oldstyle import both_styles
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec
from .ghcn import _province_name

CATALOG_URL = "https://eclipse.gsfc.nasa.gov/SEcat5/SE{span}.html"
CATALOG_INDEX = "https://eclipse.gsfc.nasa.gov/SEcat5/catalog.html"
MAP_URL = "https://eclipse.gsfc.nasa.gov/5MCSEmap/{span}/{date}.gif"
SPANS = ("1601-1700", "1701-1800", "1801-1900", "1901-2000")
YEARS = (1601, 1960)
EPHEMERIS_URL = "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de440.bsp"
EPHEMERIS_NAME = "de440.bsp"
EPHEMERIS_SIZE = 119_799_808
CREDIT = "Eclipse Predictions by Fred Espenak (NASA's GSFC)"

# Постоянные расчёта.
EARTH_A_KM = 6378.137
EARTH_F = 1 / 298.257223563
SUN_R_KM = 696_000.0
# Два радиуса Луны, как в каноне NASA: больший — для частных фаз (с учётом
# гор лунного края), меньший — для центральной фазы (по впадинам края).
MOON_K_PENUMBRA = 0.2725076
MOON_K_UMBRA = 0.272281
C_KM_S = 299_792.458
J2000 = 2451545.0

DEEP_PARTIAL = 0.9          # фаза, с которой день заметно меркнет
GAMMA_TOLERANCE = 0.002     # допуск сверки гаммы с каталогом
GRID_STEP = 0.25            # сетка узлов внутри губерний, градусы
COARSE = 2                  # каждый второй узел — для грубого прохода
TRACK_STEP_S = 60.0
FINE_STEP_S = 10.0
NARROW_KM = 40              # полоса уже — могла пройти между узлами

TYPES = {"T": "полное", "A": "кольцеобразное", "H": "гибридное (кольцеобразно-полное)"}
TYPE_NOUN = {"T": "Полное солнечное затмение", "A": "Кольцеобразное солнечное затмение",
             "H": "Гибридное солнечное затмение"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}

SOLAR_ECLIPSES = LayerSpec(
    slug="solar_eclipses",
    title="Солнечные затмения по губерниям, 1601–1960",
    group="hardship",
    source=("NASA GSFC, Five Millennium Catalog of Solar Eclipses (Ф. Эспенак, Ж. Меёс); "
            "полоса рассчитана по эфемеридам JPL DE440"),
    license=(
        "Каталог NASA: воспроизведение свободно при указании «Eclipse Predictions by Fred "
        "Espenak (NASA's GSFC)»; эфемериды JPL — общественное достояние. Полоса по "
        "губерниям — собственный расчёт проекта"
    ),
    description=(
        "Видели ли в губернии, как днём погасло солнце: полные и кольцеобразные затмения "
        "с перечнем губерний 1897 года, через которые прошла полоса, и губерний, где фаза "
        "превысила 0,9. Дата по новому и старому стилю, час по местному солнечному "
        "времени. Полоса рассчитана проектом по эфемеридам JPL и сверена с каталогом "
        "NASA; узкие полосы гибридных затмений могут пройти между узлами сетки."
    ),
    url=CATALOG_INDEX,
    status="harvested",
    # Сбор 22.11.2026: 77 затмений с полосой в губерниях, 110 глубоких частных.
    expected_rows=187,
)


class EclipseError(RuntimeError):
    """Каталог или эфемериды не читаются, либо расчёт расходится с каталогом."""


# --- каталог ---------------------------------------------------------------

@dataclass(frozen=True)
class Eclipse:
    """Строка каталога NASA."""

    number: str
    date: dt.date
    time: str               # время наибольшей фазы, TD
    delta_t: float          # секунды
    saros: int
    kind: str               # T, A, H, P
    kind_raw: str
    gamma: float
    magnitude: float
    lat: float              # точка наибольшей фазы
    lon: float
    width_km: Optional[float] = None
    duration: Optional[str] = None

    @property
    def central(self) -> bool:
        return self.kind in TYPES

    @property
    def jd_tt(self) -> float:
        h, m, s = (int(x) for x in self.time.split(":"))
        return julian_day(self.date) + (h * 3600 + m * 60 + s) / 86400 - 0.5

    @property
    def map_url(self) -> str:
        start = (self.date.year - 1) // 100 * 100 + 1
        return MAP_URL.format(span=f"{start}-{start + 99}", date=self.date.isoformat())


def julian_day(date: dt.date) -> float:
    """Юлианская дата на полдень григорианской даты."""
    a = (14 - date.month) // 12
    y = date.year + 4800 - a
    m = date.month + 12 * a - 3
    return float(date.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045)


_RE_TAG = re.compile(r"<[^>]+>")
_RE_COORD = re.compile(r"(\d+)([NSEW])$")


def _coord(text: str) -> float:
    match = _RE_COORD.match(text)
    if not match:
        raise ValueError(text)
    value = float(match.group(1))
    return -value if match.group(2) in "SW" else value


def parse_catalog(page: str) -> list[Eclipse]:
    """Строки таблицы каталога. Строка, которая не разбирается, — ошибка, а не пропуск."""
    out = []
    for line in page.splitlines():
        cells = html.unescape(_RE_TAG.sub("", line)).split()
        if len(cells) < 15 or not re.fullmatch(r"\d{5}", cells[0]) \
                or not re.fullmatch(r"-?\d{4}", cells[1]):
            continue
        try:
            date = dt.date(int(cells[1]), MONTHS[cells[2]], int(cells[3]))
            out.append(Eclipse(
                number=cells[0], date=date, time=cells[4], delta_t=float(cells[5]),
                saros=int(cells[7]), kind=cells[8][0], kind_raw=cells[8],
                gamma=float(cells[10]), magnitude=float(cells[11]),
                lat=_coord(cells[12]), lon=_coord(cells[13]),
                width_km=float(cells[15]) if len(cells) > 16 and cells[15] != "-" else None,
                duration=cells[16] if len(cells) > 16 else None))
        except (KeyError, ValueError) as exc:
            raise EclipseError(f"строка каталога не разбирается: {' '.join(cells)!r} "
                               f"({exc})") from exc
    return out


def cached_catalog(span: str, cache_dir: Path) -> str:
    path = Path(cache_dir) / f"SE{span}.html"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch_bytes(CATALOG_URL.format(span=span), error=EclipseError))
    return path.read_text(encoding="latin-1")


def cached_ephemeris(cache_dir: Path) -> Path:
    path = Path(cache_dir) / EPHEMERIS_NAME
    if not path.exists() or path.stat().st_size != EPHEMERIS_SIZE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch_bytes(EPHEMERIS_URL, error=EclipseError, timeout=1800))
    if path.stat().st_size != EPHEMERIS_SIZE:
        raise EclipseError(f"{EPHEMERIS_NAME}: {path.stat().st_size} байт, в коде "
                           f"{EPHEMERIS_SIZE}")
    return path


# --- небесная механика -----------------------------------------------------

class Ephemeris:
    """Барицентрические положения Солнца, Луны и Земли из файла JPL (км, ICRF)."""

    def __init__(self, path: Path) -> None:
        try:
            from jplephem.spk import SPK
        except ImportError as exc:
            raise EclipseError("для расчёта затмений нужен пакет jplephem "
                               "(pip install jplephem) — только этому сборщику") from exc
        self.kernel = SPK.open(str(path))

    def bodies(self, jd):
        """(Солнце, Луна, Земля) на моменты `jd` (TT≈TDB): массивы [n, 3]."""
        import numpy as np

        jd = np.atleast_1d(np.asarray(jd, dtype=np.float64))
        emb = self.kernel[0, 3].compute(jd)
        sun = self.kernel[0, 10].compute(jd)
        moon = emb + self.kernel[3, 301].compute(jd)
        earth = emb + self.kernel[3, 399].compute(jd)
        return sun.T, moon.T, earth.T

    def apparent(self, jd):
        """Геоцентрические векторы Солнца и Луны с поправкой на ход света.

        Свет, пришедший к Земле в момент t, вышел от Солнца на ~499 с раньше и
        прошёл Луну на ~1,3 с раньше; Земля за это время сместилась. Без
        поправки тень на земле уезжает на десятки километров.
        """
        import numpy as np

        jd = np.atleast_1d(np.asarray(jd, dtype=np.float64))
        sun, moon, earth = self.bodies(jd)
        tau_s = np.linalg.norm(sun - earth, axis=1) / C_KM_S / 86400
        tau_m = np.linalg.norm(moon - earth, axis=1) / C_KM_S / 86400
        sun_then, _, _ = self.bodies(jd - tau_s)
        _, moon_then, _ = self.bodies(jd - tau_m)
        return sun_then - earth, moon_then - earth


def precession_matrix(jd_tt: float):
    """Матрица J2000 → средний экватор и равноденствие даты (IAU 1976)."""
    import numpy as np

    t = (jd_tt - J2000) / 36525.0
    arcsec = math.pi / 648000
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) * arcsec
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) * arcsec
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) * arcsec
    cz, sz = math.cos(zeta), math.sin(zeta)
    ca, sa = math.cos(z), math.sin(z)
    ct, st = math.cos(theta), math.sin(theta)
    return np.array([
        [ca * ct * cz - sa * sz, -ca * ct * sz - sa * cz, -ca * st],
        [sa * ct * cz + ca * sz, -sa * ct * sz + ca * cz, -sa * st],
        [st * cz, -st * sz, ct],
    ])


def gmst(jd_ut):
    """Гринвичское среднее звёздное время, радианы (IAU 1982)."""
    import numpy as np

    d = np.asarray(jd_ut, dtype=np.float64) - J2000
    t = d / 36525.0
    degrees = 280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - t ** 3 / 38710000.0
    return np.radians(degrees % 360.0)


def observer_xyz(lat_deg, lon_deg):
    """Точка на эллипсоиде WGS-84 в земной системе, км, и её зенит."""
    import numpy as np

    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    e2 = EARTH_F * (2 - EARTH_F)
    n = EARTH_A_KM / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    xyz = np.stack([n * np.cos(lat) * np.cos(lon), n * np.cos(lat) * np.sin(lon),
                    n * (1 - e2) * np.sin(lat)], axis=-1)
    up = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1)
    return xyz, up


def rotate_z(vectors, angle: float):
    """Поворот векторов вокруг оси Z на угол: земная система → экватор даты при
    угле, равном звёздному времени."""
    import numpy as np

    c, s = math.cos(angle), math.sin(angle)
    return vectors @ np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])


def circumstances(sun, moon, points, zenith):
    """Обстоятельства затмения в точках на один момент.

    `sun`, `moon` — геоцентрические векторы в экваторе даты, `points` и
    `zenith` — там же. Возвращает (фаза, центральная ли, высота Солнца, рад).
    """
    import numpy as np

    to_sun = sun - points
    to_moon = moon - points
    d_sun = np.linalg.norm(to_sun, axis=1)
    d_moon = np.linalg.norm(to_moon, axis=1)
    cos_sep = np.clip(np.einsum("ij,ij->i", to_sun, to_moon) / (d_sun * d_moon), -1.0, 1.0)
    sep = np.arccos(cos_sep)
    r_sun = np.arcsin(SUN_R_KM / d_sun)
    r_moon = np.arcsin(MOON_K_PENUMBRA * EARTH_A_KM / d_moon)
    r_moon_umbra = np.arcsin(MOON_K_UMBRA * EARTH_A_KM / d_moon)
    magnitude = (r_sun + r_moon - sep) / (2 * r_sun)
    central = sep < np.abs(r_moon_umbra - r_sun)
    altitude = np.arcsin(np.clip(np.einsum("ij,ij->i", to_sun, zenith) / d_sun, -1.0, 1.0))
    return magnitude, central, altitude


def axis_point(sun, moon):
    """Где ось тени встречает эллипсоид: точка в экваторе даты или None.

    Ось — прямая от Солнца через Луну. Эллипсоид приводится к сфере
    растяжением оси Z, пересечение ищется как у прямой со сферой.
    """
    import numpy as np

    scale = np.array([1.0, 1.0, 1.0 / (1.0 - EARTH_F)])
    origin = moon * scale
    direction = (moon - sun) * scale
    direction = direction / np.linalg.norm(direction)
    b = float(origin @ direction)
    c = float(origin @ origin) - EARTH_A_KM ** 2
    disc = b * b - c
    if disc < 0:
        return None
    return (origin + (-b - math.sqrt(disc)) * direction) / scale


def gamma_of(sun, moon) -> float:
    """Расстояние оси тени от центра Земли в экваториальных радиусах, со знаком."""
    import numpy as np

    direction = (moon - sun) / np.linalg.norm(moon - sun)
    foot = moon - (moon @ direction) * direction
    return float(math.copysign(np.linalg.norm(foot) / EARTH_A_KM, foot[2]))


def to_geodetic(point, theta: float) -> tuple[float, float]:
    """Точка поверхности в экваторе даты → (широта, долгота), градусы."""
    c, s = math.cos(theta), math.sin(theta)
    x = c * point[0] + s * point[1]
    y = -s * point[0] + c * point[1]
    e2 = EARTH_F * (2 - EARTH_F)
    lat = math.degrees(math.atan2(point[2], (1 - e2) * math.hypot(x, y)))
    return lat, math.degrees(math.atan2(y, x))


@dataclass
class Sky:
    """Положения светил на сетке моментов вокруг наибольшей фазы."""

    eclipse: Eclipse
    jd: object              # TT
    sun: object             # [n, 3], экватор даты
    moon: object
    theta: object           # звёздное время, рад

    @classmethod
    def compute(cls, ephemeris: Ephemeris, eclipse: Eclipse, *, half_span_s: float,
                step_s: float) -> "Sky":
        import numpy as np

        steps = int(half_span_s // step_s)
        jd = eclipse.jd_tt + np.arange(-steps, steps + 1) * step_s / 86400
        sun, moon = ephemeris.apparent(jd)
        matrix = precession_matrix(eclipse.jd_tt)
        return cls(eclipse=eclipse, jd=jd, sun=sun @ matrix.T, moon=moon @ matrix.T,
                   theta=gmst(jd - eclipse.delta_t / 86400))

    def seconds(self, i: int) -> float:
        """Секунд от наибольшей фазы."""
        return float((self.jd[i] - self.eclipse.jd_tt) * 86400)


def track(sky: Sky) -> list[tuple[float, float, float]]:
    """Осевая линия тени: (секунд от наибольшей фазы, широта, долгота)."""
    out = []
    for i in range(len(sky.jd)):
        point = axis_point(sky.sun[i], sky.moon[i])
        if point is None:
            continue
        lat, lon = to_geodetic(point, float(sky.theta[i]))
        out.append((sky.seconds(i), lat, lon))
    return out


def greatest(sky: Sky) -> tuple[float, Optional[tuple[float, float]]]:
    """Гамма и точка наибольшей фазы по расчёту — для сверки с каталогом."""
    import numpy as np

    gammas = np.array([gamma_of(sky.sun[i], sky.moon[i]) for i in range(len(sky.jd))])
    i = int(np.argmin(np.abs(gammas)))
    point = axis_point(sky.sun[i], sky.moon[i])
    where = to_geodetic(point, float(sky.theta[i])) if point is not None else None
    return float(gammas[i]), where


# --- сетка губерний ---------------------------------------------------------

@dataclass
class Nodes:
    """Узлы сетки внутри губерний: координаты, номер губернии, названия."""

    lat: object
    lon: object
    province: object
    names: list

    def subset(self, mask) -> "Nodes":
        return Nodes(self.lat[mask], self.lon[mask], self.province[mask], self.names)


def province_nodes(features: Sequence[dict], *, step: float = GRID_STEP,
                   name_field: str = "prov_RU") -> Nodes:
    """Сетка узлов с шагом `step` и губерния каждого узла (правило чётности)."""
    import numpy as np

    from .raster import rasterize

    lat_max, lat_min, lon_min, lon_max = 82.0, 35.0, 17.0, 191.0
    n_rows, n_cols = round((lat_max - lat_min) / step), round((lon_max - lon_min) / step)
    index = rasterize([f.get("geometry") or {} for f in features], lat_max=lat_max,
                      lon_min=lon_min, cell=step, n_rows=n_rows, n_cols=n_cols)
    # Название — как у остальных слоёв проекта: оговорки RISTAT «вкл. …» и
    # «без …» срезаются, и два полигона одной губернии сливаются в одну.
    raw = [_province_name((f.get("properties") or {}).get(name_field)) or "" for f in features]
    names = sorted(set(raw) - {""})
    remap = np.array([names.index(n) if n else -1 for n in raw], dtype=np.int32)
    rows, cols = np.nonzero(index >= 0)
    province = remap[index[rows, cols]]
    keep = province >= 0
    rows, cols, province = rows[keep], cols[keep], province[keep]
    lon = lon_min + step * (cols + 0.5)
    return Nodes(lat=lat_max - step * (rows + 0.5), lon=np.where(lon > 180, lon - 360, lon),
                 province=province, names=names)


def _angular_km(lat1, lon1, lat2, lon2):
    import numpy as np

    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


@dataclass
class Visibility:
    """Что видели в губерниях: центральная фаза и глубокая частная."""

    central: dict = field(default_factory=dict)     # губерния → {ut, local, duration_s}
    deep: dict = field(default_factory=dict)        # губерния → наибольшая фаза
    track: list = field(default_factory=list)       # [[lon, lat], …] в рамке
    gamma: float = 0.0
    greatest: Optional[tuple] = None
    order: list = field(default_factory=list)       # губернии по ходу тени


def _scan(sky: Sky, nodes: Nodes, indices: Iterable[int]):
    """Проход по моментам: наибольшая фаза узла, число центральных шагов, время."""
    import numpy as np

    n = len(nodes.lat)
    best = np.full(n, -1.0)
    central_steps = np.zeros(n, dtype=np.int32)
    central_time = np.zeros(n)
    points_fixed, up_fixed = observer_xyz(nodes.lat, nodes.lon)
    for i in indices:
        theta = float(sky.theta[i])
        points, up = rotate_z(points_fixed, theta), rotate_z(up_fixed, theta)
        magnitude, central, altitude = circumstances(sky.sun[i], sky.moon[i], points, up)
        day = altitude > 0
        best = np.where(day & (magnitude > best), magnitude, best)
        hit = central & day
        central_steps += hit
        central_time += np.where(hit, sky.seconds(i), 0.0)
    return best, central_steps, central_time


def visibility(ephemeris: Ephemeris, eclipse: Eclipse, nodes: Nodes) -> Visibility:
    """Губернии, где затмение было центральным или глубоким частным.

    Гамма и точка наибольшей фазы считаются всегда — для сверки с каталогом;
    перечни губерний пусты, если тень прошла далеко от рамки проекта.
    """
    import numpy as np

    sky = Sky.compute(ephemeris, eclipse, half_span_s=3.2 * 3600, step_s=TRACK_STEP_S)
    line = track(sky)
    result = Visibility()
    result.gamma, result.greatest = greatest(sky)
    if not line:
        return result
    lats = np.array([p[1] for p in line])
    lons = np.array([p[2] for p in line])
    # Грубое сито: узлы ближе 1 800 км к осевой линии. Фаза 0,9 лежит не дальше
    # нескольких сотен километров от полосы; запас — на высокие широты.
    near = np.zeros(len(nodes.lat), dtype=bool)
    for k in range(0, len(line), 3):
        near |= _angular_km(nodes.lat, nodes.lon, lats[k], lons[k]) < 1800
    if not near.any():
        return result
    close = nodes.subset(near)
    best, _, _ = _scan(sky, close, range(0, len(sky.jd), 2))
    deep_mask = best >= DEEP_PARTIAL
    if not deep_mask.any():
        return result
    for number in np.unique(close.province[deep_mask]):
        value = float(best[(close.province == number) & deep_mask].max())
        result.deep[close.names[number]] = round(min(value, 1.0), 3)

    # Точный проход — только по узлам, где фаза почти полная.
    candidates = close.subset(best >= 0.97)
    if len(candidates.lat):
        fine = Sky.compute(ephemeris, eclipse, half_span_s=3.2 * 3600, step_s=FINE_STEP_S)
        _, steps, time_sum = _scan(fine, candidates, range(len(fine.jd)))
        hit = steps > 0
        for number in np.unique(candidates.province[hit]):
            mask = hit & (candidates.province == number)
            best_node = int(np.argmax(np.where(mask, steps, 0)))
            mid_s = float(time_sum[best_node] / steps[best_node])
            ut = (dt.datetime.combine(eclipse.date, dt.time(*map(int, eclipse.time.split(":"))))
                  + dt.timedelta(seconds=mid_s - eclipse.delta_t))
            local = ut + dt.timedelta(hours=float(candidates.lon[best_node]) / 15)
            name = candidates.names[number]
            result.central[name] = {
                "ut": ut.strftime("%H:%M"), "local": local.strftime("%H:%M"),
                "duration_s": int(steps[best_node] * FINE_STEP_S),
                "_mid": mid_s,
            }
            result.deep.pop(name, None)
        result.order = sorted(result.central, key=lambda k: result.central[k]["_mid"])
        for info in result.central.values():
            info.pop("_mid")
    for _, lat, lon in line[::2]:
        if 33 <= lat <= 84 and (15 <= lon <= 180 or lon <= -168):
            result.track.append([round(lon, 2), round(lat, 2)])
    return result


# --- записи ----------------------------------------------------------------

def _duration(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} мин {rest:02d} с" if minutes else f"{rest} с"


def _hour(local: str) -> str:
    hour, minute = (int(x) for x in local.split(":"))
    part = ("ночи" if hour < 4 else "утра" if hour < 12 else "дня" if hour < 17 else "вечера")
    return f"около {hour}:{minute:02d} {part}"


def _short(name: str) -> str:
    return name.replace(" губерния", "").replace(" область", " обл.")


def _extra(eclipse: Eclipse, seen: Visibility) -> dict:
    extra = {"catalog_number": eclipse.number, "saros": eclipse.saros, "type": eclipse.kind_raw,
             "gamma": eclipse.gamma, "gamma_computed": round(seen.gamma, 4),
             "delta_t_s": eclipse.delta_t, "greatest_td": eclipse.time,
             "greatest_point": [eclipse.lon, eclipse.lat], "credit": CREDIT}
    if eclipse.width_km is not None:
        extra["path_width_km"] = eclipse.width_km
    if eclipse.duration:
        extra["max_duration"] = eclipse.duration
    return extra


def to_records(eclipse: Eclipse, seen: Visibility) -> list[ContextRecord]:
    """Записи одного затмения: полоса центральной фазы и, отдельно, глубокая частная.

    Две записи, а не одна, потому что подбор идёт по перечню губерний: в
    Тверской губернии 19 августа 1887 года солнце погасло, в Рязанской —
    закрылось на 0,97. Это разные события для разных мест.
    """
    when = both_styles(eclipse.date)
    narrow = eclipse.width_km is not None and eclipse.width_km < NARROW_KM
    tail = ("Перечень губерний — расчёт проекта по эфемеридам JPL DE440, сверенный с "
            f"каталогом NASA; {CREDIT}")
    common = dict(scope=SCOPE_REGION, year_from=eclipse.date.year, year_to=eclipse.date.year,
                  date_precision="day", period_raw=eclipse.date.isoformat(),
                  url=eclipse.map_url, work=f"{TYPE_NOUN[eclipse.kind]} {when}")
    out = []
    if seen.central:
        regions = list(seen.order)
        word = {"T": "полной фазы", "A": "кольцеобразной фазы"}.get(eclipse.kind,
                                                                   "центральной фазы")
        listed = "; ".join(
            f"{_short(name)} — {_hour(seen.central[name]['local'])}, "
            f"до {_duration(seen.central[name]['duration_s'])}" for name in regions)
        parts = [f"Полоса {word} прошла через губернии (по ходу тени; время местное "
                 f"солнечное, длительность — наибольшая по узлам сетки): {listed}"]
        if eclipse.kind == "A":
            parts.append("При кольцеобразном затмении Луна не закрывает Солнце целиком: "
                         "остаётся яркое кольцо, темноты не наступает")
        if narrow:
            parts.append(f"Полоса узкая ({eclipse.width_km:.0f} км): между узлами сетки 0,25° "
                         "она могла пройти незамеченной — перечень может быть неполным")
        parts.append(tail)
        extra = _extra(eclipse, seen)
        extra["central"] = seen.central
        if seen.track:
            extra["track"] = seen.track
        if narrow:
            extra["narrow_path"] = True
        out.append(SOLAR_ECLIPSES.new_record(
            title=f"{TYPE_NOUN[eclipse.kind]} {when}", category=TYPES[eclipse.kind],
            place_text="; ".join(regions), regions=regions,
            summary=". ".join(parts) + ".", source_id=f"{eclipse.number}:central",
            extra=extra, **common))
    if seen.deep:
        regions = sorted(seen.deep)
        listed = ", ".join(f"{_short(n)} ({str(seen.deep[n]).replace('.', ',')})"
                           for n in regions)
        where = ("Рядом с полосой центральной фазы" if seen.central
                 else "Полоса центральной фазы прошла мимо губерний 1897 года, но")
        parts = [f"{where} солнце закрывалось больше чем на 0,9 диаметра в губерниях "
                 f"(в скобках — наибольшая фаза по узлам сетки): {listed}",
                 "Полной темноты здесь не было, но день заметно померк", tail]
        extra = _extra(eclipse, seen)
        extra["deep_partial"] = seen.deep
        if seen.track:
            extra["track"] = seen.track
        out.append(SOLAR_ECLIPSES.new_record(
            title=f"Солнечное затмение {when}: частное с фазой больше 0,9",
            category="частное глубокое (фаза больше 0,9)",
            place_text="; ".join(regions), regions=regions,
            summary=". ".join(parts) + ".", source_id=f"{eclipse.number}:deep",
            extra=extra, **common))
    return out


def load_provinces(path: Path) -> list[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))["features"]
    except (OSError, ValueError, KeyError) as exc:
        raise EclipseError(f"нет полигонов губерний 1897 года ({path}): {exc}") from exc
