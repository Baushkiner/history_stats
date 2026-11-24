"""Храмы России по реестру «Храмы России» (temples.ru).

Зачем этот слой. Слой `churches` собран из Викиданных, и в нём есть то, что
кто-то туда внёс: около двенадцати тысяч храмов по России, с перекосом к
сохранившимся и к городам. Для генеалогии нужнее обратное — сельская церковь,
снесённая в 1930-х, к которой был приписан приход предка. Реестр «Храмов
России» собирает именно это: церкви, монастыри и часовни, существовавшие к
1917 году на нынешней территории России (и новые тоже), с привязкой к
губернии и уезду 1917 года и к современному адресу, со статусом «утрачен»
и датой постройки последнего здания. 32 998 карточек на 24.11.2026, из них
22 007 разнесены по губерниям и уездам Российской империи.

Как устроен сбор — пакетными выгрузками сайта, а не обходом карточек.
Карточка (`card.php?ID=…`) говорит всё, но карточек тридцать три тысячи, и
при паузе в полторы секунды их обход — полсуток. Те же факты сайт отдаёт
списками:

* поиск `cardsearch.php` по региону и типу постройки (монастырь, церковь,
  часовня) — по 50 строк на страницу: номер карточки, название и иные
  названия, тип (из запроса), статус («действ.», «сохр.», «не сохр.»,
  «строит.», «неизв.» — подпись значка), историческое исповедание (класс
  ссылки: `isp_prav`, `isp_star`, `isp_edin`), современный адрес и дата
  постройки последнего здания;
* KML для Google Earth (`getkml.php?TreeID=<регион>`) — точка каждой
  карточки, у которой она есть, с подписью статуса;
* KML по губернии и уезду 1917 года (`getkml.php?ProvinceID=<единица>`) —
  через них карточка получает губернию и уезд, а дерево единиц берётся со
  страниц `provincies.php`.

Карточки дочитываются отдельной ступенью, с продолжением: в первую очередь
те, у которых нет точки или губернии, — у них карточка добавляет «Адрес на
1917 г.» и краткое описание.

Права. «Перепечатка или воспроизведение материалов любым способом полностью
или по частям допускается только с письменного разрешения и с обязательным
указанием источника» (подвал сайта). Сбор идёт с согласия владельца,
полученного владельцем проекта (сообщено 24.11.2026); снимки на сайте не
выгружаются — только ссылка на карточку.
"""

from __future__ import annotations

import html as _html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..periods import PRECISION_OPEN, parse_period
from ..schema import ContextRecord, LayerSpec

BASE = "http://temples.ru/"
CARD_URL = BASE + "card.php?ID={}"
SEARCH_PATH = "cardsearch.php"
LAYER_ID = "temples_ru"

# Горизонт открытого срока — тот же, что у слоя `churches` из Викиданных
# (`sources.wikidata.OPEN_END_YEAR`): здание стоит с года постройки, а когда
# перестало служить, реестр в списке не говорит.
OPEN_END = 1960
# Карточка, приписанная к губернии и уезду 1917 года, но без даты постройки:
# храм в реестре на 1917 год, начало срока — с 1800 года, как у слоя Викиданных
# для объекта, у которого известен только конец.
REGISTRY_YEAR = 1917
REGISTRY_FROM = 1800

LICENSE = (
    "© «Храмы России» (temples.ru); собрано с согласия владельца, полученного "
    "владельцем проекта (сообщено 24.11.2026). Берутся факты — название, тип, "
    "исповедание, статус, дата постройки, адреса, точка — и ссылка на карточку; "
    "снимки остаются на сайте"
)

TEMPLES_RU = LayerSpec(
    slug=LAYER_ID,
    title="Храмы России (реестр temples.ru)",
    group="faith",
    source="«Храмы России» (temples.ru): реестр храмов, существовавших к 1917 году",
    license=LICENSE,
    description=(
        "Церкви, монастыри и часовни на нынешней территории России с губернией и "
        "уездом 1917 года, датой постройки последнего здания, исповеданием "
        "(православные, единоверческие, старообрядческие) и статусом — около "
        "девяти тысяч из них утрачены. Дополняет слой `churches` из Викиданных "
        "сельскими и снесёнными храмами, к которым были приписаны приходы."
    ),
    url=BASE,
    status="harvested",
    expected_rows=32998,
)

