"""Сбор старых фотографий из PastVu.

Зачем отдельный источник. Викиданные дают объекты — храм, станцию, завод, —
но почти не дают того, что предок видел своими глазами. Слой Прокудина-
Горского закрывает эту нишу на 304 записи и только на 1903–1916 годы.
В PastVu лежат сотни тысяч привязанных к координатам снимков с датировкой,
и по форме записи это ровно тот же слой: точка, год, подпись, ссылка.

Что важно знать до сбора:

* **Права.** PastVu — некоммерческий проект, снимки загружают пользователи,
  и права на изображения принадлежат их владельцам. Забирать можно метаданные
  и ссылки на страницу снимка; копировать сами файлы — только после выяснения
  условий. Поэтому `image_url` здесь не заполняется: подставить прямую ссылку
  на файл значило бы предложить пользователю то, на что у проекта нет прав.
* **Ответ API не проверен на живом сервисе.** Среда, в которой писался этот
  модуль, не имеет доступа к api.pastvu.com. Имена полей взяты из
  документации (docs.pastvu.com/dev/api), а не из ответа. Поэтому первым
  делом выполняется `scripts/harvest_pastvu.py --probe`: он показывает, что
  реально пришло, и падает с понятным сообщением, если полей нет. Молча
  собрать пустоту хуже, чем остановиться.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterator, Optional

from ..geo import in_bbox, valid_coords
from ..schema import ContextRecord, LayerSpec, clean_text

ENDPOINT = "https://api.pastvu.com/api2"

# Заголовки HTTP кодируются latin-1 — в User-Agent только ASCII.
USER_AGENT = (
    "histctx/0.2 (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

# Нижняя граница датировок в самом PastVu и верхняя граница нашего периода.
YEAR_MIN, YEAR_MAX = 1826, 1960

# Зум, на котором сервис отдаёт отдельные снимки, а не кластеры.
ZOOM_PHOTOS = 17

PASTVU_PHOTOS = LayerSpec(
    slug="photos_pastvu",
    title="Старые фотографии (PastVu)",
    group="culture",
    source="PastVu, pastvu.com",
    license=(
        "метаданные — по правилам проекта со ссылкой на источник; "
        "изображения — права авторов и правообладателей, копирование требует согласования"
    ),
    description=(
        "Привязанные к координатам снимки с датировкой. Тот же вид контекста, что "
        "и фотографии Прокудина-Горского, но на полтора века и на всю страну: "
        "улица, храм или вокзал, которые предок видел в год записи о венчании."
    ),
    url="https://pastvu.com/",
    status="planned",
    expected_rows=200000,
)

# Поля, без которых запись бесполезна. Проверяются до разбора: если сервис
# переименует их, сбор должен остановиться, а не выдать пустой слой.
REQUIRED_FIELDS = ("cid", "geo")


class PastVuError(RuntimeError):
    """Запрос к PastVu не выполнен или ответ не такой, какого мы ждём."""


@dataclass
class PastVuClient:
    """Клиент api2 с повторами при перегрузке и паузой между запросами."""

    timeout: int = 60
    max_retries: int = 5
    pause_sec: float = 0.5
    _last_call: float = field(default=0.0, repr=False)

    def call(self, method: str, params: dict) -> dict:
        """Вызывает метод API и возвращает содержимое поля `result`."""
        query = urllib.parse.urlencode({
            "method": method,
            "params": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
        })
        payload = self._request(f"{ENDPOINT}?{query}")
        if "result" not in payload:
            raise PastVuError(
                f"в ответе {method} нет поля result; пришли ключи: {sorted(payload)}"
            )
        return payload["result"]

    def photos_in_bbox(self, bbox: tuple, *, year_from: int = YEAR_MIN,
                       year_to: int = YEAR_MAX, zoom: int = ZOOM_PHOTOS) -> list[dict]:
        """Снимки в прямоугольнике (lat_min, lon_min, lat_max, lon_max)."""
        result = self.call("photo.getByBounds", {
            "z": zoom,
            "bounds": [bounds_param(bbox)],
            "year": year_from,
            "year2": year_to,
            "isPainting": False,
            "localWork": False,
        })
        photos = result.get("photos")
        if photos is None:
            # Кластеры вместо снимков означают слишком мелкий зум: на таком
            # ответе слой собрать нельзя, и молчать об этом нельзя тоже.
            raise PastVuError(
                "в ответе photo.getByBounds нет поля photos; пришли ключи: "
                f"{sorted(result)} (при зуме {zoom} ожидались отдельные снимки)"
            )
        return photos

    def _request(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        delay = 2.0
        last: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (429, 500, 502, 503, 504):
                    body = exc.read()[:400].decode("utf-8", "replace")
                    raise PastVuError(f"HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
            except json.JSONDecodeError as exc:
                raise PastVuError(f"ответ не разобран как JSON: {exc}") from exc
            if attempt < self.max_retries - 1:
                time.sleep(delay)
                delay *= 2
        raise PastVuError(f"не удалось выполнить запрос после {self.max_retries} попыток: {last}")

    def _throttle(self) -> None:
        """Пауза между запросами: сервис небольшой, выгружать его нахрапом нельзя."""
        wait = self.pause_sec - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def bounds_param(bbox: tuple) -> list:
    """Наш bbox (lat_min, lon_min, lat_max, lon_max) в пару углов [[з, ю], [в, с]].

    Углы задаются в порядке «долгота, широта» — как в GeoJSON и в клиенте
    самого сервиса. Порядок легко перепутать, поэтому результат сбора ещё раз
    просеивается через `in_requested_bbox`: при перепутанных осях ответ будет
    пустым или чужим, но в слой чужие точки не попадут.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    return [[lon_min, lat_min], [lon_max, lat_max]]


