"""Места массовых расстрелов 1941–1944 годов: Yahad – In Unum и атлас Литвы.

Зачем этот слой. Запись в метрической книге или в переписи 1939 года — а
после 1941 года ничего: ни документа о смерти, ни могилы. Для еврейской семьи
местечка это почти всегда расстрел в первые месяцы оккупации, у оврага, в лесу
или у кирпичного завода за околицей. Слой `ghettos_camps` отвечает, было ли в
местечке гетто и когда его ликвидировали; слой `burned_villages_by` — о
сожжённых деревнях Белоруссии. Место самого расстрела — где лежат убитые —
отмечают только люди, которые искали его на месте. Yahad – In Unum с 2004
года опрашивает свидетелей в сёлах Украины, Белоруссии, России, Польши,
Литвы, Молдавии и Латвии и ставит на карту каждое найденное место казни.

Набор 1: карта Yahad – In Unum (`yahadmap.org`). Все точки отдаются одним
ответом на POST `/en/` с телом `search=map&r=1&t=all` — 2 877 точек на
22.11.2026: название села, страна, координата, размер значка (`s`: 1 — до 500
жертв, 2 — от 500 до 10 000, 3 — больше 10 000, так подписана легенда карты) и
пометка `pending` («soon online», 420 точек без профиля). У остальных 2 457
точек — ссылка на профиль села (`#village/<slug>.<N>`, 1 762 профиля; у села
бывает до трёх мест расстрела). Профиль (`/en/?village=<N>`) — заголовок
(«Execution of Jews in Oleksandriya»), число мест казни, таблица «Kind of place
before», «Memorials», «Period of occupation», «Total number of victims»,
выдержки из советских, немецких и польских архивов со ссылкой, свидетельства и
исторический очерк. Поле `date` у точки — год поездки исследователей, а не год
расстрела.

Набор 2: Holocaust Atlas of Lithuania (`holocaustatlas.lt`, Еврейский музей
Вильнюса). 229 мест массовых убийств в `load_markers.js.php?l=EN`: номер,
координата, заголовок и аннотация; по аннотации дата до дня у 95 мест,
месяц — у 72, только год — у 43, у 19 даты нет. С Yahad он сводится: профиль
литовского села сам ссылается на страницу атласа (`item/<номер>`), а
остальные пары ищутся по расстоянию. Сведённое место — одна запись: точка и
число жертв от Yahad, дата расстрела — от атласа, ссылка на оба.

Права. Yahad: «The content of the website may be used for personal,
educational and non-commercial purposes. Any copying or usage of the
copyrighted protected materials without the written permission of the owner
is prohibited» — тексты, снимки и видео под авторским правом. Атлас Литвы
условий не публикует. По условию 3 каталога берутся факты — точка, село,
страна, период оккупации, число жертв (категорией, как написано), вид места,
есть ли памятный знак, дата и шифр акта ЧГК, дата расстрела — и ссылка на
профиль. Свидетельства, выдержки из архивов, очерки и снимки остаются на
сайтах. Имён — ни жертв, ни свидетелей, ни исполнителей — в слое нет.

Где запись во времени. У профиля Yahad — годы периода оккупации села
(«1941-1944»), точность `year`: расстрел лежит внутри них, а дата самого
расстрела живёт в очерке, и из пересказа она не вынимается. У атласа Литвы —
дата из аннотации: одна полная дата — `day`, месяц и год — `month`, только
годы — `year`. Нет ничего — рамка оккупации страны (Украина 1941–1944, Польша
1939–1945 …) с точностью `era` и пометкой `date_approx`, как у гетто без дат в
`ghettos_camps`: запись остаётся в подборе на годы войны и не притворяется
датированной. Дата акта ЧГК — не дата расстрела: она лежит в `extra`.

Где запись на карте. Точка — место расстрела, как его поставили
исследователи. В ответе карты Yahad координата записана «градусами.минутами»
(«50.438240» — 50° 43,824′), и читать её как десятичную нельзя: точка уехала
бы в среднем на 28 км (`map_degrees`). Переведённые, точки ложатся в 1–3 км
от сёл-тёзок GeoNames — расстрел шёл за околицей — и в пределах километра от
мест атласа Литвы, на которые ссылаются профили. Рамка —
`histctx.frame.Frame`: губерния 1897 года внутри губерний, `outside_bbox` у
Галиции, Западной Польши, Румынии и Словакии — запись остаётся в слое.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..geo import haversine_km, valid_coords
from ..net import USER_AGENT, wait_for_pause
from ..schema import ContextRecord, LayerSpec, clean_text

YAHAD_URL = "https://www.yahadmap.org"
YAHAD_MAP = YAHAD_URL + "/en/"
YAHAD_POINTS_BODY = {"search": "map", "r": "1", "t": "all"}
YAHAD_PROFILE = YAHAD_URL + "/en/?village={n}"
YAHAD_PAGE = YAHAD_URL + "/en/#village/{slug}.{n}"
YAHAD_TERMS = YAHAD_URL + "/en/#terms-of-use"

HAL_URL = "http://www.holocaustatlas.lt"
HAL_ROBOTS = HAL_URL + "/robots.txt"
HAL_MARKERS = HAL_URL + "/load_markers.js.php?l=EN"
HAL_ITEM = HAL_URL + "/EN/#a_atlas/search//page/1/item/{id}/"
# robots.txt атласа: `Crawl-delay: 10` (22.11.2026). Запросов к нему два.
HAL_CRAWL_DELAY = 10.0

# Замеры 22.11.2026: расхождение — повод посмотреть, что изменилось.
EXPECTED_POINTS = 2877
EXPECTED_HAL = 229

PAUSE = 1.5

# Пара «точка Yahad — место атласа» без явной ссылки: дальше этого — разные места.
MATCH_KM = 1.5
# С явной ссылкой профиля на страницу атласа — точка атласа может стоять у
# другого рва того же местечка.
LINK_KM = 10.0

LICENSE = (
    "права не выяснены: содержимое Yahad – In Unum под авторским правом, разрешено "
    "некоммерческое образовательное использование; атлас Литвы условий не публикует. "
    "Берутся факты — точка, село, период оккупации, число жертв, вид места, дата и шифр "
    "акта ЧГК — и ссылка на профиль; свидетельства, выдержки, очерки и снимки не копируются"
)

EXECUTION_SITES = LayerSpec(
    slug="execution_sites",
    title="Места массовых расстрелов 1941–1944 годов",
    group="military",
    source="Yahad – In Unum, карта мест казней; Holocaust Atlas of Lithuania",
    license=LICENSE,
    description=(
        "Места массовых расстрелов евреев и рома на оккупированной территории — Украина, "
        "Белоруссия, Россия, Польша, Литва, Латвия, Молдавия: точка, найденная "
        "исследователями со свидетелями, период оккупации села, число жертв, вид места, "
        "есть ли памятный знак, дата и шифр акта ЧГК; в Литве — дата расстрела по атласу."
    ),
    url=YAHAD_MAP,
    status="harvested",
    expected_rows=2931,
)

# Размер значка на карте Yahad — оценка числа жертв по легенде карты.
VICTIM_BANDS = {1: "до 500 жертв", 2: "от 500 до 10 000 жертв", 3: "больше 10 000 жертв"}

# Рамка оккупации страны — для точек без профиля и без периода. Годы — как
# пишет сам Yahad в профилях этих стран («1939-1944» у Польши, «1941 - 1945» у
# Латвии), а у стран без профилей — годы войны на их земле.
OCCUPATION = {
    "Ukraine": (1941, 1944), "Belarus": (1941, 1944), "Russia": (1941, 1944),
    "Lithuania": (1941, 1944), "Latvia": (1941, 1945), "Estonia": (1941, 1944),
    "Moldova": (1941, 1944), "Poland": (1939, 1945), "Romania": (1941, 1944),
    "Slovakia": (1939, 1945),
}
WAR = (1939, 1945)

COUNTRIES_RU = {
    "Ukraine": "Украина", "Belarus": "Белоруссия", "Russia": "Россия", "Poland": "Польша",
    "Lithuania": "Литва", "Latvia": "Латвия", "Estonia": "Эстония", "Moldova": "Молдавия",
    "Romania": "Румыния", "Slovakia": "Словакия",
}

# Вид места до расстрела — короткие подписи профиля. Незнакомое идёт как есть.
PLACE_KINDS = {
    "forest": "лес", "wood": "лес", "woods": "лес", "field": "поле", "fields": "поле",
    "ravine": "овраг", "gully": "овраг", "pit": "яма", "pits": "ямы", "clay pit": "карьер",
    "quarry": "карьер", "sand quarry": "песчаный карьер", "pasture": "пастбище",
    "meadow": "луг", "cemetery": "кладбище", "jewish cemetery": "еврейское кладбище",
    "anti-tank trench": "противотанковый ров", "anti-tank ditch": "противотанковый ров",
    "trench": "ров", "ditch": "ров", "silo": "силосная яма", "well": "колодец",
    "farm": "хутор", "kolkhoz": "колхоз", "garden": "сад", "orchard": "сад",
    "swamp": "болото", "river bank": "берег реки", "riverbank": "берег реки",
    "brickyard": "кирпичный завод", "railroad": "железная дорога", "barracks": "казармы",
    "prison": "тюрьма", "synagogue": "синагога", "park": "парк", "hill": "холм",
    "village": "село", "courtyard": "двор", "bomb crater": "воронка", "shell crater": "воронка",
    "silo pit": "силосная яма", "lime pit": "известковая яма", "cattle pit": "скотомогильник",
    "cattle cemetery": "скотомогильник", "livestock cemetery": "скотомогильник",
    "cattle burial ground": "скотомогильник", "abandoned well": "заброшенный колодец",
    "clay quarry": "глиняный карьер", "sand pit": "песчаный карьер",
    "stone quarry": "каменный карьер", "peat bog": "торфяник", "gravel pit": "карьер",
    "mine shaft": "шахта", "mine": "шахта", "basement": "подвал", "cellar": "подвал",
    "barn": "сарай", "stable": "конюшня", "pigsty": "свинарник", "airfield": "аэродром",
    "stadium": "стадион", "road": "дорога", "bridge": "мост", "river": "река",
    "lake": "озеро", "beach": "берег", "school": "школа", "market": "рынок",
    "center of the village": "центр села", "steppe": "степь", "grove": "роща",
    "hospital": "больница", "factory": "завод", "sawmill": "лесопилка",
    "military base": "военный городок", "fort": "форт", "camp": "лагерь",
}
# Ключи от длинных к коротким: «anti-tank trench» раньше «trench», «jewish
# cemetery» раньше «cemetery».
_PLACE_KEYS = sorted(PLACE_KINDS, key=len, reverse=True)

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_MONTH_RE = "|".join(m.capitalize() for m in _MONTHS)

_RE_VILLAGE = re.compile(r"^#village/(.+)\.(\d+)$")
_RE_NOM = re.compile(r'<span class="nom">(.*?)</span>', re.S)
_RE_REGION = re.compile(r'<span class="region">(.*?)</span>', re.S)
_RE_H2 = re.compile(r"<h2>(.*?)</h2>", re.S)
_RE_NB = re.compile(r'class="nb_sites">\s*(\d+)\s*Killing site', re.S)
_RE_DL = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
_RE_H3 = re.compile(r"<h3>(.*?)</h3>", re.S)
_RE_HAL_LINK = re.compile(r"holocaustatlas\.lt/[^\"']*?/item/(\d+)")
_RE_BRACKET = re.compile(r"\[([^\[\]]{8,400})\]")
# «January 10, 1945», «May 17th, 1945» и «17 May 1945», «6 December, 1944».
_RE_EN_DATE = re.compile(
    rf"\b({_MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})(?!\d)")
_RE_EN_DATE_DMY = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\s*,?\s+(\d{{4}})(?!\d)")
_RE_EN_MONTH_YEAR = re.compile(rf"\b({_MONTH_RE})\s*,?\s+(\d{{4}})(?!\d)")
_RE_YEAR = re.compile(r"(?<!\d)(19[34]\d)(?!\d)")
_RE_YEARS = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
# «1,000», «1 000» и «1.300» — тысячи с разделителем; «150» — просто число.
_RE_NUMBER = re.compile(r"(\d{1,3}(?:[ ,.]\d{3})+(?!\d)|\d+)")
_RE_TAG = re.compile(r"<[^>]+>")
_RE_HAL_ROW = re.compile(
    r"markers\[\d+\]\s*=\s*new Array\((\d+),\s*([-\d.]+),\s*([-\d.]+),\s*\d+,\s*"
    r"'((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)'\);")


class ExecutionSitesError(RuntimeError):
    """Источник не ответил или ответ не такой, какой ждёт разбор."""


def _text(fragment: Optional[str]) -> Optional[str]:
    if fragment is None:
        return None
    return clean_text(html.unescape(_RE_TAG.sub(" ", fragment)).replace("\xa0", " "))


def en_dates(text: Optional[str]) -> list[tuple[int, int, int]]:
    """Полные английские даты текста в порядке появления: (год, месяц, день).

    «January 10, 1945», «May 17th, 1945», «17 May 1945». Невозможный день
    («February 31») отбрасывается.
    """
    found = []
    s = (text or "").replace("\xa0", " ").replace(" ,", ",")
    for m in _RE_EN_DATE.finditer(s):
        found.append((m.start(), int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))))
    for m in _RE_EN_DATE_DMY.finditer(s):
        found.append((m.start(), int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))))
    out = []
    for _, y, mo, d in sorted(found):
        if 1 <= d <= (29 if mo == 2 else 30 if mo in (4, 6, 9, 11) else 31):
            if (y, mo, d) not in out:
                out.append((y, mo, d))
    return out


# --- Yahad: точки ------------------------------------------------------------

@dataclass
class Point:
    """Точка карты Yahad: всё, что известно до захода в профиль."""

    name: str
    country: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    band: Optional[int]
    pending: bool
    slug: Optional[str] = None
    village: Optional[int] = None
    trip_year: Optional[int] = None
    # Координата карты, которая координатой быть не может («531.299011», «0, 0»,
    # долгота 10 000): точка не ставится, исходник хранится, запись остаётся.
    coords_raw: Optional[str] = None


# Координата в ответе карты — не десятичные градусы, а «градусы.минуты»:
# «50.438240» — это 50° 43,824′, то есть 50,7304°. Так её читает сама карта
# (`convertGPS` в `/js/coords.js`: первые две цифры после точки — минуты,
# следующие три — их тысячные, последняя отбрасывается). Прочитанная как
# десятичная, точка уезжает на юго-запад в среднем на 28 км: Бердичев
# оказывается в 44 км от Бердичева.
_RE_MAP_COORD = re.compile(r"^\s*(-?)(\d{1,3})\.(\d{2})(\d{3})\d\s*$")


def map_degrees(value) -> Optional[float]:
    """«50.438240» → 50,7304: градусы и минуты карты Yahad в десятичные градусы.

    Не похоже на запись карты (нет шести знаков после точки, минут больше 59)
    — None: такая точка не ставится.
    """
    m = _RE_MAP_COORD.match(str(value or ""))
    if not m:
        return None
    sign, deg, mm, mmm = m.groups()
    minutes = int(mm) + int(mmm) / 1000
    if minutes >= 60:
        return None
    degrees = round(int(deg) + minutes / 60, 6)
    return -degrees if sign else degrees


def parse_points(payload) -> list[Point]:
    """Разбирает ответ карты: список словарей `{pending,u,t,p,date,img,lat,lng,s}`.

    Координата переводится из записи карты в десятичные градусы (`map_degrees`).
    Точка с невозможной координатой не выбрасывается: она остаётся без точки,
    с исходником в `coords_raw`, и её запись ляжет в файл без геометрии.
    Исправлять её на глаз («531.299» — скорее всего 53.1299) разбор не берётся.
    """
    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)
    if not isinstance(payload, list) or not payload:
        raise ExecutionSitesError("ответ карты Yahad — не список точек: разметку поменяли")
    need = {"u", "t", "p", "lat", "lng", "s", "pending"}
    missing = need - set(payload[0])
    if missing:
        raise ExecutionSitesError(f"у точек карты нет полей {sorted(missing)}")
    out = []
    for item in payload:
        raw_lat, raw_lon = item.get("lat"), item.get("lng")
        lat, lon = map_degrees(raw_lat), map_degrees(raw_lon)
        good = lat is not None and lon is not None and valid_coords(lat, lon)
        m = _RE_VILLAGE.match(item.get("u") or "")
        band = int(round(float(item["s"]))) if str(item.get("s") or "").strip() else None
        year = str(item.get("date") or "")
        out.append(Point(
            name=clean_text(item.get("t")) or "",
            country=clean_text(item.get("p")),
            lat=lat if good else None, lon=lon if good else None,
            band=band if band in VICTIM_BANDS else None,
            pending=str(item.get("pending")) == "1",
            slug=m.group(1) if m else None,
            village=int(m.group(2)) if m else None,
            trip_year=int(year) if year.isdigit() else None,
            coords_raw=None if good or not f"{raw_lat or ''}{raw_lon or ''}".strip()
            else f"{raw_lat}, {raw_lon}",
        ))
    return out


def villages(points: Iterable[Point]) -> list[int]:
    """Номера профилей, на которые ссылаются точки, — по возрастанию."""
    return sorted({p.village for p in points if p.village is not None})


# --- Yahad: профиль ----------------------------------------------------------

def parse_profile(page: str) -> dict:
    """Факты профиля села. Свидетельства, выдержки и очерк не читаются."""
    out: dict = {}
    nom, region = _RE_NOM.search(page), _RE_REGION.search(page)
    out["name"] = _text(nom.group(1)) if nom else None
    out["region"] = _text(region.group(1)) if region else None
    h2 = _RE_H2.search(page)
    out["heading"] = _text(h2.group(1)) if h2 else None
    nb = _RE_NB.search(page)
    out["sites"] = int(nb.group(1)) if nb else None
    for dt, dd in _RE_DL.findall(page):
        key = (_text(dt) or "").rstrip(":").strip().lower()
        out.setdefault("fields", {})[key] = _text(dd)
    sections = [_text(h) for h in _RE_H3.findall(page)]
    out["sections"] = [s for s in sections if s]
    hal = _RE_HAL_LINK.search(page)
    out["hal_item"] = int(hal.group(1)) if hal else None
    out["soviet_archive"] = soviet_archive_ref(_section(page, "Soviet archives"))
    out["archives"] = [re.sub(r"\s+archives$", "", s, flags=re.I).lower()
                       for s in out["sections"] if s.lower().endswith(" archives")]
    return out


def check_profile(profile: dict, n: int) -> None:
    """Название села на месте — иначе сайт переделали.

    Таблицы фактов может не быть: у части сёл профиль — заготовка с названием и
    числом мест казни (Potichok, № 1475). Это пропуск в данных, а не новая
    разметка; набор целиком проверяет `check_profiles`.
    """
    if not profile.get("name"):
        raise ExecutionSitesError(
            f"профиль {n}: нет названия села — разметку поменяли; "
            "поправьте разбор, а не подгоняйте его")


def check_profiles(profiles: dict[int, dict]) -> list[int]:
    """Номера профилей без таблицы фактов; нет её ни у одного — сайт переделали."""
    empty = sorted(n for n, p in profiles.items() if not p.get("fields"))
    if profiles and len(empty) == len(profiles):
        raise ExecutionSitesError(
            f"ни в одном из {len(profiles)} профилей нет таблицы фактов — разметку "
            "поменяли; поправьте разбор, а не подгоняйте его")
    return empty


def _section(page: str, title: str) -> Optional[str]:
    """HTML раздела профиля от заголовка `<h3>title</h3>` до следующего `<h3>`."""
    m = re.search(rf"<h3>\s*{re.escape(title)}\s*</h3>(.*?)(?=<h3>|$)", page, re.S)
    return m.group(1) if m else None


# Начало архивного шифра в ссылке: всё, что левее, — описание документа, и в
# нём бывают имена («Deposition of David Z., …»), поэтому в слой идёт только
# шифр и дата.
_RE_ARCHIVE_CODE = re.compile(r"(RG[\s.-]*\d|GARF|ГАРФ|Fond\s+\d|USHMM|Copy\s+USHMM)")


def soviet_archive_ref(fragment: Optional[str]) -> Optional[dict]:
    """Ссылка на документ после выдержки в разделе «Soviet archives».

    «[Act n°34 drawn up by Soviet Extraordinary Commission (ChGK) on January 10,
    1945; RG 22.002M: GARF 7021-96-82]» → `{"kind": "акт", "date": "1945-01-10",
    "number": "34", "ref": "RG 22.002M: GARF 7021-96-82"}`. Вид — «акт»,
    «показания» (deposition, testimony, interrogation) или «документ»; дата —
    полная, а нет её — год; шифр — от архивного кода до конца ссылки. Описание
    документа левее шифра в слой не идёт: в нём бывают имена свидетелей и
    обвиняемых. Сама выдержка — перевод Yahad — не идёт тем более.
    """
    text = _text(fragment)
    if not text:
        return None
    for m in _RE_BRACKET.finditer(text):
        body = m.group(1)
        code = _RE_ARCHIVE_CODE.search(body)
        keyword = re.search(r"\b(act|commission|ChGK|ЧГК)\b", body, re.I)
        if not keyword and not code:
            continue
        head = body[:code.start()] if code else body
        out: dict = {"kind": archive_kind(head)}
        dates = [d for d in en_dates(head) if 1943 <= d[0] <= 1948]
        if dates:
            y, mo, d = dates[0]
            out["date"] = f"{y:04d}-{mo:02d}-{d:02d}"
        else:
            years = [int(y) for y in _RE_YEAR.findall(head) if 1943 <= int(y) <= 1948]
            if years:
                out["date"] = str(years[0])
        number = re.search(r"\bact\s+n\s*[°ºo.]?\s*(\d+)", head, re.I)
        if number:
            out["number"] = number.group(1)
        if code:
            ref = clean_text(body[code.start():].rstrip(" .;"))
            if ref:
                out["ref"] = ref
        if out.get("ref") or out.get("date"):
            return out
    return None


def archive_kind(head: str) -> str:
    """Вид документа по его описанию в ссылке: акт, показания или документ."""
    low = head.lower()
    if re.search(r"\b(deposition|testimony|interrogation|interview|statement)\b", low):
        return "показания"
    if re.search(r"\b(act|report)\b", low):
        return "акт"
    return "документ"


def period_years(text: Optional[str]) -> Optional[tuple[int, int]]:
    """«1941-1944», «1941 - 1945», «1942–1943», «1941» → (от, до)."""
    if not text:
        return None
    years = [int(y) for y in _RE_YEARS.findall(text) if 1930 <= int(y) <= 1950]
    if not years:
        return None
    return min(years), max(years)


def victims_estimate(text: Optional[str]) -> Optional[int]:
    """Нижняя оценка числа жертв: «Over 1,000» → 1000, «Circa 1,500» → 1500."""
    if not text:
        return None
    m = _RE_NUMBER.search(text)
    if not m:
        return None
    return int(re.sub(r"[ ,.]", "", m.group(1)))


# Оценки числа жертв в профилях — короткие английские обороты. По-русски они
# идут в подпись записи; исходник остаётся в `extra["victims"]`.
_VICTIM_WORDS = (
    (r"(?<=\d)-(?=\s)", ""),
    (r"\b(?:between|from)\s+([\d ,.]+?)\s+(?:and|to)\s+", r"от \1 до "),
    (r"\b(?:probably|likely)\s+(?:higher|more)\s+than\b", "вероятно, более"),
    (r"\b(?:over|more than|above|higher than)\b", "более"),
    (r"\bc\.?a\.(?=\s|\d)", "около"),
    (r"\b(?:about|approximately|approx\.?|circa|around|roughly)\b", "около"),
    (r"\bat least\b", "не менее"),
    (r"\bup to\b", "до"),
    (r"\bless than\b", "менее"),
    (r"\bseveral dozens?\b", "несколько десятков"),
    (r"\bseveral hundreds?\b", "несколько сотен"),
    (r"\bseveral thousands?\b", "несколько тысяч"),
    (r"\b(?:about\s+)?an?\s+dozen\b|\bdozen\b", "около десятка"),
    (r"\bоколо\s+около\b", "около"),
    (r"\bdozens\b", "десятки"),
    (r"\bhundreds\b", "сотни"),
    (r"\bthousands\b", "тысячи"),
    (r"\bseveral\b", "несколько"),
    (r"\bnumerous\b", "много"),
    (r"\bu(?:n)?known\b", "неизвестно"),
    (r"\bor\b", "или"),
    (r"\((\d)(?:st|nd|rd|th)\)", r"(\1-е место)"),
    (r"\b(?:victims|people|persons|jews)\b", ""),
)


def victims_ru(text: Optional[str]) -> Optional[str]:
    """«Over 1,000» → «более 1 000», «Between 150 and 250» → «от 150 до 250».

    Остался английский оборот — None: подпись тогда берёт исходник как есть,
    а не полупереведённую фразу.
    """
    if not text:
        return None
    s = text.strip().lower()
    for pattern, repl in _VICTIM_WORDS:
        s = re.sub(pattern, repl, s)
    s = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", " ", s)
    s = clean_text(s.strip(" .;:"))
    if not s or re.search(r"[a-z]", s):
        return None
    return s


def victims_group(heading: Optional[str]) -> str:
    """Чьё убийство описывает профиль — по заголовку «Execution of … in …»."""
    low = (heading or "").lower()
    roma = any(w in low for w in ("roma", "gypsies", "gypsy", "sinti"))
    jews = "jew" in low
    if roma and jews:
        return "расстрел евреев и рома"
    if roma:
        return "расстрел рома (цыган)"
    if jews:
        return "расстрел евреев"
    return "массовый расстрел"


def place_kind_ru(text: Optional[str]) -> Optional[str]:
    """«Forest» → «лес»; «Forest (1); cemeteries (2)» → «лес; кладбища» и т. п."""
    if not text:
        return None
    parts = []
    for piece in re.split(r"[;,/]|\band\b", text):
        key = re.sub(r"\s+", " ", re.sub(r"\(.*?\)|\d+", " ", piece)).strip().lower()
        ru = PLACE_KINDS.get(key) or PLACE_KINDS.get(_singular(key))
        if not ru:
            # «Ravine near the road», «Near a brickyard»: известное слово, которое
            # стоит в подписи первым; при равенстве — более длинный ключ.
            hits = []
            for k in _PLACE_KEYS:
                m = re.search(rf"\b{re.escape(k)}(?:s|es)?\b", key)
                if m:
                    hits.append((m.start(), -len(k), k))
            ru = PLACE_KINDS[min(hits)[2]] if hits else None
        if ru and ru not in parts:
            parts.append(ru)
    return "; ".join(parts) if parts else None


def _singular(word: str) -> str:
    """«cemeteries» → «cemetery», «ravines» → «ravine»: подписи профиля бывают во мн. ч."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1] if word.endswith("s") else word