# Тип постройки: значение `TempleType[]` в поиске → категория записи.
TEMPLE_TYPES = {1: "монастырь", 3: "церковь", 5: "часовня"}

# Класс ссылки в списках → историческое исповедание.
CONFESSIONS = {
    "isp_prav": "православная",
    "isp_edin": "единоверческая",
    "isp_star": "старообрядческая",
}

# Подпись значка статуса → слово для описания.
STATUS_WORDS = {
    "действ.": "действующий",
    "сохр.": "сохранился, не действует",
    "не сохр.": "не сохранился",
    "строит.": "строится",
    "неизв.": "судьба неизвестна",
}
LOST = "не сохр."
# Код значка (`ALT`) → статус: у строящихся подпись значка пуста, а код — 5.
STATUS_CODES = {"1": "действ.", "2": "сохр.", "3": "не сохр.", "5": "строит."}

CONFIDENCE_NO_COORDS = "no_coords"


class TemplesError(RuntimeError):
    """Сайт не ответил или ответил не тем."""


def decode(raw: bytes) -> str:
    """Страницы сайта — в windows-1251, KML — в UTF-8 (по объявлению XML)."""
    if raw[:100].lstrip().startswith(b"<?xml") and b"UTF-8" in raw[:100].upper():
        return raw.decode("utf-8", "replace")
    return raw.decode("cp1251", "replace")


def clean(text: Optional[str]) -> Optional[str]:
    """Текст ячейки: без тегов, сущностей и лишних пробелов."""
    if text is None:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


# --- клиент ----------------------------------------------------------------

class Client:
    """Одно соединение, пауза между обращениями, кэш ответов на диске.

    Ответ ложится в файл до разбора: оборванный обход продолжается с места,
    повторный разбор идёт с диска. На 429 и 5xx — отступ с ростом паузы.
    """

    def __init__(self, cache_dir: Path, *, pause: float = 1.5, attempts: int = 6,
                 timeout: int = 120, log: Callable[[str], None] = print,
                 offline: bool = False) -> None:
        self.cache_dir = Path(cache_dir)
        self.pause, self.attempts, self.timeout = pause, attempts, timeout
        self.log, self.offline = log, offline
        self._last = 0.0
        self.requests = 0

    def path(self, name: str) -> Path:
        return self.cache_dir / name

    def get(self, query: str, name: str, *, refresh: bool = False) -> bytes:
        path = self.path(name)
        if path.exists() and not refresh:
            return path.read_bytes()
        if self.offline:
            raise TemplesError(f"{name}: нет в кэше, а сеть отключена")
        data = self.fetch(query)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return data

    def fetch(self, query: str) -> bytes:
        url = BASE + query
        delay = 10.0
        for attempt in range(1, self.attempts + 1):
            self._last = wait_for_pause(self._last, self.pause)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.requests += 1
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES or attempt == self.attempts:
                    raise TemplesError(f"{url}: HTTP {exc.code}") from exc
                why = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.attempts:
                    raise TemplesError(f"{url}: сеть недоступна ({exc})") from exc
                why = str(getattr(exc, "reason", exc))
            self.log(f"  {url}: {why}; повтор через {delay:.0f} с")
            time.sleep(delay)
            delay = min(delay * 2, 300)
        raise TemplesError(f"{url}: не скачалось")  # pragma: no cover


# --- регионы и строки поиска ----------------------------------------------

def search_query(region_id: int, temple_type: int, page: int = 1) -> str:
    return (f"{SEARCH_PATH}?stype=0&TempleType%5B%5D={temple_type}"
            f"&RegionID={region_id}&Count=50&nopage={page}")


_RE_REGION_SELECT = re.compile(r'<select[^>]*name="RegionID"[^>]*>(.*?)</select>', re.S | re.I)
_RE_OPTION = re.compile(r'<option[^>]*value="(\d+)"[^>]*>([^<]*)', re.I)


def parse_regions(page: str) -> list[tuple[int, str]]:
    """Регионы из формы поиска: (номер узла дерева, название субъекта)."""
    m = _RE_REGION_SELECT.search(page)
    if not m:
        raise TemplesError("в форме поиска нет списка регионов: страницу переверстали")
    out = []
    for value, name in _RE_OPTION.findall(m.group(1)):
        if int(value) and clean(name):
            out.append((int(value), clean(name)))
    return out


