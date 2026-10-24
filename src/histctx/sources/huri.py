"""Районы УССР 1922–1937 годов, перепись 1926 года по районам и поселения Подолии.

Источник — картографический сервер атласа MAPA Украинского научного института
Гарварда (HURI): `maps-huri-ws.net/arcgis/rest/services`. Это ArcGIS REST с
открытыми MapServer, у которых разрешён Query, — машинный ответ без ключа,
до 1 000 записей за запрос. Витрина атласа (`gis.huri.harvard.edu`) нам
отвечает 403, сервер карт — нет.

Зачем три слоя из одного места.

* **Административное деление УССР по датам** (`master_admin`). Между губерниями
  1897 года и областями 1950-х в Украине — пятнадцать лет районирования:
  губернии и повиты 1922 года, округа и районы 1927-го и 1928-го, районы и
  области 1932–1937-го. Метрики и акты гражданского состояния этих лет лежат
  в фондах районов, которых больше нет, и без полигона на нужную дату не
  понять, в каком районе было село. У каждого полигона есть даты начала и
  конца, название по-украински, по-русски и латиницей, центр и примечание
  («нац. німецький», «кол. Грос-Лібентальський»). Это подложка карты, как
  полигоны 1897 года: записями схемы она не становится.
* **Перепись 1926 года по 625 районам** (`master_ethnic`): население по полу
  и по четырнадцати народностям. Для факта «родился в 1925 году в Спартаковском
  районе» это ответ на вопрос, среди кого жила семья: немецкий район, еврейское
  местечко или украинское село. Записи с охватом «район внутри губернии»,
  без точки, по образцу итогов переписей heiDATA (`admin_gis.py`).
* **Поселения Подолии XIV–XV веков** (`podillya`): 536 мест с историческим и
  нынешним названием и годом первого упоминания. Точечный слой: «Агдашов, ныне
  Серебрия, известно с 1448 года» — то, что спрашивают о селе предков.

Права. Сервер условий использования не публикует: в карточке каждого сервиса
`copyrightText` — «HURI», у карточек ArcGIS Online — «© President and Fellows of
Harvard College». **Права не выяснены**, поэтому по условию 3 «Каталога
открыт» берутся факты — названия, даты, числа переписи, границы — со ссылкой
на сервис; описательных текстов и сканов карт сервер и не отдаёт.

Что сознательно не берётся: `master_losses` (потери от голода 1932–1934
годов) — его подключает слой голода 1933 года; `master_1920s` (голод
1921–1922 и бедствие 1928–1929 годов) — записан в журнал дискавери.
"""

from __future__ import annotations

import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..io_formats import feature_collection
from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .wikidata import OPEN_END_YEAR

SERVICES_URL = "https://maps-huri-ws.net/arcgis/rest/services"
ADMIN_SERVICE = "famine_maps/master_admin/MapServer"
ETHNIC_SERVICE = "famine_maps/master_ethnic/MapServer"
PODILLYA_SERVICE = "podillya/podillya/MapServer"
ADMIN_URL = f"{SERVICES_URL}/{ADMIN_SERVICE}"
ETHNIC_URL = f"{SERVICES_URL}/{ETHNIC_SERVICE}"
PODILLYA_URL = f"{SERVICES_URL}/{PODILLYA_SERVICE}"

SOURCE = "HURI MAPA (Украинский научный институт Гарварда), ArcGIS REST"
LICENSE = (
    "права не выяснены: сервер условий не публикует (copyrightText «HURI», у карточек "
    "ArcGIS Online — «© President and Fellows of Harvard College»); берутся факты — "
    "названия, даты, числа, границы — со ссылкой на сервис"
)
CITATION = (
    "MAPA: Digital Atlas of Ukraine. Harvard Ukrainian Research Institute (HURI). "
    f"ArcGIS REST: {SERVICES_URL}/famine_maps, {SERVICES_URL}/podillya"
)

ADMIN_UKRAINE = LayerSpec(
    slug="admin_ussr_ukraine",
    title="Административное деление УССР 1922–1937 годов",
    group="admin",
    source=f"{SOURCE}, famine_maps/master_admin",
    license=LICENSE,
    description=(
        "Губернии и повиты 1922 года, округа и районы 1927 и 1928 годов, районы и "
        "области 1932–1937 годов полигонами — восемь срезов с датами начала и конца, "
        "названиями по-украински, по-русски и латиницей и центрами. Отвечает, в каком "
        "районе было село в год записи и в фонде какого упразднённого района искать "
        "дело: границы 1897 года до межвоенной Украины не доходят."
    ),
    url=ADMIN_URL,
    status="harvested",
    expected_rows=3571,
    gives_records=False,
)

