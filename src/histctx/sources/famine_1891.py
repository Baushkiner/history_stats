"""Голод 1891–1892 годов по уездам: набор В. Чарныш (Harvard Dataverse).

Зачем этот слой. Кураторское событие «Голод 1891–1892 годов» в
`data/curated/state_events.json` знает перечень семнадцати губерний — и всё.
Для факта «умер в марте 1892 года в Елецком уезде» это ответ «в вашей губернии
был голод»; набор к статье о голоде отвечает точнее: в Елецком уезде на
продовольственной помощи в пике стояли 167 тысяч человек, 72% населения,
с ноября 1891 по июль 1892 года. Слой даёт голоду уезд, а подбор
по уезду остаётся отдельной задачей — записи подбираются по губернии, как
все территориальные.

Что в наборе (проверено по API Dataverse 22.10.2026):

* `DatasetMainMay2021.tab` — 216 уездов 22 губерний, 193 колонки: число
  людей на помощи помесячно с июля 1891 по август 1892 года, ссуды семенами
  и хлебом в пудах, население, расстояние до железной дороги, состав
  населения по вере и языку, урожаи и ещё полторы сотни величин статьи;
* `Province_Mortality.tab` — 24 губернии: сверхсмертность 1892 года, доля
  населения на помощи, сбор на душу. Названия губерний испорчены двойной
  кодировкой и восстанавливаются здесь;
* `time-series-dataset.tab` — панель 499 уездов 50 губерний за 1885–1896
  годы: рождения и смерти, оценка сверхсмертности, холера 1892 года. Даёт
  ещё два вида записей — холеру 1892 года по уездам и годы со
  сверхсмертностью не ниже полутора сигм по всей панели (`panel_records`);
* `DistrictMap.*` — шейпфайл 566 уездов; поле `ter_id` сопоставляется
  с `ter_ID` главной таблицы, все 216 находятся. Полигоны идут в подложку
  карты, а не в записи.

Права. Карточка набора: **CC0 1.0** (SPDX CC0-1.0) — ограничений нет; ссылка
на набор всё равно стоит в каждой записи, по условию 4 «Каталога открыт».

Что берётся и как. По записи на уезд с охватом «уезд внутри губернии» и
без точки: колонки `lat`/`long` набора — это уездный город, и точка на нём
врала бы о месте голода; они остаются в `extra`. Период помощи читается по
помесячным колонкам — с первого по последний месяц с ненулевым числом;
авторские `onset_mo`/`endrelief_mo` считают месяцы с июля 1891 года
(июль 1891 = 1, август 1892 = 14) и начинают кампанию с месяца, когда на
помощи оказалось больше 1% населения, — так сказано в статье и так сходится
по данным (170 уездов из 175). Эти колонки — сверка, а не источник периода.

Что остаётся в `extra` без перевода в текст: урожаи (`HarvestMean*`), остатки
хлеба (`Ostatok*`), оклады (`oklady*`), индексы Майерса и Уиппла,
сверхсмертность по губерниям (`ExcessMortalityV1/V2`): единицу этих величин
статья в подписи к рисунку не называет, а выдумывать её нельзя.

Названия в наборе латиницей (`Olonets`, `Povenets`). Словари ниже переводят
их по-русски, и каждый уезд сверяется с границами 1897 года RISTAT
(`data/out/boundaries/districts_1897.geojson`): совпасть должен уезд внутри
своей губернии, ключ — `histctx.geo.region_key`. Уезд без пары остаётся в
данных с `confidence="district_unmatched"`.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..geo import region_key
from ..io_formats import feature_collection
from ..net import fetch_bytes
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .shapefile import ShapefileError, features, read_dbf, read_shapes

DOI = "doi:10.7910/DVN/Q4DMKK"
DATASET_URL = "https://doi.org/10.7910/DVN/Q4DMKK"
API_URL = ("https://dataverse.harvard.edu/api/datasets/:persistentId/"
           f"?persistentId={DOI}")
FILE_URL = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"

# Текст из карточки набора — так, как он там стоит.
LICENSE = "CC0 1.0 — общественное достояние (карточка набора: CC0 1.0, SPDX CC0-1.0); " \
          "ссылка на набор проставляется в каждой записи"

CITATION = (
    "Charnysh, Volha. Replication Data for: Explaining Out-Group Bias in Weak States: "
    "Religion and Legibility in the 1891/1892 Russian Famine. Harvard Dataverse, "
    f"V1 (2022), {DOI}. CC0 1.0"
)

# Так же называется событие famine_1891 в data/curated/state_events.json:
# по этому полю записи двух слоёв сводятся вместе.
WORK = "Голод 1891–1892 годов"

YEAR_FROM, YEAR_TO = 1891, 1892

FAMINE_1891 = LayerSpec(
    slug="famine_1891",
    title="Голод 1891–1892 годов: помощь и смертность по уездам",
    group="hardship",
    source="Harvard Dataverse, набор В. Чарныш (MIT) к статье о голоде 1891/92 годов",
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=1002,
    description=(
        "216 уездов 22 губерний: число людей на продовольственной помощи помесячно "
        "с июля 1891 по август 1892 года, ссуды семенами и хлебом в пудах, население, "
        "расстояние до железной дороги; отдельной таблицей — 24 губернии с долей "
        "населения на помощи и сверхсмертностью 1892 года; из панели 499 уездов "
        "50 губерний за 1885–1896 годы — холера 1892 года (343 уезда с умершими) и "
        "годы со сверхсмертностью не ниже полутора сигм (419 записей «уезд-год»). "
        "Даёт голоду уезд там, где вручную собранное событие в state_events знает "
        "только перечень семнадцати губерний: слои накладываются и сводятся по полю "
        "work. Записи территориальные, без точки: координаты набора — уездный город."
    ),
)


@dataclass(frozen=True)
class DatasetFile:
    """Файл набора: идентификатор в Dataverse, имя и размер по API 22.10.2026."""

    file_id: int
    name: str
    size: int


MAIN = DatasetFile(5590387, "DatasetMainMay2021.tab", 286961)
PROVINCES_FILE = DatasetFile(5590329, "Province_Mortality.tab", 3596)
PANEL = DatasetFile(5590302, "time-series-dataset.tab", 3681542)
SHP = DatasetFile(5590427, "DistrictMap.shp", 1673252)
DBF = DatasetFile(5590426, "DistrictMap.dbf", 338512)
SHX = DatasetFile(5590425, "DistrictMap.shx", 4628)
PRJ = DatasetFile(5590424, "DistrictMap.prj", 143)
README = DatasetFile(5592557, "READ_ME.rtf", 2207)

# Остальное в наборе — код статьи (.R, .do, .Rmd) и вспомогательные таблицы;
# сборщику они не нужны, и расхождения в них проверка не считает.
FILES = (MAIN, PROVINCES_FILE, PANEL, SHP, DBF, SHX, PRJ, README)


class FamineError(RuntimeError):
    """Набор не скачался или устроен не так, как ожидает разбор."""


# --- скачивание и сверка с перечнем ----------------------------------------

def fetch_manifest(*, timeout: int = 60) -> list[dict]:
    """Список файлов набора по API Dataverse: id, имя, размер."""
    raw = fetch_bytes(API_URL, error=FamineError, timeout=timeout)
    try:
        payload = json.loads(raw)
        files = payload["data"]["latestVersion"]["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FamineError(f"ответ API не разбирается: {exc}") from exc
    out = []
    for item in files:
        data = item.get("dataFile") or {}
        out.append({"id": data.get("id"), "name": item.get("label") or data.get("filename"),
                    "size": data.get("filesize")})
    return out


def check_manifest(manifest: Iterable[dict]) -> list[str]:
    """Расхождения между перечнем в коде и тем, что отдаёт API.

    Пустой список — всё сходится. Непустой — повод остановиться: набор
    переиздали, и прежде чем разбирать, надо понять, что изменилось.
    """
    by_id = {m.get("id"): m for m in manifest}
    problems = []
    for expected in FILES:
        got = by_id.get(expected.file_id)
        if got is None:
            problems.append(f"{expected.name}: файла с id {expected.file_id} в наборе нет")
            continue
        if got.get("name") != expected.name:
            problems.append(f"id {expected.file_id}: ожидалось имя {expected.name}, "
                            f"пришло {got.get('name')}")
        if got.get("size") != expected.size:
            problems.append(f"{expected.name}: ожидался размер {expected.size}, "
                            f"пришёл {got.get('size')}")
    return problems


def download(file: DatasetFile, *, timeout: int = 300) -> bytes:
    data = fetch_bytes(FILE_URL.format(file_id=file.file_id), error=FamineError,
                       timeout=timeout)
    if len(data) != file.size:
        raise FamineError(f"{file.name}: скачано {len(data)} байт, ожидалось {file.size}")
    return data


def cached(file: DatasetFile, cache_dir: Path) -> Path:
    """Файл из `data/raw/famine_1891`; чего нет — скачивается и остаётся там."""
    path = cache_dir / file.name
    if path.exists() and path.stat().st_size == file.size:
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(download(file))
    return path


# --- чтение таблиц ---------------------------------------------------------

def read_table(path: Path) -> list[dict]:
    """Ингестированный TSV Dataverse: строки как есть, значения строками."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return [dict(row) for row in reader]


