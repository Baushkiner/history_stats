#!/usr/bin/env python3
"""Сбор слоя немецких колоний и поселений из Germans from Russia Settlement Locations.

    python3 scripts/harvest_german_colonies.py --check    # скачать, сверить, разобрать
    python3 scripts/harvest_german_colonies.py --build    # записи в data/out
    python3 scripts/harvest_german_colonies.py --check --refresh   # скачать заново

Проверочный первый запуск обязателен, как у остальных сборщиков: `--check`
берёт со страницы `/htmlview` листа «GRSL-All Colonies» список вкладок,
скачивает их (40 вкладок, около 50 МБ CSV, пауза 1 с) и сводный лист
«Complete» (5 МБ) в `data/raw/german_colonies/`, сверяет листы между собой по
номеру места historic.place, разбирает, ставит губернию 1897 года и
показывает, что пришло: сколько мест по группам, у скольких год основания,
что вне рамки, как разобрались кириллические написания. Скачанное лежит в
кэше: `--build` и повторный `--check` идут из него, `--refresh` скачивает
заново.

Права. CC BY-SA 4.0 (страница данных GRSL). Берутся факты — точка, имена,
год, тип колонии, конфессия — и примечания составителя со ссылкой на
карточку места на historic.place.

На выходе:

* `geojson/german_colonies.geojson` — места с точкой, вместе с помеченными
  (`no_date` — год основания набору не известен; `outside_bbox` — вне
  рамки РИ/СССР; `after_1960`);
* `german_colonies.json` — места без точки, `confidence = no_coords`:
  в репозиторий идут оба файла, `jsonl/` в `.gitignore`;
* `jsonl/german_colonies.jsonl` — слой целиком.

Нужны `data/out/boundaries/provinces_1897.geojson` (RISTAT) и
`state_borders.geojson` (CShapes) — оба лежат в репозитории.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.german_colonies import (
    GERMAN_COLONIES, GROUPS_RU, HTMLVIEW_URL, GermanColoniesError, cached_sheets, merge,
    read_complete, read_tab, records,
)
from histctx.sources.ghcn import GhcnError

CACHE = ROOT / "data" / "raw" / "german_colonies"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"

# Места, по которым видно, ради чего слой собран: три Гальбштадта в разных
# губерниях, колония с двумя кириллическими написаниями, исчезнувшая
# колония Крыма, деревня Восточной Пруссии в Калининградской области.
WATCH = ("355922472105", "316892471307", "789850532275", "457845511879",
         "315060468476", "341200457825", "209330544265", "445108485202")


def load_frame() -> Frame:
    try:
        return Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise GermanColoniesError(
            f"рамку взять неоткуда ({exc}). Нужны {BOUNDARIES.relative_to(ROOT)}/"
            "provinces_1897.geojson и state_borders.geojson — см. docs/HARVEST.md") from exc


def collect(cache: Path, *, refresh: bool = False):
    tabs, complete_text = cached_sheets(cache, refresh=refresh)
    tab_rows = []
    per_tab = collections.Counter()
    for name, _gid, text in tabs:
        rows = read_tab(text, name)
        per_tab[name] = len(rows)
        tab_rows.extend(rows)
    complete = read_complete(complete_text)
    rows, sverka = merge(tab_rows, complete)
    recs = records(rows)
    counts = load_frame().mark(recs)
    return tabs, per_tab, complete, sverka, recs, counts


def report(tabs, per_tab, complete, sverka, recs, counts) -> None:
    print(f"Вкладок «GRSL-All Colonies»: {len(tabs)}, мест во вкладках: {sum(per_tab.values())}; "
          f"в листе «Complete»: {len(complete)}")
    print("  сверка листов по номеру места historic.place:")
    for what, n in sverka.most_common():
        print(f"    {n:>6}  {what}")
    print(f"Записей слоя: {len(recs)}")
    with_point = sum(1 for r in recs if r.has_point)
    print(f"  с точкой: {with_point}; без точки: {len(recs) - with_point}")
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    print("  пометки:")
    for what, n in collections.Counter(r.confidence for r in recs).most_common():
        print(f"    {n:>6}  {what}")
    dated = [r for r in recs if r.year_from is not None]
    print(f"  с годом основания: {len(dated)} (приблизительно — "
          f"{sum(1 for r in dated if r.date_approx)}; год прихода колонистов «see notes» — "
          f"{sum(1 for r in dated if r.extra.get('year_is_settlers'))}); годы "
          f"{min(r.year_from for r in dated)}–{max(r.year_from for r in dated)}")
    print(f"  с кириллическим написанием немецкого имени: "
          f"{sum(1 for r in recs if r.extra.get('name_ru'))}; нынешнего имени: "
          f"{sum(1 for r in recs if r.extra.get('current_name_ru'))}; исчезнувших мест: "
          f"{sum(1 for r in recs if r.extra.get('defunct'))}")

    print("\n  группы колоний (мест / с годом / в губерниях 1897 года / вне рамки):")
    groups = collections.defaultdict(collections.Counter)
    for r in recs:
        g = groups[r.extra.get("group")]
        g["all"] += 1
        g["dated"] += r.year_from is not None
        g["province"] += bool(r.region)
        g["outside"] += r.confidence == "outside_bbox"
    for name, g in sorted(groups.items(), key=lambda kv: -kv[1]["all"]):
        print(f"    {g['all']:>6} / {g['dated']:>5} / {g['province']:>5} / "
              f"{g['outside']:>5}  {name}")
    print("  губернии 1897 года, чаще всего:")
    for name, n in collections.Counter(r.region for r in recs if r.region).most_common(15):
        print(f"    {n:>6}  {name}")
    print("  типы: " + ", ".join(f"{k} — {n}" for k, n in
                                 collections.Counter(r.category for r in recs).most_common()))
    unknown = sorted({r.extra.get("group") for r in recs} - set(GROUPS_RU.values()))
    if unknown:
        print(f"  вкладки без русского названия группы: {', '.join(unknown)}")

    print("\n  образцы:")
    by_id = {r.source_id: r for r in recs}
    for key in WATCH:
        rec = by_id.get(key)
        if rec is not None:
            print(f"    {rec.title} [{rec.region or rec.confidence}]")
            print(f"      {rec.summary}")


def check(cache: Path, refresh: bool) -> int:
    print(f"GRSL: список вкладок — {HTMLVIEW_URL}")
    data = collect(cache, refresh=refresh)
    if not data[4]:
        print("Ни одного места не разобрано: проверьте разбор.", file=sys.stderr)
        return 1
    report(*data)
    print("\nЛисты читаются, разбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path, refresh: bool) -> int:
    *_, recs, counts = collect(cache, refresh=refresh)
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = GERMAN_COLONIES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    # Права, источник и группа у всех записей одни — они выносятся на уровень
    # коллекции, как у остальных слоёв, собранных после 2026 года.
    n = write_geojson(recs, geo, layer_title=GERMAN_COLONIES.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{GERMAN_COLONIES.title}: без точки")
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{GERMAN_COLONIES.title}»: {len(recs)} записей, на карте {n}, без точки {len(off_map)}")
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
                    help="скачать, сверить, разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--refresh", action="store_true", help="скачать листы заново, мимо кэша")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть листы набора")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        if args.check:
            code = check(args.cache, args.refresh)
            if code or not args.build:
                return code
            args.refresh = False
        return build(args.cache, args.out, args.refresh)
    except GermanColoniesError as exc:
        print(f"GRSL: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
