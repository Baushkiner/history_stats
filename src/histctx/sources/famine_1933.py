"""Голод 1932–1933 годов по районам: пакет Маркевича, Науменко, Цянь (Zenodo)
и потери по районам УССР из набора Rozenas, Zhukov (Harvard Dataverse).

Зачем этот слой. Кураторское событие «Голод 1932–1933 годов» в
`data/curated/state_events.json` знает перечень областей и краёв — и всё.
Для факта «умер весной 1933 года в Бершадском районе» это ответ «в вашей
области был голод»; пакет к статье о причинах голода отвечает точнее: в
1933 году в районе умерло столько-то на тысячу жителей при стольких-то
в 1928-м. Слой даёт голоду район — по всему СССР, а не только по Украине.

Что в пакете (Zenodo, запись 10983057, файл `v3.zip`, проверено 24.10.2026):

* `districts` — 2 020 районов в границах 1934 года по 27 регионам в границах
  1932 года, годы 1928 и 1933: смертность `mortality` (умерших на жителя),
  сельская `rmortality` и городская `umortality`, население, доля городского,
  национальный состав 1926 года, центроид района `xcoord`/`ycoord`.
  `excess_mortality_1933` — ровно `mortality(1933) − mortality(1928)`:
  тождество проверяется кодом до того, как единица попадёт в текст;
* `provinces` — 27 регионов, 1897–2002 годы с пропусками; из неё берутся
  умершие `dead` за 1923–1940 годы и население;
* `czar` — 50 губерний Европейской России за 1871–1914 годы: население и
  умершие по годам, сбор хлебов. Это отдельный слой `mortality_1871_1914`
  (см. ниже), а не часть голода 1932–1933 годов.

Права пакета. Карточка Zenodo: «Other (Attribution)» — использование со
ссылкой на авторов; полного текста условий в карточке нет. Берутся числа,
названия и координаты со ссылкой в каждой записи; сам пакет не выкладывается.

Второй набор — Rozenas, Zhukov, «Mass Repression and Political Loyalty:
Evidence from Stalin's "Terror by Hunger"» (Harvard Dataverse, **CC0 1.0**).
`main_data.Rdata` — объект `SpatialPolygonsDataFrame`: полигоны 386 районов
УССР в границах 1933 года и при них потери от голода `FAMINE_TOTAL`,
`FAMINE_URBAN`, `FAMINE_RURAL`. По статье (с. 7, сноска 5) и приложению
(разд. 4.1) это оценки сверхсмертности из атласа MAPA Украинского научного
института Гарварда (Wolowyna et al. 2016, «Regional variations of 1932–34
famine losses in Ukraine»), пересчитанные авторами в районы 1933 года;
доля потерь у авторов — `FAMINE_TOTAL / (FAMINE_TOTAL + POP1933_TOTAL)`
(`Replication.R`, строка 39). Читается своим разборщиком
(`histctx.sources.rserial`), без R.

Что берётся и как.

* По точке на район пакета (2 020): точка — центроид района, а не место
  события, и запись помечена `confidence="district_centroid"`; где учёт
  смертей заведомо неполон (меньше 5 умерших на тысячу в 1928 или 1933
  году), пометка другая — `registration_gap`. Губерния 1897 года по
  центроиду — в `extra`.
* По записи на регион (27) — умершие по годам из `provinces`, охват
  «регион», без точки.
* По точке на район УССР из набора Rozenas, Zhukov (386) — потери
  1932–1934 годов по оценке MAPA; точка — точка подписи полигона пакета
  `sp`. Полигоны тех же районов идут в подложку
  (`boundaries/famine_1933_ukr_rayons.geojson`).
* Районы двух наборов сводятся по координате: центроид района пакета
  ищется внутри полигона района 1933 года; пара кладётся в `extra` обеих
  записей.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import statistics
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..net import fetch_bytes
from ..io_formats import feature_collection
from ..schema import SCOPE_POINT, SCOPE_REGION, ContextRecord, LayerSpec, clean_text
from .famine_1891 import WORK as WORK_1891
from .famine_1891 import WORK_YEARS as WORK_YEARS_1891
from .famine_1891 import ProvinceIndex
from .ghcn import Provinces, _bounds, _polygons
from .rserial import RDataError, data_frame, proj4, read_rdata, sp_polygons

# --- пакет Маркевича, Науменко, Цянь на Zenodo -----------------------------

ZENODO_RECORD = "10983057"
DOI = "10.5281/zenodo.10983057"
DATASET_URL = f"https://doi.org/{DOI}"
# Список файлов берётся из `/api/records/<id>/files`: этот путь robots.txt
# Zenodo разрешает явно (`Allow: /api/records/*/files`), а карточку записи
# `/api/records/<id>` — нет. Скачивание идёт по тому же разрешённому пути.
FILES_API = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files"
CONTENT_URL = FILES_API + "/{key}/content"

LICENSE = ("Other (Attribution) — так в карточке Zenodo: использование со ссылкой на "
           "авторов, полного текста условий нет; берутся числа, названия и координаты "
           "со ссылкой на пакет в каждой записи, сам пакет не выкладывается")

CITATION = (
    "Markevich, Andrei; Naumenko, Natalya; Qian, Nancy. Replication package for: "
    "The Causes of Ukrainian Famine Mortality, 1932-33. Zenodo, 2024, v3.zip, "
    f"doi:{DOI}. Other (Attribution)"
)


@dataclass(frozen=True)
class ZenodoFile:
    key: str
    size: int
    checksum: str


# В записи два архива, v2.zip и v3.zip; берётся последний. Размер и сумма —
# по `/api/records/10983057/files` 24.10.2026.
ARCHIVE = ZenodoFile("v3.zip", 12818245, "md5:fcc7e3c858a8c04c12e771a49c5f2137")

# Таблицы внутри архива и их размеры: расхождение — повод остановиться.
MEMBERS = {
    "districts": ("v3/districts.dta", 2692949),
    "provinces": ("v3/provinces.dta", 680935),
    "czar": ("v3/czar.dta", 135195),
}

# --- набор Rozenas, Zhukov на Harvard Dataverse ----------------------------

RZ_DOI = "doi:10.7910/DVN/XKMNAO"
RZ_URL = "https://doi.org/10.7910/DVN/XKMNAO"
RZ_API_URL = ("https://dataverse.harvard.edu/api/datasets/:persistentId/"
              f"?persistentId={RZ_DOI}")
RZ_FILE_URL = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"
RZ_LICENSE = ("CC0 1.0 — общественное достояние (карточка набора на Harvard Dataverse: "
              "CC0 1.0, SPDX CC0-1.0); ссылка на набор проставляется в каждой записи")
RZ_SOURCE = ("Harvard Dataverse, набор A. Rozenas, Y. Zhukov к статье «Mass Repression and "
             "Political Loyalty» (APSR 2019); потери — атлас MAPA Украинского научного "
             "института Гарварда")
RZ_CITATION = (
    "Rozenas, Arturas; Zhukov, Yuri. Replication Data for: Mass Repression and Political "
    "Loyalty: Evidence from Stalin's 'Terror by Hunger'. Harvard Dataverse, V1 (2020), "
    f"{RZ_DOI}. CC0 1.0. Famine losses: Wolowyna et al. (2016), HURI MAPA"
)


@dataclass(frozen=True)
class DataverseFile:
    file_id: int
    name: str
    size: int
    md5: str


RZ_MAIN = DataverseFile(3336062, "main_data.Rdata", 5060677, "afe0008006de095483bd0c8fa5cc4157")


class FamineError(RuntimeError):
    """Набор не скачался или устроен не так, как ожидает разбор."""


# --- карточки слоёв ---------------------------------------------------------

# Так же называется событие famine_1932 в data/curated/state_events.json:
# по этому полю записи слоя сводятся с ним.
WORK = "Голод 1932–1933 годов"

FAMINE_1933 = LayerSpec(
    slug="famine_1933",
    title="Голод 1932–1933 годов: смертность по районам СССР",
    group="hardship",
    source=("Zenodo, пакет воспроизведения А. Маркевича, Н. Науменко, Н. Цянь к статье "
            "«The Causes of Ukrainian Famine Mortality, 1932–33» (Review of Economic "
            "Studies); районы УССР — Harvard Dataverse, набор A. Rozenas, Y. Zhukov (CC0)"),
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=2433,
    description=(
        "2 020 районов СССР в границах 1934 года по 27 регионам: смертность 1933 года "
        "на тысячу жителей рядом с 1928-м и разница между ними, сельская и городская "
        "смертность, население; точка — центроид района, а не место события. Отдельно — "
        "27 регионов с числом умерших по годам 1923–1940 и 386 районов УССР в границах "
        "1933 года с потерями от голода 1932–1934 годов по оценке атласа MAPA (набор "
        "Rozenas, Zhukov, CC0), полигоны которых идут в подложку. Даёт голоду район там, "
        "где событие в state_events знает только перечень областей; сводятся по полю work."
    ),
)

MORTALITY_1871_1914 = LayerSpec(
    slug="mortality_1871_1914",
    title="Смертность по губерниям 1871–1914 годов: годы сверхсмертности",
    group="hardship",
    source=("Zenodo, пакет воспроизведения А. Маркевича, Н. Науменко, Н. Цянь, таблица "
            "czar: население и умершие 50 губерний Европейской России по годам"),
    license=LICENSE,
    url=DATASET_URL,
    status="harvested",
    expected_rows=112,
    description=(
        "Годы, когда смертность в губернии поднималась выше своего векового хода: "
        "по 50 губерниям Европейской России за 1871–1914 годы смертность на тысячу "
        "жителей сравнивается с линейным трендом губернии, и год попадает в слой, если "
        "превышение не меньше полутора сигм по всей панели. Голод и холера 1892 года, "
        "холера 1872 и 1910 годов — то, что объясняет обрыв записей в метрической "
        "книге. Записи без точки, охват — губерния."
    ),
)


# --- скачивание и сверка с перечнем ----------------------------------------

def fetch_zenodo_manifest(*, timeout: int = 60) -> list[dict]:
    raw = fetch_bytes(FILES_API, error=FamineError, timeout=timeout)
    try:
        entries = json.loads(raw)["entries"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FamineError(f"ответ Zenodo не разбирается: {exc}") from exc
    return [{"key": e.get("key"), "size": e.get("size"), "checksum": e.get("checksum")}
            for e in entries]


def check_zenodo_manifest(manifest: Iterable[dict]) -> list[str]:
    """Расхождения с перечнем в коде; пустой список — всё сходится."""
    by_key = {m.get("key"): m for m in manifest}
    got = by_key.get(ARCHIVE.key)
    if got is None:
        return [f"{ARCHIVE.key}: в записи Zenodo такого файла нет; есть: "
                + ", ".join(sorted(str(k) for k in by_key))]
    problems = []
    if got.get("size") != ARCHIVE.size:
        problems.append(f"{ARCHIVE.key}: ожидался размер {ARCHIVE.size}, пришёл {got.get('size')}")
    if got.get("checksum") != ARCHIVE.checksum:
        problems.append(f"{ARCHIVE.key}: ожидалась сумма {ARCHIVE.checksum}, "
                        f"пришла {got.get('checksum')}")
    newer = sorted(k for k in by_key if k and k.endswith(".zip") and k > ARCHIVE.key)
    if newer:
        problems.append("в записи появился архив новее: " + ", ".join(newer))
    return problems


def fetch_rz_manifest(*, timeout: int = 60) -> list[dict]:
    raw = fetch_bytes(RZ_API_URL, error=FamineError, timeout=timeout)
    try:
        files = json.loads(raw)["data"]["latestVersion"]["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FamineError(f"ответ Dataverse не разбирается: {exc}") from exc
    out = []
    for item in files:
        data = item.get("dataFile") or {}
        out.append({"id": data.get("id"), "name": item.get("label") or data.get("filename"),
                    "size": data.get("filesize"), "md5": data.get("md5")})
    return out


def check_rz_manifest(manifest: Iterable[dict]) -> list[str]:
    by_id = {m.get("id"): m for m in manifest}
    got = by_id.get(RZ_MAIN.file_id)
    if got is None:
        return [f"{RZ_MAIN.name}: файла с id {RZ_MAIN.file_id} в наборе нет"]
    problems = []
    for key, expected in (("name", RZ_MAIN.name), ("size", RZ_MAIN.size), ("md5", RZ_MAIN.md5)):
        if got.get(key) != expected:
            problems.append(f"{RZ_MAIN.name}: поле {key} — ожидалось {expected}, "
                            f"пришло {got.get(key)}")
    return problems


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def cached_archive(cache_dir: Path, *, timeout: int = 600) -> Path:
    """`v3.zip` из `data/raw/famine_1933`; чего нет — скачивается и остаётся там."""
    path = cache_dir / ARCHIVE.key
    if path.exists() and path.stat().st_size == ARCHIVE.size:
        return path
    data = fetch_bytes(CONTENT_URL.format(key=ARCHIVE.key), error=FamineError, timeout=timeout)
    if "md5:" + _md5(data) != ARCHIVE.checksum:
        raise FamineError(f"{ARCHIVE.key}: контрольная сумма не сошлась ({len(data)} байт)")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def cached_rz(cache_dir: Path, *, timeout: int = 300) -> Path:
    path = cache_dir / RZ_MAIN.name
    if path.exists() and path.stat().st_size == RZ_MAIN.size:
        return path
    data = fetch_bytes(RZ_FILE_URL.format(file_id=RZ_MAIN.file_id), error=FamineError,
                       timeout=timeout)
    if _md5(data) != RZ_MAIN.md5:
        raise FamineError(f"{RZ_MAIN.name}: контрольная сумма не сошлась ({len(data)} байт)")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- чтение таблиц -------------------------------------------------------------

def _plain(value):
    """Число numpy/pandas → int или float Python, NaN → None."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        # Доли в .dta хранятся в float32: седьмой значащей цифры за ними нет,
        # а хвост вида 0.01903347484767437 только раздувает выгрузку.
        return float(f"{value:.7g}")
    if isinstance(value, str):
        return clean_text(value)
    return value