def number(value) -> Optional[float]:
    """«61084», «45.1», «» — к числу или None; пустая ячейка — не ноль."""
    text = clean_text(value)
    if text is None or text.upper() == "NA":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def typed(value):
    """Значение колонки для `extra`: число — числом, остальное — строкой."""
    text = clean_text(value)
    if text is None or text.upper() == "NA":
        return None
    num = number(text)
    if num is None:
        return text
    return int(num) if num.is_integer() and "." not in text else num


def source_columns(row: dict) -> dict:
    """Все непустые колонки строки под исходными именами."""
    out = {}
    for key, value in row.items():
        if key is None:
            continue
        cell = typed(value)
        if cell is not None:
            out[key] = cell
    return out


# Без этих колонок разбор бессмысленен: если набор переиздадут с другими
# именами, сбор должен остановиться с перечнем того, что пришло.
REQUIRED_MAIN = ("ter_ID", "gub_name", "uezd_name", "OnReliefTot", "TotPop", "railDist",
                 "LoanSowBreadPud91", "LoanSowBreadPud92", "LoanFoodBreadPud",
                 "LoanFoodBreadPudState", "reliefmonths", "onrelief_max.x", "lat", "long")
REQUIRED_PROVINCES = ("Gubernia", "ExcessMortalityV1", "ExcessMortalityV2", "AidPctPop",
                      "HarvestPC")


def check_columns(header: Iterable[str], required: Iterable[str], what: str) -> None:
    names = list(header)
    missing = [c for c in required if c not in names]
    if missing:
        raise FamineError(f"{what}: нет обязательных колонок " + ", ".join(missing)
                          + "; пришли: " + ", ".join(names[:16]))


# --- месяцы кампании помощи ------------------------------------------------
# Четырнадцать месяцев с июля 1891 по август 1892 года — так же считает и
# статья. Порядковый номер в кортеже совпадает с авторским onset_mo.

MONTHS = (
    ("OnReliefJuly1891", 1891, 7), ("OnReliefAug1891", 1891, 8), ("OnReliefSep1891", 1891, 9),
    ("OnReliefOct1891", 1891, 10), ("OnReliefNov1891", 1891, 11), ("OnReliefDec1891", 1891, 12),
    ("OnReliefJan1892", 1892, 1), ("OnReliefFeb1892", 1892, 2), ("OnReliefMar1892", 1892, 3),
    ("OnReliefApr1892", 1892, 4), ("OnReliefMay1892", 1892, 5), ("OnReliefJune1892", 1892, 6),
    ("OnReliefJuly1892", 1892, 7), ("OnReliefAug1892", 1892, 8),
)
MONTH_COLUMNS = tuple(column for column, _, _ in MONTHS)

MONTH_NAMES = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
               "сентябрь", "октябрь", "ноябрь", "декабрь")
MONTH_NAMES_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                   "сентября", "октября", "ноября", "декабря")

# Авторский месяц начала — первый, когда на помощи больше этой доли населения
# (сноска 65 статьи). Нужен только сверке с onset_mo, период берётся по
# ненулевым месяцам.
ONSET_SHARE = 0.01


def month_label(index: int, genitive: bool = False) -> str:
    """Номер месяца кампании (1 — июль 1891) словами: «ноябрь 1891»."""
    _, year, month = MONTHS[index - 1]
    names = MONTH_NAMES_GEN if genitive else MONTH_NAMES
    return f"{names[month - 1]} {year}"


def monthly_relief(row: dict) -> Optional[list[float]]:
    """Четырнадцать чисел на помощи или None, если колонки пусты."""
    values = [number(row.get(column)) for column in MONTH_COLUMNS]
    if all(v is None for v in values):
        return None
    return [v or 0.0 for v in values]


def relief_period(values: Optional[list[float]]) -> Optional[tuple[int, int]]:
    """Первый и последний месяц с ненулевым числом на помощи (1 — июль 1891)."""
    if not values:
        return None
    nonzero = [i for i, v in enumerate(values, start=1) if v > 0]
    if not nonzero:
        return None
    return nonzero[0], nonzero[-1]


def onset_by_share(values: list[float], population: Optional[float]) -> Optional[int]:
    """Месяц, с которого на помощи больше 1% населения, — как считает статья."""
    if not population:
        return None
    for i, v in enumerate(values, start=1):
        if v / population > ONSET_SHARE:
            return i
    return None


def period_text(period: tuple[int, int]) -> str:
    first, last = period
    if first == last:
        return month_label(first)
    return f"{month_label(first)} — {month_label(last)}"


# --- категория и описание --------------------------------------------------

CATEGORY_RELIEF = "голод: продовольственная помощь выдавалась"
CATEGORY_NO_RELIEF = "голод: без продовольственной помощи"
CATEGORY_UNKNOWN = "голод: о помощи данных нет"


def relief_category(row: dict) -> str:
    total = number(row.get("OnReliefTot"))
    if total is None:
        return CATEGORY_UNKNOWN
    return CATEGORY_RELIEF if total > 0 else CATEGORY_NO_RELIEF


def _thousands(value: float) -> str:
    # Неразрывный пробел в разряде тысяч, как у итогов переписей: число не
    # должно рваться переносом строки в карточке.
    return f"{int(round(value)):,}".replace(",", " ")


def _percent(value: float) -> str:
    if 0 < value < 0.05:
        return "менее 0,1%"
    shown = f"{value:.0f}" if value >= 10 else f"{value:.1f}".replace(".", ",")
    return f"{shown}%"


def _people(value: float) -> str:
    return f"{_thousands(value)} {_plural(value, 'человек', 'человека', 'человек')}"


def _plural(value: float, one: str, few: str, many: str) -> str:
    """«1 пуд», «3 пуда», «12 пудов» — склонение по последним цифрам."""
    n = abs(int(round(value)))
    if 11 <= n % 100 <= 19:
        return many
    last = n % 10
    if last == 1:
        return one
    return few if 2 <= last <= 4 else many


def _puds(value: float) -> str:
    return f"{_thousands(value)} {_plural(value, 'пуд', 'пуда', 'пудов')}"


def _km(value: float) -> str:
    return "менее 1 км" if value < 1 else f"{value:.0f} км"


def loans_text(row: dict) -> Optional[str]:
    """Ссуды в пудах — только те, что в строке заполнены и не нули."""
    sow91 = number(row.get("LoanSowBreadPud91"))
    sow92 = number(row.get("LoanSowBreadPud92"))
    food = number(row.get("LoanFoodBreadPud"))
    state = number(row.get("LoanFoodBreadPudState"))
    parts = []
    sow = [f"{_puds(v)} ({year})" for v, year in ((sow91, 1891), (sow92, 1892)) if v]
    if sow:
        parts.append("семенные ссуды " + " и ".join(sow))
    if food:
        text = f"продовольственные ссуды {_puds(food)}"
        if state:
            text += f", из них от казны {_puds(state)}"
        parts.append(text)
    if not parts and food == 0 and sow91 == 0 and sow92 == 0:
        return "ссуд семенами и хлебом не выдано"
    return "; ".join(parts) if parts else None


