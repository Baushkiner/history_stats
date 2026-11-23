"""Заселённость и распашка уезда по десятилетиям с 1700 года: сетка HYDE 3.2.1.

Зачем этот слой. Перепись 1897 года говорит, сколько людей жило в уезде в
одном году; ревизии дают податные души, а не всех. Между ними и до них —
пусто, а вопрос у генеалога простой: был ли этот край при прадеде уже
заселён и распахан или род пришёл на новое место. Слой отвечает оценкой:
плотность населения, доля пашни и доля пастбищ в границах уезда — на каждое
десятилетие с 1700 по 1960 год.

**Это модель, а не учёт.** HYDE (History Database of the Global Environment,
К. Кляйн Голдевейк, PBL и Утрехтский университет) раскладывает страновые и
региональные оценки населения и угодий по сетке 5′ с помощью весов —
пригодности почв, близости рек, современного расселения. Число «в уезде в
1750 году 41 тысяча жителей» — не найденный документ, а результат такого
распределения; ошибка в разы для отдельного уезда XVIII века возможна.
Поэтому запись помечена `date_approx`, в описании прямо сказано «оценка», а
сравнивать стоит не уезд с уездом, а уезд с самим собой через полвека.

Единица — уезд в границах 1897 года (RISTAT, `districts_1897.geojson`): в
1700 году таких границ не было, полигон здесь только способ назвать место.
Клетка относится к уезду, если её центр лежит внутри полигона. Площадь
клетки — сферическая (как `garea_cr.asc` самого набора); доля пашни — от
всей площади клеток уезда, у приморских и озёрных уездов она поэтому чуть
занижена.

Откуда берётся. Версия 3.2.1 (2017) лежит на станции данных DANS (Нидерланды)
под CC0 1.0; readme набора при этом называет CC BY 3.0 — записано и то и
другое, ссылка на набор стоит в каждой записи. Архив базового сценария —
5,3 ГБ: из него по заголовку Range берутся 81 сетка (население, пашня и
пастбища за 27 десятилетий), по 5–10 МБ сжатых. Архив сжат методом Deflate64,
которого нет в стандартной библиотеке: нужен пакет `inflate64` — только
сборщику, как `h5py` у засух GEDA.

Более новые версии (3.3, 3.4 и 3.5 под CC BY 4.0) лежат в хранилище Yoda
Утрехтского университета, а оно закрыто проверкой Anubis («докажи, что не
робот») — сборщик её не обходит.
"""

from __future__ import annotations

import collections
import io
import json
import math
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..net import RangeFile, fetch_bytes
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec
from .raster import rasterize as _rasterize
from .uezd_names import unit_name

DOI = "doi:10.17026/dans-25g-gez3"
DOI_URL = "https://doi.org/10.17026/dans-25g-gez3"
API_URL = ("https://archaeology.datastations.nl/api/datasets/:persistentId/"
           "?persistentId=doi:10.17026/dans-25g-gez3")
FILE_URL = "https://archaeology.datastations.nl/api/access/datafile/{file_id}"
# Сверено с API станции данных 22.11.2026.
ARCHIVE_ID = 5490328
ARCHIVE_NAME = "HYDE3_2_1-baseline.zip"
ARCHIVE_SIZE = 5_339_653_974
LICENSE_NAME = "CC0-1.0"
DEFLATE64 = 9

YEARS = tuple(range(1700, 1961, 10))
# Переменная → (каталог в архиве, шаблон имени). Население — число жителей в
# клетке, угодья — км² в клетке.
VARIABLES = {
    "population": ("pop", "popc_{year}AD.asc"),
    "cropland": ("lu", "cropland{year}AD.asc"),
    "grazing": ("lu", "grazing{year}AD.asc"),
}

# Сетка набора и окно проекта в ней. Строки идут с севера на юг.
NCOLS, NROWS, CELL = 4320, 2160, 1 / 12
NODATA = -9999.0
LAT_MAX, LAT_MIN = 82.0, 35.0
LON_MIN, LON_MAX = 17.0, 190.5           # за 180° — Чукотка, как в полигонах RISTAT
ROW0 = round((90 - LAT_MAX) / CELL)
N_ROWS = round((LAT_MAX - LAT_MIN) / CELL)
COL0 = round((LON_MIN + 180) / CELL)
N_COLS = round((LON_MAX - LON_MIN) / CELL)
EARTH_R_KM = 6371.0088

