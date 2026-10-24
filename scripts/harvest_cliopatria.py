#!/usr/bin/env python3
"""Сбор границ государств 1600–1885 из Cliopatria (Seshat, Zenodo).

    python3 scripts/harvest_cliopatria.py --check    # что в наборе, без записи слоя
    python3 scripts/harvest_cliopatria.py --build    # полигоны в data/out/boundaries

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--check`
сверяет перечень архива на Zenodo с размером и CRC32, записанными в коде,
скачивает набор (46 МБ, кладётся в кэш) и показывает, сколько строк осталось
после отбора по времени и охвату и как по ним менялась граница России.

Права. CC BY 4.0 — полигоны выгружаются целиком, цитата и ссылка на запись
Zenodo идут в выходной файл.

На выходе — `boundaries/state_borders_early.geojson`: подложка карты, к схеме
контекста границы не приводятся (`docs/HARVEST.md`, раздел «Границы»). С 1886
года границу ведёт `state_borders` (CShapes 2.0), и строки, заходящие за
1885 год, помечены `continues_in`.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.sources.cliopatria import (
    MEMBER, RUSSIA_WIKIDATA, STATE_BORDERS_EARLY, VERSION, YEAR_MAX, YEAR_MIN,
    CliopatriaError, cached, check_listing, collection, fetch_listing, read_member,
    select, states, untranslated, write,
)

CACHE = ROOT / "data" / "cache" / "boundaries"


def check(feats: list, *, region_only: bool) -> int:
    print(f"Строк в наборе: {len(feats)}")
    years = [(f.get("properties") or {}).get("FromYear") for f in feats]
    years = [y for y in years if isinstance(y, int)]
    print(f"  годы начала строк: {min(years)}–{max(years)}")
    kinds = collections.Counter((f.get("geometry") or {}).get("type") for f in feats)
    print(f"  геометрия: {dict(kinds)}")

    in_window = select(feats, region_only=False)
    picked = select(feats, region_only=True) if region_only else in_window
    print(f"\nВ рамке {YEAR_MIN}–{YEAR_MAX}: {len(in_window)} строк")
    print(f"Из них с территорией в охвате РИ/СССР: {len(picked)}")
    if not picked:
        print("  Ни одна строка не отобрана: проверьте рамку и охват.")
        return 1
    by_state = collections.Counter((f.get("properties") or {}).get("state") for f in picked)
    print(f"  политий: {len(by_state)}")
    for name, count in sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))[:25]:
        print(f"    {count:>3}  {name}")
    if len(by_state) > 25:
        print(f"    … и ещё {len(by_state) - 25}")
    missing = untranslated(picked)
    if missing:
        # Не ошибка: название идёт по-английски. Но словарь стоит дополнить.
        print(f"  без русского названия ({len(missing)}): {', '.join(missing)}")

    print("\n  как менялась граница России:")
    for feature in picked:
        props = feature.get("properties") or {}
        if not str(props.get("wikidata", "")).endswith(tuple("/" + q for q in RUSSIA_WIKIDATA)):
            continue
        tail = "  → дальше state_borders" if props.get("continues_in") else ""
        print(f"    {props.get('year_from')}–{props.get('year_to')}  "
              f"{props.get('state')}, {props.get('area_km2', 0):,} км²{tail}")

    print("\nНабор читается, разбор работает — можно запускать --build.")
    return 0


def build(feats: list, out_dir: Path, *, region_only: bool) -> int:
    picked = select(feats, region_only=region_only)
    if not picked:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    # Мировая выборка — под своим именем, как у CShapes: иначе `--world` молча
    # подменил бы опубликованный слой.
    name = STATE_BORDERS_EARLY.slug if region_only else f"{STATE_BORDERS_EARLY.slug}_world"
    path = out_dir / "boundaries" / f"{name}.geojson"
    count = write(collection(picked), path)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Границ государств: {count} строк у {len(states(picked))} политий "
          f"→ {path.relative_to(ROOT)} ({size_mb:.1f} МБ)")
    print(f"«{STATE_BORDERS_EARLY.title}» записей схемы не дают: это подложка карты.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="показать, что в наборе")
    ap.add_argument("--build", action="store_true", help="записать полигоны")
    ap.add_argument("--world", action="store_true",
                    help="не отсекать политии вне охвата РИ/СССР")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанный набор")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")

    region_only = not args.world
    try:
        if args.check:
            problems = check_listing(fetch_listing())
            if problems:
                print(f"Cliopatria {VERSION}: {MEMBER} на Zenodo не тот, что записан "
                      f"в коде:", file=sys.stderr)
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                return 1
            print(f"Cliopatria {VERSION}: перечень архива на Zenodo сходится с кодом.")
        feats = read_member(cached(args.cache))
        if args.check:
            code = check(feats, region_only=region_only)
            if code or not args.build:
                return code
        return build(feats, args.out, region_only=region_only)
    except CliopatriaError as exc:
        print(f"Cliopatria: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
