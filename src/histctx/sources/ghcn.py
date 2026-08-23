"""GHCN: месячные ряды станций NOAA, приведённые к общему виду проекта.

Зачем именно GHCN. Расчёт аномалий в `histctx.sources.weather` был написан
раньше, чем нашёлся ряд: скрипт сбора принимал «уже скачанный файл», а качать
его было неоткуда — слой стоял объявленным и пустым. GHCN-M закрывает ровно
это. Он собран NOAA из национальных архивов, лежит целиком одним файлом и
достаёт до XIX века: Астрахань — с 1846 года, Петербург, Москва и Казань —
с сороковых-пятидесятых. Ни один другой открытый набор не даёт по России
такой глубины.

Два набора, один формат идентификаторов:

* **температура** — GHCN-M v4 (`ghcnm.tavg.latest.qcu.tar.gz`), месячная
  средняя, сотые доли °C, файл фиксированной ширины;
* **осадки** — GHCN-M v4 precipitation (2024), месячная сумма, десятые доли
  мм, по файлу CSV на станцию внутри архива.

Идентификатор станции в обоих один и тот же (`RSM00034880` — Астрахань),
поэтому температура и осадки сходятся в один ряд без сопоставления по
координатам.

Что здесь есть и чего нет. Модуль разбирает форматы GHCN и переводит их
в приведённый ряд (`histctx.sources.weather.COLUMNS`) — и только. Что считать
засухой, решает `weather.py`, и это разделение намеренное: форматов у
метеоданных много, а «что считать засухой» одно.

Границы отбора. Берутся станции в границах Российской империи и СССР: код
страны в идентификаторе GHCN плюс общая рамка охвата (`histctx.geo.in_bbox`).
Финляндия и Царство Польское в списке стран есть — до 1917 года это империя,
и метрики оттуда в родословных встречаются постоянно.

Губерния берётся не из GHCN (её там нет), а по координате станции из
полигонов переписи 1897 года — тех самых, что лежат в `data/out/boundaries`.
Без губернии территориальный слой `weather_regions` не построится: усреднять
по губернии нечего, если у станции её нет.

Права. Данные NOAA/NCEI — работа правительства США и потому общественное
достояние; ограничений на использование нет, NOAA требует ссылки на набор и
гарантий точности не даёт. В записи это попадает при сборе, ключами
`--license` и `--url`: у погоды права зависят от ряда, а не от слоя, поэтому
в спецификации слоя их нет. Готовые формулировки — `LICENSE` и `CITATION`
ниже, и `--fetch` печатает их вместе с командой сборки.
"""

from __future__ import annotations

import csv
import json
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from ..geo import in_bbox
from ..schema import clean_text
from .weather import COLUMNS, GHCN_URL

BASE = "https://www.ncei.noaa.gov"

# Температура: у NOAA есть постоянная ссылка «latest», и она избавляет от
# разбора листинга каталога. qcu — ряд как измерен; qcf — он же, выровненный
# по соседним станциям. По умолчанию берём неисправленный: аномалию мы ищем
# в отдельном годе, а однородность правит уровень ряда в целом.
TAVG_URL = {
    "qcu": f"{BASE}/pub/data/ghcn/v4/ghcnm.tavg.latest.qcu.tar.gz",
    "qcf": f"{BASE}/pub/data/ghcn/v4/ghcnm.tavg.latest.qcf.tar.gz",
}

# Осадки: постоянной ссылки «latest» у набора нет, имя архива несёт дату
# сборки — приходится читать листинг каталога и брать последний.
PRCP_DIR = f"{BASE}/data/global-historical-climatology-network-monthly/v4/precipitation"
PRCP_ARCHIVE_INDEX = f"{PRCP_DIR}/archive/"

# Страница набора у NOAA. Живёт в `weather.py` — оттуда её берут спецификации
# слоёв, а слой должен ссылаться туда же, куда сборщик.
PRODUCT_URL = GHCN_URL

SOURCE = "GHCN-M v4, NOAA NCEI"

LICENSE = (
    "данные NOAA/NCEI — общественное достояние (работа правительства США), "
    "ограничений на использование нет; NOAA требует ссылки на набор "
    "и гарантий точности не даёт"
)

