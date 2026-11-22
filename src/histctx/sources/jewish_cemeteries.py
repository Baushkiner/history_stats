"""Еврейские кладбища: обследование European Jewish Cemeteries Initiative (ESJF).

Зачем этот слой. Метрические книги раввинатов сохранились плохо, а там, где
сохранились, они говорят «похоронен на местном кладбище» — и только. Слой
`cemeteries` из Викиданных знает еврейские кладбища городов, у которых есть
своя статья; кладбищ местечек черты оседлости в нём почти нет. ESJF с 2015
года обходит их одно за другим: с дроном, замером периметра и проверкой на
месте, — и для каждого пишет карточку: где оно, сохранилось ли, сколько
надгробий осталось и каких они лет. Для потомка это ответ на два вопроса:
есть ли куда поехать — и годится ли кладбище как источник, то есть стоят ли
на нём надгробия тех лет, когда умер предок.

Откуда берётся. Карточки обследования лежат по адресу `/survey/<slug>/`,
перечислены они в пяти картах сайта `survey-sitemap.xml` …
`survey-sitemap5.xml` (4 276 карточек на 22.11.2026). `robots.txt` сайта
закрывает `/wp-json/` и любые адреса с параметрами (`/*?`) — поэтому REST
WordPress, через который карта сайта подгружает точки, сборщиком не
запрашивается, хотя и отвечает; обходятся только карты сайта и сами
карточки.

Почему слой ещё не собран. Перед сайтом стоит защита хостинга: на частые
запросы вместо карточки приходит страница проверки «Захищена сторінка» с
кодом 429 и без `Retry-After`. Замер 22.11.2026: при запросе раз в три
секунды — отказ через раз, около десяти карточек в минуту; после серии
отказов защита ужесточается, и при паузе в шесть секунд за пять минут
проходят четыре карточки. Страница проверки ждёт браузера с JavaScript;
решать её за браузер, менять адрес или подпись — значит обходить защиту, а
этого сборщик не делает (так же решено с базой НАРБ, см. `docs/HARVEST.md`).
Повторный обход 22.11.2026 с паузой в секунду за двенадцать минут добавил
десять карточек — защита пропускает около одной в минуту, и обход остановлен.
Поэтому слой собран неполным, из того, что успело лечь в кэш: 40 карточек из
4 276 (`--build --partial`), и начинаются карты сайта с Греции — в рамке
РИ/СССР из них семь. Обход останавливается сам после пяти отказов подряд, а
полный сбор ждёт договорённости с ESJF (info@esjf-cemeteries.org) —
разрешения на медленный обход или выгрузки.

Что в карточке. Таблица полей: страна, область, район, населённый пункт,
адрес, координата GPS, длина периметра, снесено ли кладбище, ограда,
состояние («Fenced and protected Jewish cemetery», «Demolished and overbuilt
Jewish cemetery» …), общее состояние словами, число сохранившихся
надгробий, даты древнейшего и новейшего надгробия, срочность ограды,
владелец земли, постройки, съёмка с дрона; ниже — исторический очерк.

Права. «Copyright — All Rights Reserved — ESJF»; лицензии сайт не заявляет.
Значит, по условию 3 каталога берутся факты — точка, место, годы надгробий,
состояние, снесено ли, число надгробий, периметр, владелец земли — и ссылка
на карточку. Очерк, описания состояния и адреса словами, снимки и
трёхмерные модели остаются на сайте.

Где запись во времени. Годы — по надгробиям: древнейшее → `year_from`,
новейшее → `year_to`, точность `year`. Известен один конец — второй берётся
из горизонта проекта, как у зданий из Викиданных (`wikidata.rows_to_records`):
древнейшее надгробие 1906 года без новейшего — «1906–1960», `open`;
новейшее без древнейшего — от 1800 года. Нет ни одного — запись остаётся
без датировки: год основания из очерка не выдумывается. «1856/5616» — год
по христианскому и еврейскому счёту, берётся первый.

Где запись на карте. Точка карточки — координата GPS самого кладбища.
Рамка — `histctx.frame.Frame`: губерния 1897 года у точки внутри губерний,
`outside_bbox` у Греции, Словакии, Хорватии и Галиции — запись остаётся в
слое, на карте она видна.
"""

