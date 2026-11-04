"""Латинские храмы и приходы: два среза KUL geo-ecclesiae — около 1772 и 1938 года.

Зачем эти слои. Метрическую книгу вёл приход, а крестили и венчали часто
не в приходском костёле, а в филии или часовне соседней деревни. Вопрос
«к какому приходу относилась эта часовня» Викиданные не решают: у филии там
нет прихода, а у прихода — его филий. Институт исторической географии
Церкви в Польше (KUL, проект geo-ecclesiae) восстановил латинскую сеть
дважды — накануне первого раздела и накануне Второй мировой войны, — и оба
среза лежат на Zenodo точечными слоями с деканатом и диоцезом у каждого
храма. Это Литва с Жмудью и Инфлянтами, Волынь, Подолия, Киевщина — будущие
западные губернии, — Царство Польское и межвоенные Виленщина, Полесье и
Галиция.

Срез около 1772 года (`churches_pl_1772`). «Kościoły łacińskie ok. 1772 /
Latin churches around 1772», версия 1.0 от 18.06.2026 — Zenodo 20743455.
7 715 точек (MultiPoint из одной точки, WGS84): 4 693 главных храма
приходов («świątynia główna») и 3 022 вспомогательных («świątynia
pomocnicza»: филия или публичная часовня), у 2 919 из них назван приход.
Права: карточка Zenodo — CC BY-SA 4.0; в файле метаданных той же записи и на
data.geo-ecclesiae — CC BY-NC. Проект некоммерческий, обе лицензии требуют
указать автора, и запись слоя ссылается на набор.

Датировка среза. «Около 1772 года» — так назван набор, и у записи
`date_approx`. Само восстановление держится на визитациях и синодальных
описях: поле `source` называет годы документов — «AAPrz. AV175, s. 47,
1745 r.; ib. AV163, k. 817v, ok. 1750 r.». Годы XVIII века оттуда (1700–1800)
расширяют интервал: храм документирован в эти годы и стоит на карте около
1772 года, и запись «1745, ок. 1750» получает 1745–1772. Раньше 1700 года —
грамоты, «Liber retaxationum», силезские визитации 1660–1680-х, — и позже
1800-го — схематизмы 1820–1870-х и литература XX века — интервал не
растягивают: они говорят о храме до или после среза, а не о сети около 1772
года. Годы ищутся только перед «r.» («1745 r.», «1773-1774 r.», «1828,
1829 r.») и вне скобок: в скобках составители пишут год постройки («kł wyb.
w 1538 r.»), а голые числа — это страницы и шифры («BCz. 1775» — рукопись
№ 1775). Без годов XVIII века запись остаётся 1772–1772.

Срез 1936–1939 годов (`churches_pl_1938`). «Świątynie łacińskie przed II
wojną światową / Latin churches before World War II», версия 1.1 от
10.03.2026 — Zenodo 18944997, CC BY-NC 4.0. 5 184 приходских храма
межвоенной Польши по диоцезальным схематизмам: посвящение, деканат, диоцез,
Q-номер Викиданных (у 4 647) и ссылка на скан страницы схематизма 1938 (или
1939) года и второго, 1936–1939 годов. Годы записи — годы этих схематизмов:
оба названы источником. Ссылка записи — скан страницы основного схематизма
на geo-ecclesiae.kul.pl: это и есть первоисточник, сам скан не копируется.
Один храм (Krzywcze) пришёл с двумя точками в 144 км одна от другой — он
помечен `multiple_points`, обе точки лежат в `extra`.

Рамка. Наборы покрывают всю латинскую сеть: Силезию и Вармию, Галицию,
Великопольшу, королевскую Пруссию, Молдавию (диоцез Бакэу). Точки вне
губерний 1897 года и земель империи и СССР не выбрасываются, а получают
`outside_bbox` — тем же `frame.py`, что и слой приходов; губерния 1897 года
у точки внутри — в `region`.

Чего не берётся. Расшифровки сокращений: воеводство, материал, патронат,
вид храма и посвящение записаны в наборах сокращениями («rus», «dr», «mk»,
«Zofia M, Barbara PM»), а перечень сокращений живёт в приложениях KUL, не в
наборе. Коды идут в `extra` как есть, без догадок. Короткие примечания
составителей (`comment`) идут как есть — лицензии это позволяют.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional

from ..net import fetch_bytes
from ..schema import ContextRecord, LayerSpec, clean_text

FILES_API = "https://zenodo.org/api/records/{record}/files"


class GeoEcclesiaeError(RuntimeError):
    """Набор не скачался, не сошёлся с ожидаемым или пришёл не в том виде."""


class Dataset:
    """Файл набора на Zenodo: где лежит и каким должен прийти."""

    def __init__(self, record: str, key: str, size: int, md5: str) -> None:
        self.record, self.key, self.size, self.md5 = record, key, size, md5

    @property
    def doi(self) -> str:
        return f"10.5281/zenodo.{self.record}"

    @property
    def url(self) -> str:
        return f"https://doi.org/{self.doi}"

    @property
    def files_api(self) -> str:
        return FILES_API.format(record=self.record)

    @property
    def content_url(self) -> str:
        # В имени файла польские буквы: в адресе они кодируются.
        return f"{self.files_api}/{urllib.parse.quote(self.key)}/content"


# Сверено с перечнем файлов записи 04.11.2026. Новая версия набора — новая
# запись Zenodo, новые имя, размер и md5 здесь, сверенные руками.
CHURCHES_1772_FILE = Dataset(
    record="20743455",
    key="Świątynie_1772_GeoJSON_-6232501435685751922.geojson",
    size=4_139_932,
    md5="9d9fd0b7961b7136bfe6fe4e32536c95",
)

REQUIRED_1772 = ("ob_id", "diocese", "adeaconry", "deanery", "type", "pl_type", "pl_name",
                 "pal_name", "title", "parish", "source")

TYPE_MAIN = "świątynia główna"
TYPE_AUX = "świątynia pomocnicza"
CATEGORY_RU = {
    TYPE_MAIN: "главный храм прихода",
    TYPE_AUX: "вспомогательный храм (филия, часовня)",
}
SETTLEMENT_RU = {"miasto": "город", "wieś": "деревня"}

CONFIDENCE_NO_COORDS = "no_coords"
CONFIDENCE_MULTIPOINT = "multiple_points"

SLICE_YEAR = 1772
SLICE_RAW = "ok. 1772"
# Годы документов, которые расширяют срез: XVIII век, см. шапку модуля.
DOC_YEAR_MIN, DOC_YEAR_MAX = 1700, 1800

LICENSE_1772 = (
    "CC BY-SA 4.0 (карточка Zenodo, DataCite); в файле метаданных набора и на "
    "data.geo-ecclesiae — CC BY-NC. Проект некоммерческий; берутся факты — точка, тип "
    "храма, посвящение, приход, деканат, диоцез, ссылки на визитации — с указанием набора"
)

CHURCHES_PL_1772 = LayerSpec(
    slug="churches_pl_1772",
    title="Латинские храмы Речи Посполитой около 1772 года",
    group="faith",
    source=("KUL geo-ecclesiae: «Kościoły łacińskie ok. 1772» (Институт исторической "
            "географии Церкви в Польше), Zenodo"),
    license=LICENSE_1772,
    description=(
        "К какому приходу относилась филия или часовня накануне разделов: 7 715 "
        "латинских храмов около 1772 года — 4 693 главных храма приходов и 3 022 "
        "вспомогательных с названием прихода, — с деканатом, архидиаконатом, диоцезом "
        "и ссылками на визитации. Связка «филия → приход», которой нет в Викиданных. "
        "В губерниях 1897 года — 3 509 храмов, ещё 275 — на землях, позже вошедших в "
        "СССР (Львов); 3 931 храм Галиции, Силезии и Великопольши помечен вне рамки."
    ),
    url=CHURCHES_1772_FILE.url,
    status="harvested",
    expected_rows=7715,
)

CHURCHES_1938_FILE = Dataset(
    record="18944997",
    key="Świątynie_1938_-6837482094623975386.geojson",
    size=3_173_560,
    md5="64248944d771a6c2a3f122f6e64671eb",
)

REQUIRED_1938 = ("id", "pl_name", "title", "deanery", "diocese", "location_w",
                 "schem_1_date", "schem_1", "schem_2_date", "schem_2")

CATEGORY_1938 = "приходской храм"
# Заглушки набора вместо значения: «нет сведений», «нет костёла».
PLACEHOLDERS = frozenset({"[brak informacji]", "[brak kościoła]", "nie ustalono"})

LICENSE_1938 = (
    "CC BY-NC 4.0 (карточка Zenodo, DataCite, файл метаданных набора и data.geo-ecclesiae); "
    "проект некоммерческий: берутся факты — точка, посвящение, деканат, диоцез, годы "
    "схематизмов — и ссылки на сканы страниц схематизмов, сами сканы не копируются"
)

CHURCHES_PL_1938 = LayerSpec(
    slug="churches_pl_1938",
    title="Латинские приходские храмы по схематизмам 1936–1939 годов",
    group="faith",
    source=("KUL geo-ecclesiae: «Świątynie łacińskie przed II wojną światową» (Институт "
            "исторической географии Церкви в Польше), Zenodo"),
    license=LICENSE_1938,
    description=(
        "К какому деканату и диоцезу относился латинский приход перед войной и на какой "
        "странице схематизма он записан: 5 184 приходских храма межвоенной Польши — от "
        "Вильно и Пинска до Львова и Познани — с посвящением, деканатом, диоцезом и "
        "ссылкой на скан страницы схематизма 1936–1939 годов. В губерниях 1897 года — "
        "2 727, ещё 475 — в рамке без губернии, почти все во Львовском и Перемышльском "
        "диоцезах, на землях, позже вошедших в СССР."
    ),
    url=CHURCHES_1938_FILE.url,
    status="harvested",
    expected_rows=5184,
)


# --- запись на Zenodo --------------------------------------------------------

def fetch_manifest(dataset: Dataset, *, timeout: int = 60) -> list[dict]:
    """Перечень файлов записи: имя, размер, сумма."""
    raw = fetch_bytes(dataset.files_api, error=GeoEcclesiaeError, timeout=timeout)
    try:
        entries = json.loads(raw)["entries"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeoEcclesiaeError(f"ответ Zenodo не разбирается: {exc}") from exc
    return [{"key": e.get("key"), "size": e.get("size"), "checksum": e.get("checksum")}
            for e in entries]


def check_manifest(manifest: Iterable[dict], dataset: Dataset) -> list[str]:
    """Расхождения перечня с кодом; пусто — всё сходится."""
    by_key = {m.get("key"): m for m in manifest}
    got = by_key.get(dataset.key)
    if got is None:
        return [f"{dataset.key}: в записи такого файла нет; есть: "
                + ", ".join(sorted(str(k) for k in by_key))]
    problems = []
    if got.get("size") != dataset.size:
        problems.append(f"размер {got.get('size')}, ожидался {dataset.size}")
    if got.get("checksum") != f"md5:{dataset.md5}":
        problems.append(f"сумма {got.get('checksum')}, ожидалась md5:{dataset.md5}")
    return problems


def cached_file(dataset: Dataset, cache_dir: Path, *, timeout: int = 300) -> Path:
    """Файл из кэша; нет его или он другой — скачивается и сверяется по md5.

    В кэше файл лежит под номером записи: польские буквы в имени файла на
    диске ни к чему.
    """
    path = Path(cache_dir) / f"zenodo_{dataset.record}{Path(dataset.key).suffix}"
    if path.exists() and path.stat().st_size == dataset.size:
        return path
    data = fetch_bytes(dataset.content_url, error=GeoEcclesiaeError, timeout=timeout)
    digest = hashlib.md5(data).hexdigest()
    if len(data) != dataset.size or digest != dataset.md5:
        raise GeoEcclesiaeError(f"скачано {len(data)} байт, md5 {digest}; ожидалось "
                                f"{dataset.size} байт, md5 {dataset.md5}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- чтение набора -----------------------------------------------------------

WEB_MERCATOR_R = 6_378_137.0


def web_mercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 (метры) → (широта, долгота): сферический Меркатор наоборот."""
    lon = math.degrees(x / WEB_MERCATOR_R)
    lat = math.degrees(2 * math.atan(math.exp(y / WEB_MERCATOR_R)) - math.pi / 2)
    return lat, lon


