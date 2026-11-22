"""Остальные слои атласа Пядышева (1820–1827): селения, укрепления, храмы, заводы,
дороги и границы. Проект Imperiia, открытые сервисы автора на ArcGIS Online.

Зачем эти слои. Почтовые станции (`sources/imperiia.py`) — один лист легенды
атласа из двух десятков. Остальное отвечает на вопросы, которые до сих пор
оставались без ответа для первой трети XIX века: чем было это место в 1820-е
годы — уездным городом, местечком, селом или деревней; стояла ли рядом
крепость, редут или кордон; был ли здесь монастырь или лютеранская кирха,
завод или рудник; какой дорогой сюда ехали и в какой губернии и каком уезде
место числилось до реформ середины века.

Что берётся. Проход по учётной записи `koneill_worldmap` 22.11.2026 нашёл
473 открытых сервиса, из них 81 — слои атласа (остальное — другие проекты
Imperiia и производные карты). Из 81 собираются 23 точечных слоя, семь
слоёв линий и пять слоёв полигонов; дубли одного слоя под двумя именами,
листы-рамки отдельных губерний и производные карты (плотность населения,
черта оседлости) — нет. Перечень — `POINT_KINDS`, `LINE_KINDS`, `AREA_KINDS`.

Четыре слоя записей и две подложки:

* `settlements_1820` — города, местечки, сёла, деревни, хутора, станицы;
* `fortifications_1820` — крепости, редуты, форпосты, кордоны, военные лагеря;
* `faith_sites_1820` — монастыри, мечети, протестантские приходы;
* `economy_sites_1820` — заводы, рудники, корчмы, таможни;
* `roads_1820.geojson` — почтовые, губернские, уездные и просёлочные дороги,
  сезонные пути, каналы и укреплённые линии: линия записью «что, где, когда»
  не становится, она идёт подложкой, как границы;
* `boundaries_1820.geojson` и `districts_1820.geojson` — губернии, области,
  воеводства и уезды 1820-х годов полигонами.

**Атлас — не список населённых мест.** Масштаб листа — около 20 вёрст в дюйме:
на него попали все города и только те сёла и деревни, которые составитель счёл
нужным показать, — при дорогах, с церковью, с почтой. Десять тысяч сёл и
деревней на всю империю — это выборка; отсутствие деревни в слое ничего не
говорит о том, была ли она.

Названия. Там, где в наборе есть русское написание (поле `Name_Rs`), оно и
берётся; сервис отдаёт его испорченной кодировкой (UTF-8, прочитанный как
latin-1) — сборщик чинит. Там, где его нет (города, монастыри, приходы,
корчмы), — обратная транслитерация из латиницы, как у почтовых станций, и
запись об этом говорит. Губерния в поле `region` — по полигонам 1897 года,
губерния и уезд атласа остаются в `place_text` и `extra`.

Права те же, что у станций: CC BY-NC-SA 4.0 по сайту проекта и карточке
набора на Dataverse; на карточках сервисов лицензия не указана.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..geo import valid_coords
from ..schema import ContextRecord, LayerSpec
from .huri import esri_polygon, simplify
from .imperiia import LICENSE, YEARS, cyrillic, settlement_type, sheet_number

GALLERY_URL = "https://imperiia.omeka.fas.harvard.edu/exhibits/show/2_profile"
ATLAS = "«Географический атлас Российской империи» В. П. Пядышева, 1820–1827"
SOURCE = ("Imperiia Project (К. О'Нил, Гарвард): слои «Географического атласа Российской "
          "империи» В. П. Пядышева, 1820–1827; ArcGIS Online")
CITATION = (
    "O'Neill, Kelly. The Imperiia Project: An Historical GIS of the Russian Empire. "
    "Harvard University, Davis Center; слои атласа Пядышева на ArcGIS Online, учётная "
    "запись koneill_worldmap. Источник: Географический атлас Российской империи, Царства "
    "Польского и Великого княжества Финляндского, 1820–1827"
)
SELECTION_NOTE = "Сёла и деревни в атласе — выборка, а не полный перечень"

SETTLEMENTS_1820 = LayerSpec(
    slug="settlements_1820",
    title="Города, сёла и деревни 1820-х годов (атлас Пядышева)",
    group="admin",
    source=SOURCE, license=LICENSE,
    description=(
        "Чем было место в 1820-е годы: губернский, уездный или заштатный город, "
        "местечко, село, деревня, хутор, казачья станица — с губернией и уездом по "
        "атласу Пядышева. Города — все, сёла и деревни — выборка составителя атласа "
        "(около десяти тысяч на империю): отсутствие деревни в слое не значит, что её "
        "не было. Часть названий — обратная транслитерация из латиницы набора."
    ),
    url=GALLERY_URL, status="harvested", expected_rows=12024,
)
FORTIFICATIONS_1820 = LayerSpec(
    slug="fortifications_1820",
    title="Крепости, редуты, форпосты и кордоны 1820-х годов (атлас Пядышева)",
    group="military",
    source=SOURCE, license=LICENSE,
    description=(
        "Стояла ли рядом крепость или пограничный пост: крепости, редуты и малые "
        "укрепления, форпосты, кордоны и военные лагеря по листам атласа Пядышева — "
        "Кавказская и Оренбургская линии, Сибирь, западная граница. Объясняет, откуда в "
        "метрике солдаты, казаки и «служилые» и почему приход военный."
    ),
    url=GALLERY_URL, status="harvested", expected_rows=304,
)
FAITH_1820 = LayerSpec(
    slug="faith_sites_1820",
    title="Монастыри, мечети и протестантские приходы 1820-х годов (атлас Пядышева)",
    group="faith",
    source=SOURCE, license=LICENSE,
    description=(
        "Монастыри, мечети и протестантские приходы, показанные на листах атласа "
        "Пядышева: был ли у места свой монастырь или кирха в 1820-е годы. Православные "
        "приходские церкви атлас отдельно не показывает — этот слой их не заменяет; "
        "протестантские приходы почти все в Финляндии."
    ),
    url=GALLERY_URL, status="harvested", expected_rows=262,
)
ECONOMY_1820 = LayerSpec(
    slug="economy_sites_1820",
    title="Заводы, рудники, корчмы и таможни 1820-х годов (атлас Пядышева)",
    group="economy",
    source=SOURCE, license=LICENSE,
    description=(
        "Куда уходили на заработки и где проходила граница: заводы и фабрики, рудники, "
        "корчмы при дорогах и таможни по листам атласа Пядышева. Атлас показывает только "
        "то, что составитель счёл заметным на местности, — это не перепись заводов."
    ),
    url=GALLERY_URL, status="harvested", expected_rows=211,
)
ROADS_1820 = LayerSpec(
    slug="roads_1820",
    title="Дороги, каналы и укреплённые линии 1820-х годов (атлас Пядышева)",
    group="economy",
    source=SOURCE, license=LICENSE,
    description=(
        "Какой дорогой сюда ехали до железных дорог: почтовые, губернские, уездные и "
        "просёлочные дороги, сезонные пути, каналы и укреплённые линии по листам атласа "
        "Пядышева — линиями, подложкой карты (`boundaries/roads_1820.geojson`), а не "
        "записями: у линии нет точки, по которой подбирается контекст."
    ),
    url=GALLERY_URL, status="harvested", expected_rows=7738, gives_records=False,
)
ADMIN_BOUNDARIES_1820 = LayerSpec(
    slug="admin_boundaries_1820",
    title="Губернии и уезды 1820-х годов (атлас Пядышева)",
    group="admin",
    source=SOURCE, license=LICENSE,
    description=(
        "В какой губернии и каком уезде место числилось в 1820-е годы — до реформ, "
        "после которых сложилась сетка 1897 года: губернии, области, воеводства Царства "
        "Польского и особые территории (`boundaries/boundaries_1820.geojson`) и уезды "
        "(`boundaries/districts_1820.geojson`) полигонами. Названия — латиницей набора и "
        "обратной транслитерацией."
    ),
    url=GALLERY_URL, status="harvested", expected_rows=686, gives_records=False,
)
RECORD_LAYERS = (SETTLEMENTS_1820, FORTIFICATIONS_1820, FAITH_1820, ECONOMY_1820)


@dataclass(frozen=True)
class Kind:
    """Сервис FeatureServer и то, чем его объекты становятся в слое."""

    key: str
    service: str
    count: int               # объектов на сервере 22.11.2026
    spec: LayerSpec
    category: str
    word: str

    @property
    def name(self) -> str:   # то же имя поля, что у `imperiia.Service`: клиент общий
        return self.service


# Точечные слои. Число объектов сверено с сервером; разошлось — сбор стоит.
POINT_KINDS = (
    Kind("provincial_town", "Provincial_towns", 57, SETTLEMENTS_1820,
         "губернский город", "Губернский город"),
    Kind("district_town", "District_towns", 459, SETTLEMENTS_1820,
         "уездный город", "Уездный город"),
    Kind("town", "Towns_non_administrative_", 102, SETTLEMENTS_1820,
         "заштатный город", "Заштатный город"),
    Kind("large_town", "Large_towns", 17, SETTLEMENTS_1820, "крупный город", "Город"),
    Kind("mid_town", "Mid_sized_towns", 48, SETTLEMENTS_1820, "средний город", "Город"),
    Kind("minor_town", "Minor_towns", 1067, SETTLEMENTS_1820,
         "малый город, местечко", "Местечко"),
    Kind("walled_town", "Fortified_unfortified_towns", 12, SETTLEMENTS_1820,
         "город Закавказья", "Город"),
    Kind("selo", "Villages_sela_", 5507, SETTLEMENTS_1820, "село или слобода", "Село"),
    Kind("derevnia", "Villages_derevni_", 4455, SETTLEMENTS_1820, "деревня", "Деревня"),
    Kind("khutor", "Farmsteads_khutors_", 228, SETTLEMENTS_1820, "хутор", "Хутор"),
    Kind("stanitsa", "Cossack_villages", 72, SETTLEMENTS_1820,
         "казачья станица", "Станица"),
    Kind("fortress", "Fortresses", 122, FORTIFICATIONS_1820, "крепость", "Крепость"),
    Kind("redoubt", "Redoubts", 89, FORTIFICATIONS_1820,
         "редут или малое укрепление", "Редут"),
    Kind("forepost", "Foreposts", 40, FORTIFICATIONS_1820, "форпост", "Форпост"),
    Kind("cordon", "Cordons", 30, FORTIFICATIONS_1820, "кордон", "Кордон"),
    Kind("encampment", "Encampments", 23, FORTIFICATIONS_1820,
         "военный лагерь", "Военный лагерь"),
    Kind("monastery", "Monasteries", 75, FAITH_1820, "монастырь", "Монастырь"),
    Kind("mosque", "Mosques", 4, FAITH_1820, "мечеть", "Мечеть"),
    Kind("protestant_parish", "Protestant_church_parishes", 183, FAITH_1820,
         "протестантский приход", "Протестантский приход"),
    Kind("factory", "31122130_4d6d_11e6_a784_22000b8406af", 148, ECONOMY_1820,
         "завод или фабрика", "Завод"),
    Kind("mine", "d432d3ae_4d6e_11e6_a784_22000b8406af", 24, ECONOMY_1820,
         "рудник", "Рудник"),
    Kind("tavern", "Taverns", 29, ECONOMY_1820, "корчма", "Корчма"),
    Kind("customs", "acd222f6_5f1b_11e6_a667_22000b8406af", 10, ECONOMY_1820,
         "таможня", "Таможня"),
)

# Подписи категории у городов Закавказья (сервис «Fortified & unfortified towns»).
WALLED = {
    "large fortified town": "крупный укреплённый город",
    "large unfortified town": "крупный неукреплённый город",
    "small fortified town": "малый укреплённый город",
    "small unfortified town": "малый неукреплённый город",
}


@dataclass(frozen=True)
class LineKind:
    key: str
    service: str
    count: int
    label: str

    @property
    def name(self) -> str:
        return self.service


LINE_KINDS = (
    LineKind("post_road", "Post_roads", 1093, "почтовая дорога"),
    LineKind("provincial_road", "Post_roads_provincial_level_", 947, "губернская дорога"),
    LineKind("district_road", "Post_roads_district_level_", 1466, "уездная дорога"),
    LineKind("secondary_road", "Carriage_roads", 4239, "просёлочная дорога"),
    LineKind("seasonal_route", "Seasonal_routes", 17, "сезонный путь"),
    LineKind("canal", "0ad88df4_4dd8_11e6_a784_22000b8406af", 15, "канал"),
    LineKind("fortified_line", "Fortified_lines", 7, "укреплённая линия"),
)


@dataclass(frozen=True)
class AreaKind:
    key: str
    service: str
    count: int
    level: str               # province | district
    label: str

    @property
    def name(self) -> str:
        return self.service


AREA_KINDS = (
    AreaKind("guberniia", "Provinces_gubernii_", 56, "province", "губерния"),
    AreaKind("oblast", "Provinces_oblasti_", 5, "province", "область"),
    AreaKind("voevodstvo", "Voevodstvos", 8, "province", "воеводство Царства Польского"),
    AreaKind("territory", "Irregular_regions", 9, "province", "особая территория"),
    AreaKind("uezd", "Uezdy_Voevodstva", 608, "district", "уезд"),
)
ADMIN_TYPES = {
    "guberniia": "губерния", "oblast'": "область", "voevodstvo": "воеводство",
    "okrug": "округ", "territory": "земля", "company land": "земли компании",
    "former kingdom": "бывшее царство", "unspecified": "без названного статуса",
}

# Допуск упрощения линий и полигонов, градусы (около 300 м): атлас в масштабе
# 20 вёрст в дюйме точнее и не был.
LINE_TOLERANCE = 0.003
AREA_TOLERANCE = 0.003
DIGITS = 4


# --- названия --------------------------------------------------------------

UNKNOWN_NAMES = {"неизвестно", "neizvestno", "?", ""}


def fix_mojibake(text: Optional[str]) -> str:
    """Русское название из поля `Name_Rs`: UTF-8, отданный сервером как latin-1.

    Строка, которая не чинится (уже верная или испорченная иначе), возвращается
    как есть — запись скажет, откуда взято написание.
    """
    text = (text or "").strip()
    if not text:
        return ""
    try:
        return text.encode("latin-1").decode("utf-8").strip()
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def russian_name(attrs: dict) -> tuple[str, bool]:
    """(название кириллицей, взято ли оно из набора): иначе — транслитерация."""
    native = fix_mojibake(attrs.get("Name_Rs"))
    if native and native.lower() not in UNKNOWN_NAMES and not native.isascii():
        return native, True
    return cyrillic(attrs.get("Placename")), False


def _first(attrs: dict, *names: str) -> str:
    for name in names:
        value = attrs.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


# --- записи ----------------------------------------------------------------

def feature_to_record(feature: dict, kind: Kind) -> Optional[ContextRecord]:
    """Объект сервиса → запись. Объект без названия и без точки не берётся."""
    attrs = feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}
    latin = _first(attrs, "Placename")
    lat, lon = geometry.get("y"), geometry.get("x")
    point = valid_coords(lat, lon)
    if not latin and not point:
        return None
    province = _first(attrs, "Prov_name", "Province")
    district = _first(attrs, "Admin_3rd", "District")
    sheet = sheet_number(attrs.get("Source"))
    russian, native = russian_name(attrs)
    unnamed = latin.lower() in UNKNOWN_NAMES
    category = WALLED.get(_first(attrs, "Category"), kind.category)
    if unnamed:
        title = f"{kind.word} без названия"
    elif russian:
        title = f"{kind.word} {russian} ({latin})"
    else:
        title = f"{kind.word} {latin}"

    parts = [f"{category[:1].upper()}{category[1:]} по атласу Пядышева"]
    code = attrs.get("Cat_Code") if kind.key == "customs" else None
    host = settlement_type(code)
    if host:
        parts[0] += f"; стоит в селении типа «{host}»"
    where = ", ".join(x for x in (latin, district, province) if x)
    if where:
        parts.append(f"В наборе: {where}")
    parts.append(ATLAS + (f", лист {sheet}" if sheet else ""))
    if not unnamed:
        parts.append("Название кириллицей — как в наборе" if native
                     else "Название кириллицей — обратная транслитерация из латиницы набора")
    if kind.spec is SETTLEMENTS_1820 and kind.key in ("selo", "derevnia", "khutor"):
        parts.append(SELECTION_NOTE)

    extra = {"kind": kind.key, "name_latin": latin, "province_atlas": province,
             "district_atlas": district, "name_source": "набор" if native else "транслитерация"}
    if sheet:
        extra["atlas_sheet"] = sheet
    if attrs.get("GazID") is not None:
        extra["gaz_id"] = attrs["GazID"]

    return kind.spec.new_record(
        title=title, category=category,
        lat=round(lat, 5) if point else None, lon=round(lon, 5) if point else None,
        place_text=where or None,
        year_from=YEARS[0], year_to=YEARS[1], date_precision="year",
        period_raw="1820–1827 (годы выхода листов атласа)",
        summary=". ".join(parts) + ".",
        url=GALLERY_URL,
        source_id=f"{kind.key}:{attrs.get('GazID')}:{attrs.get('ObjectId')}",
        confidence="ok" if point else "no_coords",
        extra=extra,
    )


def records(features: Iterable[dict], kind: Kind) -> list[ContextRecord]:
    out = []
    for feature in features:
        rec = feature_to_record(feature, kind)
        if rec is not None:
            out.append(rec)
    return out


def check_point_layer(info: dict, kind, actual_count: Optional[int]) -> list[str]:
    """Расхождения точечного слоя: геометрия, поля названия и места, число объектов."""
    problems = []
    if info.get("geometryType") != "esriGeometryPoint":
        problems.append(f"{kind.service}: геометрия {info.get('geometryType')}, "
                        "ожидались точки")
    fields = {f.get("name") for f in info.get("fields") or []}
    for group in (("Placename",), ("Prov_name", "Province"), ("Admin_3rd", "District"),
                  ("Source",), ("GazID",)):
        if not fields & set(group):
            problems.append(f"{kind.service}: нет поля {' / '.join(group)}")
    if actual_count != kind.count:
        problems.append(f"{kind.service}: объектов {actual_count}, в коде {kind.count}")
    return problems


def check_count(kind, actual_count: Optional[int], geometry: Optional[str],
                expected_geometry: str) -> list[str]:
    problems = []
    if geometry != expected_geometry:
        problems.append(f"{kind.service}: геометрия {geometry}, ожидалась {expected_geometry}")
    if actual_count != kind.count:
        problems.append(f"{kind.service}: объектов {actual_count}, в коде {kind.count}")
    return problems


# --- подложки: линии и полигоны ---------------------------------------------

def _clean_path(path: list, tolerance: float) -> list:
    out: list = []
    for x, y in (p[:2] for p in simplify(path, tolerance)):
        q = [round(x, DIGITS), round(y, DIGITS)]
        if not out or q != out[-1]:
            out.append(q)
    return out


def line_feature(feature: dict, kind: LineKind) -> Optional[dict]:
    """Линия ArcGIS → GeoJSON LineString/MultiLineString, упрощённая."""
    attrs = feature.get("attributes") or {}
    paths = [_clean_path(p, LINE_TOLERANCE) for p in (feature.get("geometry") or {}).get(
        "paths") or [] if len(p) >= 2]
    paths = [p for p in paths if len(p) >= 2]
    if not paths:
        return None
    props = {"kind": kind.key, "type": kind.label,
             "year_from": YEARS[0], "year_to": YEARS[1]}
    name = _first(attrs, "NAME")
    if name and name != "?":
        props["name_latin"], props["name"] = name, cyrillic(name)
    sheet = sheet_number(_first(attrs, "SHEET"))
    if sheet:
        props["atlas_sheet"] = sheet
    length = attrs.get("LengthKm") or attrs.get("Length")
    if length:
        props["length_km"] = round(float(length), 1)
    geometry = ({"type": "LineString", "coordinates": paths[0]} if len(paths) == 1
                else {"type": "MultiLineString", "coordinates": paths})
    return {"type": "Feature", "geometry": geometry, "properties": props}


def area_feature(feature: dict, kind: AreaKind) -> Optional[dict]:
    """Полигон ArcGIS → GeoJSON с названием латиницей и кириллицей."""
    attrs = feature.get("attributes") or {}
    geometry = esri_polygon(feature.get("geometry"), tolerance=AREA_TOLERANCE, digits=DIGITS)
    if geometry is None:
        return None
    latin = _first(attrs, "Name_trs")
    native = fix_mojibake(attrs.get("Name_Rs"))
    props = {"level": kind.level, "kind": kind.key,
             "type": ADMIN_TYPES.get(_first(attrs, "AdminType"), kind.label),
             "name_latin": latin,
             "name": native if native and not native.isascii() else cyrillic(latin),
             "year_from": YEARS[0], "year_to": YEARS[1]}
    if kind.level == "district":
        parent = _first(attrs, "Admin_2nd")
        props["province_latin"], props["province"] = parent, cyrillic(parent)
    if attrs.get("GazID") is not None:
        props["gaz_id"] = attrs["GazID"]
    area = attrs.get("AreaSqKm")
    if area:
        props["area_km2"] = round(float(area))
    sheet = attrs.get("SheetID") or sheet_number(_first(attrs, "Source"))
    if sheet:
        props["atlas_sheet"] = int(sheet)
    return {"type": "Feature", "geometry": geometry, "properties": props}