def build_summary(row: dict) -> str:
    """Описание числами набора — без пересказа выводов статьи."""
    values = monthly_relief(row)
    period = relief_period(values)
    population = number(row.get("TotPop"))
    parts = []
    if period:
        peak = max(range(len(values)), key=lambda i: values[i])
        head = (f"На продовольственной помощи в пике ({month_label(peak + 1)}) "
                f"{_thousands(values[peak])} человек")
        share = number(row.get("onrelief_max.x"))
        if share is not None:
            head += f" — {_percent(share)} населения"
        months = number(row.get("reliefmonths"))
        first, last = period
        if months:
            head += (f"; помощь выдавалась {int(months)} "
                     f"{_plural(months, 'месяц', 'месяца', 'месяцев')}, "
                     f"с {month_label(first, genitive=True)} по {month_label(last)}")
        parts.append(head)
    elif values is not None:
        parts.append("Людей на продовольственной помощи в своде не учтено: нули за все "
                     "14 месяцев с июля 1891 по август 1892 года")
    else:
        parts.append("Помесячных сведений о числе людей на помощи в наборе нет: уезд "
                     "обследован, колонки помощи пусты")
    loans = loans_text(row)
    if loans:
        parts.append(loans[0].upper() + loans[1:])
    tail = []
    if population:
        tail.append(f"население {_thousands(population)} человек")
    rail = number(row.get("railDist"))
    if rail is not None:
        tail.append(f"до железной дороги {_km(rail)}")
    if tail:
        parts.append("; ".join(tail).capitalize())
    return ". ".join(parts) + "."


# --- названия по-русски ----------------------------------------------------
# Набор пишет губернии и уезды латиницей (транслитерация Библиотеки
# Конгресса). Словарь закрытый: имя, которого здесь нет, остаётся латиницей
# в place_text, а запись получает пометку district_unmatched.

PROVINCES = {
    # 22 губернии главной таблицы
    "Arkhangel'sk": "Архангельская губерния", "Kaluga": "Калужская губерния",
    "Kazan'": "Казанская губерния", "Khar'kov": "Харьковская губерния",
    "Kherson": "Херсонская губерния", "Kursk": "Курская губерния",
    "Nizhegorod": "Нижегородская губерния", "Olonets": "Олонецкая губерния",
    "Orel": "Орловская губерния", "Orenburg": "Оренбургская губерния",
    "Penza": "Пензенская губерния", "Perm'": "Пермская губерния",
    "Riazan'": "Рязанская губерния", "Samara": "Самарская губерния",
    "Saratov": "Саратовская губерния", "Simbirsk": "Симбирская губерния",
    "Tambov": "Тамбовская губерния", "Tavrida": "Таврическая губерния",
    "Tula": "Тульская губерния", "Ufa": "Уфимская губерния",
    "Viatka": "Вятская губерния", "Voronezh": "Воронежская губерния",
    # Остальные 28 из панели 1885–1896 годов (time-series-dataset.tab); в ней
    # Таврическая губерния написана иначе, чем в главной таблице.
    "Astrakhan'": "Астраханская губерния", "Bessarabia": "Бессарабская губерния",
    "Chernigov": "Черниговская губерния", "Don Cossacks": "Область Войска Донского",
    "Ekaterinoslav": "Екатеринославская губерния", "Estland": "Эстляндская губерния",
    "Grodno": "Гродненская губерния", "Iaroslavl'": "Ярославская губерния",
    "Kiev": "Киевская губерния", "Kostroma": "Костромская губерния",
    "Kovno": "Ковенская губерния", "Kurland": "Курляндская губерния",
    "Livland": "Лифляндская губерния", "Minsk": "Минская губерния",
    "Mogilev": "Могилёвская губерния", "Moscow": "Московская губерния",
    "Novgorod": "Новгородская губерния", "Podol'ia": "Подольская губерния",
    "Poltava": "Полтавская губерния", "Pskov": "Псковская губерния",
    "Smolensk": "Смоленская губерния", "St Petersburg": "Санкт-Петербургская губерния",
    "Taurida": "Таврическая губерния", "Tver'": "Тверская губерния",
    "Vil'na": "Виленская губерния", "Vitebsk": "Витебская губерния",
    "Vladimir": "Владимирская губерния", "Vologda": "Вологодская губерния",
    "Volyn'": "Волынская губерния",
}

