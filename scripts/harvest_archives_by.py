#!/usr/bin/env python3
"""Сбор слоя «Метрические книги в архивах Беларуси» с портала archives.gov.by.

    python3 scripts/harvest_archives_by.py --check   # robots.txt, разделы, одна страница, Excel
    python3 scripts/harvest_archives_by.py --build   # всё в кэш и слой в data/out

Портал — WordPress, и указатель отдаётся через WP REST: дочерние страницы
раздела «православных и униатских церквей» (244873) и «католических
костёлов» (640747) — по запросу на раздел, с HTML-таблицей в
`content.rendered`. Плюс два Excel «Единого межфондового указателя» НИАБ в
Гродно. Почему так и что берётся — шапка `src/histctx/sources/archives_by.py`.

Проверочный первый запуск обязателен. `--check` читает `robots.txt` (путь
`/wp-json/` должен быть открыт), забирает список дочерних страниц обоих
разделов и сверяет их число с замером 04.11.2026 (44 и 38), разбирает
страницу Бобруйского уезда (в таблице должны быть колонки «Приход», «Годы»,
«Фонд/Опись») и оба Excel. Расхождение — остановка с объяснением. Файлов
`--check` не пишет.

`--build` складывает ответы в `data/raw/archives_by/` (в `.gitignore`;
`--refresh` перечитывает) и пишет:

* `data/out/metric_books_by.json` — все записи (территориальные: уезд и
  губерния вместо координаты), `write_records_json`;
* `data/out/jsonl/metric_books_by.jsonl` — то же построчно (в `.gitignore`).

Права. Условий использования портал не публикует — права не выяснены.
Берутся приход, годы и шифр со ссылкой на страницу указателя.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_jsonl, write_records_json
from histctx.sources.archives_by import (
    BASE_URL, EXCEL, EXPECTED_PAGES, INDEX_ID, METRIC_BOOKS_BY, REST_RU, SECTIONS,
    ArchivesByError, Client, aggregate, children_url, entry_to_record, excel_records, excel_rows,
    page_rows, parse_page_title, parse_tables,
)
from histctx.sources.wikisource_arkhiv import UezdResolver

CACHE = ROOT / "data" / "raw" / "archives_by"
OUT = ROOT / "data" / "out"
DISTRICTS = ROOT / "data" / "out" / "boundaries" / "districts_1897.geojson"
SAMPLE_PAGE = 831787        # Бобруйский уезд, православные: 316 строк на 04.11.2026
SAMPLE_MIN_ROWS = 250


class Source:
    """Ответы портала: из кэша или из сети (`--refresh` — всегда из сети)."""

    def __init__(self, cache: Path, *, refresh: bool, offline: bool = False,
                 store: bool = True, client: Client | None = None) -> None:
        self.cache, self.refresh, self.store = cache, refresh, store
        self.client = None if offline else (client or Client())

    def get(self, name: str, url: str) -> bytes:
        path = self.cache / name
        if path.exists() and not self.refresh:
            return path.read_bytes()
        if self.client is None:
            raise ArchivesByError(f"нет {path} в кэше: запустите без --offline")
        data = self.client.get(url)
        if not self.store:
            return data
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return data

    def json(self, name: str, url: str):
        try:
            return json.loads(self.get(name, url).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ArchivesByError(f"{url}: ответ не JSON ({exc})") from exc


def check_robots(client: Client) -> None:
    robots = client.robots()
    for url in (REST_RU, f"{BASE_URL}/en/wp-json/wp/v2/pages", EXCEL["orthodox"]):
        if not robots.can_fetch("*", url):
            raise ArchivesByError(f"robots.txt закрывает {url}: сбор не идёт")
    print(f"robots.txt: WP REST и файлы открыты, пауза {client.pause:g} с")


def linked_ids(section_page: dict, children: list) -> set:
    """Номера дочерних страниц, на которые ссылается страница раздела."""
    content = (section_page.get("content") or {}).get("rendered") or ""
    ids = {int(x) for x in re.findall(r"page_id=(\d+)", content)}
    links = set(re.findall(r'href="(https?://[^"]+)"', content))
    for page in children:
        if page.get("link") in links:
            ids.add(page["id"])
    return ids


def load_sections(src: Source, *, check_counts: bool = True) -> dict:
    """{раздел: (страница раздела, дочерние русские, дочерние английские)}."""
    out = {}
    for parent, section in SECTIONS.items():
        page = src.json(f"section_{parent}.json", f"{REST_RU}/{parent}")
        ru = src.json(f"children_{parent}_ru.json", children_url(parent))
        en = src.json(f"children_{parent}_en.json", children_url(parent, english=True))
        if not isinstance(ru, list) or not isinstance(en, list):
            raise ArchivesByError(f"раздел {parent}: WP REST вернул не список страниц")
        print(f"Раздел {parent} ({section}): страниц по-русски {len(ru)} (04.11.2026 — "
              f"{EXPECTED_PAGES[section]}), по-английски {len(en)}; со ссылкой с раздела "
              f"{len(linked_ids(page, ru))}")
        if check_counts and len(ru) < EXPECTED_PAGES[section]:
            raise ArchivesByError(
                f"в разделе {parent} страниц {len(ru)}, а не {EXPECTED_PAGES[section]}: "
                "указатель перекроили — посмотрите, что пропало, и поправьте EXPECTED_PAGES")
        out[section] = (page, ru, en)
    return out


def english_only(ru: list, en: list, section: str) -> list:
    """Английские страницы уездов, которых нет по-русски.

    У переводов те же номера страниц, что у русских; у трёх уездов номер
    свой, и они сверяются по уезду справочника 1897 года.
    """
    resolver = UezdResolver.load(DISTRICTS)
    ids = {p["id"] for p in ru}

    def district(page: dict, english: bool):
        info = parse_page_title(page["id"], page["title"]["rendered"], section, english=english)
        place = resolver.match_in(info.uezd, info.province)
        return place.district or info.uezd, place.province or info.province

    have = {district(p, False) for p in ru}
    return [p for p in en if p["id"] not in ids and district(p, True) not in have]


def check(cache: Path) -> int:
    client = Client()
    check_robots(client)
    sections = load_sections(Source(cache, refresh=True, store=False, client=client))
    _, ru, _ = sections["orthodox"]
    sample = next((p for p in ru if p["id"] == SAMPLE_PAGE), None)
    if sample is None:
        raise ArchivesByError(f"среди православных страниц нет {SAMPLE_PAGE} (Бобруйский уезд)")
    tables = parse_tables(sample["content"]["rendered"])
    rows = page_rows(sample["content"]["rendered"])
    print(f"Страница {SAMPLE_PAGE}: таблиц {len(tables)}, колонки "
          f"{[t[1] for t in tables]}, строк {len(rows)}")
    if len(rows) < SAMPLE_MIN_ROWS:
        raise ArchivesByError(f"в указателе Бобруйского уезда {len(rows)} строк, ожидалось не "
                              f"меньше {SAMPLE_MIN_ROWS}: разметку таблиц поменяли")
    info = parse_page_title(sample["id"], sample["title"]["rendered"], "orthodox")
    resolver = UezdResolver.load(DISTRICTS)
    for entry in aggregate(info, rows)[:3]:
        rec = entry_to_record(entry, resolver)
        print(f"  {rec.title}\n      {rec.region} / {rec.district}; {rec.period_raw}; "
              f"{rec.extra['holdings'][:90]}")
    for url in EXCEL.values():
        data = client.get(url)
        xrows = excel_rows(data)
        print(f"Excel {url.rsplit('/', 1)[-1]}: строк {len(xrows)}; первая — {xrows[0].name}, "
              f"{xrows[0].location[:60]}")
        if len(xrows) < 200:
            raise ArchivesByError(f"{url}: строк {len(xrows)} — шапку или столбцы поменяли")
    print("\nРазделы, таблицы и Excel на месте — можно запускать --build.")
    return 0


def build(cache: Path, out_dir: Path, *, refresh: bool, offline: bool) -> int:
    src = Source(cache, refresh=refresh, offline=offline)
    if src.client is not None:
        check_robots(src.client)
    src.json(f"index_{INDEX_ID}.json", f"{REST_RU}/{INDEX_ID}")
    sections = load_sections(src)
    resolver = UezdResolver.load(DISTRICTS)
    records = []
    pages_used = collections.Counter()
    for section, (section_page, ru, en) in sections.items():
        linked = linked_ids(section_page, ru)
        extra_en = english_only(ru, en, section)
        for page, english in [(p, False) for p in ru] + [(p, True) for p in extra_en]:
            info = parse_page_title(page["id"], page["title"]["rendered"], section,
                                    english=english)
            rows = page_rows(page["content"]["rendered"])
            if not rows:
                print(f"  страница {page['id']} «{info.title[:70]}»: строк нет")
                continue
            pages_used[(section, english)] += 1
            for entry in aggregate(info, rows, linked=english or page["id"] in linked):
                records.append(entry_to_record(entry, resolver))
        data = src.get(EXCEL[section].rsplit("/", 1)[-1], EXCEL[section])
        xrecs = excel_records(excel_rows(data), section, resolver)
        print(f"Excel ({section}): записей {len(xrecs)}")
        records.extend(xrecs)
    print("Страниц указателя:", dict(pages_used))
    report(records)
    slug = METRIC_BOOKS_BY.slug
    n = write_records_json(records, out_dir / f"{slug}.json", title=METRIC_BOOKS_BY.title)
    write_jsonl(records, out_dir / "jsonl" / f"{slug}.jsonl")
    print(f"\nСобрано {n} записей: {slug}.json и jsonl/{slug}.jsonl.")
    return 0


def report(records: list) -> None:
    dated = [r for r in records if r.has_time]
    print(f"\nЗаписей: {len(records)}; с датировкой: {len(dated)}; с губернией 1897 года: "
          f"{sum(1 for r in records if r.region)}; с уездом 1897 года: "
          f"{sum(1 for r in records if r.extra.get('district_match'))}")
    if dated:
        print(f"  годы: {min(r.year_from for r in dated)}–{max(r.year_to for r in dated)}")
    print("  достоверность:",
          dict(collections.Counter(r.confidence for r in records).most_common()))
    print("  по указателям:",
          dict(collections.Counter(r.extra.get("index") for r in records).most_common()))
    print("  по губерниям:", dict(collections.Counter(r.region for r in records).most_common()))
    uids = collections.Counter(r.uid for r in records)
    dupes = [u for u, n in uids.items() if n > 1]
    if dupes:
        print(f"  совпадают uid у {len(dupes)} записей: {dupes[:5]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="robots.txt, разделы, страница-образец и Excel — без записи файлов")
    ap.add_argument("--build", action="store_true", help="собрать слой в data/out")
    ap.add_argument("--refresh", action="store_true", help="перечитать ответы портала")
    ap.add_argument("--offline", action="store_true", help="собирать только из кэша")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if not (args.check or args.build):
        ap.error("укажите --check или --build")
    try:
        if args.check:
            return check(args.cache)
        return build(args.cache, args.out, refresh=args.refresh, offline=args.offline)
    except ArchivesByError as exc:
        print(f"Архивы Беларуси: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
