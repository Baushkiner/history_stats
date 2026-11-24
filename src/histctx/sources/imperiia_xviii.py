"""XVIII век по слоям Imperiia: города 1727 года по Кирилову и уезды по ревизиям.

Зачем эти слои. До 1780-х годов у проекта почти пусто: метрические книги уже
ведутся, а обстановку вокруг них показать нечем. Два слоя Imperiia закрывают
часть этой дыры. Первый — таблица И. К. Кирилова «Цветущее состояние
Всероссийского государства» (1727): по каждому городу — сколько за ним
церквей и монастырей, сколько приказных служителей, офицеров и солдат,
заводов, есть ли архиерейская кафедра. Второй — население уездов по трём
ревизиям из таблицы В. М. Кабузана («Народы России в XVIII веке», 1990,
табл. 1), поставленное в точку уездного города.

**Права.** Эти слои автор Imperiia для скачивания не выпускала: на Harvard
Dataverse, где лежат слои атласа Пядышева, их нет; на карточках сервисов стоит
пометка `layer_downloadable:False`; у слоя «Guberniia (as town clusters)» в
описании сказано, что слой предварительный и за доступом надо обращаться к
редактору. 23.11.2026 из них взяли только факты; 24.11.2026 владелец проекта
сообщил, что согласие владельца получено, — с этого дня собрана и вторая серия
слоёв 1727 года, включая слой с оговоркой, а в `license` записано согласие.
Сами числа — из Кирилова (общественное достояние), из таблицы Кабузана и из
Арсеньева; ссылка на слой и первоисточник — в каждой записи.

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
* Дворы по I ревизии и население уездов 1766 года (добраны 23.11.2026 на тех
  же условиях) — из К. И. Арсеньева, «Статистические очерки России» (1848).
  Число дворов часто дано на несколько городов сразу («Кострома, Буй,
  Судиславль, Любим, Кадый») — запись стоит в точке первого и перечисляет
  остальные. У слоя 1766 года в описании сервиса стоит одно слово «Arsenev»:
  единица счёта не названа, а сумма (7,3 млн) вдвое меньше ревизских итогов
  Кабузана — похоже на души мужского пола, но это догадка, и запись её так
  и подаёт. Пометки набора «not recorded» и «unknown» и нули — «нет
  данных»: записей по ним нет.
* Вторая серия слоёв 1727 года (добрана 24.11.2026 с согласия владельца) —
  те же числа Кирилова, но в другой нумерации городов (`GorID`, 321 город, а
  не 293): сводный слой «Guberniia (as town clusters)» и отдельные слои
  приказных служителей, офицеров и солдат, заводов, монастырей и архиерейских
  кафедр. Числа в отдельных слоях совпадают со сводным, со слоем Кирилова —
  у всех городов, кроме четырёх. В основном слое 27 городов этой серии нет
  (Землянск, Венев, Ряжск, Керенск, Сергиевск, Семипалатная…) — они и
  добавлены в слой `towns_1727_kirilov`; остальные 293 там уже есть.
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
    "© Imperiia Project (К. О'Нил, Гарвард); слой автором для скачивания не выпущен "
    "(пометка на карточке сервиса ArcGIS, на Harvard Dataverse слоя нет) — собран с "
    "согласия владельца, полученного владельцем проекта (сообщено 24.11.2026); ссылка на "
    "слой Imperiia и на первоисточник — в каждой записи"
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

# Вторая серия слоёв 1727 года: нумерация `GorID`, 321 город. Сводный слой
# несёт все числа; отдельные — по одному числу, и по ним добираются города,
# которых в сводном нет. Поле каждого отдельного слоя — его имя в сводном.
CLUSTERS = Service("Guberniia_as_town_clusters_", "b54e987c9b7a4ac4b173e445aeaef66a", 319)
CLUSTER_FIELDS = {"GorID", "Location", "Guberniia", "Status", "State_serv", "Officers__",
                  "Monasterie", "Orthodox_c", "Bishopric", "Factories"}
GORID_LAYERS = (
    (Service("Bishoprics_eparkhiia_", "efd4de4d8fcc4ecc834c99e2ec01d38d", 327), "Bishopric"),
    (Service("Orthodox_Monasteries", "479f12518465428c8a781f31d729873e", 327), "Monasterie"),
    (Service("Government_officials", "69748b1417214386b4ce4b3da2f8fb8b", 260), "State_serv"),
    (Service("Officers_Soldiers", "0908fc6523f4406e8fa788240eb31343", 51), "Officers__"),
    (Service("Factories_craft_centers", "680a797a76444c7c8dadccd0bfb8a700", 66), "Factories"),
)
# Поля серии `GorID` → поля слоя Кирилова (`KID`), чтобы запись строилась одним разбором.
GORID_TO_KIRILOV = {"Orthodox_c": "Orth_chs", "Monasterie": "Monasterie",
                    "State_serv": "Govt_srvnt", "Officers__": "Offcrs_sol",
                    "Factories": "Zavodov", "Bishopric": "eparchies"}


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
        "его округой, а не по самому городу. Слои Imperiia автор для скачивания не "
        "выпускала — собраны с согласия владельца."
    ),
    url=KIRILOV.url, status="harvested", expected_rows=320,
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
        "большую часть Сибири. Слои Imperiia автор для скачивания не выпускала — "
        "собраны с согласия владельца."
    ),
    url=REVISIONS[0].service.url, status="harvested", expected_rows=786,
)

ARSENEV_SOURCE = ("К. И. Арсеньев, «Статистические очерки России» (СПб., 1848); "
                  "геопривязка — Imperiia Project (К. О'Нил, Гарвард), ArcGIS Online")
HOUSEHOLDS = Service("Households_in_1719", "800a78cb81184072b90c9efa2b9bba08", 242)
HOUSEHOLD_FIELDS = {"GorID", "Location", "Guberniia", "Province_1", "goroda_I_u", "dvorov",
                    "iasachnykh", "note"}
POPULATION_1766 = Service("Population_figures_1766", "379ab379ff6b48579e55f9ff1875cf85", 285)
POPULATION_1766_FIELDS = {"GorID", "Location", "Guberniia", "Provintsii", "Uezdnye_go",
                          "Uezd_pop"}

HOUSEHOLDS_1719 = LayerSpec(
    slug="households_1719",
    title="Податные дворы по I ревизии, 1719 (по Арсеньеву)",
    group="admin",
    source=ARSENEV_SOURCE, license=LICENSE,
    description=(
        "Сколько податных дворов числилось за городом с уездом по первой ревизии и "
        "сколько ясачных — по К. И. Арсеньеву (1848), в делении 1719 года на губернии и "
        "провинции. Число нередко дано сразу на несколько городов. Ревизия не охватывала "
        "татар, украинцев и большую часть Сибири. Слой Imperiia автор для скачивания не "
        "выпускала — собран с согласия владельца."
    ),
    url=HOUSEHOLDS.url, status="harvested", expected_rows=213,
)
UEZD_POPULATION_1766 = LayerSpec(
    slug="uezd_population_1766",
    title="Население уездов около 1766 года (по Арсеньеву)",
    group="admin",
    source=ARSENEV_SOURCE, license=LICENSE,
    description=(
        "Сколько населения числилось в уезде около 1766 года, в делении на губернии и "
        "провинции того времени; точка — уездный город, число — весь уезд. Единица счёта "
        "в наборе не названа: сумма вдвое меньше ревизских итогов, похоже на души мужского "
        "пола. Слой Imperiia автор для скачивания не выпускала — собран с согласия "
        "владельца."
    ),
    url=POPULATION_1766.url, status="harvested", expected_rows=248,
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
    """Владелец и открытый доступ."""
    problems = []
    if item.get("owner") != OWNER:
        problems.append(f"{service.name}: владелец {item.get('owner')!r}")
    if item.get("access") != "public":
        problems.append(f"{service.name}: доступ {item.get('access')!r}, а не public")
    # Оговорка «contact the editor for access» у слоёв 1727 года сбор больше не
    # останавливает: согласие владельца получено (сообщено 24.11.2026).
    return problems


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _plural(n: int, one: str, few: str, many: str) -> str:
    """«41 приказный служитель», «36 184 податных двора»: число с разрядами и форма."""
    if n % 10 == 1 and n % 100 != 11:
        word = one
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = few
    else:
        word = many
    return f"{_number(n)} {word}"


def _number(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _point(feature: dict) -> tuple[Optional[float], Optional[float]]:
    geometry = feature.get("geometry") or {}
    lat, lon = geometry.get("y"), geometry.get("x")
    if not valid_coords(lat, lon):
        return None, None
    return round(lat, 5), round(lon, 5)


# --- Кирилов, 1727 ----------------------------------------------------------

def kirilov_record(feature: dict, *, url: str = "", source_id: str = "",
                   note: str = "") -> Optional[ContextRecord]:
    """Город по Кирилову. `url`, `source_id`, `note` — у городов второй серии."""
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
    if note:
        parts.append(note)
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
        summary=". ".join(parts) + ".", url=url or KIRILOV.url,
        source_id=source_id or f"kirilov:{attrs.get('KID')}",
        confidence="ok" if lat is not None else "no_coords", extra=extra,
    )


def kirilov_records(features: Iterable[dict]) -> list[ContextRecord]:
    return [r for r in (kirilov_record(f) for f in features) if r is not None]


GORID_NOTE = ("В основном слое Кирилова у Imperiia этого города нет: он взят из второй серии "
              "слоёв 1727 года (сводный слой «Guberniia (as town clusters)» и отдельные слои "
              "служителей, военных, заводов, монастырей и кафедр)")


def gorid_towns(clusters: Iterable[dict], layers: dict) -> dict:
    """{GorID: объект} серии `GorID` в полях слоя Кирилова.

    Основа — сводный слой; город, которого в нём нет, собирается из отдельных
    слоёв (`layers`: {поле сводного слоя: объекты слоя}). Объект без названия
    (в слое кафедр есть пустая строка с `GorID` 0) пропускается.
    """
    towns: dict = {}
    for feature in clusters:
        attrs = feature.get("attributes") or {}
        if (attrs.get("Location") or "").strip():
            towns[attrs.get("GorID")] = {"geometry": feature.get("geometry"),
                                         "attributes": dict(attrs)}
    for field, features in layers.items():
        for feature in features:
            attrs = feature.get("attributes") or {}
            if not (attrs.get("Location") or "").strip():
                continue
            town = towns.setdefault(attrs.get("GorID"), {
                "geometry": feature.get("geometry"),
                "attributes": {k: attrs.get(k) for k in
                               ("GorID", "Location", "Guberniia", "Status")}})
            town["attributes"].setdefault(field, attrs.get(field))
    out = {}
    for gor_id, town in towns.items():
        attrs = town["attributes"]
        mapped = {"Location": attrs.get("Location"), "Guberniia": attrs.get("Guberniia"),
                  "Status": attrs.get("Status"), "GorID": gor_id}
        for src, dst in GORID_TO_KIRILOV.items():
            mapped[dst] = attrs.get(src)
        out[gor_id] = {"geometry": town["geometry"], "attributes": mapped}
    return out


def gorid_mismatches(clusters: Iterable[dict], layers: dict) -> list[str]:
    """Где отдельный слой расходится со сводным: «Kronshtat: State_serv 14 ≠ 15»."""
    by_id = {(f.get("attributes") or {}).get("GorID"): f.get("attributes") or {}
             for f in clusters}
    out = []
    for field, features in layers.items():
        for feature in features:
            attrs = feature.get("attributes") or {}
            base = by_id.get(attrs.get("GorID"))
            if base is not None and (base.get(field) or 0) != (attrs.get(field) or 0):
                out.append(f"{attrs.get('Location')}: {field} {attrs.get(field)} ≠ "
                           f"{base.get(field)}")
    return out


def gorid_records(towns: dict, kirilov_features: Iterable[dict]) -> list[ContextRecord]:
    """Города серии `GorID`, которых нет в основном слое Кирилова (сверка по названию)."""
    known = {(f.get("attributes") or {}).get("Location") for f in kirilov_features}
    out = []
    for gor_id in sorted(t for t in towns if t is not None):
        town = towns[gor_id]
        if town["attributes"].get("Location") in known:
            continue
        rec = kirilov_record(town, url=CLUSTERS.url, source_id=f"kirilov-gor:{gor_id}",
                             note=GORID_NOTE)
        if rec is not None:
            rec.extra["series"] = "GorID"
            out.append(rec)
    return out


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


# --- дворы 1719 года и уезды 1766 года (Арсеньев) ----------------------------

def _clean(value) -> str:
    text = (str(value).strip() if value is not None else "")
    return "" if text.lower() in ("na", "none") else text


def household_record(feature: dict) -> Optional[ContextRecord]:
    """Дворы по I ревизии. Без дворов и без ясачных («not recorded») записи нет."""
    attrs = feature.get("attributes") or {}
    latin = _clean(attrs.get("Location"))
    households, yasak = _int(attrs.get("dvorov")), _int(attrs.get("iasachnykh"))
    if not latin or (households <= 0 and yasak <= 0):
        return None
    lat, lon = _point(feature)
    covers = _clean(attrs.get("goroda_I_u"))
    province, guberniia = _clean(attrs.get("Province_1")), _clean(attrs.get("Guberniia"))
    name = cyrillic(latin)
    counted = []
    if households:
        counted.append(_plural(households, "податной двор", "податных двора",
                               "податных дворов"))
    if yasak:
        counted.append(f"ясачных — {_number(yasak)}")
    parts = ["По I ревизии за городом с уездом числится: " + ", ".join(counted)]
    several = "," in covers
    if several:
        parts.append(f"Число дано на несколько городов сразу: {cyrillic(covers)} ({covers}); "
                     "точка — первый из них")
    elif covers and covers != latin:
        parts.append(f"В источнике: {covers}")
    where = [x for x in (f"провинция — {province}" if province else "",
                         f"губерния 1719 года — {guberniia}" if guberniia else "") if x]
    if where:
        parts.append("В наборе: " + ", ".join(where))
    parts.append("Ревизия считала податное население и охватывала не всех")
    title_number = (_plural(households, "двор", "двора", "дворов") if households
                    else f"{_number(yasak)} ясачных")
    return HOUSEHOLDS_1719.new_record(
        title=f"{name} ({latin}): I ревизия — {title_number}",
        category="несколько городов вместе" if several else "город с уездом",
        lat=lat, lon=lon,
        place_text=", ".join(x for x in (covers or latin, province, guberniia) if x),
        year_from=1719, year_to=1724, date_precision="year",
        period_raw="I ревизия: 1719 — начало 1720-х",
        work="К. И. Арсеньев. Статистические очерки России",
        summary=". ".join(parts) + ".", url=HOUSEHOLDS.url,
        source_id=f"households1719:{attrs.get('GorID')}",
        confidence="place_level" if lat is not None else "no_coords",
        extra={"name_latin": latin, "covers": covers, "province_1719": province,
               "guberniia_1719": guberniia, "households": households, "yasak": yasak},
    )


def household_records(features: Iterable[dict]) -> list[ContextRecord]:
    return [r for r in (household_record(f) for f in features) if r is not None]


def population_1766_record(feature: dict) -> Optional[ContextRecord]:
    """Уезд около 1766 года. Ноль и пусто — «нет данных»: записи нет."""
    attrs = feature.get("attributes") or {}
    latin = _clean(attrs.get("Location"))
    population = _int(attrs.get("Uezd_pop"))
    if not latin or population <= 0:
        return None
    lat, lon = _point(feature)
    uezd_town = _clean(attrs.get("Uezdnye_go"))
    province, guberniia = _clean(attrs.get("Provintsii")), _clean(attrs.get("Guberniia"))
    name = cyrillic(latin)
    parts = [f"Около 1766 года в уезде числится {_number(population)} (число — как в "
             "наборе; единица счёта не названа, по сумме похоже на души мужского пола)"]
    parts.append(f"Точка — город {name} ({latin}), число относится ко всему уезду")
    where = [x for x in (f"провинция — {province}" if province else "",
                         f"губерния — {guberniia}" if guberniia else "") if x]
    if where:
        parts.append("В наборе: " + ", ".join(where))
    return UEZD_POPULATION_1766.new_record(
        title=f"{name} ({latin}), уезд около 1766 года: {_number(population)}",
        category="уезд в провинции" if province else "уезд без провинции",
        lat=lat, lon=lon,
        place_text=", ".join(x for x in (uezd_town or latin, province, guberniia) if x),
        year_from=1766, year_to=1766, date_precision="year", date_approx=True,
        period_raw="1766 (дата слоя; в описании — только «Arsenev»)",
        work="К. И. Арсеньев. Статистические очерки России",
        summary=". ".join(parts) + ".", url=POPULATION_1766.url,
        source_id=f"population1766:{attrs.get('GorID')}",
        confidence="place_level" if lat is not None else "no_coords",
        extra={"name_latin": latin, "uezd_town_source": uezd_town, "province_1766": province,
               "guberniia_1766": guberniia, "population": population},
    )


def population_1766_records(features: Iterable[dict]) -> list[ContextRecord]:
    return [r for r in (population_1766_record(f) for f in features) if r is not None]
