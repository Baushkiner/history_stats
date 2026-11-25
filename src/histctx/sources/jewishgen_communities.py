"""Подчинение еврейских общин около 1900, 1930 и 1950 годов по JewishGen Communities.

Зачем этот слой. Местечко из метрики раввината меняло государство и
губернию по два-три раза: Янов под Пинском около 1900 года — Кобринский
уезд Гродненской губернии Российской империи, между войнами — Дрогичинский
повят Полесского воеводства Польши, после войны — Ивановский район БССР. В
каком архиве искать запись и как назывался уезд в документе, зависит от
года, и сводной таблицы «место → уезд и губерния по годам» по нашей
территории нет нигде, кроме этой базы. Слой отвечает: в каком уезде,
губернии и государстве стояла община в год документа и как её называли на
разных языках.

Набор. JewishGen Communities Database (`jewishgen.org/Communities/`) — общины
Европы, Северной Африки и Ближнего Востока: нынешнее название и страна,
координата до минуты, названия на разных языках, подчинение «c. 1900 Before
WWI», «c. 1930 Between Wars», «c. 1950 After WWII». Карточка общины
(`community.php`) с ноября 2026 года открывается только после входа по
учётной записи JewishGen (302 на `/Auth0/login.php`); строки выдачи поиска
`jgcd.php` — открыты и несут все поля, которые берёт слой. Выгрузки нет:
выдача приходит по запросу «все общины губернии c. 1900» или «воеводства
c. 1930» (`jgcd.php?get=y&prov1900=Minsk`), и обход идёт волной: от затравки
(поиск по названиям столиц) к губерниям, которые встретились в выдаче, и от
них — к следующим. `robots.txt` — `Crawl-delay: 2`, пауза сборщика — две
секунды.

Права. © JewishGen; собрано с согласия владельца, полученного владельцем
проекта (сообщено 24.11.2026). Берутся факты строки выдачи — названия,
координата, подчинение, число записей JGFF — и ссылка на карточку общины.

Что попадает в слой. По записи на общину и эпоху — до трёх записей на
общину: «около 1900 года» (1880–1914), «между войнами» (1919–1939), «после
войны» (1945–1960), точность `era` и `date_approx`: база называет подчинение
на эпоху, а не на год. В записи — уезд (`district`) и губерния, воеводство,
комитат эпохи (`place_text`), государство эпохи (`category`), нынешнее
название и страна, названия на разных языках (`extra.names`). `region` —
губерния 1897 года по полигонам, как у всех слоёв. Точка — координата
общины (до минуты, около километра), `confidence = ok`.
"""

from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Optional

from ..schema import LayerSpec, clean_text

BASE = "https://www.jewishgen.org/Communities/"
SEARCH_URL = BASE + "jgcd.php"
CARD_URL = BASE + "community.php?usbgn={}"
PAUSE = 2.0   # robots.txt: Crawl-delay: 2

LICENSE = (
    "© JewishGen, условия использования не заявлены; собрано с согласия владельца, "
    "полученного владельцем проекта (сообщено 24.11.2026): берутся факты строки "
    "выдачи поиска и ссылка на карточку общины"
)

JEWISHGEN_COMMUNITIES = LayerSpec(
    slug="jewishgen_communities",
    title="Еврейские общины: уезд и губерния около 1900, 1930 и 1950 годов",
    group="admin",
    source="JewishGen Communities Database (jewishgen.org/Communities)",
    license=LICENSE,
    description=(
        "Местечки и города с еврейской общиной — от Литвы до Марокко — с "
        "подчинением по эпохам: уезд и губерния около 1900 года, повят и "
        "воеводство между войнами, страна после войны, названия на идише, "
        "польском, русском. Отвечает, какой уезд писать в запросе в архив."
    ),
    url=BASE,
    status="harvested",
    expected_rows=17296,
)

# Эпохи выдачи: колонка, подпись, границы лет.
ERAS = (
    ("1900", "около 1900 года, до Первой мировой", (1880, 1914)),
    ("1930", "между войнами, около 1930 года", (1919, 1939)),
    ("1950", "после Второй мировой, около 1950 года", (1945, 1960)),
)