CITATION = (
    "Menne M. J., Williams C. N., Gleason B. E., Rennie J. J., Lawrimore J. H. (2018) "
    "Global Historical Climatology Network — Monthly Temperature, Version 4, "
    "doi:10.1175/JCLI-D-18-0094.1; Applequist S., Durre I., Vose R. (2024) "
    "GHCN Monthly Precipitation, Version 4, doi:10.25921/67zp-5m03"
)

# Заголовки HTTP кодируются latin-1 — в User-Agent только ASCII.
USER_AGENT = (
    "histctx/0.2 (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

# Коды стран в идентификаторе GHCN (первые два знака, FIPS). Список — это
# территория Российской империи и СССР, а не сегодняшняя Россия: предок из
# Ковенской губернии искать себя будет в литовских станциях, а не в русских.
EMPIRE_COUNTRIES = {
    "RS",              # Россия
    "UP", "BO", "MD",  # Украина, Белоруссия, Молдавия
    "EN", "LG", "LH",  # Эстония, Латвия, Литва
    "GG", "AM", "AJ",  # Грузия, Армения, Азербайджан
    "KZ", "KG", "TI", "TX", "UZ",   # Казахстан и Средняя Азия
    "FI",              # Великое княжество Финляндское, до 1917 года
    "PL",              # Царство Польское, до 1915 года
}

# Годы, ради которых слой собирается. Верхняя граница здесь не прихоть:
# норма считается по самому ряду, и если досыпать в него потепление последних
# десятилетий, норма уедет вверх, а холодные годы XIX века посыплются в слой
# толпой. Ряд обрезается до эпохи, про которую слой отвечает.
YEARS = (1800, 1960)

# Полигоны губерний переписи 1897 года: единственное место в проекте, откуда
# у станции может взяться губерния.
PROVINCES_PATH = Path("data/out/boundaries/provinces_1897.geojson")
PROVINCE_NAME_FIELD = "prov_RU"

# «Тифлисская губерния вкл. Закатальский округ» и «Тифлисская губерния без
# Закатальского округа» — в наборе переписи это два наложенных полигона одной
# и той же губернии. Оговорка в названии для карты важна, для усреднения
# погоды — нет: без неё две половины губернии считались бы разными.
_RE_PROVINCE_QUALIFIER = re.compile(r"\s+(?:вкл\.|без)\s+.*$")

MISSING = -9999          # пропуск в обоих наборах
TRACE = -1               # «след осадков» в наборе осадков: меньше 0.05 мм


class GhcnError(RuntimeError):
    """Файл GHCN не скачался или разбирается не так, как мы ожидаем."""


@dataclass(frozen=True)
class Station:
    """Станция GHCN: то, что известно о месте наблюдения."""

    station_id: str
    lat: float
    lon: float
    name: str

    @property
    def country(self) -> str:
        return self.station_id[:2]

    @property
    def in_empire(self) -> bool:
        """Станция в границах империи или СССР — по стране и по общей рамке."""
        return self.country in EMPIRE_COUNTRIES and in_bbox(self.lat, self.lon)


@dataclass(frozen=True)
class Reading:
    """Одно месячное значение: станция, год, месяц, показатель."""

    station_id: str
    year: int
    month: int
    field: str        # tavg | prcp
    value: float


# --- разбор форматов -------------------------------------------------------

def parse_inventory(lines: Iterable[str]) -> dict[str, Station]:
    """Разбирает `.inv` набора температуры (фиксированная ширина).

    ID 1-11, широта 13-20, долгота 22-30, название 39-68 — так в readme
    GHCN-M v4. Строка, в которой на месте координат не число, пропускается:
    в реестре 27 тысяч станций, и одна битая строка не повод остановить сбор.
    """
    out: dict[str, Station] = {}
    for line in lines:
        if len(line) < 30:
            continue
        station = _station(line[0:11], line[12:20], line[21:30], line[38:68])
        if station is not None:
            out[station.station_id] = station
    return out


def parse_tavg(lines: Iterable[str], *, stations: dict[str, Station],
               years: tuple[int, int] = YEARS) -> Iterator[Reading]:
    """Разбирает `.dat` набора температуры: строка — станция и год, 12 значений.

    Значение занимает 5 знаков, за ним три флага; забракованное контролем
    качества (непустой QCFLAG) значением не считается — как и `-9999`.
    Температура хранится в сотых долях градуса.
    """
    for line in lines:
        station_id = line[0:11]
        if station_id not in stations:
            continue
        if line[15:19] != "TAVG":
            continue
        year = _int(line[11:15])
        if year is None or not years[0] <= year <= years[1]:
            continue
        for month in range(1, 13):
            start = 19 + (month - 1) * 8
            value = _int(line[start:start + 5])
            qc_flag = line[start + 6:start + 7].strip()
            if value is None or value == MISSING or qc_flag:
                continue
            yield Reading(station_id, year, month, "tavg", value / 100.0)


def parse_prcp(lines: Iterable[str], *,
               years: tuple[int, int] = YEARS) -> Iterator[tuple[Station, Reading]]:
    """Разбирает файл одной станции из набора осадков.

    Файл выглядит как CSV, но по readme это фиксированная ширина, и разбирать
    его по запятым нельзя: название станции стоит в кавычках с выравниванием
    пробелами, и запятая внутри названия сдвинула бы все колонки.

    В отличие от температуры, метаданные станции стоят в каждой строке —
    поэтому станция возвращается вместе со значением. Осадки хранятся
    в десятых долях мм; `-1` означает «след осадков», и это не пропуск,
    а ноль с оговоркой: осадки были, но измерить их нечем.
    """
    for line in lines:
        if len(line) < 96:
            continue
        station = _station(line[0:11], line[53:62], line[63:73], line[12:52])
        if station is None:
            continue
        year, month = _int(line[83:87]), _int(line[87:89])
        if year is None or month is None or not 1 <= month <= 12:
            continue
        if not years[0] <= year <= years[1]:
            continue
        value = _int(line[90:96])
        qc_flag = line[99:100].strip()
        if value is None or value == MISSING or qc_flag:
            continue
        millimetres = 0.0 if value == TRACE else value / 10.0
        yield station, Reading(station.station_id, year, month, "prcp", millimetres)


def series_rows(readings: Iterable[Reading], stations: dict[str, Station], *,
                provinces: Optional["Provinces"] = None) -> list[dict]:
    """Сводит значения в приведённый ряд: строка — станция, год и месяц.

    Порядок колонок — `weather.COLUMNS`: этот файл потом читается тем же
    `--probe`/`--build`, что и любой другой ряд, и ничего про GHCN не знает.
    """
    merged: dict[tuple[str, int, int], dict] = {}
    for reading in readings:
        key = (reading.station_id, reading.year, reading.month)
        merged.setdefault(key, {})[reading.field] = reading.value

    regions: dict[str, Optional[str]] = {}
    out = []
    for (station_id, year, month), values in sorted(merged.items()):
        station = stations.get(station_id)
        if station is None:
            continue
        if station_id not in regions:
            regions[station_id] = (provinces.region_for(station.lat, station.lon)
                                   if provinces else None)
        out.append({
            "station_id": station_id,
            "name": station.name,
            "lat": station.lat,
            "lon": station.lon,
            "region": regions[station_id] or "",
            "year": year,
            "month": month,
            "tavg": _round(values.get("tavg"), 2),
            "prcp": _round(values.get("prcp"), 1),
        })
    return out


def write_series(rows: Iterable[dict], path: Path) -> int:
    """Пишет приведённый ряд в CSV с колонками `weather.COLUMNS`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


# --- губерния по координате ------------------------------------------------

class Provinces:
    """Губернии переписи 1897 года: по координате станции — название.

    Полигоны уже лежат в проекте как подложка карты (`data/out/boundaries`),
    и это единственный способ узнать губернию станции: в GHCN её нет, а по
    названию станции латиницей губернию не восстановить.
    """

    def __init__(self, areas: list[tuple[str, list, tuple]]) -> None:
        self._areas = areas

    @classmethod
    def load(cls, path: Path, *, field: str = PROVINCE_NAME_FIELD) -> "Provinces":
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GhcnError(
                f"нет файла границ {path}: губернию станции взять неоткуда. "
                "Соберите границы (см. docs/HARVEST.md) или укажите --no-regions"
            ) from exc
        except json.JSONDecodeError as exc:
            raise GhcnError(f"{path}: не разбирается как GeoJSON ({exc})") from exc

        areas = []
        for feature in payload.get("features", []):
            name = _province_name(feature.get("properties", {}).get(field))
            geometry = feature.get("geometry") or {}
            polygons = _polygons(geometry)
            if not name or not polygons:
                continue
            areas.append((name, polygons, _bounds(polygons)))
        if not areas:
            raise GhcnError(f"{path}: не нашлось ни одного полигона с полем {field!r}")
        return cls(areas)

    def region_for(self, lat: float, lon: float) -> Optional[str]:
        for name, polygons, bounds in self._areas:
            lon_min, lat_min, lon_max, lat_max = bounds
            if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
                continue
            for rings in polygons:
                if _in_ring(lon, lat, rings[0]) and not any(
                        _in_ring(lon, lat, hole) for hole in rings[1:]):
                    return name
        return None

    def __len__(self) -> int:
        return len(self._areas)


# --- сеть ------------------------------------------------------------------

def download(url: str, dest: Path, *, timeout: int = 600, refresh: bool = False) -> Path:
    """Скачивает файл, если его ещё нет.

    Архивы GHCN весят десятки и сотни мегабайт, а пересобирается слой чаще,
    чем NOAA их обновляет: скачанное складывается рядом с выгрузкой и второй
    раз не забирается.
    """
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, \
                partial.open("wb") as fh:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    except urllib.error.HTTPError as exc:
        raise GhcnError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GhcnError(f"{url}: сеть недоступна ({exc.reason})") from exc
    partial.replace(dest)
    return dest


def latest_prcp_archive(*, timeout: int = 120) -> str:
    """Имя архива осадков меняется с каждой сборкой — берём последний в листинге."""
    request = urllib.request.Request(PRCP_ARCHIVE_INDEX, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            listing = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise GhcnError(f"{PRCP_ARCHIVE_INDEX}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GhcnError(f"{PRCP_ARCHIVE_INDEX}: сеть недоступна ({exc.reason})") from exc
    # urljoin, а не склейка строк: сегодня NOAA отдаёт в листинге голые имена
    # файлов, но ссылка от корня сайта тоже законна, и склейка дала бы 404.
    return urllib.parse.urljoin(PRCP_ARCHIVE_INDEX, newest_archive(listing))


def newest_archive(listing: str) -> str:
    """Последний по имени архив в листинге каталога.

    Имя несёт дату сборки (`..._c20260804.tar.gz`), поэтому «последний по
    алфавиту» и есть «самый свежий».
    """
    names = sorted(set(re.findall(r'href="([^"]+\.tar\.gz)"', listing)))
    if not names:
        raise GhcnError(f"{PRCP_ARCHIVE_INDEX}: в листинге нет ни одного архива")
    return names[-1]


def read_tavg_archive(path: Path) -> tuple[dict[str, Station], Iterator[str]]:
    """Реестр станций и построчный поток данных из архива температуры.

    Реестр небольшой и читается целиком, а данные (170 МБ распакованными)
    отдаются построчно: держать их в памяти списком незачем.
    """
    inventory = parse_inventory(_read_member(path, ".inv"))
    if not inventory:
        raise GhcnError(f"{path}: в архиве нет реестра станций (.inv) — формат изменился?")
    return inventory, _iter_member(path, ".dat")


def _read_member(path: Path, suffix: str) -> list[str]:
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            if member.isfile() and member.name.endswith(suffix):
                handle = tar.extractfile(member)
                if handle is not None:
                    return handle.read().decode("utf-8", "replace").splitlines()
    return []


def _iter_member(path: Path, suffix: str) -> Iterator[str]:
    found = False
    with tarfile.open(path, "r|gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(suffix):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            found = True
            for chunk in handle:
                yield chunk.decode("utf-8", "replace").rstrip("\r\n")
    if not found:
        raise GhcnError(f"{path}: в архиве нет файла {suffix} — формат изменился?")


def read_prcp_archive(path: Path, *, countries: Iterable[str] = EMPIRE_COUNTRIES
                      ) -> Iterator[str]:
    """Идёт по архиву осадков потоком и отдаёт строки нужных станций.

    В архиве больше ста тысяч файлов — по одному на станцию. Распаковывать
    его целиком незачем: страна станции видна из имени файла, и всё лишнее
    пропускается, не читаясь.
    """
    wanted = tuple(countries)
    with tarfile.open(path, "r|gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".csv"):
                continue
            if not Path(member.name).name.startswith(wanted):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            yield from handle.read().decode("utf-8", "replace").splitlines()


# --- сбор целиком ----------------------------------------------------------

def collect(cache_dir: Path, *, years: tuple[int, int] = YEARS,
            provinces: Optional[Provinces] = None, flavour: str = "qcu",
            refresh: bool = False, log=None) -> tuple[list[dict], dict]:
    """Скачивает оба набора и возвращает приведённый ряд и счётчики сбора."""
    say = log or (lambda *_: None)
    cache_dir = Path(cache_dir)
    if flavour not in TAVG_URL:
        raise GhcnError(f"неизвестный вид ряда температуры {flavour!r}: "
                        f"годятся {', '.join(sorted(TAVG_URL))}")

    tavg_url = TAVG_URL[flavour]
    say(f"температура: {tavg_url}")
    tavg_path = download(tavg_url, cache_dir / Path(tavg_url).name, refresh=refresh)
    inventory, data_lines = read_tavg_archive(tavg_path)
    stations = {sid: st for sid, st in inventory.items() if st.in_empire}
    say(f"  станций в реестре: {len(inventory)}, из них в границах РИ/СССР: {len(stations)}")

    readings = list(parse_tavg(data_lines, stations=stations, years=years))
    tavg_values = len(readings)
    say(f"  значений температуры за {years[0]}–{years[1]}: {tavg_values}")

    prcp_url = latest_prcp_archive()
    say(f"осадки: {prcp_url}")
    prcp_path = download(prcp_url, cache_dir / Path(prcp_url).name, refresh=refresh)
    prcp_stations = 0
    prcp_values = 0
    for station, reading in parse_prcp(read_prcp_archive(prcp_path), years=years):
        if not station.in_empire:
            continue
        if station.station_id not in stations:
            # Станция только с осадками — самая полезная половина слоя:
            # засуха считается по ним, а температуры за XIX век часто нет.
            stations[station.station_id] = station
            prcp_stations += 1
        readings.append(reading)
        prcp_values += 1
    say(f"  значений осадков за {years[0]}–{years[1]}: {prcp_values}"
        f" (станций только с осадками: {prcp_stations})")

    rows = series_rows(readings, stations, provinces=provinces)
    stats = {
        "stations": len({row["station_id"] for row in rows}),
        "rows": len(rows),
        "tavg": tavg_values,
        "prcp": prcp_values,
        "regions": len({row["region"] for row in rows if row["region"]}),
        "stations_with_region": len({row["station_id"] for row in rows if row["region"]}),
        "rows_with_region": sum(1 for row in rows if row["region"]),
    }
    return rows, stats


# --- мелочи ----------------------------------------------------------------

def _station(station_id, lat, lon, name) -> Optional[Station]:
    sid = (station_id or "").strip()
    latitude, longitude = _float(lat), _float(lon)
    if len(sid) != 11 or latitude is None or longitude is None:
        return None
    return Station(station_id=sid, lat=latitude, lon=longitude,
                   name=_station_name(name) or sid)


def _station_name(name) -> Optional[str]:
    """«RAS_AL_KHAIMAH» → «Ras Al Khaimah».

    Названия в GHCN — латиница заглавными. Переводить их в русское написание
    нечем: справочника соответствий у нас нет, а придумывать — врать. Поэтому
    только убираем подчёркивания и капслок.
    """
    text = clean_text((name or "").replace("_", " ").strip().strip('"'))
    return text.title() if text else None


def _province_name(name) -> Optional[str]:
    text = clean_text(name)
    return clean_text(_RE_PROVINCE_QUALIFIER.sub("", text)) if text else None


def _polygons(geometry: dict) -> list:
    """Полигоны фигуры одним списком колец. Пустые кольца отбрасываются.

    Пустой полигон в наборе границ — не повод падать с IndexError где-то
    в подсчёте рамки: такая фигура просто ничего не накрывает.
    """
    kind = geometry.get("type")
    if kind == "Polygon":
        candidates = [geometry.get("coordinates") or []]
    elif kind == "MultiPolygon":
        candidates = list(geometry.get("coordinates") or [])
    else:
        return []
    return [rings for rings in candidates if rings and rings[0]]


def _bounds(polygons: list) -> tuple:
    lons = [point[0] for rings in polygons for point in rings[0]]
    lats = [point[1] for rings in polygons for point in rings[0]]
    return (min(lons), min(lats), max(lons), max(lats))


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    """Луч вправо: нечётное число пересечений — точка внутри кольца."""
    inside = False
    count = len(ring)
    previous = count - 1
    for current in range(count):
        x1, y1 = ring[current][0], ring[current][1]
        x2, y2 = ring[previous][0], ring[previous][1]
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < crossing:
                inside = not inside
        previous = current
    return inside


def _int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _round(value: Optional[float], digits: int):
    return "" if value is None else round(value, digits)
