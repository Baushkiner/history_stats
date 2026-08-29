#!/usr/bin/env python3
"""Сбор слоя лагерных управлений из «Карты ГУЛАГа».

    python3 scripts/harvest_gulag.py --check     # что отдаёт API, без записи файлов
    python3 scripts/harvest_gulag.py --build     # собрать слой в data/out

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--check`
показывает, сколько карточек пришло, сколько из них разобралось и на чём
разбор споткнулся. Собрать пустоту молча хуже, чем остановиться.

Права. Проект открытых условий не публикует, поэтому берутся только факты —
название, координата, годы работы, вид работ, численность по годам — и ссылка
на карточку. Авторские исторические справки и фотографии карточек не
копируются: за ними запись отсылает на gulagmap.ru. Условие 3 раздела
«Каталог открыт» в `docs/CATALOG.md`.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl
from histctx.sources.gulag import (
    GULAG_CAMPS, GulagError, camps_to_records, check_camp_fields, fetch_all,
)


def check(camps: list, refs: dict) -> int:
    print(f"Карточек в ответе: {len(camps)}")
    for name, ref in refs.items():
        print(f"  справочник {name}: {len(ref)} значений")
    check_camp_fields(camps)
    print(f"  поля первой карточки: {sorted(camps[0])}")

    locations = sum(len(c.get("locations") or []) for c in camps)
    published = sum(1 for c in camps if (c.get("published") or {}).get("ru")
                    or (c.get("published") or {}).get("en"))
    print(f"  мест размещения: {locations}; опубликованных карточек: {published}")

    records = camps_to_records(camps, refs)
    print(f"\nРазобрано записей: {len(records)} из {locations} мест")
    if not records:
        print("  Ни одна запись не разобрана: проверьте geometry и описания локаций.")
        return 1

    drafts = sum(1 for r in records if r.confidence == "unpublished_source")
    with_region = sum(1 for r in records if r.region)
    print(f"  из них неопубликованных в проекте: {drafts}")
    print(f"  с распознанной губернией или областью: {with_region}")
    print(f"  годы: {min(r.year_from for r in records)}–"
          f"{max(r.year_to for r in records)}")

    kinds = collections.Counter(r.category for r in records)
    print("  по типам:")
    for kind, count in kinds.most_common():
        print(f"    {count:>5}  {kind}")

    print("\n  примеры:")
    for rec in records[:5]:
        print(f"    {rec.year_from}–{rec.year_to}  {rec.lat:.4f},{rec.lon:.4f}  "
              f"{rec.title[:48]}  {rec.url}")
    print("\nПоля на месте, разбор работает — можно запускать --build.")
    return 0


def build(camps: list, refs: dict, out_dir: Path) -> int:
    records = camps_to_records(camps, refs)
    if not records:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    n = write_geojson(records, out_dir / "geojson" / f"{GULAG_CAMPS.slug}.geojson",
                      layer_title=GULAG_CAMPS.title)
    write_jsonl(records, out_dir / "jsonl" / f"{GULAG_CAMPS.slug}.jsonl")
    drafts = sum(1 for r in records if r.confidence == "unpublished_source")
    print(f"Собрано {len(records)} записей, на карту пойдут {n}.")
    print(f"Из них помечено «карточка не опубликована в проекте»: {drafts}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="показать, что отдаёт API, и разобрать")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--from-file", type=Path, default=None,
                    help="взять ответ /api/camps из файла, а не из сети")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")

    try:
        if args.from_file:
            camps, refs = json.loads(args.from_file.read_text(encoding="utf-8")), {}
        else:
            camps, refs = fetch_all()
        if args.check:
            code = check(camps, refs)
            if code or not args.build:
                return code
        return build(camps, refs, args.out)
    except GulagError as exc:
        print(f"Карта ГУЛАГа: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
