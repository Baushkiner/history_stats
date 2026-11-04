"""Деревни Финляндии 1540–1940 и их приходы: «Suomen kylät» Национального архива.

Зачем этот слой. Метрические книги велись по приходам, а в документе о
предке стоит деревня. Вопрос «к какому приходу относилась деревня в таком-то
году» каталог называет самым недооценённым для генеалогии: приход менялся —
от прихода отделялась капелла, капелла становилась приходом, — и книги
одной деревни за разные годы лежат в разных фондах. Для Финляндии эта
связка собрана готовой: у каждой деревни — приход или община на каждые
пятьдесят лет с 1550 по 2023 год. Это всё Великое княжество Финляндское и
Выборгская губерния, включая земли, отошедшие к СССР в 1940–1944 годах.

Набор. «Suomen kylät 1540–1940», Kansallisarkisto (Национальный архив
Финляндии), версия 1 от 20.12.2023 — Zenodo 10408884, тот же набор на
avoindata.fi. `Suomen_kylat_v1.csv` — 14 172 деревни, «старые деревни
земельных книг от фогтских счетов до XX века»; описание полей —
`Suomen_kylat_v1.pdf` в той же записи. Версия помечена «keskeneräinen» —
неокончательная: приходы по годам сверены не все, и даже значения без
вопросительного знака частью не проверены (так сказано в описании полей).

Права. CC BY 4.0 — и в карточке Zenodo, и в описании полей. Нынешние
названия деревень набор берёт из топонимической базы Земельной службы
Финляндии (Maanmittauslaitos, 2023_01), она тоже под CC BY 4.0. Берутся
факты — точка, годы, приходы, названия — со ссылкой на набор.

Координаты. В наборе — ETRS-TM35FIN (EPSG:3067): поперечная проекция
Меркатора на эллипсоиде GRS80, осевой меридиан 27° в. д., масштаб 0,9996,
ложный восток 500 000 м — то же, что UTM, зона 35N. pyproj в зависимости
проекта не входит, поэтому обратное преобразование написано здесь: ряды
Крюгера по третьему сплющиванию до n⁴ (`tm35fin_to_wgs84`). Сверено с PROJ
9.8.1 на всех 13 404 точках набора: наибольшее расхождение — 2,5 микрометра.
ETRS89 принят совпадающим с WGS84: к 2026 году они разошлись меньше чем на
метр, для деревни это ничто.

Что попадает в слой. Все 14 172 деревни, по записи на деревню:

* название — нынешнее (`nimi`); написание старых источников (`nimi_2`,
  часто шведское) — в скобках, прочие варианты — в `extra`;
* `year_from` — первое найденное упоминание (`start`). Это не год
  основания: описание полей прямо предупреждает, что деревня обычно старше;
* `year_to` — оценка составителей, когда место перестало быть деревней
  (`end`; такая запись — `date_approx`). Значение 9999 в наборе значит
  «деревня и сейчас», и конец тогда — 2023 год, последняя колонка набора:
  у всех 10 948 таких деревень она заполнена. У 27 деревень приход стоит в
  колонке позже `end` (упомянута в 1539 году, «перестала» в 1539-м, а в
  1550-м числится в приходе) — конец расширяется до этой колонки;
* приход или община по годам — в `extra["parish"]` как в наборе, вместе с
  вопросительными знаками: «Vehmaa??» — значение не сверено, и чем больше
  знаков, тем дальше оно продлено от сверенного. В описании записи такие
  годы помечены «?». Колонки 1550–1850 — приходы (pitäjä); с реформы 1865
  года рядом с приходом стоит гражданская община (kunta), и колонки 1900–2023
  держат уже её название, обычно совпадающее с приходом;
* «x» в колонке 1950 года стоит у 1 637 деревень, и 1 389 из них лежат в
  границах СССР 1950 года (по `state_borders.geojson`), ещё 88 — у берега
  Выборгского залива, где контур груб: это земли, отошедшие к СССР. Приходом
  «x» не считается;
* `place_text` — последний приход до 1950 года включительно; нынешняя
  община — в описании записи («сейчас — община …»);
* `region` — губерния 1897 года по точке, рамка — как у слоя приходов
  (`frame.py`): 12 235 деревень в губерниях, 1 167 в рамке без губернии, две
  вне рамки. Внешние шхеры Турку лежат в море и для контуров губерний, и для
  контуров государств, и берег для них ищется дальше, чем в `frame.py` (до
  1°, `SHORE_STEPS`); а у границы по Торнио и в Печенге, где грубый контур
  относит точку к Швеции или Норвегии, решает сам набор: деревня, которая в
  1950–2023 годах числится в финской общине или в 1950-м помечена «x», лежит
  в рамке (`extra["frame"]`). Приход 1850 или 1900 года этого не решает:
  шведские деревни долины Торнио записаны в наборе под финскими именами
  своих приходов (Övertorneå — «Ylitornio»), и две такие деревни, Niemis и
  Ruskola, остаются `outside_bbox`. Губернии у таких точек нет, как и у
  Аландов, шхер и устьев рек, которых контуры губерний 1897 года не
  покрывают, хотя Финляндия по CShapes их покрывает: губерния по соседству
  не угадывается, как и в `frame.py`.

Что помечено, а не выброшено. 768 деревень без координаты —
`confidence = no_coords`: на карту они не идут и лежат файлом без точки.
1 200 деревень, впервые упомянутых позже 1960 года (из них 1 148 известны
только по данным 2023 года — «Isokorpi 2» и подобные номерные деревни
реестра), — `confidence = after_1960`: в рамку лет проекта они не попадают,
но из набора не пропадают.

Чего не берётся. Ссылки на геральдику и онтологию YSO, число связанных
архивных дел, кадастровые номера — к вопросу «деревня → приход» они ничего
не добавляют. Ссылка на Викиданные, карточку топонимической базы, Diplomatarium
Fennicum и место в справочнике «Suomen asutus 1560-luvulla» — берутся.

Номер деревни (`id`) в описании полей назван «пока действующим»: новая
версия набора может его сменить, и тогда сменятся и `uid` записей.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from ..net import fetch_bytes
from ..schema import ContextRecord, LayerSpec, clean_text

RECORD_ID = "10408884"
DOI = "10.5281/zenodo.10408884"
DATASET_URL = f"https://doi.org/{DOI}"
FILES_API = f"https://zenodo.org/api/records/{RECORD_ID}/files"
CSV_KEY = "Suomen_kylat_v1.csv"
CSV_URL = f"{FILES_API}/{CSV_KEY}/content"
# Сверено с перечнем файлов записи 04.11.2026. Новая версия набора — новая
# запись Zenodo, новые размер и md5 здесь, сверенные руками.
CSV_SIZE = 4_883_880
CSV_MD5 = "d8ebddccddbcbca18046f205bd873680"
DESCRIPTION_KEY = "Suomen_kylat_v1.pdf"

YEAR_COLUMNS = ("v1550", "v1600", "v1650", "v1700", "v1750", "v1800", "v1850",
                "v1900", "v1950", "v2000", "v2023")
REQUIRED = ("id", "x", "y", "nimi", "nimi_2", "nimi_muu", "start", "end",
            *YEAR_COLUMNS, "placeid", "wikidata", "df", "asutus1560luv")

# «Деревня и сейчас» в колонке `end`.
STILL_VILLAGE = 9999
# Последняя колонка набора: деревня, которая «и сейчас», существует по
# меньшей мере до неё.
LAST_COLUMN_YEAR = 2023
# Горизонт проекта: в описание записи идут приходы до 1950 года, и деревня,
# впервые упомянутая позже, в рамку лет не попадает.
HORIZON = 1960
# Колонки в пределах горизонта — они идут в описание записи и в `place_text`.
SUMMARY_COLUMNS = tuple(c for c in YEAR_COLUMNS if int(c[1:]) < HORIZON)
# Пометка колонки 1950 года у земель, отошедших к СССР.
CEDED = "x"
# Колонки, по которым набор сам ставит деревню в рамку: община в 1950–2023
# годах — это Финляндия, а «x» в 1950 году — земли, отошедшие к СССР; то и
# другое в рамке за все годы. Колонки 1850 и 1900 годов этого не решают: в
# долине Торнио шведские деревни записаны под финскими именами своих
# приходов — Övertorneå там «Ylitornio».
FRAME_COLUMNS = ("v1950", "v2000", "v2023")

CONFIDENCE_NO_COORDS = "no_coords"
CONFIDENCE_NO_DATE = "no_date"
CONFIDENCE_AFTER_HORIZON = "after_1960"
OUTSIDE = "outside_bbox"

CATEGORY_VILLAGE = "деревня"
CATEGORY_FORMER = "бывшая деревня"

LICENSE = (
    "CC BY 4.0 (карточка набора на Zenodo и описание полей); нынешние названия — "
    "из топонимической базы Земельной службы Финляндии, тоже CC BY 4.0. Берутся "
    "факты — точка, годы, приходы, названия — со ссылкой на набор"
)

VILLAGES_FI = LayerSpec(
    slug="villages_fi",
    title="Деревни Финляндии и их приходы, 1540–1940",
    group="admin",
    source="«Suomen kylät 1540–1940», Национальный архив Финляндии (Kansallisarkisto), Zenodo",
    license=LICENSE,
    description=(
        "К какому приходу относилась деревня в 1800, 1850 или 1900 году: 14 172 "
        "деревни Финляндии с первым упоминанием и приходом (с 1865 года — общиной) "
        "на каждые пятьдесят лет с 1550 по 1950 год, 13 404 — с точкой. Готовая "
        "связка «деревня → приход» для всего Великого княжества и Выборгской "
        "губернии, включая земли, отошедшие к СССР. Версия набора неокончательная: "
        "часть приходов не сверена, такие годы помечены «?»."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=14172,
)


class SuomenKylatError(RuntimeError):
    """Набор не скачался, не сошёлся с ожидаемым или пришёл не в том виде."""


# --- координаты --------------------------------------------------------------
# ETRS-TM35FIN: GRS80, осевой меридиан 27° в. д., масштаб 0,9996, ложный восток
# 500 000 м, ложного севера нет. Обратная поперечная проекция Меркатора — ряды
# Крюгера по n = f / (2 − f): сначала с плоскости на «конформную сферу»
# (коэффициенты β), потом от конформной широты к геодезической (δ).

GRS80_A = 6_378_137.0
GRS80_F = 1 / 298.257222101
TM35_K0 = 0.9996
TM35_LON0 = 27.0
TM35_FALSE_EASTING = 500_000.0

_N = GRS80_F / (2 - GRS80_F)
# Радиус прямоугольной сферы: длина четверти меридиана, делённая на π/2.
_A_RECT = GRS80_A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_BETA = (
    _N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96 - _N ** 4 / 360,
    _N ** 2 / 48 + _N ** 3 / 15 - 437 * _N ** 4 / 1440,
    17 * _N ** 3 / 480 - 37 * _N ** 4 / 840,
    4397 * _N ** 4 / 161280,
)
_DELTA = (
    2 * _N - 2 * _N ** 2 / 3 - 2 * _N ** 3 + 116 * _N ** 4 / 45,
    7 * _N ** 2 / 3 - 8 * _N ** 3 / 5 - 227 * _N ** 4 / 45,
    56 * _N ** 3 / 15 - 136 * _N ** 4 / 35,
    4279 * _N ** 4 / 630,
)


def tm35fin_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """ETRS-TM35FIN (восток, север в метрах) → (широта, долгота) в градусах.

    ETRS89 принимается совпадающим с WGS84 — расхождение меньше метра.
    """
    xi = northing / (TM35_K0 * _A_RECT)
    eta = (easting - TM35_FALSE_EASTING) / (TM35_K0 * _A_RECT)
    xi1, eta1 = xi, eta
    for j, beta in enumerate(_BETA, start=1):
        xi1 -= beta * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta1 -= beta * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
    chi = math.asin(math.sin(xi1) / math.cosh(eta1))
    lat = chi + sum(delta * math.sin(2 * j * chi) for j, delta in enumerate(_DELTA, start=1))
    lon = math.radians(TM35_LON0) + math.atan2(math.sinh(eta1), math.cos(xi1))
    return math.degrees(lat), math.degrees(lon)


# --- запись на Zenodo --------------------------------------------------------

def fetch_manifest(*, timeout: int = 60) -> list[dict]:
    """Перечень файлов записи: имя, размер, сумма."""
    raw = fetch_bytes(FILES_API, error=SuomenKylatError, timeout=timeout)
    try:
        entries = json.loads(raw)["entries"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SuomenKylatError(f"ответ Zenodo не разбирается: {exc}") from exc
    return [{"key": e.get("key"), "size": e.get("size"), "checksum": e.get("checksum")}
            for e in entries]


def check_manifest(manifest: Iterable[dict]) -> list[str]:
    """Расхождения перечня с кодом; пусто — всё сходится."""
    by_key = {m.get("key"): m for m in manifest}
    got = by_key.get(CSV_KEY)
    if got is None:
        return [f"{CSV_KEY}: в записи такого файла нет; есть: "
                + ", ".join(sorted(str(k) for k in by_key))]
    problems = []
    if got.get("size") != CSV_SIZE:
        problems.append(f"размер {got.get('size')}, ожидался {CSV_SIZE}")
    if got.get("checksum") != f"md5:{CSV_MD5}":
        problems.append(f"сумма {got.get('checksum')}, ожидалась md5:{CSV_MD5}")
    return problems


def cached_csv(cache_dir: Path, *, timeout: int = 300) -> Path:
    """Таблица из кэша; нет её или она другая — скачивается и сверяется по md5."""
    path = Path(cache_dir) / CSV_KEY
    if path.exists() and path.stat().st_size == CSV_SIZE:
        return path
    data = fetch_bytes(CSV_URL, error=SuomenKylatError, timeout=timeout)
    digest = hashlib.md5(data).hexdigest()
    if len(data) != CSV_SIZE or digest != CSV_MD5:
        raise SuomenKylatError(f"скачано {len(data)} байт, md5 {digest}; ожидалось "
                               f"{CSV_SIZE} байт, md5 {CSV_MD5}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- чтение таблицы ----------------------------------------------------------

def read_rows(data: bytes) -> list[dict]:
    """Строки таблицы: UTF-8 с BOM, разделитель «;», кавычки «"» (так в описании полей)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SuomenKylatError(f"таблица не в UTF-8: {exc}") from exc
    rows = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=";", quotechar='"'))
    if not rows:
        raise SuomenKylatError("таблица пуста")
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        raise SuomenKylatError(f"нет колонок {missing}; пришли: {sorted(rows[0])}")
    return rows


