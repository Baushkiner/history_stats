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
* **Ответ API сверен с живым сервисом 23 августа 2026 года.** До этого имена
  полей были взяты из документации (docs.pastvu.com/dev/api), и одно
  расхождение нашлось сразу же — порядок осей в `bounds`, см. `bounds_param`.
  Снимок в ответе `photo.getByBounds` выглядит так:

      {"cid": 14597, "geo": [55.765406, 37.600608], "dir": "e",
       "file": "0/3/f/03f453e59a476a79f511764217a6efde.jpg",
       "title": "Церковь Рождества Христова в Палашах",
       "year": 1881, "year2": 1881}

  Поля `cid`, `geo`, `file`, `title`, `year`, `year2` пришли у всех снимков
  двух выборок (22 936 и 112 130 записей), `dir` и служебное `__v` — не у
  всех. Проверка `check_photo_fields` держит именно это: если сервис
  переименует поле, сбор остановится, а не выдаст пустой слой.
* **Проба перед сбором остаётся обязательной.** `scripts/harvest_pastvu.py
  --probe` печатает, что реально пришло сегодня. Молча собрать пустоту хуже,
  чем остановиться.
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
from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..normalize import to_int
from ..schema import ContextRecord, LayerSpec, clean_text

ENDPOINT = "https://api.pastvu.com/api2"


# Нижняя граница датировок в самом PastVu и верхняя граница нашего периода.
YEAR_MIN, YEAR_MAX = 1826, 1960

# Зум, на котором сервис отдаёт отдельные снимки, а не кластеры. Проверено:
# на 16 и ниже в ответе появляются кластеры, на 17 и 18 — только снимки.
ZOOM_PHOTOS = 17

# Зум для счёта без выгрузки: на нём кластеры крупные, и вся страна
# пересчитывается парой десятков запросов вместо тысяч.
ZOOM_CLUSTERS = 6

# Сторона кластерной клетки в градусах на данном зуме. Замерено: на зуме 12
# рамка в градус дала 555 кластеров (сторона около 0,042°), на зуме 6 вся
# страна — около 770. Отсюда 172/2^z. Точность здесь не нужна: число служит
# одному — выбрать зум, на котором кластеры заметно мельче считаемой рамки.
CLUSTER_DEG_AT_Z0 = 172.0

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
    # Разбор сверен с живым сервисом, обход написан и продолжается после
    # обрыва — но слой не собран, и `harvested` тут было бы неправдой.
    # Обход отложен решением владельца: 686 тысяч снимков это порядка 400 МБ
    # GeoJSON, а GitHub не принимает файлы больше 100 МБ, так что перед сбором
    # надо выбрать, чем резать — годами, областями или вынесением из
    # репозитория. Сборщик к запуску готов: `harvest_pastvu.py --all --resume`.
    status="planned",
    # Не догадка: 23 августа 2026 года счётчики кластеров по всей рамке РИ/СССР
    # дали 686 123 снимка с датировкой до 1960 года включительно — двадцать
    # восемь запросов, `harvest_pastvu.py --estimate --all`. Счёт по кластерам
    # грубоват (расхождение между зумами около процента), но прежняя оценка в
    # 200 000 была занижена втрое, а не на проценты.
    expected_rows=686000,
)

# Рамка, упирающаяся в 180-й меридиан, валит сервис: и восточный край 180.0,
# и западный −180.0 дают ApplicationError на любом зуме. Отступ в десятитысячную
# градуса — это одиннадцать метров, меньше точности привязки любого снимка,
# зато последний столбец клеток у 180-го меридиана собирается, а не падает
# клетка за клеткой, и заходящая за меридиан Чукотка вообще становится доступна.
ANTIMERIDIAN_EPS = 0.0001

