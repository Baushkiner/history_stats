"""Засухи по годичным кольцам за Уралом: Great Eurasian Drought Atlas (GEDA).

Зачем этот слой. Атлас засух Европейской России (ERDA, `sources/drought.py`)
кончается на 62° в. д., и для факта из Тобольска, Омска, Барнаула или
Иркутска слой `drought_atlas` молчит. GEDA (Э. Кук и Б. Кук, 2024) — сетка
того же индекса, летнего scPDSI, на 0.5°, но по всей Евразии, 1000–2020 годы,
из 1869 древесно-кольцевых хронологий. Он и закрывает дыру «за Уралом ничего».
Monsoon Asia Drought Atlas, стоявший на очереди ради юга Сибири, по сравнению
с ним не нужен: та же задача, сетка вчетверо реже и обрезана 56-й параллелью.

Где берётся. **Только там, где ERDA нет**: узлы внутри охвата ERDA (22–62°
в. д., 41–71.5° с. ш. — ERDA там покрывает всю сушу без пропусков, это
проверено по узлам) выбрасываются, иначе одна засуха попала бы на карту
дважды и из двух несогласных между собой реконструкций (см. ниже). И только
в границах РИ/СССР: по долготе за Уралом лежат Китай и Монголия, а рамка
проекта (`geo.BBOX_RU`) прямоугольная и их не отсекает. Сито — полигоны
России и СССР из CShapes (`data/out/boundaries/state_borders.geojson`): узел
берётся, если его центр попадает в территорию России хотя бы одного из
семнадцати её периодов 1886–1960 годов (у побережья — хоть один угол клетки,
см. `make_keep`). Так в слой входят Урянхайский край
(протекторат с 1914 года) и Южный Сахалин (с 1945-го), а Внешняя Монголия и
Маньчжурия не входят.

**Значения — не шкала Палмера.** Файл на Zenodo — «урезанный и
перенормированный» scPDSI: у каждого узла среднее за 1000–2020 годы вычтено и
ряд поделён на стандартное отклонение, единица — сигма (атрибут `units` у
переменной так и говорит: `sigma`). Порог «−4, экстремальная засуха» слоя
ERDA к нему неприменим, а записи двух слоёв нельзя сравнивать числом. Шкала
словами поэтому своя (`SIGMA_CLASSES`) и подобрана по частоте: в общей полосе
ERDA и GEDA год с PDSI ERDA ≤ −4 встречается в 2.15% узлов-лет, ровно так же
часто, как GEDA ≤ −2σ (1600–1960 годы, 4259 общих узлов). Порог слоя строже —
−2.5σ; почему, сказано у `THRESHOLD`.

**В общей полосе два атласа согласуются слабо.** На тех же 4259 узлах
корреляция годовых значений ERDA и GEDA за 1600–1960 годы — 0.32 (медиана по
узлам), а за 1990–2016 годы, где оба опираются на станции, — 0.93. Лето 1891
года у Самары: в ERDA −4.4, в GEDA −1.35σ. Поэтому GEDA не заменяет ERDA там,
где ERDA есть, а за Уралом слой — лучшее, что есть, но не больше: отдельная
засуха в отдельном узле здесь — повод заглянуть в летопись, а не установленный
факт. Оговорка стоит в карточке слоя.

Точка сетки — не населённое место; губерния у записи не ставится, подбор идёт
по расстоянию — всё как в `drought.py`.

Чтение NetCDF. Файл — NetCDF4, то есть HDF5, и без библиотеки его не
прочесть. `h5py` — необязательная зависимость **только сборщика** (как
`geonamescache` у населённых мест): импортируется внутри `open_netcdf`, а
всё, что решает, какой узел и какой год идут в слой, работает на списках и
проверяется тестами без неё.
"""

from __future__ import annotations

import bisect
import collections
import hashlib
import json
import math
import urllib.error
import urllib.request
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..geo import in_bbox, valid_coords
from ..net import USER_AGENT, fetch_bytes
from ..schema import ContextRecord, LayerSpec
from .cshapes import rings
from .drought import (
    ERDA, MISSING_ABOVE, Atlas, Dataset, DroughtError, Episode, GridPoint, check_atlas,
    find_episodes, place_text,
)