def number(value) -> Optional[float]:
    """«208248», «208248,5» → число; пустое и мусор — ничего."""
    text = str(value or "").strip().replace(",", ".")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def year(value) -> Optional[int]:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def parish(value) -> tuple[Optional[str], bool]:
    """Приход из колонки: («Vehmaa», не сверен ли). «x» и пустое — не приход."""
    text = clean_text(value)
    if not text or text == CEDED:
        return None, False
    name = text.rstrip("?").strip()
    return (name or None), name != text


def parish_runs(row: dict, columns: Iterable[str] = YEAR_COLUMNS
                ) -> list[tuple[str, int, int, bool]]:
    """Подряд идущие колонки с одним приходом: (приход, с, по, есть ли «?»).

    Пустая колонка или «x» прерывают ряд: приход до и после пропуска —
    два отрезка, а не один, потому что о годах между ними набор молчит.
    """
    runs: list[tuple[str, int, int, bool]] = []
    previous_filled = False
    for column in columns:
        name, unsure = parish(row.get(column))
        if name is None:
            previous_filled = False
            continue
        when = int(column[1:])
        if runs and previous_filled and runs[-1][0] == name:
            _, first, _, was_unsure = runs[-1]
            runs[-1] = (name, first, when, was_unsure or unsure)
        else:
            runs.append((name, when, when, unsure))
        previous_filled = True
    return runs


