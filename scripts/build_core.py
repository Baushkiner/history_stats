#!/usr/bin/env python3
"""Собирает исходные файлы проекта в единый нормализованный массив.

    python3 scripts/build_core.py --raw data/raw --out data/out

На выходе:
    data/out/geojson/<слой>.geojson   — по файлу на слой для карты
    data/out/all_layers.xlsx          — все слои, по вкладке на слой
    data/out/context.jsonl            — общий массив для загрузки в базу
    data/out/report.md                — отчёт о качестве данных
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.adapters import (  # noqa: E402
    load_battles, load_literary_places, load_prokudin_gorsky, load_state_events, load_tenishev,
)
from histctx.adapters.battles import BATTLES  # noqa: E402
from histctx.adapters.bookplaces import LITERARY, TENISHEV  # noqa: E402
from histctx.adapters.prokudin_gorsky import PROKUDIN  # noqa: E402
from histctx.adapters.state_events import STATE_EVENTS  # noqa: E402
from histctx.io_formats import (  # noqa: E402
    write_geojson, write_jsonl, write_records_json, write_xlsx_multi,
)
from histctx.schema import GROUPS  # noqa: E402

# Какой файл каким адаптером читать. Имена ищутся подстрокой, чтобы работали
# и «bookplaces_data.xlsx», и выгрузка с префиксом.
SOURCES = [
    ("bookplaces", LITERARY, load_literary_places),
    ("bookplaces", TENISHEV, load_tenishev),
    ("battles", BATTLES, load_battles),
    ("prokudin", PROKUDIN, load_prokudin_gorsky),
]


def find_file(raw_dir: Path, needle: str) -> Path | None:
    hits = sorted(p for p in raw_dir.glob("*.xlsx") if needle in p.name.lower())
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--curated", type=Path, default=ROOT / "data" / "curated",
                    help="подборки, которые ведутся вручную и лежат в репозитории")
    args = ap.parse_args()

    if not args.raw.is_dir():
        print(f"Нет каталога с исходными файлами: {args.raw}", file=sys.stderr)
        return 1

    layers: dict[str, list] = {}
    specs: dict[str, object] = {}
    missing: list[str] = []

    # Территориальные события лежат в самом репозитории: их не выгрузишь
    # запросом, и xlsx для них не нужен.
    events_path = args.curated / "state_events.json"
    if events_path.exists():
        records = load_state_events(events_path)
        layers[STATE_EVENTS.slug] = records
        specs[STATE_EVENTS.slug] = STATE_EVENTS
        print(f"  {STATE_EVENTS.title}: {len(records)} записей  <- {events_path.name}")
    else:
        missing.append(f"{STATE_EVENTS.title} (ожидался файл {events_path})")

    for needle, spec, loader in SOURCES:
        path = find_file(args.raw, needle)
        if path is None:
            missing.append(f"{spec.title} (ожидался файл *{needle}*.xlsx)")
            continue
        records = loader(path)
        layers[spec.slug] = records
        specs[spec.slug] = spec
        print(f"  {spec.title}: {len(records)} записей  <- {path.name}")

    if missing:
        for m in missing:
            print(f"  ПРОПУЩЕН: {m}", file=sys.stderr)
    if not layers:
        print("Не найдено ни одного исходного файла.", file=sys.stderr)
        return 1

    geo_dir = args.out / "geojson"
    total_features = 0
    territorial: list = []
    for slug, records in layers.items():
        # На карту отдаём только то, что реально можно показать.
        mappable = [r for r in records if r.has_point and r.confidence != "not_an_event"]
        territorial += [r for r in records if not r.has_point and r.is_territorial]
        if not mappable:
            continue
        n = write_geojson(mappable, geo_dir / f"{slug}.geojson", layer_title=specs[slug].title)
        total_features += n
        print(f"  geojson/{slug}.geojson: {n} точек")

    if territorial:
        # У этих событий нет геометрии, поэтому в GeoJSON им места нет:
        # на карте они показываются лентой времени, а не точками.
        write_records_json(territorial, args.out / "territorial_events.json",
                           title="События без точки: губернии и государство")
        print(f"  territorial_events.json: {len(territorial)} событий без точки")

    all_records = [r for recs in layers.values() for r in recs]
    write_jsonl(all_records, args.out / "context.jsonl")
    counts = write_xlsx_multi({specs[s].title: r for s, r in layers.items()}, args.out / "all_layers.xlsx")

    report = build_report(layers, specs, total_features)
    (args.out / "report.md").write_text(report, encoding="utf-8")

    print(f"\nВсего записей: {len(all_records)}, точек на карте: {total_features}, "
          f"событий без точки: {len(territorial)}")
    print(f"XLSX: {counts}")
    print(f"Отчёт: {args.out / 'report.md'}")
    return 0


def build_report(layers: dict, specs: dict, total_features: int) -> str:
    lines = ["# Отчёт о качестве данных", ""]
    lines.append("Пересобирается скриптом `scripts/build_core.py`.")
    lines.append("")
    lines.append("| Слой | Записей | С координатами | С датировкой | Годно для подбора |")
    lines.append("|---|---:|---:|---:|---:|")

    grand = Counter()
    for slug, records in layers.items():
        n = len(records)
        pts = sum(1 for r in records if r.has_point)
        tm = sum(1 for r in records if r.has_time)
        ok = sum(1 for r in records if r.usable and r.confidence not in {"not_an_event", "outside_bbox"})
        grand["n"] += n
        grand["pts"] += pts
        grand["tm"] += tm
        grand["ok"] += ok
        # Территориальному событию координаты не нужны — прочерк вместо нуля,
        # иначе слой выглядит сломанным.
        coords = "—" if pts == 0 and all(r.is_territorial for r in records) else f"{pts} ({_pct(pts, n)})"
        lines.append(f"| {specs[slug].title} | {n} | {coords} | {tm} ({_pct(tm, n)}) | {ok} ({_pct(ok, n)}) |")
    lines.append(f"| **Итого** | **{grand['n']}** | **{grand['pts']}** | **{grand['tm']}** | **{grand['ok']}** |")
    lines.append("")

    territorial = [r for records in layers.values() for r in records if r.is_territorial]
    if territorial:
        lines.append("## События без точки")
        lines.append("")
        lines.append(f"Всего {len(territorial)}: подбираются по губернии и годам, а не по расстоянию.")
        lines.append("")
        by_scope = Counter(r.scope for r in territorial)
        lines.append(f"- на всё государство: {by_scope.get('state', 0)}")
        lines.append(f"- на названные губернии: {by_scope.get('region', 0)}")
        named = sorted({name for r in territorial for name in r.regions})
        lines.append(f"- различных губерний и областей в перечнях: {len(named)}")
        lines.append("")
        by_category = Counter(r.category for r in territorial if r.category)
        for category, cnt in by_category.most_common():
            lines.append(f"- {category}: {cnt}")
        lines.append("")

    lines.append("## Что мешает показу на карте")
    lines.append("")
    problems = Counter()
    for records in layers.values():
        for r in records:
            if r.is_territorial:
                continue
            if r.confidence != "ok":
                problems[r.confidence] += 1
            if not r.has_time:
                problems["no_period"] += 1
    labels = {
        "no_coords": "нет координат — точка не встанет на карту",
        "outside_bbox": "координаты вне территории РИ/СССР — вероятно, не наш контекст",
        "not_an_event": "это воинская часть или корабль, а не событие на местности",
        "place_level": "координата указывает на населённый пункт, а не на само место события",
        "no_period": "не разобрана датировка — запись не участвует в подборе по времени",
    }
    for key, cnt in problems.most_common():
        lines.append(f"- **{cnt}** — {labels.get(key, key)}")
    lines.append("")

    lines.append("## Точность датировок")
    lines.append("")
    prec = Counter(r.date_precision for records in layers.values() for r in records)
    names = {"day": "до дня", "month": "до месяца", "season": "до сезона", "year": "до года",
             "decade": "до десятилетия", "part": "часть века", "century": "век целиком",
             "era": "именованная эпоха", "unknown": "не определена"}
    for key, cnt in prec.most_common():
        lines.append(f"- {names.get(key, key)}: {cnt}")
    lines.append("")

    lines.append("## Покрытие по губерниям")
    lines.append("")
    regions = Counter(r.region for records in layers.values() for r in records if r.region)
    lines.append(f"Губерния определена у {sum(regions.values())} записей, различных губерний: {len(regions)}.")
    lines.append("")
    for region, cnt in regions.most_common(15):
        lines.append(f"- {region}: {cnt}")
    lines.append("")

    lines.append("## Группы слоёв")
    lines.append("")
    for slug, records in layers.items():
        g = specs[slug].group
        lines.append(f"- {specs[slug].title} — группа «{GROUPS.get(g, g)}», {len(records)} записей")
    lines.append("")
    return "\n".join(lines)


def _pct(part: int, total: int) -> str:
    return "0%" if not total else f"{100 * part / total:.0f}%"


if __name__ == "__main__":
    raise SystemExit(main())
