"""«Военный альбом» (waralbum.ru): фотографии 1939–1945 годов.

Зачем этот слой. Около 54 тысяч снимков Второй мировой и Великой
Отечественной войны с подписью, «Местом съемки» («Ржев», «Латвия, СССР»,
«район Сталинграда»), «Временем съемки» до дня и автором (Шагин, Халдей,
Бальтерманц, фотографы вермахта и союзников). Для генеалогии это фронт,
город, переправа или госпиталь в те месяцы, когда там был предок. Сайт
объявляет себя составным произведением — базой данных (ст. 1260 ГК РФ), права
на сами снимки — у правообладателей, названных на странице (ТАСС, IWM,
Bundesarchiv и др.); собрано с согласия владельца, полученного владельцем
проекта (сообщено 24.11.2026).

Как достаются данные. Сайт — WordPress, но REST закрыт: `/wp-json/` — 404,
`?rest_route=` отдаёт главную. Лента (`/feed/`) даёт подпись и рубрики без
места и времени. Остаются страницы снимков: адреса — в карте сайта
(`sitemap.xml` → `sitemap1.xml`, `sitemap2.xml`, 54 272 адреса
`https://waralbum.ru/<номер>/` на 24.11.2026), а на странице — блок
«Информация о фото» (`<li>Место съемки: …</li>`, `<li>Время съемки: …</li>`,
`<li>Автор: …</li>`), подпись, источник, рубрики и ссылка на оригинал. Одна
страница — один запрос, около двух секунд с паузой, то есть весь альбом —
около 30 часов. Сборщик хранит вырезанный блок страницы (`pages.jsonl`) и
продолжает с места.

Где снимок на карте. Координат на сайте нет — только место текстом.
Точка ставится по названию первого звена «Места съемки» (`geocode`): по
указателю из слоёв проекта — городам «Освобождения городов» с их названиями
военного времени, переименованиям, переписи городов 1926 года и GeoNames.
Принимается только однозначное совпадение (все кандидаты в 30 км друг от
друга); точка — город, а не место съёмки (`confidence = place_level`). Если
в «Месте съемки» названа страна вне РИ/СССР (Великобритания, Франция, Италия
…), а точки нет — запись остаётся без точки с `confidence = outside_bbox` и
пометкой `extra.frame_by`, как в слое `ghettos_camps`. Остальные
неразмещённые — `no_coords`, с местом в `place_text`.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

from ..geo import haversine_km
from ..schema import ContextRecord, LayerSpec, clean_text
from .photo_common import CONSENT, Fetcher, photo_years

BASE = "https://waralbum.ru"
SITEMAP = BASE + "/sitemap.xml"

WARALBUM = LayerSpec(
    slug="photos_waralbum",
    title="Фотографии войны 1939–1945 (Военный альбом)",
    group="military",
    source="«Военный альбом», waralbum.ru",
    license=("подборка — база данных waralbum.ru (ст. 1260 ГК РФ); снимки — права "
             "правообладателей, названных на странице снимка (ТАСС, IWM, Bundesarchiv и др.); "
             + CONSENT),
    description=(
        "Снимки Второй мировой и Великой Отечественной войны с местом и временем съёмки и "
        "автором; точка — населённый пункт из «Места съемки»."
    ),
    url="https://waralbum.ru/",
    status="harvested",
)


class WaralbumError(RuntimeError):
    pass


_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_RE_PHOTO_URL = re.compile(r"^https://waralbum\.ru/(\d+)/$")


def sitemap_ids(fetcher: Fetcher, cache: Path) -> list[int]:
    """Номера снимков из карты сайта; список кэшируется в `ids.json`."""
    path = cache / "ids.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    index = fetcher.get(SITEMAP).decode("utf-8", "replace")
    ids: list[int] = []
    for loc in _RE_LOC.findall(index):
        if "sitemap-cats" in loc or loc.endswith("sitemap0.xml"):
            continue
        body = fetcher.get(loc).decode("utf-8", "replace")
        ids += [int(m[1]) for m in (_RE_PHOTO_URL.match(u) for u in _RE_LOC.findall(body)) if m]
    ids = sorted(set(ids))
    if not ids:
        raise WaralbumError("в карте сайта нет адресов снимков")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids), encoding="utf-8")
    return ids


def fragment(page: str) -> Optional[str]:
    """Из страницы — заголовок, подпись, источник и «Информация о фото»."""
    start = page.find('<h1 class="title"')
    if start < 0:
        return None
    stop = page.find("<!-- похожие фото -->", start)
    return page[start:stop if stop > 0 else start + 20000]


def done_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    out = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                out.add(int(json.loads(line)["id"]))
            except (ValueError, KeyError):
                continue
    return out


def fetch_pages(ids: list[int], cache: Path, fetcher: Fetcher, *, limit: Optional[int] = None,
                log=print) -> int:
    """Страницы снимков по порядку номеров, с продолжением с места."""
    path = cache / "pages.jsonl"
    have = done_ids(path)
    todo = [i for i in ids if i not in have]
    if limit is not None:
        todo = todo[:limit]
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for pid in todo:
            body = fetcher.get(f"{BASE}/{pid}/", ok404=True)
            frag = fragment(body.decode("utf-8", "replace")) if body is not None else None
            fh.write(json.dumps({"id": pid, "html": frag}, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 500 == 1:
                log(f"  страниц {len(have) + n} из {len(ids)} (снимок {pid})")
    return len(have) + n


def load_pages(cache: Path) -> Iterator[tuple[int, Optional[str]]]:
    path = cache / "pages.jsonl"
    if not path.exists():
        return
    seen = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            yield row["id"], row.get("html")


# --- разбор страницы ---------------------------------------------------------

@dataclass
class Photo:
    id: int
    title: Optional[str]
    caption: Optional[str] = None
    place: Optional[str] = None
    time: Optional[str] = None
    author: Optional[str] = None
    source: Optional[str] = None
    categories: list = field(default_factory=list)
    original: Optional[str] = None
    image: Optional[str] = None
    rights: Optional[str] = None


def _strip(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return clean_text(htmllib.unescape(re.sub(r"<[^>]+>", " ", text)))


_RE_H1 = re.compile(r'<h1 class="title">(.*?)</h[12]>', re.S)
_RE_CAPTION = re.compile(r'<div class="wa-content">(.*?)</div>', re.S)
_RE_LI = re.compile(r"<li>\s*(Место съемки|Время съемки|Автор)\s*:\s*(.*?)</li>", re.S)
_RE_SOURCE = re.compile(r"Источник(?: информации о фото)?:\s*(.*?)<br", re.S)
_RE_CATS = re.compile(r'<a href="https://waralbum\.ru/photo/[^"]*" rel="category tag">(.*?)</a>')
_RE_ORIGINAL = re.compile(r'class="yapb_alternative_format"><a href="([^"]+)"')
_RE_IMAGE = re.compile(r'<div class="entry"><img[^>]*?src="([^"]+)"')
_RE_RIGHTS = re.compile(r"(Правообладател\w+ этого фото\s+является.*?)</div>", re.S)


def parse_fragment(pid: int, frag: str) -> Optional[Photo]:
    m = _RE_H1.search(frag)
    if not m:
        return None
    photo = Photo(pid, _strip(m.group(1)))
    cap = _RE_CAPTION.search(frag)
    photo.caption = _strip(cap.group(1)) if cap else None
    for label, value in _RE_LI.findall(frag):
        value = re.sub(r"<noindex>.*?</noindex>", "", value, flags=re.S)
        key = {"Место съемки": "place", "Время съемки": "time", "Автор": "author"}[label]
        setattr(photo, key, _strip(value))
    src = _RE_SOURCE.search(frag)
    photo.source = (_strip(src.group(1)) or "").rstrip(" .") or None if src else None
    photo.categories = [c for c in (_strip(x) for x in _RE_CATS.findall(frag)) if c]
    orig = _RE_ORIGINAL.search(frag)
    photo.original = orig.group(1) if orig else None
    img = _RE_IMAGE.search(frag)
    photo.image = (BASE + img.group(1) if img.group(1).startswith("/") else img.group(1)) if img else None
    rights = _RE_RIGHTS.search(frag)
    photo.rights = _strip(rights.group(1)) if rights else None
    return photo


# --- место -------------------------------------------------------------------

# Страны в последнем звене «Места съемки», целиком вне РИ/СССР в 1939–1945
# годах. Германия, Польша, Финляндия, Румыния, Чехословакия, Венгрия, Япония
# сюда не входят: Восточная Пруссия, Привислинский край, Карельский перешеек,
# Бессарабия, Закарпатье, Южный Сахалин — земли рамки.
FOREIGN = {
    "великобритания", "англия", "шотландия", "франция", "италия", "сша", "бельгия",
    "нидерланды", "голландия", "дания", "норвегия", "греция", "югославия", "болгария",
    "австрия", "швейцария", "испания", "португалия", "албания", "мальта", "египет",
    "ливия", "тунис", "алжир", "марокко", "эфиопия", "сомали", "кения", "судан", "сирия",
    "ливан", "палестина", "ирак", "индия", "бирма", "китай", "филиппины", "индонезия",
    "новая гвинея", "австралия", "новая зеландия", "канада", "исландия", "сингапур",
    "малайзия", "таиланд", "вьетнам", "тихий океан", "атлантический океан", "северная африка",
    "люксембург", "чехия", "словакия", "хорватия", "сербия", "словения", "босния",
}
# Места вне рамки, которые «Военный альбом» называет без страны: у GeoNames
# в рамке есть тёзки (Берлин — село в Челябинской области), и без этого
# списка снимки рейхстага встали бы на Урал.
FOREIGN_PLACES = {
    "берлин", "вена", "будапешт", "прага", "бреслау", "дрезден", "лейпциг", "гамбург", "мюнхен",
    "нюрнберг", "кельн", "штеттин", "потсдам", "торгау", "эльба", "одер", "зееловские высоты",
    "париж", "лондон", "рим", "неаполь", "нормандия", "сицилия", "крит", "белград", "бухарест",
    "плоешти", "яссы", "софия", "афины", "нарвик", "тобрук", "эль-аламейн", "дюнкерк", "арнем",
    "варшава-прага", "братислава", "гданьск", "данциг", "росток", "любек", "бремен", "франкфурт",
    "мадрид", "токио", "хиросима", "нагасаки", "перл-харбор", "иводзима", "окинава", "харбин",
    "мукден", "порт-артур", "дальний", "пекин", "шанхай", "сеул", "пхеньян", "хельсинки",
    "бастонь", "ахен", "реймс", "монте-кассино", "анцио", "салерно", "мальта", "гибралтар",
}
USSR = {"ссср", "россия", "рсфср", "украина", "белоруссия", "беларусь", "латвия", "литва",
        "эстония", "молдавия", "молдова", "грузия", "армения", "азербайджан", "казахстан",
        "узбекистан", "киргизия", "таджикистан", "туркмения", "карелия", "крым"}

_PREFIX = re.compile(
    r"^(?:в\s+)?(?:район[еа]?|окрестност(?:и|ях)|пригород\w*|под|близ|возле|у|около|севернее|южнее|"
    r"западнее|восточнее|г\.|город|ст\.|станция|станции|с\.|село|д\.|деревня|пос\.|поселок|посёлок|"
    r"улиц[аы]|у\s+города)\s+", re.I)


def place_parts(place: Optional[str]) -> list[str]:
    return [p.strip() for p in (place or "").split(",") if p.strip()]


def country_of(place: Optional[str]) -> Optional[str]:
    parts = place_parts(place)
    if len(parts) < 2 and not (parts and parts[0].lower() in FOREIGN | USSR):
        return None
    last = parts[-1].lower().replace("ё", "е")
    return last if last in FOREIGN or last in USSR else None


def is_foreign_place(place: Optional[str]) -> bool:
    keys = place_keys(place)
    return bool(keys) and keys[0] in FOREIGN_PLACES


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().replace("ё", "е")).strip(" .«»\"")


def place_keys(place: Optional[str]) -> list[str]:
    """Возможные имена населённого пункта из первого звена места."""
    parts = place_parts(place)
    if not parts:
        return []
    head = parts[0]
    for _ in range(3):
        new = _PREFIX.sub("", head)
        if new == head:
            break
        head = new
    key = _norm(head)
    out = [key]
    # «район Сталинграда», «под Ржевом»: род. и твор. падеж.
    for suffix, repl in (("ом", ""), ("ем", ""), ("ой", "а"), ("ей", "ь"), ("а", ""), ("я", "ь"),
                         ("ы", "а"), ("и", "а"), ("ого", "ое"), ("ого", "ий")):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            out.append(key[: -len(suffix)] + repl)
    return list(dict.fromkeys(out))


@dataclass
class Place:
    lat: float
    lon: float
    name: str
    source: str
    country: Optional[str] = None


class Gazetteer:
    """Указатель названий из слоёв проекта. Источники в порядке доверия."""

    ORDER = ("occupation_cities", "city_population", "renamed_places", "settlements")

    def __init__(self) -> None:
        self.names: dict[str, list[Place]] = {}

    def add(self, name: Optional[str], lat, lon, source: str, country: Optional[str] = None) -> None:
        if not name or lat is None or lon is None:
            return
        self.names.setdefault(_norm(name), []).append(Place(float(lat), float(lon), name, source,
                                                            country))

    @classmethod
    def load(cls, geojson_dir: Path) -> "Gazetteer":
        g = cls()
        for layer in cls.ORDER:
            path = Path(geojson_dir) / f"{layer}.geojson"
            if not path.exists():
                continue
            for feat in json.loads(path.read_text(encoding="utf-8")).get("features", []):
                lon, lat = feat["geometry"]["coordinates"][:2]
                props = feat.get("properties") or {}
                extra = props.get("extra") or {}
                title = props.get("title") or ""
                if layer == "occupation_cities":
                    g.add(extra.get("name_wartime"), lat, lon, layer)
                    g.add(title.split(":")[0].split(" (")[0], lat, lon, layer)
                    inner = re.search(r"\(([^)]+)\)", title.split(":")[0])
                    if inner:
                        g.add(inner.group(1), lat, lon, layer)
                elif layer == "city_population":
                    g.add((extra.get("name_match") or {}).get("name_ru"), lat, lon, layer)
                    g.add(title.split(":")[0], lat, lon, layer)
                elif layer == "renamed_places":
                    g.add(extra.get("old_name"), lat, lon, layer)
                    g.add(extra.get("new_name"), lat, lon, layer)
                else:
                    g.add(title, lat, lon, layer, extra.get("country"))
        return g

    def locate(self, place: Optional[str], km: float = 30.0, *, strict: bool = False
               ) -> Optional[Place]:
        """Однозначная точка по первому звену места или None.

        `strict` — место названо с областью или районом («Ивановская обл.,
        пос. Каменка»): тогда тёзок ищут во всех слоях указателя, а не только
        в первом по доверию, — иначе посёлок встаёт в одноимённый город
        другой области.
        """
        country = country_of(place)
        if country in FOREIGN or is_foreign_place(place):
            return None
        parts = place_parts(place)
        if country and len(parts) == 1:
            return None          # «Латвия, СССР» без города — страна, не место
        for key in place_keys(place):
            cands = self.names.get(key)
            if not cands:
                continue
            for source in self.ORDER:
                pool = [c for c in cands if c.source == source]
                if source == "settlements" and country:
                    # Страна названа: тёзка из GeoNames годится только из неё же.
                    pool = [c for c in pool if c.country and (
                        c.country.lower() == country or (country in USSR and c.country.lower() in USSR))]
                if not pool:
                    continue
                first = pool[0]
                check = cands if strict else pool
                if all(haversine_km(first.lat, first.lon, c.lat, c.lon) <= km for c in check):
                    return first
                return None      # неоднозначно: тёзки в разных местах
        return None


def records(photos: Iterable[Photo], gaz: Optional[Gazetteer], spec: LayerSpec = WARALBUM
            ) -> tuple[list[ContextRecord], dict]:
    out: list[ContextRecord] = []
    skipped = {"без года": 0}
    for photo in photos:
        dating = photo_years(photo.time) if photo.time else None
        if dating is None:
            skipped["без года"] += 1
            continue
        lo, hi, precision, approx, raw = dating
        point = gaz.locate(photo.place) if gaz and photo.place else None
        country = country_of(photo.place)
        extra: dict = {}
        if photo.categories:
            extra["categories"] = photo.categories
        if photo.source:
            extra["photo_source"] = photo.source
        if photo.rights:
            extra["rights"] = photo.rights
        if photo.original:
            extra["original"] = photo.original
        if point:
            confidence = "place_level"
            extra["coord_source"] = f"{point.source}: «{point.name}»"
        elif country in FOREIGN or is_foreign_place(photo.place):
            confidence = "outside_bbox"
            extra["frame_by"] = "по месту вне РИ/СССР в «Месте съемки» (точки нет)"
        else:
            confidence = "no_coords"
        out.append(spec.new_record(
            title=photo.title or "Фотография",
            category="фотография",
            lat=point.lat if point else None,
            lon=point.lon if point else None,
            place_text=photo.place,
            year_from=lo, year_to=hi,
            date_precision=precision,
            date_approx=approx or hi > lo,
            period_raw=raw,
            actor=photo.author,
            summary=photo.caption if photo.caption and photo.caption != photo.title else None,
            url=f"{BASE}/{photo.id}/",
            image_url=photo.image,
            source_id=str(photo.id),
            confidence=confidence,
            extra=extra,
        ))
    return out, skipped
