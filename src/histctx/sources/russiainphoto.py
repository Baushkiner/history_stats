"""«История России в фотографиях» (russiainphoto.ru, Мультимедиа Арт Музей).

Зачем этот слой. Около 215 тысяч снимков 1840–1999 годов из музейных и
частных собраний: у каждого — название, датировка («1870 - 1887»), автор или
ателье и «Место съемки» («г. Москва», «Тверская губ., Старицкий у.»). Для
генеалогии это портреты из местных ателье, виды улиц, усадеб, сёл, заводов
того времени и того места, где жили предки. Права на снимки — у музеев и
правообладателей (у части снимков на странице стоит CC BY 4.0); собрано с
согласия владельца, полученного владельцем проекта (сообщено 24.11.2026).

Откуда приложение берёт данные (вкладка сети браузера, разбор
`/static/dist/front.js`, 24.11.2026). Публичного REST нет (`/rest/` — 404),
но у страниц три рабочих адреса:

* `GET /search/ajax/?page=N&page_size=K` — выдача поиска JSON-ом, снимки в
  `html.photos` разметкой: номер (`data-id`), название, годы, автор, подпись
  `alt` = «название, годы, место», уменьшенная копия. Без фильтров это весь
  каталог (поле `total`: 215 084), `page_size` сервер принимает до 1000 —
  весь каталог за 216 запросов. Порядок выдачи постоянный.
* `GET /rest/front/map-grid/?bounds=С,З,Ю,В` — карта: снимки с точкой внутри
  рамки, сгруппированные по геохешу (`geohash`, `photos_count`, средняя точка
  `lat`/`lon`, номер одного снимка). Длина геохеша зависит от размера рамки:
  рамка в градус — 4 знака, в сотую градуса — 6–8.
* `GET /search/ajax/?geohash=G&page_size=K` — снимки одной ячейки геохеша.

Своих координат у снимка в выдаче нет, поэтому точка берётся из карты
(`crawl_grid`): рамка делится по ячейкам, пока ячейка не станет одиночной
(`photos_count = 1` — тогда средняя точка и есть точка снимка, а номер
снимка дан, `confidence = ok`) или не сузится до 5 знаков геохеша (около
5 × 5 км) — тогда снимки ячейки берутся третьим адресом, и точка у них
общая, средняя по ячейке (`place_level`). Снимок вне карты остаётся в слое без точки (`no_coords`), с текстом
места в `place_text`.
"""

from __future__ import annotations

import gzip
import html as htmllib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from ..schema import ContextRecord, LayerSpec, clean_text
from .photo_common import CONSENT, Fetcher, photo_years

BASE = "https://russiainphoto.ru"
SEARCH = BASE + "/search/ajax/?page={page}&page_size={size}"
CELL = BASE + "/search/ajax/?geohash={gh}&page={page}&page_size={size}"
GRID = BASE + "/rest/front/map-grid/?bounds={n},{w},{s},{e}"
PAGE = 1000
# Лист — ячейка в 5 знаков геохеша (около 4,9 × 4,9 км). Шесть знаков (1,2 ×
# 0,6 км) втрое удлиняли обход — 24.11.2026 карта отвечала по 4–5 секунд
# на запрос, — а точность почти не прибавляли: сайт сам ставит большинство
# снимков в центр города («г. Москва»).
LEAF_PRECISION = 5
# Сервер не принимает широту ±90 (500 и 400): рамка мира — до ±85. Всю
# рамку сразу он тоже не считает (пустой ответ), поэтому обход мира
# начинается с плиток 30 × 60 градусов — на таких карта отвечает.
WORLD = (85.0, -180.0, -85.0, 180.0)


