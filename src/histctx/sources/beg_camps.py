"""Перечень концлагерей и внешних команд по § 42 Abs. 2 BEG: даты «с — по».

Что это. Приложение к Шестой распорядительной инструкции к Федеральному
закону о компенсации (6. DV-BEG, BGBl. I 1967, S. 233) — «Verzeichnis der
Konzentrationslager und ihrer Außenkommandos»: перечень мест заключения,
которые для выплат приравнены к концлагерю, со всеми поправками (последняя
в сводном тексте — 24.11.1982, BGBl. I S. 1571). Опубликован на
`gesetze-im-internet.de` (Минюст ФРГ и juris) страницей `begdv_6/anlage.html`
и XML-архивом `begdv_6/xml.zip`; `robots.txt` сайта разрешает всё.

Права. Официальный текст нормативного акта по § 5 UrhG охраной авторского
права не пользуется. Берётся всё, что есть в строке: название и место, район,
главный лагерь, сроки.

Как устроен XML. Одна норма «Anlage», в ней пять таблиц CALS (по буквам
алфавита), по четыре колонки: номер, название с местом и сроками (у
названия — объединённые две средние колонки), главный лагерь. Запись
занимает несколько строк таблицы: номер с `morerows` тянется вниз, сроки
стоят в следующих строках, главный лагерь — то в первой, то в последней
строке. Поэтому строки раскладываются по колонкам с учётом `morerows`,
`namest` и `nameend` (`cals_grid`), а запись — это всё от строки с номером
до следующей. У пятой таблицы колонки названы иначе (`col1`, `COLSPEC0`,
`col2`, `col3`) — роли колонок берутся по порядку, а не по имени.

Сроки. Три формы и только они (замер 04.11.2026): «13.9.1939 bis
30.11.1941», «bis 8.4.1945», «ab 15.9.1943», после каждой — пояснение в
скобках («Männerlager», «Frauen»). У записи бывает несколько сроков: мужской
и женский лагерь, перерывы. По § 2 Abs. 3 инструкции о месте без сроков
«предполагается, что оно существовало 01.11.1943» — это правовая
презумпция, а не дата; в записи она остаётся пометкой и годами не
становится.

Записи «X, siehe Y» (446) — отсылки: в записи не идут, а дают второе
написание той записи, на которую ссылаются (Kaunas → Kauen).
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..schema import clean_text

XML_URL = "https://www.gesetze-im-internet.de/begdv_6/xml.zip"
PAGE_URL = "https://www.gesetze-im-internet.de/begdv_6/anlage.html"
ROBOTS_URL = "https://www.gesetze-im-internet.de/robots.txt"
# Сверено 04.11.2026: Last-Modified 03.08.2012, размер и md5 архива. Другой
# архив — новая сборка текста: сверить число записей и поправить здесь.
ZIP_SIZE = 663_835
ZIP_MD5 = "f5d51413000378080a0118da64f5a4be"
XML_NAME = "BJNR002330967.xml"
CACHE_NAME = "begdv_6_xml.zip"

LICENSE = ("официальный текст нормативного акта (6. DV-BEG, BGBl. I 1967, 233; "
           "сводная редакция gesetze-im-internet.de) — по § 5 UrhG охраной не пользуется")
CITATION = ("Verzeichnis der Konzentrationslager und ihrer Außenkommandos gemäß § 42 "
            "Abs. 2 BEG — Anlage zu § 1 der 6. DV-BEG vom 23.02.1967 (BGBl. I S. 233), "
            "zuletzt geändert 24.11.1982 (BGBl. I S. 1571)")

# Замер 04.11.2026: 1 679 записей, из них 446 отсылок «siehe» и 1 233 места;
# сроки «с — по» или их часть — у 1 002. Ещё две записи — Esterwegen и
# Neusustrum — говорят «siehe alle dort» о своих подкомандах, но сами — лагеря.
EXPECTED_ENTRIES = 1679
EXPECTED_SEE = 446

PRESUMED_DAY = dt.date(1943, 11, 1)     # § 2 Abs. 3 6. DV-BEG


class BegError(RuntimeError):
    """Архив не тот или таблица устроена не так, как ожидает разбор."""


# --- таблица CALS --------------------------------------------------------------

def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def anlage(xml: bytes) -> ET.Element:
    """Норма «Anlage» из XML архива."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise BegError(f"XML не разбирается ({exc})") from exc
    for norm in root.iter("norm"):
        if (norm.findtext("metadaten/enbez") or "").strip() == "Anlage":
            return norm
    raise BegError("в XML нет нормы «Anlage» — перечня концлагерей")


