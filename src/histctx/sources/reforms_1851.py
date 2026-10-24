"""Крестьянские волнения 1851–1871 годов и уезд после реформ: пакет Дауэра и др.

Пакет воспроизведения к статье P. C. Dower, E. Finkel, S. Gehlbach,
S. Nafziger «Collective Action and Representation in Autocracies: Evidence
from Russia's Great Reforms» (APSR, 2018) на Harvard Dataverse,
doi:10.7910/DVN/X7AMNO, версия 2 (поправка 2019 года к `serfperc1`), CC0 1.0.
Проверено по API 24.10.2026.

Из пакета собираются два слоя.

**`peasant_unrest_1851` — волнения по уездам и годам.** `event_data_replication.dta`
— 3 786 строк: событие хроники «Крестьянское движение в России» (тома Окуня
1962, Окуня и Сивкова 1963, Иванова 1964, Зайончковского и Паиной 1968) в
уезде (`masterid`) и году (`startyear`), 1851–1871 годы, 466 уездов. Хронику
закодировали Финкель, Гельбах и Ольсен (CPS, 2015); 183 события записаны
сразу в нескольких уездах (одно `accessid` — до двенадцати строк). Точки у
события нет: хроника называет губернию, уезд и имение, а координата набора
— уездный город, и ставить на него волнение значило бы соврать о месте.
Поэтому запись — «уезд-год» с охватом «уезд внутри губернии», как у голода
1891 года: сколько событий, какого рода, сколько крупных.

Род события — по буквам кода. Колонки `ar*`, `at*`, `ac*`, `ag*` подписей в
пакете не имеют; кодовую книгу FGO 2015 держит онлайн-приложение журнала,
из среды недоступное. Расшифровка по статье FGO: действия делятся на четыре
рода — отказ (Refusal), захват и насилие (Theft and violence, сюда же
«волнение» без уточнения), жалоба (Complaint), смена управления
(Governance). Буквы совпадают с родами (`r`, `t`, `c`, `g`), а частоты — с
описанием статьи: отказов больше всего (2 665), захватов и насилия вдвое
меньше (1 085), жалоб 420, смены управления 52. Подкоды (`ar2`, `at30`)
остаются в `extra` без перевода. `large` — событие охватило несколько
селений или уездов (так в статье APSR), `a_tsgaor` — источник события
в ЦГАОР (донесения III отделения), а не губернаторские отчёты. 39 строк без
`a` (только `at20`) статья в подсчёт не берёт; здесь они остаются и
считаются отдельно.

**`reforms_uezd` — уезд после реформ.** `variables_replication.tab` (исходник
`.dta`) — 504 уезда 50 губерний × 344 колонки. Берутся шесть сюжетов,
которые объясняют документ о предке, и только те колонки, из которых
складывается текст записи:

* крепостные по X ревизии (1857–1859) и население по Бушену 1858 года,
  доля крепостных; состав крепостных мужского пола в 1859 году — на барщине,
  на оброке, дворовые;
* выкупная операция к 1877 году: общества и души на выкупе и временнообязанные;
* раскладка гласных уездного земского собрания по Положению 1864 года:
  сколько мест у землевладельцев, городских и сельских обществ;
* земство в 1883 году: сколько крестьян среди гласных от сельских обществ
  и доли образования и медицины в расходах (суммы — в `extra`: единицу
  пакет не называет);
* сельские школы в 1860 и 1880 годах и учащиеся 1880 года;
* сельские общества 1893 года: дворы и безземельные дворы.

Остальное — почвы (`pctsoil*`), расстояния, оценки и остатки регрессий
статьи (`ahat_*`, `aresid_*`), дворянское землевладение 1877 года по
разрядам, недоимки 1895 года, монастыри — в слой не идёт: это либо
переменные модели, а не факты, либо сюжеты, которым нужен свой разбор.
Решение записано в `docs/HARVEST.md`.

Права: CC0 1.0 (карточка набора). Названия уездов латиницей сводятся с
уездами 1897 года RISTAT (`uezd_names`).
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .dataverse import DatasetFile
from .uezd_names import NAFZIGER_DISTRICTS, NAFZIGER_PROVINCES, Place, RistatDistricts, resolve

DOI = "doi:10.7910/DVN/X7AMNO"
DATASET_URL = "https://doi.org/10.7910/DVN/X7AMNO"
LICENSE_NAME = "CC0 1.0"
LICENSE = ("CC0 1.0 — общественное достояние (карточка набора: CC0 1.0, SPDX CC0-1.0); "
           "ссылка на набор проставляется в каждой записи")
CITATION = (
    "Dower, Paul Castañeda; Finkel, Evgeny; Gehlbach, Scott; Nafziger, Steven. Replication "
    "Data for: Collective Action and Representation in Autocracies: Evidence from Russia's "
    f"Great Reforms. Harvard Dataverse, V2 (2019), {DOI}. CC0 1.0"
)
CHRONICLE = ("Крестьянское движение в России: сборники документов (Окунь 1962; Окунь, "
             "Сивков 1963; Иванов 1964; Зайончковский, Паина 1968), закодировано "
             "Finkel, Gehlbach, Olsen (2015)")

EVENTS = DatasetFile(3051049, "event_data_replication.dta", 735471)
VARIABLES = DatasetFile(3480125, "variables_replication.tab", 877988, original_size=982910,
                        local_name="variables_replication.dta")
UEZD_JOIN = DatasetFile(3051056, "UezdJoin.tab", 16492)
README = DatasetFile(3051052, "README.pdf", 42645)
NOTE = DatasetFile(3550195, "Note.pdf", 93779)
# Шейпфайл 1897Uezd и код статьи сборщику не нужны: полигоны уездов 1897 года
# в проекте уже есть (RISTAT).
FILES = (EVENTS, VARIABLES, UEZD_JOIN, README, NOTE)
DATA_FILES = (EVENTS, VARIABLES, UEZD_JOIN)

PEASANT_UNREST = LayerSpec(
    slug="peasant_unrest_1851",
    title="Крестьянские волнения 1851–1871 годов по уездам",
    group="hardship",
    source="Harvard Dataverse, пакет Dower, Finkel, Gehlbach, Nafziger (APSR 2018): "
           "хроника «Крестьянское движение в России» по уездам",
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=2278,
    description=(
        "3 786 событий хроники «Крестьянское движение в России» за 1851–1871 годы в 466 уездах "
        "50 губерний, сведённые в записи «уезд-год»: сколько выступлений, какого рода (отказ "
        "от повинностей и условий освобождения, захват и насилие, жалоба, смена управления), "
        "сколько охватило несколько селений или уездов. Десятилетие до отмены крепостного "
        "права и после неё — ответ на вопрос, что происходило в уезде предка в 1858–1863 годах. "
        "Без точки: событие привязано к уезду, а не к селу."
    ),
)

REFORMS_UEZD = LayerSpec(
    slug="reforms_uezd",
    title="Уезд после реформ: крепостные, выкуп, земство, школы, общины",
    group="state",
    source="Harvard Dataverse, пакет Dower, Finkel, Gehlbach, Nafziger (APSR 2018): "
           "уездные данные 1857–1893 годов",
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=2626,
    description=(
        "Шесть сюжетов по 504 уездам 50 губерний Европейской России: крепостные по X ревизии "
        "и доля их в населении 1858 года, барщина и оброк 1859 года; выкупная операция к "
        "1877 году (общества и души на выкупе и временнообязанные); места гласных уездного "
        "земства по Положению 1864 года; крестьяне среди гласных и расходы земства 1883 года; "
        "сельские школы 1860 и 1880 годов; сельские общества и безземельные дворы 1893 года. "
        "Объясняет, был ли предок крепостным, когда его община перешла на выкуп и было ли в "
        "уезде земство и школа. Записи «уезд-год», без точки."
    ),
)

UNREST_WORK = "Крестьянское движение в России"
WORK_EMANCIPATION = "Отмена крепостного права"
WORK_REDEMPTION = "Выкупная операция"
WORK_ZEMSTVO = "Земские учреждения и земская статистика"


class ReformsError(RuntimeError):
    """Пакет не скачался или устроен не так, как ожидает разбор."""


# --- чтение -----------------------------------------------------------------

def read_stata(path: Path) -> list[dict]:
    """`.dta` в список строк: пропуски — None, целые без «.0»."""
    import pandas as pd

    frame = pd.read_stata(path, convert_categoricals=False)
    rows = []
    for record in frame.to_dict(orient="records"):
        rows.append({k: _clean_cell(v) for k, v in record.items()})
    return rows


def _clean_cell(value):
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return int(value) if value.is_integer() else value
    if hasattr(value, "item"):           # numpy-скаляр
        return _clean_cell(value.item())
    if isinstance(value, str):
        return value.strip() or None
    return value


def read_table(path: Path) -> list[dict]:
    """Ингестированный TSV Dataverse (`UezdJoin.tab`): строки как есть."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh, delimiter="\t")]


