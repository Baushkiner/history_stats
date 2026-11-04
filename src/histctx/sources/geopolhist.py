"""Статус территорий мира 1816–1960 (GeoPolHist, Sciences Po).

Зачем этот слой. Границы государств (`cshapes.py`, `cliopatria.py`) отвечают,
чья земля, полигоном. Но CShapes не рисует территорий меньше 10 000 км², а
именно они нужны родословной по империи: Порт-Артур и Дальний — аренда
России 1895–1905 годов, Харбин — полоса КВЖД, Тува — протекторат и
непризнанная республика, Данциг, Мемель, Саар, Триест. Cliopatria до 1886
года даёт государства, но не колониальный статус. GeoPolHist закрывает обе
дыры: статус каждой геополитической единицы мира с 1816 года — 1 294
единицы, у каждой строки «единица — годы — статус — суверен».

Набор. B. Dedinger, P. Girard, «How many countries in the world?» (Historical
Methods 54(4), 2021), Sciences Po, médialab; версия 202603 — Zenodo
19252806. Основа — перечни государств и зависимых территорий Correlates of
War, дополненные до 1 294 единиц: суверены, колонии, протектораты, аренды,
мандаты, оккупации, вассалы, «части» других единиц, притязания, нейтральные
зоны. Статусов двадцать (`GeoPolHist_status.csv`), у единицы — Q-номер
Викиданных (у 1 274) и точка (у 1 122), у строки — годы «с» и «по».

Права. Карточка версии 202603 на Zenodo — CC BY 4.0; в `datapackage.json`
самого архива — ODbL 1.0, у версии 202103 — ODC-BY 1.0. Записи всё равно
факты — статус, суверен, годы, — и берутся со ссылкой на набор; подписи
по-русски — словарь проекта (`geopolhist_names.py`).

Что попадает в слой. Строки, годы которых пересекаются с рамкой 1816–1960,
— 3 958 строк 1 271 единицы; годы набора сохраняются как есть («Финляндия
1917–2022, суверенное государство» остаётся с концом 2022 года). Семь строк
набора начинаются со «?» — у всех это рифы и банки Карибского моря, — и
начало у них берётся от начала набора, 1816 года, с точностью `open`, как у
открытого срока в остальных слоях. Строка со статусом «упразднение»
(«вошла в состав») — событие одного года, у неё обе границы одинаковы.

Где запись на карте. У единицы в наборе одна точка — условный центр
территории, а не место события, поэтому такая запись помечена
`confidence = territory_center`. У города или округа (Харбин, Порт-Артур,
Данциг) этого хватает: подбор контекста ищет в 50 км. У страны — нет:
центр Литвы лежит в 95 км от Вильно. Для крупных единиц запись несёт номер
полигона CShapes (`extra.state_borders_gwcode`), если он у обоих наборов
один и тот же, — так совпадает 224 номера из 226, и карта может приложить
статус к полигону по номеру и дате. У 172 единиц точки нет вовсе; их
записи лежат файлом без точки, `confidence = no_coords`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Iterable, Optional

from ..net import fetch_bytes
from ..schema import ContextRecord, LayerSpec
from .geopolhist_names import NAMES_RU

RECORD_ID = "19252806"
VERSION = "202603"
DOI = "10.5281/zenodo.19252806"
CONCEPT_DOI = "10.5281/zenodo.4600809"
DATASET_URL = f"https://doi.org/{DOI}"
FILES_API = f"https://zenodo.org/api/records/{RECORD_ID}/files"
ARCHIVE_KEY = "medialab/GeoPolHist-202603.zip"
ARCHIVE_URL = f"{FILES_API}/{ARCHIVE_KEY}/content"
# Сверено с перечнем файлов записи 04.11.2026. Новая версия — новая запись
# Zenodo, новые размер и md5 здесь, сверенные руками.
ARCHIVE_SIZE = 1_339_466
ARCHIVE_MD5 = "6c5c5db7b6f90844f50f1c9707fb4769"
CACHE_NAME = "GeoPolHist-202603.zip"
VIZ_URL = "https://medialab.github.io/GeoPolHist/"

ENTITIES = "GeoPolHist_entities.csv"
STATUSES = "GeoPolHist_entities_status_over_time.csv"
STATUS_DEFS = "GeoPolHist_status.csv"
REQUIRED = {
    ENTITIES: ("GPH_code", "GPH_name", "continent", "wikidata", "lat", "lng"),
    STATUSES: ("GPH_code", "GPH_name", "start_year", "end_year", "GPH_status",
               "sovereign_GPH_code"),
    STATUS_DEFS: ("GPH_status", "definition"),
}

CITATION = (
    "Dedinger B., Girard P. «How many countries in the world? The geopolitical "
    "entities of the world and their political status from 1816 to the present», "
    "Historical Methods 54(4), 2021; набор — GeoPolHist, версия 202603, Sciences Po "
    f"médialab, Zenodo, doi:{DOI}. CC BY 4.0"
)

# Рамка слоя: начало набора и горизонт проекта.
YEAR_MIN, YEAR_MAX = 1816, 1960

LICENSE = (
    "CC BY 4.0 (карточка версии 202603 на Zenodo); в datapackage.json архива — "
    "ODbL 1.0, у версии 202103 — ODC-BY 1.0. Берутся факты — статус, суверен, годы — "
    "со ссылкой на набор; русские подписи — словарь проекта"
)

TERRITORY_STATUS = LayerSpec(
    slug="territory_status",
    title="Статус территорий мира 1816–1960",
    group="admin",
    source="GeoPolHist (Dedinger, Girard, Sciences Po), Zenodo",
    license=LICENSE,
    description=(
        "Чья это земля и на каком праве: 3 958 периодов статуса 1 271 территории "
        "мира — суверен, колония, протекторат, аренда, мандат, оккупация, «в составе» — "
        "с государством-сувереном и годами. Есть то, чего не рисуют границы "
        "государств: Харбин и полоса КВЖД, Порт-Артур, Тува, Данциг, Мемель, Саар."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=3958,
)

# Статус для заголовка и категории: существительным, чтобы суверен после
# двоеточия стоял в именительном падеже — «Харбин — аренда: Россия (СССР)».
# Склонять 400 названий суверенов значило бы завести второй словарь.
STATUS_RU = {
    "Sovereign": "суверенное государство",
    "Sovereign (limited)": "ограниченный суверенитет",
    "Sovereign (unrecognized)": "непризнанный суверенитет",
    "Associated state of": "ассоциированное государство",
    "Colony of": "колония",
    "Dependency of": "зависимая территория",
    "Possession of": "владение",
    "Protectorate of": "протекторат",
    "Leased to": "аренда",
    "Mandated to": "мандат",
    "Occupied by": "оккупация",
    "Vassal of": "вассалитет",
    "Claimed by": "притязания",
    "Neutral or demilitarized zone of": "нейтральная зона",
    "Discovered": "открыта",
    "Part of": "в составе",
    "Unknown": "статус неизвестен",
    "Informal": "неформальное объединение",
    "International": "международная организация",
    "Dissolved into": "упразднение",
}

# Пояснение: кем суверен приходится территории. «Владение» у набора — земля,
# удерживаемая только завоеванием (определение в `GeoPolHist_status.csv`).
STATUS_SUMMARY = {
    "Sovereign": "суверенное государство",
    "Sovereign (limited)": "суверенитет ограничен",
    "Sovereign (unrecognized)": "суверенитет не признан",
    "Associated state of": "ассоциированное государство; партнёр — {s}",
    "Colony of": "колония; метрополия — {s}",
    "Dependency of": "зависимая территория; метрополия — {s}",
    "Possession of": "владение по праву завоевания; владелец — {s}",
    "Protectorate of": "протекторат; протектор — {s}",
    "Leased to": "аренда; арендатор — {s}",
    "Mandated to": "мандат; мандатарий — {s}",
    "Occupied by": "оккупация; оккупирующее государство — {s}",
    "Vassal of": "вассалитет; сюзерен — {s}",
    "Claimed by": "притязания; претендент — {s}",
    "Neutral or demilitarized zone of":
        "нейтральная или демилитаризованная зона; сторона — {s}",
    "Discovered": "открыта, политического статуса ещё нет",
    "Part of": "в составе другой единицы — {s}",
    "Unknown": "статус неизвестен",
    "Informal": "неформальное объединение",
    "International": "международная организация",
    "Dissolved into": "упразднение; правопреемник — {s}",
}

CONFIDENCE_CENTER = "territory_center"
CONFIDENCE_NO_COORDS = "no_coords"

# Номера, под которыми у GeoPolHist и CShapes разные единицы: 711 —
# Маньчжоу-го и Тибет, 7506 — Малабарский берег и Джамму и Кашмир. Остальные
# 224 общих номера означают одно и то же (сверено по названиям 04.11.2026).
CODE_MISMATCH = frozenset({711, 7506})


class GeoPolHistError(RuntimeError):
    """Набор не скачался, не сошёлся с ожидаемым или пришёл не в том виде."""


# --- запись на Zenodo ------------------------------------------------------

def fetch_manifest(*, timeout: int = 60) -> list[dict]:
    """Перечень файлов записи: имя, размер, сумма."""
    raw = fetch_bytes(FILES_API, error=GeoPolHistError, timeout=timeout)
    try:
        entries = json.loads(raw)["entries"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeoPolHistError(f"ответ Zenodo не разбирается: {exc}") from exc
    return [{"key": e.get("key"), "size": e.get("size"), "checksum": e.get("checksum")}
            for e in entries]


def check_manifest(manifest: Iterable[dict]) -> list[str]:
    """Расхождения перечня с кодом; пусто — всё сходится."""
    by_key = {m.get("key"): m for m in manifest}
    got = by_key.get(ARCHIVE_KEY)
    if got is None:
        return [f"{ARCHIVE_KEY}: в записи такого файла нет; есть: "
                + ", ".join(sorted(str(k) for k in by_key))]
    problems = []
    if got.get("size") != ARCHIVE_SIZE:
        problems.append(f"размер {got.get('size')}, ожидался {ARCHIVE_SIZE}")
    if got.get("checksum") != f"md5:{ARCHIVE_MD5}":
        problems.append(f"сумма {got.get('checksum')}, ожидалась md5:{ARCHIVE_MD5}")
    return problems


def cached_archive(cache_dir: Path, *, timeout: int = 300) -> Path:
    """Архив из кэша; нет его или он другой — скачивается и сверяется по md5."""
    path = Path(cache_dir) / CACHE_NAME
    if path.exists() and path.stat().st_size == ARCHIVE_SIZE:
        return path
    data = fetch_bytes(ARCHIVE_URL, error=GeoPolHistError, timeout=timeout)
    digest = hashlib.md5(data).hexdigest()
    if len(data) != ARCHIVE_SIZE or digest != ARCHIVE_MD5:
        raise GeoPolHistError(f"скачано {len(data)} байт, md5 {digest}; ожидалось "
                              f"{ARCHIVE_SIZE} байт, md5 {ARCHIVE_MD5}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- чтение набора ---------------------------------------------------------

def read_archive(path: Path) -> dict[str, list[dict]]:
    """Три таблицы набора из архива: единицы, статусы по годам, определения.

    Архив — снимок репозитория médialab, и таблицы лежат в `<корень>/data/`;
    имя корня меняется от версии, поэтому файл ищется по концу пути. Читается
    в память, на диск ничего не распаковывается.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            tables = {}
            for name in REQUIRED:
                found = [n for n in archive.namelist() if n.endswith(f"/data/{name}")]
                if len(found) != 1:
                    raise GeoPolHistError(f"в архиве ждали один data/{name}, нашлось: {found}")
                text = archive.read(found[0]).decode("utf-8-sig")
                tables[name] = list(csv.DictReader(io.StringIO(text)))
    except zipfile.BadZipFile as exc:
        raise GeoPolHistError(f"{path}: не разбирается как zip ({exc})") from exc
    for name, columns in REQUIRED.items():
        check_columns(tables[name], columns, name)
    return tables


