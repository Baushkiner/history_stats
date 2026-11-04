"""Указатель метрических книг Архивов Беларуси: приход → годы, фонд, опись.

Зачем этот слой. Вопрос генеалога «в каком архиве и за какие годы лежат
метрические книги прихода» для белорусских губерний закрывает сам архивный
портал: на `archives.gov.by` с 2006 года висит указатель «Метрические книги»
— по уездам Минской, Гродненской, Виленской, Витебской, Могилёвской,
Сувалкской и Ковенской губерний строки «приход — годы — фонд/опись — число
единиц хранения» отдельно для православных (и униатских) церквей и для
католических костёлов, а к ним — Excel «Единый межфондовый указатель» НИАБ
в Гродно по костёлам и церквам с крайними датами отдельно по рождениям,
бракам и смертям. В `parishes` есть приход, здесь — где его книги.

Откуда берётся. Портал — WordPress, и страницы отдаются машинно через
WP REST: `/wp-json/wp/v2/pages?parent=<id>` — все дочерние страницы раздела
одним ответом (`content.rendered` — та же HTML-таблица, что на странице).
Разделов два: «православных и униатских (греко-католических) церквей»
(страница 244873) и «католических костёлов» (640747). Главная страница
раздела ссылается на 26 и 17 уездов, но опубликованных дочерних страниц
больше — 44 и 38: Витебская и Могилёвская губернии, о которых главная пишет
«будут включены», уже выложены, просто без ссылки. Берутся все дочерние
страницы; что страница не связана с главной, видно в `extra.linked`.
Русская версия — основная: у английской (`/en/`) те же страницы и номера,
но названия приходов латиницей; с неё берутся только две страницы, которых
по-русски нет (православные Велижского уезда, католические Сокольского).

Что берётся и что не берётся:

* **Берутся** приход (как в указателе: «Аннопольский», «Бобруйск /
  Софийская кладбищенская церковь»), годы, архив (НИАБ в Минске или в
  Гродно — по заголовку таблицы), фонд, опись, число или номера единиц
  хранения, примечание; из Excel — крайние даты по рождениям, бракам и
  смертям и привязка прихода к уезду до 1921 года и к повету после.
* **Не берутся** персоналии (их в указателе и нет) и тексты страниц.

Запись — одна на приход (церковь) в указателе уезда: годы — диапазонами,
фонды и описи — строкой с годами по каждой. Строки «Разные церкви уезда»
дают запись о сводных книгах уезда. Excel — своя запись на церковь: шифра в
нём нет, а годы по типам записей есть. Это территориальные записи: губерния
и уезд — по названию страницы (или по строке Excel), уезд сведён со
справочником RISTAT 1897 года (`districts_1897.geojson`). Приход, известный
Excel только по межвоенному повету Польши, губернии 1897 года не получает:
пометка `district_interwar`, повет и воеводство — в `place_text`.

Права. Условий использования портал не публикует — права не выяснены.
Берутся факты — приход, годы, шифр — со ссылкой на страницу указателя.
`robots.txt` закрывает только `/wp-admin/`; `Crawl-delay` нет, сборщик
держит паузу в две секунды и повторяет запрос при обрыве соединения —
сервер то и дело сбрасывает его на рукопожатии.
"""

from __future__ import annotations

import html
import io
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .wikisource_arkhiv import (
    Place, UezdResolver, compact_years, expand, parse_years,
)

BASE_URL = "https://archives.gov.by"
ROBOTS_URL = BASE_URL + "/robots.txt"
REST_RU = BASE_URL + "/wp-json/wp/v2/pages"
REST_EN = BASE_URL + "/en/wp-json/wp/v2/pages"
INDEX_ID = 360168
INDEX_URL = BASE_URL + "/home/genealogiya/metricheskie-knigi"
SECTIONS = {244873: "orthodox", 640747: "catholic"}
EXCEL = {
    "catholic": BASE_URL + "/wp-content/uploads/files/ukaz_kostel.xlsx",
    "orthodox": BASE_URL + "/wp-content/uploads/files/ukaz_tserkov.xlsx",
}
FIELDS = "id,slug,title,link,date,modified,parent,content"