def crs_name(payload: dict) -> str:
    """Имя системы координат из GeoJSON; без поля — WGS84, как велит стандарт."""
    crs = payload.get("crs") or {}
    return str((crs.get("properties") or {}).get("name") or "EPSG:4326")


def is_web_mercator(name: str) -> bool:
    return name.replace("::", ":").upper().endswith(("EPSG:3857", "EPSG:900913"))


def read_features(data: bytes, required: Iterable[str]) -> tuple[list[dict], str]:
    """Объекты набора и имя системы координат. Нет нужных полей — набор переделан."""
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GeoEcclesiaeError(f"GeoJSON не разбирается: {exc}") from exc
    features = payload.get("features") if isinstance(payload, dict) else None
    if not features:
        raise GeoEcclesiaeError("в GeoJSON нет объектов")
    props = features[0].get("properties") or {}
    missing = [c for c in required if c not in props]
    if missing:
        raise GeoEcclesiaeError(f"нет полей {missing}; пришли: {sorted(props)}")
    return features, crs_name(payload)


def points_of(geometry: Optional[dict], web_mercator: bool = False
              ) -> list[tuple[float, float]]:
    """Все точки объекта, (широта, долгота): Point — одна, MultiPoint — сколько есть."""
    geometry = geometry or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Point":
        coords = [coords]
    elif geometry.get("type") != "MultiPoint":
        return []
    out = []
    for pair in coords:
        try:
            x, y = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        lat, lon = web_mercator_to_wgs84(x, y) if web_mercator else (y, x)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((lat, lon))
    return out


