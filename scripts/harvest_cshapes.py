#!/usr/bin/env python3
"""Сбор границ государств 1886–1960 из CShapes 2.0 (ETH Zurich).

    python3 scripts/harvest_cshapes.py --check    # что в наборе, без записи файлов
    python3 scripts/harvest_cshapes.py --build    # полигоны в data/out/boundaries

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--check`
показывает, сколько периодов пришло, сколько осталось после отбора по времени
и охвату и какие государства попали в слой. Собрать пустоту молча хуже, чем
остановиться.

Про обрывы соединения. `icr.ethz.ch` рвёт скачивание чаще, чем отдаёт его с
первого раза, — `Connection reset by peer` приходит примерно на двух запросах
из трёх. Скачивание идёт с повторами (`histctx.sources.cshapes.download`), и
если сбор всё-таки останавливается, стоит просто запустить его ещё раз: набор
кладётся в кэш и второй раз не качается.

Права. Набор под CC BY-NC-SA 4.0 — некоммерческая лицензия с указанием
авторства. Проект некоммерческий (решение записано в `docs/CATALOG.md`,
раздел «Каталог открыт»), поэтому полигоны выгружаются целиком; цитата
авторов и ссылка на набор идут в выходной файл.

На выходе — `boundaries/state_borders.geojson`: подложка карты, к схеме
контекста границы не приводятся (`docs/HARVEST.md`, раздел «Границы»),
поэтому записей слой не даёт ни одной — как и `admin_boundaries_1897`.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources.cshapes import (  # noqa: E402
    RUSSIA_GWCODE, STATE_BORDERS, YEAR_MAX, YEAR_MIN, CShapesError, collection,
    load, select, states, write,
)

CACHE = ROOT / "data" / "cache" / "boundaries"


def check(feats: list, *, region_only: bool) -> int:
    print(f"Периодов в наборе: {len(feats)}")
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

    in_window = select(feats, region_only=False)
    picked = in_window if not region_only else select(feats, region_only=True)
    print(f"\nВ рамке {YEAR_MIN}–{YEAR_MAX}: {len(in_window)} периодов")
    print(f"Из них с территорией в охвате РИ/СССР: {len(picked)}")
    if not picked:
        print("  Ни один период не отобран: проверьте рамку и охват.")
        return 1

    by_state = collections.Counter(
        (f.get("properties") or {}).get("state") for f in picked)
    print(f"  государств: {len(by_state)}")
    for name, count in sorted(by_state.items()):
        print(f"    {count:>3}  {name}")

    print("\n  как менялась граница России:")
    for feature in picked:
        props = feature.get("properties") or {}
        # Опознаём по номеру Gleditsch — Ward, а не по названию: название
        # переводится и однажды будет переведено иначе.
        if props.get("gwcode") != RUSSIA_GWCODE:
            continue
        print(f"    {props.get('date_from')} — {props.get('date_to')}  "
              f"столица: {props.get('capital')}")

    print("\nНабор читается, разбор работает — можно запускать --build.")
    return 0


def build(feats: list, out_dir: Path, *, region_only: bool) -> int:
    picked = select(feats, region_only=region_only)
    if not picked:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    # Мировая выборка кладётся под своим именем. Иначе `--world` молча
    # подменил бы опубликованный слой набором вчетверо больше, оставив в нём
    # прежнее описание «государства в охвате РИ/СССР».
    name = STATE_BORDERS.slug if region_only else f"{STATE_BORDERS.slug}_world"
    path = out_dir / "boundaries" / f"{name}.geojson"
    count = write(collection(picked), path)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Границ государств: {count} периодов у {len(states(picked))} государств "
          f"→ {path.relative_to(ROOT)} ({size_mb:.1f} МБ)")
    print(f"«{STATE_BORDERS.title}» записей схемы не дают: это подложка карты.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="показать, что в наборе")
    ap.add_argument("--build", action="store_true", help="записать полигоны")
    ap.add_argument("--world", action="store_true",
                    help="не отсекать государства вне охвата РИ/СССР")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанный архив набора")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")

    region_only = not args.world
    try:
        # Набор читается один раз на запуск: при `--check --build` это разбор
        # 13 МБ архива и полумиллиона вершин, делать его дважды незачем.
        feats = load(args.cache)
        if args.check:
            code = check(feats, region_only=region_only)
            if code or not args.build:
                return code
        return build(feats, args.out, region_only=region_only)
    except CShapesError as exc:
        print(f"CShapes: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
