"""Население городов 1800–1959 годов: пакет Буггле и Нафцигера.

Пакет воспроизведения к статье J. Buggle, S. Nafziger «The Slow Road from
Serfdom: Labor Coercion and Long-Run Development in the Russian Empire»
(REStat, 2021) на Harvard Dataverse, doi:10.7910/DVN/XQBGEY, CC0 1.0.
Проверено по API 24.10.2026: один файл — архив tar на 26,6 МБ.

Из архива берётся `data/city_pop_panel.dta`: 683 города Европейской России
по срезам 1800, 1850, 1897, 1926, 1939, 1959, 1970, 1979, 1989 и 2002 годов,
координата города, губерния и уезд латиницей. **Названий городов в пакете
нет**, только номер и координата; население — натуральным логарифмом
(`log_pop`). Число восстанавливается как `exp(log_pop)`, округлённое до
целого, и это проверяется на месте: у 363 из 366 городов второй таблицы
пакета (`city_pop_cross_section.dta`, население целыми числами 1897 года)
оно совпадает до человека. Срезы после 1959 года выходят за горизонт
проекта (1960) — числа лежат в `extra`, записей не дают.

Запись — город в год среза: точка (координата города в пакете, два знака
после запятой — до километра), год, население, весь ряд до 1959 года
в описании. 1897, 1926, 1939 и 1959 — годы переписей; 1800 и 1850 — оценки
статьи, их источник в пакете не назван, и категория это говорит.

Название добирается сведением с GeoNames (`settlements`, слой проекта) по
координате, и надёжность записана в `extra["name_match"]`:

* `uezd_town` — в 10 км есть место, чьё название — корень названия уезда
  (Бугуруслан и Бугурусланский уезд): уездный город, надёжно;
* `nearest` — ближайшее место GeoNames не дальше 3 км: надёжно для
  города, хотя у пригородов бывает промах;
* `uncertain` — ближайшее место дальше 3 км, но в пределах 10 км: название
  в заголовок не идёт, запись получает пометку `name_uncertain`;
* `none` — в 10 км нет ничего: город назван своим уездом, пометка та же.

Губерния и уезд — из пакета, сверенные с уездами 1897 года RISTAT
(`uezd_names`); это уезд 1897 года, даже если город существовал раньше.
"""

from __future__ import annotations

import io
import math
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

from ..geo import SpatialIndex
from ..schema import ContextRecord, LayerSpec, clean_text
from .dataverse import DatasetFile
from .reforms_1851 import _clean_cell, plural, thousands
from .uezd_names import NAFZIGER_DISTRICTS, NAFZIGER_PROVINCES, RistatDistricts, latin_key, resolve

DOI = "doi:10.7910/DVN/XQBGEY"
DATASET_URL = "https://doi.org/10.7910/DVN/XQBGEY"
LICENSE_NAME = "CC0 1.0"
LICENSE = ("CC0 1.0 — общественное достояние (карточка набора: CC0 1.0, SPDX CC0-1.0); "
           "ссылка на набор проставляется в каждой записи; названия городов — из GeoNames "
           "(CC BY 4.0, ссылка на GeoNames в extra)")
CITATION = (
    "Buggle, Johannes; Nafziger, Steven. Replication Data for: The Slow Road from Serfdom: "
    f"Labor Coercion and Long-Run Development in the Russian Empire. Harvard Dataverse, V1 "
    f"(2021), {DOI}. CC0 1.0"
)

ARCHIVE = DatasetFile(4446132, "Buggle_Nafziger_Serfdom_Replication.tar", 26628608)
FILES = (ARCHIVE,)
PANEL_MEMBER = "Buggle_Nafziger_Serfdom_Replication/data/city_pop_panel.dta"
CROSS_MEMBER = "Buggle_Nafziger_Serfdom_Replication/data/city_pop_cross_section.dta"

CITY_POPULATION = LayerSpec(
    slug="city_population",
    title="Население городов 1800–1959 годов",
    group="admin",
    source="Harvard Dataverse, пакет Buggle, Nafziger (REStat 2021): население 683 городов "
           "Европейской России; названия — GeoNames",
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=2325,
    description=(
        "683 города Европейской России с координатой и населением по срезам 1800, 1850, 1897, "
        "1926, 1939 и 1959 годов — запись на город и год, в описании весь ряд. Отвечает, "
        "каким был город предка в год записи: уездный городок в три тысячи жителей или "
        "губернский центр, и как он рос между переписями. Названий в пакете нет: они "
        "сведены с GeoNames по координате, надёжность сведения записана в каждой записи."
    ),
)

YEARS = (1800, 1850, 1897, 1926, 1939, 1959)
CENSUS_YEARS = (1897, 1926, 1939, 1959)
HORIZON = 1960