def yes_no(text: Optional[str]) -> Optional[bool]:
    low = (text or "").strip().lower()
    if low.startswith("yes"):
        return True
    if low.startswith("no"):
        return False
    return None


# --- Holocaust Atlas of Lithuania ---------------------------------------------

@dataclass
class HalPlace:
    id: int
    lat: float
    lon: float
    title: str
    summary: str


def parse_hal(script: str) -> list[HalPlace]:
    """`markers[i] = new Array(id, lat, lon, zoom, 'title', 'summary');` → места."""
    out = []
    for m in _RE_HAL_ROW.finditer(script):
        lat, lon = float(m.group(2)), float(m.group(3))
        if not valid_coords(lat, lon):
            continue
        title = _unjs(m.group(4))
        summary = _unjs(m.group(5))
        out.append(HalPlace(int(m.group(1)), lat, lon, title or "", summary or ""))
    if not out:
        raise ExecutionSitesError("в load_markers.js.php нет ни одного места: разметку поменяли")
    return out


def _unjs(text: str) -> Optional[str]:
    return _text(text.replace("\\'", "'").replace('\\"', '"'))


@dataclass
class Dating:
    year_from: Optional[int]
    year_to: Optional[int]
    precision: str
    approx: bool
    raw: Optional[str]
    iso: Optional[str] = None