CENSUS_1926 = LayerSpec(
    slug="census_1926_raion",
    title="Перепись 1926 года по районам УССР: население по народностям",
    group="admin",
    source=f"{SOURCE}, famine_maps/master_ethnic",
    license=LICENSE,
    description=(
        "Итоги переписи 17 декабря 1926 года по 625 районам УССР в границах на 1 марта "
        "1927 года: сельское население всего и по полу, украинцы, русские, евреи, поляки, "
        "немцы, молдаване, болгары, греки и ещё шесть народностей. Отвечает, среди кого "
        "жила семья, на уровне района, а не союзной республики."
    ),
    url=ETHNIC_URL,
    status="harvested",
    expected_rows=625,
)

PODILLYA = LayerSpec(
    slug="podillya_settlements",
    title="Поселения Подолии XIV–XV веков: первые упоминания",
    group="admin",
    source=f"{SOURCE}, podillya",
    license=LICENSE,
    description=(
        "536 сёл, городов, замков и пусток Подолии с историческим и нынешним названием, "
        "годом первого упоминания (1370–1506) и координатой. Отвечает, под каким именем "
        "село предков известно в документах и насколько оно старое."
    ),
    url=PODILLYA_URL,
    status="harvested",
    expected_rows=536,
)


class HuriError(RuntimeError):
    """Сервер не ответил или ответил не в том виде, какой записан в коде."""


# --- перечень слоёв сервера ------------------------------------------------
# Записан в коде и сверяется с сервером на --check: номер, имя слоя, число
# объектов. Разошлось — остановка: сервис переиздали, и прежде чем собирать,
# надо понять, что в нём поменялось.

@dataclass(frozen=True)
class Slice:
    """Один слой `master_admin`: срез деления на дату и уровень единиц."""

    layer_id: int
    name: str           # имя слоя на сервере, сверяется дословно
    as_of: str          # дата среза, ISO
    level: str          # center | raion | region
    count: int          # число объектов, измеренное 24.10.2026
    schema: str = "master"     # master | 1932_10 — два набора полей
    duplicate_of: Optional[int] = None


SLICES = (
    Slice(1, "Centers on 15 January 1937", "1937-01-15", "center", 525),
    Slice(2, "Raions on 15 January 1937", "1937-01-15", "raion", 525),
    Slice(3, "Oblasts on 15 January 1937", "1937-01-15", "region", 8),
    Slice(5, "Centers on 30 May 1934", "1934-05-30", "center", 393),
    Slice(6, "Raions on 30 May 1934", "1934-05-30", "raion", 393),
    Slice(7, "Oblasts on 30 May 1934", "1934-05-30", "region", 8),
    Slice(9, "Centers on 15 December 1933", "1933-12-15", "center", 393),
    Slice(10, "Raions on 15 December 1933", "1933-12-15", "raion", 393),
    Slice(11, "Oblasts on 15 December 1933", "1933-12-15", "region", 8),
    # Срез «1 April 1933» на сервере — точная копия среза 15 декабря 1933 года:
    # те же атрибуты с теми же датами, те же вершины. Своих данных на 1 апреля
    # в сервисе нет; копия не выгружается, а --check проверяет, что она всё
    # ещё копия.
    Slice(13, "Centers on 1 April 1933", "1933-04-01", "center", 393, duplicate_of=9),
    Slice(14, "Raions on 1 April 1933", "1933-04-01", "raion", 393, duplicate_of=10),
    Slice(15, "Oblasts on 1 April 1933", "1933-04-01", "region", 8, duplicate_of=11),
    Slice(17, "Centers on 25 October 1932", "1932-10-25", "center", 386, schema="1932_10"),
    Slice(18, "Raions on 25 October 1932", "1932-10-25", "raion", 386, schema="1932_10"),
    Slice(19, "Oblasts on 25 October 1932", "1932-10-25", "region", 8, schema="1932_10"),
    Slice(21, "Centers on 20 March 1932", "1932-03-20", "center", 386),
    Slice(22, "Raions on 20 March 1932", "1932-03-20", "raion", 387),
    Slice(23, "Oblasts on 20 March 1932", "1932-03-20", "region", 7),
    Slice(24, "Oblasts & special raions", "1932-03-20", "region", 23),
    # Группа слоёв на сервере названа «1928-04-15», а сами слои и даты начала
    # в них — 15 августа 1928 года. Срез датируется по слоям.
    Slice(26, "Centers on 15 August 1928", "1928-08-15", "center", 612),
    Slice(27, "Raions on 15 August 1928", "1928-08-15", "raion", 604),
    Slice(28, "Okruhas on 15 August 1928", "1928-08-15", "region", 41),
    Slice(30, "Centers on 1 March 1927", "1927-03-01", "center", 635),
    Slice(31, "Raions on 1 March 1927", "1927-03-01", "raion", 625),
    Slice(32, "Okruhas on 1 March 1927", "1927-03-01", "region", 41),
    Slice(34, "Centers in January 1922", "1922-01-01", "center", 102),
    Slice(35, "Povits in January 1922", "1922-01-01", "raion", 102),
    Slice(36, "Huberniyas in January 1922", "1922-01-01", "region", 12),
)