def read_stata_rows(data: bytes) -> list[dict]:
    """`.dta` → строки как словари. pandas уже в зависимостях проекта."""
    import pandas as pd

    frame = pd.read_stata(io.BytesIO(data), convert_categoricals=False)
    columns = list(frame.columns)
    return [{c: _plain(v) for c, v in zip(columns, row)}
            for row in frame.itertuples(index=False, name=None)]


def read_archive(path: Path) -> dict[str, list[dict]]:
    """Три таблицы пакета; размеры членов архива сверяются с перечнем."""
    out = {}
    with zipfile.ZipFile(path) as archive:
        sizes = {info.filename: info.file_size for info in archive.infolist()}
        for name, (member, size) in MEMBERS.items():
            if member not in sizes:
                raise FamineError(f"в архиве нет {member}")
            if sizes[member] != size:
                raise FamineError(f"{member}: ожидался размер {size}, в архиве {sizes[member]}")
            out[name] = read_stata_rows(archive.read(member))
    return out


REQUIRED = {
    "districts": ("district_id", "district_name", "province_id", "province_name", "year",
                  "xcoord", "ycoord", "mortality", "excess_mortality_1933", "rmortality",
                  "umortality", "pop", "rpop", "urbanization", "main_sample"),
    "provinces": ("id", "name", "year", "dead", "pop"),
    "czar": ("gub_id", "gubernia_en", "year", "pop", "dead", "grain", "xcoord", "ycoord"),
    "rz": ("ID", "NAME_1_1933", "NAME_2_1933", "NAME_2_1933_LAT", "ID_2_1933", "LONG", "LAT",
           "FAMINE_TOTAL", "FAMINE_URBAN", "FAMINE_RURAL", "POP1933_TOTAL", "POP1933_URBAN",
           "POP1933_RURAL", "C1926_TOTAL"),
}


