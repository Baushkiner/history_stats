"""Старые привязанные карты на место и год: Retromap, ЭтоМесто, Kartenforum SLUB.

Зачем этот слой. Тот же вопрос, что у `topo_maps`, только шире: какая старая
карта есть на это место и какого она года — план города 1850-х, карта уезда
Менде, трёхвёрстка, план губернского города. На retromap.ru и etomesto.ru
такие карты собраны тысячами и уже привязаны к местности — их можно открыть
поверх нынешней карты и сравнить, но найти нужную можно только поиском по
сайту. Слой делает из них подбор: у карты — рамка или точка, год, масштаб,
название и ссылка.

**Тайлы и сканы не копируются.** Привязанная карта — чужая работа целиком;
слой хранит только сведения о карте и ссылку на неё. Согласие владельцев
сайтов на сбор каталога сообщено владельцем проекта 24.11.2026.

Три источника, у каждого своя точка.

* **Retromap** (retromap.ru). Перечень карт — строка `dbase_cache` в
  `js/gallery_map_list.js`: код карты `mcode` с приставкой из пяти знаков
  (тип, метка, рейтинг, масштаб). Первые две цифры кода — раздел сайта:
  00–04 — нынешние онлайн-карты (не берутся), 05–11 — Москва по эпохам,
  12 — тематические, 13 — части города, 14 — регионы России, 15 — зарубежье,
  16 — карты мира. Сведения о картах отдаёт `db/read_mcodes.php` — тот же
  вызов, которым их читает сам сайт: название с годом впереди («1855 План
  Столичнаго города Москвы 1:25K»), рамка `bounds` (юг, запад, север,
  восток), масштаб, библиографическая подпись. Точка записи — центр рамки,
  рамка — в `extra.bbox`, как у `topo_maps` (`confidence = sheet_center`).
  Страницы карт сайт показывает только после проверки «Я не робот» — её
  сборщик не проходит и не обходит: страницы не запрашиваются, ссылка в
  записи ведёт на страницу карты для человека.
* **ЭтоМесто** (etomesto.ru, отвечает с etomesto.com). Карты разложены по
  региональным разделам (`/<раздел>/maps.php`, по 15 на странице); у карты —
  страница `/map-<имя>/` с названием, годом, типом и коротким описанием. Рамки
  охвата на странице нет: точка — центр раздела (город или регион, к
  которому карта отнесена), и запись помечена `place_level`. Сайт отвечает с
  перебоями — сборщик повторяет запрос и продолжает с места. Карты нынешних
  исторических атласов (`atlas_…`, «Русь в 862–1054 годах») не берутся: год
  у них изображаемый, а не год карты.
* **Virtuelles Kartenforum SLUB** (kartenforum.slub-dresden.de, Deutsche
  Fotothek). Открытый поисковый индекс каталога (`search.kartenforum…/vk20`):
  у карты — контур привязки, годы, масштаб, тип, постоянная ссылка. В рамке
  РИ/СССР около 850 карт — в основном Messtischblätter Восточной Пруссии и
  Польши и немецкие топографические карты западной России.

Каталог David Rumsey (LUNA) в слой не взят: у записей LUNA нет ни рамки, ни
координат — только название, дата и «World Area»; привязанные карты Rumsey
живут в Georeferencer, у которого открытого каталога с рамками нет.

Годы. Год карты — как его даёт источник: у Retromap — число в начале
названия, у ЭтоМесто — год карты на странице, у SLUB — `time_period_start`
и `time_period_end`. Берутся карты не позже 1960 года — горизонта проекта.
"""

from __future__ import annotations

import html
import json
import re
from typing import Iterable, Optional

from ..schema import ContextRecord, LayerSpec, clean_text

YEAR_MAX = 1960
YEAR_MIN = 1400
CONFIDENCE_SHEET = "sheet_center"

CONSENT = ("собрано с согласия владельца, полученного владельцем проекта (сообщено "
           "24.11.2026); тайлы и сканы не копируются — в слое название, год, масштаб, "
           "охват и ссылка")

