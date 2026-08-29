"""Слой рабочих конфликтов Российской империи 1895–1904 годов.

Зачем этот слой. Тема «труд и промысел» в подборке событий отвечает, что
паспорт на отход существовал и что на фабрике велась расчётная книжка, — но не
отвечает, что происходило на конкретном заводе в конкретный год. Свод отчётов
фабричных инспекторов, оцифрованный Международным институтом социальной
истории (IISH), закрывает именно это: 7886 стачек, волнений, сходок и
предъявлений требований с губернией, уездом, заводом, датами, числом
участников, причинами и действиями властей.

Для генеалогии это ответ на два вопроса. Первый — почему предок ушёл с
завода или из уезда именно в этот год. Второй — откуда взялся полицейский
след: в 260 записях вызывали полицию или войска, и надзор за участником
стачки оставлял бумаги там, где метрика молчит.

Что берётся и что не берётся. Набор лежит под **CC0** — правовых ограничений
нет вовсе, но копировать целиком незачем: в записи схемы идут факты (место,
даты, завод, отрасль, числа, исход) и ссылка на набор, а кодовые справочники
причин и требований остаются в `extra` как есть, без перевода в пересказ.

Чего ждать от данных. Координат в наборе нет: место задано губернией и
текстом «Красноуфимский уезд, пос.Михайловский завод». Поэтому записи
территориальные (`scope="region"`) — так же устроен слой итогов переписей.
Поле `Province` заполнено не всегда чисто: в сотне строк вместо губернии
стоит уезд или местечко, а «Область Войска Донского» встречается в двух
написаниях. Такие строки не выбрасываются: губерния остаётся неразобранной,
запись получает `confidence="province_unparsed"` и попадает в отчёт сбора.
"""

from __future__ import annotations

import csv
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

from ..geo import extract_district
from ..net import USER_AGENT
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text

# Карточка набора в репозитории IISH и прямая ссылка на ингестированный TSV.
DATASET_URL = "https://datasets.iisg.amsterdam/dataset.xhtml?persistentId=hdl:10622/LSCGBO"
DATA_URL = "https://datasets.iisg.amsterdam/api/access/datafile/9769"


# Свод охватывает десятилетие между двумя фабричными законами. Всё, что
# вылезает за рамку, — ошибка разбора, а не находка.
YEAR_MIN, YEAR_MAX = 1895, 1904