def check_columns(header: Iterable[str], what: str) -> None:
    names = list(header)
    missing = [c for c in REQUIRED[what] if c not in names]
    if missing:
        raise FamineError(f"{what}: нет обязательных колонок " + ", ".join(missing)
                          + "; пришли: " + ", ".join(names[:16]))


def read_rz(path: Path) -> tuple[list[dict], dict[str, dict]]:
    """Строки таблицы и полигоны по колонке ID из `main_data.Rdata`."""
    try:
        objects = read_rdata(path.read_bytes())
        data = objects["data"]
        columns = data_frame(data.attr("data"))
        shapes = list(sp_polygons(data))
        crs = proj4(data)
    except (RDataError, KeyError, AttributeError) as exc:
        raise FamineError(f"{RZ_MAIN.name}: {exc}") from exc
    if not crs or "longlat" not in crs:
        raise FamineError(f"{RZ_MAIN.name}: проекция {crs!r}, а ожидались долгота и широта")
    check_columns(columns, "rz")
    keep = REQUIRED["rz"]
    n = len(columns["ID"])
    rows = [{c: _plain(columns[c][i]) for c in keep} for i in range(n)]
    if len(shapes) != n:
        raise FamineError(f"{RZ_MAIN.name}: строк {n}, полигонов {len(shapes)}")
    # Полигоны sp и строки таблицы идут в одном порядке, а ID полигона
    # совпадает с колонкой ID: так проверяется, что порядок не съехал.
    geometry = {}
    for row, (ident, geom) in zip(rows, shapes):
        if str(row["ID"]) != str(ident):
            raise FamineError(f"{RZ_MAIN.name}: строка ID={row['ID']} против полигона {ident}")
        geometry[str(ident)] = geom
    return rows, geometry


# --- числа словами ------------------------------------------------------------

