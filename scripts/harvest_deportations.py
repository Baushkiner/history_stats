#!/usr/bin/env python3
"""Сбор спецпоселенцев 1946 и 1951 годов по районам вселения и переписи 1939 года
по районам из пакета Miho, Jarotschkin, Zhuravskaya (Zenodo, запись 7955244).

    python3 scripts/harvest_deportations.py --check    # перечень, оглавление, файлы, разбор
    python3 scripts/harvest_deportations.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) берёт перечень файлов записи с `/api/records/7955244/files`
(этот путь robots.txt Zenodo разрешает) и сверяет размер и md5 архива с
записанными в `sources/deportations.py`; читает по Range оглавление архива
на 6,5 ГБ (один запрос к хвосту) и сверяет с кодом размеры и CRC32 шести
нужных файлов и наличие ReadMe и исходных таблиц; забирает эти файлы (2,5 МБ
сжатых данных, шесть запросов) в `data/raw/deportations/`; печатает, откуда авторы
взяли перепись (`sources.docx`), первые строки и суммы таблиц, сводит итоги
областей переписи с суммами районов, сверяет суммы спецпоселенцев с таблицей
областей авторов и показывает разбор. Расхождение с кодом — остановка, а не
подгонка.

Права. CC BY 4.0 (карточка Zenodo, DataCite): числа, названия и координаты
выгружаются со ссылкой на запись в каждой записи. Перепись 1939 года авторы
собрали с «Демоскопа Weekly» — условия сайта не выяснены, числа берутся как
факты.

На выходе (`--build`):

* `geojson/special_settlements.geojson` — районы вселения с точкой (районный
  центр, `confidence = district_centroid`), 1951 и 1946 годы;
* `special_settlements.json` — районы 1946 года без координаты (`scope =
  region` по области, `confidence = no_coords`);
* `geojson/census_1939_raion.geojson` — единицы переписи 1939 года, надёжно
  сведённые с районами спецпоселений (точка — центр того района);
* `census_1939_raion.json` — остальные единицы переписи, территориальные;
* `jsonl/special_settlements.jsonl`, `jsonl/census_1939_raion.jsonl` — слои
  целиком, в репозиторий не идут.

Губерния 1897 года по точке (`extra.province_1897`) — по полигонам RISTAT
(`data/out/boundaries/provinces_1897.geojson`, лежит в репозитории); без них
записи собираются, но без губернии.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.sources.deportations import (
    ARCHIVE_ENTRIES, ARCHIVE_KEY, CENSUS_1939, MEMBERS, PRESENT, SPECIAL_SETTLEMENTS,
    DeportationsError, cached_member, census_points, census_records, census_units,
    check_columns, check_listing, check_manifest, docx_text, fetch_manifest, is_unit,
    link_sets, listing, oblast_check, oblast_totals, open_archive, read_dta, records_1946,
    records_1951, thousands, unknown_columns_1946, unknown_columns_1951,
    unknown_nationalities,
)
from histctx.sources.ghcn import GhcnError, Provinces

CACHE = ROOT / "data" / "raw" / "deportations"
PROVINCES_1897 = ROOT / "data" / "out" / "boundaries" / "provinces_1897.geojson"

# Районы, по которым видно, ради чего слой собран.
WATCH_1951 = ("г. Караганда", "Карагандинский район", "Бескарагайский район",
              "Акмолинский район", "г. Воркута", "Чебаркульский район")


def load_provinces(path: Path):
    if not path.exists():
        print(f"  {path} нет — записи останутся без губернии 1897 года. Соберите границы: "
              "python3 scripts/harvest_admin_gis.py --build", file=sys.stderr)
        return None
    try:
        return Provinces.load(path)
    except GhcnError as exc:
        print(f"  губернии 1897 года не читаются ({exc}) — записи без губернии",
              file=sys.stderr)
        return None


# --- скачивание ------------------------------------------------------------

def fetch_tables(cache: Path, archive=None) -> dict:
    """Шесть файлов пакета: из кэша, а нет их — из архива на Zenodo по Range."""
    raw = {}
    for key in MEMBERS:
        path = cache / MEMBERS[key].name
        if archive is None and not (path.exists() and path.stat().st_size == MEMBERS[key].size):
            archive = open_archive()
        raw[key] = cached_member(cache, key, archive=archive)
    tables = {
        "settlers_1951": read_dta(raw["settlers_1951"]),
        "settlers_1946": read_dta(raw["settlers_1946"]),
        "census_1939": read_dta(raw["census_1939"]),
        "crosswalk": read_dta(raw["crosswalk"], labels=True),
        "oblast_compare": read_dta(raw["oblast_compare"]),
    }
    for key, rows in tables.items():
        check_columns(rows, key)
    tables["sources_note"] = docx_text(raw["sources_note"])
    return tables


def collect(tables: dict, provinces) -> dict:
    rec_1951 = records_1951(tables["settlers_1951"], provinces)
    rec_1946 = records_1946(tables["settlers_1946"], provinces)
    links = link_sets(rec_1951, rec_1946)
    points, stats = census_points(tables["crosswalk"], tables["settlers_1951"],
                                  tables["census_1939"])
    rec_1939 = census_records(tables["census_1939"], points, provinces)
    return {"1951": rec_1951, "1946": rec_1946, "1939": rec_1939, "point_stats": stats,
            "links": links}


# --- проверка --------------------------------------------------------------

def _show_row(row: dict, columns: tuple) -> str:
    return ", ".join(f"{c}={row.get(c)!r}" for c in columns)


def report_tables(tables: dict) -> None:
    s51, s46, c39 = tables["settlers_1951"], tables["settlers_1946"], tables["census_1939"]
    print("\nОткуда перепись, по самому пакету (sources.docx):")
    for line in tables["sources_note"].splitlines():
        print(f"  «{line}»")

    total = sum(int(r.get("totaldeportsdistrict") or 0) for r in s51)
    print(f"\ndeportationsall.dta: {len(s51)} районов, колонок {len(s51[0])}, "
          f"спецпоселенцев всего {thousands(total)}")
    for row in s51[:2]:
        print("  " + _show_row(row, ("raion_id", "raion_russ", "oblast_russ", "countrydeport",
                                     "latfinal", "lonfinal", "totaldeportsdistrict")))
    by_country = collections.Counter(r.get("countrydeport") for r in s51)
    print(f"  по графе страны: {dict(by_country)}")
    print(f"  без точки: {sum(1 for r in s51 if r.get('latfinal') is None)}")
    unknown = unknown_columns_1951(s51[0])
    if unknown:
        print(f"  колонки без подписи (пойдут под своим именем): {unknown}")

    total = sum(int(v or 0) for r in s46 for c, v in r.items() if c.endswith("sum"))
    print(f"\ndeports1946_union.dta: {len(s46)} строк, колонок {len(s46[0])}, "
          f"спецпоселенцев всего {thousands(total)}")
    for row in s46[:2]:
        print("  " + _show_row(row, ("id_distr", "country", "oblast", "raion", "latitude",
                                     "longitude", "germansum", "chechensum")))
    print(f"  с точкой: {sum(1 for r in s46 if r.get('latitude') is not None)}; номеров "
          f"района: {len({r.get('id_distr') for r in s46 if r.get('id_distr') is not None})}")
    unknown = unknown_columns_1946(s46[0])
    if unknown:
        print(f"  колонки без подписи: {unknown}")

    groups = census_units(c39)
    units = [unit for unit, _ in groups]
    oblasts = len({r.get("oblast") for r in c39})
    parts = sum(len(p) for _, p in groups)
    print(f"\n1939_census_all.dta: {len(c39)} строк, областей {oblasts}, "
          f"единиц итогов {len(units)}, строк городов и сёл внутри единиц {parts}")
    for row in c39[:2]:
        print("  " + _show_row(row, ("ID", "oblast", "raion", "subraion", "total", "Russians",
                                     "Ukrainians", "Jews")))
    kinds = collections.Counter(r.get("subraion") if is_unit(r) else "без пометки «весь…»"
                                for r in units)
    print(f"  единицы: {dict(kinds)}")
    totals = oblast_totals(c39)
    exact = [t for t in totals if t["total"] is not None and t["total"] == t["units"]]
    short = [t for t in totals if t["total"] is not None and t["total"] != t["units"]]
    print(f"  итог области = сумме её единиц: в {len(exact)} областях из "
          f"{sum(1 for t in totals if t['total'] is not None)}")
    for t in sorted(short, key=lambda t: t["units"] - t["total"])[:6]:
        print(f"    {t['oblast']}: итог {thousands(t['total'])}, единиц {thousands(t['units'])} "
              f"(−{thousands(t['total'] - t['units'])})" if t['units'] < t['total'] else
              f"    {t['oblast']}: итог {thousands(t['total'])}, единиц {thousands(t['units'])}")
    missing = [t["oblast"] for t in totals if t["total"] is None]
    if missing:
        print(f"  области без строки итога: {missing}")
    unknown = unknown_nationalities(c39[0])
    if unknown:
        print(f"  национальности без подписи: {unknown}")


def report_check(tables: dict) -> None:
    chk = oblast_check(tables["settlers_1951"], tables["settlers_1946"],
                       tables["oblast_compare"])
    print("\nСверка с таблицей областей авторов (deports_oblast_compare.dta):")
    print(f"  1951 год: сходится до человека в {chk['exact_1951']} областях из "
          f"{len(chk['rows'])} (с переносом района 307 в Тюменскую область, как у авторов)")
    print(f"  1946 год: процедура авторов воспроизводит таблицу в {chk['exact_1946']} областях "
          f"из {chk['with_1946']} — вместе с её ошибками: удаление всех копий строк с одним "
          "номером района или одной точкой и двойной счёт карачаевцев")
    print(f"  в таблице нет 1946 года для: {', '.join(chk['no_1946_in_table'])}")
    differ = sorted(chk["ours_differ_1946"],
                    key=lambda r: -abs(sum(r["ours_1946"]) - sum(r["table_1946"])))
    print(f"  записи слоя (без потерь) против таблицы 1946 года: расходятся {len(differ)} "
          "областей; крупнейшие:")
    for row in differ[:8]:
        print(f"    {row['oblast_engl']}: «протестанты» и «мусульмане» в записях "
              f"{row['ours_1946']}, в таблице {row['table_1946']}")
    if chk["not_in_table_1946"]:
        print(f"  области 1946 года, которых нет в таблице: {chk['not_in_table_1946']}")


def report_records(got: dict) -> None:
    for year in ("1951", "1946"):
        recs = got[year]
        with_point = sum(1 for r in recs if r.has_point)
        print(f"\nСпецпоселенцы, набор {year}: {len(recs)} записей, с точкой {with_point}, "
              f"без точки {len(recs) - with_point}")
        print(f"  годы: {dict(collections.Counter(r.year_from for r in recs))}")
        print(f"  пометки: {dict(collections.Counter(r.confidence for r in recs))}")
        republics = collections.Counter(r.place_text.rsplit(", ", 1)[-1] for r in recs)
        print(f"  республики: {dict(republics)}")
        total = sum(r.extra.get("total", 0) for r in recs)
        print(f"  спецпоселенцев в записях: {thousands(total)}")
        labels = collections.Counter()
        for r in recs:
            labels.update(r.extra.get("contingents", {}))
        print("  категории: " + ", ".join(f"{k} {thousands(v)}"
                                          for k, v in labels.most_common(12)))
        same = sum(1 for r in recs if r.extra.get("same_raion"))
        if same:
            print(f"  записей со ссылкой на одноимённую строку (не сложены): {same}")
        fixed = sum(1 for r in recs if r.extra.get("oblast_fixed"))
        if fixed:
            print(f"  область исправлена по названию и координате: {fixed}")
    print(f"\nЛист «Алтай 1946» и таблица 1946 года: ссылок между записями одного района "
          f"{got['links']} (числа разные — разные документы, не сложены)")
    for rec in got["1951"]:
        if rec.district in WATCH_1951:
            print(f"    {rec.title}: {rec.summary}")

    recs = got["1939"]
    with_point = sum(1 for r in recs if r.has_point)
    print(f"\nПерепись 1939 года: {len(recs)} единиц, с точкой {with_point}, "
          f"территориальных {len(recs) - with_point}")
    print(f"  сведение с районами вселения: {got['point_stats']}")
    print(f"  виды: {dict(collections.Counter(r.extra['unit']['kind'] for r in recs))}")
    for rec in recs[:2] + [r for r in recs if r.has_point][:2]:
        print(f"    {rec.title}: {rec.summary}")


def check(cache: Path, provinces_path: Path) -> int:
    problems = check_manifest(fetch_manifest())
    if problems:
        print(f"Zenodo 7955244: {ARCHIVE_KEY} не тот, что записан в коде:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Zenodo 7955244: перечень файлов записи сходится с кодом ({ARCHIVE_KEY}).")
    archive = open_archive()
    entries = listing(archive)
    problems = check_listing(entries, total=len(archive.infolist()))
    if problems:
        print("Оглавление архива не то, что записано в коде:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Оглавление архива: {len(archive.infolist())} записей (ожидалось {ARCHIVE_ENTRIES}), "
          f"нужные файлы на месте, размеры и CRC32 сходятся:")
    by_path = {e["path"]: e for e in entries}
    for member in MEMBERS.values():
        entry = by_path[member.path]
        print(f"  {member.path}: {thousands(entry['size'])} байт "
              f"(сжато {thousands(entry['compressed'])})")
    for path in PRESENT:
        print(f"  есть: {path} ({thousands(by_path[path]['size'])} байт)")

    tables = fetch_tables(cache, archive)
    print(f"Файлы в кэше: {cache.relative_to(ROOT) if cache.is_relative_to(ROOT) else cache} "
          f"(запросов к архиву: {archive.fp.requests if hasattr(archive.fp, 'requests') else '?'})")
    report_tables(tables)
    report_check(tables)
    got = collect(tables, load_provinces(provinces_path))
    report_records(got)
    if not got["1951"] or not got["1939"]:
        print("Ничего не разобралось: проверьте разбор.", file=sys.stderr)
        return 1
    print("\nНабор читается, разбор работает — можно запускать --build.")
    return 0


# --- сборка ----------------------------------------------------------------

def write_layer(spec, records: list, out_dir: Path) -> None:
    geo = out_dir / "geojson" / f"{spec.slug}.geojson"
    n = write_geojson(records, geo, layer_title=spec.title, hoist_shared=True)
    off_map = [r for r in records if not r.has_point]
    json_path = out_dir / f"{spec.slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{spec.title}: без точки")
    elif json_path.exists():
        json_path.unlink()
    jsonl = out_dir / "jsonl" / f"{spec.slug}.jsonl"
    write_jsonl(records, jsonl)
    print(f"«{spec.title}»: {len(records)} записей, на карте {n}, без точки {len(off_map)}")
    for path in (geo, json_path if off_map else None, jsonl):
        if path is not None:
            print(f"  → {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} "
                  f"({path.stat().st_size / 1024 / 1024:.1f} МБ)")


def build(cache: Path, out_dir: Path, provinces_path: Path) -> int:
    tables = fetch_tables(cache)
    got = collect(tables, load_provinces(provinces_path))
    settlements = got["1951"] + got["1946"]
    if not settlements or not got["1939"]:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    write_layer(SPECIAL_SETTLEMENTS, settlements, out_dir)
    write_layer(CENSUS_1939, got["1939"], out_dir)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="сверить с Zenodo, скачать, разобрать — без записи слоёв")
    ap.add_argument("--build", action="store_true", help="записать слои в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE, help="куда класть файлы пакета")
    ap.add_argument("--provinces", type=Path, default=PROVINCES_1897,
                    help="губернии 1897 года RISTAT: губерния по точке района")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache, args.provinces)
            if code or not args.build:
                return code
        return build(args.cache, args.out, args.provinces)
    except DeportationsError as exc:
        print(f"Спецпоселения и перепись 1939 года: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