def hal_dating(summary: str) -> Optional[Dating]:
    """Дата расстрела из аннотации атласа.

    Только полные даты («August 29, 1941», «September 9, 1941») — `day`, годы
    между крайними; рядом с ними ещё и месяц без числа («At the end of June,
    1941 … On August 29, 1941» — два расстрела) — `month`, в `raw` все
    названные даты; только месяц и год — `month`; только годы — `year`.
    Не нашлось ничего — None, дальше решает рамка.
    """
    text = (summary or "").replace("\xa0", " ")
    full = sorted({d for d in en_dates(text) if 1939 <= d[0] <= 1945})
    in_full = {(y, m) for y, m, _ in full}
    months = sorted({(int(y), _MONTHS[mo.lower()]) for mo, y in _RE_EN_MONTH_YEAR.findall(text)
                     if 1939 <= int(y) <= 1945} - in_full)
    if full or months:
        years = [y for y, *_ in full] + [y for y, _ in months]
        raw = ", ".join([f"{m:02d}.{y}" for y, m in months]
                        + [f"{d:02d}.{m:02d}.{y}" for y, m, d in full])
        precision = "day" if full and not months else "month"
        iso = (f"{full[0][0]:04d}-{full[0][1]:02d}-{full[0][2]:02d}"
               if len(full) == 1 and not months else None)
        return Dating(min(years), max(years), precision, False, raw, iso)
    years = sorted({int(y) for y in _RE_YEAR.findall(text) if 1939 <= int(y) <= 1945})
    if years:
        return Dating(years[0], years[-1], "year", False, ", ".join(map(str, years)))
    return None


