"""Землетрясения и цунами 1600–1960 годов (NOAA NCEI, EMCA, GEM).

Зачем этот слой. Землетрясение — одно из немногих бедствий, которое
объясняет запись в метрике дословно: десятки похорон в один день, приход,
переведённый в соседнее село, храм, «вновь выстроенный» через три года.
Шемаха 1667 и 1902 годов, Верный 1887-го и 1911-го, Андижан 1902-го, Кеминское
1911-го, Ленинакан 1926-го, Крым 1927-го, Ашхабад 1948-го, Хаит 1949-го —
после каждого семьи уходили с места, а книги церквей и мечетей гибли вместе
со зданиями. Слой `disasters` из Викиданных знает на всю территорию 28
землетрясений; здесь их на порядок больше, с датой до дня, магнитудой и
числом жертв.

Наборы. Три каталога, и каждый закрывает своё:

* NOAA NCEI Global Significant Earthquake Database (doi:10.7289/V5TD9V7K) и
  Global Historical Tsunami Database (doi:10.7289/V5PN93H7) — «значимые»
  события: с жертвами, разрушениями, магнитудой от 7,5 или с цунами. Дата до
  дня, точка, магнитуда, интенсивность по шкале Меркалли, погибшие, раненые,
  разрушенные дома, ущерб — числом или порядком величины. Только здесь есть
  последствия, поэтому описание записи берётся отсюда. Отдаётся JSON по
  `hazard-service/api/v1/`; `robots.txt` сервера просит `Crawl-delay: 60`, и
  сбор его соблюдает: запросов около двадцати пяти, полчаса.
* EMCA Central Asia Earthquake Catalogue (GFZ, doi:10.5880/GFZ.EWS.2015.001,
  CC BY-SA 4.0) — однородный каталог Средней Азии и Кавказа с древности:
  33 620 событий, из них 1 446 за 1600–1960 годы. Даёт доинструментальные
  землетрясения, которых нет у NOAA, — магнитуда MLH (поверхностные волны,
  советская шкала), дата до дня, если она известна.
* GEM Global Homogenised Earthquake Catalogue v2026 (Zenodo 20716759, CC BY-SA
  4.0) — инструментальная эпоха с 1904 года: все события от M 5 с
  переопределённой точкой и однородной Mw (ISC-GEM, GCMT, ComCat). Точка у
  него лучше всех, поэтому координата сведённого события берётся отсюда.

Права. NOAA — общественное достояние (данные правительства США), EMCA и GEM —
CC BY-SA 4.0. Берутся факты — дата, точка, магнитуда, жертвы — со ссылкой на
каталог; у каждой записи в поле `license` стоят права именно её каталогов.

Что попадает в слой. Из каждого каталога — события 1600–1960 годов в
прямоугольнике охвата (`geo.BBOX_RU`); дальше решает рамка
(`histctx.frame`): губернии 1897 года и земли империи и СССР по CShapes.

* эпицентр в рамке — запись с губернией 1897 года, при любой магнитуде;
* эпицентр в море у берега рамки (Курилы, Камчатка, Крым, Каспий) —
  запись остаётся, если его могли почувствовать на берегу: «значимое» по
  NOAA — в поясе 150 км, остальное — до 25 км при любой магнитуде, до 75 км
  от M 6, до 150 км от M 7. `frame.py` ищет берег только в 0,3°, а
  курильские события лежат над желобом в 50–150 км от суши; без правила
  магнитуд слой заполнили бы сотни афтершоков 1952 года. Губерния у такой
  записи — губерния ближайшего берега, в `extra.frame` — расстояние;
* эпицентр на соседней земле не дальше 100 км от рамки — запись остаётся с
  пометкой `outside_bbox` и расстоянием до рамки, если событие «значимое»
  по NOAA или с магнитудой от 6: такое землетрясение в Хорасане или
  Синьцзяне рушило дома в Ашхабаде и Пржевальске. Ближе 25 км остаётся любое;
* остальное (Япония, Греция, Турция, Иран вдали от границы) в слой не идёт —
  это отбор, а не потеря: число отброшенных показывает `--check`.

Сведение каталогов. Одно событие разных каталогов — одна запись. Пары ищутся
по дате и расстоянию: при дате до дня — расхождение не больше суток и 150 км,
при месяце — тот же месяц и 100 км, при одном годе — 75 км и магнитуды не
дальше единицы. Каждое событие каталога сводится не больше чем с одним
событием другого, лучшие пары — первыми: афтершоки Шемахи 1671 года не
слипаются в одно землетрясение. Координата — GEM, иначе EMCA, иначе NOAA;
дата — самая точная, при равной точности NOAA; магнитуда — Mw GEM, иначе
NOAA, иначе MLH EMCA. Все каталоги события с их номерами и магнитудами — в
`extra.catalogs`.

Цунами. Цунами от землетрясения прикладывается к его записи (высота волны,
жертвы). Цунами без сведённого землетрясения — вулканическое, оползневое или
с очагом вне отбора — своя запись. Набеги цунами (`/tsunamis/runups`) — точки
побережья, куда дошла волна, — берутся по государствам рамки и только там,
где волна была от двух метров или были жертвы и разрушения: так на карте
оказываются Северо-Курильск 1952 года и Петропавловск 1841-го, а не сотни
мареографных отметок в пять сантиметров.

Даты. Каталоги дают дату по новому стилю. Метрическая книга писала по
старому, и у записей до 14 февраля 1918 года в описании стоит и юлианская
дата: Верненское землетрясение — 9 июня 1887 года, в метрике — 28 мая.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..frame import SHORE_STEPS, Banded, Frame, _rings
from ..geo import BBOX_RU, BBOX_RU_EAST, SpatialIndex, haversine_km, in_bbox
from ..io_formats import read_geojson
from ..net import RETRY_CODES, USER_AGENT, fetch_bytes
from ..schema import ContextRecord, LayerSpec
from .cshapes import touches_region

YEAR_MIN, YEAR_MAX = 1600, 1960

# --- NOAA NCEI --------------------------------------------------------------

NOAA_API = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/"
# `robots.txt` www.ngdc.noaa.gov: `Crawl-delay: 60` для всех. Путь
# `/hazel/` им не закрыт, но пауза между запросами — минута.
NOAA_PAUSE = 60.0
NOAA_EQ_PAGE = "https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/event-more-info/{}"
NOAA_TS_PAGE = "https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/event-more-info/{}"
NOAA_RUNUP_PAGE = "https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/runup-more-info/{}"
NOAA_EQ_DOI = "https://doi.org/10.7289/V5TD9V7K"
NOAA_TS_DOI = "https://doi.org/10.7289/V5PN93H7"

# Прямоугольники запроса — тот же охват, что `geo.BBOX_RU` и `BBOX_RU_EAST`:
# Чукотка заходит за 180-й меридиан, и её запрос отдельный.
RECTANGLES = {
    "rect": {"minLatitude": BBOX_RU[0], "maxLatitude": BBOX_RU[2],
             "minLongitude": BBOX_RU[1], "maxLongitude": BBOX_RU[3]},
    "east": {"minLatitude": BBOX_RU_EAST[0], "maxLatitude": BBOX_RU_EAST[2],
             "minLongitude": BBOX_RU_EAST[1], "maxLongitude": BBOX_RU_EAST[3]},
}
# Набеги цунами берутся по государствам с побережьем в рамке: в прямоугольнике
# их 12 270, и четыре пятых — японские берега.
RUNUP_COUNTRIES = ("RUSSIA", "UKRAINE", "GEORGIA", "AZERBAIJAN", "TURKMENISTAN",
                   "KAZAKHSTAN", "FINLAND", "ESTONIA", "LATVIA", "LITHUANIA")

# --- EMCA (GFZ) ---------------------------------------------------------------

EMCA_DOI = "10.5880/GFZ.EWS.2015.001"
EMCA_URL = ("https://datapub.gfz-potsdam.de/download/10.5880.GFZ.EWS.2015.001/"
            "EMCA_seismocatv1.0.zip")
# Сверено 22.11.2026: архив версии 1.0 от 2019 года. Другой размер или сумма
# — новая версия каталога, её сверяют руками.
EMCA_SIZE = 450_085
EMCA_MD5 = "a0b42e91d6979c59fdb2b6bb529cb255"
EMCA_CSV = "EMCA_SeismoCat_v1.0.csv"
EMCA_COLUMNS = ("id", "year", "month", "day", "lat", "lon", "fdepth", "mlh")

# --- GEM (Zenodo) -------------------------------------------------------------

GEM_RECORD_ID = "20716759"
GEM_DOI = "10.5281/zenodo.20716759"
GEM_FILES_API = f"https://zenodo.org/api/records/{GEM_RECORD_ID}/files"
GEM_KEY = "GEM_globcat26.zip"
GEM_URL = f"{GEM_FILES_API}/{GEM_KEY}/content"
GEM_SIZE = 18_291_863
GEM_MD5 = "6b22905b4cb3fc4611c65b40823501c0"
GEM_CSV = "GEM_globcat26/gem_globcat26.csv"
GEM_COLUMNS = ("eventID", "year", "month", "day", "latitude", "longitude", "depth",
               "magnitude")

CATALOG_URL = {
    "NOAA": NOAA_EQ_DOI,
    "EMCA": f"https://doi.org/{EMCA_DOI}",
    "GEM": f"https://doi.org/{GEM_DOI}",
}
CATALOG_SOURCE = {
    "NOAA": "NOAA NCEI, Global Significant Earthquake Database",
    "EMCA": "EMCA Central Asia Earthquake Catalogue (GFZ)",
    "GEM": "GEM Global Homogenised Earthquake Catalogue v2026",
}
CATALOG_LICENSE = {
    "NOAA": "общественное достояние (данные NOAA NCEI)",
    "EMCA": "CC BY-SA 4.0 (EMCA, GFZ Potsdam)",
    "GEM": "CC BY-SA 4.0 (GEM)",
}
CATALOG_ORDER = ("NOAA", "EMCA", "GEM")

LICENSE = (
    "NOAA NCEI — общественное достояние; EMCA (GFZ Potsdam) и GEM — CC BY-SA 4.0. "
    "Берутся факты — дата, точка, магнитуда, жертвы — со ссылкой на каталог; у "
    "записи стоят права её каталогов"
)

EARTHQUAKES = LayerSpec(
    slug="earthquakes",
    title="Землетрясения и цунами",
    group="hardship",
    source="NOAA NCEI (землетрясения и цунами), EMCA (GFZ), GEM",
    license=LICENSE,
    description=(
        "Почему в метрике десятки похорон в один день и почему приход отстроен "
        "заново: землетрясения 1600–1960 годов с датой до дня, магнитудой, числом "
        "погибших и разрушенных домов — Шемаха, Верный, Андижан, Ленинакан, Крым, "
        "Ашхабад, Хаит, — цунами Камчатки и Курил и побережья, куда дошла волна. "
        "Три каталога сведены в одно событие; у записей до 1918 года — дата и по "
        "старому стилю."
    ),
    url=NOAA_EQ_DOI,
    status="harvested",
    expected_rows=1425,
)

# Отбор у границ рамки, км.
SEA_KM = 150          # эпицентр в море — до берега рамки
BORDER_KM = 100       # эпицентр на соседней земле — до рамки
NEAR_KM = 25          # ближе этого соседнее событие берётся при любой магнитуде
BORDER_MAGNITUDE = 6.0
# Море: (до берега не дальше, км; магнитуда не меньше). «Значимые» события
# NOAA берутся на всём поясе в 150 км.
SEA_RULES = ((25, None), (75, 6.0), (150, 7.0))
RINGS_KM = (5, 10, 25, 50, 75, 100, 150)
BEARINGS = 16
CELL = 0.05           # клетка запоминания ответов «чья земля» на кольцах, градусы

# Набег цунами идёт в слой с волны от двух метров — или при жертвах и ущербе.
RUNUP_MIN_M = 2.0

# Подпись места: город в 30 км, иначе любое селение в 15 км.
TOWN_KM, VILLAGE_KM = 30.0, 15.0
TOWNS = ("город", "малый город")

OLD_STYLE_END = dt.date(1918, 2, 14)

MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря")

# Порядки величин NOAA там, где точного числа нет (`*AmountOrder`).
ORDER_PEOPLE = {1: "до 50", 2: "от 51 до 100", 3: "от 101 до 1000", 4: "больше тысячи"}
ORDER_DAMAGE = {1: "ограниченный (до $1 млн)", 2: "умеренный ($1–5 млн)",
                3: "тяжёлый ($5–25 млн)", 4: "крайне тяжёлый (от $25 млн)"}
# Причина цунами (`causeCode`) и достоверность (`eventValidity`) по NOAA.
TSUNAMI_CAUSE = {
    0: "причина неизвестна", 1: "землетрясение", 2: "землетрясение (под вопросом)",
    3: "землетрясение и оползень", 4: "вулкан и землетрясение",
    5: "вулкан, землетрясение и оползень", 6: "извержение вулкана",
    7: "вулкан и оползень", 8: "оползень", 9: "метеорологическая причина",
    10: "взрыв", 11: "астрономический прилив",
}
TSUNAMI_VALIDITY = {
    0: "сейш или волнение, а не цунами", 1: "очень сомнительное",
    2: "под вопросом", 3: "вероятное", 4: "достоверное",
}
# Магнитуда NOAA: какое из полей совпадает с выбранной `eqMagnitude`.
NOAA_MAG_TYPES = (("eqMagMw", "Mw"), ("eqMagMs", "Ms"), ("eqMagMb", "mb"),
                  ("eqMagMl", "ML"), ("eqMagMfa", "Mfa"), ("eqMagUnk", None))

KIND_FRAME, KIND_SEA, KIND_ABROAD, KIND_OFF = "frame", "sea", "abroad", "off"
OUTSIDE = "outside_bbox"


class EarthquakesError(RuntimeError):
    """Каталог не скачался, не сошёлся с ожидаемым или пришёл не в том виде."""


# --- события каталогов --------------------------------------------------------

@dataclass
class Event:
    """Землетрясение одного каталога, приведённое к общему виду."""

    catalog: str
    source_id: str
    year: int
    month: Optional[int]
    day: Optional[int]
    lat: float
    lon: float
    magnitude: Optional[float] = None
    mag_type: Optional[str] = None
    depth_km: Optional[float] = None
    fields: dict = field(default_factory=dict)

    @property
    def precision(self) -> str:
        if self.month and self.day:
            return "day"
        return "month" if self.month else "year"

    @property
    def date(self) -> Optional[dt.date]:
        if not (self.month and self.day):
            return None
        try:
            return dt.date(self.year, self.month, self.day)
        except ValueError:
            return None

    def iso(self) -> str:
        if self.month and self.day:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        return f"{self.year:04d}-{self.month:02d}" if self.month else f"{self.year:04d}"


def _int(value) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "NA":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _float(value) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "NA":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return None if math.isnan(number) else number


def _month(value) -> Optional[int]:
    month = _int(value)
    return month if month and 1 <= month <= 12 else None


def _day(value) -> Optional[int]:
    day = _int(value)
    return day if day and 1 <= day <= 31 else None


def in_years(year: Optional[int], year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> bool:
    return year is not None and year_min <= year <= year_max


def noaa_mag_type(item: dict) -> Optional[str]:
    """Тип магнитуды NOAA: поле, значение которого выбрано в `eqMagnitude`."""
    value = item.get("eqMagnitude")
    if value is None:
        return None
    for key, label in NOAA_MAG_TYPES:
        if item.get(key) == value:
            return label
    return None


NOAA_FIELDS = (
    "locationName", "country", "intensity", "deaths", "deathsTotal", "deathsAmountOrder",
    "deathsAmountOrderTotal", "injuries", "injuriesTotal", "injuriesAmountOrderTotal",
    "housesDestroyed", "housesDestroyedTotal", "housesDestroyedAmountOrderTotal",
    "housesDamaged", "housesDamagedTotal", "damageAmountOrder", "damageAmountOrderTotal",
    "damageMillionsDollars", "tsunamiEventId", "volcanoEventId",
)


def noaa_events(items: Iterable[dict], *, year_min: int = YEAR_MIN,
                year_max: int = YEAR_MAX) -> list[Event]:
    """Землетрясения NOAA: по событию на строку ответа, без координаты — мимо."""
    out = []
    for item in items:
        year, lat, lon = _int(item.get("year")), _float(item.get("latitude")), \
            _float(item.get("longitude"))
        if not in_years(year, year_min, year_max) or lat is None or lon is None:
            continue
        out.append(Event(
            catalog="NOAA", source_id=str(item.get("id")), year=year,
            month=_month(item.get("month")), day=_day(item.get("day")),
            lat=lat, lon=lon, magnitude=_float(item.get("eqMagnitude")),
            mag_type=noaa_mag_type(item), depth_km=_float(item.get("eqDepth")),
            fields={k: item[k] for k in NOAA_FIELDS if item.get(k) not in (None, "")},
        ))
    return out


def check_columns(header: Iterable[str], required: Iterable[str], what: str) -> None:
    missing = [c for c in required if c not in set(header)]
    if missing:
        raise EarthquakesError(f"{what}: нет колонок {missing}; пришли: {sorted(header)}")


def emca_events(text: str, *, year_min: int = YEAR_MIN,
                year_max: int = YEAR_MAX) -> list[Event]:
    """EMCA: CSV id,year,month,…,lat,lon,fdepth,mlh; «NA» — значение неизвестно."""
    reader = csv.DictReader(io.StringIO(text))
    check_columns(reader.fieldnames or (), EMCA_COLUMNS, EMCA_CSV)
    out = []
    for row in reader:
        year, lat, lon = _int(row.get("year")), _float(row.get("lat")), _float(row.get("lon"))
        if not in_years(year, year_min, year_max) or lat is None or lon is None:
            continue
        out.append(Event(
            catalog="EMCA", source_id=str(row["id"]).strip(), year=year,
            month=_month(row.get("month")), day=_day(row.get("day")), lat=lat, lon=lon,
            magnitude=_float(row.get("mlh")), mag_type="MLH",
            depth_km=_float(row.get("fdepth")),
        ))
    return out


def gem_events(text: str, *, year_min: int = YEAR_MIN, year_max: int = YEAR_MAX,
               keep: Callable[[float, float], bool] = lambda lat, lon: in_bbox(lat, lon)
               ) -> list[Event]:
    """GEM: CSV с однородной Mw. Весь мир с 1900 года — отбирается охват и годы."""
    reader = csv.DictReader(io.StringIO(text))
    check_columns(reader.fieldnames or (), GEM_COLUMNS, GEM_CSV)
    out = []
    for row in reader:
        year = _int(row.get("year"))
        if not in_years(year, year_min, year_max):
            continue
        lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
        if lat is None or lon is None or not keep(lat, lon):
            continue
        out.append(Event(
            catalog="GEM", source_id=str(row["eventID"]).strip(), year=year,
            month=_month(row.get("month")), day=_day(row.get("day")), lat=lat, lon=lon,
            magnitude=_float(row.get("magnitude")), mag_type="Mw",
            depth_km=_float(row.get("depth")),
            fields={"agency": row.get("Agency") or None,
                    "mag_agency": row.get("magAgency") or None},
        ))
    return out


# --- сведение каталогов -------------------------------------------------------

def days_apart(a: Event, b: Event) -> Optional[int]:
    if a.date is None or b.date is None:
        return None
    return abs((a.date - b.date).days)


def match_score(a: Event, b: Event) -> Optional[tuple]:
    """Насколько два события разных каталогов похожи на одно; None — не одно.

    Чем меньше кортеж, тем лучше пара: расхождение в днях, затем в километрах.
    """
    if a.catalog == b.catalog or a.year != b.year:
        return None
    km = haversine_km(a.lat, a.lon, b.lat, b.lon)
    gap = days_apart(a, b)
    if gap is not None:
        return (gap, km) if gap <= 1 and km <= 150 else None
    if a.month and b.month:
        return (2, km) if a.month == b.month and km <= 100 else None
    if km > 75:
        return None
    if a.magnitude is not None and b.magnitude is not None \
            and abs(a.magnitude - b.magnitude) > 1.0:
        return None
    return (3, km)


def cluster(events: Iterable[Event]) -> list[list[Event]]:
    """Сводит события каталогов: в группе не больше одного события каждого каталога.

    Пары ищутся по всем каталогам сразу и отдаются лучшими вперёд; событие,
    уже сведённое с другим из того же каталога, второй пары не получает.
    """
    events = list(events)
    by_year: dict[int, list[int]] = {}
    for i, ev in enumerate(events):
        by_year.setdefault(ev.year, []).append(i)
    pairs = []
    for idx in by_year.values():
        for x, i in enumerate(idx):
            for j in idx[x + 1:]:
                score = match_score(events[i], events[j])
                if score is not None:
                    pairs.append((score, i, j))
    pairs.sort()
    group_of = list(range(len(events)))
    members: dict[int, list[int]] = {i: [i] for i in range(len(events))}
    for _, i, j in pairs:
        gi, gj = group_of[i], group_of[j]
        if gi == gj:
            continue
        catalogs_i = {events[k].catalog for k in members[gi]}
        catalogs_j = {events[k].catalog for k in members[gj]}
        if catalogs_i & catalogs_j:
            continue
        members[gi].extend(members[gj])
        for k in members.pop(gj):
            group_of[k] = gi
    out = [[events[k] for k in sorted(m, key=lambda k: CATALOG_ORDER.index(events[k].catalog))]
           for m in members.values()]
    out.sort(key=lambda g: (g[0].year, g[0].month or 0, g[0].day or 0, g[0].source_id))
    return out


def pick(group: list[Event], order: tuple[str, ...]) -> Event:
    by_catalog = {ev.catalog: ev for ev in group}
    for name in order:
        if name in by_catalog:
            return by_catalog[name]
    return group[0]


PRECISION_RANK = {"day": 0, "month": 1, "year": 2}


def best_date(group: list[Event]) -> Event:
    """Событие с самой точной датой; при равной точности — NOAA, GEM, EMCA."""
    order = {"NOAA": 0, "GEM": 1, "EMCA": 2}
    return min(group, key=lambda ev: (PRECISION_RANK[ev.precision], order[ev.catalog]))


def best_magnitude(group: list[Event]) -> Optional[Event]:
    for name in ("GEM", "NOAA", "EMCA"):
        for ev in group:
            if ev.catalog == name and ev.magnitude is not None:
                return ev
    return None


# --- где событие: рамка, море у берега, соседняя земля ------------------------

@dataclass
class Spot:
    kind: str                       # frame | sea | abroad | off
    province: Optional[str] = None
    km: Optional[int] = None        # до земли рамки; у события в рамке — 0
    state: Optional[str] = None     # чья земля у события за границей рамки
    shore: bool = False             # точку рамки нашёл поиск берега frame.py


def offset(lat: float, lon: float, km: float, bearing: float) -> tuple[float, float]:
    """Точка на расстоянии `km` по азимуту `bearing` (градусы) по большому кругу."""
    d = km / 6371.0088
    b = math.radians(bearing)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540.0) % 360.0 - 180.0


@dataclass
class State:
    name: str
    year_from: int
    year_to: int
    shape: Banded


def load_states_named(path: Path) -> list[State]:
    """Государства с именем и годами — чтобы назвать соседнюю землю у события."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for feat in payload.get("features", []):
        props = feat.get("properties") or {}
        if not touches_region(feat.get("geometry")):
            continue
        year_from, year_to = props.get("year_from"), props.get("year_to")
        if not isinstance(year_from, int) or not isinstance(year_to, int):
            continue
        out.append(State(props.get("state") or props.get("state_en") or "?", year_from,
                         year_to, Banded(_rings(feat.get("geometry") or {}))))
    return out