NEAR_KM = 3.0
SEARCH_KM = 10.0
STEM_MIN = 4

REQUIRED = ("city_id", "year", "latitude_city", "longitude_city", "uezd", "province", "log_pop")


class CityPopulationError(RuntimeError):
    """Архив не скачался или устроен не так, как ожидает разбор."""


def read_member(archive: Path, member: str) -> list[dict]:
    """`.dta` из архива пакета — в память, без распаковки на диск."""
    import pandas as pd

    with tarfile.open(archive) as tar:
        try:
            info = tar.getmember(member)
        except KeyError as exc:
            raise CityPopulationError(f"в архиве нет {member}") from exc
        if not info.isfile():
            raise CityPopulationError(f"{member}: не файл")
        data = tar.extractfile(info).read()
    frame = pd.read_stata(io.BytesIO(data), convert_categoricals=False)
    return [{k: _clean_cell(v) for k, v in row.items()} for row in frame.to_dict("records")]


def check_columns(header: Iterable[str]) -> None:
    names = list(header)
    missing = [c for c in REQUIRED if c not in names]
    if missing:
        raise CityPopulationError("city_pop_panel.dta: нет обязательных колонок "
                                  + ", ".join(missing) + "; пришли: " + ", ".join(names[:16]))


def population(log_pop) -> Optional[int]:
    """`log_pop` → число жителей: exp и округление до человека."""
    if log_pop is None:
        return None
    try:
        value = float(log_pop)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    return int(round(math.exp(value)))


def check_against_cross_section(panel: Iterable[dict], cross: Iterable[dict],
                                tolerance: float = 0.02) -> tuple[int, int]:
    """Сколько городов второй таблицы нашлись в панели по координате и сколько
    из них совпали по населению 1897 года до человека."""
    by_coord = {}
    for row in panel:
        if row.get("year") == 1897:
            by_coord[(row.get("latitude_city"), row.get("longitude_city"))] = row
    found = equal = 0
    for row in cross:
        lat, lon = row.get("latitude_city"), row.get("longitude_city")
        if lat is None or lon is None:
            continue
        best = min(by_coord.items(), default=None,
                   key=lambda kv: abs(kv[0][0] - lat) + abs(kv[0][1] - lon))
        if best is None or abs(best[0][0] - lat) + abs(best[0][1] - lon) > tolerance:
            continue
        found += 1
        if population(best[1].get("log_pop")) == row.get("pop1897"):
            equal += 1
    return found, equal


# --- города -------------------------------------------------------------------

def cities(rows: Iterable[dict]) -> dict[int, dict]:
    """city_id → {координата, губерния и уезд латиницей, население по годам}."""
    out: dict[int, dict] = {}
    for row in rows:
        cid = row.get("city_id")
        if cid is None:
            continue
        city = out.setdefault(int(cid), {
            "lat": row.get("latitude_city"), "lon": row.get("longitude_city"),
            "province": clean_text(row.get("province")), "uezd": clean_text(row.get("uezd")),
            "population": {}})
        pop = population(row.get("log_pop"))
        if pop is not None and row.get("year") is not None:
            city["population"][int(row["year"])] = pop
    return dict(sorted(out.items()))


# --- русские названия GeoNames ------------------------------------------------
# Заголовок точки в слое `settlements` — первое кириллическое из альтернативных
# названий `geonamescache`, без языка: у Москвы это «Маскав», у Казани «Казан»,
# у Нижнего Новгорода «Горький». Для названия города этого мало, поэтому
# русское имя берётся из выгрузки альтернативных названий GeoNames по стране
# (`alternatenames/XX.zip`, CC BY 4.0) — там у каждого имени есть язык и флаги
# «основное», «краткое», «разговорное», «историческое».

ALT_NAMES_URL = "https://download.geonames.org/export/dump/alternatenames/{code}.zip"


def countries_by_name() -> dict:
    """«Россия» → «RU»: страна точки в слое `settlements` записана по-русски."""
    from .geonames import COUNTRIES

    return {name: code for code, name in COUNTRIES.items()}