# Затравка обхода: по городу на страну выбора формы поиска; дальше обход
# идёт по губерниям, встреченным в выдаче.
SEEDS = (
    ("Pinsk", "Belarus"), ("Minsk", "Belarus"), ("Vilnius", "Lithuania"), ("Riga", "Latvia"),
    ("Tallinn", "Estonia"), ("Kiev", "Ukraine"), ("Odessa", "Ukraine"), ("Lviv", "Ukraine"),
    ("Chisinau", "Moldova"), ("Warszawa", "Poland"), ("Krakow", "Poland"),
    ("Moskva", "Russia"), ("Smolensk", "Russia"), ("Bucuresti", "Romania"),
    ("Iasi", "Romania"), ("Budapest", "Hungary"), ("Wien", "Austria"), ("Praha", "Czech Republic"),
    ("Bratislava", "Slovakia"), ("Berlin", "Germany"), ("Frankfurt", "Germany"),
    ("Paris", "France"), ("Strasbourg", "France"), ("Amsterdam", "Netherlands"),
    ("Antwerpen", "Belgium"), ("Kobenhavn", "Denmark"), ("Zurich", "Switzerland"),
    ("Roma", "Italy"), ("Venezia", "Italy"), ("Ljubljana", "Slovenia"), ("Zagreb", "Croatia"),
    ("Sarajevo", "Bosnia-Herzegovina"), ("Beograd", "Serbia"), ("Skopje", "Macedonia"),
    ("Pristina", "Kosovo"), ("Sofia", "Bulgaria"), ("Thessaloniki", "Greece"),
    ("Istanbul", "Turkey"), ("Izmir", "Turkey"), ("Tbilisi", "Georgia"), ("Yerevan", "Armenia"),
    ("Baku", "Azerbaijan"), ("Tashkent", "Uzbekistan"), ("Bukhara", "Uzbekistan"),
    ("Samarkand", "Uzbekistan"), ("Dushanbe", "Tajikistan"), ("Ashgabat", "Turkmenistan"),
    ("Almaty", "Kazakhstan"), ("Tehran", "Iran"), ("Baghdad", "Iraq"), ("Damascus", "Syria"),
    ("Beirut", "Lebanon"), ("Cairo", "Egypt"), ("Tripoli", "Libya"), ("Tunis", "Tunisia"),
    ("Alger", "Algeria"), ("Oran", "Algeria"), ("Casablanca", "Morocco"), ("Fes", "Morocco"),
)


class JewishGenError(RuntimeError):
    """Страница не скачалась или пришла не в том виде."""


def seed_form(town: str, country: str) -> dict:
    return {"Town": town, "Country": country, "interwar": "ZZ", "prewwi": "ZZ",
            "Miles": "MILES", "cl": "capital", "ttype": "Q"}


def query_url(params: dict) -> str:
    return SEARCH_URL + "?" + urllib.parse.urlencode({"get": "y", **params})


def query_key(params: dict) -> str:
    """Имя файла кэша для запроса: читаемое начало и хеш."""
    text = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text)[:60].strip("_")
    return f"{slug}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]}"


# --- выдача ---------------------------------------------------------------------

_RE_ROW = re.compile(r'<tr class="sr-row[^"]*"[^>]*>(.*?)</tr>', re.S)
_RE_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_RE_BR = re.compile(r"<br\s*/?>", re.I)
_RE_TAG = re.compile(r"<[^>]+>")
# Номер общины — код USBGN (`-1947920`) или свой номер JewishGen (`A0009`).
_RE_USBGN = re.compile(r'usbgn="(-?[A-Za-z0-9]+)"')
_RE_LINK = re.compile(r"jgcd\.php\?get=y&(?:amp;)?([^'\"]+)['\"]")
_RE_COORD = re.compile(r"(\d+)\s*°\s*(\d+)'\s*([NS])\s+(\d+)\s*°\s*(\d+)'\s*([EW])")


def _text(fragment: Optional[str]) -> Optional[str]:
    if fragment is None:
        return None
    return clean_text(html.unescape(_RE_TAG.sub(" ", fragment)).replace("\xa0", " "))


@dataclass
class Community:
    usbgn: str
    name: str
    country: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    names: list
    eras: dict          # "1900" → {"town", "district", "province", "country"}
    jgff: Optional[int]


