"""Оккупация и освобождение городов СССР 1941–1945 годов: справочник 1985 года.

Зачем этот слой. Записи «родился в 1942 году в Барвенкове» или «эвакуирован
из Гжатска в октябре 1941-го» объясняются одним вопросом: был ли город в
этот день под оккупацией. Кураторское событие о войне знает, что война шла
на всей территории; справочник «Освобождение городов» отвечает до дня: по
каждому городу — когда он был оккупирован и когда освобождён, а если город
переходил из рук в руки — по каждому разу. Машинно таких дат по местам
больше нигде нет (проход 24.10.2026, `docs/DISCOVERY.md`).

Источник. «Освобождение городов: Справочник по освобождению городов
в период Великой Отечественной войны 1941–1945» / М. Л. Дударенко,
Ю. Г. Перечнев, В. Т. Елисеев и др. — М.: Воениздат, 1985. Полный текст —
на soldat.ru (И. И. Ивлев): раздел СССР лежит шестью страницами
`1-ssr-1.html` … `1-ssr-6.html` в cp1251, весь документ — ещё и архивом
`osv-gorod.zip` (внутри `osv-gorod.doc`, Word 97: без сторонних библиотек он
не читается, и сборщик берёт страницы). Приложение 2 — «Хроника освобождения
городов» по дням — служит сверкой дат освобождения.

Права. Издание 1985 года, права на текст не выяснены. Сайт требует активную
ссылку на использованную страницу — она стоит в `url` каждой записи.
Берутся только факты: название города, даты, указанная справочником область
и одна короткая справка о том, чьими войсками и в ходе какой операции город
освобождён. Перечни соединений и частей с командирами — это изложение
справочника, к тому же с именами людей, — не берутся.

Как устроен текст. Статья начинается названием прописными: «АБРЕНЕ
(ПЫТАЛОВО)» — в скобках нынешнее название, — дальше «Оккупирован 5 июля
1941 г. Освобожден 22 июля 1944 г. войсками …». Город, переходивший из рук
в руки, получает несколько пар подряд (у Барвенкова — три). Кроме пар
встречаются:

* «Частично захвачен» — Воронеж, Сталинград, Новороссийск, Наро-Фоминск:
  противник держал часть города; пара пишется, захват помечается;
* «Освобожден» без даты оккупации — Закарпатье (с 1939 года у Венгрии),
  Мемельский край (с 1939 года у Германии), Южный Сахалин и Курилы (у Японии
  с 1905 года): начала справочник не называет, и запись несёт одну дату;
* «Городом овладели» — города Восточной Пруссии и Петсамо: они не были
  советскими и не оккупировались, а были взяты; запись тоже с одной датой;
* «Восточная часть города освобождена 13 октября 1944 г., западная —
  15 октября» (Рига): конец оккупации — по последней части, обе даты
  в `extra`;
* ошибки распознавания: «Оккупиройан», «Освобождей», «Освобождён»,
  «Оккупирована»/«Освобождена» у станицы, статья «БЕЛЫЙ», склеенная
  с концом статьи «БЕЛЬЦЫ», и «БАР» без выделения названия.

Привязка к месту. Область справочник называет только у тёзок: «ГОРОДОК
(Витебская область)». Остальные города сводятся по названию — нынешнему,
если оно дано, иначе военному — с Викиданными (метка или другое название,
государства-преемники, координата) и с GeoNames из слоя `settlements`; при
нескольких кандидатах решают область из справочника, полоса оккупации,
тип «город» и население. Город, которому пары не нашлось, остаётся в данных
без точки с `confidence="no_coords"`.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..geo import haversine_km
from ..net import USER_AGENT
from ..schema import ContextRecord, LayerSpec

BASE_URL = "https://www.soldat.ru/spravka/freedom/"
INDEX_URL = BASE_URL
PAGES = tuple(f"1-ssr-{i}.html" for i in range(1, 7))
CHRONICLE_PAGE = "application2.html"
ARCHIVE = "osv-gorod.zip"
ENCODING = "cp1251"

CITATION = (
    "Освобождение городов: Справочник по освобождению городов в период Великой "
    "Отечественной войны 1941–1945 / М. Л. Дударенко, Ю. Г. Перечнев, В. Т. Елисеев и др. "
    "М.: Воениздат, 1985. Электронная версия: www.soldat.ru (И. И. Ивлев)"
)

LICENSE = (
    "права на издание 1985 года не выяснены; сайт soldat.ru требует активную ссылку "
    "на использованную страницу — она стоит в каждой записи. Взяты только город, "
    "даты и область; перечни частей и текст справочника не копируются"
)

WORK = "Великая Отечественная война"

OCCUPATION_CITIES = LayerSpec(
    slug="occupation_cities",
    title="Оккупация и освобождение городов 1941–1945 годов",
    group="military",
    source=("«Освобождение городов: Справочник по освобождению городов в период "
            "Великой Отечественной войны 1941–1945» (М.: Воениздат, 1985), "
            "электронная версия на soldat.ru"),
    license=LICENSE,
    url=INDEX_URL,
    status="harvested",
    expected_rows=785,
    description=(
        "По каждому городу СССР из справочника 1985 года — даты до дня: когда "
        "оккупирован и когда освобождён, а если город переходил из рук в руки, — "
        "по каждому разу (у Барвенкова три периода). Города Восточной Пруссии и "
        "Петсамо — с датой взятия, Закарпатье, Мемельский край и Южный Сахалин — "
        "с датой освобождения без начала. Точка — по Викиданным и GeoNames; "
        "не сведённые города остаются без точки. Отвечает на вопрос, был ли город "
        "под оккупацией в день, названный документом о предке."
    ),
)

# Число статей на каждой из шести страниц (с отсылками «см.») — замер
# 24.10.2026. Разошлось — сайт переверстали или поправили текст, и прежде
# чем собирать, надо понять, что изменилось.
EXPECTED_HEADINGS = {
    "1-ssr-1.html": 142, "1-ssr-2.html": 128, "1-ssr-3.html": 143,
    "1-ssr-4.html": 111, "1-ssr-5.html": 183, "1-ssr-6.html": 125,
}

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
MONTHS_BY_NUMBER = {v: k for k, v in MONTHS.items()}

# Война на территории СССР: всё, что вылезло за рамку, — ошибка разбора.
DATE_MIN, DATE_MAX = dt.date(1941, 6, 22), dt.date(1945, 9, 3)

KIND_OCCUPIED = "occupied"
KIND_PARTIAL = "partial"
KIND_LIBERATED = "liberated"
KIND_CAPTURED = "captured"

CATEGORY_OCCUPATION = "оккупация"
CATEGORY_PARTIAL = "частичная оккупация"
CATEGORY_LIBERATION = "освобождение без даты оккупации"
CATEGORY_CAPTURE = "взятие города"
CATEGORY_UNCLOSED = "оккупация без даты освобождения"


class OccupationError(RuntimeError):
    """Страницы не пришли или устроены не так, как ожидает разбор."""


# --- скачивание -------------------------------------------------------------

def page_url(page: str) -> str:
    return BASE_URL + page


def fetch(url: str, *, attempts: int = 6, pause: float = 3.0, timeout: int = 60) -> bytes:
    """Страница soldat.ru. Соединение рвётся примерно на каждом третьем
    запросе (замер 24.10.2026), поэтому повтор — часть сбора, а не исключение."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise OccupationError(f"{url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(pause * (attempt + 1))
    raise OccupationError(f"{url}: не скачалось за {attempts} попыток ({last})")


# --- текст страниц ------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    """Статья справочника: заголовок прописными и текст после него."""

    page: str
    heading: str
    text: str


_HEAD_OPEN, _HEAD_CLOSE = "\x01", "\x02"
_EVENT_START = r"(?:Оккупиро|Освобожд|Частично захвачен|Городом овладели|Восточная часть)"
# Заголовок, который вёрстка не выделила: «БАР. Оккупирован …» в начале
# абзаца или «… орудий-БЕЛЫЙ. Оккупирован …» внутри чужой статьи.
_RE_BARE_HEADING = re.compile(
    r"(?:(?<=^)|(?<=[\s\-.;]))"
    r"([А-ЯЁ]{2,}(?:[ \-][А-ЯЁ]{2,})*(?: ?\([А-ЯЁ \-]+\))?)"
    rf"(?=\.\s+{_EVENT_START})"
)


def page_text(raw: bytes) -> str:
    """HTML страницы — в текст с отметками заголовков статей."""
    doc = raw.decode(ENCODING, errors="replace")
    start = doc.find("<h2>")
    if start < 0:
        raise OccupationError("на странице нет заголовка раздела <h2>")
    doc = doc[start:]
    end = doc.find("Назад")
    if end > 0:
        doc = doc[:end]
    doc = re.sub(r"<script.*?</script>", " ", doc, flags=re.S | re.I)
    doc = re.sub(r'<font size="\+1">(.*?)</font>',
                 lambda m: f"{_HEAD_OPEN}{m.group(1)}{_HEAD_CLOSE}", doc, flags=re.S)
    doc = re.sub(r"<[^>]+>", " ", doc)
    doc = html.unescape(doc).replace("\xa0", " ")
    return re.sub(r"\s+", " ", doc)


def split_entries(text: str, page: str) -> list[Entry]:
    """Текст страницы — в статьи, включая те, чей заголовок не выделен."""
    # Невыделенные заголовки получают ту же отметку, что и выделенные.
    pieces = []
    for chunk in re.split(f"({_HEAD_OPEN}.*?{_HEAD_CLOSE})", text):
        if chunk.startswith(_HEAD_OPEN):
            pieces.append(chunk)
        else:
            pieces.append(_RE_BARE_HEADING.sub(
                lambda m: f"{_HEAD_OPEN}{m.group(1)}{_HEAD_CLOSE}", chunk))
    marked = "".join(pieces)
    out = []
    parts = re.split(f"{_HEAD_OPEN}(.*?){_HEAD_CLOSE}", marked)
    # parts: [до первой статьи, заголовок, текст, заголовок, текст, …]
    for i in range(1, len(parts) - 1, 2):
        heading = re.sub(r"\s+", " ", parts[i]).strip()
        body = parts[i + 1].strip()
        if not heading:
            continue
        out.append(Entry(page=page, heading=heading, text=body))
    return out


def parse_pages(pages: dict[str, bytes]) -> list[Entry]:
    entries = []
    for page in PAGES:
        if page not in pages:
            raise OccupationError(f"нет страницы {page}")
        entries.extend(split_entries(page_text(pages[page]), page))
    return entries


def heading_counts(pages: dict[str, bytes]) -> dict[str, int]:
    """Число статей на странице — для сверки с `EXPECTED_HEADINGS`."""
    return {page: len(split_entries(page_text(raw), page)) for page, raw in pages.items()}


def check_headings(counts: dict[str, int]) -> list[str]:
    problems = []
    for page, expected in EXPECTED_HEADINGS.items():
        got = counts.get(page)
        if got != expected:
            problems.append(f"{page}: ожидалось статей {expected}, разобрано {got}")
    return problems


# --- название и пометки статьи -----------------------------------------------

_RE_SEE = re.compile(r"^[,.]?\s*см\.\s*(.+?)\.?$")
_RE_QUALIFIER_REGION = re.compile(r"\(([А-ЯЁа-яё\- ]+?(?:область|обл\.|АССР|ССР|край))\)")
_RE_PART_OF = re.compile(r"ныне часть (?:г\. )?([А-ЯЁ][а-яё\-]+(?: [А-ЯЁ][а-яё\-]+)?)")
_LOWER_PARTS = {"НА", "НАД", "ПОД", "ИМЕНИ"}


def title_case(name: str) -> str:
    """«РОСТОВ-НА-ДОНУ» → «Ростов-на-Дону», «ВЕЛИКИЕ ЛУКИ» → «Великие Луки»."""
    def word(w: str, first: bool) -> str:
        if not first and w.upper() in _LOWER_PARTS:
            return w.lower()
        return w[:1].upper() + w[1:].lower()

    out = []
    for i, token in enumerate(re.split(r"([ \-])", name.strip())):
        if token in (" ", "-") or not token:
            out.append(token)
            continue
        out.append(word(token, i == 0))
    return "".join(out)


@dataclass
class City:
    """Город статьи: военное и нынешнее название, область, пометки."""

    heading: str
    name: str                       # как назван в статье (на день освобождения)
    modern: Optional[str] = None    # нынешнее название из скобок
    region: Optional[str] = None    # область — только у тёзок
    part_of: Optional[str] = None   # «ныне часть Севастополя»
    note: Optional[str] = None      # «станица», «ныне деревня»

    @property
    def label(self) -> str:
        return f"{self.name} ({self.modern})" if self.modern else self.name

    def search_names(self) -> list[str]:
        """Названия для сведения с Викиданными: нынешнее первым."""
        names = [n for n in (self.modern, self.name) if n]
        if self.name.startswith("имени "):
            names.append(self.name.replace("имени ", "Имени ", 1))
        return list(dict.fromkeys(names))

    def part_of_names(self) -> list[str]:
        """«ныне часть Брянска» — именительный падеж для поиска: Брянск."""
        return nominatives(self.part_of) if self.part_of else []


# Окончания родительного падежа в пометке «ныне часть …» и их именительный:
# Брянска → Брянск, Севастополя → Севастополь, Горловки → Горловка,
# Юрмалы → Юрмала, Снежного → Снежное. Плявиняс и Екабпилс не склоняются.
_GENITIVE = (("ого", "ое"), ("ки", "ка"), ("ы", "а"), ("я", "ь"), ("а", ""))


def nominatives(word: str) -> list[str]:
    out = [word]
    for tail, repl in _GENITIVE:
        if word.endswith(tail):
            out.append(word[: -len(tail)] + repl)
    return list(dict.fromkeys(out))


def parse_city(entry: Entry, head: str) -> City:
    """Заголовок и текст до первой даты — в название и пометки."""
    heading = entry.heading.strip().rstrip(".").strip()
    m = re.match(r"^(.+?)\s*\(([^()]+)\)$", heading)
    name, modern = (m.group(1), m.group(2)) if m else (heading, None)
    city = City(heading=entry.heading, name=title_case(name),
                modern=title_case(modern) if modern else None)
    head = head.strip(" .,")
    if not head:
        return city
    if head.lower().startswith("имени"):
        # «АРТЕМА» + «имени (АРТЕМОВО)» — посёлок имени Артёма.
        city.name = f"имени {city.name}"
        rest = re.search(r"\(([^()]+)\)", head)
        if rest:
            city.modern = title_case(rest.group(1))
        return city
    region = _RE_QUALIFIER_REGION.search(head)
    if region:
        city.region = region.group(1).strip()
    part = _RE_PART_OF.search(head)
    if part:
        city.part_of = part.group(1)
    if not region and not part:
        modern = re.search(r"\(([А-ЯЁ \-]+)\)", head)
        if modern:
            city.modern = title_case(modern.group(1))
        note = re.sub(r"\([^()]*\)", "", head).strip(" .,")
        city.note = note or None
    return city


def see_reference(entry: Entry) -> Optional[str]:
    """«ПЫТАЛОВО, см. АБРЕНЕ» — отсылка к статье под военным названием."""
    m = _RE_SEE.match(entry.text.strip())
    return m.group(1).strip() if m else None


# --- даты ---------------------------------------------------------------------

@dataclass
class Event:
    kind: str
    date: dt.date
    raw: str
    approx: bool = False            # «к 22 октября»: не позднее этого дня
    note: Optional[str] = None


_DATE = r"(?P<by>к\s+)?(?P<d>\d{1,2})\s+(?P<m>[а-я]+)\s+(?P<y>19\d\d)\s*г?\.?"
_RE_EVENT = re.compile(
    r"(?:(?<=^)|(?<=[.;,]\s)|(?<=\.))\s*"
    r"(?P<kw>Оккупиро\w+|Частично захвачен\w*|Освобожд\w+|Городом овладели|"
    r"Восточная часть города освобождена)\s+" + _DATE
)
# «…, западная - 15 октября 1944 г.» — вторая часть города (Рига).
_RE_WEST_PART = re.compile(r",?\s*западная\s*[-–—]\s*" + _DATE)


def _date(m: re.Match) -> Optional[dt.date]:
    month = MONTHS.get(m.group("m"))
    if month is None:
        return None
    try:
        value = dt.date(int(m.group("y")), month, int(m.group("d")))
    except ValueError:
        return None
    return value if DATE_MIN - dt.timedelta(days=1) <= value <= DATE_MAX else None


def _kind(keyword: str) -> str:
    low = keyword.lower()
    if low.startswith("оккупиро"):
        return KIND_OCCUPIED
    if low.startswith("частично"):
        return KIND_PARTIAL
    if low.startswith("городом"):
        return KIND_CAPTURED
    return KIND_LIBERATED


@dataclass
class ParsedEntry:
    city: City
    events: list[Event]
    page: str
    unparsed: list[str] = field(default_factory=list)   # даты, которые не прочитались
    clauses: list[Optional[str]] = field(default_factory=list)
    heading_raw: str = ""            # заголовок как напечатан, до правки опечатки


# «войсками 3 ПрибФ в ходе Псковско-Островской операции» — до двоеточия,
# за которым начинается перечень частей. Перечень с командирами в справку
# не попадает: она обрывается и на «;», и перед скобкой со званием.
_RE_BY_CLAUSE = re.compile(r"^\s*(?:войсками|войска|силами|частями)[^:.;]{0,200}")
_RE_RANK = re.compile(r"\((?:[^()]*\s)?(?:генерал|полковник|подполковник|майор|капитан|"
                      r"лейтенант|старший|адмирал|контр|вице)")


def by_clause(tail: str) -> Optional[str]:
    """Чьими войсками и в ходе какой операции — без перечня частей."""
    m = _RE_BY_CLAUSE.match(tail)
    if not m:
        return None
    clause = m.group(0)
    rank = _RE_RANK.search(clause)
    if rank:
        # Скобка со званием — значит, начался перечень «17 гв. ск (генерал-
        # майор …)»; он отделён от фронта тире.
        clause = re.split(r"\s[-–—]\s", clause[:rank.start()])[0]
    return clause.strip(" ,-–—") or None


def parse_entry(entry: Entry) -> ParsedEntry:
    """Статья — в город и последовательность событий с датами."""
    events: list[Event] = []
    clauses: list[Optional[str]] = []
    unparsed: list[str] = []
    first = None
    for m in _RE_EVENT.finditer(entry.text):
        if first is None:
            first = m.start()
        date = _date(m)
        raw = m.group(0).strip()
        if date is None:
            unparsed.append(raw)
            continue
        note = None
        kind = _kind(m.group("kw"))
        tail_at = m.end()
        if m.group("kw").startswith("Восточная"):
            west = _RE_WEST_PART.match(entry.text, m.end())
            if west and _date(west):
                note = (f"восточная часть освобождена {human_date(date)}, западная — "
                        f"{human_date(_date(west))}")
                raw = entry.text[m.start():west.end()].strip()
                date = _date(west)
                tail_at = west.end()
        events.append(Event(kind=kind, date=date, raw=raw, approx=bool(m.group("by")),
                            note=note))
        clause = None
        if kind in (KIND_LIBERATED, KIND_CAPTURED):
            clause = by_clause(entry.text[tail_at:])
        clauses.append(clause)
    head = entry.text[:first] if first is not None else entry.text
    fixed = HEADING_FIXES.get(entry.heading, entry.heading)
    city = parse_city(Entry(entry.page, fixed, entry.text), head)
    return ParsedEntry(city=city, events=events, page=entry.page, unparsed=unparsed,
                       clauses=clauses, heading_raw=entry.heading)


def human_date(value: dt.date) -> str:
    return f"{value.day} {MONTHS_BY_NUMBER[value.month]} {value.year} г."


# --- периоды ------------------------------------------------------------------

@dataclass
class Period:
    """Период по одному городу: с какого дня по какой."""

    category: str
    start: Optional[Event]
    end: Optional[Event]
    clause: Optional[str] = None   # «войсками 3 ПрибФ в ходе Псковско-Островской операции»
    number: int = 1
    of: int = 1


def periods(parsed: ParsedEntry) -> tuple[list[Period], list[str]]:
    """События статьи — в периоды. Второй элемент — что не сложилось в пару.

    Захват открывает период, освобождение его закрывает. Освобождение без
    открытого периода — город до войны не был советским или оккупирован
    раньше 22 июня 1941 года; захват без освобождения — справочник
    освобождения не называет. Ни то, ни другое не выбрасывается.
    """
    out: list[Period] = []
    problems: list[str] = []
    open_: Optional[Event] = None
    for event, clause in zip(parsed.events, parsed.clauses):
        if event.kind in (KIND_OCCUPIED, KIND_PARTIAL):
            if open_ is not None:
                problems.append(f"два захвата подряд: {open_.raw} / {event.raw}")
                out.append(Period(CATEGORY_UNCLOSED, open_, None))
            open_ = event
            continue
        if event.kind == KIND_CAPTURED:
            out.append(Period(CATEGORY_CAPTURE, None, event, clause))
            continue
        if open_ is None:
            out.append(Period(CATEGORY_LIBERATION, None, event, clause))
            continue
        if event.date < open_.date:
            problems.append(f"освобождение раньше захвата: {open_.raw} / {event.raw}")
        category = CATEGORY_PARTIAL if open_.kind == KIND_PARTIAL else CATEGORY_OCCUPATION
        out.append(Period(category, open_, event, clause))
        open_ = None
    if open_ is not None:
        out.append(Period(CATEGORY_UNCLOSED, open_, None))
    occupations = [p for p in out if p.category in (CATEGORY_OCCUPATION, CATEGORY_PARTIAL)]
    for i, p in enumerate(occupations, 1):
        p.number, p.of = i, len(occupations)
    return out, problems


# --- хроника освобождения (приложение 2) ----------------------------------

_RE_CHRONICLE_YEAR = re.compile(r"(19\d\d) год")
_RE_CHRONICLE_DAY = re.compile(r"(\d{1,2}) ([а-я]+) [-–—] ")


def chronicle(raw: bytes) -> list[tuple[dt.date, str]]:
    """Приложение 2: «13 июля - Жлобин. Рогачев.» — пары (дата, название).

    Хроника — второй, независимый от статей список дат освобождения внутри
    того же справочника: по нему сверяется разбор статей.
    """
    text = page_text(raw).replace(_HEAD_OPEN, " ").replace(_HEAD_CLOSE, " ")
    out = []
    years = list(_RE_CHRONICLE_YEAR.finditer(text))
    for i, ym in enumerate(years):
        year = int(ym.group(1))
        chunk = text[ym.end(): years[i + 1].start() if i + 1 < len(years) else len(text)]
        days = list(_RE_CHRONICLE_DAY.finditer(chunk))
        for j, dm in enumerate(days):
            month = MONTHS.get(dm.group(2))
            if not month:
                continue
            try:
                day = dt.date(year, month, int(dm.group(1)))
            except ValueError:
                continue
            names = chunk[dm.end(): days[j + 1].start() if j + 1 < len(days) else len(chunk)]
            for name in re.split(r"[.,;]\s*", names):
                name = re.sub(r"\((?:вторично|третий раз|в третий раз)\)", "", name).strip()
                if name and name[0].isupper() and len(name) < 60:
                    out.append((day, name))
    return out


def name_key(name: Optional[str]) -> str:
    """Ключ сравнения названий: без регистра, «ё», скобок и дефисов."""
    if not name:
        return ""
    s = name.lower().replace("ё", "е")
    s = re.sub(r"\([^()]*\)", " ", s)
    s = re.sub(r"[^а-яa-z0-9]+", " ", s)
    return s.strip()


def check_chronicle(parsed: Iterable[ParsedEntry], chron: list[tuple[dt.date, str]]) -> dict:
    """Даты освобождения статей против хроники: сколько сошлось, что нет."""
    liberations: dict[str, set] = {}
    for p in parsed:
        dates = {e.date for e in p.events if e.kind in (KIND_LIBERATED, KIND_CAPTURED)}
        for n in (p.city.name, p.city.modern):
            if n:
                liberations.setdefault(name_key(n), set()).update(dates)
    found = agree = 0
    differ, missing = [], []
    for day, name in chron:
        keys = [name_key(name)] + [name_key(x) for x in re.findall(r"\(([^()]+)\)", name)]
        hit = next((liberations[k] for k in keys if k in liberations), None)
        if hit is None:
            missing.append(f"{human_date(day)} {name}")
            continue
        found += 1
        if day in hit:
            agree += 1
        else:
            differ.append(f"{name}: хроника {human_date(day)}, статья "
                          + ", ".join(human_date(d) for d in sorted(hit)))
    return {"chronicle": len(chron), "found": found, "agree": agree,
            "differ": differ, "missing": missing}


# --- привязка к точке ---------------------------------------------------------

# Где города справочника вообще могли быть: западнее линии наибольшего
# продвижения противника и отдельно Южный Сахалин с Курилами. Линия задана
# ступенями по широте — севернее 57,5° не восточнее Тихвина и Медвежьегорска,
# до 52° не восточнее Скопина, южнее — до Сталинграда и Элисты. Тёзка за её
# пределами — Галич Костромской области вместо Галича Ивано-Франковской,
# Киров Кировской вместо Кирова Калужской — не кандидат.
WEST_ZONE = ((57.5, 70.5, 19.5, 36.5), (52.0, 57.5, 19.5, 40.0), (41.0, 52.0, 19.5, 47.0))
EAST_ZONE = ((43.0, 51.5, 141.0, 157.0),)    # Южный Сахалин и Курилы

# Викиданные: государства-преемники, где лежат города справочника.
WD_COUNTRIES = {
    "Q159": "Россия", "Q212": "Украина", "Q184": "Белоруссия", "Q217": "Молдавия",
    "Q37": "Литва", "Q211": "Латвия", "Q191": "Эстония",
}

# Прежние названия областей в пометках справочника — к нынешним, по которым
# ищется предок в Викиданных.
REGION_NOW = {"Ворошиловградская область": "Луганская область"}

# Города, взятые в Восточной Пруссии, ищутся сперва в Калининградской области:
# нынешние названия там сплошь русские и повторяют чужие (Приморск, Нестеров,
# Калиновка, Краснознаменск — есть и в Ленинградской, Львовской, Винницкой,
# Московской областях).
CAPTURE_REGIONS = ("Калининградская область", "Мурманская область", "Литва")

# Опечатки распознавания в заголовках: исправленное название идёт в запись,
# заголовок как напечатан — в `extra`.
HEADING_FIXES = {"СЛАВЯНОК": "СЛАВЯНСК"}

# Выбор вручную — там, где не помогли ни область, ни полоса, ни население.
# Ключ — заголовок статьи как напечатан, значение — Q-номер Викиданных или
# `geonames:<id>`. Причина у каждого — фронт и операция из самой статьи или
# изъян метки в Викиданных.
OVERRIDES: dict[str, str] = {
    # Волховский фронт, Новгородско-Лужская операция — Любань Ленинградской
    # области, а не Минской, которая больше.
    "ЛЮБАНЬ": "Q15279",
    # Ленинградский фронт, Выборгская операция — Приморск Ленинградской
    # области, а не Запорожской.
    "КОЙВИСТО (ПРИМОРСК)": "Q15307",
    # Ленинградский фронт, Красносельско-Ропшинская операция: Слуцк — это
    # Павловск под Ленинградом (так он назывался в 1918–1944 годах), а не Слуцк
    # Минской области. В Викиданных Павловск заведён муниципальным округом.
    "СЛУЦК (ПАВЛОВСК)": "Q177888",
    # Юго-Западный фронт, Донбасская операция — Новомосковск
    # Днепропетровской области; тульский Новомосковск — это Сталиногорск,
    # у него своя статья. Метка украинского города в Викиданных — «Самар».
    "НОВОМОСКОВСК": "Q640680",
    # Волховский фронт, Новгородско-Лужская операция — Великий Новгород.
    # Метка «Новгород» в GeoNames стоит у Новгорода-Северского.
    "НОВГОРОД": "geonames:519336",
    # Метка Кингисеппа в Викиданных — «Кингисеппское городское поселение»;
    # в GeoNames город записан с опечаткой «Кингисеп».
    "КИНГИСЕПП": "geonames:548602",
    # Юго-Западный фронт, Донбасская операция — Артёмовск Донецкой области
    # (ныне Бахмут, в Викиданных «Артёмовск» — другое название), а не
    # Артёмовск Луганской, у которого это метка.
    "АРТЕМОВСК": "Q706857",
    # Юго-Западный фронт, Ворошиловградская операция — Красноармейск Донецкой
    # области (ныне Покровск), а не подмосковный и не саратовский.
    "КРАСНОАРМЕЙСКОЕ (КРАСНОАРМЕЙСК)": "Q1000446",
    # Ворошиловск, в 1985 году Коммунарск (ныне Алчевск) Луганской области;
    # Ворошиловском назывался и Ставрополь — у него своя статья.
    "ВОРОШИЛОВСК (КОММУНАРСК)": "Q161144",
    # Красноград в 2024 году переименован в Берестин; прежнего названия
    # по-русски ни у Викиданных, ни у GeoNames нет.
    "КРАСНОГРАД": "geonames:704388",
}

SETTLEMENT_WORDS = ("город", "посёлок", "поселок", "село", "деревня", "станица", "местечко",
                    "населённый пункт", "населенный пункт", "хутор", "агрогородок",
                    "курорт", "район города", "микрорайон", "столица", "мегаполис")


def in_zone(lat: float, lon: float, zone=WEST_ZONE) -> bool:
    return any(a <= lat <= b and c <= lon <= d for a, b, c, d in zone)


def name_variants(name: str) -> list[str]:
    """Написания для точного сравнения с метками: как есть и с «ё».

    Справочник печатает «е» там, где в метке Викиданных «ё» (Артемовск —
    Артёмовск): каждое «е» по очереди заменяется на «ё».
    """
    out = [name]
    for i, ch in enumerate(name):
        if ch in "еЕ":
            out.append(name[:i] + ("ё" if ch == "е" else "Ё") + name[i + 1:])
    return list(dict.fromkeys(out))


def wikidata_query(names: Iterable[str]) -> str:
    """Запрос кандидатов по точному названию: метка (main=1) или другое (main=0).

    Различать их обязательно: «Новороссийск» — другое название Днепра
    1796–1802 годов, и без этого признака Днепр обходит сам Новороссийск.
    """
    values = " ".join(f'"{n}"@ru' for n in names if '"' not in n)
    countries = " ".join(f"wd:{q}" for q in WD_COUNTRIES)
    return f"""SELECT ?name ?main ?item ?coord ?typeLabel ?pop ?ancLabel WHERE {{
  VALUES ?name {{ {values} }}
  {{ ?item rdfs:label ?name }} UNION {{ ?item skos:altLabel ?name }}
  ?item wdt:P17 ?country .
  VALUES ?country {{ {countries} }}
  ?item wdt:P625 ?coord .
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel .
             FILTER(LANG(?typeLabel) = "ru") }}
  OPTIONAL {{ ?item wdt:P1082 ?pop . }}
  OPTIONAL {{ ?item wdt:P131+ ?anc . ?anc rdfs:label ?ancLabel .
             FILTER(LANG(?ancLabel) = "ru") }}
  BIND(IF(EXISTS {{ ?item rdfs:label ?name }}, 1, 0) AS ?main)
}}"""


@dataclass
class Candidate:
    """Кандидат в точку города: объект Викиданных или место GeoNames."""

    source: str                 # «wikidata» | «geonames»
    ident: str                  # Q-номер или geonameid
    title: str
    lat: float
    lon: float
    main: bool = True           # совпала метка, а не другое название
    types: set = field(default_factory=set)
    population: int = 0
    ancestors: set = field(default_factory=set)

    @property
    def is_settlement(self) -> bool:
        if self.source == "geonames" or not self.types:
            return self.source == "geonames"
        return any(any(w in t for w in SETTLEMENT_WORDS) for t in self.types)

    @property
    def is_town(self) -> bool:
        if self.source == "geonames":
            return self.population >= 5000
        return any(_RE_TOWN_TYPE.search(t) for t in self.types)

    @property
    def coord_source(self) -> str:
        return f"{'Викиданные' if self.source == 'wikidata' else 'GeoNames'} {self.ident}"


_RE_POINT = re.compile(r"Point\(([-\d.eE]+)\s+([-\d.eE]+)\)")
# Тип «город» в любой обёртке («город областного значения Украины», «большой
# город», «столица»), но не «городской округ» и не «городское поселение».
_RE_TOWN_TYPE = re.compile(r"(?:^|\s)город(?:\s|$)|^посёлок городского типа|^местечко|"
                           r"столица|мегаполис")


def candidates_from_rows(rows: Iterable[dict]) -> dict[str, list[Candidate]]:
    """Строки SPARQL — в кандидатов по искомому названию (ключ `name_key`)."""
    by_item: dict[tuple[str, str], Candidate] = {}
    for row in rows:
        name = row.get("name", {}).get("value")
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        point = _RE_POINT.match(row.get("coord", {}).get("value", ""))
        if not name or not qid.startswith("Q") or not point:
            continue
        main = row.get("main", {}).get("value") == "1"
        key = (name_key(name), qid)
        cand = by_item.get(key)
        if cand is None:
            cand = Candidate(source="wikidata", ident=qid, title=name, main=main,
                             lon=float(point.group(1)), lat=float(point.group(2)))
            by_item[key] = cand
        cand.main = cand.main or main
        t = row.get("typeLabel", {}).get("value")
        if t:
            cand.types.add(t.lower())
        anc = row.get("ancLabel", {}).get("value")
        if anc:
            cand.ancestors.add(anc)
        pop = row.get("pop", {}).get("value")
        if pop:
            try:
                cand.population = max(cand.population, int(float(pop)))
            except ValueError:
                pass
    out: dict[str, list[Candidate]] = {}
    for (key, _), cand in by_item.items():
        out.setdefault(key, []).append(cand)
    return out


def geonames_index(features: Iterable[dict], variants: Optional[dict] = None) -> dict:
    """Слой `settlements` (GeoNames) — указатель по названию и написаниям.

    `variants` — `items` из `data/out/name_variants.json`: там у места есть
    и русское написание, когда заглавным GeoNames поставил украинское.
    """
    out: dict[str, list[Candidate]] = {}
    variants = variants or {}
    for feat in features:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        gid = str(props.get("source_id") or "")
        if len(coords) < 2 or not gid:
            continue
        extra = props.get("extra") or {}
        title = props.get("title") or ""
        base = dict(source="geonames", ident=gid, title=title,
                    lat=float(coords[1]), lon=float(coords[0]),
                    population=int(extra.get("population_modern") or 0))

        # Заглавное название — как метка Викиданных; написания из указателя —
        # как другие названия: среди них бывают прежние («Новороссийск» у Днепра).
        keys = {name_key(title): True}
        for n in (variants.get(gid) or {}).get("names") or []:
            keys.setdefault(name_key(n), False)
        for k, main in keys.items():
            if k:
                out.setdefault(k, []).append(Candidate(main=main, **base))
    return out


@dataclass
class Placement:
    """Итог сведения города с точкой."""

    candidate: Optional[Candidate]
    how: str                      # как найдена: по какому названию и источнику
    rivals: list = field(default_factory=list)   # другие города-тёзки в полосе
    part_of: bool = False         # точка — город, частью которого стал этот
    check_km: Optional[float] = None   # расстояние до точки второго источника


def lookup_names(cities: Iterable[City]) -> list[str]:
    """Все написания, по которым города ищутся в Викиданных."""
    out = []
    for city in cities:
        for name in city.search_names() + city.part_of_names():
            out.extend(name_variants(name))
    return sorted(set(out))


def wikidata_candidates(client, names: list[str], *, batch: int = 100) -> dict:
    """Кандидаты из Викиданных по всем написаниям, пачками по `batch`."""
    rows = []
    for i in range(0, len(names), batch):
        rows.extend(client.query(wikidata_query(names[i:i + batch])))
    return candidates_from_rows(rows)


def region_ok(cand: Candidate, region: Optional[str]) -> bool:
    """Лежит ли кандидат в названной области (по цепочке P131 Викиданных)."""
    if not region:
        return True
    want = REGION_NOW.get(region, region)
    if " " not in want:
        return any(want.lower() == a.lower() for a in cand.ancestors)
    stem = want.split()[0][:-2].lower()      # «Витебская» → «витебск»
    return any(stem in a.lower() and "област" in a.lower() for a in cand.ancestors)


def _rank(c: Candidate) -> tuple:
    # Город раньше села, метка раньше другого названия, Викиданные раньше
    # GeoNames (у них есть цепочка областей, а заглавное название GeoNames —
    # первое попавшееся кириллическое: у Науйойи-Вильни это «Вилейка»),
    # больший раньше меньшего.
    return (not c.is_town, not c.main, c.source != "wikidata", -c.population)


def gather(names: Iterable[str], *indexes: dict) -> list[Candidate]:
    """Кандидаты по всем названиям из всех указателей, без повторов."""
    out, seen = [], set()
    for name in names:
        for index in indexes:
            for cand in index.get(name_key(name), []):
                key = (cand.source, cand.ident, cand.main)
                if key not in seen:
                    seen.add(key)
                    out.append(cand)
    return out


def choose(cands: list[Candidate], *, region: Optional[str] = None, zone=WEST_ZONE,
           near: Optional[tuple] = None) -> tuple[Optional[Candidate], list]:
    """Лучший кандидат и тёзки, которых он обошёл.

    Отбор: населённый пункт в полосе, в названной области, рядом с городом,
    частью которого стал (`near`); порядок — `_rank`. Тёзка — другой город
    дальше 15 км от выбранного и от уже записанных тёзок: один город часто
    заведён дважды (город и городской округ, Викиданные и GeoNames) — это
    не тёзки.
    """
    pool = [c for c in cands if c.is_settlement and in_zone(c.lat, c.lon, zone)]
    pool = [c for c in pool if region_ok(c, region)]
    if near:
        pool = [c for c in pool if haversine_km(near[0], near[1], c.lat, c.lon) <= 25]
    if not pool:
        return None, []
    pool.sort(key=_rank)
    best = pool[0]
    if best.source == "geonames":
        # То же место в Викиданных — лучше: у него есть цепочка областей.
        same = [c for c in pool if c.source == "wikidata"
                and haversine_km(best.lat, best.lon, c.lat, c.lon) <= 15]
        if same:
            best = same[0]
    rivals: list[Candidate] = []
    for c in pool[1:]:
        if not (c.is_town and best.is_town and c.main and best.main):
            continue
        if all(haversine_km(x.lat, x.lon, c.lat, c.lon) > 15 for x in [best, *rivals]):
            rivals.append(c)
    return best, rivals


def zone_of(parsed: "ParsedEntry") -> tuple:
    """Южный Сахалин и Курилы освобождены в августе 1945 года, остальное — раньше."""
    dates = [e.date for e in parsed.events]
    return EAST_ZONE if dates and min(dates) >= dt.date(1945, 8, 9) else WEST_ZONE


def _source_word(cand: Candidate) -> str:
    return "Викиданные" if cand.source == "wikidata" else "GeoNames"


def place_city(parsed: "ParsedEntry", wd: dict, gn: dict,
               overrides: Optional[dict] = None) -> Placement:
    """Точка города по Викиданным и GeoNames вместе; часть города — рядом с ним.

    Порядок попыток: область из справочника (или, у взятых городов, сперва
    Калининградская область); если у тёзок с областью не нашлось никого —
    GeoNames без проверки области (цепочки областей у него нет); у города,
    ставшего частью другого, — кандидаты в 25 км от того, а если и их нет,
    точка того города с пометкой `place_level`.
    """
    city = parsed.city
    overrides = OVERRIDES if overrides is None else overrides
    names = city.search_names()
    forced = overrides.get(parsed.heading_raw or city.heading)
    if forced:
        source, _, ident = forced.rpartition(":")
        index = wd if not source else gn
        # Сперва среди кандидатов по названиям статьи, потом по всему указателю.
        everywhere = (c for cands in index.values() for c in cands)
        for cand in [*gather(names, index), *everywhere]:
            if cand.ident == ident:
                return Placement(cand, f"{_source_word(cand)}, «{cand.title}», выбор вручную")
        return Placement(None, f"выбор вручную ({forced}) не найден среди кандидатов")
    zone = zone_of(parsed)
    near = whole = None
    if city.part_of:
        found, _ = choose(gather(city.part_of_names(), wd, gn), zone=zone)
        if found:
            near, whole = (found.lat, found.lon), found
    attempts: list = []
    if city.region:
        attempts += [(city.region, (wd,)), (None, (gn,))]
    elif parsed.events and all(e.kind == KIND_CAPTURED for e in parsed.events):
        attempts += [(r, (wd, gn)) for r in CAPTURE_REGIONS] + [(None, (wd, gn))]
    else:
        attempts.append((None, (wd, gn)))
    for region, indexes in attempts:
        best, rivals = choose(gather(names, *indexes), region=region, zone=zone, near=near)
        if best:
            how = f"{_source_word(best)}, «{best.title}»"
            if region and region != city.region:
                how += f", {region}"
            if city.region and region is None:
                how += ", область не проверена"
            return Placement(best, how, rivals)
    if whole:
        return Placement(whole, f"{_source_word(whole)}, город «{whole.title}», частью "
                                "которого стал", part_of=True)
    return Placement(None, "не сведён: " + ", ".join(names))


def cross_check(place: Placement, gn: dict, city: City) -> None:
    """Расстояние от точки Викиданных до ближайшего тёзки GeoNames в полосе."""
    if not place.candidate or place.candidate.source != "wikidata":
        return
    best = None
    for name in city.search_names():
        for cand in gn.get(name_key(name), []):
            if not (in_zone(cand.lat, cand.lon) or in_zone(cand.lat, cand.lon, EAST_ZONE)):
                continue
            d = haversine_km(place.candidate.lat, place.candidate.lon, cand.lat, cand.lon)
            best = d if best is None else min(best, d)
    place.check_km = None if best is None else round(best, 1)


# --- записи -------------------------------------------------------------------

def _period_raw(period: Period) -> str:
    parts = [e.raw for e in (period.start, period.end) if e]
    return " ".join(p if p.endswith(".") else p + "." for p in parts)


_ORDINALS = {1: "первый", 2: "второй", 3: "третий"}
_OF = {2: "двух", 3: "трёх"}


def _title(city: City, period: Period) -> str:
    s, e = period.start, period.end
    if period.category in (CATEGORY_OCCUPATION, CATEGORY_PARTIAL):
        word = "частичная оккупация" if period.category == CATEGORY_PARTIAL else "оккупация"
        return f"{city.label}: {word} {human_date(s.date)} — {human_date(e.date)}"
    if period.category == CATEGORY_CAPTURE:
        return f"{city.label}: взят {human_date(e.date)}"
    if period.category == CATEGORY_LIBERATION:
        return f"{city.label}: освобождён {human_date(e.date)}"
    return f"{city.label}: оккупирован {human_date(s.date)}"


def _summary(city: City, period: Period) -> str:
    s, e = period.start, period.end
    bits = []
    if period.category == CATEGORY_OCCUPATION:
        bits.append(f"Оккупирован {human_date(s.date)}, освобождён {human_date(e.date)}: "
                    f"{(e.date - s.date).days} дн.")
    elif period.category == CATEGORY_PARTIAL:
        approx = "не позднее " if s.approx else ""
        bits.append(f"Противник захватил часть города {approx}{human_date(s.date)}, город "
                    f"освобождён {human_date(e.date)}.")
    elif period.category == CATEGORY_CAPTURE:
        bits.append(f"Город противника, взят советскими войсками {human_date(e.date)}; "
                    "оккупации в справочнике нет.")
    elif period.category == CATEGORY_LIBERATION:
        bits.append(f"Освобождён {human_date(e.date)}; дату перехода под власть противника "
                    "справочник не называет.")
    else:
        bits.append(f"Оккупирован {human_date(s.date)}; даты освобождения в статье нет.")
    if period.of > 1:
        bits.append(f"{_ORDINALS.get(period.number, str(period.number)).capitalize()} из "
                    f"{_OF.get(period.of, str(period.of))} периодов оккупации по справочнику.")
    if e and e.note:
        bits.append(e.note[:1].upper() + e.note[1:] + ".")
    if city.part_of:
        bits.append(f"Ныне часть г. {city.part_of}.")
    if city.note:
        bits.append(city.note[:1].upper() + city.note[1:] + ".")
    if city.region:
        bits.append(f"{city.region} (по справочнику).")
    return " ".join(bits)


def modern_region(cand: Optional[Candidate]) -> Optional[str]:
    """Область кандидата по цепочке P131 Викиданных — если она одна.

    В цепочке лежат и прежние подчинения: у тульского Новомосковска там
    Московская и Тульская области. Две области — не выбирается ни одна.
    """
    if not cand:
        return None
    for tail in (" область", " край"):
        hits = {a for a in cand.ancestors if a.endswith(tail)}
        if hits:
            return hits.pop() if len(hits) == 1 else None
    return None


def period_records(parsed: ParsedEntry, place: Placement,
                   spec: LayerSpec = OCCUPATION_CITIES) -> list[ContextRecord]:
    city = parsed.city
    plist, problems = periods(parsed)
    out = []
    url = page_url(parsed.page)
    cand = place.candidate
    for i, period in enumerate(plist):
        s, e = period.start, period.end
        first = s.date if s else e.date
        last = e.date if e else s.date
        extra = {
            "name_wartime": city.name,
            "occupied": s.date.isoformat() if s else None,
            "liberated": e.date.isoformat() if e else None,
            "days": (e.date - s.date).days if s and e else None,
            "period_number": period.number if period.of > 1 else None,
            "periods_total": period.of if period.of > 1 else None,
            "occupied_by_date": True if s and s.approx else None,
            "liberated_by": period.clause,
            "heading": parsed.heading_raw if parsed.heading_raw != city.heading else None,
            "place_match": place.how,
            "place_rivals": [c.coord_source for c in place.rivals] or None,
            "coord_source": cand.coord_source if cand else None,
            "coord_check_km": place.check_km,
            "problems": problems or None,
        }
        extra = {k: v for k, v in extra.items() if v is not None}
        out.append(spec.new_record(
            title=_title(city, period),
            category=period.category,
            lat=round(cand.lat, 6) if cand else None,
            lon=round(cand.lon, 6) if cand else None,
            place_text=city.label,
            region=(REGION_NOW.get(city.region, city.region) if city.region
                    else modern_region(cand)),
            year_from=first.year, year_to=last.year,
            date_precision="day",
            date_approx=bool(s and s.approx),
            period_raw=_period_raw(period),
            work=WORK,
            summary=_summary(city, period),
            url=url,
            source_id=f"{parsed.page}:{city.heading}:{i + 1}",
            confidence=("no_coords" if not cand else
                        "place_level" if place.part_of else "ok"),
            extra=extra,
        ))
    return out


# --- сверка с набором Grunewald (CC0) -----------------------------------------

GRUNEWALD_DOI = "doi:10.7910/DVN/MCLEXN"
GRUNEWALD_URL = "https://doi.org/10.7910/DVN/MCLEXN"
GRUNEWALD_FILE_ID = 3909010
GRUNEWALD_FILE_URL = (f"https://dataverse.harvard.edu/api/access/datafile/"
                      f"{GRUNEWALD_FILE_ID}?format=original")
GRUNEWALD_SIZE = 29558

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


def latin_key(name: Optional[str]) -> str:
    """Ключ сравнения латинских написаний: «Белёв» и «Belev», «Ромны» и «Romny».

    Русское название переводится в латиницу, оба написания упрощаются
    одинаково: kh → h, й/ы/j → i, удвоенные буквы — одна.
    """
    if not name:
        return ""
    s = name.lower().translate(_TRANSLIT)
    s = re.sub(r"[^a-z]", "", s)
    s = s.replace("kh", "h").replace("y", "i").replace("j", "i").replace("w", "v")
    return re.sub(r"(.)\1+", r"\1", s)


# Написания набора, которые ключ не сводит: опечатки, немецкая и польская
# запись, другое название. Орджоникидзе набора — Владикавказ, не Енакиево:
# он не оккупировался, и с одноимённой статьёй справочника его сводить нельзя.
GRUNEWALD_ALIASES = {
    "Konigsberg": "Кёнигсберг", "Karsnoe Selo": "Красное Село",
    "Krasnogvardiesk": "Красногвардейск", "Khvin": "Тихвин", "Jelez": "Елец",
    "Jarzewo": "Ярцево", "Dvinsk": "Даугавпилс", "Baranowicze": "Барановичи",
    "Tilsit": "Тильзит", "Bogorodisk": "Богородицк", "Yelets": "Елец",
    "Kirovo": "Кировоград", "Nikolayev": "Николаев|Николаевская область",
    "Kingisepp": "Кингисепп|Ленинградская область",
    "Zithomir": "Житомир", "Mogliev": "Могилев", "Polots": "Полоцк",
    "Tarnpol": "Тарнополь", "Mozdor": "Моздок", "Yefrimov": "Ефремов",
    "Sukhinchi": "Сухиничи", "Mtensk": "Мценск", "Naro Fominsk": "Наро-Фоминск",
    "Rostov": "Ростов-на-Дону", "Kotelnikov": "Котельниковский",
    "Kotelnikovo": "Котельниковский", "Kotelnikovski": "Котельниковский",
    "Stalinogorsk": "Сталиногорск", "Solnechogorsk": "Солнечногорск",
    "Ordzhonikidze": None,
}


def grunewald_rows(path) -> list[dict]:
    """Листы набора: место, дата, пояснение. Лист метаданных и источников пропущен."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows or not rows[0] or rows[0][:3] != ("ID", "Place", "Date"):
            continue
        for r in rows[1:]:
            if not r or not r[1] or not isinstance(r[2], dt.datetime):
                continue
            out.append({"sheet": ws.title, "place": str(r[1]).strip(),
                        "date": r[2].date(), "note": str(r[3] or "")})
    return out


def grunewald_status(note: str) -> Optional[str]:
    """Пояснение набора — в утверждение о дне `date`: «axis» или «soviet».

    Формулировок восемь: «Under Axis Control by …», «… before Start of
    Operation Barbarossa» — под противником; «Recaptured by Soviet forces
    by …», «Under Red Army Control …», «Under Soviet Control by/at …»,
    «Still under Soviet control …» — под советскими войсками.
    """
    low = note.lower()
    if "axis control" in low:
        return "axis"
    if "soviet" in low or "red army" in low:
        return "soviet"
    return None


def occupied_on(parsed: ParsedEntry, day: dt.date) -> Optional[bool]:
    """Был ли город под противником в этот день — по периодам статьи."""
    plist, _ = periods(parsed)
    known = False
    for p in plist:
        if p.start and p.end:
            known = True
            if p.start.date <= day < p.end.date:
                return True
    return False if known else None


def check_grunewald(parsed: list[ParsedEntry], rows: list[dict]) -> dict:
    """Утверждения набора против периодов справочника.

    Даты набора — «к такому-то дню» по картам популярных атласов, а не дни
    событий, поэтому сверяется не равенство дат, а непротиворечие: «под
    контролем Оси к 19 ноября 1942 года» верно, если в этот день город по
    справочнику оккупирован. Города, которых в справочнике нет (Москва,
    Ленинград, Тула — не оккупировались), в сверку не идут.
    """
    by_key: dict[str, list] = {}
    for p in parsed:
        for n in dict.fromkeys((p.city.name, p.city.modern)):
            if n:
                by_key.setdefault(latin_key(n), []).append(p)
    result = {"rows": len(rows), "matched": 0, "agree": 0, "disagree": [], "unmatched": [],
              "no_claim": 0}
    for row in rows:
        place = row["place"].strip()
        region = None
        if place in GRUNEWALD_ALIASES:
            ru, _, region = (GRUNEWALD_ALIASES[place] or "").partition("|")
            found = by_key.get(latin_key(ru), []) if ru else []
        else:
            found = by_key.get(latin_key(place), [])
        if region:
            found = [p for p in found if p.city.region == region]
        # Два города с одним названием (Николаев, Первомайск) без подсказки
        # области — не сверяются: угадывать нельзя.
        entry = found[0] if len(found) == 1 else None
        if entry is None:
            result["unmatched"].append(place)
            continue
        result["matched"] += 1
        status = grunewald_status(row["note"])
        state = occupied_on(entry, row["date"])
        if status is None or state is None:
            result["no_claim"] += 1
            continue
        if (status == "axis") == state:
            result["agree"] += 1
        else:
            result["disagree"].append(
                f"{row['sheet']}: {place} {row['date'].isoformat()} «{row['note']}» — "
                f"по справочнику {'оккупирован' if state else 'не оккупирован'} "
                f"({entry.city.label}: " + "; ".join(
                    f"{human_date(p.start.date)} — {human_date(p.end.date)}"
                    for p in periods(entry)[0] if p.start and p.end) + ")")
    return result