# Уезд → прилагательное, как в справочнике границ RISTAT («Елецкий»).
# Слово «уезд» добавляется при сборке записи. Одно латинское написание
# всегда даёт одно прилагательное, губерния различает тёзок при сверке.
DISTRICTS = {
    # Архангельская
    "Arkhangel'sk": "Архангельский", "Kem'": "Кемский", "Kholmogory": "Холмогорский",
    "Mezen'": "Мезенский", "Onega": "Онежский", "Pinega": "Пинежский",
    "Shenkursk": "Шенкурский",
    # Калужская
    "Borovsk": "Боровский", "Kaluga": "Калужский", "Kozel'sk": "Козельский",
    "Likhvin": "Лихвинский", "Maloiaroslavets": "Малоярославецкий", "Medyn'": "Медынский",
    "Meshchovsk": "Мещовский", "Mosal'sk": "Мосальский", "Peremyshl'": "Перемышльский",
    "Tarusa": "Тарусский", "Zhizdra": "Жиздринский",
    # Казанская
    "Cheboksary": "Чебоксарский", "Chistopol'": "Чистопольский", "Iadrin": "Ядринский",
    "Kazan'": "Казанский", "Koz'modem'iansk": "Козьмодемьянский", "Laishev": "Лаишевский",
    "Mamadysh": "Мамадышский", "Spassk": "Спасский", "Sviiazhsk": "Свияжский",
    "Tetiushi": "Тетюшский", "Tsarevokokshaisk": "Царевококшайский",
    "Tsivil'sk": "Цивильский",
    # Харьковская
    "Akhtyrka": "Ахтырский", "Bogodukhov": "Богодуховский", "Izium": "Изюмский",
    "Khar'kov": "Харьковский", "Kupiansk": "Купянский", "Lebedin": "Лебединский",
    "Starobel'sk": "Старобельский", "Sumy": "Сумский", "Valkovsk": "Валковский",
    "Volchansk": "Волчанский", "Zmiev": "Змиевский",
    # Херсонская
    "Aleksandriia": "Александрийский", "Anan'ev": "Ананьевский",
    "Elisavetgrad": "Елисаветградский", "Kherson": "Херсонский", "Odessa": "Одесский",
    "Tiraspol'": "Тираспольский",
    # Курская
    "Belgorod": "Белгородский", "Dmitriev": "Дмитриевский", "Fatezh": "Фатежский",
    "Graivoron": "Грайворонский", "Korocha": "Корочанский", "Kursk": "Курский",
    "L'gov": "Льговский", "Novyi Oskol": "Новооскольский", "Oboian'": "Обоянский",
    "Putivl'": "Путивльский", "Ryl'sk": "Рыльский", "Shchigry": "Щигровский",
    "Staryi Oskol": "Старооскольский", "Sudzha": "Суджанский", "Tim": "Тимский",
    # Нижегородская
    "Ardatov": "Ардатовский", "Arzamas": "Арзамасский", "Balakhna": "Балахнинский",
    "Gorbatov": "Горбатовский", "Kniaginin": "Княгининский", "Lukoianov": "Лукояновский",
    "Makar'ev": "Макарьевский", "Nizhnii Novgorod": "Нижегородский",
    "Semenov": "Семёновский", "Sergach": "Сергачский", "Vasil'sursk": "Васильсурский",
    # Олонецкая
    "Kargopol'": "Каргопольский", "Lodeinoe Pole": "Лодейнопольский", "Olonets": "Олонецкий",
    "Petrozavodsk": "Петрозаводский", "Povenets": "Повенецкий", "Pudozh": "Пудожский",
    "Vytegra": "Вытегорский",
    # Орловская
    "Bolkhov": "Болховский", "Briansk": "Брянский", "Dmitrovsk": "Дмитровский",
    "Elets": "Елецкий", "Karachev": "Карачевский", "Kromy": "Кромской", "Livny": "Ливенский",
    "Maloarkhangel'sk": "Малоархангельский", "Mtsensk": "Мценский", "Orel": "Орловский",
    "Sevsk": "Севский", "Trubchevsk": "Трубчевский",
    # Оренбургская
    "Cheliabinsk": "Челябинский", "Orenburg": "Оренбургский", "Orsk": "Орский",
    "Troitsk": "Троицкий", "Verkhneural'sk": "Верхнеуральский",
    # Пензенская
    "Chembar": "Чембарский", "Gorodishche": "Городищенский", "Insar": "Инсарский",
    "Kerensk": "Керенский", "Krasnoslobodsk": "Краснослободский", "Mokshan": "Мокшанский",
    "Narovchat": "Наровчатский", "Nizhnii Lomov": "Нижнеломовский", "Penza": "Пензенский",
    "Saransk": "Саранский",
    # Пермская
    "Cherdyn'": "Чердынский", "Ekaterinburg": "Екатеринбургский", "Irbit": "Ирбитский",
    "Kamyshlov": "Камышловский", "Krasnoufimsk": "Красноуфимский", "Kungur": "Кунгурский",
    "Okhansk": "Оханский", "Osa": "Осинский", "Perm'": "Пермский", "Shadrinsk": "Шадринский",
    "Solikamsk": "Соликамский", "Verkhotur'e": "Верхотурский",
    # Рязанская
    "Dankov": "Данковский", "Egor'evsk": "Егорьевский", "Kasimov": "Касимовский",
    "Mikhailov": "Михайловский", "Pronsk": "Пронский", "Ranenburg": "Раненбургский",
    "Riazan'": "Рязанский", "Riazhsk": "Ряжский", "Sapozhok": "Сапожковский",
    "Skopin": "Скопинский", "Zaraisk": "Зарайский",
    # Самарская
    "Bugul'ma": "Бугульминский", "Buguruslan": "Бугурусланский", "Buzuluk": "Бузулукский",
    "Nikolaev": "Николаевский", "Novouzensk": "Новоузенский", "Samara": "Самарский",
    "Stavropol'": "Ставропольский",
    # Саратовская
    "Atkarsk": "Аткарский", "Balashov": "Балашовский", "Kamyshin": "Камышинский",
    "Khvalynsk": "Хвалынский", "Kuznetsk": "Кузнецкий", "Petrovsk": "Петровский",
    "Saratov": "Саратовский", "Serdobsk": "Сердобский", "Tsaritsyn": "Царицынский",
    "Vol'sk": "Вольский",
    # Симбирская
    "Alatyr'": "Алатырский", "Buinsk": "Буинский", "Korsun": "Корсунский",
    "Kurmysh": "Курмышский", "Sengilei": "Сенгилеевский", "Simbirsk": "Симбирский",
    "Syzran'": "Сызранский",
    # Тамбовская
    "Borisoglebsk": "Борисоглебский", "Elat'ma": "Елатомский", "Kirsanov": "Кирсановский",
    "Kozlov": "Козловский", "Lebedian'": "Лебедянский", "Lipetsk": "Липецкий",
    "Morshansk": "Моршанский", "Shatsk": "Шацкий", "Tambov": "Тамбовский",
    "Temnikov": "Темниковский", "Usman'": "Усманский",
    # Таврическая
    "Berdiansk": "Бердянский", "Dneprovsk": "Днепровский", "Evpatoriia": "Евпаторийский",
    "Feodosiia": "Феодосийский", "Ialta": "Ялтинский", "Melitopol'": "Мелитопольский",
    "Perekop": "Перекопский", "Simferopol'": "Симферопольский",
    # Тульская
    "Aleksin": "Алексинский", "Belev": "Белёвский", "Bogoroditsk": "Богородицкий",
    "Chern'": "Чернский", "Efremov": "Ефремовский", "Epifan'": "Епифанский",
    "Kashira": "Каширский", "Krapivna": "Крапивенский", "Novosil'": "Новосильский",
    "Odoev": "Одоевский", "Tula": "Тульский", "Venev": "Венёвский",
    # Уфимская
    "Belebei": "Белебеевский", "Birsk": "Бирский", "Menzelinsk": "Мензелинский",
    "Sterlitamak": "Стерлитамакский", "Zlatoust": "Златоустовский",
    # Вятская
    "Elabuga": "Елабужский", "Glazov": "Глазовский", "Iaransk": "Яранский",
    "Kotel'nich": "Котельнический", "Malmyzh": "Малмыжский", "Nolinsk": "Нолинский",
    "Orlov": "Орловский", "Sarapul": "Сарапульский", "Slobodskoi": "Слободской",
    "Urzhum": "Уржумский", "Viatka": "Вятский",
    # Воронежская
    "Biriuch": "Бирюченский", "Bobrov": "Бобровский", "Boguchar": "Богучарский",
    "Korotoiak": "Коротоякский", "Nizhnedevitsk": "Нижнедевицкий",
    "Novokhopersk": "Новохопёрский", "Ostrogozhsk": "Острогожский", "Pavlovsk": "Павловский",
    "Valuiki": "Валуйский", "Voronezh": "Воронежский", "Zadonsk": "Задонский",
    "Zemliansk": "Землянский",

    # --- уезды панели 1885–1896 годов (time-series-dataset.tab), которых нет
    # в главной таблице: ещё 28 губерний. Тёзки из разных губерний дают одно
    # прилагательное («Бельский» в Гродненской и Смоленской), и это не ошибка.
    # Архангельская
    "Pechora": "Печорский",
    # Астраханская
    "Astrakhan'": "Астраханский", "Chernyi Iar": "Черноярский", "Enotaevsk": "Енотаевский",
    "Krasnyi Iar": "Красноярский", "Tsarev": "Царевский",
    # Бессарабская
    "Akkerman": "Аккерманский", "Bel'tsy": "Белецкий", "Bendery": "Бендерский",
    "Ismail": "Измаильский", "Khotin": "Хотинский", "Kishinev": "Кишинёвский",
    "Orgeev": "Оргеевский", "Soroki": "Сорокский",
    # Черниговская
    "Borzna": "Борзнянский", "Chernigov": "Черниговский", "Glukhov": "Глуховский",
    "Gorodnia": "Городнянский", "Konotop": "Конотопский", "Kozelets": "Козелецкий",
    "Krolevets": "Кролевецкий", "Mglin": "Мглинский", "Nezhin": "Нежинский",
    "Novgorod-Seversk": "Новгород-Северский", "Novozybkov": "Новозыбковский",
    "Oster": "Остерский", "Sosnitsa": "Сосницкий", "Starodub": "Стародубский",
    "Surazh": "Суражский",
    # Екатеринославская
    "Aleksandrovsk": "Александровский", "Bakhmut": "Бахмутский",
    "Ekaterinoslav": "Екатеринославский", "Mariupol'": "Мариупольский",
    "Novomoskovsk": "Новомосковский", "Pavlograd": "Павлоградский",
    "Slavianoserbsk": "Славяносербский", "Verkhnedneprovsk": "Верхнеднепровский",
    # Эстляндская
    "Gapsal'": "Гапсальский", "Revel'": "Ревельский", "Veisenshtein": "Вейсенштейнский",
    "Vezenberg": "Везенбергский",
    # Гродненская
    "Bel'sk": "Бельский", "Belostok": "Белостокский", "Brest-Litovsk": "Брестский",
    "Grodno": "Гродненский", "Kobrin": "Кобринский", "Pruzhany": "Пружанский",
    "Slonim": "Слонимский", "Sokolka": "Сокольский", "Volkovysk": "Волковысский",
    # Ярославская
    "Danilov": "Даниловский", "Iaroslavl'": "Ярославский", "Liubim": "Любимский",
    "Mologa": "Мологский", "Myshkin": "Мышкинский", "Poshekhon'e": "Пошехонский",
    "Romanovo-Borisoglebsk": "Романово-Борисоглебский", "Rostov": "Ростовский",
    "Rybinsk": "Рыбинский", "Uglich": "Угличский",
    # Киевская
    "Berdichev": "Бердичевский", "Cherkassy": "Черкасский", "Chigirin": "Чигиринский",
    "Kanev": "Каневский", "Kiev": "Киевский", "Lipovets": "Липовецкий",
    "Radomysl'": "Радомысльский", "Skvira": "Сквирский", "Tarashcha": "Таращанский",
    "Uman'": "Уманский", "Vasil'kov": "Васильковский", "Zvenigorodka": "Звенигородский",
    # Костромская
    "Buisk": "Буйский", "Chukhloma": "Чухломский", "Galich": "Галичский",
    "Iur'evets": "Юрьевецкий", "Kineshma": "Кинешемский", "Kologriv": "Кологривский",
    "Kostroma": "Костромской", "Nerekhta": "Нерехтский", "Soligalich": "Солигаличский",
    "Varnavin": "Варнавинский", "Vetluga": "Ветлужский",
    # Ковенская
    "Kovno": "Ковенский", "Novoaleksandrovsk": "Новоалександровский",
    "Ponevezh": "Поневежский", "Rossieny": "Россиенский", "Shavli": "Шавельский",
    "Tel'shi": "Тельшевский", "Vil'komir": "Вилькомирский",
    # Курляндская
    "Bausk": "Бауский", "Doblensk": "Добленский", "Fridrikhshtadt": "Фридрихштадтский",
    "Gazenpot": "Газенпотский", "Gol'dingen": "Гольдингенский", "Grobin": "Гробинский",
    "Illukst": "Иллукстский", "Tal'sen": "Тальсенский", "Tukkum": "Туккумский",
    "Vindava": "Виндавский",
    # Лифляндская
    "Ezel'": "Эзельский", "Fellin": "Феллинский", "Iur'ev": "Юрьевский",
    "Pernov": "Перновский", "Riga": "Рижский", "Valk": "Валкский", "Venden": "Венденский",
    "Verro": "Верроский", "Vol'mar": "Вольмарский",
    # Минская
    "Bobruisk": "Бобруйский", "Borisov": "Борисовский", "Igumen": "Игуменский",
    "Minsk": "Минский", "Mozyr'": "Мозырский", "Novogrudok": "Новогрудский",
    "Pinsk": "Пинский", "Rechitsa": "Речицкий", "Slutsk": "Слуцкий",
    # Могилёвская
    "Bykhov": "Быховский", "Chausy": "Чаусский", "Chernikov": "Чериковский",
    "Gomel'": "Гомельский", "Gorki": "Горецкий", "Klimovichi": "Климовичский",
    "Mogilev": "Могилёвский", "Mstislavl'": "Мстиславский", "Orsha": "Оршанский",
    "Rogachev": "Рогачёвский", "Senno": "Сенненский",
    # Московская
    "Bogorodsk": "Богородский", "Bronnitsy": "Бронницкий", "Dmitrov": "Дмитровский",
    "Klin": "Клинский", "Kolomna": "Коломенский", "Moscow": "Московский",
    "Mozhaisk": "Можайский", "Podol'sk": "Подольский", "Ruza": "Рузский",
    "Serpukhov": "Серпуховский", "Vereia": "Верейский", "Volokolamsk": "Волоколамский",
    "Zvenigorod": "Звенигородский",
    # Новгородская
    "Belozersk": "Белозерский", "Borovichi": "Боровичский", "Cherepovets": "Череповецкий",
    "Dem'iansk": "Демянский", "Kirillov": "Кирилловский", "Kresttsy": "Крестецкий",
    "Novgorod": "Новгородский", "Staraia Russa": "Старорусский", "Tikhvin": "Тихвинский",
    "Ustiuzhna": "Устюженский", "Valdai": "Валдайский",
    # Подольская
    "Balta": "Балтский", "Bratslav": "Брацлавский", "Gaisin": "Гайсинский",
    "Iampol'": "Ямпольский", "Kamenets-Podol'skii": "Каменец-Подольский",
    "Letichev": "Летичевский", "Litin": "Литинский", "Mogilev-na-Dnestre": "Могилёвский",
    "Ol'gopol'": "Ольгопольский", "Proskurov": "Проскуровский", "Ushitsa": "Ушицкий",
    "Vinnitsa": "Винницкий",
    # Полтавская
    "Gadiach": "Гадячский", "Khorol'": "Хорольский", "Kobeliaki": "Кобелякский",
    "Konstantinograd": "Константиноградский", "Kremenchug": "Кременчугский",
    "Lokhvitsa": "Лохвицкий", "Lubny": "Лубенский", "Mirgorod": "Миргородский",
    "Pereiaslav": "Переяславский", "Piriatin": "Пирятинский", "Poltava": "Полтавский",
    "Priluki": "Прилукский", "Romny": "Роменский", "Zen'kov": "Зеньковский",
    "Zolotonosha": "Золотоношский",
    # Псковская
    "Kholm": "Холмский", "Novorzhev": "Новоржевский", "Opochka": "Опочецкий",
    "Ostrov": "Островский", "Porkhov": "Порховский", "Pskov": "Псковский",
    "Toropets": "Торопецкий", "Velikie Luki": "Великолукский",
    # Смоленская
    "Dorogobuzh": "Дорогобужский", "Dukhovshchina": "Духовщинский",
    "El'ninsk": "Ельнинский", "Gzhatsk": "Гжатский", "Iukhnov": "Юхновский",
    "Krasninsk": "Краснинский", "Porech'e": "Поречский", "Roslavl'": "Рославльский",
    "Smolensk": "Смоленский", "Sychevka": "Сычёвский", "Viaz'ma": "Вяземский",
    # Санкт-Петербургская
    "Gdov": "Гдовский", "Iamburg": "Ямбургский", "Luga": "Лужский",
    "Novaia Ladoga": "Новоладожский", "Petergof": "Петергофский",
    "Shlissel'burg": "Шлиссельбургский", "St Petersburg": "Санкт-Петербургский",
    "Tsarskoe Selo": "Царскосельский",
    # Тверская
    "Bezhetsk": "Бежецкий", "Kaliazin": "Калязинский", "Kashin": "Кашинский",
    "Korcheva": "Корчевский", "Novotorzhok": "Новоторжский", "Ostashkov": "Осташковский",
    "Rzhev": "Ржевский", "Staritsa": "Старицкий", "Tver'": "Тверской",
    "Ves'egonsk": "Весьегонский", "Vyshnii Volochek": "Вышневолоцкий",
    "Zubtsov": "Зубцовский",
    # Уфимская
    "Ufa": "Уфимский",
    # Виленская
    "Disna": "Дисненский", "Lida": "Лидский", "Oshmiany": "Ошмянский",
    "Sventsiany": "Свенцянский", "Troki": "Трокский", "Vil'na": "Виленский",
    "Vileika": "Вилейский",
    # Витебская
    "Drissa": "Дриссенский", "Dvinsk": "Двинский", "Gorodok": "Городокский",
    "Lepel'": "Лепельский", "Liutsyn": "Люцинский", "Nevel'": "Невельский",
    "Polotsk": "Полоцкий", "Rezhitsa": "Режицкий", "Sebezh": "Себежский",
    "Velizh": "Велижский", "Vitebsk": "Витебский",
    # Владимирская
    "Aleksandrov": "Александровский", "Gorokhovets": "Гороховецкий", "Kovrov": "Ковровский",
    "Melenki": "Меленковский", "Murom": "Муромский", "Pereslavl'": "Переславский",
    "Pokrov": "Покровский", "Shuia": "Шуйский", "Sudogda": "Судогодский",
    "Suzdal'": "Суздальский", "Viazniki": "Вязниковский", "Vladimir": "Владимирский",
    # Вологодская
    "Griazovets": "Грязовецкий", "Iarensk": "Яренский", "Kadnikov": "Кадниковский",
    "Nikol'sk": "Никольский", "Sol'vychegodsk": "Сольвычегодский", "Tot'ma": "Тотемский",
    "Ust'sysol'sk": "Усть-Сысольский", "Vel'sk": "Вельский",
    "Velikii Ustiug": "Великоустюгский", "Vologda": "Вологодский",
    # Волынская
    "Dubno": "Дубенский", "Kovel'": "Ковельский", "Kremenets": "Кременецкий",
    "Lutsk": "Луцкий", "Novograd-Volynsk": "Новоград-Волынский", "Ostrog": "Острожский",
    "Ovruch": "Овручский", "Rovno": "Ровенский", "Starokonstantinov": "Староконстантиновский",
    "Vladimir-Volynsk": "Владимир-Волынский", "Zaslavl'": "Заславский",
    "Zhitomir": "Житомирский",
}