def point_of(geometry: Optional[dict], web_mercator: bool = False
             ) -> tuple[Optional[float], Optional[float]]:
    """(широта, долгота) точки или первой точки MultiPoint."""
    points = points_of(geometry, web_mercator)
    return points[0] if points else (None, None)


def placed(feature: dict, web_mercator: bool, extra: dict) -> tuple[
        Optional[float], Optional[float], str]:
    """Точка записи и пометка. Несколько точек у одного храма — `multiple_points`.

    В наборе 1938 года такой храм один (Krzywcze, деканат Borszczów): две точки
    в 144 км одна от другой. Какая верна, набор не говорит, поэтому запись
    стоит в первой, обе лежат в `extra["points"]`, а пометка зовёт проверить.
    """
    points = points_of(feature.get("geometry"), web_mercator)
    if not points:
        return None, None, CONFIDENCE_NO_COORDS
    if len(points) > 1:
        extra["points"] = [[round(lat, 6), round(lon, 6)] for lat, lon in points]
        return points[0][0], points[0][1], CONFIDENCE_MULTIPOINT
    return points[0][0], points[0][1], "ok"


_RE_PARENS = re.compile(r"\([^()]*\)")
# «1745 r.», «1773-1774 r.», «1828, 1829 r.»: год или перечень лет перед «r.».
_RE_DOC_YEARS = re.compile(r"(?<!\d)((?:1\d{3}\s*[-–,]\s*)*1\d{3})\s*r\.")
_RE_YEAR = re.compile(r"1\d{3}")