def bounds(shape: Banded) -> tuple[float, float, float, float]:
    """(широта от, до, долгота от, до) фигуры — по её рёбрам."""
    lats, lons = [], []
    for edges in shape.bands.values():
        for x1, y1, x2, y2 in edges:
            lats += (y1, y2)
            lons += (x1, x2)
    if not lats:
        return (0.0, -1.0, 0.0, -1.0)
    return min(lats), max(lats), min(lons), max(lons)


def within(box: tuple[float, float, float, float], lat: float, lon: float) -> bool:
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


class Placement:
    """Рамка проекта плюс подписи: соседнее государство и ближайший город."""

    def __init__(self, frame: Frame, states: list[State], towns: Iterable[ContextRecord]
                 ) -> None:
        self.frame = frame
        self.states = states
        self.towns = SpatialIndex(towns)
        # Рамки фигур государств: кольца вокруг событий проверяют землю сотни
        # тысяч раз, и без быстрого «нет» по прямоугольнику сборка идёт минуты.
        self._frame_states = [(bounds(shape), framed, shape) for framed, shape in frame.states]
        self._named = [(bounds(state.shape), state) for state in states]
        self._cells: dict[tuple[int, int], tuple[Optional[bool], Optional[str]]] = {}

    @classmethod
    def load(cls, boundaries_dir: Path, settlements: Path) -> "Placement":
        boundaries_dir = Path(boundaries_dir)
        states = load_states_named(boundaries_dir / "state_borders.geojson")
        early = boundaries_dir / "state_borders_early.geojson"
        if early.exists():
            # До 1886 года CShapes нет; соседнюю землю называет Cliopatria.
            states += [s for s in load_states_named(early) if s.year_from < 1886]
        towns = read_geojson(settlements) if Path(settlements).exists() else []
        return cls(Frame.load(boundaries_dir), states, towns)

    def land(self, lat: float, lon: float) -> tuple[Optional[bool], Optional[str]]:
        """(в рамке ли, губерния) или (None, None), если точка в воде."""
        province = self.frame.provinces.region_for(lat, lon)
        if province:
            return True, province
        hits = [framed for box, framed, shape in self._frame_states
                if within(box, lat, lon) and shape.contains(lat, lon)]
        if not hits:
            return None, None
        return any(hits), None

    def nearby_province(self, lat: float, lon: float) -> Optional[str]:
        """Губерния рядом с точкой рамки, до которой грубый контур 1897 года не дошёл.

        Камчатка и устья рек: CShapes считает точку сушей, а полигон губернии
        кончается раньше. Шаги и направления — те же, что у поиска берега в
        `frame.py`.
        """
        for step in SHORE_STEPS:
            for k in range(8):
                province = self.frame.provinces.region_for(
                    lat + math.sin(k * math.pi / 4) * step,
                    lon + math.cos(k * math.pi / 4) * step)
                if province:
                    return province
        return None

    def land_cell(self, lat: float, lon: float) -> tuple[Optional[bool], Optional[str]]:
        """`land` в центре клетки 0,05° — для колец вокруг событий.

        События лежат гнёздами (Курилы, Япония, Эгейское море), и кольца
        соседних событий проходят по одним и тем же клеткам: ответ клетки
        запоминается. Ошибка — до 3 км, на кольцах в 5–150 км её не видно;
        сам эпицентр проверяется точно, без клеток.
        """
        key = (round(lat / CELL), round(lon / CELL))
        if key not in self._cells:
            self._cells[key] = self.land(key[0] * CELL, key[1] * CELL)
        return self._cells[key]

    def nearest_frame(self, lat: float, lon: float) -> tuple[Optional[int], Optional[str]]:
        """До ближайшей земли рамки, км (по кольцам), и её губерния."""
        for km in RINGS_KM:
            found, province = False, None
            for k in range(BEARINGS):
                framed, prov = self.land_cell(*offset(lat, lon, km, k * 360.0 / BEARINGS))
                if framed:
                    found = True
                    if prov:
                        province = prov
                        break
            if found:
                return km, province
        return None, None

    def state_at(self, lat: float, lon: float, year: int) -> Optional[str]:
        hits = [s for box, s in self._named if within(box, lat, lon) and s.shape.contains(lat, lon)]
        if not hits:
            return None
        current = [s for s in hits if s.year_from <= year <= s.year_to]
        chosen = current or sorted(hits, key=lambda s: abs(s.year_from - year))
        return chosen[0].name

    def place(self, lat: float, lon: float, year: int) -> Spot:
        if in_bbox(lat, lon):
            inside, province, shore = self.frame.place(lat, lon)
            if inside:
                return Spot(KIND_FRAME, province or self.nearby_province(lat, lon), 0,
                            shore=shore)
        framed, province = self.land(lat, lon)
        if framed:
            # Земля рамки вне прямоугольника охвата: Кушка лежит у 35° с. ш.
            return Spot(KIND_FRAME, province, 0)
        km, province = self.nearest_frame(lat, lon)
        if framed is None:
            if km is not None and km <= SEA_KM:
                return Spot(KIND_SEA, province, km)
            return Spot(KIND_OFF, None, km)
        state = self.state_at(lat, lon, year)
        if km is not None and km <= BORDER_KM:
            return Spot(KIND_ABROAD, None, km, state=state)
        return Spot(KIND_OFF, None, km, state=state)

    def coast_place(self, lat: float, lon: float, spot: Spot) -> Optional[str]:
        """Ближайшее селение в радиусе пояса — для события в море без губернии."""
        if spot.kind != KIND_SEA or spot.province:
            return None
        near = self.towns.near(lat, lon, SEA_KM)
        return near[0][0].title if near else None

    def town(self, lat: float, lon: float) -> tuple[Optional[str], Optional[float]]:
        """Город в 30 км, иначе любое селение в 15 км: (имя, км).

        Сначала «город» GeoNames, потом «малый город», внутри — ближайший:
        у Ашхабадского землетрясения 1948 года в подписи должен стоять
        Ашхабад в 20 км, а не посёлок в пяти.
        """
        near = self.towns.near(lat, lon, TOWN_KM)
        for category in TOWNS:
            for rec, km in near:
                if (rec.category or "") == category:
                    return rec.title, km
        for rec, km in near:
            if km <= VILLAGE_KM:
                return rec.title, km
        return None, None