# Названия, которые зависят от губернии: Область Войска Донского делилась
# не на уезды, а на округа, и панель называет округ по его станице или
# городу — «Novocherkassk» это Черкасский округ. «Rostov» при этом есть и в
# Ярославской губернии, поэтому ключ здесь — губерния и уезд вместе.
# Значение с единицей внутри берётся как есть, без добавления «уезд».
DISTRICTS_BY_PROVINCE = {
    ("Don Cossacks", "Don-1"): "Донской 1-й округ",
    ("Don Cossacks", "Don-2"): "Донской 2-й округ",
    ("Don Cossacks", "Donetsk"): "Донецкий округ",
    ("Don Cossacks", "Khopersk"): "Хопёрский округ",
    ("Don Cossacks", "Novocherkassk"): "Черкасский округ",
    ("Don Cossacks", "Rostov"): "Ростовский округ",
    ("Don Cossacks", "Taganrog"): "Таганрогский округ",
    ("Don Cossacks", "Ust'-Medveditskaia"): "Усть-Медведицкий округ",
}

UNIT_WORDS = ("уезд", "округ", "отдел")

# Где справочник RISTAT пишет единицу не так, как она называлась в 1890-е:
# сверка идёт по его написанию, в запись идёт наше. Первые строки — чистые
# написания; Петроградский и Изяславский — названия 1914 и 1910 годов,
# которые справочник 1897 года приписал уездам задним числом.
RISTAT_DISTRICT_SPELLING = {
    "Малоярославецкий": "Малоярославский",
    "Мещовский": "Мещонский",
    "Курмышский": "Курмыжский",
    "Верхнеднепровский": "Верхне-днепровский",
    "Сокольский": "Соколский",
    "Волковысский": "Волковыский",
    "Мологский": "Моложский",
    "Великолукский": "Великолуцкий",
    "Рославльский": "Рославский",
    "Великоустюгский": "Устюжский",
    "Новоград-Волынский": "Новоградволынский",
    "Усть-Медведицкий": "Усть-Медведковский",
    "Санкт-Петербургский": "Петроградский",
    "Заславский": "Изяславский",
}
# То же для губерний: у RISTAT Донская область названа землёй.
RISTAT_PROVINCE_SPELLING = {
    "Область Войска Донского": "Земля войска Донского",
}