def world_tiles() -> list[tuple]:
    bands = [(85.0, 55.0), (55.0, 25.0), (25.0, -5.0), (-5.0, -35.0), (-35.0, -60.0), (-60.0, -85.0)]
    tiles = [(n, w, s, w + 60.0) for n, s in bands for w in range(-180, 180, 60)]
    # Обход — стеком, с конца: плитки РИ/СССР (север, восточное полушарие)
    # ставятся последними, чтобы пройти первыми.
    return sorted(tiles, key=lambda t: (t[0] > 25.0 and t[3] > 0.0, t[0]))

RUSSIAINPHOTO = LayerSpec(
    slug="photos_russiainphoto",
    title="История России в фотографиях",
    group="culture",
    source="russiainphoto.ru (Мультимедиа Арт Музей и собрания-участники)",
    license=("снимки — права музеев и правообладателей (у части — CC BY 4.0, указано на "
             "странице снимка); метаданные — russiainphoto.ru; " + CONSENT),
    description=(
        "Снимки 1840–1960 годов из музейных и частных собраний с местом съёмки, датировкой "
        "и автором; точка — с карты сайта (ячейка геохеша до 5 км), у остальных — место текстом."
    ),
    url="https://russiainphoto.ru/",
    status="harvested",
)


class RussiaInPhotoError(RuntimeError):
    pass


# --- разбор выдачи поиска ----------------------------------------------------

@dataclass
class Item:
    id: int
    title: Optional[str]
    years: Optional[str]
    author: Optional[str]
    place: Optional[str]
    thumb: Optional[str]


_RE_ITEM = re.compile(r'<a class="b-search-result__item"(.*?)</a>', re.S)
_RE_TITLE = re.compile(r'class="b-search-result__item-title">(.*?)</div>', re.S)
_RE_YEARS = re.compile(r'class="b-search-result__item-years">(.*?)</div>', re.S)
_RE_AUTHOR = re.compile(r'class="b-search-result__item-author">(.*?)</div>', re.S)
_RE_IMG = re.compile(r'<img\s[^>]*?src="([^"]*)"[^>]*?alt="([^"]*)"', re.S)
_RE_ID = re.compile(r'data-id="(\d+)"')


def _text(m: Optional[re.Match]) -> Optional[str]:
    if not m:
        return None
    return clean_text(htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))))


def parse_items(fragment: str) -> list[Item]:
    """Снимки из разметки выдачи (`html.photos`)."""
    out = []
    for block in _RE_ITEM.findall(fragment):
        mid = _RE_ID.search(block)
        if not mid:
            continue
        title, years, author = _text(_RE_TITLE.search(block)), _text(_RE_YEARS.search(block)), \
            _text(_RE_AUTHOR.search(block))
        img = _RE_IMG.search(block)
        thumb = img.group(1) if img else None
        alt = clean_text(htmllib.unescape(img.group(2))) if img else None
        out.append(Item(int(mid.group(1)), title, years, author, place_from_alt(alt, title, years),
                        thumb))
    return out


def place_from_alt(alt: Optional[str], title: Optional[str], years: Optional[str]) -> Optional[str]:
    """Подпись `alt` — «название, годы, место»: место — то, что после годов."""
    if not alt:
        return None
    if years and f", {years}, " in alt:
        return clean_text(alt.split(f", {years}, ", 1)[1])
    if title and alt.startswith(title):
        rest = alt[len(title):].lstrip(", ")
        if years and rest.startswith(years):
            rest = rest[len(years):].lstrip(", ")
        return clean_text(rest)
    return None


# --- сбор --------------------------------------------------------------------

def _json(fetcher: Fetcher, url: str) -> dict:
    return json.loads(fetcher.get(url, headers={"X-Requested-With": "XMLHttpRequest"}))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")))


def _read(path: Path):
    return json.loads(gzip.decompress(path.read_bytes()))


