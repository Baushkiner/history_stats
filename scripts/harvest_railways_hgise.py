#!/usr/bin/env python3
"""Сбор подложки железных дорог HGISE (Марти-Хеннеберг): срезы 1850–1970 годов.

    python3 scripts/harvest_railways_hgise.py --check    # набор, разбор, отчёт
    python3 scripts/harvest_railways_hgise.py --build    # подложка в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) достаёт из zip-архива
допматериалов Springer (21 МБ) только `Europe_railways.gpkg` (7 МБ) —
частичным чтением по Range, — кладёт его в `data/raw/railways_hgise/`,
сверяет размер и поля, переводит отрезки из EPSG:3035 в широту и долготу,
отбирает те, чья середина в рамке РИ/СССР, и показывает, что вышло: отрезки
и километры по срезам, окна открытия, губернии 1897 года. Повторный запуск
берёт файл из кэша.

Права: открытой лицензии нет; согласие владельца сообщено 24.11.2026.
Десятилетняя серия HGISE в сети не выложена — её нужно получить у проекта.

На выходе `boundaries/railways_hgise.geojson` — в репозиторий.
"""

from __future__ import annotations

import argparse
import collections
import sys
import zipfile
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import feature_collection, write_feature_collection
from histctx.net import RangeFile
from histctx.sources.geopackage import GeoPackageError, read_features
from histctx.sources.ghcn import GhcnError
from histctx.sources.railways_hgise import (
    CITATION, FIELDS, MEMBER, MEMBER_SIZE, RAILWAYS_HGISE, SNAPSHOTS, TABLE, YEAR_LIMIT,
    ZIP_URL, RailwaysError, segments,
)

CACHE = ROOT / "data" / "raw" / "railways_hgise"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"


def fetch(cache: Path) -> Path:
    path = cache / Path(MEMBER).name
    if path.exists() and path.stat().st_size == MEMBER_SIZE:
        return path
    cache.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(RangeFile(ZIP_URL, error=RailwaysError))
        data = archive.read(MEMBER)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise RailwaysError(f"{ZIP_URL}: в архиве нет {MEMBER} ({exc})") from exc
    if len(data) != MEMBER_SIZE:
        raise RailwaysError(f"{MEMBER}: {len(data)} байт, в коде {MEMBER_SIZE} — набор "
                            "сменился, сверьте руками")
    path.write_bytes(data)
    return path


def collect(cache: Path) -> tuple[list, list]:
    path = fetch(cache)
    try:
        raw = read_features(path, TABLE)
    except GeoPackageError as exc:
        raise RailwaysError(str(exc)) from exc
    missing = FIELDS - set().union(*(f["properties"] for f in raw[:50]))
    if missing:
        raise RailwaysError(f"{TABLE}: нет полей {', '.join(sorted(missing))}")
    try:
        frame = Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise RailwaysError(f"рамку взять неоткуда ({exc}): нужны границы из "
                            f"{BOUNDARIES.relative_to(ROOT)}") from exc
    return raw, segments(raw, frame.place)


def _km(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def report(raw: list, feats: list) -> None:
    km_all = sum(f["properties"].get("Length_km") or 0 for f in raw)
    print(f"В наборе отрезков: {len(raw)}, {_km(km_all)} км")
    km = sum(f["properties"].get("length_km", 0) for f in feats)
    print(f"В рамке РИ/СССР, с линией до {YEAR_LIMIT} года: {len(feats)}, {_km(km)} км")
    for y in SNAPSHOTS:
        here = [f for f in feats if f["properties"][f"state_{y}"] != "NE"]
        codes = collections.Counter(f["properties"][f"state_{y}"] for f in here)
        length = sum(f["properties"].get("length_km", 0) for f in here)
        print(f"  {y}: {len(here):>4} отрезков, {length:>6.0f} км  {dict(codes)}")
    print("Открытие:")
    for what, n in collections.Counter(f["properties"]["opened"] for f in feats).most_common():
        print(f"  {n:>4}  {what}")
    closed = collections.Counter(f["properties"].get("closed") for f in feats
                                 if f["properties"].get("closed"))
    print("Закрытие:", dict(closed.most_common()))
    regions = collections.Counter(f["properties"].get("region", "вне губерний 1897 года")
                                  for f in feats)
    print("Губернии 1897 года:")
    for what, n in regions.most_common(12):
        print(f"  {n:>4}  {what}")


def check(cache: Path) -> int:
    raw, feats = collect(cache)
    report(raw, feats)
    if not feats:
        print("В рамке ничего нет — разбор сломан.", file=sys.stderr)
        return 1
    print("\nРазбор работает — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    _, feats = collect(cache)
    if not feats:
        print("railways_hgise: ничего не собрано.", file=sys.stderr)
        return 1
    spec = RAILWAYS_HGISE
    collection = feature_collection(
        spec.slug, feats, license=spec.license, source=spec.source, citation=CITATION,
        url=spec.url, extra={"snapshots": list(SNAPSHOTS), "download": ZIP_URL})
    path = out_dir / "boundaries" / f"{spec.slug}.geojson"
    n = write_feature_collection(collection, path, compact=True)
    print(f"«{spec.title}»: {n} отрезков → {path.relative_to(ROOT)} "
          f"({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="достать набор, показать разбор")
    ap.add_argument("--build", action="store_true", help="записать подложку в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except RailwaysError as exc:
        print(f"HGISE: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