RECORD_ID = "11059894"
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
DOI_URL = "https://doi.org/10.5281/zenodo.11059894"
FILE_NAME = "geda_trim.nc"
FILE_URL = f"{RECORD_API}/files/{FILE_NAME}/content"
# Сверено с API Zenodo 24.10.2026: файл в записи один, лицензия CC BY 4.0.
FILE_SIZE = 226_412_265
FILE_MD5 = "b05338614a43627b43acb878d860fb6a"
LICENSE_ID = "cc-by-4.0"

# Что лежит в файле — сверено h5py 24.10.2026. Разошлось — сбор стоит.
VARIABLE = "scPDSI"
DIMENSIONS = ("yr", "lat", "lon")
UNITS = "sigma"

GEDA = Dataset(
    key="geda",
    title="Great Eurasian Drought Atlas (GEDA)",
    grid_url=FILE_URL,
    matrix_url=FILE_URL,
    study_url=DOI_URL,
    citation=(
        "Cook E., Cook B. The Great Eurasian Drought Atlas. Zenodo, 2024, "
        "doi:10.5281/zenodo.11059894 (CC BY 4.0); описание — Cook B. I., Cook E. R., "
        "Anchukaitis K. J., Singh D. Characterizing the 2010 Russian heatwave–Pakistan "
        "flood concurrent extreme over the last millennium using the Great Eurasian "
        "Drought Atlas. Journal of Climate, 2024, 37, 4389–4401, "
        "doi:10.1175/JCLI-D-23-0773.1"
    ),
    span=(1000, 2020),
    extent="вся Евразия, 0.25–78.75° с. ш., −21.75–179.75° в. д.; в слое — "
           "РИ/СССР вне охвата ERDA: Сибирь, Дальний Восток, Средняя Азия и "
           "Казахстан, Закавказье южнее 41° с. ш., Польша западнее 22° в. д.",
    bbox=(0.25, -21.75, 78.75, 179.75),
)

DROUGHT_ATLAS_GEDA = LayerSpec(
    slug="drought_atlas_geda",
    title="Реконструкция засух по кольцам деревьев: за пределами ERDA (GEDA)",
    group="hardship",
    source="Zenodo: The Great Eurasian Drought Atlas (GEDA), Э. Кук и Б. Кук",
    license=(
        "CC BY 4.0 (карточка записи на Zenodo): брать можно всё, со ссылкой на "
        "авторов и набор — ссылка и цитата проставляются в каждую запись"
    ),
    description=(
        "Летняя засушливость по годичным кольцам там, куда атлас Европейской "
        "России не дотягивается: Сибирь, Дальний Восток, Казахстан и Средняя "
        "Азия, Закавказье южнее 41° с. ш., Польша западнее 22° в. д. — только "
        "в границах РИ/СССР. Индекс в сигмах от нормы 1000–2020 годов, а не по "
        "шкале Палмера: с записями слоя drought_atlas числом не сравнивается. "
        "В общей с ERDA полосе два атласа согласуются слабо (корреляция по "
        "узлам 0.32 за 1600–1960 годы), поэтому отдельная засуха в отдельном "
        "узле — повод проверить по летописи и метрике, а не установленный факт."
    ),
    url=DOI_URL,
    status="harvested",
    expected_rows=19057,      # сбор 24.10.2026: 1600–1960 годы, порог −2.5σ
)

# Порог слоя в сигмах.
#
# По частоте эквивалентом «экстремальной засухи» ERDA (PDSI ≤ −4, 2.15%
# узлов-лет в общей полосе) был бы порог −2σ: в GEDA он срабатывает в 2.08%
# узлов-лет. Но за пределами ERDA у GEDA 10 936 узлов против 4259, и при −2σ
# слой вырастает до 68 тысяч записей — вдвое больше ERDA и втрое больше
# разумного файла. А главное, на −2σ сильнее всего видна слабость
# согласия: из узлов-лет, где ERDA даёт ≤ −4, GEDA сам опускается до −2σ лишь
# в 15%. Порог −2.5σ (0.5% узлов-лет, в среднем раз в два века на узел)
# оставляет в слое то, что выделяется и на фоне этой неуверенности. Кому нужна
# полная картина — `--threshold -2`.
THRESHOLD = -2.5

