"""Сожжённые деревни Белоруссии 1941–1944 годов: набор Ю. Жукова и база НАРБ.

Зачем этот слой. Запись о рождении в деревне Витебской области, а после
1943 года — ни одной: книги не продолжены, семья не найдена в переписи
1959 года. Ответ часто в том, что деревни больше нет — её сожгли при
карательной операции, и вместе с ней сгорели или ушли жители. Слой ставит
такую деревню на карту с месяцем уничтожения, числом сожжённых дворов и
погибших.

Основа — набор к статье Yuri M. Zhukov, «External Resources and
Indiscriminate Violence: Evidence from German-occupied Belarus» (World
Politics, 2017) на Harvard Dataverse, **CC0 1.0**. Проверено по API 24.10.2026:

* `BELARUS_VILLAGES_Full.tab` — 7 929 деревень, 70 колонок: название,
  область и район «до войны», координата, сожжённые дворы
  `HOUSES_DESTROYED` (больше нуля у 7 497), погибшие `PEOPLE_KILLED`
  (у 5 578, всего 194 940), число карательных акций `REPRISAL`. Остальное —
  переменные статьи по району: партизанский контроль, железные дороги,
  этнический состав;
* `BELARUS_VILLAGES_MONTHS_Full.tab` — 291 МБ, те же деревни по месяцам
  с июня 1941 по май 1945 года (48 месяцев, 380 595 строк). Нужен только
  месяц: в каком из них у деревни акция, сожжённые дворы и погибшие. Файл
  читается потоком прямо из сети, в память и на диск не ложится; на диск
  идёт выжимка — месяцы с ненулевыми числами, несколько сотен килобайт.
  Названия в нём испорчены: UTF-8, прочитанный как latin-1, как у
  губерний в наборе Чарныш (`famine_1891.decode_province`); здесь они
  восстанавливаются только для сверки с главной таблицей.

Что выяснилось по данным, а не из описания:

* `HOUSES_PRE` и `PEOPLE_PRE` — не дворы и жители деревни, а величины
  района: у всех деревень одного `RAYON_ID` они одинаковы (170 районов из
  170), а `HOUSES_PROP` равно `HOUSES_DESTROYED / HOUSES_PRE`. В запись
  они не идут; дворы и жители деревни до войны есть в карточке НАРБ;
* координата не всегда деревня. 7 929 деревень стоят в 4 175 точках:
  325 деревень Воложинского, Ивенецкого, Смолевичского и ещё десятка
  районов — в одной точке у Руденска, 231 — в Освее. Геокодер, судя по
  всему, искал по названию без района: одноимённые деревни разных районов
  получили одну координату. Поэтому точка считается деревней, только если
  в ней не стоит другая деревня с другим названием или из другого района
  (`point_mates`); остальные записи идут без точки, с охватом «район
  в области», и с `confidence="shared_point"`, а координата набора
  остаётся в `extra`. Поставить их на карту значило бы соврать о месте;
* у одной деревни (VID 2217, Заболотье) помесячные строки за январь
  1944 года задвоены — сумма вдвое больше итога главной таблицы.
  Одинаковые строки «деревня-месяц» схлопываются, после этого суммы
  сходятся у всех 7 929;
* у 13 деревень нулевые и дворы, и погибшие, и акции — в наборе они есть,
  месяца нет; запись остаётся с периодом 1941–1944 и пометкой в категории.

Дополнение — база Национального архива Республики Беларусь «Белорусские
деревни, сожжённые в годы Великой Отечественной войны» (`db.narb.by`).
Карточка деревни даёт то, чего у Жукова нет: дворы и жителей деревни до
войны, дату уничтожения словами («октябрь 1943 г.», где известно — до
дня), архивные шифры («НАРБ. Ф.1403. Оп.1. Д.174. Л.14.»), судьбу деревни
(«не восстановлена») и сельсовет. Координат в карточке нет. Права база не
заявляет — **права не выяснены**: берутся факты и ссылка на карточку,
фотографии документов и письма не берутся. `robots.txt` закрывает
`/wp-json/`, `/search` и адреса с параметрами; карточки `/village/<slug>/`
открыты и перечислены в sitemap — сбор идёт только по ним, и каждый адрес
перед запросом сверяется с `robots.txt`. Сайт рвёт соединение примерно
через запрос, поэтому у клиента повторы и пауза, а разобранные карточки
копятся в кэше и при повторном запуске не запрашиваются.

Персоналий в слое нет: числа погибших берутся, имён нет ни в наборе, ни в
том, что берётся из карточки.
"""

from __future__ import annotations

import csv
import html as html_lib
import io
import json
import re
import urllib.error
import urllib.request
import urllib.robotparser
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from ..geo import region_key
from ..net import USER_AGENT, fetch_bytes, wait_for_pause
from ..schema import SCOPE_POINT, SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .famine_1891 import MONTH_NAMES, MONTH_NAMES_GEN, DatasetFile, number

DOI = "doi:10.7910/DVN/WLVZQH"
DATASET_URL = "https://doi.org/10.7910/DVN/WLVZQH"
API_URL = ("https://dataverse.harvard.edu/api/datasets/:persistentId/"
           f"?persistentId={DOI}")
FILE_URL = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"

NARB_HOST = "https://db.narb.by"
NARB_URL = NARB_HOST + "/"
NARB_SITEMAP_INDEX = NARB_HOST + "/sitemap_index.xml"
NARB_ROBOTS = NARB_HOST + "/robots.txt"

# Сетевой фильтр `db.narb.by` обрывает соединение, если в User-Agent есть
# слово «harvesting» (проверено 24.10.2026: с общей подписью `net.USER_AGENT`
# не проходит ни один запрос). Это отказ сайта сборщикам, а не сбой, и
# подпись под него не подгоняется: сборщик ходит с общей подписью проекта, и
# пока архив не разрешил сбор (info@mail.narb.by), карточки НАРБ не
# скачиваются — слой собирается из набора Жукова.
NARB_USER_AGENT = USER_AGENT

