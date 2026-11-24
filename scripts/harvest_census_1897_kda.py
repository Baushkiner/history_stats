#!/usr/bin/env python3
"""Сбор переписи 1897 года по уездам и городам со сборки k-da.dev/russia-1897.

    python3 scripts/harvest_census_1897_kda.py --check   # скачать, разобрать, отчёт
    python3 scripts/harvest_census_1897_kda.py --build   # записи в data/out

Запросов два: страница `https://k-da.dev/russia-1897/ru/` (около 3 КБ) и
сборка приложения, адрес которой взят со страницы
(`/russia-1897/assets/index-<хэш>.js`, около 5 МБ): хэш меняется с каждой
выкладкой сайта, и зашитый адрес устарел бы с первой же. Между запросами —
пауза; оба ответа ложатся в `data/raw/census_1897_kda/` (сборка — под своим
именем), `--build` и повторный `--check` берут их из кэша. `--refresh`
скачивает страницу заново; новая сборка скачивается, только если сменилось
её имя.

Формат сборки проверяется при каждом разборе (`census_1897_kda.parse_bundle`):
таблица модулей `../data/<губерния>/<уезд>.json`, не меньше 700 уездов, поля
модулей, словарь `ru` и таблица кодов губерний. Не сошлось — сборщик
останавливается с «формат сборки изменился», а не пишет слой из обломков.

Права: лицензия не заявлена; сборка взята с согласия владельца, полученного
владельцем проекта (сообщено 24.11.2026). Сборка — в `.gitignore`.

На выходе `census_1897_kda.json` (в репозиторий) и `jsonl/` (в `.gitignore`).
Нужен `data/out/boundaries/districts_1897.geojson` (уезды RISTAT, лежит в
репозитории); без него уезды не сводятся, а записи остаются.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

from _paths import ROOT

from histctx.geo import region_key
from histctx.io_formats import write_jsonl, write_records_json
from histctx.sources.census_1897_kda import (
    CENSUS_1897_KDA, PAGE_URL, KdaError, bundle_url, consistency, fetch, parse_bundle, records,
)
from histctx.sources.uezd_names import RistatDistricts

CACHE = ROOT / "data" / "raw" / "census_1897_kda"
DISTRICTS_1897 = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"
HEIDATA = ROOT / "data" / "out" / "admin_1897_gis.json"
PAUSE_SEC = 2.0

# Уезды и места, по которым видно, ради чего слой собран.
WATCH = ("Кирилловский уезд", "Читинский округ", "Бердичев", "Пинск", "Шуя")


def cached_bundle(cache: Path, refresh: bool) -> tuple[str, str]:
    page = cache / "page_ru.html"
    if refresh or not page.exists():
        cache.mkdir(parents=True, exist_ok=True)
        page.write_bytes(fetch(PAGE_URL))
        time.sleep(PAUSE_SEC)
    url = bundle_url(page.read_text(encoding="utf-8", errors="replace"))
    path = cache / url.rsplit("/", 1)[-1]
    if not path.exists():
        print(f"  сборка {url}", file=sys.stderr)
        path.write_bytes(fetch(url))
    return url, path.read_text(encoding="utf-8")


def collect(cache: Path, refresh: bool, districts: Path) -> tuple[list, dict]:
    url, text = cached_bundle(cache, refresh)
    bundle = parse_bundle(text)
    index = RistatDistricts.load(districts) if districts.exists() else None
    if index is None:
        print(f"  {districts} нет — уезды не сводятся с RISTAT", file=sys.stderr)
    recs = records(bundle, index)
    return recs, {"url": url, "bundle": bundle, "index": index,
                  "size": len(text.encode("utf-8"))}


def report(recs: list, meta: dict) -> None:
    bundle = meta["bundle"]
    print(f"Сборка: {meta['url']} ({meta['size'] / 1024 / 1024:.1f} МБ); модулей уездов "
          f"{meta['bundle'].module_paths}, губерний и областей {len(bundle.provinces)}")
    uezds = [r for r in recs if r.extra.get("unit") == "уезд"]
    places = [r for r in recs if r.extra.get("unit") != "уезд"]
    total = sum(r.extra["population"]["оба"] for r in uezds)
    shown = f"{total:,}".replace(",", " ")
    print(f"  записей {len(recs)}: уездов {len(uezds)}, мест с таблицей {len(places)}; "
          f"население по уездам {shown}")
    print(f"  точек: {sum(1 for r in recs if r.has_point)} (координат в данных нет)")
    print("  типы мест:")
    kinds = collections.Counter(r.extra.get("settlement_type_ru") or r.extra.get("settlement_type")
                                for r in places)
    for name, n in kinds.most_common():
        print(f"    {n:>5}  {name}")
    print("  сверка с уездами RISTAT:")
    for name, n in collections.Counter(r.extra.get("ristat_match") or "не сведён"
                                       for r in uezds).most_common():
        print(f"    {n:>5}  {name}")
    for r in uezds:
        if not r.extra.get("ristat_distr_id"):
            print(f"           — {r.district}, {r.region}")
    twice = [k for k, n in collections.Counter(r.extra.get("ristat_distr_id") for r in uezds
                                               if r.extra.get("ristat_distr_id")).items() if n > 1]
    if twice:
        print(f"  уезд RISTAT достался двум уездам сайта: {', '.join(twice)}")
    print("  суммы таблиц против итога населения:")
    for name, n in sorted(consistency(bundle).items()):
        print(f"    {n:>5}  {name}")
    compare_heidata(uezds)
    literate = [r for r in recs if "грамотность" in (r.extra.get("census_1897") or {})]
    print(f"  с грамотностью: {len(literate)} ({', '.join(r.place_text for r in literate)})")
    print("  примеры:")
    for want in WATCH:
        hits = [r for r in recs if r.district == want or r.place_text.startswith(want + ",")]
        for rec in hits[:2]:
            print(f"    {rec.title}\n      {rec.summary}")


# Как heiDATA называет единицы, которые у сайта названы иначе.
HEIDATA_NAMES = {"Елизаветопольская губерния": "Елисаветпольская губерния",
                 "Петербургская губерния": "Санкт-Петербургская губерния",
                 "Сахалин остров": "Остров Сахалин",
                 "Сырь-Дарьинская область": "Сырдарьинская область",
                 "Ревельская губерния": "Эстляндская губерния"}


def compare_heidata(uezds: list) -> None:
    """Сумма уездов губернии против итога губернии у heiDATA (`admin_1897_gis`).

    Два независимых перенабора одних и тех же томов: совпадение до человека —
    лучшая проверка, какая есть без самих томов.
    """
    if not HEIDATA.exists():
        print(f"  {HEIDATA.relative_to(ROOT)} нет — сверки с heiDATA не будет")
        return
    payload = json.loads(HEIDATA.read_text(encoding="utf-8"))
    ref = {}
    for rec in payload.get("records") or []:
        census = (rec.get("extra") or {}).get("census") or {}
        if rec.get("year_from") == 1897 and census.get("POPALL"):
            name = rec.get("region") or rec.get("place_text")
            ref[region_key(HEIDATA_NAMES.get(name, name))] = census["POPALL"]
    sums = collections.Counter()
    for r in uezds:
        sums[r.region] += r.extra["population"]["оба"]
    same = near = far = 0
    missing, worst = [], []
    for province, n in sums.items():
        want = ref.get(region_key(province))
        if want is None:
            missing.append(province)
        elif want == n:
            same += 1
        elif abs(n - want) <= 0.01 * want:
            near += 1
        else:
            far += 1
            worst.append((abs(n - want) / want, province, n, want))
    print(f"  губернии против heiDATA: до человека {same}, в пределах 1% {near}, дальше {far}, "
          f"нет пары {len(missing)}")
    for share, province, n, want in sorted(worst, reverse=True)[:8]:
        line = f"           {province}: {n:,} против {want:,} ({100 * share:.1f}%)"
        print(line.replace(",", " "))
    if missing:
        print(f"           без пары: {', '.join(sorted(missing))}")


def build(recs: list, out_dir: Path) -> int:
    slug = CENSUS_1897_KDA.slug
    path = out_dir / f"{slug}.json"
    write_records_json(recs, path, title=CENSUS_1897_KDA.title, hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{CENSUS_1897_KDA.title}»: {len(recs)} записей, без точки — все")
    for p in (path, jsonl):
        print(f"  → {p.relative_to(ROOT)} ({p.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="скачать, разобрать, напечатать отчёт — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--refresh", action="store_true",
                    help="скачать страницу заново (сборку — если сменилось имя)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--districts", type=Path, default=DISTRICTS_1897)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check или --build")
    try:
        recs, meta = collect(args.cache, args.refresh, args.districts)
    except KdaError as exc:
        print(f"k-da.dev: {exc}", file=sys.stderr)
        return 1
    if args.check:
        report(recs, meta)
        if not args.build:
            print("\nСборка читается, разбор работает — можно запускать --build.")
            return 0
    return build(recs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
