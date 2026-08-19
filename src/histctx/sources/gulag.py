"""Сбор слоя лагерей и лагерных управлений из «Карты ГУЛАГа».

Зачем отдельный источник. Слой территориальных событий говорит, что человека
осудили; он не говорит, куда его увезли. «Карта ГУЛАГа» Музея истории ГУЛАГа
собрана по справочнику «Мемориала» «Система исправительно-трудовых лагерей
в СССР, 1923–1960» и даёт ровно недостающее: управление, координата, годы
работы, производственный профиль и учтённая численность по годам. Для потомка
это подсказка, в каком архиве лежит личное дело.

Что берётся и что не берётся:

* **Берутся факты.** Название и второе название лагеря, координата управления,
  годы работы, тип, вид работ, численность заключённых по годам, ссылка на
  карточку проекта. Сведения такого рода охране не подлежат — по условию 3
  раздела «Каталог открыт» (`docs/CATALOG.md`) они берутся при любой лицензии.
* **Не берутся тексты.** Поле `description` карточки — авторская историческая
  справка музея, и она в записи не копируется: в `summary` идёт фраза,
  собранная из справочников и чисел, а за справкой запись отсылает на
  `gulagmap.ru`. Фотографии карточек не забираются и не подставляются
  ссылками: права на них принадлежат архивам и музею.

Чего ждать от данных. API отдаёт и неопубликованные карточки — их примерно
две пятых, и по составу полей они не хуже опубликованных. Молча выбрасывать
их нельзя (правило репозитория), выдавать за проверенные — тоже: такие записи
получают `confidence="unpublished_source"` и помечены в отчёте сбора.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Iterable, Optional

from ..geo import extract_district, extract_region, in_bbox, valid_coords
from ..schema import ContextRecord, LayerSpec, clean_text

BASE_URL = "https://gulagmap.ru/api"
CARD_URL = "https://gulagmap.ru/camp{id}"

# Заголовки HTTP кодируются latin-1 — в User-Agent только ASCII.
USER_AGENT = (
    "histctx/0.2 (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

# Первые лагеря принудительных работ — 1918 год, справочник «Мемориала»
# доведён до 1960-го. Всё, что вылезает за рамку, — ошибка разбора.
YEAR_MIN, YEAR_MAX = 1918, 1960

GULAG_CAMPS = LayerSpec(
    slug="gulag_camps",
    title="Лагеря и лагерные управления ГУЛАГа",
    group="hardship",
    source=(
        "Карта ГУЛАГа (Музей истории ГУЛАГа) по справочнику «Мемориала» "
        "«Система исправительно-трудовых лагерей в СССР, 1923–1960»"
    ),
    license=(
        "открытых условий проект не публикует; берутся только факты — название, "
        "координата, годы, численность — и ссылка на карточку. Авторские справки "
        "и фотографии не копируются"
    ),
    description=(
        "Лагерные управления 1918–1960 годов с координатами, годами работы, видом "
        "работ и учтённой численностью заключённых по годам. Отвечает на вопрос, "
        "куда человек уехал после приговора и где искать личное дело."
    ),
    url="https://gulagmap.ru/",
    status="harvested",
    expected_rows=1570,
)

# Поля, без которых разбор бессмысленен. Проверяются до него: если проект
# переделает API, сбор должен остановиться, а не выдать пустой слой.
REQUIRED_FIELDS = ("id", "title", "locations")

# Справочники: имя в API → как называть в записи.
REFERENCES = {
    "types": "camp-types",
    "activities": "camp-activities",
    "regions": "camp-regions",
}

# «1947-1953 Якутская АССР, город Якутск» — годы стоят в начале описания
# локации; тире бывает любым из трёх.
_RE_SPAN = re.compile(r"^\s*(\d{4})\s*(?:[-–—]\s*(\d{4}))?\s*(?:г{1,2}\.?)?\s*[.,]?\s*")


class GulagError(RuntimeError):
    """Запрос к «Карте ГУЛАГа» не выполнен или ответ не такой, какого мы ждём."""


def fetch(path: str, *, timeout: int = 60) -> list:
    """Забирает один эндпоинт API и возвращает разобранный список."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GulagError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GulagError(f"{url}: сеть недоступна ({exc.reason})") from exc
    except json.JSONDecodeError as exc:
        raise GulagError(f"{url}: ответ не разбирается как JSON ({exc})") from exc
    if not isinstance(payload, list):
        raise GulagError(f"{url}: ожидался список, пришло {type(payload).__name__}")
    return payload


