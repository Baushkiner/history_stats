#!/usr/bin/env python3
"""Сбор слоя землетрясений и цунами 1600–1960 из NOAA NCEI, EMCA и GEM.

    python3 scripts/harvest_earthquakes.py --fetch    # только скачать в кэш (около 25 минут)
    python3 scripts/harvest_earthquakes.py --check    # сверка, скачивание, разбор, отчёт
    python3 scripts/harvest_earthquakes.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков: `--check`
сверяет перечень файлов записи GEM на Zenodo и архив EMCA с размерами и md5
в коде, забирает ответы NOAA (по странице в минуту — так просит
`robots.txt`), сводит три каталога и показывает, сколько событий взято, сколько
отброшено отбором и как выглядят знакомые землетрясения: Шемаха, Верный,
Андижан, Крым, Ашхабад, Камчатка 1952 года.

Права. NOAA — общественное достояние; EMCA (GFZ) и GEM — CC BY-SA 4.0. Берутся
факты — дата, точка, магнитуда, жертвы — со ссылкой на каталог.

На выходе:

* `geojson/earthquakes.geojson` — записи с точкой (у всех она есть): в
  репозиторий;
* `jsonl/earthquakes.jsonl` — слой целиком (`jsonl/` в `.gitignore`).

Нужны `data/out/boundaries/provinces_1897.geojson`, `state_borders.geojson`
(рамка и названия соседних государств), `state_borders_early.geojson`
(соседи до 1886 года) и `data/out/geojson/settlements.geojson` (подпись места:
ближайший город) — все лежат в репозитории.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl
from histctx.sources.earthquakes import (
    EARTHQUAKES, EMCA_CSV, EMCA_MD5, EMCA_SIZE, EMCA_URL, GEM_CSV, GEM_KEY, GEM_MD5,
    GEM_SIZE, GEM_URL, OUTSIDE, EarthquakesError, NoaaClient, Placement, build,
    cached_file, check_gem_manifest, emca_events, fetch_gem_manifest, fetch_noaa, gem_events,
    read_zip_member,
)

CACHE = ROOT / "data" / "raw" / "earthquakes"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
SETTLEMENTS = ROOT / "data" / "out" / "geojson" / "settlements.geojson"

# Землетрясения, по которым разбор проверяется глазами: год и слово в подписи
# или в месте по NOAA.
# Слова — как NOAA пишет место: Верный — «VERNENSK», Шемаха 1902 года —
# «SEMACHA», Ленинакан 1926 года — «TURKEY; ARMENIA», Хаит 1949-го — просто
# «TAJIKISTAN». Печатается самое сильное событие года с этим словом.
WATCH = ((1667, "SHEMAKHA"), (1887, "VERNENSK"), (1902, "SEMACHA"), (1902, "ANDIZHAN"),
         (1911, "ALMA-ATA"), (1911, "USOY"), (1926, "ARMENIA"), (1927, "CRIMEA"),
         (1948, "ASHKHABAD"), (1949, "TAJIKISTAN"), (1952, "KAMCHATKA"))


def need_boundaries() -> None:
    for path in (BOUNDARIES / "provinces_1897.geojson", BOUNDARIES / "state_borders.geojson"):
        if not path.exists():
            raise EarthquakesError(f"нет {path.relative_to(ROOT)} — соберите границы "
                                   "(docs/HARVEST.md, шаги 5 и 6)")


def download(cache: Path, *, check_manifest: bool) -> tuple:
    """Три каталога: NOAA по API, EMCA и GEM файлами со сверкой."""
    if check_manifest:
        problems = check_gem_manifest(fetch_gem_manifest())
        if problems:
            raise EarthquakesError(f"GEM на Zenodo: файл {GEM_KEY} не тот, что записан в "
                                   "коде: " + "; ".join(problems))
        print(f"GEM: перечень файлов записи на Zenodo сходится с кодом ({GEM_KEY}).")
    emca_raw = cached_file(cache, "EMCA_seismocatv1.0.zip", EMCA_URL, EMCA_SIZE, EMCA_MD5)
    gem_raw = cached_file(cache, GEM_KEY, GEM_URL, GEM_SIZE, GEM_MD5, timeout=1800)
    print("EMCA и GEM: архивы в кэше, размер и md5 сходятся.")
    client = NoaaClient(cache / "noaa")
    quakes, tsunamis, runups = fetch_noaa(client)
    print(f"NOAA: землетрясений {len(quakes)}, цунами {len(tsunamis)}, набегов {len(runups)} "
          f"(новых запросов: {client.requests})")
    return quakes, tsunamis, runups, emca_raw, gem_raw


def collect(cache: Path, *, check_manifest: bool):
    need_boundaries()
    quakes, tsunamis, runups, emca_raw, gem_raw = download(cache, check_manifest=check_manifest)
    emca = emca_events(read_zip_member(emca_raw, EMCA_CSV))
    gem = gem_events(read_zip_member(gem_raw, GEM_CSV))
    place = Placement.load(BOUNDARIES, SETTLEMENTS)
    return build(quakes, tsunamis, runups, emca, gem, place)


def report(result) -> None:
    recs = result.records
    print(f"\nЗаписей в слое: {len(recs)}")
    for key, n in result.counts.items():
        print(f"  {key}: {n}")
    print("  землетрясения слоя по каталогам:")
    for combo, n in sorted(result.by_catalogs.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>5}  {combo}")
    print("  по виду:")
    for what, n in collections.Counter(r.category for r in recs).most_common():
        print(f"    {n:>5}  {what}")
    print("  место:")
    frames = collections.Counter(
        "вне рамки, у границы" if r.confidence == OUTSIDE else
        ("в море у берега" if str(r.extra.get("frame", "")).startswith("в море") else "в рамке")
        for r in recs)
    for what, n in frames.most_common():
        print(f"    {n:>5}  {what}")
    print(f"  с губернией 1897 года: {sum(1 for r in recs if r.region)}")
    print("  точность даты:")
    for what, n in collections.Counter(r.date_precision for r in recs).most_common():
        print(f"    {n:>5}  {what}")
    decades = collections.Counter(r.year_from // 50 * 50 for r in recs)
    print("  по полувекам: " + ", ".join(f"{d}-е — {n}" for d, n in sorted(decades.items())))
    print("\n  образцы:")
    for year, word in WATCH:
        found = [r for r in recs if r.year_from == year and word in (r.place_text or "").upper()]
        if not found:
            print(f"    {year} {word}: не найдено")
            continue
        rec = max(found, key=lambda r: r.extra.get("magnitude") or 0)
        print(f"    {rec.title} [{rec.region or rec.extra.get('frame', '')}]")
        print(f"      {rec.summary[:300]}")


def check(cache: Path) -> int:
    result = collect(cache, check_manifest=True)
    if not result.records:
        print("Ни одно событие не попало в слой: проверьте разбор.", file=sys.stderr)
        return 1
    report(result)
    print("\nКаталоги читаются, разбор работает — можно запускать --build.")
    return 0


def build_layer(cache: Path, out_dir: Path) -> int:
    result = collect(cache, check_manifest=False)
    recs = result.records
    if not recs:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    slug = EARTHQUAKES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=EARTHQUAKES.title, hoist_shared=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{EARTHQUAKES.title}»: {len(recs)} записей, на карте {n}")
    for path in (geo, jsonl):
        print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="только скачать каталоги в кэш")
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить, скачать, разобрать — без записи слоя")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть ответы и архивы")
    args = ap.parse_args()

    if not (args.fetch or args.check or args.build):
        ap.error("укажите --fetch, --check или --build")
    try:
        if args.fetch:
            download(args.cache, check_manifest=True)
            if not (args.check or args.build):
                return 0
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build_layer(args.cache, args.out)
    except EarthquakesError as exc:
        print(f"Землетрясения: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
