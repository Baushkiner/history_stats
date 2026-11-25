"""Малочисленные селения России: база «Вот моя деревня» (votmoyaderevnya.ru).

Зачем этот слой. В метрике и ревизской сказке предок записан деревней, а
деревни, где сейчас живут двадцать человек или не живёт никто, в GeoNames
есть не всегда, а если есть — без года основания и без прежнего имени. Сайт
«Вот моя деревня» — база именно таких мест: деревни, сёла, посёлки, хутора,
выселки, с нынешней муниципальной принадлежностью, точкой, прежними
названиями в скобках («Каркадиново (Красное, Слободка)»), статусом
«действующий/недействующий» и, где составители его нашли, годом основания.
Для генеалогии важнее всего недействующие: деревни, которых нет на нынешней
карте, но которые стоят в документах.

Устройство сайта. Страницы — пустые шаблоны (`catalog.html`,
`settlement.html`), данные отдаёт JSON-API, к которому ходит сам сайт:

* `/api/categories.php[?parent_id=N]` — разделы: «Области», «Республики»,
  «Края», «Автономная область», «Автономные округа» → субъект РФ → район или
  муниципальный (городской) округ → сельское поселение или город. У раздела —
  `children_count` и `settlements_count`;
* `/api/category-settlements.php?category_id=N` — селения раздела:
  `id`, `name`, `status`, `custom_status` (деревня, село, посёлок…),
  `year_founded`;
* `/api/settlement-details-v2.php?id=N` — карточка: то же плюс `latitude`,
  `longitude`, `description`, путь разделов (`breadcrumb`), рубрики («История
  деревни», «Топоним», «Владельцы», «Админпринадлежность в разные периоды»…),
  галерея и численность населения по годам.

Объём на 24.11.2026 (полный обход). Каркас каталога — вся Россия: 4 842
раздела, 86 субъектов, 2 006 районов и округов, 2 745 поселений. Селения
заведены только в 24 разделах семи субъектов — 360 карточек: Тульская
область — 313 (Венёвский округ — 148, Новомосковск — 119, Кимовский район —
40), Московская — 36 (из них 30 в округе Серебряные Пруды, в 1897 году —
Тульская губерния), Липецкая — 4, по две Рязанская, Орловская и Волгоградская, одна
Ярославская. Счётчики разделов сходятся с обходом, а перебор номеров карточек
1–455 (`--gaps`) не нашёл ни одной карточки вне разделов: номера 1–405 заняты
с пропусками, на несуществующий номер сайт отвечает кодом 500 с `success:
false`. Год основания заполнен у 23 селений (1572–1843), прежние или
параллельные названия — у 180, недействующих — 83, рубрики с текстом — у
десяти, численность по годам и «Админпринадлежность в разные периоды» — у
одной деревни (Кукуй). База растёт: повторный `--fetch --refresh` соберёт
новое.

Селения висят на любом уровне: на сельском поселении, на муниципальном
округе без поселений, изредка на районе. Обход идёт по всему дереву разделов
(`walk_categories`), а селения раздела запрашиваются только там, где
`settlements_count > 0`. Человеческая карточка — `settlement.html?id=N`,
её адрес и идёт в `url`.

Права. В подвале сайта — «© 2025 Малочисленные населенные пункты РФ. Все права
защищены»; выгрузки нет. Собрано с согласия владельцев, полученного
владельцем проекта (сообщено 24.11.2026). Берутся факты — название, прежние
названия, тип, статус, год основания, точка, принадлежность, численность по
годам — и ссылка на карточку. Тексты рубрик и снимки галереи в слой не
выгружаются: в записи отмечено только, какие рубрики заполнены.

Время. Год основания (`year_founded`) — начало записи, `date_precision =
year`. Конец у действующей деревни открыт — до 1960 года, рамки проекта
(`open`), как у храмов из Викиданных; у недействующей конец неизвестен, и
срок тоже тянется до 1960 года: когда деревня опустела, база не говорит,
а статус «недействующий» — о нынешнем дне. Года основания нет у большинства селений — им ставится только
рамка проекта, 1600–1960 (`unknown` не годится: без времени запись не
подбирается совсем), с `date_precision = era`, `date_approx` и
`extra.date_source = "рамка проекта"`. Это наше решение, а не датировка
источника; подбор такую широкую запись понижает.

Место. Точка — из карточки, это само селение, `confidence = ok`; без точки —
`no_coords`. В `place_text` — путь разделов от субъекта до поселения, в
`region` — субъект РФ (нынешний, не губерния), в `district` — район или
округ. Губерния 1897 года по точке — в `extra.province_1897`, если сборщик
нашёл контуры (`frame.Frame`).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..schema import ContextRecord, LayerSpec

SITE = "https://votmoyaderevnya.ru"
API = f"{SITE}/api"
CARD_URL = f"{SITE}/settlement.html?id={{id}}"
CATALOG_URL = f"{SITE}/catalog.html"
LAYER_ID = "settlements_vmd"

# Рамка проекта для селений без года основания и открытый конец.
FRAME = (1600, 1960)
HORIZON = 1960

PAUSE_SEC = 1.0

LICENSE = (
    "© votmoyaderevnya.ru («© 2025 Малочисленные населенные пункты РФ. Все права "
    "защищены»); собрано с согласия владельцев, полученного владельцем проекта "
    "(сообщено 24.11.2026): берутся факты — название, прежние названия, тип, "
    "статус, год основания, точка, принадлежность, численность — и ссылка на "
    "карточку; тексты рубрик и снимки не выгружаются"
)

SETTLEMENTS_VMD = LayerSpec(
    slug=LAYER_ID,
    title="Малочисленные селения России («Вот моя деревня»)",
    group="admin",
    source="«Вот моя деревня» (votmoyaderevnya.ru), база малочисленных населённых "
           "пунктов РФ",
    license=LICENSE,
    description=(
        "Деревни, сёла, посёлки и хутора, в том числе недействующие, с точкой, "
        "прежними названиями, нынешней муниципальной принадлежностью и годом "
        "основания, где он известен. Ещё один источник к слою населённых мест — "
        "о малых и исчезнувших деревнях, которых в GeoNames и Викиданных нет. "
        "На 24.11.2026 база заполнена в семи субъектах, почти вся — Тульская "
        "область: 360 селений, у 23 год основания."
    ),
    url=CATALOG_URL,
    status="harvested",
    expected_rows=360,
)

CONFIDENCE_NO_COORDS = "no_coords"


class VmdError(RuntimeError):
    """API сайта не ответило или ответило не тем."""


# --- сеть и кэш --------------------------------------------------------------


class Client:
    """Одно соединение, пауза не меньше секунды, отступ на 429 и 5xx, кэш.

    Каждый ответ API ложится файлом в `cache` (`categories/<parent>.json`,
    `settlements/<category>.json`, `details/<id>.json`); повторный запуск
    берёт готовое из кэша и продолжает с того места, где оборвался.
    """

    def __init__(self, cache: Path, *, pause: float = PAUSE_SEC, refresh: bool = False,
                 opener: Optional[Callable[[str], bytes]] = None, log=None) -> None:
        self.cache, self.pause, self.refresh = cache, pause, refresh
        self.opener = opener or self._open
        self.log = log or (lambda msg: None)
        self.last = 0.0
        self.requests = 0
        self.hits = 0

    def _open(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()

    def get(self, endpoint: str, key: str, path: str) -> dict:
        """JSON ответа `endpoint` из кэша `path` или из сети."""
        file = self.cache / path
        if file.exists() and not self.refresh:
            self.hits += 1
            return json.loads(file.read_text(encoding="utf-8"))
        url = f"{API}/{endpoint}"
        delay = 5.0
        for attempt in range(6):
            self.last = wait_for_pause(self.last, self.pause)
            try:
                self.requests += 1
                raw = self.opener(url)
                break
            except urllib.error.HTTPError as exc:
                # «Населённый пункт не найден» сайт отдаёт кодом 500 с телом
                # `{"success": false, …}`: это ответ, а не сбой, и повторять
                # его незачем.
                body = _answer(exc)
                if body is not None:
                    raw = body
                    break
                if exc.code not in RETRY_CODES or attempt == 5:
                    raise VmdError(f"{url}: HTTP {exc.code}") from exc
                self.log(f"  {url}: HTTP {exc.code}; повтор через {delay:.0f} с")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == 5:
                    raise VmdError(f"{url}: сеть недоступна ({exc})") from exc
                self.log(f"  {url}: {exc}; повтор через {delay:.0f} с")
            time.sleep(delay)
            delay = min(delay * 2, 120)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise VmdError(f"{url}: ответ не JSON") from exc
        if not isinstance(data, dict) or "success" not in data:
            raise VmdError(f"{url}: в ответе нет поля success")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def categories(self, parent: Optional[int]) -> list[dict]:
        endpoint = "categories.php" + (f"?parent_id={parent}" if parent else "")
        data = self.get(endpoint, str(parent), f"categories/{parent or 'root'}.json")
        return data.get("data") or [] if data.get("success") else []

    def settlements(self, category: int) -> list[dict]:
        data = self.get(f"category-settlements.php?category_id={category}", str(category),
                        f"settlements/{category}.json")
        return data.get("data") or [] if data.get("success") else []

    def details(self, sid: int) -> Optional[dict]:
        data = self.get(f"settlement-details-v2.php?id={sid}", str(sid), f"details/{sid}.json")
        return data.get("data") if data.get("success") else None


def _answer(exc: urllib.error.HTTPError) -> Optional[bytes]:
    """Тело ошибки HTTP, если это ответ API (`{"success": false, …}`), иначе None."""
    try:
        body = exc.read() if exc.fp is not None else b""
        data = json.loads(body.decode("utf-8"))
    except (ValueError, OSError, AttributeError):
        return None
    if isinstance(data, dict) and data.get("success") is False:
        return body
    return None


@dataclass
class Node:
    """Раздел каталога с путём от корня."""

    id: int
    name: str
    path: tuple[str, ...]
    children: int
    settlements: int


def walk_categories(client: Client, parent: Optional[int] = None,
                    path: tuple[str, ...] = ()) -> Iterator[Node]:
    """Все разделы дерева, в глубину; дети запрашиваются, только если они есть."""
    for cat in client.categories(parent):
        node = Node(int(cat["id"]), str(cat.get("name") or "").strip(),
                    path + (str(cat.get("name") or "").strip(),),
                    int(cat.get("children_count") or 0),
                    int(cat.get("settlements_count") or 0))
        yield node
        if node.children > 0:
            yield from walk_categories(client, node.id, node.path)


# --- разбор ------------------------------------------------------------------

_RE_PAREN = re.compile(r"^(?P<name>[^()]*?)\s*\((?P<alt>[^()]*)\)\s*$")
_RE_YEAR = re.compile(r"(?<!\d)(1[0-9]\d{2}|20[0-2]\d)(?!\d)")

# Нынешний субъект РФ — второй шаг пути (первый — «Области», «Края»…);
# район или округ — третий; поселение — четвёртый.
TOP_KINDS = {"Области", "Республики", "Края", "Автономная область", "Автономные округа",
             "Города федерального значения"}


def split_name(raw: str) -> tuple[str, list[str]]:
    """«Каркадиново (Красное, Слободка)» → («Каркадиново», ["Красное", "Слободка"]).

    В скобках — прежние и параллельные названия; «Кукуй (Белколодезь + Великое
    Поле)» — деревня, слившаяся из двух, и обе части тоже идут в список.
    """
    raw = re.sub(r"\s+", " ", (raw or "").strip())
    m = _RE_PAREN.match(raw)
    if not m or not m.group("name"):
        return raw, []
    alts = [a.strip() for a in re.split(r"[,;+]", m.group("alt")) if a.strip()]
    return m.group("name").strip(), alts


def founded_year(value) -> Optional[int]:
    """`year_founded` → год: число, «1678», «1678 г.», «XVII в.» → None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if 800 <= value <= 2030 else None
    m = _RE_YEAR.search(str(value))
    return int(m.group(1)) if m else None


