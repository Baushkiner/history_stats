"""Границы государств 1886–1960 (CShapes 2.0, ETH Zurich).

Зачем этот слой. Губернии и уезды (`admin_gis.py`, `ristat.py`) отвечают, где
человек жил внутри страны. Этот слой отвечает на вопрос уровнем выше:
гражданином какого государства он при этом был. Для западных губерний вопрос
не праздный — Вильно, Ковно, Гродно, Кишинёв и Львов за одну жизнь меняли
государство по три раза, и от ответа зависит, в архиве какой нынешней страны
лежит метрическая книга.

Данные того же порядка точности, что и события: граница здесь меняется не
«примерно тогда-то», а по дате. У России в наборе 17 периодов, попадающих в
рамку слоя, и по ним читается вся хронология: Портсмутский мир (05.09.1905),
протекторат над Урянхайским краем (17.04.1914), Брестский мир (03.03.1918),
перенос столицы в Москву (11.03.1918), присоединения 1940 года, май и август
1945-го.

Права. Набор под **CC BY-NC-SA 4.0** — некоммерческая лицензия с указанием
авторства. Проект некоммерческий, это решение принято и записано в каталоге
(`docs/CATALOG.md`, раздел «Каталог открыт»), поэтому полигоны выгружаются
целиком, а не подменяются ссылкой. Цитата авторов и ссылка на набор
проставляются в выходной файл — этого требует и лицензия, и условие 4
(проверяемость).

Доступность. Домен `icr.ethz.ch` отвечает, но соединение рвётся с
`Connection reset by peer` примерно на двух запросах из трёх — сбрасывается
именно скачивание, страница набора при этом открывается. Разница между
«источник исчез» и «источник огрызается» здесь ровно одна: повтор. Поэтому
скачивание идёт с несколькими попытками, и это не украшение, а условие
работоспособности сбора.

На выходе — GeoJSON с полигонами в `data/out/boundaries/`: к схеме контекста
границы не приводятся, это подложка карты (`docs/HARVEST.md`, раздел
«Границы»), ровно как у `ristat.py`. Записей слой не даёт ни одной.

Что отбирается. Из 710 периодов набора берутся те, что попадают в рамку слоя
по времени (1886–1960) и имеют территорию в охвате РИ/СССР (`geo.in_bbox`).
Полигоны при этом не обрезаются: обрезанная граница — это уже не граница
государства, а пересечение с нашей рамкой, и на карте она врала бы. Поэтому
государство берётся целиком, если хоть чем-то в охват заходит: Китай, Иран и
Османская империя нужны границей с империей, а не своей дальней стороной.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import zipfile
from http.client import HTTPException
from io import BytesIO
from typing import Iterable, Optional

from ..geo import in_bbox
from ..net import USER_AGENT
from ..schema import LayerSpec
from .shapefile import ShapefileError, features, read_dbf, read_shapes

DATASET_URL = "https://icr.ethz.ch/data/cshapes/"
ARCHIVE_URL = "https://icr.ethz.ch/data/cshapes/CShapes-2.0.zip"


CITATION = (
    "Schvitz, Guy; Girardin, Luc; Rüegger, Seraina; Weidmann, Nils B.; "
    "Cederman, Lars-Erik; Gleditsch, Kristian Skrede. 2022. «Mapping the "
    "International System, 1886-2019: The CShapes 2.0 Dataset». Journal of "
    "Conflict Resolution 66(1): 144–161. CC BY-NC-SA 4.0"
)

# Рамка слоя. Нижняя граница — начало самого набора, верхняя взята из названия
# слоя: после 1960 года для генеалогии по РИ/СССР меняется уже не то, где
# человек жил, а то, как называется его страна сегодня.
YEAR_MIN, YEAR_MAX = 1886, 1960

ARCHIVE_MEMBERS = ("CShapes-2.0.shp", "CShapes-2.0.dbf")

# Номер России в кодировке Gleditsch — Ward. Отчёт о сборе показывает её
# хронологию, и опознавать её по названию нельзя: название переводится, а
# номер в наборе неизменен.
RUSSIA_GWCODE = 365

# Поля таблицы, без которых разбор бессмысленен. Проверяются до него: если
# ETH переделает набор, сбор должен остановиться, а не выдать пустой слой.
REQUIRED_FIELDS = ("cntry_name", "gwcode", "gwsdate", "gwedate", "gwsyear", "gweyear")

# Горизонт набора: 31.12.2019 в поле «конец периода» означает «границa дожила
# до конца данных», а не очередное её изменение. В рамку слоя это не попадает,
# но при чтении файла разница важна, поэтому такой конец помечается отдельно.
DATASET_END = "20191231"

STATE_BORDERS = LayerSpec(
    slug="state_borders",
    title="Границы государств 1886–1960",
    group="admin",
    source="CShapes 2.0, ETH Zurich (Schvitz, Girardin, Rüegger и др., 2022)",
    license=(
        "CC BY-NC-SA 4.0 — некоммерческая с указанием авторства; проект "
        "некоммерческий, поэтому годится. Цитата и ссылка — в выходном файле"
    ),
    description=(
        "Государственные границы и столицы по датам их изменения: 151 период "
        "46 государств, заходящих территорией в охват РИ/СССР. Отвечает на "
        "вопрос, гражданином какой страны был предок в год записи — Вильно, "
        "Кишинёв и Львов за одну жизнь меняли государство по три раза, а от "
        "ответа зависит, в архиве какой нынешней страны искать."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=151,
    gives_records=False,
)

# Названия государств в наборе английские, и слой от этого читается хуже, чем
# мог бы. Словарь покрывает всё, что реально попадает в отбор; для незнакомого
# названия в файл идёт английское как есть — лучше «Danzig», чем выдуманный
# перевод. Тот же принцип, что у подписей столбцов в `admin_gis.py`.
NAMES_RU = {
    "Afghanistan": "Афганистан",
    "Alaska": "Аляска",
    "Albania": "Албания",
    "Austria": "Австрия",
    "Austria-Hungary": "Австро-Венгрия",
    "Bokhara": "Бухарский эмират",
    "Bosnia": "Босния",
    "Bulgaria": "Болгария",
    "China": "Китай",
    "Cyprus": "Кипр",
    "Czechoslovakia": "Чехословакия",
    "Danzig": "Данциг, вольный город",
    "Estonia": "Эстония",
    "Finland": "Финляндия",
    "Germany (Prussia)": "Германия (Пруссия)",
    "Greece": "Греция",
    "Herzegovina": "Герцеговина",
    "Hungary": "Венгрия",
    "India": "Индия",
    "Iran (Persia)": "Иран (Персия)",
    "Iraq": "Ирак",
    "Italy/Sardinia": "Италия (Сардинское королевство)",
    "Jammu and Kashmir": "Джамму и Кашмир",
    "Japan": "Япония",
    "Kashmir (North, Azad)": "Кашмир (Азад Кашмир)",
    "Khiva": "Хивинское ханство",
    "Korea": "Корея",
    "Korea, People's Republic of": "Корея (КНДР)",
    "Korea, Republic of": "Корея (Республика Корея)",
    "Latvia": "Латвия",
    "Lithuania": "Литва",
    "Mongolia": "Монголия",
    "Montenegro": "Черногория",
    "Norway": "Норвегия",
    "Pakistan": "Пакистан",
    "Poland": "Польша",
    "Rumania": "Румыния",
    "Russia (Soviet Union)": "Россия (Советский Союз)",
    "Serbia": "Сербия",
    "Southern Sakhalin Island": "Южный Сахалин",
    "Sweden": "Швеция",
    "Syria": "Сирия",
    "Tibet": "Тибет",
    "Turkey (Ottoman Empire)": "Турция (Османская империя)",
    "United States of America": "Соединённые Штаты Америки",
    "Yugoslavia": "Югославия",
}


class CShapesError(RuntimeError):
    """Набор не скачался или пришёл не в том виде, какого мы ждём."""


def download(url: str = ARCHIVE_URL, *, timeout: int = 300, attempts: int = 5,
             pause: float = 2.0) -> bytes:
    """Скачивает архив набора, повторяя попытку при обрыве соединения.

    Повторы здесь обязательны: `icr.ethz.ch` рвёт скачивание чаще, чем отдаёт
    его с первого раза. HTTP-ответ с кодом ошибки, наоборот, не повторяется —
    404 от повтора не исправится, а от 403 повтор только навредит.

    Между попытками выдерживается растущая пауза. Долбить сервер, который и
    так рвёт соединение, — верный способ получить обрыв и в следующий раз:
    причиной сброса вполне может быть сама частота обращений.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total = max(1, attempts)
    last: Optional[Exception] = None
    for made in range(1, total + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise CShapesError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, HTTPException, OSError) as exc:
            last = exc
            if made < total and pause:
                time.sleep(pause * made)
    reason = getattr(last, "reason", last)
    raise CShapesError(
        f"{url}: соединение обрывается ({reason}); попыток сделано {total}"
    )