def read_alt_names(lines: Iterable[str], wanted: set) -> dict[str, dict]:
    """Строки `XX.txt` → {geonameid: {"name": основное русское, "historic": […]}}.

    Колонки: id, geonameid, язык, название, основное, краткое, разговорное,
    историческое, с, по. Основным считается `ru` «основное» и не «краткое»,
    затем любое «основное», затем первое не разговорное и не историческое.

    Исторические русские названия идут списком `{"name", "from", "to"}`.
    Годы у них стоят редко (Ленинград 1924–1991), а у английских двойников
    чаще (Tsaritsyn 1589–1925, Stalingrad 1925–1961): если английское
    историческое название сводится с русским по `latin_key`, его годы
    переходят к русскому. Без годов название остаётся в списке, но к году
    записи не прикладывается.
    """
    found: dict[str, list] = defaultdict(list)
    english: dict[str, list] = defaultdict(list)
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 8 or parts[1] not in wanted or parts[2] not in ("ru", "en"):
            continue
        parts += [""] * (10 - len(parts))
        # Знак ударения («Алексе́евка») — не часть названия.
        parts[3] = parts[3].replace("\u0301", "").replace("\u0300", "")
        (found if parts[2] == "ru" else english)[parts[1]].append(parts)
    out = {}
    for gid, names in found.items():
        current = [p for p in names if p[6] != "1" and p[7] != "1"]
        ranked = sorted(current, key=lambda p: (p[4] != "1", p[5] == "1"))
        dated_en = {latin_key(p[3]): (p[8], p[9]) for p in english.get(gid, [])
                    if p[7] == "1" and (p[8] or p[9])}
        historic: dict[str, dict] = {}
        for p in names:
            if p[7] != "1":
                continue
            start, stop = (p[8], p[9]) if (p[8] or p[9]) else dated_en.get(latin_key(p[3]),
                                                                          ("", ""))
            item = {"name": p[3], "from": _year(start), "to": _year(stop)}
            # «Горький» записан дважды — с годами и без: остаётся строка с годами.
            known = historic.get(p[3])
            if known is None or (known["from"] is None and item["from"] is not None):
                historic[p[3]] = item
        historic = list(historic.values())
        out[gid] = {"name": ranked[0][3] if ranked else None, "historic": historic}
    return out


def _year(text: str) -> Optional[int]:
    text = (text or "").strip()
    return int(text[:4]) if text[:4].isdigit() else None


def name_in_year(match: dict, year: int) -> Optional[str]:
    """Историческое название, действовавшее в году записи, если годы известны."""
    for item in match.get("names_historic") or []:
        start, stop = item.get("from"), item.get("to")
        if start is not None and stop is not None and start <= year < stop:
            return item["name"]
    return None


def load_alt_names(paths: Iterable[Path], wanted: set) -> dict[str, dict]:
    import zipfile

    out: dict[str, dict] = {}
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            member = next((n for n in archive.namelist()
                           if n.endswith(".txt") and n != "readme.txt"), None)
            if member is None:
                raise CityPopulationError(f"{path.name}: в архиве нет таблицы названий")
            with archive.open(member) as fh:
                lines = (raw.decode("utf-8", errors="replace") for raw in fh)
                out.update(read_alt_names(lines, wanted))
    return out


def candidate_ids(rows: Iterable[dict], index: SpatialIndex) -> tuple[set, set]:
    """geonameid мест в 10 км от городов панели и их страны (по-русски)."""
    ids, countries = set(), set()
    for city in cities(rows).values():
        if city["lat"] is None or city["lon"] is None:
            continue
        for rec, _ in index.near(float(city["lat"]), float(city["lon"]), SEARCH_KM):
            ids.add(str(rec.source_id))
            countries.add((rec.extra or {}).get("country"))
    return ids, countries - {None}


# --- сведение по координате ---------------------------------------------------------

def name_match(lat: float, lon: float, uezd_latin: Optional[str],
               index: Optional[SpatialIndex], names_ru: Optional[dict] = None) -> dict:
    """Название города по GeoNames и надёжность сведения."""
    if index is None:
        return {"how": "none"}
    near = index.near(lat, lon, SEARCH_KM)
    if not near:
        return {"how": "none"}
    names_ru = names_ru or {}
    uezd_key = latin_key(uezd_latin) if uezd_latin else ""
    for rec, km in near:
        ru = (names_ru.get(str(rec.source_id)) or {}).get("name")
        keys = {latin_key(ru), latin_key((rec.extra or {}).get("name_latin"))} - {""}
        if uezd_key and any(len(k) >= STEM_MIN and uezd_key.startswith(k) for k in keys):
            return _found(rec, km, "uezd_town", names_ru)
    rec, km = near[0]
    return _found(rec, km, "nearest" if km <= NEAR_KM else "uncertain", names_ru)


def _found(rec, km: float, how: str, names_ru: dict) -> dict:
    ru = names_ru.get(str(rec.source_id)) or {}
    latin = (rec.extra or {}).get("name_latin")
    # Без русского имени в выгрузке названий заголовок берёт латинское имя
    # GeoNames, а не кириллицу слоя `settlements`: та бывает не русской.
    match = {"how": how, "name": ru.get("name") or latin or rec.title,
             "name_ru": ru.get("name"), "name_geonames": latin,
             "title_settlements": rec.title, "distance_km": round(km, 2),
             "geonameid": rec.source_id, "url": rec.url}
    if ru.get("historic"):
        match["names_historic"] = ru["historic"]
    return {k: v for k, v in match.items() if v is not None}


