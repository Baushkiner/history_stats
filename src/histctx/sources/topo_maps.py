"""Топографические карты на место и год: Russian Military Topographic Map Collection.

Зачем этот слой. Факт из метрики стоит на нынешней карте, а деревни 1890
года на ней может не быть: хутор слился с селом, урочище распахали, погост
затопили. Самый короткий путь к обстановке того года — подробная карта того
же времени, и вопрос «есть ли лист на эту деревню и какого он года» обычно
решается неделями переписки с картохранилищами. Здесь он решается подбором:
у каждого листа — рамка охвата, годы, масштаб, номенклатура, ссылка на скан
с привязкой.

Набор. Russian Military Topographic Map Collection, Indiana University
Libraries: больше четырёх тысяч листов русских и советских военных
топографических карт около 1880–1945 годов, от Скандинавии до Ирана, больше
всего — Восточная Европа и запад России; поступили из дублетного фонда
Библиотеки Конгресса, на многих — штампы «Captured Map» и картохранилищ,
через которые лист прошёл (Quill, Dalmau, Cartographic Perspectives 93,
doi:10.14714/CP93.1567). Метаданные листов Индиана публикует в
OpenGeoMetadata: репозиторий `OpenGeoMetadata/big-ten`, формат Aardvark,
папка `metadata-aardvark/Maps/01d-00`, у листов коллекции в
`dct_isPartOf_sm` стоит «01d-03». Каталог — geo.btaa.org/catalog/01d-03 (тот
же набор показывает и geodata.lib.berkeley.edu). Читается сам репозиторий:
поиск порталов GeoBlacklight закрыт в robots.txt, а метаданные открыты.

Права. О картах коллекция пишет прямо: «The maps in the Russian Military
Topographic Map Collection are in the public domain», заявление о правах —
RightsStatements «No Copyright — United States». Лицензии на сами
метаданные в репозитории нет — права на метаданные не выяснены, и берутся
факты: рамка листа, годы, номенклатура, масштаб, издатель — и ссылки на
лист, скан GeoTIFF и манифест IIIF. Сканы не копируются.

Что попадает в слой. По записи на лист:

* заголовок — «Лист P-36-134-A «Хиттолово», 1:50 000, 1895–1934»:
  номенклатура и имя листа из `dct_title_s`; если имени листа нет
  («O-36-52-Б (Ryshevo, Russia)»), в кавычках — нынешнее место по каталогу;
* годы — `gbl_dateRange_drsim` («[1895 TO 1934]»): одно число или интервал
  от самого раннего до самого позднего года, который каталог даёт листу
  (`dct_temporal_sm` «1895-1934»); точность — год. У двенадцати листов «n.d.»
  каталог ставит оценку («between 1880 and 1942») — у них `date_approx`;
  листов совсем без года нет;
* точка — центр листа (`dcat_centroid`), сам лист — рамка в `extra.bbox`
  (запад, юг, восток, север). Подбор контекста ищет в 50 км от факта, а лист
  1:100 000 — это около 55 × 37 км, поэтому деревня у края листа к нему
  подбирается, у края соседнего — к соседнему. Пометка
  `confidence = sheet_center` говорит, что точка — центр рамки, а не место;
* масштаб — `category` («1:50 000»); издатель — `actor` («Генеральный штаб
  РККА», «Управление военных топографов»); гриф («Не подлежит оглашению»,
  «Секретно», «Для служебного пользования») и пометка «Captured map» — в
  описании и в `extra`;
* губерния 1897 года и рамка — `frame.Frame` по центру листа; листы на Иран,
  Румынию, Венгрию — `outside_bbox`, записи остаются.

Прочие карты BTAA того же репозитория в слой не взяты: центр рамки в охвате
РИ/СССР и год не позже 1960-го — у 126 записей из 36 592, и среди тех, что
поменьше, рамки заведомо ошибочны (лист «Trenton East», окрестности Парижа и
Тироль с центром в рамке) — без ручной сверки их не взять.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from ..schema import ContextRecord, LayerSpec, clean_text

REPO_URL = "https://github.com/OpenGeoMetadata/big-ten"
# Папка коллекции в репозитории; клон частичный, разрежённый: только она.
COLLECTION_DIR = "metadata-aardvark/Maps/01d-00"
COLLECTION_ID = "01d-03"
CATALOG_URL = "https://geo.btaa.org/catalog/01d-03"
ARTICLE_DOI = "10.14714/CP93.1567"

LICENSE = (
    "карты — общественное достояние («The maps in the Russian Military Topographic Map "
    "Collection are in the public domain», RightsStatements NoC-US); лицензии метаданных "
    "в репозитории OpenGeoMetadata/big-ten нет — права на метаданные не выяснены, берутся "
    "рамка листа, годы, номенклатура, масштаб и ссылки на скан"
)

TOPO_MAPS = LayerSpec(
    slug="topo_maps",
    title="Топографические карты на место и год",
    group="culture",
    source="Indiana University Libraries, Russian Military Topographic Map Collection "
           "(метаданные OpenGeoMetadata/big-ten)",
    license=LICENSE,
    description=(
        "Какая подробная карта есть на деревню и какого она года: 4 132 листа русских и "
        "советских военных топографических карт 1:25 000, 1:50 000 и 1:100 000, около "
        "1880–1945 годов, с рамкой охвата, годами, номенклатурой и ссылкой на скан с "
        "привязкой (GeoTIFF) — Европейская Россия, Белоруссия, Украина, Польша, Прибалтика, "
        "Кавказ."
    ),
    url=CATALOG_URL,
    status="harvested",
    expected_rows=4132,
)

CONFIDENCE_SHEET = "sheet_center"
CONFIDENCE_NO_DATE = "no_date"

# Грифы, которые каталог переносит с листа в `dct_alternative_sm`.
GRIFS = ("Не подлежит оглашению", "Для служебного пользования", "Секретно",
         "Совершенно секретно", "Временное издание")
CAPTURED = "Captured map"

_RE_ENVELOPE = re.compile(
    r"ENVELOPE\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")
_RE_RANGE = re.compile(r"\[\s*(-?\d{1,4})\s+TO\s+(-?\d{1,4})\s*\]")
_RE_YEARS = re.compile(r"^\s*(\d{4})(?:\s*[-–]\s*(\d{4}))?\s*$")
_RE_SCALE = re.compile(r"Scale\s*=?\s*1\s*:\s*([\d,. ]+)", re.I)
_RE_MODERN = re.compile(r"Modern area represented:\s*([^;]+)", re.I)
# «P-36-134-A Хиттолово (Khittolovo, Russia)», «O-34-56-Б-Г Керузе (Estonia)»,
# «O-36-52-Б (Ryshevo, Russia)»: номенклатура — латинская буква пояса, номер
# колонны, номер листа и литеры четвертей (кириллица и латиница вперемешку).
# Листы 1:25 000 несут две литеры («-Б-Г»), и обе бывают заглавными.
_RE_TITLE = re.compile(
    r"^\s*(?P<nom>[A-Z]-\d{1,2}(?:-\d{1,3}(?:,\d{1,3})*)?(?:-[A-DА-Гa-dа-г](?![\wа-яё])){0,2})"
    r"\s*(?P<name>[^()]*?)\s*(?:\((?P<modern>[^()]*)\))?\s*$")
# Пояс номенклатуры — латинская буква, но у 326 листов каталог пишет её
# кириллицей-двойником («О-36-6-В»): перед разбором она меняется на латинскую.
_ZONE_LATIN = str.maketrans({"О": "O", "Р": "P", "М": "M", "Н": "N", "К": "K"})
_RE_NOM = re.compile(
    r"^\s*(?P<nom>[A-Z]-\d{1,2}(?:-\d{1,3}(?:,\d{1,3})*)?(?:-[A-DА-Гa-dа-г](?![\wа-яё])){0,2})"
    r"(?P<rest>.*)$")


class TopoMapsError(RuntimeError):
    """Репозиторий не достался или записи пришли не в том виде."""


# --- репозиторий ------------------------------------------------------------

def _git(*args: str, cwd: Optional[Path] = None, timeout: int = 900) -> str:
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TopoMapsError(f"git {' '.join(args)}: {exc}") from exc
    if done.returncode != 0:
        raise TopoMapsError(f"git {' '.join(args)}: {done.stderr.strip()[-400:]}")
    return done.stdout


def ensure_repo(target: Path, *, refresh: bool = False) -> Path:
    """Клон репозитория метаданных: частичный (без лишних объектов) и только с папкой
    коллекции. Нет его — клонируется; `refresh` подтягивает последний коммит."""
    target = Path(target)
    if not (target / ".git").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO_URL, str(target))
        _git("sparse-checkout", "set", COLLECTION_DIR, cwd=target)
    elif refresh:
        _git("fetch", "--depth", "1", "origin", cwd=target)
        _git("reset", "--hard", "FETCH_HEAD", cwd=target)
    if not (target / COLLECTION_DIR).is_dir():
        raise TopoMapsError(f"{target}: папки {COLLECTION_DIR} нет — клон неполный?")
    return target


def repo_commit(repo: Path) -> tuple[str, str]:
    """(хеш, дата) коммита, из которого собран слой: в отчёт и в записи."""
    out = _git("log", "-1", "--format=%H %cs", cwd=Path(repo)).strip()
    commit, _, date = out.partition(" ")
    return commit, date


def read_collection(repo: Path) -> list[dict]:
    """Записи Aardvark коллекции 01d-03 из папки 01d-00, по порядку имён файлов."""
    folder = Path(repo) / COLLECTION_DIR
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise TopoMapsError(f"{path.name}: не разбирается ({exc})") from exc
        if isinstance(doc, dict) and COLLECTION_ID in (doc.get("dct_isPartOf_sm") or []):
            out.append(doc)
    if not out:
        raise TopoMapsError(f"в {folder} нет ни одной записи коллекции {COLLECTION_ID}")
    return out


# --- разбор полей ------------------------------------------------------------

def envelope(text: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    """«ENVELOPE(W,E,N,S)» → (запад, юг, восток, север) — порядок GeoJSON bbox."""
    m = _RE_ENVELOPE.match(str(text or ""))
    if not m:
        return None
    w, e, n, s = (float(x) for x in m.groups())
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= 90 and -90 <= n <= 90):
        return None
    return (min(w, e), min(s, n), max(w, e), max(s, n))


def centroid(doc: dict) -> tuple[Optional[float], Optional[float]]:
    """Центр листа: `dcat_centroid` («lat,lon»), иначе середина рамки."""
    text = str(doc.get("dcat_centroid") or "")
    try:
        lat, lon = (float(x) for x in text.split(","))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except ValueError:
        pass
    box = envelope(doc.get("dcat_bbox") or doc.get("locn_geometry"))
    if box is None:
        return None, None
    return (box[1] + box[3]) / 2, (box[0] + box[2]) / 2


def years(doc: dict) -> tuple[Optional[int], Optional[int], Optional[str], bool]:
    """(от, до, как в каталоге, оценка ли): «[1895 TO 1934]» → (1895, 1934, «1895-1934»).

    У листов без даты («n.d.») каталог ставит оценку — «between 1880 and
    1942»; такие годы помечаются как приблизительные.
    """
    raw = (clean_text((doc.get("dct_temporal_sm") or [None])[0])
           or clean_text(doc.get("dct_issued_s")))
    approx = bool(raw and raw.lower().startswith("between"))
    for value in doc.get("gbl_dateRange_drsim") or []:
        m = _RE_RANGE.match(str(value))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return min(a, b), max(a, b), raw, approx
    m = _RE_YEARS.match(raw or "")
    if m:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        return min(a, b), max(a, b), raw, approx
    return None, None, raw, approx


def scale(doc: dict) -> Optional[int]:
    """Знаменатель масштаба из описания: «Scale =1:100,000» → 100000."""
    m = _RE_SCALE.search(" ".join(doc.get("dct_description_sm") or []))
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def scale_label(value: Optional[int]) -> Optional[str]:
    """100000 → «1:100 000»."""
    return f"1:{value:,}".replace(",", " ") if value else None


def modern_area(doc: dict) -> Optional[str]:
    m = _RE_MODERN.search(" ".join(doc.get("dct_description_sm") or []))
    return clean_text(m.group(1)) if m else None


def _split_tail(rest: str) -> tuple[str, Optional[str]]:
    """«Бартенштайн (Bartoszyce, Poland (North side))» → (имя, то, что в последних скобках).

    Скобки бывают вложенными, поэтому пара к последней «)» ищется счётом.
    """
    rest = rest.strip()
    if not rest.endswith(")"):
        return rest, None
    depth = 0
    for i in range(len(rest) - 1, -1, -1):
        if rest[i] == ")":
            depth += 1
        elif rest[i] == "(":
            depth -= 1
            if depth == 0:
                return rest[:i].strip(), rest[i + 1:-1].strip() or None
    return rest, None


def parse_title(title: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(номенклатура, имя листа, нынешнее место) из `dct_title_s`.

    Обычный вид — «P-36-134-A Хиттолово (Khittolovo, Russia)». Бывает и
    неровный: пояс строчной («n-37-2-А-Б»), имя в скобках («L-53-117 (Ключи)
    (Bay Jigit, Russia)»), скобки во скобках — тогда номенклатура берётся
    отдельно, а нынешнее место — из последних скобок.
    """
    text = clean_text(title) or ""
    if len(text) > 1 and text[1] == "-":
        text = text[0].translate(_ZONE_LATIN).upper() + text[1:]
    m = _RE_TITLE.match(text)
    if m:
        return m.group("nom"), clean_text(m.group("name")), clean_text(m.group("modern"))
    m = _RE_NOM.match(text)
    if not m:
        return None, text or None, None
    name, modern = _split_tail(m.group("rest"))
    name = name.strip().removeprefix("(").removesuffix(")").strip()
    return m.group("nom"), clean_text(name), clean_text(modern)