# Шкала словами, по сигмам. Подобрана по частоте в общей с ERDA полосе
# (1600–1960 годы, 4259 узлов): −2σ встречается так же часто, как PDSI ERDA
# ≤ −4, −1.5σ — как ≤ −3, −1σ — как ≤ −2. Названия поэтому те же, что у
# Палмера в слое ERDA, — по редкости, а не по числу. Ступень −2.5σ сверху
# названа «исключительной» (D4 в американском Drought Monitor).
SIGMA_CLASSES = (
    (-2.5, "исключительная засуха"),
    (-2.0, "экстремальная засуха"),
    (-1.5, "сильная засуха"),
    (-1.0, "умеренная засуха"),
)

# Россия и СССР в CShapes — один код Глёдича — Уорда на все периоды.
RUSSIA_GWCODE = 365


class GedaError(DroughtError):
    """Набор не скачался, не сошёлся с ожидаемым или не читается."""


# --- запись на Zenodo ------------------------------------------------------

def fetch_record(*, timeout: int = 60) -> dict:
    """Карточка записи по API Zenodo: файлы, размеры, контрольные суммы, лицензия."""
    raw = fetch_bytes(RECORD_API, error=GedaError, timeout=timeout)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise GedaError(f"ответ API Zenodo не разбирается: {exc}") from exc


def check_record(record: dict) -> list[str]:
    """Расхождения карточки с тем, что записано в коде. Пусто — всё сходится."""
    problems = []
    files = {f.get("key"): f for f in record.get("files") or []}
    got = files.get(FILE_NAME)
    if got is None:
        problems.append(f"в записи нет файла {FILE_NAME}; есть: {sorted(files)}")
    else:
        if got.get("size") != FILE_SIZE:
            problems.append(f"{FILE_NAME}: ожидался размер {FILE_SIZE}, пришёл {got.get('size')}")
        if got.get("checksum") != f"md5:{FILE_MD5}":
            problems.append(f"{FILE_NAME}: контрольная сумма {got.get('checksum')}, "
                            f"ожидалась md5:{FILE_MD5}")
    if len(files) > 1:
        problems.append(f"в записи {len(files)} файлов, а ждали один: {sorted(files)}")
    license_id = ((record.get("metadata") or {}).get("license") or {}).get("id")
    if license_id != LICENSE_ID:
        problems.append(f"лицензия в карточке {license_id!r}, а записана {LICENSE_ID!r} — "
                        "поправьте `license` в карточке слоя")
    return problems


