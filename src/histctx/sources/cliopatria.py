"""Границы государств 1600–1885 (Cliopatria, Seshat Global History Databank).

Зачем этот слой. CShapes (`cshapes.py`) отвечает, гражданином какого
государства был предок, но начинается с 1886 года — а ревизские сказки,
первые метрические книги и вся история западных губерний лежат раньше.
Вильно до 1795 года — Речь Посполитая, Бессарабия до 1812-го — Молдавское
княжество под Портой, Крым до 1783-го — ханство, Финляндия до 1809-го —
Швеция. Без этого слоя карта до 1886 года показывает губернии, но не
отвечает, чьё государство вокруг них и в архив какой страны идти.

Набор. Cliopatria — полигоны политий мира с 3400 года до н. э. по 2024 год,
около 14 тысяч строк. У строки — название, годы «с» и «по» включительно,
полигон и ссылки на Википедию и Викиданные: по ним запись проверяется
(условие 4). Шаг строк не постоянный: у России в рамке слоя 82 строки,
от года до десяти лет каждая, и по ним читаются Смута, Переяславская рада,
Ништадтский мир, все три раздела Речи Посполитой, Финляндия 1809 года и
продажа Аляски. Точность ниже, чем у CShapes: год, а не день, и полигон
снят с карт обзорного масштаба. Поэтому с 1886 года первенство за CShapes.

Права. **CC BY 4.0** — файл `LICENSE.md` в самом архиве и карточка записи на
Zenodo. Полигоны выгружаются целиком; цитата и ссылка на запись идут
в выходной файл.

Скачивание. Запись на Zenodo — архив репозитория на 299 МБ, из которых
сам набор — один вложенный zip на 46 МБ, остальное — сканы исходных карт.
Zenodo отдаёт файл из архива по отдельности (`…/container/<путь>`), а в
перечне содержимого пишет его размер и CRC32: сбор берёт только его и
сверяет обе величины. Оба адреса лежат под `/api/records/*/files`, который
robots.txt Zenodo открывает явно; карточку записи сбор не запрашивает,
лицензия сверена по ней руками.

Что отбирается. Строки, пересекающиеся с рамкой 1600–1885 годов, у которых
полигон хоть одной вершиной заходит в охват РИ/СССР (`cshapes.touches_region`,
та же проверка, что у CShapes). Полигоны не обрезаются — по той же причине,
что и у CShapes: обрезанная граница государства врала бы на карте. Годы
строки сохраняются как есть: у Российской империи последняя строка —
1885–1894, и она остаётся такой, а пометка `continues_in` говорит, что
с 1886 года та же граница есть в `state_borders` по дням.

На выходе — GeoJSON в `data/out/boundaries/`: подложка карты, к схеме
контекста не приводится (`docs/HARVEST.md`, раздел «Границы»). Записей слой
не даёт ни одной.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Iterable, Optional

from ..io_formats import feature_collection, write_feature_collection
from ..net import USER_AGENT, fetch_bytes
from ..schema import LayerSpec
from .cshapes import STATE_BORDERS, touches_region

# Версия закреплена: у Cliopatria выходят новые версии, и полигоны в них
# правят. Новая версия — это новый RECORD_ID и новые размер и CRC ниже,
# сверенные руками, а не молча подтянутый «последний».
VERSION = "v0.2.1"
RECORD_ID = "23128623"
DOI = "10.5281/zenodo.23128623"
DOI_URL = f"https://doi.org/{DOI}"
REPO_URL = "https://github.com/Seshat-Global-History-Databank/cliopatria"
ARCHIVE_KEY = "Seshat-Global-History-Databank/cliopatria-v0.2.1.zip"
FILES_API = f"https://zenodo.org/api/records/{RECORD_ID}/files"
CONTAINER_API = f"{FILES_API}/{ARCHIVE_KEY}/container"
MEMBER = "Seshat-Global-History-Databank-cliopatria-5f43337/cliopatria.geojson.zip"
MEMBER_URL = f"{CONTAINER_API}/{MEMBER}"
# Сверено с перечнем содержимого архива 24.10.2026.
MEMBER_SIZE = 46_005_176
MEMBER_CRC = 3_845_452_743
CACHE_NAME = "cliopatria-v0.2.1.geojson.zip"

CITATION = (
    "Bennett J. S., Mutch E., Tollefson A., Chalstrey E., Benam M., Cioni E., "
    "Reddish J., Zsambok J., Levine J., Cook C. J., Francois P., Hoyer D., "
    "Turchin P. «Cliopatria — A geospatial database of world-wide political "
    "entities from 3400BCE to 2024CE». Scientific Data 12, 247 (2025), "
    "doi:10.1038/s41597-025-04516-9; набор — "
    f"Chalstrey E., Bennett J. Cliopatria {VERSION}, Zenodo, doi:{DOI}. CC BY 4.0"
)

# Рамка слоя. Нижняя граница — начало XVII века: лента событий проекта
# начинается с 1619 года, а Смута нужна целиком. Верхняя — год до начала
# CShapes, который датирует границы по дням и с 1886 года точнее.
YEAR_MIN, YEAR_MAX = 1600, 1885

REQUIRED_FIELDS = ("Name", "FromYear", "ToYear", "Type", "Wikipedia", "Wikidata")

# Координаты в наборе — с точностью до миллионных долей градуса, а полигоны
# сняты с карт обзорного масштаба. Три знака — это сто метров, и они вдвое
# уменьшают файл, ничего не меняя в границе, которую можно увидеть.
COORD_DIGITS = 3

STATE_BORDERS_EARLY = LayerSpec(
    slug="state_borders_early",
    title="Границы государств 1600–1885",
    group="admin",
    source="Cliopatria (Seshat Global History Databank), Zenodo",
    license=(
        "CC BY 4.0 (LICENSE.md в архиве и карточка записи на Zenodo): брать "
        "можно всё, со ссылкой — цитата и ссылка в выходном файле"
    ),
    description=(
        "Государственные границы по годам до начала CShapes: 1 187 строк "
        "121 политии, заходящих территорией в охват РИ/СССР, — Московское "
        "царство и империя, Речь Посполитая, Крымское ханство, Швеция, Порта, "
        "грузинские царства, казахские жузы и среднеазиатские ханства. "
        "Отвечает, в каком государстве лежал приход в год ревизии или записи "
        "до 1886 года; точность — год, а не день."
    ),
    url=DOI_URL,
    status="harvested",
    expected_rows=1187,
    gives_records=False,
)

# Названия в наборе английские. Словарь покрывает всё, что попадает в отбор
# версии v0.2.1; незнакомое название идёт как есть. Переводится то, что
# написано, а не то, что имелось в виду: «First Hellenic Republic» у
# Cliopatria тянется до 1907 года, но называть её «Греческим королевством»
# значило бы править источник подписью.
NAMES_RU = {
    "(Alliance between Papal States and Spanish Empire)":
        "(Союз Папской области и Испанской империи)",
    "(Bourbon Kingdom of France)": "(Французское королевство Бурбонов)",
    "(British Empire)": "(Британская империя)",
    "(First French Empire)": "(Первая Французская империя)",
    "(French Directory)": "(Французская республика времён Директории)",
    "(French Third Republic)": "(Третья французская республика)",
    "(Habsburg Monarchy)": "(Габсбургская монархия)",
    "(Holy Roman Empire)": "(Священная Римская империя)",
    "(Second French Empire)": "(Вторая Французская империя)",
    "(Spanish Empire)": "(Испанская империя)",
    "Afsharid Iran": "Иран Афшаридов",
    "Astrakhan Khanate": "Астраханское ханство",
    "Austria-Hungary": "Австро-Венгрия",
    "Austrian Empire": "Австрийская империя",
    "Bessarabia": "Бессарабия",
    "Bourbon Kingdom of France": "Французское королевство Бурбонов",
    "Brandenburg-Prussia": "Бранденбург-Пруссия",
    "British Colonial Empire": "Британская колониальная империя",
    "British Empire": "Британская империя",
    "British Raj": "Британская Индия",
    "Caucasian Imamate": "Северо-Кавказский имамат",
    "Confederation of the Rhine": "Рейнский союз",
    "Crimean Khanate": "Крымское ханство",
    "Denmark-Norway": "Дания-Норвегия",
    "Don Cossacks": "Войско Донское",
    "Duchy of Courland": "Курляндское герцогство",
    "Duchy of Prussia": "Прусское герцогство",
    "Duchy of Warsaw": "Варшавское герцогство",
    "Durrani Dynasty": "Дуррани",
    "Durrani Empire": "Дурранийская держава",
    "Dzungar Khanate": "Джунгарское ханство",
    "Eastern Moghulistan": "Восточный Могулистан",
    "Emirate of Afghanistan": "Афганский эмират",
    "Emirate of Bukhara": "Бухарский эмират",
    "Empire of Japan": "Японская империя",
    "First French Empire": "Первая Французская империя",
    "First Hellenic Republic": "Первая Греческая республика",
    "Free City of Danzig": "Данциг, вольный город",
    "Free City of Krakow": "Краков, вольный город",
    "French Directory": "Французская республика времён Директории",
    "French Indochina": "Французский Индокитай",
    "German Confederation": "Германский союз",
    "German Empire": "Германская империя",
    "Golden Horde": "Золотая Орда",
    "Habsburg Monarchy": "Габсбургская монархия",
    "Holy Roman Empire": "Священная Римская империя",
    "Holy Roman Empire Minor States": "Малые государства Священной Римской империи",
    "Hotaki Dynasty": "Хотаки",
    "Hungarian Nationalists": "Венгерские повстанцы",
    "Iberian Union": "Иберийская уния",
    "Joseon": "Чосон",
    "Kalmyk Khanate": "Калмыцкое ханство",
    "Kashmir and Jammu": "Джамму и Кашмир",
    "Kazakh Khanate": "Казахское ханство",
    "Khanate of Bukhara": "Бухарское ханство",
    "Khanate of Khiva": "Хивинское ханство",
    "Khanate of Kokand": "Кокандское ханство",
    "Khanates of the Caucasus": "Закавказские ханства",
    "Khoshut Khanate": "Хошутское ханство",
    "Kingdom of Georgia": "Грузинское царство",
    "Kingdom of Great Britain": "Королевство Великобритания",
    "Kingdom of Imereti": "Имеретинское царство",
    "Kingdom of Italy": "Королевство Италия",
    "Kingdom of Kakheti": "Кахетинское царство",
    "Kingdom of Kartli": "Картлийское царство",
    "Kingdom of Naples (Napoleonic)": "Неаполитанское королевство (наполеоновское)",
    "Kingdom of Norway": "Королевство Норвегия",
    "Kingdom of Prussia": "Королевство Пруссия",
    "Kingdom of Sardinia": "Сардинское королевство",
    "Kingdom of Serbia": "Королевство Сербия",
    "Kingdom of Spain": "Королевство Испания",
    "Kingdom of Sweden": "Королевство Швеция",
    "Kingdom of the Two Sicilies": "Королевство Обеих Сицилий",
    "Later Jin Dynasty": "Поздняя Цзинь",
    "Li Zicheng": "Ли Цзычэн",
    "Ming Dynasty": "Империя Мин",
    "Mongol Khanate": "Монгольское ханство",
    "Montenegro": "Черногория",
    "Mughal Empire": "Империя Великих Моголов",
    "Muhammad Ali dynasty": "Египет при династии Мухаммеда Али",
    "North German Confederation": "Северогерманский союз",
    "Oirat Confederation": "Ойратский союз",
    "Ottoman Empire": "Османская империя",
    "Poles": "Польские повстанцы",
    "Polish-Lithuanian Commonwealth": "Речь Посполитая",
    "Principality of Abkhazia": "Абхазское княжество",
    "Principality of Bulgaria": "Княжество Болгария",
    "Principality of Guria": "Гурийское княжество",
    "Principality of Mingrelia": "Мегрельское княжество",
    "Principality of Moldavia": "Молдавское княжество",
    "Principality of Svaneti": "Сванетское княжество",
    "Principality of Transylvania": "Трансильванское княжество",
    "Principality of Upper Hungary": "Княжество Верхняя Венгрия",
    "Principality of Wallachia": "Валашское княжество",
    "Pro-Swedish Poland": "Польша сторонников Швеции",
    "Qajar Dynasty": "Каджарский Иран",
    "Qing Dynasty": "Империя Цин",
    "Republic of Genoa": "Генуэзская республика",
    "Republic of Ragusa": "Рагузская республика",
    "Republic of Venice": "Венецианская республика",
    "Russian Empire": "Российская империя",
    "Safavid Dynasty": "Сефевидское государство",
    "Second French Empire": "Вторая Французская империя",
    "Septinsular Republic": "Республика Семи Островов",
    "Serbs": "Сербские повстанцы",
    "Sikh Empire": "Сикхская держава",
    "Sloboda Ukraine": "Слободская Украина",
    "Small Horde": "Малый жуз",
    "Swedish Empire": "Шведская держава",
    "Talpur Dynasty": "Талпуры",
    "Tibet": "Тибет",
    "Tokugawa Shogunate": "Сёгунат Токугава",
    "Tsardom of Russia": "Русское царство",
    "Tümed": "Тумэты",
    "United Kingdoms of Sweden and Norway": "Шведско-норвежская уния",
    "United Principalities of Moldavia and Wallachia":
        "Соединённое княжество Молдавии и Валахии",
    "United States of America": "Соединённые Штаты Америки",
    "Warring States Japan": "Япония периода Сэнгоку",
    "Western Moghulistan": "Западный Могулистан",
    "Zand Dynasty": "Иран Зендов",
    "Zaporozhian Cossacks": "Войско Запорожское",
}

# Названия, по которым отчёт о сборе показывает хронологию русской границы.
# Строк с одним номером, как у CShapes, здесь нет; Викиданные надёжнее
# названия, но у трёх эпох три разных Q-номера.
RUSSIA_WIKIDATA = ("Q186096", "Q34266")   # Русское царство, Российская империя


class CliopatriaError(RuntimeError):
    """Набор не скачался, не сошёлся с ожидаемым или пришёл не в том виде."""


# --- запись на Zenodo ------------------------------------------------------

def fetch_listing(*, timeout: int = 60) -> dict:
    """Перечень содержимого архива: имена, размеры, CRC32 вложенных файлов."""
    raw = fetch_bytes(CONTAINER_API, error=CliopatriaError, timeout=timeout)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise CliopatriaError(f"перечень архива на Zenodo не разбирается: {exc}") from exc


def check_listing(listing: dict) -> list[str]:
    """Расхождения перечня с тем, что записано в коде. Пусто — всё сходится."""
    entries = {e.get("key"): e for e in listing.get("entries") or []}
    got = entries.get(MEMBER)
    if got is None:
        geojsons = sorted(k for k in entries if str(k).endswith(".geojson.zip"))
        return [f"в архиве нет {MEMBER}; похожие: {geojsons or 'нет'}"]
    problems = []
    if got.get("size") != MEMBER_SIZE:
        problems.append(f"размер {got.get('size')}, ожидался {MEMBER_SIZE}")
    if got.get("crc") != MEMBER_CRC:
        problems.append(f"CRC32 {got.get('crc')}, ожидался {MEMBER_CRC}")
    return problems


def download(dest: Path, *, url: str = MEMBER_URL, timeout: int = 600) -> Path:
    """Скачивает вложенный zip кусками, сверяя размер и CRC32. Не сошлось — файла нет."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    crc, size = 0, 0
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, \
                partial.open("wb") as fh:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                crc = zlib.crc32(chunk, crc)
                size += len(chunk)
    except urllib.error.HTTPError as exc:
        partial.unlink(missing_ok=True)
        raise CliopatriaError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise CliopatriaError(f"{url}: сеть недоступна ({getattr(exc, 'reason', exc)})") from exc
    if size != MEMBER_SIZE or crc != MEMBER_CRC:
        partial.unlink(missing_ok=True)
        raise CliopatriaError(f"скачано {size} байт, CRC32 {crc}; ожидалось "
                              f"{MEMBER_SIZE} байт, CRC32 {MEMBER_CRC}")
    partial.replace(dest)
    return dest