from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..geo import valid_coords
from ..net import USER_AGENT, wait_for_pause
from ..periods import PRECISION_OPEN
from ..schema import ContextRecord, LayerSpec, clean_text
from .russian_names import RussianNames

BASE_URL = "https://www.esjf-cemeteries.org"
ROBOTS_URL = BASE_URL + "/robots.txt"
SITEMAPS = tuple(f"{BASE_URL}/survey-sitemap{suffix}.xml" for suffix in ("", "2", "3", "4", "5"))
CARD_PREFIX = BASE_URL + "/survey/"
MAP_URL = BASE_URL + "/surveys-map/"

# Сколько карточек было в картах сайта при сборе 22.11.2026. Новые обследования
# добавляются каждый месяц; расхождение не ошибка, а повод посмотреть, сколько
# прибавилось, — сборщик его печатает.
EXPECTED_CARDS = 4276

# Пауза между запросами. Замер 22.11.2026: при запросе раз в три секунды сервер
# отказывает 429 через раз, а `Retry-After` не присылает. При отказе обход
# стоит минуту, пауза растёт на полсекунды (до потолка), после серии удачных
# запросов возвращается к исходной; пять отказов подряд — защита сайта не
# пускает сборщик, и обход останавливается (см. шапку модуля).
PAUSE = 6.0
PAUSE_STEP = 0.5
PAUSE_MAX = 12.0
COOLDOWN = 60.0
STREAK = 30
MAX_REFUSALS_IN_ROW = 5
# Страница защиты хостинга, которую сайт отдаёт вместо карточки.
PROTECTION_MARK = "Захищена сторінка"

# Горизонты открытого срока — те же, что у зданий из Викиданных.
OPEN_END_YEAR = 1960
OPEN_START_YEAR = 1800
# Годы, которые принимаются за год надгробия: раньше — опечатка или еврейский
# счёт без христианского, позже — сегодняшний день.
YEAR_MIN, YEAR_MAX = 1300, 2030

LICENSE = (
    "права не выяснены: «Copyright — All Rights Reserved — ESJF», лицензии сайт не "
    "заявляет. Берутся факты — точка, место, годы надгробий, состояние, число "
    "надгробий — и ссылка на карточку; очерки, описания и снимки не копируются. "
    "Полный обход — после договорённости: сайт защищён страницей проверки"
)

JEWISH_CEMETERIES = LayerSpec(
    slug="jewish_cemeteries",
    title="Еврейские кладбища (обследование ESJF)",
    group="faith",
    source="European Jewish Cemeteries Initiative (ESJF), карточки обследования",
    license=LICENSE,
    description=(
        "Еврейские кладбища местечек и городов Восточной Европы по обследованию ESJF: "
        "точка GPS, сохранилось ли кладбище или снесено и застроено, сколько надгробий "
        "осталось, годы древнейшего и новейшего надгробия. Отвечает, есть ли куда "
        "поехать и стоят ли на кладбище надгробия лет, когда умер предок. Собран "
        "неполным: 40 карточек из 4 276 — сайт отвечает сборщику страницей защиты, "
        "полный обход ждёт договорённости (замер 22.11.2026, docs/DISCOVERY.md)."
    ),
    url=MAP_URL,
    status="harvested",
    # Измерено 22.11.2026: столько карточек успело лечь в кэш до остановки обхода;
    # в картах сайта их 4 276 (EXPECTED_CARDS).
    expected_rows=40,
)