SURE = ("uezd_town", "nearest")


def series_text(pops: dict) -> str:
    return "; ".join(f"{y} — {thousands(pops[y])}" for y in YEARS if y in pops)


def name_note(match: dict) -> str:
    how = match.get("how")
    if how == "uezd_town":
        return (f"Название — по GeoNames: место с тем же корнем, что у уезда, "
                f"{_km(match['distance_km'])} от точки набора; сам пакет названий не даёт.")
    if how == "nearest":
        return (f"Название — ближайшее место GeoNames, {_km(match['distance_km'])} от точки "
                "набора; сам пакет названий не даёт.")
    if how == "uncertain":
        return (f"Пакет названий не даёт; ближайшее место GeoNames — {match['name']}, "
                f"{_km(match['distance_km'])} от точки: сведение ненадёжно.")
    return "Пакет названий не даёт, и в 10 км от точки в GeoNames ничего нет."


def historic_note(match: dict) -> str:
    names = []
    for item in match.get("names_historic") or []:
        if item["name"] == match.get("name"):
            continue
        span = ""
        if item.get("from") is not None and item.get("to") is not None:
            span = f" ({item['from']}–{item['to']})"
        names.append(item["name"] + span)
    return f" Прежние названия по GeoNames: {', '.join(names)}." if names else ""


def _km(value: float) -> str:
    """Расстояние с предлогом: «ближе километра», «в 3 км»."""
    return "ближе километра" if value < 1 else f"в {value:.0f} км"


def records(rows: Iterable[dict], districts: Optional[RistatDistricts],
            settlements: Optional[SpatialIndex],
            names_ru: Optional[dict] = None) -> list[ContextRecord]:
    out = []
    for cid, city in cities(rows).items():
        lat, lon = city["lat"], city["lon"]
        if lat is None or lon is None:
            continue
        lat, lon = round(float(lat), 4), round(float(lon), 4)
        province = NAFZIGER_PROVINCES.get(city["province"] or "")
        manual = NAFZIGER_DISTRICTS.get((city["province"], city["uezd"]))
        place = resolve(districts, province or city["province"], city["uezd"], manual=manual)
        match = name_match(lat, lon, city["uezd"], settlements, names_ru)
        sure = match.get("how") in SURE
        name = match.get("name") if sure else None
        pops = city["population"]
        for year in YEARS:
            if year not in pops or year >= HORIZON:
                continue
            census = year in CENSUS_YEARS
            people = pops[year]
            old = name_in_year(match, year) if sure else None
            if old and old != name:
                head = f"{old} (ныне {name})"
            else:
                head = name or f"Город ({place.head})"
            summary = (f"Население в {year} году — {thousands(people)} "
                       f"{plural(people, 'человек', 'человека', 'человек')} "
                       + ("(перепись)." if census else
                          "(оценка статьи; источник в пакете не назван).")
                       + f" Ряд по пакету: {series_text(pops)}. " + name_note(match)
                       + (historic_note(match) if sure else ""))
            extra = {"city_id": cid, "population": {str(y): p for y, p in sorted(pops.items())},
                     "province_latin": city["province"], "uezd_latin": city["uezd"],
                     "name_match": match, "citation": CITATION}
            if place.distr_id:
                extra["ristat_distr_id"] = place.distr_id
                extra["ristat_match"] = place.how
            out.append(CITY_POPULATION.new_record(
                title=f"{head}: население в {year} году",
                category=(f"население города: перепись {year} года" if census
                          else f"население города: {year} год (до переписей)"),
                lat=lat, lon=lon,
                place_text=", ".join(p for p in (name, place.place_text) if p) or None,
                region=place.province,
                district=place.district,
                year_from=year, year_to=year, date_precision="year", period_raw=str(year),
                summary=summary,
                url=DATASET_URL,
                source_id=f"{cid}:{year}",
                confidence="ok" if sure else "name_uncertain",
                extra=extra,
            ))
    return out


def settlements_index(path: Path) -> SpatialIndex:
    """Слой GeoNames проекта (`geojson/settlements.geojson`) как сетка для поиска."""
    from ..io_formats import read_geojson

    return SpatialIndex(read_geojson(path))


def name_stats(recs: Iterable[ContextRecord]) -> dict:
    by_city: dict[int, str] = {}
    for rec in recs:
        by_city[rec.extra["city_id"]] = rec.extra["name_match"]["how"]
    stats: dict[str, int] = defaultdict(int)
    for how in by_city.values():
        stats[how] += 1
    return dict(stats)
