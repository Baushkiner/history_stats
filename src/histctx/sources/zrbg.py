"""Перечень гетто ZRBG («Ghetto-Liste», на 01.08.2014): даты открытия и ликвидации.

Что это. Закон о пенсиях за работу в гетто (Gesetz zur Zahlbarmachung von
Renten aus Beschäftigungen in einem Ghetto, ZRBG, 2002) потребовал от
пенсионного ведомства Германии (Deutsche Rentenversicherung) решать, было ли
в данном месте и в данное время гетто. Для этого ведомство ведёт служебный
перечень: место с вариантами написания, территория оккупации и нынешняя
область, дата открытия и дата ликвидации гетто до дня, депортации,
примечания и источник сведений (энциклопедия USHMM 2008 года, «Encyclopedia
of Jewish Life» 2001 года, справочники по Транснистрии и Венгрии). Копию
перечня на 01.08.2014 выложила израильская организация Aviv
(`aviv.org.il/pdf/Ghetto-List-1.8.2014.pdf`, 180 страниц, `robots.txt`
сайта разрешает всё).

Права. Служебный перечень ведомства, условия использования не заявлены —
**права не выяснены**. Берутся факты: место, территория, даты, пункты
депортации, номер записи и источник, на который она ссылается. Примечания
(«Bemerkungen») — изложение составителей, иногда с числом убитых; они не
копируются: из них берутся только пометки — «не гетто в смысле закона»,
«открытое гетто», «дата взята у соседнего гетто».

Как устроен файл. Таблица из Word на альбомных страницах (страница повёрнута
на 90°), девять колонок: Nr., Ort, Gebiet, Eröffnung, Liquidierung,
Deportationen, Bemerkungen, Quelle, Datum der Ergänzung. Текст в ячейках
выровнен по вертикали по центру, поэтому строки таблицы по одному тексту не
разделить: промежуток между строками таблицы всего на полпункта больше
межстрочного. Разделяют их линии сетки — тонкие прямоугольники в потоке
страницы. Поэтому разбор берёт:

* слова с рамками — у `pdftotext -bbox` (poppler): он раскладывает строку
  `TJ` с большими отступами на отдельные слова, а `pypdf` отдаёт такую
  строку одним куском — «Transnistrien 30.08.1941 18.03.1944» из трёх ячеек;
* линии сетки — у `pypdf` из потока страницы (`re` шириной 0,48 пт).

Обе программы нужны только сборщику; сам разбор — чистые функции над
словами и линиями (`page_cells`, `table_entries`) и проверяется тестом без
PDF. Строка таблицы, разорванная переносом страницы, продолжается первой
строкой следующей страницы без номера записи — она подклеивается к
предыдущей (замер 04.11.2026: 102 такие строки; одна запись без номера,
Szydlowiec, стоит посреди страницы и остаётся отдельной).

Редакция. Взята редакция на 01.08.2014: в ней девять колонок и номера
записей. Есть и новая — на 05.12.2022 (`aviv.org.il/wp-content/uploads/
2024/07/zrbg-Geto-liste.pdf`, 88 страниц, найдена 04.11.2026): в ней около
сотни записей прибавилось — гетто в самой Румынии и места депортации рома
1942 года в Транснистрии (после заключения 2016 года по заказу Минфина), —
зато в ней только четыре колонки (место, территория, две даты): ни номеров,
ни депортаций, ни примечаний, ни источников, и записей «не гетто» нет. Сетка
там нарисована контурами, а не прямоугольниками, и этот разбор её не
читает; сверка двух редакций — следующий шаг.

Даты. В основном «ДД.ММ.ГГГГ»; встречаются «01. 09.1941», «16.04 1944»,
«24. Juli 1941», «Ende Mai 1944», «Sep 41», «??.??.1942», «1942»,
опечатки «131.12.1942» и «31.12.19441» (берётся «31.12.1942» и
«31.12.1944» с пометкой) и «./.» — даты нет. Многие даты открытия — не
местные, а правовые: в шапке перечня названы даты начала гетто «по
распоряжениям» для Генерал-губернаторства (01.01.1940), Галиции
(06.09.1941), Белостока и рейхскомиссариата «Остланд» (02.08.1941),
рейхскомиссариата «Украина» (05.09.1941); у Транснистрии вся запись —
30.08.1941–18.03.1944 (румынская администрация), у Венгрии —
16.04.1944–13.07.1944. Такая дата помечается (`rule_dates`): гетто в
местечке могло открыться позже, а дата годится как граница, а не как день.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..schema import clean_text

PDF_URL = "https://www.aviv.org.il/pdf/Ghetto-List-1.8.2014.pdf"
ROBOTS_URL = "https://www.aviv.org.il/robots.txt"
# Сверено 04.11.2026: Last-Modified 20.11.2014, размер и md5 файла. Другой
# файл по тому же адресу — новая редакция перечня, её надо смотреть глазами.
PDF_SIZE = 1_327_028
PDF_MD5 = "06dd3352524f9e01636f51dd412d71ed"
PDF_PAGES = 180
STAND = "01.08.2014"
CACHE_NAME = "Ghetto-List-1.8.2014.pdf"

LICENSE = (
    "права не выяснены: служебный перечень Deutsche Rentenversicherung (копия "
    "организации Aviv); взяты место, территория и даты со ссылкой, примечания "
    "составителей не копируются"
)

COLUMNS = ("nr", "place", "territory", "opened", "liquidated", "deportations",
           "remarks", "source", "updated")
HEADER = ("Nr.", "Ort:", "Gebiet:", "Eröffnung:", "Liquidierung:", "Deportationen:",
          "Bemerkungen:", "Quelle:", "Datum der Ergänzung")

# Записей в перечне — замер 04.11.2026: 2 238 записей в 2 340 строках
# таблицы, 102 строки — продолжения записей через перенос страницы.
EXPECTED_ENTRIES = 2238

# Линия сетки: прямоугольник тоньше пункта. Строку таблицы делит линия во
# всю ширину таблицы (823 пт), колонку — линия выше заголовка.
RULE_WIDTH = 1.0
ROW_RULE_MIN = 400.0
COL_RULE_MIN = 50.0


class ZrbgError(RuntimeError):
    """Файл не тот или таблица устроена не так, как ожидает разбор."""


# --- слова и сетка ----------------------------------------------------------

@dataclass(frozen=True)
class Word:
    """Слово с рамкой в координатах показа (начало — левый верхний угол)."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


