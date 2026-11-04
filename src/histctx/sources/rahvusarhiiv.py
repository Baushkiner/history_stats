"""Метрические книги приходов Эстонии: открытые данные Национального архива (Rahvusarhiiv).

Зачем. Подложка кирхшпилей (`sources/maaamet.py`) отвечает, к какому приходу
относилась деревня. Следующий вопрос — за какие годы книги этого прихода
сохранились, под каким шифром лежат и есть ли скан. Ответ — в описях
Национального архива Эстонии: метрические книги приходов хранятся в
Историческом архиве в Тарту (EAA) и в Таллинском городском архиве (TLA),
фонд на приход, книга на год или на несколько лет, у большинства — скан в
Saaga. Сбор 04.11.2026 нашёл 322 таких фонда: православных 160, лютеранских
142, старообрядческих 9, иудейских общин 6 (метрики раввината), католических
4, реформатский 1.

Откуда. `www.ra.ee/apps/opendata/` — снимок описей от 31.01.2020 в формате
apeEAD (EAD профиля Archives Portal Europe): 15 140 XML-файлов, по одному на
фонд. Перечня с названиями нет: страница каталога листает только имена
файлов, по сорок на странице (379 страниц). Название фонда стоит в начале
файла (`eadid`, `titleproper`), поэтому отбор идёт в три шага:

1. листинг каталога → имена файлов; из них берутся фонды архивов, где
   лежат приходы (`CANDIDATE_PREFIXES`);
2. первые 3 КБ каждого кандидата по заголовку Range → шифр и название
   фонда; приходом считается фонд, названный «… kogudus» (община) с
   признаком конфессии (`fond_confession`). Таллинский архив называет
   лютеранские приходы без признака — там конфессия выводится и запись
   это помечает;
3. файлы приходов скачиваются целиком и разбираются по единицам описания.

Что берётся из фонда:

* **метрические книги** — единицы описания с рождениями, браками и
  смертями (сводные «Meetrikaraamat», «Sünni-, abielu- ja surmameetrika» и
  раздельные: «Sünnimeetrika», «Sündinute ja ristitute nimekiri»,
  «Abielumeetrika», «Surmameetrika»…): шифр (`EAA.1255.1.108`), годы, ссылка
  на скан в Saaga (`ra.ee/dgs/_purl.php?shc=…`), если она есть;
* **смежные приходские книги** — персональные (Personaalraamat,
  hingeraamat), книги причастников и конфирмантов: шифр, годы, ссылка и
  название — в названии персональной книги стоят мызы и деревни, которые
  она охватывает («Personaalraamat. Kriimanni, Vana-Kuuste, Vastse-Kuuste»).

Что не берётся: персоналии — описи их не содержат, а сканы книг остаются в
Saaga (слой хранит ссылку). Протоколы, переписка, счета прихода в слой не
идут. Сводные фонды консисторий (копии книг многих приходов) приходом не
считаются и остаются несобранными — см. `docs/HARVEST.md`.

Права. «Avaandmetena avaldatud metaandmeid võib kasutada vastavalt CC0
litsentsile; failides viidatud ainese digikujutistele kehtib CC-BY-SA
litsents» — описи (метаданные) под CC0, сканы под CC BY-SA. Слой берёт
только описи и ссылается на сканы.

Вежливость. Корень `www.ra.ee` и его `robots.txt` отвечают 403 (NinjaFirewall),
каталог `/apps/opendata/` открыт; ИС AIS (`ais.ra.ee`) закрыта robots.txt
целиком и не запрашивается вовсе — ссылка на карточку фонда в AIS берётся
из самого XML. Обход идёт одним постоянным соединением с паузой между
запросами; всё скачанное кладётся в кэш и второй раз не запрашивается.
"""

from __future__ import annotations

import html
import http.client
import os
import re
import ssl
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..schema import ContextRecord, LayerSpec, clean_text

HOST = "www.ra.ee"
BASE_URL = f"https://{HOST}/apps/opendata/"
LISTING_PATH = "/apps/opendata/index.php/site/index"
FILE_PATH = "/apps/opendata/zip2/{name}"
FILE_URL = f"https://{HOST}" + FILE_PATH

SOURCE = "Rahvusarhiiv (Национальный архив Эстонии), открытые данные: описи фондов apeEAD"
LICENSE = (
    "метаданные описей — CC0 («metaandmeid võib kasutada vastavalt CC0 litsentsile»); "
    "сканы книг в Saaga — CC BY-SA, в слой не копируются, хранится ссылка"
)
SNAPSHOT = "31.01.2020"

PARISH_REGISTERS_EE = LayerSpec(
    slug="parish_registers_ee",
    title="Метрические книги приходов Эстляндии и северной Лифляндии",
    group="faith",
    source=SOURCE,
    license=LICENSE,
    description=(
        "Фонды православных, лютеранских, старообрядческих и католических приходов и "
        "иудейских общин в Национальном архиве Эстонии: за какие годы сохранились "
        "метрические книги, под каким шифром лежит "
        "каждая и есть ли скан в Saaga. Отвечает, в какой книге искать запись о рождении, "
        "браке или смерти предка из прихода, к которому относилась его деревня."
    ),
    url=BASE_URL,
    status="harvested",
    expected_rows=322,
)


class RahvusarhiivError(RuntimeError):
    """Каталог не ответил или файл не такой, каким его ждёт разбор."""


# --- листинг каталога ---------------------------------------------------------

# Сколько файлов и страниц было в каталоге 04.11.2026 — расхождение означает,
# что снимок переиздан, и его надо посмотреть, а не собрать молча.
EXPECTED_FILES = 15140
EXPECTED_PAGES = 379

# Архивы, в фондах которых лежат приходы: Исторический архив (EAA, Тарту) и
# Таллинский городской архив (TLA). Префикс имени файла → шифр архива.
# Советские фонды тех же архивов (`EAA_T…`, `RA_EAAT-…`), Государственный
# архив (ERA — учреждения после 1918 года) и уездные архивы (SAMA, LVMA,
# VAMA, LAMA) в отбор не идут: книги приходов лежат в фондах самих приходов
# в EAA. Шапки этих 7 000 файлов не просматривались — если там найдётся
# приход, его префикс добавляется сюда.
CANDIDATE_PREFIXES = ("RA_EAA", "RA_TLA")
_RE_FILE = re.compile(r'href="/apps/opendata/zip2/([^"/]+\.xml)"')
_RE_PAGE = re.compile(r"site/index\?page=(\d+)")