# Сколько дочерних страниц было в разделах 04.11.2026 (русская версия): 44
# православных и 38 католических. Меньше — раздел перекроили, и прежде чем
# собирать, надо понять, что пропало.
EXPECTED_PAGES = {"orthodox": 44, "catholic": 38}
PAUSE = 2.0

LICENSE = "права не выяснены: условий портал не публикует; берутся приход, годы и шифр"

METRIC_BOOKS_BY = LayerSpec(
    slug="metric_books_by",
    title="Метрические книги в архивах Беларуси: указатель по приходам",
    group="faith",
    source="Архивы Беларуси (archives.gov.by): указатель метрических книг и Excel НИАБ в Гродно",
    license=LICENSE,
    description=(
        "За какие годы и в каком фонде НИАБ (в Минске или в Гродно) лежат метрические "
        "книги прихода — по указателю портала «Архивы Беларуси»: православные, униатские "
        "церкви и костёлы Минской, Гродненской, Виленской, Витебской, Могилёвской, "
        "Сувалкской и Ковенской губерний по уездам, плюс межфондовый указатель НИАБ в "
        "Гродно с крайними датами по рождениям, бракам и смертям. Отвечает, куда писать "
        "запрос о метрике прихода за нужный год."
    ),
    url=INDEX_URL,
    status="harvested",
    # 04.11.2026: 1 629 приходов из указателя по уездам и 727 церквей и
    # костёлов из Excel НИАБ в Гродно.
    expected_rows=2356,
)

CONFESSIONS = {
    "orthodox": ("церковь", "православная (до 1839 года — и униатская)"),
    "catholic": ("костёл", "римско-католическая"),
}

ARCHIVES = {
    "минске": ("НИАБ (Минск)", "Национальный исторический архив Беларуси в г. Минске"),
    "minsk": ("НИАБ (Минск)", "Национальный исторический архив Беларуси в г. Минске"),
    "гродно": ("НИАБ (Гродно)", "Национальный исторический архив Беларуси в г. Гродно"),
    "grodno": ("НИАБ (Гродно)", "Национальный исторический архив Беларуси в г. Гродно"),
}


class ArchivesByError(RuntimeError):
    """Портал не ответил или ответил не в том виде, какой записан в коде."""


# --- сеть ---------------------------------------------------------------------------