# --- сведение двух наборов -----------------------------------------------------

def match_hal(points: list[Point], profiles: dict[int, dict],
              places: list[HalPlace]) -> dict[int, int]:
    """Пары «индекс точки Yahad → номер места атласа», каждая сторона один раз.

    Сначала — явные ссылки профиля на страницу атласа (до `LINK_KM`), потом
    ближайшие пары по расстоянию (до `MATCH_KM`), от ближних к дальним.
    """
    by_id = {p.id: p for p in places}
    pairs = []
    for i, pt in enumerate(points):
        if pt.lat is None:
            continue
        link = (profiles.get(pt.village) or {}).get("hal_item") if pt.village else None
        for place in places:
            if abs(place.lat - pt.lat) > 0.1 and place.id != link:
                continue
            d = haversine_km(pt.lat, pt.lon, place.lat, place.lon)
            if place.id == link and d <= LINK_KM:
                pairs.append((0, d, i, place.id))
            elif d <= MATCH_KM:
                pairs.append((1, d, i, place.id))
    out: dict[int, int] = {}
    used: set[int] = set()
    for _, _, i, pid in sorted(pairs):
        if i in out or pid in used or pid not in by_id:
            continue
        out[i] = pid
        used.add(pid)
    return out


# --- записи схемы --------------------------------------------------------------