def keep_spot(spot: Spot, group: list[Event]) -> bool:
    """Идёт ли событие в слой по месту: рамка, море у берега, соседняя земля у границы.

    В рамке — всегда. В море и за границей — если его могли почувствовать на
    земле рамки: «значимое» по NOAA (жертвы, разрушения, цунами) берётся на
    всём поясе, остальное — по магнитуде и расстоянию (`SEA_RULES`,
    `BORDER_KM`): у Курил и Камчатки иначе в слое оказались бы сотни
    афтершоков 1952 года над желобом.
    """
    if spot.kind == KIND_FRAME:
        return True
    if spot.kind not in (KIND_SEA, KIND_ABROAD) or spot.km is None:
        return False
    if any(ev.catalog == "NOAA" for ev in group):
        return True
    ev = best_magnitude(group)
    magnitude = ev.magnitude if ev is not None else None
    if spot.kind == KIND_SEA:
        return any(spot.km <= km and (need is None or (magnitude or 0) >= need)
                   for km, need in SEA_RULES)
    if spot.km <= NEAR_KM:
        return True
    return magnitude is not None and magnitude >= BORDER_MAGNITUDE


# --- подписи ------------------------------------------------------------------

def fmt_number(value: float, digits: int = 1) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:.0f}"
    return text.replace(".", ",")


