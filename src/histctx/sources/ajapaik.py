"""Старые снимки Ajapaik (ajapaik.ee) с краудсорсинговой геопривязкой.

Зачем этот слой. Ajapaik — проект Эстонского общества фотографического
наследия (MTÜ Ajapaik, Vahur Puik): снимки из музеев Эстонии (MuIS, Fotis
Национального архива), Финляндии (Finna) и других собраний, которым
пользователи ставят точку и направление съёмки. Для Эстонии и Лифляндии это
то же, чем PastVu служит остальной стране: улица, мыза, кирха, хутор в год
записи в метрической книге. Права: снимки — у музеев и авторов (часть под
открытыми лицензиями), метаданные — проекта; собрано с согласия владельца,
полученного владельцем проекта (сообщено 24.11.2026).

Как достаются данные. Документированный `GET /bbox/v1/` (рамка `sw-lat` …
`ne-lon`, поля `date`, `author`, `lat`, `lon`) и `/map-data/` 24.11.2026 не
годились для обхода: первый на любой рамке отвечает 502 через 14–17 секунд,
второй отдаёт только номер, точку и подпись (без даты и автора) и требует
POST с CSRF. Ответил быстро другой метод API — `GET /api/v1/album/nearest/`
без альбома: снимки по удалённости от точки, `start` и `limit` листают выдачу,
поле на снимок — как у `PhotoSerializer` (`title`, `date`, `author`,
`source`, `latitude`, `longitude`, `azimuth`). Обход идёт от центра Таллина
страницами по 500 до первой страницы без координат: снимки без точки
сортируются в конец. 500 снимков отдаются за 3–12 секунд (чем дальше, тем
дольше: сервер считает смещение).

Оговорка о полноте. Порядок «по удалённости» не уникален: у снимков в одной
точке расстояние одинаковое, и на стыке страниц такой снимок может попасть
на обе или ни на одну. Повторы сводятся по номеру; пропуски видны только
сверкой с другим путём (`/map-data/` по рамке), и `--check` её делает на
одной рамке.

Датировка. `date` приходит либо днём («17-08-1938», когда в базе есть
дата), либо текстом из музея («1930», «1920-1930», «u 1935», «[arvatav aeg
17.8.1998]»). Год без даты иногда стоит в подписи («… 19.apr. 1977.a.») — он
берётся с `date_approx` и пометкой `extra.date_from = "подпись"`. Снимок без
года в слой не идёт, как и в PastVu: на ленту времени его не поставить.
Горизонт — 1960 год (`YEAR_MAX`).
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Iterable, Iterator, Optional

from ..schema import ContextRecord, LayerSpec, clean_text
from .photo_common import CONSENT, YEAR_MAX, Fetcher

BASE = "https://ajapaik.ee"
NEAREST = BASE + "/api/v1/album/nearest/?latitude={lat}&longitude={lon}&limit={limit}&start={start}"
# Центр обхода — Ратушная площадь Таллина: самая густая точка базы, и от неё
# удалённость растёт сначала по Эстонии, потом по Финляндии и дальше.
CENTER = (59.437, 24.745)
PAGE = 500

KEEP = ("id", "title", "date", "author", "source", "latitude", "longitude", "azimuth")

AJAPAIK = LayerSpec(
    slug="photos_ajapaik",
    title="Старые фотографии (Ajapaik)",
    group="culture",
    source="Ajapaik, ajapaik.ee (MTÜ Ajapaik; снимки музеев Эстонии, Финляндии и др.)",
    license=("снимки — права музеев и авторов, у части открытые лицензии; метаданные и "
             "геопривязка — Ajapaik; " + CONSENT),
    description=(
        "Снимки из музеев Эстонии и Финляндии с точкой съёмки, поставленной пользователями "
        "Ajapaik: для Эстляндии, Лифляндии и Финляндии — то же, что PastVu для остальной страны."
    ),
    url="https://ajapaik.ee/",
    status="harvested",
)


class AjapaikError(RuntimeError):
    pass


def page_path(cache: Path, start: int) -> Path:
    return cache / "nearest" / f"{start:07d}.json.gz"


def slim(photo: dict) -> dict:
    """Из ответа — только поля слоя: ссылки на ретушь и повторные снимки не нужны."""
    return {k: photo.get(k) for k in KEEP}


def fetch_pages(cache: Path, *, fetcher: Optional[Fetcher] = None, limit_pages: Optional[int] = None,
                center: tuple = CENTER, page: int = PAGE, log=print) -> int:
    """Листает выдачу по удалённости, страница за страницей, с продолжением с места.

    Возвращает число страниц в кэше. Конец — страница короче `page` или без
    единой точки (снимки без координат идут после всех с координатами).
    """
    fetcher = fetcher or Fetcher(pause=1.0, timeout=180)
    start, done = 0, 0
    while True:
        path = page_path(cache, start)
        if path.exists():
            photos = json.loads(gzip.decompress(path.read_bytes()))
        else:
            if limit_pages is not None and done >= limit_pages:
                break
            url = NEAREST.format(lat=center[0], lon=center[1], limit=page, start=start)
            payload = json.loads(fetcher.get(url))
            if payload.get("error") not in (0, None):
                raise AjapaikError(f"{url}: error={payload.get('error')}")
            photos = [slim(p) for p in payload.get("photos") or []]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps(photos, ensure_ascii=False).encode("utf-8")))
            done += 1
            located = sum(1 for p in photos if p.get("latitude") is not None)
            if done % 20 == 1:
                log(f"  start={start}: {len(photos)} снимков, с точкой {located}")
        if len(photos) < page or not any(p.get("latitude") is not None for p in photos):
            break
        start += page
    return len(list((cache / "nearest").glob("*.json.gz")))


def load_pages(cache: Path) -> Iterator[dict]:
    for path in sorted((cache / "nearest").glob("*.json.gz")):
        yield from json.loads(gzip.decompress(path.read_bytes()))


_RE_YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20[0-2]\d)(?!\d)")
_RE_DMY = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
_RE_DECADE = re.compile(r"(?<!\d)(1[89]\d)(?:0[-\s]?(?:ndad|ndate|ndatel|luku|luvulla|s)\b|-?\?)", re.I)
# «u», «umbes» (эст.), «noin», «n.» (фин.), «ca», «arvatav» (предположительно), «?».
_RE_APPROX = re.compile(r"\b(?:u\.?|umbes|noin|n\.|ca\.?|circa|arvatav\w*|oletatav\w*)(?=\s|\d|$)|\?",
                        re.I)


def years(date: Optional[str], title: Optional[str] = None, *, year_max: int = YEAR_MAX):
    """(год от, год до, точность, приблизительно, исходник, откуда) или None."""
    raw = clean_text(date)
    if raw:
        m = _RE_DMY.match(raw)
        if m:
            y = int(m[3])
            return (y, y, "day", False, raw, "date") if y <= year_max else None
        dec = _RE_DECADE.search(raw)
        if dec:
            lo = int(dec[1]) * 10
            return _cap(lo, lo + 9, "decade", bool(_RE_APPROX.search(raw)), raw, "date", year_max)
        found = [int(y) for y in _RE_YEAR.findall(raw)]
        if found:
            # «[arvatav aeg 17.8.1998]» и «u 1935» — приблизительно; две и
            # больше даты — интервал, как «1920-1930».
            return _cap(min(found), max(found), "year", bool(_RE_APPROX.search(raw)), raw,
                        "date", year_max)
    text = clean_text(title)
    if text:
        found = sorted({int(y) for y in _RE_YEAR.findall(text)})
        if found:
            return _cap(found[0], found[-1], "year", True, ", ".join(map(str, found)),
                        "подпись", year_max)
    return None


def _cap(lo, hi, precision, approx, raw, origin, year_max):
    if lo > year_max:
        return None
    return lo, min(hi, year_max), precision, approx, raw, origin


def records(photos: Iterable[dict], spec: LayerSpec = AJAPAIK) -> tuple[list[ContextRecord], dict]:
    """Записи слоя и счёт отброшенного: без точки, без года, за горизонтом."""
    out: list[ContextRecord] = []
    seen: set = set()
    skipped = {"повтор": 0, "без точки": 0, "без года или позже горизонта": 0}
    for photo in photos:
        pid = photo.get("id")
        if pid is None or pid in seen:
            skipped["повтор"] += pid is not None
            continue
        seen.add(pid)
        lat, lon = photo.get("latitude"), photo.get("longitude")
        if lat is None or lon is None:
            skipped["без точки"] += 1
            continue
        dating = years(photo.get("date"), photo.get("title"))
        if dating is None:
            skipped["без года или позже горизонта"] += 1
            continue
        lo, hi, precision, approx, raw, origin = dating
        text = clean_text(photo.get("title")) or "Фотография"
        title = text if len(text) <= 200 else text[:197].rstrip() + "…"
        source = photo.get("source") or {}
        extra: dict = {}
        if source.get("name"):
            extra["source_name"] = clean_text(source["name"])
        if source.get("url"):
            extra["source_url"] = source["url"]
        if photo.get("azimuth") is not None:
            extra["azimuth"] = round(float(photo["azimuth"]), 1)
        if origin == "подпись":
            extra["date_from"] = "подпись"
        out.append(spec.new_record(
            title=title,
            category="фотография",
            lat=float(lat), lon=float(lon),
            year_from=lo, year_to=hi,
            date_precision=precision,
            date_approx=approx or hi > lo,
            period_raw=raw,
            actor=clean_text(photo.get("author")),
            summary=text if len(text) > 200 else None,
            url=f"{BASE}/photo/{pid}/",
            image_url=f"{BASE}/photo-thumb/{pid}/800/",
            source_id=str(pid),
            extra=extra,
        ))
    return out, skipped