OLD_MAPS = LayerSpec(
    slug="old_maps",
    title="Старые привязанные карты на место и год (Retromap, ЭтоМесто, SLUB)",
    group="culture",
    source="Retromap (retromap.ru); ЭтоМесто (etomesto.ru); Virtuelles Kartenforum "
           "SLUB Dresden / Deutsche Fotothek",
    license="© владельцев сайтов и правообладателей карт; " + CONSENT,
    description=(
        "Какая старая карта с привязкой есть на это место и какого она года: планы "
        "городов, карты уездов и губерний, топографические листы до 1960 года из "
        "каталогов Retromap, ЭтоМесто и Kartenforum SLUB — с рамкой охвата или точкой "
        "раздела, годом, масштабом и ссылкой, по которой карту можно открыть поверх "
        "нынешней. Сами карты не копируются."
    ),
    url="https://retromap.ru/",
    status="harvested",
    expected_rows=5447,          # 24.11.2026: Retromap 4 788, ЭтоМесто 368 (4 раздела из 83), SLUB 291
)


class OldMapsError(RuntimeError):
    """Каталог не достался или пришёл не в том виде."""


def _deg(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def scale_label(value: Optional[int]) -> Optional[str]:
    return f"1:{value:,}".replace(",", " ") if value else None


def coverage(box: Optional[tuple]) -> str:
    """Охват по рамке: план города, окрестности, область, обзорная карта."""
    if not box:
        return "охват не указан"
    w, s, e, n = box
    span = max(e - w, n - s)
    if span < 0.5:
        return "план города или местности"
    if span < 2.5:
        return "карта окрестностей, уезда"
    if span < 10:
        return "карта губернии, области"
    return "обзорная карта"


def bbox_text(box: tuple) -> str:
    w, s, e, n = box
    return f"охват {_deg(s)}–{_deg(n)}° с. ш., {_deg(w)}–{_deg(e)}° в. д."


def _record(*, source_key: str, title: str, box: Optional[tuple],
            lat: Optional[float], lon: Optional[float], year_from: Optional[int],
            year_to: Optional[int], approx: bool, period_raw: Optional[str],
            scale: Optional[int], summary: list, url: str, source_id: str, source: str,
            license: str, confidence: str, actor: Optional[str] = None,
            extra: Optional[dict] = None) -> ContextRecord:
    category = coverage(box) if box else "карта раздела сайта"
    parts = [p for p in summary if p]
    label = scale_label(scale)
    if label:
        parts.append(f"масштаб {label}")
    if box:
        parts.append(bbox_text(box))
    extra = dict(extra or {})
    extra.update(catalog=source_key, scale=scale,
                 bbox=[round(x, 4) for x in box] if box else None)
    text = "; ".join(parts)
    text += " " if text.endswith(".") else ". "
    return OLD_MAPS.new_record(
        title=title, category=category, lat=lat, lon=lon,
        year_from=year_from, year_to=year_to,
        date_precision=("unknown" if year_from is None else "century"
                        if year_to - year_from == 99 and year_from % 100 == 1 else "year"),
        date_approx=approx, period_raw=period_raw, actor=actor, work=title,
        summary=text + f"Карта не скопирована — открыть по ссылке ({source})",
        url=url, source=source, source_id=source_id, license=license,
        confidence=confidence if lat is not None else "no_coords",
        extra={k: v for k, v in extra.items() if v not in (None, "", [])},
    )


# --- Retromap ---------------------------------------------------------------

RETROMAP = "Retromap (retromap.ru)"
RETROMAP_LIST_URL = "https://retromap.ru/js/gallery_map_list.js"
RETROMAP_DB_URL = "https://retromap.ru/db/read_mcodes.php"
RETROMAP_MAP_URL = "https://retromap.ru/{mcode}"
RETROMAP_LICENSE = "© Retromap (retromap.ru) и правообладатели карт; " + CONSENT
# Раздел сайта по первым двум цифрам кода карты (`map_class_name` в functions.js).
RETROMAP_CLASSES = {
    5: "Москва, 1945–2000-е", 6: "Москва, 1918–1940-е", 7: "Москва, 1900–1917",
    8: "Москва, XIX век", 9: "Москва, XVIII век", 10: "Москва в древности",
    11: "Москва, Генплан 2025", 12: "тематические карты", 13: "части города",
    14: "регионы России", 15: "зарубежье", 16: "карты мира", 24: "прочие карты",
}
RETROMAP_FIRST_OLD = 5            # 00–04 — нынешние онлайн-карты
_RE_DBASE = re.compile(r"var\s+dbase_cache\s*=\s*'([^']*)'")
_RE_LEAD_YEAR = re.compile(r"^\s*(\d{3,4})(?:\s*[-–]\s*(\d{2,4}))?\s+(.*)$", re.S)
_RE_SCALE_K = re.compile(r"\s*1\s*:\s*([\d.,]+)\s*([KkКкMmМм])?\s*$")


_RE_CENTURY = re.compile(r"^\s*([IVX]{1,5})\s+век\s+(.*)$", re.S)


def _roman(text: str) -> Optional[int]:
    values = {"I": 1, "V": 5, "X": 10}
    total = 0
    for a, b in zip(text, text[1:] + " "):
        v = values[a]
        total += -v if values.get(b, 0) > v else v
    return total if 10 <= total <= 20 else None


def retromap_mcodes(js: str) -> list[str]:
    """Коды старых карт из `gallery_map_list.js`: приставка в пять знаков отрезается."""
    m = _RE_DBASE.search(js or "")
    if not m:
        raise OldMapsError("в gallery_map_list.js нет строки dbase_cache — сайт сменился")
    out, seen = [], set()
    for code in m.group(1).split():
        mcode = code[5:].removesuffix(".jpg")
        if len(mcode) < 4 or not mcode[:2].isdigit() or int(mcode[:2]) < RETROMAP_FIRST_OLD:
            continue
        if mcode not in seen:
            seen.add(mcode)
            out.append(mcode)
    return out


def retromap_years(name: str, mcode: str) -> tuple[Optional[int], Optional[int], str]:
    """(от, до, название без года) — год стоит в начале названия; запасной — в коде."""
    m = _RE_LEAD_YEAR.match(name or "")
    if m:
        a = int(m.group(1))
        b = m.group(2)
        if b:
            b = int(b) if len(b) == 4 else int(str(a)[: 4 - len(b)] + b)
        else:
            b = a
        if YEAR_MIN <= a <= 2100 and a <= b:
            return a, b, m.group(3).strip()
    m = _RE_CENTURY.match(name or "")
    if m:
        century = _roman(m.group(1))
        if century:
            return (century - 1) * 100 + 1, century * 100, m.group(2).strip()
    digits = mcode[2:6]
    if digits.isdigit() and YEAR_MIN <= int(digits) <= 2100:
        return int(digits), int(digits), (name or "").strip()
    return None, None, (name or "").strip()


def retromap_scale(entry: dict, name: str) -> tuple[Optional[int], str]:
    """Масштаб: поле `s`, иначе хвост названия («1:25K» → 25 000). Хвост отрезается."""
    scale = None
    m = _RE_SCALE_K.search(name)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        mult = {"k": 1000, "к": 1000, "m": 1_000_000, "м": 1_000_000}.get(
            (m.group(2) or "").lower(), 1)
        if digits:
            scale = int(digits) * mult
        name = name[: m.start()].strip()
    try:
        s = int(float(entry.get("s") or 0))
    except (TypeError, ValueError):
        s = 0
    return (s or scale or None), name


def parse_bounds(text: Optional[str]) -> Optional[tuple]:
    """«юг,запад,север,восток» → (запад, юг, восток, север); вся Земля — None."""
    try:
        s, w, n, e = (float(x) for x in str(text or "").split(","))
    except ValueError:
        return None
    if not (-90 <= s < n <= 90 and -180 <= w < e <= 180):
        return None
    if n - s > 150 or e - w > 300:
        return None
    return (w, s, e, n)


def retromap_record(mcode: str, entry: dict) -> Optional[ContextRecord]:
    raw = html.unescape(clean_text(entry.get("n")) or "")
    year_from, year_to, name = retromap_years(raw, mcode)
    if year_from is None or year_from > YEAR_MAX:
        return None
    scale, name = retromap_scale(entry, name)
    box = parse_bounds(entry.get("bounds"))
    lat = lon = None
    if box:
        lat, lon = round((box[1] + box[3]) / 2, 5), round((box[0] + box[2]) / 2, 5)
    period = str(year_from) if year_from == year_to else f"{year_from}–{year_to}"
    section = RETROMAP_CLASSES.get(int(mcode[:2]))
    caption = html.unescape(clean_text(entry.get("caption")) or "")
    summary = [f"Привязанная карта на Retromap, {period}"]
    if section:
        summary.append(f"раздел сайта — {section}")
    keywords = html.unescape(clean_text(entry.get("keywords")) or "")
    return _record(
        source_key="retromap", title=f"{name or 'Карта'}, {period}", box=box, lat=lat,
        lon=lon, year_from=year_from, year_to=year_to, approx=False, period_raw=raw,
        scale=scale, summary=summary, url=RETROMAP_MAP_URL.format(mcode=mcode),
        source_id=f"retromap:{mcode}", source=RETROMAP, license=RETROMAP_LICENSE,
        confidence=CONFIDENCE_SHEET,
        extra={"caption": caption[:200] or None, "keywords": keywords or None,
               "section": section, "mcode": mcode},
    )


def retromap_records(entries: dict) -> list[ContextRecord]:
    return [r for r in (retromap_record(k, v) for k, v in sorted(entries.items()))
            if r is not None]


# --- SLUB Kartenforum ---------------------------------------------------------

SLUB = "Virtuelles Kartenforum, SLUB Dresden / Deutsche Fotothek"
SLUB_SEARCH_URL = "https://search.kartenforum.slub-dresden.de/vk20/_search"
SLUB_LICENSE = ("© SLUB Dresden / Deutsche Fotothek (права на сканы — по карточке Deutsche "
                "Fotothek); " + CONSENT)
SLUB_TYPES = {"mtb": "Messtischblatt", "tk": "топографическая карта",
              "ak": "старая карта", "gl": "геологическая карта"}


def slub_query(box: tuple, size: int = 2000) -> dict:
    """Запрос к индексу: карты, чей контур пересекает рамку (запад, юг, восток, север)."""
    w, s, e, n = box
    return {"size": size, "sort": [{"file_name": "asc"}],
            "query": {"bool": {"filter": [{"geo_shape": {"geometry": {
                "shape": {"type": "envelope", "coordinates": [[w, n], [e, s]]},
                "relation": "intersects"}}}]}}}


def _ring_box(geometry: Optional[dict]) -> Optional[tuple]:
    coords = []

    def walk(x):
        if isinstance(x, (list, tuple)) and x and isinstance(x[0], (int, float)):
            coords.append(x)
        elif isinstance(x, (list, tuple)):
            for y in x:
                walk(y)
    walk((geometry or {}).get("coordinates"))
    if not coords:
        return None
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def _year(text: Optional[str]) -> Optional[int]:
    m = re.match(r"^\s*(-?\d{4})", str(text or ""))
    return int(m.group(1)) if m else None


def slub_record(hit: dict) -> Optional[ContextRecord]:
    src = hit.get("_source") or {}
    year_from = _year(src.get("time_period_start")) or _year(src.get("time_published"))
    year_to = _year(src.get("time_period_end")) or year_from
    if year_from is None or year_from > YEAR_MAX:
        return None
    box = _ring_box(src.get("geometry"))
    lat = lon = None
    if box:
        lat, lon = round((box[1] + box[3]) / 2, 5), round((box[0] + box[2]) / 2, 5)
    title = clean_text(src.get("title")) or "Карта"
    period = str(year_from) if year_from == year_to else f"{year_from}–{year_to}"
    kind = SLUB_TYPES.get(src.get("map_type"), f"тип в каталоге — {src.get('map_type')}")
    try:
        scale = int(src.get("map_scale") or 0) or None
    except (TypeError, ValueError):
        scale = None
    wms = next((r.get("url") for r in src.get("online_resources") or []
                if r.get("type") == "WMS"), None)
    map_id = str(src.get("map_id") or hit.get("_id") or "")
    return _record(
        source_key="slub", title=f"{title}, {period}", box=box, lat=lat, lon=lon,
        year_from=year_from, year_to=year_to, approx=False,
        period_raw=f"{src.get('time_period_start')} — {src.get('time_period_end')}",
        scale=scale, summary=[f"Привязанная карта в Kartenforum SLUB ({kind}), {period}"],
        url=src.get("permalink") or src.get("slub_url") or "https://kartenforum.slub-dresden.de/",
        source_id=f"slub:{map_id.rsplit(':', 1)[-1]}", source=SLUB, license=SLUB_LICENSE,
        confidence=CONFIDENCE_SHEET,
        extra={"map_type": src.get("map_type"), "wms": wms,
               "title_long": clean_text(src.get("title_long")) or None},
    )


def slub_records(payload: dict) -> list[ContextRecord]:
    hits = (payload.get("hits") or {}).get("hits") or []
    return [r for r in (slub_record(h) for h in hits) if r is not None]


# --- ЭтоМесто -----------------------------------------------------------------

ETOMESTO = "ЭтоМесто (etomesto.ru)"
ETOMESTO_BASE = "https://etomesto.com"
ETOMESTO_LICENSE = "© ЭтоМесто (etomesto.ru) и правообладатели карт; " + CONSENT
ETOMESTO_PAGE = 15
# «atlas_…» — карты нынешних исторических атласов («Русь в 862–1054 годах»):
# год у них — изображаемый, а не год карты; в слой не идут.
ETOMESTO_SKIP = ("atlas_",)
_RE_SECTION = re.compile(r'href=["\']?/([a-z][a-z0-9_-]*)/catalog\.php')
_RE_ROW = re.compile(
    r"<a href=/map-([^/\s>]+)/ class=bb><big>(.*?)</big></a>.*?god=(\d+)", re.S)
_RE_CX = re.compile(r"var cxmap=(-?[\d.]+)")
_RE_CY = re.compile(r"var cymap=(-?[\d.]+)")
_RE_MAPID = re.compile(r"var mapID = (\d+)")
_RE_YEAR_TIP = re.compile(r"&year=(\d+)&tip=(\d+)")
_RE_TITLE = re.compile(r"<title>([^<]*)</title>")
_RE_READ = re.compile(r"<div class=read[^>]*>(.*?)(?:<p>|</div>)", re.S)
_RE_TAG = re.compile(r"<[^>]+>")


def etomesto_sections(html_text: str) -> list[str]:
    """Региональные разделы сайта: `/<раздел>/catalog.php` → «<раздел>»."""
    return sorted(set(_RE_SECTION.findall(html_text or "")))


def etomesto_rows(html_text: str) -> list[dict]:
    """Строки страницы списка: имя карты, название, год."""
    out = []
    for slug, title, year in _RE_ROW.findall(html_text or ""):
        out.append({"slug": slug, "title": html.unescape(_RE_TAG.sub("", title)).strip(),
                    "year": int(year)})
    return out


def etomesto_page(html_text: str) -> dict:
    """Страница карты → {title, year, tip, map_id, lat, lon, text}."""
    def first(rx):
        m = rx.search(html_text or "")
        return m.group(1) if m else None
    title = html.unescape(first(_RE_TITLE) or "").removesuffix(" - Это Место").strip()
    yt = _RE_YEAR_TIP.search(html_text or "")
    text = first(_RE_READ)
    text = re.sub(r"\s+", " ", html.unescape(_RE_TAG.sub(" ", text or ""))).strip()
    lat, lon = first(_RE_CY), first(_RE_CX)
    return {"title": title or None, "year": int(yt.group(1)) if yt else None,
            "tip": int(yt.group(2)) if yt else None, "map_id": first(_RE_MAPID),
            "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
            "text": text[:250] or None}


def etomesto_record(slug: str, row: dict, page: dict) -> Optional[ContextRecord]:
    year = page.get("year") or row.get("year")
    if year is None or not (YEAR_MIN <= year <= YEAR_MAX) or slug.startswith(ETOMESTO_SKIP):
        return None
    title = page.get("title") or row.get("title") or slug
    lat, lon = page.get("lat"), page.get("lon")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = lon = None
    summary = [f"Привязанная карта на ЭтоМесто, {year}"]
    if page.get("text"):
        summary.append(page["text"].rstrip(". "))
    summary.append("точка — центр раздела сайта, к которому отнесена карта, а не рамка карты")
    return _record(
        source_key="etomesto", title=title if str(year) in title else f"{title}, {year}",
        box=None, lat=lat, lon=lon, year_from=year, year_to=year, approx=False,
        period_raw=str(year), scale=None, summary=summary,
        url=f"https://etomesto.ru/map-{slug}/", source_id=f"etomesto:{slug}",
        source=ETOMESTO, license=ETOMESTO_LICENSE, confidence="place_level",
        extra={"section": row.get("section"), "map_id": page.get("map_id"),
               "slug": slug},
    )


def etomesto_records(rows: Iterable[dict], pages: dict) -> list[ContextRecord]:
    out, seen = [], set()
    for row in rows:
        slug = row["slug"]
        if slug in seen or slug not in pages:
            continue
        seen.add(slug)
        rec = etomesto_record(slug, row, pages[slug])
        if rec is not None:
            out.append(rec)
    return out


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
