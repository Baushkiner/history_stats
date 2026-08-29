"""Разбор русских текстовых датировок в числовой интервал лет.

Ключевой модуль проекта. Пока период записан как «конец 19 - начало 20 в.»,
факт из метрической книги невозможно сопоставить с контекстом: нужны
числовые границы. Здесь свободный текст превращается в (year_from, year_to)
плюс оценка точности.

Принцип: при неоднозначности расширяем интервал, а не сужаем. Для подбора
контекста вокруг факта лучше показать лишнее (пользователь отсеет глазами),
чем потерять релевантное. Степень огрубления видна в поле `precision`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Точность интервала, от самой точной к самой грубой.
#
# `open` этим разбором не выдаётся: так помечают срок, у которого один конец
# взят не из источника, а из горизонта проекта — «основан в 1802 году и не
# упразднён». Его ширина ничего не говорит о том, насколько точно известна
# дата, поэтому он стоит грубее любой названной датировки и уступает только
# «не определена». Кто его ставит — сборщики, см. `PRECISION_OPEN`.
PRECISION_ORDER = ("day", "month", "season", "year", "decade", "part",
                   "century", "era", "open", "unknown")

# Открытый срок: известен один конец, другой растянут до горизонта.
#
# Значение появилось потому, что сборщики ставили здесь `part` — «часть века»,
# — и отчёт о качестве честно пересказывал это словами: 33 тысячи записей
# выглядели датированными половиной столетия, хотя у них измерен ровно один
# год. Ширина такого интервала — свойство нашей рамки, а не источника.
PRECISION_OPEN = "open"

_DASHES = "‐‑‒–—―−"
_RANGE_WORDS = r"(?:\s+(?:по|до|и)\s+)"

_APPROX_MARKERS = (
    "примерно", "около", "приблизительно", "ориентировочно", "предположительно",
    "не позднее", "не ранее", "накануне", "сразу после", "вскоре после", "почти",
)

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_SEASONS = {"зим": (12, 2), "весн": (3, 5), "лет": (6, 8), "осен": (9, 11)}

# Именованные эпохи. Границы намеренно широкие.
_ERAS = {
    "советское время": (1917, 1991),
    "советский период": (1917, 1991),
    "советская эпоха": (1917, 1991),
    "дореволюционное время": (1800, 1917),
    "до революции": (1800, 1917),
    "послевоенный период": (1945, 1960),
    "послевоенное время": (1945, 1960),
    "гражданская война": (1917, 1922),
    "великая отечественная война": (1941, 1945),
    "первая мировая война": (1914, 1918),
    "смутное время": (1598, 1613),
    "нэп": (1921, 1928),
    "коллективизация": (1929, 1933),
    "оттепель": (1953, 1964),
}

# Доли века -> (смещение начала, смещение конца) внутри века 0..99.
_PARTS = {
    "начало": (0, 14),
    "нач": (0, 14),
    "первая половина": (0, 49),
    "первая пол": (0, 49),
    "вторая половина": (50, 99),
    "вторая пол": (50, 99),
    "середина": (39, 59),
    "сер": (39, 59),
    "конец": (89, 99),
    "кон": (89, 99),
    "к": (89, 99),
    "первая треть": (0, 32),
    "вторая треть": (33, 65),
    "последняя треть": (66, 99),
    "третья треть": (66, 99),
    "первая четверть": (0, 24),
    "вторая четверть": (25, 49),
    "третья четверть": (50, 74),
    "последняя четверть": (75, 99),
    "четвертая четверть": (75, 99),
    "первые десятилетия": (0, 29),
    "последние десятилетия": (70, 99),
    "весь": (0, 99),
}

# Доли десятилетия -> (смещение начала, смещение конца) внутри декады 0..9.
_DECADE_PARTS = {
    "начало": (0, 3),
    "нач": (0, 3),
    "первая половина": (0, 4),
    "первая пол": (0, 4),
    "вторая половина": (5, 9),
    "вторая пол": (5, 9),
    "середина": (4, 6),
    "сер": (4, 6),
    "конец": (7, 9),
    "кон": (7, 9),
    "к": (7, 9),
}


def _with_oblique(table: dict) -> dict:
    """Добавляет косвенные формы: «с конца 70-х», «до начала 20 в.»."""
    endings = {
        "начало": ("начала", "началу"),
        "середина": ("середины", "середине"),
        "конец": ("конца", "концу"),
        "первая половина": ("первой половины", "первой половине"),
        "вторая половина": ("второй половины", "второй половине"),
        "первая треть": ("первой трети",),
        "вторая треть": ("второй трети",),
        "последняя треть": ("последней трети",),
        "первая четверть": ("первой четверти",),
        "вторая четверть": ("второй четверти",),
        "третья четверть": ("третьей четверти",),
        "последняя четверть": ("последней четверти",),
    }
    out = dict(table)
    for base, forms in endings.items():
        if base in table:
            for f in forms:
                out.setdefault(f, table[base])
    return out


_PARTS = _with_oblique(_PARTS)
_DECADE_PARTS = _with_oblique(_DECADE_PARTS)

_PART_ALT = "|".join(sorted((re.escape(k) for k in _PARTS), key=len, reverse=True))

_RE_CLEAN_PAREN = re.compile(r"\([^()]*\)")
_RE_SPACES = re.compile(r"\s+")

# Полнострочные шаблоны, проверяются до разбора по частям.
_RE_FULL_DECADE_OF_CENTURY = re.compile(
    rf"^(?:(?P<part>{_PART_ALT})\.?\s+)?(?P<dec>\d{{1,2}})-?[ех]?\s*(?:гг?|годы|годов|года)?\.?\s+"
    rf"(?P<cent>\d{{1,2}})\s*(?:вв?|века?|век)\.?$"
)
_RE_FULL_CENTURY_SPAN = re.compile(
    r"^(?P<a>\d{1,2})\s*[-–]\s*(?P<b>\d{1,2})\s*(?:вв?|века?|веков)\.?$"
)
_RE_FULL_YEAR_SPAN = re.compile(
    r"^(?P<a>\d{3,4})\s*[-–]\s*(?P<b>\d{1,4})\s*(?:гг?|годы?|годов|года)?\.?$"
)
_RE_FULL_DECADE_SPAN = re.compile(
    r"^(?P<a>\d{3,4})\s*[-–]\s*(?P<b>\d{1,4})-?[ех]\s*(?:гг?|годы?|годов|года)?\.?$"
)

_RE_ATOM_YEAR = re.compile(r"^(?P<y>\d{3,4})\s*(?:г|гг|год|году|года|годы)?\.?$")
_RE_ATOM_DECADE = re.compile(
    rf"^(?:(?P<part>{_PART_ALT})\.?\s+)?(?P<d>\d{{3,4}})-?[ех]\s*(?:гг?|годы?|годов|года)?\.?$"
)
_RE_ATOM_CENTURY = re.compile(
    rf"^(?:(?P<part>{_PART_ALT})\.?\s+)?(?P<c>\d{{1,2}})\s*(?:вв?|века?|век|веков)\.?$"
)
_RE_ATOM_TURN = re.compile(
    r"^рубеж\s+(?P<a>\d{1,2})\s*(?:и|-|–)\s*(?P<b>\d{1,2})\s*(?:вв?|века?|век)\.?$"
)
_RE_ATOM_MONTH_YEAR = re.compile(r"^(?P<m>[а-я]+)\s+(?P<y>\d{3,4})\s*(?:г|гг|год|года)?\.?$")
_RE_ISO = re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})")


@dataclass(frozen=True)
class Period:
    """Разобранная датировка."""

    year_from: Optional[int]
    year_to: Optional[int]
    precision: str
    approx: bool
    raw: str

    @property
    def ok(self) -> bool:
        return self.year_from is not None and self.year_to is not None

    @property
    def span(self) -> Optional[int]:
        return None if not self.ok else self.year_to - self.year_from + 1

    def overlaps(self, year_from: int, year_to: int) -> bool:
        """Пересекается ли период с заданным интервалом."""
        if not self.ok:
            return False
        return self.year_from <= year_to and year_from <= self.year_to


def _norm(text: str) -> str:
    s = str(text).strip().lower().replace("ё", "е")
    for d in _DASHES:
        s = s.replace(d, "-")
    s = s.replace(" ", " ")
    # Порядковые окончания при веке: «20-й века», «19-го в.».
    s = re.sub(r"(\d{1,2})-(?:й|го|м|ый|ого)(?=\s*(?:вв?|века?|век))", r"\1", s)
    return _RE_SPACES.sub(" ", s).strip()


def _century_bounds(c: int) -> tuple[int, int]:
    """19 в. -> 1801..1900."""
    return (c - 1) * 100 + 1, c * 100


def _apply_part(part: Optional[str], lo: int, hi: int, table: dict) -> tuple[int, int, str]:
    if not part:
        return lo, hi, "full"
    key = part.strip().rstrip(".")
    off = table.get(key)
    if off is None:
        return lo, hi, "full"
    base = lo - 1 if table is _PARTS else lo
    shift = 1 if table is _PARTS else 0
    return base + off[0] + shift, base + off[1] + shift, "part"


def _parse_atom(s: str) -> Optional[tuple[int, int, str]]:
    """Разбирает одиночное выражение (без диапазона) в (lo, hi, precision)."""
    s = s.strip().strip(",;").strip()
    if not s:
        return None

    for era, (a, b) in _ERAS.items():
        if s == era or s.startswith(era + " ") or s.endswith(" " + era):
            return a, b, "era"

    m = _RE_ATOM_TURN.match(s)
    if m:
        a, b = int(m["a"]), int(m["b"])
        return _century_bounds(a)[1] - 10, _century_bounds(b)[0] + 9, "part"

    m = _RE_FULL_DECADE_OF_CENTURY.match(s)
    if m:
        base = (int(m["cent"]) - 1) * 100 + int(m["dec"])
        lo, hi, _ = _apply_part(m["part"], base, base + 9, _DECADE_PARTS)
        return lo, hi, "decade"

    m = _RE_ATOM_YEAR.match(s)
    if m:
        y = int(m["y"])
        return y, y, "year"

    m = _RE_ATOM_MONTH_YEAR.match(s)
    if m:
        y = int(m["y"])
        word = m["m"]
        for stem in _SEASONS:
            if word.startswith(stem):
                return y, y, "season"
        for stem in _MONTHS:
            if word.startswith(stem):
                return y, y, "month"

    m = _RE_ATOM_DECADE.match(s)
    if m:
        d = int(m["d"])
        lo, hi, _ = _apply_part(m["part"], d, d + 9, _DECADE_PARTS)
        return lo, hi, "decade"

    m = _RE_ATOM_CENTURY.match(s)
    if m:
        c = int(m["c"])
        lo, hi = _century_bounds(c)
        if m["part"]:
            lo, hi, _ = _apply_part(m["part"], lo, hi, _PARTS)
            return lo, hi, "part"
        return lo, hi, "century"

    return None


def _split_range(s: str) -> Optional[tuple[str, str]]:
    """Делит строку на две части по разделителю диапазона верхнего уровня."""
    m = re.search(_RANGE_WORDS, s)
    if m and not s.startswith("рубеж"):
        return s[: m.start()].strip(), s[m.end():].strip()

    # Дефис как разделитель: годится, только если он не суффикс декады
    # («1770-е») и не часть «1850-60-е».
    for m in re.finditer(r"-", s):
        left, right = s[: m.start()].strip(), s[m.end():].strip()
        if not left or not right:
            continue
        if re.match(r"^[ех]\b", right):
            continue
        return left, right
    return None


def parse_period(text: Optional[str]) -> Period:
    """Превращает свободный текст датировки в числовой интервал."""
    raw = "" if text is None else str(text)
    s = _norm(raw)
    if not s or s in {"-", "--", "?", "неизв", "неизв.", "неизвестно", "нет данных", "n/a", "nan"}:
        return Period(None, None, "unknown", False, raw)

    m = _RE_ISO.match(s)
    if m:
        y = int(m["y"])
        return Period(y, y, "day", False, raw)

    approx = any(mk in s for mk in _APPROX_MARKERS)

    # Скобочные уточнения отбрасываем: они чаще комментируют, чем сужают.
    s = _RE_CLEAN_PAREN.sub(" ", s)
    s = _RE_SPACES.sub(" ", s).strip().strip(".,;:").strip()
    s = re.sub(r"^(?:с|в|от)\s+", "", s)
    s = re.sub(r"\s*(?:и\s+)?(?:позже|ранее|раньше|после|до)\s*$", "", s).strip()
    if not s:
        return Period(None, None, "unknown", approx, raw)

    for mk in _APPROX_MARKERS:
        if s.startswith(mk + " "):
            s = s[len(mk) + 1:].strip()

    atom = _parse_atom(s)
    if atom:
        lo, hi, prec = atom
        return Period(lo, hi, prec, approx, raw)

    m = _RE_FULL_CENTURY_SPAN.match(s)
    if m:
        return Period(_century_bounds(int(m["a"]))[0], _century_bounds(int(m["b"]))[1],
                      "century", approx, raw)

    m = _RE_FULL_DECADE_SPAN.match(s)
    if m:
        a, b = int(m["a"]), m["b"]
        end = int(b) if len(b) >= 3 else int(str(a)[: 4 - len(b)] + b)
        return Period(a, end + 9, "decade", approx, raw)

    m = _RE_FULL_YEAR_SPAN.match(s)
    if m:
        a, b = int(m["a"]), m["b"]
        end = int(b) if len(b) >= 3 else int(str(a)[: 4 - len(b)] + b)
        if end >= a:
            return Period(a, end, "year", approx, raw)

    parts = _split_range(s)
    if parts:
        left, right = parts
        la, ra = _parse_atom(left), _parse_atom(right)
        # Эллипсис единицы измерения: «конец 19 - начало 20 в.», где «в.»
        # относится к обеим границам. Занимаем единицу у той стороны, где она есть.
        if ra and not la:
            for unit in (" в.", "-е гг."):
                retry = _parse_atom(left + unit)
                if retry:
                    la = retry
                    break
        if la and ra:
            prec = la[2] if PRECISION_ORDER.index(la[2]) >= PRECISION_ORDER.index(ra[2]) else ra[2]
            return Period(min(la[0], ra[0]), max(la[1], ra[1]), prec, approx, raw)
        if la and not ra:
            return Period(la[0], la[1], la[2], True, raw)
        if ra and not la:
            return Period(ra[0], ra[1], ra[2], True, raw)

    # Последняя попытка: собрать все четырёхзначные годы и века из текста.
    years = [int(y) for y in re.findall(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", s)]
    if years:
        return Period(min(years), max(years), "year", True, raw)
    cents = [int(c) for c in re.findall(r"\b(1[5-9]|20|21)\s*(?:вв?|века?|век)\b", s)]
    if cents:
        return Period(_century_bounds(min(cents))[0], _century_bounds(max(cents))[1],
                      "century", True, raw)

    return Period(None, None, "unknown", approx, raw)


def parse_year(value) -> Optional[int]:
    """Достаёт год из числа, даты или текста."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    m = _RE_ISO.match(s)
    if m:
        return int(m["y"])
    try:
        f = float(s)
        if 1000 <= f <= 2100:
            return int(f)
    except ValueError:
        pass
    m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", s)
    return int(m.group(1)) if m else None
