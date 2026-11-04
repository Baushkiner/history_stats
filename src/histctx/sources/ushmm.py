"""Карта «Энциклопедии лагерей и гетто» USHMM на Project MUSE: точки по томам.

Откуда. «The USHMM Encyclopedia of Camps and Ghettos, 1933–1945» —
многотомный справочник Мемориального музея Холокоста США; с 06.05.2025 он в
открытом доступе на Project MUSE под **CC BY-NC-ND 4.0** (страница серии
`muse.jhu.edu/encyclopedia/ushmm`). К справочнику приложена карта
(`/ushmm/map`): по пять файлов JSON на тома I–V, `?json=vol_N.json`, — ключи
`countries`, `places`, `camp_types`. У места — название, тип и подтип,
страна в нынешних границах, широта, долгота, внутренний номер `_id` и
пометка `ApproximateLocation` у 39 мест с приблизительной точкой. Выгрузка
Excel (`?action=excel`) — то же самое плюс столбец «Location Accuracy»,
который один в один повторяет эту пометку (проверено 04.11.2026), поэтому
сборщик её не берёт.

Тома (замер 04.11.2026, 3 598 мест):

* I — ранние концлагеря, молодёжные лагеря, концлагеря SS и их подлагеря
  (1 079);
* II — гетто на оккупированном востоке Европы (1 131);
* III — лагеря и гетто союзных Германии режимов: Румыния с Транснистрией,
  Венгрия, Виши, Италия (698);
* IV — лагеря и места заключения вермахта, прежде всего военнопленных (554);
* V — места преследования неевреев: транзитные лагеря для поляков,
  места убийства пациентов (136).

Тома VI (рабочие и транзитные лагеря, центры уничтожения — Белжец,
Собибор, Треблинка) и VII на карту ещё не выложены.

Что берётся. Факты: название, тип, страна, точка, номер тома и места — и
ссылка, которая открывает карту на этом месте; со всплывающей карточки
карты читатель переходит к статье. Текст статей не берётся: это изложение
под NC-ND, и раздел `/chapter` к тому же закрыт `robots.txt` для всех.
Раздел `/ushmm/` `robots.txt` не закрывает; ИИ-сборщикам сайт закрыт
целиком, но сборщик проекта ходит с подписью проекта (`net.USER_AGENT`) по
правилам для всех — шесть запросов: `robots.txt` и пять томов.

Дат в данных карты нет — они в статьях. Даты к точкам приводит слой
(`sources/ghettos_camps.py`): гетто — сведением с перечнем ZRBG, лагеря SS
— с перечнем концлагерей по § 42 BEG.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from ..geo import valid_coords
from ..schema import clean_text

MAP_URL = "https://muse.jhu.edu/ushmm/map"
JSON_URL = MAP_URL + "?json=vol_{volume}.json"
ROBOTS_URL = "https://muse.jhu.edu/robots.txt"
ENCYCLOPEDIA_URL = "https://muse.jhu.edu/encyclopedia/ushmm"

LICENSE = (
    "CC BY-NC-ND 4.0 (USHMM Encyclopedia of Camps and Ghettos, открытый доступ на "
    "Project MUSE с 06.05.2025): взяты название, тип и точка со ссылкой на карту; "
    "тексты статей не копируются"
)

VOLUMES = (1, 2, 3, 4, 5)
VOLUME_TITLES = {
    1: "Early Camps, Youth Camps, and Concentration Camps and Subcamps under the "
       "SS-Business Administration Main Office (WVHA)",
    2: "Ghettos in German-Occupied Eastern Europe",
    3: "Camps and Ghettos under European Regimes Aligned with Nazi Germany",
    4: "Camps and Other Detention Facilities under the German Armed Forces",
    5: "Nazi Sites for Racial Persecution, Detention, Resettlement, and Murder of Non-Jews",
}
VOLUME_RU = {
    1: "т. I — концлагеря SS и их подлагеря",
    2: "т. II — гетто на оккупированном востоке Европы",
    3: "т. III — лагеря и гетто союзных Германии режимов",
    4: "т. IV — лагеря и места заключения вермахта",
    5: "т. V — места преследования неевреев",
}

# Число мест в каждом томе — замер 04.11.2026. Разошлось — карту дополнили
# (энциклопедия выкладывает новые тома и статьи по мере выхода): сначала
# посмотреть, что добавилось, потом поправить здесь.
EXPECTED_PLACES = {1: 1079, 2: 1131, 3: 698, 4: 554, 5: 136}

REQUIRED_KEYS = ("Name", "Type", "Latitude", "Longitude", "country", "_id")

# Страны карты, которые целиком или частью лежат на земле империи и СССР.
# Польша — частью: Царство Польское и Белосток в рамке, Краков и Познань нет;
# решает полигон рамки (`frame.py`), а не этот список.
FORMER_USSR = frozenset({"Russia", "Ukraine", "Belarus", "Lithuania", "Latvia",
                         "Estonia", "Moldova"})
COUNTRY_RU = {
    "Russia": "Россия", "Ukraine": "Украина", "Belarus": "Белоруссия",
    "Lithuania": "Литва", "Latvia": "Латвия", "Estonia": "Эстония", "Moldova": "Молдавия",
    "Poland": "Польша", "Finland": "Финляндия", "Germany": "Германия",
    "Austria": "Австрия", "Czechia": "Чехия", "Czech Republic": "Чехия",
    "Hungary": "Венгрия", "Romania": "Румыния", "Slovakia": "Словакия",
    "France": "Франция", "Italy": "Италия", "Netherlands": "Нидерланды",
    "Belgium": "Бельгия", "Luxembourg": "Люксембург", "Norway": "Норвегия",
    "Denmark": "Дания", "Greece": "Греция", "Croatia": "Хорватия", "Serbia": "Сербия",
    "Slovenia": "Словения", "Bosnia and Herz.": "Босния и Герцеговина",
    "Montenegro": "Черногория", "North Macedonia": "Северная Македония",
    "Kosovo": "Косово", "Albania": "Албания", "Bulgaria": "Болгария",
    "United Kingdom": "Великобритания", "Algeria": "Алжир", "Morocco": "Марокко",
    "Tunisia": "Тунис", "Libya": "Ливия", "Egypt": "Египет", "Mali": "Мали",
    "Guinea": "Гвинея", "Chad": "Чад", "Unknown": "страна не указана",
}

# Тип и подтип места — по-русски. Словарь закрытый: при сборе 04.11.2026
# встретились только эти значения. Незнакомое не теряется — идёт в категорию
# как есть, по-английски, и `--check` его перечисляет.
TYPES_RU = {
    "Ghetto": "гетто",
    "Concentration Camp": "концлагерь",
    "Early Concentration Camp": "ранний концлагерь",
    "Youth Camp": "молодёжный лагерь (Jugendschutzlager)",
    "Internment Camp": "лагерь для интернированных",
    "Internment Camp (Internierungslager)": "лагерь для интернированных",
    "Administrative Internment Camp": "лагерь административного интернирования",
    "Forced Labor Camp": "лагерь принудительного труда",
    "Forced Labor Camp (Zwangsarbeitslager)": "лагерь принудительного труда",
    "SS Labor Camp": "трудовой лагерь SS",
    "Transit Camp": "транзитный лагерь",
    "Prisoner of War Camp": "лагерь военнопленных",
    "Prison": "тюрьма",
    "Detention Center": "место заключения",
    "Deportation Center": "пункт депортации",
    "Collection Camp": "сборный лагерь",
    "Refugee Camp": "лагерь беженцев",
    "Hospital Center": "больничный центр",
    "Asylum": "приют",
    "Entrainment Center": "пункт погрузки в эшелоны",
    "Youth/Children's Camp": "детский лагерь",
    "State Security Settlements": "поселение под надзором госбезопасности",
    "NDH Camps": "лагерь Независимого государства Хорватия",
    "KEV Camps": "лагерь KEV (Венгрия)",
    "Group of Foreign Workers (Groupements des Travailleurs Étrangers, GTEs)":
        "группа иностранных рабочих (GTE)",
    "Centers of Assigned Residence (centre de residence assignée)":
        "место принудительного поселения",
    "Confinement Centers (Centres de Séjour Surveillés, CSS)": "центр заключения (CSS)",
    "Confinement Center for “Undesirables” (Centre de Séjour Surveillé pour Indesirables)":
        "центр заключения «нежелательных»",
    "Reception Center (centre d’accueil)": "приёмный центр",
    "Reception Camp (camp d’accueil pour étrangers)": "приёмный лагерь для иностранцев",
    "Provisional Housing Center (centre d’hebergement)": "временный центр размещения",
    "Disciplinary camp (camp disciplinaire)": "дисциплинарный лагерь",
    "Screening Center for Foreigners (centre de criblage pour les étrangers)":
        "фильтрационный центр для иностранцев",
    "Locality of Forced Residence (località di soggiorno obbligatorio)":
        "место принудительного проживания",
    "Wehrmacht Prisoner of War Camp (POW Camp)": "лагерь военнопленных вермахта",
    "Prisoner of War Special Camps": "особый лагерь военнопленных",
    "Frontstammlager": "фронтовой лагерь военнопленных (фронтшталаг)",
    "Tunisia Wehrmacht Camps": "лагерь вермахта в Тунисе",
    "Wehrmacht Disciplinary Facilities": "тюрьма вермахта",
    "Camps and Other Facilities for Civilians": "лагерь для гражданских",
    "Transit Camp for Poles": "транзитный лагерь для поляков",
    "Transit Camp for Poles/Soviets": "транзитный лагерь для поляков и советских граждан",
    "Transit Camp for Poles/Internment Camp": "транзитный лагерь для поляков и интернированных",
    "Detention/Killing Sites for Patients": "место заключения и убийства пациентов",
    "UWZ Resettlement Camp": "переселенческий лагерь UWZ",
    "Penal Camp (Straflager)": "штрафной лагерь",
    "N/A": "место заключения (тип в карте не указан)",
}

SUBTYPES_RU = {
    "Main Camp": "главный лагерь",
    "Subcamp": "подлагерь",
    "Stalag (Mannschaftsstammlager)": "шталаг",
    "Oflag (Offizierlager)": "офлаг",
    "Dulag (Durchgangslager)": "дулаг, пересыльный",
    "Dulag (Marine Durchgangslager)": "дулаг флота, пересыльный",
    "AGSSt (Armee-Gefangensammelstelle)": "армейский сборный пункт",
    "Heilag (Heimkehrerlager)": "хайлаг, для репатриируемых",
    "Marlag Milag (Marinelager Marineinterniertenlager)": "марлаг и милаг, флотский",
    "KGL (Kriegsgefangenenlager)": "KGL",
    "Sonderlager": "особый лагерь",
    "Luftwaffe Sonderlager Ost": "особый лагерь люфтваффе «Восток»",
    "KWG (Kriegswehrmachtgefängnis)": "военная тюрьма KWG",
    "WG (Wehrmachtgefängnis)": "тюрьма вермахта WG",
    "WGL (Wehrmachtgefangenenlager)": "лагерь заключённых вермахта WGL",
    "Ilag (Internierungslager)": "илаг, для интернированных",
}

# Подтипы без смысла: «N/A», «Unknown» — в категорию не идут.
EMPTY_SUBTYPES = {"N/A", "Unknown", ""}


class UshmmError(RuntimeError):
    """Том карты не пришёл или устроен не так, как ожидает разбор."""


@dataclass(frozen=True)
class Place:
    """Место с карты энциклопедии: что известно до сведения с перечнями."""

    volume: int
    pid: int                    # `_id` места внутри тома
    name: str
    type: str
    subtype: str
    country: str
    lat: Optional[float]
    lon: Optional[float]
    approximate: bool = False
    notes: Optional[str] = None

    @property
    def key(self) -> str:
        """Устойчивый ключ: том и номер места в нём."""
        return f"ushmm:{self.volume}:{self.pid}"

    @property
    def is_ghetto(self) -> bool:
        return self.type == "Ghetto"

    @property
    def is_ss_camp(self) -> bool:
        """Лагерь системы концлагерей SS — его даты ищутся в перечне BEG."""
        return self.volume == 1


def parse_volume(raw: bytes, volume: int) -> tuple[list[Place], list[str]]:
    """JSON тома — места и перечень того, что не разобралось.

    Сервер объявляет кодировку ISO-8859-1, а отдаёт UTF-8 («Terezín»):
    читается как UTF-8. Место без точки или с точкой, которая не разбирается,
    не выбрасывается: оно идёт в разбор без координат, а в перечень
    проблем — строкой.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UshmmError(f"том {volume}: не разбирается как JSON ({exc})") from exc
    places = payload.get("places") if isinstance(payload, dict) else None
    if not isinstance(places, list) or not places:
        raise UshmmError(f"том {volume}: нет списка places")
    missing = [k for k in REQUIRED_KEYS if not any(k in p for p in places)]
    if missing:
        raise UshmmError(f"том {volume}: ни у одного места нет полей {missing} — формат "
                         "карты поменяли, поправьте разбор, а не подгоняйте его")
    out, problems = [], []
    for item in places:
        name = clean_text(item.get("Name"))
        try:
            pid = int(item.get("_id"))
        except (TypeError, ValueError):
            problems.append(f"том {volume}: место без номера _id: {item!r}"[:200])
            continue
        lat, lon = item.get("Latitude"), item.get("Longitude")
        if valid_coords(lat, lon):
            lat, lon = round(float(lat), 6), round(float(lon), 6)
        else:
            problems.append(f"том {volume}, место {pid} «{name}»: точка не разбирается "
                            f"({lat!r}, {lon!r})")
            lat = lon = None
        out.append(Place(
            volume=volume, pid=pid, name=name or f"место {pid}",
            type=clean_text(item.get("Type")) or "N/A",
            subtype=clean_text(item.get("Subtype")) or "N/A",
            country=clean_text(item.get("country")) or "Unknown",
            lat=lat, lon=lon,
            approximate=str(item.get("ApproximateLocation") or "0") not in ("0", "", "False"),
            notes=clean_text(item.get("notes")),
        ))
    return out, problems