def marks(doc: dict) -> tuple[list[str], bool]:
    """Грифы листа и пометка «Captured map» из `dct_alternative_sm`."""
    text = " ".join(doc.get("dct_alternative_sm") or [])
    # «Для cлужебного пользования» у части листов — с латинской «c».
    norm = text.replace("cлуж", "служ")
    grifs = [g for g in GRIFS if g in norm]
    return grifs, CAPTURED.lower() in text.lower()


def references(doc: dict) -> dict:
    """Ссылки листа: страница, каталог IU, GeoTIFF, манифест IIIF."""
    try:
        refs = json.loads(doc.get("dct_references_s") or "{}")
    except ValueError:
        return {}
    out = {"purl": refs.get("http://schema.org/url"),
           "iucat": refs.get("http://lccn.loc.gov/sh85035852"),
           "iiif": refs.get("http://iiif.io/api/presentation#manifest")}
    downloads = refs.get("http://schema.org/downloadUrl") or []
    if isinstance(downloads, str):
        downloads = [{"url": downloads}]
    for item in downloads:
        if isinstance(item, dict) and "geotiff" in str(item.get("label", "")).lower():
            out["geotiff"] = item.get("url")
    return {k: v for k, v in out.items() if v}


# --- записи -------------------------------------------------------------------

