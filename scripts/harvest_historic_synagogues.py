#!/usr/bin/env python3
"""Сбор слоя исторических синагог Европы (historicsynagogueseurope.org).

    python3 scripts/harvest_historic_synagogues.py --check            # карта и пять карточек
    python3 scripts/harvest_historic_synagogues.py --fetch            # все карточки в кэш, с продолжением
    python3 scripts/harvest_historic_synagogues.py --build [--partial] # слой из кэша

Собрано с согласия владельца (сообщено владельцем проекта 24.11.2026).
Страница карты `synagogue-map` (0,6 МБ) несёт все точки; карточка здания —
по запросу на каждое, 3 427 запросов, около полутора часов при паузе в
секунду. Всё ложится в `data/raw/historic_synagogues/` (в `.gitignore`)
сжатым gzip, оборванный обход продолжается тем же вызовом.

Сервер не отдаёт промежуточный сертификат: сборщик скачивает его по адресу
из поля AIA (`crt.sectigo.com`, кладёт в кэш) и добавляет к доверенным;
проверка TLS не отключается.

На выходе:

* `geojson/historic_synagogues.geojson` — здания с точкой, в репозиторий;
* `historic_synagogues.json` — без точки, если есть;
* `jsonl/historic_synagogues.jsonl` — слой целиком (в `.gitignore`).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.historic_synagogues import (
    CARD_URL, EXPECTED, HISTORIC_SYNAGOGUES, INTERMEDIATE_URL, MAP_URL, PAUSE, SynagoguesError,
    check_card, parse_card, parse_map, records, ssl_context,
)
from histctx.sources.polite import PoliteClient, cache_read, cache_write

CACHE = ROOT / "data" / "raw" / "historic_synagogues"
OUT = ROOT / "data" / "out"
BOUNDARIES = OUT / "boundaries"


def client(cache: Path, pause: float) -> PoliteClient:
    cert = cache / "SectigoPublicServerAuthenticationCADVR36.crt"
    if not cert.exists():
        der = PoliteClient(pause=0, error=SynagoguesError).fetch(INTERMEDIATE_URL)
        cert.parent.mkdir(parents=True, exist_ok=True)
        cert.write_bytes(der)
    return PoliteClient(pause=pause, error=SynagoguesError,
                        ssl_context=ssl_context(cert.read_bytes()))


def cached(cl, path: Path, url: str, *, refresh: bool = False) -> str:
    text = None if refresh else cache_read(path)
    if text is None:
        if cl is None:
            raise SynagoguesError(f"нет {path} в кэше, а сеть отключена (--offline)")
        raw = cl.fetch(url)
        cache_write(path, raw)
        text = raw.decode("utf-8", errors="replace")
    return text


def card_path(cache: Path, sid: int) -> Path:
    return cache / "cards" / f"{sid // 1000:03d}" / f"{sid}.html.gz"


def load_map(cl, cache: Path, refresh: bool):
    points = parse_map(cached(cl, cache / "synagogue-map.html.gz", MAP_URL, refresh=refresh))
    print(f"Точек на карте: {len(points)} (замер 24.11.2026 — {EXPECTED})", flush=True)
    if not points:
        raise SynagoguesError("на карте нет ни одной точки")
    return points


def check(cache: Path, pause: float, sample: int) -> int:
    cl = client(cache, pause)
    points = load_map(cl, cache, refresh=True)
    step = max(1, len(points) // sample)
    for p in points[::step][:sample]:
        card = parse_card(cached(cl, card_path(cache, p.id), CARD_URL.format(p.id)))
        check_card(card, p.id)
        rec = records([(p, card)])[0]
        print(f"  {p.id}: {rec.title}; {rec.lat}, {rec.lon}")
        print(f"      {rec.period_raw!r} → {rec.year_from}–{rec.year_to} ({rec.date_precision}); "
              f"{rec.summary}")
    print(f"\nЗапросов: {cl.requests}, повторов: {cl.backoffs}. Поля на месте — можно --fetch.")
    return 0


def fetch(cache: Path, pause: float, *, refresh: bool, limit=None):
    cl = client(cache, pause)
    points = load_map(cl, cache, refresh)
    todo = [p for p in points if not card_path(cache, p.id).exists()]
    print(f"Карточек в кэше {len(points) - len(todo)}, докачать {len(todo)}", flush=True)
    for i, p in enumerate(todo[:limit] if limit else todo, 1):
        try:
            check_card(parse_card(cached(cl, card_path(cache, p.id), CARD_URL.format(p.id))), p.id)
        except SynagoguesError as exc:
            print(f"  {exc}", file=sys.stderr, flush=True)
        if i % 100 == 0:
            print(f"  {i}/{len(todo)}; повторов {cl.backoffs}, пауза {cl.pause:g} с", flush=True)
    return points


def build(cache: Path, out_dir: Path, *, partial: bool) -> int:
    points = load_map(None, cache, refresh=False)
    items, missing = [], 0
    for p in points:
        text = cache_read(card_path(cache, p.id))
        if text is None:
            missing += 1
        items.append((p, parse_card(text) if text else None))
    if missing and not partial:
        print(f"Карточек нет в кэше: {missing} — слой не собирается неполным; запустите "
              "--fetch ещё раз или соберите --partial", file=sys.stderr)
        return 1
    if missing:
        print(f"Неполный слой (--partial): без карточки {missing} зданий из {len(points)}")
    recs = records(items)
    marks = Frame.load(BOUNDARIES).mark(recs)
    report(recs, marks)
    slug = HISTORIC_SYNAGOGUES.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=HISTORIC_SYNAGOGUES.title, hoist_shared=True)
    off_map = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{HISTORIC_SYNAGOGUES.title}: без точки",
                           hoist_shared=True)
    write_jsonl(recs, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"\n«{HISTORIC_SYNAGOGUES.title}»: {len(recs)} записей, на карте {n}, "
          f"без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None):
        if path is not None:
            print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def report(recs: list, marks: dict) -> None:
    print(f"Записей: {len(recs)}; с точкой: {sum(1 for r in recs if r.has_point)}; "
          f"с датировкой: {sum(1 for r in recs if r.has_time)}")
    print("  рамка:", dict(marks))
    print("  точность дат:", dict(collections.Counter(r.date_precision for r in recs)))
    print("  ныне:", collections.Counter(r.category for r in recs).most_common(8))
    gub = collections.Counter(r.region for r in recs if r.region)
    print(f"  в губерниях 1897 года: {sum(gub.values())}; чаще всего: {gub.most_common(6)}")
    raw = collections.Counter(r.extra.get("building_date") for r in recs
                              if r.extra.get("building_date") and r.date_precision == "unknown")
    if raw:
        print("  год постройки не разобран:", raw.most_common(10))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="перечитать страницу карты")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    if args.pause < 1.0:
        ap.error("пауза не меньше секунды")
    try:
        if args.check:
            return check(args.cache, args.pause, args.sample)
        if args.fetch:
            fetch(args.cache, args.pause, refresh=args.refresh, limit=args.limit)
        if args.build:
            return build(args.cache, args.out, partial=args.partial)
        return 0
    except SynagoguesError as exc:
        print(f"Historic Synagogues: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; скачанное лежит в кэше, повторный вызов продолжит.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