def document_years(source: Optional[str]) -> list[int]:
    """Годы документов XVIII века из поля `source`, по возрастанию."""
    text = clean_text(source)
    if not text:
        return []
    # Вложенных скобок в наборе нет, но снимаются они до неподвижной точки.
    previous = None
    while previous != text:
        previous, text = text, _RE_PARENS.sub(" ", text)
    years = {int(y) for group in _RE_DOC_YEARS.findall(text) for y in _RE_YEAR.findall(group)}
    return sorted(y for y in years if DOC_YEAR_MIN <= y <= DOC_YEAR_MAX)


def church_years(source: Optional[str]) -> tuple[int, int, list[int]]:
    """(с, по, годы документов): срез около 1772 года, расширенный документами."""
    years = document_years(source)
    span = [*years, SLICE_YEAR]
    return min(span), max(span), years


def church_title(place: str, dedication: Optional[str], kind: str) -> str:
    """«Brzozów — Zofia M, Barbara PM»; без посвящения — тип храма."""
    if dedication:
        return f"{place} — {dedication}"
    return f"{place} — {CATEGORY_RU.get(kind, 'храм')}"


def church_summary(p: dict, place: str, kind: str, years: list[int]) -> str:
    """Своя фраза из полей: где, какой храм, чей приход, деканат и диоцез."""
    settlement = SETTLEMENT_RU.get(clean_text(p.get("pl_type")) or "")
    where = f"{place} ({settlement})" if settlement else place
    parish = clean_text(p.get("parish"))
    if kind == TYPE_MAIN:
        what = "главный храм прихода"
    elif parish:
        what = f"вспомогательный храм (филия или часовня) прихода {parish}"
    else:
        what = "вспомогательный храм (филия или часовня), приход в наборе не указан"
    text = f"{where}: около 1772 года — {what}."
    units = [(label, clean_text(p.get(key))) for label, key in (
        ("диоцез", "diocese"), ("архидиаконат", "adeaconry"), ("деканат", "deanery"))]
    units = ", ".join(f"{label} {value}" for label, value in units if value)
    if units:
        # Не `capitalize()`: тот опускает регистр у названий — «przemyśl».
        text += f" {units[0].upper()}{units[1:]}."
    if years:
        text += " Годы документов в источнике: " + ", ".join(map(str, years)) + "."
    return text