def _deg(value: float) -> str:
    """62.337 → «62,34»: градусы с запятой, как в остальных описаниях."""
    return f"{value:.2f}".replace(".", ",")


def sheet_title(nom: Optional[str], name: Optional[str], modern: Optional[str],
                scale_value: Optional[int], period: Optional[str]) -> str:
    """«Лист P-36-134-A «Хиттолово», 1:50 000, 1895–1934»."""
    place = name or (modern.split(",")[0].strip() if modern else None)
    parts = [f"Лист {nom}" if nom else "Лист топографической карты"]
    if place:
        parts[0] += f" «{place}»"
    label = scale_label(scale_value)
    if label:
        parts.append(label)
    if period:
        parts.append(period)
    return ", ".join(parts)


def sheet_summary(doc: dict, *, nom: Optional[str], scale_value: Optional[int],
                  period: Optional[str], box, grifs: list[str], captured: bool,
                  refs: dict) -> str:
    label = scale_label(scale_value)
    parts = [f"Топографическая карта {label}" if label else "Топографическая карта"]
    if nom:
        parts[0] += f", лист {nom}"
    publisher = "; ".join(doc.get("dct_publisher_sm") or [])
    if publisher:
        parts.append(f"издатель — {publisher}")
    parts.append(f"годы по каталогу — {period}" if period else "год издания каталогу не известен")
    if grifs:
        parts.append("гриф «" + "», «".join(grifs) + "»")
    if captured:
        parts.append("штамп «Captured map»")
    if box:
        w, s, e, n = box
        parts.append(f"лист покрывает {_deg(s)}–{_deg(n)}° с. ш., {_deg(w)}–{_deg(e)}° в. д.")
    area = modern_area(doc)
    if area:
        parts.append(f"нынешнее место — {area}")
    if refs.get("geotiff"):
        parts.append("скан с привязкой (GeoTIFF) — в IU DataCORE")
    return "; ".join(parts) + ". По каталогу Indiana University Libraries"