def parse_listing(page: str) -> list[str]:
    """Страница каталога → имена файлов в порядке страницы."""
    return list(dict.fromkeys(_RE_FILE.findall(page)))


def listing_pages(page: str) -> int:
    """Число страниц каталога — по самой дальней ссылке листалки."""
    numbers = [int(n) for n in _RE_PAGE.findall(page)]
    return max(numbers) if numbers else 1


def is_candidate(name: str) -> bool:
    """Файл фонда, в котором может лежать приход: `RA_EAA1255.xml`, `RA_TLA31.xml`.

    Сразу за префиксом — номер фонда: так отсекаются советские фонды тех же
    архивов, у которых за префиксом буква (`RA_EAAT-…`, `RA_TLAR-…`).
    """
    return any(re.match(re.escape(p) + r"\d", name) for p in CANDIDATE_PREFIXES)


# --- заголовок фонда ------------------------------------------------------------

HEAD_BYTES = 3072

_RE_EADID = re.compile(r"<eadid\b([^>]*)>([^<]*)</eadid>", re.S)
_RE_TITLEPROPER = re.compile(r"<titleproper\b[^>]*>(.*?)</titleproper>", re.S)
_RE_UNITDATE = re.compile(r"<archdesc\b.*?<unitdate\b([^>]*)>([^<]*)</unitdate>", re.S)
_RE_ATTR = re.compile(r'([\w:]+)="([^"]*)"')
_RE_LB = re.compile(r"<lb\s*/>")
_RE_TAG = re.compile(r"<[^>]+>")


@dataclass
class Head:
    """Шапка фонда: всё, что нужно, чтобы решить, приход ли это."""

    name: str                       # имя файла в каталоге
    code: Optional[str]             # шифр фонда: EAA.1255
    title: Optional[str]            # эстонское название: EELK Kambja kogudus
    title_alt: Optional[str]        # второе название (обычно немецкое)
    dates: Optional[str]            # крайние даты фонда, как в описи
    ais_url: Optional[str] = None   # карточка фонда в AIS — только ссылка

    @property
    def url(self) -> str:
        return FILE_URL.format(name=self.name)


def parse_head(name: str, data: bytes) -> Head:
    """Первые килобайты файла → шапка. Файл обрезан, поэтому — регулярками."""
    text = data.decode("utf-8", "replace")
    eadid = _RE_EADID.search(text)
    title = _RE_TITLEPROPER.search(text)
    unitdate = _RE_UNITDATE.search(text)
    parts = []
    if title:
        parts = [clean_text(html.unescape(_RE_TAG.sub(" ", p)))
                 for p in _RE_LB.split(title.group(1))]
        parts = [p for p in parts if p]
    attrs = dict(_RE_ATTR.findall(eadid.group(1))) if eadid else {}
    return Head(
        name=name,
        code=clean_text(eadid.group(2)) if eadid else None,
        title=parts[0] if parts else None,
        title_alt=parts[1] if len(parts) > 1 else None,
        dates=clean_text(unitdate.group(2)) if unitdate else None,
        ais_url=html.unescape(attrs["url"]) if attrs.get("url") else None,
    )


# --- конфессия по названию фонда --------------------------------------------------
# Приход в описи называется общиной: «EELK Kambja kogudus» (Эстонская
# евангелическо-лютеранская церковь), «Tartu Uspenski õigeusu kogudus»,
# «Tartu Rooma-Katoliku kogudus». Конфессия — по признаку в названии; фонд
# «… kogudus» без признака в слой не идёт и называется в отчёте сбора.

CONFESSIONS = (
    ("лютеранский", re.compile(r"\bEELK\b|evangeeliumi|luteri|lutheri|ev\.?-?lut|"
                               r"evangelse luterliku", re.I)),
    ("реформатский", re.compile(r"reformeeritud|reformiert", re.I)),
    ("православный", re.compile(r"õigeusu|EAÕK|EAOK|apostlik|kreeka-katoliku|ortodoks|"
                                r"aleksander[- ]nevski", re.I)),
    ("старообрядческий", re.compile(r"vanausu", re.I)),
    ("католический", re.compile(r"rooma-katoliku|roomakatoliku|katoliku", re.I)),
    # Еврейская община — не приход, но метрики раввината у неё есть
    # («Tartu Juudiusu kogudus»: рождения, браки, смерти с 1906 года).
    ("иудейский", re.compile(r"juudi|heebrea", re.I)),
)
# Как называть общину в заголовке и категории записи.
CATEGORIES = {
    "лютеранский": "лютеранский приход", "реформатский": "реформатский приход",
    "православный": "православный приход", "старообрядческий": "старообрядческая община",
    "католический": "католический приход", "иудейский": "иудейская община",
}
# «kogudus» бывает и концом слова: «Tallinna Toomkogudus» (Домский приход).
_RE_CONGREGATION = re.compile(r"kogudus\b|koguduse\b|Gemeinde\b", re.I)
# Не приходы, хотя слово «kogudus» в названии есть: союзы и управления
# церкви, консистории, братства, общества при приходе.
# «Tartu ülikooli kogudus» (университетский приход) — приход, хотя в нём
# есть «kooli»; «… Vaestekool», «… koguduse kool» — школы при приходе.
_RE_NOT_PARISH = re.compile(
    r"konsistoorium|praostkond|piiskop|sinod|kirikuvalitsus|vennaskond|\bselts|ühing|"
    r"\bliit\b|keskus|(?<!üli)kooli?\b|seminar|kogudusevalitsus|nõukogu|hoolekanne",
    re.I)