def province_name(latin) -> Optional[str]:
    text = clean_text(latin)
    return PROVINCES.get(text) if text else None


def district_name(latin, province_latin=None) -> Optional[str]:
    """«Elets» → «Елецкий уезд», («Don Cossacks», «Rostov») → «Ростовский округ».

    Неизвестное написание — None: запись останется с пометкой, а не с
    выдуманным названием.
    """
    text = clean_text(latin)
    if not text:
        return None
    gub = clean_text(province_latin)
    name = DISTRICTS_BY_PROVINCE.get((gub, text)) if gub else None
    if name is None:
        name = DISTRICTS.get(text)
    if name is None:
        return None
    return name if name.endswith(UNIT_WORDS) else f"{name} уезд"


def _genitive(province: str) -> str:
    """«Орловская губерния» → «Орловской губернии» для заголовка."""
    words = province.split()
    if len(words) == 2 and words[1] == "губерния" and words[0].endswith(("ая", "яя")):
        return words[0][:-2] + ("ой" if words[0].endswith("ая") else "ей") + " губернии"
    if province.startswith("Область "):
        return "Области " + province[len("Область "):]
    return province


# --- сверка с границами 1897 года ------------------------------------------

class DistrictIndex:
    """Уезды RISTAT 1897 года по ключу (губерния, уезд) → RISTAT_ID.

    Строится из `data/out/boundaries/districts_1897.geojson`; ключи считает
    `histctx.geo.region_key`, поэтому «Елецкий уезд» и «Елецкий» — одно и то
    же, а «Слободской» и «Слободский» — тоже.
    """

    def __init__(self, feats: Iterable[dict]) -> None:
        self.by_key: dict[tuple, str] = {}
        self.names: dict[str, list[str]] = {}
        for feature in feats:
            props = feature.get("properties") or {}
            province, name = props.get("prov_RU"), props.get("Name_RU")
            if not province or not name:
                continue
            key = (region_key(province), region_key(name))
            self.by_key.setdefault(key, str(props.get("RISTAT_ID") or ""))
            self.names.setdefault(province, []).append(name)

    @classmethod
    def load(cls, path: Path) -> "DistrictIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload.get("features") or [])

    def __len__(self) -> int:
        return len(self.by_key)

    def find(self, province: Optional[str], district: Optional[str]) -> Optional[str]:
        """RISTAT_ID уезда внутри своей губернии или None."""
        if not province or not district:
            return None
        adjective = district
        for unit in UNIT_WORDS:
            adjective = adjective.replace(f" {unit}", "")
        candidates = [adjective, RISTAT_DISTRICT_SPELLING.get(adjective)]
        provinces = [province, RISTAT_PROVINCE_SPELLING.get(province)]
        for prov in filter(None, provinces):
            for name in filter(None, candidates):
                hit = self.by_key.get((region_key(prov), region_key(name)))
                if hit:
                    return hit
        return None

    def candidates(self, province: Optional[str]) -> list[str]:
        """Уезды губернии по справочнику — чтобы несовпавший было с чем сравнить."""
        for prov in filter(None, [province, RISTAT_PROVINCE_SPELLING.get(province or "")]):
            for known, names in self.names.items():
                if region_key(known) == region_key(prov):
                    return sorted(names)
        return []


class ProvinceIndex:
    """Губернии 1897 года из `provinces_1897.geojson`: ключ → название prov_RU."""

    def __init__(self, names: Iterable[str]) -> None:
        self.by_key = {region_key(n): n for n in names if n}

    @classmethod
    def load(cls, path: Path) -> "ProvinceIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls((f.get("properties") or {}).get("prov_RU")
                   for f in payload.get("features") or [])

    def find(self, province: Optional[str]) -> Optional[str]:
        for name in filter(None, [province, RISTAT_PROVINCE_SPELLING.get(province or "")]):
            hit = self.by_key.get(region_key(name))
            if hit:
                return hit
        return None


# --- место записи: уезд внутри губернии -------------------------------------

@dataclass(frozen=True)
class Place:
    """Куда относится запись: по-русски, с парой в RISTAT и пометкой."""

    province: Optional[str]
    district: Optional[str]
    place_text: Optional[str]
    head: str                  # «Елецкий уезд Орловской губернии» для заголовка
    ristat_id: Optional[str]
    confidence: str


def locate(gub_latin, uezd_latin, index: Optional[DistrictIndex]) -> Place:
    """Губерния и уезд из латиницы набора, сверенные со справочником границ.

    Уезд, которого словарь не знает, остаётся в `place_text` латиницей с
    пометкой, а запись получает `district_unmatched` — так же, как уезд,
    которому не нашлось пары среди уездов 1897 года.
    """
    province = province_name(gub_latin)
    district = district_name(uezd_latin, gub_latin)
    uezd_raw = clean_text(uezd_latin)
    gub_raw = clean_text(gub_latin)
    ristat_id = index.find(province, district) if index is not None else None
    confidence = "ok" if (district and (index is None or ristat_id)) else "district_unmatched"
    place_district = district or (f"{uezd_raw} (уезд, написание набора)" if uezd_raw else None)
    place_province = province or gub_raw
    place_text = ", ".join(p for p in (place_district, place_province) if p) or None
    if district and province:
        head = f"{district} {_genitive(province)}"
    else:
        head = place_text or "уезд без названия"
    return Place(province, district, place_text, head, ristat_id, confidence)


