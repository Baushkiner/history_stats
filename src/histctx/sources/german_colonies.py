"""Немецкие колонии и поселения: Germans from Russia Settlement Locations (GRSL).

Зачем этот слой. В лютеранской или католической метрической книге колонии и
в документах о «российских немцах» место названо по-немецки — Schilling,
Rosenheim, Halbstadt, — а на нынешней карте его нет: колонию переименовали в
1915 году, ещё раз после 1941-го, а сотни вовсе исчезли. Вопрос «где стояла
колония, названная в метрике немецким именем, и когда её основали» решает
указатель, сведённый генеалогами: немецкое имя — его кириллическое написание —
нынешнее имя — точка — год основания — материнская колония или дочерняя —
конфессия. Без него Halbstadt не отличить от трёх других Halbstadt: в
Таврической губернии (Молочна, меннониты, 1804), в Херсонской (Березань,
католики, 1869) и в Сибири (Акмолинская область, меннониты, 1908).

Набор. Germans from Russia Settlement Locations (GRSL), составитель S. Riehl,
карта — historic.place. Два листа Google Sheets, оба отдаются таблицей CSV
адресом `gviz/tq?tqx=out:csv` (robots.txt docs.google.com — `Allow:
/spreadsheet`):

* «GRSL-All Colonies» — рабочий лист, 40 вкладок по группам колоний (Волга,
  Молочна, Хортица, Березань, Волынь, Бессарабия, Сибирь, Восточная Пруссия…),
  19 438 мест, 40 колонок: группа, немецкое имя, варианты написания с
  кириллицей в квадратных скобках, подчинение (волость, приход), губерния или
  область по набору, государство на год основания, широта и долгота, нынешнее
  имя и государство, год основания, материнская, дочерняя колония или хутор,
  конфессия, примечания, номера GOV, Викиданных и GeoNames, дата правки.
  Список вкладок берётся со страницы `/htmlview` листа;
* «Complete» — сводный лист проекта, 18 999 мест, семь колонок. Сверено
  22.11.2026: общих мест 18 985, год основания не расходится ни у одного,
  координаты — у одного; 452 места есть только во вкладках, 14 — только в
  «Complete» (Данцигская губерния, вкладки у неё нет). Основа слоя — вкладки,
  14 мест из «Complete» добавляются к ним с пометкой `extra.sheet`.

Права. CC BY-SA 4.0 — так на странице данных проекта: «Creative Commons
Attribution-ShareAlike 4.0 International License… Enjoy, use, distribute».
Берутся факты — точка, имена, год, тип колонии, конфессия — и короткие
примечания составителя (лицензия это разрешает) со ссылкой на карточку места
на historic.place. Ссылки на источники в колонке «Sources» не копируются:
до них ведёт карточка.

Что попадает в слой. Все места, по записи на место:

* заголовок — тип по колонке «Mother / Daughter / Chutor» («материнская
  колония», «дочерняя колония», «хутор»), иначе «колония», а в трёх
  вкладках Восточной Пруссии, где это обычные деревни, — «поселение»; имя —
  кириллическое написание немецкого имени, если оно есть в скобках, иначе
  немецкое; в скобках — нынешнее имя (кириллицей, если набор его так даёт;
  латиницей набора — иначе, своей транслитерации здесь нет) или «не
  существует»; затем год: «Материнская колония Шиллинг (Sosnovka), осн. 1764»;
* какое кириллическое написание чьё — немецкого имени или нынешнего, —
  набор не размечает: «[Шиллинг]» и «[Кошкарево]» стоят одинаково. Решает
  сходство латинской записи с тем и другим (`assign_cyrillic`);
* год основания — `year_from`, конец — горизонт проекта, 1960 год, с
  точностью `open` («с 1764»), как у храмов из Викиданных: колонии
  переименовывали и выселяли, но год конца набор не даёт. «1790-1835»,
  «1748/49», «after 1865» — первый год и `date_approx`; «1820s» —
  десятилетие; «9th century» — век. «(see notes)» в наборе значит, что год —
  это приход первых немецких колонистов, а не основание села: в заголовке
  тогда «с 1749», а не «осн.». Без года — `no_date`: на ленте времени такой
  записи нет, а указатель «немецкое имя → нынешнее» от этого не хуже;
* губерния 1897 года и рамка — `frame.Frame`. Земли Восточной Пруссии,
  ставшие в 1945 году Калининградской областью, рамку проходят (полигоны СССР
  по CShapes), губернии у них нет; польская часть Пруссии, Банат, Бачка,
  Добруджа — `outside_bbox`, и записи остаются в выгрузке: соседние земли,
  откуда приходили и куда уходили.
"""

