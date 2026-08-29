"""Границы губерний и уездов 1897 года (RISTAT, IISH Amsterdam).

Чего не хватало. Набор heiDATA (`admin_gis.py`) даёт 99 губерний с итогами
переписи — но не даёт уездов, а уезд для генеалогии и есть рабочая единица:
в уезде лежит фонд консистории, по уезду ищется приход. Здесь уезды есть:
824 полигона на 1897 год плюс 103 губернии, все в WGS 84.

Права. Карточка набора в Dataverse IISH: **CC0** — общественное достояние.
Авторы отдельно просят ссылаться на «Electronic Repository of Russian
Historical Statistics», и это просьба, а не условие лицензии; ссылка всё
равно проставляется — по условию 4 «Каталога открыт» (проверяемость)
она нужна нам самим.

На выходе — GeoJSON с полигонами: к схеме контекста границы не приводятся,
это подложка карты (`docs/HARVEST.md`, раздел «Границы»). Переписные числа
к ним не подмешиваются: у RISTAT они лежат отдельными таблицами и своим
разбором, а выдавать пустой полигон за слой с данными нельзя.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..schema import LayerSpec
from .geopackage import GeoPackageError, read_features

HANDLE = "hdl:10622/DN9QDM"
DATASET_URL = f"https://datasets.iisg.amsterdam/dataset.xhtml?persistentId={HANDLE}"
FILE_URL = "https://datasets.iisg.amsterdam/api/access/datafile/{file_id}"

USER_AGENT = (
    "histctx/0.2 (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

CITATION = (
    "Kessler, Gijs; Markevich, Andrei. Electronic Repository of Russian Historical "
    "Statistics, 18th–21st centuries, https://ristat.org/, Version I (2020): "
    f"Russian Empire Historical GIS Maps (1897). IISH Dataverse, {HANDLE}. CC0"
)

RISTAT_BOUNDARIES = LayerSpec(
    slug="admin_boundaries_1897",
    title="Границы губерний и уездов 1897 года",
    group="admin",
    source="RISTAT, Russian Empire Historical GIS Maps (1897), IISH Amsterdam",
    license="CC0 — общественное достояние; авторы просят ссылаться на RISTAT, ссылка проставляется",
    description=(
        "824 уезда и 103 губернии Российской империи 1897 года полигонами в WGS 84, "
        "с русскими и английскими названиями. Уезд — рабочая единица поиска: в нём "
        "лежит фонд консистории и по нему ищется приход, а подбор по названию "
        "губернии до уезда не достаёт."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=927,
    gives_records=False,
)


@dataclass(frozen=True)
class Boundaries:
    """Один файл набора: что это, откуда качать и как называется поле имени."""

    key: str
    file_id: int
    filename: str
    name_field: str
    title: str


DISTRICTS = Boundaries("districts_1897", 10336, "districts_1897.gpkg", "Name_RU", "уезды")
PROVINCES = Boundaries("provinces_1897", 10335, "provinces_1897.gpkg", "prov_RU", "губернии")

FILES = (PROVINCES, DISTRICTS)


class RistatError(RuntimeError):
    """Набор не скачался или пришёл не в том виде, какого мы ждём."""


def download(file_id: int, *, timeout: int = 300) -> bytes:
    url = FILE_URL.format(file_id=file_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RistatError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RistatError(f"{url}: сеть недоступна ({exc.reason})") from exc


def load(boundaries: Boundaries, cache_dir) -> list[dict]:
    """Полигоны одного файла набора; скачанное остаётся в кэше."""
    path = cache_dir / boundaries.filename
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(download(boundaries.file_id))
    try:
        return read_features(path, boundaries.key)
    except GeoPackageError as exc:
        raise RistatError(f"{boundaries.filename}: {exc}") from exc


def named(feats: list[dict], boundaries: Boundaries) -> int:
    """Сколько единиц подписано по-русски — без названия полигон бесполезен."""
    return sum(1 for f in feats if (f.get("properties") or {}).get(boundaries.name_field))


def collection(feats: list[dict], boundaries: Boundaries) -> dict:
    return {
        "type": "FeatureCollection",
        "name": boundaries.key,
        "license": RISTAT_BOUNDARIES.license,
        "source": RISTAT_BOUNDARIES.source,
        "citation": CITATION,
        "url": DATASET_URL,
        "features": feats,
    }


def write(collection_dict: dict, path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection_dict, ensure_ascii=False), encoding="utf-8")
    return len(collection_dict.get("features") or [])