# Строки короткие намеренно: они повторяются в каждой из восьми тысяч записей.
LICENSE_ZHUKOV = "набор Жукова: CC0 1.0 (карточка набора на Harvard Dataverse)"
LICENSE_NARB = ("база НАРБ: права не выяснены — взяты факты и ссылка на карточку, "
                "сканы и фотографии не копируются")
LICENSE = f"{LICENSE_ZHUKOV}; {LICENSE_NARB}"

CITATION = (
    "Zhukov, Yuri M. Replication data for: External Resources and Indiscriminate "
    "Violence: Evidence from German-occupied Belarus. Harvard Dataverse, V1 (2017), "
    f"{DOI}. CC0 1.0"
)

# Так называется война в слое сражений: по полю `work` слои сводятся.
WORK = "Великая Отечественная война 1941–1945"

# Оккупация Белоруссии — с конца июня 1941 по июль 1944 года; набор кончается
# маем 1945-го, но с августа 1944 года в нём всего семь деревень-месяцев.
YEAR_FROM, YEAR_TO = 1941, 1944

BURNED_VILLAGES = LayerSpec(
    slug="burned_villages_by",
    title="Сожжённые деревни Белоруссии 1941–1944 годов",
    group="military",
    source="набор Ю. Жукова (Harvard Dataverse); база НАРБ «Белорусские деревни, сожжённые…»",
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    # 7 929 деревень набора и 29 карточек НАРБ без пары из кэша на 24.10.2026;
    # с полным обходом НАРБ число вырастет на несведённые карточки.
    expected_rows=7958,
    description=(
        "7 929 деревень, пострадавших при карательных акциях 1941–1944 годов: месяц "
        "уничтожения, сожжённые дворы и погибшие (194 940 человек), довоенные область "
        "и район. Координата набора берётся, только если она одна на деревню: 3 552 "
        "деревни встают точкой, остальные — записью района, потому что геокодер "
        "набора ставил одноимённые деревни разных районов в одну точку. Карточки "
        "базы НАРБ, сведённые с набором по названию и району, добавляют дворы и "
        "жителей деревни до войны, дату словами, архивные шифры и судьбу деревни. "
        "Отвечает на вопрос, почему записи о семье обрываются в 1942–1944 годах."
    ),
)


class BurnedVillagesError(RuntimeError):
    """Набор или карточки устроены не так, как ожидает разбор."""


# --- набор Жукова: перечень файлов -----------------------------------------

VILLAGES = DatasetFile(2972130, "BELARUS_VILLAGES_Full.tab", 4988615)
MONTHS_FILE = DatasetFile(2972087, "BELARUS_VILLAGES_MONTHS_Full.tab", 291306706)

# Остальные 66 файлов набора — районные таблицы, шейпфайлы, RData и код
# статьи; сборщику они не нужны, и расхождения в них проверка не считает.
FILES = (VILLAGES, MONTHS_FILE)

REQUIRED_VILLAGES = ("VID", "VIL_ID", "VILLAGE", "OBLAST_PREWAR", "RAYON_PREWAR", "LONG",
                     "LAT", "HOUSES_DESTROYED", "PEOPLE_KILLED", "REPRISAL", "OBLAST",
                     "RAYON", "RAYON_ID")
REQUIRED_MONTHS = ("VID", "YRMO", "VILLAGE", "HOUSES_DESTROYED", "PEOPLE_KILLED", "REPRISAL")