from __future__ import annotations

import csv
import difflib
import io
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from ..net import USER_AGENT
from ..schema import ContextRecord, LayerSpec, clean_text
from .uezd_names import translit

SHEET_ALL = "16w8pOrKYIS7pPH7GyJMFAt2Mgve4eH6d9NpArxlY-6A"
SHEET_COMPLETE = "1pUbl8_DGtiwvHwXwEIDAhbwPB3uApKCpIQCI6hPEnH4"
HTMLVIEW_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ALL}/htmlview"
TAB_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ALL}/gviz/tq?tqx=out:csv&gid={{gid}}"
COMPLETE_URL = (f"https://docs.google.com/spreadsheets/d/{SHEET_COMPLETE}"
                "/gviz/tq?tqx=out:csv&sheet=Complete")
DATA_PAGE = "https://sites.google.com/riehl-partner-web.de/grsl-daten/startpage"
PROJECT_URL = "https://www.germansfromrussiasettlementlocations.org/"

LICENSE = (
    "CC BY-SA 4.0 (страница данных GRSL: «Creative Commons Attribution-ShareAlike 4.0 "
    "International License… Enjoy, use, distribute»). Берутся факты — точка, имена, год, "
    "тип колонии, конфессия — и примечания составителя со ссылкой на карточку места"
)

GERMAN_COLONIES = LayerSpec(
    slug="german_colonies",
    title="Немецкие колонии и поселения",
    group="admin",
    source="Germans from Russia Settlement Locations (GRSL, S. Riehl), листы Google Sheets",
    license=LICENSE,
    description=(
        "Где стояла колония, названная в метрике немецким именем, и когда её основали: "
        "19 452 места — колонии Поволжья, Причерноморья, Волыни, Бессарабии, Кавказа, "
        "Сибири и Царства Польского, деревни Восточной Пруссии — с кириллическим "
        "написанием, нынешним именем, годом основания (у 2 424), материнской или дочерней "
        "колонией и конфессией."
    ),
    url=DATA_PAGE,
    status="harvested",
    expected_rows=19452,
)

# Горизонт проекта: конец открытого срока у колонии с годом основания.
HORIZON = 1960

# Колонки вкладок, на которых держится разбор. Заголовки в листе многострочные
# («Other Names \nand Spellings») — сравниваются после схлопывания пробелов.
REQUIRED = (
    "Colony Group", "Ancestral Name(s)", "Other Names and Spellings",
    "District, Parish and/or City of Authority", "Area, Governorate, Oblast",
    "Country at time of Founding (assumed*)", "Latitude", "Longitude", "Current Name(s)",
    "Current Country", "Year Founded", "Mother / Daughter / Chutor Colony",
    "Religions (primary*)", "Notes", "GOV-ID", "Wikidata", "GeoNames ID Permanent Link",
    "Last Update", "@id Historic Place GRSL", "Historic.Place GRSL, DEU",
)
# Лист «Complete»: две строки шапки, семь колонок без имён у последней.
COMPLETE_COLUMNS = ("Ancestral Name(s)", "Other Names and Spellings", "Current Name(s)",
                    "Area, Governorate, Oblast", "Year Founded", "Historic.Place GRSL")