# Поля карточки: подпись на сайте → ключ в записи. Читаются только они;
# очерк («Historical overview») разбор не трогает.
CARD_FIELDS = {
    "Country": "country",
    "Region": "region",
    "District": "district",
    "Settlement": "settlement",
    "GPS coordinates": "gps",
    "Perimeter length": "perimeter",
    "Is the cemetery demolished": "demolished",
    "Preservation condition": "condition",
    "Number of existing gravestones": "gravestones",
    "Date of oldest tombstone": "oldest",
    "Date of newest tombstone": "newest",
    "Urgency of erecting a fence": "fence_urgency",
    "Land ownership": "ownership",
    "Drone surveys": "drone",
}
# Без них карточка не разбирается: сайт переделали.
REQUIRED_FIELDS = ("Country", "Settlement", "GPS coordinates")

# Состояние кладбища — закрытый словарь сайта. Незнакомое значение не
# теряется: идёт в категорию по-английски, как есть, и видно в --check.
CONDITIONS = {
    "fenced and protected jewish cemetery": "огорожено и охраняется",
    "unfenced jewish cemetery": "без ограды",
    "demolished and overbuilt jewish cemetery": "снесено и застроено",
    "demolished jewish cemetery that has not been built over": "снесено, не застроено",
    "jewish section": "еврейский участок общего кладбища",
    "jewish section of general cemetery": "еврейский участок общего кладбища",
    "partially demolished jewish cemetery": "снесено частично",
    "mass grave": "братская могила",
}

# Страны карточек по-русски — для подписи; незнакомая идёт как есть.
COUNTRIES = {
    "Ukraine": "Украина", "Poland": "Польша", "Lithuania": "Литва", "Latvia": "Латвия",
    "Belarus": "Белоруссия", "Moldova": "Молдавия", "Russia": "Россия",
    "Georgia": "Грузия", "Slovakia": "Словакия", "Greece": "Греция", "Croatia": "Хорватия",
    "Czech Republic": "Чехия", "Hungary": "Венгрия", "Romania": "Румыния",
    "Serbia": "Сербия", "Estonia": "Эстония", "Bulgaria": "Болгария",
    "North Macedonia": "Северная Македония", "Austria": "Австрия",
    "Bosnia and Herzegovina": "Босния и Герцеговина", "Slovenia": "Словения",
}

_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_RE_LASTMOD = re.compile(r"<url>\s*<loc>\s*([^<\s]+)\s*</loc>\s*<lastmod>\s*([^<\s]+)\s*</lastmod>")
_RE_ITEM = re.compile(
    r'<div class="text-block-7">\s*(.*?)\s*</div>.*?<div class="srv-right[^"]*">(.*?)</div>',
    re.S)
_RE_H1 = re.compile(r'<h1[^>]*class="h1-inside"[^>]*>(.*?)</h1>', re.S)
_RE_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_GPS = re.compile(r"(-?\d{1,2}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)")
_RE_YEAR = re.compile(r"(?<!\d)(1[3-9]\d\d|20[0-3]\d)(?!\d)")
_RE_NUMBER = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ ,]\d{3})+|\d+)(?![\d])")
_RE_METRES = re.compile(r"(\d[\d ,.]*)\s*(?:m|м)", re.I)
# Начала поля «Number of existing gravestones», означающие «не сохранилось ни одного».
_NONE_LEFT = ("no tombstones", "no gravestones", "no preserved", "no matzevot", "none",
              "not preserved", "there are no")


class EsjfError(RuntimeError):
    """Сайт не ответил или карточка не такая, какой её ждёт разбор."""


# --- карты сайта -------------------------------------------------------------

def parse_sitemap(xml: str) -> list[tuple[str, Optional[str]]]:
    """Адреса карточек и даты их правки из одной карты сайта."""
    dated = dict(_RE_LASTMOD.findall(xml))
    out = []
    for url in _RE_LOC.findall(xml):
        url = html.unescape(url)
        if not url.startswith(CARD_PREFIX):
            continue
        out.append((url, dated.get(url)))
    return out


def card_slug(url: str) -> str:
    """`…/survey/fastiv-jewish-cemetery/` → `fastiv-jewish-cemetery`."""
    tail = url[len(CARD_PREFIX):] if url.startswith(CARD_PREFIX) else url
    slug = tail.strip("/")
    if not slug or "/" in slug or "?" in slug or not re.fullmatch(r"[\w%.-]+", slug):
        raise EsjfError(f"не адрес карточки обследования: {url!r}")
    return slug


