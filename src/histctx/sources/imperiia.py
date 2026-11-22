"""Почтовые станции и почтовые дворы 1820-х годов: атлас Пядышева, проект Imperiia.

Зачем этот слой. До железных дорог человек и бумага двигались по почтовым
трактам: рекрута вели по этапу, невесту везли из соседнего уезда, метрическую
выпись отправляли в консисторию — и всё это шло от станции к станции. Слой
отвечает на вопрос «где была ближайшая почтовая станция в 1820-е годы», а у
дорог первой половины XIX века в проекте до него не было ничего.

Источник — «Географический атлас Российской империи, Царства Польского и
Великого княжества Финляндского» В. П. Пядышева (Военно-топографическое депо,
1820–1827), оцифрованный проектом Imperiia (К. О'Нил, Гарвард). Атлас
различает станцию в селении и отдельно стоящий почтовый двор при дороге —
это два слоя Imperiia, и оба собираются сюда.

Откуда берётся. Набор на Harvard Dataverse (doi:10.7910/DVN/DDTKS9) закрыт
гостевой книгой: без имени, почты, места работы и описания исследования файл
не отдаётся, и подставлять туда выдуманное сборщик не будет. Тот же слой
автор выложила открыто на ArcGIS Online (учётная запись `koneill_worldmap`,
доступ `public`) — оттуда он и берётся, двумя сервисами FeatureServer.
Лицензия на карточке сервиса не указана; на сайте проекта и на карточке
набора в Dataverse стоит CC BY-NC-SA 4.0 — она и записана.

Названия в наборе — латиницей, в транслитерации Библиотеки Конгресса
(«Zhirmony», «Usol'e»). Заголовок записи даёт обратную транслитерацию
кириллицей и рядом — написание набора: обратный перевод механический, для
нерусских названий (Финляндия, Польша, Остзейские губернии) он условен, и
искать по нему нельзя — искать надо по точке. Губерния в поле `region` — не
из атласа, а по полигонам 1897 года (`histctx.frame`): в 1820-е деление было
другим, и губерния атласа остаётся в `place_text` и `extra`.

Датировка — 1820–1827, годы выхода листов атласа: станция показана на листе,
а когда она открыта и когда закрыта, атлас не говорит.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Optional

from ..geo import valid_coords
from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..schema import ContextRecord, LayerSpec

SERVICES_URL = "https://services7.arcgis.com/iEMmryaM5E3wkdnU/arcgis/rest/services"
ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item}?f=json"
DOCUMENT_URL = "https://imperiia.omeka.fas.harvard.edu/document/676"
DATASET_URL = "https://doi.org/10.7910/DVN/DDTKS9"
OWNER = "koneill_worldmap"
YEARS = (1820, 1827)

SOURCE = ("Imperiia Project (К. О'Нил, Гарвард): почтовые станции по «Географическому "
          "атласу Российской империи» В. П. Пядышева, 1820–1827; ArcGIS Online")
LICENSE = (
    "CC BY-NC-SA 4.0 (сайт проекта Imperiia и карточка набора на Harvard Dataverse; на "
    "карточке сервиса ArcGIS лицензия не указана): некоммерческое использование со ссылкой "
    "на проект и на тех же условиях — ссылка и цитата стоят в каждой записи"
)
CITATION = (
    "O'Neill, Kelly. Post stations of the Russian Empire (1820s). Harvard Dataverse, 2016, "
    "doi:10.7910/DVN/DDTKS9. Credits: Rachel Koroloff, Alexander Tedeschi, Kelly O'Neill. "
    "Источник: Географический атлас Российской империи, 1820–1827 [атлас Пядышева]"
)


class ImperiiaError(RuntimeError):
    """Сервис не ответил или устроен не так, как записано в коде."""


@dataclass(frozen=True)
class Service:
    """Сервис FeatureServer: имя, карточка, число объектов в день подключения."""

    key: str
    name: str
    item: str
    count: int
    category: str
    word: str


# Сверено с сервером 22.11.2026. Число объектов разошлось — сбор стоит.
STATIONS = Service("station", "Post_stations", "de236dbdd8394ad4ac95b63f23a09e27", 3569,
                   "станция в селении", "Почтовая станция")
HOUSES = Service("house", "Post_houses", "60dc41fab99b453bb259c940765cc667", 575,
                 "почтовый двор при дороге", "Почтовый двор")
SERVICES = (STATIONS, HOUSES)
REQUIRED_FIELDS = {"Placename", "Prov_name", "Admin_3rd", "GazID", "Source", "Cat_Rus_Tr",
                   "PostType", "ObjectId"}

# Тип селения, в котором стоит станция. В самих сервисах станций код не
# расшифрован; расшифровка получена сведением по `GazID` с соседними слоями
# Imperiia (губернские и уездные города, сёла, редуты, крепости), где тот же
# код стоит рядом с подписью. Коды 5, 6, 7, 12 и 14 (77 станций) так не
# нашлись и остаются числом.
SETTLEMENT_TYPES = {
    1: "губернский город", 2: "уездный город", 3: "заштатный город",
    4: "малый город, местечко", 8: "село или слобода", 9: "деревня", 10: "хутор",
    11: "почтовый двор", 17: "форпост", 18: "редут", 19: "крепость",
    31: "крупный город", 32: "средний город", 33: "крупный укреплённый город",
    34: "крупный неукреплённый город", 35: "малый укреплённый город",
    36: "малый неукреплённый город",
}

POST_STATIONS = LayerSpec(
    slug="post_stations_1820",
    title="Почтовые станции и почтовые дворы 1820-х годов (атлас Пядышева)",
    group="economy",
    source=SOURCE,
    license=LICENSE,
    description=(
        "Где была ближайшая почтовая станция до железных дорог: станции в селениях и "
        "отдельно стоящие почтовые дворы по листам атласа Пядышева 1820–1827 годов — вся "
        "империя с Царством Польским и Финляндией. Названия в наборе латиницей; кириллица "
        "в заголовке — обратная транслитерация, искать надо по точке, а не по имени. "
        "Атлас показывает, что станция была на листе, а годов открытия и закрытия не даёт."
    ),
    url=DOCUMENT_URL,
    status="harvested",
    expected_rows=4144,      # сбор 22.11.2026: 3 569 станций и 575 почтовых дворов
)


# --- сеть ------------------------------------------------------------------

class Client:
    """Запросы к ArcGIS Online: подпись, пауза, повторы."""

    def __init__(self, *, pause_sec: float = 0.5, attempts: int = 4, timeout: int = 120) -> None:
        self.pause_sec, self.attempts, self.timeout = pause_sec, attempts, timeout
        self._last = 0.0

    def get_url(self, url: str) -> dict:
        error: Optional[Exception] = None
        for attempt in range(self.attempts):
            self._last = wait_for_pause(self._last, self.pause_sec)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES:
                    raise ImperiiaError(f"{url}: HTTP {exc.code}") from exc
                error = exc
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                error = exc
            else:
                if isinstance(payload, dict) and "error" in payload:
                    raise ImperiiaError(f"{url}: сервер ответил ошибкой {payload['error']}")
                return payload
            time.sleep(2 * (attempt + 1))
        raise ImperiiaError(f"{url}: не ответил за {self.attempts} попыток ({error})")

    def get(self, path: str, **params) -> dict:
        params.setdefault("f", "json")
        return self.get_url(f"{SERVICES_URL}/{path}?{urllib.parse.urlencode(params)}")

    def layer_info(self, service: Service) -> dict:
        return self.get(f"{service.name}/FeatureServer/0")

    def count(self, service: Service) -> int:
        return self.get(f"{service.name}/FeatureServer/0/query", where="1=1",
                        returnCountOnly="true").get("count")

    def query_all(self, service: Service, *, page: int = 2000) -> list[dict]:
        """Все объекты слоя страницами, по порядку `ObjectId`.

        Порядок задан явно: без него сервер вправе отдавать страницы как
        угодно, и смещение пропустит или повторит объекты.
        """
        features: list = []
        while True:
            payload = self.get(
                f"{service.name}/FeatureServer/0/query", where="1=1", outFields="*",
                outSR="4326", orderByFields="ObjectId", resultOffset=len(features),
                resultRecordCount=page)
            got = payload.get("features") or []
            features += got
            if not payload.get("exceededTransferLimit") or not got:
                return features


def check_layer(info: dict, service: Service, actual_count: Optional[int]) -> list[str]:
    """Расхождения слоя с записанным в коде: геометрия, поля, число объектов."""
    problems = []
    if info.get("geometryType") != "esriGeometryPoint":
        problems.append(f"{service.name}: геометрия {info.get('geometryType')}, ожидались точки")
    fields = {field.get("name") for field in info.get("fields") or []}
    missing = sorted(REQUIRED_FIELDS - fields)
    if missing:
        problems.append(f"{service.name}: нет полей {', '.join(missing)}")
    if actual_count != service.count:
        problems.append(f"{service.name}: объектов {actual_count}, в коде {service.count}")
    return problems


def check_item(item: dict) -> list[str]:
    """Карточка сервиса: тот же владелец и открытый доступ."""
    problems = []
    if item.get("owner") != OWNER:
        problems.append(f"владелец сервиса {item.get('owner')!r}, ожидался {OWNER!r}")
    if item.get("access") != "public":
        problems.append(f"доступ к сервису {item.get('access')!r}, а не public — сбор стоит")
    return problems


# --- обратная транслитерация ------------------------------------------------

# Таблица Библиотеки Конгресса без диакритики, как в наборе. Длинные сочетания
# идут первыми. «ts» читается как «ц»: «тс» в названиях встречается реже.
_PAIRS = (
    ("shch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
    ("iu", "ю"), ("ia", "я"), ("ie", "ие"), ("yi", "ый"), ("ii", "ий"),
    ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"), ("z", "з"),
    ("i", "и"), ("j", "й"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"),
    ("p", "п"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("f", "ф"), ("y", "ы"),
    ("h", "г"), ("c", "к"), ("w", "в"), ("x", "кс"), ("q", "к"),
    ("''", "ъ"), ("'", "ь"), ("’", "ь"),
)
_VOWELS = "аеёиоуыэюя"
_RE_WORD = re.compile(r"[A-Za-z'’]+")


def _word(match: re.Match) -> str:
    text = match.group(0)
    low, out, i = text.lower(), [], 0
    while i < len(low):
        for latin, cyr in _PAIRS:
            if low.startswith(latin, i):
                # «и» после гласной в конце слова или перед согласной — «й»:
                # «Krasnoi» → «Красной», «Nikolaevsk» остаётся как есть.
                if latin == "i" and out and out[-1][-1] in _VOWELS and (
                        i + 1 == len(low) or low[i + 1] not in "aeiouy"):
                    cyr = "й"
                # «e» в начале слова и после гласной в наборе — чаще «э»/«е»
                # без различия; оставляем «е», кроме начала слова.
                if latin == "e" and not out:
                    cyr = "э"
                out.append(cyr)
                i += len(latin)
                break
        else:
            out.append(low[i])
            i += 1
    word = "".join(out)
    return word[:1].upper() + word[1:] if text[:1].isupper() else word


def cyrillic(name: Optional[str]) -> str:
    """Обратная транслитерация названия из набора. Механическая — см. описание модуля."""
    return _RE_WORD.sub(_word, name or "").strip()


_RE_SHEET = re.compile(r"(\d+)\s*$")


def sheet_number(source: Optional[str]) -> Optional[int]:
    """«Piadyshev Atlas 059» → 59."""
    match = _RE_SHEET.search(source or "")
    return int(match.group(1)) if match else None


def settlement_type(code) -> Optional[str]:
    return SETTLEMENT_TYPES.get(code)


# --- записи ----------------------------------------------------------------

def feature_to_record(feature: dict, service: Service) -> Optional[ContextRecord]:
    """Объект сервиса → запись. Объект без названия и без точки не берётся."""
    attrs = feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}
    name = (attrs.get("Placename") or "").strip()
    lat, lon = geometry.get("y"), geometry.get("x")
    point = valid_coords(lat, lon)
    if not name and not point:
        return None
    province = (attrs.get("Prov_name") or "").strip()
    district = (attrs.get("Admin_3rd") or "").strip()
    sheet = sheet_number(attrs.get("Source"))
    code = attrs.get("Cat_Rus_Tr")
    kind = settlement_type(code)
    russian = cyrillic(name)
    title = f"{service.word} {russian} ({name})" if name else f"{service.word} без названия"

    parts = []
    if service is HOUSES:
        parts.append("Отдельно стоящий почтовый двор при дороге (в атласе — «почтовая "
                     "станция с двором»)")
    elif kind:
        parts.append(f"Почтовая станция в селении; тип селения по атласу — {kind}")
    else:
        parts.append("Почтовая станция в селении")
    where = ", ".join(x for x in (name, district, province) if x)
    parts.append(f"В наборе: {where}" if where else "")
    parts.append("«Географический атлас Российской империи» В. П. Пядышева, 1820–1827"
                 + (f", лист {sheet}" if sheet else ""))
    parts.append("Название кириллицей — обратная транслитерация; год открытия и закрытия "
                 "станции атлас не даёт")

    # Цитата набора — одна на слой (`CITATION`, она же в карточке слоя): в
    # каждую запись её не кладём, файл от этого вдвое тяжелее.
    extra = {"kind": service.key, "name_latin": name, "province_atlas": province,
             "district_atlas": district, "dataset": DATASET_URL}
    if sheet:
        extra["atlas_sheet"] = sheet
    if code is not None:
        extra["settlement_code"] = code
    if kind:
        extra["settlement_type"] = kind
    if attrs.get("GazID") is not None:
        extra["gaz_id"] = attrs["GazID"]

    return POST_STATIONS.new_record(
        title=title, category=service.category,
        lat=round(lat, 5) if point else None, lon=round(lon, 5) if point else None,
        place_text=where or None,
        year_from=YEARS[0], year_to=YEARS[1], date_precision="year",
        period_raw="1820–1827 (годы выхода листов атласа)",
        work="Географический атлас Российской империи (атлас Пядышева)",
        summary=". ".join(p for p in parts if p) + ".",
        url=DOCUMENT_URL,
        source_id=f"{service.key}:{attrs.get('GazID')}:{attrs.get('ObjectId')}",
        confidence="ok" if point else "no_coords",
        extra=extra,
    )


def records(features: Iterable[dict], service: Service) -> list[ContextRecord]:
    out = []
    for feature in features:
        rec = feature_to_record(feature, service)
        if rec is not None:
            out.append(rec)
    return out