def _thousands(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _per_mille(value: float) -> str:
    """Доля на жителя → «на тысячу» с одним знаком: 0,0473 → «47,3»."""
    return f"{value * 1000:.1f}".replace(".", ",")


def _decimal(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _plural(value: float, one: str, few: str, many: str) -> str:
    n = abs(int(round(value)))
    if 11 <= n % 100 <= 19:
        return many
    last = n % 10
    if last == 1:
        return one
    return few if 2 <= last <= 4 else many


def _people(value: float) -> str:
    return f"{_thousands(value)} {_plural(value, 'человек', 'человека', 'человек')}"


# --- названия --------------------------------------------------------------

# Регионы пакета в границах 1932 года — так, как они названы в таблицах, —
# и полное название для записи. Где кураторское событие famine_1932 называет
# регион, написание взято оттуда же.
REGIONS = {
    "Башкирская АССР": "Башкирская АССР",
    "Беларусь": "Белорусская ССР",
    "Восточная Сибирь": "Восточно-Сибирский край",
    "Дагестанская АССР": "Дагестанская АССР",
    "Дальне-Восточный край": "Дальневосточный край",
    "Западная": "Западная область",
    "Западная Сибирь": "Западно-Сибирский край",
    "Ивановская": "Ивановская Промышленная область",
    "Кабардино-Балкарская нац обл": "Кабардино-Балкарская автономная область",
    "Карачаевская нац обл": "Карачаевская автономная область",
    "Карельская АССР": "Карельская АССР",
    "Крым": "Крымская АССР",
    "Ленинградская": "Ленинградская область",
    "Московская": "Московская область",
    "Нижегородский край": "Нижегородский край",
    "Нижне-Волжский край": "Нижне-Волжский край",
    "Северный край": "Северный край",
    "Северо-Кавказский край": "Северо-Кавказский край",
    "Северо-Осетинская нац обл": "Северо-Осетинская автономная область",
    "Средне-Волжский край": "Средне-Волжский край",
    "Татарская АССР": "Татарская АССР",
    "Украина": "Украинская ССР",
    "Уральская": "Уральская область",
    "ЦЧО": "Центрально-Чернозёмная область",
    "Черкесская нац обл": "Черкесская автономная область",
    "Чечено-Ингушская нац обл": "Чечено-Ингушская автономная область",
    "Якутская АССР": "Якутская АССР",
}

# Области УССР 1933 года в наборе Rozenas, Zhukov — по-украински.
UKR_OBLASTS = {
    "Вінницька": "Винницкая область",
    "Дніпропетровська": "Днепропетровская область",
    "Донецька": "Донецкая область",
    "Київська": "Киевская область",
    "Одеська": "Одесская область",
    "Харківська": "Харьковская область",
    "Чернігівська": "Черниговская область",
}

_ABBREVIATIONS = (
    (" гс", " горсовет"), (" нац окр", " национальный округ"), (" авт обл", " автономная область"),
    (" обл", " область"), (" гор", " (город)"), (" окр", " округ"),
)
_ADJECTIVE_ENDINGS = ("ий", "ой", "ый")


def region_name(raw) -> Optional[str]:
    text = clean_text(raw)
    return REGIONS.get(text, text) if text else None


def district_title(raw) -> Optional[str]:
    """«Янаульский» → «Янаульский район», «Москва гс» → «Москва горсовет».

    Название без слова-единицы — прилагательное — получает «район»; сокращения
    набора раскрываются; всё прочее («Приволжский улус», «Адыгейская АО»)
    остаётся как есть. Точка вместо названия — не название.
    """
    text = clean_text(raw)
    if not text or not any(ch.isalpha() for ch in text):
        return None
    for short, full in _ABBREVIATIONS:
        if text.endswith(short):
            return text[: -len(short)] + full
    first, _, rest = text.partition(" ")
    if first.endswith(_ADJECTIVE_ENDINGS) and (not rest or rest.startswith("(")):
        return f"{first} район" + (f" {rest}" if rest else "")
    return text


# --- районы пакета: точка — центроид -----------------------------------------

CATEGORY_EXCESS = "голод 1933 года: смертность выше 1928-го"
CATEGORY_NO_EXCESS = "смертность 1933 года не выше 1928-го"
CATEGORY_1933_ONLY = "смертность 1933 года без сравнения с 1928-м"
CATEGORY_NO_DATA = "о смертности 1933 года данных нет"

CONFIDENCE_CENTROID = "district_centroid"
CONFIDENCE_GAP = "registration_gap"

# Меньше пяти умерших на тысячу жителей за год не бывает ни у какого
# населения той эпохи: в среднем по районам пакета 1928 года — 19 на тысячу.
# Такое число — неполный учёт смертей, а не здоровый район; запись остаётся
# и получает пометку. Порог проверен на данных: ниже него 23 района, из них
# 16 в Дагестане, которые и статья держит вне основной выборки.
MIN_PLAUSIBLE_RATE = 0.005

# Тождество excess = m1933 − m1928 в данных выполняется до 1,5e-8:
# колонки хранятся в float32.
IDENTITY_TOLERANCE = 1e-6

POINT_NOTE = ("центроид района в границах 1934 года из пакета (xcoord, ycoord) — "
              "место района, а не место события")

DISTRICT_YEAR_COLUMNS = ("mortality", "rmortality", "umortality", "pop", "rpop",
                         "urbanization")


def district_pairs(rows: Iterable[dict]) -> list[tuple[Optional[dict], Optional[dict]]]:
    """Строки 1928 и 1933 годов одного района, в порядке district_id."""
    by_id: dict = {}
    for row in rows:
        year = row.get("year")
        if year not in (1928, 1933):
            continue
        by_id.setdefault(row.get("district_id"), {})[year] = row
    return [(years.get(1928), years.get(1933)) for _, years in sorted(by_id.items())]


def check_identity(pairs: Iterable[tuple[Optional[dict], Optional[dict]]]) -> dict:
    """excess_mortality_1933 = mortality(1933) − mortality(1928) у каждой строки,
    где есть все три числа. Не сошлось — разбор останавливается: единица
    разницы пишется в текст записи, и угадывать её нельзя."""
    checked, worst = 0, 0.0
    for row28, row33 in pairs:
        if not row28 or not row33:
            continue
        excess, m33, m28 = (row33.get("excess_mortality_1933"), row33.get("mortality"),
                            row28.get("mortality"))
        if excess is None or m33 is None or m28 is None:
            continue
        diff = abs(excess - (m33 - m28))
        worst = max(worst, diff)
        checked += 1
        if diff > IDENTITY_TOLERANCE:
            raise FamineError(
                f"район {row33.get('district_id')}: excess_mortality_1933={excess} не равно "
                f"mortality 1933 − 1928 = {m33 - m28}"
            )
    return {"identity_rows": checked, "identity_max_diff": worst}


def district_category(m28: Optional[float], m33: Optional[float],
                      excess: Optional[float]) -> str:
    if m33 is None:
        return CATEGORY_NO_DATA
    if excess is None or m28 is None:
        return CATEGORY_1933_ONLY
    return CATEGORY_EXCESS if excess > 0 else CATEGORY_NO_EXCESS


def district_summary(row28: Optional[dict], row33: dict) -> str:
    m33 = row33.get("mortality")
    m28 = row28.get("mortality") if row28 else None
    excess = row33.get("excess_mortality_1933")
    parts = []
    if m33 is None:
        parts.append("Смертность за 1933 год в наборе не указана")
        if m28 is not None:
            parts.append(f"в 1928 году умерло {_per_mille(m28)} на тысячу жителей")
    else:
        head = f"В 1933 году умерло {_per_mille(m33)} на тысячу жителей"
        if m28 is not None:
            head += f" при {_per_mille(m28)} в 1928-м"
            if excess is not None:
                if excess > 0:
                    head += f": на {_per_mille(excess)} больше"
                elif excess < 0:
                    head += f": на {_per_mille(-excess)} меньше"
                else:
                    head += ": столько же"
        parts.append(head)
        split = []
        if row33.get("rmortality") is not None:
            split.append(f"сельская смертность {_per_mille(row33['rmortality'])}")
        if row33.get("umortality") is not None:
            split.append(f"городская {_per_mille(row33['umortality'])}")
        if split:
            parts.append(", ".join(split))
    pop = row33.get("pop")
    if pop:
        parts.append(f"население района в 1933 году — {_people(pop)}")
    rates = [r for r in (m28, m33) if r is not None]
    if any(r < MIN_PLAUSIBLE_RATE for r in rates):
        parts.append("меньше пяти умерших на тысячу за год — вероятно, учёт смертей неполон")
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def _year_columns(row: Optional[dict]) -> dict:
    if not row:
        return {}
    return {c: row[c] for c in DISTRICT_YEAR_COLUMNS if row.get(c) is not None}


def district_record(row28: Optional[dict], row33: Optional[dict],
                    provinces_1897: Optional[Provinces] = None) -> ContextRecord:
    base = row33 or row28
    district_id = base.get("district_id")
    district = district_title(base.get("district_name"))
    region = region_name(base.get("province_name"))
    m33 = row33.get("mortality") if row33 else None
    m28 = row28.get("mortality") if row28 else None
    excess = row33.get("excess_mortality_1933") if row33 else None
    lat, lon = base.get("ycoord"), base.get("xcoord")

    place = district or f"район без названия (district_id {district_id})"
    place_text = ", ".join(p for p in (place, region) if p)
    rates = [r for r in (m28, m33) if r is not None]
    confidence = (CONFIDENCE_GAP if any(r < MIN_PLAUSIBLE_RATE for r in rates)
                  else CONFIDENCE_CENTROID)

    columns = {
        "district_id": district_id,
        "district_name": base.get("district_name"),
        "province_id": base.get("province_id"),
        "province_name": base.get("province_name"),
        "main_sample": base.get("main_sample"),
        "excess_mortality_1933": excess,
        "1928": _year_columns(row28),
        "1933": _year_columns(row33),
    }
    extra = {
        "famine_1933": {k: v for k, v in columns.items() if v not in (None, {})},
        "point": POINT_NOTE,
        "citation": CITATION,
    }
    if provinces_1897 is not None and lat is not None and lon is not None:
        gub = provinces_1897.region_for(lat, lon)
        if gub:
            extra["province_1897"] = gub

    summary = (district_summary(row28, row33) if row33
               else "Район есть только в строке 1928 года; за 1933 год данных нет.")
    return FAMINE_1933.new_record(
        title=f"{place} ({region}): смертность в голод 1933 года",
        category=district_category(m28, m33, excess),
        lat=lat, lon=lon,
        scope=SCOPE_POINT,
        place_text=place_text,
        region=region,
        district=district,
        year_from=1933, year_to=1933,
        date_precision="year",
        period_raw="1933 (в сравнении с 1928)",
        work=WORK,
        summary=summary,
        url=DATASET_URL,
        source_id=f"district:{district_id}",
        confidence=confidence,
        extra=extra,
    )


def district_records(rows: Iterable[dict],
                     provinces_1897: Optional[Provinces] = None) -> list[ContextRecord]:
    pairs = district_pairs(rows)
    check_identity(pairs)
    return [district_record(r28, r33, provinces_1897) for r28, r33 in pairs]


# --- регионы: умершие по годам ------------------------------------------------

CATEGORY_REGION = "голод 1932–1933 годов: умершие по региону"
REGION_YEARS = (1923, 1940)
SUMMARY_YEARS = (1928, 1932, 1933, 1934)


def region_summary(deaths: dict[int, float], pop1933: Optional[float]) -> str:
    d33, d28 = deaths.get(1933), deaths.get(1928)
    parts = []
    if d33 is None:
        parts.append("Число умерших за 1933 год в наборе не указано")
    else:
        head = f"В 1933 году умерло {_people(d33)}"
        if d28:
            ratio = d33 / d28
            if ratio >= 1.05:
                head += f" — в {_decimal(ratio)} раза больше, чем в 1928-м ({_thousands(d28)})"
            elif ratio <= 0.95:
                head += f" — меньше, чем в 1928-м ({_thousands(d28)})"
            else:
                head += f" — почти столько же, сколько в 1928-м ({_thousands(d28)})"
        parts.append(head)
    others = [f"{year} — {_thousands(deaths[year])}" for year in SUMMARY_YEARS
              if year not in (1928, 1933) and deaths.get(year) is not None]
    if others:
        parts.append("умерших в " + ", ".join(others))
    if pop1933:
        parts.append(f"население в 1933 году — {_people(pop1933)}")
    covered = sorted(deaths)
    if covered:
        parts.append(f"ряд умерших в extra — {len(covered)} лет между {covered[0]} и "
                     f"{covered[-1]} годами")
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def region_records(rows: Iterable[dict]) -> list[ContextRecord]:
    by_name: dict[str, dict] = {}
    for row in rows:
        name = clean_text(row.get("name"))
        if not name:
            continue
        item = by_name.setdefault(name, {"id": row.get("id"), "deaths": {}, "pop": {}})
        year = row.get("year")
        if row.get("dead") is not None and REGION_YEARS[0] <= year <= REGION_YEARS[1]:
            item["deaths"][year] = row["dead"]
        if row.get("pop") is not None:
            item["pop"][year] = row["pop"]
    out = []
    for name, item in by_name.items():
        region = region_name(name)
        deaths = dict(sorted(item["deaths"].items()))
        pop = dict(sorted(item["pop"].items()))
        extra = {
            "famine_1933": {"id": item["id"], "name": name,
                            "dead": {str(y): v for y, v in deaths.items()},
                            "pop": {str(y): v for y, v in pop.items()}},
            "citation": CITATION,
        }
        out.append(FAMINE_1933.new_record(
            title=f"{region}: умершие в голод 1932–1933 годов",
            category=CATEGORY_REGION,
            scope=SCOPE_REGION,
            place_text=f"{region} (в границах 1932 года)",
            region=region,
            regions=[region],
            year_from=1932, year_to=1933,
            date_precision="year",
            period_raw="1932–1933 (ряд 1923–1940)",
            work=WORK,
            summary=region_summary(deaths, pop.get(1933)),
            url=DATASET_URL,
            source_id=f"region:{item['id']}",
            confidence="ok",
            extra=extra,
        ))
    return out


# --- районы УССР: потери по оценке MAPA ---------------------------------------

CATEGORY_RZ = "голод 1932–1934 годов: потери по району УССР (оценка HURI MAPA)"
RZ_POINT_NOTE = ("точка подписи полигона района 1933 года (labpt пакета sp, колонки "
                 "LONG/LAT набора) — место района, а не место события")


def rz_share(row: dict) -> Optional[float]:
    """Доля потерь, как у авторов: потери / (потери + население 1933 года), в %."""
    famine, pop = row.get("FAMINE_TOTAL"), row.get("POP1933_TOTAL")
    if famine is None or pop is None or famine + pop <= 0:
        return None
    return 100 * famine / (famine + pop)


def rz_summary(row: dict) -> str:
    total = row.get("FAMINE_TOTAL")
    parts = []
    if total is None:
        parts.append("Оценки потерь по району в наборе нет")
    else:
        head = (f"Потери от голода 1932–1934 годов по оценке атласа MAPA — {_people(total)}")
        rural, urban = row.get("FAMINE_RURAL"), row.get("FAMINE_URBAN")
        if rural is not None and urban is not None:
            head += f": в сёлах {_thousands(rural)}, в городах {_thousands(urban)}"
        parts.append(head)
        share = rz_share(row)
        if share is not None:
            parts.append(f"{_decimal(share)}% от суммы потерь и населения 1933 года — так "
                         "долю считают авторы набора")
    pop = row.get("POP1933_TOTAL")
    if pop:
        parts.append(f"население района в 1933 году — {_people(pop)}")
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def rz_record(row: dict, pair: Optional[list] = None) -> ContextRecord:
    name = clean_text(row.get("NAME_2_1933"))
    oblast_uk = clean_text(row.get("NAME_1_1933"))
    oblast = UKR_OBLASTS.get(oblast_uk or "", f"{oblast_uk} область" if oblast_uk else None)
    # LONG/LAT — это и есть точка записи; второй раз в extra они не нужны.
    columns = {c: row[c] for c in REQUIRED["rz"]
               if row.get(c) is not None and c not in ("LONG", "LAT")}
    extra = {"famine_1933_rz": columns, "point": RZ_POINT_NOTE, "citation": RZ_CITATION}
    share = rz_share(row)
    if share is not None:
        extra["famine_share_pct"] = round(share, 2)
    if pair:
        extra["mnq_district_ids"] = pair
    place = name or f"район без названия (ID {row.get('ID')})"
    return FAMINE_1933.new_record(
        title=f"{place} ({oblast}, УССР): потери от голода 1932–1934 годов",
        category=CATEGORY_RZ,
        lat=row.get("LAT"), lon=row.get("LONG"),
        scope=SCOPE_POINT,
        place_text=f"{place}, {oblast_uk} область, УССР (границы 1933 года)",
        region=oblast,
        district=name,
        year_from=1932, year_to=1934,
        date_precision="year",
        period_raw="1932–1934",
        work=WORK,
        summary=rz_summary(row),
        url=RZ_URL,
        source=RZ_SOURCE,
        license=RZ_LICENSE,
        source_id=f"rz:{row.get('ID')}",
        confidence=CONFIDENCE_CENTROID,
        extra=extra,
    )


# --- сведение двух наборов -------------------------------------------------

class RayonIndex:
    """Районы УССР 1933 года по полигонам: точка → ID района набора RZ.

    Точка в полигоне считается тем же лучом, что губерния станции погоды
    (`ghcn.Provinces`): своего геометрического кода здесь нет.
    """

    def __init__(self, geometry: dict[str, dict]) -> None:
        areas = []
        for ident, geom in geometry.items():
            polygons = _polygons(geom)
            if polygons:
                areas.append((ident, polygons, _bounds(polygons)))
        self._index = Provinces(areas)

    def find(self, lat: Optional[float], lon: Optional[float]) -> Optional[str]:
        if lat is None or lon is None:
            return None
        return self._index.region_for(lat, lon)


# Грубый ключ названия: первые три согласных после сведения украинских букв
# к русским. «Чечільницький» и «Чечельникский» — «ччл», «Бершадський» и
# «Бершадский» — «брш». Пару он не задаёт — её задаёт координата; ключ
# нужен отчёту о сверке и второму проходу, который разводит районы,
# попавшие центроидом в соседний полигон.
_UK_TO_RU = str.maketrans({"і": "и", "ї": "и", "є": "е", "ґ": "г", "ы": "и", "ё": "е",
                           "э": "е", "'": "", "ʼ": "", "’": ""})
_VOWELS = set("аеиоуюяйьъ")


def name_key(text: Optional[str]) -> str:
    if not text:
        return ""
    word = text.lower().translate(_UK_TO_RU).replace("им. ", "").split(" ")[0]
    consonants = [ch for ch in word if ch.isalpha() and ch not in _VOWELS]
    return "".join(consonants[:3])


def match_datasets(districts: Iterable[ContextRecord], rz_rows: Iterable[dict],
                   index: RayonIndex) -> dict:
    """Районы пакета (границы 1934 года) против районов RZ (1933 года).

    Первый проход — координата: центроид района пакета ищется внутри
    полигона района RZ. Границы 1933 и 1934 годов не совпадают, и бывает,
    что центроид ложится в соседний полигон, а свой район остаётся без пары.
    Второй проход это разводит: район RZ без пары забирает район пакета с тем
    же ключом названия из полигона, куда легли несколько районов, — если
    кандидат ровно один и хозяину полигона он по названию не пара.

    Записи района пакета получают пару в `extra["rz_rayon"]` с пометкой,
    каким проходом она найдена; возвращаются пары и счётчики для отчёта.
    """
    rz_by_id = {str(r["ID"]): r for r in rz_rows}
    ukr = [r for r in districts if r.region == REGIONS["Украина"]]
    by_district = {r.extra["famine_1933"].get("district_id"): r for r in ukr}
    assigned: dict = {}
    outside = []
    for district_id, rec in by_district.items():
        ident = index.find(rec.lat, rec.lon)
        if ident is None:
            outside.append(rec)
        else:
            assigned[district_id] = (ident, "coordinate")

    def hosts() -> dict[str, list]:
        out: dict[str, list] = {}
        for district_id, (ident, _) in assigned.items():
            out.setdefault(ident, []).append(district_id)
        return out

    def mnq_key(district_id) -> str:
        return name_key(by_district[district_id].extra["famine_1933"].get("district_name"))

    def rz_key(ident) -> str:
        return name_key(rz_by_id[ident].get("NAME_2_1933"))

    by_name = 0
    for ident in sorted(set(rz_by_id) - set(hosts()), key=int):
        key = rz_key(ident)
        candidates = [did for host, dids in hosts().items() if len(dids) > 1
                      for did in dids if mnq_key(did) == key and rz_key(host) != key]
        if len(candidates) == 1:
            assigned[candidates[0]] = (ident, "name")
            by_name += 1

    by_rz = hosts()
    for district_id, (ident, method) in assigned.items():
        rz = rz_by_id.get(ident, {})
        by_district[district_id].extra["rz_rayon"] = {
            "ID": rz.get("ID"), "NAME_2_1933": rz.get("NAME_2_1933"),
            "FAMINE_TOTAL": rz.get("FAMINE_TOTAL"), "matched_by": method,
        }
    one_to_one = {k: v[0] for k, v in by_rz.items() if len(v) == 1}
    names_agree = sum(1 for ident, did in one_to_one.items() if mnq_key(did) == rz_key(ident))
    return {
        "mnq_ukraine": len(ukr),
        "mnq_inside": len(ukr) - len(outside),
        "mnq_outside": [r.district for r in outside],
        "rz_total": len(rz_by_id),
        "rz_matched": len(by_rz),
        "rz_one_to_one": len(one_to_one),
        "rz_by_name": by_name,
        "rz_many": {k: v for k, v in by_rz.items() if len(v) > 1},
        "rz_unmatched": sorted(set(rz_by_id) - set(by_rz), key=int),
        "names_agree": names_agree,
        "pairs": by_rz,
    }


def rz_records(rows: Iterable[dict], pairs: Optional[dict] = None) -> list[ContextRecord]:
    pairs = pairs or {}
    return [rz_record(row, pairs.get(str(row["ID"]))) for row in rows]


def boundaries_geojson(geometry: dict[str, dict], records: Iterable[ContextRecord],
                       digits: int = 6) -> dict:
    """Полигоны 386 районов УССР 1933 года со свойствами из записей RZ."""
    by_id = {r.source_id.split(":", 1)[1]: r for r in records
             if r.source_id and r.source_id.startswith("rz:")}
    feats = []
    for ident, geom in geometry.items():
        rec = by_id.get(ident)
        if rec is None:
            continue
        cols = rec.extra["famine_1933_rz"]
        props = {
            "ID": cols.get("ID"),
            "ID_2_1933": cols.get("ID_2_1933"),
            "rayon": cols.get("NAME_2_1933"),
            "rayon_lat": cols.get("NAME_2_1933_LAT"),
            "oblast_1933": cols.get("NAME_1_1933"),
            "oblast_ru": rec.region,
            "famine_total": cols.get("FAMINE_TOTAL"),
            "famine_rural": cols.get("FAMINE_RURAL"),
            "famine_urban": cols.get("FAMINE_URBAN"),
            "pop1933_total": cols.get("POP1933_TOTAL"),
            "famine_share_pct": rec.extra.get("famine_share_pct"),
            "c1926_total": cols.get("C1926_TOTAL"),
            "mnq_district_ids": rec.extra.get("mnq_district_ids"),
        }
        feats.append({"type": "Feature", "id": rec.uid,
                      "geometry": _rounded(geom, digits),
                      "properties": {k: v for k, v in props.items() if v is not None}})
    return feature_collection(
        "famine_1933_ukr_rayons", feats,
        license=RZ_LICENSE, source=RZ_SOURCE, citation=RZ_CITATION, url=RZ_URL,
        extra={"period": "1932–1934", "borders": "районы УССР на 1933 год"},
    )


def _rounded(geom: dict, digits: int) -> dict:
    def ring(points):
        return [[round(x, digits), round(y, digits)] for x, y in points]

    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(r) for r in geom["coordinates"]]}
    return {"type": "MultiPolygon",
            "coordinates": [[ring(r) for r in poly] for poly in geom["coordinates"]]}


