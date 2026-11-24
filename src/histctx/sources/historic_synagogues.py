"""Синагоги Европы по инвентаризации Historic Synagogues of Europe.

Зачем этот слой. В метрике раввината и в ревизской сказке еврейской общины
место названо — «местечко Ошмяны», — а где стояла синагога, когда её
построили, из чего и что с ней теперь, не сказано нигде, кроме этой
инвентаризации. Викиданные знают сотню-другую синагог черты оседлости, эта
база — три с лишним тысячи по всей Европе, преимущественно довоенных: год
постройки, материал, нынешнее состояние и назначение здания.

Набор. Historic Synagogues of Europe (`historicsynagogueseurope.org`,
Foundation for Jewish Heritage и Center for Jewish Art Еврейского
университета в Иерусалиме) — 3 427 зданий 48 стран на 24.11.2026. Выгрузки
нет, но страница карты `synagogue-map` несёт все точки разом строкой
`predata`: широта, долгота, номер, название, материал, нынешнее назначение,
состояние, значимость. Год постройки, архитектор, стиль, община и место по
справочнику — в карточке здания `browser.php?mode=set&id=N`, по запросу на
здание. `robots.txt` закрывает сайт только для PetalBot.

Сертификат. Сервер отдаёт один сертификат сайта без промежуточного (Sectigo
Public Server Authentication CA DV R36), и проверка TLS без него не
сходится. Промежуточный сертификат скачивается по адресу из его же поля
AIA (`crt.sectigo.com`) и добавляется к доверенным в контексте TLS;
проверка не отключается.

Права. © Foundation for Jewish Heritage и Center for Jewish Art; собрано с
согласия владельца, полученного владельцем проекта (сообщено 24.11.2026).
Берутся факты — место, год постройки, материал, назначение, состояние,
значимость, архитектор, стиль, община — и ссылка на карточку; снимки,
описания и библиография остаются на сайте.

Где запись на карте. Точка — здание, `confidence = ok`. Время — от года
постройки до горизонта проекта (1960 год) с точностью `open`: здание стоит
и сейчас или стояло до разрушения, о котором база не всегда знает; после
1960 года постройки — год постройки как есть. Без года постройки — граница
по полю «Period» карточки («Russian Empire», «Interwar Period»), если оно
есть, с точностью `era`; иначе запись остаётся без времени (`unknown`).
"""

from __future__ import annotations

import html
import re
import ssl
from dataclasses import dataclass
from typing import Iterable, Optional

from ..schema import LayerSpec, clean_text

BASE = "https://historicsynagogueseurope.org/"
MAP_URL = BASE + "synagogue-map"
CARD_URL = BASE + "browser.php?mode=set&id={}"
# Промежуточный сертификат, которого сервер не отдаёт: адрес из поля AIA
# сертификата сайта («CA Issuers»).
INTERMEDIATE_URL = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"
PAUSE = 1.0
EXPECTED = 3427
HORIZON = 1960

LICENSE = (
    "© Foundation for Jewish Heritage и Center for Jewish Art (HUJI), условия "
    "использования не заявлены; собрано с согласия владельца, полученного "
    "владельцем проекта (сообщено 24.11.2026): берутся факты и ссылка на карточку, "
    "снимки и описания остаются на сайте"
)

HISTORIC_SYNAGOGUES = LayerSpec(
    slug="historic_synagogues",
    title="Исторические синагоги Европы",
    group="faith",
    source="Historic Synagogues of Europe (historicsynagogueseurope.org), Foundation for "
           "Jewish Heritage и Center for Jewish Art",
    license=LICENSE,
    description=(
        "Здания синагог и молелен от Атлантики до Кавказа, большей частью "
        "довоенные: год постройки, материал, архитектор, нынешнее назначение и "
        "состояние. Отвечает, где молилась община из метрики раввината и что "
        "стоит на этом месте теперь."
    ),
    url=MAP_URL,
    status="harvested",
    expected_rows=EXPECTED,
)


class SynagoguesError(RuntimeError):
    """Страница не скачалась или пришла не в том виде."""