def coord(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v == 0 else v


def admin_path(breadcrumb: Iterable[dict]) -> list[str]:
    """Путь разделов без верхнего «Области»/«Края» — от субъекта до поселения."""
    names = [str(c.get("name") or "").strip() for c in breadcrumb or []]
    names = [n for n in names if n]
    if names and names[0] in TOP_KINDS:
        names = names[1:]
    return names


def _plain(html) -> str:
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = re.sub(r"&nbsp;|&#160;|\xa0", " ", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


ADMIN_RUBRIC = "Админпринадлежность"
_END = r"(?:1\d{3}|20\d{2}|н\.\s*в\.?|наст\w*\.?\s*вр\w*\.?)"
_RE_ADMIN = re.compile(
    r"(?P<a>1\d{3}|20\d{2})\s*[-–—]\s*(?P<b>" + _END + r")\s*[-–—:]\s*(?P<unit>.+?)"
    r"(?=\s*(?:1\d{3}|20\d{2})\s*[-–—]\s*" + _END + r"\s*[-–—:]|$)")


def admin_history(rubrics: Iterable[dict]) -> list[dict]:
    """Рубрика «Админпринадлежность в разные периоды» → [{from, to, unit}].

    Составители пишут её строками «1796-1861 - Российская империя, Тульская
    губерния, Венёвский уезд.»; конец «н. в.» — по сей день (`to` = None).
    Куски, не похожие на этот вид, пропускаются: текст рубрики в слой не
    идёт, берутся только годы и названия единиц.
    """
    out: list[dict] = []
    for r in rubrics or []:
        if not str(r.get("title") or "").startswith(ADMIN_RUBRIC):
            continue
        # «…» и «...» у составителей — пропуск периодов, а не часть единицы.
        for chunk in re.split(r"\.\.\.|…", _plain(r.get("content"))):
            for m in _RE_ADMIN.finditer(chunk.strip()):
                unit = re.sub(r"\s+([,.;])", r"\1", m.group("unit")).strip(" .;")
                if not unit or len(unit) > 300:
                    continue
                b = m.group("b")
                out.append({"from": int(m.group("a")),
                            "to": int(b) if b[0].isdigit() else None,
                            "unit": unit})
    return out


def _rubrics_filled(rubrics: Iterable[dict]) -> list[str]:
    out = []
    for r in rubrics or []:
        if _plain(r.get("content")):
            out.append(str(r.get("title") or "").strip())
    return [t for t in out if t]


def _population(rows: Iterable[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows or []:
        try:
            out[str(int(row.get("year")))] = int(row.get("population"))
        except (TypeError, ValueError):
            continue
    return dict(sorted(out.items()))


def record(details: dict) -> Optional[ContextRecord]:
    """Карточка селения (`data` ответа settlement-details-v2) → запись слоя."""
    s = details.get("settlement") or {}
    sid = s.get("id")
    raw_name = str(s.get("name") or "").strip()
    if sid is None or not raw_name:
        return None
    name, alts = split_name(raw_name)
    kind = (str(s.get("custom_status") or "").strip() or None)
    active = s.get("status") == "active"
    path = admin_path(details.get("breadcrumb"))
    lat, lon = coord(s.get("latitude")), coord(s.get("longitude"))
    if lat is None or lon is None:
        lat = lon = None
    year = founded_year(s.get("year_founded"))
    extra: dict = {"name_raw": raw_name, "status": "действующий" if active
                   else "недействующий"}
    if alts:
        extra["former_names"] = alts
    if s.get("year_founded") not in (None, "") and year is None:
        extra["year_founded_raw"] = str(s.get("year_founded"))
    population = _population(details.get("population"))
    if population:
        extra["population"] = population
    filled = _rubrics_filled(details.get("rubrics"))
    if filled:
        extra["rubrics"] = filled
    if details.get("gallery"):
        extra["photos"] = len(details["gallery"])
    if path:
        extra["admin_path"] = path
    history = admin_history(details.get("rubrics"))
    if history:
        extra["admin_history"] = history
    # Первое упоминание: самый ранний год численности или принадлежности.
    # Когда года основания нет, это нижняя граница, которую карточка знает.
    mentioned = [int(y) for y in population if int(y) <= HORIZON]
    mentioned += [h["from"] for h in history if h["from"] <= HORIZON]

    if year is not None:
        y_to = max(year, HORIZON)
        precision, approx = "open", False
        period = f"основан в {year} г."
        if year > HORIZON:
            y_to, precision = year, "year"
    elif mentioned:
        year = min(mentioned)
        y_to, precision, approx = HORIZON, "open", True
        period = f"год основания не указан; в карточке — с {year} г."
        extra["date_source"] = "первое упоминание в карточке"
    else:
        year, y_to = FRAME
        precision, approx = "era", True
        period = "год основания не указан — рамка проекта"
        extra["date_source"] = "рамка проекта"

    summary_parts = [kind or "селение", "недействующее" if not active else None]
    if alts:
        summary_parts.append("прежние и другие названия: " + ", ".join(alts))
    if population:
        summary_parts.append("население: " + ", ".join(f"{y} — {n}" for y, n in
                                                         population.items()))
    for h in history:
        if h["from"] <= 1897 <= (h["to"] or 9999):
            summary_parts.append(f"в 1897 г.: {h['unit']}")
            break
    desc = _plain(s.get("description"))
    if desc:
        summary_parts.append(desc[:300])
    title = f"{kind} {name}" if kind else name
    return SETTLEMENTS_VMD.new_record(
        title=title,
        category=(kind or "селение") + ("" if active else " (недействующее)"),
        lat=lat, lon=lon,
        place_text=", ".join(path) or None,
        region=path[0] if path else None,
        district=path[1] if len(path) > 1 else None,
        year_from=year, year_to=y_to, date_precision=precision, date_approx=approx,
        period_raw=period,
        summary="; ".join(p for p in summary_parts if p),
        url=CARD_URL.format(id=sid),
        source_id=str(sid),
        confidence="ok" if lat is not None else CONFIDENCE_NO_COORDS,
        extra=extra,
    )


def records(cards: Iterable[dict]) -> list[ContextRecord]:
    out = [r for r in (record(c) for c in cards) if r is not None]
    out.sort(key=lambda r: int(r.source_id))
    return out