def fetch_manifest(*, timeout: int = 60) -> list[dict]:
    """Список файлов набора по API Dataverse: id, имя, размер."""
    raw = fetch_bytes(API_URL, error=BurnedVillagesError, timeout=timeout)
    try:
        files = json.loads(raw)["data"]["latestVersion"]["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise BurnedVillagesError(f"ответ API не разбирается: {exc}") from exc
    return [{"id": (f.get("dataFile") or {}).get("id"),
             "name": f.get("label") or (f.get("dataFile") or {}).get("filename"),
             "size": (f.get("dataFile") or {}).get("filesize")} for f in files]


def check_manifest(manifest: Iterable[dict]) -> list[str]:
    """Расхождения перечня в коде с тем, что отдаёт API; пусто — всё сходится."""
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


def check_columns(header: Iterable[str], required: Iterable[str], what: str) -> None:
    names = list(header)
    missing = [c for c in required if c not in names]
    if missing:
        raise BurnedVillagesError(f"{what}: нет обязательных колонок " + ", ".join(missing)
                                  + "; пришли: " + ", ".join(names[:16]))


def cached_villages(cache_dir: Path) -> Path:
    """Главная таблица из кэша; чего нет — скачивается и остаётся там."""
    path = cache_dir / VILLAGES.name
    if path.exists() and path.stat().st_size == VILLAGES.size:
        return path
    data = fetch_bytes(FILE_URL.format(file_id=VILLAGES.file_id), error=BurnedVillagesError)
    if len(data) != VILLAGES.size:
        raise BurnedVillagesError(f"{VILLAGES.name}: скачано {len(data)} байт, "
                                  f"ожидалось {VILLAGES.size}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- чтение таблиц ---------------------------------------------------------

def tab_rows(lines: Iterable[str]) -> Iterator[dict]:
    """Строки TSV Dataverse словарями; кавычки внутри значения — `\\"\\"`."""
    reader = csv.reader(lines, delimiter="\t")
    header = next(reader, None)
    if header is None:
        return
    for row in reader:
        yield dict(zip(header, row))


def read_villages(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(tab_rows(fh))


def village_name(raw) -> Optional[str]:
    """«Льнозавод \\\\"КИМ\\"\\""» → «Льнозавод "КИМ"».

    Ингест Dataverse записал кавычку внутри строки как `\\"\\"`; csv
    отдаёт из этого обратные косые черты и лишние кавычки. Таких названий
    в наборе три, и обратной косой черты в названиях деревень не бывает.
    """
    text = clean_text(raw)
    if text is None:
        return None
    text = text.replace("\\", "")
    while '""' in text:
        text = text.replace('""', '"')
    if text.count('"') % 2 and text.endswith('"'):
        text = text[:-1]
    return clean_text(text)


def repair_mojibake(raw) -> Optional[str]:
    """UTF-8, прочитанный как latin-1: «ÐÐ±Ð°ÐºÑÐ¼Ñ» → «Абакумы».

    Тот же обратный проход, что у губерний голода 1891 года
    (`famine_1891.decode_province`). Чистить строку до него нельзя: байты
    кириллицы в испорченном виде — это и управляющие символы, и
    неразрывный пробел.
    """
    if raw is None:
        return None
    text = str(raw)
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


# --- помесячный файл: потоком, в выжимку ------------------------------------

@dataclass
class MonthScan:
    """Выжимка помесячного файла: что нужно слою и что нужно сверке."""

    rows: int = 0
    header: list = field(default_factory=list)
    yrmo_min: Optional[int] = None
    yrmo_max: Optional[int] = None
    # VID → [(YRMO, дворы, погибшие, акции)] — только месяцы с ненулевым числом.
    months: dict = field(default_factory=dict)
    # Сколько строк «деревня-месяц» оказались буквальным повтором.
    duplicates: int = 0
    duplicate_vids: list = field(default_factory=list)
    # VID → название после починки кодировки: сверка с главной таблицей.
    names: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"rows": self.rows, "header": self.header, "yrmo_min": self.yrmo_min,
                "yrmo_max": self.yrmo_max, "duplicates": self.duplicates,
                "duplicate_vids": self.duplicate_vids,
                "months": {vid: [list(m) for m in ms] for vid, ms in self.months.items()},
                "names": self.names}

    @classmethod
    def from_json(cls, payload: dict) -> "MonthScan":
        scan = cls(rows=payload["rows"], header=payload["header"],
                   yrmo_min=payload["yrmo_min"], yrmo_max=payload["yrmo_max"],
                   duplicates=payload["duplicates"],
                   duplicate_vids=payload.get("duplicate_vids", []),
                   names=payload.get("names", {}))
        scan.months = {vid: [tuple(m) for m in ms] for vid, ms in payload["months"].items()}
        return scan


def _count(value) -> int:
    num = number(value)
    return int(num) if num else 0


def scan_months(lines: Iterable[str]) -> MonthScan:
    """Проход по помесячному файлу строка за строкой; в памяти — только выжимка."""
    reader = csv.reader(lines, delimiter="\t")
    header = next(reader, None) or []
    check_columns(header, REQUIRED_MONTHS, MONTHS_FILE.name)
    ix = {name: i for i, name in enumerate(header)}
    scan = MonthScan(header=header)
    seen: set = set()
    dup_vids: set = set()
    for row in reader:
        scan.rows += 1
        vid = row[ix["VID"]]
        yrmo = int(row[ix["YRMO"]])
        scan.yrmo_min = yrmo if scan.yrmo_min is None else min(scan.yrmo_min, yrmo)
        scan.yrmo_max = yrmo if scan.yrmo_max is None else max(scan.yrmo_max, yrmo)
        if vid not in scan.names:
            scan.names[vid] = repair_mojibake(row[ix["VILLAGE"]])
        values = (_count(row[ix["HOUSES_DESTROYED"]]), _count(row[ix["PEOPLE_KILLED"]]),
                  _count(row[ix["REPRISAL"]]))
        key = (vid, yrmo, values)
        if key in seen:
            scan.duplicates += 1
            dup_vids.add(vid)
            continue
        seen.add(key)
        if any(values):
            scan.months.setdefault(vid, []).append((yrmo, *values))
    for months in scan.months.values():
        months.sort()
    scan.duplicate_vids = sorted(dup_vids, key=int)
    return scan


def stream_months(*, timeout: int = 600) -> Iterator[str]:
    """Помесячный файл строками прямо из сети — 291 МБ мимо диска и памяти."""
    url = FILE_URL.format(file_id=MONTHS_FILE.file_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise BurnedVillagesError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise BurnedVillagesError(f"{url}: сеть недоступна ({exc.reason})") from exc
    with response:
        yield from io.TextIOWrapper(response, encoding="utf-8", newline="")


def months_scan(cache_dir: Path, *, refresh: bool = False,
                lines: Optional[Iterable[str]] = None) -> MonthScan:
    """Выжимка из кэша или новым проходом по файлу (из сети, если строк не дали)."""
    path = cache_dir / "months_scan.json"
    if path.exists() and not refresh and lines is None:
        return MonthScan.from_json(json.loads(path.read_text(encoding="utf-8")))
    scan = scan_months(lines if lines is not None else stream_months())
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scan.to_json(), ensure_ascii=False), encoding="utf-8")
    return scan


def check_scan(scan: MonthScan, villages: list[dict]) -> list[str]:
    """Сверка выжимки с главной таблицей: суммы по месяцам и названия.

    Пустой список — сходится. Расхождение — остановка: значит, файл
    переиздан или разобран не так.
    """
    problems = []
    by_vid = {v["VID"]: v for v in villages}
    if set(scan.names) != set(by_vid):
        problems.append(f"деревень в помесячном файле {len(scan.names)}, "
                        f"в главной таблице {len(by_vid)}")
    for vid, row in by_vid.items():
        months = scan.months.get(vid, [])
        got = tuple(sum(m[i] for m in months) for i in (1, 2, 3))
        want = (_count(row.get("HOUSES_DESTROYED")), _count(row.get("PEOPLE_KILLED")),
                _count(row.get("REPRISAL")))
        if got != want:
            problems.append(f"VID {vid}: по месяцам дворы/погибшие/акции {got}, итог {want}")
    # Сравнение по ключу без знаков: кавычки внутри названия («Льнозавод
    # "КИМ"») два файла экранируют по-разному, и это не порча названия.
    bad_names = [vid for vid, name in scan.names.items()
                 if vid in by_vid and name_key(name) != name_key(by_vid[vid]["VILLAGE"])]
    if bad_names:
        problems.append(f"названия после починки кодировки расходятся у {len(bad_names)}: "
                        + ", ".join(bad_names[:10]))
    return problems


# --- координата: деревня или чужая точка ------------------------------------

# Тип поселения после запятой — «Староселье, пос.», «Антоново, хут.» — в
# наборе и в базе пишется не всегда одинаково и для сравнения снимается.
_RE_KIND_TAIL = re.compile(r",\s*(пос|поселок|хут|хутор|хутора|дер|д)\.?\s*$")


def name_key(name) -> str:
    """«Абразеево», «абразеёво », «Абразеево, пос.» → «абразеево»: для сравнения."""
    text = (village_name(name) or "").lower().replace("ё", "е")
    text = _RE_KIND_TAIL.sub("", text)
    return " ".join(re.sub(r"[^а-яa-z0-9]+", " ", text).split())


def rayon_key(name) -> Optional[str]:
    """«Дубровенский» и «Дубровненский», «Логойский р-н» — к одному ключу.

    Поверх `region_key` снимается «-ский»/«-нский» и «р-н»: написания
    районов в наборе и в базе НАРБ расходятся на букву.
    """
    key = region_key((clean_text(name) or "").replace("р-н", " "))
    if not key:
        return None
    return re.sub(r"(нск|ск)$", "", key)


def point_mates(villages: list[dict]) -> dict[str, int]:
    """VID → сколько других деревень стоят в той же точке, отличаясь от неё.

    Отличие — другое название или другой довоенный район. Две записи
    «Байдино, Россонский район» в одной точке — это, скорее всего, одна
    деревня в двух строках базы, и точка за ней сохраняется; «Адамово»
    Сенненского и Освейского районов в одной точке — нет: одна из них
    стоит не там.
    """
    groups = defaultdict(list)
    for v in villages:
        groups[(v.get("LAT"), v.get("LONG"))].append(v)
    out = {}
    for members in groups.values():
        for v in members:
            me = (name_key(v.get("VILLAGE")), rayon_key(v.get("RAYON_PREWAR")))
            out[v["VID"]] = sum(1 for o in members if o is not v and
                                (name_key(o.get("VILLAGE")),
                                 rayon_key(o.get("RAYON_PREWAR"))) != me)
    return out


# --- база НАРБ: карточки ----------------------------------------------------

CARD_LABELS = {
    "Область": "oblast",
    "Довоенная область": "oblast_prewar",
    "Район": "rayon",
    "Довоенный район": "rayon_prewar",
    "Год разрушения": "year",
    "Дата разрушения": "date",
    "Домов до войны": "houses_pre",
    "Разрушено домов": "houses_destroyed",
    "Людей до войны": "people_pre",
    "Убито людей": "people_killed",
    "Поисковые данные": "sources",
    "Судьба деревни": "fate",
    "Заметки": "notes",
}
# Без этих полей карточка не сводится с набором: если сайт переделают,
# сбор должен остановиться, а не набрать пустые карточки.
REQUIRED_CARD = ("oblast_prewar", "rayon_prewar", "year", "date", "houses_destroyed",
                 "people_killed")

_RE_H2 = re.compile(r"<h2>(.*?)</h2>", re.S)
_RE_POST = re.compile(r'id="village-(\d+)"')
_RE_FIELD = re.compile(
    r"<strong[^>]*>\s*([^<]+?)\s*</strong>\s*<p[^>]*>(.*?)</p>", re.S)
_RE_TAG = re.compile(r"<[^>]+>")


def _cell(html_text: str) -> Optional[str]:
    text = clean_text(html_lib.unescape(_RE_TAG.sub(" ", html_text)))
    if text is None or text.upper() == "NULL":
        return None
    return text


def parse_card(page: str, url: str) -> dict:
    """Карточка `/village/<slug>/` → словарь фактов.

    Берутся только поля таблицы «Информация о деревне»; блок «Ссылки на
    медиафайлы» (сканы, фотографии, письма) не разбирается вовсе.
    """
    start = page.find('class="village-page__info')
    end = page.find('class="village-page__media', start)
    if start < 0:
        raise BurnedVillagesError(f"{url}: нет блока «Информация о деревне»")
    block = page[start:end if end > 0 else len(page)]
    names = _RE_H2.findall(page[:start])
    post = _RE_POST.search(page)
    card = {"url": url, "slug": url.rstrip("/").rsplit("/", 1)[-1],
            "post_id": int(post.group(1)) if post else None,
            "name": _cell(names[-1]) if names else None, "unknown": []}
    for label, value in _RE_FIELD.findall(block):
        key = CARD_LABELS.get(label.strip())
        if key is None:
            card["unknown"].append(label.strip())
            continue
        card[key] = _cell(value)
    return card


def check_card(card: dict) -> list[str]:
    """Чего не хватает в разобранной карточке: пусто — формат прежний."""
    problems = [f"нет поля {key}" for key in REQUIRED_CARD if key not in card]
    if not card.get("name"):
        problems.append("нет названия")
    if card.get("unknown"):
        problems.append("незнакомые поля: " + ", ".join(card["unknown"]))
    return problems


_MONTHS_NOM = {name: i for i, name in enumerate(MONTH_NAMES, start=1)}
_MONTHS_GEN = {name: i for i, name in enumerate(MONTH_NAMES_GEN, start=1)}
# Опечатки, встреченные в карточках: «мац 1944 г.».
_MONTH_TYPOS = {"мац": 5}
_RE_DAY = re.compile(r"^(\d{1,2})\s+([а-яё]+)\s+(\d{4})")
_RE_MONTH = re.compile(r"^([а-яё]+)\s+(\d{4})")
_RE_YEAR = re.compile(r"^(\d{4})")


def _one_date(part: str) -> Optional[tuple[Optional[int], Optional[int], Optional[int]]]:
    m = _RE_DAY.match(part)
    if m and m.group(2) in _MONTHS_GEN and 1 <= int(m.group(1)) <= 31:
        return int(m.group(3)), _MONTHS_GEN[m.group(2)], int(m.group(1))
    m = _RE_MONTH.match(part)
    if m:
        month = _MONTHS_NOM.get(m.group(1)) or _MONTH_TYPOS.get(m.group(1))
        if month:
            return int(m.group(2)), month, None
    m = _RE_YEAR.match(part)
    if m:
        return int(m.group(1)), None, None
    month = _MONTHS_NOM.get(part) or _MONTH_TYPOS.get(part)
    if month:
        return None, month, None     # «февраль, май, сентябрь 1943 г.» — год справа
    return None


def parse_narb_dates(text) -> list[tuple[int, Optional[int], Optional[int]]]:
    """Все даты карточки: «1942 г., август 1943 г.» → [(1942, None, None), (1943, 8, None)].

    Каждая дата — (год, месяц или None, день или None). Месяц без года
    («февраль, май, сентябрь 1943 г.») берёт год ближайшей даты справа.
    Нераспознанная часть пропускается; ничего не распознано — пустой список.
    """
    raw = (clean_text(text) or "").lower().replace("ё", "е")
    parts = [p.strip(" .") for p in re.split(r"[,;]", raw) if p.strip(" .")]
    found = [_one_date(p) for p in parts]
    out: list = []
    year = None
    for item in reversed(found):
        if item is None:
            continue
        y, m, d = item
        year = y if y is not None else year
        if year is not None:
            out.append((year, m, d))
    return list(reversed(out))


def parse_narb_date(text) -> Optional[tuple[int, Optional[int], Optional[int]]]:
    """Первая дата карточки: «24 мая 1943 г.» → (1943, 5, 24)."""
    dates = parse_narb_dates(text)
    return dates[0] if dates else None


def sitemap_locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


def village_sitemaps(index_xml: str) -> list[str]:
    return [u for u in sitemap_locs(index_xml) if re.search(r"/village-sitemap\d*\.xml$", u)]


def card_urls(sitemap_xml: str) -> list[str]:
    """Адреса карточек; корень `/village/` — список, а не карточка."""
    return [u for u in sitemap_locs(sitemap_xml)
            if re.match(r"^https://db\.narb\.by/village/[^/?#]+/$", u)]


class NarbClient:
    """Клиент к `db.narb.by`: robots.txt, пауза, повторы на обрыв соединения.

    Сайт рвёт соединение примерно через запрос (ConnectionResetError на
    чтении) — это не отказ, а особенность сервера, и лечится повтором через
    паузу. Отказ — это HTTP 4xx: он не повторяется.
    """

    def __init__(self, *, pause: float = 1.0, retries: int = 8, timeout: int = 40,
                 opener: Optional[Callable[[str, int], bytes]] = None) -> None:
        self.pause = pause
        self.retries = retries
        self.timeout = timeout
        self.opener = opener or self._open
        self.last_call = 0.0
        self.robots: Optional[urllib.robotparser.RobotFileParser] = None
        self.requests = 0
        self.resets = 0

    def _open(self, url: str, timeout: int) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": NARB_USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def load_robots(self) -> list[str]:
        """Читает robots.txt и возвращает строки Disallow — для отчёта."""
        text = self._get(NARB_ROBOTS, check_robots=False)
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(text.splitlines())
        self.robots = parser
        return [line.split(":", 1)[1].strip() for line in text.splitlines()
                if line.lower().startswith("disallow:")]

    def allowed(self, url: str) -> bool:
        if "?" in url:
            return False   # `Disallow: /*?` — robotparser подстановок не понимает
        return self.robots is not None and self.robots.can_fetch(NARB_USER_AGENT, url)

    def get(self, url: str) -> str:
        return self._get(url, check_robots=True)

    def _get(self, url: str, *, check_robots: bool) -> str:
        if check_robots:
            if self.robots is None:
                self.load_robots()
            if not self.allowed(url):
                raise BurnedVillagesError(f"{url}: закрыт robots.txt — не запрашивается")
        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            self.last_call = wait_for_pause(self.last_call, self.pause + attempt)
            self.requests += 1
            try:
                return self.opener(url, self.timeout).decode("utf-8")
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504):
                    last_error = exc
                    continue
                raise BurnedVillagesError(f"{url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
                self.resets += 1
                last_error = exc
        raise BurnedVillagesError(f"{url}: {self.retries} попыток, последняя — {last_error}")


def all_card_urls(client: NarbClient) -> list[str]:
    """Все карточки по sitemap — без закрытого REST и без поиска."""
    urls: list[str] = []
    for sitemap in village_sitemaps(client.get(NARB_SITEMAP_INDEX)):
        urls.extend(card_urls(client.get(sitemap)))
    seen: set = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def spread_sample(urls: list[str], n: int) -> list[str]:
    """`n` адресов, равномерно разнесённых по списку: проба на весь алфавит."""
    if n <= 0 or not urls:
        return []
    if n >= len(urls):
        return list(urls)
    step = len(urls) / n
    return [urls[int(i * step)] for i in range(n)]


class CardCache:
    """Разобранные карточки построчно в JSONL: дописывается, не переписывается.

    HTML не хранится — только факты карточки. Повторный запуск пропускает
    то, что уже есть, поэтому полный обход можно прерывать и продолжать.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.cards: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").split("\n"):
                if not line.strip():
                    continue
                try:
                    card = json.loads(line)
                except ValueError:
                    continue   # строка, оборванная прерванным обходом: карточка запросится снова
                self.cards[card["url"]] = card

    def __contains__(self, url: str) -> bool:
        return url in self.cards

    def add(self, card: dict) -> None:
        self.cards[card["url"]] = card
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(card, ensure_ascii=False) + "\n")


def fetch_cards(client: NarbClient, urls: Iterable[str], cache: CardCache,
                *, progress: Optional[Callable[[int, dict], None]] = None) -> int:
    """Запрашивает карточки, которых нет в кэше. Возвращает число новых."""
    added = 0
    for url in urls:
        if url in cache:
            continue
        card = parse_card(client.get(url), url)
        problems = check_card(card)
        if problems:
            raise BurnedVillagesError(f"{url}: карточка не разбирается — "
                                      + "; ".join(problems))
        cache.add(card)
        added += 1
        if progress:
            progress(added, card)
    return added


# --- сведение карточек с деревнями набора ------------------------------------

HOW_EXACT = "название, район и числа"
HOW_NAME_RAYON = "название и район"
HOW_NAME_NUMBERS = "название и числа, район другой"
HOW_RAYON_NUMBERS = "район и числа, название другое"


def rayons_close(a, b) -> bool:
    """Один ли район: ключи равны или расходятся на одну букву.

    «Дубровенский» и «Дубровненский» — одно и то же; у ключей короче шести
    букв поправка не делается.
    """
    ka, kb = rayon_key(a), rayon_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if min(len(ka), len(kb)) < 6 or abs(len(ka) - len(kb)) > 1:
        return False
    return _edit_distance(ka, kb) <= 1


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _same_rayon(village: dict, card: dict) -> bool:
    mine = village.get("RAYON_PREWAR")
    return any(rayons_close(mine, card.get(k)) for k in ("rayon_prewar", "rayon"))


def _same_numbers(village: dict, card: dict) -> bool:
    return (_count(village.get("HOUSES_DESTROYED")) == _count(card.get("houses_destroyed"))
            and _count(village.get("PEOPLE_KILLED")) == _count(card.get("people_killed")))


def _how(village: dict, card: dict, same_name: bool) -> Optional[str]:
    rayon, numbers = _same_rayon(village, card), _same_numbers(village, card)
    if same_name and rayon and numbers:
        return HOW_EXACT
    if same_name and rayon:
        return HOW_NAME_RAYON
    if same_name and numbers and (_count(card.get("houses_destroyed"))
                                  or _count(card.get("people_killed"))):
        return HOW_NAME_NUMBERS
    if (not same_name and rayon and numbers
            and _count(card.get("houses_destroyed")) and _count(card.get("people_killed"))):
        return HOW_RAYON_NUMBERS
    return None


_RANK = {HOW_EXACT: 0, HOW_NAME_RAYON: 1, HOW_NAME_NUMBERS: 2, HOW_RAYON_NUMBERS: 3}


def _twin_key(v: dict) -> tuple:
    return (name_key(v.get("VILLAGE")), rayon_key(v.get("RAYON_PREWAR")),
            _count(v.get("HOUSES_DESTROYED")), _count(v.get("PEOPLE_KILLED")),
            v.get("LAT"), v.get("LONG"))


def match_cards(villages: list[dict], cards: Iterable[dict]) -> tuple[dict, dict]:
    """Сводит карточки НАРБ с деревнями набора.

    Возвращает `(VID → (карточка, как сведено), счётчики)`. Основное правило
    задания — название и довоенный район; числа (сожжённые дворы и погибшие)
    различают одноимённые деревни одного района. Два запасных правила
    записываются отдельно: название и числа при другом районе (в наборе
    у части деревень стоит нынешний район, а не довоенный) и район и
    числа при другом написании названия («Абразеево» у Жукова —
    «Образеево» в базе). Неоднозначность — не сведение: если у карточки
    два равных кандидата или у деревни две карточки одного ранга, пара
    не ставится.
    """
    by_name = defaultdict(list)
    by_rayon = defaultdict(list)
    for v in villages:
        by_name[name_key(v.get("VILLAGE"))].append(v)
        by_rayon[rayon_key(v.get("RAYON_PREWAR"))].append(v)

    proposals = []   # (ранг, как сведено, карточка, деревня)
    stats = Counter()
    cards = list(cards)
    for card in cards:
        options = []
        for v in by_name.get(name_key(card.get("name")), []):
            how = _how(v, card, same_name=True)
            if how:
                options.append((_RANK[how], how, v))
        if not options:
            keys = {rayon_key(card.get("rayon_prewar")), rayon_key(card.get("rayon"))} - {None}
            for key in keys:
                for v in by_rayon.get(key, []):
                    how = _how(v, card, same_name=False)
                    if how:
                        options.append((_RANK[how], how, v))
        if not options:
            stats["без пары"] += 1
            continue
        best = min(o[0] for o in options)
        top = [o for o in options if o[0] == best]
        if len({o[2]["VID"] for o in top}) > 1 and len({_twin_key(o[2]) for o in top}) > 1:
            stats["неоднозначно"] += 1
            continue
        # Двойники — одна деревня двумя строками набора (то же название, район,
        # числа и точка): карточка достаётся каждой из строк.
        for _, how, v in top:
            proposals.append((best, how, card, v))

    # Деревне — одна карточка: лучший ранг выигрывает, равные — снимаются.
    by_vid = defaultdict(list)
    for rank, how, card, v in proposals:
        by_vid[v["VID"]].append((rank, how, card))
    matched = {}
    for vid, items in by_vid.items():
        best = min(i[0] for i in items)
        top = [i for i in items if i[0] == best]
        if len(top) > 1:
            stats["неоднозначно"] += len(top)
            stats["без пары"] += len(items) - len(top)
            continue
        matched[vid] = (top[0][2], top[0][1])
        stats["без пары"] += len(items) - 1
        stats[top[0][1]] += 1
    stats["карточек"] = len(cards)
    stats["сведено"] = len({card["url"] for card, _ in matched.values()})
    stats["деревень с карточкой"] = len(matched)
    return matched, dict(stats)


# --- записи ----------------------------------------------------------------

# Месяцы в `extra["months"]` — списки [«ГГГГ-ММ», дворы, погибшие, акции]:
# словари с именами полей в каждой из девяти тысяч строк весили бы вдвое больше.
MONTH_FIELDS = ("month", "houses", "people", "reprisals")

CATEGORY_BURNED = "сожжены дворы"
CATEGORY_KILLED = "погибли жители, дворы не сожжены"
CATEGORY_ACTION = "карательная акция без учтённых потерь"
CATEGORY_NONE = "потерь и месяца в наборе нет"
CATEGORY_NARB_ONLY = "сожжены дворы (только база НАРБ)"
CATEGORY_NARB_KILLED = "погибли жители (только база НАРБ)"
CATEGORY_NARB_EMPTY = "дворы и погибшие не указаны (только база НАРБ)"

CONFIDENCE_SHARED = "shared_point"


def _plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 19:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def _n(n: int, one: str, few: str, many: str) -> str:
    return f"{n:,}".replace(",", " ") + " " + _plural(n, one, few, many)


def _loss_short(houses: int, killed: int, actions: int) -> str:
    """Для заголовка — одно главное число."""
    if houses:
        return f"сожжено дворов: {houses}"
    if killed:
        return f"погибших: {killed}"
    return "карательная акция" if actions else "потери не указаны"


def _loss_full(houses: int, killed: int) -> str:
    if not houses and not killed:
        return "Сожжённых дворов и погибших источник не называет"
    return f"Сожжено дворов: {houses}, погибших: {killed}"


def _yrmo(yrmo: int) -> tuple[int, int]:
    return yrmo // 100, yrmo % 100


def month_text(yrmo: int, genitive: bool = False) -> str:
    year, month = _yrmo(yrmo)
    names = MONTH_NAMES_GEN if genitive else MONTH_NAMES
    return f"{names[month - 1]} {year}"


def period_of(months: list[tuple]) -> Optional[tuple[int, int]]:
    """Первый и последний месяц с акцией; дворы и погибшие без акции не бывают."""
    active = [m[0] for m in months if any(m[1:])]
    return (min(active), max(active)) if active else None


def months_text(months: list[tuple]) -> str:
    """«март 1943», «июнь 1942; март 1943», «с июня 1942 по июнь 1944, 32 месяца»."""
    active = sorted(m[0] for m in months if any(m[1:]))
    if not active:
        return ""
    if len(active) <= 4:
        return "; ".join(month_text(y) for y in active)
    return (f"с {month_text(active[0], True)} по {month_text(active[-1])}, "
            f"{_n(len(active), 'месяц', 'месяца', 'месяцев')} с акциями")


# Написания «Судьбы деревни» в карточках — к словам; прочее идёт как есть.
FATES = {"не восстановлена": "не восстановлена", "не восст.": "не восстановлена",
         "с част -восст": "частично восстановлена", "восстановлена": "восстановлена"}


def _oblast(name) -> Optional[str]:
    text = clean_text(name)
    return f"{text} область" if text else None


def _rayon(name) -> Optional[str]:
    text = clean_text(name)
    return f"{text} район" if text else None


def _narb_extra(card: dict) -> dict:
    keys = ("url", "post_id", "name", "oblast_prewar", "rayon_prewar", "oblast", "rayon",
            "year", "date", "houses_pre", "houses_destroyed", "people_pre", "people_killed",
            "sources", "fate", "notes")
    return {k: card[k] for k in keys if card.get(k) not in (None, "")}


def _narb_summary(card: dict) -> str:
    parts = []
    pre = []
    houses_pre, people_pre = number(card.get("houses_pre")), number(card.get("people_pre"))
    if houses_pre:
        pre.append(_n(int(houses_pre), "двор", "двора", "дворов"))
    if people_pre:
        pre.append(_n(int(people_pre), "житель", "жителя", "жителей"))
    if pre:
        parts.append("до войны " + " и ".join(pre))
    if card.get("date"):
        parts.append(f"дата уничтожения — {card['date']}")
    fate = (card.get("fate") or "").strip()
    if fate in FATES:
        parts.append(f"деревня {FATES[fate]}")
    elif fate:
        parts.append(f"судьба деревни: {fate}")
    text = "По базе НАРБ: " + ", ".join(parts) + "." if parts else "Карточка в базе НАРБ."
    if card.get("sources"):
        text += f" Источник в карточке: {card['sources']}"
        if not text.endswith("."):
            text += "."
    return text


def _date_fields(months: list[tuple], card: Optional[dict]) -> dict:
    """Границы, точность и исходная запись даты из набора и карточки.

    Месяц набора и дата карточки обычно совпадают. Если карточка называет
    одну дату с днём внутри единственного месяца набора — точность «день».
    Если ни один месяц карточки не совпал с месяцами набора, интервал
    расширяется на годы обоих (правило схемы), точность — по набору, а
    расхождение видно в `period_raw` и в `extra["dates_agree"]`.
    """
    period = period_of(months)
    narb = parse_narb_dates(card.get("date")) if card else []
    raw_parts = []
    if period:
        y0, y1 = period[0] // 100, period[1] // 100
        precision = "month"
        raw_parts.append(f"набор: {months_text(months)}")
    else:
        y0, y1, precision = YEAR_FROM, YEAR_TO, "year"
        raw_parts.append(f"набор: месяца нет, {YEAR_FROM}–{YEAR_TO}")
    agreed = None
    if card and card.get("date"):
        raw_parts.append(f"НАРБ: {card['date']}")
    if narb:
        active = {m[0] for m in months if any(m[1:])}
        hits = [d for d in narb if d[1] and d[0] * 100 + d[1] in active]
        if hits:
            agreed = True
            if len(narb) == 1 and narb[0][2] and len(active) == 1:
                precision = "day"
        elif not period:
            agreed = True
            y0, y1 = min(d[0] for d in narb), max(d[0] for d in narb)
            precision = _dates_precision(narb)
        else:
            agreed = False
            y0 = min(y0, *(d[0] for d in narb))
            y1 = max(y1, *(d[0] for d in narb))
    return {"year_from": y0, "year_to": y1, "date_precision": precision,
            "period_raw": "; ".join(raw_parts), "dates_agree": agreed}


def _dates_precision(dates: list[tuple]) -> str:
    """Точность по датам карточки: одна дата с днём — «день», все с месяцем — «месяц»."""
    if len(dates) == 1 and dates[0][2]:
        return "day"
    return "month" if all(d[1] for d in dates) else "year"


def village_record(row: dict, months: list[tuple], mates: int,
                   card: Optional[dict] = None, how: Optional[str] = None) -> ContextRecord:
    """Деревня набора (и, если сведена, карточка НАРБ) → запись схемы."""
    name = village_name(row.get("VILLAGE")) or "деревня без названия"
    oblast, rayon = _oblast(row.get("OBLAST_PREWAR")), _rayon(row.get("RAYON_PREWAR"))
    houses, killed = _count(row.get("HOUSES_DESTROYED")), _count(row.get("PEOPLE_KILLED"))
    actions = _count(row.get("REPRISAL"))
    dates = _date_fields(months, card)

    if houses:
        category = CATEGORY_BURNED
    elif killed:
        category = CATEGORY_KILLED
    elif actions:
        category = CATEGORY_ACTION
    else:
        category = CATEGORY_NONE
    when = months_text(months) or f"{YEAR_FROM}–{YEAR_TO}"
    head = f"{name}, {rayon}" if rayon else name
    title = f"{head}: {when} — {_loss_short(houses, killed, actions)}"

    summary = _loss_full(houses, killed)
    if months:
        summary += f" — {when}, карательных акций: {actions}."
    else:
        summary += "; месяц в наборе не указан."
    if card:
        summary += " " + _narb_summary(card)
    if mates:
        others = _n(mates, "деревней", "деревнями", "деревнями")
        summary += f" Точка набора общая ещё с {others} — не место деревни, на карте её нет."

    lat, lon = number(row.get("LAT")), number(row.get("LONG"))
    extra = {
        # Название, довоенные область и район и итоги уже стоят в полях
        # записи; здесь — ключи набора, район 1941 года, к которому статья
        # отнесла деревню по точке, и месяцы. Ссылка на набор и права — в
        # карточке слоя: повторять их в каждой из 7 929 записей — мегабайт.
        "zhukov": {"VID": row.get("VID"), "VIL_ID": clean_text(row.get("VIL_ID")),
                   "OBLAST": clean_text(row.get("OBLAST")),
                   "RAYON": clean_text(row.get("RAYON"))},
        "months": [[f"{y // 100}-{y % 100:02d}", h, p, r] for y, h, p, r in months],
    }
    if mates:
        # Точка набора — не деревня: она остаётся здесь, а не в lat/lon.
        extra["zhukov"]["LAT"], extra["zhukov"]["LONG"] = row.get("LAT"), row.get("LONG")
        extra["point_mates"] = mates
    if card:
        extra["narb"] = _narb_extra(card)
        extra["narb_match"] = how
        if dates["dates_agree"] is not None:
            extra["dates_agree"] = dates["dates_agree"]

    point = not mates and lat is not None and lon is not None
    place = ", ".join(p for p in (f"д. {name}", rayon, oblast) if p)
    return BURNED_VILLAGES.new_record(
        title=title,
        category=category,
        lat=lat if point else None,
        lon=lon if point else None,
        scope=SCOPE_POINT if point else SCOPE_REGION,
        place_text=place,
        region=oblast,
        regions=[] if point or not oblast else [oblast],
        district=rayon,
        year_from=dates["year_from"],
        year_to=dates["year_to"],
        date_precision=dates["date_precision"],
        period_raw=dates["period_raw"],
        work=WORK,
        summary=summary,
        url=card["url"] if card else DATASET_URL,
        source_id=clean_text(row.get("VIL_ID")),
        license=LICENSE if card else LICENSE_ZHUKOV,
        confidence="ok" if point else CONFIDENCE_SHARED if mates else "no_coords",
        extra=extra,
    )


def card_record(card: dict) -> ContextRecord:
    """Карточка НАРБ без пары в наборе: деревня есть, координаты нет."""
    name = card.get("name") or "деревня без названия"
    oblast = _oblast(card.get("oblast_prewar") or card.get("oblast"))
    rayon = _rayon(card.get("rayon_prewar") or card.get("rayon"))
    houses, killed = _count(card.get("houses_destroyed")), _count(card.get("people_killed"))
    narb = parse_narb_dates(card.get("date"))
    year = number(card.get("year"))
    if narb:
        y0, y1 = min(d[0] for d in narb), max(d[0] for d in narb)
        precision = _dates_precision(narb)
    elif year:
        y0 = y1 = int(year)
        precision = "year"
    else:
        # База целиком о 1941–1944 годах: без даты интервал — вся оккупация.
        y0, y1, precision = YEAR_FROM, YEAR_TO, "year"
    when = card.get("date") or (str(int(year)) if year else "дата не указана")
    if houses:
        category = CATEGORY_NARB_ONLY
    elif killed:
        category = CATEGORY_NARB_KILLED
    else:
        category = CATEGORY_NARB_EMPTY
    head = f"{name}, {rayon}" if rayon else name
    place = ", ".join(p for p in (f"д. {name}", rayon, oblast) if p) + " (довоенное деление)"
    summary = _loss_full(houses, killed) + ". "
    summary += _narb_summary(card) + " В наборе Жукова пары нет — координаты у записи нет."
    return BURNED_VILLAGES.new_record(
        title=f"{head}: {when} — {_loss_short(houses, killed, 0)}",
        category=category,
        scope=SCOPE_REGION,
        place_text=place,
        region=oblast,
        regions=[oblast] if oblast else [],
        district=rayon,
        year_from=y0,
        year_to=y1,
        date_precision=precision,
        period_raw=(f"НАРБ: {card['date']}" if card.get("date") else
                    f"НАРБ: даты нет, {YEAR_FROM}–{YEAR_TO}"),
        work=WORK,
        summary=summary,
        url=card["url"],
        source_id=f"narb:{card.get('post_id') or card.get('slug')}",
        license=LICENSE_NARB,
        extra={"narb": _narb_extra(card)},
    )


def build_records(villages: list[dict], scan: MonthScan,
                  cards: Iterable[dict] = ()) -> tuple[list[ContextRecord], dict]:
    """Все записи слоя и счётчики сведения."""
    cards = list(cards)
    mates = point_mates(villages)
    matched, stats = match_cards(villages, cards) if cards else ({}, {})
    records = []
    for row in villages:
        vid = row["VID"]
        card, how = matched.get(vid, (None, None))
        records.append(village_record(row, scan.months.get(vid, []), mates[vid], card, how))
    used = {c["url"] for c, _ in matched.values()}
    records.extend(card_record(c) for c in cards if c["url"] not in used)
    return records, stats