_RE_PAGE = re.compile(r"<page\b[^>]*>(.*?)</page>", re.S)
_RE_WORD = re.compile(r'<word xMin="([-\d.]+)" yMin="([-\d.]+)" xMax="([-\d.]+)" '
                      r'yMax="([-\d.]+)">(.*?)</word>', re.S)


def bbox_words(xhtml: str) -> list[list[Word]]:
    """Вывод `pdftotext -bbox` — слова по страницам.

    Координаты poppler уже даёт в повёрнутой странице, как её видит читатель:
    у альбомного листа x идёт вдоль строки таблицы, y — сверху вниз.
    """
    pages = []
    for body in _RE_PAGE.findall(xhtml):
        words = []
        for m in _RE_WORD.finditer(body):
            x0, y0, x1, y1 = (float(v) for v in m.groups()[:4])
            text = html.unescape(m.group(5)).strip()
            if text:
                words.append(Word(x0, y0, x1, y1, text))
        pages.append(words)
    return pages


def grid_from_rects(rects: Iterable[tuple], rotate: int = 90) -> tuple[list[float], list[float]]:
    """Линии сетки из прямоугольников потока страницы: (строки по y, колонки по x).

    `rects` — (x, y, w, h) в пространстве PDF. У страницы, повёрнутой на 90°,
    ось y PDF идёт вдоль строки таблицы, а ось x — сверху вниз: точка (x, y)
    видна читателю в (y, x) — так же её даёт и `pdftotext -bbox`. Линия
    строки — во всю ширину таблицы, поэтому куски одной высоты складываются,
    прежде чем сравнить длину. Других поворотов в перечне нет, и разбор их
    не угадывает.
    """
    if rotate != 90:
        raise ZrbgError(f"страница повёрнута на {rotate}°, а перечень свёрстан альбомными "
                        "листами с поворотом 90° — файл не тот")
    rows: dict[float, float] = {}
    cols: dict[float, float] = {}
    for x, y, w, h in rects:
        x, y, w, h = float(x), float(y), float(w), float(h)
        if w < 0:
            x, w = x + w, -w
        if h < 0:
            y, h = y + h, -h
        # строка таблицы: тонкая по x PDF и длинная по y; колонка — наоборот
        if w <= RULE_WIDTH < h:
            key = round(x + w / 2, 1)
            rows[key] = rows.get(key, 0.0) + h
        elif h <= RULE_WIDTH < w:
            key = round(y + h / 2, 1)
            cols[key] = cols.get(key, 0.0) + w
    row_y = _merge(sorted(k for k, v in rows.items() if v >= ROW_RULE_MIN))
    col_x = _merge(sorted(k for k, v in cols.items() if v >= COL_RULE_MIN))
    return row_y, col_x


