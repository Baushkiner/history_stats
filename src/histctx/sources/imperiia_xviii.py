"""XVIII век по слоям Imperiia: города 1727 года по Кирилову и уезды по ревизиям.

Зачем эти слои. До 1780-х годов у проекта почти пусто: метрические книги уже
ведутся, а обстановку вокруг них показать нечем. Два слоя Imperiia закрывают
часть этой дыры. Первый — таблица И. К. Кирилова «Цветущее состояние
Всероссийского государства» (1727): по каждому городу — сколько за ним
церквей и монастырей, сколько приказных служителей, офицеров и солдат,
заводов, есть ли архиерейская кафедра. Второй — население уездов по трём
ревизиям из таблицы В. М. Кабузана («Народы России в XVIII веке», 1990,
табл. 1), поставленное в точку уездного города.

**Права: только факты.** Эти слои автор Imperiia для скачивания не выпускала:
на Harvard Dataverse, где лежат слои атласа Пядышева, их нет; на карточках
сервисов стоит пометка `layer_downloadable:False`; у соседнего слоя 1727 года
в описании прямо сказано, что слой предварительный и за доступом надо
обращаться к редактору. Владелец проекта решил 23.11.2026 взять из них только
факты — место, год и числа — со ссылкой на слой; так и записано в `license`.
Сами числа — из Кирилова (общественное достояние) и из таблицы Кабузана.
Слой с прямой оговоркой («Guberniia (as town clusters)») не запрашивается.

Что надо знать о числах.

* У Кирилова счёт идёт по городу вместе с приписанной к нему округой: 776
  церквей «за Тихвином» — это не город Тихвин. Запись так и говорит.
* Ревизии — население **уезда**, а точка — уездный город: запись помечена
  `place_level`. Ревизия считала податное население: татар, украинцев и
  большую часть Сибири первые ревизии не охватывали, нули в наборе — «нет
  данных», а не «никого», и такие записи не создаются.
* Третий срез назван в наборе «третьей ревизией» и отнесён к 1781 году. Это
  не сходится: третья ревизия шла в 1761–1767 годах, а в 1781–1782 — четвёртая.
  Какая из двух стоит в таблице, по набору не установить; запись покрывает
  1762–1785 годы и помечена `date_approx` — интервал расширен, а не угадан.
* Названия — латиницей набора и обратной транслитерацией; губерния набора
  (у Кирилова — провинция 1727 года, у ревизий — губерния позднейшего деления)
  остаётся в `place_text`, а `region` — по полигонам 1897 года.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..geo import valid_coords
from ..schema import ContextRecord, LayerSpec
from .imperiia import cyrillic

ITEM_PAGE = "https://www.arcgis.com/home/item.html?id={item}"
OWNER = "koneill_worldmap"
LICENSE = (
    "Права не выяснены, слой автором для скачивания не выпущен (пометка на карточке "
    "сервиса ArcGIS; на Harvard Dataverse слоя нет): берутся только факты — место, год и "
    "числа — со ссылкой на слой Imperiia Project (К. О'Нил, Гарвард) и на первоисточник"
)


@dataclass(frozen=True)
class Service:
    """Сервис FeatureServer: имя, карточка, число объектов 23.11.2026."""

    name: str
    item: str
    count: int

    @property
    def url(self) -> str:
        return ITEM_PAGE.format(item=self.item)


KIRILOV = Service("Orthodox_Churches_1727", "cfcad46e8e704ab1b8e4184234364467", 293)
KIRILOV_FIELDS = {"KID", "Guberniia", "Location", "Status", "Monasterie", "Orth_chs",
                  "Govt_srvnt", "Offcrs_sol", "Zavodov", "eparchies"}


@dataclass(frozen=True)
class Revision:
    key: str
    service: Service
    field: str
    title: str               # «I ревизия»
    years: tuple[int, int]
    approx: bool
    period_raw: str
    note: str = ""


REVISIONS = (
    Revision("1", Service("Population_in_1719_1st_revision_by_town",
                          "389c59311d1b4cbc8c802e39694648a9", 275),
             "First_Revi", "I ревизия", (1719, 1724), False,
             "I ревизия: указ 1719 года, окончена в начале 1720-х"),
    Revision("2", Service("Population_c_1743_2nd_revision_by_town",
                          "5ad9a7d6c93b4284a26ea01e1ef23975", 275),
             "Second_Rev", "II ревизия", (1743, 1747), False,
             "II ревизия: указ 1743 года, окончена через несколько лет"),
    Revision("3", Service("Population_3rd_revision_1781", "6caa07a836b846788de90019a26a4850",
                          275),
             "Third_Revi", "ревизия 1760-х или 1780-х годов", (1762, 1785), True,
             "в наборе: «3rd revision, 1781»",
             note=("В наборе срез назван третьей ревизией и отнесён к 1781 году; третья "
                   "ревизия шла в 1761–1767 годах, четвёртая — в 1781–1782: какая из двух "
                   "стоит в таблице, не установлено")),
)
REVISION_FIELDS = {"GorID", "Location", "Guberniia", "Uezd__coun"}

KIRILOV_SOURCE = ("И. К. Кирилов, «Цветущее состояние Всероссийского государства» (1727); "
                  "геопривязка — Imperiia Project (К. О'Нил, Гарвард), ArcGIS Online")
REVISIONS_SOURCE = ("В. М. Кабузан, «Народы России в XVIII веке» (М.: Наука, 1990), табл. 1; "
                    "геопривязка — Imperiia Project (К. О'Нил, Гарвард), ArcGIS Online")

TOWNS_1727 = LayerSpec(
    slug="towns_1727_kirilov",
    title="Города 1727 года по Кирилову: церкви, монастыри, служители, заводы",
    group="faith",
    source=KIRILOV_SOURCE, license=LICENSE,
    description=(
        "Что было за городом в 1727 году: число церквей и монастырей, приказных "
        "служителей, офицеров и солдат, заводов, архиерейская кафедра и место города в "
        "делении на провинции — по описанию И. К. Кирилова. Счёт идёт по городу вместе с "
        "его округой, а не по самому городу. Из слоя Imperiia взяты только факты: автор "
        "слой для скачивания не выпускала."
    ),
    url=KIRILOV.url, status="harvested", expected_rows=293,
)
REVISIONS_UEZD = LayerSpec(
    slug="revisions_uezd_towns",
    title="Население уездов по ревизиям XVIII века (таблица Кабузана)",
    group="admin",
    source=REVISIONS_SOURCE, license=LICENSE,
    description=(
        "Сколько податного населения числилось в уезде по ревизиям XVIII века — I (1719), "
        "II (1743) и срезу 1760-х или 1780-х годов, по таблице В. М. Кабузана; точка — "
        "уездный город, число — весь уезд. Ревизии не охватывали татар, украинцев и "
        "большую часть Сибири. Из слоёв Imperiia взяты только факты: автор их для "
        "скачивания не выпускала."
    ),
    url=REVISIONS[0].service.url, status="harvested", expected_rows=786,
)

STATUS_RU = {
    "capital": "город провинции (главный)", "pripisnyj": "приписной город",
    "prigorod": "пригород", "fortress": "крепость",
}


def check_layer(info: dict, service: Service, required: set,
                actual_count: Optional[int]) -> list[str]:
    problems = []
    if info.get("geometryType") != "esriGeometryPoint":
        problems.append(f"{service.name}: геометрия {info.get('geometryType')}, "
                        "ожидались точки")
    fields = {f.get("name") for f in info.get("fields") or []}
    missing = sorted(required - fields)
    if missing:
        problems.append(f"{service.name}: нет полей {', '.join(missing)}")
    if actual_count != service.count:
        problems.append(f"{service.name}: объектов {actual_count}, в коде {service.count}")
    return problems


def check_item(item: dict, service: Service) -> list[str]:
    """Владелец и открытый доступ; оговорка «по запросу у редактора» — остановка."""
    problems = []
    if item.get("owner") != OWNER:
        problems.append(f"{service.name}: владелец {item.get('owner')!r}")
    if item.get("access") != "public":
        problems.append(f"{service.name}: доступ {item.get('access')!r}, а не public")
    if "contact the editor" in (item.get("description") or "").lower():
        problems.append(f"{service.name}: в описании слоя появилась оговорка о доступе по "
                        "запросу — такой слой не собирается")
    return problems


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {few}"
    return f"{n} {many}"


def _number(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _point(feature: dict) -> tuple[Optional[float], Optional[float]]:
    geometry = feature.get("geometry") or {}
    lat, lon = geometry.get("y"), geometry.get("x")
    if not valid_coords(lat, lon):
        return None, None
    return round(lat, 5), round(lon, 5)


# --- Кирилов, 1727 ----------------------------------------------------------

def kirilov_record(feature: dict) -> Optional[ContextRecord]:
    attrs = feature.get("attributes") or {}
    latin = (attrs.get("Location") or "").strip()
    if not latin:
        return None
    lat, lon = _point(feature)
    province = (attrs.get("Guberniia") or "").strip()
    status = STATUS_RU.get((attrs.get("Status") or "").strip())
    churches, monasteries = _int(attrs.get("Orth_chs")), _int(attrs.get("Monasterie"))
    officials, military = _int(attrs.get("Govt_srvnt")), _int(attrs.get("Offcrs_sol"))
    factories, see = _int(attrs.get("Zavodov")), bool(_int(attrs.get("eparchies")))
    name = cyrillic(latin)

    counted = []
    if churches:
        counted.append(_plural(churches, "церковь", "церкви", "церквей"))
    if monasteries:
        counted.append(_plural(monasteries, "монастырь", "монастыря", "монастырей"))
    if officials:
        counted.append(_plural(officials, "приказный служитель", "приказных служителя",
                               "приказных служителей"))
    if military:
        counted.append(_plural(military, "офицер и солдат", "офицера и солдата",
                               "офицеров и солдат"))
    if factories:
        counted.append(_plural(factories, "завод", "завода", "заводов"))
    parts = []
    if counted:
        parts.append("По Кирилову за городом с его округой числится: " + ", ".join(counted))
    else:
        parts.append("У Кирилова город назван, чисел за ним в наборе нет")
    if see:
        parts.append("Здесь архиерейская кафедра")
    where = []
    if status:
        where.append(status)
    if province:
        where.append(f"провинция в наборе — {province}")
    if where:
        text = "; ".join(where)
        parts.append(text[:1].upper() + text[1:])
    river = (attrs.get("geo_river") or "").strip()
    if river:
        parts.append(f"Стоит на реке {cyrillic(river)} ({river})")
    parts.append("Название кириллицей — обратная транслитерация из латиницы набора")

    if churches and monasteries:
        category = "церкви и монастыри"
    elif churches:
        category = "церкви"
    elif monasteries:
        category = "монастыри"
    else:
        category = "без церквей в описании"
    title_tail = _plural(churches, "церковь", "церкви", "церквей") if churches else (
        "церквей не показано")
    extra = {"name_latin": latin, "province_1727": province, "churches": churches,
             "monasteries": monasteries, "officials": officials, "officers_soldiers": military,
             "factories": factories, "bishopric": see}
    if attrs.get("Status"):
        extra["status_source"] = attrs["Status"]
    if river:
        extra["river"] = river
    return TOWNS_1727.new_record(
        title=f"{name} ({latin}) в 1727 году: {title_tail}", category=category,
        lat=lat, lon=lon, place_text=", ".join(x for x in (latin, province) if x),
        year_from=1727, year_to=1727, date_precision="year", period_raw="1727",
        work="И. К. Кирилов. Цветущее состояние Всероссийского государства",
        summary=". ".join(parts) + ".", url=KIRILOV.url,
        source_id=f"kirilov:{attrs.get('KID')}",
        confidence="ok" if lat is not None else "no_coords", extra=extra,
    )


def kirilov_records(features: Iterable[dict]) -> list[ContextRecord]:
    return [r for r in (kirilov_record(f) for f in features) if r is not None]


# --- ревизии ----------------------------------------------------------------

def revision_record(feature: dict, revision: Revision) -> Optional[ContextRecord]:
    """Запись «уезд по ревизии». Ноль и пусто в наборе — «нет данных»: записи нет."""
    attrs = feature.get("attributes") or {}
    population = _int(attrs.get(revision.field))
    latin = (attrs.get("Location") or "").strip()
    if population <= 0 or not latin:
        return None
    lat, lon = _point(feature)
    uezd = (attrs.get("Uezd__coun") or "").strip()
    province = (attrs.get("Guberniia") or "").strip()
    name = cyrillic(latin)
    parts = [f"{revision.title[:1].upper()}{revision.title[1:]}: в уезде числится "
             f"{_number(population)} человек (число — как в таблице Кабузана)"]
    parts.append(f"Точка — город {name} ({latin}), число относится ко всему уезду"
                 + (f" ({uezd})" if uezd and uezd != latin else ""))
    if province:
        parts.append(f"Губерния в наборе — {province}")
    if revision.note:
        parts.append(revision.note)
    parts.append("Ревизия считала податное население и охватывала не всех")
    return REVISIONS_UEZD.new_record(
        title=f"{name} ({latin}), уезд: {revision.title} — {_number(population)} человек",
        category=revision.title, lat=lat, lon=lon,
        place_text=", ".join(x for x in (latin, uezd if uezd != latin else "", province) if x),
        year_from=revision.years[0], year_to=revision.years[1], date_precision="year",
        date_approx=revision.approx, period_raw=revision.period_raw,
        work="В. М. Кабузан. Народы России в XVIII веке, табл. 1",
        summary=". ".join(parts) + ".", url=revision.service.url,
        source_id=f"revision{revision.key}:{attrs.get('GorID')}",
        confidence="place_level" if lat is not None else "no_coords",
        extra={"name_latin": latin, "uezd_source": uezd, "province_source": province,
               "region_source": (attrs.get("Region") or "").strip(),
               "population": population, "revision": revision.key},
    )


def revision_records(features: Iterable[dict], revision: Revision) -> list[ContextRecord]:
    return [r for r in (revision_record(f, revision) for f in features) if r is not None]
