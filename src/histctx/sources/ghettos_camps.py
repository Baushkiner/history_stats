"""Гетто, лагеря и места заключения 1933–1945 годов: точки USHMM, даты ZRBG и BEG.

Зачем этот слой. Запись «родился в 1938 году в местечке Ляховичи», а после
1941 года о семье ни строки; справка «содержался в шталаге 352»; анкета
репатрианта «был в лагере в Клооге». Все три объясняются одним вопросом:
было ли в этом месте гетто или лагерь, и когда — когда его открыли и когда
ликвидировали. Слой оккупации (`occupation_cities`) отвечает, когда пришёл
противник; сожжённые деревни (`burned_villages_by`) — что стало с деревней;
этот слой — что стало с людьми, которых собрали в гетто или лагерь.

Три источника (проход 04.11.2026, `docs/DISCOVERY.md`):

* **Карта «Энциклопедии лагерей и гетто» USHMM** (`sources/ushmm.py`) —
  основа: 3 598 мест в пяти томах, точка, тип, страна. CC BY-NC-ND 4.0;
  берутся факты и ссылка на карту, тексты статей нет. Дат в данных карты нет.
* **Перечень гетто ZRBG** на 01.08.2014 (`sources/zrbg.py`) — даты открытия
  и ликвидации гетто до дня, 2 238 записей. Права не выяснены: место и даты
  со ссылкой.
* **Перечень концлагерей по § 42 Abs. 2 BEG** (`sources/beg_camps.py`) —
  сроки концлагерей SS и их внешних команд, 1 233 места. Официальный текст,
  охраной не пользуется.

Сведение.

* **Гетто ← ZRBG.** Гетто карты (т. II и гетто т. III) и места т. III на
  Украине и в Молдавии — лагеря Транснистрии, которые ZRBG тоже считает
  гетто, — сводятся с записями перечня по написанию ключом `name_key`
  (латиница без диакритики, «sz»/«ш»/«sch» → «s» и т. п.). Ступени:
  главное название ZRBG против главного названия карты; любой вариант ZRBG
  против главного; против вариантов карты в скобках; без уточнений («nad
  Bugiem», «Litewski»); одна правка в написании (румынские формы
  Транснистрии: «Acmecetca» карты — «Acmicecta» ZRBG) — последняя только
  там, где сведение потом проверяется по территории. Страна сверяется, если
  ZRBG её называет (`zrbg.territory_countries`); на земле бывшего СССР
  единственный кандидат берётся и в соседней стране — перечень и карта
  расходятся на границах (Kuldiga у ZRBG в «Generalbezirk Litauen»).
  Несколько кандидатов разводят область в скобках карты, центр нынешней
  области из «heute Gebiet X» (по GeoNames), гетто вместо лагеря при нём,
  Украина для дистрикта Галиция.
* **Проверка по территории.** У записи ZRBG есть территория — нынешняя
  область или дистрикт, генеральный округ, Транснистрия — с центром и
  радиусом (`TERRITORY_CENTERS`). Точка карты вне радиуса, а город-тёзка
  GeoNames от 20 000 жителей в нём — ошибка точки карты, сведение остаётся;
  тёзки-города нет — ложное сведение, запись ZRBG отвязывается от места
  (Radomysl nad Sanem из дистрикта Краков — не житомирский Радомышль) и
  становится своей записью.
* **Лагеря SS ← BEG.** Места т. I сводятся с записями перечня BEG: полное
  название с номером или уточнением («Breslau I», «Riga, Balastdamm» =
  «Riga (Balastdamm)»); место и уточнение среди частей карты; отсылки
  «siehe» (Majdanek → «Lublin Main Camp (Majdanek)»); написание места;
  части карты, называющие само место («Riese / Dörnhau»). Страна — по земле
  перечня.
* **Несколько записей на одно место** (два номера ZRBG, мужской и женский
  лагерь BEG) — даты по крайним. **Запись ZRBG «не гетто в смысле закона»**
  дат не даёт, но остаётся пометкой у места карты.
* **Как надёжно.** Способ сведения записан в `extra["date_match"]`, номера
  записей и их даты — в `extra["zrbg"]` и `extra["beg"]`.

Даты, которых нет. Даты не выдумываются. Месту, которому перечни дат не дали,
ставится **граница периода** — и это видно: `date_approx = True`, точность
`era` (граница эпохи, а не дата места), `extra["date_source"] = "рамка
оккупации"`, `"рамка войны"` или `"рамка тома"`, исходник — в `period_raw`:

* в рамке РИ/СССР — годы оккупации города из слоя `occupation_cities`, если
  его точка не дальше 15 км (у Фастова — 1941–1943); иначе годы оккупации
  территории: СССР — 1941–1944, Латвия — 1941–1945 (Курляндия до мая
  1945 года), Польша — 1939–1945; Калининградская область — Восточная
  Пруссия, Германия до 1945 года, — рамка войны 1939–1945;
* у записи ZRBG без точки — по её территории (`ZRBG_TERRITORY_FRAMES`):
  Галиция, Белосток, рейхскомиссариаты, Транснистрия — 1941–1944,
  Генерал-губернаторство и аннексированные земли Польши — 1939–1945;
* вне рамки — рамка тома энциклопедии: т. I — 1933–1945 (ранние лагеря
  открыты в 1933 году), остальные — 1939–1945.

У перечня, который назвал только один конец («bis 8.4.1945», «ab
15.9.1943», «? — 21.08.1942»), второй конец берётся из той же рамки с
точностью `open` — как открытый срок в остальных слоях проекта. Даты ZRBG,
совпадающие с правовыми (начало гетто «по распоряжениям», общие даты
Транснистрии и Венгрии, см. `zrbg.RULE_DATES`), идут с `date_approx`.

Записи без пары. Запись BEG или ZRBG, которой нет на карте (Белжец, Собибор,
Треблинка, Малый Тростенец — т. VI на карту не выложен; гетто, которых нет в
энциклопедии), не теряется: она становится своей записью. Точка — GeoNames
из слоя `settlements`, если место с таким написанием в стране и в пределах
территории записи одно (или все тёзки не дальше 10 км друг от друга):
`confidence = "name_match"` — точка подобрана по названию и может оказаться
тёзкой. Неразведённая запись (подходят два места карты) тоже становится
своей записью: если оба места в одном городе («Riga-Strasdenhof») — с их
точкой и `place_level`, иначе без точки. Записи без точки: `no_coords`,
если по тексту место в рамке, `outside_bbox` — если нет (Силезия, Венгрия).

Проверка точек. Точка карты сверяется с GeoNames по названию и стране; ближе
15 км — подпись в заголовок: русское название из справочника «Освобождение
городов» (слой `occupation_cities`, точка не дальше 5 км), иначе название
GeoNames, если оно кириллицей. `coord_suspect` ставится, если точку
опровергает территория ZRBG (см. выше) или — для гетто т. II без
подтверждающей территории ZRBG не шире 250 км — если тёзка GeoNames в стране
один, это город от 20 000 жителей, точка от него дальше 50 км, а в названии
карты нет области в скобках. Точка не исправляется, расстояние и тёзка — в
`extra["geonames_far"]` (Барановичи стоят в 273 км от города, Слоним — в 78).

Рамка — полигоны `frame.py`: Царство Польское и земли СССР в рамке, Краков,
Германия, Франция — нет; что вне рамки, помечается `outside_bbox` и
остаётся. Губерния 1897 года — по точке. Персоналий в слое нет: ни списков
узников, ни имён из примечаний.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..geo import haversine_km
from ..schema import SCOPE_POINT, ContextRecord, LayerSpec, clean_text
from . import beg_camps, ushmm, zrbg

LICENSE = (
    "точки и типы — CC BY-NC-ND 4.0 (USHMM Encyclopedia of Camps and Ghettos, факты "
    "и ссылка на карту, тексты статей не копируются); даты гетто — перечень ZRBG "
    "Deutsche Rentenversicherung, права не выяснены (место и даты со ссылкой); даты "
    "концлагерей — перечень § 42 BEG, официальный текст (§ 5 UrhG)"
)

GHETTOS_CAMPS = LayerSpec(
    slug="ghettos_camps",
    title="Гетто, лагеря и места заключения 1933–1945 годов",
    group="military",
    source=("USHMM Encyclopedia of Camps and Ghettos, 1933–1945 (карта на Project MUSE, "
            "т. I–V); ZRBG Ghetto-Liste на 01.08.2014; Verzeichnis der "
            "Konzentrationslager … gemäß § 42 Abs. 2 BEG"),
    license=LICENSE,
    url=ushmm.MAP_URL,
    status="harvested",
    # Замер сборки 04.11.2026: 3 598 мест карты, 982 записи ZRBG и 556 записей
    # BEG без пары (в том числе неразведённые).
    expected_rows=5136,
    description=(
        "Гетто, концлагеря и их подлагеря, лагеря военнопленных вермахта и другие места "
        "заключения 1933–1945 годов: точка и тип — по карте энциклопедии USHMM, даты "
        "открытия и ликвидации гетто — по перечню ZRBG, сроки концлагерей — по перечню "
        "§ 42 BEG; где дат нет, — годы оккупации места с пометкой. Отвечает, было ли в "
        "местечке гетто или лагерь и когда его открыли и ликвидировали."
    ),
)

SHORT_LICENSE = {
    "ushmm": "CC BY-NC-ND 4.0 (USHMM): факты и ссылка",
    "zrbg": "даты — перечень ZRBG, права не выяснены: факты и ссылка",
    "beg": "сроки — перечень § 42 BEG, официальный текст (§ 5 UrhG)",
}
SOURCE_NAMES = {
    "ushmm": "USHMM Encyclopedia of Camps and Ghettos (карта, Project MUSE)",
    "zrbg": "ZRBG Ghetto-Liste (DRV), на 01.08.2014",
    "beg": "Verzeichnis der Konzentrationslager (§ 42 Abs. 2 BEG)",
}

# Рамки, когда дат нет (см. шапку модуля).
TERRITORY_FRAMES = {
    "Poland": (1939, 1945), "Latvia": (1941, 1945),
    "Russia": (1941, 1944), "Ukraine": (1941, 1944), "Belarus": (1941, 1944),
    "Lithuania": (1941, 1944), "Estonia": (1941, 1944), "Moldova": (1941, 1944),
    "Finland": (1941, 1944),
}
VOLUME_FRAMES = {1: (1933, 1945), 2: (1939, 1945), 3: (1939, 1945), 4: (1939, 1945),
                 5: (1939, 1945)}
WAR_FRAME = (1939, 1945)
DATE_ZRBG, DATE_BEG = "ZRBG", "BEG"
DATE_OCCUPATION, DATE_WAR, DATE_VOLUME = "рамка оккупации", "рамка войны", "рамка тома"

CITY_FRAME_KM = 15.0        # точка города из occupation_cities — не дальше
GEONAMES_NEAR_KM = 15.0     # русская подпись — если GeoNames не дальше
GEONAMES_FAR_KM = 50.0      # дальше — точка под сомнением
TOWN_MIN_POP = 20_000
EVIDENCE_MAX_RADIUS = 250.0  # территория ZRBG не шире — годится в подтверждение точки
PLACE_CLUSTER_KM = 10.0     # тёзки ближе — одно место

CONF_SUSPECT = "coord_suspect"
CONF_NAME_MATCH = "name_match"

WORK_GPW = "Великая Отечественная война"
WORK_WW2 = "Вторая мировая война"
WORK_NAZI = "нацистский режим в Германии"


# --- ключ названия ------------------------------------------------------------

_CYR = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e",
    "є": "ie", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ў": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "iu", "я": "ia",
})
_LAT = str.maketrans({
    "ł": "l", "ß": "ss", "đ": "d", "ø": "o", "æ": "ae", "œ": "oe", "ı": "i",
    "š": "sh", "ž": "zh", "č": "ch", "ş": "sh", "ș": "sh", "ţ": "ts", "ț": "ts",
    "ż": "zh", "ź": "z", "ő": "o", "ű": "u",
})
_DIGRAPHS = (("tsch", "ch"), ("sch", "sh"), ("szcz", "shch"), ("cz", "ch"), ("sz", "sh"),
             ("rz", "r"), ("shch", "sc"), ("kh", "h"), ("ch", "c"), ("sh", "s"),
             ("zh", "z"), ("ts", "c"), ("tz", "c"), ("w", "v"), ("y", "i"), ("j", "i"),
             ("x", "ks"), ("q", "k"))


def name_key(name: Optional[str]) -> str:
    """Ключ сравнения написаний: «Baranowicze», «Baranovichi», «Барановичи» → один.

    Кириллица переводится в латиницу, диакритика снимается, польские,
    немецкие, румынские и литовские сочетания сводятся к одному виду, затем
    ключ огрубляется: «kh» → «h», «ch» → «c», «y» и «j» → «i», «w» → «v»,
    удвоенные буквы — одна. Польское «rz» читается как «r» — так оно
    передаётся по-русски («Korzec» — Корец), румынское «-ca» — как «-ka»
    («Balanovca» = «Balanovka»). Огрубление нарочно грубое: тёзок разводят
    страна и расстояние, а не ключ.
    """
    if not name:
        return ""
    s = name.lower().replace("’", "").replace("'", "").replace("ʹ", "").replace("`", "")
    s = s.translate(_CYR).translate(_LAT)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    for a, b in _DIGRAPHS:
        s = s.replace(a, b)
    words = re.findall(r"[a-z0-9]+", s)
    words = [re.sub(r"ca$", "ka", w) for w in words]
    s = " ".join(words)
    return re.sub(r"([a-z])\1+", r"\1", s)


def compact(key: str) -> str:
    return key.replace(" ", "")


# Уточнения при названии: предлоги с хвостом («nad Bugiem», «an der Weichsel»),
# прилагательные («Litewski», «Kujawska», «Shevchenkovskii») и «Stary»,
# «Wielki», «Mały». Ключ без них — последняя ступень сведения, только при
# сверке страны и единственном кандидате.
_PREPOSITIONS = {"nad", "pod", "an", "am", "bei", "near", "na", "kolo", "koło", "u", "w"}
_SIZE_WORDS = {"stary", "staryi", "stara", "stare", "staraia", "staroe", "old", "wielki",
               "wielka", "wielkie", "velikii", "velikaia", "maly", "mały", "mala", "mała",
               "male", "małe", "malyi", "malaia", "port"}
_RE_ADJ = re.compile(r"(?:sk|ck|zk)(?:i|ii|y|yi|a|aia|aja|e|ie|oe|oie)$|(?:ski|ska|skie)$")


def core_key(name: Optional[str]) -> str:
    """Ключ названия без уточнений: «Brześć Litewski» и «Brest Litovsk» → «bresc»/«brest»."""
    if not name:
        return ""
    words = re.split(r"[\s\-]+", name.strip())
    for i, w in enumerate(words):
        if i > 0 and w.lower() in _PREPOSITIONS:
            words = words[:i]
            break
    words = [w for w in words if w.lower() not in _SIZE_WORDS] or words
    while len(words) > 1 and _RE_ADJ.search(words[-1].lower()):
        words = words[:-1]
    return compact(name_key(" ".join(words)))


# --- названия карты -------------------------------------------------------------

_RE_PAREN = re.compile(r"\(([^()]*)\)")
# «Dondangen I and II», «Gleiwitz IV», «Vivikonna OT» — номер лагеря и «OT»
# (организация Тодта) к названию места не относятся.
_RE_NUMERALS = re.compile(r"\s+(?:I{1,3}|IV|V|VI{0,3}|OT)(?:\s+and\s+(?:I{1,3}|IV|V|VI{0,3}))?"
                          r"(?=[\s,/]|$)")
_REGION_WORDS = re.compile(r"oblast|raion|rayon|kreis|gebiet|county|district|okrug", re.I)


def ushmm_names(name: str) -> tuple[str, list[str], list[str]]:
    """Название карты — главное, части для сравнения и полные варианты.

    «Kauen Main Camp (Kaunas, Kovno, Kowno, Slobodka)» → главное «Kauen»,
    части [Kauen, Kaunas, Kovno, Kowno, Slobodka], полные [«Kauen»,
    «Kauen Kaunas», …]; «Riga (Balastdamm)» → части [Riga, Balastdamm],
    полные [«Riga», «Riga Balastdamm»]; «Radom (Radom (Szkolna Street))» —
    вложенные скобки раскрываются; «Gomel’ (Vitebsk Oblast’)» — скобка с
    областью в части не идёт; «Riga - Kaiserwald» даёт и «Riga», и полное
    «Riga - Kaiserwald»; «Breslau I» — полное и с номером, и без.
    """
    main, heads, inner, full = _ushmm_split(name)
    return main, list(dict.fromkeys(heads + inner)), full


def ushmm_regions(name: str) -> set[str]:
    """Области из скобок карты: «Gomel’ (Vitebsk Oblast’)» → {«vitebsk»}."""
    out = set()
    for m in _RE_PAREN.finditer(name):
        if _REGION_WORDS.search(m.group(1)):
            words = [w for w in name_key(m.group(1)).split()
                     if not _REGION_WORDS.search(w) and w not in ("oblast", "obl")]
            if words:
                out.add("".join(words))
    return out


def ushmm_specific(name: str) -> list[str]:
    """Части, которые называют само место, а не головной лагерь: скобки и всё
    после «/» или « - » («Riese / Dörnhau» → Dörnhau, «Kottern / Fischen» →
    Fischen, но не Kottern)."""
    _, heads, inner, _ = _ushmm_split(name)
    return list(dict.fromkeys(heads[1:] + inner))


def _ushmm_split(name: str) -> tuple[str, list[str], list[str], list[str]]:
    inner = []
    outer = name
    while "(" in outer and _RE_PAREN.search(outer):
        for m in _RE_PAREN.finditer(outer):
            for piece in re.split(r",|\bor\b|\band\b|\bwith\b|\bincl\.", m.group(1)):
                piece = clean_text(re.sub(r"^\s*(?:the|and|with)\s+", "", piece)) or ""
                if piece and not _REGION_WORDS.search(piece) and not piece[0].islower():
                    inner.append(piece)
        outer = _RE_PAREN.sub(" ", outer)
    outer = clean_text(outer.replace("(", " ").replace(")", " ")) or name
    outer = clean_text(re.sub(r"\b(?:Main Camp|Subcamp|Complex)\b", " ", outer)) or outer
    numbered = outer
    outer = clean_text(_RE_NUMERALS.sub(" ", outer)) or outer
    heads = [clean_text(p) or "" for p in re.split(r",|\band\b|\s[-/]\s|/", outer)]
    heads = [_RE_NUMERALS.sub(" ", h).strip() for h in heads]
    heads = [h for h in heads if h and not re.fullmatch(r"(?:I{1,3}|IV|V|VI{0,3})", h)]
    for h in list(heads):
        if h.startswith("Port "):
            heads.append(h[5:])
    main = heads[0] if heads else outer
    full = list(dict.fromkeys([main, outer, numbered] + [f"{main} {p}" for p in inner]))
    return main, heads, inner, full


# --- GeoNames -----------------------------------------------------------------------

@dataclass(frozen=True)
class GeoPlace:
    gid: str
    title: str          # русское название (слой settlements)
    lat: float
    lon: float
    country: str        # по-русски, как в слое settlements
    population: int


def geonames_index(features: Iterable[dict], variants: Optional[dict] = None
                   ) -> dict[str, list[GeoPlace]]:
    """Слой `settlements` и указатель написаний — места по ключу `name_key`."""
    out: dict[str, list[GeoPlace]] = defaultdict(list)
    variants = variants or {}
    for feat in features:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        gid = str(props.get("source_id") or "")
        if len(coords) < 2 or not gid:
            continue
        extra = props.get("extra") or {}
        place = GeoPlace(gid=gid, title=props.get("title") or "", lat=float(coords[1]),
                         lon=float(coords[0]), country=extra.get("country") or "",
                         population=int(extra.get("population_modern") or 0))
        names = [place.title, extra.get("name_latin")]
        names += (variants.get(gid) or {}).get("names") or []
        for k in {compact(name_key(n)) for n in names if n}:
            if k:
                out[k].append(place)
    return dict(out)


def geonames_candidates(index: dict, names: Iterable[str],
                        countries: Iterable[str]) -> list[GeoPlace]:
    """Места GeoNames с тем же ключом в названных странах (страны — как у карты)."""
    allowed = {ushmm.COUNTRY_RU.get(c, c) for c in countries}
    seen, out = set(), []
    for n in names:
        for p in index.get(compact(name_key(n)), ()):
            if p.gid not in seen and (not allowed or p.country in allowed):
                seen.add(p.gid)
                out.append(p)
    return out


def single_place(cands: list[GeoPlace]) -> Optional[GeoPlace]:
    """Одно место: единственный кандидат или тёзки не дальше 10 км (берётся больший)."""
    if not cands:
        return None
    best = max(cands, key=lambda p: p.population)
    if all(haversine_km(best.lat, best.lon, p.lat, p.lon) <= PLACE_CLUSTER_KM for p in cands):
        return best
    return None


@dataclass
class GeoCheck:
    """Сверка точки карты с GeoNames."""

    near: Optional[GeoPlace] = None     # тот же ключ, не дальше GEONAMES_NEAR_KM
    near_km: Optional[float] = None
    far: Optional[GeoPlace] = None      # тёзка, к которому точка, видимо, и относится
    far_km: Optional[float] = None
    reason: Optional[str] = None        # чем подтверждено сомнение
    candidates: int = 0


def _plausible(p: GeoPlace) -> bool:
    """Место GeoNames там, где могли быть гетто и лагеря: Польша или земля
    бывшего СССР западнее линии наибольшего продвижения противника (как в
    слое оккупации) — Татарск под Новосибирском тёзкой смоленского не будет."""
    from .occupation import EAST_ZONE, WEST_ZONE, in_zone
    if p.country in ("Польша", "Финляндия"):
        return True
    return in_zone(p.lat, p.lon, WEST_ZONE) or in_zone(p.lat, p.lon, EAST_ZONE)


def _qualified(name: str) -> bool:
    """В скобках названия карты — область («Gomel’ (Vitebsk Oblast’)»): это тёзка."""
    return any(_REGION_WORDS.search(m.group(1)) for m in _RE_PAREN.finditer(name))


def place_candidates(index: dict, place: ushmm.Place) -> list[GeoPlace]:
    main, parts, _ = ushmm_names(place.name)
    cands = geonames_candidates(index, [main], [place.country])
    if not cands:
        cands = geonames_candidates(index, parts, [place.country])
    return [p for p in cands if _plausible(p)]


def check_point(index: dict, place: ushmm.Place, *, confirmed: bool = False) -> GeoCheck:
    """Тёзки GeoNames в той же стране: ближний даёт подпись, дальний — сомнение.

    Без свидетельства ZRBG сомнение ставится только гетто т. II (они стоят в
    городах и местечках), если тёзка один, это город от 20 000 жителей,
    точка карты от него дальше 50 км, а в названии карты нет области в
    скобках: у деревень тёзок слишком много. Если территория записи ZRBG не
    шире 250 км и точка карты в ней (`confirmed`), сомнения нет: Златополь
    карты лежит в дистрикте Кировоград, а не там, где харьковский тёзка.
    Свидетельство территории проверяет `territory_check` уже после сведения.
    """
    if place.lat is None:
        return GeoCheck()
    cands = place_candidates(index, place)
    out = GeoCheck(candidates=len(cands))
    if not cands:
        return out
    dist = sorted(((haversine_km(place.lat, place.lon, p.lat, p.lon), p) for p in cands),
                  key=lambda t: t[0])
    d0, p0 = dist[0]
    if d0 <= GEONAMES_NEAR_KM:
        out.near, out.near_km = p0, round(d0, 1)
    elif d0 > GEONAMES_FAR_KM and not confirmed and place.volume == 2 \
            and not _qualified(place.name) and single_place(cands) is not None \
            and max(p.population for p in cands) >= TOWN_MIN_POP:
        out.far, out.far_km = p0, round(d0, 1)
        out.reason = "единственный город с этим названием в стране"
    return out


# Центры территорий ZRBG и радиус, в котором лежат их места: страховка от
# ложного сведения и проверка точки карты.
TERRITORY_CENTERS = (
    (r"Galizien", 49.84, 24.03, 250.0, "Дистрикт Галиция"),
    (r"Distrikt\s+Krakau", 50.06, 19.94, 260.0, "Дистрикт Краков"),
    (r"Distrikt\s+Lublin", 51.25, 22.57, 180.0, "Дистрикт Люблин"),
    (r"Distrikt\s+Radom|Bezirk\s+Radom", 51.40, 21.15, 190.0, "Дистрикт Радом"),
    (r"Distrikt\s+Warschau", 52.23, 21.01, 180.0, "Дистрикт Варшава"),
    (r"Bialystok|Białystok", 53.13, 23.16, 200.0, "Белостокский округ"),
    (r"Zichenau", 52.88, 20.62, 130.0, "округ Цеханув"),
    (r"Wartheland|Warthegau", 52.0, 18.5, 230.0, "Вартеланд"),
    (r"Oberschlesien", 50.3, 19.0, 160.0, "Верхняя Силезия"),
    (r"Generalbezirk\s+Litauen", 55.0, 24.0, 260.0, "генеральный округ Литва"),
    (r"Lettland|Kurland", 56.9, 24.6, 280.0, "генеральный округ Латвия"),
    (r"Estland", 58.8, 25.5, 280.0, "генеральный округ Эстония"),
    (r"Weißruth|Weissruth", 53.9, 27.56, 340.0, "генеральный округ Белоруссия"),
    (r"Wolhynien", 50.6, 26.25, 260.0, "генеральный округ Волынь-Подолия"),
    (r"Transnistr", 47.9, 29.4, 270.0, "Транснистрия"),
    (r"Bessarabien", 47.0, 28.8, 230.0, "Бессарабия"),
    (r"Bukowina", 48.3, 25.9, 160.0, "Буковина"),
    # области и генеральные округа военных лет на Украине — когда нет «heute»
    (r"Kirovograd|Kirowograd", 48.51, 32.26, 200.0, "Кировоград"),
    (r"Nikolajew|Nikolaev|Mykolajiw", 46.97, 32.0, 230.0, "Николаев"),
    (r"Shitomir|Zhitomir|Schytomyr|Shytomir", 50.25, 28.66, 230.0, "Житомир"),
    (r"Dnjepropetrowsk|Dnipropetrowsk|Dnepropetrovsk", 48.46, 35.04, 230.0, "Днепропетровск"),
    (r"Poltawa|Poltava", 49.59, 34.55, 200.0, "Полтава"),
    (r"Charkow|Charkiv|Charkiw|Kharkov", 49.99, 36.23, 200.0, "Харьков"),
    (r"Stalino|Donezk|Donets", 48.0, 37.8, 200.0, "Сталино"),
    (r"Winniza|Winnyzja|Vinnitsa", 49.23, 28.47, 230.0, "Винница"),
    (r"Kamenez-Podol|Kamjanez-Podil|Kamenets-Podol|Proskurow", 49.42, 27.0, 200.0,
     "Каменец-Подольский"),
    (r"Tschernigow|Tschernigiw|Chernigov", 51.5, 31.3, 200.0, "Чернигов"),
    (r"\bKiew\b|Kyjiw|Kiev", 50.45, 30.52, 230.0, "Киев"),
    (r"Krim|Crimea|Taurien", 45.0, 34.1, 230.0, "Крым"),
)


def territory_center(index: dict, e: zrbg.Entry) -> Optional[tuple]:
    """(широта, долгота, радиус, подпись) — по области «heute Gebiet X» или территории."""
    center = region_center(index, e.region_today, e.countries)
    if center is not None:
        return center.lat, center.lon, REGION_RADIUS_KM, f"нынешняя область ({center.title})"
    for pattern, lat, lon, radius, label in TERRITORY_CENTERS:
        if re.search(pattern, e.territory):
            return lat, lon, radius, label
    return None


def territory_check(index: dict, place: ushmm.Place, e: zrbg.Entry
                    ) -> tuple[bool, Optional[GeoPlace], Optional[str]]:
    """Сходится ли точка карты с территорией записи ZRBG.

    (оставить сведение, тёзка GeoNames для сомнения, пояснение). Точка в
    радиусе территории — всё хорошо. Точка далеко, а тёзка GeoNames в радиусе
    есть — ошибка точки карты (Барановичи стоят в 273 км от города):
    сведение остаётся, точка получает сомнение. Ошибкой точки это считается,
    только если тёзка — город от 20 000 жителей: деревня-тёзка в радиусе
    скорее говорит о другом месте с тем же названием. Иначе — ложное
    сведение: запись ZRBG отвязывается от места (Radomysl nad Sanem из
    дистрикта Краков — не житомирский Радомышль).
    """
    center = territory_center(index, e)
    if center is None or place.lat is None:
        return True, None, None
    lat, lon, radius, label = center
    if haversine_km(place.lat, place.lon, lat, lon) <= radius:
        return True, None, None
    near = [p for p in place_candidates(index, place)
            if haversine_km(p.lat, p.lon, lat, lon) <= radius
            and p.population >= TOWN_MIN_POP]
    if near:
        best = max(near, key=lambda p: p.population)
        return True, best, f"по перечню ZRBG место лежит в пределах: {label}"
    return False, None, f"точка карты вне пределов «{label}» из перечня ZRBG"


# --- рамки оккупации ----------------------------------------------------------------

@dataclass(frozen=True)
class CityFrame:
    city: str
    uid: str
    year_from: int
    year_to: int
    lat: float
    lon: float
    raw: str


OCCUPATION_CATEGORIES = ("оккупация", "частичная оккупация", "оккупация без даты освобождения")


def occupation_frames(features: Iterable[dict]) -> list[CityFrame]:
    """Периоды оккупации городов из `occupation_cities.geojson` — по городу один.

    Город, переходивший из рук в руки, даёт несколько записей; рамка — от
    первой оккупации до последнего освобождения. Взятые города Восточной
    Пруссии и освобождения без даты оккупации рамки не дают.
    """
    by_city: dict[str, list[dict]] = defaultdict(list)
    for feat in features:
        props = feat.get("properties") or {}
        if props.get("category") not in OCCUPATION_CATEGORIES:
            continue
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2 or props.get("year_from") is None:
            continue
        city = props.get("place_text") or props.get("title") or ""
        by_city[f"{city}|{coords[0]:.4f}|{coords[1]:.4f}"].append(
            dict(props, lon=float(coords[0]), lat=float(coords[1])))
    out = []
    for items in by_city.values():
        first = min(items, key=lambda p: p["year_from"])
        ext = [p.get("extra") or {} for p in items]
        occ = min((e.get("occupied") for e in ext if e.get("occupied")), default=None)
        lib = max((e.get("liberated") for e in ext if e.get("liberated")), default=None)
        raw = f"оккупация {first.get('place_text')}: {_ru_date(occ)} — {_ru_date(lib)}"
        if len(items) > 1:
            raw += f" ({len(items)} периода)" if len(items) < 5 else f" ({len(items)} периодов)"
        out.append(CityFrame(city=first.get("place_text") or "", uid=first.get("uid") or "",
                             year_from=min(p["year_from"] for p in items),
                             year_to=max(p["year_to"] for p in items),
                             lat=first["lat"], lon=first["lon"], raw=raw))
    return out


def nearest_city(frames: list[CityFrame], lat: float, lon: float
                 ) -> tuple[Optional[CityFrame], Optional[float]]:
    best, best_d = None, None
    for f in frames:
        if abs(f.lat - lat) > 0.2 or abs(f.lon - lon) > 0.35:
            continue
        d = haversine_km(lat, lon, f.lat, f.lon)
        if d <= CITY_FRAME_KM and (best_d is None or d < best_d):
            best, best_d = f, d
    return best, (round(best_d, 1) if best_d is not None else None)


def is_kaliningrad(lat: float, lon: float) -> bool:
    return 54.2 <= lat <= 55.4 and 19.5 <= lon <= 23.0


def _ru_date(iso: Optional[str]) -> str:
    if not iso:
        return "?"
    y, m, d = (iso.split("-") + [None, None])[:3]
    if d:
        return f"{int(d)}.{int(m):02d}.{y}"
    if m:
        return f"{int(m):02d}.{y}"
    return y


# --- сведение: гетто и ZRBG ----------------------------------------------------------

def zrbg_target(place: ushmm.Place) -> bool:
    """Место карты, к которому ищутся даты ZRBG: гетто и лагеря Транснистрии."""
    return place.is_ghetto or (place.volume == 3 and place.country in ("Ukraine", "Moldova"))


@dataclass
class Match:
    """Итог сведения места карты с записями перечня."""

    entries: list = field(default_factory=list)
    how: str = ""
    ambiguous: list = field(default_factory=list)   # ключи тех, с кем не развелось


def _tiers(cands_by_tier: list[tuple[str, list]], countries: set, *, relax: bool,
           narrow: Optional[Callable[[list, str], tuple[list, str]]] = None
           ) -> tuple[list, str]:
    """Первая ступень, давшая одного кандидата.

    Ступень с несколькими кандидатами сначала сужается (`narrow`: область,
    главный лагерь, гетто вместо лагеря при нём); не сузилась — сведение
    идёт на следующую ступень, а если и там нет единственного, возвращается
    первый неразведённый набор (это «неоднозначно»). Страна сверяется, а при
    `relax` и без сверки ищется единственный кандидат на земле бывшего СССР.
    """
    first_multi: tuple[list, str] = ([], "")
    for how, pool in cands_by_tier:
        cands = _pick(pool, countries)
        how = how + (", страна сверена" if countries else ", страна не названа")
        if len(cands) > 1 and narrow:
            cands, how = narrow(cands, how)
        if len(cands) == 1:
            return cands, how
        if cands and not first_multi[0]:
            first_multi = (cands, how)
    if first_multi[0]:
        return first_multi
    if relax:
        for how, pool in cands_by_tier:
            cands = [p for p in _pick(pool, set()) if p.country in ushmm.FORMER_USSR]
            if len(cands) > 1 and narrow:
                cands, how = narrow(cands, how)
            if len(cands) == 1:
                return cands, how + ", страна соседняя (перечень и карта расходятся)"
    return [], ""


# Области ZRBG, которые не названы по своему центру: «Gebiet Wolyn» — центр Луцк.
REGION_CENTERS = {
    "wolyn": "Lutsk", "volyn": "Lutsk", "wolhynien": "Lutsk", "krim": "Simferopol",
    "crimea": "Simferopol", "zakarpattya": "Uzhhorod", "lodzkie": "Lodz",
    "małopolskie": "Krakow", "malopolskie": "Krakow", "slaskie": "Katowice",
    "śląskie": "Katowice", "kujawsko-pomorskie": "Bydgoszcz", "stalino": "Donetsk",
    "kamjanez-podilskyj": "Khmelnytskyi", "kamenets-podolski": "Khmelnytskyi",
    "kamenez": "Khmelnytskyi", "vilniaus": "Vilnius", "vilna": "Vilnius",
}
REGION_RADIUS_KM = 250.0


def region_center(index: dict, region: Optional[str],
                  countries: Iterable[str] = ()) -> Optional[GeoPlace]:
    """Центр нынешней области из «heute Gebiet X» — крупнейшее место GeoNames с
    этим названием в странах записи и в полосе, где были гетто."""
    if not region:
        return None
    name = re.split(r"[\s(\[]", region.strip())[0].strip(" ,.;")
    name = REGION_CENTERS.get(name.lower().replace("’", "").replace("'", ""), name)
    allowed = {ushmm.COUNTRY_RU.get(c, c) for c in countries}
    cands = [p for p in index.get(compact(name_key(name)), ())
             if p.population >= 20_000 and (not allowed or p.country in allowed)
             and _plausible(p)]
    return max(cands, key=lambda p: p.population) if cands else None


def _near_center(cands: list, center: Optional[GeoPlace]) -> list:
    if center is None:
        return cands
    return [p for p in cands if p.lat is not None and
            haversine_km(p.lat, p.lon, center.lat, center.lon) <= REGION_RADIUS_KM]


def near_keys(key: str, keys: Iterable[str]) -> list[str]:
    """Ключи на расстоянии одной правки (замена, вставка, удаление) — для
    ключей от семи букв: «acmecetka» (Acmecetca карты) и «acmicetka»
    (Acmicecta ZRBG)."""
    if len(key) < 7:
        return []
    out = []
    for k in keys:
        if abs(len(k) - len(key)) > 1 or len(k) < 7 or k == key:
            continue
        if _one_edit(key, k):
            out.append(k)
    return out


def _one_edit(a: str, b: str) -> bool:
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if a == b[:i] + b[i + 1:]:
            return True
    return False


def match_zrbg(places: list[ushmm.Place], entries: list[zrbg.Entry],
               geo_index: Optional[dict] = None
               ) -> tuple[dict[str, Match], list[zrbg.Entry], list[tuple]]:
    """Записи ZRBG — к местам карты.

    Возвращает {ключ места: Match}, записи ZRBG без пары и неоднозначные
    (запись, ключи мест-кандидатов). Ступени: главное название ZRBG против
    главного названия карты; любой вариант ZRBG против главного; любой
    вариант против любой части карты; то же без уточнений («nad Bugiem»,
    «Litewski», `core_key`). Страна сверяется, если ZRBG её называет; если
    ни одна ступень со сверкой не дала пары, а место и запись на земле
    бывшего СССР, берётся единственный кандидат без сверки — на границе
    Белоруссии, России и Прибалтики перечень и карта иногда расходятся
    (Kuldiga у ZRBG в «Generalbezirk Litauen»). При нескольких кандидатах
    решает область из скобок карты («Vitebsk Oblast’») против «heute Gebiet
    Vitebsk».
    """
    targets = [p for p in places if zrbg_target(p)]
    by_main: dict[str, list] = defaultdict(list)
    by_part: dict[str, list] = defaultdict(list)
    by_core: dict[str, list] = defaultdict(list)
    for p in targets:
        main, parts, _ = ushmm_names(p.name)
        by_main[compact(name_key(main))].append(p)
        for part in parts:
            by_part[compact(name_key(part))].append(p)
            by_core[core_key(part)].append(p)
    out: dict[str, Match] = {}
    unmatched, ambiguous = [], []
    for e in entries:
        keys = [k for k in (compact(name_key(n)) for n in e.names) if k]
        cores = [k for k in (core_key(n) for n in e.names) if k]
        if not keys:
            unmatched.append(e)
            continue
        tiers = [
            ("главное название", by_main.get(keys[0], [])),
            ("вариант написания ZRBG", [p for k in keys for p in by_main.get(k, [])]),
            ("вариант написания карты", [p for k in keys for p in by_part.get(k, [])]),
            ("название без уточнений", [p for k in cores for p in by_core.get(k, [])]),
        ]
        if e.countries and territory_center(geo_index or {}, e) is not None:
            # Одна правка — только там, где сведение потом проверят по
            # территории: «Bratslav» Транснистрии не станет белорусским Браславом.
            tiers.append(("написание с одной правкой",
                          [p for k in keys for nk in near_keys(k, by_part) for p in by_part[nk]]))
        relax = not e.countries or bool(e.countries & ushmm.FORMER_USSR)
        center = region_center(geo_index or {}, e.region_today, e.countries)

        def narrow(cands: list, how: str, e=e, center=center) -> tuple[list, str]:
            if e.region:
                region = compact(name_key(e.region))
                named = [p for p in cands if region and region in ushmm_regions(p.name)]
                if named:
                    cands, how = named, how + ", область в названии карты"
            if len(cands) > 1 and center is not None:
                near = _near_center(cands, center)
                if near:
                    cands, how = near, how + f", область ({center.title})"
            if len(cands) > 1:
                ghettos = [p for p in cands if p.is_ghetto]
                if len(ghettos) == 1:
                    cands, how = ghettos, how + ", гетто, а не лагерь при нём"
            if len(cands) > 1 and re.search(r"Galizien", e.territory):
                ukr = [p for p in cands if p.country == "Ukraine"]
                if len(ukr) == 1:
                    cands, how = ukr, how + ", Галиция — Украина"
            return cands, how

        cands, how = _tiers(tiers, e.countries, relax=relax, narrow=narrow)
        if not cands:
            unmatched.append(e)
            continue
        if len(cands) > 1:
            ambiguous.append((e, [p.key for p in cands]))
            for p in cands:
                out.setdefault(p.key, Match()).ambiguous.append(e.key)
            continue
        m = out.setdefault(cands[0].key, Match())
        m.entries.append(e)
        if not m.how:
            m.how = f"ZRBG: {how}"
    return out, unmatched, ambiguous


def _pick(pool: list, countries: set) -> list:
    seen, out = set(), []
    for p in pool:
        if p.key in seen:
            continue
        if countries and p.country not in countries:
            continue
        seen.add(p.key)
        out.append(p)
    return out


# --- сведение: лагеря SS и BEG -----------------------------------------------------------

BEG_REGION_COUNTRIES = {
    "East Prussia": {"Russia", "Poland", "Lithuania"},
    "Czechia": {"Czechia", "Czech Republic"},
}
NEAR_COUNTRIES = {
    "Minsk": "Belarus", "Riga": "Latvia", "Warschau": "Poland", "Lublin": "Poland",
    "Kauen": "Lithuania", "Kaunas": "Lithuania", "Litzmannstadt": "Poland", "Lodz": "Poland",
    "Krakau": "Poland", "Lemberg": "Ukraine", "Kiew": "Ukraine", "Reval": "Estonia",
    "Tallin": "Estonia", "Narwa": "Estonia",
}


def beg_countries(e: beg_camps.Entry) -> set[str]:
    """Нынешние государства записи BEG — по земле после косой черты или по «bei …»."""
    if e.region:
        c = beg_camps.REGIONS.get(e.region)
        if c:
            return set(BEG_REGION_COUNTRIES.get(c, {c}))
    for word in (e.near, e.place):
        for city, country in NEAR_COUNTRIES.items():
            if word and re.search(rf"\b{city}\b", word):
                return {country}
    return set()


def _beg_keys(e: beg_camps.Entry) -> tuple[list[str], list[str]]:
    """(полные ключи, написания без номера лагеря).

    Полные — место с уточнением («Riga Balastdamm»), а у записи без уточнения
    ещё и сами написания с номером («Breslau I»): голое «Bremen» у записи
    «Bremen, Borgwardwerke» подходит к любому лагерю Бремена.
    """
    full = []
    if e.detail:
        full.append(compact(name_key(f"{e.place} {e.detail}")))
    else:
        full += [compact(name_key(n)) for n in e.names]
    names = [re.sub(r"\s+(?:I{1,3}|IV|V)$", "", n) for n in e.names]
    return ([k for k in dict.fromkeys(full) if k],
            [k for k in dict.fromkeys(compact(name_key(n)) for n in names) if k])


def _detail_hit(detail_key: str, place: ushmm.Place) -> bool:
    """Уточнение перечня среди частей карты: равно или одно содержит другое
    («Präzifix» — «Präzifix GmbH», «Pollnhof» — «Gut Pollnhof»)."""
    if len(detail_key) < 4:
        return False
    for part in ushmm_specific(place.name):
        k = compact(name_key(part))
        if k == detail_key or (min(len(k), len(detail_key)) >= 5
                               and (detail_key in k or k in detail_key)):
            return True
    return False


def match_beg(places: list[ushmm.Place], entries: list[beg_camps.Entry]
              ) -> tuple[dict[str, Match], list[beg_camps.Entry], list[tuple]]:
    """Записи BEG — к местам т. I.

    Ступени: полное название — написание с номером лагеря или место с
    уточнением («Breslau I» = «Breslau I», «Riga, Balastdamm» = «Riga
    (Balastdamm)»); место и уточнение среди частей карты; отсылки «siehe»
    против полных названий и скобок карты (Majdanek → «Lublin Main Camp
    (Majdanek)»); написание места против главного названия карты; написание
    против частей, которые называют само место («Riese / Dörnhau» —
    Dörnhau, но «Kottern / Fischen» — не Kottern). На первой ступени из
    нескольких кандидатов записи без уточнения достаётся место карты без
    скобок («Königsberg», а не «Königsberg (Neumark)»); главной записи
    перечня (без главного лагеря) — главный лагерь карты. Страна сверяется
    по земле перечня; на земле бывшего СССР — как у ZRBG, с соседней страной
    для единственного кандидата (Narva у карты — Россия, у перечня — Эстония).
    """
    targets = [p for p in places if p.is_ss_camp]
    by_full: dict[str, list] = defaultdict(list)
    by_main: dict[str, list] = defaultdict(list)
    by_spec: dict[str, list] = defaultdict(list)
    for p in targets:
        main, parts, full = ushmm_names(p.name)
        for f in full:
            by_full[compact(name_key(f))].append(p)
        by_main[compact(name_key(main))].append(p)
        for part in ushmm_specific(p.name):
            by_spec[compact(name_key(part))].append(p)
    out: dict[str, Match] = {}
    unmatched, ambiguous = [], []
    for e in entries:
        if e.is_reference:
            continue
        countries = beg_countries(e)
        full_keys, name_keys = _beg_keys(e)
        alias_keys = [k for k in (compact(name_key(a)) for a in e.aliases) if k]
        place_key = compact(name_key(re.sub(r"\s+(?:I{1,3}|IV|V)$", "", e.place)))
        detail_key = compact(name_key(e.detail)) if e.detail else ""
        tiers = [
            ("полное название", [p for k in full_keys for p in by_full.get(k, [])]),
            ("место и уточнение", [p for p in by_main.get(place_key, [])
                                   if detail_key and _detail_hit(detail_key, p)]),
            ("отсылка «siehe»", [p for k in alias_keys
                                 for p in by_full.get(k, []) + by_spec.get(k, [])]),
            ("написание места", [p for k in name_keys for p in by_main.get(k, [])]),
            ("написание в скобках карты", [p for k in name_keys for p in by_spec.get(k, [])]),
        ]
        relax = bool(countries & ushmm.FORMER_USSR)

        def narrow(cands: list, how: str, e=e) -> tuple[list, str]:
            if how.startswith("полное") and not e.detail:
                bare = [p for p in cands if len(ushmm_names(p.name)[1]) == 1]
                if len(bare) == 1:
                    return bare, how + ", место карты без уточнения"
            if not e.main_camp:
                heads = [p for p in cands if p.subtype == "Main Camp"]
                if len(heads) == 1:
                    return heads, how + ", главный лагерь"
            return cands, how

        cands, how = _tiers(tiers, countries, relax=relax, narrow=narrow)
        if not cands:
            unmatched.append(e)
            continue
        if len(cands) > 1:
            ambiguous.append((e, [p.key for p in cands]))
            for p in cands:
                out.setdefault(p.key, Match()).ambiguous.append(e.key)
            continue
        m = out.setdefault(cands[0].key, Match())
        m.entries.append(e)
        if not m.how:
            m.how = f"BEG: {how.replace('страна', 'земля')}"
    return out, unmatched, ambiguous


# --- даты записи ------------------------------------------------------------------------

@dataclass
class Dating:
    year_from: Optional[int]
    year_to: Optional[int]
    precision: str
    approx: bool
    raw: str
    source: str
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Frame:
    """Рамка на случай, когда перечни дат не дали: годы, вид, исходник."""

    year_from: int
    year_to: int
    kind: str           # DATE_OCCUPATION | DATE_WAR | DATE_VOLUME
    raw: str
    extra: tuple = ()


def place_frame(*, inside: Optional[bool], country: Optional[str], lat: Optional[float],
                lon: Optional[float], volume: Optional[int],
                cities: list[CityFrame]) -> Frame:
    """Рамка места: оккупация города, оккупация территории, война или том."""
    if inside and lat is not None and lon is not None:
        if country == "Russia" and is_kaliningrad(lat, lon):
            return Frame(1939, 1945, DATE_WAR,
                         "рамка войны: Восточная Пруссия, Германия до 1945 года, 1939–1945")
        city, km = nearest_city(cities, lat, lon)
        if city:
            return Frame(city.year_from, city.year_to, DATE_OCCUPATION,
                         f"рамка: {city.raw} (слой occupation_cities, {km} км)",
                         (("city", city.city), ("uid", city.uid), ("km", km)))
    if inside and country in TERRITORY_FRAMES:
        a, b = TERRITORY_FRAMES[country]
        where = ushmm.COUNTRY_RU.get(country, country)
        return Frame(a, b, DATE_OCCUPATION, f"рамка оккупации территории: {where}, {a}–{b}")
    if volume in VOLUME_FRAMES:
        a, b = VOLUME_FRAMES[volume]
        return Frame(a, b, DATE_VOLUME, f"рамка тома {volume} энциклопедии USHMM: {a}–{b}")
    a, b = WAR_FRAME
    return Frame(a, b, DATE_WAR, f"рамка войны: {a}–{b}")


def city_label(frame: Frame, place: ushmm.Place) -> Optional[str]:
    """Русское название из справочника «Освобождение городов», если точка
    рядом и название то же («Гомель», а не «Гомел» из GeoNames)."""
    extra = dict(frame.extra)
    city = extra.get("city")
    if not city or (extra.get("km") or 99) > 5:
        return None
    modern = re.findall(r"\(([^()]+)\)", city)
    names = [re.sub(r"\s*\([^()]*\)", "", city)] + modern
    main, parts, _ = ushmm_names(place.name)
    keys = {compact(name_key(p)) for p in parts}
    for n in names:
        if compact(name_key(n)) in keys:
            return n.strip()
    return None


def frame_dating(frame: Frame) -> Dating:
    return Dating(frame.year_from, frame.year_to, "era", True, frame.raw, frame.kind,
                  {"date_frame": dict(frame.extra)} if frame.extra else {})


_PREC_ORDER = ("day", "month", "year")


def zrbg_dating(entries: list[zrbg.Entry], frame: Frame) -> Optional[Dating]:
    """Даты гетто по записям ZRBG; None — если у записей дат нет."""
    usable = [e for e in entries if e.dated
              and not (e.flags.get("not_ghetto") or e.flags.get("no_evidence"))]
    if not usable:
        return None
    opens = [e.opened for e in usable if e.opened]
    liqs = [e.liquidated for e in usable if e.liquidated]
    days = opens + liqs
    approx = any(d.approx for d in days) or any(e.rule for e in usable)
    precision = max((d.precision for d in days), key=_PREC_ORDER.index)
    years = [d.year for d in days]
    extra: dict = {}
    if opens and liqs:
        y0, y1 = min(o.year for o in opens), max(x.year for x in liqs)
        if min(o.iso() for o in opens) > max(x.iso() for x in liqs) or y0 > y1:
            # дата открытия позже ликвидации — ошибка перечня: интервал по крайним
            y0, y1, approx = min(years), max(years), True
            extra["dates_inverted"] = True
    elif liqs:
        y0, y1, precision = min(frame.year_from, min(years)), max(years), "open"
    else:
        y0, y1, precision = min(years), max(frame.year_to, max(years)), "open"
    raw = "; ".join(f"ZRBG № {e.nr or '—'}: {e.opened_raw or '?'} — {e.liquidated_raw or '?'}"
                    for e in usable)
    if precision == "open":
        raw += f"; второй конец — {frame.raw}"
    return Dating(y0, y1, precision, approx, raw, DATE_ZRBG, extra)


def beg_dating(entries: list[beg_camps.Entry], frame: Frame) -> Optional[Dating]:
    """Сроки по записям BEG; None — если сроков нет ни у одной."""
    with_periods = [e for e in entries if e.periods]
    if not with_periods:
        return None
    starts, ends = [], []
    start_known = end_known = True
    for e in with_periods:
        s, t, sk, ek = e.interval()
        start_known &= sk
        end_known &= ek
        if s:
            starts.append(s)
        if t:
            ends.append(t)
    y0 = min(s.year for s in starts) if start_known else min(
        [frame.year_from] + [s.year for s in starts])
    y1 = max(t.year for t in ends) if end_known else max(
        [frame.year_to] + [t.year for t in ends])
    precision = "day" if start_known and end_known else "open"
    raw = "; ".join(f"BEG № {e.nr}: " + ", ".join(p.raw + (f" ({p.note})" if p.note else "")
                                                for p in e.periods) for e in with_periods)
    if precision == "open":
        raw += f"; второй конец — {frame.raw}"
    return Dating(y0, y1, precision, False, raw, DATE_BEG)


def work_for(country: Optional[str], year_from: Optional[int], year_to: Optional[int]) -> str:
    if year_to is not None and year_to < 1939:
        return WORK_NAZI
    if country in ushmm.FORMER_USSR and year_from is not None and year_from >= 1941:
        return WORK_GPW
    return WORK_WW2


# --- записи ----------------------------------------------------------------------------

FramePlace = Callable[[float, float], tuple]   # (lat, lon) → (в рамке, губерния, по берегу)


def _zrbg_extra(e: zrbg.Entry) -> dict:
    d = {"nr": e.nr, "names": e.names[:6], "territory": e.territory,
         "opened": e.opened.iso() if e.opened else None,
         "liquidated": e.liquidated.iso() if e.liquidated else None,
         "rule_dates": e.rule or None, "deportations": e.deportations,
         "source": e.source, "page": e.page}
    flags = {k: v for k, v in e.flags.items() if k != "several_numbers"}
    if flags:
        d["flags"] = flags
    return {k: v for k, v in d.items() if v not in (None, [], "")}


def _beg_extra(e: beg_camps.Entry) -> dict:
    d = {"nr": e.nr, "text": e.text, "main_camp": e.main_camp,
         "periods": [[p.start.isoformat() if p.start else None,
                      p.end.isoformat() if p.end else None, p.note] for p in e.periods]
         or None}
    if not e.periods:
        d["presumed"] = "§ 2 Abs. 3 6. DV-BEG: существовало 01.11.1943 (правовая презумпция)"
    return {k: v for k, v in d.items() if v not in (None, [], "")}


def _fmt_day(d: Optional[zrbg.Day]) -> str:
    return _ru_date(d.iso()) if d else "?"


def _dating_phrase(dating: Dating) -> str:
    if dating.source == DATE_ZRBG:
        return f"даты по перечню ZRBG: {dating.extra.get('phrase', '')}".rstrip(": ")
    if dating.source == DATE_BEG:
        return f"сроки по перечню § 42 BEG: {dating.extra.get('phrase', '')}".rstrip(": ")
    return (f"дат в источниках нет — годы {dating.year_from}–{dating.year_to} взяты из "
            f"рамки ({dating.raw.split(': ', 1)[-1]})")


def _zrbg_phrase(entries: list[zrbg.Entry]) -> str:
    bits = []
    for e in entries:
        if not e.dated:
            continue
        s = f"открыто {_fmt_day(e.opened)}, ликвидировано {_fmt_day(e.liquidated)}"
        if e.rule:
            which = " и ".join({"opened": "открытия", "liquidated": "ликвидации"}[w]
                               for w in e.rule)
            s += f" (дата {which} — правовая, по распоряжениям для всей территории)"
        bits.append(s)
    return "; ".join(dict.fromkeys(bits))


def _beg_phrase(entries: list[beg_camps.Entry]) -> str:
    bits = []
    for e in entries:
        for p in e.periods:
            a = p.start.strftime("%d.%m.%Y") if p.start else "?"
            b = p.end.strftime("%d.%m.%Y") if p.end else "?"
            bits.append(f"{a} — {b}" + (f" ({p.note})" if p.note else ""))
    return "; ".join(bits)


def place_record(place: ushmm.Place, *, frame_place: Optional[FramePlace], geo: GeoCheck,
                 cities: list[CityFrame], zm: Optional[Match] = None,
                 bm: Optional[Match] = None,
                 spec: LayerSpec = GHETTOS_CAMPS) -> ContextRecord:
    """Место карты (с датами перечней, если сведено) — запись схемы."""
    inside = province = None
    shore = False
    if place.lat is not None and frame_place is not None:
        inside, province, shore = frame_place(place.lat, place.lon)
    frame = place_frame(inside=inside, country=place.country, lat=place.lat, lon=place.lon,
                        volume=place.volume, cities=cities)
    zentries = zm.entries if zm else []
    bentries = bm.entries if bm else []
    dating = None
    if zentries:
        dating = zrbg_dating(zentries, frame)
        if dating:
            dating.extra["phrase"] = _zrbg_phrase(zentries)
    if dating is None and bentries:
        dating = beg_dating(bentries, frame)
        if dating:
            dating.extra["phrase"] = _beg_phrase(bentries)
    if dating is None:
        dating = frame_dating(frame)

    ru = city_label(frame, place) or (russian_label(geo.near.title) if geo.near else None)
    title = f"{place.name} ({ru})" if ru else place.name
    cat = ushmm.category(place)
    country_ru = ushmm.COUNTRY_RU.get(place.country, place.country)

    used = ["ushmm"] + (["zrbg"] if zentries else []) + (["beg"] if bentries else [])
    extra: dict = {
        "ushmm": {"volume": place.volume, "id": place.pid, "type": place.type,
                  "subtype": place.subtype if place.subtype not in ushmm.EMPTY_SUBTYPES
                  else None, "country": place.country},
        "date_source": dating.source,
    }
    extra["ushmm"] = {k: v for k, v in extra["ushmm"].items() if v is not None}
    if place.approximate:
        extra["location"] = "приблизительная (USHMM: Approximate Location)"
    if place.notes:
        extra["ushmm"]["notes"] = place.notes
    if zm and zm.how and zentries:
        extra["date_match"] = zm.how
    elif bm and bm.how and bentries:
        extra["date_match"] = bm.how
    if zentries:
        extra["zrbg"] = [_zrbg_extra(e) for e in zentries]
        not_ghetto = [e for e in zentries if e.flags.get("not_ghetto") or
                      e.flags.get("no_evidence")]
        if not_ghetto:
            extra["zrbg_not_ghetto"] = [e.nr for e in not_ghetto]
    if bentries:
        extra["beg"] = [_beg_extra(e) for e in bentries]
    for m, key in ((zm, "zrbg_ambiguous"), (bm, "beg_ambiguous")):
        if m and m.ambiguous:
            extra[key] = sorted(set(m.ambiguous))
    extra.update({k: v for k, v in dating.extra.items() if k != "phrase"})
    if geo.near:
        extra["geonames"] = {"id": geo.near.gid, "name": geo.near.title, "km": geo.near_km}
    if geo.far:
        extra["geonames_far"] = {"id": geo.far.gid, "name": geo.far.title, "km": geo.far_km,
                                 "why": geo.reason}
    if shore:
        extra["frame"] = "по берегу"

    if place.lat is None:
        confidence = "no_coords"
    elif inside is False:
        confidence = "outside_bbox"
    elif geo.far:
        confidence = CONF_SUSPECT
    elif place.approximate:
        confidence = "place_level"
    else:
        confidence = "ok"

    summary = f"{cat[:1].upper() + cat[1:]} ({ushmm.VOLUME_RU[place.volume]} энциклопедии USHMM)"
    summary += f"; {_dating_phrase(dating)}."
    if extra.get("zrbg_not_ghetto"):
        summary += " Перечень ZRBG считает, что гетто в смысле закона здесь не было."
    if geo.far:
        summary += (f" Точка карты в {geo.far_km:g} км от места GeoNames «{geo.far.title}» "
                    f"({geo.reason}) — координата под сомнением, не исправлена.")
    if place.approximate:
        summary += " Точка приблизительная."

    return spec.new_record(
        title=title,
        category=cat,
        lat=place.lat, lon=place.lon,
        scope=SCOPE_POINT,
        place_text=f"{place.name}, {country_ru}",
        region=province,
        year_from=dating.year_from, year_to=dating.year_to,
        date_precision=dating.precision, date_approx=dating.approx,
        period_raw=dating.raw,
        work=work_for(place.country, dating.year_from, dating.year_to),
        summary=summary,
        url=ushmm.place_url(place),
        source="; ".join(SOURCE_NAMES[s] for s in used),
        source_id=place.key,
        license="; ".join(SHORT_LICENSE[s] for s in used),
        confidence=confidence,
        extra=extra,
    )


_RE_CYRILLIC = re.compile(r"^[А-ЯЁЇІЄҐЎа-яёїієґў\s\-’'()]+$")


def russian_label(title: Optional[str]) -> Optional[str]:
    """Подпись GeoNames годится в заголовок, только если она кириллицей."""
    return title if title and _RE_CYRILLIC.match(title) else None


# Земли ZRBG без точки, которые по тексту лежат в рамке: земля бывшего СССР
# целиком или польские дистрикты, вышедшие из Царства Польского и Белостока.
# Краков, Вартеланд, Верхняя Силезия, Данциг — в рамке лишь частью, и без
# точки запись идёт как «вне рамки».
_RE_ZRBG_FRAME_PL = re.compile(r"Warschau|Radom|Lublin|Bialystok|Białystok|Zichenau|Galizien")


def zrbg_frame_hint(e: zrbg.Entry) -> bool:
    if not e.countries:
        return False
    if e.countries <= ushmm.FORMER_USSR:
        return True
    if e.countries <= ushmm.FORMER_USSR | {"Poland"}:
        return bool(_RE_ZRBG_FRAME_PL.search(e.territory))
    return False


# Рамка записи ZRBG без точки — по территории перечня: Галиция, Белосток,
# рейхскомиссариаты и Транснистрия — с лета 1941 года, Генерал-губернаторство
# и аннексированные земли Польши — с осени 1939-го.
ZRBG_TERRITORY_FRAMES = (
    (r"Lettland|Kurland", 1941, 1945, "генеральный округ Латвия"),
    (r"Galizien", 1941, 1944, "дистрикт Галиция"),
    (r"Bialystok|Białystok", 1941, 1944, "Белостокский округ"),
    (r"Ostland|Weißruth|Weissruth|Litauen|Estland", 1941, 1944, "рейхскомиссариат «Остланд»"),
    (r"Reichskommiss?ariat\s+Ukr|Wolhynien|Ukraine", 1941, 1944, "рейхскомиссариат «Украина»"),
    (r"Transnistr", 1941, 1944, "Транснистрия"),
    (r"Bessarabien|Bukowina", 1941, 1944, "Бессарабия и Буковина"),
    (r"Russland|Rußland", 1941, 1944, "оккупированная территория РСФСР"),
    (r"Generalg[ou]+vernement|Distrikt|Wartheland|Warthegau|Oberschlesien|Danzig|Zichenau|"
     r"Ostpreußen|Polen", 1939, 1945, "оккупированная Польша"),
)


def zrbg_territory_frame(e: zrbg.Entry) -> Optional[Frame]:
    for pattern, a, b, label in ZRBG_TERRITORY_FRAMES:
        if re.search(pattern, e.territory):
            kind = DATE_OCCUPATION if zrbg_frame_hint(e) else DATE_WAR
            return Frame(a, b, kind, f"рамка оккупации территории: {label}, {a}–{b}")
    return None


def cluster_point(candidates: list) -> Optional[ushmm.Place]:
    """Место карты, если все кандидаты неразведённого сведения — один город
    (точки не дальше 10 км): у записи будет его точка с `place_level`."""
    pts = [c for c in candidates if c.lat is not None]
    if not pts or len(pts) != len(candidates):
        return None
    if all(haversine_km(pts[0].lat, pts[0].lon, c.lat, c.lon) <= PLACE_CLUSTER_KM for c in pts):
        return pts[0]
    return None


def _candidates_note(candidates: list) -> str:
    names = "; ".join(dict.fromkeys(f"{c.name} ({ushmm.COUNTRY_RU.get(c.country, c.country)})"
                                    for c in candidates))
    return f" С местами карты USHMM не развелось — подходят: {names}."


def zrbg_record(e: zrbg.Entry, *, geo_index: dict, frame_place: Optional[FramePlace],
                cities: list[CityFrame], candidates: Optional[list] = None,
                spec: LayerSpec = GHETTOS_CAMPS) -> ContextRecord:
    """Запись ZRBG без пары на карте — своя запись, точка по GeoNames, если одна.

    `candidates` — места карты, между которыми сведение не выбрало: если они
    в одном городе, запись берёт их точку (`place_level`), иначе точки нет.
    """
    point = None
    anchor = cluster_point(candidates) if candidates else None
    if e.countries and not candidates:
        cands = [p for p in geonames_candidates(geo_index, e.names, e.countries)
                 if _plausible(p)]
        center = territory_center(geo_index, e)
        if center is not None:
            lat0, lon0, radius, _ = center
            cands = [p for p in cands if haversine_km(p.lat, p.lon, lat0, lon0) <= radius]
        point = single_place(cands)
    lat, lon = (point.lat, point.lon) if point else (None, None)
    if anchor is not None:
        lat, lon = anchor.lat, anchor.lon
    inside = province = None
    if lat is not None and frame_place is not None:
        inside, province, _ = frame_place(lat, lon)
    frame_hint = zrbg_frame_hint(e)
    country = next(iter(e.countries)) if len(e.countries) == 1 else None
    if point is not None:
        country = {v: k for k, v in ushmm.COUNTRY_RU.items()}.get(point.country, country)
    if anchor is not None:
        country = anchor.country
    located = point is not None or anchor is not None
    frame = place_frame(inside=inside if located else (frame_hint or None),
                        country=country if (located or frame_hint) else None,
                        lat=lat, lon=lon, volume=None, cities=cities)
    if not located:
        frame = zrbg_territory_frame(e) or frame
    dating = zrbg_dating([e], frame) if not (e.flags.get("not_ghetto") or
                                             e.flags.get("no_evidence")) else None
    if dating is None:
        dating = frame_dating(frame)
    else:
        dating.extra["phrase"] = _zrbg_phrase([e])

    if e.flags.get("no_evidence"):
        cat = "гетто не подтверждено (по перечню ZRBG)"
    elif e.flags.get("not_ghetto") and e.flags.get("not_ghetto_kind"):
        cat = e.flags["not_ghetto_kind"] + " (по перечню ZRBG — не гетто)"
    elif e.flags.get("not_ghetto"):
        cat = "не гетто в смысле закона (по перечню ZRBG)"
    elif e.flags.get("open_ghetto"):
        cat = "открытое гетто (по перечню ZRBG)"
    else:
        cat = "гетто (по перечню ZRBG)"
    label = russian_label(point.title) if point else None
    title = f"{e.name} ({label})" if label else e.name

    extra: dict = {"zrbg": [_zrbg_extra(e)], "date_source": dating.source}
    extra.update({k: v for k, v in dating.extra.items() if k != "phrase"})
    if candidates:
        extra["ushmm_candidates"] = [c.key for c in candidates]
    if anchor is not None:
        extra["coord_source"] = f"точка места карты {anchor.key}: все кандидаты в одном городе"
    elif point:
        extra["coord_source"] = f"GeoNames {point.gid} «{point.title}»: по названию"
    if not located:
        confidence = "no_coords" if frame_hint else "outside_bbox"
        if not frame_hint:
            extra["frame_by"] = "по территории в перечне (точки нет)"
    elif inside is False:
        confidence = "outside_bbox"
    else:
        confidence = "place_level" if anchor is not None else CONF_NAME_MATCH

    summary = f"{cat[:1].upper() + cat[1:]}: запись № {e.nr or '—'} перечня ZRBG, " \
              f"территория — {e.territory or 'не указана'}"
    summary += f"; {_dating_phrase(dating)}."
    if e.deportations:
        summary += f" Депортации по перечню: {e.deportations}."
    if candidates:
        summary += _candidates_note(candidates)
        if anchor is not None:
            summary += " Все они в одном городе — точка взята оттуда."
    elif point:
        summary += " Точка — место GeoNames с тем же названием: может оказаться тёзкой."
    else:
        summary += " На карте энциклопедии USHMM места нет, точки у записи нет."

    return spec.new_record(
        title=title,
        category=cat,
        lat=lat, lon=lon,
        place_text="; ".join(x for x in (e.place_raw, e.territory) if x),
        region=province,
        year_from=dating.year_from, year_to=dating.year_to,
        date_precision=dating.precision, date_approx=dating.approx,
        period_raw=dating.raw,
        work=work_for(country, dating.year_from, dating.year_to),
        summary=summary,
        url=f"{zrbg.PDF_URL}#page={e.page}",
        source=SOURCE_NAMES["zrbg"],
        source_id=e.key,
        license=zrbg.LICENSE,
        confidence=confidence,
        extra=extra,
    )


def beg_record(e: beg_camps.Entry, *, geo_index: dict, frame_place: Optional[FramePlace],
               cities: list[CityFrame], candidates: Optional[list] = None,
               spec: LayerSpec = GHETTOS_CAMPS) -> ContextRecord:
    """Запись BEG без пары на карте — своя запись, точка по GeoNames для рамки.

    `candidates` — места т. I, между которыми сведение не выбрало («Riga-
    Strasdenhof, Widzemer Chaussee» — к двум лагерям Страсденхофа): если они
    в одном городе, запись берёт их точку с `place_level`.
    """
    countries = beg_countries(e)
    frame_hint = e.frame_hint
    names = [re.sub(r"\s+(?:I{1,3}|IV|V)$", "", n) for n in e.names + e.aliases]
    anchor = cluster_point(candidates) if candidates else None
    point = single_place([p for p in geonames_candidates(geo_index, names, countries)
                          if _plausible(p)]) \
        if countries and frame_hint and not candidates else None
    lat, lon = (point.lat, point.lon) if point else (None, None)
    if anchor is not None:
        lat, lon = anchor.lat, anchor.lon
        countries = {anchor.country}
    located = point is not None or anchor is not None
    inside = province = None
    if located and frame_place is not None:
        inside, province, _ = frame_place(lat, lon)
    country = next(iter(countries)) if len(countries) == 1 else None
    frame = place_frame(inside=inside if located else (frame_hint or None), country=country,
                        lat=lat, lon=lon, volume=1, cities=cities)
    dating = beg_dating([e], frame)
    if dating is None:
        dating = frame_dating(frame)
    else:
        dating.extra["phrase"] = _beg_phrase([e])

    cat = (f"внешняя команда концлагеря (главный лагерь — {e.main_camp})" if e.main_camp
           else "концлагерь или место заключения, приравненное к нему (§ 42 BEG)")
    title = e.place + (f", {e.detail}" if e.detail else "")
    if len(e.names) > 1:
        title += f" ({e.names[1]})"
    if point and russian_label(point.title):
        title += f" — {point.title}"

    extra: dict = {"beg": [_beg_extra(e)], "date_source": dating.source}
    extra.update({k: v for k, v in dating.extra.items() if k != "phrase"})
    if candidates:
        extra["ushmm_candidates"] = [c.key for c in candidates]
    if anchor is not None:
        extra["coord_source"] = f"точка места карты {anchor.key}: все кандидаты в одном городе"
    elif point:
        extra["coord_source"] = f"GeoNames {point.gid} «{point.title}»: по названию"
    if not located:
        confidence = "no_coords" if frame_hint else "outside_bbox"
        if not frame_hint:
            extra["frame_by"] = "по тексту перечня (точки нет)"
    elif inside is False:
        confidence = "outside_bbox"
    else:
        confidence = "place_level" if anchor is not None else CONF_NAME_MATCH

    summary = (f"{cat[:1].upper() + cat[1:]}: запись № {e.nr} перечня концлагерей по § 42 "
               f"BEG; {_dating_phrase(dating)}.")
    if not e.periods:
        summary += (" Сроков перечень не называет; по § 2 Abs. 3 инструкции место считается "
                    "существовавшим 01.11.1943 — это правовая презумпция, не дата.")
    if candidates:
        summary += _candidates_note(candidates)
        if anchor is not None:
            summary += " Все они в одном городе — точка взята оттуда."
    else:
        summary += (" Точка — место GeoNames с тем же названием." if point else
                    " На карте энциклопедии USHMM места нет, точки у записи нет.")

    return spec.new_record(
        title=title,
        category=cat,
        lat=lat, lon=lon,
        place_text=e.head[:200],
        region=province,
        year_from=dating.year_from, year_to=dating.year_to,
        date_precision=dating.precision, date_approx=dating.approx,
        period_raw=dating.raw,
        work=work_for(country, dating.year_from, dating.year_to),
        summary=summary,
        url=beg_camps.PAGE_URL,
        source=SOURCE_NAMES["beg"],
        source_id=e.key,
        license=beg_camps.LICENSE,
        confidence=confidence,
        extra=extra,
    )


@dataclass
class Build:
    """Всё собранное: записи и счётчики сведения — для отчёта сборщика."""

    records: list
    zrbg_matched: int = 0
    zrbg_unmatched: list = field(default_factory=list)
    zrbg_ambiguous: list = field(default_factory=list)
    zrbg_rejected: list = field(default_factory=list)     # (запись, место, почему)
    beg_matched: int = 0
    beg_unmatched: list = field(default_factory=list)
    beg_ambiguous: list = field(default_factory=list)
    geo: dict = field(default_factory=dict)


def build_records(places: list[ushmm.Place], zentries: list[zrbg.Entry],
                  bentries: list[beg_camps.Entry], *, geo_index: dict,
                  cities: list[CityFrame], frame_place: Optional[FramePlace]) -> Build:
    zmatch, zun, zamb = match_zrbg(places, zentries, geo_index)
    bmatch, bun, bamb = match_beg(places, bentries)
    by_key = {p.key: p for p in places}
    rejected = []
    evidence: dict[str, tuple] = {}
    confirmed: set[str] = set()
    for key, m in zmatch.items():
        keep = []
        place = by_key[key]
        for e in m.entries:
            ok, far, why = territory_check(geo_index, place, e)
            if ok:
                keep.append(e)
                if far is not None:
                    evidence[key] = (far, why)
                center = territory_center(geo_index, e)
                if far is None and center and center[2] <= EVIDENCE_MAX_RADIUS:
                    confirmed.add(key)
            else:
                rejected.append((e, key, why))
        m.entries = keep
    zun = zun + [e for e, _, _ in rejected]
    records, geo = [], {}
    for p in places:
        check = check_point(geo_index, p, confirmed=p.key in confirmed)
        if p.key in evidence and p.lat is not None:
            far, why = evidence[p.key]
            check.far, check.far_km, check.reason = far, round(
                haversine_km(p.lat, p.lon, far.lat, far.lon), 1), why
            check.near = check.near_km = None
        geo[p.key] = check
        records.append(place_record(p, frame_place=frame_place, geo=check, cities=cities,
                                    zm=zmatch.get(p.key), bm=bmatch.get(p.key)))
    # Записи без пары и неразведённые — своими записями: ничего не теряется.
    for e in zun:
        records.append(zrbg_record(e, geo_index=geo_index, frame_place=frame_place,
                                   cities=cities))
    for e, keys in zamb:
        records.append(zrbg_record(e, geo_index=geo_index, frame_place=frame_place,
                                   cities=cities, candidates=[by_key[k] for k in keys]))
    for e in bun:
        records.append(beg_record(e, geo_index=geo_index, frame_place=frame_place,
                                  cities=cities))
    for e, keys in bamb:
        records.append(beg_record(e, geo_index=geo_index, frame_place=frame_place,
                                  cities=cities, candidates=[by_key[k] for k in keys]))
    return Build(records=records,
                 zrbg_matched=sum(len(m.entries) for m in zmatch.values()),
                 zrbg_unmatched=zun, zrbg_ambiguous=zamb, zrbg_rejected=rejected,
                 beg_matched=sum(len(m.entries) for m in bmatch.values()),
                 beg_unmatched=bun, beg_ambiguous=bamb, geo=geo)


def load_geonames(settlements: Path, variants: Path) -> dict:
    features = json.loads(Path(settlements).read_text(encoding="utf-8"))["features"]
    items = json.loads(Path(variants).read_text(encoding="utf-8")).get("items") or {}
    return geonames_index(features, items)


def load_cities(path: Path) -> list[CityFrame]:
    if not Path(path).exists():
        return []
    return occupation_frames(json.loads(Path(path).read_text(encoding="utf-8"))["features"])


def summary_counts(records: list[ContextRecord]) -> dict[str, Counter]:
    return {
        "confidence": Counter(r.confidence for r in records),
        "date_source": Counter((r.extra or {}).get("date_source") for r in records),
        "precision": Counter(r.date_precision for r in records),
        "category": Counter(r.category for r in records),
    }