# Поля, без которых срез не разобрать. Набора два: у среза 25 октября 1932
# года поля названы по-другому (NAME_UA вместо UKR_Name, DATE вместо START_D).
REQUIRED_FIELDS = {
    "master": {"OBJECTID", "UKR_Name", "RUS_Name", "ENG_Name", "ADM_Type", "START_D"},
    "1932_10": {"OBJECTID", "NAME_UA", "NAME_RUS", "NAME_LAT", "TYPE"},
}

# Какой срез даёт районы для переписи и откуда берутся названия округов.
CENSUS_RAIONS_LAYER = 31
CENSUS_OKRUHAS_LAYER = 32

# Перепись: все девять слоёв `master_ethnic` несут одну и ту же таблицу и
# различаются только раскраской — берётся один, без геометрии (полигоны те же,
# что у районов 1 марта 1927 года, и они уже есть в подложке).
ETHNIC_LAYER = 8
ETHNIC_LAYER_NAME = "Ethnic Ukrainians by raion, % of rural population"
ETHNIC_COUNT = 625

PODILLYA_LAYER = 0
PODILLYA_LAYER_NAME = "Podillya Settlement"
PODILLYA_COUNT = 536
REQUIRED_PODILLYA = {"OBJECTID", "name_historic_ukr", "name_modern_ukr", "type_placename__ukr",
                     "date_start", "date_end", "y_Latitude", "x_Longitude"}

# Народности переписи: приставка колонки → подпись. Колонки `<код>_male`,
# `<код>_female`, `<код>_both`; `All_*` — всё население района.
NATIONALITIES = {
    "Ukr": "украинцы", "Rus": "русские", "Jew": "евреи", "Pol": "поляки",
    "Ger": "немцы", "Bel": "белорусы", "Mol": "молдаване", "Gyp": "цыгане",
    "Cze": "чехи", "Gre": "греки", "Tat": "татары", "Bul": "болгары",
    "Arm": "армяне", "Lat": "латыши",
}
REQUIRED_ETHNIC = ({"OBJECTID_1", "RAY_Master", "UKR_Name", "RUS_Name", "REGION", "ADM_Type",
                    "All_male", "All_female", "All_both"}
                   | {f"{code}_both" for code in NATIONALITIES})

# Сколько народностей называть в описании: три — это уже портрет района.
TOP_GROUPS = 3

# Названия округов 1927 года по-русски — из слоя округов того же среза. Колонка
# REGION у районов пишет три округа иначе, чем сам слой округов; LABEL слоя
# округов пишет их так же, как REGION, поэтому ключом служат оба написания.
# Две опечатки русских названий в слое округов исправлены здесь, а не молча.
OKRUHA_RU_FIXES = {"Харковский": "Харьковский", "Бердичевкий": "Бердичевский"}

# Кто такие владельцы у поселений Подолии: сокращения источника.
PODILLYA_PROPERTY = {
    "кор. вл.": "королевское владение",
    "дід. вл.": "наследственное (дедичное) владение",
    "влкн. вл.": "великокняжеское владение",
    "єп. вл.": "епископское владение",
}
PODILLYA_TYPES = {
    "село": "село", "cело": "село", "місто": "город", "замок": "замок",
    "пустка": "пустошь", "урочище": "урочище", "городище": "городище", "ліс": "лес",
    "місцевість": "местность", "поле": "поле", "присілок": "присёлок",
    "монастир": "монастырь", "територія": "территория",
}
# Поселение, которое существует и сегодня (у него есть нынешнее название), —
# с первого упоминания до горизонта проекта, как храм из Викиданных «с 1802».
# Пустошь, урочище, лес, замок, городище — только год упоминания: о том, что
# было на их месте потом, источник не говорит.
PODILLYA_LIVING = {"село", "місто", "присілок", "cело", "село/місто", "місто/село"}

# Подложка: точность упрощения и округления. Полигоны 1922, 1927 и 1928 годов
# на сервере подробные (до 394 тысяч вершин на срез), срезы 1932–1937 годов —
# уже обобщённые. Дугласа — Пекера с допуском 0,001° (около 70–110 м)
# хватает, чтобы граница района на карте не отличалась на глаз, а все срезы
# вместе уложились в несколько мегабайт; координата — до 4 знаков (около 10 м).
SIMPLIFY_TOLERANCE = 0.001
COORD_DIGITS = 4
POINT_DIGITS = 5


# --- сеть ------------------------------------------------------------------

