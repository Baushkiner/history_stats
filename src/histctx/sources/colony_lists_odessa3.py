"""Списки колоний Odessa Digital Library: Поволжье, Причерноморье, Крым, меннониты.

Зачем этот слой. Указатель GRSL (слой `german_colonies`) — один свод, и год
основания в нём один. Odessa Digital Library (odessa3.org, Р. Эрих) хранит
четыре списка сёл, которые генеалоги GRHS свели в 1996–1999 годах по Штумпу,
Саллету, Бератцу и Гизингеру, — независимую от GRSL запись тех же колоний.
По ним видно, где годы основания расходятся, и в них есть то, чего в GRSL
нет: у колоний Поволжья — сторона Волги и население по переписи (1773, 1912,
1926 годов), у меннонитских сёл — материнское поселение («daughter colony of
Am Trakt»), у сёл под Одессой — русские имена и район, у крымских — аренда
(«Hochheim Leased Villages») по петербургскому перечню 1905 года.

Списки (`collections/refs/link/`, текст с колонками фиксированной ширины):

* `volgavl.txt` — «Volga Area Villages», R. Heinle, 1996: немецкое и русское
  имя, группа или район, сторона Волги (B — нагорная, W — луговая, S —
  Самарская, P — петербургские колонии), год основания, конфессия (E, K, M),
  другое имя, год переписи и население, ссылки на страницы Саллета (s),
  Гизингера (g), Бератца (b);
* `odessavl.txt` — «Odessa Area Villages», B. Gutenberg, 1996: немецкое имя,
  другие имена, группа, район, год, конфессия, примечания;
* `crimeavl.txt` — «Crimea Area Villages», D. L. Wahl, 1996: село, волость,
  год, область, ссылка (ST — Штумп, S — Саллет, SP — петербургский перечень
  1905 года), примечания;
* `menvil.txt` — «Mennonite Villages in Russia», T. P. Janzen, 1999: село,
  русское имя, год, губерния (и уезд), поселение.

Права. У каждого списка в шапке: «may be freely used for personal, nonprofit
purposes… it may not be republished in any form without permission of the
copyright owner»; на странице библиотеки — «no document may be… embedded in
public databases without permission». Согласие получено владельцем проекта
(сообщено 24.11.2026). Берутся факты — имя, место, год, конфессия, население,
поселение — со ссылкой на файл списка; шапки, вступления и пересказ
источников не копируются.

Что попадает в слой. Каждая строка каждого списка — запись. Списки сами
предупреждают, что одно село стоит в них несколько раз («Little effort has
been made to prevent multiple entries»), и строки не схлопываются: у двух
строк одного села бывают разные годы, ссылки и примечания, а сверка — то,
ради чего слой собран.

* Точка — из GRSL: строка ищется в слое `german_colonies` по немецкому имени
  (затем по русскому и другим именам) среди групп своего края; несколько
  кандидатов разводятся годом основания, затем районом. Если год расходится с
  GRSL больше чем на десять лет, точка не берётся (кандидат — в
  `extra.grsl_candidate`). Не нашлось или не развелось — записи без точки
  (`no_coords`), губерния тогда — по самому списку (у меннонитов — губерния из строки, у Одессы — Херсонская, у Крыма —
  Таврическая, у Поволжья — по стороне Волги: нагорная — Саратовская, луговая
  и Самарская — Самарская, на 1897 год). Совпадение записано в `extra.grsl`,
  расхождение годов — в `extra.grsl_year`.
* Год — как у GRSL: год основания, конец — 1960 (`open`), «1848-64» и
  «1804/05» — первый год и `date_approx`. Без года — `no_date` при точке.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..net import fetch_bytes
from ..schema import ContextRecord, LayerSpec, clean_text
from .german_colonies import HORIZON, fold, parse_year, year_label

LAYER_ID = "colony_lists_odessa3"
BASE_URL = "https://www.odessa3.org/collections/refs/link/"
LIBRARY_URL = "https://www.odessa3.org/collections/"

LICENSE = (
    "© составители списков (R. Heinle, B. Gutenberg, D. L. Wahl, T. P. Janzen), "
    "Odessa Digital Library (R. Ehrich): «may not be republished in any form without "
    "permission of the copyright owner»; собрано с согласия владельца, полученного "
    "владельцем проекта (сообщено 24.11.2026). Берутся факты — имя, место, год, "
    "конфессия, население — со ссылкой на файл списка; точка — из GRSL (CC BY-SA 4.0)"
)

COLONY_LISTS = LayerSpec(
    slug=LAYER_ID,
    title="Списки колоний Odessa3: Поволжье, Причерноморье, Крым, меннониты",
    group="admin",
    source="Odessa Digital Library (odessa3.org), списки сёл GRHS 1996–1999 годов: "
           "R. Heinle, B. Gutenberg, D. L. Wahl, T. P. Janzen; точки — GRSL",
    license=LICENSE,
    description=(
        "Вторая, независимая от GRSL запись немецких и меннонитских колоний: год "
        "основания по Штумпу и Саллету, сторона Волги и население по переписи у "
        "колоний Поволжья, материнское поселение у меннонитских сёл. Отвечает, "
        "сходятся ли годы основания у двух сводов и из какого поселения вышло село."
    ),
    url=LIBRARY_URL,
    status="harvested",
    expected_rows=2116,
)

CONFIDENCE_NO_COORDS = "no_coords"
# На сколько лет год основания может разойтись с GRSL, чтобы точка GRSL
# всё ещё считалась точкой этого села.
YEAR_TOLERANCE = 10
CONFIDENCE_NO_DATE = "no_date"
CONFIDENCE_AFTER_HORIZON = "after_1960"


class Odessa3Error(RuntimeError):
    """Список не скачался или пришёл не в том виде."""


@dataclass(frozen=True)
class ListSpec:
    key: str
    file: str
    title: str
    compiler: str
    year: int
    area: str            # край по-русски, для заголовка и категории
    fields: tuple        # имена колонок слева направо
    groups: tuple        # группы GRSL (по-русски), среди которых ищется точка
    region: Optional[str] = None   # губерния 1897 года для записей без точки

    @property
    def url(self) -> str:
        return BASE_URL + self.file


# Группы GRSL, в которых стоят меннонитские сёла. Пруссия, Висла, Волынь,
# Банат и прочие земли вне империи сюда не входят: меннонитов там список
# Янцена не перечисляет.
MENNONITE_GROUPS = (
    "Хортица", "Молочна", "Заградовка", "Самарские колонии", "Сибирь", "Кавказ",
    "Екатеринославские колонии", "Мариупольские колонии", "Таврия", "Крым", "Урал",
    "Средняя Азия", "Область войска Донского", "Херсонские колонии", "Поволжье",
    "Березань", "Пришиб", "Кронау",
)

LISTS = (
    ListSpec("volga", "volgavl.txt", "Volga Area Villages", "R. Heinle", 1996, "Поволжье",
             ("name", "name_ru", "district", "side", "year", "religion", "aka", "census",
              "population", "remarks"),
             ("Поволжье", "Самарские колонии", "Астраханские колонии")),
    ListSpec("odessa", "odessavl.txt", "Odessa Area Villages", "B. Gutenberg", 1996,
             "Причерноморье (Одесса)",
             ("name", "other_names", "district", "rayon", "year", "religion", "remarks"),
             ("Гросслибенталь", "Глюксталь", "Кучурган", "Березань", "Херсонские колонии",
              "Гофнунгсталь", "Шведские колонии", "Заградовка", "Бессарабия"),
             "Херсонская губерния"),
    ListSpec("crimea", "crimeavl.txt", "Crimea Area Villages", "D. L. Wahl", 1996, "Крым",
             ("name", "district", "year", "area", "ref", "remarks"),
             ("Крым", "Таврия"), "Таврическая губерния"),
    ListSpec("mennonite", "menvil.txt", "Mennonite Villages in Russia", "T. P. Janzen", 1999,
             "меннонитские сёла",
             ("name", "name_ru", "year", "place", "colony"), MENNONITE_GROUPS),
)
BY_KEY = {spec.key: spec for spec in LISTS}

# Шапка таблицы у Крыма без линейки: колонки — по началу слов заголовка.
CRIMEA_HEADER = ("VILLAGE", "DISTRICT", "YEAR", "AREA", "REF", "REMARKS")

SIDES_RU = {"B": "нагорная сторона Волги", "W": "луговая сторона Волги",
            "S": "Самарский край", "P": "петербургские колонии"}
SIDE_REGION = {"B": "Саратовская губерния", "W": "Самарская губерния",
               "S": "Самарская губерния"}
RELIGION_CODES = {"E": "лютеране", "K": "католики", "M": "меннониты"}
RELIGION_WORDS = {"evangelical": "лютеране", "catholic": "католики",
                  "mennonite": "меннониты", "baptist": "баптисты",
                  "reformed": "реформаты", "separatist": "сепаратисты", "ev": "лютеране"}
CRIMEA_REFS = {"ST": "Штумп", "S": "Саллет", "SP": "петербургский перечень 1905 года"}

# Губернии строки меннонитского списка → губерния 1897 года.
GOVERNMENTS = {
    "taurida": "Таврическая губерния", "ekaterinoslav": "Екатеринославская губерния",
    "kherson": "Херсонская губерния", "samara": "Самарская губерния",
    "orenburg": "Оренбургская губерния", "ufa": "Уфимская губерния",
    "saratov": "Саратовская губерния", "voronezh": "Воронежская губерния",
    "kharkov": "Харьковская губерния", "terek": "Терская область",
    "kuban": "Кубанская область", "stavropol": "Ставропольская губерния",
    "don": "Земля войска Донского", "tomsk": "Томская губерния",
    "akmolinsk": "Акмолинская область", "omsk": "Акмолинская область",
    "pavlodar": "Семипалатинская область", "slavgorod": "Томская губерния",
    "barnaul": "Томская губерния", "volhynia": "Волынская губерния",
    "kiev": "Киевская губерния", "poltava": "Полтавская губерния",
    "chernigov": "Черниговская губерния", "orel": "Орловская губерния",
    "mogilev": "Могилёвская губерния", "minsk": "Минская губерния",
    "turgai": "Тургайская область", "ural": "Уральская область",
    "syr-darya": "Сырдарьинская область", "tashkent": "Сырдарьинская область",
    "aulie-ata": "Сырдарьинская область", "khiva": "Хива",
    "transcaspia": "Закаспийская область", "astrakhan": "Астраханская губерния",
}

_RE_DASHES = re.compile(r"-{3,}")
_RE_UMLAUT = re.compile(r"(?<=[^aeiouAEIOU])[aouAOU]e")
_RE_VOLGA_REF = re.compile(r"^[sgbSGB]\d+$")


# --- разбор текста ----------------------------------------------------------


def spans_from_dashes(line: str) -> list[tuple[int, int]]:
    """Линейка «----  -----» → границы колонок; последняя — до конца строки."""
    starts = [m.start() for m in _RE_DASHES.finditer(line)]
    spans = [(a, b) for a, b in zip(starts, starts[1:] + [10_000])]
    return spans


def spans_from_header(line: str, words: Iterable[str]) -> list[tuple[int, int]]:
    starts = [line.index(word) for word in words]
    return [(a, b) for a, b in zip(starts, starts[1:] + [10_000])]


def _cut(line: str, spans: list[tuple[int, int]]) -> list[str]:
    return [line[a:b].strip() for a, b in spans]


def _is_rule(line: str) -> bool:
    return bool(line.strip()) and set(line.strip()) <= {"-", " "}


def table_lines(text: str, spec: ListSpec) -> tuple[list[tuple[int, int]], list[tuple[int, str]]]:
    """Границы колонок и строки таблицы (с номерами строк файла)."""
    lines = text.expandtabs(8).splitlines()
    spans, start = None, None
    if spec.key == "crimea":
        for i, line in enumerate(lines):
            if all(word in line for word in CRIMEA_HEADER):
                spans, start = spans_from_header(line, CRIMEA_HEADER), i + 1
                break
    else:
        for i, line in enumerate(lines):
            if _is_rule(line) and len(_RE_DASHES.findall(line)) >= len(spec.fields) - 1:
                spans, start = spans_from_dashes(line), i + 1
                break
    if spans is None:
        raise Odessa3Error(f"{spec.file}: не найдена шапка таблицы")
    if len(spans) != len(spec.fields):
        raise Odessa3Error(f"{spec.file}: колонок {len(spans)}, ожидалось {len(spec.fields)}")
    body = []
    for i in range(start, len(lines)):
        line = lines[i]
        if _is_rule(line):      # у Поволжья после таблицы — линейка и примечания
            break
        if line.strip():
            body.append((i + 1, line.rstrip()))
    return spans, body


def parse_list(text: str, spec: ListSpec) -> list[dict]:
    """Строки таблицы → словари полей. Перенос строки склеивается с предыдущей.

    У меннонитского списка длинное имя переносится: «Andreyevka» и ниже
    «(same as Gnadental)  1882 Samara …»; примечание — «(daughter colony of» и
    «   Altonau, Molotschna)». Строка, начатая скобкой или отступом, — продолжение
    предыдущей: имя дописывается, пустые поля заполняются, а если других полей
    нет — текст уходит в примечание.
    """
    spans, body = table_lines(text, spec)
    rows: list[dict] = []
    last_field = spec.fields[-1]
    for lineno, line in body:
        cells = dict(zip(spec.fields, _cut(line, spans)))
        continuation = rows and (line.startswith("(") or line.startswith(" "))
        if not continuation:
            row = {k: v for k, v in cells.items() if v}
            row["_line"] = lineno
            if row.get("name"):
                rows.append(row)
            continue
        prev = rows[-1]
        others = {k: v for k, v in cells.items() if v and k != "name"}
        if others and line.startswith("("):
            prev["name"] = f"{prev['name']} {cells['name']}".strip()
            for k, v in others.items():
                prev[k] = f"{prev[k]}; {v}" if prev.get(k) else v
        else:
            note = " ".join(line.split())
            prev[last_field] = f"{prev[last_field]} {note}" if prev.get(last_field) else note
    return rows


# --- поля -------------------------------------------------------------------


def religions_of(row: dict, spec: ListSpec) -> list[str]:
    raw = row.get("religion") or ""
    out: list[str] = []
    if spec.key == "volga":
        for code in re.split(r"[,/ ]+", raw):
            name = RELIGION_CODES.get(code.strip().upper())
            if name and name not in out:
                out.append(name)
        return out
    text = raw
    if spec.key == "crimea":
        # У Крыма конфессия стоит в примечании сокращением: «ev», «kath».
        text = row.get("remarks") or ""
    for word in re.split(r"[^A-Za-z]+", text.lower()):
        name = RELIGION_WORDS.get(word) or ("католики" if word.startswith("cath") or
                                            word.startswith("kath") else None)
        if name and name not in out:
            out.append(name)
    return out


def volga_refs(remarks: Optional[str]) -> tuple[list[str], Optional[str]]:
    """«s147,g87,b355» → (ссылки, примечание без ссылок)."""
    if not remarks:
        return [], None
    refs, notes = [], []
    for part in remarks.split(","):
        part = part.strip()
        if _RE_VOLGA_REF.match(part) or part == "W":
            refs.append(part)
        elif part:
            notes.append(part)
    return refs, (", ".join(notes) or None)


def number(value: Optional[str]) -> Optional[int]:
    if value and value.isdigit():
        return int(value)
    return None


def region_of(row: dict, spec: ListSpec) -> Optional[str]:
    """Губерния 1897 года по самому списку — для записей без точки."""
    if spec.key == "volga":
        return SIDE_REGION.get((row.get("side") or "").upper())
    if spec.key == "mennonite":
        place = row.get("place") or ""
        for part in reversed([p.strip().lower() for p in place.split(",")]):
            if part in GOVERNMENTS:
                return GOVERNMENTS[part]
        return None
    return spec.region


def kind_of(row: dict) -> str:
    name = (row.get("name") or "").lower()
    if "chutor" in name or "khutor" in name:
        return "Хутор"
    return "Колония"


# --- точки из GRSL ------------------------------------------------------------


@dataclass
class GrslPlace:
    uid: str
    lat: float
    lon: float
    group: str
    names: frozenset
    year: Optional[int]
    name_ru: Optional[str]
    context: str          # губерния, подчинение, примечания — для развода по району
    mennonite: bool


class GrslIndex:
    """Указатель мест слоя `german_colonies` по сложенным написаниям имён."""

    def __init__(self, places: Iterable[GrslPlace]) -> None:
        self.by_name: dict[str, list[GrslPlace]] = {}
        for place in places:
            for name in place.names:
                self.by_name.setdefault(name, []).append(place)

    @classmethod
    def from_features(cls, features: Iterable[dict]) -> "GrslIndex":
        places = []
        for feat in features:
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            props = feat.get("properties") or {}
            extra = props.get("extra") or {}
            names = [extra.get("name_de"), extra.get("name_ru")]
            names += list(extra.get("variants") or []) + list(extra.get("cyrillic") or [])
            folded = frozenset(f for f in (fold(n) for n in names if n) if len(f) > 2)
            if not folded:
                continue
            lon, lat = geom["coordinates"][:2]
            year = props.get("year_from")
            context = " ".join(str(v) for v in (props.get("place_text"), extra.get("authority"),
                                                  extra.get("notes")) if v)
            places.append(GrslPlace(
                uid=props.get("uid") or feat.get("id"), lat=lat, lon=lon,
                group=extra.get("group") or "", names=folded,
                year=year if isinstance(year, int) else None,
                name_ru=extra.get("name_ru"), context=fold(context),
                mennonite="mennonite" in (extra.get("religions_en") or "").lower()))
        return cls(places)

    @classmethod
    def load(cls, path: Path) -> "GrslIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_features(payload.get("features", []))

    def find(self, row: dict, spec: ListSpec, year: Optional[int]) -> tuple[Optional[GrslPlace], str]:
        """Место GRSL для строки списка и как оно найдено (или почему нет)."""
        names = [row.get("name")]
        names += [row.get(k) for k in ("name_ru", "aka")]
        if spec.key == "odessa":
            names += [row.get("other_names")]
        # «Adargin (Schoenbrunn)» — оба имени.
        expanded = []
        for name in names:
            if not name:
                continue
            expanded.append(re.sub(r"\(.*?\)", "", name))
            expanded += re.findall(r"\(([^)]*)\)", name)
        allowed = set(spec.groups)
        keys = []
        for name in expanded:
            # Списки пишут умлаут двумя буквами (Zuerichtal), GRSL — умлаутом
            # (Zürichtal, после `fold` — zurichtal): пробуются оба написания.
            for key in (fold(name), fold(_RE_UMLAUT.sub(lambda m: m.group(0)[0], name))):
                if len(key) >= 3 and key not in keys:
                    keys.append(key)
        for key in keys:
            cands = [p for p in self.by_name.get(key, []) if p.group in allowed]
            cands = list({p.uid: p for p in cands}.values())
            if spec.key == "mennonite" and len(cands) > 1:
                menno = [p for p in cands if p.mennonite]
                cands = menno or cands
            if len(cands) == 1:
                return cands[0], "имя"
            if not cands:
                continue
            if year is not None:
                same = [p for p in cands if p.year == year]
                if len(same) == 1:
                    return same[0], "имя и год"
                if same:
                    cands = same
            hint = " ".join(row.get(k) or "" for k in ("district", "rayon", "place", "colony"))
            tokens = [fold(t) for t in re.split(r"[,;/ ]+", hint) if len(fold(t)) > 3]
            near = [p for p in cands if any(t in p.context for t in tokens)]
            if len(near) == 1:
                return near[0], "имя и район"
            return None, "несколько мест GRSL"
        return None, "нет в GRSL"


# --- записи -------------------------------------------------------------------


def row_to_record(row: dict, spec: ListSpec, grsl: Optional[GrslIndex] = None) -> ContextRecord:
    name = row["name"]
    raw_year = row.get("year")
    info = parse_year(raw_year)
    year_from = year_to = None
    precision, approx, period_raw = "unknown", False, raw_year
    if info["year"] is not None:
        year_from, approx = info["year"], info["approx"]
        if year_from > HORIZON:
            year_to, precision = year_from, "year"
        else:
            year_to, precision, period_raw = HORIZON, "open", f"с {raw_year}"

    match, how = (None, "без GRSL") if grsl is None else grsl.find(row, spec, info["year"])
    candidate = None
    if (match is not None and match.year is not None and info["year"] is not None
            and abs(match.year - info["year"]) > YEAR_TOLERANCE):
        # Одно имя, а годы расходятся на десятилетия: чаще это другое село
        # с тем же именем (Rosenthal Хортицы 1790 и Rosenthal 1927), чем
        # ошибка свода. Точку не берём, кандидата оставляем для сверки.
        candidate, match, how = match, None, "год расходится с GRSL"
    lat = lon = None
    if match is not None:
        lat, lon = match.lat, match.lon
    name_ru = row.get("name_ru")
    title_name = (match.name_ru if match and match.name_ru else None) or name
    kind = kind_of(row)
    title = f"{kind} {title_name}"
    if title_name != name:
        title += f" ({name})"
    label = year_label(raw_year)
    if label:
        title += f", осн. {label}"

    faiths = religions_of(row, spec)
    refs, notes = volga_refs(row.get("remarks")) if spec.key == "volga" else ([], row.get("remarks"))
    parts = [f"{kind}, список «{spec.title}» ({spec.compiler}, {spec.year})"]
    if spec.key == "volga" and row.get("side"):
        parts.append(SIDES_RU.get(row["side"].upper(), f"сторона — {row['side']}"))
    if row.get("district"):
        parts.append(f"район или группа — {row['district']}")
    if row.get("rayon"):
        parts.append(f"район — {row['rayon']}")
    if row.get("place"):
        parts.append(f"губерния и уезд — {row['place']}")
    if row.get("colony"):
        parts.append(f"поселение — {row['colony']}")
    parts.append(f"основана — {label}" if label else "год основания в списке не указан")
    if faiths:
        parts.append("конфессия — " + ", ".join(faiths))
    if name_ru:
        parts.append(f"русское имя — {name_ru}")
    if row.get("other_names"):
        parts.append(f"другие имена — {row['other_names']}")
    if row.get("aka"):
        parts.append(f"также — {row['aka']}")
    census, population = number(row.get("census")), number(row.get("population"))
    swapped = False
    if census is not None and not 1700 <= census <= HORIZON and \
            population is not None and 1700 <= population <= HORIZON:
        # «105  1926» у Kwasny Kowka: год переписи и население стоят не в
        # своих колонках. Меняются местами с пометкой в `extra`.
        census, population, swapped = population, census, True
    if census and population is not None:
        parts.append(f"население в {census} году — {population}")
    if spec.key == "crimea" and row.get("ref"):
        code = re.match(r"[A-Z]*", row["ref"]).group(0)
        parts.append(f"по: {CRIMEA_REFS.get(code, row['ref'])}")
    if notes:
        parts.append(f"примечание — {notes}")
    if match is not None:
        parts.append("точка — GRSL")
    summary = "; ".join(parts) + "."

    if lat is None:
        confidence = CONFIDENCE_NO_COORDS
    elif year_from is None:
        confidence = CONFIDENCE_NO_DATE
    elif year_from > HORIZON:
        confidence = CONFIDENCE_AFTER_HORIZON
    else:
        confidence = "ok"

    extra = {
        "list": spec.key,
        "line": row.get("_line"),
        "name_de": name,
        "name_ru": name_ru,
        "other_names": row.get("other_names"),
        "aka": row.get("aka"),
        "district": row.get("district"),
        "rayon": row.get("rayon"),
        "side": row.get("side"),
        "place": row.get("place"),
        "colony": row.get("colony"),
        "area": row.get("area"),
        "religion_raw": row.get("religion"),
        "religions": faiths or None,
        "census_year": census,
        "population": population,
        "census_columns_swapped": True if swapped else None,
        "refs": refs or (row.get("ref") and [row["ref"]]) or None,
        "remarks": notes,
        "grsl": match.uid if match else None,
        "grsl_match": how,
        "grsl_candidate": candidate.uid if candidate else None,
        "grsl_candidate_year": candidate.year if candidate else None,
        "grsl_year": match.year if match and match.year != info["year"] else None,
    }
    rec = COLONY_LISTS.new_record(
        title=title,
        category=f"{kind}: {spec.area}",
        lat=lat, lon=lon,
        place_text="; ".join(v for v in (row.get("district"), row.get("place"),
                                          row.get("colony"), spec.area) if v),
        year_from=year_from, year_to=year_to,
        date_precision=precision, date_approx=approx,
        period_raw=period_raw,
        work=f"{spec.title} ({spec.compiler}, {spec.year})",
        summary=summary,
        url=spec.url,
        source_id=f"odessa3:{spec.file}:{row.get('_line')}",
        confidence=confidence,
        extra={k: v for k, v in extra.items() if v not in (None, "", [])},
    )
    if lat is None:
        rec.region = region_of(row, spec)
    return rec


def records(texts: dict[str, str], grsl: Optional[GrslIndex] = None) -> list[ContextRecord]:
    out = []
    for spec in LISTS:
        if spec.key in texts:
            out.extend(row_to_record(row, spec, grsl) for row in parse_list(texts[spec.key], spec))
    return out


def match_counts(recs: Iterable[ContextRecord]) -> Counter:
    return Counter((r.extra.get("list"), r.extra.get("grsl_match")) for r in recs)


# --- сеть ---------------------------------------------------------------------


def fetch_lists(cache: Path, *, refresh: bool = False, pause: float = 1.5) -> dict[str, str]:
    """Четыре файла списков; кэш в `cache`, повтор на сбое — три попытки."""
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for spec in LISTS:
        path = cache / spec.file
        if path.exists() and not refresh:
            out[spec.key] = path.read_bytes().decode("latin-1")
            continue
        for attempt in range(3):
            try:
                data = fetch_bytes(spec.url, error=Odessa3Error, timeout=120)
                break
            except Odessa3Error:
                if attempt == 2:
                    raise
                time.sleep(10 * (attempt + 1))
        path.write_bytes(data)
        out[spec.key] = data.decode("latin-1")
        time.sleep(pause)
    return out