def download(dest: Path, *, timeout: int = 600) -> Path:
    """Скачивает файл кусками, сверяя размер и md5. Не сошлось — файла нет."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.md5()
    size = 0
    request = urllib.request.Request(FILE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, \
                partial.open("wb") as fh:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except urllib.error.HTTPError as exc:
        raise GedaError(f"{FILE_URL}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GedaError(f"{FILE_URL}: сеть недоступна ({exc.reason})") from exc
    if size != FILE_SIZE or digest.hexdigest() != FILE_MD5:
        partial.unlink(missing_ok=True)
        raise GedaError(f"{FILE_NAME}: скачано {size} байт, md5 {digest.hexdigest()}; "
                        f"ожидалось {FILE_SIZE} байт, md5 {FILE_MD5}")
    partial.replace(dest)
    return dest


def cached(cache_dir: Path) -> Path:
    """Файл из `data/raw/geda/`; нет его или он неполный — скачивается заново."""
    path = Path(cache_dir) / FILE_NAME
    if path.exists() and path.stat().st_size == FILE_SIZE:
        return path
    return download(path)


# --- чтение NetCDF ---------------------------------------------------------

@dataclass
class Cube:
    """Открытый файл набора: оси и доступ к значениям, без самих значений."""

    years: tuple[int, ...]
    lats: tuple[float, ...]
    lons: tuple[float, ...]
    units: str
    comment: str
    # (годы, широты, долготы) → столбец по индексам внутри прочитанного куска:
    # `read(t, i, j)(a, b)` — ряд значений узла (i.start + a, j.start + b).
    read: Callable[[slice, slice, slice], Callable[[int, int], Sequence[float]]]


def open_netcdf(path: Path) -> Cube:
    """Открывает `geda_trim.nc` через h5py и сверяет то, на чём держится разбор."""
    try:
        import h5py
    except ImportError as exc:
        raise GedaError(
            "нет пакета h5py: pip install h5py. Он нужен только сборщику GEDA, чтобы "
            "прочесть NetCDF4 (это HDF5); остальной проект и тесты без него работают"
        ) from exc

    handle = h5py.File(Path(path), "r")
    missing = [name for name in (VARIABLE, *DIMENSIONS) if name not in handle]
    if missing:
        raise GedaError(f"{path}: в файле нет {missing}; есть {sorted(handle)}. "
                        "Формат набора изменился — поправьте разбор.")
    variable = handle[VARIABLE]
    years = tuple(int(round(v)) for v in handle["yr"][:])
    lats = tuple(float(v) for v in handle["lat"][:])
    lons = tuple(float(v) for v in handle["lon"][:])
    expected = (len(years), len(lats), len(lons))
    if tuple(variable.shape) != expected:
        raise GedaError(f"{VARIABLE}: размер {tuple(variable.shape)}, а оси {DIMENSIONS} "
                        f"дают {expected} — порядок измерений не тот, что ждёт разбор")
    units = _text(variable.attrs.get("units"))
    comment = _text(handle.attrs.get("comment"))
    if units != UNITS:
        raise GedaError(
            f"{VARIABLE}: единица {units!r}, а ждали {UNITS!r}. Набор переиздан в другой "
            "шкале — порог и шкала словами в слое считаны в сигмах и к ней не подходят."
        )

    def read(t: slice, i: slice, j: slice) -> Callable[[int, int], Sequence[float]]:
        block = variable[t, i, j]          # один numpy-массив на всё окно
        return lambda a, b: block[:, a, b].tolist()

    return Cube(years=years, lats=lats, lons=lons, units=units, comment=comment, read=read)


def read_atlas(cube: Cube, *, keep: Callable[[float, float], Optional[str]],
               year_from: int, year_to: int) -> tuple[Atlas, collections.Counter]:
    """Читает окно лет и узлы, прошедшие сито `keep`, в `drought.Atlas`.

    Читается не весь куб (1021 год × 158 × 404 узла), а прямоугольник рамки
    проекта за нужные годы: этого хватает, и это в десять раз меньше.
    """
    t0, t1 = _span(cube.years, year_from, year_to)
    i0, i1 = _span(cube.lats, BBOX_LAT[0], BBOX_LAT[1])
    j0, j1 = _span(cube.lons, BBOX_LON[0], BBOX_LON[1])
    block = cube.read(slice(t0, t1), slice(i0, i1), slice(j0, j1))
    years = cube.years[t0:t1]

    def column(i: int, j: int) -> Sequence[float]:
        return block(i - i0, j - j0)

    nodes, reasons = select_nodes(cube.lats[i0:i1], cube.lons[j0:j1],
                                  lambda i, j: has_data(column(i + i0, j + j0)),
                                  keep=keep, offset=(i0, j0))
    points = {}
    series = {}
    for i, j in nodes:
        number = node_number(i, j, len(cube.lons))
        points[number] = GridPoint(number=number, lat=cube.lats[i], lon=cube.lons[j])
        series[number] = array("f", (clean(v) for v in column(i, j)))
    if not points:
        raise GedaError("после сита не осталось ни одного узла — проверьте полигоны границ")
    atlas = Atlas(dataset=GEDA, points=points, years=years, series=series)
    check_atlas(atlas)
    return atlas, reasons


# --- отбор узлов -----------------------------------------------------------

# Рамка проекта, по которой режется куб при чтении.
BBOX_LAT = (35.0, 82.0)
BBOX_LON = (18.0, 180.0)

REASON_SEA = "нет данных (море, озеро)"
REASON_BBOX = "вне рамки проекта"
REASON_ERDA = "в охвате ERDA"
REASON_ABROAD = "вне РИ/СССР (Китай, Монголия и др.)"


def clean(value) -> float:
    """Значение или NaN. Пропуск в файле — не NaN, а заполнитель NetCDF
    9.97e36: h5py его не подменяет, и «морской» узел без этой проверки
    выглядел бы узлом с огромной влажностью."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if math.isnan(number) or abs(number) >= MISSING_ABOVE:
        return float("nan")
    return number