class Client:
    """Запросы к серверу: подпись, пауза, повторы.

    Сервер то и дело рвёт соединение на рукопожатии (`Connection reset by
    peer`) — на пробе это случалось примерно на каждом десятом запросе. Повтор
    здесь — условие работоспособности сбора, как у CShapes.
    """

    def __init__(self, *, pause_sec: float = 0.5, attempts: int = 5, timeout: int = 300) -> None:
        self.pause_sec = pause_sec
        self.attempts = attempts
        self.timeout = timeout
        self._last = 0.0

    def get(self, path: str, **params) -> dict:
        params.setdefault("f", "json")
        url = f"{SERVICES_URL}/{path}?{urllib.parse.urlencode(params)}"
        error: Optional[Exception] = None
        for attempt in range(self.attempts):
            self._last = wait_for_pause(self._last, self.pause_sec)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES:
                    raise HuriError(f"{url}: HTTP {exc.code}") from exc
                error = exc
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                error = exc
            else:
                if isinstance(payload, dict) and "error" in payload:
                    raise HuriError(f"{url}: сервер ответил ошибкой {payload['error']}")
                return payload
            time.sleep(2 * (attempt + 1))
        raise HuriError(f"{url}: не ответил за {self.attempts} попыток ({error})")

    def query_all(self, service: str, layer: int, *, geometry: bool = True) -> dict:
        """Все объекты слоя: страницами по 1 000, по порядку OBJECTID.

        Порядок задан явно: без него сервер вправе отдавать страницы в любом
        порядке, и смещение пропустит или повторит объекты.
        """
        features: list = []
        payload: dict = {}
        while True:
            payload = self.get(
                f"{service}/{layer}/query", where="1=1", outFields="*", outSR="4326",
                returnGeometry="true" if geometry else "false", orderByFields="OBJECTID",
                resultOffset=len(features), resultRecordCount=1000,
            )
            page = payload.get("features") or []
            features += page
            if not payload.get("exceededTransferLimit") or not page:
                break
        payload["features"] = features
        return payload


# --- сверка с сервером -----------------------------------------------------

def check_admin_service(service_info: dict) -> list[str]:
    """Расхождения перечня слоёв `master_admin` с записанным в коде."""
    on_server = {layer["id"]: layer["name"] for layer in service_info.get("layers") or []}
    problems = []
    for item in SLICES:
        name = on_server.get(item.layer_id)
        if name != item.name:
            problems.append(f"слой {item.layer_id}: в коде «{item.name}», на сервере «{name}»")
    return problems


def check_layer(info: dict, *, name: str, required: set, count: Optional[int],
                actual_count: Optional[int]) -> list[str]:
    """Расхождения одного слоя: имя, обязательные поля, число объектов."""
    problems = []
    if info.get("name") != name:
        problems.append(f"имя слоя «{info.get('name')}», ожидалось «{name}»")
    fields = {field.get("name") for field in info.get("fields") or []}
    missing = sorted(required - fields)
    if missing:
        problems.append(f"«{name}»: нет полей {', '.join(missing)}")
    if count is not None and actual_count != count:
        problems.append(f"«{name}»: объектов {actual_count}, в коде {count}")
    return problems


def same_features(a: dict, b: dict) -> bool:
    """Два ответа сервера несут одни и те же объекты — атрибуты и геометрию."""
    def strip(payload):
        return [(f.get("attributes"), f.get("geometry")) for f in payload.get("features") or []]
    return strip(a) == strip(b)


# --- разбор: подложка ------------------------------------------------------

def epoch_date(value) -> Optional[str]:
    """Дата ArcGIS (миллисекунды от 1970 года, UTC) → «1937-01-15»."""
    if value is None or value == "":
        return None
    moment = datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=float(value))
    return moment.date().isoformat()