CITATION = (
    "Klein Goldewijk, K., Beusen, A., Doelman, J., Stehfest, E. Anthropogenic land use "
    "estimates for the Holocene — HYDE 3.2. Earth System Science Data, 2017, 9, 927–953, "
    "doi:10.5194/essd-9-927-2017; набор: DANS Data Station Archaeology, "
    "doi:10.17026/dans-25g-gez3 (версия 3.2.1)"
)

POPULATION_HYDE = LayerSpec(
    slug="population_landuse_hyde",
    title="Заселённость и распашка уезда по десятилетиям, 1700–1960 (оценка HYDE)",
    group="admin",
    source="HYDE 3.2.1 (К. Кляйн Голдевейк и др.), DANS Data Station Archaeology",
    license=(
        "CC0 1.0 на карточке набора (DANS); readme набора называет CC BY 3.0 — ссылка на "
        "авторов и набор проставляется в каждую запись в любом случае"
    ),
    description=(
        "Был ли край уже заселён и распахан: оценка плотности населения, доли пашни и "
        "пастбищ в границах уезда 1897 года на каждое десятилетие с 1700 по 1960 год. "
        "Это модельная реконструкция по сетке 5′, а не учёт: страновые итоги разложены по "
        "клеткам весами, и для отдельного уезда XVIII века ошибка в разы возможна. "
        "Сравнивать стоит уезд с самим собой во времени, а не уезды между собой."
    ),
    url=DOI_URL,
    status="harvested",
    expected_rows=22248,     # сбор 22.11.2026: 824 уезда × 27 десятилетий
)


class HydeError(RuntimeError):
    """Архив не читается или устроен не так, как записано в коде."""


# --- архив -----------------------------------------------------------------

def member_name(variable: str, year: int) -> str:
    folder, pattern = VARIABLES[variable]
    return f"baseline/asc/{year}AD_{folder}/{pattern.format(year=year)}"


def check_manifest(payload: bytes) -> list[str]:
    """Расхождения карточки набора с записанным в коде: лицензия, файл, размер."""
    try:
        version = json.loads(payload)["data"]["latestVersion"]
    except (ValueError, KeyError, TypeError) as exc:
        return [f"ответ API не разбирается: {exc}"]
    problems = []
    license_name = (version.get("license") or {}).get("name")
    if license_name != LICENSE_NAME:
        problems.append(f"лицензия набора: ожидалась {LICENSE_NAME}, пришла {license_name}")
    files = {f.get("dataFile", {}).get("id"): f for f in version.get("files") or []}
    item = files.get(ARCHIVE_ID)
    if item is None:
        return problems + [f"файла с id {ARCHIVE_ID} в наборе нет"]
    if item.get("label") != ARCHIVE_NAME:
        problems.append(f"id {ARCHIVE_ID}: имя {item.get('label')}, ожидалось {ARCHIVE_NAME}")
    if item["dataFile"].get("filesize") != ARCHIVE_SIZE:
        problems.append(f"{ARCHIVE_NAME}: размер {item['dataFile'].get('filesize')}, "
                        f"в коде {ARCHIVE_SIZE}")
    return problems


def fetch_manifest() -> bytes:
    return fetch_bytes(API_URL, error=HydeError, timeout=60)


class Archive:
    """Архив на станции данных, читаемый кусками. Распаковка — `inflate64`."""

    def __init__(self) -> None:
        try:
            import inflate64  # noqa: F401
        except ImportError as exc:
            raise HydeError("архив HYDE сжат методом Deflate64: нужен пакет inflate64 "
                            "(pip install inflate64) — только этому сборщику") from exc
        self._inflate64 = inflate64
        self.file = RangeFile(FILE_URL.format(file_id=ARCHIVE_ID), error=HydeError,
                              tail=1 << 20, chunk=12 << 20)
        if self.file.size != ARCHIVE_SIZE:
            raise HydeError(f"{ARCHIVE_NAME}: размер {self.file.size}, в коде {ARCHIVE_SIZE}")
        self.zip = zipfile.ZipFile(self.file)

    def read(self, name: str) -> bytes:
        try:
            info = self.zip.getinfo(name)
        except KeyError as exc:
            raise HydeError(f"в архиве нет {name}") from exc
        if info.compress_type != DEFLATE64:
            return self.zip.read(info)
        self.file.seek(info.header_offset)
        header = self.file.read(30)
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        self.file.seek(info.header_offset + 30 + name_len + extra_len)
        raw = self.file.read(info.compress_size)
        data = self._inflate64.Inflater().inflate(raw)
        if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
            raise HydeError(f"{name}: распаковано {len(data)} байт, контрольная сумма "
                            "не сходится")
        return data