def _run_text(run: tuple[str, int, int, bool]) -> str:
    name, first, last, unsure = run
    years = str(first) if first == last else f"{first}–{last}"
    return f"{name} ({years}{'?' if unsure else ''})"


def village_summary(row: dict, start: Optional[int], end: Optional[int]) -> str:
    """«Деревня прихода Taivassalo (1550–1900), Kustavi (1950); сейчас — …»."""
    runs = parish_runs(row, SUMMARY_COLUMNS)
    if runs:
        head = "Деревня прихода " + ", ".join(_run_text(r) for r in runs)
    else:
        head = "Деревня; приход до 1950 года в наборе не указан"
    now, _ = parish(row.get("v2023"))
    if now and end == STILL_VILLAGE:
        head += f"; сейчас — община {now}"
    tail = f"Первое упоминание — {start}" if start else "Первое упоминание в наборе не указано"
    if end == STILL_VILLAGE:
        tail += ", деревня существует и сейчас"
    elif end is None:
        tail += "; когда перестала быть деревней, в наборе не указано"
    else:
        tail += f"; по оценке составителей, перестала быть деревней в {end} году"
        if clean_text(row.get("v1950")) == CEDED and end >= 1940:
            tail += ", к 1950 году земля отошла к СССР"
    return f"{head}. {tail}."