def admin_properties(attrs: dict, item: Slice) -> dict:
    """Атрибуты объекта среза → свойства подложки с едиными именами.

    Пустые значения (сервер пишет их пробелом) опускаются. Даты начала и конца
    — как в источнике: `end` — это день перед следующим срезом, а не дата
    упразднения единицы (повиты 1922 года «действуют» до 28 февраля 1927-го,
    хотя упразднены в 1923-м). Срез, к которому относится объект, — `as_of`.
    """
    if item.schema == "1932_10":
        raw = {
            "name_uk": attrs.get("NAME_UA"), "name_ru": attrs.get("NAME_RUS"),
            "name_en": attrs.get("NAME_LAT"), "kind": attrs.get("TYPE"),
            "region": attrs.get("Region"), "notes": attrs.get("COMMENT"),
            "label": attrs.get("LABEL"),
            "start": epoch_date(attrs.get("DATE")), "end": epoch_date(attrs.get("End_Date")),
            "id": attrs.get("Master_rai") or attrs.get("Master_reg"),
            "population_range": attrs.get("POP_RANGE"),
        }
    else:
        raw = {
            "name_uk": attrs.get("UKR_Name"), "name_ru": attrs.get("RUS_Name"),
            "name_en": attrs.get("ENG_Name"), "kind": attrs.get("ADM_Type"),
            "seat": attrs.get("ADM_Seat"), "region": attrs.get("REGION"),
            "notes": attrs.get("NOTES"), "label": attrs.get("LABEL"),
            "start": epoch_date(attrs.get("START_D")),
            "end": epoch_date(attrs.get("END_Date", attrs.get("End_Date"))),
            "id": attrs.get("RAY_Master") or attrs.get("REG_Master") or attrs.get("ADM_Master"),
            "historic": attrs.get("HISTORIC"), "present": attrs.get("PRESENT"),
        }
    props = {"as_of": item.as_of, "level": item.level, "layer": item.layer_id,
             "oid": attrs.get("OBJECTID")}
    for key, value in raw.items():
        text = clean_text(value) if isinstance(value, str) else value
        if text not in (None, ""):
            props[key] = text
    # Даты, взятые из чужого среза, — пометка, а не правка: у райцентров
    # января 1922 года в источнике стоят даты 1928–1932 годов.
    if props.get("start") and props["start"] > _slice_end(item):
        props["dates_conflict"] = True
    return props


def _slice_end(item: Slice) -> str:
    later = sorted({s.as_of for s in SLICES if s.as_of > item.as_of and s.duplicate_of is None})
    return later[0] if later else "9999-12-31"


def simplify(points: list, tolerance: float) -> list:
    """Дуглас — Пекер по одному кольцу: концы остаются, середина прореживается."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    limit = tolerance * tolerance
    while stack:
        first, last = stack.pop()
        ax, ay = points[first][0], points[first][1]
        bx, by = points[last][0], points[last][1]
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        worst, index = -1.0, -1
        for i in range(first + 1, last):
            px, py = points[i][0], points[i][1]
            t = 0.0 if norm == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / norm))
            dist = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if dist > worst:
                worst, index = dist, i
        if worst > limit:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep) if k]


def _rounded(points: list, digits: int) -> list:
    out: list = []
    for point in points:
        q = [round(point[0], digits), round(point[1], digits)]
        if not out or q != out[-1]:
            out.append(q)
    return out


def _signed_area(ring: list) -> float:
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat):
            if lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def esri_polygon(geometry: Optional[dict], *, tolerance: float = SIMPLIFY_TOLERANCE,
                 digits: int = COORD_DIGITS) -> Optional[dict]:
    """Кольца ArcGIS → GeoJSON Polygon/MultiPolygon, упрощённые и округлённые.

    В ArcGIS внешнее кольцо идёт по часовой стрелке, дыра — против, и какая
    дыра в каком полигоне, не записано: она относится к внешнему кольцу, в
    котором лежит. В GeoJSON (RFC 7946) наоборот — внешнее против часовой.
    Кольцо, которое упрощение схлопнуло, берётся без упрощения: район не
    должен пропасть с карты из-за допуска.
    """
    outers: list = []
    holes: list = []
    for ring in (geometry or {}).get("rings") or []:
        if len(ring) < 4:
            continue
        clean = _rounded(simplify(ring, tolerance), digits)
        if len(clean) < 4:
            clean = _rounded(ring, digits)
        if len(clean) < 4:
            continue
        if clean[0] != clean[-1]:
            clean.append(clean[0])
        area = _signed_area(clean)
        if area < 0:                       # по часовой — внешнее
            outers.append([clean[::-1]])
        elif area > 0:
            holes.append(clean[::-1])
    if not outers and holes:
        # Кольца в обратном порядке обхода: значит, дыр нет, это внешние.
        outers = [[ring[::-1]] for ring in holes]
        holes = []
    for hole in holes:
        lon, lat = hole[0]
        for polygon in outers:
            if _in_ring(lon, lat, polygon[0]):
                polygon.append(hole)
                break
    if not outers:
        return None
    if len(outers) == 1:
        return {"type": "Polygon", "coordinates": outers[0]}
    return {"type": "MultiPolygon", "coordinates": outers}


def esri_point(geometry: Optional[dict], digits: int = POINT_DIGITS) -> Optional[dict]:
    if not geometry or geometry.get("x") is None or geometry.get("y") is None:
        return None
    return {"type": "Point",
            "coordinates": [round(geometry["x"], digits), round(geometry["y"], digits)]}


def slice_features(payload: dict, item: Slice) -> list[dict]:
    """Объекты одного среза → GeoJSON-фичи подложки."""
    out = []
    for feature in payload.get("features") or []:
        props = admin_properties(feature.get("attributes") or {}, item)
        geometry = (esri_point(feature.get("geometry")) if item.level == "center"
                    else esri_polygon(feature.get("geometry")))
        out.append({"type": "Feature", "geometry": geometry, "properties": props})
    return out


def boundaries_collection(feats: list[dict], name: str) -> dict:
    return feature_collection(
        name, feats, license=ADMIN_UKRAINE.license, source=ADMIN_UKRAINE.source,
        citation=CITATION, url=ADMIN_URL,
        extra={"slices": sorted({s.as_of for s in SLICES if s.duplicate_of is None})},
    )


# --- разбор: перепись 1926 года --------------------------------------------

def to_number(value) -> Optional[float]:
    """Число из ячейки: у части народностей колонка строковая, «1,596»."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def okruha_names(payload: dict) -> dict[str, str]:
    """Написание округа в колонке REGION → «Херсонский округ»."""
    out: dict[str, str] = {}
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        ru = clean_text(attrs.get("RUS_Name"))
        if not ru:
            continue
        ru = OKRUHA_RU_FIXES.get(ru, ru)
        kind = clean_text(attrs.get("ADM_Type")) or ""
        full = f"{ru} АССР" if kind == "АСРР" else f"{ru} округ"
        for key in (clean_text(attrs.get("UKR_Name")),
                    _strip_suffix(clean_text(attrs.get("LABEL")), (" округа", " АСРР"))):
            if key:
                out.setdefault(key, full)
    return out