def _merge(values: list[float], tol: float = 1.0) -> list[float]:
    out: list[float] = []
    for v in values:
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def page_cells(words: list[Word], row_y: list[float],
               col_x: list[float]) -> tuple[list[list[list[str]]], list[Word]]:
    """Слова страницы — в ячейки сетки: строки × колонки × строки текста.

    Слово принадлежит ячейке, в которую попадает его центр. Строки текста
    внутри ячейки — по верхнему краю слова (допуск 3 пт), слова в строке —
    слева направо. Слова вне сетки (заголовок перечня, номер страницы)
    возвращаются отдельно.
    """
    cells: dict[tuple[int, int], list[Word]] = {}
    loose = []
    for w in words:
        ri = _band(row_y, w.cy)
        ci = _band(col_x, w.cx)
        if ri is None or ci is None:
            loose.append(w)
            continue
        cells.setdefault((ri, ci), []).append(w)
    table = []
    for ri in range(len(row_y) - 1):
        row = []
        for ci in range(len(col_x) - 1):
            lines: list[list[Word]] = []
            for w in sorted(cells.get((ri, ci), []), key=lambda w: (w.y0, w.x0)):
                if lines and abs(lines[-1][0].y0 - w.y0) < 3:
                    lines[-1].append(w)
                else:
                    lines.append([w])
            row.append([" ".join(x.text for x in sorted(ln, key=lambda w: w.x0))
                        for ln in lines])
        table.append(row)
    return table, loose


def _band(edges: list[float], v: float) -> Optional[int]:
    for i in range(len(edges) - 1):
        if edges[i] < v < edges[i + 1]:
            return i
    return None


# --- записи -----------------------------------------------------------------

@dataclass
class RawEntry:
    """Запись таблицы до разбора полей: ячейки как строки текста."""

    page: int
    cells: list           # девять списков строк
    continued: bool = False


_RE_MAIN_NR = re.compile(r"\d{3,4}")


def _has_main_number(lines: list[str]) -> bool:
    return bool(main_numbers(" ".join(lines)))


def table_entries(pages: list[list[list[list[str]]]]) -> list[RawEntry]:
    """Строки таблиц всех страниц — в записи перечня.

    Строка заголовка (`Nr.` …) на каждой странице пропускается. Строка без
    номера записи, первая на странице, — продолжение записи, разорванной
    переносом: если у неё нет своих дат или их нет у предыдущей. Строка без
    номера в середине страницы — отдельная запись (так в перечне стоит
    Szydlowiec).
    """
    out: list[RawEntry] = []
    for pn, table in enumerate(pages, 1):
        first = True
        for row in table:
            if len(row) != len(COLUMNS):
                raise ZrbgError(f"страница {pn}: в строке {len(row)} колонок, а не "
                                f"{len(COLUMNS)} — сетку таблицы поменяли")
            if row[0][:1] == ["Nr."]:
                continue
            if not any(row):
                first = False
                continue
            has_nr = _has_main_number(row[0])
            own_dates = bool(row[3] or row[4])
            if (not has_nr and first and out
                    and not (own_dates and (out[-1].cells[3] or out[-1].cells[4]))):
                for i, lines in enumerate(row):
                    out[-1].cells[i].extend(lines)
                out[-1].continued = True
            else:
                out.append(RawEntry(page=pn, cells=[list(c) for c in row]))
            first = False
    return out