def doc_to_record(doc: dict) -> ContextRecord:
    """Запись Aardvark → запись слоя. Губерния и рамка — потом, `Frame.mark`."""
    nom, name, modern = parse_title(doc.get("dct_title_s"))
    scale_value = scale(doc)
    year_from, year_to, raw, approx = years(doc)
    period = None
    if year_from is not None:
        period = str(year_from) if year_from == year_to else f"{year_from}–{year_to}"
    box = envelope(doc.get("dcat_bbox") or doc.get("locn_geometry"))
    lat, lon = centroid(doc)
    grifs, captured = marks(doc)
    refs = references(doc)
    confidence = CONFIDENCE_SHEET if year_from is not None else CONFIDENCE_NO_DATE
    if lat is None:
        confidence = "no_coords"
    extra = {
        "nomenclature": nom,
        "sheet_name": name,
        "scale": scale_value,
        "bbox": [round(x, 4) for x in box] if box else None,
        "modern_place": modern_area(doc) or modern,
        "grif": grifs or None,
        "captured": True if captured else None,
        "geotiff": refs.get("geotiff"),
        "iiif": refs.get("iiif"),
        "call_number": next((x for x in doc.get("dct_identifier_sm") or []
                             if not str(x).startswith("http")), None),
    }
    return TOPO_MAPS.new_record(
        title=sheet_title(nom, name, modern, scale_value, period),
        category=scale_label(scale_value) or "масштаб не указан",
        lat=lat, lon=lon,
        place_text=modern_area(doc) or modern,
        year_from=year_from, year_to=year_to,
        date_precision="year" if year_from is not None else "unknown",
        date_approx=approx,
        period_raw=raw,
        actor="; ".join(doc.get("dct_publisher_sm") or []) or None,
        work=clean_text(doc.get("dct_title_s")),
        summary=sheet_summary(doc, nom=nom, scale_value=scale_value, period=period, box=box,
                              grifs=grifs, captured=captured, refs=refs),
        url=refs.get("purl") or CATALOG_URL,
        source_id=clean_text(doc.get("id")),
        confidence=confidence,
        extra={k: v for k, v in extra.items() if v is not None},
    )


def records(docs: Iterable[dict]) -> list[ContextRecord]:
    return [doc_to_record(doc) for doc in docs]