REQUIRED_EVENTS = ("masterid", "accessid", "startyear", "a", "ar", "at", "ac", "ag", "large",
                   "a_tsgaor")
REQUIRED_VARIABLES = (
    "masterid", "province", "uezd", "maleserfs_1857", "femaleserfs_1857", "bushenmalepop1858",
    "bushenfemalepop1858", "serfperc1", "householdserfs_1859", "barshchinaserfs_1859",
    "obrokserfs_1859", "redeemingcommunes_1877", "redeemingsouls_1877",
    "obligatedcommunes_1877", "obligatedsouls_1877", "curia1reps_1864", "curia2reps_1864",
    "curia3reps_1864", "peasantrepresentation_1864", "peasantuglasnye3rdcuria_1883",
    "totaluglasnye3rdcuria_1883", "zeducexp1883", "zmedicalexp1883", "ztotalexp1883",
    "schools_1860", "totalschools1880", "boysenrolled1880", "girlsenrolled1880",
    "communes_1893", "communesettlements_1893", "communehhs_1893", "communelandlesshhs_1893",
)
REQUIRED_JOIN = ("province_name", "uezd_name", "masterid")


def check_columns(header: Iterable[str], required: Iterable[str], what: str) -> None:
    names = list(header)
    missing = [c for c in required if c not in names]
    if missing:
        raise ReformsError(f"{what}: нет обязательных колонок " + ", ".join(missing)
                           + "; пришли: " + ", ".join(names[:16]))


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _int(value) -> Optional[int]:
    number = _num(value)
    return int(number) if number is not None else None


