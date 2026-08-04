"""Сражения на территории России и сопредельных земель.

Здесь же чинятся три проблемы исходного файла:
  * колонка «Исход» заполнена в 2 строках из 1850 и содержит не исходы —
    она не переносится, вместо неё есть поле `summary`;
  * одна и та же война записана под разными именами (см. normalize_war);
  * в списке есть воинские части и корабли, а не события — они помечаются
    `confidence="not_an_event"`, чтобы не выкидывать данные молча.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from ..geo import in_bbox, valid_coords
from ..normalize import (
    looks_like_military_unit, looks_like_person, normalize_war, years_from_title,
)
from ..periods import parse_period, parse_year
from ..schema import LayerSpec, clean_text

BATTLES = LayerSpec(
    slug="battles",
    title="Сражения и военные события",
    group="military",
    source="Русская Википедия / Викиданные",
    license="CC BY-SA 4.0",
    description=(
        "Сражения, осады, десанты и операции. Для генеалогии важны как маркер: "
        "рекрутские наборы, мобилизации, разорение местности, потоки беженцев."
    ),
    status="curated",
)


def load_battles(path: Path) -> list:
    import pandas as pd

    df = pd.read_excel(path)
    out = []
    for _, row in df.iterrows():
        title = clean_text(row.get("Название")) or "Событие"

        lat = lon = None
        conf = "no_coords"
        if valid_coords(row.get("Широта (lat)"), row.get("Долгота (lon)")):
            lat, lon = float(row["Широта (lat)"]), float(row["Долгота (lon)"])
            conf = "ok" if in_bbox(lat, lon) else "outside_bbox"

        # «да (место)» означает, что координата указывает на населённый пункт,
        # а не на поле боя — точность ниже, но запись остаётся полезной.
        if conf == "ok" and clean_text(row.get("✓ коорд")) == "да (место)":
            conf = "place_level"

        if looks_like_military_unit(title) or looks_like_person(title):
            conf = "not_an_event"

        year = parse_year(row.get("Год"))
        if year is None:
            year = parse_year(row.get("Дата"))
        period = parse_period(row.get("Дата") if pd.notna(row.get("Дата")) else None)

        year_from = year if year is not None else period.year_from
        year_to = year if year is not None else period.year_to
        precision = "day" if clean_text(row.get("Дата")) else ("year" if year is not None else "unknown")

        # Год часто вынесен в название: «Осада Смоленска (1613—1617)».
        if year_from is None:
            ta, tb = years_from_title(title)
            if ta is not None:
                year_from, year_to = ta, tb
                precision = "year"

        war = normalize_war(row.get("Война/Конфликт"))
        qid = clean_text(row.get("QID"))

        out.append(BATTLES.new_record(
            title=title,
            category=war or clean_text(row.get("Эпоха")),
            lat=lat, lon=lon,
            year_from=year_from,
            year_to=year_to,
            date_precision=precision,
            date_approx=False,
            period_raw=clean_text(row.get("Дата")) or clean_text(row.get("Год")),
            actor=None,
            work=war,
            summary=clean_text(row.get("Описание")),
            url=_readable_url(row.get("Ссылка")),
            source_id=qid,
            confidence=conf,
            extra={"era": clean_text(row.get("Эпоха")), "war_raw": clean_text(row.get("Война/Конфликт"))},
        ))
    return out


def _readable_url(value) -> str | None:
    """Ссылки в файле процентно-закодированы; раскодируем для читаемости."""
    s = clean_text(value)
    if not s:
        return None
    try:
        return unquote(s)
    except Exception:
        return s
