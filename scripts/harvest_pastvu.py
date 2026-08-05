#!/usr/bin/env python3
"""Сбор слоя старых фотографий из PastVu.

    python3 scripts/harvest_pastvu.py --probe                  # что реально отдаёт API
    python3 scripts/harvest_pastvu.py --bbox 55.5 37.3 56.0 37.9   # один прямоугольник
    python3 scripts/harvest_pastvu.py --all --step 0.5          # вся территория РИ/СССР

Первым запуском обязательно делайте `--probe`. Модуль писался без доступа к
api.pastvu.com: имена полей взяты из документации, а не из живого ответа.
Проба показывает, что пришло на самом деле, и падает с понятным сообщением,
если обязательных полей нет.

Права: снимки принадлежат их авторам, PastVu — некоммерческий проект.
Собираются метаданные и ссылки на страницы снимков, файлы не копируются.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.geo import BBOX_RU  # noqa: E402
from histctx.io_formats import write_geojson, write_jsonl  # noqa: E402
from histctx.sources.pastvu import (  # noqa: E402
    PASTVU_PHOTOS, YEAR_MAX, YEAR_MIN, PastVuClient, PastVuError,
    check_photo_fields, grid, in_requested_bbox, photos_to_records,
)

# Небольшой прямоугольник в центре Москвы: снимков там заведомо много,
# и проба возвращает содержательный ответ за один запрос.
PROBE_BBOX = (55.75, 37.60, 55.77, 37.63)


def probe(client: PastVuClient, bbox: tuple, year_to: int) -> int:
    print(f"Проба: {bbox}, годы {YEAR_MIN}–{year_to}\n")
    photos = client.photos_in_bbox(bbox, year_to=year_to)
    print(f"  снимков в ответе: {len(photos)}")
    if not photos:
        print("  Пусто. Возможные причины: слишком мелкий прямоугольник, "
              "перепутанный порядок координат в bounds, изменившийся формат запроса.")
        return 1

    print(f"  поля первого снимка: {sorted(photos[0])}")
    print("  сырая запись:")
    print("   ", json.dumps(photos[0], ensure_ascii=False)[:400])
    check_photo_fields(photos)

    records = photos_to_records(photos, require_bbox=False, year_max=year_to)
    print(f"\n  разобрано в записи: {len(records)} из {len(photos)}")
    for rec in records[:5]:
        print(f"    {rec.year_from}–{rec.year_to}  {rec.lat:.5f},{rec.lon:.5f}  "
              f"{rec.title[:60]}  {rec.url}")
    if not records:
        print("  Ни одна запись не разобрана: проверьте поля geo/year в выводе выше.")
        return 1
    print("\nПоля на месте, разбор работает — можно запускать сбор.")
    return 0


def harvest(client: PastVuClient, bbox: tuple, *, step: float, year_to: int,
            out_dir: Path, max_cells: int | None) -> int:
    cells = list(grid(bbox, step))
    if max_cells:
        cells = cells[:max_cells]
    print(f"Сбор: {len(cells)} клеток по {step}°, годы {YEAR_MIN}–{year_to}")

    records, seen, failed = [], set(), 0
    for i, cell in enumerate(cells, 1):
        try:
            photos = client.photos_in_bbox(cell, year_to=year_to)
        except PastVuError as exc:
            failed += 1
            print(f"  [{i}/{len(cells)}] ОШИБКА {cell}: {exc}", file=sys.stderr)
            continue
        # Ответ просеивается по запрошенному прямоугольнику ещё раз: если
        # порядок осей в bounds окажется другим, чужие точки в слой не пройдут.
        photos = [p for p in photos if _inside(p, cell)]
        for rec in photos_to_records(photos, year_max=year_to):
            if rec.source_id in seen:
                continue
            seen.add(rec.source_id)
            records.append(rec)
        if i % 20 == 0 or i == len(cells):
            print(f"  [{i}/{len(cells)}] записей: {len(records)}")

    if not records:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    n = write_geojson(records, out_dir / "geojson" / f"{PASTVU_PHOTOS.slug}.geojson",
                      layer_title=PASTVU_PHOTOS.title)
    write_jsonl(records, out_dir / "jsonl" / f"{PASTVU_PHOTOS.slug}.jsonl")
    print(f"\nСобрано {len(records)} записей, на карту пойдут {n}. Клеток с ошибкой: {failed}.")
    return 0


def _inside(photo: dict, bbox: tuple) -> bool:
    geo = photo.get("geo")
    if not isinstance(geo, (list, tuple)) or len(geo) != 2:
        return False
    try:
        return in_requested_bbox(float(geo[0]), float(geo[1]), bbox)
    except (TypeError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="один запрос и разбор ответа, без сбора")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"))
    ap.add_argument("--all", action="store_true", help="вся территория РИ/СССР — это надолго")
    ap.add_argument("--step", type=float, default=0.5, help="сторона клетки в градусах")
    ap.add_argument("--year-to", type=int, default=YEAR_MAX, help="верхняя граница датировки")
    ap.add_argument("--pause", type=float, default=0.5, help="пауза между запросами, секунды")
    ap.add_argument("--max-cells", type=int, default=None, help="ограничить число клеток")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    client = PastVuClient(pause_sec=args.pause)
    bbox = tuple(args.bbox) if args.bbox else (BBOX_RU if args.all else PROBE_BBOX)

    try:
        if args.probe:
            return probe(client, tuple(args.bbox) if args.bbox else PROBE_BBOX, args.year_to)
        if not args.bbox and not args.all:
            ap.error("укажите --probe, --bbox или --all")
        return harvest(client, bbox, step=args.step, year_to=args.year_to,
                       out_dir=args.out, max_cells=args.max_cells)
    except PastVuError as exc:
        print(f"PastVu: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