def has_data(values: Iterable) -> bool:
    return any(not math.isnan(clean(v)) for v in values)


def select_nodes(lats: Sequence[float], lons: Sequence[float],
                 has_values: Callable[[int, int], bool], *,
                 keep: Callable[[float, float], Optional[str]],
                 offset: tuple[int, int] = (0, 0)
                 ) -> tuple[list[tuple[int, int]], collections.Counter]:
    """Узлы, которые идут в слой, и почему не пошли остальные.

    `keep(lat, lon)` возвращает причину отказа или None. Индексы на выходе —
    в полной сетке файла (`offset` — где начинается прочитанный кусок).
    """
    taken = []
    reasons: collections.Counter = collections.Counter()
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            reason = keep(lat, lon)
            # Море считается морем, где бы оно ни лежало: иначе Северный
            # Ледовитый океан записался бы в «вне РИ/СССР» рядом с Китаем.
            if reason != REASON_BBOX and not has_values(i, j):
                reason = REASON_SEA
            if reason is not None:
                reasons[reason] += 1
                continue
            taken.append((i + offset[0], j + offset[1]))
    reasons["в слое"] = len(taken)
    return taken, reasons


def make_keep(territory: Optional["Territory"], *,
              foreign: Optional["Territory"] = None,
              exclude_bbox: Optional[tuple] = ERDA.bbox,
              step: float = 0.5) -> Callable[[float, float], Optional[str]]:
    """Сито узлов: рамка проекта, охват ERDA, территория РИ/СССР — по порядку.

    Узел в РИ/СССР, если центр его клетки внутри `territory`. Есть исключение —
    побережье: полигоны CShapes обобщены, и центр прибрежной клетки, у которой
    GEDA видит сушу, часто ложится в море (при первом сборе таких клеток 441,
    4% слоя). Поэтому клетка, чей центр не попал ни в одно государство
    (`foreign` — все остальные государства набора), берётся, если в
    `territory` лежит хоть один её угол. Центр в Китае или Монголии клетку не
    пускает, даже если угол заходит в Россию.
    """
    half = step / 2

    def keep(lat: float, lon: float) -> Optional[str]:
        if not valid_coords(lat, lon) or not in_bbox(lat, lon):
            return REASON_BBOX
        if exclude_bbox is not None and in_bbox(lat, lon, exclude_bbox):
            return REASON_ERDA
        if territory is None or territory.contains(lat, lon):
            return None
        if foreign is not None and not foreign.contains(lat, lon) and any(
                territory.contains(lat + dy, lon + dx)
                for dy in (-half, half) for dx in (-half, half)):
            return None
        return REASON_ABROAD

    return keep


def node_number(i: int, j: int, n_lons: int) -> int:
    """Номер узла в полной сетке файла: строка широты × длина строки + долгота.
    Номер не зависит от окна чтения и годится в `source_id`."""
    return i * n_lons + j