# --- текст ------------------------------------------------------------------

def thousands(value: float) -> str:
    """12345 → «12 345» (неразрывный пробел, как у голода 1891 года)."""
    return f"{int(round(value)):,}".replace(",", " ")


def percent(part: float, whole: float) -> str:
    share = 100.0 * part / whole
    if 0 < share < 0.05:
        return "менее 0,1%"
    shown = f"{share:.0f}" if share >= 10 else f"{share:.1f}".replace(".", ",")
    return f"{shown}%"


def plural(value: float, one: str, few: str, many: str) -> str:
    n = abs(int(round(value)))
    if 11 <= n % 100 <= 19:
        return many
    last = n % 10
    if last == 1:
        return one
    return few if 2 <= last <= 4 else many


# --- место --------------------------------------------------------------------

class Places:
    """masterid → место записи. Названия — из таблицы уездов пакета, губерния
    по закрытому словарю, уезд — сверкой с RISTAT."""

    def __init__(self, variables: Iterable[dict], join: Iterable[dict],
                 index: Optional[RistatDistricts]) -> None:
        self.index = index
        self.names: dict[int, tuple] = {}
        for row in join:
            mid = _int(row.get("masterid"))
            if mid is not None:
                self.names[mid] = (clean_text(row.get("province_name")),
                                   clean_text(row.get("uezd_name")))
        for row in variables:
            mid = _int(row.get("masterid"))
            if mid is not None:
                self.names[mid] = (clean_text(row.get("province")), clean_text(row.get("uezd")))
        self._cache: dict[int, Place] = {}

    def latin(self, masterid: int) -> tuple:
        return self.names.get(masterid, (None, None))

    def get(self, masterid: int) -> Place:
        if masterid not in self._cache:
            province_latin, uezd_latin = self.latin(masterid)
            # Динабургского уезда в таблице переменных нет: в таблице уездов
            # пакета у него нет губернии. Он Витебский — так и в коде статьи.
            if province_latin is None and uezd_latin == "Dinaburgskii":
                province_latin = "Vitebsk"
            province = NAFZIGER_PROVINCES.get(province_latin or "")
            manual = NAFZIGER_DISTRICTS.get((province_latin, uezd_latin))
            place = resolve(self.index, province or province_latin, uezd_latin, manual=manual)
            self._cache[masterid] = place
        return self._cache[masterid]