def stand(xml: bytes) -> Optional[str]:
    """Строка «Stand» сводного текста: «Zuletzt geändert durch … 24.11.1982 I 1571»."""
    m = re.search(rb"<standkommentar>(.*?)</standkommentar>", xml, re.S)
    return clean_text(m.group(1).decode("utf-8", "replace")) if m else None


def cals_grid(tgroup: ET.Element) -> list[list[str]]:
    """Строки таблицы CALS — по колонкам, с учётом `morerows`, `namest`, `nameend`.

    Возвращает строки вида [номер, текст средних колонок, главный лагерь]:
    роли колонок — по порядку `colspec` (первая, средние, последняя), потому
    что имена колонок в разных таблицах приложения разные.
    """
    cols = [c.get("colname") for c in tgroup.findall("colspec")]
    if len(cols) < 3:
        raise BegError(f"в таблице {len(cols)} колонки, а не четыре")
    body = tgroup.find("tbody")
    if body is None:
        raise BegError("у таблицы нет tbody")
    pending = [0] * len(cols)
    out = []
    for row in body.findall("row"):
        cells = [""] * len(cols)
        ci = 0
        for entry in row.findall("entry"):
            name = entry.get("colname") or entry.get("namest")
            if name in cols:
                ci = max(ci, cols.index(name))
            while ci < len(cols) and pending[ci] > 0:
                ci += 1
            if ci >= len(cols):
                raise BegError(f"в строке больше ячеек, чем колонок: {_text(row)[:120]!r}")
            end = ci
            if entry.get("nameend") in cols:
                end = max(ci, cols.index(entry.get("nameend")))
            cells[ci] = _text(entry)
            span = int(entry.get("morerows") or 0) + 1
            for k in range(ci, end + 1):
                pending[k] = span
            ci = end + 1
        out.append([cells[0], " ".join(c for c in cells[1:-1] if c), cells[-1]])
        pending = [max(0, p - 1) for p in pending]
    return out


_RE_NR = re.compile(r"^\d+[a-z]?$")
_RE_LETTER = re.compile(r"^[A-ZÄÖÜ]$")


@dataclass
class RawEntry:
    nr: str
    text: list = field(default_factory=list)
    main: list = field(default_factory=list)


def raw_entries(rows: Iterable[list[str]]) -> list[RawEntry]:
    """Строки — в записи: от строки с номером до следующей; буквы-разделы пропускаются."""
    out: list[RawEntry] = []
    current: Optional[RawEntry] = None
    for nr, text, main in rows:
        if _RE_NR.match(nr):
            current = RawEntry(nr=nr)
            out.append(current)
        elif not nr and _RE_LETTER.match(text) and not main:
            current = None
            continue
        elif nr == "Lfd. Nr.":
            continue
        if current is None:
            if text or main:
                raise BegError(f"строка вне записи: {nr!r} {text!r} {main!r}")
            continue
        if text:
            current.text.append(text)
        if main:
            current.main.append(main)
    return out


def table_rows(xml: bytes) -> list[list[str]]:
    rows = []
    for tg in anlage(xml).iter("tgroup"):
        rows.extend(cals_grid(tg))
    return rows


# --- сроки ------------------------------------------------------------------------

_D = r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})"
_RE_PERIOD = re.compile(
    rf"(?:{_D}\s*(?:bis|–|-)\s*{_D})|(?:\bbis\s+{_D})|(?:\bab\s+{_D})")
_RE_NOTE = re.compile(r"^\s*\(([^()]{1,60})\)")


@dataclass(frozen=True)
class Period:
    """Срок из перечня: начало и конец (любой может быть неизвестен) и пояснение."""

    start: Optional[dt.date]
    end: Optional[dt.date]
    note: Optional[str] = None
    raw: str = ""


def _date(d: str, m: str, y: str) -> Optional[dt.date]:
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_periods(text: str) -> list[Period]:
    """Все сроки в тексте записи — в порядке появления."""
    out = []
    for m in _RE_PERIOD.finditer(text):
        g = m.groups()
        if g[0]:
            start, end = _date(*g[0:3]), _date(*g[3:6])
        elif g[6]:
            start, end = None, _date(*g[6:9])
        else:
            start, end = _date(*g[9:12]), None
        note_m = _RE_NOTE.match(text[m.end():])
        out.append(Period(start, end, clean_text(note_m.group(1)) if note_m else None,
                          clean_text(m.group(0)) or ""))
    return out