def occupation_frame(country: Optional[str]) -> Dating:
    a, b = OCCUPATION.get(country or "", WAR)
    where = COUNTRIES_RU.get(country or "", country or "территория")
    return Dating(a, b, "era", True, f"рамка оккупации: {where}, {a}–{b}")


def records(points: list[Point], profiles: dict[int, dict], places: list[HalPlace], *,
            names=None, spec: LayerSpec = EXECUTION_SITES) -> list[ContextRecord]:
    """Записи слоя: по точке Yahad и по месту атласа, не сведённому с Yahad."""
    matched = match_hal(points, profiles, places)
    by_id = {p.id: p for p in places}
    per_village: dict[int, list[int]] = {}
    for i, pt in enumerate(points):
        if pt.village is not None:
            per_village.setdefault(pt.village, []).append(i)
    out = []
    for i, pt in enumerate(points):
        profile = profiles.get(pt.village) if pt.village is not None else None
        hal = by_id.get(matched.get(i)) if i in matched else None
        siblings = per_village.get(pt.village, [i]) if pt.village is not None else [i]
        out.append(point_record(pt, profile, hal, names=names, spec=spec,
                                order=(siblings.index(i) + 1, len(siblings))))
    used = set(matched.values())
    alone = [p for p in places if p.id not in used]
    # Несколько мест одного местечка (форты Каунаса, три рва у Бутримониса)
    # нумеруются, как места одного села у Yahad.
    towns: dict[Optional[str], list[int]] = {}
    for place in alone:
        towns.setdefault(hal_town(place.title), []).append(place.id)
    for place in alone:
        same = towns.get(hal_town(place.title), [place.id])
        order = (same.index(place.id) + 1, len(same)) if hal_town(place.title) else (1, 1)
        out.append(hal_record(place, names=names, spec=spec, order=order))
    return out


