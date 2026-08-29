#!/usr/bin/env python3
"""Собранный слой -> таблица XLSX с русскими заголовками.

    python3 scripts/export_xlsx.py --list                 # что уже собрано
    python3 scripts/export_xlsx.py --layer disasters      # один слой
    python3 scripts/export_xlsx.py --all --one-file       # всё в одну книгу
    python3 scripts/export_xlsx.py --layer disasters --file ~/disasters.xlsx

Сбор из сети эта команда не повторяет: слои уже лежат в `data/out`, и таблица
делается из них. Нужна она затем, что xlsx пишется только вместе со сбором
(`scripts/harvest.py`), а в репозиторий выгрузка не идёт — посмотреть слой в
таблице после `git clone` иначе нечем.

Записи собираются из всего, что о слое есть в выгрузке: построчный JSON в
`jsonl/`, точки в `geojson/`, общая `context.jsonl` и события без точки в
`territorial_events.json`. Порядок такой потому, что полнота у файлов разная:
в GeoJSON по определению нет записей без координат, а per-layer `jsonl/`
пишет только сбор из Викиданных. Повторы отсеиваются по `uid`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.io_formats import (  # noqa: E402
    read_geojson, read_jsonl, read_records_json, write_xlsx, write_xlsx_multi,
)
from histctx.registry import BY_SLUG  # noqa: E402
from histctx.schema import ContextRecord  # noqa: E402


def available_layers(out_dir: Path) -> list[str]:
    """Слои, у которых в выгрузке есть свой файл."""
    slugs = {p.stem for p in (out_dir / "jsonl").glob("*.jsonl")}
    slugs |= {p.stem for p in (out_dir / "geojson").glob("*.geojson")}
    return sorted(slugs)


def read_layer(out_dir: Path, slug: str) -> tuple[list[ContextRecord], list[str]]:
    """Записи слоя и перечень файлов, из которых они взяты."""
    records: list[ContextRecord] = []
    seen: set[str] = set()
    used: list[str] = []

    def take(path: Path, found) -> None:
        n = 0
        for rec in found:
            if rec.layer != slug or rec.uid in seen:
                continue
            seen.add(rec.uid)
            records.append(rec)
            n += 1
        if n:
            used.append(f"{path.relative_to(out_dir)} ({n})")

    for path, reader in (
        (out_dir / "jsonl" / f"{slug}.jsonl", read_jsonl),
        (out_dir / "geojson" / f"{slug}.geojson", read_geojson),
        (out_dir / "context.jsonl", read_jsonl),
        (out_dir / "territorial_events.json", read_records_json),
    ):
        if path.exists():
            take(path, reader(path))
    return records, used


def layer_title(slug: str, records: list[ContextRecord]) -> str:
    spec = BY_SLUG.get(slug)
    if spec:
        return spec.title
    return next((r.layer_title for r in records if r.layer_title), slug)


def describe(records: list[ContextRecord]) -> str:
    dated = sum(1 for r in records if r.has_time)
    points = sum(1 for r in records if r.has_point)
    return (f"{len(records)} записей, с координатами {points}, "
            f"с датировкой {dated}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", action="append", help="слой (можно повторять)")
    ap.add_argument("--all", action="store_true", help="все собранные слои")
    ap.add_argument("--list", action="store_true", help="показать собранные слои и выйти")
    ap.add_argument("--one-file", action="store_true",
                    help="все выбранные слои в одну книгу, по вкладке на слой")
    ap.add_argument("--file", type=Path, help="куда писать xlsx (по умолчанию "
                                              "data/out/xlsx/<слой>.xlsx)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out",
                    help="каталог выгрузки, откуда читаются слои")
    args = ap.parse_args()

    known = available_layers(args.out)
    if args.list or not (args.layer or args.all):
        if not known:
            print(f"В {args.out} нет собранных слоёв. Соберите их "
                  f"scripts/build_core.py или scripts/harvest.py.", file=sys.stderr)
            return 1
        print(f"Собранные слои в {args.out}:\n")
        for slug in known:
            print(f"  {slug:22s} {layer_title(slug, [])}")
        return 0 if args.list else 1

    slugs = known if args.all else list(dict.fromkeys(args.layer))
    unknown = [s for s in slugs if s not in known]
    if unknown:
        # Опечатка в названии слоя иначе даёт пустую книгу с заголовками —
        # правдоподобный, но пустой файл хуже отказа.
        print(f"Нет в выгрузке: {', '.join(unknown)}.\n"
              f"Есть: {', '.join(known)}", file=sys.stderr)
        return 1

    sheets: dict[str, list[ContextRecord]] = {}
    for slug in slugs:
        records, used = read_layer(args.out, slug)
        if not records:
            print(f"Слой «{slug}»: записей не нашлось, файл не пишется", file=sys.stderr)
            continue
        print(f"Слой «{layer_title(slug, records)}» ({slug}): {describe(records)}")
        print(f"  взято из: {', '.join(used)}")
        sheets[layer_title(slug, records)] = records

    if not sheets:
        return 1

    xlsx_dir = args.out / "xlsx"
    if args.one_file or len(sheets) > 1:
        path = args.file or xlsx_dir / "layers.xlsx"
        counts = write_xlsx_multi(sheets, path)
        print(f"\n{path}: {len(counts)} вкладок, {sum(counts.values())} строк")
    else:
        title, records = next(iter(sheets.items()))
        path = args.file or xlsx_dir / f"{slugs[0]}.xlsx"
        n = write_xlsx(records, path, sheet_name=title)
        print(f"\n{path}: {n} строк")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
