#!/usr/bin/env python3
"""Сбор слоя «Урожайность и хлебные цены по губерниям» из RISTAT / ERRHS.

    python3 scripts/harvest_errhs.py --check          # что реально в таблице
    python3 scripts/harvest_errhs.py --build          # собрать слой

Первым запуском обязательно `--check`: он выгружает одну таблицу и печатает
её настоящие колонки, показатели и единицы. Каталог `ristat.org` собирает
архив под запрос, и если форма или состав колонок изменятся, лучше узнать об
этом на одной таблице, чем после десяти.

Права: выгрузка идёт по CC BY-NC-SA 4.0 — это условие принимается на самом
сайте перед скачиванием. Ссылка на авторов архива обязательна и проставлена
в каждой записи:

    Кесслер Г., Маркевич А. Электронный архив российской исторической
    статистики, XVIII–XXI вв. https://ristat.org/, Версия I (2020).

Скачанные архивы кладутся в data/raw/ristat: ссылка каталога одноразовая, а
пересобирать слой приходится чаще, чем меняются данные.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.io_formats import write_jsonl, write_records_json  # noqa: E402
from histctx.sources.errhs import (  # noqa: E402
    CONFIDENCE_UNMATCHED, HARVEST_PRICES, TOPICS, ErrhsError, RistatCatalog,
    read_figures, region_records,
)

# Тема и срез для пробы: таблица небольшая, но в ней есть и пары
# «посеяно / снято», и четверти — то есть всё, на чём держится разбор.
CHECK_TOPIC, CHECK_BENCHMARK = "4.02", 1795


def check(catalog: RistatCatalog, topic: str, benchmark: int) -> int:
    print(f"Проба: тема {topic} ({TOPICS[topic][0]}), опорный срез {benchmark}\n")
    header, rows = catalog.table(topic, benchmark)
    print(f"  строк в таблице: {len(rows)}")
    print(f"  колонки: {header}\n")
    if not rows:
        print("  Таблица пуста — проверьте, существует ли такое сочетание темы и среза.")
        return 1

    print("  первая строка:")
    for key in header:
        value = rows[0].get(key)
        if value not in (None, "", "."):
            print(f"    {key:20} {value}")

    figures = read_figures(rows, topic=topic, benchmark=benchmark)
    print(f"\n  разобрано величин: {len(figures)} из {len(rows)} строк")
    print(f"  территорий: {len(({f.region for f in figures}))}")
    print(f"  единицы: {dict(Counter(f.unit for f in figures).most_common(6))}")
    print(f"  ролей «посев»: {sum(1 for f in figures if f.role == 'посев')}, "
          f"«урожай»: {sum(1 for f in figures if f.role == 'урожай')}")

    records = region_records(figures)
    print(f"  записей слоя: {len(records)}")
    for rec in records[:5]:
        print(f"    {rec.year_from}  {rec.category:16} {rec.title}")
    if not records:
        print("  Ни одной записи: проверьте колонки в выводе выше.")
        return 1
    print("\nКолонки на месте, разбор работает — можно запускать сбор.")
    return 0


def build(catalog: RistatCatalog, out_dir: Path, *, only: list[str] | None,
          benchmarks: list[int] | None) -> int:
    figures, rows_read, tables = [], 0, 0
    for topic, (title, years) in TOPICS.items():
        if only and topic not in only:
            continue
        for benchmark in years:
            if benchmarks and benchmark not in benchmarks:
                continue
            try:
                _, rows = catalog.table(topic, benchmark)
            except ErrhsError as exc:
                # Одна недоступная тема не повод бросать остальные, но и
                # промолчать о ней нельзя: слой уедет неполным.
                print(f"  ОШИБКА {topic}/{benchmark}: {exc}", file=sys.stderr)
                continue
            tables += 1
            rows_read += len(rows)
            part = read_figures(rows, topic=topic, benchmark=benchmark)
            figures += part
            print(f"  {topic} {benchmark}: строк {len(rows)}, величин {len(part)}  ({title})")

    if not figures:
        print("Ничего не собрано.", file=sys.stderr)
        return 1

    records = region_records(figures)
    skipped = rows_read - len(figures)
    print(f"\nТаблиц: {tables}. Строк прочитано: {rows_read}; "
          f"без территории или без числа: {skipped} — в слой не идут.")
    print(f"Величин: {len(figures)}; записей после сведения пар «посеяно / снято»: "
          f"{len(records)}.")

    write_records_json(records, out_dir / f"{HARVEST_PRICES.slug}.json",
                       title=HARVEST_PRICES.title)
    write_jsonl(records, out_dir / "jsonl" / f"{HARVEST_PRICES.slug}.jsonl")
    print(f"  {HARVEST_PRICES.slug}.json: {len(records)} записей по губерниям")

    for category, count in Counter(r.category for r in records).most_common():
        print(f"    {category:18} {count}")
    with_ratio = sum(1 for r in records if "сам" in r.extra)
    print(f"  из них с посчитанным сам-N: {with_ratio}")

    unmatched = {r.region for r in records if r.confidence == CONFIDENCE_UNMATCHED}
    if unmatched:
        # Правило репозитория: несопоставленное помечается и остаётся в данных.
        print(f"  территорий, которых подбор по названию может не найти "
              f"({CONFIDENCE_UNMATCHED}): {len(unmatched)} — " + ", ".join(sorted(unmatched)))
    years = sorted({r.year_from for r in records if r.year_from})
    print(f"  годы: {years[0]}–{years[-1]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="выгрузить одну таблицу и напечатать её настоящие колонки")
    ap.add_argument("--build", action="store_true", help="собрать слой")
    ap.add_argument("--topic", action="append", choices=sorted(TOPICS),
                    help="ограничить темы (можно повторять)")
    ap.add_argument("--benchmark", action="append", type=int,
                    help="ограничить опорные срезы (можно повторять)")
    ap.add_argument("--pause", type=float, default=1.0, help="пауза между запросами, секунды")
    ap.add_argument("--cache", default=str(ROOT / "data" / "raw" / "ristat"),
                    help="куда класть скачанные архивы; --cache '' отключает кэш")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check или --build")

    # Путь кэша принимается строкой, а не Path: argparse превратил бы пустую
    # строку в Path('.') и вместо «без кэша» получилось бы «в текущий каталог».
    catalog = RistatCatalog(pause_sec=args.pause,
                            cache_dir=Path(args.cache) if args.cache else None)
    try:
        if args.check:
            topic = args.topic[0] if args.topic else CHECK_TOPIC
            benchmark = args.benchmark[0] if args.benchmark else CHECK_BENCHMARK
            return check(catalog, topic, benchmark)
        return build(catalog, args.out, only=args.topic, benchmarks=args.benchmark)
    except ErrhsError as exc:
        print(f"RISTAT: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
