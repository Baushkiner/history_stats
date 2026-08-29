#!/usr/bin/env python3
"""Сбор слоя переименований населённых мест из Викиданных.

    python3 scripts/harvest_renamed.py --probe    # одна Россия, один чанк, без записи файлов
    python3 scripts/harvest_renamed.py --build    # собрать слой в data/out
    python3 scripts/harvest_renamed.py --probe --dump ответ.json   # сохранить ответ
    python3 scripts/harvest_renamed.py --from-file ответ.json      # разобрать его без сети

Проверочный первый запуск обязателен, как и у остальных сборщиков: `--probe`
берёт одно государство и первые пятьсот мест, печатает разобранные записи —
старое название, новое, год — и ничего не пишет на диск. Запрос, который не
выполняется или отдаёт пусто, должен быть виден сразу, а не через сорок минут
обхода семнадцати стран.

Почему сбор отдельный, а не запрос в `queries/*.rq`: годы переименований
лежат в квалификаторах времени, а вторая ступень движка умеет только `wdt:` —
подробное объяснение в `src/histctx/sources/renamed.py`.

Права: Викиданные — CC0, берётся всё, включая сами названия.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Optional

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_xlsx
from histctx.registry import BY_SLUG
from histctx.sources.renamed import (
    PROBE_OBJECTS, collect, dedupe, ids_query, names_query, rows_to_records,
)
from histctx.sources.wikidata import COUNTRIES, SparqlClient, SparqlError

SLUG = "renamed_places"


def show(records: list, limit: int = 8) -> None:
    print(f"\n  разобрано записей: {len(records)}")
    if not records:
        return
    dated = sum(1 for r in records if not r.date_approx)
    with_region = sum(1 for r in records if r.region)
    years = [r.year_to for r in records]
    print(f"  год начала прежнего названия известен у {dated} из {len(records)}")
    print(f"  с губернией или областью: {with_region}")
    print(f"  годы переименований: {min(years)}–{max(years)}")

    # 1900 год — это девятнадцатый век, а не двадцатый: век считается от
    # года без единицы, иначе круглые годы уезжают на сто лет вперёд.
    by_century = collections.Counter(f"{(r.year_to - 1) // 100 + 1} в." for r in records)
    print("  по векам:")
    for century, count in sorted(by_century.items()):
        print(f"    {count:>5}  {century}")

    print("\n  примеры:")
    for rec in records[:limit]:
        print(f"    {rec.period_raw:>12s}  {rec.lat:7.3f},{rec.lon:8.3f}  {rec.title}")
        print(f"                  {rec.summary}")


def replay(spec, path: Path) -> int:
    """Разбор сохранённого ответа — без сети.

    Нужен не для удобства: сервис ограничивает частоту обращений, а править
    разбор приходится по многу раз. Ответ пробы сохраняется ключом `--dump`
    и дальше крутится с диска, пока разбор не станет верным.
    """
    rows = json.loads(path.read_text(encoding="utf-8"))
    print(f"Разбор сохранённого ответа {path}: строк {len(rows)}")
    records = dedupe(rows_to_records(rows, spec))
    show(records)
    return 0 if records else 1


def probe(client: SparqlClient, spec, limit: int, dump: Optional[Path]) -> int:
    """Живая проба: одно государство, один чанк, файлы не пишутся."""
    country, name = COUNTRIES[0]
    print(f"Проба слоя «{spec.title}» ({spec.slug}), государство: {name}")
    rows = client.query(ids_query(country))
    qids = sorted({r["item"]["value"].rsplit("/", 1)[-1] for r in rows})
    print(f"  мест с прежним названием: {len(qids)}")
    if not qids:
        print("  Ничего не нашлось: проверьте класс и свойства названий.", file=sys.stderr)
        return 1

    chunk = qids[:limit]
    print(f"  беру первые {len(chunk)} и спрашиваю их названия целиком")
    name_rows = client.query(names_query(chunk))
    print(f"  строк в ответе: {len(name_rows)}")
    if dump:
        dump.parent.mkdir(parents=True, exist_ok=True)
        dump.write_text(json.dumps(name_rows, ensure_ascii=False), encoding="utf-8")
        print(f"  ответ сохранён в {dump}")

    records = dedupe(rows_to_records(name_rows, spec))
    show(records)
    if not records:
        print("  Ни одной записи: пришли названия без дат или без преемника.",
              file=sys.stderr)
        return 1
    print("\nЗапрос работает — можно запускать --build.")
    return 0


def build(client: SparqlClient, spec, out_dir: Path) -> int:
    print(f"Сбор слоя «{spec.title}» ({spec.slug})…")
    records = collect(client, spec, progress=print)
    if not records:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    show(records, limit=5)

    out_dir.mkdir(parents=True, exist_ok=True)
    mapped = write_geojson(records, out_dir / "geojson" / f"{spec.slug}.geojson",
                           layer_title=spec.title)
    write_jsonl(records, out_dir / "jsonl" / f"{spec.slug}.jsonl")
    write_xlsx(records, out_dir / "xlsx" / f"{spec.slug}.xlsx", sheet_name=spec.title)
    print(f"\nСобрано {len(records)} записей, на карту пойдут {mapped}.")
    print(f"  записано в {out_dir}/{{geojson,jsonl,xlsx}}/{spec.slug}.*")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true",
                    help="одно государство и один чанк, без записи файлов")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--limit", type=int, default=PROBE_OBJECTS,
                    help="сколько мест берёт проба")
    ap.add_argument("--dump", type=Path, default=None,
                    help="сохранить сырой ответ пробы в файл (образец для тестов)")
    ap.add_argument("--from-file", type=Path, default=None,
                    help="разобрать сохранённый ответ вместо запроса к сервису")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "cache")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    if not args.probe and not args.build and not args.from_file:
        ap.error("укажите --probe, --build или --from-file")

    spec = BY_SLUG.get(SLUG)
    if spec is None:
        print(f"Слой {SLUG} не описан в registry.py.", file=sys.stderr)
        return 1

    if args.from_file:
        return replay(spec, args.from_file)

    # Повторов меньше, чем у клиента по умолчанию: 504 приходит не от
    # перегрузки, а от лимита времени на запрос, и пятью попытками не лечится.
    # Адрес, с которого мы приходим, у всех сборщиков общий — долбить сервис
    # заведомо бесполезными повторами нельзя.
    client = SparqlClient(cache_dir=None if args.no_cache else args.cache,
                          max_retries=2)
    try:
        if args.probe:
            code = probe(client, spec, args.limit, args.dump)
            if code or not args.build:
                return code
        return build(client, spec, args.out)
    except SparqlError as exc:
        print(f"Викиданные: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