# --- сетка -----------------------------------------------------------------

def check_header(data: bytes) -> None:
    """Шапка ESRI ASCII grid: та ли сетка, под которую записано окно."""
    lines = data[:400].decode("ascii", "replace").splitlines()[:6]
    got = {}
    for line in lines:
        key, _, value = line.strip().partition(" ")
        try:
            got[key.lower()] = float(value)
        except ValueError:
            raise HydeError(f"шапка сетки не разбирается: {line!r}") from None
    want = {"ncols": NCOLS, "nrows": NROWS, "xllcorner": -180.0, "yllcorner": -90.0,
            "nodata_value": NODATA}
    for key, value in want.items():
        if got.get(key) != value:
            raise HydeError(f"сетка не та: {key} = {got.get(key)}, ожидалось {value}")
    if abs(got.get("cellsize", 0) - CELL) > 1e-5:
        raise HydeError(f"сетка не та: cellsize = {got.get('cellsize')}")


def read_window(data: bytes):
    """Окно проекта из сетки: массив float32 [N_ROWS × N_COLS], NODATA → 0.

    Столбцы идут от 17° в. д. через 180° до 169,5° з. д. — как в полигонах
    RISTAT, где Чукотка записана долготой больше 180.
    """
    import numpy as np
    import pandas as pd

    check_header(data)
    frame = pd.read_csv(io.BytesIO(data), sep=" ", skiprows=6 + ROW0, nrows=N_ROWS,
                        header=None, skipinitialspace=True)
    grid = frame.to_numpy(dtype=np.float32)[:, :NCOLS]
    if grid.shape != (N_ROWS, NCOLS):
        raise HydeError(f"окно сетки {grid.shape}, ожидалось {(N_ROWS, NCOLS)}")
    east = NCOLS - COL0
    window = np.concatenate([grid[:, COL0:], grid[:, :N_COLS - east]], axis=1)
    window = np.nan_to_num(window, nan=0.0)
    window[window <= NODATA] = 0.0
    return window


def cell_areas():
    """Площадь клетки по строкам окна, км² (сфера)."""
    import numpy as np

    north = np.radians(LAT_MAX - CELL * np.arange(N_ROWS))
    south = np.radians(LAT_MAX - CELL * (np.arange(N_ROWS) + 1))
    return (EARTH_R_KM ** 2 * math.radians(CELL) * (np.sin(north) - np.sin(south))).astype(
        np.float64)


def rasterize(geometries: Sequence[dict]):
    """Номер уезда для каждой клетки окна (−1 — ни один): см. `raster.rasterize`."""
    return _rasterize(geometries, lat_max=LAT_MAX, lon_min=LON_MIN, cell=CELL,
                      n_rows=N_ROWS, n_cols=N_COLS)


def aggregate(index, values, n: int):
    """Сумма значений сетки по полигонам."""
    import numpy as np

    mask = index >= 0
    return np.bincount(index[mask], weights=values[mask].astype(np.float64), minlength=n)


# --- записи ----------------------------------------------------------------

@dataclass(frozen=True)
class Unit:
    """Уезд 1897 года: как назвать и к какой губернии отнести."""

    key: str
    name: str
    province: str


def units_from(features: Iterable[dict]) -> list[Unit]:
    out = []
    for feature in features:
        props = feature.get("properties") or {}
        province = (props.get("prov_RU") or "").strip()
        name = unit_name((props.get("Name_RU") or "").strip(), province)
        # `Distr_ID` — номер уезда; `RISTAT_ID` в этом файле — номер губернии.
        out.append(Unit(key=str(props.get("Distr_ID")), name=name, province=province))
    return out


DENSITY_CLASSES = (
    (1.0, "почти не заселён (меньше 1 чел./км²)"),
    (5.0, "редко заселён (1–5 чел./км²)"),
    (20.0, "заселён умеренно (5–20 чел./км²)"),
    (50.0, "заселён плотно (20–50 чел./км²)"),
    (math.inf, "заселён очень плотно (больше 50 чел./км²)"),
)


def density_class(density: float) -> str:
    for limit, label in DENSITY_CLASSES:
        if density < limit:
            return label
    return DENSITY_CLASSES[-1][1]


def _people(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}".replace(".", ",") + " млн"
    if value >= 10_000:
        return f"{round(value / 1000)} тыс."
    if value >= 1000:
        return f"{value / 1000:.1f}".replace(".", ",") + " тыс."
    return f"{round(value)}"