def village_title(row: dict) -> str:
    """Нынешнее название и, если оно другое, написание старых источников."""
    name = clean_text(row.get("nimi")) or clean_text(row.get("nimi_2")) or "Без названия"
    old = clean_text(row.get("nimi_2"))
    # «Isokorpi 2» и «Isokorpi»: номер у одноимённых деревень реестра — не
    # другое написание, повторять его в скобках незачем.
    if old and old != name and re.sub(r"\s+\d+$", "", name) != old:
        return f"{name} ({old})"
    return name


def _variants(value) -> list[str]:
    text = clean_text(value)
    return [v.strip() for v in text.split(";") if v.strip()] if text else []


def years_of(row: dict) -> tuple[Optional[int], Optional[int], bool]:
    """(с, по, приблизительна ли) — см. шапку модуля.

    В версии 1 год первого упоминания и конец есть у каждой деревни. Если
    новая версия оставит их пустыми, начало берётся из самой ранней колонки
    с приходом, конец — из самой поздней, и запись становится приблизительной;
    без колонок тоже — дат нет вовсе.
    """
    start, end = year(row.get("start")), year(row.get("end"))
    filled = [int(c[1:]) for c in YEAR_COLUMNS if parish(row.get(c))[0]]
    if start is None:
        start = min(filled) if filled else None
    if start is None:
        return None, None, False
    if end == STILL_VILLAGE:
        return start, max(start, LAST_COLUMN_YEAR), False
    return start, max([start, *filled] + ([end] if end is not None else [])), True