def ssl_context(intermediate_der: bytes) -> ssl.SSLContext:
    """Обычная проверка TLS плюс недостающий промежуточный сертификат."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(intermediate_der))
    return ctx


# --- точки карты ----------------------------------------------------------------

@dataclass(frozen=True)
class MapPoint:
    id: int
    lat: Optional[float]
    lon: Optional[float]
    name: str
    location_id: Optional[str]
    at_risk: bool
    material: Optional[str]
    usage: Optional[str]
    condition: Optional[str]
    significance: Optional[str]


_RE_PREDATA = re.compile(r"var predata = '(.*?)';", re.S)


def _num(text: str) -> Optional[float]:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value else None


def parse_map(page: str) -> list[MapPoint]:
    """Строка `predata` страницы карты: записи через `||||`, поля через `;;`."""
    m = _RE_PREDATA.search(page)
    if not m:
        raise SynagoguesError("на странице карты нет строки predata — разметку поменяли")
    out = []
    for row in m.group(1).split("||||"):
        if not row.strip():
            continue
        f = row.split(";;")
        if len(f) < 13 or not f[3].strip().isdigit():
            raise SynagoguesError(f"строка карты не того вида: {row[:120]!r}")
        out.append(MapPoint(
            id=int(f[3]), lat=_num(f[0]), lon=_num(f[1]),
            name=clean_text(html.unescape(f[4])) or f"#{f[3]}",
            location_id=clean_text(f[5]),
            at_risk=f[8].strip() == "1",
            material=clean_text(f[9]), usage=clean_text(f[10]),
            condition=clean_text(f[11]), significance=clean_text(f[12]),
        ))
    return out


# --- карточка -------------------------------------------------------------------

_RE_FIELD = re.compile(
    r'browser-line-title"[^>]*>\s*(.*?)\s*</div>\s*<div[^>]*cell-mhs"[^>]*>(.*?)</div>', re.S)
_RE_TAG = re.compile(r"<[^>]+>")

# Поля карточки, которые берутся: остальное — либо пусто у синагог (поля
# общей схемы Index of Jewish Art для рукописей и монет), либо чужое
# изложение (описание, библиография).
FIELDS = ("Name/Title", "Object", "Building Date", "Synagogue active dates",
          "Reconstruction Dates", "Architect/ Maker", "Community", "Location", "Style",
          "Period", "Present Usage", "Present Usage Details",
          "Condition of Building Fabric", "Significance Rating")


def _cell(fragment: str) -> Optional[str]:
    text = html.unescape(_RE_TAG.sub(" ", fragment))
    text = re.sub(r"(\s*\|\s*)+$", "", text.strip())
    text = clean_text(re.sub(r"\s*\|\s*", " | ", text))
    # «Great Synagogue in Oshmiany | Unknown»: пустая вторая часть подписи.
    text = clean_text(re.sub(r"(?:\s*\|\s*Unknown)+$", "", text or "", flags=re.I))
    if text and text.lower() in ("unknown", "unknown (unknown)"):
        return None
    return text


def parse_card(page: str) -> dict[str, str]:
    """Поля карточки здания; первое непустое значение подписи выигрывает.

    Часть полей («Period», «Condition of Building Fabric») сайт прячет в
    HTML-комментарий, но данные там те же — они берутся тоже.
    """
    out: dict[str, str] = {}
    for label, value in _RE_FIELD.findall(page):
        key = clean_text(_RE_TAG.sub(" ", label))
        if key not in FIELDS or key in out:
            continue
        text = _cell(value)
        if key == "Period" and text:
            # «Russian Empire Russian Empire»: ссылка повторена дважды.
            half = len(text) // 2
            if len(text) % 2 == 1 and text[:half] == text[half + 1:]:
                text = text[:half]
        if text:
            out[key] = text
    return out


def check_card(card: dict, sid: int) -> None:
    if "Name/Title" not in card and "Location" not in card:
        raise SynagoguesError(f"id={sid}: в карточке нет ни названия, ни места — "
                              "разметку поменяли или пришла не карточка")


# --- датировка ------------------------------------------------------------------

@dataclass(frozen=True)
class Dating:
    year_from: Optional[int]
    year_to: Optional[int]
    precision: str
    approx: bool
    raw: Optional[str]
    source: Optional[str] = None


_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3,
        "4th": 4, "last": 4}
_RE_YEAR = re.compile(r"(?<!\d)(1[0-9]\d\d|20[0-2]\d)(?!\d)")
_RE_DECADE = re.compile(r"(?<!\d)(1[0-9]\d0|20[0-2]0)'?s\b")
_RE_CENTURY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)\s*(?:-\s*\d{1,2}(?:st|nd|rd|th)\s*)?c", re.I)
_APPROX = re.compile(r"\b(?:ca\.?|c\.|circa|about|around|before|after|probably|"
                     r"possibly|late|early|mid|approx\.?)\b|\?", re.I)


def building_dating(raw: Optional[str]) -> Optional[tuple[int, int, str, bool]]:
    """«1902», «1765-1767», «1890s», «ca. 1850», «late 19th c.» → (от, до, точность, ≈)."""
    text = clean_text(raw)
    if not text:
        return None
    approx = bool(_APPROX.search(text))
    decades = [int(d) for d in _RE_DECADE.findall(text)]
    years = [int(y) for y in _RE_YEAR.findall(text) if int(y) not in decades]
    if years:
        lo, hi = min(years), max(years)
        if decades:
            lo, hi = min(lo, min(decades)), max(hi, max(decades) + 9)
            return lo, hi, "decade", approx
        return lo, hi, "year", approx
    if decades:
        return min(decades), max(decades) + 9, "decade", approx
    m = re.search(r"(?<!\d)(1[0-9])\?\?", text)
    if m:
        # «18??»: век известен, год — нет.
        c = int(m.group(1))
        return c * 100, c * 100 + 99, "century", True
    m = re.search(r"(?<!\d)(1[0-9]\d)\?", text)
    if m:
        # «185?»: десятилетие.
        d = int(m.group(1)) * 10
        return d, d + 9, "decade", True
    centuries = [int(c) for c in re.findall(r"(\d{1,2})(?:st|nd|rd|th)", text)]
    if centuries and _RE_CENTURY.search(text):
        lo, hi = (min(centuries) - 1) * 100 + 1, max(centuries) * 100
        low = text.lower()
        part = None
        if "first half" in low or "1st half" in low:
            part = (lo, lo + 49)
        elif "second half" in low or "2nd half" in low:
            part = (lo + 50, hi)
        elif "early" in low or "beginning" in low:
            part = (lo, lo + 32)
        elif "mid" in low or "middle" in low:
            part = (lo + 33, lo + 66)
        elif "late" in low or "end of" in low:
            part = (lo + 66, hi)
        if part and len(centuries) == 1:
            return part[0], part[1], "part", True
        return lo, hi, "century", approx
    return None


# Граница эпохи по полю «Period» карточки — только для зданий без года
# постройки. Ключ — начало подписи, как её пишет справочник сайта.
PERIODS = {
    "russian empire": (1772, 1917),
    "interwar period": (1918, 1939),
    "austro-hungarian empire": (1867, 1918),
    "austrian empire": (1804, 1867),
    "habsburg": (1526, 1918),
    "kingdom of prussia": (1701, 1871),
    "german empire": (1871, 1918),
    "polish-lithuanian commonwealth": (1569, 1795),
    "ottoman empire": (1453, 1918),
    "soviet": (1922, 1991),
    "post-war": (1945, 1960),
    "postwar": (1945, 1960),
}


def period_bounds(period: Optional[str]) -> Optional[tuple[int, int]]:
    low = (period or "").lower()
    for key, bounds in PERIODS.items():
        if low.startswith(key):
            return bounds
    return None


def dating(card: dict) -> Dating:
    raw = card.get("Building Date")
    parsed = building_dating(raw)
    if parsed:
        lo, hi, precision, approx = parsed
        # «1860s, 1924, 1995 (in Gießen)», «1791, 1859 (expanded)»: первый год —
        # постройка, остальные — перестройки и переезды; срок идёт от первого.
        if lo < HORIZON:
            return Dating(lo, HORIZON, "open", approx, f"построена: {raw}")
        return Dating(lo, hi, precision, approx, f"построена: {raw}")
    bounds = period_bounds(card.get("Period"))
    if bounds:
        return Dating(bounds[0], bounds[1], "era", True,
                      f"года постройки нет; период по карточке: {card['Period']}",
                      "период карточки")
    return Dating(None, None, "unknown", False, raw and f"построена: {raw}")


# --- запись ---------------------------------------------------------------------

USAGE_RU = {
    "Synagogue": "синагога", "Church": "церковь", "Club": "клуб", "Abandoned": "заброшено",
    "Museum": "музей", "Dwelling": "жильё", "Factory": "завод", "Office building": "контора",
    "Theater": "театр", "Storage": "склад", "Educational Institution": "учебное заведение",
    "Restaurant": "ресторан", "Shop": "магазин", "Fire Depot": "пожарная часть",
    "House of Culture": "дом культуры", "Sport facility": "спортзал",
    "Library": "библиотека", "Cinema": "кинотеатр", "Funeral parlor": "похоронное бюро",
    "Garage": "гараж", "Bathhouse": "баня", "Art center": "художественный центр",
    "Hospital": "больница", "Bank": "банк", "Police station": "полиция",
    "Cultural center": "культурный центр", "Archives": "архив", "Bakery": "пекарня",
    "Under reconstruction": "на реконструкции", "Mosque": "мечеть", "Workshop": "мастерская",
    "Workhouse": "работный дом", "Freemasonic lodge": "масонская ложа",
    "Memorial": "мемориал", "Sikh Gurdwara": "гурдвара сикхов",
}
MATERIAL_RU = {"Stone": "камень", "Brick": "кирпич", "Timber": "дерево",
               "Half-timber": "фахверк", "Concrete": "бетон"}
CONDITION_RU = {"A": "хорошее", "B": "удовлетворительное", "C": "плохое",
                "D": "очень плохое", "E": "невосстановимое"}
SIGNIFICANCE_RU = {"1": "местная", "2": "региональная", "3": "национальная",
                   "4": "международная"}


def _usage_ru(value: Optional[str]) -> Optional[str]:
    if not value or value == "No information":
        return None
    return USAGE_RU.get(value, value)


def _graded(value: Optional[str], table: dict) -> Optional[str]:
    m = re.match(r"\s*([A-E1-4])\b", value or "")
    if not m or m.group(1) not in table:
        return None
    return f"{m.group(1)} — {table[m.group(1)]}"


def record(point: MapPoint, card: Optional[dict]):
    card = card or {}
    d = dating(card) if card else Dating(None, None, "unknown", False, None)
    usage = _usage_ru(point.usage or card.get("Present Usage"))
    material = MATERIAL_RU.get(point.material or "", point.material)
    condition = _graded(point.condition or card.get("Condition of Building Fabric"),
                        CONDITION_RU)
    significance = _graded(point.significance or card.get("Significance Rating"),
                           SIGNIFICANCE_RU)
    architect = card.get("Architect/ Maker")
    if architect:
        architect = clean_text(re.sub(r"\(\s*Unknown\s*\)|\bUnknown\b", "", architect)) or None

    parts = []
    if card.get("Building Date"):
        parts.append(f"построена: {card['Building Date']}")
    if card.get("Reconstruction Dates"):
        parts.append(f"перестройки: {card['Reconstruction Dates']}")
    if architect:
        parts.append(f"архитектор: {architect}")
    if material:
        parts.append(f"материал: {material}")
    if usage:
        parts.append(f"ныне: {usage}")
    if condition:
        parts.append(f"состояние: {condition}")
    if significance:
        parts.append(f"значимость: {significance}")
    if point.at_risk:
        parts.append("под угрозой")

    extra = {k: v for k, v in {
        "hse_id": point.id,
        "building_date": card.get("Building Date"),
        "active_dates": card.get("Synagogue active dates"),
        "reconstruction": card.get("Reconstruction Dates"),
        "architect": architect,
        "community": card.get("Community"),
        "style": card.get("Style"),
        "period": card.get("Period"),
        "material": point.material,
        "usage": point.usage or card.get("Present Usage"),
        "usage_details": card.get("Present Usage Details"),
        "condition": point.condition,
        "significance": point.significance,
        "at_risk": point.at_risk or None,
        "date_source": d.source,
        "card": "нет в кэше" if not card else None,
    }.items() if v}

    return HISTORIC_SYNAGOGUES.new_record(
        title=card.get("Name/Title") or point.name,
        category=f"синагога; ныне {usage}" if usage else "синагога",
        lat=point.lat, lon=point.lon,
        place_text=card.get("Location") or point.name,
        year_from=d.year_from, year_to=d.year_to,
        date_precision=d.precision, date_approx=d.approx, period_raw=d.raw,
        actor=architect,
        summary="; ".join(parts) or None,
        url=CARD_URL.format(point.id),
        source_id=str(point.id),
        confidence="ok" if point.lat is not None and point.lon is not None else "no_coords",
        extra=extra,
    )


def records(items: Iterable[tuple[MapPoint, Optional[dict]]]) -> list:
    return [record(p, c) for p, c in items]