@dataclass
class Row:
    """Строка выдачи поиска (или строка из карточки — тот же набор фактов)."""

    id: int
    name: str
    status: Optional[str] = None
    icon: Optional[str] = None
    confession: Optional[str] = None
    alt_names: Optional[str] = None
    address: Optional[str] = None
    tree_id: Optional[int] = None
    built: Optional[str] = None
    temple_type: Optional[str] = None
    region_id: Optional[int] = None

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}

    @classmethod
    def from_json(cls, data: dict) -> "Row":
        return cls(**data)


_RE_TOTAL = re.compile(r"Найдено карточек:\s*(\d+)")
_RE_ROW_SPLIT = re.compile(r"<TR\s+BGCOLOR=\"#[0-9A-F]{6}\">", re.I)
_RE_ICON = re.compile(
    r'<IMG\s+SRC="\.\./img/([a-z_]+)\.gif"\s+TITLE="([^"]*)"(?:\s+ALT="(\d*)")?', re.I)
# У ссылки на карточку в атрибуте подсказки лежит `<img …>` в кавычках, и
# «[^>]*» на нём рвётся: класс исповедания ищется рядом с адресом карточки.
_RE_CARD_LINK = re.compile(
    r'(?:CLASS="(isp_[a-z]+)"\s+)?HREF="/?card\.php\?ID=(\d+)"[^>]*>(.*?)</A>', re.I | re.S)
_RE_ALT = re.compile(r'<span[^>]*class="isp_[a-z]+"[^>]*>\s*\((.*?)\)\s*</span>', re.I | re.S)
_RE_ITEMS = re.compile(r'<a\s+class="Items"\s+href="/?tree\.php\?ID=(\d+)">(.*?)</a>', re.I | re.S)
_RE_NOBR = re.compile(r"<NOBR>(.*?)</NOBR>", re.I | re.S)


def parse_search(page: str) -> tuple[Optional[int], list[Row]]:
    """Счётчик выдачи и строки страницы поиска."""
    m = _RE_TOTAL.search(page)
    total = int(m.group(1)) if m else None
    start = page.find("Найдено карточек")
    rows: list[Row] = []
    if start < 0:
        return (0 if "ничего не найдено" in page else None), rows
    body = page[start:]
    end = body.find("</TABLE>")
    body = body[:end] if end > 0 else body
    for chunk in _RE_ROW_SPLIT.split(body)[1:]:
        link = _RE_CARD_LINK.search(chunk)
        if not link:
            continue
        icon = _RE_ICON.search(chunk)
        alt = _RE_ALT.search(chunk)
        items = _RE_ITEMS.search(chunk)
        nobr = _RE_NOBR.findall(chunk)
        rows.append(Row(
            id=int(link.group(2)),
            name=clean(link.group(3)) or f"карточка {link.group(2)}",
            status=icon_status(icon),
            icon=icon.group(1) if icon else None,
            confession=CONFESSIONS.get((link.group(1) or "").lower()),
            alt_names=clean(alt.group(1)) if alt else None,
            address=clean(items.group(2)) if items else None,
            tree_id=int(items.group(1)) if items else None,
            built=clean(nobr[-1]) if nobr else None,
        ))
    return total, rows


def icon_status(icon) -> Optional[str]:
    """Статус из значка: подпись, а у строящихся (подпись пуста) — код."""
    if not icon:
        return None
    return clean(icon.group(2)) or STATUS_CODES.get(icon.group(3) or "")