STRIKES = LayerSpec(
    slug="labour_conflicts",
    title="Стачки и рабочие волнения 1895–1904 годов",
    group="economy",
    source=(
        "International Institute of Social History, Micro data on strikes in the "
        "Russian Empire 1895–1904 (по отчётам фабричных инспекторов)"
    ),
    license="CC0 1.0 — общественное достояние; ссылка на набор проставляется в записи",
    description=(
        "Стачки, волнения, сходки и предъявления требований на заводах и стройках "
        "Российской империи 1895–1904 годов: губерния, уезд, предприятие, даты, "
        "отрасль, число бастовавших, требования, исход и вызов полиции или войск. "
        "Объясняет, почему человек ушёл с завода и откуда взялся полицейский надзор."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=7886,
)

# Без этих колонок разбор бессмысленен: если IISH переделает набор, сбор
# должен остановиться с перечнем того, что пришло, а не выдать пустой слой.
REQUIRED_COLUMNS = (
    "Province", "LocationofFactory", "NameofFactory",
    "BeginYear", "EndYear", "Startmonth", "Typeofconflict", "Outcome",
)

# Вид конфликта из кодировки набора — по-русски. Список закрытый: значение,
# которого здесь нет, остаётся английским и видно в отчёте сбора.
CONFLICT_KINDS = {
    "Strike": "Стачка",
    "Collective strike": "Коллективная стачка",
    "General strike": "Всеобщая стачка",
    "General strike of workers of one trade": "Всеобщая стачка рабочих одного ремесла",
    "City Strike": "Городская стачка",
    "All-city action of workers": "Общегородское выступление рабочих",
    "Unrest": "Волнения",
    "Collective unrest": "Коллективные волнения",
    "Demonstration, meeting": "Демонстрация или сходка",
    "Secret meeting, mayovka": "Тайная сходка, маёвка",
    "The statement of requirements (Giving of requirements)": "Предъявление требований",
    "Giving of the complaint or application": "Жалоба или прошение",
    "Giving by workers the judicial claim on the owner": "Судебный иск к владельцу",
    "Collective action of workers": "Коллективное выступление рабочих",
    "General action of workers": "Общее выступление рабочих",
    "General action of workers of one trade": "Общее выступление рабочих одного ремесла",
    "A working holiday, posting of flags": "Рабочий праздник",
}

OUTCOMES = {
    "Victory": "требования удовлетворены",
    "Lost": "требования отклонены",
    "Settled": "улажено",
    "Improvements promised": "обещаны улучшения",
    "Requirements not made to the right adressee": "требования предъявлены не по адресу",
    "Unknown": "исход неизвестен",
}

# Две записи одной территории: в своде она набрана двумя способами, и без
# сведения к одному написанию губерния распалась бы надвое.
PROVINCE_ALIASES = {
    "Област Войска Донского": "Область Войска Донского",
    "Область Войская Донского": "Область Войска Донского",
}

_RE_PROVINCE_ADJ = re.compile(r"^[А-ЯЁ][а-яё-]+(?:ая|яя)$")
_RE_OBLAST = re.compile(r"^(.+?)\s+обл\.?$")
# «[Варшавская]» — так в своде помечена губерния, восстановленная составителем
# по косвенным данным. Скобки снимаются, сомнение остаётся в поле confidence.
_RE_BRACKETS = re.compile(r"^\[(.+)\]$")


class StrikesError(RuntimeError):
    """Набор не пришёл или устроен не так, как ожидает разбор."""


def fetch(cache_dir: Path) -> Path:
    """Скачивает TSV набора в кэш и возвращает путь. Уже скачанное не трогает."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "strikes_1895_1904.tsv"
    if path.exists() and path.stat().st_size > 0:
        return path
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StrikesError(f"не удалось скачать набор: {exc}") from exc
    if len(data) < 100_000:
        raise StrikesError(f"набор подозрительно мал: {len(data)} байт")
    path.write_bytes(data)
    return path


def check_columns(header: Iterable[str]) -> None:
    """Проверяет состав колонок до разбора."""
    names = list(header)
    missing = [c for c in REQUIRED_COLUMNS if c not in names]
    if missing:
        raise StrikesError(
            "в наборе нет обязательных колонок: " + ", ".join(missing)
            + "; пришли: " + ", ".join(names[:20])
        )


def read_rows(path: Path) -> list[dict]:
    """Читает TSV набора и проверяет колонки."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        check_columns(reader.fieldnames or [])
        return list(reader)


def parse_int(value) -> Optional[int]:
    """«1895.0», « 800 », «» — к числу или None."""
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(" ", "").replace(",", ".")
    try:
        return int(float(text))
    except ValueError:
        return None


def normalize_province(value) -> Optional[str]:
    """Приводит поле Province к названию территории или отказывается.

    «Пермская» → «Пермская губерния», «Терская обл.» → «Терская область»,
    «[Варшавская]» → «Варшавская губерния». Строка, в которой вместо губернии
    записан уезд или город, названием территории не становится: пусть лучше
    запись честно останется без губернии, чем подберётся к чужому факту.
    """
    text = clean_text(value)
    if text is None:
        return None
    m = _RE_BRACKETS.match(text)
    if m:
        text = m.group(1).strip()
    text = PROVINCE_ALIASES.get(text, text)
    if _RE_PROVINCE_ADJ.match(text):
        return f"{text} губерния"
    m = _RE_OBLAST.match(text)
    if m:
        return f"{m.group(1)} область"
    if re.search(r"губерн|област|окру|войск", text, re.IGNORECASE):
        return text
    return None


def parse_provinces(value) -> list:
    """Разбирает поле Province, включая перечисление нескольких губерний.

    Конфликт на железной дороге или на промыслах шёл сразу по нескольким
    губерниям, и в своде они записаны через запятую: «Архангельская,
    Вологодская, Олонецкая». Схема такое держит списком, поэтому терять
    перечисление незачем — но только если каждая часть действительно
    губерния: иначе «Белостокский уезд, мест.Супросль» развалилось бы на два
    несуществующих названия.
    """
    text = clean_text(value)
    if text is None:
        return []
    single = normalize_province(text)
    if single:
        return [single]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < 2:
        return []
    names = [normalize_province(p) for p in parts]
    return names if all(names) else []


def conflict_kind(value) -> Optional[str]:
    text = clean_text(value)
    if text is None:
        return None
    return CONFLICT_KINDS.get(text, text)


def record_years(row: dict) -> tuple[Optional[int], Optional[int], str]:
    """Годы конфликта и точность датировки."""
    year_from = parse_int(row.get("BeginYear"))
    year_to = parse_int(row.get("EndYear")) or year_from
    if year_from is None:
        return None, None, "unknown"
    if year_to is None or year_to < year_from:
        year_to = year_from
    month = parse_int(row.get("Startmonth"))
    day = parse_int(row.get("Startday2")) or parse_int(row.get("Startday"))
    precision = "day" if month and day else ("month" if month else "year")
    return year_from, year_to, precision


def record_title(row: dict) -> str:
    kind = conflict_kind(row.get("Typeofconflict")) or "Рабочий конфликт"
    factory = clean_text(row.get("NameofFactory"))
    if factory:
        return f"{kind}: {factory}"
    place = clean_text(row.get("LocationofFactory")) or normalize_province(row.get("Province"))
    return f"{kind}: {place}" if place else kind


def record_summary(row: dict) -> Optional[str]:
    """Фраза человеческим языком: кто бастовал, сколько, чем кончилось."""
    parts = []
    sector = clean_text(row.get("Theeconomicsector"))
    if sector:
        parts.append(re.sub(r"^\d+\.\s*", "", sector))
    strikers = parse_int(row.get("NumberofStrikers"))
    workers = parse_int(row.get("Numberofallworkers"))
    if strikers and workers:
        parts.append(f"участвовали {strikers} из {workers} рабочих")
    elif strikers:
        parts.append(f"участвовали {strikers} рабочих")
    days = parse_int(row.get("DurationofStrike"))
    if days:
        parts.append(f"продолжительность {days} дн.")
    outcome = clean_text(row.get("Outcome"))
    if outcome:
        parts.append(OUTCOMES.get(outcome, outcome))
    if clean_text(row.get("Police/army")):
        parts.append("вызваны полиция или войска")
    return "; ".join(parts) if parts else None


def _listed(row: dict, prefix: str, count: int = 4) -> list:
    """Причины и требования лежат в четырёх колонках подряд."""
    values = []
    for i in range(1, count + 1):
        text = clean_text(row.get(f"{prefix}{i}"))
        if text:
            values.append(text)
    return values


def row_to_record(row: dict) -> ContextRecord:
    """Одна строка свода → запись схемы."""
    year_from, year_to, precision = record_years(row)
    provinces = parse_provinces(row.get("Province"))
    province = provinces[0] if provinces else None
    location = clean_text(row.get("LocationofFactory"))
    place_bits = [b for b in (location, "; ".join(provinces) or None) if b]

    # Стачка, начатая в декабре 1904 года, кончалась уже в 1905-м — верхняя
    # граница у конца на год шире, чем у начала, и это не ошибка разбора.
    confidence = "ok"
    if not provinces:
        confidence = "province_unparsed"
    elif year_from is not None and not (YEAR_MIN <= year_from <= YEAR_MAX):
        confidence = "year_out_of_range"
    elif year_to is not None and year_to > YEAR_MAX + 1:
        confidence = "year_out_of_range"

    extra = {
        "province_raw": clean_text(row.get("Province")),
        "sector": clean_text(row.get("Theeconomicsector")),
        "causes": _listed(row, "Cause"),
        "demands": _listed(row, "Demands"),
        "strikers": parse_int(row.get("NumberofStrikers")),
        "workers": parse_int(row.get("Numberofallworkers")),
        "duration_days": parse_int(row.get("DurationofStrike")),
        "outcome": clean_text(row.get("Outcome")),
        "police_or_army": bool(clean_text(row.get("Police/army"))),
        "source_reference": clean_text(row.get("SourceReferences")),
    }
    extra = {k: v for k, v in extra.items() if v not in (None, [], False)}

    number = parse_int(row.get("Number"))
    source_id = f"{year_from}-{number}" if year_from and number else None

    return STRIKES.new_record(
        title=record_title(row),
        category=conflict_kind(row.get("Typeofconflict")),
        scope=SCOPE_REGION,
        place_text="; ".join(place_bits) or None,
        region=province,
        regions=list(provinces),
        district=extract_district(location),
        year_from=year_from,
        year_to=year_to,
        date_precision=precision,
        period_raw=clean_text(row.get("Date1ORG")),
        work=clean_text(row.get("NameofFactory")),
        summary=record_summary(row),
        url=DATASET_URL,
        source_id=source_id,
        confidence=confidence,
        extra=extra,
    )


def rows_to_records(rows: Iterable[dict]) -> list[ContextRecord]:
    return [row_to_record(row) for row in rows]