# --- губернии 1871–1914: годы сверхсмертности -------------------------------

# Губернии таблицы czar записаны транслитом в стиле RISTAT, с приписками
# вроде «after1851» — годом, с которого считаются границы. Закрытый словарь:
# чего здесь нет, остаётся латиницей с пометкой region_unmatched.
CZAR_PROVINCES = {
    "Arkhangelskaya": "Архангельская губерния",
    "Astrakhanskayaafter1851": "Астраханская губерния",
    "Bessarabskaya": "Бессарабская губерния",
    "Chernigovskaya": "Черниговская губерния",
    "Donskoe Voysko": "Область Войска Донского",
    "Ekaterinoslavskaya": "Екатеринославская губерния",
    "Estlyandskaya": "Эстляндская губерния",
    "Grodnenskayaafter1843": "Гродненская губерния",
    "Kaluzhskaya": "Калужская губерния",
    "Kazanskaya": "Казанская губерния",
    "Kharkovskayaafter1835": "Харьковская губерния",
    "Khersonskaya": "Херсонская губерния",
    "Kievskaya": "Киевская губерния",
    "Kostromskaya": "Костромская губерния",
    "Kurlyandskaya": "Курляндская губерния",
    "Kurskaya": "Курская губерния",
    "Liflyandskaya": "Лифляндская губерния",
    "Minskayafter1843": "Минская губерния",
    "Mogilevskaya": "Могилевская губерния",
    "Moskovskaya": "Московская губерния",
    "Nizhegorodskaya": "Нижегородская губерния",
    "Novgorodskaya": "Новгородская губерния",
    "Olonetskaya": "Олонецкая губерния",
    "Orenburgskayafter1851": "Оренбургская губерния",
    "Orlovskaya": "Орловская губерния",
    "Penzenskaya": "Пензенская губерния",
    "Permskaya": "Пермская губерния",
    "Podolskaya": "Подольская губерния",
    "Poltavskaya": "Полтавская губерния",
    "Pskovskaya": "Псковская губерния",
    "Ryazanskaya": "Рязанская губерния",
    "Samarskaya": "Самарская губерния",
    "Sankt Peterburgskaya": "Санкт-Петербургская губерния",
    "Saratovskayaafter1851": "Саратовская губерния",
    "Simbirskayaafter1851": "Симбирская губерния",
    "Smolenskaya": "Смоленская губерния",
    "Tambovskaya": "Тамбовская губерния",
    "Tavricheskayaafter1820": "Таврическая губерния",
    "Tulskaya": "Тульская губерния",
    "Tverskaya": "Тверская губерния",
    "Ufimskaya": "Уфимская губерния",
    "Vilenskayafdter1843": "Виленская губерния",
    "Vitebskaya": "Витебская губерния",
    "Vladimirskaya": "Владимирская губерния",
    "Volhynskaya": "Волынская губерния",
    "Vologodskaya": "Вологодская губерния",
    "Voronezhskayaafter1824": "Воронежская губерния",
    "Vyatskaya": "Вятская губерния",
    "Yaroslavskaya": "Ярославская губерния",
    "kovenskaya": "Ковенская губерния",
}