class Territory:
    """Территория по полигонам: точка внутри, если внутри хоть одного из них.

    Узлов десять тысяч, а у полигона России двадцать тысяч вершин и семнадцать
    периодов, так что луч из `ghcn._in_ring` по каждой точке занял бы минуты.
    Сетка же регулярная: на одной широте лежат сотни узлов. Поэтому рёбра
    раскладываются по градусным полосам широты, пересечения луча с границей
    считаются один раз на широту, а дальше для каждой долготы — двоичный поиск
    по ним. Правило то же — чёт-нечет, дырки полигонов учитываются сами.
    """

    def __init__(self, geometries: Iterable[dict]) -> None:
        self._shapes: list[dict[int, list[tuple[float, float, float, float]]]] = []
        for geometry in geometries:
            bands: dict[int, list] = collections.defaultdict(list)
            for ring in rings(geometry):
                for k in range(len(ring)):
                    x1, y1 = ring[k - 1][0], ring[k - 1][1]
                    x2, y2 = ring[k][0], ring[k][1]
                    if y1 == y2:
                        continue
                    for band in range(math.floor(min(y1, y2)), math.floor(max(y1, y2)) + 1):
                        bands[band].append((x1, y1, x2, y2))
            if bands:
                self._shapes.append(dict(bands))
        self._rows: dict[tuple[int, float], list[float]] = {}

    @classmethod
    def load(cls, path: Path, *, gwcode: int = RUSSIA_GWCODE,
             others: bool = False) -> "Territory":
        """Россия и СССР всех периодов из выгрузки CShapes — или, с `others`,
        все остальные государства набора (для прибрежных клеток, см. `make_keep`)."""
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GedaError(
                f"нет файла границ {path}: отделить РИ/СССР от Китая и Монголии нечем. "
                "Соберите границы: python3 scripts/harvest_cshapes.py --build"
            ) from exc
        except ValueError as exc:
            raise GedaError(f"{path}: не разбирается как GeoJSON ({exc})") from exc
        geometries = [f.get("geometry") for f in payload.get("features", [])
                      if ((f.get("properties") or {}).get("gwcode") == gwcode) != others]
        territory = cls(g for g in geometries if g)
        if not territory._shapes:
            raise GedaError(f"{path}: нет ни одного полигона с gwcode={gwcode}")
        return territory

    def __len__(self) -> int:
        return len(self._shapes)

    def contains(self, lat: float, lon: float) -> bool:
        for index in range(len(self._shapes)):
            crossings = self._crossings(index, lat)
            # Луч вправо: сколько пересечений правее точки. Нечётно — внутри.
            if (len(crossings) - bisect.bisect_right(crossings, lon)) % 2:
                return True
        return False

    def _crossings(self, index: int, lat: float) -> list[float]:
        key = (index, lat)
        row = self._rows.get(key)
        if row is None:
            row = sorted(
                (x2 - x1) * (lat - y1) / (y2 - y1) + x1
                for x1, y1, x2, y2 in self._shapes[index].get(math.floor(lat), ())
                if (y1 > lat) != (y2 > lat)
            )
            self._rows[key] = row
        return row


# --- сверка с ERDA в общей полосе -------------------------------------------

@dataclass(frozen=True)
class Agreement:
    """Как GEDA сходится с ERDA на общих узлах: из этого выведены порог и шкала."""

    nodes: int
    pairs: int
    median_r: float
    # порог Палмера ERDA → (доля узлов-лет ERDA ниже него, сигма GEDA с той же
    # долей, доля этих узлов-лет, где и GEDA не выше найденной сигмы)
    levels: dict