def _strip_suffix(text: Optional[str], suffixes: tuple) -> Optional[str]:
    if not text:
        return None
    for suffix in suffixes:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def representative_point(geometry: Optional[dict]) -> Optional[tuple[float, float]]:
    """Точка внутри полигона: середина самого широкого отрезка горизонтали.

    Центроид района бывает вне района (подкова, излучина реки), а губернию по
    нему спрашивать нельзя. Горизонталь через середину самого большого
    кольца по высоте пересекает его чётное число раз, и середина отрезка между
    парой пересечений лежит внутри.
    """
    if not geometry:
        return None
    polygons = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                else [geometry["coordinates"]])
    ring = max((p[0] for p in polygons), key=lambda r: abs(_signed_area(r)))
    lats = [pt[1] for pt in ring]
    lat = (min(lats) + max(lats)) / 2
    crossings = sorted(
        (x2 - x1) * (lat - y1) / (y2 - y1) + x1
        for (x1, y1), (x2, y2) in zip(ring, ring[1:])
        if (y1 > lat) != (y2 > lat)
    )
    pairs = list(zip(crossings[0::2], crossings[1::2]))
    if not pairs:
        return None
    left, right = max(pairs, key=lambda pair: pair[1] - pair[0])
    return lat, (left + right) / 2


@dataclass
class RaionIndex:
    """Полигоны районов 1 марта 1927 года по ключу (RAY_Master, UKR_Name).

    Ключ двойной, потому что RAY_Master в источнике не уникален: под
    «Ray-1927-01-31» лежат два разных района, Новоселовский и Мангушский.
    """

    shapes: dict
    okruhas: dict

    def geometry(self, attrs: dict) -> Optional[dict]:
        return self.shapes.get(_raion_key(attrs))


def raion_index(raions: dict, okruhas: dict) -> RaionIndex:
    shapes = {}
    for feature in raions.get("features") or []:
        attrs = feature.get("attributes") or {}
        shapes[_raion_key(attrs)] = esri_polygon(feature.get("geometry"))
    return RaionIndex(shapes=shapes, okruhas=okruha_names(okruhas))


def _raion_key(attrs: dict) -> tuple:
    return clean_text(attrs.get("RAY_Master")), clean_text(attrs.get("UKR_Name"))


def raion_title(attrs: dict) -> str:
    """«Скадовский район», «Сталинский горсовет», «Плавни»."""
    name = clean_text(attrs.get("RUS_Name")) or clean_text(attrs.get("UKR_Name")) or "?"
    kind = clean_text(attrs.get("ADM_Type"))
    if kind == "район":
        return f"{name} район"
    if kind == "міськрада":
        return f"{name} горсовет"
    return name


def nationality_counts(attrs: dict) -> dict[str, dict]:
    """{"всего": {...}, "украинцы": {"м": .., "ж": .., "оба": ..}, …} — по числам."""
    out: dict[str, dict] = {}
    for code, label in [("All", "всего"), *NATIONALITIES.items()]:
        row = {}
        for suffix, key in (("male", "м"), ("female", "ж"), ("both", "оба")):
            value = to_number(attrs.get(f"{code}_{suffix}"))
            if value is not None:
                row[key] = int(round(value))
        if row.get("оба"):
            out[label] = row
    return out