def _extra(place: Place, masterid: int, latin: tuple, columns: dict) -> dict:
    extra = {"masterid": masterid, "province_latin": latin[0], "uezd_latin": latin[1],
             "columns": {k: v for k, v in columns.items() if v is not None},
             "citation": CITATION}
    if place.distr_id:
        extra["ristat_distr_id"] = place.distr_id
        extra["ristat_match"] = place.how
    return extra


# --- волнения ----------------------------------------------------------------

KINDS = (
    ("ar", "отказ от повинностей, выкупа или условий освобождения"),
    ("at", "захват, насилие, порча имущества или «волнение» без уточнения"),
    ("ac", "жалоба властям"),
    ("ag", "попытка сменить управление имением или волостью"),
)
KIND_CODES = tuple(code for code, _ in KINDS)
CATEGORY_LARGE = "волнения: охватили несколько селений или уездов"
CATEGORY_LOCAL = "волнения в отдельных селениях"


def _subcodes(row: dict) -> list[str]:
    return sorted(k for k, v in row.items()
                  if v and k[:2] in KIND_CODES and k[2:].isdigit())


def group_events(rows: Iterable[dict]) -> dict[tuple, list[dict]]:
    """(masterid, год) → события. Строки без уезда или года — отдельно не теряются:
    их число печатает `--check`."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        mid, year = _int(row.get("masterid")), _int(row.get("startyear"))
        if mid is None or year is None:
            continue
        groups[(mid, year)].append(row)
    return dict(sorted(groups.items()))


def shared_events(rows: Iterable[dict]) -> set:
    """`accessid`, записанные сразу в нескольких уездах."""
    seen: dict[int, set] = defaultdict(set)
    for row in rows:
        acc, mid = _int(row.get("accessid")), _int(row.get("masterid"))
        if acc is not None and mid is not None:
            seen[acc].add(mid)
    return {acc for acc, mids in seen.items() if len(mids) > 1}


def unrest_summary(year: int, events: list[dict], shared: set) -> tuple[str, dict]:
    n = len(events)
    kinds = Counter()
    for event in events:
        for code in KIND_CODES:
            if event.get(code):
                kinds[code] += 1
    uncoded = sum(1 for e in events if not e.get("a"))
    large = sum(1 for e in events if e.get("large"))
    tsgaor = sum(1 for e in events if e.get("a_tsgaor"))
    multi = sum(1 for e in events if _int(e.get("accessid")) in shared)
    word = plural(n, "выступление", "выступления", "выступлений")
    text = f"В {year} году хроника «Крестьянское движение в России» записала в уезде {n} {word}"
    parts = [f"{label} — {kinds[code]}" for code, label in KINDS if kinds[code]]
    if parts:
        text += ": " + "; ".join(parts)
    text += "."
    tail = []
    if large:
        tail.append(f"охватили несколько селений или уездов — {large}")
    if multi:
        tail.append(f"записаны сразу в нескольких уездах — {multi}")
    if tsgaor:
        tail.append(f"известны по донесениям III отделения (ЦГАОР) — {tsgaor}")
    if uncoded:
        tail.append(f"без кода действия (статья их не считает) — {uncoded}")
    if tail:
        text += " Из них " + "; ".join(tail) + "."
    if len([1 for e in events if sum(1 for c in KIND_CODES if e.get(c)) > 1]):
        text += " Событие с несколькими действиями считается в каждом роде."
    stats = {"events": n, "kinds": {c: kinds[c] for c in KIND_CODES if kinds[c]},
             "large": large, "tsgaor": tsgaor, "uncoded": uncoded, "shared": multi}
    return text, stats


def unrest_records(rows: list[dict], places: Places) -> list[ContextRecord]:
    """Запись «уезд-год» на каждое сочетание с хотя бы одним событием."""
    shared = shared_events(rows)
    out = []
    for (mid, year), events in group_events(rows).items():
        place = places.get(mid)
        summary, stats = unrest_summary(year, events, shared)
        codes = Counter(code for e in events for code in _subcodes(e))
        extra = _extra(place, mid, places.latin(mid), {})
        extra.pop("columns")
        extra.update({"unrest": stats, "codes": dict(sorted(codes.items())),
                      "access_ids": sorted(_int(e.get("accessid")) for e in events),
                      "chronicle": CHRONICLE})
        out.append(PEASANT_UNREST.new_record(
            title=f"{place.head}: крестьянские волнения {year} года",
            category=CATEGORY_LARGE if stats["large"] else CATEGORY_LOCAL,
            scope=SCOPE_REGION,
            place_text=place.place_text,
            region=place.province,
            regions=[place.province] if place.province else [],
            district=place.district,
            year_from=year, year_to=year, date_precision="year", period_raw=str(year),
            work=UNREST_WORK,
            summary=summary,
            url=DATASET_URL,
            source_id=f"{mid}:{year}",
            confidence=place.confidence,
            extra=extra,
        ))
    return out


# --- уезд после реформ ------------------------------------------------------------

CATEGORY_SERFS = "крепостные накануне освобождения"
CATEGORY_REDEMPTION = "выкупная операция к 1877 году"
CATEGORY_ZEMSTVO_1864 = "земство: гласные по Положению 1864 года"
CATEGORY_ZEMSTVO_1883 = "земство в 1883 году"
CATEGORY_SCHOOLS = "сельские школы 1860 и 1880 годов"
CATEGORY_COMMUNES = "сельские общества в 1893 году"


def _pick(row: dict, names: Iterable[str]) -> dict:
    return {n: row.get(n) for n in names}


def serfs_record(row: dict) -> Optional[tuple]:
    male, female = _num(row.get("maleserfs_1857")), _num(row.get("femaleserfs_1857"))
    if male is None or female is None:
        return None
    serfs = male + female
    parts = []
    if serfs == 0:
        parts.append("По X ревизии (1857–1859) крепостных в уезде не числилось")
    else:
        parts.append(f"По X ревизии (1857–1859) в уезде {thousands(serfs)} "
                     f"{plural(serfs, 'крепостной', 'крепостных', 'крепостных')} "
                     f"(мужчин {thousands(male)}, женщин {thousands(female)})")
    bm, bf = _num(row.get("bushenmalepop1858")), _num(row.get("bushenfemalepop1858"))
    share = _num(row.get("serfperc1"))
    if bm is not None and bf is not None and bm + bf > 0:
        pop = bm + bf
        text = (f"население уезда в 1858 году по Бушену — {thousands(pop)} "
                f"{plural(pop, 'человек', 'человека', 'человек')}")
        if share is not None and serfs > 0:
            text += f", крепостные — {percent(share, 1.0)}"
        parts.append(text)
    elif share is not None and serfs > 0:
        parts.append(f"крепостные — {percent(share, 1.0)} населения 1858 года")
    house, corvee, quit_ = (_num(row.get(k)) for k in
                            ("householdserfs_1859", "barshchinaserfs_1859", "obrokserfs_1859"))
    if None not in (house, corvee, quit_) and house + corvee + quit_ > 0:
        total = house + corvee + quit_
        parts.append(f"из крепостных мужского пола в 1859 году на барщине "
                     f"{percent(corvee, total)}, на оброке {percent(quit_, total)}, "
                     f"дворовых {percent(house, total)}")
    note = clean_text(row.get("bushendataissues1858"))
    summary = ". ".join(p[0].upper() + p[1:] for p in parts) + "."
    if note:
        summary += " У населения 1858 года в пакете пометка составителей (в extra)."
    columns = _pick(row, ("maleserfs_1857", "femaleserfs_1857", "bushenmalepop1858",
                          "bushenfemalepop1858", "serfperc1", "householdserfs_1859",
                          "barshchinaserfs_1859", "obrokserfs_1859", "bushendataissues1858"))
    return (CATEGORY_SERFS, "крепостные накануне освобождения", 1857, 1859, "1857–1859",
            WORK_EMANCIPATION, summary, columns)


def redemption_record(row: dict) -> Optional[tuple]:
    rc, rs = _num(row.get("redeemingcommunes_1877")), _num(row.get("redeemingsouls_1877"))
    oc, os_ = _num(row.get("obligatedcommunes_1877")), _num(row.get("obligatedsouls_1877"))
    if None in (rc, rs, oc, os_) or rs + os_ == 0:
        return None
    summary = (f"К 1877 году на выкуп перешли {thousands(rc)} "
               f"{plural(rc, 'сельское общество', 'сельских общества', 'сельских обществ')} "
               f"({_souls(rs)}), временнообязанными оставались {thousands(oc)} "
               f"({_souls(os_)}) — {percent(os_, rs + os_)} душ бывших помещичьих "
               "крестьян уезда ещё не выкупали надел.")
    columns = _pick(row, ("redeemingcommunes_1877", "redeemingsouls_1877",
                          "redeemingallotmentland_1877", "obligatedcommunes_1877",
                          "obligatedsouls_1877", "obligatedallotmentland_1877"))
    return (CATEGORY_REDEMPTION, "выкуп и временнообязанные к 1877 году", 1877, 1877, "1877",
            WORK_REDEMPTION, summary, columns)


def _souls(value: float) -> str:
    return f"{thousands(value)} {plural(value, 'душа', 'души', 'душ')}"


def zemstvo_1864_record(row: dict) -> Optional[tuple]:
    c1, c2, c3 = (_num(row.get(k)) for k in ("curia1reps_1864", "curia2reps_1864",
                                            "curia3reps_1864"))
    if None in (c1, c2, c3) or c1 + c2 + c3 == 0:
        return None
    total = c1 + c2 + c3
    summary = (f"По раскладке Положения о земских учреждениях 1864 года в уездном земском "
               f"собрании {thousands(total)} {plural(total, 'гласный', 'гласных', 'гласных')}: "
               f"от землевладельцев {thousands(c1)}, от "
               f"городских обществ {thousands(c2)}, от сельских обществ {thousands(c3)} — "
               f"{percent(c3, total)} мест.")
    columns = _pick(row, ("curia1reps_1864", "curia2reps_1864", "curia3reps_1864",
                          "peasantrepresentation_1864"))
    return (CATEGORY_ZEMSTVO_1864, "гласные уездного земства по Положению 1864 года",
            1864, 1864, "1864", WORK_ZEMSTVO, summary, columns)


def zemstvo_1883_record(row: dict) -> Optional[tuple]:
    peasants, curia3 = (_num(row.get(k)) for k in ("peasantuglasnye3rdcuria_1883",
                                                  "totaluglasnye3rdcuria_1883"))
    educ, med, total = (_num(row.get(k)) for k in ("zeducexp1883", "zmedicalexp1883",
                                                  "ztotalexp1883"))
    parts = []
    if peasants is not None and curia3:
        parts.append(f"На выборах 1883 года сельские общества избрали в уездное земское "
                     f"собрание {thousands(curia3)} "
                     f"{plural(curia3, 'гласного', 'гласных', 'гласных')}, из них крестьян "
                     f"{thousands(peasants)}")
    if total and educ is not None and med is not None:
        if educ <= total and med <= total:
            parts.append(f"на народное образование ушло {percent(educ, total)} расходов "
                         f"уездного земства, на медицину {percent(med, total)}")
        else:
            parts.append("доли расходов на образование и медицину выходят в пакете больше "
                         "всех расходов — в текст не пересказываются")
    if not parts:
        return None
    summary = ". ".join(p[0].upper() + p[1:] for p in parts) + "."
    if total:
        summary += " Суммы расходов — в extra: единицу пакет не называет."
    columns = _pick(row, ("peasantuglasnye3rdcuria_1883", "totaluglasnye3rdcuria_1883",
                          "zeducexp1883", "zmedicalexp1883", "ztotalexp1883"))
    return (CATEGORY_ZEMSTVO_1883, "земство в 1883 году", 1883, 1883, "1883", WORK_ZEMSTVO,
            summary, columns)


def schools_record(row: dict) -> Optional[tuple]:
    s1880 = _num(row.get("totalschools1880"))
    if s1880 is None:
        return None
    text = f"В 1880 году в уезде {thousands(s1880)} " + plural(
        s1880, "сельская начальная школа", "сельские начальные школы",
        "сельских начальных школ")
    s1860 = _num(row.get("schools_1860"))
    if s1860 is not None:
        text += f" (в 1860 году — {thousands(s1860)})"
    boys, girls = _num(row.get("boysenrolled1880")), _num(row.get("girlsenrolled1880"))
    if boys is not None and girls is not None:
        text += f"; учащихся мальчиков {thousands(boys)}, девочек {thousands(girls)}"
    columns = _pick(row, ("schools_1860", "totalschools1880", "boysenrolled1880",
                          "girlsenrolled1880", "percenrolledm1880", "percenrolledf1880"))
    return (CATEGORY_SCHOOLS, "сельские школы 1880 года", 1880, 1880, "1880 (сравнение с 1860)",
            None, text + ".", columns)


def communes_record(row: dict) -> Optional[tuple]:
    communes, hhs = _num(row.get("communes_1893")), _num(row.get("communehhs_1893"))
    if communes is None or hhs is None:
        return None
    text = (f"В 1893 году в уезде {thousands(communes)} "
            f"{plural(communes, 'сельское общество', 'сельских общества', 'сельских обществ')}")
    settlements = _num(row.get("communesettlements_1893"))
    if settlements:
        text += f" в {thousands(settlements)} " + plural(settlements, "селении", "селениях",
                                                         "селениях")
    text += f", {thousands(hhs)} {plural(hhs, 'двор', 'двора', 'дворов')}"
    landless = _num(row.get("communelandlesshhs_1893"))
    if landless is not None and hhs > 0:
        text += f", из них безземельных {thousands(landless)} ({percent(landless, hhs)})"
    columns = _pick(row, ("communes_1893", "communesettlements_1893", "communehhs_1893",
                          "communelandlesshhs_1893"))
    return (CATEGORY_COMMUNES, "сельские общества в 1893 году", 1893, 1893, "1893", None,
            text + ".", columns)


BUILDERS = (serfs_record, redemption_record, zemstvo_1864_record, zemstvo_1883_record,
            schools_record, communes_record)


def reforms_records(variables: Iterable[dict], places: Places) -> list[ContextRecord]:
    out = []
    for row in variables:
        mid = _int(row.get("masterid"))
        if mid is None:
            continue
        place = places.get(mid)
        for builder in BUILDERS:
            built = builder(row)
            if built is None:
                continue
            category, what, y0, y1, period, work, summary, columns = built
            extra = _extra(place, mid, places.latin(mid), columns)
            lat, lon = _num(row.get("latitude")), _num(row.get("longitude"))
            if lat is not None and lon is not None:
                # Координата уезда в пакете — для сверки, не для карты.
                extra["uezd_lat_lon"] = [round(lat, 5), round(lon, 5)]
            out.append(REFORMS_UEZD.new_record(
                title=f"{place.head}: {what}",
                category=category,
                scope=SCOPE_REGION,
                place_text=place.place_text,
                region=place.province,
                regions=[place.province] if place.province else [],
                district=place.district,
                year_from=y0, year_to=y1, date_precision="year", period_raw=period,
                work=work,
                summary=summary,
                url=DATASET_URL,
                source_id=f"{mid}:{category}",
                confidence=place.confidence,
                extra=extra,
            ))
    return out