def feature_to_record(feature: dict, *, web_mercator: bool = False) -> ContextRecord:
    """Объект набора 1772 года → запись слоя. Губерния и рамка — `frame.Frame.mark`."""
    p = feature.get("properties") or {}
    place = clean_text(p.get("pl_name")) or "Без названия"
    kind = clean_text(p.get("type")) or ""
    dedication = clean_text(p.get("title"))
    year_from, year_to, years = church_years(p.get("source"))
    extra = {
        "parish": clean_text(p.get("parish")),
        "deanery": clean_text(p.get("deanery")),
        "archdeaconry": clean_text(p.get("adeaconry")),
        "diocese": clean_text(p.get("diocese")),
        "palatinate": clean_text(p.get("pal_name")),
        "settlement": clean_text(p.get("pl_type")),
        "dedication": dedication,
        "material": clean_text(p.get("material")),
        "patronage": clean_text(p.get("patronage")),
        "kind": clean_text(p.get("kind")),
        "sources": clean_text(p.get("source")),
        "source_years": years or None,
        "name_de": clean_text(p.get("pl_name_de")),
        "name_variant": clean_text(p.get("pl_name_v")),
        "comment": clean_text(p.get("comment")),
    }
    extra = {k: v for k, v in extra.items() if v}
    lat, lon, confidence = placed(feature, web_mercator, extra)
    return CHURCHES_PL_1772.new_record(
        title=church_title(place, dedication, kind),
        category=CATEGORY_RU.get(kind, kind or None),
        lat=lat, lon=lon,
        place_text=place,
        year_from=year_from, year_to=year_to,
        date_precision="year",
        date_approx=True,
        period_raw=SLICE_RAW,
        summary=church_summary(p, place, kind, years),
        url=CHURCHES_1772_FILE.url,
        source_id=clean_text(p.get("ob_id")),
        confidence=confidence,
        extra=extra,
    )


def records_1772(features: Iterable[dict], crs: str = "EPSG:4326") -> list[ContextRecord]:
    """Записи слоя 1772 года: по одной на храм."""
    mercator = is_web_mercator(crs)
    return [feature_to_record(f, web_mercator=mercator) for f in features]