def latest_parish(row: dict) -> Optional[str]:
    """Последний приход до горизонта; если его нет — последний вообще."""
    for columns in (SUMMARY_COLUMNS, YEAR_COLUMNS):
        for column in reversed(columns):
            name, _ = parish(row.get(column))
            if name:
                return name
    return None


def wikidata_url(value) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    return "https://www.wikidata.org/wiki/" + text.rstrip("/").rsplit("/", 1)[-1]


def row_to_record(row: dict) -> ContextRecord:
    """Строка набора → запись слоя. Губерния и рамка — потом, `mark_frame`."""
    start, end_year, approx = years_of(row)
    raw_end = year(row.get("end"))
    x, y = number(row.get("x")), number(row.get("y"))
    lat = lon = None
    if x is not None and y is not None:
        lat, lon = tm35fin_to_wgs84(x, y)
    if lat is None:
        confidence = CONFIDENCE_NO_COORDS
    elif start is None:
        confidence = CONFIDENCE_NO_DATE
    elif start > HORIZON:
        confidence = CONFIDENCE_AFTER_HORIZON
    else:
        confidence = "ok"
    name = clean_text(row.get("nimi"))
    old = clean_text(row.get("nimi_2"))
    extra = {
        "parish": {c[1:]: v for c in YEAR_COLUMNS if (v := clean_text(row.get(c)))},
        "name_old": old if old and old != name else None,
        "name_variants": _variants(row.get("nimi_muu")) or None,
        "wikidata": wikidata_url(row.get("wikidata")),
        "nls_place": clean_text(row.get("placeid")),
        "diplomatarium": clean_text(row.get("df")),
        "suomen_asutus_1560": clean_text(row.get("asutus1560luv")),
    }
    return VILLAGES_FI.new_record(
        title=village_title(row),
        category=(CATEGORY_VILLAGE if raw_end == STILL_VILLAGE
                  else CATEGORY_FORMER if raw_end is not None else None),
        lat=lat, lon=lon,
        place_text=latest_parish(row),
        year_from=start, year_to=end_year,
        date_precision="year" if start is not None else "unknown",
        date_approx=approx,
        period_raw=f"{clean_text(row.get('start')) or '?'}–{clean_text(row.get('end')) or '?'}",
        summary=village_summary(row, year(row.get("start")), raw_end),
        url=DATASET_URL,
        source_id=clean_text(row.get("id")),
        confidence=confidence,
        extra={k: v for k, v in extra.items() if v},
    )


