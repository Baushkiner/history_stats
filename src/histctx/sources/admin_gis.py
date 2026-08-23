"""Границы и итоги переписей 1897 и 1926 годов (heiDATA, «Transcultural Empire»).

Зачем этот слой. Сейчас губерния у факта определяется по названию из текста
записи — и всё, что написано непривычно, мимо. С полигонами губерния
определяется по координате, и притом на нужный год: Холмская губерния
существует в 1912-м и не существует в 1897-м.

Второе, ради чего он нужен, — числа. Набор несёт итоги переписи по каждой
губернии: население, город и село, мужчины и женщины, распределение по языку,
вере и сословию (1897) и по народностям (1926). Для записи «венчание в
Кириллове в 1899 году» это ответ на вопрос, среди кого предок жил.

Права. Карточка набора: **CC BY 4.0** — свободное использование с указанием
авторства. Это тот случай, когда права выяснены и разрешают всё; ссылка на
авторов и DOI проставляется в каждый выходной файл и в каждую запись.

Что на выходе:

* `boundaries_1897.geojson` и `boundaries_1926.geojson` — полигоны с полной
  таблицей переписи в свойствах. Это подложка карты, к схеме контекста они не
  приводятся (см. `docs/HARVEST.md`, раздел «Границы»);
* записи схемы с охватом «губерния» — по одной на единицу, с итогами переписи
  в `summary` и полной раскладкой в `extra`.

Оговорка про единицы. Каталог обещал «губернии и уезды», порядок 800. На деле
в наборе 99 единиц за 1897 год и 67 за 1926-й — это губернии, области и
союзные единицы, уездов в нём нет. Оценка исправлена по факту, а не подогнана.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Optional

from ..schema import SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .shapefile import ShapefileError, features, read_dbf, read_shapes

DOI = "doi:10.11588/DATA/10064"
DATASET_URL = f"https://heidata.uni-heidelberg.de/dataset.xhtml?persistentId={DOI}"
FILE_URL = "https://heidata.uni-heidelberg.de/api/access/datafile/{file_id}"

USER_AGENT = (
    "histctx/0.2 (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

CITATION = (
    "Sablin, Ivan; Kuchinskiy, Aleksandr; Korobeinikov, Aleksandr et al. "
    "Transcultural Empire: Geographic Information System of the 1897 and 1926 "
    "General Censuses in the Russian Empire and Soviet Union. heiDATA, "
    f"{DOI}. CC BY 4.0"
)

ADMIN_GIS = LayerSpec(
    slug="admin_1897_gis",
    title="Губернии и области переписей 1897 и 1926 годов",
    group="admin",
    source="heiDATA, «Transcultural Empire» (Гейдельбергский университет)",
    license="CC BY 4.0 — свободно с указанием авторства; ссылка и DOI в каждой записи",
    description=(
        "Полигоны губерний, областей и союзных единиц с итогами переписей: "
        "население, город и село, распределение по языку, вере и сословию в 1897 "
        "году и по народностям в 1926-м. Снимает главное ограничение подбора — "
        "губерния определяется по координате и на нужный год, а не по названию "
        "из текста записи."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=166,
)


@dataclass(frozen=True)
class Census:
    """Одна перепись: файлы в наборе и как читать её таблицу."""

    year: int
    shp_id: int
    dbf_id: int
    name_field: str
    unit_word: str
    # Столбцы, которые описывают саму единицу, а не распределение по группам.
    base_fields: frozenset
    # Разделы распределения: подпись → отбор столбцов.
    sections: tuple


CENSUS_1897 = Census(
    year=1897, shp_id=2087, dbf_id=2083,
    name_field="NAMERUS", unit_word="губерния или область",
    base_fields=frozenset({"NAMERUS", "NAMEENG", "AREAV", "POPALL", "POPCITY",
                           "POPRUR", "POPW", "POPM", "FOREIGNNAT"}),
    sections=(("родной язык", "LAN"), ("вероисповедание", "REL"), ("сословие", "EST")),
)

CENSUS_1926 = Census(
    year=1926, shp_id=2092, dbf_id=2089,
    name_field="NameRUS", unit_word="союзная или автономная единица",
    base_fields=frozenset({"Id", "NameENG", "NameRUS", "AreaV", "PopALL", "PopCITY",
                           "PopRUR", "PopW", "PopM", "Nationalit", "Foreigners"}),
    sections=(("народность", ""),),
)

CENSUSES = {1897: CENSUS_1897, 1926: CENSUS_1926}

# Названия столбцов — латинские сокращения из самого набора. Здесь только те,
# в которых мы уверены; для остальных в подпись идёт код столбца как есть —
# лучше нерасшифрованное «LANTURKIND», чем выдуманный народ. Осторожность тут
# не лишняя: часть столбцов 1926 года переведена на английский машинно, и в
# наборе стоят «Lucky», «Huskies», «Jackie» — угадывать по ним народность
# нельзя, такие подписи так и остаются кодом.
LABELS_1897 = {
    "LANVRUS": "великорусский", "LANLRUS": "малорусский", "LANBELORUS": "белорусский",
    "LANPOLISH": "польский", "LANJEWISH": "еврейский", "LANGERMAN": "немецкий",
    "LANLATVIAN": "латышский", "LANLITHUAN": "литовский", "LANZHMUDSK": "жмудский",
    "LANESTONIA": "эстонский", "LANFINNISH": "финский", "LANKARELIA": "карельский",
    "LANCHUDSKO": "чудской", "LANMOLDOVA": "молдавский", "LANARMENIA": "армянский",
    "LANGEORGIA": "грузинский", "LANIMERETI": "имеретинский", "LANMIGRELI": "мингрельский",
    "LANOSETIN": "осетинский", "LANCHECHEN": "чеченский", "LANCIRCASS": "черкесский",
    "LANKURIN": "кюринский", "LANDARGIN": "даргинский", "LANKURDISH": "курдский",
    "LANTATAR": "татарский", "LANBASHKIR": "башкирский", "LANCHUVASH": "чувашский",
    "LANCHEREMI": "черемисский", "LANMORDOVI": "мордовский", "LANVOTYATS": "вотяцкий",
    "LANZYRYANS": "зырянский", "LANPERMYAT": "пермяцкий", "LANKALMYK": "калмыцкий",
    "LANBURYAT": "бурятский", "LANYAKUT": "якутский", "LANTUNGUS": "тунгусский",
    "LANGILYAK": "гиляцкий", "LANNOGAY": "ногайский", "LANSART": "сартский",
    "LANUZBEK": "узбекский", "LANTAJIK": "таджикский", "LANTURKMEN": "туркменский",
    "LANTURKISH": "турецкий", "LANTARANCH": "таранчинский", "LANTATIAN": "татский",
    "LANCHINEES": "китайский", "LANKOREAN": "корейский", "LANGREEK": "греческий",
    "LANSWEDISH": "шведский", "LANNODATA": "язык не указан",

    "RELORT": "православные", "RELOLDBELI": "старообрядцы",
    "RELARMG": "армяно-григориане", "REL_ARMC": "армяно-католики",
    "RELROMANCA": "католики", "RELLUTHERA": "лютеране", "RELREFORME": "реформаты",
    "RELBAPTIST": "баптисты", "RELMENNONI": "меннониты", "RELANGLICA": "англикане",
    "RELOTHERCH": "прочие христиане", "RELCRIMKA": "караимы", "RELJUDAISM": "иудеи",
    "RELMOHAMME": "магометане", "RELBUDDHLA": "буддисты и ламаиты",
    "RELOTHERNC": "прочие нехристиане",

    "ESTHEREDIT": "дворяне потомственные", "ESTNOBLESP": "дворяне личные и чиновники",
    "ESTCLERGYW": "духовенство с семьями", "ESTHHONCIT": "почётные граждане",
    "ESTMERCHAN": "купцы", "ESTPHILIST": "мещане", "ESTPEASANT": "крестьяне",
    "ESTARMYCOS": "войсковые казаки", "ESTALIENS": "инородцы",
    "ESTFINNISH": "финляндские уроженцы", "ESTNOMEMBE": "вне сословий",
    "ESTNODATA": "сословие не указано",
}

LABELS_1926 = {
    "Russians": "русские", "Ukranians": "украинцы", "Belarus": "белорусы",
    "Poles": "поляки", "Jews": "евреи", "Germans": "немцы", "Latvians": "латыши",
    "Lithuanian": "литовцы", "Estonians": "эстонцы", "Finns": "финны",
    "LeningradF": "ленинградские финны", "Karely": "карелы", "Vepsians": "вепсы",
    "Zyryan": "зыряне", "Permians": "пермяки", "Votyak": "вотяки", "Maris": "марийцы",
    "Mordva": "мордва", "Chuvash": "чуваши", "Tatars": "татары", "Mishary": "мишари",
    "Bashkirs": "башкиры", "Nogai": "ногайцы", "Kalmyks": "калмыки",
    "Buryats": "буряты", "Yakuts": "якуты", "Tunguses": "тунгусы",
    "Samoyeds": "самоеды", "Altai": "алтайцы", "Telengety": "теленгиты",
    "Georgians": "грузины", "Megrelians": "мегрелы", "Abkhazians": "абхазы",
    "Armenians": "армяне", "Ossetians": "осетины", "Chechens": "чеченцы",
    "Ingush": "ингуши", "Kabardians": "кабардинцы", "Balkars": "балкарцы",
    "Karachai": "карачаевцы", "Circassian": "черкесы", "Avars": "аварцы",
    "Dargins": "даргинцы", "Kumyks": "кумыки", "Lezgi": "лезгины",
    "Uzbeks": "узбеки", "Tajiks": "таджики", "Turkmens": "туркмены",
    "Kirghiz": "киргизы", "Karakalpak": "каракалпаки", "Koreans": "корейцы",
    "Chinese": "китайцы", "Greeks": "греки", "Moldovans": "молдаване",
    "Romanians": "румыны", "Cossacks": "казаки",
    # В переписи 1926 года «тюрки» — это учётное название азербайджанцев,
    # а турки-османы шли отдельной строкой. Переводить Turks как «турки»
    # значило бы приписать Закавказью четверть турецкого населения.
    "Turks": "тюрки (азербайджанцы)", "OttomanTur": "турки-османы",
    "Lopar": "лопари", "Kurds": "курды", "Others": "прочие",
}

LABELS = {1897: LABELS_1897, 1926: LABELS_1926}

# Сколько групп называть в описании: три крупнейшие — это уже портрет
# губернии, дальше начинается таблица, которой место в `extra`.
TOP_GROUPS = 3


class HeiDataError(RuntimeError):
    """Набор не скачался или пришёл не в том виде, какого мы ждём."""


def download(file_id: int, *, timeout: int = 180) -> bytes:
    """Забирает один файл набора по его идентификатору в Dataverse."""
    url = FILE_URL.format(file_id=file_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise HeiDataError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HeiDataError(f"{url}: сеть недоступна ({exc.reason})") from exc


def load_census(census: Census, *, cache_dir=None) -> list[dict]:
    """Полигоны с таблицей переписи одной GeoJSON-фичей на единицу."""
    shp = _cached(census.shp_id, f"{census.year}.shp", cache_dir)
    dbf = _cached(census.dbf_id, f"{census.year}.dbf", cache_dir)
    try:
        return features(read_shapes(shp), read_dbf(dbf, "utf-8"))
    except ShapefileError as exc:
        raise HeiDataError(f"перепись {census.year}: {exc}") from exc


def _cached(file_id: int, name: str, cache_dir) -> bytes:
    """Скачанное кладётся рядом: набор весит мегабайты и не меняется с 2015 года."""
    if cache_dir is None:
        return download(file_id)
    path = cache_dir / name
    if path.exists():
        return path.read_bytes()
    data = download(file_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def unit_name(props: dict, census: Census) -> Optional[str]:
    return clean_text(props.get(census.name_field))


def group_columns(props: dict, census: Census, prefix: str) -> list[str]:
    """Столбцы одного раздела: по приставке, кроме описывающих саму единицу."""
    return [k for k in props
            if k not in census.base_fields and (not prefix or k.startswith(prefix))
            and (prefix or not any(k.startswith(p) for _, p in census.sections if p))]


def top_groups(props: dict, columns: Iterable[str], year: int,
               limit: int = TOP_GROUPS) -> list[tuple[str, float]]:
    """Крупнейшие группы раздела: (подпись, число), от большего к меньшему."""
    labels = LABELS.get(year, {})
    rows = []
    for column in columns:
        value = props.get(column)
        if isinstance(value, (int, float)) and value > 0:
            rows.append((labels.get(column, column), float(value)))
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows[:limit]


def build_summary(props: dict, census: Census) -> str:
    """Портрет единицы числами переписи, без пересказа чужих выводов."""
    total = _num(props.get("POPALL") or props.get("PopALL"))
    urban = _num(props.get("POPCITY") or props.get("PopCITY"))
    parts = []
    if total:
        head = f"Перепись {census.year} года: {_thousands(total)} жителей"
        if urban:
            head += f", из них в городах {_share(urban, total)}"
        parts.append(head)
    for title, prefix in census.sections:
        top = top_groups(props, group_columns(props, census, prefix), census.year)
        if not top:
            continue
        listed = ", ".join(
            f"{name} — {_share(value, total)}" if total else f"{name} — {_thousands(value)}"
            for name, value in top
        )
        parts.append(f"{title}: {listed}")
    if not parts:
        return f"Перепись {census.year} года: числа по единице в наборе не заполнены."
    return ". ".join(parts) + "."


def census_records(feats: list[dict], census: Census,
                   spec: LayerSpec = ADMIN_GIS) -> list[ContextRecord]:
    """Записи схемы с охватом «губерния»: без точки, но с перечнем единиц.

    Точку такой записи не дают намеренно: событие относится ко всей губернии,
    и центроид полигона врал бы о месте. Подбор по таким записям идёт по
    названию губернии и годам — см. `histctx.enrich`.
    """
    out = []
    for feature in feats:
        props = feature.get("properties") or {}
        name = unit_name(props, census)
        if not name:
            continue
        out.append(spec.new_record(
            title=f"{name}: итоги переписи {census.year} года",
            category="перепись",
            scope=SCOPE_REGION,
            place_text=name,
            regions=[name],
            year_from=census.year,
            year_to=census.year,
            date_precision="year",
            period_raw=str(census.year),
            summary=build_summary(props, census),
            url=DATASET_URL,
            source_id=f"{census.year}:{name}",
            extra={"census": {k: v for k, v in props.items() if v not in (None, 0)},
                   "citation": CITATION},
        ))
    return out


def boundaries_geojson(feats: list[dict], census: Census) -> dict:
    """FeatureCollection границ: подложка карты, а не слой контекста."""
    return {
        "type": "FeatureCollection",
        "name": f"boundaries_{census.year}",
        "license": ADMIN_GIS.license,
        "source": ADMIN_GIS.source,
        "citation": CITATION,
        "url": DATASET_URL,
        "features": feats,
    }


def write_geojson(collection: dict, path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    return len(collection.get("features") or [])


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _share(part: float, total: Optional[float]) -> str:
    if not total:
        return _thousands(part)
    percent = 100.0 * part / total
    shown = f"{percent:.1f}".rstrip("0").rstrip(".") if percent < 10 else f"{percent:.0f}"
    return f"{shown}%"


def _thousands(value: float) -> str:
    # Неразрывный пробел в разряде тысяч: число не должно рваться переносом
    # строки в карточке слоя. Записан escape-последовательностью намеренно —
    # от обычного пробела в исходнике он неотличим.
    return f"{int(round(value)):,}".replace(",", "\u00a0")