def _value(value) -> Optional[str]:
    """Значение поля без заглушек «[brak informacji]» и «nie ustalono»."""
    text = clean_text(value)
    return None if text in PLACEHOLDERS else text


def _year(value) -> Optional[int]:
    text = clean_text(value)
    return int(text) if text and text.isdigit() else None


def schematism_summary(place: str, diocese: Optional[str], deanery: Optional[str],
                       years: list[int]) -> str:
    """«Kleszczele: латинский приходской храм в схематизмах диоцеза Pińsk 1938 и 1939 годов»."""
    text = f"{place}: латинский приходской храм"
    if years:
        books = "схематизме" if len(years) == 1 else "схематизмах"
        where = f" диоцеза {diocese}" if diocese else ""
        when = (f"{years[0]} года" if len(years) == 1
                else f"{', '.join(map(str, years[:-1]))} и {years[-1]} годов")
        text += f" в {books}{where} {when}"
    text += "."
    if deanery:
        text += f" Деканат {deanery}."
    return text


def feature_to_record_1938(feature: dict, *, web_mercator: bool = False) -> ContextRecord:
    """Объект набора 1936–1939 годов → запись слоя.

    Годы — годы схематизмов, по которым храм записан (`schem_1_date`,
    `schem_2_date`): оба названы источником, точность — год. Ссылка записи —
    скан страницы основного схематизма; второй — в `extra`.
    """
    p = feature.get("properties") or {}
    place = clean_text(p.get("pl_name")) or "Без названия"
    dedication = _value(p.get("title"))
    diocese, deanery = clean_text(p.get("diocese")), clean_text(p.get("deanery"))
    years = sorted({y for y in (_year(p.get("schem_1_date")), _year(p.get("schem_2_date")))
                    if y is not None})
    extra = {
        "deanery": deanery,
        "diocese": diocese,
        "dedication": dedication,
        "wikidata": clean_text(p.get("location_w")),
        # Скан основного схематизма — ссылка самой записи (`url`), здесь его год.
        "schematism_year": _year(p.get("schem_1_date")),
        "schematism_2": clean_text(p.get("schem_2")),
        "schematism_2_year": _year(p.get("schem_2_date")),
        "material": _value(p.get("material_type")),
        "location_source": clean_text(p.get("location_g")),
        "location_info": clean_text(p.get("location_i")),
        "name_variant": clean_text(p.get("pl_name_v")),
        "comment": clean_text(p.get("comments")),
    }
    extra = {k: v for k, v in extra.items() if v}
    lat, lon, confidence = placed(feature, web_mercator, extra)
    raw = "; ".join(t for t in (clean_text(p.get("schem_1_date")),
                                clean_text(p.get("schem_2_date"))) if t)
    return CHURCHES_PL_1938.new_record(
        title=f"{place} — {dedication}" if dedication else f"{place} — {CATEGORY_1938}",
        category=CATEGORY_1938,
        lat=lat, lon=lon,
        place_text=place,
        year_from=years[0] if years else None,
        year_to=years[-1] if years else None,
        date_precision="year" if years else "unknown",
        period_raw=raw or None,
        summary=schematism_summary(place, diocese, deanery, years),
        url=clean_text(p.get("schem_1")) or CHURCHES_1938_FILE.url,
        source_id=clean_text(p.get("id")),
        confidence=confidence if years else "no_date",
        extra=extra,
    )


def records_1938(features: Iterable[dict], crs: str = "EPSG:4326") -> list[ContextRecord]:
    """Записи слоя 1936–1939 годов: по одной на храм."""
    mercator = is_web_mercator(crs)
    return [feature_to_record_1938(f, web_mercator=mercator) for f in features]


def unknown_types(features: Iterable[dict]) -> list[str]:
    """Типы храмов, которых нет в словаре: их категория пойдёт по-польски."""
    return sorted({clean_text((f.get("properties") or {}).get("type")) or "—"
                   for f in features} - set(CATEGORY_RU))