def fmt_mag(value: float) -> str:
    """Магнитуда всегда с десятыми: «9,0», а не «9»."""
    return f"{value:.1f}".replace(".", ",")


def fmt_int(value) -> str:
    return f"{int(value):,}".replace(",", " ")


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def gregorian_to_julian(day: dt.date) -> tuple[int, int, int]:
    """Та же дата по юлианскому календарю: (год, месяц, число)."""
    a = (14 - day.month) // 12
    y = day.year + 4800 - a
    m = day.month + 12 * a - 3
    jdn = day.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    c = jdn + 32082
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m2 = (5 * e + 2) // 153
    return d - 4800 + m2 // 10, m2 + 3 - 12 * (m2 // 10), e - (153 * m2 + 2) // 5 + 1


def date_text(ev: Event) -> str:
    """«9 июня 1887 года (28 мая по старому стилю)», «июнь 1887 года», «1887 год»."""
    if ev.date is not None:
        text = f"{ev.day} {MONTHS_GEN[ev.month - 1]} {ev.year} года"
        if ev.date < OLD_STYLE_END:
            jy, jm, jd = gregorian_to_julian(ev.date)
            old = f"{jd} {MONTHS_GEN[jm - 1]}" + (f" {jy} года" if jy != ev.year else "")
            text += f" ({old} по старому стилю)"
        return text
    if ev.month:
        months = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
                  "сентябрь", "октябрь", "ноябрь", "декабрь")
        return f"{months[ev.month - 1]} {ev.year} года"
    return f"{ev.year} год"