def page_count(total: Optional[int], per_page: int = 50) -> int:
    return max(1, -(-(total or 0) // per_page))


# --- KML -------------------------------------------------------------------

@dataclass(frozen=True)
class Placemark:
    id: int
    name: str
    status: Optional[str]
    address: Optional[str]
    lat: float
    lon: float
    destroyed: bool


_RE_PLACEMARK = re.compile(r"<Placemark>(.*?)</Placemark>", re.S)
_RE_OBJECT = re.compile(r"<!-- Object #(\d+) -->")
_RE_PM_NAME = re.compile(r"<name>(.*?)</name>", re.S)
_RE_PM_COORDS = re.compile(r"<Point><coordinates>\s*([-0-9.]+),([-0-9.]+)")
_RE_PM_ADDRESS = re.compile(r"<br><br>\s*([^<]*?)\s*<br><br><a\s+href=\"[^\"]*card\.php", re.S)
_RE_PM_CARD = re.compile(r"card\.php\?ID=(\d+)")
_RE_NAME_STATUS = re.compile(r"^(.*?)\s*\(([^()]*\.)\)\s*$")


def parse_kml(text: str) -> list[Placemark]:
    """Точки KML-выгрузки: номер карточки, подпись, статус, адрес, координата."""
    out = []
    for block in _RE_PLACEMARK.findall(text):
        m = _RE_OBJECT.search(block) or _RE_PM_CARD.search(block)
        c = _RE_PM_COORDS.search(block)
        if not m or not c:
            continue
        lon, lat = float(c.group(1)), float(c.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 1e-9 and abs(lon) < 1e-9):
            continue
        name = clean((_RE_PM_NAME.search(block) or [None, ""])[1]) or ""
        status = None
        ns = _RE_NAME_STATUS.match(name)
        if ns:
            name, status = ns.group(1), ns.group(2)
        addr = _RE_PM_ADDRESS.search(block)
        out.append(Placemark(
            id=int(m.group(1)), name=name, status=status,
            address=clean(addr.group(1)) if addr else None,
            lat=lat, lon=lon, destroyed="style_destroyed" in block,
        ))
    return out


# --- дерево губерний и уездов 1917 года ------------------------------------

_RE_BRANCH = re.compile(
    r'class="branch_title"\s+href="provincies\.php\?ProvinceID=(\d+)">([^<]*)</a></td>\s*'
    r'<td\s+class="pr_tree_object">(\d+)', re.I)
_RE_TOTAL_TREE = re.compile(r'Итого</td>\s*<td\s+class="pr_tree_object">(\d+)', re.I)


def parse_province_children(page: str) -> tuple[Optional[int], list[tuple[int, str, int]]]:
    """Итог по единице и её дочерние единицы: (номер, название, объектов)."""
    m = _RE_TOTAL_TREE.search(page)
    total = int(m.group(1)) if m else None
    return total, [(int(i), clean(n) or "", int(c)) for i, n, c in _RE_BRANCH.findall(page)]


# --- карточка --------------------------------------------------------------

_RE_INIT = re.compile(r"Initialization\((\d+),\s*([-0-9.]+),\s*([-0-9.]+)")
_RE_CARD_FIELD = re.compile(
    r'<TD\s+valign="top"\s+CLASS="Bold"\s+WIDTH="30%">([^<]+)</TD><TD[^>]*>(.*?)</TD></TR>',
    re.S | re.I)
_RE_PROVINCE_LINK = re.compile(r'href="provincies\.php\?ProvinceID=(\d+)"[^>]*>([^<]*)<', re.I)

CARD_FIELDS = {
    "Название": "name",
    "Обиходные названия": "common_names",
    "Тип постройки": "temple_type",
    "Дата постройки последнего здания": "built",
    "Дата основания": "founded",
    "Архитектор": "architect",
    "Историческое исповедание": "confession",
    "Статус": "status",
    "Адрес на 1917 г.": "address_1917",
    "Современный адрес": "address",
    "Краткое описание": "description",
    "Посвящение": "dedication",
}


def parse_card(page: str) -> Optional[dict]:
    """Поля учётной карточки; None — карточки нет (удалена или номер пуст)."""
    if "У Ч Е Т Н А Я" not in page:
        return None
    out: dict = {}
    m = _RE_INIT.search(page)
    if m:
        out["id"] = int(m.group(1))
        lat, lon = float(m.group(2)), float(m.group(3))
        if abs(lat) > 1e-9 or abs(lon) > 1e-9:
            out["lat"], out["lon"] = lat, lon
    for label, value in _RE_CARD_FIELD.findall(page):
        key = CARD_FIELDS.get(clean(label) or "")
        if not key:
            continue
        value = re.sub(r"\(\s*<a[^>]*card_hron[^>]*>.*?</a>\s*\)", "", value, flags=re.S | re.I)
        text = clean(value)
        if text and text != "нет данных":
            out[key] = text
    # Цепочка губерния → уезд → место: ссылки на дерево Империи в шапке.
    chain = [(int(i), clean(n)) for i, n in _RE_PROVINCE_LINK.findall(page) if int(i)]
    seen, units = set(), []
    for pid, name in chain:
        if pid not in seen and name:
            seen.add(pid)
            units.append([pid, name])
    if units:
        out["provinces"] = units
    return out


# --- датировка -------------------------------------------------------------

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}
_CYR_ROMAN = str.maketrans({"Х": "X", "І": "I"})


def _roman(token: str) -> int:
    total, prev = 0, 0
    for ch in reversed(token):
        val = _ROMAN[ch]
        total = total - val if val < prev else total + val
        prev = max(prev, val)
    return total


_ABBR = (
    (r"\bок\.", "около "), (r"\bкон\.", "конец "), (r"\bнач\.", "начало "),
    (r"\bсер\.", "середина "), (r"\bпол\.", "половина "), (r"\bчетв\.", "четверть "),
    (r"\bвв\.", "в."),
    # «1-я пол.», «2-я треть», «3-я четв.»: порядковые словами, как их ждёт разбор.
    (r"\b1-я\s+", "первая "), (r"\b2-я\s+", "вторая "),
    (r"\b3-я\s+треть", "последняя треть"), (r"\b3-я\s+", "третья "),
    (r"\b4-я\s+", "последняя "),
)


@dataclass(frozen=True)
class Dating:
    year_from: Optional[int]
    year_to: Optional[int]
    precision: str
    approx: bool
    raw: Optional[str]
    source: Optional[str] = None


def parse_built(text: Optional[str]) -> Optional[tuple[int, int, str, bool]]:
    """«1759», «1720-1740», «кон. XVII - 1-я пол. XVIII вв.», «1743 (1749 ?)».

    Римские века переводятся в арабские, сокращения раскрываются, разбор — в
    `histctx.periods`. Скобочный вариант («1743 (1749 ?)», «1756 (1761 ?)»)
    расширяет интервал, а не заменяет основную дату; «(?)» — приблизительно.
    """
    if not text:
        return None
    raw = text.strip()
    approx = "?" in raw
    alt_years = [int(y) for y in re.findall(r"\(([^()]*)\)", raw)
                 for y in re.findall(r"\b(1\d{3}|20\d{2})\b", y)]
    main = re.sub(r"\([^()]*\)", " ", raw)
    # Век бывает набран кириллицей: «ХХ», «ХIХ» — «Х» и «І» русские.
    main = re.sub(r"(?<![^\W\d_])[IVXLХІ]+(?![^\W\d_])",
                  lambda m: str(_roman(m.group(0).translate(_CYR_ROMAN))), main)
    for pat, rep in _ABBR:
        main = re.sub(pat, rep, main, flags=re.I)
    main = re.sub(r"\s+", " ", main).strip(" ,;")
    period = parse_period(main)
    if period.year_from is None:
        return None
    lo, hi = period.year_from, period.year_to
    if alt_years:
        lo, hi = min([lo] + alt_years), max([hi] + alt_years)
    return lo, hi, period.precision, approx or period.approx


def dating(built: Optional[str], in_1917_registry: bool,
           founded: Optional[str] = None) -> Dating:
    """Срок записи: от основания или постройки последнего здания до горизонта.

    Дата основания есть только в карточке (в выдаче поиска её нет); если она
    раньше постройки последнего здания, срок начинается с неё — храм на этом
    месте стоял и до нынешнего здания.
    """
    parsed = parse_built(built)
    base = parse_built(founded)
    if parsed or base:
        lo, hi, _, approx = parsed or base
        bits = [f"построен {built}"] if parsed else []
        if base and (not parsed or base[0] < lo):
            lo, approx = base[0], approx or base[3]
            bits.insert(0, f"основан {founded}")
        bits.append(f"конец срока — горизонт {OPEN_END} г.")
        return Dating(lo, max(hi, OPEN_END), PRECISION_OPEN, approx, "; ".join(bits), None)
    if in_1917_registry:
        return Dating(REGISTRY_FROM, REGISTRY_YEAR, PRECISION_OPEN, True,
                      (f"дата постройки {'не разобрана: ' + built if built else 'не указана'}; "
                       f"в реестре на {REGISTRY_YEAR} г."),
                      "реестр на 1917 год")
    return Dating(None, None, "unknown", False,
                  f"дата постройки не разобрана: {built}" if built else "дата постройки не указана")


# --- сборка записей --------------------------------------------------------

@dataclass
class Unit:
    """Губерния или уезд 1917 года на сайте."""

    id: int
    name: str
    parent: Optional[int] = None


def broken_units(members: dict[int, list[int]], counts: dict[int, int]) -> set[int]:
    """Единицы, чья KML длиннее их счётчика в дереве, — такой выгрузке не верим.

    24.11.2026 так отвечали две: Романово-Борисоглебский уезд (70 объектов в
    дереве) и Ярославская губерния (1 056) отдавали KML на 10–11 тысяч точек со
    всей России — с пустым именем документа, похоже, всё, что ни к какой
    единице не приписано. Принять их значило бы записать в Ярославскую
    губернию Самару и Королёв.
    """
    return {uid for uid, cards in members.items()
            if uid in counts and len(set(cards)) > counts[uid]}


def province_index(units: Iterable[Unit], members: dict[int, list[int]],
                   counts: Optional[dict[int, int]] = None) -> dict[int, tuple]:
    """Номер карточки → (губерния, уезд) по спискам KML единиц.

    `members` — номер единицы → номера карточек из её KML. Уезд точнее
    губернии, поэтому губернская KML только дополняет то, чего нет в уездных.
    `counts` — счётчики дерева: единицы из `broken_units` пропускаются.
    """
    by_id = {u.id: u for u in units}
    bad = broken_units(members, counts or {})
    members = {uid: cards for uid, cards in members.items() if uid not in bad}
    out: dict[int, tuple] = {}
    for uid, cards in members.items():
        unit = by_id.get(uid)
        if unit is None or unit.parent is None:
            continue
        gub = by_id.get(unit.parent)
        for cid in cards:
            out.setdefault(cid, (gub.name if gub else None, unit.name))
    for uid, cards in members.items():
        unit = by_id.get(uid)
        if unit is None or unit.parent is not None:
            continue
        for cid in cards:
            out.setdefault(cid, (unit.name, None))
    return out


def card_units(card: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """(губерния, уезд) из шапки карточки: первые две ссылки дерева Империи."""
    units = (card or {}).get("provinces") or []
    gub = units[0][1] if units else None
    uezd = units[1][1] if len(units) > 1 else None
    return gub, uezd


def _first_word_type(name: str) -> Optional[str]:
    word = (name.split() or [""])[0].lower()
    if word.startswith("часовн"):
        return "часовня"
    if "монастыр" in name.lower() or word in ("скит", "пустынь"):
        return "монастырь"
    if word in ("церковь", "собор", "храм", "кирха", "костел", "костёл", "молельня"):
        return "церковь"
    return None


def record(row: Row, *, point: Optional[Placemark] = None, units: tuple = (None, None),
           card: Optional[dict] = None) -> ContextRecord:
    """Одна запись слоя из строки поиска, точки KML и (если есть) карточки."""
    card = card or {}
    name = row.name or card.get("name") or f"карточка {row.id}"
    status = row.status or (point.status if point else None) or card.get("status")
    confession = row.confession or (card.get("confession") or "").lower() or None
    kind = row.temple_type or (card.get("temple_type") or "").lower() or _first_word_type(name)
    built = row.built or card.get("built")
    gub, uezd = units
    if not gub:
        gub, uezd = card_units(card)
    address_1917 = card.get("address_1917")
    in_registry = bool(gub or address_1917)
    date = dating(built, in_registry, card.get("founded"))

    lat = lon = None
    if point is not None:
        lat, lon = point.lat, point.lon
    elif "lat" in card:
        lat, lon = card["lat"], card["lon"]

    bits = [kind or "храм"]
    if confession:
        bits.append(confession)
    if status:
        bits.append(STATUS_WORDS.get(status, status))
    bits.append(f"последнее здание — {built}" if built else "дата постройки не указана")
    summary = "; ".join(bits)
    summary = summary[:1].upper() + summary[1:]
    if card.get("description"):
        summary += ". " + card["description"]

    address = row.address or card.get("address") or (point.address if point else None)
    place = "; ".join(x for x in (address_1917, address) if x) or None
    extra = {
        "temples_id": row.id,
        "status": status,
        "lost": status == LOST if status else None,
        "confession": confession,
        "alt_names": row.alt_names or card.get("common_names"),
        "address_1917": address_1917,
        "address_now": address,
        "uezd_1917": uezd,
        "guberniya_1917": gub,
        "dedication": card.get("dedication"),
        "architect": card.get("architect"),
        "founded": card.get("founded"),
        "card_read": bool(card) or None,
    }
    if date.source:
        extra["date_source"] = date.source
    return TEMPLES_RU.new_record(
        title=name,
        category=kind,
        lat=lat, lon=lon,
        place_text=place,
        region=gub,
        district=uezd,
        year_from=date.year_from, year_to=date.year_to,
        date_precision=date.precision,
        date_approx=date.approx,
        period_raw=date.raw,
        summary=summary,
        url=CARD_URL.format(row.id),
        source_id=f"temples.ru:{row.id}",
        confidence="ok" if lat is not None else CONFIDENCE_NO_COORDS,
        extra={k: v for k, v in extra.items() if v not in (None, "")},
    )


def row_from_card(cid: int, card: dict) -> Row:
    """Карточка, которой нет в выдаче поиска (например, вне регионов формы)."""
    return Row(id=cid, name=card.get("name") or f"карточка {cid}",
               status=card.get("status"),
               confession=(card.get("confession") or "").lower() or None,
               alt_names=card.get("common_names"), address=card.get("address"),
               built=card.get("built"),
               temple_type=(card.get("temple_type") or "").lower() or None)


@dataclass
class Collected:
    """Всё, что обход положил в кэш, — в разобранном виде."""

    rows: dict[int, Row] = field(default_factory=dict)
    points: dict[int, Placemark] = field(default_factory=dict)
    units: dict[int, tuple] = field(default_factory=dict)
    cards: dict[int, dict] = field(default_factory=dict)


def records(data: Collected) -> list[ContextRecord]:
    ids = sorted(set(data.rows) | set(data.cards) | set(data.points))
    out = []
    for cid in ids:
        card = data.cards.get(cid)
        row = data.rows.get(cid)
        if row is None:
            if card:
                row = row_from_card(cid, card)
            else:
                pm = data.points[cid]
                row = Row(id=cid, name=pm.name, status=pm.status, address=pm.address)
        out.append(record(row, point=data.points.get(cid),
                          units=data.units.get(cid, (None, None)), card=card))
    return out


# --- связь со слоем `churches` из Викиданных -------------------------------
#
# Слои не сливаются: у Викиданных своя точка, своя датировка (год основания
# или постройки по P571, а не дата последнего здания) и своя лицензия. Но один
# и тот же храм не должен выглядеть двумя разными, поэтому запись получает
# `extra.churches` — uid записи Викиданных, если та стоит рядом и называется
# похоже. Рядом — не дальше `LINK_KM`; похоже — общий корень посвящения:
# «Покрова Пресвятой Богородицы» и «Покровская церковь» сходятся на «покр».
# В городе храмы стоят в сотне метров друг от друга, и одной близости мало.

LINK_KM = 0.3

_GENERIC = {
    "церк", "собо", "храм", "часо", "мона", "пуст", "скит", "свят", "пред", "прес",
    "бого", "госп", "икон", "божи", "мате", "мужс", "женс", "нова", "стар", "дере",
    "каме", "клад", "прих", "кафе", "chur", "sain", "kapl", "kośc", "посе", "село",
    "горо", "орто",
}


def _stems(title: Optional[str]) -> set[str]:
    """Корни посвящения: без места — «(Сосновка)», «в Сосновке», «на погосте…»."""
    text = re.sub(r"\([^()]*\)", " ", (title or "").lower().replace("ё", "е"))
    text = re.split(r"\s(?:в|во|на|при|у|близ|in|w|we)\s", text, maxsplit=1)[0]
    words = re.findall(r"[а-яa-zś]{4,}", text)
    return {w[:4] for w in words} - _GENERIC


def link_churches(recs: Iterable[ContextRecord], churches: Iterable[ContextRecord],
                  radius_km: float = LINK_KM) -> int:
    """Ставит `extra.churches` записям, у которых тот же храм есть в Викиданных."""
    from ..geo import SpatialIndex

    index = SpatialIndex(churches)
    linked = 0
    for rec in recs:
        if not rec.has_point:
            continue
        mine = _stems(rec.title) | _stems(rec.extra.get("alt_names"))
        for other, _km in index.near(rec.lat, rec.lon, radius_km):
            if mine & _stems(other.title):
                rec.extra["churches"] = other.uid
                linked += 1
                break
    return linked