def fetch_catalog(cache: Path, fetcher: Fetcher, *, limit_pages: Optional[int] = None,
                  size: int = PAGE, log=print) -> int:
    """Весь каталог выдачей поиска. Возвращает `total` сайта."""
    page, total, done = 1, None, 0
    while True:
        path = cache / "catalog" / f"{page:04d}.json.gz"
        if path.exists():
            payload = _read(path)
        else:
            if limit_pages is not None and done >= limit_pages:
                break
            raw = _json(fetcher, SEARCH.format(page=page, size=size))
            payload = {"total": raw.get("total"), "has_next": raw.get("has_next"),
                       "html": (raw.get("html") or {}).get("photos", "")}
            _write(path, payload)
            done += 1
            if done % 25 == 1:
                log(f"  каталог: страница {page}, всего {payload['total']}")
        total = payload.get("total")
        if not payload.get("has_next"):
            break
        page += 1
    return total or 0


def catalog_items(cache: Path) -> Iterator[Item]:
    for path in sorted((cache / "catalog").glob("*.json.gz")):
        yield from parse_items(_read(path).get("html", ""))


B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_bounds(gh: str) -> tuple[float, float, float, float]:
    """(север, запад, юг, восток) ячейки геохеша."""
    lat, lon = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for ch in gh:
        value = B32.index(ch)
        for bit in (16, 8, 4, 2, 1):
            rng = lon if even else lat
            mid = (rng[0] + rng[1]) / 2
            if value & bit:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    return lat[1], lon[0], lat[0], lon[1]


def intersect(a: tuple, b: tuple) -> Optional[tuple]:
    n, w, s, e = min(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3])
    return (n, w, s, e) if n > s and e > w else None


def quarters(rect: tuple) -> list[tuple]:
    n, w, s, e = rect
    mlat, mlon = (n + s) / 2, (w + e) / 2
    return [(n, w, mlat, mlon), (n, mlon, mlat, e), (mlat, w, s, mlon), (mlat, mlon, s, e)]


def _key(rect: tuple) -> str:
    return "_".join(f"{x:.7f}" for x in rect)


@dataclass
class Leaf:
    geohash: str
    lat: float
    lon: float
    count: int
    photo_id: Optional[int]


def crawl_grid(rect: tuple, get_grid: Callable[[tuple], dict], *, leaf_precision: int = LEAF_PRECISION,
               min_side: float = 1e-5) -> dict[str, Leaf]:
    """Листья карты: одиночные ячейки и ячейки длиной `leaf_precision` знаков.

    Рамка делится по ячейкам ответа (пересечение рамки с ячейкой — новая
    рамка) и, если ответ не измельчился, — на четверти. Ячейка, встретившаяся
    в двух соседних рамках, учитывается один раз: её снимки потом берутся
    целиком по геохешу.
    """
    leaves: dict[str, Leaf] = {}
    stack = [(t, 0) for t in (world_tiles() if rect == WORLD else [rect])]
    while stack:
        cur, parent_len = stack.pop()
        payload = get_grid(cur)
        results = payload.get("results") or []
        if not results:
            continue
        lengths = {len(c["geohash"]) for c in results}
        tiny = (cur[0] - cur[2]) < min_side or (cur[3] - cur[1]) < min_side
        if max(lengths) <= parent_len and not tiny:
            # Ответ не стал мельче: рамка ещё велика для следующего уровня.
            stack.extend((q, parent_len) for q in quarters(cur))
            continue
        for c in results:
            gh, count = c["geohash"], int(c.get("photos_count") or 0)
            if count <= 0:
                continue
            photo = c.get("photo") or {}
            if count == 1 or len(gh) >= leaf_precision or tiny:
                old = leaves.get(gh)
                if old is None or count > old.count:
                    leaves[gh] = Leaf(gh, float(c["lat"]), float(c["lon"]), count,
                                      photo.get("id"))
                continue
            sub = intersect(cur, geohash_bounds(gh))
            if sub:
                stack.append((sub, len(gh)))
    return leaves