def people(fields: dict, exact: tuple[str, ...], order: tuple[str, ...]) -> Optional[str]:
    for key in exact:
        if fields.get(key):
            return fmt_int(fields[key])
    for key in order:
        if fields.get(key) in ORDER_PEOPLE:
            return ORDER_PEOPLE[fields[key]]
    return None


def losses(fields: dict) -> list[str]:
    """Жертвы и разрушения по NOAA: число, а нет его — порядок величины."""
    out = []
    killed = people(fields, ("deathsTotal", "deaths"),
                    ("deathsAmountOrderTotal", "deathsAmountOrder"))
    if killed:
        out.append(f"погибших — {killed}")
    hurt = people(fields, ("injuriesTotal", "injuries"), ("injuriesAmountOrderTotal",))
    if hurt:
        out.append(f"раненых — {hurt}")
    houses = people(fields, ("housesDestroyedTotal", "housesDestroyed"),
                    ("housesDestroyedAmountOrderTotal",))
    if houses:
        out.append(f"разрушено домов — {houses}")
    damaged = people(fields, ("housesDamagedTotal", "housesDamaged"), ())
    if damaged:
        out.append(f"повреждено домов — {damaged}")
    damage = fields.get("damageAmountOrderTotal") or fields.get("damageAmountOrder")
    if damage in ORDER_DAMAGE:
        out.append(f"ущерб {ORDER_DAMAGE[damage]}")
    return out