def point_record(pt: Point, profile: Optional[dict], hal: Optional[HalPlace], *,
                 names=None, spec: LayerSpec = EXECUTION_SITES,
                 order: tuple[int, int] = (1, 1)) -> ContextRecord:
    fields = (profile or {}).get("fields") or {}
    name = (profile or {}).get("name") or pt.name
    where = (names.lookup(name, pt.lat, pt.lon) if (names and pt.lat is not None) else None) \
        or _base_name(name)
    title = f"Место расстрела — {where}"
    if order[1] > 1:
        title += f" ({order[0]} из {order[1]})"

    years = period_years(fields.get("period of occupation"))
    hal_date = hal_dating(hal.summary) if hal else None
    if hal_date:
        date = hal_date
    elif years:
        date = Dating(years[0], years[1], "year", False,
                      f"период оккупации: {fields.get('period of occupation')}")
    else:
        date = occupation_frame(pt.country)

    victims_raw = fields.get("total number of victims")
    estimate = victims_estimate(victims_raw)
    category = victims_group((profile or {}).get("heading")) if profile else "массовый расстрел"
    kind = fields.get("kind of place before")
    archive = (profile or {}).get("soviet_archive")
    extra = {
        "source_set": "yahad" + ("+hal" if hal else ""),
        "village": pt.village,
        "name_en": name,
        "region_en": (profile or {}).get("region"),
        "country": pt.country,
        "pending": pt.pending or None,
        "victims_band": VICTIM_BANDS.get(pt.band) if pt.band else None,
        "victims": victims_raw,
        "victims_min": estimate,
        "killing_sites": (profile or {}).get("sites"),
        "place_before_en": kind,
        "place_before": place_kind_ru(kind),
        "memorial": yes_no(fields.get("memorials")),
        "occupation": fields.get("period of occupation"),
        "soviet_archive": archive,
        "archives": (profile or {}).get("archives") or None,
        "trip_year": pt.trip_year,
        "coords_raw": pt.coords_raw,
    }
    if hal:
        extra["holocaust_atlas_lt"] = {"id": hal.id, "url": HAL_ITEM.format(id=hal.id),
                                       "title_en": hal.title, "date": date.iso}
    url = YAHAD_PAGE.format(slug=pt.slug, n=pt.village) if pt.village is not None else YAHAD_MAP
    return spec.new_record(
        title=title,
        category=category,
        lat=pt.lat, lon=pt.lon,
        place_text=", ".join(x for x in (name, (profile or {}).get("region"), pt.country) if x),
        year_from=date.year_from, year_to=date.year_to,
        date_precision=date.precision, date_approx=date.approx,
        period_raw=date.raw,
        summary=point_summary(category, pt, fields, archive, date, hal),
        url=url,
        source_id=(f"yahad:{pt.village}:{order[0]}" if pt.village is not None
                   else f"yahad:pending:{pt.lat:.5f},{pt.lon:.5f}" if pt.lat is not None
                   else f"yahad:pending:{pt.name}"),
        confidence="ok" if pt.lat is not None else "no_coords",
        extra={k: v for k, v in extra.items() if v is not None},
    )