def cached_grid(cache: Path, fetcher: Fetcher, log=print) -> Callable[[tuple], dict]:
    counter = {"n": 0}

    def get(rect: tuple) -> dict:
        path = cache / "grid" / f"{_key(rect)}.json.gz"
        if path.exists():
            return _read(path)
        n, w, s, e = (round(x, 7) for x in rect)
        payload = _json(fetcher, GRID.format(n=n, w=w, s=s, e=e))
        _write(path, {"total": payload.get("total"), "results": payload.get("results") or []})
        counter["n"] += 1
        if counter["n"] % 200 == 1:
            log(f"  карта: запрос {counter['n']}, рамка {n},{w},{s},{e}")
        return payload
    return get


def fetch_cells(leaves: Iterable[Leaf], cache: Path, fetcher: Fetcher, *, size: int = PAGE,
                log=print) -> int:
    """Номера снимков в ячейках, где их больше одного. Возвращает число ячеек."""
    n = 0
    for leaf in leaves:
        if leaf.count <= 1:
            continue
        path = cache / "cells" / f"{leaf.geohash}.json.gz"
        if path.exists():
            continue
        ids: list[int] = []
        page = 1
        while True:
            raw = _json(fetcher, CELL.format(gh=leaf.geohash, page=page, size=size))
            ids += [i.id for i in parse_items((raw.get("html") or {}).get("photos", ""))]
            if not raw.get("has_next"):
                break
            page += 1
        _write(path, {"geohash": leaf.geohash, "total": raw.get("total"), "ids": ids})
        n += 1
        if n % 200 == 1:
            log(f"  ячейки: {n}, {leaf.geohash} — {len(ids)} снимков")
    return n


def save_leaves(leaves: dict[str, Leaf], path: Path) -> None:
    _write(path, [vars(l) for l in leaves.values()])


def load_leaves(path: Path) -> dict[str, Leaf]:
    return {d["geohash"]: Leaf(**d) for d in _read(path)} if path.exists() else {}


def points(leaves: dict[str, Leaf], cache: Path) -> dict[int, tuple[float, float, str, int]]:
    """Номер снимка → (широта, долгота, геохеш, снимков в ячейке)."""
    out: dict[int, tuple[float, float, str, int]] = {}
    for leaf in leaves.values():
        if leaf.count == 1 and leaf.photo_id is not None:
            out.setdefault(int(leaf.photo_id), (leaf.lat, leaf.lon, leaf.geohash, 1))
            continue
        path = cache / "cells" / f"{leaf.geohash}.json.gz"
        if not path.exists():
            continue
        for pid in _read(path).get("ids", []):
            out.setdefault(int(pid), (leaf.lat, leaf.lon, leaf.geohash, leaf.count))
    return out


# --- записи ------------------------------------------------------------------

def records(items: Iterable[Item], pts: dict, spec: LayerSpec = RUSSIAINPHOTO
            ) -> tuple[list[ContextRecord], dict]:
    out: list[ContextRecord] = []
    seen: set = set()
    skipped = {"повтор": 0, "без года или позже горизонта": 0}
    for item in items:
        if item.id in seen:
            skipped["повтор"] += 1
            continue
        seen.add(item.id)
        dating = photo_years(item.years)
        if dating is None:
            skipped["без года или позже горизонта"] += 1
            continue
        lo, hi, precision, approx, raw = dating
        point = pts.get(item.id)
        extra: dict = {}
        if point:
            extra["geohash"] = point[2]
            if point[3] > 1:
                extra["cell_photos"] = point[3]
        out.append(spec.new_record(
            title=item.title or "Фотография",
            category="фотография",
            lat=point[0] if point else None,
            lon=point[1] if point else None,
            place_text=item.place,
            year_from=lo, year_to=hi,
            date_precision=precision,
            date_approx=approx or hi > lo,
            period_raw=raw,
            actor=item.author,
            url=f"{BASE}/photos/{item.id}/",
            image_url=item.thumb,
            source_id=str(item.id),
            confidence=("ok" if point[3] == 1 else "place_level") if point else "no_coords",
            extra=extra,
        ))
    return out, skipped
