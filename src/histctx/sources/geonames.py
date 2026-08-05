"""Населённые места из GeoNames — скелет карты.

Зачем. Все остальные слои цепляются к населённому месту: приход, ярмарка,
станция, усадьба, сама запись из метрической книги. Без этого слоя карта
пуста между точками, а поиск «что было рядом» не с чем сравнивать.

Откуда. Набор GeoNames в виде пакета `geonamescache` (данные CC BY 4.0,
код пакета MIT). Взят `cities500` — населённые места, у которых в GeoNames
указано население от 500 человек. Пакетный реестр доступен там, где закрыты
сайты источников, и это единственная причина, по которой слой удалось
собрать здесь, а не через Викиданные: запрос `queries/settlements.rq` никуда
не делся и остаётся вторым источником для сведения.

Три честных ограничения, и все три записаны в самом слое, а не только тут:

* **Дат нет.** В наборе нет года основания. Приписывать населённому месту
  срок «1800–1960» нельзя: Магнитогорск основан в 1929 году, Норильск в
  1935-м, и такая датировка была бы выдумкой. Записи идут без датировки и в
  подборе по времени участвуют с пониженным весом.
* **Губернии нет.** Код единицы (`admin1code`) в наборе есть, а справочника
  названий к нему — нет. Приписать «Московская область» по коду наугад хуже,
  чем оставить поле пустым: подбор по территории поверит.
* **Население современное.** Оно годится как признак размера места, но не
  как сведение о XIX веке, и лежит в `extra`, а не в описании.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Optional

from ..geo import in_bbox, valid_coords
from ..schema import LayerSpec, clean_text

SETTLEMENTS = LayerSpec(
    slug="settlements",
    title="Населённые места",
    group="admin",
    source="GeoNames (через пакет geonamescache)",
    license="CC BY 4.0 — обязательна ссылка на GeoNames; код пакета MIT",
    description=(
        "Города, посёлки и сёла с координатами — скелет карты, к которому цепляются "
        "остальные слои. Года основания в наборе нет, поэтому слой участвует в подборе "
        "как место, а не как событие."
    ),
    url="https://www.geonames.org/",
    status="harvested",
)

# Страны, на территории которых лежала Российская империя или СССР.
# Польша и Финляндия входят целиком: отделять Царство Польское от прусской
# части по современным границам всё равно нечем, а лишние точки на западе
# вредят меньше, чем пропущенные губернские города.
COUNTRIES = {
    "RU": "Россия", "UA": "Украина", "BY": "Белоруссия", "MD": "Молдавия",
    "LT": "Литва", "LV": "Латвия", "EE": "Эстония", "PL": "Польша", "FI": "Финляндия",
    "KZ": "Казахстан", "UZ": "Узбекистан", "TM": "Туркмения", "TJ": "Таджикистан",
    "KG": "Киргизия", "AM": "Армения", "AZ": "Азербайджан", "GE": "Грузия",
}

# Пороги размера. Границы условные и служат одному: отличить губернский город
# от деревни в подписи, чтобы на карте было видно, что крупнее.
SIZES = ((100_000, "город"), (10_000, "малый город"), (2_000, "посёлок"), (0, "село"))

_RE_CYRILLIC = re.compile(r"^[А-ЯЁ][А-Яа-яЁё\s\-’']*$")


class GeoNamesError(RuntimeError):
    """Набор GeoNames недоступен."""


def load_cities(dataset: str = "cities500") -> list[dict]:
    """Читает набор из пакета geonamescache.

    Пакет ставится отдельно (`pip install geonamescache`) и весит немало,
    поэтому он не в обязательных зависимостях: без него работает всё
    остальное, а не падает сборка целиком.
    """
    try:
        import geonamescache
    except ImportError as exc:  # pragma: no cover — проверяется руками
        raise GeoNamesError(
            "нет пакета geonamescache: pip install geonamescache. "
            "Данные GeoNames распространяются под CC BY 4.0."
        ) from exc

    gc = geonamescache.GeonamesCache(min_city_population=_population_of(dataset))
    cities = gc.get_cities()
    if not cities:
        raise GeoNamesError(f"набор {dataset} пуст")
    return list(cities.values())


def _population_of(dataset: str) -> int:
    try:
        return int(dataset.replace("cities", ""))
    except ValueError as exc:
        raise GeoNamesError(f"неизвестный набор {dataset!r}") from exc


def select(cities: Iterable[dict], *, countries: Optional[set] = None,
           min_population: int = 0) -> Iterator[dict]:
    """Оставляет то, что относится к территории РИ/СССР."""
    allowed = countries if countries is not None else set(COUNTRIES)
    for city in cities:
        if city.get("countrycode") not in allowed:
            continue
        lat, lon = city.get("latitude"), city.get("longitude")
        if not valid_coords(lat, lon) or not in_bbox(float(lat), float(lon)):
            continue
        if (city.get("population") or 0) < min_population:
            continue
        yield city


def to_records(cities: Iterable[dict], spec: LayerSpec = SETTLEMENTS) -> list:
    """Приводит записи набора к единой схеме."""
    out, seen = [], set()
    for city in cities:
        gid = city.get("geonameid")
        if gid is None or gid in seen:
            continue
        seen.add(gid)
        lat, lon = float(city["latitude"]), float(city["longitude"])
        latin = clean_text(city.get("name")) or str(gid)
        russian = pick_russian_name(city)
        title = russian or latin
        population = int(city.get("population") or 0)
        country = COUNTRIES.get(city.get("countrycode"), city.get("countrycode"))

        extra = {"population_modern": population, "country": country,
                 "geonameid": gid, "admin1code": clean_text(city.get("admin1code"))}
        if russian and russian != latin:
            extra["name_latin"] = latin

        out.append(spec.new_record(
            title=title,
            category=size_of(population),
            lat=lat, lon=lon,
            # Губерния намеренно не заполняется: в наборе есть только код
            # современной единицы, а справочника названий к нему нет.
            # Описание тоже не пишется: у семнадцати тысяч записей это была бы
            # одна и та же фраза с подставленными числами, а сами числа лежат
            # рядом в extra и годятся для подписи на карте как есть.
            url=f"https://www.geonames.org/{gid}",
            source_id=str(gid),
            extra={k: v for k, v in extra.items() if v not in (None, "")},
        ))
    return out


def pick_russian_name(city: dict) -> Optional[str]:
    """Кириллическое написание из альтернативных названий, если оно есть.

    Оно важнее латинского: в метрической книге село называется по-русски, и
    сопоставлять придётся с ним.
    """
    for name in city.get("alternatenames") or []:
        text = clean_text(name)
        if text and _RE_CYRILLIC.match(text):
            return text
    return None


def size_of(population: int) -> str:
    for limit, label in SIZES:
        if population >= limit:
            return label
    return "село"


# Письменности, которые для поиска по русским документам ничего не дают.
# Иврит, армянский, грузинский и арабица оставлены намеренно: метрические
# книги велись и на них, и написание из документа надо с чем-то сверять.
_RE_USELESS_SCRIPT = re.compile(
    r"[　-鿿가-힯぀-ヿ฀-๿ऀ-ॿ]"
)


def name_variants(cities: Iterable[dict], *, max_per_place: int = 12) -> dict:
    """Собирает написания названий: как место называли в разных языках и эпохах.

    Для генеалогии это отдельная ценность, а не украшение. Село в метрической
    книге названо не так, как на нынешней карте: Совєташен вместо Зангакатуна,
    Dorpat вместо Тарту, Вильна вместо Вильнюса. Поиск по одному написанию
    такой род теряет.

    Возвращает словарь по местам, а не обратный индекс: одно и то же название
    носят десятки деревень, и обратный индекс собирается из этого одной
    строкой на стороне карты — а обратно точность уже не вернуть.
    """
    out = {}
    for city in cities:
        gid = city.get("geonameid")
        if gid is None:
            continue
        title = pick_russian_name(city) or clean_text(city.get("name"))
        if not title:
            continue
        seen = {title.casefold()}
        names = []
        for raw in city.get("alternatenames") or []:
            name = clean_text(raw)
            if not name or name.casefold() in seen:
                continue
            if _RE_USELESS_SCRIPT.search(name):
                continue
            seen.add(name.casefold())
            names.append(name)
            if len(names) >= max_per_place:
                break
        if not names:
            continue
        out[str(gid)] = {
            "title": title,
            "lat": round(float(city["latitude"]), 5),
            "lon": round(float(city["longitude"]), 5),
            "names": names,
        }
    return out