def hal_record(place: HalPlace, *, names=None, spec: LayerSpec = EXECUTION_SITES,
               order: tuple[int, int] = (1, 1)) -> ContextRecord:
    date = hal_dating(place.summary) or occupation_frame("Lithuania")
    town = hal_town(place.title)
    where = (names.lookup(town, place.lat, place.lon) if (names and town) else None) or town
    title = f"Место расстрела — {where}" if where else "Место массового расстрела (Литва)"
    if order[1] > 1:
        title += f" ({order[0]} из {order[1]})"
    low = place.title.lower()
    category = "расстрел евреев" if "jew" in low else "массовый расстрел"
    extra = {
        "source_set": "hal",
        "holocaust_atlas_lt": {"id": place.id, "title_en": place.title, "date": date.iso},
        "country": "Lithuania",
    }
    text = [category, f"дата по аннотации атласа — {date.raw}" if date.precision != "era"
            else "дата в аннотации не названа", "аннотация — на странице атласа Литвы"]
    return spec.new_record(
        title=title,
        category=category,
        lat=place.lat, lon=place.lon,
        place_text=place.title,
        year_from=date.year_from, year_to=date.year_to,
        date_precision=date.precision, date_approx=date.approx,
        period_raw=date.raw,
        summary=_sentence(text),
        url=HAL_ITEM.format(id=place.id),
        source_id=f"hal:{place.id}",
        extra=extra,
    )