def magnitude_text(group: list[Event]) -> Optional[str]:
    main = best_magnitude(group)
    if main is None:
        return None
    label = f" ({main.mag_type})" if main.mag_type else ""
    text = f"магнитуда {fmt_mag(main.magnitude)}{label} по {main.catalog}"
    others = [f"{ev.catalog} — {fmt_mag(ev.magnitude)}" + (f" {ev.mag_type}" if ev.mag_type
                                                           else "")
              for ev in group if ev is not main and ev.magnitude is not None]
    return text + (f"; {', '.join(others)}" if others else "")


def where_text(spot: Spot, town: Optional[str], town_km: Optional[float]) -> str:
    parts = []
    if town:
        parts.append("эпицентр — у населённого пункта " + town if town_km < 1 else
                     f"эпицентр — в {fmt_number(town_km, 0)} км от населённого пункта {town}")
    if spot.kind == KIND_SEA:
        parts.append(f"в море, в {spot.km} км от берега")
    elif spot.kind == KIND_ABROAD:
        where = spot.state or "соседняя земля"
        parts.append(f"{where}, в {spot.km} км от земель империи и СССР")
    return "; ".join(parts)


def place_label(spot: Spot, town: Optional[str], fallback: Optional[str],
                coast: Optional[str] = None) -> str:
    """Подпись места: город, губерния 1897 года, ближайшее селение берега, сосед."""
    if town:
        return town
    if spot.kind == KIND_SEA:
        if spot.province:
            return f"в море, {spot.province}"
        if coast:
            return f"в море, ближайшее селение — {coast}"
        return f"в море, {fallback}" if fallback else "в море у берегов империи и СССР"
    if spot.province:
        return spot.province
    if spot.kind == KIND_ABROAD and spot.state:
        return spot.state
    return fallback or "место не названо"


def clean_location(text: Optional[str]) -> Optional[str]:
    """Место по NOAA без государства впереди: «RUSSIA:  CAUCASUS» → «Caucasus»."""
    if not text:
        return None
    tail = str(text).split(":", 1)[-1].strip()
    return title_case(tail or text)


def title_case(text: Optional[str]) -> Optional[str]:
    """«SEVERO-KURILSK, PARAMUSHIR I.» → «Severo-Kurilsk, Paramushir I.»."""
    if not text:
        return None
    words = []
    for word in str(text).split():
        words.append("-".join(p[:1].upper() + p[1:].lower() for p in word.split("-")))
    return " ".join(words).replace("  ", " ")


# --- записи -------------------------------------------------------------------

def tsunami_note(ts: dict) -> str:
    parts = ["вызвало цунами"]
    height = _float(ts.get("maxWaterHeight"))
    if height:
        parts.append(f"волна до {fmt_number(height)} м")
    killed = people(ts, ("deathsTotal", "deaths"), ("deathsAmountOrderTotal",
                                                    "deathsAmountOrder"))
    if killed:
        parts.append(f"погибших от цунами — {killed}")
    return ", ".join(parts)


def apply_spot(rec: ContextRecord, spot: Spot) -> None:
    rec.region = spot.province
    if spot.kind == KIND_FRAME:
        if spot.shore:
            rec.extra["frame"] = "по берегу"
    elif spot.kind == KIND_SEA:
        rec.extra["frame"] = f"в море, {spot.km} км до берега"
    else:
        rec.confidence = OUTSIDE
        rec.extra["frame"] = (f"за пределами рамки, {spot.km} км до неё" if spot.km is not None
                              else "за пределами рамки")
        if spot.state:
            rec.extra["state"] = spot.state


def quake_record(group: list[Event], spot: Spot, place: Placement,
                 tsunami: Optional[dict] = None) -> ContextRecord:
    point = pick(group, ("GEM", "EMCA", "NOAA"))
    when = best_date(group)
    noaa = next((ev for ev in group if ev.catalog == "NOAA"), None)
    fields = noaa.fields if noaa else {}
    main = best_magnitude(group)
    town, town_km = place.town(point.lat, point.lon)
    fallback = clean_location(fields.get("locationName")) \
        or place.state_at(point.lat, point.lon, point.year)
    label = place_label(spot, town, fallback, place.coast_place(point.lat, point.lon, spot))
    kind = "Землетрясение и цунами" if tsunami else "Землетрясение"
    mag = f" M {fmt_mag(main.magnitude)}" if main is not None else ""
    pieces = [date_text(when)]
    mag_text = magnitude_text(group)
    if mag_text:
        pieces.append(mag_text)
    intensity = _float(fields.get("intensity"))
    if intensity:
        n = int(intensity)
        pieces.append(f"сила в эпицентре — {n} {plural(n, ('балл', 'балла', 'баллов'))} "
                      "по шкале Меркалли")
    pieces += losses(fields)
    if tsunami:
        pieces.append(tsunami_note(tsunami))
    where = where_text(spot, town, town_km)
    if where:
        pieces.append(where)
    catalogs = [ev.catalog for ev in group]
    summary = "; ".join(pieces) + ". По каталогам: " + ", ".join(catalogs)
    primary = noaa or point
    url = NOAA_EQ_PAGE.format(noaa.source_id) if noaa else CATALOG_URL[point.catalog]
    extra = {
        "magnitude": main.magnitude if main else None,
        "mag_type": main.mag_type if main else None,
        "depth_km": point.depth_km,
        "catalogs": [{k: v for k, v in (("catalog", ev.catalog), ("id", ev.source_id),
                                        ("date", ev.iso()), ("magnitude", ev.magnitude),
                                        ("mag_type", ev.mag_type)) if v is not None}
                     for ev in group],
    }
    if intensity:
        extra["intensity_mmi"] = intensity
    if town:
        extra["nearest_place"] = town
        extra["nearest_km"] = round(town_km, 1)
    if tsunami:
        extra["tsunami_id"] = tsunami.get("id")
        if _float(tsunami.get("maxWaterHeight")):
            extra["tsunami_max_m"] = _float(tsunami.get("maxWaterHeight"))
    rec = EARTHQUAKES.new_record(
        title=f"{kind}{mag} — {label}",
        category="землетрясение и цунами" if tsunami else "землетрясение",
        lat=round(point.lat, 4), lon=round(point.lon, 4),
        place_text=fields.get("locationName"),
        year_from=when.year, year_to=when.year,
        date_precision=when.precision,
        date_approx=when.catalog == "EMCA" and when.precision == "year",
        period_raw=when.iso(),
        summary=summary,
        url=url,
        source="; ".join(CATALOG_SOURCE[c] for c in catalogs),
        source_id=f"{primary.catalog.lower()}:{primary.source_id}",
        license="; ".join(CATALOG_LICENSE[c] for c in catalogs),
        extra={k: v for k, v in extra.items() if v is not None},
    )
    apply_spot(rec, spot)
    return rec


