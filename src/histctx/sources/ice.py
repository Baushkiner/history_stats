"""Ледостав и вскрытие рек и озёр: Global Lake and River Ice Phenology Database (NSIDC).

Зачем этот слой. Пока стоит лёд, река — дорога; когда лёд пошёл — преграда на
две-три недели. От вскрытия зависели сроки навигации и сплава, ярмарка,
дорога в приходскую церковь на другом берегу и то, когда ребёнка довезли до
крещения. Поздняя весна — это ещё и поздний сев. Слой отвечает на вопрос
«когда в этом году встала и вскрылась вода» — до дня.

Что в наборе на самом деле. База NSIDC (Benson, Magnuson, Sharma; G01377)
велика за счёт Северной Америки и Финляндии. По России в ней 96 постов, но до
1900 года начинаются только два ряда: Ангара у Иркутска (1721–1956) и Байкал
у Листвянки (с 1869); остальные — озёра с 1917–1937 годов. Невы, Северной
Двины, Волги в базе нет. Финляндия (102 поста с зимами до 1960 года: Торнио
с 1693 года, Каллавеси с 1822-го, с 1880-х — десятки озёр) закрывает Великое
княжество. В слой идут зимы до 1960 года
включительно — горизонт проекта; позже набор не обрезан, он просто не нужен.

Запись — одна зима одного поста. Сама дата мало что говорит, пока не сказано,
насколько она отличается от обычной, — как у погоды. Поэтому у поста с рядом
не короче `MIN_SEASONS` зим считается медианная дата по зимам до 1960 года, и
запись говорит «на 12 дней позже обычного». У короткого ряда нормы нет, и
запись так и говорит.

Координаты. У постов из свода В. С. Вуглинского широта и долгота записаны
числом вида `67.59` — это градусы и минуты (67°59′), а не десятичные градусы:
так сходятся Ловозеро, Умбозеро, Ильмень и Кубенское. Сборщик пересчитывает
их и помечает запись `place_level`: точка — озеро, а не пост. У озера Большие
Чаны в наборе стоит координата озера Аргаяш (ошибка набора) — запись остаётся
без точки. Даты в наборе григорианские; для России до 1918 года рядом пишется
старый стиль.

Откуда берётся. Сборщик в сеть не ходит. Две таблицы набора лежат у NSIDC на
файловом хосте `noaadata.apps.nsidc.org`, и его `robots.txt` закрывает хост
целиком (`Disallow: /`) — автоматический сбор оттуда проект не ведёт. Таблицы
скачивает человек со страницы набора (ссылка «HTTPS File System») и кладёт в
`data/raw/nsidc_ice/`; сборщик сверяет размер и колонки и разбирает то, что
лежит. Условие использования одно: ссылка на набор — она стоит в каждой
записи.
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import io
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..geo import valid_coords
from ..oldstyle import both_styles, format_ru
from ..schema import ContextRecord, LayerSpec

FILES_PAGE = "https://noaadata.apps.nsidc.org/NOAA/G01377/"
SEASONS_FILE = "liag_freeze_thaw_table.csv"
SITES_FILE = "liag_physical_character_table.csv"
DATASET_URL = "https://nsidc.org/data/g01377/versions/1"
DOI_URL = "https://doi.org/10.7265/N5W66HP8"
# Размеры файлов 22.11.2026 (в каталоге — от 11.10.2023). Разошлись — набор
# обновили: сборщик останавливается, разбор надо сверить заново.
SIZES = {SEASONS_FILE: 3_143_418, SITES_FILE: 135_427}
REQUIRED_SEASONS = {"lakecode", "lakename", "lakeorriver", "season", "iceon_year",
                    "iceon_month", "iceon_day", "iceoff_year", "iceoff_month", "iceoff_day",
                    "country", "froze"}
REQUIRED_SITES = {"lakecode", "lakename", "lakeorriver", "country", "latitude", "longitude",
                  "lat_decimal", "lon_decimal", "contributor"}

MISSING = "-999"
HORIZON = 1960
COUNTRIES = {"RUSSIA": "Россия", "RUSSIA-ESTONIA": "Россия и Эстония", "FINLAND": "Финляндия"}
MIN_SEASONS = 15        # короче — нормы нет
NOTABLE_DAYS = 10       # отклонение, с которого зима названа ранней или поздней
DEGMIN_CONTRIBUTOR = "VUGLINSKY"
# Координата в наборе заведомо чужая: запись остаётся, точки у неё нет.
BAD_COORDS = {"VSV30": "в наборе стоит координата озера Аргаяш (Урал); Большие Чаны — "
                       "в Барабинской степи"}

CITATION = (
    "Benson, B., Magnuson, J., Sharma, S. Global Lake and River Ice Phenology Database, "
    "Version 1 (G01377). Boulder, Colorado USA: National Snow and Ice Data Center, 2000, "
    "updated 2020. doi:10.7265/N5W66HP8"
)

# Русские названия постов, у которых есть зимы до 1960 года. Остальные посты
# России в слой не попадают (ряды с 1962–1983 годов), финские названия
# остаются как в наборе.
NAMES_RU = {
    "NG1": "Байкал (Листвянка)", "NG2": "Гусиное озеро", "NG3": "Ангара (Иркутск)",
    "VSV10": "Гусиное озеро", "VSV11": "Озеро Джека Лондона", "VSV12": "Хантайское озеро",
    "VSV13": "Кубенское озеро", "VSV14": "Озеро Лача", "VSV17": "Озеро Ничатка",
    "VSV19": "Сенежское озеро", "VSV20": "Шакшинское озеро", "VSV21": "Озеро Шира",
    "VSV22": "Озеро Сосновое", "VSV23": "Озеро Сюрюн-Кюёль", "VSV24": "Озеро Таймыр",
    "VSV29": "Телецкое озеро", "VSV3": "Озеро Арахлей", "VSV30": "Озеро Большие Чаны",
    "VSV31": "Кулундинское озеро", "VSV32": "Убинское озеро", "VSV33": "Озеро Сартлан",
    "VSV34": "Озеро Увильды", "VSV35": "Озеро Аргаяш", "VSV36": "Ладожское озеро",
    "VSV37": "Онежское озеро (Петрозаводск)", "VSV38": "Озеро Ильмень",
    "VSV39": "Чудско-Псковское озеро", "VSV40": "Озеро Сяберо", "VSV41": "Сямозеро",
    "VSV42": "Ловозеро", "VSV43": "Умбозеро", "VSV44": "Озеро Асликуль",
    "VSV46": "Онежское озеро (Лонгасы)", "VSV5": "Байкал (Нижнеангарск)",
    "VSV8": "Байкал (Песчаная бухта)",
}

ICE_PHENOLOGY = LayerSpec(
    slug="ice_phenology",
    title="Ледостав и вскрытие рек и озёр по годам (NSIDC)",
    group="hardship",
    source="NSIDC: Global Lake and River Ice Phenology Database, Version 1 (G01377)",
    license=(
        "Условие NSIDC на странице набора — обязательная ссылка на набор (Benson, "
        "Magnuson, Sharma, doi:10.7265/N5W66HP8); лицензия иначе не названа. Ссылка и "
        "цитата проставляются в каждую запись"
    ),
    description=(
        "Когда в этом году встала и вскрылась вода — до дня и с отклонением от обычного "
        "срока: по Финляндии — река Торнио с 1693 года и сотня озёр с XIX века, по "
        "России — Ангара у Иркутска с 1721 года, "
        "Байкал с 1869-го и три десятка озёр советского времени. Ранняя или поздняя весна "
        "двигала навигацию, сплав, сев и дорогу в приход на другом берегу. Невы, Волги и "
        "Двины в наборе нет: для Европейской России XIX века слой почти молчит."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=5711,      # сбор 22.11.2026: зимы до 1960 года, Россия и Финляндия
)


class IceError(RuntimeError):
    """Файл не скачался или устроен не так, как записано в коде."""


# --- чтение ----------------------------------------------------------------

def local_file(name: str, cache_dir: Path) -> Path:
    """Таблица набора, положенная в кэш руками. Размер сверяется."""
    path = Path(cache_dir) / name
    if not path.exists():
        raise IceError(
            f"нет файла {path}: скачайте {name} со страницы набора {DATASET_URL} "
            f"(«HTTPS File System», каталог {FILES_PAGE}) и положите сюда. Сам "
            "сборщик этот хост не запрашивает: его robots.txt закрыт целиком")
    size = path.stat().st_size
    if size != SIZES[name]:
        raise IceError(f"{name}: {size} байт, в коде {SIZES[name]} — набор обновлён, "
                       "сверьте разбор и поправьте размер")
    return path


def read_table(data: bytes, required: set, name: str) -> list[dict]:
    """CSV набора: latin-1, шапка в первой строке."""
    rows = list(csv.DictReader(io.StringIO(data.decode("latin-1"))))
    if not rows:
        raise IceError(f"{name}: пустая таблица")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise IceError(f"{name}: нет колонок {', '.join(missing)}")
    return [{k: (v or "").strip() for k, v in row.items() if k} for row in rows]


def _number(text: str) -> Optional[float]:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if value <= -999 else value


def _degmin(text: str) -> Optional[float]:
    """«67.59» как 67°59′. Минут больше 59 не бывает — тогда это не тот формат."""
    whole, _, frac = text.partition(".")
    try:
        degrees, minutes = int(whole), int((frac + "00")[:2]) if frac else 0
    except ValueError:
        return None
    if minutes > 59:
        return None
    return round(degrees + minutes / 60, 4)


def site_coords(site: dict) -> tuple[Optional[float], Optional[float], str]:
    """(широта, долгота, как получена): `decimal`, `degmin` или `none`."""
    code = site.get("lakecode")
    if code in BAD_COORDS:
        return None, None, "none"
    raw_lat, raw_lon = site.get("latitude", ""), site.get("longitude", "")
    plain = " " not in raw_lat.strip() and " " not in raw_lon.strip()
    if site.get("contributor", "").upper().startswith(DEGMIN_CONTRIBUTOR) and plain:
        lat, lon = _degmin(raw_lat), _degmin(raw_lon)
        if lat is not None and lon is not None and valid_coords(lat, lon):
            return lat, lon, "degmin"
    lat, lon = _number(site.get("lat_decimal", "")), _number(site.get("lon_decimal", ""))
    if lat is None or lon is None or not valid_coords(lat, lon):
        return None, None, "none"
    return lat, lon, "decimal"


def _date(row: dict, prefix: str) -> Optional[dt.date]:
    parts = [row.get(f"{prefix}_{part}", MISSING) for part in ("year", "month", "day")]
    if MISSING in parts or "" in parts:
        return None
    try:
        return dt.date(*(int(float(p)) for p in parts))
    except ValueError:
        return None


@dataclass
class Season:
    """Одна зима одного поста."""

    code: str
    label: str
    ice_on: Optional[dt.date]
    ice_off: Optional[dt.date]
    froze: str
    comment: str = ""

    @property
    def winter(self) -> Optional[int]:
        """Год, на который приходится конец зимы: 1899–1900 → 1900."""
        if self.ice_off:
            return self.ice_off.year
        if self.ice_on:
            return self.ice_on.year + (1 if self.ice_on.month >= 7 else 0)
        try:
            return int(self.label[:4]) + 1
        except ValueError:
            return None


def offset(date: Optional[dt.date], winter: Optional[int]) -> Optional[int]:
    """Дней от 1 января года конца зимы: ледостав в ноябре — число отрицательное."""
    if date is None or winter is None:
        return None
    return (date - dt.date(winter, 1, 1)).days


@dataclass
class Site:
    code: str
    name: str
    river: bool
    country: str
    lat: Optional[float]
    lon: Optional[float]
    coords: str
    seasons: list = field(default_factory=list)
    norm_on: Optional[float] = None
    norm_off: Optional[float] = None

    @property
    def title(self) -> str:
        return NAMES_RU.get(self.code) or self.name.title()


def read_sites(site_rows: Iterable[dict], season_rows: Iterable[dict], *,
               horizon: int = HORIZON) -> list[Site]:
    """Посты в странах слоя с зимами до горизонта; норма считается здесь же."""
    sites: dict[str, Site] = {}
    for row in site_rows:
        if row.get("country") not in COUNTRIES:
            continue
        lat, lon, how = site_coords(row)
        sites[row["lakecode"]] = Site(
            code=row["lakecode"], name=row.get("lakename", ""),
            river=row.get("lakeorriver") == "R", country=row["country"],
            lat=lat, lon=lon, coords=how)
    for row in season_rows:
        site = sites.get(row.get("lakecode"))
        if site is None:
            continue
        season = Season(code=site.code, label=row.get("season", ""), ice_on=_date(row, "iceon"),
                        ice_off=_date(row, "iceoff"), froze=row.get("froze", ""),
                        comment=row.get("comments", ""))
        winter = season.winter
        if winter is None or winter > horizon:
            continue
        if season.ice_on is None and season.ice_off is None and season.froze != "N":
            continue
        site.seasons.append(season)
    out = []
    for site in sites.values():
        if not site.seasons:
            continue
        site.seasons.sort(key=lambda s: s.winter)
        site.norm_on = _median([offset(s.ice_on, s.winter) for s in site.seasons])
        site.norm_off = _median([offset(s.ice_off, s.winter) for s in site.seasons])
        out.append(site)
    return sorted(out, key=lambda s: s.code)


def _median(values: list) -> Optional[float]:
    known = [v for v in values if v is not None]
    return statistics.median(known) if len(known) >= MIN_SEASONS else None


# --- записи ----------------------------------------------------------------

def _norm_date(norm: float) -> str:
    """Медианный срок словами: «17 апреля», «28 ноября»."""
    date = dt.date(2001, 1, 1) + dt.timedelta(days=round(norm))
    return format_ru(date.year, date.month, date.day, with_year=False)


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {few}"
    return f"{n} {many}"


def _days(n: int) -> str:
    return _plural(n, "день", "дня", "дней")


def _deviation(delta: Optional[float]) -> str:
    if delta is None:
        return ""
    days = round(delta)
    if days == 0:
        return ", в обычный срок"
    return f", на {_days(days)} {'позже' if days > 0 else 'раньше'} обычного"


def classify(d_on: Optional[float], d_off: Optional[float], froze: str,
             has_norm: bool) -> str:
    if froze == "N":
        return "не замерзало"
    if d_off is not None and abs(d_off) >= NOTABLE_DAYS:
        return "позднее вскрытие" if d_off > 0 else "раннее вскрытие"
    if d_on is not None and abs(d_on) >= NOTABLE_DAYS:
        return "поздний ледостав" if d_on > 0 else "ранний ледостав"
    if not has_norm:
        return "сроки без нормы"
    return "обычные сроки"


def season_to_record(site: Site, season: Season) -> ContextRecord:
    winter = season.winter
    russia = site.country != "FINLAND"
    d_on = d_off = None
    if site.norm_on is not None and season.ice_on:
        d_on = offset(season.ice_on, winter) - site.norm_on
    if site.norm_off is not None and season.ice_off:
        d_off = offset(season.ice_off, winter) - site.norm_off
    has_norm = site.norm_on is not None or site.norm_off is not None
    category = classify(d_on, d_off, season.froze, has_norm)

    what = "Река" if site.river else "Озеро"
    parts = []
    if season.froze == "N":
        parts.append(f"{what} в эту зиму не замерзало" if not site.river
                     else "Река в эту зиму не замерзала")
    if season.ice_on:
        parts.append(f"Ледостав {both_styles(season.ice_on, russia=russia)}{_deviation(d_on)}")
    if season.ice_off:
        parts.append(f"Вскрытие {both_styles(season.ice_off, russia=russia)}{_deviation(d_off)}")
    if season.ice_on and season.ice_off:
        parts.append(f"Подо льдом {_days((season.ice_off - season.ice_on).days)}")
    norms = []
    if site.norm_on is not None:
        norms.append(f"ледостав {_norm_date(site.norm_on)}")
    if site.norm_off is not None:
        norms.append(f"вскрытие {_norm_date(site.norm_off)}")
    known = sum(1 for s in site.seasons if s.ice_on or s.ice_off)
    if norms:
        parts.append(f"Обычный срок (медиана по {known} зимам до {HORIZON} года): "
                     + ", ".join(norms))
    else:
        parts.append(f"Ряд короткий ({_plural(known, 'зима', 'зимы', 'зим')} до {HORIZON} "
                     "года) — обычный срок не считается")
    if site.coords == "degmin":
        parts.append("Точка — водоём, а не пост наблюдений")
    if site.code in BAD_COORDS:
        parts.append(f"Точки нет: {BAD_COORDS[site.code]}")

    dates = [d for d in (season.ice_on, season.ice_off) if d]
    year_from = min(d.year for d in dates) if dates else winter
    year_to = max(d.year for d in dates) if dates else winter
    extra = {"site": site.code, "name_source": site.name,
             "water": "река" if site.river else "озеро"}
    if season.ice_on:
        extra["ice_on"] = season.ice_on.isoformat()
    if season.ice_off:
        extra["ice_off"] = season.ice_off.isoformat()
    if d_on is not None:
        extra["ice_on_delta_days"] = round(d_on)
    if d_off is not None:
        extra["ice_off_delta_days"] = round(d_off)
    if season.comment and season.comment != MISSING:
        extra["comment"] = season.comment
    if site.coords != "decimal":
        extra["coords"] = site.coords

    has_point = site.lat is not None
    return ICE_PHENOLOGY.new_record(
        title=f"{site.title}: зима {winter - 1}/{str(winter)[2:]}",
        category=category,
        lat=site.lat, lon=site.lon,
        place_text=f"{site.title} ({site.name.title()}), {COUNTRIES[site.country]}",
        year_from=year_from, year_to=year_to,
        date_precision="day" if dates else "year",
        period_raw=season.label,
        summary=". ".join(parts) + ".",
        url=DATASET_URL,
        source_id=f"{site.code}:{season.label}",
        confidence=("no_coords" if not has_point
                    else "place_level" if site.coords == "degmin" else "ok"),
        extra=extra,
    )


def records(sites: Iterable[Site]) -> list[ContextRecord]:
    return [season_to_record(site, season) for site in sites for season in site.seasons]


def summary_counts(sites: Iterable[Site]) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for site in sites:
        counts[f"постов: {COUNTRIES[site.country]}"] += 1
        counts[f"зим: {COUNTRIES[site.country]}"] += len(site.seasons)
    return counts