def cached(cache_dir: Path) -> Path:
    """Файл из кэша; нет его или он другого размера — скачивается заново."""
    path = Path(cache_dir) / CACHE_NAME
    if path.exists() and path.stat().st_size == MEMBER_SIZE:
        return path
    return download(path)


# --- чтение набора ---------------------------------------------------------

def read_member(path: Path) -> list[dict]:
    """Строки набора из вложенного zip: в нём один GeoJSON, имя меняется от версии."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith(".geojson")]
            if len(names) != 1:
                raise CliopatriaError(f"в архиве ждали один .geojson, лежат: {names}")
            with archive.open(names[0]) as fh:
                data = json.load(fh)
    except zipfile.BadZipFile as exc:
        raise CliopatriaError(f"{path}: не разбирается как zip ({exc})") from exc
    except ValueError as exc:
        raise CliopatriaError(f"{path}: GeoJSON не разбирается ({exc})") from exc
    feats = data.get("features") if isinstance(data, dict) else None
    if not feats:
        raise CliopatriaError(f"{path}: в наборе нет ни одной строки")
    check_fields(feats)
    return feats


def check_fields(feats: list[dict]) -> None:
    """Поля, на которых держится разбор. Нет хоть одного — набор переделали."""
    keys: set = set()
    for feature in feats:
        keys.update(feature.get("properties") or {})
    missing = [f for f in REQUIRED_FIELDS if f not in keys]
    if missing:
        raise CliopatriaError(
            f"в наборе нет обязательных полей {missing}; пришли: {sorted(keys)}. "
            f"Проверьте {REPO_URL} и поправьте разбор."
        )


def overlaps(props: dict, year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> bool:
    """Пересекаются ли годы строки с рамкой слоя (годы набора — включительно)."""
    start, end = props.get("FromYear"), props.get("ToYear")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return start <= year_max and end >= year_min


def select(feats: Iterable[dict], *, year_min: int = YEAR_MIN,
           year_max: int = YEAR_MAX, region_only: bool = True) -> list[dict]:
    """Строки в рамке слоя, приведённые к подписям, понятным читателю файла."""
    out = []
    for feature in feats:
        props = feature.get("properties") or {}
        if not overlaps(props, year_min, year_max):
            continue
        if region_only and not touches_region(feature.get("geometry")):
            continue
        out.append(boundary(feature, year_max=year_max))
    return out


def boundary(feature: dict, *, year_max: int = YEAR_MAX) -> dict:
    """Одна строка набора: русское название, годы, ссылки, связи политий.

    Годы не обрезаются по рамке: строка «1885–1894» остаётся такой, а
    `continues_in` говорит, где та же граница лежит с 1886 года по дням.
    Строки в скобках — у Cliopatria объединения («(British Empire)» — сама
    Британия вместе с владениями); их состав идёт в `components`, а у
    частей — `member_of`, чтобы подложка не рисовала их одну поверх другой
    вслепую.
    """
    props = feature.get("properties") or {}
    name = props.get("Name")
    year_to = props.get("ToYear")
    out = {
        "state": NAMES_RU.get(name, name),
        "state_en": name,
        "year_from": props.get("FromYear"),
        "year_to": year_to,
        "kind": "relation" if props.get("Type") == "RELATION" else "polity",
        "components": _split(props.get("Components")),
        "member_of": _split(props.get("MemberOf")),
        "area_km2": round(props["Area"]) if isinstance(props.get("Area"), (int, float)) else None,
        "wikidata": _wikidata(props.get("Wikidata")),
        "wikipedia": _wikipedia(props.get("Wikipedia")),
        "seshat_id": _split(props.get("SeshatID")),
    }
    if isinstance(year_to, int) and year_to > year_max:
        out["continues_in"] = STATE_BORDERS.slug
    return {
        "type": "Feature",
        "geometry": rounded_geometry(feature.get("geometry")),
        "properties": {k: v for k, v in out.items() if v not in (None, "", [])},
    }


def _split(value) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def _wikidata(value) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return f"https://www.wikidata.org/wiki/{value.strip()}"


def _wikipedia(value) -> Optional[str]:
    """README набора хранит заголовок статьи, а не адрес: адрес собирается здесь."""
    if not isinstance(value, str) or not value.strip():
        return None
    title = value.strip().replace(" ", "_")
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title, safe="_(),'-")


def rounded_geometry(geometry: Optional[dict], digits: int = COORD_DIGITS) -> Optional[dict]:
    """Координаты до `digits` знаков; кольцо, которое округление схлопнуло, — как было.

    Повторы подряд после округления убираются: в GeoJSON соседние одинаковые
    вершины ничего не значат, а файл утяжеляют.
    """
    if not isinstance(geometry, dict):
        return geometry
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        return {"type": kind, "coordinates": [_ring(r, digits) for r in coords]}
    if kind == "MultiPolygon":
        return {"type": kind,
                "coordinates": [[_ring(r, digits) for r in polygon] for polygon in coords]}
    return geometry


def _ring(ring: list, digits: int) -> list:
    out: list = []
    for point in ring:
        q = [round(point[0], digits), round(point[1], digits)]
        if not out or q != out[-1]:
            out.append(q)
    if len(out) < 4:
        return [list(p[:2]) for p in ring]
    return out


def states(feats: Iterable[dict]) -> list[str]:
    """Политии отбора по-русски, по алфавиту — для отчёта о сборе."""
    return sorted({(f.get("properties") or {}).get("state") for f in feats
                   if (f.get("properties") or {}).get("state")})


def untranslated(feats: Iterable[dict]) -> list[str]:
    """Английские названия, которых нет в словаре: новая версия набора их добавит."""
    return sorted({(f.get("properties") or {}).get("state_en") for f in feats} - set(NAMES_RU)
                  - {None})


def collection(feats: list[dict], *, year_min: int = YEAR_MIN,
               year_max: int = YEAR_MAX) -> dict:
    return feature_collection(
        STATE_BORDERS_EARLY.slug, feats,
        license=STATE_BORDERS_EARLY.license, source=STATE_BORDERS_EARLY.source,
        citation=CITATION, url=DOI_URL,
        extra={"period": f"{year_min}–{year_max}", "version": VERSION,
               "continues_in": STATE_BORDERS.slug},
    )


def write(collection_dict: dict, path) -> int:
    """Пишет коллекцию сжатым JSON: у 680 тысяч вершин пробелы — это мегабайт."""
    return write_feature_collection(collection_dict, path, compact=True)