# Таллинский городской архив называет лютеранские приходы без признака:
# «Tallinna Niguliste Kogudus», «Tallinna Toomkogudus», «Harju - Madise
# kogudus», «Paldiski Nikolai kogudus». Фонд TLA «… kogudus» без слова другой
# веры считается лютеранским — и запись это помечает
# (`extra["confession_from"]`), потому что это вывод, а не слово источника.
TLA_LUTHERAN_NOTE = "в названии фонда TLA конфессии нет; приход TLA без признака другой веры"
# Полковые, флотские и госпитальные церкви русской армии в Таллине —
# православные; книги в их фондах ведены по-русски («Метрическая книга о
# родившихся… 91 пехотного Двинского полка»). Это тоже вывод — и он помечен.
TLA_MILITARY_NOTE = ("в названии фонда TLA конфессии нет; полковая, флотская или госпитальная "
                     "церковь русской армии — православная")
_RE_MILITARY = re.compile(r"polgu|sõjaväe|mereväe|sõjasadama|hospitali|haigla", re.I)
_RE_OTHER_FAITH = re.compile(
    r"baptist|metodist|adventist|juudi|heebrea|vennaste|nelipühi|katoliku|õigeusu|vanausu|"
    r"muhamedi|islami|karaiimi|kristlik|evangeeliumi kristlaste", re.I)


def fond_confession(title: Optional[str], code: Optional[str] = None) -> Optional[str]:
    """Конфессия прихода по названию фонда или None, если фонд не приход."""
    if not title or not _RE_CONGREGATION.search(title) or _RE_NOT_PARISH.search(title):
        return None
    for name, pattern in CONFESSIONS:
        if pattern.search(title):
            return name
    if (code or "").startswith("TLA.") and not _RE_OTHER_FAITH.search(title):
        return "православный" if _RE_MILITARY.search(title) else "лютеранский"
    return None


def confession_note(title: Optional[str], code: Optional[str]) -> Optional[str]:
    """Пояснение, если конфессия выведена, а не названа в фонде."""
    if not (code or "").startswith("TLA.") or any(p.search(title or "") for _, p in CONFESSIONS):
        return None
    return TLA_MILITARY_NOTE if _RE_MILITARY.search(title or "") else TLA_LUTHERAN_NOTE


# --- фонд целиком ----------------------------------------------------------------

_NS = "{urn:isbn:1-931666-22-9}"
_XLINK = "{http://www.w3.org/1999/xlink}"


@dataclass
class Unit:
    """Единица описания уровня «дело» (file): книга, папка, документ."""

    code: str                     # шифр: EAA.1255.1.108
    title: Optional[str]
    year_from: Optional[int]
    year_to: Optional[int]
    date_text: Optional[str]
    scan_url: Optional[str]
    path: tuple = ()              # заголовки разделов над единицей, сверху вниз


@dataclass
class Fond:
    code: str
    title: Optional[str]
    title_alt: Optional[str]
    dates: Optional[str]
    units: list = field(default_factory=list)
    ais_url: Optional[str] = None


_RE_NORMAL = re.compile(r"^(\d{4})(?:-\d\d(?:-\d\d)?)?(?:/(\d{4})(?:-\d\d(?:-\d\d)?)?)?$")
_RE_YEARS = re.compile(r"(?<!\d)(1[4-9]\d\d|20[0-2]\d)(?!\d)")