def check_columns(rows: list[dict], columns: Iterable[str], what: str) -> None:
    """Колонки, на которых держится разбор. Нет хоть одной — набор переделали."""
    if not rows:
        raise GeoPolHistError(f"{what}: таблица пуста")
    missing = [c for c in columns if c not in rows[0]]
    if missing:
        raise GeoPolHistError(f"{what}: нет колонок {missing}; пришли: {sorted(rows[0])}")


def year(value) -> Optional[int]:
    """Год из таблицы: «1896» — 1896, «?» и пустое — ничего."""
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def point(entity: dict) -> tuple[Optional[float], Optional[float]]:
    """Точка единицы, если она есть и похожа на координаты."""
    try:
        lat, lon = float(entity.get("lat")), float(entity.get("lng"))
    except (TypeError, ValueError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def name_ru(name: Optional[str]) -> Optional[str]:
    """Русская подпись единицы; незнакомое название идёт как есть."""
    if not name:
        return None
    return NAMES_RU.get(name, name)


def wikidata_url(value) -> Optional[str]:
    """«http://www.wikidata.org/entity/Q30» и «…/wiki/Q30» — к одному виду."""
    text = str(value or "").strip()
    if not text:
        return None
    return "https://www.wikidata.org/wiki/" + text.rstrip("/").rsplit("/", 1)[-1]


def overlaps(row: dict, year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> bool:
    """Пересекаются ли годы строки с рамкой; начало «?» — с начала набора."""
    start, end = year(row.get("start_year")), year(row.get("end_year"))
    if end is None:
        return False
    return (start if start is not None else year_min) <= year_max and end >= year_min


def status_title(entity: str, status: str, sovereign: Optional[str]) -> str:
    """«Харбин — аренда: Россия (СССР)», «Литва — суверенное государство»."""
    title = f"{entity} — {STATUS_RU.get(status, status)}"
    return f"{title}: {sovereign}" if sovereign else title


def status_summary(status: str, sovereign: Optional[str], period: str) -> str:
    """Годы и пояснение статуса; суверен — в именительном, после тире."""
    template = STATUS_SUMMARY.get(status, status)
    if "{s}" in template:
        text = template.format(s=sovereign) if sovereign else template.split(";")[0]
    else:
        text = f"{template}; связь — {sovereign}" if sovereign else template
    return f"{period}: {text}. По GeoPolHist"


def records(tables: dict[str, list[dict]], *, polygon_codes: Iterable[int] = (),
            year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> list[ContextRecord]:
    """Записи слоя: по одной на строку статуса, годы которой задевают рамку."""
    entities = {row["GPH_code"]: row for row in tables[ENTITIES]}
    polygons = {int(c) for c in polygon_codes} - CODE_MISMATCH
    out = []
    for row in tables[STATUSES]:
        if not overlaps(row, year_min, year_max):
            continue
        code = row["GPH_code"]
        entity = entities.get(code, {})
        name = row.get("GPH_name") or entity.get("GPH_name")
        status = row.get("GPH_status") or "Unknown"
        sov_code = (row.get("sovereign_GPH_code") or "").strip()
        sov_name = (entities.get(sov_code) or {}).get("GPH_name") if sov_code else None
        start, end = year(row.get("start_year")), year(row.get("end_year"))
        raw_period = f"{row.get('start_year')}–{row.get('end_year')}"
        precision = "year"
        if start is None:
            start, precision = year_min, "open"
        period = str(start) if start == end else f"{start}–{end}"
        lat, lon = point(entity)
        extra = {
            "gph_code": code,
            "status_en": status,
            "sovereign_gph_code": sov_code or None,
            "sovereign_en": sov_name,
            "wikidata": wikidata_url(entity.get("wikidata")),
            "continent": entity.get("continent") or None,
        }
        if code.isdigit() and int(code) in polygons:
            extra["state_borders_gwcode"] = int(code)
        out.append(TERRITORY_STATUS.new_record(
            title=status_title(name_ru(name), status, name_ru(sov_name)),
            category=STATUS_RU.get(status, status),
            lat=lat, lon=lon,
            place_text=name,
            year_from=start, year_to=end,
            date_precision=precision,
            period_raw=raw_period,
            actor=name_ru(sov_name),
            summary=status_summary(status, name_ru(sov_name), period),
            url=DATASET_URL,
            source_id=code,
            confidence=CONFIDENCE_CENTER if lat is not None else CONFIDENCE_NO_COORDS,
            extra={k: v for k, v in extra.items() if v is not None},
        ))
    return out


def untranslated(tables: dict[str, list[dict]]) -> list[str]:
    """Названия единиц без русской подписи: новая версия набора их добавит."""
    return sorted({row["GPH_name"] for row in tables[ENTITIES]} - set(NAMES_RU))


def unknown_statuses(tables: dict[str, list[dict]]) -> list[str]:
    """Статусы набора, которых нет в словаре: их подпись пойдёт по-английски."""
    return sorted({row["GPH_status"] for row in tables[STATUSES]} - set(STATUS_RU))


def polygon_codes(path: Path) -> set[int]:
    """Номера полигонов `state_borders.geojson` — для ссылки записи на полигон."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {f["properties"]["gwcode"] for f in payload.get("features", [])
            if isinstance((f.get("properties") or {}).get("gwcode"), int)}
