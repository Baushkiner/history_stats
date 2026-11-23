"""Регулярные планы городов 1766–1831 годов (ПСЗ, «Книга чертежей и рисунков»).

Зачем этот слой. Конфирмованный — высочайше утверждённый — план менял город
на десятилетия вперёд: кварталы перекладывались по линейке, деревянные
слободы сносили или переносили за черту, приходские церкви оказывались на
новых площадях, а улицы получали новые имена. Для родословной это объясняет,
почему двор предка в одной ревизии стоит «в слободе», а в следующей — «во
2-м квартале», почему прихожане храма разом сменились и откуда в
городовой обывательской книге новые номера домов. Планы утверждались
наместничествами при Екатерине II и губерниями при Александре I и Николае I —
385 городов, начиная с 1766 года; в 1839 году они вышли отдельным томом
Полного собрания законов, «Книгой чертежей и рисунков».

Набор. Проект Imperiia (Davis Center, Гарвард; К. О'Нил) разобрал этот том
постранично: у каждого плана в Omeka — город латиницей и кириллицей,
наместничество или губерния на момент плана, год утверждения, номер плана в
томе, редакция (первая, вторая — город перепланирован, «contended» —
спорная), насыщенность плана объектами и точка города. Отдаётся открытым API
Omeka Classic: тип предмета 38 «PSZ Town Plans» — 415 планов 382 городов
1766–1831 годов, точка (`/api/geolocations`) у 411. Описание проекта
говорит о 385 городах и 416 планах тома: разница — несколько планов,
которых в каталоге нет.

Права. На сайте не заявлены (поля «Rights» у предметов нет); оригинал — том
ПСЗ 1839 года — общественное достояние. Берутся факты — город, наместничество,
год, номер и редакция плана — со ссылкой на страницу предмета; аннотации
проекта (поле Description у 26 планов) и снимки листов не копируются.

Где запись на карте. Точка — город, а не план: `confidence = place_level`.
У четырёх планов Imperiia точки не даёт; двум из них (Тамбов 1781 года,
Красноборск 1784-го) она берётся из GeoNames — единственный тёзка в той же
губернии, пометка `extra.point`. Черна (ныне Чернь) и Петербург 1831 года
(в GeoNames тёзок несколько) остаются без точки.
Губерния 1897 года — по полигонам (`histctx.frame`), наместничество времени
плана — в `place_text`: Харьков 1786 года стоит в Харьковском наместничестве,
а не в Харьковской губернии. Где губерния точки и наместничество плана не
сходятся по названию, у записи `extra.check` — 49 планов из 413 с точкой.
Почти всегда это переподчинение уезда (Елец, Гдов, Луга, города Полоцкого
наместничества в Витебской губернии), но у Ардатова (оба плана), Починок и
Онеги 1817 года точка Imperiia стоит у одноимённого места в другой
губернии — пометка называет кандидата из GeoNames, а точка остаётся как в
источнике.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..frame import SHORE_STEPS, Frame
from ..geo import haversine_km
from ..net import RETRY_CODES, USER_AGENT
from ..schema import ContextRecord, LayerSpec

API = "https://imperiia.omeka.fas.harvard.edu/api/"
ITEM_TYPE = 38                      # «PSZ Town Plans»
PER_PAGE = 50                       # больше Omeka Classic не отдаёт
ITEM_PAGE = "https://imperiia.omeka.fas.harvard.edu/items/show/{}"
SITE_URL = "https://imperiia.omeka.fas.harvard.edu/"
# Пауза между запросами: `robots.txt` сайта закрывает только SemrushBot и
# паузы не просит, но запросов двадцать, и спешить незачем.
PAUSE = 1.0

LICENSE = (
    "права на сайте не заявлены; оригинал — «Книга чертежей и рисунков» ПСЗ 1839 года — "
    "общественное достояние. Берутся факты (город, наместничество, год, номер и редакция "
    "плана) со ссылкой на страницу Imperiia; аннотации проекта и снимки не копируются"
)

TOWN_PLANS = LayerSpec(
    slug="town_plans",
    title="Регулярные планы городов (ПСЗ, «Книга чертежей и рисунков»)",
    group="admin",
    source="Imperiia Project (Davis Center, Гарвард), каталог «PSZ Town Plans»",
    license=LICENSE,
    description=(
        "Когда городу утвердили регулярный план: 415 планов 382 городов 1766–1831 годов "
        "из «Книги чертежей и рисунков» ПСЗ — год, наместничество или губерния того "
        "времени, номер плана в томе, первая или вторая редакция. Объясняет, почему "
        "двор предка в одной ревизии «в слободе», а в следующей — «в квартале», и "
        "почему у прихода сменились прихожане."
    ),
    url=SITE_URL,
    status="harvested",
    expected_rows=415,
)

EDITION_RU = {
    "first": "первая редакция",
    "second": "вторая редакция — город планировался повторно",
    "contended": "редакция спорная (contended)",
}
DIVERSITY_RU = {
    "very low": "очень мало", "low": "мало", "medium": "средне", "high": "много",
    "very high": "очень много",
}
CONFIDENCE_TOWN = "place_level"


class TownPlansError(RuntimeError):
    """Каталог не ответил или пришёл не в том виде."""


# --- поля предмета ------------------------------------------------------------

def element_texts(item: dict) -> dict[str, str]:
    """Поля предмета Omeka по имени элемента: «Plan Date» → «1786»."""
    out: dict[str, str] = {}
    for el in item.get("element_texts") or []:
        name = ((el.get("element") or {}).get("name") or "").strip()
        text = (el.get("text") or "").strip()
        if name and text and name not in out:
            out[name] = text
    return out


_RE_BILINGUAL = re.compile(r"^(?P<latin>.*?)\s*\((?P<cyr>[^()]*)\)\s*$")


def bilingual(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """«Yekaterinoslav (Екатеринослав)» → («Yekaterinoslav», «Екатеринослав»)."""
    if not value:
        return None, None
    match = _RE_BILINGUAL.match(value.strip())
    if not match:
        return value.strip(), None
    return match.group("latin").strip() or None, match.group("cyr").strip() or None


def plan_year(value: Optional[str]) -> Optional[int]:
    match = re.search(r"\b(1[67]\d\d|18\d\d)\b", value or "")
    return int(match.group(1)) if match else None


def plan_number(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def geolocations_by_item(geos: Iterable[dict]) -> dict[int, tuple[float, float]]:
    out = {}
    for geo in geos:
        item = (geo.get("item") or {}).get("id")
        try:
            lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
        except (TypeError, ValueError):
            continue
        if item is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            out[int(item)] = (lat, lon)
    return out


def plan_record(item: dict, point: Optional[tuple[float, float]]) -> Optional[ContextRecord]:
    """Запись слоя по предмету каталога; без года плана записи нет."""
    fields = element_texts(item)
    year = plan_year(fields.get("Plan Date"))
    if year is None:
        return None
    town_lat, town_ru = bilingual(fields.get("Town"))
    prov_lat, prov_ru = bilingual(fields.get("Province"))
    town = town_ru or town_lat or fields.get("Title") or "город не назван"
    province = prov_ru or prov_lat
    number = plan_number(fields.get("Plan Number"))
    edition = (fields.get("Plan Edition") or "").strip().lower() or None
    diversity = (fields.get("Feature Diversity") or "").strip().lower() or None
    parts = [f"Высочайше утверждённый план города {town}"
             + (f" ({province})" if province else "") + f", {year} год"]
    if number:
        parts.append(f"план № {number} «Книги чертежей и рисунков» Полного собрания "
                     "законов (собрание первое, 1839)")
    if edition:
        parts.append(EDITION_RU.get(edition, edition))
    if diversity:
        parts.append(f"объектов на плане — {DIVERSITY_RU.get(diversity, diversity)}")
    lat, lon = point if point else (None, None)
    extra = {
        "omeka_id": item.get("id"),
        "town_ru": town_ru,
        "town_latin": town_lat,
        "province_at_plan": province,
        "province_latin": prov_lat,
        "plan_number": number,
        "edition": edition,
        "feature_diversity": diversity,
        "orientation": (fields.get("Plan Orientation") or None),
        "iiif_uuid": fields.get("UUID"),
    }
    return TOWN_PLANS.new_record(
        title=f"Регулярный план: {town}, {year}",
        category="регулярный план города",
        lat=lat, lon=lon,
        place_text=", ".join(p for p in (town, province) if p),
        year_from=year, year_to=year,
        date_precision="year",
        period_raw=fields.get("Plan Date"),
        work="Полное собрание законов Российской империи (собрание первое). Книга чертежей "
             "и рисунков. Планы городов. СПб., 1839",
        summary="; ".join(parts) + ". По каталогу Imperiia (Гарвард)",
        url=ITEM_PAGE.format(item.get("id")),
        source_id=str(item.get("id")),
        confidence=CONFIDENCE_TOWN if point else "no_coords",
        extra={k: v for k, v in extra.items() if v not in (None, "")},
    )


def records(items: Iterable[dict], geos: Iterable[dict]) -> list[ContextRecord]:
    points = geolocations_by_item(geos)
    out = []
    for item in items:
        rec = plan_record(item, points.get(int(item.get("id"))))
        if rec is not None:
            out.append(rec)
    out.sort(key=lambda r: (r.year_from, r.title))
    return out


def nearby_province(frame: Frame, lat: float, lon: float) -> Optional[str]:
    """Губерния рядом с точкой, которую грубый контур 1897 года оставил в устье.

    Архангельск стоит в дельте Двины: CShapes считает точку сушей России, а
    полигон губернии до неё не доходит. Тот же поиск, что у берега в
    `frame.py`, — восемь направлений до 0,3°, — но ищется губерния.
    """
    for step in SHORE_STEPS:
        for k in range(8):
            province = frame.provinces.region_for(
                lat + math.sin(k * math.pi / 4) * step, lon + math.cos(k * math.pi / 4) * step)
            if province:
                return province
    return None


def stem(name: Optional[str]) -> str:
    """Основа названия губернии для сверки: «Санктпетербургская» = «Санкт-Петербургская»."""
    letters = "".join(ch for ch in (name or "").lower() if ch.isalpha())
    return letters[:5]


def town_key(name: Optional[str]) -> str:
    return (name or "").lower().replace("ё", "е").strip()


def fill_points(recs: Iterable[ContextRecord], frame: Frame,
                towns: Iterable[ContextRecord]) -> int:
    """Точка города без геолокации — из GeoNames, если тёзка один и в той же губернии.

    У четырёх планов Imperiia точки нет (Тамбов 1781 года, Петербург 1831-го).
    Город ищется по имени среди населённых мест GeoNames; берётся, только
    если подходящий ровно один и его губерния 1897 года совпадает по основе
    с наместничеством плана. Запись помечается `extra.point`.
    """
    by_name: dict[str, list[ContextRecord]] = {}
    for town in towns:
        if town.has_point:
            by_name.setdefault(town_key(town.title), []).append(town)
    filled = 0
    for rec in recs:
        if rec.has_point:
            continue
        at_plan = rec.extra.get("province_at_plan")
        name = rec.extra.get("town_ru")
        fits = [t for t in by_name.get(town_key(name), [])
                if stem(frame.place(t.lat, t.lon)[1]) == stem(at_plan)]
        if len(fits) != 1:
            continue
        rec.lat, rec.lon = round(fits[0].lat, 5), round(fits[0].lon, 5)
        rec.confidence = CONFIDENCE_TOWN
        rec.extra["point"] = f"GeoNames по названию и губернии: {fits[0].url or fits[0].title}"
        filled += 1
    return filled


def mark_frame(recs: Iterable[ContextRecord], frame: Frame,
               towns: Iterable[ContextRecord] = ()) -> dict:
    """Губерния 1897 года по точке города; вне рамки — outside_bbox.

    Наместничество плана и губерния точки сверяются по основе названия. Не
    совпали — запись получает `extra.check`: чаще это переподчинение (Елец
    в 1778 году ушёл из Воронежского наместничества в Орловское), но бывает
    и точка у одноимённого города. Тогда пометка называет город с тем же
    именем в губернии плана — по населённым местам GeoNames, — а точка не
    двигается: исправлять источник молча нельзя.
    """
    by_name: dict[str, list[ContextRecord]] = {}
    for town in towns:
        if town.has_point:
            by_name.setdefault(town_key(town.title), []).append(town)
    counts: dict = {}

    def bump(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    for rec in recs:
        if not rec.has_point:
            bump("без точки")
            continue
        inside, province, _ = frame.place(rec.lat, rec.lon)
        if inside and not province:
            province = nearby_province(frame, rec.lat, rec.lon)
            if province:
                rec.extra["frame"] = "губерния по соседству"
                bump("из них губерния найдена по соседству")
        rec.region = province
        bump("в губерниях 1897 года" if province else
             "в рамке, вне губерний 1897 года" if inside else "вне рамки РИ/СССР")
        if not inside:
            rec.confidence = "outside_bbox"
        at_plan = rec.extra.get("province_at_plan")
        if not (province and at_plan) or stem(province) == stem(at_plan):
            continue
        note = (f"точка в губернии «{province}» (1897), план — по «{at_plan}»: "
                "переподчинение или точка у другого города")
        town = rec.extra.get("town_ru") or rec.title.split(": ", 1)[-1].rsplit(",", 1)[0]
        for other in by_name.get(town_key(town), []):
            _, other_prov, _ = frame.place(other.lat, other.lon)
            if other_prov and stem(other_prov) == stem(at_plan) \
                    and haversine_km(rec.lat, rec.lon, other.lat, other.lon) > 25:
                note += (f"; одноимённое место в губернии плана: {other.title}, "
                         f"{other.lat:.4f}, {other.lon:.4f} (GeoNames)")
                bump("губерния не совпала, есть одноимённое место в губернии плана")
                break
        rec.extra["check"] = note
        bump("губерния точки не совпала с наместничеством плана")
    return counts


# --- сеть ---------------------------------------------------------------------

def _get(url: str, *, timeout: int = 90, tries: int = 4) -> list:
    last = None
    for attempt in range(tries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_CODES:
                raise TownPlansError(f"{url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
            last = exc
        else:
            if isinstance(payload, dict) and payload.get("message"):
                raise TownPlansError(f"{url}: {payload['message']}")
            if not isinstance(payload, list):
                raise TownPlansError(f"{url}: ждали список, пришло {type(payload).__name__}")
            return payload
        time.sleep(5 * (attempt + 1))
    raise TownPlansError(f"{url}: не ответил после {tries} попыток ({last})")


def fetch_all(resource: str, query: str, cache_dir: Path, *, pause: float = PAUSE,
              log: Callable[[str], None] = print) -> list[dict]:
    """Все страницы ресурса Omeka; каждая ложится в кэш файлом."""
    cache_dir = Path(cache_dir)
    out, page = [], 1
    while True:
        cached = cache_dir / f"{resource}_{query.replace('=', '-').replace('&', '_')}_p{page}.json"
        if cached.exists():
            batch = json.loads(cached.read_text(encoding="utf-8"))
        else:
            sep = "&" if query else ""
            batch = _get(f"{API}{resource}?{query}{sep}per_page={PER_PAGE}&page={page}")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            log(f"  {resource}: страница {page}, {len(batch)}")
            time.sleep(pause)
        out += batch
        if len(batch) < PER_PAGE:
            return out
        page += 1


def fetch(cache_dir: Path, **kw) -> tuple[list[dict], list[dict]]:
    """Планы (тип 38) и все геолокации сайта — их меньше пятисот."""
    items = fetch_all("items", f"item_type={ITEM_TYPE}", cache_dir, **kw)
    geos = fetch_all("geolocations", "", cache_dir, **kw)
    return items, geos
