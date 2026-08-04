"""Единая схема записи исторического контекста.

Все слои — литературные места, сражения, фотографии, церкви, ярмарки, голод —
приводятся к одной записи. Только так факт из метрической книги можно
сопоставить со всем массивом сразу, а не писать матчинг под каждый источник.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

SCHEMA_VERSION = "1.0"

# Крупные тематические группы слоёв. Пригодятся для легенды и фильтров карты.
GROUPS = {
    "admin": "Административное деление и населённые места",
    "faith": "Церкви, приходы и религиозные общины",
    "hardship": "Бедствия и потрясения",
    "economy": "Экономика и пути сообщения",
    "culture": "Культура и свидетельства очевидцев",
    "military": "Войны и сражения",
}

# Поля в порядке выгрузки в XLSX.
COLUMNS = [
    "uid", "layer", "layer_title", "group", "title", "category",
    "lat", "lon", "place_text", "region", "district",
    "year_from", "year_to", "date_precision", "date_approx", "period_raw",
    "actor", "work", "summary", "quote", "url", "image_url",
    "source", "source_id", "license", "confidence",
]

# Русские заголовки для XLSX — чтобы файл читался так же, как текущие выгрузки.
COLUMNS_RU = {
    "uid": "UID", "layer": "Слой", "layer_title": "Название слоя", "group": "Группа",
    "title": "Название", "category": "Категория",
    "lat": "Широта (lat)", "lon": "Долгота (lon)",
    "place_text": "Территория", "region": "Губерния/область", "district": "Уезд/район",
    "year_from": "Год от", "year_to": "Год до", "date_precision": "Точность даты",
    "date_approx": "Дата приблизительна", "period_raw": "Период (исходный текст)",
    "actor": "Автор/действующее лицо", "work": "Произведение/событие",
    "summary": "Описание", "quote": "Цитата", "url": "Ссылка", "image_url": "Изображение",
    "source": "Источник", "source_id": "ID в источнике", "license": "Лицензия",
    "confidence": "Достоверность",
}

_RE_WS = re.compile(r"\s+")


def clean_text(value: Any) -> Optional[str]:
    """Приводит ячейку к чистой строке или None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-", "—", "n/a", "null"}:
        return None
    s = _RE_WS.sub(" ", s.replace(" ", " "))
    return s or None


@dataclass
class ContextRecord:
    """Одна запись контекста: что, где и когда."""

    layer: str
    title: str
    lat: Optional[float] = None
    lon: Optional[float] = None

    layer_title: str = ""
    group: str = ""
    category: Optional[str] = None

    place_text: Optional[str] = None
    region: Optional[str] = None
    district: Optional[str] = None

    year_from: Optional[int] = None
    year_to: Optional[int] = None
    date_precision: str = "unknown"
    date_approx: bool = False
    period_raw: Optional[str] = None

    actor: Optional[str] = None
    work: Optional[str] = None
    summary: Optional[str] = None
    quote: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None

    source: str = ""
    source_id: Optional[str] = None
    license: Optional[str] = None
    confidence: str = "ok"

    uid: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uid:
            self.uid = self.make_uid()

    def make_uid(self) -> str:
        """Стабильный идентификатор: пересборка не меняет ID существующих точек."""
        basis = "|".join(
            str(x) for x in (
                self.layer,
                self.source_id or "",
                self.title or "",
                f"{self.lat:.5f}" if self.lat is not None else "",
                f"{self.lon:.5f}" if self.lon is not None else "",
                self.year_from if self.year_from is not None else "",
            )
        )
        return f"{self.layer}:{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def has_time(self) -> bool:
        return self.year_from is not None and self.year_to is not None

    @property
    def mappable(self) -> bool:
        """Годится ли запись для показа на карте по (место, время)."""
        return self.has_point and self.has_time

    def overlaps_years(self, year_from: int, year_to: int) -> bool:
        if not self.has_time:
            return False
        return self.year_from <= year_to and year_from <= self.year_to

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return {c: d.get(c) for c in COLUMNS}

    def to_feature(self) -> dict:
        """GeoJSON Feature. Записи без координат сюда попадать не должны."""
        props = self.to_row()
        props.pop("lat", None)
        props.pop("lon", None)
        props = {k: v for k, v in props.items() if v is not None and v != ""}
        if self.extra:
            props["extra"] = self.extra
        return {
            "type": "Feature",
            "id": self.uid,
            "geometry": {"type": "Point", "coordinates": [round(self.lon, 6), round(self.lat, 6)]},
            "properties": props,
        }


@dataclass
class LayerSpec:
    """Описание слоя: что это, откуда, на каких правах."""

    slug: str
    title: str
    group: str
    source: str
    license: str
    description: str = ""
    url: Optional[str] = None
    status: str = "planned"          # planned | harvested | curated
    expected_rows: Optional[int] = None

    def new_record(self, **kwargs) -> ContextRecord:
        kwargs.setdefault("layer", self.slug)
        kwargs.setdefault("layer_title", self.title)
        kwargs.setdefault("group", self.group)
        kwargs.setdefault("source", self.source)
        kwargs.setdefault("license", self.license)
        return ContextRecord(**kwargs)