def _record_extra(row: dict, place: Place) -> dict:
    extra = {"famine": source_columns(row), "citation": CITATION}
    if place.ristat_id:
        extra["RISTAT_ID"] = place.ristat_id
    return extra


# --- записи главной таблицы -------------------------------------------------

def row_to_record(row: dict, index: Optional[DistrictIndex] = None) -> ContextRecord:
    """Одна строка главной таблицы → запись схемы с охватом «уезд в губернии».

    Точки у записи нет намеренно: `lat`/`long` набора — уездный город, и
    поставить на него голод значило бы соврать о месте. Координаты остаются
    в `extra` под исходными именами колонок.
    """
    place = locate(row.get("gub_name"), row.get("uezd_name"), index)
    values = monthly_relief(row)
    period = relief_period(values)
    if period:
        precision, period_raw = "month", period_text(period)
    else:
        precision, period_raw = "year", f"{YEAR_FROM}–{YEAR_TO}"

    return FAMINE_1891.new_record(
        title=f"{place.head}: голод 1891–1892 годов",
        category=relief_category(row),
        scope=SCOPE_REGION,
        place_text=place.place_text,
        region=place.province,
        regions=[place.province] if place.province else [],
        district=place.district,
        year_from=YEAR_FROM,
        year_to=YEAR_TO,
        date_precision=precision,
        period_raw=period_raw,
        work=WORK,
        summary=build_summary(row),
        url=DATASET_URL,
        source_id=clean_text(row.get("ter_ID")),
        confidence=place.confidence,
        extra=_record_extra(row, place),
    )


def rows_to_records(rows: Iterable[dict],
                    index: Optional[DistrictIndex] = None) -> list[ContextRecord]:
    return [row_to_record(row, index) for row in rows]


# --- губернские итоги -------------------------------------------------------
# Названия в Province_Mortality.tab прошли через latin-1 и выглядят как
# «Ð¡Ð°Ñ€Ð°Ñ‚Ð¾Ð²Ñ\x81ÐºaÑ\x8f»; обратный проход восстанавливает «Саратовскaя» —
# с латинской «a» внутри, которую набор принёс сам.

_LOOKALIKES = str.maketrans({
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О",
    "P": "Р", "T": "Т", "X": "Х",
})
_RE_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")

# Единственное название не в форме прилагательного.
PROVINCE_FORMS = {"Астрахань": "Астраханская губерния"}

CATEGORY_PROVINCE = "голод: итоги по губернии"


def decode_province(raw) -> Optional[str]:
    """Снимает двойную кодировку и латинские буквы внутри кириллицы.

    Чистить строку до раскодирования нельзя: в испорченном виде внутри неё
    стоят NEL (U+0085) и неразрывный пробел — это байты кириллицы, а не
    пробелы, и `clean_text` их бы вырезал.
    """
    if raw is None:
        return None
    text = str(raw)
    try:
        text = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    text = clean_text(text)
    if text and _RE_CYRILLIC.search(text):
        text = text.translate(_LOOKALIKES)
    return text


def escaped(raw) -> Optional[str]:
    """«Ð¡Ð°Ñ\\x80…» — исходная строка в ASCII, чтобы её можно было прочитать и
    сверить, не ломая построчную выгрузку."""
    if raw is None:
        return None
    return str(raw).encode("unicode_escape").decode("ascii")


def province_from_table(raw) -> Optional[str]:
    """«Саратовскaя» → «Саратовская губерния», «Астрахань» → «Астраханская губерния»."""
    text = decode_province(raw)
    if text is None:
        return None
    if text in PROVINCE_FORMS:
        return PROVINCE_FORMS[text]
    if text.endswith(("ая", "яя")):
        return f"{text} губерния"
    return text


def province_summary(row: dict) -> str:
    aid = number(row.get("AidPctPop"))
    parts = []
    if aid is None:
        parts.append("Доля населения на продовольственной помощи в наборе не указана")
    elif aid == 0:
        parts.append("На продовольственной помощи населения не числилось (0%)")
    else:
        parts.append(f"На продовольственной помощи {_percent(aid)} населения губернии")
    parts.append("сверхсмертность 1892 года по двум оценкам статьи и сбор на душу лежат "
                 "в исходных колонках записи (ExcessMortalityV1, ExcessMortalityV2, "
                 "HarvestPC) — подпись к рисунку статьи их единицу не называет, и в текст "
                 "они не переводятся")
    return "; ".join(parts) + "."


def province_records(rows: Iterable[dict],
                     index: Optional[ProvinceIndex] = None) -> list[ContextRecord]:
    """24 записи «голод: итоги по губернии», в том числе по губерниям, которых
    нет в главной таблице (Астраханская, Тобольская)."""
    out = []
    for row in rows:
        raw = row.get("Gubernia")
        province = province_from_table(raw)
        if province is None:
            continue
        known = index.find(province) if index is not None else province
        confidence = "ok" if known else "region_unmatched"
        columns = source_columns(row)
        # Испорченное название в исходных колонках заменяется восстановленным,
        # а то, что пришло из файла, лежит рядом — в виде escape-записи:
        # внутри него управляющие знаки (NEL, C1), которым в построчном JSON
        # не место, а показать, что именно пришло, нужно.
        columns["Gubernia"] = decode_province(raw)
        extra = {"famine": columns, "province_raw": escaped(raw), "citation": CITATION}
        out.append(FAMINE_1891.new_record(
            title=f"{province}: итоги голода 1891–1892 годов",
            category=CATEGORY_PROVINCE,
            scope=SCOPE_REGION,
            place_text=province,
            region=province,
            regions=[province],
            year_from=YEAR_FROM,
            year_to=YEAR_TO,
            date_precision="year",
            period_raw=f"{YEAR_FROM}–{YEAR_TO}",
            work=WORK,
            summary=province_summary(row),
            url=DATASET_URL,
            source_id=f"province:{province}",
            confidence=confidence,
            extra=extra,
        ))
    return out


# --- панель 1885–1896 годов: холера и сверхсмертность по годам ---------------
# Та же панель, по которой статья считает сверхсмертность: рождения и смерти
# по уездам из ежегодников ЦСК МВД, переведённые в коэффициенты на тысячу
# населения. Из неё берутся два факта. Холера 1892 года — единственный год,
# за который колонки заполнены, — даёт слою эпидемий то, чего в Викиданных
# нет вовсе. Сверхсмертность `est_em = est_cdr − cdr_pred` — смертей на тысячу
# сверх ожидаемого — становится записью «уезд-год» по правилу слоя погоды:
# отклонение не меньше полутора сигм, сигма по всей панели.

REQUIRED_PANEL = ("ter_id", "year", "nameg", "name", "cholera_cases", "cholera_deaths",
                  "est_cdr", "cdr_pred", "est_em", "deaths_m", "deaths_f", "births_m",
                  "births_f")

CATEGORY_CHOLERA = "холера 1892 года"
CATEGORY_EXCESS = "сверхсмертность за год"

SIGMA_FACTOR = 1.5
# Поле work — только у записей панели за годы голода: 1891 — неурожай,
# 1892–1893 — годы, которые статья считает голодными (`famine2`).
# Сверхсмертность 1885 года в Лифляндии сводить с голодом 1891 года нельзя.
WORK_YEARS = (1891, 1893)
# Тождество est_em = est_cdr − cdr_pred сходится в наборе до 1e-8; если
# оно разойдётся, единицу «на тысячу» писать в текст нельзя — сбор встанет.
IDENTITY_TOLERANCE = 1e-6


def check_identity(rows: Iterable[dict],
                   tolerance: float = IDENTITY_TOLERANCE) -> tuple[int, float]:
    """Сколько строк проверено и наибольшее расхождение est_em с est_cdr − cdr_pred."""
    checked, worst = 0, 0.0
    for row in rows:
        em, cdr, pred = (number(row.get(k)) for k in ("est_em", "est_cdr", "cdr_pred"))
        if em is None or cdr is None or pred is None:
            continue
        checked += 1
        worst = max(worst, abs(em - (cdr - pred)))
    if checked and worst > tolerance:
        raise FamineError(f"est_em не равно est_cdr − cdr_pred: расхождение до {worst:g} "
                          f"на {checked} строках — единицу «на тысячу» писать нельзя")
    return checked, worst