def records(rows: Iterable[dict]) -> list[ContextRecord]:
    """Записи слоя: по одной на деревню."""
    return [row_to_record(row) for row in rows]


# --- губерния и рамка --------------------------------------------------------
# Сам расчёт — `frame.Frame`: губернии 1897 года плюс государства CShapes. Здесь
# только то, что нужно финским шхерам и границе по Торнио, — см. шапку модуля.

# Шаги поиска берега для точки в море, градусы широты. В `frame.py` поиск
# кончается на 0,3°, а внешние шхеры Турку лежат от суши контура дальше.
SHORE_STEPS = (0.4, 0.5, 0.6, 0.8, 1.0)
_DIRECTIONS = tuple((math.sin(k * math.pi / 8), math.cos(k * math.pi / 8)) for k in range(16))

FRAME_SHORE = "по берегу"
FRAME_BY_PARISH = "по приходу в наборе"


def _land(frame, lat: float, lon: float) -> tuple[Optional[bool], Optional[str]]:
    """Чья это земля: (в рамке ли, губерния) или (None, None) — вода.

    То же, что `Frame._land`, только через открытые поля рамки.
    """
    province = frame.provinces.region_for(lat, lon)
    if province:
        return True, province
    hits = [framed for framed, shape in frame.states if shape.contains(lat, lon)]
    if not hits:
        return None, None
    return any(hits), None


def _far_shore(frame, lat: float, lon: float) -> tuple[Optional[bool], Optional[str]]:
    """Первая суша вокруг точки в море, дальше, чем ищет `frame.py`."""
    stretch = 1 / max(math.cos(math.radians(lat)), 0.2)
    for step in SHORE_STEPS:
        for dy, dx in _DIRECTIONS:
            framed, province = _land(frame, lat + dy * step, lon + dx * step * stretch)
            if framed is not None:
                return framed, province
    return None, None


def listed_in_frame(parish_by_year: dict) -> bool:
    """Ставит ли набор деревню в рамку сам: община или «x» в 1950–2023 годах."""
    return any(clean_text(parish_by_year.get(c[1:])) for c in FRAME_COLUMNS)


def place(frame, rec: ContextRecord) -> tuple[bool, Optional[str], Optional[str]]:
    """(в рамке ли, губерния 1897 года, как найдено) для записи с точкой."""
    inside, province, shore = frame.place(rec.lat, rec.lon)
    if inside:
        return True, province, FRAME_SHORE if shore else None
    # Чужую сушу не двигают никогда — как и в `frame.py`; дальний берег
    # ищется только точке в море.
    if _land(frame, rec.lat, rec.lon)[0] is None:
        framed, found = _far_shore(frame, rec.lat, rec.lon)
        if framed:
            return True, found, FRAME_SHORE
    if listed_in_frame(rec.extra.get("parish") or {}):
        return True, None, FRAME_BY_PARISH
    return False, None, None


def mark_frame(records: Iterable[ContextRecord], frame) -> Counter:
    """Губерния 1897 года в `region` и пометка `outside_bbox`. Возвращает счёт."""
    counts: Counter = Counter()
    for rec in records:
        if not rec.has_point:
            counts["без точки"] += 1
            continue
        inside, province, how = place(frame, rec)
        rec.region = province
        if how:
            rec.extra["frame"] = how
            counts[f"из них найдены {how}"] += 1
        if province:
            counts["в губерниях 1897 года"] += 1
        elif inside:
            counts["в рамке, вне губерний 1897 года"] += 1
        else:
            rec.confidence = OUTSIDE
            counts["вне рамки РИ/СССР"] += 1
    return counts