def tsunami_event(item: dict) -> Optional[Event]:
    year, lat, lon = _int(item.get("year")), _float(item.get("latitude")), \
        _float(item.get("longitude"))
    if not in_years(year) or lat is None or lon is None:
        return None
    return Event(catalog="NOAA", source_id=str(item.get("id")), year=year,
                 month=_month(item.get("month")), day=_day(item.get("day")), lat=lat,
                 lon=lon, magnitude=_float(item.get("eqMagnitude")), fields=dict(item))


def tsunami_record(item: dict, spot: Spot, place: Placement) -> Optional[ContextRecord]:
    ev = tsunami_event(item)
    if ev is None:
        return None
    town, town_km = place.town(ev.lat, ev.lon)
    label = place_label(spot, town, clean_location(item.get("locationName")),
                        place.coast_place(ev.lat, ev.lon, spot))
    pieces = [date_text(ev)]
    cause = TSUNAMI_CAUSE.get(_int(item.get("causeCode")))
    if cause:
        pieces.append(f"причина — {cause}")
    validity = TSUNAMI_VALIDITY.get(_int(item.get("eventValidity")))
    if validity:
        pieces.append(f"достоверность по NOAA — {validity}")
    height = _float(item.get("maxWaterHeight"))
    if height:
        pieces.append(f"волна до {fmt_number(height)} м")
    pieces += losses(item)
    where = where_text(spot, town, town_km).replace("эпицентр", "источник")
    if where:
        pieces.append(where)
    rec = EARTHQUAKES.new_record(
        title=f"Цунами — {label}",
        category="цунами",
        lat=round(ev.lat, 4), lon=round(ev.lon, 4),
        place_text=item.get("locationName"),
        year_from=ev.year, year_to=ev.year, date_precision=ev.precision,
        period_raw=ev.iso(),
        summary="; ".join(pieces) + ". По NOAA NCEI, Global Historical Tsunami Database",
        url=NOAA_TS_PAGE.format(ev.source_id),
        source="NOAA NCEI, Global Historical Tsunami Database",
        source_id=f"noaa-tsunami:{ev.source_id}",
        license=CATALOG_LICENSE["NOAA"],
        extra={k: v for k, v in {
            "tsunami_id": item.get("id"), "tsunami_max_m": height,
            "validity": _int(item.get("eventValidity")),
            "cause_code": _int(item.get("causeCode")),
            "earthquake_id": item.get("earthquakeEventId"),
        }.items() if v is not None},
    )
    apply_spot(rec, spot)
    return rec


def runup_wanted(item: dict) -> bool:
    """Набег — на карту, если волна от двух метров или были жертвы и ущерб."""
    if str(item.get("doubtful") or "").lower() == "y":
        return False
    height = _float(item.get("runupHt")) or 0.0
    harm = any(item.get(k) for k in ("deaths", "deathsAmountOrder", "injuries",
                                     "housesDestroyed", "housesDestroyedAmountOrder",
                                     "damageAmountOrder"))
    return height >= RUNUP_MIN_M or harm


def runup_record(item: dict, spot: Spot, place: Placement,
                 source: Optional[dict] = None) -> Optional[ContextRecord]:
    ev = tsunami_event(item)
    if ev is None:
        return None
    town, town_km = place.town(ev.lat, ev.lon)
    name = town if town and town_km <= VILLAGE_KM else clean_location(item.get("locationName"))
    pieces = [date_text(ev)]
    height = _float(item.get("runupHt"))
    if height:
        pieces.append(f"волна высотой {fmt_number(height)} м")
    pieces += losses(item)
    if source:
        what = TSUNAMI_CAUSE.get(_int(source.get("causeCode")), "")
        origin = f"цунами: {clean_location(source.get('locationName')) or 'источник не назван'}"
        if what:
            origin += f" ({what})"
        pieces.append(origin)
    dist = _float(item.get("distFromSource"))
    if dist:
        pieces.append(f"{fmt_number(dist, 0)} км от источника")
    rec = EARTHQUAKES.new_record(
        title=f"Набег цунами — {name}",
        category="набег цунами",
        lat=round(ev.lat, 4), lon=round(ev.lon, 4),
        place_text=item.get("locationName"),
        year_from=ev.year, year_to=ev.year, date_precision=ev.precision,
        period_raw=ev.iso(),
        summary="; ".join(pieces) + ". По NOAA NCEI, Global Historical Tsunami Database",
        url=NOAA_RUNUP_PAGE.format(item.get("id")),
        source="NOAA NCEI, Global Historical Tsunami Database",
        source_id=f"noaa-runup:{item.get('id')}",
        license=CATALOG_LICENSE["NOAA"],
        extra={k: v for k, v in {
            "tsunami_id": item.get("tsunamiEventId"), "runup_m": height,
            "km_from_source": round(dist) if dist else None,
            "nearest_place": town, "nearest_km": round(town_km, 1) if town else None,
        }.items() if v is not None},
    )
    apply_spot(rec, spot)
    return rec


@dataclass
class Build:
    """Итог сборки: записи и счёт отбора — для отчёта `--check`."""

    records: list[ContextRecord]
    counts: dict
    by_catalogs: dict = field(default_factory=dict)