CONFIDENCE_NO_COORDS = "no_coords"
CONFIDENCE_NO_DATE = "no_date"
CONFIDENCE_AFTER_HORIZON = "after_1960"

# Вкладки Восточной Пруссии: там не колонии, а обычные деревни провинции.
PRUSSIA_PREFIX = "East_Prussia"

# Группы колоний по-русски — по имени вкладки. Незнакомая вкладка (лист
# пополняется) пойдёт под своим именем.
GROUPS_RU = {
    "Astrakhan": "Астраханские колонии", "Banat": "Банат", "Batschka": "Бачка",
    "Belowesch": "Беловежские колонии", "Beresan": "Березань", "Bessarabia": "Бессарабия",
    "Bukovina": "Буковина", "Carpatho": "Закарпатье", "Caucasus": "Кавказ",
    "Central Asia": "Средняя Азия", "Chortitza": "Хортица", "Crimea (Krim)": "Крым",
    "Dobrudscha": "Добруджа", "Don Cossacks": "Область войска Донского",
    "East_Prussia-Allenstein": "Восточная Пруссия, округ Алленштейн",
    "East_Prussia-Gumbinnen": "Восточная Пруссия, округ Гумбиннен",
    "East_Prussia-Königsberg": "Восточная Пруссия, округ Кёнигсберг",
    "Galizien": "Галиция", "Glückstal": "Глюксталь", "Großliebental": "Гросслибенталь",
    "Hoffnungstal": "Гофнунгсталь", "Jewish": "еврейские земледельческие колонии",
    "Kherson": "Херсонские колонии", "Kronau": "Кронау", "Kutschurgan": "Кучурган",
    "Mariupol": "Мариупольские колонии", "Molotschna": "Молочна", "Prischib": "Пришиб",
    "Samara": "Самарские колонии", "Schwedengebiet": "Шведские колонии",
    "Siberia": "Сибирь", "St Petersburg": "Петербургские колонии", "Taurien": "Таврия",
    "Ural": "Урал", "Vistula": "Висла (Царство Польское)",
    "Volga": "Поволжье", "Volhynia (Polish)": "Волынь (польская часть)",
    "Volhynia (Ukrainian)": "Волынь (украинская часть)",
    "Yekaterinoslav": "Екатеринославские колонии", "Zagradovka": "Заградовка",
    "Danzig": "Данцигская губерния",
}
# Группа для 14 мест, которые есть только в листе «Complete».
COMPLETE_ONLY_GROUP = "Danzig"

# Тип колонии по колонке «Mother / Daughter / Chutor Colony».
KINDS = {
    "mother": "Материнская колония",
    "daughter": "Дочерняя колония",
    "chutor": "Хутор",
    "daughter, chutor": "Хутор",
    "hamlet": "Хутор",
    "deportation": "Поселение депортированных",
}
KIND_DEFAULT = "Колония"
KIND_PRUSSIA = "Поселение"

# Конфессии; звёздочка в наборе отмечает основную («primary*»).
RELIGIONS_RU = {
    "protestant": "протестанты", "protestamt": "протестанты", "prodestant": "протестанты",
    "catholic": "католики", "mennonite": "меннониты", "jewish": "иудеи",
    "hutterite": "гуттериты", "orthodox": "православные", "reformed": "реформаты",
}

ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX",
         10: "X", 11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV", 16: "XVI",
         17: "XVII", 18: "XVIII", 19: "XIX", 20: "XX"}

_RE_TABS = re.compile(r'items\.push\(\{name: "([^"]+)", pageUrl: "[^"]+", gid: "(\d+)"')
_RE_LATLON = re.compile(r"[?&]lat=(-?[\d.]+)&lon=(-?[\d.]+)")
_RE_SELECT = re.compile(r"select=n(\d+)")
_RE_BRACKET = re.compile(r"\[([^\]]*)\]")
_RE_CYR = re.compile(r"[А-Яа-яЁёІіЇїЄєЎў]")
_RE_SEE_NOTES = re.compile(r"\s*\(see notes\)\s*$", re.I)