@dataclass
class Client:
    """Пауза, повтор на 429/5xx и на сброс соединения, подпись проекта."""

    pause: float = PAUSE
    timeout: int = 120
    retries: int = 6
    _last: float = field(default=0.0, repr=False)
    requests: int = field(default=0, repr=False)

    def get(self, url: str) -> bytes:
        error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            self._last = wait_for_pause(self._last, self.pause)
            self.requests += 1
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES:
                    raise ArchivesByError(f"{url}: HTTP {exc.code}") from exc
                error = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                error = exc
            if attempt < self.retries:
                time.sleep(self.pause * (attempt + 1))
        raise ArchivesByError(f"{url}: не ответил за {self.retries + 1} попыток ({error})")

    def get_json(self, url: str):
        try:
            return json.loads(self.get(url).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ArchivesByError(f"{url}: ответ не JSON ({exc})") from exc

    def robots(self) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser(ROBOTS_URL)
        parser.parse(self.get(ROBOTS_URL).decode("utf-8", "replace").splitlines())
        delay = parser.crawl_delay("*")
        if delay:
            self.pause = max(self.pause, float(delay))
        return parser


def children_url(parent: int, *, english: bool = False) -> str:
    base = REST_EN if english else REST_RU
    return f"{base}?parent={parent}&per_page=100&_fields={FIELDS}"


def page_url(page_id: int, *, english: bool = False) -> str:
    return f"{BASE_URL}{'/en' if english else ''}/?page_id={page_id}"


# --- страница уезда -----------------------------------------------------------------------

_RE_TAG = re.compile(r"<[^>]+>")


def text_of(fragment: str) -> str:
    s = _RE_TAG.sub(" ", fragment or "")
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class PageInfo:
    """Чей указатель: раздел, уезд и губерния из заголовка страницы."""

    page_id: int
    section: str               # orthodox | catholic
    title: str
    uezd: Optional[str]        # «Минский» — именительный падеж, по-русски
    province: Optional[str]    # «Минская губерния»
    unit: str = "уезд"         # уезд | деканат
    english: bool = False
    note: Optional[str] = None


_RE_RU_UEZD = re.compile(r"([А-ЯЁ][\w-]+?)(ого|его)\s+(уезда|деканат)", re.U)
_RE_RU_PROV = re.compile(r"([А-ЯЁ][\w-]+?)(ой|ей)\s*(?:\([^)]*\)\s*)?губернии", re.U)
_RE_RU_DEANERY = re.compile(r"([А-ЯЁ][\w-]+?)ий\s+деканат", re.U)
_RE_EN = re.compile(r"(?:^|>|\s)([A-Z][\w-]+)\s+(uezd|deanery)\s+([A-Z][\w-]+)\s+province", re.U)

# Губернии в английских заголовках → по-русски.
EN_PROVINCES = {
    "Minsk": "Минская губерния", "Grodno": "Гродненская губерния", "Vilno": "Виленская губерния",
    "Vitebsk": "Витебская губерния", "Mogilev": "Могилевская губерния",
    "Suvalki": "Сувалкская губерния", "Kovno": "Ковенская губерния",
    "Sedlitsa": "Седлецкая губерния",
}


def parse_page_title(page_id: int, title_html: str, section: str, *,
                     english: bool = False) -> PageInfo:
    """«… церквей Минского уезда Минской губернии» → уезд «Минский», «Минская губерния»."""
    title = text_of(title_html)
    if english:
        m = _RE_EN.search(title.replace("<br>", " "))
        if not m:
            return PageInfo(page_id, section, title, None, None, english=True)
        return PageInfo(page_id, section, title, m.group(1),
                        EN_PROVINCES.get(m.group(3)), "деканат" if m.group(2) == "deanery"
                        else "уезд", english=True)
    uezd = province = None
    unit = "уезд"
    m = _RE_RU_UEZD.search(title)
    if m:
        uezd = m.group(1) + "ий"
        if m.group(3).startswith("деканат"):
            unit = "деканат"
    else:
        m = _RE_RU_DEANERY.search(title)
        if m:
            uezd, unit = m.group(1) + "ий", "деканат"
    m = _RE_RU_PROV.search(title)
    if m:
        province = m.group(1) + ("ая" if m.group(2) == "ой" else "яя") + " губерния"
    note = None
    m = re.search(r"\(([^)]*)\)\s*губернии", title)
    if m:
        note = m.group(1)
        # «Дисненского уезда Минской (с 1845 — Виленской) губернии»: губерния
        # записи — та, в которой уезд был в 1897 году.
        later = re.search(r"с\s*\d{4}\s*[–—-]\s*([А-ЯЁ][\w-]+?)ой", note)
        if later:
            province = later.group(1) + "ая губерния"
    return PageInfo(page_id, section, title, uezd, province, unit, False, note)


@dataclass(frozen=True)
class Row:
    """Строка указателя: приход (или продолжение предыдущего) и шифр."""

    archive: str
    parish: str
    years_raw: str
    fond: Optional[str]
    opis: Optional[str]
    units: Optional[str]
    note: Optional[str] = None


HEADERS = (
    ("parish", re.compile(r"^(приход|parish)", re.I)),
    ("years", re.compile(r"^(годы|years)", re.I)),
    ("fond_opis", re.compile(r"^(фонд\s*/\s*опись|fond\s*/\s*inventory)", re.I)),
    ("fond", re.compile(r"^(фонд|fond)$", re.I)),
    ("opis", re.compile(r"^(опись|inventory)$", re.I)),
    ("units", re.compile(r"^(количество\s*единиц|номера\s*единиц|number\s+of|items)", re.I)),
    ("note", re.compile(r"^(примечани|notes?)", re.I)),
)


def _header_name(text: str) -> Optional[str]:
    for name, pattern in HEADERS:
        if pattern.search(text.strip()):
            return name
    return None


_RE_TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
_RE_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_RE_TR = re.compile(r"<tr[^>]*>(.*?)(?=<tr|</table>)", re.S | re.I)


def parse_tables(content: str) -> list[tuple[str, list[str], list[list[str]]]]:
    """HTML страницы → [(архив, заголовок, строки)].

    Архив — по ближайшему перед таблицей абзацу («Национальный исторический
    архив Беларуси в г. Минске»). Строки режутся по ширине заголовка: у части
    страниц в разметке нет `</tr>`, и строка данных слипается с заголовком.
    """
    out = []
    pos = 0
    archive = "НИАБ (Минск)"
    for m in _RE_TABLE.finditer(content):
        before = text_of(content[pos:m.start()]).lower()
        for key, (short, _) in ARCHIVES.items():
            if key in before:
                archive = short
        pos = m.end()
        cells = [text_of(c) for c in _RE_CELL.findall(m.group(0))]
        width = 0
        header = []
        for cell in cells:
            name = _header_name(cell)
            if name is None or name in header:
                break
            header.append(name)
            width += 1
        if "parish" not in header or "years" not in header:
            continue
        body = cells[width:]
        rows = [body[i:i + width] for i in range(0, len(body), width)]
        out.append((archive, header, [r for r in rows if len(r) == width]))
    return out


def page_rows(content: str) -> list[Row]:
    """Строки указателя: пустой приход — продолжение предыдущего."""
    out = []
    for archive, header, rows in parse_tables(content):
        parish = ""
        for cells in rows:
            row = dict(zip(header, cells))
            if row.get("parish"):
                parish = row["parish"]
            if not parish:
                continue
            fond = opis = None
            if row.get("fond_opis"):
                fond, opis = split_fond(row["fond_opis"])
            else:
                fond = clean_text(row.get("fond"))
                opis = clean_text(row.get("opis"))
            years_raw = clean_text(row.get("years")) or ""
            if not years_raw and not fond and not row.get("units"):
                continue
            out.append(Row(archive=archive, parish=parish, years_raw=years_raw, fond=fond,
                           opis=opis, units=clean_text(row.get("units")),
                           note=clean_text(row.get("note"))))
    return out


def split_fond(text: str) -> tuple[Optional[str], Optional[str]]:
    """«136/13» → («136», «13»); «1356» → («1356», None)."""
    s = clean_text(text)
    if not s:
        return None, None
    parts = [p.strip() for p in s.split("/", 1)]
    return parts[0] or None, (parts[1] or None) if len(parts) > 1 else None


# --- приход ---------------------------------------------------------------------------------

_RE_GROUP = re.compile(r"(?i)^(разн\w+|different|various)\b")


@dataclass(frozen=True)
class Parish:
    """Приход строки указателя: «Бобруйск / Софийская кладбищенская церковь»."""

    name: str                  # как в указателе
    parish: str                # «Бобруйск»
    church: Optional[str]      # «Софийская кладбищенская церковь»
    group: bool

    @property
    def key(self) -> str:
        return "|".join(x.lower().replace("ё", "е") for x in (self.parish, self.church or ""))


def parse_parish(name: str) -> Parish:
    s = clean_text(name) or ""
    group = bool(_RE_GROUP.search(s))
    if "/" in s:
        left, right = (p.strip() for p in s.split("/", 1))
        return Parish(s, left, right or None, group)
    return Parish(s, s, None, group)


@dataclass
class Entry:
    page: PageInfo
    parish: Parish
    rows: list[Row]
    linked: bool = True

    @property
    def years(self) -> set[int]:
        return expand(y for row in self.rows for y in parse_years(row.years_raw))


def aggregate(page: PageInfo, rows: Iterable[Row], *, linked: bool = True) -> list[Entry]:
    entries: dict[str, Entry] = {}
    for row in rows:
        parish = parse_parish(row.parish)
        entry = entries.setdefault(parish.key, Entry(page, parish, [], linked))
        entry.rows.append(row)
    return list(entries.values())


def holdings(rows: list[Row]) -> str:
    """«НИАБ (Минск) ф. 136, оп. 13: 1786–1791, 1796–1840 (25 ед. хр.); …»."""
    out = []
    for row in rows:
        code = f"{row.archive} ф. {row.fond}" if row.fond else f"{row.archive}, шифр не указан"
        if row.opis:
            code += f", оп. {row.opis}"
        tail = row.years_raw or "годы не указаны"
        if row.units:
            tail += f" ({row.units} ед. хр.)" if re.fullmatch(r"\d+", row.units) else \
                f" (ед. хр. {row.units})"
        if row.note:
            tail += f"; {row.note}"
        out.append(f"{code}: {tail}")
    return "; ".join(out)


def entry_to_record(entry: Entry, resolver: Optional[UezdResolver] = None,
                    spec: LayerSpec = METRIC_BOOKS_BY) -> ContextRecord:
    page, parish = entry.page, entry.parish
    years = entry.years
    church, confession = CONFESSIONS[page.section]
    place = resolve(resolver, page.uezd, page.province) if page.unit == "уезд" \
        else Place(page.province, None, None, None)
    region = place.province or page.province
    uezd_text = f"{page.uezd} {page.unit}" if page.uezd else None
    label = parish.name if not parish.group else f"сводные книги: {parish.name}"
    archives = sorted({r.archive for r in entry.rows})
    fonds = sorted({f"{r.fond}/{r.opis}" if r.opis else r.fond for r in entry.rows if r.fond})
    extra = {
        "index": "указатель по уездам",
        "page_id": page.page_id,
        "language": "en" if page.english else None,
        "linked": None if entry.linked else False,
        "archives": archives,
        "fonds": fonds,
        "holdings": holdings(entry.rows),
        "parish": parish.parish,
        "church": parish.church,
        "uezd_source": uezd_text,
        "district_match": place.how,
    }
    extra = {k: v for k, v in extra.items() if v not in (None, [], "")}
    years_text = compact_years(years)
    confidence = "ok" if place.district or page.unit == "деканат" and region else (
        "district_unmatched" if region else "region_unmatched")
    if not years:
        confidence = "no_date"
    codes = []
    for row in entry.rows:
        code = f"{row.archive} ф. {row.fond}" + (f", оп. {row.opis}" if row.opis else "") \
            if row.fond else f"{row.archive} (шифр не указан)"
        if code not in codes:
            codes.append(code)
    summary = (f"Метрические книги ({church}, {parish.name}) за {years_text or 'годы не указаны'}"
               f": {'; '.join(codes)}"
               + (f"; {place.district or uezd_text}, {region}" if region else "") + ".")
    return spec.new_record(
        title=f"Метрические книги: {label} — {uezd_text or page.title}",
        category=church if not parish.group else "сводные книги нескольких приходов",
        scope=SCOPE_REGION,
        place_text=", ".join(p for p in (parish.name, uezd_text, page.province) if p),
        region=region, regions=[region] if region else [],
        district=place.district or uezd_text,
        year_from=min(years) if years else None, year_to=max(years) if years else None,
        date_precision="year" if years else "unknown",
        period_raw=years_text or None,
        summary=summary,
        url=page_url(page.page_id, english=page.english),
        source_id=f"page:{page.page_id}:{parish.key}",
        confidence=confidence,
        extra={**extra, "confession": confession},
    )


# Губернии, в которых ищется уезд, не найденный в названной: уезды Северо-Западного
# края переходили из губернии в губернию (Дисненский, Лидский, Сокольский).
NEIGHBOURS = ("Минская губерния", "Гродненская губерния", "Виленская губерния",
              "Витебская губерния", "Могилевская губерния", "Ковенская губерния",
              "Сувалкская губерния", "Седлецкая губерния")


def resolve(resolver: Optional[UezdResolver], uezd: Optional[str],
            province: Optional[str]) -> Place:
    """Уезд 1897 года: в названной губернии, иначе — точным ключом в соседних."""
    if resolver is None or not uezd:
        return Place(province, None, None, None)
    place = resolver.match_in(uezd, province)
    if place.district:
        return place
    for other in NEIGHBOURS:
        if other == province:
            continue
        alt = resolver.match_in(uezd, other, exact_only=True)
        if alt.district:
            return Place(alt.province, alt.district, alt.distr_id, f"{alt.how}+province")
    return place


# --- Excel НИАБ в Гродно ------------------------------------------------------------------

@dataclass(frozen=True)
class ExcelRow:
    name: str            # «Батуринский костёл»
    location: str        # «Вилейского у. Виленской губ., с 1921 г. …»
    births: str
    marriages: str
    deaths: str
    see: Optional[str] = None   # «(см. Камень-Шляхетская церковь)»


_RE_KIND = re.compile(r"(?i)\b(костёл|костел|церковь|собор|часовня|каплица|кирха|монастыр\w*)\b")


def excel_rows(data: bytes) -> list[ExcelRow]:
    """Строки Excel-указателя: название с местом и три столбца крайних дат."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    out = []
    started = False
    for values in ws.iter_rows(values_only=True):
        cells = [clean_text(v) if v is not None else None for v in values[:4]]
        if not started:
            # Шапка кончается строкой с номерами колонок «1 2 3 4».
            if cells[:4] == ["1", "2", "3", "4"]:
                started = True
            continue
        first = cells[0]
        if not first or len(first) < 4:
            continue
        m = _RE_KIND.search(first)
        if not m:
            continue
        name = first[: m.end()].strip()
        rest = first[m.end():].strip(" ,")
        see = None
        ms = re.search(r"\(\s*см\.?\s*([^)]*)\)", rest)
        if ms:
            see = ms.group(1).strip()
        # «( Алексейковская)» сразу после названия — другое имя прихода.
        alias = re.match(r"^\(([^)]*)\)\s*", rest)
        if alias and not ms:
            name += f" ({alias.group(1).strip()})"
            rest = rest[alias.end():]
        out.append(ExcelRow(name=name, location=rest, births=cells[1] or "",
                            marriages=cells[2] or "", deaths=cells[3] or "", see=see))
    return out


_RE_X_UEZD = re.compile(r"([А-ЯЁ][\w-]+?)(ого|его)\s*у(?:езда|\.)\s*([А-ЯЁ][\w-]+?)(ой|ей)\s+губ",
                        re.U)
_RE_X_PROV = re.compile(r"^\s*([А-ЯЁ][\w-]+?)(ой|ей)\s+губ", re.U)
_RE_X_POWIAT = re.compile(r"([А-ЯЁ][\w-]+?)(ого|его)\s+повета\s+([А-ЯЁ][\w-]+?)(ого|его)\s+"
                          r"воеводства", re.U)
_RE_X_OBL = re.compile(r"([А-ЯЁ][\w-]+?)(ого|его)\s*у(?:езда|\.)\s*([А-ЯЁ][\w-]+?)(ой|ей)\s+обл",
                       re.U)


def excel_place(location: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Место из строки Excel: (уезд, губерния, повет межвоенной Польши).

    Берётся первая названная единица империи: «Лидского у. Гродненской губ.,
    с 1843 г. Лидского у. Виленской губ., …» — Лидский уезд Гродненской
    губернии; переподчинения остаются в `place_text`.
    """
    m = _RE_X_UEZD.search(location)
    if m:
        return m.group(1) + "ий", _province(m.group(3), m.group(4)), None
    m = _RE_X_OBL.search(location)
    if m:
        # «Дрогичинского у. Белостокской обл.» — область 1807–1842 годов,
        # в 1897-м её уезды — в Гродненской губернии.
        return m.group(1) + "ий", "Гродненская губерния", None
    m = _RE_X_POWIAT.search(location)
    if m:
        return None, None, f"{m.group(1)}ий повет {m.group(3)}ого воеводства"
    m = _RE_X_PROV.search(location)
    if m:
        # «Могилёвской губ.» без уезда: губерния есть, уезда нет.
        return None, _province(m.group(1), m.group(2)), None
    return None, None, None


def _province(stem: str, ending: str) -> str:
    """«Могилёвск» + «ой» → «Могилевская губерния» (написание справочника 1897 года)."""
    return (stem + ("ая" if ending == "ой" else "яя")).replace("ё", "е") + " губерния"


def excel_to_record(row: ExcelRow, section: str, resolver: Optional[UezdResolver] = None,
                    spec: LayerSpec = METRIC_BOOKS_BY, aliases: Optional[list] = None
                    ) -> ContextRecord:
    church, confession = CONFESSIONS[section]
    if re.search(r"(?i)униат", row.name):
        confession = "греко-католическая (униатская)"
    uezd, province, powiat = excel_place(row.location)
    place = resolve(resolver, uezd, province)
    region = place.province or province
    by_type = {"births": row.births, "marriages": row.marriages, "deaths": row.deaths}
    years = expand(y for text in by_type.values() for y in parse_years(text))
    years_text = compact_years(years)
    if not years:
        confidence = "no_date"
    elif place.district:
        confidence = "ok"
    elif powiat and not uezd:
        confidence = "district_interwar"
    elif region:
        confidence = "district_unmatched"
    else:
        confidence = "region_unmatched"
    uezd_text = f"{uezd} уезд" if uezd else None
    extra = {
        "index": "единый межфондовый указатель НИАБ в Гродно",
        "archives": ["НИАБ (Гродно)"],
        "births": row.births or None, "marriages": row.marriages or None,
        "deaths": row.deaths or None,
        "location_source": row.location or None,
        "powiat": powiat,
        "aliases": aliases or None,
        "district_match": place.how,
        "confession": confession,
    }
    extra = {k: v for k, v in extra.items() if v not in (None, [], "")}
    types = [label for label, text in (("рождения", row.births), ("браки", row.marriages),
                                       ("смерти", row.deaths)) if parse_years(text)]
    summary = (f"Метрические книги ({row.name}) за {years_text or 'годы не указаны'}: НИАБ в "
               f"Гродно, единый межфондовый указатель (шифр — в описях фондов архива)"
               + (f"; записи: {', '.join(types)}" if types else "")
               + (f"; {place.district or uezd_text}, {region}" if region else
                  (f"; {powiat}" if powiat else "")) + ".")
    return spec.new_record(
        title=f"Метрические книги: {row.name} — НИАБ (Гродно)",
        category=church if section == "catholic" or not re.search(r"(?i)костел|костёл", row.name)
        else "костёл",
        scope=SCOPE_REGION,
        place_text=", ".join(p for p in (row.name, row.location) if p),
        region=region, regions=[region] if region else [],
        district=place.district or uezd_text or powiat,
        year_from=min(years) if years else None, year_to=max(years) if years else None,
        date_precision="year" if years else "unknown",
        period_raw=years_text or None,
        summary=summary,
        url=EXCEL[section],
        source_id=f"excel:{section}:{row.name.lower().replace('ё', 'е')}",
        confidence=confidence,
        extra=extra,
    )


def excel_records(rows: list[ExcelRow], section: str,
                  resolver: Optional[UezdResolver] = None) -> list[ContextRecord]:
    """Записи Excel; строки-отсылки («см. …») становятся другим именем прихода."""
    aliases: dict[str, list[str]] = {}
    names = {_kind_key(row.name) for row in rows}
    for row in rows:
        if row.see and _kind_key(row.see) in names:
            aliases.setdefault(_kind_key(row.see), []).append(row.name)
    out = []
    for row in rows:
        # Отсылка без дат, у которой цель в указателе есть, — другое имя
        # прихода цели, а не своя запись; без цели остаётся записью без дат.
        if row.see and not (row.births or row.marriages or row.deaths) \
                and _kind_key(row.see) in names:
            continue
        out.append(excel_to_record(row, section, resolver,
                                   aliases=aliases.get(_kind_key(row.name))))
    return out


def _kind_key(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", name)).strip().lower().replace("ё", "е")
