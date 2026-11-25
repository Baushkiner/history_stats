"""Места Восточной Пруссии в нашей рамке по указателю Kartenmeister.

Зачем этот слой. Калининградская область и Клайпедский край до 1945 года —
прусские крейсы, и метрика, ЗАГС, перепись называют место по-немецки:
«Killigkehmen», «Gumbinnen», «Ackmonienen, Kirchspiel Enzuhnen». Нынешнее
имя — Гусев, Klaipėda — с немецким не сходится ни буквой, а Викиданные и
GeoNames старое немецкое написание знают далеко не у каждого хутора. Слой
отвечает: что это за место по-нынешнему, где оно, в каком приходе
(лютеранском и католическом) и при каком ЗАГСе стояло на 1905 год и сколько в
нём жило людей в 1782–1939 годах.

Набор. Kartenmeister (`kartenmeister.com`, Uwe-Karsten Krickhahn) — указатель
мест восточных провинций Пруссии в границах весны 1918 года, по замеру
24.10.2026 — 110 406 мест. Выгрузки нет: форма `Results.asp` отдаёт список
мест по нынешней области (по 100 на страницу), а карточка `City.asp?CitNum=N`
— поля места. Собираются места, которые сейчас в нашей рамке: «Today's
Province» — Kaliningrad Oblast (16 303) и Klaipeda (около 1 630). Сайт по
https обрывает соединение, по http отвечает; `robots.txt` нет (404).

Права. Собрано с согласия владельца, полученного владельцем проекта
(сообщено 24.11.2026); прав сайт не заявляет. Берутся факты карточки —
названия, крейс, провинция, координата, приходы, ЗАГС, население по годам,
число жителей иудейской веры — и короткая справка «Remarks» (1785 и 1818
годы по топографиям Гольдбека и Ведделя) без контактов кураторов крейса.
Карты, которые сайт продаёт, не берутся вовсе.

Где запись на карте. Координата карточки дана до минуты («East 22°12' North
54°35'»), это около километра; точка — само место, `confidence = ok`. Время —
годы, которые карточка подтверждает: годы переписей населения, 1905 год
приходов и годы справки («Shows in 1785 …»), `date_precision = year`. У
карточки без единого года — рамка указателя 1871–1945 годов с точностью
`era` и `date_approx`, `extra.date_source = "рамка указателя"`. Приход «D» —
заглушка карточки без прихода, именем прихода не считается.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from ..schema import LayerSpec, clean_text

BASE = "http://www.kartenmeister.com/preview/"
SEARCH_URL = BASE + "Results.asp"
CARD_URL = BASE + "City.asp?CitNum={}"
ENCODING = "latin-1"
PAUSE = 1.0
PAGE_SIZE = 100
# Нынешние области в нашей рамке: так их пишет поле «Today's Province»;
# поиск по форме идёт по началу слова.
TODAY_PROVINCES = ("Kaliningrad", "Klaip")
EXPECTED = {"Kaliningrad": 16303, "Klaip": 1631}
PARISH_YEAR = 1905
# Карточка без единого года (ни переписи, ни прихода, ни справки) получает
# рамку указателя: от образования Германской империи до 1945 года, когда
# немецкие имена сменились русскими и литовскими. Точность `era`.
GERMAN_ERA = (1871, 1945)

LICENSE = (
    "© Kartenmeister (Uwe-Karsten Krickhahn), условия использования не заявлены; "
    "собрано с согласия владельца, полученного владельцем проекта (сообщено "
    "24.11.2026): берутся факты карточки и ссылка на неё"
)

KARTENMEISTER = LayerSpec(
    slug="kartenmeister",
    title="Места Восточной Пруссии: немецкие и нынешние названия, приходы 1905 года",
    group="admin",
    source="Kartenmeister (kartenmeister.com), указатель мест восточных провинций Пруссии",
    license=LICENSE,
    description=(
        "Хутора, деревни и города Калининградской области и Клайпедского края "
        "под прежним немецким именем и нынешним названием: крейс, лютеранский и "
        "католический приход и ЗАГС на 1905 год, население 1782–1939 годов. "
        "Отвечает, что за место названо в прусской метрике."
    ),
    url="http://www.kartenmeister.com/preview/databaseuwe.asp",
    status="harvested",
    expected_rows=17934,
)


class KartenmeisterError(RuntimeError):
    """Страница не скачалась или пришла не в том виде."""


# --- список мест --------------------------------------------------------------

def search_form(today_province: str) -> dict:
    return {"germanname": "", "polishname": "", "Kreis": "", "provincege": "",
            "provincepo": today_province, "nexttogerm": "", "nexttopoli": "",
            "SScreen": "1", "FamilyName": "", "optPageSize": str(PAGE_SIZE), "go": "Submit"}


def page_url(today_province: str, page: int) -> str:
    return f"{BASE}results.asp?pg={page}&p={PAGE_SIZE}&s5={today_province}"


_RE_TOTAL = re.compile(r"There are\s*<u>\s*(\d+)\s*</u>", re.I)
_RE_ROW = re.compile(
    r'href="City\.asp\?CitNum=(\d+)">\s*(.*?)\s*</a>.*?<font[^>]*>(.*?)</font>', re.S | re.I)


@dataclass(frozen=True)
class Entry:
    cit_num: int
    name: str
    kreis: Optional[str]


def parse_results(page: str) -> tuple[Optional[int], list[Entry]]:
    """Страница списка: (сколько всего мест, места этой страницы)."""
    m = _RE_TOTAL.search(page)
    total = int(m.group(1)) if m else None
    rows = [Entry(int(n), _text(name) or "", _text(kreis)) for n, name, kreis in _RE_ROW.findall(page)]
    return total, rows


# --- карточка -----------------------------------------------------------------

_RE_PAIR = re.compile(
    r'<td[^>]*bgcolor="#CCCCCC"[^>]*>(.*?)</td>\s*<td[^>]*bgcolor="#66CCFF"[^>]*>(.*?)</td>',
    re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_EMAIL = re.compile(r"\S+@\S+")


def _text(fragment: Optional[str]) -> Optional[str]:
    if fragment is None:
        return None
    return clean_text(html.unescape(_RE_TAG.sub(" ", fragment.replace("<br>", "\n"))))


def parse_card(page: str) -> dict[str, str]:
    """Поля карточки: подпись (без переносов) → значение текстом."""
    fields: dict[str, str] = {}
    for label, value in _RE_PAIR.findall(page):
        key = _text(label)
        if not key:
            continue
        if key.startswith("Population"):
            raw = _RE_TAG.sub("\n", value.replace("<br>", "\n"))
            text = "; ".join(x.strip() for x in html.unescape(raw).split("\n") if x.strip())
        else:
            text = _text(value)
        if text and key not in fields:
            fields[key] = text
    return fields


REQUIRED = ("German Name", "Kreis/County", "Location")


def check_card(card: dict, cit_num: int) -> None:
    missing = [k for k in REQUIRED if k not in card]
    if "German Name" in missing:
        raise KartenmeisterError(f"CitNum={cit_num}: в карточке нет полей {missing} — "
                                 "разметку поменяли или пришла не карточка")


_RE_DM = re.compile(r"East\s*(\d+)\D+(\d+)'?\s*North\s*(\d+)\D+(\d+)", re.I)


def location(text: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """«East 22°12' North 54°35'» → (54.5833, 22.2). Нулевая точка — нет точки."""
    m = _RE_DM.search(text or "")
    if not m:
        return None, None
    lon = int(m.group(1)) + int(m.group(2)) / 60
    lat = int(m.group(3)) + int(m.group(4)) / 60
    if lat == 0 or lon == 0:
        return None, None
    return round(lat, 4), round(lon, 4)


_RE_POP = re.compile(r"(1[6-9]\d\d)\s*:\s*([\d.,]+)")


def population(text: Optional[str]) -> dict[int, int]:
    out: dict[int, int] = {}
    for year, value in _RE_POP.findall(text or ""):
        digits = re.sub(r"\D", "", value)
        if digits:
            out[int(year)] = int(digits)
    return out


def parish(text: Optional[str]) -> Optional[str]:
    """«Gumbinnen 1905» → «Gumbinnen»: год у всех приходов один.

    Одна буква без года («D») — заглушка карточки, у которой прихода нет:
    это не имя прихода.
    """
    value = clean_text(re.sub(r"\b%d\b" % PARISH_YEAR, "", text or ""))
    if value and len(value) <= 2:
        return None
    return value


_RE_REMARK_YEAR = re.compile(r"\b[Ii]n (17\d\d|18[0-4]\d)\b")


def remark_years(text: Optional[str]) -> set[int]:
    """Годы, на которые справка описывает место: «Shows in 1785 …», «In 1818 …»."""
    return {int(y) for y in _RE_REMARK_YEAR.findall(text or "")}


def remarks(text: Optional[str]) -> Optional[str]:
    """Справка без контактов: «Kreisbetreuer: …» и адреса почты отрезаются."""
    if not text:
        return None
    text = re.split(r"Kreisbetreuer|Ortsbetreuer|Kirchspielvertreter", text)[0]
    return clean_text(_RE_EMAIL.sub("", text))


def card_to_record(cit_num: int, card: dict, *, names=None):
    german = card.get("German Name")
    local = card.get("Polish/Russian Name")
    if local and local.lower().startswith("more research"):
        local = None
    lat, lon = location(card.get("Location"))
    pops = population(card.get("Population By Year/Einwohner"))
    lutheran = parish(card.get("Lutheran Parish"))
    catholic = parish(card.get("Catholic Parish"))
    registry = parish(card.get("Standesamt/Civil Registry"))
    kreis = card.get("Kreis/County")
    province = card.get("German Province")
    today = card.get("Today's Province")

    russian = None
    if names is not None and local and lat is not None:
        russian = names.lookup(local, lat, lon)
    title = german or f"CitNum {cit_num}"
    if russian or local:
        title = f"{title} — {russian or local}"

    note = remarks(card.get("Remarks"))
    years = sorted(set(pops) | remark_years(note))
    if lutheran or catholic or registry:
        years = sorted(set(years) | {PARISH_YEAR})
    framed = not years
    if framed:
        years = list(GERMAN_ERA)
    parts = []
    if remark_years(note):
        parts.append("справка на " + ", ".join(map(str, sorted(remark_years(note)))) + " год")
    if pops:
        parts.append(f"население по годам {min(pops)}–{max(pops)}")
    if lutheran or catholic or registry:
        parts.append(f"приходы и ЗАГС на {PARISH_YEAR} год")
    period_raw = "; ".join(parts) or (
        f"годов карточка не даёт — рамка указателя: немецкое имя места "
        f"{GERMAN_ERA[0]}–{GERMAN_ERA[1]}")

    summary_parts = []
    where = ", ".join(x for x in (f"крейс {kreis}" if kreis else None, province) if x)
    if where:
        summary_parts.append(where[0].upper() + where[1:])
    if local:
        summary_parts.append(f"ныне {local}" + (f" ({today})" if today else ""))
    church = []
    if lutheran:
        church.append(f"лютеранский приход {lutheran}")
    if catholic:
        church.append(f"католический — {catholic}")
    if registry:
        church.append(f"ЗАГС (Standesamt) — {registry}")
    if church:
        summary_parts.append(", ".join(church) + f" (на {PARISH_YEAR} год)")
    if pops:
        summary_parts.append("население: " + ", ".join(f"{y} — {n}" for y, n in sorted(pops.items())))

    extra = {k: v for k, v in {
        "name_de": german,
        "name_alt_de": [card[k] for k in sorted(card) if k.startswith("Alternate Name")] or None,
        "name_local": local,
        "kreis": kreis,
        "province_de": province,
        "province_today": today,
        "parish_lutheran_1905": lutheran,
        "parish_catholic_1905": catholic,
        "standesamt_1905": registry,
        "population": {str(y): n for y, n in sorted(pops.items())} or None,
        "jewish_residents": card.get("Residents of Jewish Faith"),
        "gemeindelexikon": card.get("Gemeindelexikon/Town Index"),
        "map_number": card.get("Map Number"),
        "church": card.get("Church"),
        "location_note": card.get("Location Description"),
        "remarks": note,
        "date_source": "рамка указателя" if framed else None,
    }.items() if v}

    return KARTENMEISTER.new_record(
        title=title,
        category=f"место прусской провинции {province}" if province else "место Пруссии",
        lat=lat, lon=lon,
        place_text="; ".join(x for x in (f"Kreis {kreis}" if kreis else None, province,
                                          f"ныне {today}" if today else None) if x) or None,
        district=kreis,
        year_from=years[0], year_to=years[-1],
        date_precision="era" if framed else "year",
        date_approx=framed,
        period_raw=period_raw,
        summary="; ".join(summary_parts) or None,
        url=CARD_URL.format(cit_num),
        source_id=str(cit_num),
        confidence="ok" if lat is not None else "no_coords",
        extra=extra,
    )


def records(cards: Iterable[tuple[int, dict]], *, names=None) -> list:
    return [card_to_record(n, card, names=names) for n, card in cards]
