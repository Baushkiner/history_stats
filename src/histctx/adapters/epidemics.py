"""Эпидемии: вспышки в населённых пунктах, собранные вручную.

В метрической книге эпидемия видна как всплеск смертей за несколько недель,
и вопрос исследователя — «что это было» — решается только тогда, когда
известно, где и когда болезнь действительно приходила. Викиданные на этот
вопрос не отвечают: дореволюционных вспышек с местом и датой там нет вовсе
(замер в `queries/epidemics.rq`). Поэтому слой ведётся как подборка: каждая
вспышка выписана из исследовательской или справочной литературы с
указанием страницы, где её можно проверить, а координата взята у
населённого пункта — отсюда `confidence = place_level` у каждой точки.

Подборка лежит в `data/curated/epidemics.json` и правится без правки кода.
Общегосударственные волны — четыре холерные эпидемии, «испанка», сыпной тиф
Гражданской войны — сюда не входят: у них нет точки, и они расписаны по
губерниям в слое «Указы, реформы и потрясения». Здесь — то, что случилось
в конкретном селе, станице, на станции или руднике.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..geo import in_bbox, valid_coords
from ..schema import SCOPE_POINT, SCOPE_REGION, LayerSpec, clean_text

EPIDEMICS = LayerSpec(
    slug="epidemics",
    title="Эпидемии",
    group="hardship",
    source="Подборка проекта по исследовательской и справочной литературе",
    license=(
        "факты (место, годы, число заболевших и умерших) — со ссылкой на источник "
        "в каждой записи; тексты пояснений — CC BY 4.0"
    ),
    description=(
        "Вспышки чумы, холеры, оспы, тифа и других болезней в конкретных "
        "населённых пунктах. В метрических книгах видны как всплеск смертей "
        "за короткий срок — слой объясняет причину."
    ),
    status="curated",
)

# Закрытый список: болезнь, которой нет в перечне, — опечатка, а не новая
# тема. Перечень дублируется в самом файле данных и сверяется с ним.
DISEASES = (
    "чума",
    "холера",
    "оспа",
    "сыпной тиф",
    "брюшной тиф",
    "возвратный тиф",
    "тиф",
    "сибирская язва",
    "грипп",
    "дифтерия",
    "малярия",
    "другое",
)

PRECISIONS = ("day", "month", "season", "year", "decade")

# Рамка правдоподобия для дат — та же, что у кураторских территориальных
# событий: раньше — не наш период, позже — опечатка.
YEAR_MIN, YEAR_MAX = 1600, 1965

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "curated" / "epidemics.json"


class DatasetError(ValueError):
    """Файл вспышек не проходит проверку."""


def load_epidemics(path: Optional[Path] = None) -> list:
    """Читает подборку вспышек и приводит её к единой схеме.

    Проверки падают с ошибкой, а не пропускают запись: вспышка с битой датой
    или координатой на карте выглядит достоверно и вводит в заблуждение.
    """
    path = Path(path) if path is not None else DEFAULT_PATH
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    declared = tuple(payload.get("diseases") or DISEASES)
    if set(declared) != set(DISEASES):
        raise DatasetError("перечень болезней в файле разошёлся с DISEASES")
    sources = payload.get("sources") or {}

    out, seen = [], set()
    for raw in payload.get("outbreaks") or []:
        outbreak_id = clean_text(raw.get("id"))
        if not outbreak_id:
            raise DatasetError(f"вспышка без id: {raw.get('title')!r}")
        if outbreak_id in seen:
            raise DatasetError(f"повторяющийся id: {outbreak_id}")
        seen.add(outbreak_id)
        out.append(_to_record(raw, outbreak_id, sources))
    return out


def _to_record(raw: dict, outbreak_id: str, sources: dict):
    title = clean_text(raw.get("title"))
    if not title:
        raise DatasetError(f"{outbreak_id}: пустое название")

    disease = clean_text(raw.get("disease"))
    if disease not in DISEASES:
        raise DatasetError(f"{outbreak_id}: неизвестная болезнь {disease!r}")

    year_from, year_to = _years(raw, outbreak_id)
    precision = clean_text(raw.get("precision")) or "year"
    if precision not in PRECISIONS:
        raise DatasetError(f"{outbreak_id}: недопустимая точность даты {precision!r}")

    source_key = clean_text(raw.get("source"))
    if source_key not in sources:
        raise DatasetError(f"{outbreak_id}: источник {source_key!r} не описан в sources")
    url = clean_text(raw.get("url")) or clean_text(sources[source_key].get("url"))
    if not url:
        raise DatasetError(f"{outbreak_id}: нет ссылки, по которой запись проверяется")

    scope = clean_text(raw.get("scope")) or SCOPE_POINT
    region = clean_text(raw.get("region"))
    regions: list = []
    lat, lon, confidence = None, None, "no_coords"
    if scope == SCOPE_POINT:
        lat, lon, confidence = _coords(raw, outbreak_id)
    elif scope == SCOPE_REGION:
        # Вспышка «в прикаспийских урочищах» или «в улусах округа» случилась
        # не в точке. Ставить её в губернский город — выдумка, поэтому она
        # подбирается по губернии, как территориальные события.
        regions = [clean_text(r) for r in raw.get("regions") or [region]]
        regions = [r for r in regions if r]
        if not regions:
            raise DatasetError(f"{outbreak_id}: у вспышки без точки не названа губерния")
        if len(regions) != len(set(regions)):
            raise DatasetError(f"{outbreak_id}: губерния повторена в перечне")
        confidence = "ok"
    else:
        raise DatasetError(f"{outbreak_id}: недопустимый охват {scope!r}")

    cases, deaths = _count(raw, "cases", outbreak_id), _count(raw, "deaths", outbreak_id)
    summary = clean_text(raw.get("summary"))
    if not summary:
        raise DatasetError(f"{outbreak_id}: пустое описание")
    tally = _tally(cases, deaths)
    if tally:
        summary = f"{summary} {tally}"

    extra = {"disease": disease}
    for key in ("form", "place_modern", "coord_source"):
        value = clean_text(raw.get(key))
        if value:
            extra[key] = value
    if cases is not None:
        extra["cases"] = cases
    if deaths is not None:
        extra["deaths"] = deaths

    return EPIDEMICS.new_record(
        title=title,
        category=disease,
        lat=lat,
        lon=lon,
        scope=scope,
        place_text=clean_text(raw.get("place")),
        region=region,
        regions=regions,
        year_from=year_from,
        year_to=year_to,
        date_precision=precision,
        date_approx=bool(raw.get("approx")),
        period_raw=clean_text(raw.get("date_text"))
        or (str(year_from) if year_from == year_to else f"{year_from}–{year_to}"),
        work=clean_text(sources[source_key].get("title")),
        summary=summary,
        url=url,
        source=clean_text(sources[source_key].get("cite")) or EPIDEMICS.source,
        source_id=outbreak_id,
        license=clean_text(sources[source_key].get("license")) or EPIDEMICS.license,
        confidence=confidence,
        extra=extra,
    )


def _coords(raw: dict, outbreak_id: str) -> tuple[Optional[float], Optional[float], str]:
    """Координата населённого пункта, а не самого очага.

    Вспышка без координаты остаётся в подборке с пометкой `no_coords`:
    разъезд Забайкальской дороги или хутор, которого нет ни на одной
    нынешней карте, — всё равно факт, и по нему можно искать в архиве.
    """
    lat, lon = raw.get("lat"), raw.get("lon")
    if lat is None and lon is None:
        return None, None, "no_coords"
    if not valid_coords(lat, lon):
        raise DatasetError(f"{outbreak_id}: координаты не разобраны: {lat!r}, {lon!r}")
    lat, lon = float(lat), float(lon)
    if not clean_text(raw.get("coord_source")):
        raise DatasetError(f"{outbreak_id}: не сказано, откуда взята координата")
    return lat, lon, "place_level" if in_bbox(lat, lon) else "outside_bbox"


def _years(raw: dict, outbreak_id: str) -> tuple[int, int]:
    years = raw.get("years")
    if not isinstance(years, list) or len(years) != 2:
        raise DatasetError(f"{outbreak_id}: годы должны быть парой [от, до]")
    try:
        year_from, year_to = int(years[0]), int(years[1])
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{outbreak_id}: годы не разобраны: {years!r}") from exc
    if year_from > year_to:
        raise DatasetError(f"{outbreak_id}: начало позже конца: {year_from} > {year_to}")
    if not (YEAR_MIN <= year_from and year_to <= YEAR_MAX):
        raise DatasetError(f"{outbreak_id}: годы вне периода {YEAR_MIN}–{YEAR_MAX}: {years!r}")
    return year_from, year_to


def _count(raw: dict, key: str, outbreak_id: str) -> Optional[int]:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DatasetError(f"{outbreak_id}: {key} должно быть целым неотрицательным: {value!r}")
    return value


def _tally(cases: Optional[int], deaths: Optional[int]) -> Optional[str]:
    parts = []
    if cases is not None:
        parts.append(f"заболело {format_count(cases)}")
    if deaths is not None:
        parts.append(f"умерло {format_count(deaths)}")
    if not parts:
        return None
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


def format_count(n: int) -> str:
    """Число с разделением разрядов, как в русском тексте: «10 000»."""
    return f"{n:,}".replace(",", " ") if n >= 10_000 else str(n)
