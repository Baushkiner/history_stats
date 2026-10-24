"""Пакеты воспроизведения на Harvard Dataverse: перечень файлов, сверка, кэш.

Набор по голоду 1891 года (`famine_1891`) держит это у себя, и там оно
останется. Три пакета, подключённые 24.10.2026 — волнения и земство
(Дауэр, Финкель, Гельбах, Нафцигер), мобилизация 1914–1916 годов (Дауэр,
Маркевич) и население городов (Буггле, Нафцигер), — устроены одинаково, и
писать сверку трижды незачем.

Путь тот же, что у голода: список файлов — `/api/datasets/:persistentId/`,
файл — `/api/access/datafile/{id}`. Таблицы, которые Dataverse
«ингестировал», он по умолчанию отдаёт TSV-копией без подписей колонок;
исходный `.dta` приходит по `?format=original`, и размер у него свой —
`originalFileSize` в перечне. Сборщики берут исходник: `pandas.read_stata`
читает его вместе с типами, а подписи колонок — единственное описание
переменных, которое есть в пакете.

Файлы без ингеста (`.dta`, `.tar`) Dataverse отдаёт переадресацией на
`dvn-cloud-iqss.s3.amazonaws.com` — подписанная ссылка живёт час.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..net import fetch_bytes

API_URL = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId={doi}"
FILE_URL = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"


class DataverseError(RuntimeError):
    """Набор не скачался или устроен не так, как записано в коде."""


@dataclass(frozen=True)
class DatasetFile:
    """Файл набора: id, имя и размеры по API в день подключения.

    `original_size` задан у ингестированной таблицы: тогда скачивается
    исходник (`?format=original`) и сохраняется под `local_name`.
    """

    file_id: int
    name: str
    size: int
    original_size: Optional[int] = None
    local_name: str = ""

    @property
    def cache_name(self) -> str:
        return self.local_name or self.name

    @property
    def download_size(self) -> int:
        return self.original_size if self.original_size is not None else self.size

    @property
    def url(self) -> str:
        url = FILE_URL.format(file_id=self.file_id)
        return url + "?format=original" if self.original_size is not None else url


def fetch_manifest(doi: str, *, error: type[Exception] = DataverseError,
                   timeout: int = 60) -> dict:
    """Перечень файлов и лицензия набора по API: {"license": …, "files": […]}."""
    raw = fetch_bytes(API_URL.format(doi=doi), error=error, timeout=timeout)
    try:
        version = json.loads(raw)["data"]["latestVersion"]
    except (ValueError, KeyError, TypeError) as exc:
        raise error(f"ответ API не разбирается: {exc}") from exc
    files = []
    for item in version.get("files") or []:
        data = item.get("dataFile") or {}
        files.append({"id": data.get("id"), "name": item.get("label") or data.get("filename"),
                      "size": data.get("filesize"),
                      "original_size": data.get("originalFileSize")})
    license_info = version.get("license") or {}
    name = license_info.get("name") if isinstance(license_info, dict) else license_info
    return {"license": name, "version": version.get("versionNumber"), "files": files}


def check_manifest(manifest: dict, expected: Iterable[DatasetFile], *,
                   license_name: Optional[str] = None) -> list[str]:
    """Расхождения между перечнем в коде и ответом API. Пустой список — сходится."""
    by_id = {f.get("id"): f for f in manifest.get("files") or []}
    problems = []
    if license_name and manifest.get("license") != license_name:
        problems.append(f"лицензия набора: ожидалась {license_name}, "
                        f"пришла {manifest.get('license')}")
    for file in expected:
        got = by_id.get(file.file_id)
        if got is None:
            problems.append(f"{file.name}: файла с id {file.file_id} в наборе нет")
            continue
        if got.get("name") != file.name:
            problems.append(f"id {file.file_id}: ожидалось имя {file.name}, "
                            f"пришло {got.get('name')}")
        if got.get("size") != file.size:
            problems.append(f"{file.name}: ожидался размер {file.size}, пришёл {got.get('size')}")
        if file.original_size is not None and got.get("original_size") != file.original_size:
            problems.append(f"{file.name}: ожидался размер исходника {file.original_size}, "
                            f"пришёл {got.get('original_size')}")
    return problems


def download(file: DatasetFile, *, error: type[Exception] = DataverseError,
             timeout: int = 600) -> bytes:
    data = fetch_bytes(file.url, error=error, timeout=timeout)
    if len(data) != file.download_size:
        raise error(f"{file.name}: скачано {len(data)} байт, ожидалось {file.download_size}")
    return data


def cached(file: DatasetFile, cache_dir: Path, *,
           error: type[Exception] = DataverseError) -> Path:
    """Файл из кэша сборщика; чего нет или не тот размер — скачивается заново."""
    path = Path(cache_dir) / file.cache_name
    if path.exists() and path.stat().st_size == file.download_size:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(download(file, error=error))
    return path