def build(noaa_eq: Iterable[dict], tsunamis: Iterable[dict], runups: Iterable[dict],
          emca: Iterable[Event], gem: Iterable[Event], place: Placement) -> Build:
    """Записи слоя из трёх каталогов, цунами и набегов."""
    counts: dict = {}

    def bump(key: str, n: int = 1) -> None:
        counts[key] = counts.get(key, 0) + n

    by_catalogs: dict = {}
    noaa = noaa_events(noaa_eq)
    emca, gem = list(emca), list(gem)
    bump("NOAA, землетрясений", len(noaa))
    bump("EMCA, землетрясений", len(emca))
    bump("GEM, землетрясений", len(gem))
    groups = cluster([*noaa, *emca, *gem])
    tsunami_by_id = {str(t.get("id")): t for t in tsunamis}
    tsunami_by_quake = {str(t.get("earthquakeEventId")): t for t in tsunami_by_id.values()
                        if t.get("earthquakeEventId")}
    out, used_tsunamis = [], set()
    for group in groups:
        point = pick(group, ("GEM", "EMCA", "NOAA"))
        spot = place.place(point.lat, point.lon, point.year)
        if not keep_spot(spot, group):
            bump(f"не взято: {'соседняя земля' if spot.kind == KIND_ABROAD else 'вдали'}")
            continue
        noaa_ev = next((ev for ev in group if ev.catalog == "NOAA"), None)
        tsunami = None
        if noaa_ev is not None:
            ts_id = noaa_ev.fields.get("tsunamiEventId")
            tsunami = tsunami_by_id.get(str(ts_id)) if ts_id else None
            tsunami = tsunami or tsunami_by_quake.get(noaa_ev.source_id)
        if tsunami is not None:
            used_tsunamis.add(str(tsunami.get("id")))
        out.append(quake_record(group, spot, place, tsunami))
        bump("землетрясений в слое")
        combo = "+".join(ev.catalog for ev in group)
        by_catalogs[combo] = by_catalogs.get(combo, 0) + 1
    for ts_id, item in tsunami_by_id.items():
        if ts_id in used_tsunamis:
            continue
        if _int(item.get("eventValidity")) == -1:
            bump("цунами: ошибочная запись NOAA (validity −1), не взято")
            continue
        ev = tsunami_event(item)
        if ev is None:
            continue
        spot = place.place(ev.lat, ev.lon, ev.year)
        if spot.kind not in (KIND_FRAME, KIND_SEA):
            bump("цунами: источник вдали от берега рамки, не взято")
            continue
        rec = tsunami_record(item, spot, place)
        if rec is not None:
            out.append(rec)
            bump("цунами без сведённого землетрясения")
    for item in runups:
        if not runup_wanted(item):
            bump("набегов: ниже двух метров без жертв и ущерба, не взято")
            continue
        ev = tsunami_event(item)
        if ev is None:
            continue
        spot = place.place(ev.lat, ev.lon, ev.year)
        rec = runup_record(item, spot, place, tsunami_by_id.get(str(item.get("tsunamiEventId"))))
        if rec is not None:
            out.append(rec)
            bump("набегов цунами в слое")
    return Build(out, counts, by_catalogs)


# --- сеть ---------------------------------------------------------------------

def _get_json(url: str, *, timeout: int = 120, tries: int = 4) -> dict:
    last = None
    for attempt in range(tries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_CODES:
                raise EarthquakesError(f"{url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
            last = exc
        time.sleep(10 * (attempt + 1))
    raise EarthquakesError(f"{url}: не ответил после {tries} попыток ({last})")


class NoaaClient:
    """Запросы к Hazard Service с паузой из `robots.txt` и кэшем на диске.

    Каждая страница ответа ложится файлом: повторный запуск берёт её из кэша
    и не ждёт минуту ради того, что уже есть.
    """

    def __init__(self, cache_dir: Path, *, pause: float = NOAA_PAUSE,
                 log: Callable[[str], None] = print) -> None:
        self.cache_dir = Path(cache_dir)
        self.pause = pause
        self.log = log
        self._last = 0.0
        self.requests = 0

    def page(self, path: str, label: str, params: dict, page: int) -> dict:
        name = f"{path.replace('/', '_')}_{label}_p{page}.json"
        cached = self.cache_dir / name
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        wait = self.pause - (time.monotonic() - self._last)
        if self._last and wait > 0:
            time.sleep(wait)
        url = NOAA_API + path + "?" + urllib.parse.urlencode({**params, "page": page})
        payload = _get_json(url)
        self._last = time.monotonic()
        self.requests += 1
        if not isinstance(payload, dict) or "items" not in payload:
            raise EarthquakesError(f"{url}: ответ без поля items")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.log(f"  NOAA {path} {label}: страница {page} из {payload.get('totalPages')}, "
                 f"{len(payload['items'])} записей")
        return payload

    def all_items(self, path: str, label: str, params: dict) -> list[dict]:
        items, page = [], 1
        while True:
            payload = self.page(path, label, params, page)
            items += payload["items"]
            if page >= int(payload.get("totalPages") or 1):
                return items
            page += 1


def years_params() -> dict:
    return {"minYear": YEAR_MIN, "maxYear": YEAR_MAX}


def fetch_noaa(client: NoaaClient) -> tuple[list[dict], list[dict], list[dict]]:
    """Землетрясения и цунами в прямоугольниках охвата, набеги — по государствам."""
    quakes, tsunamis, runups = [], [], []
    for label, rect in RECTANGLES.items():
        quakes += client.all_items("earthquakes", label, {**years_params(), **rect})
        tsunamis += client.all_items("tsunamis/events", label, {**years_params(), **rect})
    for country in RUNUP_COUNTRIES:
        runups += client.all_items("tsunamis/runups", country,
                                   {**years_params(), "country": country})
    return dedupe(quakes), dedupe(tsunamis), dedupe(runups)


def dedupe(items: Iterable[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        key = item.get("id")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def cached_file(cache_dir: Path, name: str, url: str, size: int, md5: str, *,
                timeout: int = 600) -> bytes:
    """Файл каталога из кэша; нет его или он другой — скачивается и сверяется."""
    path = Path(cache_dir) / name
    if path.exists() and path.stat().st_size == size:
        data = path.read_bytes()
        if _md5(data) == md5:
            return data
    data = fetch_bytes(url, error=EarthquakesError, timeout=timeout)
    if len(data) != size or _md5(data) != md5:
        raise EarthquakesError(f"{url}: скачано {len(data)} байт, md5 {_md5(data)}; "
                               f"ожидалось {size} байт, md5 {md5}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def read_zip_member(data: bytes, member: str) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read(member).decode("utf-8-sig")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise EarthquakesError(f"архив не разбирается или в нём нет {member}: {exc}") from exc


def fetch_gem_manifest(*, timeout: int = 60) -> list[dict]:
    raw = fetch_bytes(GEM_FILES_API, error=EarthquakesError, timeout=timeout)
    try:
        entries = json.loads(raw)["entries"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EarthquakesError(f"ответ Zenodo не разбирается: {exc}") from exc
    return [{"key": e.get("key"), "size": e.get("size"), "checksum": e.get("checksum")}
            for e in entries]


def check_gem_manifest(manifest: Iterable[dict]) -> list[str]:
    by_key = {m.get("key"): m for m in manifest}
    got = by_key.get(GEM_KEY)
    if got is None:
        return [f"{GEM_KEY}: в записи такого файла нет; есть: "
                + ", ".join(sorted(str(k) for k in by_key))]
    problems = []
    if got.get("size") != GEM_SIZE:
        problems.append(f"размер {got.get('size')}, ожидался {GEM_SIZE}")
    if got.get("checksum") != f"md5:{GEM_MD5}":
        problems.append(f"сумма {got.get('checksum')}, ожидалась md5:{GEM_MD5}")
    return problems