# --- название и место -------------------------------------------------------------

# Земли и государства после косой черты: «Kauen = Kaunas/Litauen».
REGIONS = {
    "Estland": "Estonia", "Lettland": "Latvia", "Kurland": "Latvia", "Litauen": "Lithuania",
    "Polen": "Poland", "Galizien": "Ukraine", "Ukraine": "Ukraine",
    "Ostpreußen": "East Prussia", "Westpreußen": "Poland", "Danzig-Westpreußen": "Poland",
    "Wartheland": "Poland", "Oberschlesien": "Poland", "Niederschlesien": "Poland",
    "Österreich": "Austria", "Tschech.": "Czechia", "Tschechoslowakei": "Czechia",
    "Sudetenland": "Czechia", "Holland": "Netherlands", "Niederlande": "Netherlands",
    "Frankreich": "France", "Elsaß": "France", "Lothringen": "France", "Belgien": "Belgium",
    "Norwegen": "Norway", "Italien": "Italy", "Jugoslawien": "Serbia",
    "Griechenland": "Greece", "Luxemburg": "Luxembourg", "Ungarn": "Hungary",
}
# Земли рамки РИ/СССР: по ним запись без точки узнаётся как «наша».
FRAME_REGIONS = frozenset({"Estland", "Lettland", "Kurland", "Litauen", "Galizien", "Ukraine"})
FRAME_WORDS = re.compile(r"\b(?:Minsk|Kiew|Riga|Kauen|Kaunas|Wilna|Reval|Tallin|Libau|Windau|"
                         r"Lemberg|Lwow|Bialystok|Lublin|Warschau|Radom|Sokolow|"
                         r"Wlodawa|Zamosc|Pulawy|Krasnik|Litzmannstadt|Lodz|Konstantynow|"
                         r"Dzierzazna|Treblinka|Sobibor|Belzec|Majdanek|Trawniki|Poniatowa|"
                         r"Budzyn|Blizyn|Narwa|Klooga|Vaivara|Dünaburg|Schaulen)\b")

_RE_SEE = re.compile(r"^(?P<alias>.+?),?\s+siehe\s+(?P<target>.+?)\.?$")
_RE_DISTRICT = re.compile(r"^(?:Kreis|Krs\.|Landkreis|Kreisgebiet|Kreishauptmannschaft|"
                          r"Gemeinde|Gem\.|Bezirk|Bez\.|Regierungsbezirk|Amt)\b")


@dataclass
class Entry:
    """Запись перечня BEG после разбора."""

    nr: str
    text: str
    main_camp: Optional[str]
    names: list                 # написания места: «Kauen», «Kaunas»
    place: str                  # первое написание
    detail: Optional[str]       # уточнение после запятой: «Balastdamm», «Gartenstraße 12»
    district: Optional[str]
    region: Optional[str]       # земля или государство после косой черты
    near: Optional[str]         # «bei Minsk»
    periods: list
    see: Optional[str] = None   # отсылка «siehe»: куда
    aliases: list = field(default_factory=list)   # написания из отсылок на эту запись

    @property
    def key(self) -> str:
        return f"beg:{self.nr}"

    @property
    def is_reference(self) -> bool:
        return self.see is not None

    @property
    def frame_hint(self) -> bool:
        """По тексту — земля РИ/СССР (для записи, которой не нашлось точки).

        «Polen» само по себе не в счёт: Силезия, Померания и Познань — Польша,
        но не империя. В счёт — Прибалтика, Галиция, Украина и места Царства
        Польского и СССР, названные прямо (`FRAME_WORDS`).
        """
        return bool(self.region in FRAME_REGIONS or FRAME_WORDS.search(self.text))

    @property
    def head(self) -> str:
        """Текст записи без сроков: место, район, уточнение."""
        return (_RE_PERIOD.split(self.text, maxsplit=1)[0] if self.periods
                else self.text).strip(" ,;")

    def interval(self) -> tuple[Optional[dt.date], Optional[dt.date], bool, bool]:
        """(начало, конец, начало известно, конец известен) по всем срокам.

        Начало известно, только если оно есть у каждого срока: у женского лагеря
        «bis 12.4.1945» начала нет, и мужской «27.11.1944 bis …» его не заменит.
        """
        if not self.periods:
            return None, None, False, False
        starts = [p.start for p in self.periods]
        ends = [p.end for p in self.periods]
        start_known = all(starts)
        end_known = all(ends)
        start = min((s for s in starts if s), default=None)
        end = max((e for e in ends if e), default=None)
        return start, end, start_known, end_known