def card_cache_name(slug: str) -> str:
    return f"cards/{slug}.html"


def url_allowed(url: str, parser: Optional[urllib.robotparser.RobotFileParser] = None) -> bool:
    """Открыт ли адрес для сбора.

    `urllib.robotparser` шаблонов со звёздочкой не понимает, а у ESJF закрыто
    именно `/*?` — любой адрес с параметрами. Поэтому сверх ответа разборщика
    проверяется руками: ни параметров, ни `/wp-json/`.
    """
    if "?" in url or "/wp-json/" in url:
        return False
    return parser.can_fetch("*", url) if parser is not None else True


# --- карточка ----------------------------------------------------------------

def _text(fragment: str) -> Optional[str]:
    return clean_text(html.unescape(_RE_TAG.sub(" ", fragment)).replace("\xa0", " "))


def parse_card(page: str) -> dict:
    """Поля карточки по подписям сайта. Пустое значение — отсутствующее поле."""
    out: dict = {"labels": []}
    h1 = _RE_H1.search(page) or _RE_TITLE.search(page)
    title = _text(h1.group(1)) if h1 else None
    if title:
        title = re.sub(r"\s*[–—-]\s*ESJF Surveys\s*$", "", title)
    out["title"] = title
    for label, value in _RE_ITEM.findall(page):
        label = _text(label) or ""
        out["labels"].append(label)
        key = CARD_FIELDS.get(label)
        if key and key not in out:
            text = _text(value)
            if text:
                out[key] = text
    return out


def check_card(card: dict, slug: str) -> None:
    """Подписи, на которых держится разбор, есть в карточке."""
    missing = [f for f in REQUIRED_FIELDS if f not in card["labels"]]
    if missing:
        raise EsjfError(
            f"{slug}: в карточке нет полей {missing}; есть {card['labels'][:20]}. "
            "Разметку сайта поменяли — поправьте разбор, а не подгоняйте его")