def fetch_all(*, timeout: int = 60) -> tuple[list, dict]:
    """Карточки лагерей и три справочника к ним одним заходом."""
    camps = fetch("camps", timeout=timeout)
    refs = {name: reference_titles(fetch(path, timeout=timeout))
            for name, path in REFERENCES.items()}
    return camps, refs


def reference_titles(rows: Iterable[dict], lang: str = "ru") -> dict[int, str]:
    """Справочник вида `{id: название}`; записи без названия пропускаются."""
    out: dict[int, str] = {}
    for row in rows or []:
        ident = row.get("id")
        title = clean_text((row.get("title") or {}).get(lang))
        if ident is not None and title:
            out[int(ident)] = title
    return out


def check_camp_fields(camps: list) -> None:
    """Проверяет, что в ответе есть поля, на которых держится разбор."""
    if not camps:
        raise GulagError("в ответе нет ни одной карточки лагеря")
    keys = set(camps[0])
    missing = [f for f in REQUIRED_FIELDS if f not in keys]
    if missing:
        raise GulagError(
            f"в карточке нет обязательных полей {missing}; пришли: {sorted(keys)}. "
            "Проверьте https://gulagmap.ru/api/camps и поправьте разбор."
        )


def split_years(text: Optional[str]) -> tuple[Optional[int], Optional[int], str]:
    """Отрезает годы от описания локации.

    Возвращает `(год от, год до, остаток текста)`. Остаток — это место
    («Якутская АССР, город Якутск»), и он нужен целиком: по нему определяются
    губерния и уезд.
    """
    s = clean_text(text) or ""
    match = _RE_SPAN.match(s)
    if not match:
        return None, None, s
    year_from = int(match.group(1))
    year_to = int(match.group(2)) if match.group(2) else year_from
    if year_to < year_from:
        year_from, year_to = year_to, year_from
    return year_from, year_to, s[match.end():].strip()


def statistics_years(location: dict) -> list[int]:
    """Годы, за которые в карточке есть численность, — тоже датировка."""
    out = []
    for row in location.get("statistics") or []:
        year = row.get("year")
        if isinstance(year, int) and YEAR_MIN <= year <= YEAR_MAX:
            out.append(year)
    return sorted(out)


def peak_prisoners(location: dict) -> tuple[Optional[int], Optional[int]]:
    """Наибольшая учтённая численность и её год.

    Нули в карточках означают «сведений нет», а не «в лагере никого не было»:
    в тот же год лагерь по описанию работает. Поэтому ноль в пик не идёт.
    """
    best_count, best_year = None, None
    for row in location.get("statistics") or []:
        count, year = row.get("prisonersCount"), row.get("year")
        if not isinstance(count, int) or count <= 0 or not isinstance(year, int):
            continue
        if best_count is None or count > best_count:
            best_count, best_year = count, year
    return best_count, best_year


def camp_title(camp: dict, lang: str = "ru") -> Optional[str]:
    """Название с сокращением в скобках: «Джугджурский ИТЛ (Джугджурлаг)»."""
    title = clean_text((camp.get("title") or {}).get(lang))
    short = clean_text((camp.get("subTitles") or {}).get(lang))
    if title and short and short.lower() != title.lower():
        return f"{title} ({short})"
    return title or short


def build_summary(kind: Optional[str], activity: Optional[str],
                  peak: Optional[int], peak_year: Optional[int],
                  moved: bool) -> str:
    """Фраза из справочников и чисел, а не пересказ авторской справки."""
    parts = []
    if kind:
        parts.append(kind.rstrip("."))
    if activity:
        parts.append(f"вид работ — {activity[:1].lower() + activity[1:]}")
    if peak and peak_year:
        # Неразрывный пробел в разряде тысяч: «2 099» не должно рваться
        # переносом строки в карточке слоя.
        count = f"{peak:,}".replace(",", "\u00a0")
        parts.append(f"наибольшая учтённая численность — {count} человек в {peak_year} году")
    if moved:
        parts.append("одно из мест размещения управления")
    parts.append("справка и источники — на карточке проекта")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


