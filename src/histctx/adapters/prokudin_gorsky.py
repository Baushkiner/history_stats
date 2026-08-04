"""Места съёмок С. М. Прокудина-Горского, 1903–1916."""

from __future__ import annotations

from pathlib import Path

from ..geo import in_bbox, valid_coords
from ..normalize import tidy_url
from ..schema import LayerSpec, clean_text

PROKUDIN = LayerSpec(
    slug="prokudin_gorsky",
    title="Фотографии Прокудина-Горского",
    group="culture",
    source="prokudin-gorskiy.ru",
    license="фотографии — общественное достояние; привязка мест — по сайту-каталогу",
    description=(
        "Цветные фотографии Российской империи 1903–1916 гг. Самый сильный слой "
        "визуального контекста: предок мог видеть ровно эти улицы и храмы."
    ),
    url="http://prokudin-gorskiy.ru/",
    status="curated",
)

# Экспедиции Прокудина-Горского укладываются в этот промежуток.
YEAR_FROM, YEAR_TO = 1903, 1916


def load_prokudin_gorsky(path: Path) -> list:
    import pandas as pd

    df = pd.read_excel(path)
    out = []
    for _, row in df.iterrows():
        lat = lon = None
        conf = "no_coords"
        if valid_coords(row.get("Широта (lat)"), row.get("Долгота (lon)")):
            lat, lon = float(row["Широта (lat)"]), float(row["Долгота (lon)"])
            conf = "ok" if in_bbox(lat, lon) else "outside_bbox"

        place = clean_text(row.get("Название")) or "Место съёмки"
        out.append(PROKUDIN.new_record(
            title=place,
            category="фотография",
            lat=lat, lon=lon,
            place_text=place,
            year_from=YEAR_FROM,
            year_to=YEAR_TO,
            date_precision="part",
            date_approx=True,
            period_raw="1903–1916",
            actor="С. М. Прокудин-Горский",
            summary=f"Место съёмки Прокудина-Горского: {place}.",
            url=tidy_url(row.get("Страница места")),
            image_url=tidy_url(row.get("Пример фото (jpg)")),
            source_id=clean_text(row.get("ID")),
            confidence=conf,
            extra={"photo_page": tidy_url(row.get("Пример фото (страница)"))},
        ))
    return out
