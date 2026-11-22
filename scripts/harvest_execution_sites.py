#!/usr/bin/env python3
"""Сбор слоя мест массовых расстрелов: карта Yahad – In Unum и атлас Литвы.

    python3 scripts/harvest_execution_sites.py --check   # точки карты, атлас, пять профилей
    python3 scripts/harvest_execution_sites.py --fetch   # все профили в кэш, с продолжением
    python3 scripts/harvest_execution_sites.py --build   # собрать слой из кэша

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
забирает все точки карты Yahad одним запросом, сверяет их число с замером
22.11.2026 (2 877), читает `robots.txt` атласа Литвы (пауза — не короче его
`Crawl-delay`) и его 229 мест, разбирает пять профилей сёл из разных концов
списка: название и таблица фактов должны быть на месте. Файлы слоя `--check`
не пишет; ответы кладёт в кэш.

`--fetch` складывает профили (1 762 на 22.11.2026) в
`data/raw/execution_sites/yahad/profiles/` — в `.gitignore`; при паузе 1,5 с
это около 45 минут. Оборванный обход продолжается тем же вызовом.
`--refresh` перечитывает точки карты и места атласа (профили — нет).

`--build` разбирает кэш (`--offline` — без докачки), сводит места атласа с
точками Yahad, ставит губернию 1897 года и пометку `outside_bbox` по
полигонам `data/out/boundaries`, отмечает гетто слоя `ghettos_camps` в
`--near-km` от места расстрела и пишет:

* `geojson/execution_sites.geojson` — в репозиторий;
* `jsonl/execution_sites.jsonl` — в `.gitignore`.

Права. Содержимое Yahad под авторским правом (некоммерческое образовательное
использование разрешено), атлас Литвы условий не публикует: берутся факты —
точка, село, период оккупации, число жертв, вид места, дата и шифр акта
ЧГК — и ссылка на профиль; свидетельства, выдержки и очерки остаются на
сайтах, имён людей в слое нет.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.robotparser
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.execution_sites import (
    EXECUTION_SITES, EXPECTED_HAL, EXPECTED_POINTS, HAL_CRAWL_DELAY, HAL_MARKERS, HAL_ROBOTS,
    PAUSE, YAHAD_MAP, YAHAD_POINTS_BODY, YAHAD_PROFILE, Client, ExecutionSitesError,
    check_profile, check_profiles, parse_hal, parse_points, parse_profile, profile_cache_name,
    records, villages,
)
from histctx.sources.russian_names import RussianNames
from histctx.sources.mapofmemory import mark_neighbours

CACHE = ROOT / "data" / "raw" / "execution_sites"
OUT = ROOT / "data" / "out"
BOUNDARIES = OUT / "boundaries"
NAMES = OUT / "name_variants.json"
POINTS_CACHE = "yahad/points.json"
HAL_CACHE = "hal/markers_en.js"
HAL_ROBOTS_CACHE = "hal/robots.txt"
NEAR_KM = 3.0
# Место расстрела — за околицей, у оврага или в лесу: русская подпись села ищется
# в 10 км, а не в 5, как у кладбищ.
NAME_KM = 10.0
NEIGHBOUR_LAYERS = ("ghettos_camps",)


def load_points(client: Client, *, refresh: bool) -> list:
    text = client.cached(POINTS_CACHE, YAHAD_MAP, data=YAHAD_POINTS_BODY, refresh=refresh)
    points = parse_points(text)
    linked = sum(1 for p in points if p.village is not None)
    broken = [p for p in points if p.lat is None]
    print(f"Точек на карте Yahad: {len(points)} (22.11.2026 — {EXPECTED_POINTS}); с профилем: "
          f"{linked}, «soon online»: {sum(1 for p in points if p.pending)}; профилей: "
          f"{len(villages(points))}")
    if broken:
        print(f"  без годной координаты {len(broken)} — останутся записями без точки: "
              + "; ".join(f"{p.name} ({p.coords_raw})" for p in broken))
    return points


def load_hal(cache: Path, *, refresh: bool) -> list:
    hal = Client(cache_dir=cache, pause=HAL_CRAWL_DELAY)
    robots_text = hal.cached(HAL_ROBOTS_CACHE, HAL_ROBOTS, refresh=refresh)
    parser = urllib.robotparser.RobotFileParser(HAL_ROBOTS)
    parser.parse(robots_text.splitlines())
    if not parser.can_fetch("*", HAL_MARKERS):
        raise ExecutionSitesError(f"robots.txt атласа закрывает {HAL_MARKERS}")
    delay = parser.crawl_delay("*")
    hal.pause = max(hal.pause, float(delay or 0))
    places = parse_hal(hal.cached(HAL_CACHE, HAL_MARKERS, refresh=refresh))
    print(f"Мест атласа Литвы: {len(places)} (22.11.2026 — {EXPECTED_HAL}); "
          f"пауза атласа {hal.pause:g} с")
    return places


def check(cache: Path, pause: float, sample: int) -> int:
    client = Client(cache_dir=cache, pause=pause)
    points = load_points(client, refresh=True)
    load_hal(cache, refresh=True)
    ns = villages(points)
    step = max(1, len(ns) // sample)
    names = RussianNames.load(NAMES, radius_km=NAME_KM) if NAMES.exists() else None
    for n in ns[::step][:sample]:
        profile = parse_profile(client.cached(profile_cache_name(n), YAHAD_PROFILE.format(n=n)))
        check_profile(profile, n)
        mine = [p for p in points if p.village == n]
        rec = records(mine, {n: profile}, [], names=names)[0]
        print(f"  {n}: {rec.title}; {rec.category}; {rec.year_from}–{rec.year_to} "
              f"({rec.date_precision}); жертв: {rec.extra.get('victims')!r}; "
              f"архив: {rec.extra.get('soviet_archive')}")
    print(f"\nЗапросов к Yahad: {client.requests}. Разбор работает — можно запускать "
          "--fetch и --build.")
    return 0


def fetch(cache: Path, pause: float, *, refresh: bool, limit=None) -> tuple[list, list]:
    client = Client(cache_dir=cache, pause=pause)
    points = load_points(client, refresh=refresh)
    places = load_hal(cache, refresh=refresh)
    ns = villages(points)
    todo = [n for n in ns if not (cache / profile_cache_name(n)).exists()]
    print(f"Профилей в кэше: {len(ns) - len(todo)}, докачать: {len(todo)}", flush=True)
    for i, n in enumerate(todo[:limit] if limit else todo, 1):
        client.cached(profile_cache_name(n), YAHAD_PROFILE.format(n=n))
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    return points, places


def load_profiles(cache: Path, points: list) -> tuple[dict, list[int]]:
    profiles, missing = {}, []
    for n in villages(points):
        path = cache / profile_cache_name(n)
        if not path.exists():
            missing.append(n)
            continue
        profile = parse_profile(path.read_text(encoding="utf-8"))
        check_profile(profile, n)
        profiles[n] = profile
    empty = check_profiles(profiles)
    if empty:
        print(f"  профилей без таблицы фактов (заготовки): {len(empty)} — {empty[:12]}; "
              "их записи остаются с рамкой оккупации")
    return profiles, missing


def load_neighbours(out_dir: Path) -> dict:
    others = {}
    for layer in NEIGHBOUR_LAYERS:
        path = out_dir / "geojson" / f"{layer}.geojson"
        if not path.exists():
            print(f"  нет {path}: сверка с {layer} пропущена")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        others[layer] = [
            (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0],
             f.get("id"), (f.get("properties") or {}).get("title"))
            for f in payload.get("features", [])
            if (f.get("geometry") or {}).get("type") == "Point"]
    return others


def build(cache: Path, out_dir: Path, pause: float, *, offline: bool, refresh: bool,
          near_km: float) -> int:
    if offline:
        for name in (POINTS_CACHE, HAL_CACHE):
            if not (cache / name).exists():
                raise ExecutionSitesError(f"нет {cache / name}: сначала --check или --fetch")
        points = parse_points((cache / POINTS_CACHE).read_text(encoding="utf-8"))
        places = parse_hal((cache / HAL_CACHE).read_text(encoding="utf-8"))
    else:
        points, places = fetch(cache, pause, refresh=refresh)
    profiles, missing = load_profiles(cache, points)
    if missing:
        print(f"Профилей нет в кэше: {len(missing)} ({missing[:10]}…) — слой не собирается "
              "неполным; запустите --fetch ещё раз", file=sys.stderr)
        return 1
    names = RussianNames.load(NAMES, radius_km=NAME_KM) if NAMES.exists() else None
    recs = records(points, profiles, places, names=names)
    marks = Frame.load(BOUNDARIES).mark(recs)
    near = mark_neighbours([r for r in recs if r.has_point], load_neighbours(out_dir),
                           radius_km=near_km)
    report(recs, marks, near, near_km)

    slug = EXECUTION_SITES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=EXECUTION_SITES.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{EXECUTION_SITES.title}: без точки")
    write_jsonl(recs, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"\n«{EXECUTION_SITES.title}»: {len(recs)} записей, на карте {n}")
    print(f"  → {geo.relative_to(ROOT)} ({geo.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def report(recs: list, marks: dict, near: dict, near_km: float) -> None:
    print(f"\nЗаписей: {len(recs)}; с датировкой: {sum(1 for r in recs if r.has_time)}")
    print("  наборы:", dict(collections.Counter(r.extra.get("source_set") for r in recs)))
    print("  рамка:", dict(marks))
    print("  точность дат:", dict(collections.Counter(r.date_precision for r in recs)))
    print("  страны:", dict(collections.Counter(r.extra.get("country") for r in recs)
                            .most_common()))
    print("  категории:", dict(collections.Counter(r.category for r in recs)))
    archived = [r.extra["soviet_archive"] for r in recs if r.extra.get("soviet_archive")]
    print(f"  со ссылкой на советский архив: {len(archived)} "
          f"({dict(collections.Counter(a.get('kind') for a in archived))}); с датой акта: "
          f"{sum(1 for a in archived if a.get('kind') == 'акт' and a.get('date'))}; "
          f"с памятным знаком: {sum(1 for r in recs if r.extra.get('memorial'))}")
    years = collections.Counter((r.year_from, r.year_to) for r in recs if r.has_time)
    print("  годы:", years.most_common(8))
    for layer, count in near.items():
        print(f"  рядом (до {near_km:g} км) точка слоя {layer}: {count}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="точки, атлас и пять профилей — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="все профили в кэш")
    ap.add_argument("--build", action="store_true", help="собрать слой в data/out")
    ap.add_argument("--offline", action="store_true", help="собирать только из кэша")
    ap.add_argument("--refresh", action="store_true", help="перечитать точки и атлас")
    ap.add_argument("--limit", type=int, default=None, help="--fetch: не больше N профилей")
    ap.add_argument("--sample", type=int, default=5, help="--check: сколько профилей")
    ap.add_argument("--pause", type=float, default=PAUSE, help="пауза к Yahad, с")
    ap.add_argument("--near-km", type=float, default=NEAR_KM)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check:
            return check(args.cache, args.pause, args.sample)
        if args.fetch and not args.build:
            points, _ = fetch(args.cache, args.pause, refresh=args.refresh, limit=args.limit)
            profiles, missing = load_profiles(args.cache, points)
            print(f"Разобрано профилей: {len(profiles)}; не хватает: {len(missing)}")
            return 0
        return build(args.cache, args.out, args.pause, offline=args.offline,
                     refresh=args.refresh, near_km=args.near_km)
    except ExecutionSitesError as exc:
        print(f"Места расстрелов: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; уже скачанное лежит в кэше, повторный вызов продолжит.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