# Поля, без которых запись бесполезна. Проверяются до разбора: если сервис
# переименует их, сбор должен остановиться, а не выдать пустой слой.
# `year` здесь потому же, почему `geo`: снимок без датировки не встанет ни на
# карту, ни на ленту времени, и слой из таких снимков — пустой слой.
REQUIRED_FIELDS = ("cid", "geo", "year")


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
            # Сервис отвечает на ошибку не HTTP-кодом, а телом вида
            # {"type": "ApplicationError", "code": ..., "message": ...} — его
            # и показываем: «нет поля result» само по себе ничего не объясняет.
            message = payload.get("message") or payload.get("error")
            if message:
                raise PastVuError(f"{method}: {payload.get('type', 'ошибка')} — {message}")
            raise PastVuError(
                f"в ответе {method} нет поля result; пришли ключи: {sorted(payload)}"
            )
        return payload["result"]

    def photos_in_bbox(self, bbox: tuple, *, year_from: int = YEAR_MIN,
                       year_to: int = YEAR_MAX, zoom: int = ZOOM_PHOTOS) -> list[dict]:
        """Снимки в прямоугольнике (lat_min, lon_min, lat_max, lon_max)."""
        result = self._by_bounds(bbox, year_from, year_to, zoom)
        photos = result.get("photos")
        if photos is None:
            raise PastVuError(
                "в ответе photo.getByBounds нет поля photos; пришли ключи: "
                f"{sorted(result)} (при зуме {zoom} ожидались отдельные снимки)"
            )
        # Кластеры вместо снимков означают слишком мелкий зум. Ответ при этом
        # не ошибочный: поле photos на месте, просто почти пустое — так сбор
        # и прошёл бы молча по всей стране, собрав крохи. Останавливаемся.
        clusters = result.get("clusters")
        if clusters:
            raise PastVuError(
                f"на зуме {zoom} сервис вернул {len(clusters)} кластеров и всего "
                f"{len(photos)} снимков: кластеры собирать нельзя, нужен зум "
                f"не меньше {ZOOM_PHOTOS}"
            )
        return photos

    def count_in_bbox(self, bbox: tuple, *, year_from: int = YEAR_MIN,
                      year_to: int = YEAR_MAX, zoom: Optional[int] = None) -> int:
        """Сколько снимков в рамке — по счётчикам кластеров, без выгрузки.

        Кластер несёт поле `c` — число снимков, попавших под тот же фильтр по
        годам, что и запрос (проверено: сумма `c` совпала с суммой гистограммы
        `y` по годам до 1960). Это единственный способ узнать объём заранее:
        выгрузка всей страны — сотни мегабайт, а счёт по кластерам — пара
        десятков запросов.

        Оценка приблизительная: кластер приписан к своему центру, поэтому у
        края рамки счёт немного плывёт. На одной и той же области зум 6 и зум 8
        дали 199 427 и 197 780 — расхождение около процента. Зум поэтому берётся
        по размеру рамки (`cluster_zoom`): на маленькой рамке крупные кластеры
        врали бы не на проценты, а в разы.
        """
        result = self._by_bounds(bbox, year_from, year_to,
                                 cluster_zoom(bbox) if zoom is None else zoom)
        clusters = result.get("clusters")
        if clusters is None:
            raise PastVuError(
                "в ответе нет поля clusters; пришли ключи: "
                f"{sorted(result)}. Счёт по кластерам работает только на мелком зуме."
            )
        # Рядом с кластерами сервис иногда отдаёт и отдельные снимки — те, что
        # ни в один кластер не попали. Не сложить их значило бы недосчитаться.
        return (sum(int(c.get("c") or 0) for c in clusters)
                + len(result.get("photos") or []))

    def _by_bounds(self, bbox: tuple, year_from: int, year_to: int, zoom: int) -> dict:
        return self.call("photo.getByBounds", {
            "z": zoom,
            "bounds": [bounds_param(bbox)],
            "year": year_from,
            "year2": year_to,
            "isPainting": False,
            "localWork": False,
        })

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
                if exc.code not in RETRY_CODES:
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
        self._last_call = wait_for_pause(self._last_call, self.pause_sec)


def cluster_zoom(bbox: tuple) -> int:
    """Зум, на котором кластеры заметно мельче рамки — иначе счёт бессмыслен.

    Кластер приписан к своему центру, и если он одного порядка с рамкой, в
    ответ попадёт либо всё соседнее, либо ничего. Берём зум, на котором в
    рамку укладывается около двадцати кластеров по короткой стороне.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    span = min(abs(lat_max - lat_min), abs(lon_max - lon_min))
    if span <= 0:
        return ZOOM_PHOTOS
    zoom = ZOOM_CLUSTERS
    # Верхняя граница — 15: на 16-м сервис уже мешает кластеры с отдельными
    # снимками, а на 17-м кластеров не отдаёт вовсе.
    while zoom < ZOOM_PHOTOS - 2 and CLUSTER_DEG_AT_Z0 / (2 ** zoom) > span / 20.0:
        zoom += 1
    return zoom


def bounds_param(bbox: tuple) -> list:
    """Наш bbox (lat_min, lon_min, lat_max, lon_max) в пару углов [[ю, з], [с, в]].

    Порядок осей — «широта, долгота», и это ровно то место, где документация
    разошлась с сервисом. Документация (docs.pastvu.com/dev/api) описывает
    параметр `geometry` — GeoJSON-полигон в порядке «долгота, широта»; живой
    сервис 23 августа 2026 года на `geometry` при зуме 17 не отдал ни одного
    снимка ни в одном порядке обхода полигона, зато на `bounds` отдал — и
    только когда широта идёт первой. Проверка: рамка [[59.93, 30.30],
    [59.95, 30.35]] вернула 22 936 снимков с координатами в Петербурге, та же
    рамка в порядке «долгота, широта» — ноль.

    Координаты в ответе (`geo`) идут в том же порядке: [широта, долгота].
    Перепутать легко, поэтому результат сбора ещё раз просеивается через
    `in_requested_bbox`: чужие точки в слой не пройдут.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    return [[lat_min, max(lon_min, -180.0 + ANTIMERIDIAN_EPS)],
            [lat_max, min(lon_max, 180.0 - ANTIMERIDIAN_EPS)]]


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
    """Попал ли снимок в тот прямоугольник, который у сервиса и просили."""
    return in_bbox(lat, lon, bbox)


def check_photo_fields(photos: list[dict], sample: int = 50) -> None:
    """Проверяет, что в ответе есть поля, на которых держится разбор.

    Смотрим не первый снимок, а объединение полей первых полусотни: у
    отдельной записи поле может отсутствовать по делу (так бывает с `dir`),
    а вот если его нет ни у кого — сервис переименовал поле, и это ошибка
    сбора, а не пустой слой.
    """
    if not photos:
        return
    keys: set = set()
    for photo in photos[:sample]:
        keys |= set(photo)
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
            # `year` и `year2` оба названы автором снимка: точность — год,
            # а то, что момент внутри интервала неизвестен, помечено
            # `date_approx`. «Часть века» здесь была неправдой: 1893–1896 —
            # не половина столетия.
            date_precision="year",
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
    year_from = to_int(photo.get("year"))
    if year_from is None:
        return None, 0
    year_to = to_int(photo.get("year2")) or year_from
    if year_to < year_from:
        year_from, year_to = year_to, year_from
    return year_from, year_to