def join_lines(lines: list[str]) -> str:
    """Строки ячейки — в одну: перенос по дефису склеивается без пробела."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out.endswith("-") and not out.endswith(" -"):
            out += line
        elif out:
            out += " " + line
        else:
            out = line
    return clean_text(out) or ""


def main_numbers(text: str) -> list[str]:
    """Номера записи без скобок: «5613 (5010)» → ['5613']; в скобках — прежние."""
    rest = re.sub(r"[\(\[]\s*\d+\s*[\)\]]", " ", text)
    return _RE_MAIN_NR.findall(rest)


def old_numbers(text: str) -> list[str]:
    return re.findall(r"[\(\[]\s*(\d+)\s*[\)\]]", text)


# --- даты -------------------------------------------------------------------

GERMAN_MONTHS = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "mär": 3,
    "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "oktober": 10,
    "okt": 10, "oct": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12, "dec": 12,
}
_MONTH_RE = "|".join(sorted(GERMAN_MONTHS, key=len, reverse=True))


@dataclass(frozen=True)
class Day:
    """Дата из перечня с честной точностью: день, месяц или только год."""

    year: int
    month: Optional[int] = None
    day: Optional[int] = None
    approx: bool = False        # «Ende Mai», опечатка, дата соседнего гетто
    note: Optional[str] = None

    @property
    def precision(self) -> str:
        return "day" if self.day else "month" if self.month else "year"

    def iso(self) -> str:
        if self.day:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if self.month:
            return f"{self.year:04d}-{self.month:02d}"
        return f"{self.year:04d}"

    def date(self) -> Optional[dt.date]:
        return dt.date(self.year, self.month, self.day) if self.day else None


_RE_FOOTNOTE = re.compile(r"\[\d+\]")
_RE_DMY = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
_RE_DMY_LOOSE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_RE_D_MONTH_Y = re.compile(rf"(\d{{1,2}})\.?\s*({_MONTH_RE})\.?\s+(\d{{4}})", re.I)
_RE_MONTH_Y = re.compile(rf"(?:(Anfang|Mitte|Ende)\s+)?\b({_MONTH_RE})\.?\s+(\d{{4}}|\d{{2}})\b",
                         re.I)
_RE_YEAR = re.compile(r"(?<!\d)(19[34]\d)(?!\d)")


def parse_day(text: Optional[str]) -> Optional[Day]:
    """Ячейка «Eröffnung» или «Liquidierung» — дата или None.

    Хвост после даты — сноска «[2]», пояснение в скобках («erste Erwähnung»,
    «in Anlehnung an das Ghetto Wilna») — не дата: он даёт только пометку
    `approx`, если дата заимствована у другого гетто.
    """
    s = clean_text(text)
    if not s or s.strip(" ./?:") == "":
        return None
    borrowed = bool(re.search(r"Anlehnung|übernommen", s, re.I))
    first = bool(re.search(r"erste Erwähnung", s, re.I))
    s = _RE_FOOTNOTE.sub(" ", s)
    # «01. 09.1941», «16.04 1944», «01.01..1940»: пробелы и повторы точек
    norm = re.sub(r"(\d)\s*\.\s*(?=\d)", r"\1.", s)
    norm = re.sub(r"\.{2,}", ".", norm)
    norm = re.sub(r"(?<!\d)(\d{1,2})\.(\d{1,2})\s+(\d{4})(?!\d)", r"\1.\2.\3", norm)
    note = "дата соседнего гетто" if borrowed else "первое упоминание" if first else None

    m = _RE_DMY.search(norm)
    loose = False
    if not m:
        m = _RE_DMY_LOOSE.search(norm)
        loose = bool(m)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mo, d):
            return Day(y, mo, d, approx=borrowed or loose,
                       note=("опечатка в источнике: «" + s + "»") if loose else note)
    m = _RE_D_MONTH_Y.search(norm)
    if m:
        d, mo, y = int(m.group(1)), GERMAN_MONTHS[m.group(2).lower()], int(m.group(3))
        if _valid(y, mo, d):
            return Day(y, mo, d, approx=borrowed, note=note)
    m = _RE_MONTH_Y.search(norm)
    if m:
        y = int(m.group(3))
        y = y + 1900 if y < 100 else y
        mo = GERMAN_MONTHS[m.group(2).lower()]
        if 1933 <= y <= 1945:
            return Day(y, mo, approx=borrowed or bool(m.group(1)), note=note)
    m = _RE_YEAR.search(norm)
    if m:
        return Day(int(m.group(1)), approx=borrowed, note=note)
    return None


def _valid(y: int, mo: int, d: int) -> bool:
    if not (1933 <= y <= 1945 and 1 <= mo <= 12):
        return False
    try:
        dt.date(y, mo, d)
    except ValueError:
        return False
    return True


# --- территория ---------------------------------------------------------------

# Нынешние государства по словам столбца «Gebiet» — для сверки с картой USHMM,
# где страна указана в нынешних границах. Порядок важен: «heute: Polen» точнее
# «Generalbezirk Weißruthenien», поэтому сперва ищется явное «heute».
TERRITORY_WORDS = (
    (r"Transnistr", {"Ukraine", "Moldova"}),
    (r"Reichskommiss?ariat\s+Ukr|RK\s+Ukraine|Wolhynien|Shitomir|Podolien",
     {"Ukraine", "Belarus"}),
    (r"Weißruth|Weissruth|Weißruss|Weissruss|Belarus|Weißrußland", {"Belarus", "Lithuania"}),
    (r"Generalbezirk\s+Litauen|\bLitauen\b", {"Lithuania", "Belarus"}),
    (r"Lettland|Kurland", {"Latvia"}),
    (r"Estland", {"Estonia"}),
    (r"Ostland", {"Belarus", "Lithuania", "Latvia", "Estonia"}),
    (r"Galizien", {"Ukraine", "Poland"}),
    (r"Bialystok|Białystok", {"Poland", "Belarus"}),
    (r"Ostpreußen|Ostpreussen", {"Poland", "Russia", "Lithuania"}),
    (r"Distrikt\s+(?:Lublin|Radom|Warschau)|Bezirk\s+Radom|Wartheland|Warthegau|Danzig|"
     r"Oberschlesien|Posen|Zichenau", {"Poland"}),
    (r"Distrikt\s+Krakau|Generalg[ou]+vernement|Karpatenvorland", {"Poland", "Ukraine"}),
    (r"Belgien", {"Belgium"}),
    (r"Transkarpat|Karpato|Zakarpat", {"Ukraine"}),
    (r"Bessarabien|Moldawien|Moldau", {"Moldova", "Ukraine"}),
    (r"Bukowina", {"Ukraine", "Romania"}),
    (r"Siebenbürgen", {"Romania"}),
    (r"Ungarn", {"Hungary", "Ukraine", "Romania", "Slovakia", "Serbia"}),
    (r"Rumänien", {"Romania", "Moldova", "Ukraine"}),
    (r"Slowakei", {"Slovakia"}),
    (r"Protektorat|Tschech|Böhmen|Mähren", {"Czech Republic", "Czechia"}),
    (r"Russland|Rußland|Smolensk|Oriol|Orel|Kalinin|Krasnodar|Brjansk|Kursk|Rostow|"
     r"Stawropol|Leningrad|Pskow|Woronesch|Kaluga|Kalmück|Elista|Krim|Crimea",
     {"Russia", "Ukraine"}),
    (r"Ukraine", {"Ukraine"}),
    (r"\bPolen\b", {"Poland"}),
    (r"Niederlande|Holland", {"Netherlands"}),
    (r"Griechenland", {"Greece"}),
    (r"Jugoslawien|Serbien|Kroatien", {"Serbia", "Croatia"}),
    (r"Bulgarien", {"Bulgaria"}),
    (r"Österreich", {"Austria"}),
    (r"Tunesien", {"Tunisia"}),
    (r"Italien", {"Italy"}),
    (r"Frankreich", {"France"}),
    (r"Reichsgebiet|Deutschland", {"Germany"}),
)

_RE_TODAY = re.compile(r"heute:?\s*(?P<what>[^;]+)", re.I)
TODAY_COUNTRIES = {
    "Polen": "Poland", "Ukraine": "Ukraine", "Belarus": "Belarus",
    "Weißrussland": "Belarus", "Weißrußland": "Belarus", "Litauen": "Lithuania",
    "Lettland": "Latvia", "Estland": "Estonia", "Moldawien": "Moldova",
    "Rumänien": "Romania", "Serbien": "Serbia", "Slowakei": "Slovakia",
    "Russland": "Russia", "Ungarn": "Hungary",
}


def territory_countries(text: Optional[str]) -> set[str]:
    """Нынешние государства, где может лежать место, — по столбцу «Gebiet».

    Пустое множество — территория не узнана; тогда сведение с картой идёт
    без сверки страны.
    """
    s = clean_text(text) or ""
    today = _RE_TODAY.search(s)
    if today:
        what = today.group("what")
        hits = {v for k, v in TODAY_COUNTRIES.items() if re.search(rf"\b{k}\b", what)}
        if hits:
            return hits
    out: set[str] = set()
    for pattern, countries in TERRITORY_WORDS:
        if re.search(pattern, s, re.I):
            out |= countries
            break
    return out


def today_region(text: Optional[str]) -> Optional[str]:
    """Нынешняя область: «heute Gebiet Vitebsk», «heute: Ukraine, Gebiet Riwne».

    Только с «heute»: область без него — военных лет, а те были крупнее
    нынешних (Калининская область 1935–1944 годов доходила до Невеля и
    Опочки, Орловская — до Клинцов и Стародуба).
    """
    s = clean_text(text) or ""
    m = re.search(r"heute:?\s*(?:[A-ZÄÖÜa-zäöüß]+,\s*)?Gebiet\s+([^;,()]+)", s)
    return clean_text(m.group(1)) if m else None


def region_hint(text: Optional[str]) -> Optional[str]:
    """Любая область в столбце «Gebiet» — для подсказки «область в названии карты»."""
    s = clean_text(text) or ""
    m = re.search(r"(?:^|[,;:]\s*|heute:?\s*)Gebiet\s+([^;,()]+)", s)
    return clean_text(m.group(1)) if m else None


# Даты начала гетто «по распоряжениям» — шапка перечня — и общие даты
# Транснистрии и Венгрии: (территория, поле, дата).
RULE_DATES = (
    (r"Generalgouvernement|Distrikt\s+(?:Lublin|Radom|Warschau|Krakau)", "opened",
     dt.date(1940, 1, 1)),
    (r"Galizien", "opened", dt.date(1941, 9, 6)),
    (r"Bialystok|Białystok", "opened", dt.date(1941, 8, 2)),
    (r"Ostland|Weißruth|Litauen|Lettland|Estland", "opened", dt.date(1941, 8, 2)),
    (r"Reichskommiss?ariat\s+Ukraine|RK\s+Ukraine|Wolhynien", "opened", dt.date(1941, 9, 5)),
    (r"Transnistr", "opened", dt.date(1941, 8, 30)),
    (r"Transnistr", "liquidated", dt.date(1944, 3, 18)),
    (r"Ungarn|Transkarpat", "opened", dt.date(1944, 4, 16)),
    (r"Ungarn|Transkarpat", "liquidated", dt.date(1944, 7, 13)),
)


def rule_dates(territory: str, opened: Optional[Day], liquidated: Optional[Day]) -> list[str]:
    """Какие даты записи — правовые («по распоряжениям»), а не местные."""
    out = []
    for pattern, which, day in RULE_DATES:
        value = opened if which == "opened" else liquidated
        if value and value.date() == day and re.search(pattern, territory, re.I):
            if which not in out:
                out.append(which)
    return out


# --- названия -------------------------------------------------------------------

# Пометки в квадратных скобках: язык написания («[Pol]», «[Rus, Yid]»), годы
# («[Ger, 1939-45]», «[Rus, since 1961]») и сноски («[2]»). Бывают в скобках
# и сами варианты («Balsoi Caranica [Balsaia-Caranica, Balschaja Karanika]») —
# такие скобки читаются как круглые.
LANG_TAGS = frozenset({
    "pol", "yid", "rus", "ger", "ukr", "hun", "hung", "bel", "rom", "rum", "lith", "lit",
    "slov", "slo", "cz", "lat", "latv", "heb", "serb", "turk", "tur", "croa", "tatar",
    "grk", "mold", "fr", "ital", "est", "eng", "sp", "wwii", "since", "before", "until",
    "to", "seit", "vor", "bis", "ab", "near",
})
_RE_BRACKET = re.compile(r"\[([^\[\]]*)\]")


def _bracket(m: re.Match) -> str:
    tokens = [t for t in re.split(r"[,;\s]+", m.group(1).strip()) if t]
    if not tokens or tokens[0].lower() == "near" or all(
            t.lower().strip(".") in LANG_TAGS or re.fullmatch(r"\d{1,4}(?:[-–]\d{2,4})?", t)
            for t in tokens):
        return " "
    return f" ({m.group(1)}) "


def place_names(text: Optional[str]) -> list[str]:
    """Ячейка «Ort» — главное название и варианты написания, без пометок языка.

    «Aboltsy [Bel] (Oboltsy [Rus], Oboltzi [Yid], Obolce [Pol])» →
    ['Aboltsy', 'Oboltsy', 'Oboltzi', 'Obolce']. Уточнения со строчной буквы
    («nad Wisla», «an der Weichsel») вариантом не считаются.
    """
    s = clean_text(text) or ""
    for _ in range(2):          # вложенные скобки: «Lyubar [Lyubar [Rus, Ukr]]»
        s = _RE_BRACKET.sub(_bracket, s)
    s = s.replace("[", "(").replace("]", ")")
    parts = re.split(r"[(),;/]|\s+oder\s+|\s+or\s+", s)
    out = []
    for part in parts:
        part = clean_text(part.strip(" .-–'’\"")) or ""
        if len(part) < 2 or part.isdigit() or part[0].islower():
            continue
        if re.match(r"(?:Gebiet|Kreis|Rayon|Bezirk|heute|früher)\b", part):
            continue
        if part not in out:
            out.append(part)
    return out


# --- пометки из примечаний ---------------------------------------------------------

# Что было на месте, если, по перечню, не гетто: слово из примечания → тип.
NOT_GHETTO_KINDS = (
    (r"Vernichtungslager", "лагерь уничтожения"),
    (r"Kriegsgefangen|Durchgangslager", "лагерь военнопленных или пересыльный"),
    (r"Konzentrationslager|\bKZ\b|Außenlager|Aussenlager|Außenkommando|Aussenkommando|"
     r"Nebenlager", "концлагерь или его подлагерь"),
    (r"\bZAL\b|Zwangsarbeitslager|Arbeitslager|Arbeitsbataillon", "лагерь принудительного труда"),
    (r"Internierung|Schleusungslager", "лагерь для интернированных"),
    (r"Haftstätte|Gefängnis", "место заключения"),
    (r"Lager", "лагерь"),
)


def remark_flags(text: Optional[str]) -> dict:
    """Пометки из примечаний — без самого текста примечания.

    * `not_ghetto` — «kein Ghetto i. S. d. ZRBG»: по закону здесь не гетто;
      `not_ghetto_kind` — что было вместо него, если сказано (ZAL, лагерь,
      тюрьма, лагерь уничтожения);
    * `no_evidence` — «kein Hinweis auf ein Ghetto»: свидетельств гетто нет;
    * `open_ghetto`, `village_ghetto` — открытое, сельское гетто;
    * `borrowed` — дата взята у соседнего гетто;
    * `also_camp` — в месте был ещё и лагерь (ZAL, рабочий, для интернированных);
    * `name_ambiguous` — составители предупреждают о тёзках («43 Orte»).
    """
    s = clean_text(text) or ""
    flags: dict = {}
    if not s:
        return flags
    if re.search(r"kein(?:e)?\s+Hinweis", s, re.I):
        flags["no_evidence"] = True
    elif re.search(r"kein\s+Ghetto", s, re.I):
        flags["not_ghetto"] = True
        tail = re.split(r"ZRBG\s*[:\-.,]?", s, maxsplit=1)
        rest = tail[1] if len(tail) > 1 else s
        for pattern, kind in NOT_GHETTO_KINDS:
            if re.search(pattern, rest, re.I):
                flags["not_ghetto_kind"] = kind
                break
    if re.search(r"offenes\s+Ghetto|offenen\s+Ghetto", s, re.I):
        flags["open_ghetto"] = True
    if re.search(r"Dorfghetto", s, re.I):
        flags["village_ghetto"] = True
    if re.search(r"übernommen|Anlehnung", s, re.I):
        flags["borrowed"] = True
    if re.search(r"auch\s+(?:ein|eine)\s+(?:\w+\s+)?(?:ZAL|Lager|Arbeitslager|"
                 r"Internier\w*|Zivil\w*)", s, re.I):
        flags["also_camp"] = True
    if re.search(r"Beachte|mehrere Orte|\d+\s+Orte", s, re.I):
        flags["name_ambiguous"] = True
    return flags


# --- запись перечня --------------------------------------------------------------

@dataclass
class Entry:
    """Запись перечня после разбора полей."""

    nr: Optional[str]
    old_nr: list
    names: list
    place_raw: str
    territory: str
    opened: Optional[Day]
    liquidated: Optional[Day]
    opened_raw: str
    liquidated_raw: str
    deportations: Optional[str]
    source: Optional[str]
    updated: Optional[str]
    page: int
    flags: dict = field(default_factory=dict)
    rule: list = field(default_factory=list)
    countries: set = field(default_factory=set)
    region_today: Optional[str] = None
    region: Optional[str] = None
    continued: bool = False

    @property
    def name(self) -> str:
        return self.names[0] if self.names else self.place_raw or "без названия"

    @property
    def key(self) -> str:
        """Устойчивый ключ: номер записи и главное название (номера повторяются)."""
        slug = re.sub(r"[^a-z0-9]+", "-", _ascii(self.name).lower()).strip("-")
        return f"zrbg:{self.nr or 'p' + str(self.page)}:{slug}"

    @property
    def dated(self) -> bool:
        return self.opened is not None or self.liquidated is not None


def parse_entry(raw: RawEntry) -> Entry:
    c = [join_lines(lines) for lines in raw.cells]
    nrs = main_numbers(c[0])
    territory = c[2]
    opened, liquidated = parse_day(c[3]), parse_day(c[4])
    flags = remark_flags(c[6])
    if flags.get("borrowed"):
        opened = _approx(opened) if re.search(r"Eröffnung", c[6], re.I) else opened
        liquidated = (_approx(liquidated) if re.search(r"Liquid", c[6], re.I)
                      else liquidated)
    if len(nrs) > 1:
        flags["several_numbers"] = nrs
    return Entry(
        nr=nrs[0] if nrs else None,
        old_nr=old_numbers(c[0]),
        names=place_names(c[1]),
        place_raw=c[1],
        territory=territory,
        opened=opened, liquidated=liquidated,
        opened_raw=c[3], liquidated_raw=c[4],
        deportations=clean_text(c[5]),
        source=clean_text(c[7]),
        updated=clean_text(c[8]),
        page=raw.page,
        flags=flags,
        rule=rule_dates(territory, opened, liquidated),
        countries=territory_countries(territory),
        region_today=today_region(territory),
        region=region_hint(territory),
        continued=raw.continued,
    )


def _approx(day: Optional[Day]) -> Optional[Day]:
    if day is None or day.approx:
        return day
    return Day(day.year, day.month, day.day, approx=True, note="дата соседнего гетто")


def read_tables(pdf_path) -> tuple[list[list[list[list[str]]]], list[str]]:
    """PDF перечня — таблицы страниц (`page_cells`) и слова вне сетки.

    Не разбор, а чтение файла: слова — `pdftotext -bbox` (poppler), линии —
    `pypdf`. Обеих программ в зависимостях проекта нет, они нужны только
    этому сборщику, и без них он останавливается с внятным сообщением.
    """
    import shutil
    import subprocess

    if not shutil.which("pdftotext"):
        raise ZrbgError("нет pdftotext — поставьте poppler-utils (apt install poppler-utils): "
                        "без него слова таблицы не разложить по ячейкам")
    try:
        from pypdf import PdfReader
        from pypdf.generic import ContentStream
    except ImportError as exc:
        raise ZrbgError("нет pypdf — python3 -m pip install pypdf: им читаются линии "
                        "сетки таблицы") from exc
    run = subprocess.run(["pdftotext", "-bbox", str(pdf_path), "-"], capture_output=True,
                         check=False)
    if run.returncode != 0:
        raise ZrbgError(f"pdftotext: {run.stderr.decode('utf-8', 'replace')[:300]}")
    pages_words = bbox_words(run.stdout.decode("utf-8"))
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) != len(pages_words):
        raise ZrbgError(f"pypdf видит {len(reader.pages)} страниц, pdftotext — "
                        f"{len(pages_words)}")
    tables, loose = [], []
    for pn, page in enumerate(reader.pages, 1):
        rects = []
        for operands, op in ContentStream(page.get_contents(), reader).operations:
            if op == b"re" and len(operands) == 4:
                rects.append(tuple(float(v) for v in operands))
        row_y, col_x = grid_from_rects(rects, int(page.get("/Rotate") or 0) % 360)
        if len(col_x) != len(COLUMNS) + 1:
            raise ZrbgError(f"страница {pn}: колонок в сетке {len(col_x) - 1}, а не "
                            f"{len(COLUMNS)}")
        table, outside = page_cells(pages_words[pn - 1], row_y, col_x)
        tables.append(table)
        loose.extend(f"стр. {pn}: {w.text}" for w in outside)
    return tables, loose


def check_header(pages: list[list[list[list[str]]]]) -> list[str]:
    """Заголовок таблицы на каждой странице — те же девять колонок."""
    problems = []
    for pn, table in enumerate(pages, 1):
        head = next((row for row in table if row and row[0][:1] == ["Nr."]), None)
        if head is None:
            problems.append(f"страница {pn}: нет строки заголовка")
            continue
        got = tuple(join_lines(c) for c in head)
        if got != HEADER:
            problems.append(f"страница {pn}: заголовок {got}")
    return problems


def _ascii(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