def census_summary(counts: dict) -> str:
    total = (counts.get("всего") or {}).get("оба")
    if not total:
        return ("Перепись 17 декабря 1926 года: в таблице источника числа по этой "
                "единице не заполнены (нули).")
    whole = counts["всего"]
    head = f"Перепись 17 декабря 1926 года, сельское население: {_thousands(total)} человек"
    if whole.get("м") is not None and whole.get("ж") is not None:
        head += f" ({_thousands(whole['м'])} муж., {_thousands(whole['ж'])} жен.)"
    groups = sorted(((label, row["оба"]) for label, row in counts.items() if label != "всего"),
                    key=lambda pair: pair[1], reverse=True)[:TOP_GROUPS]
    if groups:
        listed = ", ".join(f"{label} — {_share(value, total)}" for label, value in groups)
        head += f". {listed[0].upper()}{listed[1:]}"
    return head + "."


def census_records(payload: dict, index: Optional[RaionIndex] = None, provinces=None,
                   spec: LayerSpec = CENSUS_1926) -> list[ContextRecord]:
    """Записи переписи с охватом «район»: без точки, губерния 1897 года — по полигону.

    Подбор территориальных записей идёт по названию губернии (`histctx.enrich`),
    а у факта из метрики XIX века губерния та, что в 1897 году. Поэтому район
    получает губернию 1897 года, в которой лежит точка внутри его полигона, —
    это ключ подбора, а не утверждение, что район входил в губернию: губерний
    в 1926 году уже нет. Округ 1927 года — в `place_text`.
    """
    out = []
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        counts = nationality_counts(attrs)
        title = raion_title(attrs)
        okruha_uk = clean_text(attrs.get("REGION"))
        okruha = (index.okruhas.get(okruha_uk) if index and okruha_uk else None) or okruha_uk
        region = None
        point = None
        if index is not None:
            point = representative_point(index.geometry(attrs))
            if point and provinces is not None:
                region = provinces.region_for(*point)
        majority = clean_text(attrs.get("Majority"))
        oid = attrs.get("OBJECTID_1") or attrs.get("OBJECTID")
        extra = {
            "census_1926": counts,
            "raion": {k: v for k, v in {
                "ray_master": clean_text(attrs.get("RAY_Master")),
                "name_uk": clean_text(attrs.get("UKR_Name")),
                "name_en": clean_text(attrs.get("ENG_Name")),
                "seat": clean_text(attrs.get("ADM_Seat")),
                "kind": clean_text(attrs.get("ADM_Type")),
                "okruha_uk": okruha_uk,
                "notes": clean_text(attrs.get("NOTES")),
                "boundaries_as_of": epoch_date(attrs.get("START_D")),
            }.items() if v},
            "majority": NATIONALITIES.get(majority, majority) if majority != "Non" else None,
            "citation": CITATION,
        }
        if point:
            extra["region_point"] = [round(point[0], 4), round(point[1], 4)]
        extra = {k: v for k, v in extra.items() if v}
        out.append(spec.new_record(
            title=f"{title} ({okruha}): перепись 1926 года" if okruha else
                  f"{title}: перепись 1926 года",
            category=("перепись 1926 года: население по народностям" if counts.get("всего")
                      else "перепись 1926 года: числа не заполнены"),
            scope=SCOPE_REGION,
            place_text=", ".join(p for p in (title, okruha, "УССР") if p),
            region=region,
            regions=[region] if region else [],
            district=title,
            year_from=1926, year_to=1926,
            date_precision="day",
            period_raw="17 декабря 1926 года; границы района — на 1 марта 1927 года",
            summary=census_summary(counts),
            url=(f"{ETHNIC_URL}/{ETHNIC_LAYER}/query?where=OBJECTID_1%3D{oid}"
                 "&outFields=*&returnGeometry=false&f=html"),
            source_id=f"{clean_text(attrs.get('RAY_Master'))}:{clean_text(attrs.get('UKR_Name'))}",
            confidence="ok" if region or index is None else "region_unmatched",
            extra=extra,
        ))
    return out


def share_mismatches(payload: dict, tolerance: float = 0.01) -> dict[str, int]:
    """Где колонка доли `<код>_to_All_both` не сходится с числами — по народностям."""
    out: dict[str, int] = {}
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        total = to_number(attrs.get("All_both"))
        for code in NATIONALITIES:
            part = to_number(attrs.get(f"{code}_both"))
            share = to_number(attrs.get(f"{code}_to_All_both"))
            if total and part is not None and share is not None \
                    and abs(100 * part / total - share) > tolerance:
                out[code] = out.get(code, 0) + 1
    return out


# --- разбор: поселения Подолии ----------------------------------------------