def read_archive(data: bytes) -> list[dict]:
    """Достаёт из zip-архива шейпфайл и сшивает геометрию с таблицей."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            missing = [m for m in ARCHIVE_MEMBERS if m not in names]
            if missing:
                raise CShapesError(
                    f"в архиве нет файлов {missing}; лежат: {sorted(names)}"
                )
            shp, dbf = (archive.read(m) for m in ARCHIVE_MEMBERS)
    except zipfile.BadZipFile as exc:
        raise CShapesError(f"скачанное не разбирается как zip ({exc})") from exc

    try:
        feats = features(read_shapes(shp), read_dbf(dbf))
    except ShapefileError as exc:
        raise CShapesError(f"шейпфайл не разбирается: {exc}") from exc
    check_fields(feats)
    return feats


def load(cache_dir, *, timeout: int = 300) -> list[dict]:
    """Периоды набора; скачанный архив остаётся в кэше.

    Набор весит 13 МБ и с версией 2.0 не меняется, поэтому качается один раз:
    при рвущемся соединении это ещё и способ не дёргать сервер лишний раз.

    В кэш архив кладётся только после того, как разобрался. Иначе оборванное
    скачивание отравило бы кэш навсегда: следующий запуск нашёл бы файл на
    месте, снова споткнулся о него и снова — а совет «просто запустите ещё
    раз» перестал бы работать.
    """
    path = cache_dir / "CShapes-2.0.zip"
    if path.exists():
        try:
            return read_archive(path.read_bytes())
        except CShapesError as exc:
            raise CShapesError(
                f"кэш повреждён: {exc}. Удалите {path} и запустите сбор снова."
            ) from exc
    data = download(timeout=timeout)
    feats = read_archive(data)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return feats


def check_fields(feats: list[dict]) -> None:
    """Проверяет, что в таблице есть поля, на которых держится разбор.

    Смотрит на все записи, а не на первую: пустое значение до свойств не
    доезжает (`shapefile.features` выбрасывает None), и одна незаполненная
    клетка в первой строке выглядела бы как переделанный набор.
    """
    if not feats:
        raise CShapesError("в наборе нет ни одного полигона")
    keys = set()
    for feature in feats:
        keys.update(feature.get("properties") or {})
    missing = [f for f in REQUIRED_FIELDS if f not in keys]
    if missing:
        raise CShapesError(
            f"в таблице набора нет обязательных полей {missing}; пришли: "
            f"{sorted(keys)}. Проверьте {DATASET_URL} и поправьте разбор."
        )


def rings(geometry: Optional[dict]) -> list[list]:
    """Все кольца полигона одним списком — и внешние, и дырки."""
    if not isinstance(geometry, dict):
        return []
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return list(coords)
    if geometry.get("type") == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def touches_region(geometry: Optional[dict]) -> bool:
    """Заходит ли государство хоть одной точкой границы в охват РИ/СССР.

    Проверка по вершинам, а не по описанному прямоугольнику: у России
    прямоугольник растянут от −180° до 180° (Чукотка за меридианом), и по нему
    в отбор попало бы полмира.
    """
    return any(in_bbox(lat, lon) for ring in rings(geometry) for lon, lat in ring)


def overlaps(props: dict, year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> bool:
    """Пересекается ли период существования границы с рамкой слоя."""
    start, end = props.get("gwsyear"), props.get("gweyear")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return start <= year_max and end >= year_min


def select(feats: Iterable[dict], *, year_min: int = YEAR_MIN,
           year_max: int = YEAR_MAX, region_only: bool = True) -> list[dict]:
    """Периоды в рамке слоя, приведённые к подписям, понятным читателю файла."""
    out = []
    for feature in feats:
        props = feature.get("properties") or {}
        if not overlaps(props, year_min, year_max):
            continue
        if region_only and not touches_region(feature.get("geometry")):
            continue
        out.append(boundary(feature))
    return out


def boundary(feature: dict) -> dict:
    """Один период с русским названием, датами и столицей.

    Даты набора сохраняются как есть, без обрезки по рамке слоя: период
    «1945–1991» на карте 1950 года всё равно отберётся по году, а подмена его
    конца на 1960-й была бы выдумкой про данные.
    """
    props = feature.get("properties") or {}
    name = props.get("cntry_name")
    date_from, date_to = _date(props.get("gwsdate")), _date(props.get("gwedate"))
    out = {
        "state": NAMES_RU.get(name, name),
        "state_en": name,
        "gwcode": props.get("gwcode"),
        "year_from": props.get("gwsyear"),
        "year_to": props.get("gweyear"),
        "date_from": date_from,
        "date_to": date_to,
        "capital": props.get("capname"),
        "caplat": props.get("caplat"),
        "caplon": props.get("caplong"),
    }
    if str(props.get("gwedate")) == DATASET_END:
        # Не изменение границы, а край данных: важно для того, кто станет
        # читать файл и увидит у полигона конец «2019».
        out["open_end"] = True
    return {
        "type": "Feature",
        "geometry": feature.get("geometry"),
        "properties": {k: v for k, v in out.items() if v is not None},
    }


def _date(value) -> Optional[str]:
    """«18860101» → «1886-01-01»; в таблице поле строковое, но бывает и число."""
    if value is None:
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"


def states(feats: Iterable[dict]) -> list[str]:
    """Государства отбора по-русски, по алфавиту — для отчёта о сборе."""
    return sorted({(f.get("properties") or {}).get("state") for f in feats
                   if (f.get("properties") or {}).get("state")})


def collection(feats: list[dict], *, year_min: int = YEAR_MIN,
               year_max: int = YEAR_MAX) -> dict:
    return {
        "type": "FeatureCollection",
        "name": STATE_BORDERS.slug,
        "period": f"{year_min}–{year_max}",
        "license": STATE_BORDERS.license,
        "source": STATE_BORDERS.source,
        "citation": CITATION,
        "url": DATASET_URL,
        "features": feats,
    }


def write(collection_dict: dict, path) -> int:
    """Пишет коллекцию сжатым JSON: у 557 тысяч вершин пробелы — это мегабайт."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(collection_dict, fh, ensure_ascii=False, separators=(",", ":"))
    return len(collection_dict.get("features") or [])