def _num(value: float) -> str:
    digits = 0 if value >= 10 else 1 if value >= 1 else 2
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(share: float) -> str:
    pct = share * 100
    if 0 < pct < 0.1:
        return "меньше 0,1%"
    return f"{pct:.0f}%" if pct >= 10 else f"{pct:.1f}%".replace(".", ",")


@dataclass
class Estimate:
    population: float
    cropland: float
    grazing: float


def unit_records(unit: Unit, area_km2: float, cells: int,
                 series: dict[int, Estimate]) -> list[ContextRecord]:
    """Записи уезда по десятилетиям. Уезд без клеток не даёт ничего."""
    if cells == 0 or area_km2 <= 0:
        return []
    out = []
    years = sorted(series)
    place = f"{unit.name}, {unit.province}" if unit.province else unit.name
    for i, year in enumerate(years):
        est = series[year]
        density = est.population / area_km2
        crop, graze = est.cropland / area_km2, est.grazing / area_km2
        parts = [f"Оценка HYDE на {year} год: около {_people(est.population)} жителей, "
                 f"{_num(density)} чел./км²"]
        if i:
            before = series[years[i - 1]]
            if before.population > 0:
                change = (est.population / before.population - 1) * 100
                parts[0] += (f" ({'+' if change >= 0 else '−'}{abs(change):.0f}% за "
                             f"{year - years[i - 1]} лет)")
        parts.append(f"Пашня — {_pct(crop)} площади, пастбища и сенокосы — {_pct(graze)}")
        # Оговорка короткая и в каждой записи: длинная — в карточке слоя.
        parts.append("Модельная оценка в границах уезда 1897 года, не данные учёта")
        last = year == years[-1]
        out.append(POPULATION_HYDE.new_record(
            title=f"{place}: заселённость и распашка около {year} года",
            category=density_class(density),
            scope=SCOPE_REGION, place_text=place,
            region=unit.province or None, regions=[unit.province] if unit.province else [],
            district=unit.name,
            year_from=year, year_to=year if last else year + 9,
            date_precision="year" if last else "decade", date_approx=True,
            period_raw=f"{year} (оценка на начало десятилетия)",
            summary=". ".join(parts) + ".",
            url=DOI_URL,
            source_id=f"{unit.key}:{year}",
            # Площади угодий в км² не пишутся: это доля, умноженная на площадь.
            extra={"population": round(est.population),
                   "density_per_km2": round(density, 2),
                   "cropland_share": round(crop, 4), "grazing_share": round(graze, 4),
                   "area_km2": round(area_km2)},
        ))
    return out


def build_records(units: Sequence[Unit], index, grids: dict[int, dict]) -> list[ContextRecord]:
    """Записи слоя из карты «клетка → уезд» и сеток по годам.

    `grids[год]` — словарь переменная → окно сетки (`read_window`).
    """
    import numpy as np

    n = len(units)
    areas_by_row = cell_areas()
    area_grid = np.repeat(areas_by_row[:, None], N_COLS, axis=1)
    area = aggregate(index, area_grid, n)
    cells = np.bincount(index[index >= 0], minlength=n)
    sums = {year: {var: aggregate(index, grid, n) for var, grid in by_var.items()}
            for year, by_var in grids.items()}
    out = []
    for i, unit in enumerate(units):
        series = {year: Estimate(population=float(s["population"][i]),
                                 cropland=float(s["cropland"][i]),
                                 grazing=float(s["grazing"][i]))
                  for year, s in sums.items()}
        out += unit_records(unit, float(area[i]), int(cells[i]), series)
    return out


def coverage(units: Sequence[Unit], index) -> collections.Counter:
    import numpy as np

    cells = np.bincount(index[index >= 0], minlength=len(units))
    counts: collections.Counter = collections.Counter()
    counts["уездов"] = len(units)
    counts["уездов без единой клетки"] = int((cells == 0).sum())
    counts["клеток в уездах"] = int(cells.sum())
    return counts


def cache_path(cache_dir: Path, variable: str, year: int) -> Path:
    return Path(cache_dir) / f"{variable}_{year}.npy"


def load_grid(cache_dir: Path, variable: str, year: int, archive: Optional[Archive]):
    """Окно сетки из кэша; чего нет — берётся из архива и кладётся в кэш."""
    import numpy as np

    path = cache_path(cache_dir, variable, year)
    if path.exists():
        return np.load(path)
    if archive is None:
        raise HydeError(f"нет {path}: сначала --check или --fetch")
    window = read_window(archive.read(member_name(variable, year)))
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, window)
    return window
