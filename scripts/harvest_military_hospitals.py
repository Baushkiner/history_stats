#!/usr/bin/env python3
"""Сбор слоя госпиталей РККА 1941–1945 годов: справочник дислокации на soldat.ru.

    python3 scripts/harvest_military_hospitals.py --check    # живая проба, разбор, без записи
    python3 scripts/harvest_military_hospitals.py --fetch    # обход справочника (часы), с кэшем
    python3 scripts/harvest_military_hospitals.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) делает несколько живых запросов: страницу формы, выдачу по
Вологодской области (147 записей на 22.11.2026) со всеми её страницами — число
записей должно сойтись со счётчиком сайта — и форму правки одной записи;
печатает, что разобралось. Расхождение — остановка, а не подгонка.

`--fetch` обходит справочник деревом запросов (по району, типу и месту, см.
шапку `sources/military_hospitals.py`) с паузой не меньше секунды и кэширует
каждый ответ в `data/raw/military_hospitals/pages/`: оборванный обход
продолжается тем же `--fetch`. Итог обхода — `records.json` и `tree.json`
там же. Дерево сверяется со счётчиками сайта: где он не обрезан, сумма по
детям должна совпасть с ним.

`--build` сводит места дислокации с точками (Викиданные, GeoNames из слоя
`settlements`) и пишет слой. Права на справочник не выяснены; сайт требует
активную ссылку на использованную страницу — она стоит в каждой записи.

На выходе:

* `geojson/military_hospitals.geojson` — записи с точкой места дислокации;
* `military_hospitals.json` — записи, которым точки не нашлось: в
  репозиторий идут оба файла, `jsonl/` в `.gitignore`;
* `jsonl/military_hospitals.jsonl` — слой целиком.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.military_hospitals import (
    CAP, F_REGION, MILITARY_HOSPITALS, SEARCH_URL, Crawler, HospitalsError, Node,
    candidates_from_rows, check_tree, choose, geonames_index, load_records, lookup_names,
    missing_pids, place_names, post, record, region_hint, wikidata_query,
)
from histctx.sources.wikidata import SparqlClient, SparqlError

CACHE = ROOT / "data" / "raw" / "military_hospitals"
WD_CACHE = ROOT / "data" / "cache" / "military_hospitals"
SETTLEMENTS = ROOT / "data" / "out" / "geojson" / "settlements.geojson"
VARIANTS = ROOT / "data" / "out" / "name_variants.json"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"

# Проба `--check`: выдача по Вологодской области — 147 записей на 22.11.2026.
PROBE_REGION = "Вологодская*"
PROBE_PID = 7782


def check(cache: Path) -> int:
    probe_cache = cache / "probe"
    # Проба всегда живая: кэш пробы чистится, чтобы проверялся сайт, а не диск.
    if probe_cache.exists():
        for path in (probe_cache / "pages").glob("*.html"):
            path.unlink()
    crawler = Crawler(probe_cache, pause=1.2, log=print)
    raw = post(SEARCH_URL, {})
    text = raw.decode("cp1251", errors="replace")
    if "fields[hospobl.name]" not in text:
        print("Форма поиска не нашлась на странице: сайт переверстали.", file=sys.stderr)
        return 1
    print("Форма поиска на месте: поля номера, типа, места, района, даты.")
    first, recs = crawler.all_pages({F_REGION: PROBE_REGION})
    pids = {r.pid for r in recs}
    print(f"«{PROBE_REGION}»: счётчик сайта {first.count}, страниц {first.pages}, "
          f"записей разобрано {len(recs)}, разных {len(pids)}")
    if first.count >= CAP or len(pids) != first.count:
        print("Число записей не сошлось со счётчиком: разбор устарел.", file=sys.stderr)
        return 1
    kinds = collections.Counter(r.kind for r in recs)
    print("  типы:", ", ".join(f"{k} — {n}" for k, n in kinds.most_common(6)))
    dated = sum(1 for r in recs if r.start or r.end)
    print(f"  с датами: {dated}, только с «по»: {sum(1 for r in recs if r.end and not r.start)}, "
          f"без номера: {sum(1 for r in recs if not r.number)}")
    for r in recs[:3]:
        print(f"  {r.pid}: {r.kind} {r.number or 'б/н'} — {r.place}, {r.region}; "
              f"{r.start_raw or '…'} — {r.end_raw or '…'}; {r.note or ''}")
    rec = crawler.edit(PROBE_PID)
    if rec is None:
        print(f"Форма правки записи {PROBE_PID} не разобралась.", file=sys.stderr)
        return 1
    print(f"Форма правки {PROBE_PID}: {rec.kind} — {rec.place}, {rec.region}")
    print("\nСайт отвечает, разбор работает — можно запускать --fetch.")
    return 0


def tree_report(trees: dict) -> None:
    for name, tree in trees.items():
        node = tree if isinstance(tree, Node) else None
        if node is None:
            continue
        problems = check_tree(node)
        print(f"  дерево «{name}»: записей {node.got}, расхождений со счётчиком "
              f"{len(problems)}")
        for problem in problems[:20]:
            print(f"    {problem}")


def fetch(cache: Path, pause: float) -> int:
    crawler = Crawler(cache, pause=pause, log=lambda s: print(s, flush=True))
    trees = crawler.crawl()
    print(f"\nЗаписей: {len(crawler.records)}; запросов к сайту {crawler.requests}, "
          f"из кэша {crawler.hits}")
    tree_report(trees)
    if crawler.truncated:
        print(f"  обрезано на {CAP} ({len(crawler.truncated)}):")
        for fields in crawler.truncated:
            print(f"    {fields}")
    gaps = missing_pids(crawler.records)
    print(f"  номеров записей {min(crawler.records)}–{max(crawler.records)}, "
          f"пропусков в нумерации {len(gaps)}")
    sample = sorted(random.Random(22).sample(gaps, min(40, len(gaps)))) if gaps else []
    found = [r for r in (crawler.edit(pid) for pid in sample) if r is not None]
    print(f"  выборка пропусков через форму правки: {len(sample)}, из них записей "
          f"есть {len(found)}")
    for r in found[:15]:
        print(f"    {r.pid}: {r.kind} {r.number or 'б/н'} — {r.place or '?'}, "
              f"{r.region or 'район не указан'}")
    (cache / "gaps_sample.json").write_text(
        json.dumps({"sample": sample, "found": [r.to_json() for r in found]},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def wikidata_index(raws: list, *, batch: int = 40, cache_dir: Path = WD_CACHE) -> dict:
    """Кандидаты Викиданных по всем написаниям мест.

    Ответы кэшируются по названию, а не по запросу: пачка из сорока названий
    при новом обходе справочника сложится иначе, а название останется тем же —
    и спрашивать его второй раз незачем. Название без ответа тоже записывается.
    """
    path = cache_dir / "by_name.json"
    known: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names = lookup_names(raws)
    todo = [n for n in names if n not in known]
    client = SparqlClient()
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        got: dict = {n: [] for n in chunk}
        for row in client.query(wikidata_query(chunk), use_cache=False):
            got.setdefault(row.get("name", {}).get("value"), []).append(row)
        known.update(got)
        if (i // batch) % 10 == 9 or i + batch >= len(todo):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
            print(f"  Викиданные: {min(i + batch, len(todo))} новых названий из {len(todo)}",
                  flush=True)
    return candidates_from_rows(row for n in names for row in known.get(n, []))


def collect(cache: Path) -> tuple[list, list, dict]:
    raws = load_records(cache)
    print(f"Записей справочника: {len(raws)}; мест {len({r.place for r in raws})}, "
          f"районов {len({r.region for r in raws})}", flush=True)
    wd = wikidata_index(raws)
    features = json.loads(SETTLEMENTS.read_text(encoding="utf-8"))["features"]
    variants = json.loads(VARIANTS.read_text(encoding="utf-8")).get("items", {})
    gn = geonames_index(features, variants)
    placements: dict = {}
    for raw in raws:
        key = (raw.place, raw.region)
        if key not in placements:
            placements[key] = choose(place_names(raw.place), region_hint(raw.region), wd, gn)
    recs = [record(raw, placements[(raw.place, raw.region)]) for raw in raws]
    counts = Frame.load(BOUNDARIES).mark(recs)
    return raws, recs, counts


def report(raws: list, recs: list, counts) -> None:
    with_point = [r for r in recs if r.has_point]
    print(f"Записей слоя {len(recs)}: с точкой {len(with_point)}, без точки "
          f"{len(recs) - len(with_point)}")
    print("Рамка:", ", ".join(f"{k} — {v}" for k, v in counts.items()))
    print("Типы:", ", ".join(f"{k} — {n}" for k, n in collections.Counter(
        r.category for r in recs).most_common(12)))
    print("Точность дат:", ", ".join(f"{k} — {n}" for k, n in collections.Counter(
        r.date_precision for r in recs).most_common()))
    print("По годам начала:", ", ".join(f"{k} — {n}" for k, n in sorted(collections.Counter(
        r.year_from for r in recs).items())))
    how = collections.Counter((r.extra.get("place_match") or "").split(",")[0] for r in recs)
    print("Как найдены места:", ", ".join(f"{k} — {n}" for k, n in how.most_common()))
    lost = collections.Counter((r.place_text, r.extra.get("region_wartime"))
                               for r in recs if not r.has_point)
    print(f"Не сведено мест {len(lost)}, записей {sum(lost.values())}; чаще всего:")
    for (place, region), n in lost.most_common(25):
        print(f"  {n:>4}  {place} — {region or 'район не указан'}")


def build(cache: Path, out_dir: Path) -> int:
    raws, recs, counts = collect(cache)
    report(raws, recs, counts)
    slug = MILITARY_HOSPITALS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=MILITARY_HOSPITALS.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        # Записей без точки тысячи: общие свойства — в шапку, без отступов.
        write_records_json(off_map, json_path, title=f"{MILITARY_HOSPITALS.title}: без точки",
                           hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"\n«{MILITARY_HOSPITALS.title}»: {len(recs)} записей, на карте {n}, "
          f"без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="живая проба и разбор — без обхода и без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="обойти справочник (с кэшем)")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--pause", type=float, default=1.0, help="пауза между запросами, с")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()

    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code:
                return code
        if args.fetch:
            code = fetch(args.cache, max(args.pause, 1.0))
            if code:
                return code
        if args.build:
            return build(args.cache, args.out)
        return 0
    except (HospitalsError, SparqlError) as exc:
        print(f"Справочник госпиталей: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