def unit_years(normal: Optional[str], text: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """Годы единицы: из `normal` («1834-01-01/1834-12-31»), иначе из текста даты."""
    m = _RE_NORMAL.match((normal or "").strip())
    if m:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        return (a, b) if a <= b else (b, a)
    years = [int(y) for y in _RE_YEARS.findall(text or "")]
    if years:
        return min(years), max(years)
    return None, None


def _did(c) -> tuple:
    did = c.find(f"{_NS}did")
    if did is None:
        return None, None, None, None, None
    titles = [clean_text("".join(t.itertext())) for t in did.findall(f"{_NS}unittitle")]
    titles = [t for t in titles if t]
    unitdate = did.find(f"{_NS}unitdate")
    dao = did.find(f"{_NS}dao")
    return (clean_text(did.findtext(f"{_NS}unitid")), titles[0] if titles else None,
            unitdate, dao, titles[1] if len(titles) > 1 else None)


def parse_fond(data: bytes) -> Fond:
    """Файл фонда apeEAD → фонд с единицами описания уровня «дело»."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RahvusarhiivError(f"файл фонда не разбирается как XML ({exc})") from exc
    archdesc = root.find(f"{_NS}archdesc")
    if archdesc is None:
        raise RahvusarhiivError("в файле нет archdesc: это не опись apeEAD")
    code, title, unitdate, _, _ = _did(archdesc)
    header = root.find(f"{_NS}eadheader/{_NS}eadid")
    titleproper = root.find(f"{_NS}eadheader/{_NS}filedesc/{_NS}titlestmt/{_NS}titleproper")
    title_alt = None
    if titleproper is not None:
        # «EELK Kambja kogudus<lb/>Evangelisch-Lutherische … zu Kamby»: второе
        # название идёт после разрыва строки.
        parts = [clean_text(titleproper.text)] + [clean_text(lb.tail) for lb in titleproper]
        parts = [p for p in parts if p]
        title = title or (parts[0] if parts else None)
        title_alt = parts[1] if len(parts) > 1 else None
    fond = Fond(code=code or (clean_text(header.text) if header is not None else ""),
                title=title, title_alt=title_alt,
                dates=clean_text(unitdate.text) if unitdate is not None else None,
                ais_url=header.get("url") if header is not None else None)

    def walk(c, path: tuple) -> None:
        unit_code, unit_title, unit_date, dao, _ = _did(c)
        if c.get("level") == "file":
            normal = unit_date.get("normal") if unit_date is not None else None
            text = clean_text(unit_date.text) if unit_date is not None else None
            year_from, year_to = unit_years(normal, text)
            fond.units.append(Unit(
                code=unit_code or "", title=unit_title, year_from=year_from, year_to=year_to,
                date_text=text, scan_url=dao.get(f"{_XLINK}href") if dao is not None else None,
                path=path))
        here = path + ((unit_title,) if unit_title and c.get("level") != "file" else ())
        for child in c.findall(f"{_NS}c"):
            walk(child, here)

    dsc = archdesc.find(f"{_NS}dsc")
    if dsc is not None:
        for c in dsc.findall(f"{_NS}c"):
            walk(c, ())
    return fond


# --- какие единицы — книги ----------------------------------------------------------
# Схема описи прихода EELK одна на все фонды: раздел «Kirikuraamatud ja
# nimistud» (церковные книги и списки), в нём подразделы — сводная метрика,
# рождения, конфирмация, браки, причастники, смерти, персональные книги. Но
# описи старых приходов и православные описи бывают плоскими, без разделов,
# поэтому вид книги определяется по её названию, а раздел служит проверкой:
# «распоряжения консистории об исправлениях в метрических книгах» лежат в
# разделе узаконений и книгой не считаются.

KIND_METRICAL = "метрическая книга"
KIND_BIRTHS = "рождения и крещения"
KIND_MARRIAGES = "браки"
KIND_DEATHS = "смерти и погребения"
KIND_PERSONAL = "персональная книга"
KIND_COMMUNION = "причастники"
KIND_CONFIRMATION = "конфирманты"
KIND_CONFESSION = "исповедные ведомости"

METRICAL_KINDS = (KIND_METRICAL, KIND_BIRTHS, KIND_MARRIAGES, KIND_DEATHS)
OTHER_BOOK_KINDS = (KIND_PERSONAL, KIND_COMMUNION, KIND_CONFIRMATION, KIND_CONFESSION)

# Порядок важен: первое совпадение решает. Сводная метрика проверяется раньше
# раздельных — в её названии есть и «sünni», и «surma».
_KIND_PATTERNS = (
    (KIND_METRICAL, re.compile(
        r"meetrikaraamat|метрическ|sünni-,?\s*abielu-?|sünni-\s*ja\s*surma|abielu-\s*ja\s*surma|"
        r"kirchenbuch|^meetrika|sündinute,?\s*(?:laulatatute|abiellunute)|"
        r"ristitute,?\s*(?:laulatatute|abiellunute)", re.I)),
    (KIND_BIRTHS, re.compile(r"sünnimeetrika|sündinute|ristitute|sündinud|ristitud|"
                             r"ristimis(?:raamat|meetrika)|taufregister|getaufte", re.I)),
    (KIND_MARRIAGES, re.compile(r"abielumeetrika|abiellunute|laulatatute|kihlatute|"
                                r"kuulutatute|laulatus(?:raamat|meetrika)|trauregister|"
                                r"getraute|proklamierte", re.I)),
    (KIND_DEATHS, re.compile(r"surmameetrika|surnute|maetute|matmis(?:raamat|meetrika)|"
                             r"totenregister|sterberegister|verstorbene|begrabene", re.I)),
    (KIND_PERSONAL, re.compile(r"personaalraamat|hingeraamat|hingede|seelenregister|"
                               r"personalbuch|kommunikantenbuch der|perekonnaraamat", re.I)),
    (KIND_COMMUNION, re.compile(r"armulaualiste|kommunikant", re.I)),
    (KIND_CONFIRMATION, re.compile(r"leeritatute|leerilaste|leeri(?:raamat|nimekiri)|"
                                   r"konfirm", re.I)),
    # «Pihiliste nimekiri» православной описи — исповедные ведомости.
    (KIND_CONFESSION, re.compile(r"pihili|pihila|pihiraamat|pihtimis|исповедн", re.I)),
)
# Разделы описи, в которых лежат книги прихода.
_RE_BOOK_SECTION = re.compile(r"kirikuraamat|meetrika|nimistud|personaalraamat|"
                              r"kirchenb|metrik", re.I)
# Признаки дела о книгах, а не самой книги: распоряжения, переписка, справки,
# свидетельства, выписки.
_RE_NOT_BOOK = re.compile(r"\basjus\b|korraldus|eeskiri|teadaanne|kirjavahetus|"
                          r"tunnistus|teatis|väljavõte|register\s+meetrika|"
                          r"\bload\b|parandus", re.I)
_GENERIC_TITLES = {"meetrikaraamat", "sünnimeetrika", "abielumeetrika", "surmameetrika",
                   "sünni-, abielu- ja surmameetrika", "personaalraamat"}


def unit_kind(unit: Unit) -> Optional[str]:
    """Вид приходской книги или None, если единица — не книга прихода."""
    title = unit.title or ""
    if not title or _RE_NOT_BOOK.search(title):
        return None
    in_section = any(_RE_BOOK_SECTION.search(p or "") for p in unit.path)
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(title):
            if in_section or kind == KIND_METRICAL or title.lower().startswith(
                    ("sünni", "abielu", "surma", "personaalraamat", "hingeraamat")):
                return kind
            return None
    if in_section:
        # Книга без говорящего названия в разделе книг («Raamat», «Vihik»):
        # вид — по подразделу над ней.
        for part in reversed(unit.path):
            for kind, pattern in _KIND_PATTERNS:
                if pattern.search(part or ""):
                    return kind
    return None


def year_ranges(units: list) -> list[tuple[int, int]]:
    """Покрытые годы одним списком непересекающихся отрезков."""
    spans = sorted((u.year_from, u.year_to) for u in units
                   if u.year_from is not None and u.year_to is not None)
    out: list[list[int]] = []
    for a, b in spans:
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def format_ranges(ranges: list[tuple[int, int]]) -> str:
    """[(1719, 1793), (1795, 1926)] → «1719–1793, 1795–1926»."""
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in ranges)


def gaps(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Пропуски между отрезками: годы, за которые книг в описи нет."""
    return [(ranges[i][1] + 1, ranges[i + 1][0] - 1) for i in range(len(ranges) - 1)]


@dataclass
class Books:
    """Книги фонда, разложенные по видам."""

    metrical: list = field(default_factory=list)       # [(Unit, вид)]
    other: list = field(default_factory=list)

    @property
    def metrical_units(self) -> list:
        return [u for u, _ in self.metrical]


def fond_books(fond: Fond) -> Books:
    books = Books()
    for unit in fond.units:
        kind = unit_kind(unit)
        if kind in METRICAL_KINDS:
            books.metrical.append((unit, kind))
        elif kind in OTHER_BOOK_KINDS:
            books.other.append((unit, kind))
    return books


def book_entry(unit: Unit, kind: str) -> dict:
    """Книга для `extra["books"]`: шифр, годы, вид, скан, название, если оно говорит."""
    entry = {"shc": unit.code, "kind": kind}
    if unit.year_from is not None:
        entry["years"] = (str(unit.year_from) if unit.year_from == unit.year_to
                          else f"{unit.year_from}–{unit.year_to}")
    if unit.scan_url:
        entry["scan"] = unit.scan_url
    if unit.title and unit.title.lower() not in _GENERIC_TITLES:
        entry["title"] = unit.title
    return entry


# --- сеть ---------------------------------------------------------------------------

class Client:
    """Один постоянный HTTPS-канал к каталогу: пауза, повтор на 429/5xx, кэш.

    Новое соединение через прокси среды стоит 0,4–0,7 секунды на одно только
    рукопожатие, а сам ответ на 3 КБ — 0,14 секунды. Первый обход шапок
    через `urllib` (соединение на запрос, пауза 1 с) шёл по 3,5 секунды на
    файл; с постоянным соединением и паузой 0,5 с — по 0,5 секунды, и 4 034
    шапки берутся за 35–40 минут вместо четырёх часов. Соединение держится
    открытым (keep-alive) и пересоздаётся только после сбоя. Прокси берётся
    из `HTTPS_PROXY`, как его взял бы `urllib`.
    """

    def __init__(self, cache_dir: Path, *, pause_sec: float = 0.5, attempts: int = 4,
                 timeout: int = 120) -> None:
        self.cache_dir = Path(cache_dir)
        self.pause_sec = pause_sec
        self.attempts = attempts
        self.timeout = timeout
        self._last = 0.0
        self._conn: Optional[http.client.HTTPSConnection] = None
        self.requests = 0

    def _connect(self) -> http.client.HTTPSConnection:
        context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            parts = urllib.parse.urlsplit(proxy)
            conn = http.client.HTTPSConnection(parts.hostname, parts.port or 80,
                                               context=context, timeout=self.timeout)
            conn.set_tunnel(HOST, 443)
        else:
            conn = http.client.HTTPSConnection(HOST, 443, context=context, timeout=self.timeout)
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get(self, path: str, *, head_bytes: Optional[int] = None) -> bytes:
        headers = {"User-Agent": USER_AGENT}
        if head_bytes:
            headers["Range"] = f"bytes=0-{head_bytes - 1}"
        error: Optional[Exception] = None
        for attempt in range(self.attempts):
            self._last = wait_for_pause(self._last, self.pause_sec)
            self.requests += 1
            try:
                if self._conn is None:
                    self._conn = self._connect()
                self._conn.request("GET", path, headers=headers)
                response = self._conn.getresponse()
                body = response.read()
            except (http.client.HTTPException, OSError) as exc:
                self.close()
                error = exc
                time.sleep(self.pause_sec * 4 * (attempt + 1))
                continue
            if response.status in (200, 206):
                return body
            if response.status in RETRY_CODES:
                error = RahvusarhiivError(f"HTTP {response.status}")
                time.sleep(self.pause_sec * 4 * (attempt + 1))
                continue
            raise RahvusarhiivError(f"https://{HOST}{path}: HTTP {response.status}")
        raise RahvusarhiivError(f"https://{HOST}{path}: не ответил за {self.attempts} "
                                f"попыток ({error})")

    def cached(self, name: str, path: str, *, head_bytes: Optional[int] = None,
               refresh: bool = False) -> bytes:
        """Ответ из кэша или из сети; в кэш пишется только целый ответ."""
        target = self.cache_dir / name
        if target.exists() and not refresh:
            return target.read_bytes()
        data = self.get(path, head_bytes=head_bytes)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return data

    def listing_page(self, page: int, *, refresh: bool = False) -> str:
        path = LISTING_PATH + (f"?page={page}" if page > 1 else "")
        return self.cached(f"listing/page-{page:04d}.html", path,
                           refresh=refresh).decode("utf-8", "replace")

    def head(self, name: str) -> bytes:
        return self.cached(f"heads/{name}", FILE_PATH.format(name=name), head_bytes=HEAD_BYTES)

    def fond(self, name: str) -> bytes:
        return self.cached(f"fonds/{name}", FILE_PATH.format(name=name))


# --- сведение фонда с кирхшпилем ---------------------------------------------------
# Фонд назван по приходу: «EELK Kambja kogudus» → Kambja, «EELK Tartu Maarja
# kogudus» → Tartu-Maarja (так кирхшпиль назван в слое Maa- ja Ruumiamet).
# Городской приход назван по городу и храму: «EELK Tallinna Oleviste
# kogudus», «EELK Tartu Jaani kogudus». Город — не кирхшпиль: точкой служит
# центр города, кирхшпилем — тот, в полигоне которого город лежит (Тарту — в
# Tartu-Maarja, Нарва — в Vaivara, Хаапсалу — в Ridala). Валга в полигоны
# кирхшпилей не попадает: её приход остаётся с точкой города и без кирхшпиля.

# Центры городов (ратушная площадь или старый центр), до сотой градуса. Это
# факт о городе, а не о храме: точка записи городского прихода помечена
# `place_level`. Губерния и уезд записаны только для Валги — у остальных
# они берутся у кирхшпиля, в котором лежит город.
TOWNS = {
    "Tallinn": (59.4372, 24.7453, ("Tallinna", "Tallinn", "Kopli")),
    "Nõmme": (59.3845, 24.6862, ("Nõmme",)),
    "Tartu": (58.3801, 26.7224, ("Tartu",)),
    "Pärnu": (58.3859, 24.4971, ("Pärnu",)),
    "Viljandi": (58.3639, 25.5900, ("Viljandi",)),
    "Narva": (59.3772, 28.1903, ("Narva",)),
    "Haapsalu": (58.9431, 23.5414, ("Haapsalu",)),
    "Kuressaare": (58.2481, 22.5039, ("Kuressaare", "Arensburgi")),
    "Paide": (58.8856, 25.5572, ("Paide",)),
    "Rakvere": (59.3464, 26.3558, ("Rakvere",)),
    "Valga": (57.7769, 26.0470, ("Valga",)),
    "Võru": (57.8339, 27.0194, ("Võru",)),
    "Paldiski": (59.3567, 24.0531, ("Paldiski",)),
    "Põltsamaa": (58.6526, 25.9705, ("Põltsamaa",)),
    "Kärdla": (58.9978, 22.7496, ("Kärdla",)),
    "Narva-Jõesuu": (59.4590, 28.0410, ("Narva-Jõesuu",)),
    "Mustvee": (58.8486, 26.9461, ("Mustvee",)),
    "Tapa": (59.2606, 25.9586, ("Tapa",)),
    "Sillamäe": (59.3997, 27.7631, ("Sillamäe",)),
    "Antsla": (57.8256, 26.5406, ("Antsla",)),
    "Kilingi-Nõmme": (58.1500, 24.9631, ("Kilingi", "Kilingi-Nõmme")),
    "Elva": (58.2225, 26.4211, ("Elva",)),
    "Sindi": (58.4006, 24.6672, ("Sindi",)),
    # Каласте на Чудском озере: мыза Kallaste в наборе — тёзка под Рынгу.
    "Kallaste": (58.6597, 27.1606, ("Kallaste",)),
    # Печоры в 1917 году — Псковская губерния: кирхшпилей Эстляндии и
    # Лифляндии там нет, губерния и уезд записаны прямо.
    "Petseri": (57.8128, 27.6083, ("Petseri",)),
}
TOWN_REGIONS = {"Valga": ("Лифляндская губерния", "Валкский уезд"),
                "Petseri": ("Псковская губерния", "Псковский уезд")}

# Название прихода в фонде → кирхшпиль слоя 1917 года, где они расходятся.
# Заполнено по сбору 04.11.2026: каждое несведённое название проверено
# глазами, сюда попало только то, где кирхшпиль назван иначе.
PARISH_ALIASES = {
    "järva-peetri": "Peetri",           # в слое 1917 года просто Peetri
    "pärnu-jakobi": "Pärnu-Jaagupi",    # Jakobi — немецкая форма имени Jaagup
}

_RE_CONFESSION_WORDS = re.compile(
    r"\bEELK\b|\bEAÕK\b|\bEAOK\b|\bapostlik-?\b|\bõigeusu\b|\bvanausuliste\b|"
    r"\brooma-katoliku\b|\bkatoliku\b|\bkogudus\b|\bkoguduse\b|\bev\.?-?lut\.?\b|"
    r"\bjuudiusu\b|\bjuudi\b", re.I)


def parish_place(title: Optional[str]) -> Optional[str]:
    """Название фонда → название прихода: «EELK Tartu Maarja kogudus» → «Tartu Maarja»."""
    if not title:
        return None
    # «Eesti Apostliku Õigeusu Kiriku Tallinna Kaasani Kogudus», «Rooma-Katoliku
    # Kiriku Tallinna Peeter-Pauli Kogudus», «Vene Vanausuliste Tallinna Kogudus»:
    # церковь и народ впереди названия — не место.
    text = re.sub(r"^(?:Eesti\s+)?(?:Apostliku\s+Õigeusu|Evangeelse\s+Luterliku|"
                  r"Evangeeliumi\s+Luteri\s+Usu|Rooma-Katoliku)\s+Kiriku\s+", "", title,
                  flags=re.I)
    text = re.sub(r"^Vene\s+", "", text)
    text = _RE_CONFESSION_WORDS.sub(" ", text)
    text = re.sub(r"\(.*?\)", " ", text)
    # «EAÕK Jaama kogudus Vasknarva vallas»: уточнение «в волости X» —
    # отдельно, в `parish_hint`.
    text = re.sub(r"\s+\S+\s+vallas\b.*$", " ", text)
    return clean_text(text.strip(" ,.-"))


def parish_hint(title: Optional[str]) -> Optional[str]:
    """Уточнение места из названия фонда: «… kogudus Vasknarva vallas» → «Vasknarva»."""
    m = re.search(r"(\S+)\s+vallas\b", title or "")
    return m.group(1) if m else None


def place_key(text: Optional[str]) -> str:
    """Ключ сравнения: строчные, пробел и дефис — одно и то же."""
    return re.sub(r"[\s_-]+", "-", (text or "").strip().lower())


@dataclass
class Match:
    """Где фонд на карте и почему именно там."""

    kind: str                       # кирхшпиль | город | мыза | не сведён
    place: Optional[str]            # название прихода из фонда
    parish: Optional[str] = None    # кирхшпиль 1917 года (NIMI)
    town: Optional[str] = None
    manor: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    region: Optional[str] = None
    district: Optional[str] = None
    note: Optional[str] = None      # что за точка
    candidates: list = field(default_factory=list)   # если не сведён: что предлагалось


@dataclass
class ParishIndex:
    """Кирхшпили, города и мызы для сведения фондов по названию.

    Порядок проверок — от надёжного к приблизительному:

    1. название целиком — кирхшпиль 1917 года (или его другое имя из
       `PARISH_ALIASES`): точка — центр территории кирхшпиля;
    2. первое слово — город из `TOWNS`: точка — центр города, кирхшпиль —
       тот, в полигоне которого город лежит;
    3. начало названия из нескольких слов — кирхшпиль;
    4. православные приходы названы по деревне или мызе, часто двойным
       именем: каждая половина и уточнение «X vallas» проверяются и как
       кирхшпиль, и как мыза с единственным таким именем. Мыза, стоящая в
       названном кирхшпиле, — лучший ответ (точка мызы). Кирхшпиль первой
       половиной — тоже ответ: «Võnnu-Kärsa» лежит в Вынну, хотя
       единственная мыза Kärsa в наборе стоит в Вяйке-Маарья (деревни Кярса
       под Вынну среди мыз набора нет). Когда половины спорят, а кирхшпиль
       назван второй, — «Seli-Tõstamaa» (кирхшпиль Тыстамаа, мыза Seli — в
       Юуру) и «Pootsi-Kõpu» (мыза Pootsi — в Тыстамаа, Kõpu — кирхшпиль в
       Вильяндимаа или деревня-тёзка) — выбрать по данным нельзя: запись
       остаётся без точки, оба кандидата — в `candidates`;
    5. одно имя, совпавшее с единственной мызой («EAÕK Angerja kogudus» →
       мыза Angerja), — точка мызы с отдельной пометкой: в наборе только
       мызы, и одноимённая деревня в другом уезде возможна (так «Alajõe» —
       деревня на Чудском озере, а мыза Alajõe в наборе — в кирхшпиле
       Maarja-Magdaleena).

    Не сведённое ни одним шагом остаётся без точки, с пометкой.
    """

    parishes: dict                  # ключ → Parish
    towns: dict                     # ключ формы названия → город
    manors: dict                    # ключ эстонского имени мызы → [Feature]
    parish_of: object = None        # (широта, долгота) → Parish; ставит build

    @classmethod
    def build(cls, parishes: list, manor_features: list) -> "ParishIndex":
        from .maaamet import contains, wgs84_to_lest97

        by_key = {place_key(p.name): p for p in parishes}
        towns = {}
        for town, (_, _, forms) in TOWNS.items():
            for form in forms:
                towns[place_key(form)] = town
        manors: dict = {}
        for feature in manor_features:
            # Только эстонское имя: немецкие («Neuhof», «Annenhof») повторяются
            # десятками и дали бы ложные совпадения.
            if feature.get("NIMI"):
                manors.setdefault(place_key(feature.get("NIMI")), []).append(feature)

        def parish_of(lat: float, lon: float):
            x, y = wgs84_to_lest97(lat, lon)
            return next((p for p in parishes if contains(p.polygons, x, y)), None)

        return cls(parishes=by_key, towns=towns, manors=manors, parish_of=parish_of)

    def _parish(self, name: str):
        key = place_key(name)
        alias = PARISH_ALIASES.get(key)
        return self.parishes.get(place_key(alias) if alias else key)

    def _unique_manor(self, name: str):
        found = self.manors.get(place_key(name)) or []
        return found[0] if len(found) == 1 else None

    @staticmethod
    def _parish_match(place: str, parish) -> Match:
        return Match(kind="кирхшпиль", place=place, parish=parish.name, lat=parish.lat,
                     lon=parish.lon, region=parish.region, district=parish.uezd,
                     note=f"центр территории кирхшпиля {parish.name}, а не храм")

    def _manor_match(self, place: str, feature, parish) -> Match:
        from .maaamet import COUNTY_UEZD, GOVERNORATES
        lat, lon = self._manor_point(feature)
        return Match(kind="мыза", place=place,
                     parish=parish.name if parish else feature.get("KIHELKOND"),
                     manor=feature.get("NIMI"), lat=lat, lon=lon,
                     region=parish.region if parish else GOVERNORATES.get(
                         feature.get("KUBERMANG") or ""),
                     district=parish.uezd if parish else COUNTY_UEZD.get(
                         feature.get("MAAKOND") or ""),
                     note=f"мызный центр {feature.get('NIMI')}, по которому назван приход, "
                          "а не храм")

    @staticmethod
    def _manor_point(feature) -> tuple[float, float]:
        from .maaamet import lest97_to_wgs84
        lat, lon = lest97_to_wgs84(*feature.point)
        return round(lat, 6), round(lon, 6)

    def match(self, title: Optional[str]) -> Match:
        place = parish_place(title)
        if not place:
            return Match(kind="не сведён", place=None)
        tokens = place.split()
        parish = self._parish(place)
        if parish is not None:
            return self._parish_match(place, parish)
        town = self.towns.get(place_key(tokens[0]))
        if town is not None:
            lat, lon, _ = TOWNS[town]
            parish = self.parish_of(lat, lon)
            region, district = TOWN_REGIONS.get(town, (None, None))
            return Match(kind="город", place=place, parish=parish.name if parish else None,
                         town=town, lat=lat, lon=lon,
                         region=parish.region if parish else region,
                         district=parish.uezd if parish else district,
                         note=f"центр города {town}, а не храм")
        for n in range(len(tokens) - 1, 0, -1):
            parish = self._parish(" ".join(tokens[:n]))
            if parish is not None:
                return self._parish_match(place, parish)

        names = [part for part in tokens[0].split("-") if part]
        hint = parish_hint(title)
        kirchs = [(n, self._parish(n)) for n in names]
        kirchs = [(n, k) for n, k in kirchs if k is not None]
        manors = [self._unique_manor(place)] + [self._unique_manor(n) for n in names]
        manors = list({id(f): f for f in manors if f is not None}.values())
        located = [(f, self.parish_of(*self._manor_point(f))) for f in manors]
        for feature, parish in located:
            if parish is not None and any(k is parish for _, k in kirchs):
                return self._manor_match(place, feature, parish)
        if kirchs and (not located or kirchs[0][0] == names[0]):
            return self._parish_match(place, kirchs[0][1])
        if hint:
            parish = self._parish(hint)
            if parish is not None:
                return self._parish_match(place, parish)
            feature = self._unique_manor(hint)
            if feature is not None:
                return self._manor_match(place, feature,
                                         self.parish_of(*self._manor_point(feature)))
        where = {p.name if p is not None else f.get("KIHELKOND") for f, p in located}
        if located and not kirchs and len(where) == 1:
            feature, parish = located[0]
            match = self._manor_match(place, feature, parish)
            if len(located) == 1:
                # Одно имя — одна мыза: деревня-тёзка возможна.
                match.kind = "мыза по имени"
                match.note = (f"мызный центр {feature.get('NIMI')}: приход сведён с мызой "
                              "только по имени, деревня-тёзка в другом месте возможна; не храм")
            return match
        if located:
            return Match(kind="не сведён", place=place, candidates=(
                [f"кирхшпиль {k.name}" for _, k in kirchs]
                + [f"мыза {f.get('NIMI')} (кирхшпиль {p.name if p else f.get('KIHELKOND')})"
                   for f, p in located]))
        return Match(kind="не сведён", place=place)


# --- запись схемы ------------------------------------------------------------------

def _plural_books(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "метрическая книга"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "метрические книги"
    return "метрических книг"


def fond_record(head: Head, confession: str, fond: Fond, match: Match,
                spec: LayerSpec = PARISH_REGISTERS_EE) -> ContextRecord:
    """Фонд прихода → запись: годы метрических книг, шифры, сканы.

    Дата записи — первый и последний год метрических книг фонда (оба конца
    измерены, точность `year`); пропуски — в `extra["metrical"]["gaps"]`.
    Фонд без метрических книг остаётся в слое без даты (`no_registers`):
    смежные книги (персональные, причастников) в нём бывают, а его
    существование — тоже ответ на вопрос «где искать».
    """
    books = fond_books(fond)
    metrical = books.metrical_units
    ranges = year_ranges(metrical)
    holes = gaps(ranges)
    scans = sum(1 for u in metrical if u.scan_url)
    place = match.place or parish_place(fond.title) or fond.code
    fond_title = fond.title or head.title or fond.code

    extra: dict = {
        "fond": fond.code,
        "fond_title": fond_title,
        "confession": confession,
        "match": match.kind,
        "snapshot": SNAPSHOT,
    }
    if fond.title_alt or head.title_alt:
        extra["fond_title_alt"] = fond.title_alt or head.title_alt
    note = confession_note(fond_title, head.code)
    if note:
        extra["confession_from"] = note
    if fond.dates:
        extra["fond_dates"] = fond.dates
    for key in ("parish", "town", "manor"):
        if getattr(match, key):
            extra[key] = getattr(match, key)
    if match.note:
        extra["point"] = match.note
    extra["metrical"] = {
        "units": len(metrical),
        "scans": scans,
        "years": format_ranges(ranges),
    }
    if holes:
        extra["metrical"]["gaps"] = format_ranges(holes)
    other: dict = {}
    for unit, kind in books.other:
        entry = other.setdefault(kind, {"units": 0, "scans": 0, "_units": []})
        entry["units"] += 1
        entry["scans"] += 1 if unit.scan_url else 0
        entry["_units"].append(unit)
    for entry in other.values():
        entry["years"] = format_ranges(year_ranges(entry.pop("_units")))
    if other:
        extra["other_books"] = other
    # Книги — по годам: метрические, затем смежные; так список читается как
    # «за какой год какая книга», а не в порядке описи.
    def by_year(pair):
        unit, kind = pair
        return (unit.year_from if unit.year_from is not None else 9999, unit.code)

    extra["books"] = [book_entry(u, k) for u, k in
                      sorted(books.metrical, key=by_year) + sorted(books.other, key=by_year)]
    if fond.ais_url or head.ais_url:
        extra["ais"] = fond.ais_url or head.ais_url

    if match.candidates:
        extra["candidates"] = match.candidates
    if match.kind == "кирхшпиль":
        confidence = "parish_centroid"
    elif match.kind in ("город", "мыза"):
        confidence = "place_level"
    elif match.kind == "мыза по имени":
        confidence = "manor_name_match"
    else:
        confidence = "parish_unmatched"
    if not metrical:
        confidence = "no_registers"

    category = CATEGORIES.get(confession, f"{confession} приход")
    unit = "общины" if category.endswith("община") else "прихода"
    label = f"Метрические книги {unit} {place}" if metrical else f"Фонд {unit} {place}"
    return spec.new_record(
        title=f"{label} ({fond_title})",
        category=category,
        lat=match.lat, lon=match.lon,
        place_text=", ".join(x for x in (
            match.parish and f"кирхшпиль {match.parish}",
            match.town and f"город {match.town}") if x) or None,
        region=match.region,
        district=match.district,
        year_from=ranges[0][0] if ranges else None,
        year_to=ranges[-1][1] if ranges else None,
        date_precision="year" if ranges else "unknown",
        period_raw=format_ranges(ranges) or None,
        summary=fond_summary(category, place, len(metrical), scans, ranges, holes, fond.code,
                             books),
        url=head.url,
        source_id=fond.code,
        confidence=confidence,
        extra=extra,
    )


def fond_summary(category: str, place: str, n: int, scans: int, ranges: list,
                 holes: list, code: str, books: Books) -> str:
    """Своя фраза из полей описи."""
    head = f"{category.capitalize()} {place}"
    if n:
        years = (f"{ranges[0][0]}–{ranges[-1][1]} годы" if ranges[0][0] != ranges[-1][1]
                 else f"{ranges[0][0]} год")
        text = f"{head}: {n} {_plural_books(n)} за {years}"
        if holes:
            text += f" (пропуски: {format_ranges(holes)})"
        text += f"; со сканом в Saaga — {scans}" if scans else "; сканов в Saaga нет"
    else:
        text = f"{head}: метрических книг в описи нет"
        if books.other:
            text += f", смежных приходских книг — {len(books.other)}"
    return f"{text}. Фонд {code} Национального архива Эстонии."


def parish_summary(record: ContextRecord) -> dict:
    """Запись → сводка фонда для подложки кирхшпилей."""
    extra = record.extra or {}
    out = {
        "fond": extra.get("fond"),
        "title": extra.get("fond_title"),
        "confession": extra.get("confession"),
        "years": extra.get("metrical", {}).get("years") or None,
        "books": extra.get("metrical", {}).get("units", 0),
        "scans": extra.get("metrical", {}).get("scans", 0),
        "url": record.url,
    }
    if extra.get("match") != "кирхшпиль":
        # Городской приход, приход при мызе или сведённый по одному имени —
        # подложке это надо знать: книги такого фонда не обязательно
        # покрывают все деревни кирхшпиля.
        out["match"] = extra.get("match")
    if extra.get("town"):
        out["town"] = extra["town"]
    if extra.get("manor"):
        out["manor"] = extra["manor"]
    return {k: v for k, v in out.items() if v is not None}


_MATCH_ORDER = {"кирхшпиль": 0, "город": 1, "мыза": 2, "мыза по имени": 3}


def summary_order(summary: dict) -> tuple:
    """Порядок фондов в подложке: свой приход, городские, при мызах, по имени."""
    return (_MATCH_ORDER.get(summary.get("match", "кирхшпиль"), 9),
            summary.get("confession") != "лютеранский", summary.get("fond") or "")