CATEGORY_CZAR = "сверхсмертность за год по губернии"
SIGMA_FACTOR = 1.5


def czar_rate(row: dict) -> Optional[float]:
    """Умерших на тысячу жителей. Ноль умерших — пропуск, а не ноль смертей:
    таких строк три (Гродненская и Воронежская 1871, Минская 1879), и
    в тренд они не идут."""
    dead, pop = row.get("dead"), row.get("pop")
    if not dead or not pop:
        return None
    return dead / pop * 1000


def czar_gaps(rows: Iterable[dict]) -> list[dict]:
    """Строки с нулём умерших — чтобы показать их в проверке, а не терять молча."""
    return [r for r in rows if r.get("dead") == 0]


def czar_residuals(rows: Iterable[dict]) -> dict[tuple, dict]:
    """По губернии — линейный тренд смертности 1871–1914 годов; по строке —
    ожидаемое по тренду и превышение над ним, на тысячу жителей."""
    by_gub: dict[str, list] = {}
    for row in rows:
        rate = czar_rate(row)
        if rate is not None:
            by_gub.setdefault(row["gubernia_en"], []).append((row, rate))
    out = {}
    for gub, items in by_gub.items():
        if len(items) < 3:
            continue
        fit = statistics.linear_regression([r["year"] for r, _ in items],
                                           [rate for _, rate in items])
        for row, rate in items:
            expected = fit.slope * row["year"] + fit.intercept
            out[(gub, row["year"])] = {"row": row, "rate": rate, "expected": expected,
                                       "excess": rate - expected}
    return out