def camps_to_records(camps: list, refs: Optional[dict] = None,
                     spec: LayerSpec = GULAG_CAMPS, *,
                     require_bbox: bool = True,
                     include_unpublished: bool = True) -> list[ContextRecord]:
    """Превращает ответ API в записи единой схемы — по записи на место.

    Управление, переехавшее из Котласа в Архангельск, — это две точки и два
    периода, а не одна усреднённая. Карточка без координаты или без года на
    карту не встанет и в подбор не пойдёт, поэтому пропускается.
    """
    check_camp_fields(camps)
    refs = refs or {}
    types = refs.get("types") or {}
    activities = refs.get("activities") or {}
    regions = refs.get("regions") or {}

    out: list[ContextRecord] = []
    for camp in camps:
        camp_id = camp.get("id")
        title = camp_title(camp)
        if camp_id is None or not title:
            continue
        published = bool((camp.get("published") or {}).get("ru")
                         or (camp.get("published") or {}).get("en"))
        if not published and not include_unpublished:
            continue

        locations = camp.get("locations") or []
        moved = len(locations) > 1
        kind = types.get(camp.get("typeId"))
        activity = activities.get(camp.get("activityId"))
        region_group = regions.get(camp.get("regionId"))

        for location in locations:
            record = _location_record(
                camp_id, title, location, spec,
                kind=kind, activity=activity, region_group=region_group,
                moved=moved, published=published, require_bbox=require_bbox,
            )
            if record is not None:
                out.append(record)
    return out


def _location_record(camp_id, title: str, location: dict, spec: LayerSpec, *,
                     kind, activity, region_group, moved: bool,
                     published: bool, require_bbox: bool) -> Optional[ContextRecord]:
    lat, lon = _point(location.get("geometry"))
    if lat is None:
        return None
    if require_bbox and not in_bbox(lat, lon):
        return None

    year_from, year_to, place = split_years((location.get("description") or {}).get("ru"))
    years = statistics_years(location)
    if year_from is None and years:
        # Датировки в описании нет, но численность по годам есть: границы
        # берутся по ней. Это уже приблизительно, и так и помечается.
        year_from, year_to = years[0], years[-1]
        approx = True
    else:
        approx = False
    if year_from is None:
        return None
    year_from = max(year_from, YEAR_MIN)
    year_to = min(year_to or year_from, YEAR_MAX)
    if year_to < year_from:
        return None

    peak, peak_year = peak_prisoners(location)
    span = year_to - year_from
    extra = {"prisoners": {str(r["year"]): r.get("prisonersCount")
                           for r in location.get("statistics") or []
                           if isinstance(r.get("year"), int)}}
    if region_group:
        extra["camp_region"] = region_group
    if peak:
        extra["prisoners_peak"] = peak

    return spec.new_record(
        title=title,
        category=kind,
        lat=lat, lon=lon,
        place_text=place or None,
        region=extract_region(place),
        district=extract_district(place),
        year_from=year_from,
        year_to=year_to,
        date_precision="year" if span == 0 else "part",
        date_approx=approx or span > 0,
        period_raw=str(year_from) if span == 0 else f"{year_from}–{year_to}",
        summary=build_summary(kind, activity, peak, peak_year, moved),
        url=CARD_URL.format(id=camp_id),
        source_id=f"{camp_id}:{location.get('id')}",
        confidence="ok" if published else "unpublished_source",
        extra={k: v for k, v in extra.items() if v},
    )


def _point(geometry) -> tuple[Optional[float], Optional[float]]:
    """GeoJSON-точка отдаётся парой [долгота, широта] — порядок обратный."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None, None
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None, None
    lon, lat = coords[0], coords[1]
    if not valid_coords(lat, lon):
        return None, None
    return float(lat), float(lon)