class GermanColoniesError(RuntimeError):
    """Лист не скачался или пришёл не в том виде."""


# --- сеть -----------------------------------------------------------------

def fetch_text(url: str, *, attempts: int = 4, pause: float = 3.0, timeout: int = 180) -> str:
    """Страница или CSV листа; сброс соединения повторяется, 4xx — нет."""
    last: Optional[Exception] = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise GermanColoniesError(f"{url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(pause * (attempt + 1))
    raise GermanColoniesError(f"{url}: не скачалось за {attempts} попытки ({last})")


def parse_tabs(html: str) -> list[tuple[str, str]]:
    """Вкладки листа со страницы `/htmlview`: [(имя, gid), …] в порядке листа."""
    tabs = _RE_TABS.findall(html)
    if not tabs:
        raise GermanColoniesError("на странице листа не нашлось вкладок: разметка сменилась?")
    return tabs


def cached_sheets(cache_dir: Path, *, refresh: bool = False,
                  pause: float = 1.0) -> tuple[list[tuple[str, str, str]], str]:
    """Вкладки «All Colonies» и лист «Complete» — из кэша или из сети.

    Возвращает [(имя вкладки, gid, текст CSV), …] и текст «Complete». Каждый
    ответ ложится в `cache_dir` сразу: оборванное скачивание продолжается
    с места обрыва. `refresh` скачивает всё заново, список вкладок тоже.
    """
    cache_dir = Path(cache_dir)
    tabs_dir = cache_dir / "tabs"
    tabs_dir.mkdir(parents=True, exist_ok=True)
    view = cache_dir / "htmlview.html"
    if refresh or not view.exists():
        view.write_text(fetch_text(HTMLVIEW_URL), encoding="utf-8")
    tabs = parse_tabs(view.read_text(encoding="utf-8"))
    out = []
    for name, gid in tabs:
        path = tabs_dir / f"{gid}.csv"
        if refresh or not path.exists() or path.stat().st_size == 0:
            path.write_text(fetch_text(TAB_URL.format(gid=gid)), encoding="utf-8")
            time.sleep(pause)
        out.append((name, gid, path.read_text(encoding="utf-8")))
    complete = cache_dir / "complete.csv"
    if refresh or not complete.exists() or complete.stat().st_size == 0:
        complete.write_text(fetch_text(COMPLETE_URL), encoding="utf-8")
    return out, complete.read_text(encoding="utf-8")


# --- чтение листов -----------------------------------------------------------

def header_key(value: str) -> str:
    """«Other Names \\nand Spellings» → «Other Names and Spellings»."""
    return " ".join(str(value or "").split())


def read_tab(text: str, tab: str) -> list[dict]:
    """Строки вкладки словарями; пустые строки листа пропускаются."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise GermanColoniesError(f"вкладка «{tab}» пуста")
    head = [header_key(h) for h in rows[0]]
    missing = [c for c in REQUIRED if c not in head]
    if missing:
        raise GermanColoniesError(f"вкладка «{tab}»: нет колонок {missing}")
    out = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        record = dict(zip(head, row))
        record["_tab"] = tab
        out.append(record)
    return out


def read_complete(text: str) -> list[dict]:
    """Лист «Complete»: две строки шапки, точка — в параметрах ссылки historic.place."""
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise GermanColoniesError("лист «Complete» пуст")
    head = [header_key(h) for h in rows[1]]
    # Шестая колонка подписана с припиской места составителя («… Torgau,
    # DE-SN») — сверяется начало заголовка, а не весь.
    if len(head) < 6 or any(not h.startswith(c) for c, h in zip(COMPLETE_COLUMNS, head)):
        raise GermanColoniesError(f"лист «Complete»: колонки не те — {head}")
    out = []
    for row in rows[2:]:
        if not any(cell.strip() for cell in row) or len(row) < 6:
            continue
        if header_key(row[0]) == COMPLETE_COLUMNS[0]:      # шапка, повторённая в листе
            continue
        link = row[5].strip()
        key = _RE_SELECT.search(link)
        point = _RE_LATLON.search(link)
        out.append({
            "Ancestral Name(s)": row[0], "Other Names and Spellings": row[1],
            "Current Name(s)": row[2], "Area, Governorate, Oblast": row[3],
            "Year Founded": row[4], "Historic.Place GRSL, DEU": link,
            "@id Historic Place GRSL": key.group(1) if key else "",
            "Latitude": point.group(1) if point else "",
            "Longitude": point.group(2) if point else "",
            "_tab": COMPLETE_ONLY_GROUP,
        })
    return out


# --- разбор полей -------------------------------------------------------------

def parse_year(raw: Optional[str]) -> dict:
    """Год основания в числа.

    Возвращает {year, kind, approx, settlers}: `kind` — «year», «decade»,
    «century» или None; `settlers` — год прихода первых немецких колонистов
    («(see notes)»), а не основания села. «1748/49», «1790-1835» и «after
    1865» дают первый год и `approx`; «before 1864» — тот же год и `approx`:
    колония к нему уже стояла, а раньше — неизвестно.
    """
    text = clean_text(raw) or ""
    settlers = bool(_RE_SEE_NOTES.search(text))
    text = _RE_SEE_NOTES.sub("", text).strip()
    out = {"year": None, "kind": None, "approx": False, "settlers": settlers}
    if not text or text.lower() == "unknown":
        return out
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th) century", text, re.I)
    if m:
        out.update(year=(int(m.group(1)) - 1) * 100 + 1, kind="century", approx=True)
        return out
    m = re.fullmatch(r"(\d{4})'?s", text)
    if m:
        out.update(year=int(m.group(1)), kind="decade", approx=True)
        return out
    m = re.fullmatch(r"(after|before)\s+(\d{4})", text, re.I)
    if m:
        out.update(year=int(m.group(2)), kind="year", approx=True)
        return out
    m = re.fullmatch(r"(\d{4})(?:\s*[-/–]\s*(\d{1,4}))?", text)
    if m:
        out.update(year=int(m.group(1)), kind="year", approx=bool(m.group(2)))
        return out
    return out


def year_label(raw: Optional[str]) -> Optional[str]:
    """Год для заголовка: «1764», «1790–1835», «после 1865», «1820-е», «IX век»."""
    info = parse_year(raw)
    if info["year"] is None:
        return None
    text = _RE_SEE_NOTES.sub("", clean_text(raw) or "").strip()
    if info["kind"] == "century":
        century = (info["year"] - 1) // 100 + 1
        return f"{ROMAN.get(century, century)} век"
    if info["kind"] == "decade":
        return f"{info['year']}-е"
    low = text.lower()
    if low.startswith("after"):
        return f"после {info['year']}"
    if low.startswith("before"):
        return f"до {info['year']}"
    m = re.fullmatch(r"(\d{4})\s*[-/–]\s*(\d{1,4})", text)
    if m:
        tail = m.group(2)
        end = int(m.group(1)[: 4 - len(tail)] + tail)
        return f"{m.group(1)}–{end}"
    return str(info["year"])


def fold(text: str) -> str:
    """Латиница и кириллица к одному виду для сравнения написаний."""
    s = translit(text) if _RE_CYR.search(text or "") else str(text or "").lower()
    s = unicodedata.normalize("NFKD", s.replace("ß", "ss"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("tsch", "ch").replace("sch", "sh").replace("w", "v").replace("kh", "h")
    return re.sub(r"[^a-z]", "", s)


def split_names(value: Optional[str]) -> tuple[list[str], list[str]]:
    """«Sosnovka, Koshkarevo, [Кошкарево]» → (латинские варианты, кириллица)."""
    text = clean_text(value) or ""
    cyrillic = []
    for group in _RE_BRACKET.findall(text):
        for part in re.split(r"\s*/\s*", group):
            part = part.strip()
            if part:
                cyrillic.append(part)
    rest = _RE_BRACKET.sub("", text)
    variants = [v.strip() for v in rest.split(",") if v.strip()]
    # В скобках бывает и латиница — «[Biurkenhof / Kustarnikowo / Кустарниково]».
    latin_in_brackets = [c for c in cyrillic if not _RE_CYR.search(c)]
    cyrillic = [c for c in cyrillic if _RE_CYR.search(c)]
    return variants + latin_in_brackets, cyrillic


def current_name(value: Optional[str]) -> tuple[Optional[str], Optional[str], bool]:
    """(имя, полная строка, исчезло ли место) из «Current Name(s)».

    «Sosnovka, Saratov, Russia» → «Sosnovka»; «Defunct. Village no longer
    exists. Formerly known as …» — места нет.
    """
    text = clean_text(value)
    if not text:
        return None, None, False
    text = _RE_SEE_NOTES.sub("", text).strip()
    if text.lower().startswith("defunct"):
        return None, text, True
    return text.split(",")[0].strip() or None, text, False


def _similar(a: str, b: str) -> float:
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    return difflib.SequenceMatcher(None, fa, fb).ratio()


def assign_cyrillic(cyrillic: Iterable[str], ancestral: Optional[str],
                    current: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Какое кириллическое написание — немецкого имени, какое — нынешнего.

    Набор кладёт их в одни скобки без пометки: «[Шиллинг]» — немецкое имя,
    «[Кошкарево]» — нынешнее, «[Колобатино/Росенхеим]» — оба. Решает сходство
    латинской записи с тем и другим; ничья — в пользу немецкого имени: слой
    отвечает на вопрос о немецком имени из метрики.
    """
    german_ru = current_ru = None
    best_g = best_c = 0.0
    for name in cyrillic:
        sg = _similar(name, ancestral or "")
        sc = _similar(name, current or "")
        if sg >= sc:
            if sg > best_g:
                german_ru, best_g = name, sg
        elif sc > best_c:
            current_ru, best_c = name, sc
    return german_ru, current_ru


def kind_of(row: dict) -> str:
    """Тип места по колонке «Mother / Daughter / Chutor» и по вкладке."""
    raw = (clean_text(row.get("Mother / Daughter / Chutor Colony")) or "").lower()
    raw = re.sub(r"\s*\(.*?\)", "", raw).strip()
    if raw in KINDS:
        return KINDS[raw]
    if raw.startswith("chutor"):
        return KINDS["chutor"]
    if str(row.get("_tab", "")).startswith(PRUSSIA_PREFIX):
        return KIND_PRUSSIA
    return KIND_DEFAULT


def religions(value: Optional[str]) -> list[str]:
    """«Catholic*, Mennonite» → [«католики (основная)», «меннониты»]."""
    out = []
    for part in re.split(r"\s*,\s*", clean_text(value) or ""):
        primary = part.endswith("*")
        key = part.rstrip("*").strip().lower()
        if key not in RELIGIONS_RU:
            continue
        label = RELIGIONS_RU[key] + (" (основная)" if primary else "")
        if label not in out:
            out.append(label)
    return out


def number(value) -> Optional[float]:
    try:
        x = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x


def point(row: dict) -> tuple[Optional[float], Optional[float]]:
    lat, lon = number(row.get("Latitude")), number(row.get("Longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None, None
    return lat, lon


def geonames_id(value) -> Optional[str]:
    """«580497» и «https://www.geonames.org/580497» — к номеру."""
    m = re.search(r"(\d{3,})", str(value or ""))
    return m.group(1) if m else None


def wikidata_qid(value) -> Optional[str]:
    """«https://www.wikidata.org/wiki/Q3927» → «Q3927»: в файле хватает номера."""
    m = re.search(r"(Q\d+)", str(value or ""))
    return m.group(1) if m else None


# --- записи -------------------------------------------------------------------

def place_title(row: dict) -> str:
    """«Материнская колония Шиллинг (Sosnovka), осн. 1764»."""
    ancestral = clean_text(row.get("Ancestral Name(s)")) or "без имени"
    _, cyrillic = split_names(row.get("Other Names and Spellings"))
    current, _, defunct = current_name(row.get("Current Name(s)"))
    german_ru, current_ru = assign_cyrillic(cyrillic, ancestral, current)
    title = f"{kind_of(row)} {german_ru or ancestral}"
    now = current_ru or current
    if defunct:
        title += " (не существует)"
    elif now and fold(now) not in {fold(ancestral), fold(german_ru or "")}:
        # Колония, сохранившая имя («Halbstadt» в Алтайском крае), скобок
        # не получает: нынешнее имя то же, что немецкое.
        title += f" ({now})"
    label = year_label(row.get("Year Founded"))
    if label:
        prefix = "с" if parse_year(row.get("Year Founded"))["settlers"] else "осн."
        title += f", {prefix} {label}"
    return title


def place_summary(row: dict, group: str) -> str:
    """Пояснение: тип, группа, год, конфессия, подчинение, нынешнее имя."""
    parts = [f"{kind_of(row)}, группа «{GROUPS_RU.get(group, group)}»"]
    info = parse_year(row.get("Year Founded"))
    label = year_label(row.get("Year Founded"))
    if label and info["settlers"]:
        parts.append(f"первые немецкие колонисты — {label} (по примечанию набора)")
    elif label:
        parts.append(f"основана — {label}")
    else:
        parts.append("год основания набору не известен")
    faiths = religions(row.get("Religions (primary*)"))
    if faiths:
        parts.append("конфессия — " + ", ".join(faiths))
    authority = clean_text(row.get("District, Parish and/or City of Authority"))
    if authority:
        parts.append(f"подчинение — {authority}")
    # Губерния или область по набору — в `place_text`, сюда не повторяется.
    _, full, defunct = current_name(row.get("Current Name(s)"))
    if defunct:
        parts.append("сейчас места нет")
    elif full:
        parts.append(f"сейчас — {full}")
    return "; ".join(parts) + ". По GRSL"


def row_to_record(row: dict, *, sheet: str = "all") -> ContextRecord:
    """Строка листа → запись слоя. Губерния и рамка — потом, `Frame.mark`."""
    group = row.get("_tab") or ""
    ancestral = clean_text(row.get("Ancestral Name(s)"))
    variants, cyrillic = split_names(row.get("Other Names and Spellings"))
    current, _, defunct = current_name(row.get("Current Name(s)"))
    german_ru, current_ru = assign_cyrillic(cyrillic, ancestral, current)
    raw_year = clean_text(row.get("Year Founded"))
    info = parse_year(raw_year)
    lat, lon = point(row)

    year_from = year_to = None
    precision, approx = "unknown", False
    period_raw = raw_year
    if info["year"] is not None:
        year_from, approx = info["year"], info["approx"]
        if year_from > HORIZON:
            year_to, precision = year_from, "year"
        else:
            year_to, precision = HORIZON, "open"
            period_raw = f"с {raw_year}"

    if lat is None:
        confidence = CONFIDENCE_NO_COORDS
    elif year_from is None:
        confidence = CONFIDENCE_NO_DATE
    elif year_from > HORIZON:
        confidence = CONFIDENCE_AFTER_HORIZON
    else:
        confidence = "ok"

    # Нынешнее имя целиком («Sosnovka, Saratov, Russia») стоит в описании,
    # губерния набора — в `place_text`, исходный год — в `period_raw`: в extra
    # они не повторяются, слой и так один из самых крупных.
    extra = {
        "group": GROUPS_RU.get(group, group),
        "name_de": ancestral,
        "name_ru": german_ru,
        "variants": variants or None,
        "cyrillic": cyrillic or None,
        "current_name_ru": current_ru,
        "current_country": clean_text(row.get("Current Country")),
        "defunct": True if defunct else None,
        "country_at_founding": clean_text(row.get("Country at time of Founding (assumed*)")),
        "authority": clean_text(row.get("District, Parish and/or City of Authority")),
        "type_en": clean_text(row.get("Mother / Daughter / Chutor Colony")),
        "religions_en": clean_text(row.get("Religions (primary*)")),
        "year_is_settlers": True if info["settlers"] else None,
        "notes": clean_text(row.get("Notes")),
        "wikidata": wikidata_qid(row.get("Wikidata")),
        "geonames": geonames_id(row.get("GeoNames ID Permanent Link")),
        "gov_id": clean_text(row.get("GOV-ID")),
        "plat_map": clean_text(row.get("Plat Map")),
        "sheet": None if sheet == "all" else sheet,
    }
    url = clean_text(row.get("Historic.Place GRSL, DEU")) or DATA_PAGE
    return GERMAN_COLONIES.new_record(
        title=place_title(row),
        category=kind_of(row),
        lat=lat, lon=lon,
        place_text=clean_text(row.get("Area, Governorate, Oblast")),
        year_from=year_from, year_to=year_to,
        date_precision=precision, date_approx=approx,
        period_raw=period_raw,
        summary=place_summary(row, group),
        url=url,
        source_id=clean_text(row.get("@id Historic Place GRSL")),
        confidence=confidence,
        extra={k: v for k, v in extra.items() if v is not None},
    )


def merge(tab_rows: Iterable[dict], complete_rows: Iterable[dict]) -> tuple[list[dict], Counter]:
    """Вкладки — основа, из «Complete» — только то, чего во вкладках нет.

    Сверка по номеру места historic.place: расхождения года и точки
    считаются (в отчёт) и помечаются у записи вкладки (`extra`), строка
    «Complete» в слой тогда не идёт.
    """
    counts: Counter = Counter()
    rows = list(tab_rows)
    by_key = {}
    for row in rows:
        key = (row.get("@id Historic Place GRSL") or "").strip()
        if key:
            if key in by_key:
                counts["повтор номера во вкладках"] += 1
            by_key.setdefault(key, row)
    for row in complete_rows:
        key = (row.get("@id Historic Place GRSL") or "").strip()
        own = by_key.get(key)
        if own is None:
            counts["только в «Complete»"] += 1
            rows.append(row)
            continue
        counts["в обоих листах"] += 1
        if (clean_text(own.get("Year Founded")) or "").lower() != \
                (clean_text(row.get("Year Founded")) or "").lower():
            counts["год расходится"] += 1
            own["_complete_year"] = clean_text(row.get("Year Founded"))
        a, b = point(own), point(row)
        if None not in a and None not in b and (abs(a[0] - b[0]) > 0.01 or abs(a[1] - b[1]) > 0.01):
            counts["точка расходится"] += 1
            own["_complete_point"] = [b[0], b[1]]
    counts["только во вкладках"] = len(by_key) - counts["в обоих листах"]
    return rows, counts


def records(rows: Iterable[dict]) -> list[ContextRecord]:
    out = []
    for row in rows:
        sheet = "complete" if row.get("_tab") == COMPLETE_ONLY_GROUP else "all"
        rec = row_to_record(row, sheet=sheet)
        if row.get("_complete_year"):
            rec.extra["complete_year"] = row["_complete_year"]
        if row.get("_complete_point"):
            rec.extra["complete_point"] = row["_complete_point"]
        out.append(rec)
    return out