def category(place: Place) -> str:
    """Тип места по-русски: «подлагерь концлагеря», «лагерь военнопленных вермахта: шталаг»."""
    kind = TYPES_RU.get(place.type, place.type)
    sub = place.subtype
    if sub in EMPTY_SUBTYPES:
        return kind
    if place.type == "Concentration Camp" and sub == "Subcamp":
        return "подлагерь концлагеря SS"
    if place.type == "Concentration Camp" and sub == "Main Camp":
        return "концлагерь SS (главный лагерь)"
    return f"{kind}: {SUBTYPES_RU.get(sub, sub)}"


def untranslated(places: list[Place]) -> list[str]:
    """Типы и подтипы, которых нет в словаре, — для `--check`."""
    out = set()
    for p in places:
        if p.type not in TYPES_RU:
            out.add(f"тип «{p.type}»")
        if p.subtype not in EMPTY_SUBTYPES and p.subtype not in SUBTYPES_RU:
            out.add(f"подтип «{p.subtype}»")
    return sorted(out)


def place_url(place: Place) -> str:
    """Ссылка на карту, открытую на месте: том, точка и карточка места.

    Карта сама открывает всплывающую карточку по `open_name`, `open_type` и
    `open_subtype` — тем же параметрам, что она пишет в адрес при щелчке.
    Из карточки читатель переходит к статье энциклопедии.
    """
    params = {"volume": str(place.volume)}
    if place.lat is not None and place.lon is not None:
        params.update(lat=f"{place.lat:.4f}", lng=f"{place.lon:.4f}", zoom="10")
    params["open_name"] = place.name
    params["open_type"] = place.type
    if place.subtype not in EMPTY_SUBTYPES:
        params["open_subtype"] = place.subtype
    return MAP_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def counts_by_country(places: list[Place]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in places:
        out[p.country] = out.get(p.country, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