def grid(bbox: tuple, step_deg: float = 0.5) -> Iterator[tuple]:
    """Режет прямоугольник на клетки: за один запрос сервис отдаёт немного."""
    if step_deg <= 0:
        raise ValueError("шаг сетки должен быть положительным")
    lat_min, lon_min, lat_max, lon_max = bbox
    lat = lat_min
    while lat < lat_max:
        lon = lon_min
        while lon < lon_max:
            yield (lat, lon, min(lat + step_deg, lat_max), min(lon + step_deg, lon_max))
            lon += step_deg
        lat += step_deg


def in_requested_bbox(lat: float, lon: float, bbox: tuple) -> bool:
    lat_min, lon_min, lat_max, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def check_photo_fields(photos: list[dict]) -> None:
    """Проверяет, что в ответе есть поля, на которых держится разбор."""
    if not photos:
        return
    keys = set(photos[0])
    missing = [f for f in REQUIRED_FIELDS if f not in keys]
    if missing:
        raise PastVuError(
            f"в ответе нет обязательных полей {missing}; пришли: {sorted(keys)}. "
            "Сверьтесь с docs.pastvu.com/dev/api и поправьте разбор."
        )


def photos_to_records(photos: list[dict], spec: LayerSpec = PASTVU_PHOTOS, *,
                      require_bbox: bool = True, year_max: int = YEAR_MAX) -> list[ContextRecord]:
    """Превращает ответ API в записи единой схемы.

    Снимок без координат или без года для подбора контекста бесполезен: он
    не встанет ни на карту, ни на ленту времени — такие пропускаются, а не
    сохраняются с пустыми полями.
    """
    check_photo_fields(photos)
    out: list[ContextRecord] = []
    seen: set[str] = set()
    for photo in photos:
        cid = photo.get("cid")
        if cid is None or str(cid) in seen:
            continue
        lat, lon = _geo(photo.get("geo"))
        if lat is None:
            continue
        if require_bbox and not in_bbox(lat, lon):
            continue

        year_from, year_to = _years(photo)
        if year_from is None or year_from > year_max:
            continue
        year_to = min(year_to, year_max)

        seen.add(str(cid))
        span = year_to - year_from
        title = clean_text(photo.get("title")) or "Фотография"
        out.append(spec.new_record(
            title=title,
            category="фотография",
            lat=lat, lon=lon,
            year_from=year_from,
            year_to=year_to,
            date_precision="year" if span == 0 else "part",
            date_approx=span > 0,
            period_raw=str(year_from) if span == 0 else f"{year_from}–{year_to}",
            summary=f"Снимок PastVu: {title}.",
            url=f"https://pastvu.com/p/{cid}",
            source_id=str(cid),
            # Путь к файлу сохраняем, но ссылкой на изображение не делаем:
            # права на снимки принадлежат их владельцам.
            extra={"file": clean_text(photo.get("file"))} if photo.get("file") else {},
        ))
    return out


def _geo(geo) -> tuple[Optional[float], Optional[float]]:
    """PastVu отдаёт координаты парой [широта, долгота]."""
    if not isinstance(geo, (list, tuple)) or len(geo) != 2:
        return None, None
    lat, lon = geo
    if not valid_coords(lat, lon):
        return None, None
    return float(lat), float(lon)


def _years(photo: dict) -> tuple[Optional[int], int]:
    """`year` — начало датировки, `year2` — её конец; второй бывает пуст."""
    year_from = _int(photo.get("year"))
    if year_from is None:
        return None, 0
    year_to = _int(photo.get("year2")) or year_from
    if year_to < year_from:
        year_from, year_to = year_to, year_from
    return year_from, year_to


def _int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