def coords(text: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """«52°07' N 26°04' E» → (52.1167, 26.0667)."""
    m = _RE_COORD.search(html.unescape(text or "").replace("&deg;", "°"))
    if not m:
        return None, None
    lat = int(m.group(1)) + int(m.group(2)) / 60
    lon = int(m.group(4)) + int(m.group(5)) / 60
    if m.group(3) == "S":
        lat = -lat
    if m.group(6) == "W":
        lon = -lon
    return round(lat, 4), round(lon, 4)


def _era_cell(fragment: str, with_units: bool) -> dict:
    parts = [_text(p) for p in _RE_BR.split(fragment)]
    if with_units and len(parts) == 4:
        keys = ("town", "district", "province", "country")
    elif len(parts) == 2:
        keys = ("town", "country")
    elif with_units and len(parts) == 3:
        keys = ("town", "province", "country")
    else:
        keys = ("town",) + tuple(f"part{i}" for i in range(1, len(parts)))
    return {k: v for k, v in zip(keys, parts) if v}


def parse_names(text: Optional[str]) -> list[str]:
    """«Pinsk [Rus, Bel, Yid], Pińsk [Pol]» → ["Pinsk [Rus, Bel, Yid]", "Pińsk [Pol]"]."""
    out, depth, cur = [], 0, ""
    for ch in text or "":
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_rows(page: str) -> list[Community]:
    out = []
    for row in _RE_ROW.findall(page):
        tds = _RE_TD.findall(row)
        m = _RE_USBGN.search(row)
        if len(tds) < 5 or not m:
            continue
        head = _RE_BR.split(tds[0], maxsplit=1)
        name_country = _text(head[0]) or ""
        name, _, country = name_country.rpartition(",")
        if not name:
            name, country = country, ""
        lat, lon = coords(tds[0])
        jgff = None
        if len(tds) > 5:
            digits = re.sub(r"\D", "", _text(tds[5]) or "")
            jgff = int(digits) if digits else None
        out.append(Community(
            usbgn=m.group(1), name=name.strip(), country=clean_text(country),
            lat=lat, lon=lon, names=parse_names(_text(tds[1])),
            eras={"1950": _era_cell(tds[2], False), "1930": _era_cell(tds[3], True),
                  "1900": _era_cell(tds[4], True)},
            jgff=jgff))
    return out


def page_links(page: str) -> list[dict]:
    """Запросы губерний и воеводств из ссылок выдачи; уезд — только без губернии."""
    out, seen = [], set()
    for query in _RE_LINK.findall(html.unescape(page)):
        params = dict(urllib.parse.parse_qsl(html.unescape(query), keep_blank_values=True))
        params.pop("get", None)
        for era in ("1900", "1930"):
            prov = params.get(f"prov{era}")
            dist = params.get(f"dist{era}")
            if prov:
                q = {f"prov{era}": prov}
            elif dist:
                q = {f"dist{era}": dist}
            else:
                continue
            key = tuple(sorted(q.items()))
            if key not in seen:
                seen.add(key)
                out.append(q)
    return out


def result_count(page: str) -> Optional[int]:
    m = re.search(r'class="sr-count"><strong>([\d,]+)', page)
    return int(m.group(1).replace(",", "")) if m else None


# --- записи ---------------------------------------------------------------------

STATES_RU = {
    "Russian Empire": "Российская империя", "Austrian Empire": "Австрийская империя",
    "Germany": "Германия", "Hungary": "Венгрия", "Romania": "Румыния", "Poland": "Польша",
    "Soviet Union": "СССР", "Lithuania": "Литва", "Latvia": "Латвия", "Estonia": "Эстония",
    "Czechoslovakia": "Чехословакия", "Ottoman Empire": "Османская империя",
}


# Как называть единицы эпохи: уезд и губерния у империи, повят и воеводство
# у Польши. Неизвестное государство — «округ» и «область».
UNITS_RU = {
    "Russian Empire": ("уезд", "губерния"), "Poland": ("повят", "воеводство"),
    "Austrian Empire": ("округ", "коронная земля"), "Hungary": ("округ", "комитат"),
    "Germany": ("крейс", "провинция"), "Romania": ("пласа", "жудец"),
    "Lithuania": ("уезд", "округ"), "Latvia": ("уезд", "край"), "Estonia": ("уезд", "край"),
    "Czechoslovakia": ("округ", "земля"), "Soviet Union": ("район", "республика или область"),
}


def describe(unit: dict) -> str:
    """«Pinsk: уезд Pinsk, губерния Minsk, Российская империя»."""
    state = unit.get("country")
    district_word, province_word = UNITS_RU.get(state or "", ("округ", "область"))
    bits = []
    if unit.get("district"):
        bits.append(f"{district_word} {unit['district']}")
    if unit.get("province"):
        bits.append(f"{province_word} {unit['province']}")
    if state:
        bits.append(STATES_RU.get(state, state))
    town = unit.get("town")
    if town and bits:
        return f"{town}: " + ", ".join(bits)
    return town or ", ".join(bits)


def records(communities: Iterable[Community], *, names=None) -> list:
    out = []
    for c in communities:
        russian = None
        if names is not None and c.lat is not None:
            for candidate in [c.name] + [n.split(" [")[0] for n in c.names]:
                russian = names.lookup(candidate, c.lat, c.lon)
                if russian:
                    break
        label = c.name + (f" ({russian})" if russian and russian != c.name else "")
        modern = ", ".join(x for x in (c.name, c.country) if x)
        for era, era_ru, (lo, hi) in ERAS:
            unit = c.eras.get(era) or {}
            if not unit:
                continue
            state = unit.get("country")
            chain = [x for x in (unit.get("district"), unit.get("province"), state) if x]
            town = unit.get("town")
            place = ", ".join(([town] if town else []) + chain)
            described = describe(unit)
            summary = f"{era_ru} — {described}" if described else era_ru
            summary += f"; ныне {modern}"
            extra = {k: v for k, v in {
                "usbgn": c.usbgn, "era": era, "town_era": town,
                "district_era": unit.get("district"), "province_era": unit.get("province"),
                "state_era": state, "modern_name": c.name, "modern_country": c.country,
                "names": c.names or None, "jgff_entries": c.jgff,
            }.items() if v}
            out.append(JEWISHGEN_COMMUNITIES.new_record(
                title=f"{label}: {era_ru}",
                category=STATES_RU.get(state or "", state) or "государство не указано",
                lat=c.lat, lon=c.lon,
                place_text=place or modern,
                district=unit.get("district"),
                year_from=lo, year_to=hi, date_precision="era", date_approx=True,
                period_raw=f"c. {era} ({era_ru})",
                summary=summary,
                url=CARD_URL.format(c.usbgn),
                source_id=f"{c.usbgn}:{era}",
                confidence="ok" if c.lat is not None else "no_coords",
                extra=extra,
            ))
    return out