def podillya_records(payload: dict, provinces=None, districts=None,
                     spec: LayerSpec = PODILLYA) -> list[ContextRecord]:
    """Поселения Подолии → точки с первым упоминанием.

    `date_start`–`date_end` — датировка первого упоминания, а не годы жизни
    поселения: «1411–1430» значит, что документ датирован этим промежутком.
    Если начала нет, упоминание — «не позже» конца.
    """
    out = []
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        lat, lon = to_number(attrs.get("y_Latitude")), to_number(attrs.get("x_Longitude"))
        historic = clean_text(attrs.get("name_historic_ukr"))
        modern = clean_text(attrs.get("name_modern_ukr"))
        # Шесть мест вместо нынешнего названия несут «тепер не існує»: это не
        # имя, а сведение, что поселения нет, — открытого срока у них нет.
        gone = bool(modern) and "не існує" in modern
        if gone:
            modern = None
        kind_uk = clean_text(attrs.get("type_placename__ukr"))
        start, end = _year(attrs.get("date_start")), _year(attrs.get("date_end"))
        first = start if start is not None else end
        last = end if end is not None else start
        mention = _mention_text(start, end)
        living = kind_uk in PODILLYA_LIVING and bool(modern)
        if first is None:
            year_from = year_to = None
            precision = "unknown"
        elif living:
            year_from, year_to, precision = first, max(last, OPEN_END_YEAR), "open"
        else:
            year_from, year_to, precision = first, last, "year"
        name = historic or modern or "?"
        title = name if not modern or modern == name else f"{name} (ныне {modern})"
        kind = _podillya_kind(kind_uk)
        owner = clean_text(attrs.get("ptoperty_type"))
        povit = clean_text(attrs.get("povit_middle_ages_modern_ukr"))
        parts = [f"Историческое название — {historic}" if historic else None,
                 f"нынешнее — {modern}" if modern else None,
                 "ныне не существует" if gone else None]
        summary = ", ".join(p for p in parts if p)
        if mention:
            summary += f". Первое упоминание — {mention}"
        if owner:
            summary += f"; {PODILLYA_PROPERTY.get(owner, owner)}"
        if povit:
            summary += f"; повет (по средневековому делению) — {povit}"
        if not summary.endswith("."):
            summary += "."
        oid = attrs.get("OBJECTID")
        out.append(spec.new_record(
            title=f"{title}: первое упоминание",
            category=kind,
            lat=lat, lon=lon,
            place_text=", ".join(p for p in (modern, povit and f"{povit} повіт") if p) or None,
            region=provinces.region_for(lat, lon) if provinces and lat is not None else None,
            district=_uezd(districts.region_for(lat, lon)) if districts and lat is not None
            else None,
            year_from=year_from, year_to=year_to, date_precision=precision,
            period_raw=(f"первое упоминание {mention}" + (", существует поныне" if living else "")
                        if mention else None),
            summary=summary,
            url=(f"{PODILLYA_URL}/{PODILLYA_LAYER}/query?where=OBJECTID%3D{oid}"
                 "&outFields=*&returnGeometry=false&f=html"),
            source_id=f"podillya:{oid}",
            extra={k: v for k, v in {
                "name_historic_uk": historic, "name_modern_uk": modern,
                "name_historic_en": clean_text(attrs.get("name_historic_eng")),
                "name_modern_en": clean_text(attrs.get("name_modern_eng")),
                "type_uk": kind_uk, "first_mention": [start, end],
                "property": owner, "povit_uk": povit, "gone": gone, "citation": CITATION,
            }.items() if v},
        ))
    return out


def _uezd(name: Optional[str]) -> Optional[str]:
    """«Каменецкий» из справочника RISTAT → «Каменецкий уезд»."""
    if not name:
        return None
    return name if name.endswith(("уезд", "округ", "отдел")) else f"{name} уезд"


def _year(value) -> Optional[int]:
    number = to_number(value)
    return int(number) if number is not None else None


def _mention_text(start: Optional[int], end: Optional[int]) -> Optional[str]:
    if start is not None and end is not None and end != start:
        return f"{start}–{end} гг."
    if start is not None:
        return f"{start} г."
    if end is not None:
        return f"не позже {end} г."
    return None


def _podillya_kind(kind_uk: Optional[str]) -> Optional[str]:
    if not kind_uk:
        return None
    return "/".join(PODILLYA_TYPES.get(part.strip(), part.strip()) for part in kind_uk.split("/"))


# --- мелочи ----------------------------------------------------------------

def _share(part: float, total: float) -> str:
    percent = 100.0 * part / total
    shown = f"{percent:.1f}".rstrip("0").rstrip(".") if percent < 10 else f"{percent:.0f}"
    return f"{shown.replace('.', ',')}%"


def _thousands(value: float) -> str:
    # Неразрывный пробел в разряде тысяч: число не рвётся переносом строки.
    return f"{int(round(value)):,}".replace(",", " ")