def gps_point(text: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """«50.08836, 29.92844» → (50.08836, 29.92844). Не похоже — (None, None)."""
    if not text:
        return None, None
    m = _RE_GPS.search(text)
    if not m:
        return None, None
    lat, lon = (float(x.replace(",", ".")) for x in m.groups())
    if not valid_coords(lat, lon):
        return None, None
    return lat, lon


def tombstone_year(text: Optional[str]) -> Optional[int]:
    """Год надгробия из поля карточки.

    «1906» → 1906; «At least 1856/5616. Requires additional research.» → 1856
    (через косую — год по еврейскому счёту, он вне рамки и отсеивается сам);
    «N/A», «Requires additional research», пусто → None. Век словами
    («19th century») — не год: точнее столетия он ничего не говорит, и запись
    остаётся без этого конца, а исходник — в `period_raw`.
    """
    if not text:
        return None
    for m in _RE_YEAR.finditer(text):
        year = int(m.group(1))
        if YEAR_MIN <= year <= YEAR_MAX:
            return year
    return None


def gravestone_count(text: Optional[str]) -> Optional[int]:
    """Число сохранившихся надгробий: «Around 500» → 500, «No tombstones» → 0.

    Берётся первое число поля; диапазон («100-150») — его нижняя граница.
    Слова после числа — описание ESJF, в слой не идут.
    """
    if not text:
        return None
    low = text.strip().lower()
    if low in {"no", "none", "0"} or low.startswith(_NONE_LEFT):
        return 0
    m = _RE_NUMBER.search(text)
    if not m:
        return None
    return int(re.sub(r"[ ,]", "", m.group(1)))


def perimeter_metres(text: Optional[str]) -> Optional[int]:
    """«540 metres» → 540; «261 мetres» (кириллическая «м» у сайта) → 261."""
    if not text:
        return None
    m = _RE_METRES.search(text) or _RE_NUMBER.search(text)
    if not m:
        return None
    digits = re.sub(r"[ ,]", "", m.group(1)).split(".")[0]
    return int(digits) if digits.isdigit() else None


def yes_no(text: Optional[str]) -> Optional[bool]:
    if not text:
        return None
    low = text.strip().lower()
    if low.startswith("yes"):
        return True
    if low.startswith("no"):
        return False
    return None


@dataclass
class Dating:
    year_from: Optional[int]
    year_to: Optional[int]
    precision: str
    approx: bool
    raw: Optional[str]


def dating(oldest_raw: Optional[str], newest_raw: Optional[str]) -> Dating:
    """Годы записи по двум надгробиям — правило шапки модуля."""
    oldest, newest = tombstone_year(oldest_raw), tombstone_year(newest_raw)
    parts = []
    if oldest_raw:
        parts.append(f"древнейшее надгробие: {oldest_raw}")
    if newest_raw:
        parts.append(f"новейшее надгробие: {newest_raw}")
    raw = "; ".join(parts) or None
    if oldest and newest:
        lo, hi = min(oldest, newest), max(oldest, newest)
        return Dating(lo, hi, "year", False, raw)
    if oldest:
        return Dating(oldest, max(oldest, OPEN_END_YEAR), PRECISION_OPEN, True, raw)
    if newest:
        return Dating(min(newest, OPEN_START_YEAR), newest, PRECISION_OPEN, True, raw)
    return Dating(None, None, "unknown", False, raw)


def condition_ru(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return CONDITIONS.get(text.strip().rstrip(".").lower(), text)


# --- запись схемы --------------------------------------------------------------

def card_to_record(url: str, card: dict, *, lastmod: Optional[str] = None,
                   names: Optional[RussianNames] = None,
                   spec: LayerSpec = JEWISH_CEMETERIES) -> ContextRecord:
    """Карточка обследования — одна запись схемы."""
    slug = card_slug(url)
    lat, lon = gps_point(card.get("gps"))
    settlement = card.get("settlement")
    place_ru = names.lookup(settlement, lat, lon) if (names and lat is not None) else None
    where = place_ru or settlement or card.get("title") or slug
    country = card.get("country")
    date = dating(card.get("oldest"), card.get("newest"))
    condition = condition_ru(card.get("condition"))
    demolished = yes_no(card.get("demolished"))
    stones = gravestone_count(card.get("gravestones"))

    extra = {
        "esjf_slug": slug,
        "title_en": card.get("title"),
        "country": country,
        "region_en": card.get("region"),
        "district_en": card.get("district"),
        "settlement_en": settlement,
        "condition_en": card.get("condition"),
        "demolished": demolished,
        "gravestones": stones,
        "perimeter_m": perimeter_metres(card.get("perimeter")),
        "fence_urgency": card.get("fence_urgency"),
        "land_ownership": card.get("ownership"),
        "drone_survey": yes_no(card.get("drone")),
        "lastmod": lastmod,
    }
    place_parts = [settlement, card.get("district"), card.get("region"), country]
    place_text = ", ".join(p for p in place_parts if p) or None

    return spec.new_record(
        title=f"Еврейское кладбище — {where}",
        category=condition,
        lat=lat, lon=lon,
        place_text=place_text,
        district=card.get("district"),
        year_from=date.year_from,
        year_to=date.year_to,
        date_precision=date.precision,
        date_approx=date.approx,
        period_raw=date.raw,
        summary=build_summary(country, condition, demolished, stones, date),
        url=url,
        source_id=slug,
        confidence="ok" if lat is not None else "no_coords",
        extra={k: v for k, v in extra.items() if v is not None},
    )


def build_summary(country: Optional[str], condition: Optional[str],
                  demolished: Optional[bool], stones: Optional[int], date: Dating) -> str:
    """Фраза из полей карточки, а не пересказ очерка."""
    parts = []
    if country:
        parts.append(COUNTRIES.get(country, country))
    if condition:
        parts.append(condition)
    elif demolished:
        parts.append("снесено")
    if stones == 0:
        parts.append("надгробий не сохранилось")
    elif stones:
        parts.append(f"сохранившихся надгробий — около {stones}")
    if date.precision == "year":
        span = str(date.year_from) if date.year_from == date.year_to \
            else f"{date.year_from}–{date.year_to}"
        parts.append(f"годы надгробий — {span}")
    elif date.raw and date.precision == PRECISION_OPEN:
        parts.append(date.raw)
    parts.append("очерк и снимки — на карточке ESJF")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


def records(cards: Iterable[tuple[str, dict, Optional[str]]], *,
            names: Optional[RussianNames] = None) -> list[ContextRecord]:
    """Записи слоя из пар (адрес, карточка, дата правки)."""
    return [card_to_record(url, card, lastmod=lastmod, names=names)
            for url, card, lastmod in cards]


# --- сеть и кэш ----------------------------------------------------------------

class ProtectionError(EsjfError):
    """Сайт раз за разом отвечает страницей защиты: обход останавливается."""


@dataclass
class Client:
    """Вежливый обход: пауза растёт при каждом 429, повтор при сбросе, кэш.

    Пять отказов подряд — не перегрузка, а защита сайта, которая не пускает
    сборщик: обход останавливается `ProtectionError`, а не ждёт часами. Страницу
    проверки сборщик не решает и подпись не меняет — это обход защиты.
    """

    cache_dir: Path
    pause: float = PAUSE
    timeout: int = 90
    retries: int = 8
    max_refusals_in_row: int = MAX_REFUSALS_IN_ROW
    _last: float = field(default=0.0, repr=False)
    _base: float = field(default=0.0, repr=False)
    _streak: int = field(default=0, repr=False)
    _refused_in_row: int = field(default=0, repr=False)
    requests: int = field(default=0, repr=False)
    refusals: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self._base = self.pause

    def refused(self, url: str, exc: urllib.error.HTTPError) -> float:
        """Учёт отказа 429: сколько ждать — или остановка обхода."""
        self.refusals += 1
        self._refused_in_row += 1
        self._streak = 0
        if self._refused_in_row >= self.max_refusals_in_row:
            raise ProtectionError(
                f"{url}: {self._refused_in_row} отказов 429 подряд — сайт отвечает страницей "
                "защиты; обход остановлен, нужна договорённость с ESJF") from exc
        self.pause = min(PAUSE_MAX, self.pause + PAUSE_STEP)
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        return float(retry_after) if (retry_after or "").isdigit() else COOLDOWN

    def get(self, url: str) -> str:
        for attempt in range(self.retries + 1):
            self._last = wait_for_pause(self._last, self.pause)
            self.requests += 1
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    text = response.read().decode("utf-8", errors="replace")
                if PROTECTION_MARK in text[:2000]:
                    raise EsjfError(f"{url}: вместо карточки пришла страница защиты сайта")
                self._refused_in_row = 0
                self._streak += 1
                if self._streak >= STREAK and self.pause > self._base:
                    self.pause = max(self._base, self.pause - PAUSE_STEP)
                    self._streak = 0
                return text
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < self.retries:
                    time.sleep(min(self.refused(url, exc), 300.0))
                    continue
                if exc.code in (500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(10.0 * (attempt + 1))
                    continue
                raise EsjfError(f"{url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(10.0 * (attempt + 1))
                    continue
                reason = getattr(exc, "reason", exc)
                raise EsjfError(f"{url}: сеть недоступна ({reason})") from exc
        raise EsjfError(f"{url}: не ответил за {self.retries + 1} попыток")

    def robots(self) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser(ROBOTS_URL)
        parser.parse(self.get(ROBOTS_URL).splitlines())
        delay = parser.crawl_delay("*")
        if delay:
            self.pause = max(self.pause, float(delay))
        return parser

    def cached(self, name: str, url: str, *, refresh: bool = False) -> str:
        path = self.cache_dir / name
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")
        text = self.get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return text
