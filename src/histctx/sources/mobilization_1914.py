"""Мобилизация 1914–1916 годов и посевы по уездам: пакет Дауэра и Маркевича.

Пакет воспроизведения к статье P. C. Dower, A. Markevich «Labor Misallocation
and Mass Mobilization: Russian Agriculture during the Great War» (REStat,
2018) на Harvard Dataverse, doi:10.7910/DVN/GJFTDC, CC0 1.0. Проверено по API
24.10.2026.

`LMMM_district_farmtype.tab` (исходник `.dta`) — 4 578 строк: 763 уезда
94 губерний и областей за 1913, 1914 и 1916 годы, каждый уезд двумя строками
— общинные и частные хозяйства. Из 164 колонок в запись идут:

* `mobiliz2` — «Mobilized military draftees in thousands»: призванные из
  уезда, тысяч человек; заполнена в строках 1916 года и одна на уезд
  (`mobiliz0`/`mobiliz1` — то же число, разнесённое на 1913 и 1914 годы
  для регрессии статьи, в запись не идут);
* `rpop1912` — сельское население 1912 года, тысяч человек: знаменатель доли
  призванных;
* `agrains` — посевы четырёх главных хлебов (рожь, пшеница, овёс, ячмень),
  тысяч гектаров, по году и типу хозяйства; в запись идёт сумма двух типов за
  1913 и 1916 годы, когда заполнены обе строки.

Сборов в пакете нет — только площади посевов. Остальное (погода, расстояния,
цены, переменные взаимодействия `mobiliz2*`, фиктивные `y14dprovince*`) —
переменные модели, а не факты; в слой не идут.

Число призванных у 25 уездов отрицательно, у трёх больше трети сельского
населения: `mobiliz2` в пакете — оценка, а не перепись призывников. Такие
записи остаются в слое, но доли в тексте не получают (категория
«оценка неправдоподобна»). Порог — вне отрезка 0–30% сельского населения
1912 года; при медиане 8% это отсекает только явные выбросы.

Уезды названы латиницей с порядковым номером («1. Omskij», «2. Aleksandr»),
губернии — своей транслитерацией («KHar'kovskaya», «S.-Peterburgskaya»).
Сверка с уездами 1897 года RISTAT — `uezd_names`; уезды, созданные после
1897 года (Александровский Архангельской губернии, Иманский, Ольгинский),
пары не находят и остаются с пометкой `district_unmatched`.

Запись — уезд за 1914–1916 годы, охват «уезд внутри губернии», без точки:
координат в пакете нет.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .dataverse import DatasetFile
from .reforms_1851 import plural, read_stata, thousands
from .uezd_names import Place, RistatDistricts, latin_key, resolve

DOI = "doi:10.7910/DVN/GJFTDC"
DATASET_URL = "https://doi.org/10.7910/DVN/GJFTDC"
LICENSE_NAME = "CC0 1.0"
LICENSE = ("CC0 1.0 — общественное достояние (карточка набора: CC0 1.0, SPDX CC0-1.0); "
           "ссылка на набор проставляется в каждой записи")
CITATION = (
    "Dower, Paul Castañeda; Markevich, Andrei. Replication Data for: Labor Misallocation and "
    f"Mass Mobilization: Russian Agriculture during the Great War. Harvard Dataverse, V1 "
    f"(2019), {DOI}. CC0 1.0"
)

PANEL = DatasetFile(2972522, "LMMM_district_farmtype.tab", 3742489, original_size=3349411,
                    local_name="LMMM_district_farmtype.dta")
WEIGHTS = DatasetFile(2889356, "LMMM_weights.tab", 15129)
README = DatasetFile(2889355, "README.pdf", 125299)
FILES = (PANEL, WEIGHTS, README)

MOBILIZATION_1914 = LayerSpec(
    slug="mobilization_1914",
    title="Мобилизация 1914–1916 годов и посевы по уездам",
    group="military",
    source="Harvard Dataverse, пакет Dower, Markevich (REStat 2018): призванные и посевы "
           "по уездам 1913–1916 годов",
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=763,
    description=(
        "763 уезда 94 губерний и областей: сколько тысяч человек призвано из уезда к 1916 году "
        "и какая это доля сельского населения 1912 года, как изменились посевы ржи, пшеницы, "
        "овса и ячменя между 1913 и 1916 годами. Ответ на вопрос «сколько мужчин забрали из "
        "уезда предка» и почему в 1916 году в деревне сеяли меньше. Записи по уезду, без точки."
    ),
)

WORK = "Первая мировая война: мобилизация"
YEAR_FROM, YEAR_TO = 1914, 1916
SHARE_MAX = 0.30

CATEGORY_OK = "мобилизация: призванные и посевы"
CATEGORY_SUSPECT = "мобилизация: оценка числа призванных неправдоподобна"
CATEGORY_NO_DATA = "мобилизация: о призванных данных нет, только посевы"

REQUIRED = ("iddistrict", "district_latin", "province_latin", "commune", "year", "mobiliz2",
            "rpop1912", "agrains")

# Губернии, которые по первому слову названия со справочником 1897 года не
# сводятся: другая транслитерация или единица, которой в 1897 году не было.
PROVINCES_MANUAL = {
    "S.-Peterburgskaya": "Санкт-Петербургская губерния",
    "Oblast' vojska donskogo": "Область Войска Донского",
    "Batumskaya": "Батумская область",
    "Sukhumskij okrug": "Сухумский округ",
    "Zakatal'skij okrug": "Закатальский округ",
    "Kamchatskaya oblast'": "Камчатская область",
    "Sakhalinskaya oblast'": "Сахалинская область",
    "Kutaisskaya": "Кутаисская губерния",
    "Tiflisskaya": "Тифлисская губерния",
    "Terskaya oblast'": "Терская область",
}

# Уезды, которые по ключу не сводятся: опечатки пакета и переименования.
# Значение — (название для записи, название в справочнике 1897 года, губерния
# справочника или None).
DISTRICTS_MANUAL = {
    ("CHernigovskaya", "2. Boranenskij"): ("Борзнянский уезд", "Борзнянский", None),
    ("CHernigovskaya", "6.Kokotovskij"): ("Конотопский уезд", "Конотопский", None),
    ("Podol'skaya", "1. K-Podol'sk"): ("Каменец-Подольский уезд", "Каменец-Подольский", None),
    ("Vologodskaya", "2. Vel.-Ustjugsk."): ("Великоустюгский уезд", "Устюжский", None),
    ("YAroslavskaya", "7. Roman-Borisog"): ("Романово-Борисоглебский уезд",
                                            "Романово-Борисоглебский", None),
    ("Stavropol'skaya", "8. Turkmenskij"): ("Туркменский уезд", "Трухменское", None),
    ("Oblast' vojska donskogo", "3. Donskoj 1-j"): ("Первый Донской округ", "Донской 1-й", None),
    ("Oblast' vojska donskogo", "4. Donskoj 2-j"): ("Второй Донской округ", "Донской 2-й", None),
    ("S.-Peterburgskaya", "1. S.-Peterburgs"): ("Санкт-Петербургский уезд", "Петроградский",
                                               None),
}


class MobilizationError(RuntimeError):
    """Пакет не скачался или устроен не так, как ожидает разбор."""


def check_columns(header: Iterable[str]) -> None:
    names = list(header)
    missing = [c for c in REQUIRED if c not in names]
    if missing:
        raise MobilizationError(f"{PANEL.name}: нет обязательных колонок " + ", ".join(missing)
                                + "; пришли: " + ", ".join(names[:16]))


def _num(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _clean_province(name: str) -> str:
    """«Кутаисская  губерния вкл. Сухумский округ» → «Кутаисская губерния»."""
    return " ".join(name.split(" вкл.")[0].split())


def province_name(latin: Optional[str], index: Optional[RistatDistricts]) -> Optional[str]:
    """Губерния пакета по-русски: ручной словарь, затем первое слово по ключу."""
    text = clean_text(latin)
    if not text:
        return None
    if text in PROVINCES_MANUAL:
        return PROVINCES_MANUAL[text]
    if index is None:
        return None
    key = latin_key(text.split()[0])
    for name in index.provinces.values():
        if latin_key(name.split()[0]) == key:
            return _clean_province(name)
    return None


def locate(province_latin, district_latin, index: Optional[RistatDistricts]) -> Place:
    province = province_name(province_latin, index)
    manual = DISTRICTS_MANUAL.get((clean_text(province_latin), clean_text(district_latin)))
    return resolve(index, province or clean_text(province_latin),
                   _district_label(district_latin), manual=manual)


def _district_label(latin) -> Optional[str]:
    """«10. Plonskij» → «Plonskij»: номер — порядок в своде, а не часть названия."""
    text = clean_text(latin)
    if not text:
        return None
    parts = text.split(".", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        return parts[1].strip() or text
    head = text.split(" ", 1)
    if len(head) == 2 and head[0].isdigit():
        return head[1].strip()
    return text


def by_district(rows: Iterable[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        did = _num(row.get("iddistrict"))
        if did is not None:
            out[int(did)].append(row)
    return dict(sorted(out.items()))


def district_facts(rows: list[dict]) -> dict:
    """Числа уезда из шести строк: призванные, население, посевы по годам."""
    mobilized = [_num(r.get("mobiliz2")) for r in rows if _num(r.get("year")) == 1916]
    mobilized = [m for m in mobilized if m is not None]
    population = [_num(r.get("rpop1912")) for r in rows if _num(r.get("rpop1912")) is not None]
    grains: dict[int, list] = defaultdict(list)
    for r in rows:
        year = _num(r.get("year"))
        if year is not None:
            grains[int(year)].append(_num(r.get("agrains")))
    area = {}
    for year, values in grains.items():
        # Обе строки — общинные и частные хозяйства; без одной из них сумма
        # была бы половиной уезда.
        if len(values) == 2 and all(v is not None for v in values):
            area[year] = sum(values)
    return {"mobilized": max(mobilized) if mobilized else None,
            "rpop1912": population[0] if population else None,
            "grain_area": dict(sorted(area.items()))}


def _round(value: Optional[float]) -> Optional[float]:
    """Колонки `.dta` — float32: 16.922000885 — это 16,922 тыс."""
    return None if value is None else round(value, 3)


def _thousand(value: float) -> str:
    text = f"{value:.1f}".replace(".", ",").replace("-", "−")
    return text[:-2] if text.endswith(",0") else text


def summary(facts: dict) -> tuple[str, str]:
    mob, pop = facts["mobilized"], facts["rpop1912"]
    parts = []
    if mob is None:
        category = CATEGORY_NO_DATA
        parts.append("Сколько человек призвано из уезда, в пакете не указано")
    else:
        share = mob / pop if pop else None
        if share is None or not 0 <= share <= SHARE_MAX:
            category = CATEGORY_SUSPECT
            parts.append(f"Оценка числа призванных из уезда в пакете — {_thousand(mob)} тыс., "
                         "при сельском населении 1912 года "
                         + (f"{_thousand(pop)} тыс." if pop else "неизвестном")
                         + "; такая оценка неправдоподобна и долей не пересказывается")
        else:
            category = CATEGORY_OK
            people = mob * 1000
            shown = f"{100 * share:.1f}".replace(".", ",")
            parts.append(f"К 1916 году из уезда призвано в армию {thousands(people)} "
                         f"{plural(people, 'человек', 'человека', 'человек')} — {shown}% "
                         f"сельского населения 1912 года ({_thousand(pop)} тыс.)")
    area = facts["grain_area"]
    if 1913 in area and 1916 in area:
        a13, a16 = area[1913], area[1916]
        text = (f"посевы ржи, пшеницы, овса и ячменя: {_thousand(a13)} тыс. га в 1913 году, "
                f"{_thousand(a16)} тыс. га в 1916 году")
        if a13 > 0:
            change = 100 * (a16 - a13) / a13
            sign = "+" if change > 0 else "−"
            text += f" ({sign}{abs(change):.0f}%)"
        parts.append(text)
    return category, ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def records(rows: Iterable[dict], index: Optional[RistatDistricts]) -> list[ContextRecord]:
    out = []
    for did, group in by_district(rows).items():
        first = group[0]
        place = locate(first.get("province_latin"), first.get("district_latin"), index)
        facts = district_facts(group)
        category, text = summary(facts)
        extra = {"iddistrict": did, "province_latin": clean_text(first.get("province_latin")),
                 "district_latin": clean_text(first.get("district_latin")),
                 "mobiliz2_thousands": _round(facts["mobilized"]),
                 "rpop1912_thousands": _round(facts["rpop1912"]),
                 "grain_area_thousand_ha": {str(k): round(v, 3)
                                            for k, v in facts["grain_area"].items()},
                 "citation": CITATION}
        if place.distr_id:
            extra["ristat_distr_id"] = place.distr_id
            extra["ristat_match"] = place.how
        out.append(MOBILIZATION_1914.new_record(
            title=f"{place.head}: мобилизация 1914–1916 годов",
            category=category,
            scope=SCOPE_REGION,
            place_text=place.place_text,
            region=place.province,
            regions=[place.province] if place.province else [],
            district=place.district,
            year_from=YEAR_FROM, year_to=YEAR_TO, date_precision="year",
            period_raw="1914–1916 (призванные к 1916 году; посевы 1913 и 1916 годов)",
            work=WORK,
            summary=text,
            url=DATASET_URL,
            source_id=str(did),
            confidence=place.confidence,
            extra={k: v for k, v in extra.items() if v is not None},
        ))
    return out


def load(path: Path) -> list[dict]:
    rows = read_stata(path)
    check_columns(rows[0].keys() if rows else [])
    return rows
