"""Места захоронений жертв террора и ГУЛАГа: «Некрополь террора и ГУЛАГа».

Зачем отдельный источник. Слой `repressions` собран из Викиданных и держит
тюрьмы, расстрельные полигоны и братские могилы, у которых есть свой элемент;
кладбищ спецпоселенцев и депортированных в Викиданных нет как класса (см.
`queries/repressions.rq`). Слой `gulag_camps` даёт управления лагерей, а не
кладбища при них. «Некрополь террора и ГУЛАГа» (Фонд Иоффе, справочник
«Мемориала») — выборочный перечень мест захоронений с координатой,
датировкой и типом: тайное захоронение расстрелянных, лагерное кладбище,
кладбище спецпоселенцев. Для потомка это ответ на вопрос «где лежит» там, где
архивная справка говорит только «расстрелян» или «умер в спецпосёлке».

Откуда берётся. Русский `mapofmemory.org` из этой среды не отвечает,
английская версия `en.mapofmemory.org` (перевод Дж. Кроуфута, открыта
05.08.2021) — отвечает. Главная страница несёт все точки карты в
`Drupal.settings.yandexViews.markers`: широта, долгота и всплывающая подсказка
с кодом карточки (`59-01`: регион — номер места), названием и адресом.
Датировка, тип захоронения, нынешнее использование и охранный статус — только
в карточке, поэтому за каждой точкой идёт один запрос.

Что берётся и что не берётся:

* **Берутся факты** — координата, код и название места, адрес, датировка
  захоронения, тип, нынешнее использование, наличие памятных знаков,
  охранный статус и ссылка на карточку.
* **Не берутся тексты и снимки.** Справка («Background»), разделы о книгах
  памяти и источниках — авторское изложение; подписи к снимкам и сами снимки
  принадлежат «Мемориалу» и архивам. Условий использования сайт не
  публикует, значит права не выяснены, и слой хранит ссылку, а не пересказ.
* **Не берутся персоналии.** Имена расстрелянных и похороненных в справках
  есть — в слой они не идут ни в каком виде.

`robots.txt` сайта закрывает служебные пути Drupal, поиск и
`/год-захоронений`; карточки и главная открыты, `Crawl-delay: 10`. Сборщик
сверяет это перед обходом и держит паузу не короче указанной.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..geo import in_bbox, valid_coords
from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..periods import PRECISION_ORDER, Period, parse_period
from ..schema import ContextRecord, LayerSpec, clean_text

BASE_URL = "https://en.mapofmemory.org"
INDEX_URL = BASE_URL + "/"
ROBOTS_URL = BASE_URL + "/robots.txt"
CARD_URL = BASE_URL + "/{code}"

# Пауза между запросами — из `Crawl-delay` в robots.txt сайта (10 секунд на
# 24.10.2026). Короче сборщик не ходит, даже если robots.txt её снимет.
CRAWL_DELAY = 10.0

# Сколько точек было на главной при проверке 24.10.2026; совпадает с числом
# «411 sites» на странице KEY. Расхождение — повод посмотреть, что изменилось,
# а не молча собрать другое число.
EXPECTED_MARKERS = 411

BURIAL_SITES_TERROR = LayerSpec(
    slug="burial_sites_terror",
    title="Места захоронений жертв террора и ГУЛАГа",
    group="hardship",
    source="«Некрополь террора и ГУЛАГа» (Фонд Иоффе, «Мемориал»), английская версия",
    license=(
        "права не выяснены: условий использования сайт не публикует. Берутся "
        "факты — координата, датировка, тип, адрес — и ссылка на карточку; "
        "справки, подписи и снимки не копируются"
    ),
    description=(
        "Выборочный перечень мест захоронений жертв политических репрессий: тайные "
        "захоронения расстрелянных, лагерные кладбища, кладбища спецпоселенцев и "
        "депортированных — с координатой, годами захоронений и типом места. "
        "Закрывает то, чего нет в слое repressions: кладбища спецпоселений как места."
    ),
    url=INDEX_URL,
    status="harvested",
    expected_rows=411,
)

# Поля карточки, на которых держится разбор. Нет хотя бы одного у всех
# карточек разом — сайт переделали, и сбор должен остановиться.
REQUIRED_CARD_FIELDS = ("nane", "data-zahoron-text", "tipologia")

# Поля карточки, которые идут в слой: машинное имя Drupal → ключ в записи.
# Остальные — справка, книги памяти, источники, снимки — не берутся (см.
# шапку модуля), и разбор их не читает вовсе.
CARD_FIELDS = {
    "nane": "name",
    "data-zahoron-text": "date",
    "maps-data-test": "address",
    "tipologia": "burial_type",
    "harakter-isp": "current_use",
    "dostup-nalich": "memorials",
    "systemohran-kategor": "protected",
}

_RE_SETTINGS = re.compile(
    r"jQuery\.extend\(Drupal\.settings,\s*(\{.*?\})\);\s*(?://--><!\]\]>|</script>)", re.S)
_RE_HREF = re.compile(r'href="([^"]+)"')
_RE_BALLOON_NAME = re.compile(r'class="balloon_name">(.*?)</div>', re.S)
_RE_BALLOON_ADR = re.compile(r'class="balloon_adr">(.*?)</div>', re.S)
_RE_CODE = re.compile(r"^\d{2,3}-\d{2,3}[a-z]?$")
_RE_CARD_NO = re.compile(r'class="card_no">\s*№?\s*([^<]+?)\s*</h2>')
_RE_FIELD = re.compile(r'<div class="field field-name-field-([\w-]+) ')
_RE_ITEM = re.compile(r'<div class="field-item[^"]*">(.*?)</div>', re.S)
_RE_TAG = re.compile(r"<[^>]+>")

# Пометки в названии места — не тип, а памятные мероприятия (страница KEY,
# раздел 4): [C] — ежегодные, (c) — время от времени, (s) — несколько раз в
# год, * — иное уместное использование. Плюс {RF}, [P], [ss] и пр. Из названия
# они вынимаются в отдельное поле, чтобы не мешать поиску по названию.
_RE_MARKS = re.compile(r"\s*[\[\{\(]([A-Za-z]{1,3})[\]\}\)](\**)\s*")


class MapOfMemoryError(RuntimeError):
    """Запрос к сайту не выполнен или страница не такая, какой мы её ждём."""


# --- главная страница: точки ------------------------------------------------

@dataclass
class Marker:
    """Точка с главной страницы: всё, что известно до захода в карточку."""

    code: str
    lat: float
    lon: float
    name: Optional[str]
    address: Optional[str]


def parse_markers(page: str) -> list[Marker]:
    """Достаёт точки из `Drupal.settings.yandexViews.markers` главной страницы."""
    match = _RE_SETTINGS.search(page)
    if not match:
        raise MapOfMemoryError("на главной нет Drupal.settings: разметку сайта поменяли")
    try:
        settings = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise MapOfMemoryError(f"Drupal.settings не разбирается как JSON ({exc})") from exc
    raw = (settings.get("yandexViews") or {}).get("markers")
    if not isinstance(raw, list) or not raw:
        raise MapOfMemoryError("в Drupal.settings нет yandexViews.markers")

    out = []
    for item in raw:
        balloon = item.get("url") or item.get("description") or ""
        href = _RE_HREF.search(balloon)
        code = href.group(1).strip("/").rsplit("/", 1)[-1] if href else None
        if not code or not _RE_CODE.match(code):
            raise MapOfMemoryError(f"у точки нет кода карточки вида 59-01: {balloon[:120]!r}")
        lat, lon = item.get("lat"), item.get("lng")
        if not valid_coords(lat, lon):
            raise MapOfMemoryError(f"{code}: координата не разбирается ({lat!r}, {lon!r})")
        name = _RE_BALLOON_NAME.search(balloon)
        adr = _RE_BALLOON_ADR.search(balloon)
        out.append(Marker(code=code, lat=float(lat), lon=float(lon),
                          name=_text(name.group(1)) if name else None,
                          address=_text(adr.group(1)) if adr else None))
    return out


# --- карточка ----------------------------------------------------------------

def parse_card(page: str) -> dict:
    """Разбирает карточку места в словарь фактов.

    Значение поля — список: тип захоронения и нынешнее использование бывают
    множественными («Ceremonial events», «Excursions»). Читаются только поля
    из `CARD_FIELDS`; справка и снимки не трогаются.
    """
    out: dict = {"fields": set()}
    card_no = _RE_CARD_NO.search(page)
    out["card_no"] = clean_text(html.unescape(card_no.group(1))) if card_no else None

    starts = [(m.start(), m.group(1)) for m in _RE_FIELD.finditer(page)]
    for i, (pos, name) in enumerate(starts):
        out["fields"].add(name)
        key = CARD_FIELDS.get(name)
        if key is None:
            continue
        end = starts[i + 1][0] if i + 1 < len(starts) else len(page)
        chunk = page[pos:end]
        items = [_text(x) for x in _RE_ITEM.findall(chunk)]
        out[key] = [x for x in items if x]
    return out


def check_card(card: dict, code: str) -> None:
    """Номер карточки совпадает с адресом, а название на месте.

    Тип и датировку проверяет `check_cards` по всему набору: пустое поле у
    одной карточки — пропуск в данных (у 14-12 нет типа), а не новая разметка.
    """
    if "nane" not in card["fields"]:
        raise MapOfMemoryError(
            f"{code}: в карточке нет названия (field-nane); есть {sorted(card['fields'])}. "
            "Разметку сайта поменяли — поправьте разбор, а не подгоняйте его"
        )
    if card.get("card_no") and card["card_no"] != code:
        raise MapOfMemoryError(f"{code}: в карточке номер {card['card_no']!r}")


def check_cards(cards: dict[str, dict]) -> dict[str, list[str]]:
    """Обязательные поля есть у набора карточек; у каких карточек их нет.

    Поля нет ни у одной карточки — сайт переделали, сбор останавливается.
    Нет у отдельных — возвращается перечень, и записи этих карточек остаются
    в слое с пометкой.
    """
    gaps = {f: sorted(code for code, card in cards.items() if f not in card["fields"])
            for f in REQUIRED_CARD_FIELDS}
    gone = [f for f, codes in gaps.items() if cards and len(codes) == len(cards)]
    if gone:
        raise MapOfMemoryError(
            f"поля {gone} нет ни в одной из {len(cards)} карточек: разметку сайта "
            "поменяли — поправьте разбор, а не подгоняйте его"
        )
    return {f: codes for f, codes in gaps.items() if codes}


# --- датировка ---------------------------------------------------------------

_EN_MONTHS = {
    "january": "январь", "february": "февраль", "march": "март", "april": "апрель",
    "may": "май", "june": "июнь", "july": "июль", "august": "август",
    "september": "сентябрь", "october": "октябрь", "november": "ноябрь",
    "december": "декабрь",
}
_EN_SEASONS = {"winter": "зима", "spring": "весна", "summer": "лето",
               "autumn": "осень", "fall": "осень"}
_EN_DECADE_PARTS = {"early": "начало", "mid": "середина", "late": "конец"}
_EN_APPROX = ("c.", "ca.", "circa", "about", "approximately", "around")

_RE_BRACKETS = re.compile(r"\[[^\]]*\]")
# «1930s», «late 1930s», «mid-1940s». «mid-1940 to 1950s» — без «s», но тоже
# десятилетие: середина 1940 года до 1950-х читалась бы как 1950-е целиком.
_RE_EN_DECADE = re.compile(
    r"\b(?:(early|mid|late)[\s-]+(1\d{2}0)(?:['’]?s)?|(1\d{2}0)['’]?s)\b")
_EN_MONTH_ABBR = {"jan": "january", "feb": "february", "mar": "march", "apr": "april",
                  "jun": "june", "jul": "july", "aug": "august", "sep": "september",
                  "sept": "september", "oct": "october", "nov": "november", "dec": "december"}
_RE_EN_ABBR = re.compile(r"\b(" + "|".join(_EN_MONTH_ABBR) + r")\.(?=\s)")
_RE_EN_DAY = re.compile(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$")


def english_period(text: Optional[str]) -> Optional[str]:
    """Переводит английскую датировку карточки в русскую для `parse_period`.

    «1940s–1950s» → «1940-е–1950-е», «late 1930s» → «конец 1930-х»,
    «November 1941» → «ноябрь 1941». Разборщик периодов в проекте один, и
    второй, английский, рядом с ним не нужен: достаточно сказать ему те же
    слова по-русски.
    """
    s = clean_text(text)
    if s is None:
        return None
    # «1940s [2003]»: в квадратных скобках — позднейшее событие (перезахоронение,
    # памятник), а не годы захоронений. В разбор не идёт, исходник остаётся
    # в `period_raw`.
    s = clean_text(_RE_BRACKETS.sub(" ", s).lower())
    if s is None:
        return None
    approx = any(s.startswith(mark + " ") or s.startswith(mark) and mark.endswith(".")
                 for mark in _EN_APPROX)
    for mark in _EN_APPROX:
        if s.startswith(mark):
            s = s[len(mark):].strip()
            break

    def decade(m: re.Match) -> str:
        part, year = m.group(1), m.group(2) or m.group(3)
        if part:
            return f"{_EN_DECADE_PARTS[part]} {year}-х"
        return f"{year}-е"

    s = _RE_EN_ABBR.sub(lambda m: _EN_MONTH_ABBR[m.group(1)], s)
    s = _RE_EN_DECADE.sub(decade, s)
    for en, ru in {**_EN_MONTHS, **_EN_SEASONS}.items():
        s = re.sub(rf"\b{en}\b", ru, s)
    s = re.sub(r"\b(?:and|&)\b", "и", s)
    s = re.sub(r"\b(?:to|until|till)\b", "по", s)
    s = re.sub(r"\b(?:from|in|since)\b\s*", "", s).strip()
    return ("около " + s) if approx else s


def burial_period(text: Optional[str]) -> Period:
    """Датировка захоронения из карточки — `Period` из `histctx.periods`.

    Две формы разбираются здесь, а не общим разборщиком. Дата до дня
    («11 September 1941») — общий её не знает и огрубил бы до года с пометкой
    «приблизительно». Перечень через запятую или точку с запятой
    («1923, 1930s-1950s», «Dec. 1935; Feb. 1938») — общий берёт из него
    последний кусок; здесь каждый кусок разбирается отдельно, а границы
    берутся по крайним.
    """
    raw = "" if text is None else str(text)
    s = english_period(text)
    if s is None:
        return Period(None, None, "unknown", False, raw)
    day = _RE_EN_DAY.match(_RE_BRACKETS.sub(" ", raw).strip().lower())
    if day and day.group(2) in _EN_MONTHS and 1 <= int(day.group(1)) <= 31:
        year = int(day.group(3))
        return Period(year, year, "day", False, raw)
    pieces = [p.strip() for p in re.split(r"[;,]", s) if p.strip()]
    if len(pieces) < 2:
        return parse_period(s)
    parsed = [parse_period(p) for p in pieces]
    if not all(p.ok for p in parsed):
        return parse_period(s)
    precision = max((p.precision for p in parsed), key=PRECISION_ORDER.index)
    return Period(min(p.year_from for p in parsed), max(p.year_to for p in parsed),
                  precision, any(p.approx for p in parsed), raw)


# --- запись схемы ------------------------------------------------------------

# Типы захоронения — поле «Type of burial» карточки. Словарь закрытый: при
# сборе 24.10.2026 в 411 карточках встретились только эти значения. Незнакомое
# не теряется — идёт в категорию по-английски, как есть, и видно в --build.
BURIAL_TYPES = {
    "secret interment of executed": "тайное захоронение расстрелянных",
    "camp (prison) burial ground": "лагерное (тюремное) кладбище",
    "deportees’ graveyard": "кладбище спецпоселенцев и депортированных",
    "reburial": "перезахоронение",
    "individual grave": "отдельная могила",
}


# Охранный статус места («Protected status») — тоже закрытый словарь.
PROTECTED = {
    "not protected": "не охраняется",
    "local": "охраняется как памятник местного значения",
    "regional / republican": "охраняется как памятник регионального значения",
    "national (russian federation)": "охраняется как памятник федерального значения",
}


def split_marks(name: Optional[str]) -> tuple[Optional[str], list[str]]:
    """Отделяет пометки KEY («[C]*», «(c)») от названия места."""
    if not name:
        return name, []
    marks = [f"{m.group(0).strip()}" for m in _RE_MARKS.finditer(name)]
    title = clean_text(_RE_MARKS.sub(" ", name))
    return title, marks


def card_to_record(marker: Marker, card: dict, spec: LayerSpec = BURIAL_SITES_TERROR, *,
                   provinces=None) -> ContextRecord:
    """Точка с главной и карточка — одна запись схемы.

    Датировки нет или она не разобралась — запись всё равно сохраняется,
    с `confidence="no_date"`: молча выбрасывать место нельзя, а на карте по
    времени оно и так не встанет.
    """
    name = _first(card.get("name")) or marker.name or marker.code
    title, marks = split_marks(name)
    date_raw = _first(card.get("date"))
    period = burial_period(date_raw)
    types = card.get("burial_type") or []
    category = "; ".join(BURIAL_TYPES.get(t.lower().replace("'", "’"), t)
                         for t in types) or None
    address = _first(card.get("address")) or marker.address

    extra = {"card": marker.code}
    if types:
        extra["burial_type_en"] = types
    for key in ("current_use", "memorials", "protected"):
        if card.get(key):
            extra[key] = card[key]
    if marks:
        extra["marks"] = marks
    later = _RE_BRACKETS.findall(date_raw or "")
    if later:
        # «1940s [2003]»: что значит год в скобках, сайт не поясняет; в разбор
        # датировки он не идёт и хранится отдельно, как есть.
        extra["date_bracket"] = [x.strip("[] ") for x in later]

    confidence = "ok"
    if not period.ok:
        confidence = "no_date"
    if not in_bbox(marker.lat, marker.lon):
        confidence = "outside_bbox"

    region = provinces.region_for(marker.lat, marker.lon) if provinces is not None else None
    return spec.new_record(
        title=title or marker.code,
        category=category,
        lat=marker.lat, lon=marker.lon,
        place_text=address,
        region=region,
        year_from=period.year_from,
        year_to=period.year_to,
        date_precision=period.precision if period.ok else "unknown",
        date_approx=bool(period.approx),
        period_raw=date_raw,
        summary=build_summary(category, date_raw, card),
        url=CARD_URL.format(code=marker.code),
        source_id=marker.code,
        confidence=confidence,
        extra=extra,
    )


def build_summary(category: Optional[str], date_raw: Optional[str], card: dict) -> str:
    """Фраза из полей карточки, а не пересказ справки."""
    parts = []
    if category:
        parts.append(category)
    if date_raw:
        parts.append(f"датировка захоронений по карточке — {date_raw}")
    protected = _first(card.get("protected"))
    if protected:
        parts.append(PROTECTED.get(protected.lower(), f"охранный статус — {protected}"))
    parts.append("справка и источники — на карточке «Некрополя»")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


# --- близость к уже собранным слоям -------------------------------------------

def mark_neighbours(records: list[ContextRecord], others: dict[str, list[tuple]], *,
                    radius_km: float) -> dict[str, int]:
    """Помечает записи, рядом с которыми есть точка другого слоя.

    `others` — `{слой: [(lat, lon, uid, title), ...]}`. Ближайшая точка в
    радиусе пишется в `extra["near"][слой]`; запись не удаляется: одно и то же
    кладбище в двух слоях — повод сверить, а не выбросить (правило
    репозитория). Возвращает число помеченных записей по слоям.
    """
    from ..geo import haversine_km

    counts = dict.fromkeys(others, 0)
    for rec in records:
        for layer, points in others.items():
            best = None
            for lat, lon, uid, title in points:
                if abs(lat - rec.lat) > radius_km / 111.0 + 0.01:
                    continue
                d = haversine_km(rec.lat, rec.lon, lat, lon)
                if d <= radius_km and (best is None or d < best[0]):
                    best = (d, uid, title)
            if best:
                rec.extra.setdefault("near", {})[layer] = {
                    "uid": best[1], "title": best[2], "km": round(best[0], 2)}
                counts[layer] += 1
    return counts


# --- сеть и кэш ----------------------------------------------------------------

@dataclass
class Client:
    """Вежливый обход: пауза не короче Crawl-delay, повтор на 429/5xx, кэш."""

    cache_dir: Path
    pause: float = CRAWL_DELAY
    timeout: int = 90
    retries: int = 3
    _last: float = field(default=0.0, repr=False)
    requests: int = field(default=0, repr=False)

    def get(self, url: str) -> str:
        for attempt in range(self.retries + 1):
            self._last = wait_for_pause(self._last, self.pause)
            self.requests += 1
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_CODES and attempt < self.retries:
                    time.sleep(self.pause * (attempt + 1))
                    continue
                raise MapOfMemoryError(f"{url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(self.pause * (attempt + 1))
                    continue
                reason = getattr(exc, "reason", exc)
                raise MapOfMemoryError(f"{url}: сеть недоступна ({reason})") from exc
        raise MapOfMemoryError(f"{url}: не ответил за {self.retries + 1} попыток")

    def robots(self) -> urllib.robotparser.RobotFileParser:
        """Читает robots.txt и поднимает паузу до его Crawl-delay."""
        parser = urllib.robotparser.RobotFileParser(ROBOTS_URL)
        parser.parse(self.get(ROBOTS_URL).splitlines())
        delay = parser.crawl_delay("*")
        if delay:
            self.pause = max(self.pause, float(delay))
        return parser

    def cached(self, name: str, url: str, *, refresh: bool = False) -> str:
        """Страница из кэша или из сети; в кэш пишется только целый ответ."""
        path = self.cache_dir / name
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")
        text = self.get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return text


def card_cache_name(code: str) -> str:
    return f"cards/{code}.html"


def allowed(parser: urllib.robotparser.RobotFileParser, url: str) -> bool:
    return parser.can_fetch("*", url)


# --- мелочи ----------------------------------------------------------------------

def _text(fragment: str) -> Optional[str]:
    return clean_text(html.unescape(_RE_TAG.sub(" ", fragment)).replace("\xa0", " "))


def _first(values) -> Optional[str]:
    return values[0] if values else None