def parse_entry(raw: RawEntry) -> Entry:
    text = clean_text(" ".join(raw.text)) or ""
    text = text.replace("„", '"').replace("“", '"')
    main = clean_text(" ".join(raw.main))
    see = _RE_SEE.match(text)
    if see and not _RE_PERIOD.search(text):
        alias = see.group("alias")
        names, place, *_ = _names(alias)
        return Entry(nr=raw.nr, text=text, main_camp=main, names=names, place=place,
                     detail=None, district=None, region=None, near=None, periods=[],
                     see=clean_text(see.group("target")))
    periods = parse_periods(text)
    head = _RE_PERIOD.split(text, maxsplit=1)[0] if periods else text
    names, place, detail, district, region, near = _names(head)
    if region is None:
        m = re.search(r"/\s*([A-ZÄÖÜ][\w.\-ßäöü]+)", text)
        if m and m.group(1) in REGIONS:
            region = m.group(1)
    return Entry(nr=raw.nr, text=text, main_camp=main, names=names, place=place,
                 detail=detail, district=district, region=region, near=near,
                 periods=periods)


def _names(head: str) -> tuple:
    """Голова записи до сроков — написания места, уточнение, район, земля, «bei …»."""
    segs = [s.strip() for s in head.strip(" ,;").split(",") if s.strip()]
    first = segs[0] if segs else head
    region = None
    near = None
    names = []
    detail = district = None
    for part in re.split(r"\s+=\s+", first):
        part = part.strip()
        # «Laoküla/Estland Unterkdo. v. Klooga», «Warszawa/Polen (außer Getto)»
        m = re.match(r"^(.*?)\s*/\s*([A-ZÄÖÜ][\w.\-ßäöü]+)(.*)$", part)
        if m and m.group(2) in REGIONS:
            part, region = m.group(1).strip(), m.group(2)
            detail = clean_text(m.group(3).strip(" ,()")) or detail
        b = re.match(r"^(.*?)\s+bei\s+(.+)$", part)
        if b:
            part, near = b.group(1).strip(), b.group(2).strip()
        part = re.sub(r"\((?:Männer|Frauen)\)", "", part).strip(' "')
        part = re.sub(r'\s*"\s*', " ", part)
        part = re.sub(r"(?<=\w)-\s+", "-", part).strip()
        if part:
            names.append(part)
    for seg in segs[1:]:
        m = re.match(r"^(.*?)\s*/\s*([A-ZÄÖÜ][\w.\-ßäöü]+)\s*$", seg)
        if m and m.group(2) in REGIONS:
            seg, region = m.group(1).strip(), region or m.group(2)
        b = re.match(r"^(.*?)\s+bei\s+(.+)$", seg)
        if b and near is None:
            near = b.group(2).strip()
        if _RE_DISTRICT.match(seg):
            district = district or seg
        elif detail is None and seg:
            detail = seg
    place = names[0] if names else first
    return names or [first], place, detail, district, region, near


def entries(xml: bytes) -> list[Entry]:
    """Все записи перечня с отсылками; написания из отсылок — у тех, на кого ссылаются."""
    out = [parse_entry(r) for r in raw_entries(table_rows(xml))]
    camps = [e for e in out if not e.is_reference]
    for ref in (e for e in out if e.is_reference):
        target = resolve(ref.see, camps)
        if target is not None:
            for n in ref.names:
                if n not in target.aliases and n not in target.names:
                    target.aliases.append(n)
    return out


def _key(s: str) -> str:
    return re.sub(r"[^a-zäöüß0-9]+", " ", s.lower()).strip()


def resolve(target: str, camps: list[Entry]) -> Optional[Entry]:
    """Запись, на которую ссылается «siehe»: по всему тексту головы или по названию.

    «siehe Lublin» подходит к трём записям «Lublin/Polen, …» — берётся та, у
    которой нет главного лагеря (она и есть главный), а если таких несколько,
    первая.
    """
    want = _key(target)
    exact = [c for c in camps if _key(_RE_PERIOD.split(c.text, maxsplit=1)[0]).strip()
             .startswith(want) and _key(c.place) == _key(target.split(",")[0])]
    pool = exact or [c for c in camps if any(_key(n) == want for n in c.names)]
    if not pool:
        pool = [c for c in camps if _key(c.text).startswith(want)]
    if not pool:
        return None
    heads = [c for c in pool if not c.main_camp]
    return (heads or pool)[0]
