"""События, действовавшие на территории, а не в точке.

Самое ценное для генеалогии почти никогда не является точкой на карте.
Ревизия, отмена крепостного права, воинская повинность, голод 1891 года,
депортация — всё это происходит с целой губернией или со всей страной, и
именно этим объясняется, почему нужный документ существует, куда он делся
и почему семья вдруг оказалась за две тысячи вёрст от родного села.

Слой собран вручную: запросом такое не выгрузишь, потому что в Викиданных
у подобных событий нет ни координат, ни привязки к губерниям. Источник —
законодательные акты и справочная литература, перечень дат и территорий
лежит в `data/curated/state_events.json` и правится без правки кода.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..schema import SCOPE_REGION, SCOPE_STATE, LayerSpec, clean_text

STATE_EVENTS = LayerSpec(
    slug="state_events",
    title="Указы, реформы и потрясения",
    group="state",
    source="Подборка проекта по законодательным актам и справочной литературе",
    license="CC BY 4.0 (тексты пояснений); сами акты и даты — общественное достояние",
    description=(
        "События, охватывающие губернию или всё государство: ревизии и переписи, "
        "крепостное право и повинности, межевания и переселения, голод и эпидемии, "
        "мобилизации, ссылка и депортации, перекройки губерний и утраты самих архивов. "
        "Отвечают на вопрос, который не решает ни один точечный слой: почему "
        "документ о предке существует именно такой, где он теперь лежит и почему "
        "он оборвался."
    ),
    status="curated",
)

# Закрытый список: категория, которой нет в перечне, — это опечатка, а не
# новая тема. Перечень дублируется в самом файле данных и сверяется с ним.
CATEGORIES = (
    "учёт населения",
    "сословия и повинности",
    "вера и приход",
    "земля и переселение",
    "война и мобилизация",
    "голод и эпидемия",
    "репрессии и депортации",
    "границы и управление",
    "труд и промысел",
    "суд и ссылка",
    "архив и утраты",
)

# Рамка правдоподобия для дат: раньше — не наш период, позже — опечатка.
YEAR_MIN, YEAR_MAX = 1600, 1965

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "curated" / "state_events.json"


class DatasetError(ValueError):
    """Файл событий не проходит проверку."""


def load_state_events(path: Path | None = None) -> list:
    """Читает подборку событий и приводит её к единой схеме.

    Проверки строгие и падают с ошибкой: молча пропустить событие с битой
    датой хуже, чем остановиться — на карте такая запись выглядит достоверно.
    """
    path = Path(path) if path is not None else DEFAULT_PATH
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    events = payload.get("events") or []
    declared = tuple(payload.get("categories") or CATEGORIES)
    if set(declared) != set(CATEGORIES):
        raise DatasetError("перечень категорий в файле разошёлся с CATEGORIES")

    out, seen = [], set()
    for raw in events:
        event_id = clean_text(raw.get("id"))
        if not event_id:
            raise DatasetError(f"событие без id: {raw.get('title')!r}")
        if event_id in seen:
            raise DatasetError(f"повторяющийся id: {event_id}")
        seen.add(event_id)
        out.append(_to_record(raw, event_id))
    return out


def _to_record(raw: dict, event_id: str):
    title = clean_text(raw.get("title"))
    if not title:
        raise DatasetError(f"{event_id}: пустое название")

    category = clean_text(raw.get("category"))
    if category not in CATEGORIES:
        raise DatasetError(f"{event_id}: неизвестная категория {category!r}")

    year_from, year_to = _years(raw, event_id)

    scope = clean_text(raw.get("scope")) or SCOPE_STATE
    regions = [clean_text(r) for r in raw.get("regions") or []]
    regions = [r for r in regions if r]
    if scope == SCOPE_REGION and not regions:
        raise DatasetError(f"{event_id}: губернское событие без перечня губерний")
    if scope == SCOPE_STATE and regions:
        raise DatasetError(f"{event_id}: у общегосударственного события лишний перечень губерний")
    if scope not in (SCOPE_REGION, SCOPE_STATE):
        raise DatasetError(f"{event_id}: недопустимый охват {scope!r}")

    summary = clean_text(raw.get("summary"))
    if not summary:
        raise DatasetError(f"{event_id}: пустое описание")
    documents = clean_text(raw.get("documents"))
    if documents:
        summary = f"{summary} Что искать в архиве: {documents}."

    return STATE_EVENTS.new_record(
        title=title,
        category=category,
        scope=scope,
        place_text=clean_text(raw.get("place")),
        regions=regions,
        year_from=year_from,
        year_to=year_to,
        date_precision=clean_text(raw.get("precision")) or "year",
        date_approx=bool(raw.get("approx")),
        period_raw=str(year_from) if year_from == year_to else f"{year_from}–{year_to}",
        summary=summary,
        url=clean_text(raw.get("url")),
        source_id=event_id,
        extra={"documents": documents} if documents else {},
    )


def _years(raw: dict, event_id: str) -> tuple[int, int]:
    years = raw.get("years")
    if not isinstance(years, list) or len(years) != 2:
        raise DatasetError(f"{event_id}: годы должны быть парой [от, до]")
    try:
        year_from, year_to = int(years[0]), int(years[1])
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{event_id}: годы не разобраны: {years!r}") from exc
    if year_from > year_to:
        raise DatasetError(f"{event_id}: начало позже конца: {year_from} > {year_to}")
    if not (YEAR_MIN <= year_from and year_to <= YEAR_MAX):
        raise DatasetError(f"{event_id}: годы вне периода {YEAR_MIN}–{YEAR_MAX}: {years!r}")
    return year_from, year_to
