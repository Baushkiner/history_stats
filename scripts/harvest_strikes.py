#!/usr/bin/env python3
"""Сбор слоя рабочих конфликтов 1895–1904 годов из набора IISH.

    python3 scripts/harvest_strikes.py --probe    # что в файле на самом деле
    python3 scripts/harvest_strikes.py --build    # собрать слой в data/out

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--probe`
печатает реальные колонки набора, показывает, сколько строк разобралось в
записи, и перечисляет губернии, которые разбор не признал. Собрать не то
молча хуже, чем остановиться.

Права. Набор лежит под CC0 — брать можно всё; в записи идут факты и ссылка на
карточку набора, кодовые справочники причин и требований остаются в `extra`
как есть. Условие 3 раздела «Каталог открыт» (`docs/CATALOG.md`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_jsonl
from histctx.sources.strikes import (
    STRIKES, StrikesError, fetch, read_rows, rows_to_records,
)

CACHE = ROOT / "data" / "cache" / "strikes"


def probe(rows: list) -> int:
    print(f"Строк в наборе: {len(rows)}")
    if not rows:
        print("  Пустой файл: проверьте ссылку на набор.", file=sys.stderr)
        return 1
    columns = list(rows[0])
    print(f"  колонок: {len(columns)}")
    print("  колонки:", ", ".join(columns[:16]), "…" if len(columns) > 16 else "")

    records = rows_to_records(rows)
    usable = [r for r in records if r.usable]
    print(f"\nРазобрано записей: {len(records)}, годны для подбора: {len(usable)}")
    if not usable:
        print("  Ни одной годной записи: проверьте колонки Province и BeginYear.")
        return 1

    years = [r.year_from for r in usable]
    print(f"  годы: {min(years)}–{max(r.year_to for r in usable)}")
    print(f"  губерний и областей: {len({r.region for r in usable})}")
    multi = sum(1 for r in records if len(r.regions) > 1)
    print(f"  записей сразу по нескольким губерниям: {multi}")
    print(f"  уезд распознан у: {sum(1 for r in records if r.district)}")

    kinds = collections.Counter(r.category or "вид не указан" for r in records)
    print("  по видам конфликта:")
    for kind, count in kinds.most_common(8):
        print(f"    {count:>5}  {kind}")

    unparsed = [r for r in records if r.confidence == "province_unparsed"]
    if unparsed:
        raw = collections.Counter(r.extra.get("province_raw") for r in unparsed)
        print(f"\n  губерния не разобрана у {len(unparsed)} записей — они остаются "
              f"в данных с пометкой province_unparsed:")
        for value, count in raw.most_common(8):
            print(f"    {count:>5}  {value}")

    print("\n  примеры:")
    for rec in usable[:5]:
        print(f"    {rec.year_from}  {rec.region:<28} {rec.title[:56]}")
    print("\nКолонки на месте, разбор работает — можно запускать --build.")
    return 0


def build(rows: list, out_dir: Path) -> int:
    records = rows_to_records(rows)
    usable = [r for r in records if r.usable]
    if not usable:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(records, out_dir / "jsonl" / f"{STRIKES.slug}.jsonl")
    police = sum(1 for r in records if r.extra.get("police_or_army"))
    unparsed = sum(1 for r in records if r.confidence == "province_unparsed")
    print(f"Собрано {len(records)} записей (охват «губерния», без точки), "
          f"годны для подбора {len(usable)}.")
    print(f"  с вызовом полиции или войск: {police}")
    print(f"  с неразобранной губернией (остались в данных): {unparsed}")
    print(f"  файл: {(out_dir / 'jsonl' / (STRIKES.slug + '.jsonl')).relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="показать колонки набора и разбор")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--from-file", type=Path, default=None,
                    help="взять TSV из файла, а не из сети")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()

    if not args.probe and not args.build:
        ap.error("укажите --probe или --build")

    try:
        path = args.from_file or fetch(args.cache)
        rows = read_rows(path)
        if args.probe:
            code = probe(rows)
            if code or not args.build:
                return code
        return build(rows, args.out)
    except StrikesError as exc:
        print(f"Набор IISH: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