_CAP = "A-ZĄČĘĖĮŠŲŪŽ"
_RE_HAL_FROM = re.compile(
    rf"\bfrom\s+(?:the\s+)?([{_CAP}][^,;]*?)(?:,|\s+and\s+|\s+in\s+|\s+next to\b|$)")
_RE_HAL_TAIL = re.compile(rf"^.*\b(?:of|in|near|at)\s+(?:the\s+)?([{_CAP}][^,;]*)$")
_RE_HAL_PLACE = re.compile(rf"^([{_CAP}][\wąčęėįšųūž]+)\s+(?:[IVX]+\s+)?(?:Fort|Ghetto|ghetto)\b")
_RE_HAL_NOISE = re.compile(
    r"\b(?:(?:and\s+)?s[ou]rrounding\s+areas?|forest|woods?|district|area|jewish cemetery|"
    r"cemetery|town|village)\b.*$", re.I)


def hal_town(title: str) -> Optional[str]:
    """Местечко из заголовка атласа: «Mass Murder of the Jews of Molėtai» → «Molėtai».

    По порядку: «… from X, Y and Z» — первое из перечня; хвост после последнего
    « of »/« in »/« near »/« at »; «Kaunas IX Fort», «Vilnius Ghetto» — первое
    слово. Скобки, «(1st site)», «and Surrounding Areas», «forest», «woods»
    отбрасываются. Не нашлось — None: подпись тогда общая.
    """
    t = clean_text(re.sub(r"\([^)]*\)", " ", title or "")) or ""
    m = _RE_HAL_FROM.search(t)
    if not m:
        # Жадное начало: берётся последнее «of/in/near/at», а не первое — в
        # «Mass Murder of the Jews of Molėtai» местечко стоит после второго «of».
        m = _RE_HAL_TAIL.search(t) or _RE_HAL_PLACE.search(t)
    if not m:
        return None
    town = clean_text(_RE_HAL_NOISE.sub("", m.group(1)).strip(" .-"))
    return town or None


def point_summary(category: str, pt: Point, fields: dict, archive: Optional[dict],
                  date: Dating, hal: Optional[HalPlace]) -> str:
    parts = [category]
    victims = fields.get("total number of victims")
    if victims:
        parts.append(f"жертв по профилю — {victims_ru(victims) or victims}")
    elif pt.band:
        parts.append(f"оценка по карте — {VICTIM_BANDS[pt.band]}")
    if fields.get("period of occupation"):
        parts.append(f"оккупация — {fields['period of occupation']}")
    if hal and date.precision in ("day", "month"):
        parts.append(f"дата расстрела по атласу Литвы — {date.raw}")
    if archive and archive.get("kind") == "акт" and archive.get("date"):
        parts.append(f"акт ЧГК от {archive['date']}")
    elif archive and archive.get("ref"):
        parts.append(f"в советских архивах — {archive['kind']}, {archive['ref']}")
    if pt.pending:
        parts.append("профиль на сайте ещё не опубликован")
    else:
        parts.append("свидетельства и очерк — в профиле Yahad – In Unum")
    return _sentence(parts)


def _sentence(parts: list[str]) -> str:
    text = "; ".join(p for p in parts if p)
    return text[:1].upper() + text[1:] + "."


def _base_name(name: str) -> str:
    """«Andrushivka (Andrushovka, Andruszowka)» → «Andrushivka» для поиска подписи."""
    return re.split(r"[(,/]", name or "")[0].strip()


# --- сеть и кэш ----------------------------------------------------------------

@dataclass
class Client:
    """Вежливый обход одного хоста: пауза, повтор при сбросе и 429, кэш."""

    cache_dir: Path
    pause: float = PAUSE
    timeout: int = 90
    retries: int = 5
    _last: float = field(default=0.0, repr=False)
    requests: int = field(default=0, repr=False)

    def request(self, url: str, data: Optional[dict] = None) -> bytes:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        for attempt in range(self.retries + 1):
            self._last = wait_for_pause(self._last, self.pause)
            self.requests += 1
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    self.pause = min(10.0, self.pause + 0.5) if exc.code == 429 else self.pause
                    time.sleep(10.0 * (attempt + 1))
                    continue
                raise ExecutionSitesError(f"{url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(5.0 * (attempt + 1))
                    continue
                reason = getattr(exc, "reason", exc)
                raise ExecutionSitesError(f"{url}: сеть недоступна ({reason})") from exc
        raise ExecutionSitesError(f"{url}: не ответил за {self.retries + 1} попыток")

    def cached(self, name: str, url: str, *, data: Optional[dict] = None,
               refresh: bool = False, encoding: str = "utf-8") -> str:
        path = self.cache_dir / name
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")
        text = self.request(url, data).decode(encoding, errors="replace")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return text


def profile_cache_name(n: int) -> str:
    return f"yahad/profiles/{n}.html"
