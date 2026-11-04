#!/usr/bin/env python3
"""Сбор слоёв KUL geo-ecclesiae: латинские храмы около 1772 и 1936–1939 годов (Zenodo).

    python3 scripts/harvest_geo_ecclesiae.py --check                 # оба среза
    python3 scripts/harvest_geo_ecclesiae.py --build
    python3 scripts/harvest_geo_ecclesiae.py --check --layer 1772    # один срез

Проверочный первый запуск обязателен, как у остальных сборщиков: `--check`
сверяет перечень файлов записи Zenodo с именем, размером и md5, записанными
в коде, скачивает GeoJSON (4,1 и 3,2 МБ, кладутся в `data/raw/geo_ecclesiae/`
под номером записи), разбирает его, ставит губернию 1897 года и рамку РИ/СССР
и показывает, что пришло: у среза 1772 года — сколько главных и
вспомогательных храмов, у скольких назван приход, сколько записей датировано
визитациями; у среза 1936–1939 годов — годы схематизмов и ссылки на сканы;
у обоих — сколько лежит вне рамки и по каким диоцезам.

Права. 1772 год: карточка Zenodo — CC BY-SA 4.0, в файле метаданных набора и
на data.geo-ecclesiae — CC BY-NC. 1936–1939 годы: CC BY-NC 4.0. Проект
некоммерческий; берутся факты — точка, тип храма, посвящение, приход,
деканат, диоцез, годы — и ссылки на визитации и сканы схематизмов.

На выходе:

* `geojson/churches_pl_1772.geojson`, `geojson/churches_pl_1938.geojson` —
  все храмы: точка есть у каждого, храмы вне губерний 1897 года и земель
  империи и СССР — с пометкой `outside_bbox`, как у слоя приходов;
* `jsonl/churches_pl_1772.jsonl`, `jsonl/churches_pl_1938.jsonl` — слои
  целиком (`jsonl/` в `.gitignore`).

Нужны `data/out/boundaries/provinces_1897.geojson` (RISTAT) и
`state_borders.geojson` (CShapes) — оба лежат в репозитории.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import OUTSIDE, Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.geo_ecclesiae import (
    CHURCHES_1772_FILE, CHURCHES_1938_FILE, CHURCHES_PL_1772, CHURCHES_PL_1938,
    REQUIRED_1772, REQUIRED_1938, SLICE_YEAR, TYPE_AUX, TYPE_MAIN, GeoEcclesiaeError,
    cached_file, check_manifest, fetch_manifest, read_features, records_1772, records_1938,
    unknown_types,
)
from histctx.sources.ghcn import GhcnError

CACHE = ROOT / "data" / "raw" / "geo_ecclesiae"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"

# Слой → (файл на Zenodo, обязательные поля, разбор, карточка слоя).
LAYERS = {
    "1772": (CHURCHES_1772_FILE, REQUIRED_1772, records_1772, CHURCHES_PL_1772),
    "1938": (CHURCHES_1938_FILE, REQUIRED_1938, records_1938, CHURCHES_PL_1938),
}

# Храмы, по которым видно, ради чего слой собран: филии с приходом в будущих
# западных губерниях, кафедральный Вильно, приход в Галиции вне рамки.
WATCH = ("Wilno", "Troki", "Kiejdany", "Brzozów", "Łuck", "Kamieniec Podolski")


def load_frame() -> Frame:
    try:
        return Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise GeoEcclesiaeError(
            f"рамку взять неоткуда ({exc}). Нужны {BOUNDARIES.relative_to(ROOT)}/"
            "provinces_1897.geojson и state_borders.geojson — см. docs/HARVEST.md") from exc


def collect(layer: str, cache: Path) -> tuple[list[dict], list, collections.Counter]:
    dataset, required, parse, _ = LAYERS[layer]
    features, crs = read_features(cached_file(dataset, cache).read_bytes(), required)
    recs = parse(features, crs)
    counts = load_frame().mark(recs)
    return features, recs, counts


def report_1772(features: list[dict], recs: list, counts: collections.Counter) -> None:
    print(f"Объектов в наборе: {len(features)}, записей: {len(recs)}")
    kinds = collections.Counter((f.get("properties") or {}).get("type") for f in features)
    print(f"  главных храмов: {kinds.get(TYPE_MAIN, 0)}; вспомогательных: "
          f"{kinds.get(TYPE_AUX, 0)}, из них с приходом: "
          f"{sum(1 for r in recs if 'parish' in r.extra)}")
    strange = unknown_types(features)
    if strange:
        print(f"  типы без перевода ({len(strange)}): {', '.join(strange)}")
    print(f"  с точкой: {sum(1 for r in recs if r.has_point)}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    dated = [r for r in recs if r.extra.get("source_years")]
    print(f"  с годами документов XVIII века: {len(dated)}; без них — срез {SLICE_YEAR}–"
          f"{SLICE_YEAR}: {len(recs) - len(dated)}")
    print("  начало интервала по десятилетиям: " + ", ".join(
        f"{d}-е — {n}" for d, n in sorted(collections.Counter(
            r.year_from // 10 * 10 for r in recs).items())))
    print("  конец интервала по десятилетиям: " + ", ".join(
        f"{d}-е — {n}" for d, n in sorted(collections.Counter(
            r.year_to // 10 * 10 for r in recs).items())))

    report_dioceses(recs)

    print("\n  образцы:")
    for place in WATCH:
        for rec in [r for r in recs if r.place_text == place][:2]:
            print(f"    [{rec.region or rec.confidence}] {rec.title} ({rec.year_from}–"
                  f"{rec.year_to}): {rec.summary}")


def report_dioceses(recs: list) -> None:
    inside = collections.Counter(r.extra.get("diocese") for r in recs if r.confidence != OUTSIDE)
    outside = collections.Counter(r.extra.get("diocese") for r in recs if r.confidence == OUTSIDE)
    print("\n  диоцез: в рамке / вне рамки")
    for diocese in sorted(set(inside) | set(outside), key=lambda d: -(inside[d] + outside[d])):
        print(f"    {diocese or '—':<12} {inside[diocese]:>5} / {outside[diocese]:>5}")
    print("  губернии 1897 года, чаще всего: " + ", ".join(
        f"{g} — {n}" for g, n in collections.Counter(
            r.region for r in recs if r.region).most_common(10)))


def report_1938(features: list[dict], recs: list, counts: collections.Counter) -> None:
    print(f"Объектов в наборе: {len(features)}, записей: {len(recs)}")
    print(f"  с точкой: {sum(1 for r in recs if r.has_point)}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    print("  пометки: " + ", ".join(
        f"{c} — {n}" for c, n in collections.Counter(r.confidence for r in recs).most_common()))
    pairs = collections.Counter((r.extra.get("schematism_year"), r.extra.get("schematism_2_year"))
                                for r in recs)
    print("  годы схематизмов (основной, второй): " + ", ".join(
        f"{a}/{b or '—'} — {n}" for (a, b), n in pairs.most_common()))
    scans = sum(1 for r in recs if r.url and "/skany/" in r.url)
    print(f"  со ссылкой на скан схематизма: {scans}; "
          f"на Викиданные: {sum(1 for r in recs if 'wikidata' in r.extra)}")
    report_dioceses(recs)
    print("\n  образцы:")
    for place in ("Wilno", "Pińsk", "Brześć nad Bugiem", "Krzywcze", "Lwów"):
        for rec in [r for r in recs if r.place_text == place][:1]:
            print(f"    [{rec.region or rec.confidence}] {rec.title} ({rec.year_from}–"
                  f"{rec.year_to}): {rec.summary} {rec.url}")


REPORTS = {"1772": report_1772, "1938": report_1938}


def check(layer: str, cache: Path) -> int:
    dataset, _, _, spec = LAYERS[layer]
    problems = check_manifest(fetch_manifest(dataset), dataset)
    if problems:
        print(f"geo-ecclesiae {layer} (Zenodo {dataset.record}): файл не тот, что записан "
              "в коде:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"«{spec.title}»: перечень файлов записи Zenodo {dataset.record} сходится с кодом.")
    features, recs, counts = collect(layer, cache)
    if not recs:
        print("Ни одного храма не разобрано: проверьте разбор.", file=sys.stderr)
        return 1
    REPORTS[layer](features, recs, counts)
    print("\nНабор читается, разбор работает — можно запускать --build.")
    return 0


def build(layer: str, cache: Path, out_dir: Path) -> int:
    _, _, _, spec = LAYERS[layer]
    _, recs, counts = collect(layer, cache)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    geo = out_dir / "geojson" / f"{spec.slug}.geojson"
    # Права, источник и ссылка у всех записей одни — они выносятся на уровень
    # коллекции, как у остальных слоёв, собранных после 2026 года.
    n = write_geojson(recs, geo, layer_title=spec.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{spec.slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{spec.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{spec.slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{spec.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
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
    ap.add_argument("--layer", choices=[*LAYERS, "all"], default="all",
                    help="какой срез собирать (по умолчанию — все)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть файлы набора")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    layers = list(LAYERS) if args.layer == "all" else [args.layer]
    try:
        for layer in layers:
            if args.check:
                code = check(layer, args.cache)
                if code:
                    return code
            if args.build:
                code = build(layer, args.cache, args.out)
                if code:
                    return code
        return 0
    except GeoEcclesiaeError as exc:
        print(f"geo-ecclesiae: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