def agreement(pairs: Iterable[tuple[Sequence[float], Sequence[float]]],
              palmer: Sequence[float] = (-4.0, -3.0, -2.0)) -> Agreement:
    """Сверяет ряды ERDA (PDSI) и GEDA (σ) по одним и тем же узлам и годам."""
    erda_all: list[float] = []
    geda_all: list[float] = []
    rs = []
    nodes = 0
    for erda, geda in pairs:
        both = [(e, g) for e, g in zip(erda, geda)
                if not math.isnan(clean(e)) and not math.isnan(clean(g))]
        if len(both) < 3:
            continue
        nodes += 1
        es = [e for e, _ in both]
        gs = [g for _, g in both]
        erda_all.extend(es)
        geda_all.extend(gs)
        r = _pearson(es, gs)
        if r is not None:
            rs.append(r)
    if not erda_all:
        raise GedaError("у ERDA и GEDA не нашлось ни одного общего узла-года")
    ordered = sorted(geda_all)
    levels = {}
    for limit in palmer:
        dry = [g for e, g in zip(erda_all, geda_all) if e <= limit]
        share = len(dry) / len(erda_all)
        sigma = ordered[max(0, min(len(ordered) - 1, round(share * len(ordered)) - 1))]
        hit = sum(1 for g in dry if g <= sigma) / len(dry) if dry else 0.0
        levels[limit] = (share, sigma, hit)
    rs.sort()
    median = rs[len(rs) // 2] if rs else float("nan")
    return Agreement(nodes=nodes, pairs=len(erda_all), median_r=median, levels=levels)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


# --- записи ----------------------------------------------------------------

def sigma_class(z: float) -> str:
    """Шкала словами в сигмах (см. `SIGMA_CLASSES`)."""
    for limit, name in SIGMA_CLASSES:
        if z <= limit:
            return name
    return "сухой год"


def episodes_to_records(episodes: Iterable[Episode], *,
                        spec: LayerSpec = DROUGHT_ATLAS_GEDA) -> list[ContextRecord]:
    """По записи на узел и эпизод — как в `drought.episodes_to_records`, но в сигмах.

    Описание короче, чем у ERDA, и это не скупость: записей десятки тысяч, а
    всё общее (что это реконструкция, почему в сигмах, чем ограничена) стоит
    один раз в карточке слоя.
    """
    out = []
    for episode in episodes:
        point = episode.point
        category = sigma_class(episode.worst)
        single = episode.year_from == episode.year_to
        span = f"{episode.year_from}" if single else f"{episode.year_from}–{episode.year_to}"
        out.append(spec.new_record(
            title=f"{category.capitalize()} {span} {'года' if single else 'годов'}",
            category=category,
            lat=point.lat, lon=point.lon,
            place_text=place_text(point),
            summary=build_summary(episode, category),
            year_from=episode.year_from, year_to=episode.year_to,
            date_precision="year",
            period_raw=span,
            source=f"{GEDA.title}. {GEDA.citation}",
            url=DOI_URL,
            source_id=f"{GEDA.key}:{point.number}:{episode.year_from}",
            extra={"sigma": list(episode.values), "gridpt": point.number},
        ))
    return out


def to_records(atlas: Atlas, *, threshold: float = THRESHOLD,
               year_from: int, year_to: int) -> list[ContextRecord]:
    """Атлас → засухи ниже порога → записи. Сито узлов уже пройдено при чтении."""
    episodes = find_episodes(atlas, threshold=threshold, year_from=year_from,
                             year_to=year_to, require_bbox=True)
    return episodes_to_records(episodes)


def build_summary(episode: Episode, category: str) -> str:
    parts = [f"Летний scPDSI {_num(episode.worst)}σ от нормы 1000–2020 годов — {category}"]
    if episode.year_to > episode.year_from:
        parts.append(f"сухих лет подряд {episode.year_to - episode.year_from + 1}, "
                     f"тяжелее всего {episode.worst_year}-й")
    return "; ".join(parts) + ". Реконструкция GEDA по кольцам деревьев, не наблюдение."


# --- мелочи ----------------------------------------------------------------

def _num(value: float) -> str:
    return f"{value:.1f}".replace("-", "−")


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def _span(axis: Sequence[float], low: float, high: float) -> tuple[int, int]:
    """Срез возрастающей оси от `low` до `high` включительно."""
    if list(axis) != sorted(axis):
        raise GedaError("ось в файле не возрастает — разбор рассчитан на возрастающую")
    start = bisect.bisect_left(axis, low)
    stop = bisect.bisect_right(axis, high)
    if start >= stop:
        raise GedaError(f"в файле нет значений оси между {low} и {high}")
    return start, stop