def excess_threshold(values: Iterable[Optional[float]],
                     factor: float = SIGMA_FACTOR) -> tuple[float, float]:
    """(σ, порог): выборочное стандартное отклонение est_em по всей панели."""
    data = [v for v in values if v is not None]
    if len(data) < 2:
        raise FamineError("панель пуста: порог сверхсмертности считать не по чему")
    sigma = statistics.stdev(data)
    return sigma, factor * sigma


def _year(row: dict) -> Optional[int]:
    year = number(row.get("year"))
    return int(year) if year is not None else None


def _total(row: dict, male: str, female: str) -> Optional[float]:
    m, f = number(row.get(male)), number(row.get(female))
    return m + f if m is not None and f is not None else None


def _per_mille(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _work_for(year: Optional[int]) -> Optional[str]:
    return WORK if year is not None and WORK_YEARS[0] <= year <= WORK_YEARS[1] else None


def cholera_summary(row: dict) -> str:
    cases = number(row.get("cholera_cases"))
    deaths = number(row.get("cholera_deaths")) or 0.0
    parts = []
    if cases:
        parts.append(f"заболели {_thousands(cases)}")
    parts.append(f"умерли {_people(deaths)}")
    text = "Холера 1892 года: " + ", ".join(parts)
    total = _total(row, "deaths_m", "deaths_f")
    if total and deaths:
        text += (f" — {_percent(100.0 * deaths / total)} всех смертей в уезде за год "
                 f"({_thousands(total)})")
    return text + "."


def cholera_records(rows: Iterable[dict],
                    index: Optional[DistrictIndex] = None) -> list[ContextRecord]:
    """Запись на уезд с умершими от холеры > 0; уезды с нулём не берутся."""
    out = []
    for row in rows:
        deaths = number(row.get("cholera_deaths"))
        year = _year(row)
        if not deaths or deaths <= 0 or year is None:
            continue
        place = locate(row.get("nameg"), row.get("name"), index)
        out.append(FAMINE_1891.new_record(
            title=f"{place.head}: холера {year} года",
            category=CATEGORY_CHOLERA,
            scope=SCOPE_REGION,
            place_text=place.place_text,
            region=place.province,
            regions=[place.province] if place.province else [],
            district=place.district,
            year_from=year,
            year_to=year,
            date_precision="year",
            period_raw=str(year),
            work=_work_for(year),
            summary=cholera_summary(row),
            url=DATASET_URL,
            source_id=f"{clean_text(row.get('ter_id'))}:{year}:cholera",
            confidence=place.confidence,
            extra=_record_extra(row, place),
        ))
    return out


def excess_summary(row: dict, threshold: float) -> str:
    year = _year(row)
    cdr, pred, em = (number(row.get(k)) for k in ("est_cdr", "cdr_pred", "est_em"))
    text = (f"Смертность {year} года — {_per_mille(cdr)} на тысячу населения при "
            f"ожидаемых {_per_mille(pred)}: сверх обычного {_per_mille(em)} на тысячу "
            f"(порог слоя {_per_mille(threshold)})")
    deaths = _total(row, "deaths_m", "deaths_f")
    births = _total(row, "births_m", "births_f")
    tail = []
    if deaths is not None:
        tail.append(f"умерло {_people(deaths)}")
    if births is not None:
        tail.append(f"родилось {_thousands(births)}")
    cholera = number(row.get("cholera_deaths"))
    if cholera:
        tail.append(f"от холеры умерло {_thousands(cholera)}")
    if tail:
        text += ". " + "; ".join(tail).capitalize()
    return text + "."


def excess_records(rows: Iterable[dict], index: Optional[DistrictIndex],
                   threshold: float) -> list[ContextRecord]:
    """Запись «уезд-год» там, где сверхсмертность не ниже порога."""
    out = []
    for row in rows:
        em = number(row.get("est_em"))
        year = _year(row)
        if em is None or em < threshold or year is None:
            continue
        place = locate(row.get("nameg"), row.get("name"), index)
        extra = _record_extra(row, place)
        extra["excess_threshold"] = {"sigma_factor": SIGMA_FACTOR, "value": round(threshold, 4)}
        out.append(FAMINE_1891.new_record(
            title=f"{place.head}: сверхсмертность {year} года",
            category=CATEGORY_EXCESS,
            scope=SCOPE_REGION,
            place_text=place.place_text,
            region=place.province,
            regions=[place.province] if place.province else [],
            district=place.district,
            year_from=year,
            year_to=year,
            date_precision="year",
            period_raw=str(year),
            work=_work_for(year),
            summary=excess_summary(row, threshold),
            url=DATASET_URL,
            source_id=f"{clean_text(row.get('ter_id'))}:{year}:excess",
            confidence=place.confidence,
            extra=extra,
        ))
    return out


def panel_records(rows: Iterable[dict],
                  index: Optional[DistrictIndex] = None) -> tuple[list, list, dict]:
    """Холера, сверхсмертность и то, на чём держится порог.

    Тождество проверяется до того, как единица попадёт в текст; сигма
    считается по всей панели, а не по строкам, прошедшим порог.
    """
    rows = list(rows)
    checked, worst = check_identity(rows)
    sigma, threshold = excess_threshold(number(r.get("est_em")) for r in rows)
    stats = {"identity_rows": checked, "identity_max_diff": worst,
             "sigma": sigma, "threshold": threshold}
    return cholera_records(rows, index), excess_records(rows, index, threshold), stats


# --- полигоны уездов: подложка, а не слой -----------------------------------

def load_shapes(cache_dir: Path) -> list[dict]:
    """566 полигонов DistrictMap.shp с таблицей атрибутов."""
    shp = cached(SHP, cache_dir).read_bytes()
    dbf = cached(DBF, cache_dir).read_bytes()
    try:
        return features(read_shapes(shp), read_dbf(dbf, "utf-8"))
    except ShapefileError as exc:
        raise FamineError(f"DistrictMap: {exc}") from exc


def boundary_properties(record: ContextRecord) -> dict:
    """Что остаётся у полигона: кто это, пара в RISTAT и главные числа помощи."""
    columns = record.extra.get("famine", {})
    props = {
        "ter_id": record.source_id,
        "uezd": record.district,
        "province": record.region,
        "RISTAT_ID": record.extra.get("RISTAT_ID"),
        "category": record.category,
        "relief_share_max_pct": columns.get("onrelief_max.x"),
        "relief_months": columns.get("reliefmonths"),
        "relief_period": record.period_raw if record.date_precision == "month" else None,
        "loan_sow_pud_1891": columns.get("LoanSowBreadPud91"),
        "loan_sow_pud_1892": columns.get("LoanSowBreadPud92"),
        "loan_food_pud": columns.get("LoanFoodBreadPud"),
        "loan_food_pud_state": columns.get("LoanFoodBreadPudState"),
        "population": columns.get("TotPop"),
    }
    return {k: v for k, v in props.items() if v is not None}


def boundaries_geojson(feats: Iterable[dict], records: Iterable[ContextRecord]) -> dict:
    """FeatureCollection уездов главной таблицы: полигон из шейпфайла, свойства
    из записи. Уезды шейпфайла, которых нет в таблице, не берутся: у них нет
    ни чисел, ни русского названия."""
    by_ter = {r.source_id: r for r in records if r.source_id}
    out = []
    for feature in feats:
        ter_id = clean_text((feature.get("properties") or {}).get("ter_id"))
        record = by_ter.get(ter_id)
        if record is None:
            continue
        out.append({"type": "Feature", "id": record.uid,
                    "geometry": feature["geometry"],
                    "properties": boundary_properties(record)})
    return feature_collection(
        "famine_1891_districts", out,
        license=LICENSE, source=FAMINE_1891.source, citation=CITATION, url=DATASET_URL,
        extra={"period": f"{YEAR_FROM}–{YEAR_TO}"},
    )