def czar_threshold(residuals: dict) -> tuple[float, float]:
    sigma = statistics.stdev(v["excess"] for v in residuals.values())
    return sigma, SIGMA_FACTOR * sigma


def czar_summary(item: dict, threshold: float) -> str:
    row = item["row"]
    return (
        f"Умерло {_decimal(item['rate'])} на тысячу жителей при {_decimal(item['expected'])} "
        f"по тренду губернии за 1871–1914 годы: на {_decimal(item['excess'])} больше "
        f"(в слой идут годы с превышением от {_decimal(threshold)} — полутора сигм по всей "
        f"панели). Умерших {_thousands(row['dead'])} при населении {_people(row['pop'])}."
    )


def czar_records(rows: Iterable[dict], index: Optional[ProvinceIndex] = None
                 ) -> tuple[list[ContextRecord], dict]:
    rows = list(rows)
    residuals = czar_residuals(rows)
    sigma, threshold = czar_threshold(residuals)
    out = []
    for (gub, year), item in sorted(residuals.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if item["excess"] < threshold:
            continue
        province = CZAR_PROVINCES.get(gub)
        known = index.find(province) if (index is not None and province) else province
        confidence = "ok" if known else "region_unmatched"
        name = province or gub
        row = item["row"]
        extra = {
            "czar": {k: row[k] for k in REQUIRED["czar"] if row.get(k) is not None},
            "rate_per_1000": round(item["rate"], 3),
            "expected_per_1000": round(item["expected"], 3),
            "excess_per_1000": round(item["excess"], 3),
            "sigma": round(sigma, 4),
            "threshold": round(threshold, 4),
            "citation": CITATION,
        }
        if known and known != province:
            extra["province_1897"] = known
        work = WORK_1891 if WORK_YEARS_1891[0] <= year <= WORK_YEARS_1891[1] else None
        out.append(MORTALITY_1871_1914.new_record(
            title=f"{name}, {year}: смертность выше обычной",
            category=CATEGORY_CZAR,
            scope=SCOPE_REGION,
            place_text=name,
            region=name,
            regions=[name],
            year_from=year, year_to=year,
            date_precision="year",
            period_raw=str(year),
            work=work,
            summary=czar_summary(item, threshold),
            url=DATASET_URL,
            source_id=f"czar:{row.get('gub_id')}:{year}",
            confidence=confidence,
            extra=extra,
        ))
    stats = {"rows": len(residuals), "sigma": sigma, "threshold": threshold,
             "gaps": czar_gaps(rows)}
    return out, stats
