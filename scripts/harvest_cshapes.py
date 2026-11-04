#!/usr/bin/env python3
"""Сбор границ государств 1886–1960 по всему миру из CShapes 2.0 (ETH Zurich).

    python3 scripts/harvest_cshapes.py --check    # что в наборе, без записи файлов
    python3 scripts/harvest_cshapes.py --build    # полигоны в data/out/boundaries

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--check`
показывает, сколько периодов пришло, сколько осталось после отбора по
времени, сколько из них заходит в охват РИ/СССР, какие у периодов статусы
и владельцы и как менялась граница России. Собрать пустоту молча хуже, чем
остановиться.

Скачивается два файла с одного сайта: шейпфайл набора (13 МБ) и R-пакет
(4 МБ), в котором у тех же периодов записаны статус — колония, протекторат,
подмандатная или оккупированная территория — и государство-владелец.
Периоды сшиваются по номеру и датам; если хоть один период шейпфайла не
нашёл пары, сбор останавливается: слой со статусом у части стран врал бы
молчанием у остальных.

Про обрывы соединения. `icr.ethz.ch` рвёт скачивание чаще, чем отдаёт его с
первого раза, — `Connection reset by peer` приходит примерно на двух запросах
из трёх. Скачивание идёт с повторами (`histctx.sources.cshapes.download`), и
если сбор всё-таки останавливается, стоит просто запустить его ещё раз: оба
файла кладутся в кэш и второй раз не качаются.

Права. Набор под CC BY-NC-SA 4.0 — некоммерческая лицензия с указанием
авторства. Проект некоммерческий (решение записано в `docs/CATALOG.md`,
раздел «Каталог открыт»), поэтому полигоны выгружаются целиком; цитата
авторов и ссылка на набор идут в выходной файл.

На выходе — `boundaries/state_borders.geojson`, весь мир: подложка карты, к
схеме контекста границы не приводятся (`docs/HARVEST.md`, раздел «Границы»),
поэтому записей слой не даёт ни одной — как и `admin_boundaries_1897`.
`--region` пишет прежнюю выборку, только государства в охвате РИ/СССР, под
своим именем (`state_borders_region.geojson`, в репозиторий не идёт).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.sources.cshapes import (
    RUSSIA_GWCODE, STATE_BORDERS, YEAR_MAX, YEAR_MIN, CShapesError, collection,
    load, load_attributes, select, states, unmatched, untranslated, write,
)

CACHE = ROOT / "data" / "cache" / "boundaries"


def check(feats: list, attrs: dict) -> int:
    print(f"Периодов в наборе: {len(feats)}, со статусом из R-пакета: {len(attrs)}")
    sample = feats[0].get("properties") or {}
    print(f"  поля таблицы: {sorted(sample)}")

    # Пустое поле таблицы до свойств не доезжает (см. `shapefile.features`),
    # поэтому год берётся через get, а не по ключу.
    years = [p.get("gwsyear") for p in ((f.get("properties") or {}) for f in feats)]
    years = [y for y in years if isinstance(y, int)]
    if not years:
        print("  Ни у одного периода нет годного года начала: набор переделали "
              "и разбор надо править.", file=sys.stderr)
        return 1
    print(f"  годы начала периодов: {min(years)}–{max(years)}")
    kinds = collections.Counter((f.get("geometry") or {}).get("type") for f in feats)
    print(f"  геометрия: {dict(kinds)}")

    picked = select(feats, attrs=attrs)
    region = select(feats, attrs=attrs, region_only=True)
    print(f"\nВ рамке {YEAR_MIN}–{YEAR_MAX}: {len(picked)} периодов "
          f"у {len(states(picked))} государств и территорий")
    print(f"Из них с территорией в охвате РИ/СССР: {len(region)} "
          f"у {len(states(region))} (так слой выглядел до ноября 2026 года)")
    if not picked:
        print("  Ни один период не отобран: проверьте рамку.")
        return 1

    status = collections.Counter((f.get("properties") or {}).get("status") for f in picked)
    print("\n  статус периодов:")
    for name, count in status.most_common():
        print(f"    {count:>3}  {name}")
    owners = collections.Counter((f.get("properties") or {}).get("owner") for f in picked
                                 if (f.get("properties") or {}).get("owner"))
    print("  владельцы зависимых территорий:")
    for name, count in owners.most_common():
        print(f"    {count:>3}  {name}")
    undefined = sum(1 for f in picked
                    if (f.get("properties") or {}).get("border_defined") is False)
    print(f"  граница проведена не на всём протяжении: {undefined} периодов")
    missing = untranslated(picked)
    if missing:
        # Не ошибка: название идёт по-английски. Но словарь стоит дополнить.
        print(f"  без русского названия ({len(missing)}): {', '.join(missing)}")

    print("\n  как менялась граница России:")
    for feature in picked:
        props = feature.get("properties") or {}
        # Опознаём по номеру Gleditsch — Ward, а не по названию: название
        # переводится и однажды будет переведено иначе.
        if props.get("gwcode") != RUSSIA_GWCODE:
            continue
        print(f"    {props.get('date_from')} — {props.get('date_to')}  "
              f"столица: {props.get('capital')}")
    print("  земли под властью России, не входившие в неё:")
    for feature in picked:
        props = feature.get("properties") or {}
        if props.get("owner_gwcode") == RUSSIA_GWCODE:
            print(f"    {props.get('date_from')} — {props.get('date_to')}  "
                  f"{props.get('state')}: {props.get('status')}")

    print("\nНабор читается, разбор работает — можно запускать --build.")
    return 0


def build(feats: list, attrs: dict, out_dir: Path, *, region_only: bool) -> int:
    picked = select(feats, attrs=attrs, region_only=region_only)
    if not picked:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    # Выборка по охвату РИ/СССР кладётся под своим именем. Иначе `--region`
    # молча подменил бы опубликованный слой вчетверо меньшим, оставив в нём
    # описание «весь мир».
    name = f"{STATE_BORDERS.slug}_region" if region_only else STATE_BORDERS.slug
    path = out_dir / "boundaries" / f"{name}.geojson"
    count = write(collection(picked), path)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Границ государств: {count} периодов у {len(states(picked))} государств "
          f"и территорий → {path.relative_to(ROOT)} ({size_mb:.1f} МБ)")
    print(f"«{STATE_BORDERS.title}» записей схемы не дают: это подложка карты.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="показать, что в наборе")
    ap.add_argument("--build", action="store_true", help="записать полигоны")
    ap.add_argument("--region", action="store_true",
                    help="только государства в охвате РИ/СССР, отдельным файлом")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанные архив набора и R-пакет")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")

    try:
        # Набор читается один раз на запуск: при `--check --build` это разбор
        # 13 МБ архива и миллиона вершин, делать его дважды незачем.
        feats = load(args.cache)
        attrs = load_attributes(args.cache)
        lost = unmatched(feats, attrs)
        if lost:
            print(f"CShapes: у {len(lost)} периодов шейпфайла нет статуса в R-пакете "
                  f"(первые: {lost[:5]}). Наборы разошлись — сверьте версии.",
                  file=sys.stderr)
            return 1
        if args.check:
            code = check(feats, attrs)
            if code or not args.build:
                return code
        return build(feats, attrs, args.out, region_only=args.region)
    except CShapesError as exc:
        print(f"CShapes: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
