"""Лагеря военнопленных вермахта 1939–1945 годов (карта dekoder по списку Moosburg.org).

Зачем этот слой. «Пропал без вести», «умер в плену» — самые частые записи о
мужчинах 1941–1942 годов в книгах памяти и в карточках учёта, и более пяти
миллионов пленных красноармейцев прошли через лагеря вермахта: дулаги у
линии фронта, фронтшталаги на оккупированной земле, шталаги и офлаги в
рейхе и генерал-губернаторстве. Номер лагеря стоит в трофейной карточке
военнопленного и в извещении — «Шталаг 352», «Дулаг 131», — но где этот лагерь
был и когда, по номеру не понять: Шталаг 352 в 1942–1943 годах — Минск, а
Дулаг 131 в одном 1941 году стоял и в Слониме, и в Бобруйске — лагеря
переезжали вслед за фронтом. Слой отвечает: где стоял лагерь с этим номером
и в какие месяцы.

Набор. dekoder, «Karte der NS-Verbrechen» (`war.dekoder.org`, карта
преступлений национал-социализма на востоке Европы), слой
«Kriegsgefangenenlager» — 914 лагерей. Источник слоя, как его называет сама
карта, — перечень лагерей военнопленных Moosburg.org («Stalag list»,
`moosburg.org/info/stalag/laglist.html`), где лагерю даны тип, номер, военный
округ и время; dekoder привязал их к точке. Главная страница карты отдаёт
все слои сразу: точки лежат в разметке страницы (React Server Components,
куски `self.__next_f.push`) как GeoJSON — `id`, `name_de`, `category`
(Stalag, Dulag, Oflag, Frontstalag, Ilag, лазареты) и `description_de` в
Markdown с полями «Lager Nr.», «District», «Zeit», «Quelle». Карточка лагеря —
`/de/map/pow_camps/<имя>-<id>`, адреса — в `sitemap-map.xml`. robots.txt
сайта — `Allow: /`.

Права. Условий использования карта не заявляет — права не выяснены. Берутся
факты — тип и номер лагеря, место, время, военный округ — и ссылка на
карточку dekoder; первоисточник (Moosburg.org) назван в записи.

Что попадает в слой. Все 914 лагерей, по записи на лагерь. Заголовок —
«Шталаг 352 — Минск»: тип по-русски, номер из «Lager Nr.», место — русское
название по указателю написаний GeoNames, если рядом с точкой есть место с
таким написанием (`russian_names.RussianNames`), иначе немецкое имя карты.
Время — из «Zeit»: «9.1939-4.1945» — с сентября 1939 по апрель 1945 года
(точность `month`), «1942» — год, «1941-9.1942» — год и месяц (точность —
грубейшая из двух), «6.1942-» — открытый конец: лагерь работал с июня 1942
года, а конец набор не даёт, и срок тянется до мая 1945 года с точностью
`open`; «-12.1944-» — лагерь известен в декабре 1944 года; «1.1943(-1944)»
и «?» — `date_approx`. Время не указано — у 92 лагерей: им ставится граница
периода, рамка войны 1939–1945 годов, с точностью `era`, `date_approx` и
`extra.date_source = "рамка войны"`, как у мест без дат в `ghettos_camps`.

Где запись на карте. Точка — место лагеря на карте dekoder (город или
посёлок, а не ограда лагеря), `confidence = place_level`. Рамка —
`frame.Frame`: лагерь в губерниях 1897 года получает губернию, в рамке
РИ/СССР вне губерний — без неё, в рейхе, Франции или Норвегии —
`outside_bbox`, запись остаётся: туда угоняли пленных из того же села. У 37
лагерей карта точки не знает — они лежат файлом без точки, `no_coords`.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, Optional

from ..net import fetch_bytes
from ..schema import ContextRecord, LayerSpec

MAP_URL = "https://war.dekoder.org/de/map"
SITEMAP_URL = "https://war.dekoder.org/sitemap-map.xml"
CARD_PREFIX = "https://war.dekoder.org/de/map/pow_camps/"
MOOSBURG_URL = "https://moosburg.org/info/stalag/laglist.html"
LAYER_ID = "pow_camps"

# Год, до которого тянется открытый конец: капитуляция Германии.
WAR_FRAME = (1939, 1945)
OPEN_END = 1945

LICENSE = (
    "права не выяснены: условий карта dekoder не заявляет — берутся факты (тип и "
    "номер лагеря, место, время, военный округ) и ссылка на карточку лагеря; "
    "первоисточник — перечень лагерей Moosburg.org"
)

POW_CAMPS = LayerSpec(
    slug="pow_camps",
    title="Лагеря военнопленных вермахта 1939–1945",
    group="military",
    source="dekoder, «Karte der NS-Verbrechen» (war.dekoder.org), слой "
           "«Kriegsgefangenenlager»; перечень — Moosburg.org, «Stalag list»",
    license=LICENSE,
    description=(
        "Где стоял лагерь с номером из карточки военнопленного и когда: 914 "
        "шталагов, дулагов, офлагов и фронтшталагов вермахта, от Бобруйска и "
        "Масюковщины до рейха и Норвегии, с номером, военным округом и месяцами "
        "работы. Отвечает, куда делся «пропавший без вести» 1941–1942 годов."
    ),
    url=MAP_URL,
    status="harvested",
    expected_rows=914,
)

# Тип лагеря: русское название для заголовка и пояснение для категории.
TYPES_RU = {
    "Stalag": ("шталаг", "шталаг — основной лагерь для рядовых и унтер-офицеров"),
    "Dulag": ("дулаг", "дулаг — пересыльный лагерь у линии фронта"),
    "Oflag": ("офлаг", "офлаг — лагерь для офицеров"),
    "Frontstalag": ("фронтшталаг",
                    "фронтшталаг — основной лагерь в зоне военных действий"),
    "Ilag": ("ильлаг", "ильлаг — лагерь для интернированных гражданских"),
    "Ilag/Oflag": ("ильлаг и офлаг", "лагерь для интернированных и офицеров"),
    "Ilag/Stalag": ("ильлаг и шталаг", "лагерь для интернированных и рядовых"),
    "Res-Laz": ("резервный лазарет", "резервный лазарет для военнопленных"),
    "Kgf-Laz": ("лазарет для военнопленных", "лазарет для военнопленных"),
    "Heilag": ("хайлаг", "хайлаг — лагерь для репатриации тяжелораненых"),
    "Kgf-Lager": ("лагерь военнопленных", "лагерь военнопленных"),
    "Marlag": ("марлаг", "марлаг — лагерь для военных моряков"),
    "Marine": ("лагерь военных моряков", "лагерь военных моряков"),
    "Auswertestelle": ("пункт допроса", "Auswertestelle — пункт допроса пленных"),
}

CONFIDENCE_PLACE = "place_level"
CONFIDENCE_NO_COORDS = "no_coords"


class DekoderError(RuntimeError):
    """Страница карты не скачалась или пришла не в том виде."""


# --- страница карты --------------------------------------------------------

_RE_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', re.S)


def payload_text(html: str) -> str:
    """Склеенные куски данных страницы (строки `self.__next_f.push([1, "…"])`)."""
    chunks = _RE_CHUNK.findall(html)
    if not chunks:
        raise DekoderError("в странице нет кусков self.__next_f: разметка карты изменилась")
    return "".join(json.loads(chunk) for chunk in chunks)


def layer_block(text: str, layer_id: str = LAYER_ID) -> tuple[list[dict], Optional[str]]:
    """Точки слоя карты и номер листа Google Sheets, из которого слой собран.

    У каждого слоя в данных страницы: `"spreadsheetId": "…"`, `"layerProps":
    {"id": "<слой>", …}`, а дальше, до следующего слоя, — `"preloadedGeojson":
    {FeatureCollection}`. Ищется своя метка слоя, от неё — ближайшая коллекция.
    """
    mark = f'"layerProps":{{"id":"{layer_id}"'
    pos = text.find(mark)
    if pos < 0:
        raise DekoderError(f"слоя {layer_id} в данных страницы нет")
    head = text.rfind('"spreadsheetId":"', 0, pos)
    sheet = None
    if head >= 0:
        m = re.match(r'"spreadsheetId":"([^"]*)"', text[head:])
        sheet = m.group(1) if m else None
    start = text.find('"preloadedGeojson":', pos)
    nxt = text.find('"spreadsheetId":"', pos)
    if start < 0 or (0 <= nxt < start):
        raise DekoderError(f"у слоя {layer_id} нет коллекции точек")
    obj, _ = json.JSONDecoder().raw_decode(text, start + len('"preloadedGeojson":'))
    if obj.get("type") != "FeatureCollection":
        raise DekoderError(f"у слоя {layer_id} не FeatureCollection: {obj.get('type')}")
    return obj.get("features") or [], sheet


def card_urls(sitemap_xml: bytes) -> dict[int, str]:
    """Номер лагеря на карте → адрес его карточки (`…/pow_camps/<имя>-<id>`)."""
    root = ET.fromstring(sitemap_xml)
    out: dict[int, str] = {}
    for loc in root.iter():
        if not loc.tag.endswith("loc") or not loc.text:
            continue
        url = loc.text.strip()
        m = re.match(re.escape(CARD_PREFIX) + r"[^/]*-(\d+)/?$", url)
        if m:
            out[int(m.group(1))] = url
    return out


def fetch_page(url: str, *, timeout: int = 120) -> bytes:
    return fetch_bytes(url, error=DekoderError, timeout=timeout)


# --- поля описания ---------------------------------------------------------

_RE_FIELD = re.compile(r"\*\*([^*:]+):\*\*\s*([^\n]*)")


def description_fields(markdown: Optional[str]) -> dict[str, str]:
    """«**Lager Nr.:** Stalag 352» → {"Lager Nr.": "Stalag 352"}; ссылки — текстом."""
    fields: dict[str, str] = {}
    for key, value in _RE_FIELD.findall(markdown or ""):
        value = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", value).strip()
        if value:
            fields[key.strip()] = value
    return fields


@dataclass(frozen=True)
class Dating:
    year_from: int
    year_to: int
    precision: str
    approx: bool
    raw: str
    source: Optional[str] = None


_RE_STAMP = re.compile(r"(?:(\d{1,2}(?:/\d{1,2})?)\.)?(1\d{3})")


def parse_time(zeit: Optional[str]) -> Optional[Dating]:
    """«Zeit» карты в годы; пусто или без года — None.

    «9.1939-4.1945», «1941-9.1942», «6.1942-» (открытый конец — до 1945 года,
    точность `open`), «-1/3.1944» (открытое начало — с 1939 года, `open`),
    «-12.1944-» (известен в декабре 1944-го), «1.1943(-1944)» и «?» —
    приблизительно.
    """
    text = (zeit or "").strip()
    stamps = _RE_STAMP.findall(text)
    if not stamps:
        return None
    years = [int(y) for _, y in stamps]
    months = [m for m, _ in stamps]
    lo, hi = min(years), max(years)
    approx = "?" in text or "(" in text or any("/" in m for m in months)
    precision = "month" if all(months) else "year"
    bare = text.replace("(", "").replace(")", "").strip()
    open_start = bare.startswith("-") and not bare.endswith("-")
    open_end = bare.endswith("-") and not bare.startswith("-")
    if bare.startswith("-") and bare.endswith("-"):
        # «-12.1944-»: лагерь известен на эту дату, ни начала, ни конца нет.
        approx = True
    if open_end and len(stamps) == 1:
        hi = max(lo, OPEN_END)
        precision = "open"
    if open_start and len(stamps) == 1:
        lo = min(hi, WAR_FRAME[0])
        precision = "open"
    return Dating(lo, hi, precision, approx, text)


def war_frame() -> Dating:
    a, b = WAR_FRAME
    return Dating(a, b, "era", True, f"время не указано — рамка войны: {a}–{b}", "рамка войны")


# --- записи ----------------------------------------------------------------

def point(feature: dict) -> tuple[Optional[float], Optional[float]]:
    """Точка лагеря; «$NaN» и прочее нечисловое — без точки."""
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None, None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None, None
    if lat != lat or lon != lon or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return None, None
    return lat, lon


def camp_number(lager_nr: Optional[str]) -> Optional[str]:
    """«Stalag 352», «Dulag 131», «Frontstalag 150», «Oflag XIII B» → номер."""
    if not lager_nr:
        return None
    m = re.match(r"^\s*[A-Za-zÄÖÜäöü/\-]+\.?\s+(.+?)\s*$", lager_nr)
    return m.group(1) if m else None


def title_for(category: Optional[str], number: Optional[str], place: str) -> str:
    kind = TYPES_RU.get(category or "", (category or "лагерь военнопленных", None))[0]
    kind = kind[:1].upper() + kind[1:]
    return f"{kind} {number} — {place}" if number else f"{kind} — {place}"


def records(features: Iterable[dict], *, urls: Optional[dict[int, str]] = None,
            names=None, sheet: Optional[str] = None) -> list[ContextRecord]:
    """Записи слоя: по одной на лагерь карты."""
    urls = urls or {}
    out: list[ContextRecord] = []
    for feat in features:
        props = feat.get("properties") or {}
        fid = props.get("id")
        name_de = (props.get("name_de") or "").strip() or "без названия"
        category = (props.get("category") or "").strip() or None
        fields = description_fields(props.get("description_de"))
        lat, lon = point(feat)
        place = None
        if names is not None and lat is not None:
            place = names.lookup(name_de, lat, lon)
        place = place or name_de
        number = camp_number(fields.get("Lager Nr."))
        dating = parse_time(fields.get("Zeit")) or war_frame()
        kind = TYPES_RU.get(category or "")
        district = fields.get("District")
        bits = [kind[1] if kind else (category or "лагерь военнопленных")]
        if fields.get("Lager Nr."):
            bits.append(f"номер по перечню — {fields['Lager Nr.']}")
        if district:
            bits.append(f"округ — {district}")
        bits.append(f"время — {fields['Zeit']}" if fields.get("Zeit")
                    else "время в перечне не указано")
        summary = "; ".join(bits) + ". Перечень Moosburg.org, точка — карта dekoder"
        summary = summary[:1].upper() + summary[1:]
        extra = {
            "dekoder_id": fid,
            "name_de": name_de,
            "category_de": category,
            "lager_nr": fields.get("Lager Nr."),
            "district": district,
            "list": fields.get("Quelle"),
            "sheet": sheet,
        }
        if dating.source:
            extra["date_source"] = dating.source
        out.append(POW_CAMPS.new_record(
            title=title_for(category, number, place),
            category=kind[0] if kind else (category or "лагерь военнопленных"),
            lat=lat, lon=lon,
            place_text=f"{name_de}; {district}" if district else name_de,
            year_from=dating.year_from, year_to=dating.year_to,
            date_precision=dating.precision,
            date_approx=dating.approx,
            period_raw=dating.raw,
            work="Перечень лагерей военнопленных Moosburg.org («Stalag list»)",
            summary=summary,
            url=(urls.get(fid) if isinstance(fid, int) else None) or MAP_URL,
            source_id=f"dekoder:{LAYER_ID}:{fid}",
            confidence=CONFIDENCE_PLACE if lat is not None else CONFIDENCE_NO_COORDS,
            extra={k: v for k, v in extra.items() if v not in (None, "")},
        ))
    return out
