#!/usr/bin/env python3
"""Сбор двух слоёв из пакета Дауэра, Финкеля, Гельбаха и Нафцигера (Harvard Dataverse).

    python3 scripts/harvest_reforms_1851.py --check    # перечень по API, сверка, разбор
    python3 scripts/harvest_reforms_1851.py --build    # записи в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) запрашивает перечень
файлов набора, сверяет id, имена, размеры и лицензию с записанным в
`sources/reforms_1851.py`, скачивает три таблицы в `data/raw/reforms_1851/`,
проверяет колонки, разбирает их в записи и перечисляет уезды, которым не
нашлось пары среди уездов 1897 года RISTAT. Расхождение с перечнем —
остановка, а не подгонка.

Права: CC0 1.0 (карточка набора); ссылка на набор стоит в каждой записи.

На выходе — два слоя без точки (охват «уезд внутри губернии»):

* `peasant_unrest_1851.json` — крестьянские волнения 1851–1871 годов,
  запись «уезд-год»;
* `reforms_uezd.json` — уезд после реформ: шесть сюжетов 1857–1893 годов.

Оба файла идут в репозиторий; рядом — `jsonl/` (в `.gitignore`). Нужен
`data/out/boundaries/districts_1897.geojson` (`harvest_admin_gis.py --build`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_jsonl, write_records_json
from histctx.sources.dataverse import DataverseError, cached, check_manifest, fetch_manifest
from histctx.sources.reforms_1851 import (
    DATA_FILES, DATASET_URL, DOI, EVENTS, FILES, LICENSE_NAME, PEASANT_UNREST, REFORMS_UEZD,
    REQUIRED_EVENTS, REQUIRED_JOIN, REQUIRED_VARIABLES, UEZD_JOIN, VARIABLES, Places,
    ReformsError, check_columns, read_stata, read_table, reforms_records, shared_events,
    unrest_records,
)
from histctx.sources.uezd_names import RistatDistricts

CACHE = ROOT / "data" / "raw" / "reforms_1851"
DISTRICTS_1897 = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"


def collect(cache_dir: Path, districts_path: Path) -> dict:
    if not districts_path.exists():
        raise ReformsError(f"нет справочника уездов 1897 года: {districts_path}. Сначала "
                           "`python3 scripts/harvest_admin_gis.py --build`")
    index = RistatDistricts.load(districts_path)
    paths = {f.name: cached(f, cache_dir, error=ReformsError) for f in DATA_FILES}
    events = read_stata(paths[EVENTS.name])
    check_columns(events[0].keys() if events else [], REQUIRED_EVENTS, EVENTS.name)
    variables = read_stata(paths[VARIABLES.name])
    check_columns(variables[0].keys() if variables else [], REQUIRED_VARIABLES, VARIABLES.name)
    join = read_table(paths[UEZD_JOIN.name])
    check_columns(join[0].keys() if join else [], REQUIRED_JOIN, UEZD_JOIN.name)
    places = Places(variables, join, index)
    return {"events": events, "variables": variables, "join": join, "index": index,
            "unrest": unrest_records(events, places),
            "reforms": reforms_records(variables, places)}


def _report_places(records: list, index: RistatDistricts, label: str) -> None:
    by_place = {}
    for rec in records:
        by_place.setdefault(rec.extra.get("masterid"), rec)
    how = collections.Counter(r.extra.get("ristat_match") or "нет пары" for r in by_place.values())
    print(f"  уездов {label}: {len(by_place)}; сверка с RISTAT 1897: "
          + ", ".join(f"{k} {v}" for k, v in how.most_common()))
    for rec in by_place.values():
        if rec.confidence == "district_unmatched":
            known = ", ".join(index.names(rec.region)) or "губерния не найдена"
            print(f"    без пары: {rec.place_text}  (в справочнике: {known})")


def check(cache_dir: Path, districts_path: Path) -> int:
    print(f"Карточка набора: {DATASET_URL}")
    manifest = fetch_manifest(DOI, error=ReformsError)
    print(f"Версия {manifest['version']}, лицензия {manifest['license']}; файлов "
          f"{len(manifest['files'])}, в перечне сборщика {len(FILES)}")
    problems = check_manifest(manifest, FILES, license_name=LICENSE_NAME)
    if problems:
        print("\nПеречень в коде расходится с набором — сбор остановлен:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    got = collect(cache_dir, districts_path)
    for f in DATA_FILES:
        print(f"  {f.file_id}  {f.cache_name:<30} {f.download_size:>9} байт  сходится")

    events = got["events"]
    years = collections.Counter(e.get("startyear") for e in events)
    print(f"\n{EVENTS.name}: строк {len(events)}, колонок {len(events[0])}; уездов "
          f"{len({e.get('masterid') for e in events})}, годы {min(years)}–{max(years)}")
    print(f"  событий в нескольких уездах сразу: {len(shared_events(events))}; без кода "
          f"действия (a пусто): {sum(1 for e in events if not e.get('a'))}")
    for code in ("ar", "at", "ac", "ag"):
        print(f"  {code}: {sum(1 for e in events if e.get(code))}")
    unrest = got["unrest"]
    print(f"Записей «уезд-год»: {len(unrest)}")
    for category, n in collections.Counter(r.category for r in unrest).most_common():
        print(f"  {n:>5}  {category}")
    _report_places(unrest, got["index"], "с волнениями")

    variables = got["variables"]
    print(f"\n{VARIABLES.cache_name}: строк {len(variables)}, колонок {len(variables[0])}")
    reforms = got["reforms"]
    print(f"Записей «уезд после реформ»: {len(reforms)}")
    for category, n in collections.Counter(r.category for r in reforms).most_common():
        print(f"  {n:>5}  {category}")
    _report_places(reforms, got["index"], "таблицы переменных")

    print("\n  примеры:")
    for rec in unrest[:1] + [r for r in unrest if r.extra["unrest"]["events"] > 3][:1] \
            + reforms[:6]:
        print(f"    {rec.title}\n      {rec.summary}")
    print("\nНабор на месте, перечень сходится, разбор работает — можно запускать --build.")
    return 0


def build(cache_dir: Path, out_dir: Path, districts_path: Path) -> int:
    got = collect(cache_dir, districts_path)
    for spec, records in ((PEASANT_UNREST, got["unrest"]), (REFORMS_UEZD, got["reforms"])):
        if not records:
            print(f"{spec.slug}: ничего не собрано.", file=sys.stderr)
            return 1
        path = out_dir / f"{spec.slug}.json"
        write_records_json(records, path, title=spec.title)
        write_jsonl(records, out_dir / "jsonl" / f"{spec.slug}.jsonl")
        unmatched = sum(1 for r in records if r.confidence == "district_unmatched")
        print(f"{spec.slug}: {len(records)} записей (без пары в RISTAT: {unmatched}) → "
              f"{path.relative_to(ROOT)} ({path.stat().st_size / 1_048_576:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить набор с перечнем, скачать, показать разбор")
    ap.add_argument("--build", action="store_true", help="собрать слои в файлы")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--districts", type=Path, default=DISTRICTS_1897)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache, args.districts)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.districts)
    except (ReformsError, DataverseError) as exc:
        print(f"Набор Dataverse: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
