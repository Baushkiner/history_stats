#!/usr/bin/env python3
"""Кирхшпили, мызы и метрические книги Эстляндии и северной Лифляндии.

    python3 scripts/harvest_estonia.py --check   # проба обоих источников, файлов не пишет
    python3 scripts/harvest_estonia.py --fetch   # всё в кэш, с продолжением
    python3 scripts/harvest_estonia.py --build   # докачать недостающее и собрать три выгрузки

Два источника, одна цепочка «деревня → мыза → кирхшпиль → метрические книги»:

* WFS Maa- ja Ruumiamet «Ajalooline haldusjaotus» (`sources/maaamet.py`):
  кирхшпили, уезды и губернии до 1917 года полигонами и 2 513 мызных
  центров. Пять слоёв — пять запросов, в `data/raw/maaamet/` (25 МБ);
* открытые данные Rahvusarhiiv (`sources/rahvusarhiiv.py`): описи фондов
  приходов в apeEAD XML. Листинг каталога (379 страниц), первые 3 КБ
  каждого фонда-кандидата (около 4 000 запросов по заголовку Range) и
  файлы приходов целиком — в `data/raw/rahvusarhiiv/`.

Проверочный запуск обязателен. `--check` сверяет с замером 04.11.2026
заголовки и число объектов пяти слоёв WFS, поля и систему координат (сервер
подписывает ответ как EPSG:4326, а отдаёт L-EST97 — это проверяется по
величине координат, а не по подписи), листинг каталога архива и разбор
фонда Камби (EAA.1255). Расхождение — остановка, а не подгонка.

`--fetch` складывает всё в кэш. Первый обход — около часа: листинг
каталога отвечает медленно (страница — от одной до пяти секунд, около 20
минут на 379 страниц), шапки фондов — быстро (при паузе 0,5 с — около 35
минут на 4 034); оборванный обход продолжается тем же вызовом.

`--build` пишет:

* `boundaries/parishes_ee_1917.geojson` — 106 кирхшпилей со сводкой книг;
* `geojson/parish_registers_ee.geojson` и `jsonl/parish_registers_ee.jsonl`
  — фонд прихода на запись; несведённые с кирхшпилем фонды без точки —
  в `parish_registers_ee.json`;
* `geojson/manors_ee.geojson` и `jsonl/manors_ee.jsonl` — мызы;
* с ключом `--manor-lands` — ещё `boundaries/manor_lands_ee_1917.geojson`,
  1 232 полигона мызных земель (около 11 МБ): деревня с координатой сводится
  к мызе точкой в полигоне. По умолчанию не пишется — файл крупный, а
  кирхшпиль, от которого зависят книги, деревня получает и без него.

Права. Описи архива — CC0, сканы в Saaga — CC BY-SA и не копируются (слой
хранит ссылку). Данные Maa- ja Ruumiamet — по условиям его картографических
сервисов: выписки и производные разрешены со ссылкой на набор, дату и
ведомство; права на исторические единицы — у Национального архива.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from _paths import ROOT

from histctx.io_formats import (
    write_feature_collection, write_geojson, write_jsonl, write_records_json,
)
from histctx.sources import maaamet as M
from histctx.sources import rahvusarhiiv as R
from histctx.sources.ghcn import PROVINCES_PATH, GhcnError, Provinces

CACHE_WFS = ROOT / "data" / "raw" / "maaamet"
CACHE_RA = ROOT / "data" / "raw" / "rahvusarhiiv"
OUT = ROOT / "data" / "out"
BOUNDARIES_FILE = f"{M.PARISH_BOUNDARIES_EE.slug}.geojson"

# Фонд для пробы: приход Камби — пример из журнала дискавери (EAA.1255, 604
# единицы описания, 144 ссылки на сканы).
PROBE_FOND = "RA_EAA1255.xml"


# --- WFS ------------------------------------------------------------------------

def wfs_layers(cache: Path, client: M.Client, *, refresh: bool = False,
               offline: bool = False) -> dict[str, list]:
    """Пять слоёв: из кэша или из сервиса; каждый сверяется с замером."""
    out = {}
    for layer in M.LAYERS:
        path = cache / f"{layer.name}.gml"
        if not path.exists() or refresh:
            if offline:
                raise M.MaaametError(f"нет {path}: сначала --fetch")
            data = client.layer(layer)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        features = M.parse_gml(path.read_bytes(), layer.name)
        M.check_layer(layer, features)
        out[layer.name] = features
    return out


def check_wfs(client: M.Client) -> None:
    titles = M.parse_capabilities(client.capabilities())
    print(f"WFS: слоёв в GetCapabilities — {len(titles)} (при проверке 04.11.2026 — 117)")
    for layer in M.LAYERS:
        title = titles.get(layer.name)
        if title != layer.title:
            raise M.MaaametError(
                f"слой {layer.name}: заголовок {title!r}, а не {layer.title!r} — сервис "
                "переделан; посмотрите, что изменилось")
    for layer in M.LAYERS:
        matched = M.parse_hits(client.layer(layer, resultType="hits"))
        features = M.parse_gml(client.layer(layer, count=2), layer.name)
        M.check_layer(layer, features, matched)
        f = features[0]
        if f.point:
            lat, lon = M.lest97_to_wgs84(*f.point)
        else:
            x, y = M.point_on_surface(f.polygons)
            lat, lon = M.lest97_to_wgs84(x, y)
        fields = ", ".join(f"{k}={v!r}" for k, v in list(f.props.items())[:4] if k != "y")
        print(f"  {layer.name}: {matched} объектов; первый — {fields}; "
              f"точка {lat:.4f}, {lon:.4f}")
    print("  координаты — L-EST97 (проверено по величине), обратная проекция своя")


# --- архив ------------------------------------------------------------------------

def listing_names(client: R.Client, *, refresh: bool = False) -> list[str]:
    first = client.listing_page(1, refresh=refresh)
    pages = R.listing_pages(first)
    if pages != R.EXPECTED_PAGES:
        print(f"  страниц в каталоге {pages}, а не {R.EXPECTED_PAGES}: снимок переиздан?")
    names = R.parse_listing(first)
    for page in range(2, pages + 1):
        names += R.parse_listing(client.listing_page(page, refresh=refresh))
        if page % 50 == 0:
            print(f"  листинг: {page}/{pages}", flush=True)
    names = list(dict.fromkeys(names))
    if len(names) != R.EXPECTED_FILES:
        raise R.RahvusarhiivError(
            f"в каталоге {len(names)} файлов, а не {R.EXPECTED_FILES} (замер 04.11.2026): "
            "снимок переиздан — посмотрите, что изменилось, и поправьте EXPECTED_FILES")
    return names


def parish_heads(client: R.Client, names: list[str]) -> tuple[list, list]:
    """Шапки кандидатов → (приходы, фонды «… kogudus» без признака конфессии)."""
    candidates = [n for n in names if R.is_candidate(n)]
    todo = [n for n in candidates if not (client.cache_dir / "heads" / n).exists()]
    print(f"Фондов-кандидатов: {len(candidates)}; шапок в кэше: "
          f"{len(candidates) - len(todo)}, докачать: {len(todo)}")
    parishes, unknown = [], []
    for i, name in enumerate(candidates, 1):
        head = R.parse_head(name, client.head(name))
        confession = R.fond_confession(head.title, head.code)
        if confession:
            parishes.append((head, confession))
        elif head.title and R._RE_CONGREGATION.search(head.title):
            unknown.append(head)
        if i % 500 == 0:
            print(f"  шапки: {i}/{len(candidates)}", flush=True)
    return parishes, unknown


def check_archive(client: R.Client) -> None:
    first = client.get(R.LISTING_PATH).decode("utf-8", "replace")
    pages, names = R.listing_pages(first), R.parse_listing(first)
    print(f"Каталог Rahvusarhiiv: страниц {pages} (замер — {R.EXPECTED_PAGES}), "
          f"файлов на первой {len(names)}: {', '.join(names[:3])}…")
    if not names:
        raise R.RahvusarhiivError("на странице каталога нет ссылок на файлы: разметку поменяли")
    head = R.parse_head(PROBE_FOND, client.get(R.FILE_PATH.format(name=PROBE_FOND),
                                               head_bytes=R.HEAD_BYTES))
    confession = R.fond_confession(head.title)
    print(f"  {PROBE_FOND}: {head.code} «{head.title}», {head.dates}; конфессия — {confession}")
    if head.code != "EAA.1255" or confession != "лютеранский":
        raise R.RahvusarhiivError("шапка фонда Камби разобралась не так: поправьте разбор")
    fond = R.parse_fond(client.get(R.FILE_PATH.format(name=PROBE_FOND)))
    books = R.fond_books(fond)
    ranges = R.year_ranges(books.metrical_units)
    scans = sum(1 for u in books.metrical_units if u.scan_url)
    print(f"  единиц описания: {len(fond.units)}; метрических книг: {len(books.metrical)} "
          f"({scans} со сканом), годы {R.format_ranges(ranges)}; смежных книг: {len(books.other)}")
    if not books.metrical:
        raise R.RahvusarhiivError("в фонде Камби не нашлось ни одной метрической книги")


# --- сборка ------------------------------------------------------------------------

def build(args) -> int:
    wfs_client = M.Client(pause_sec=args.pause_wfs)
    layers = wfs_layers(args.cache_wfs, wfs_client, refresh=args.refresh, offline=args.offline)
    parishes = M.build_parishes(layers[M.PARISH_LAYER.name], layers[M.COUNTY_LAYER.name])
    print(f"Кирхшпилей: {len(parishes)}; мызных центров: "
          f"{len(layers[M.MANOR_LAYER.name])}; полигонов мызных земель: "
          f"{len(layers[M.MANOR_LAND_LAYER.name])}")
    check_regions(parishes)

    parish_areas = [M.Area.of(f) for f in layers[M.PARISH_LAYER.name]]
    county_areas = [M.Area.of(f) for f in layers[M.COUNTY_LAYER.name]]
    land_areas = [M.Area.of(f) for f in layers[M.MANOR_LAND_LAYER.name]]
    manors = [M.manor_record(f, parishes=parish_areas, counties=county_areas, lands=land_areas)
              for f in layers[M.MANOR_LAYER.name]]
    report_manors(manors)

    ra_client = R.Client(args.cache_ra, pause_sec=args.pause_ra)
    try:
        if args.offline:
            names = offline_listing(args.cache_ra)
        else:
            names = listing_names(ra_client, refresh=args.refresh)
        heads, unknown = parish_heads(ra_client, names) if not args.offline \
            else offline_heads(args.cache_ra, names)
        for head in unknown:
            print(f"  «… kogudus» без признака конфессии, в слой не идёт: {head.code} "
                  f"«{head.title}»")
        fonds = []
        for head, confession in heads:
            path = args.cache_ra / "fonds" / head.name
            if args.offline and not path.exists():
                print(f"  нет в кэше: {head.name} — фонд пропущен, запустите --fetch")
                continue
            fonds.append((head, confession, R.parse_fond(ra_client.fond(head.name))))
    finally:
        ra_client.close()
    print(f"Фондов приходов: {len(fonds)}")

    index = R.ParishIndex.build(parishes, layers[M.MANOR_LAYER.name])
    records, by_parish = [], collections.defaultdict(list)
    for head, confession, fond in fonds:
        match = index.match(fond.title or head.title)
        record = R.fond_record(head, confession, fond, match)
        records.append(record)
        if match.parish:
            by_parish[match.parish].append(R.parish_summary(record))
    report_registers(records)

    manors_in = collections.Counter((r.extra or {}).get("parish") for r in manors)
    feats = [M.parish_feature(p, sorted(by_parish.get(p.name, []), key=R.summary_order),
                              manors_in.get(p.name, 0)) for p in parishes]
    n = write_feature_collection(M.boundaries_collection(feats),
                                 args.out / "boundaries" / BOUNDARIES_FILE, compact=True)
    print(f"\nПодложка: {n} кирхшпилей → boundaries/{BOUNDARIES_FILE}")

    if args.manor_lands:
        lands = [M.manor_land_feature(f) for f in layers[M.MANOR_LAND_LAYER.name]]
        n = write_feature_collection(M.manor_lands_collection(lands),
                                     args.out / "boundaries" / "manor_lands_ee_1917.geojson",
                                     compact=True)
        print(f"Мызные земли: {n} полигонов → boundaries/manor_lands_ee_1917.geojson")

    slug = R.PARISH_REGISTERS_EE.slug
    n_points = write_geojson(records, args.out / "geojson" / f"{slug}.geojson",
                             layer_title=R.PARISH_REGISTERS_EE.title, hoist_shared=True)
    write_jsonl(records, args.out / "jsonl" / f"{slug}.jsonl")
    pointless = [r for r in records if not r.has_point]
    if pointless:
        write_records_json(pointless, args.out / f"{slug}.json",
                           title=R.PARISH_REGISTERS_EE.title)
    print(f"Метрические книги: {len(records)} фондов, на карту — {n_points}, "
          f"без точки — {len(pointless)}")

    slug = M.MANORS_EE.slug
    n_points = write_geojson(manors, args.out / "geojson" / f"{slug}.geojson",
                             layer_title=M.MANORS_EE.title, hoist_shared=True)
    write_jsonl(manors, args.out / "jsonl" / f"{slug}.jsonl")
    print(f"Мызы: {len(manors)} записей, на карту — {n_points}")
    return 0


def offline_listing(cache: Path) -> list[str]:
    pages = sorted((cache / "listing").glob("page-*.html"))
    if len(pages) < R.EXPECTED_PAGES:
        raise R.RahvusarhiivError(f"в кэше {len(pages)} страниц листинга из "
                                  f"{R.EXPECTED_PAGES}: сначала --fetch")
    names = []
    for page in pages:
        names += R.parse_listing(page.read_text(encoding="utf-8"))
    return list(dict.fromkeys(names))


def offline_heads(cache: Path, names: list[str]) -> tuple[list, list]:
    parishes, unknown, missing = [], [], 0
    for name in names:
        if not R.is_candidate(name):
            continue
        path = cache / "heads" / name
        if not path.exists():
            missing += 1
            continue
        head = R.parse_head(name, path.read_bytes())
        confession = R.fond_confession(head.title, head.code)
        if confession:
            parishes.append((head, confession))
        elif head.title and R._RE_CONGREGATION.search(head.title):
            unknown.append(head)
    if missing:
        print(f"  шапок нет в кэше: {missing} — сборка неполная, запустите --fetch")
    return parishes, unknown


def check_regions(parishes: list) -> None:
    """Губерния источника против губернии 1897 года по полигонам RISTAT."""
    try:
        provinces = Provinces.load(ROOT / PROVINCES_PATH)
    except GhcnError as exc:
        print(f"  сверка с губерниями 1897 года пропущена: {exc}")
        return
    diff = [(p.name, p.region, provinces.region_for(p.lat, p.lon)) for p in parishes
            if provinces.region_for(p.lat, p.lon) != p.region]
    print(f"  губерния по полю KUBERMANG и по полигонам 1897 года расходится у {len(diff)} "
          f"кирхшпилей из {len(parishes)}")
    for name, ours, theirs in diff[:10]:
        print(f"    {name}: {ours} / {theirs}")
    hiiu = [p.name for p in parishes if p.county_src != p.county]
    if hiiu:
        print(f"  уезд по полигону 1917 года вместо поля MAAKOND: {', '.join(hiiu)}")


def report_manors(records: list) -> None:
    dated = [r for r in records if r.has_time]
    print(f"Мызы: {len(records)}; с первым упоминанием: {len(dated)}")
    if dated:
        print(f"  годы первого упоминания: {min(r.year_from for r in dated)}–"
              f"{max(r.year_from for r in dated)}")
    print("  по типам:", dict(collections.Counter(r.category for r in records).most_common()))
    print("  достоверность:", dict(collections.Counter(r.confidence for r in records)))
    print("  точность исходного упоминания:", dict(collections.Counter(
        (r.extra or {}).get("first_mention_precision") for r in records).most_common()))
    mismatch = [r for r in records if (r.extra or {}).get("parish_mismatch")]
    outside = [r for r in records if "parish" not in (r.extra or {})]
    print(f"  кирхшпиль поля KIHELKOND и полигона расходится: {len(mismatch)}; "
          f"точка вне полигонов кирхшпилей: {len(outside)}")


def report_registers(records: list) -> None:
    print(f"\nФондов приходов: {len(records)}; с метрическими книгами: "
          f"{sum(1 for r in records if r.has_time)}")
    print("  по конфессиям:", dict(collections.Counter(r.category for r in records)))
    print("  сведение с кирхшпилем:", dict(collections.Counter(
        (r.extra or {}).get("match") for r in records).most_common()))
    print("  достоверность:", dict(collections.Counter(r.confidence for r in records)))
    dated = [r for r in records if r.has_time]
    if dated:
        print(f"  годы книг: {min(r.year_from for r in dated)}–{max(r.year_to for r in dated)}")
        books = sum((r.extra or {}).get("metrical", {}).get("units", 0) for r in records)
        scans = sum((r.extra or {}).get("metrical", {}).get("scans", 0) for r in records)
        print(f"  метрических книг: {books}, со сканом: {scans}")
    for r in records:
        if r.confidence == "parish_unmatched":
            print(f"    не сведён: {r.source_id} «{(r.extra or {}).get('fond_title')}»")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="проба обоих источников — без записи файлов")
    ap.add_argument("--fetch", action="store_true", help="всё скачать в кэш")
    ap.add_argument("--build", action="store_true", help="собрать выгрузки в data/out")
    ap.add_argument("--offline", action="store_true", help="собирать только из кэша")
    ap.add_argument("--refresh", action="store_true",
                    help="перечитать слои WFS и листинг каталога (шапки и фонды — нет)")
    ap.add_argument("--manor-lands", action="store_true",
                    help="--build: записать и полигоны мызных земель (около 11 МБ)")
    ap.add_argument("--pause-wfs", type=float, default=3.0, help="пауза между запросами к WFS, с")
    ap.add_argument("--pause-ra", type=float, default=0.5,
                    help="пауза между запросами к каталогу архива, с")
    ap.add_argument("--cache-wfs", type=Path, default=CACHE_WFS)
    ap.add_argument("--cache-ra", type=Path, default=CACHE_RA)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check, --fetch или --build")
    try:
        if args.check:
            check_wfs(M.Client(pause_sec=args.pause_wfs))
            client = R.Client(args.cache_ra, pause_sec=args.pause_ra)
            try:
                check_archive(client)
            finally:
                client.close()
            print("\nПоля на месте, разбор работает — можно запускать --fetch и --build.")
            return 0
        if args.fetch and not args.build:
            wfs_layers(args.cache_wfs, M.Client(pause_sec=args.pause_wfs), refresh=args.refresh)
            client = R.Client(args.cache_ra, pause_sec=args.pause_ra)
            try:
                heads, _ = parish_heads(client, listing_names(client, refresh=args.refresh))
                for i, (head, _) in enumerate(heads, 1):
                    client.fond(head.name)
                    if i % 50 == 0:
                        print(f"  фонды: {i}/{len(heads)}", flush=True)
            finally:
                client.close()
            print(f"В кэше: пять слоёв WFS, листинг, шапки и {len(heads)} фондов приходов")
            return 0
        return build(args)
    except (M.MaaametError, R.RahvusarhiivError) as exc:
        print(f"Эстония: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано; уже скачанное лежит в кэше, повторный вызов продолжит.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
