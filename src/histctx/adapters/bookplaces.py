"""Литературные места и материалы Этнографического бюро кн. Тенишева."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..geo import extract_district, extract_region, in_bbox, valid_coords
from ..normalize import normalize_genre, strip_quotes, tidy_url
from ..periods import parse_period
from ..schema import LayerSpec, clean_text

LITERARY = LayerSpec(
    slug="literary_places",
    title="Литературные места",
    group="culture",
    source="Свод литературных мест проекта «Цифровой летописец»",
    license="собственная подборка проекта",
    description=(
        "Места, описанные в художественной прозе, очерках, дневниках и письмах. "
        "Даёт голос очевидца: как выглядела местность и чем жили люди."
    ),
    status="curated",
)

TENISHEV = LayerSpec(
    slug="tenishev",
    title="Материалы Этнографического бюро кн. Тенишева",
    group="culture",
    source="Этнографическое бюро кн. В. Н. Тенишева, 1897–1901",
    license="общественное достояние",
    description=(
        "Программа опроса крестьянского быта 1897–1901 гг. Описания по конкретным "
        "сёлам: хозяйство, обряды, семейный уклад, говор."
    ),
    status="curated",
)


def _sheet(path: Path, name: str):
    import pandas as pd

    return pd.read_excel(path, sheet_name=name)


def _coords(row) -> tuple[Optional[float], Optional[float], str]:
    lat, lon = row.get("Широта (lat)"), row.get("Долгота (lon)")
    if not valid_coords(lat, lon):
        return None, None, "no_coords"
    lat, lon = float(lat), float(lon)
    if not in_bbox(lat, lon):
        return lat, lon, "outside_bbox"
    return lat, lon, "ok"


def load_literary_places(path: Path) -> list:
    """Читает вкладку «Литературные места»."""
    df = _sheet(path, "Литературные места")
    out = []
    for _, row in df.iterrows():
        lat, lon, conf = _coords(row)
        territory = clean_text(row.get("Территория"))
        period = parse_period(row.get("Период"))
        work = strip_quotes(row.get("Произведение"))
        author = clean_text(row.get("Автор"))

        out.append(LITERARY.new_record(
            title=work or territory or "Литературное место",
            category=normalize_genre(row.get("Жанр/Тип")),
            lat=lat, lon=lon,
            place_text=territory,
            region=extract_region(territory),
            district=extract_district(territory),
            year_from=period.year_from,
            year_to=period.year_to,
            date_precision=period.precision,
            date_approx=period.approx,
            period_raw=clean_text(row.get("Период")),
            actor=author,
            work=work,
            summary=clean_text(row.get("Ценность/Описание")),
            quote=clean_text(row.get("Цитата")),
            url=tidy_url(row.get("Ссылка")),
            source_id=clean_text(row.get("ID")),
            confidence=conf,
        ))
    return out


def load_tenishev(path: Path) -> list:
    """Читает вкладку «Материалы Тенишева».

    Территория проставлена не у всех записей (244 пусты), поэтому губернию
    дополнительно пытаемся достать из описания.
    """
    df = _sheet(path, "Материалы Тенишева")
    out = []
    for _, row in df.iterrows():
        lat, lon, conf = _coords(row)
        settlement = clean_text(row.get("Произведение"))
        territory = clean_text(row.get("Территория"))
        summary = clean_text(row.get("Ценность/Описание"))
        period = parse_period(row.get("Период"))

        region = extract_region(territory) or extract_region(summary)

        out.append(TENISHEV.new_record(
            title=settlement or "Тенишевское описание",
            category="этнография",
            lat=lat, lon=lon,
            place_text=territory or region,
            region=region,
            district=extract_district(territory),
            year_from=period.year_from,
            year_to=period.year_to,
            date_precision=period.precision,
            date_approx=period.approx,
            period_raw=clean_text(row.get("Период")),
            actor="Этнографическое бюро кн. Тенишева",
            work=settlement,
            summary=summary,
            url=tidy_url(row.get("Ссылка")),
            source_id=None,
            confidence=conf,
        ))
    return out
