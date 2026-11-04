#!/usr/bin/env python3
"""Сбор слоя деревень Финляндии и их приходов из «Suomen kylät 1540–1940» (Zenodo).

    python3 scripts/harvest_suomen_kylat.py --check    # сверка, разбор, без записи слоя
    python3 scripts/harvest_suomen_kylat.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков: `--check`
сверяет перечень файлов записи Zenodo 10408884 с размером и md5, записанными
в коде, скачивает таблицу (4,9 МБ, кладётся в `data/raw/suomen_kylat/`),
разбирает её, переводит координаты из ETRS-TM35FIN, ставит губернию 1897 года
и показывает, что пришло: сколько деревень с точкой, сколько приходов
заполнено по годам, сколько значений не сверено («?»), что помечено.

Права. CC BY 4.0 (карточка набора и описание полей). Берутся факты — точка,
годы, приходы, названия — со ссылкой на набор.

На выходе:

* `geojson/villages_fi.geojson` — деревни с точкой, вместе с помеченными
  (`after_1960` — впервые упомянуты позже 1960 года; `outside_bbox`);
* `villages_fi.json` — деревни без координаты, `confidence = no_coords`:
  в репозиторий идут оба файла, `jsonl/` в `.gitignore`;
* `jsonl/villages_fi.jsonl` — слой целиком.

Нужны `data/out/boundaries/provinces_1897.geojson` (RISTAT) и
`state_borders.geojson` (CShapes) — оба лежат в репозитории: по ним ставится
губерния и рамка, как у слоя приходов.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.ghcn import GhcnError
from histctx.sources.suomen_kylat import (
    CEDED, CSV_KEY, HORIZON, RECORD_ID, VILLAGES_FI, YEAR_COLUMNS, SuomenKylatError,
    cached_csv, check_manifest, fetch_manifest, mark_frame, parish, read_rows, records,
)

CACHE = ROOT / "data" / "raw" / "suomen_kylat"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"

# Деревни, по которым видно, ради чего слой собран: приход менялся, деревня
# отошла к СССР, деревня в шхерах — проверка разбора глазами.
WATCH = ("10001", "10006", "16065", "16431", "23937", "11169", "23475")


def load_frame() -> Frame:
    try:
        return Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise SuomenKylatError(
            f"рамку взять неоткуда ({exc}). Нужны {BOUNDARIES.relative_to(ROOT)}/"
            "provinces_1897.geojson и state_borders.geojson — см. docs/HARVEST.md") from exc


def collect(cache: Path) -> tuple[list[dict], list, collections.Counter]:
    rows = read_rows(cached_csv(cache).read_bytes())
    recs = records(rows)
    counts = mark_frame(recs, load_frame())
    return rows, recs, counts


def report(rows: list[dict], recs: list, counts: collections.Counter) -> None:
    print(f"Деревень в наборе: {len(rows)}, записей: {len(recs)}")
    with_point = sum(1 for r in recs if r.has_point)
    print(f"  с точкой: {with_point}; без координаты: {len(recs) - with_point}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    print("  пометки:")
    for what, n in collections.Counter(r.confidence for r in recs).most_common():
        print(f"    {n:>6}  {what}")

    print("\n  приход по годам (заполнено деревень / различных приходов / не сверено «?»):")
    for column in YEAR_COLUMNS:
        values = [row[column].strip() for row in rows if row[column].strip()]
        names = {parish(v)[0] for v in values} - {None}
        unsure = sum(1 for v in values if parish(v)[1])
        ceded = sum(1 for v in values if v == CEDED)
        tail = f", «{CEDED}» — {ceded}" if ceded else ""
        print(f"    {column[1:]}: {len(values):>6} / {len(names):>4} / {unsure:>4}{tail}")
    starts = collections.Counter(r.year_from for r in recs)
    print("  первое упоминание, чаще всего: "
          + ", ".join(f"{y} — {n}" for y, n in starts.most_common(8)))
    late = sum(1 for r in recs if r.year_from > HORIZON)
    print(f"  впервые упомянуты позже {HORIZON} года: {late}")
    print(f"  деревня и сейчас: {sum(1 for r in recs if not r.date_approx)}; "
          f"перестали быть деревней: {sum(1 for r in recs if r.date_approx)}")
    print(f"  со ссылкой на Викиданные: {sum(1 for r in recs if 'wikidata' in r.extra)}")

    print("\n  образцы:")
    by_id = {r.source_id: r for r in recs}
    for key in WATCH:
        rec = by_id.get(key)
        if rec is not None:
            print(f"    {rec.title} [{rec.region or 'губерния не найдена'}]: {rec.summary}")


def check(cache: Path) -> int:
    problems = check_manifest(fetch_manifest())
    if problems:
        print(f"Suomen kylät (Zenodo {RECORD_ID}): файл {CSV_KEY} не тот, что записан в коде:",
              file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Suomen kylät: перечень файлов записи Zenodo {RECORD_ID} сходится с кодом.")
    rows, recs, counts = collect(cache)
    if not recs:
        print("Ни одной деревни не разобрано: проверьте разбор.", file=sys.stderr)
        return 1
    report(rows, recs, counts)
    print("\nТаблица читается, разбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    _, recs, counts = collect(cache)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = VILLAGES_FI.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    # Права, источник и ссылка у всех записей одни — они выносятся на уровень
    # коллекции, как у остальных слоёв, собранных после 2026 года.
    n = write_geojson(recs, geo, layer_title=VILLAGES_FI.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{VILLAGES_FI.title}: без координаты")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{VILLAGES_FI.title}»: {len(recs)} записей, на карте {n}, "
          f"без координаты {len(off_map)}")
    for what, count in counts.most_common():
        print(f"  {what}: {count}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить, скачать, разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть таблицу набора")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except SuomenKylatError as exc:
        print(f"Suomen kylät: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
