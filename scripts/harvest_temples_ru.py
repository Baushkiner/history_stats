#!/usr/bin/env python3
"""Сбор слоя храмов по реестру «Храмы России» (temples.ru).

    python3 scripts/harvest_temples_ru.py --check              # живая проба на одном регионе
    python3 scripts/harvest_temples_ru.py --fetch              # пакетные выгрузки, с кэшем
    python3 scripts/harvest_temples_ru.py --cards 3000         # дочитать карточки, с продолжением
    python3 scripts/harvest_temples_ru.py --build              # записи в data/out

Проверочный первый запуск обязателен. `--check` (он же `--probe`) живьём
скачивает в `data/raw/temples_ru/probe/` форму поиска, всю выдачу по
Алтайскому краю (169 карточек на 24.11.2026) по трём типам построек, KML
края, ветку Акмолинской области в дереве губерний с её уездами и одну
карточку — и сверяет: сумма выдачи по типам должна сойтись со счётчиком
сайта, точек KML не может быть больше карточек. Расхождение — остановка.

`--fetch` идёт по ступеням, каждая докачивает недостающее и пропускает то,
что уже лежит в `data/raw/temples_ru/`: выдача поиска по каждому из 86
регионов и трём типам (около 700 страниц по 50 строк), KML по регионам (86
файлов), дерево губерний и уездов 1917 года (54 губернии) и KML по каждой
губернии и уезду (около 700 файлов). Оборванный обход продолжается тем же
`--fetch`. Пауза между обращениями — 1,5 с, одно соединение; на 429 и 5xx —
отступ с ростом паузы.

`--cards N` дочитывает до N карточек `card.php?ID=…` (`--cards all` —
все): сначала те, у которых нет точки, потом не приписанные к губернии,
потом остальные. Разобранное ложится строкой в `cards.jsonl`, повторный
запуск продолжает с того места, где остановился. Обход всех 33 тысяч —
около 15 часов.

`--build` разбирает кэш без сети и пишет слой. Губерния и уезд — по
дереву 1917 года на сайте (`region`, `district`); у записей вне дерева
`region` — губерния 1897 года по точке, как у соседних слоёв.

Права: «Перепечатка или воспроизведение материалов… допускается только с
письменного разрешения»; сбор идёт с согласия владельца, полученного
владельцем проекта (сообщено 24.11.2026). Берутся факты и ссылка на карточку,
снимки остаются на сайте.

На выходе:

* `geojson/temples_ru.geojson` — карточки с точкой;
* `temples_ru.json` — карточки без точки, `confidence = no_coords`;
* `jsonl/temples_ru.jsonl` — слой целиком (в `.gitignore`).
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
from pathlib import Path

from _paths import ROOT

from histctx.frame import OUTSIDE, Frame
from histctx.io_formats import read_geojson, write_geojson, write_jsonl, write_records_json
from histctx.sources.temples_ru import (
    SEARCH_PATH, TEMPLE_TYPES, TEMPLES_RU, Client, Collected, TemplesError, Unit, broken_units,
    decode, link_churches, page_count, parse_card, parse_kml, parse_province_children,
    parse_regions, parse_search, province_index, records, search_query,
)

CACHE = ROOT / "data" / "raw" / "temples_ru"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
CHURCHES = ROOT / "data" / "out" / "geojson" / "churches.geojson"

PROBE_REGION = 717         # Алтайский край: 169 карточек на 24.11.2026
PROBE_PROVINCE = 497       # Акмолинская область: 22 карточки
PROBE_CARD = 8248          # Вознесенская церковь на погосте Евфимиев Монастырь


# --- ступени обхода --------------------------------------------------------

def regions(client: Client) -> list[tuple[int, str]]:
    return parse_regions(decode(client.get(SEARCH_PATH, "form.html")))


def search_region(client: Client, region: int, log=print) -> tuple[int, int]:
    """Вся выдача по региону и трём типам. Возвращает (сумма счётчиков, строк)."""
    total = got = 0
    for code in TEMPLE_TYPES:
        first = decode(client.get(search_query(region, code), f"search/{region}_{code}_1.html"))
        count, rows = parse_search(first)
        if count is None:
            raise TemplesError(f"регион {region}, тип {code}: выдача не разобралась")
        total += count
        got += len(rows)
        for page in range(2, page_count(count) + 1):
            text = decode(client.get(search_query(region, code, page),
                                     f"search/{region}_{code}_{page}.html"))
            got += len(parse_search(text)[1])
    return total, got


def province_tree(client: Client, only: int | None = None) -> list[Unit]:
    """Губернии и их уезды из дерева «Храмы Империи»."""
    _, gubs = parse_province_children(decode(client.get(
        "provincies.php?ProvinceID=0", "provinces/0.html")))
    units: list[Unit] = []
    for gid, name, _ in gubs:
        if only is not None and gid != only:
            continue
        units.append(Unit(gid, name))
        _, children = parse_province_children(decode(client.get(
            f"provincies.php?ProvinceID={gid}", f"provinces/{gid}.html")))
        units += [Unit(cid, cname, gid) for cid, cname, _ in children]
    return units


def kml(client: Client, kind: str, uid: int) -> list:
    key = "TreeID" if kind == "tree" else "ProvinceID"
    return parse_kml(decode(client.get(f"getkml.php?{key}={uid}", f"kml/{kind}_{uid}.kml")))


def fetch(client: Client, log=print) -> int:
    regs = regions(client)
    log(f"Регионов в форме поиска: {len(regs)}")
    total = got = 0
    for i, (rid, name) in enumerate(regs, 1):
        t, g = search_region(client, rid)
        total, got = total + t, got + g
        mark = "" if t == g else f"  ← строк {g} при счётчике {t}"
        log(f"  [{i}/{len(regs)}] {name}: {t}{mark}")
    log(f"Выдача поиска: счётчики {total}, строк {got}; запросов {client.requests}")
    for i, (rid, name) in enumerate(regs, 1):
        pts = kml(client, "tree", rid)
        if i % 10 == 0 or i == len(regs):
            log(f"  KML регионов: {i}/{len(regs)} (последний — {name}, {len(pts)} точек)")
    units = province_tree(client)
    log(f"Дерево 1917 года: {sum(1 for u in units if u.parent is None)} губерний, "
        f"{sum(1 for u in units if u.parent is not None)} уездов и городов")
    for i, unit in enumerate(units, 1):
        kml(client, "prov", unit.id)
        if i % 50 == 0 or i == len(units):
            log(f"  KML губерний и уездов: {i}/{len(units)}; запросов {client.requests}")
    (client.cache_dir / "units.json").write_text(
        json.dumps([u.__dict__ for u in units], ensure_ascii=False), encoding="utf-8")
    return 0


# --- карточки --------------------------------------------------------------

def load_cards(cache: Path) -> dict[int, dict]:
    path = cache / "cards.jsonl"
    out: dict[int, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue        # строка, оборванная остановкой обхода, — дочитается
            out[int(item["id"])] = item
    return out


def card_order(data: Collected) -> list[int]:
    """Сначала карточки без точки, затем без губернии, затем остальные."""
    ids = sorted(set(data.rows) | set(data.points))
    return sorted(ids, key=lambda i: (i in data.points, i in data.units, i))


def fetch_cards(client: Client, data: Collected, limit: int | None, log=print) -> int:
    done = load_cards(client.cache_dir)
    todo = [i for i in card_order(data) if i not in done]
    if limit is not None:
        todo = todo[:limit]
    log(f"Карточек прочитано {len(done)}, в очереди {len(todo)}")
    path = client.cache_dir / "cards.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    torn = path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8") as fh:
        if torn:
            fh.write("\n")      # оборванная строка остаётся отдельной и пропускается
        for n, cid in enumerate(todo, 1):
            raw = client.fetch(f"card.php?ID={cid}")
            card = parse_card(decode(raw)) or {"missing": True}
            card["id"] = cid
            fh.write(json.dumps(card, ensure_ascii=False) + "\n")
            fh.flush()
            if n % 200 == 0 or n == len(todo):
                log(f"  карточек {n}/{len(todo)}")
    return 0


# --- разбор кэша -----------------------------------------------------------

def collect(cache: Path) -> tuple[Collected, dict]:
    data = Collected()
    meta: dict = collections.Counter()
    for path in sorted((cache / "search").glob("*.html")):
        region, code, _ = (int(x) for x in path.stem.split("_"))
        _, rows = parse_search(decode(path.read_bytes()))
        for row in rows:
            row.temple_type = TEMPLE_TYPES[code]
            row.region_id = region
            if row.id in data.rows:
                meta["повтор строки поиска"] += 1
            data.rows.setdefault(row.id, row)
    for path in sorted((cache / "kml").glob("tree_*.kml")):
        for pm in parse_kml(decode(path.read_bytes())):
            data.points.setdefault(pm.id, pm)
    units_path = cache / "units.json"
    if units_path.exists():
        units = [Unit(**u) for u in json.loads(units_path.read_text(encoding="utf-8"))]
        members = {}
        for unit in units:
            path = cache / "kml" / f"prov_{unit.id}.kml"
            if path.exists():
                pts = parse_kml(decode(path.read_bytes()))
                members[unit.id] = [p.id for p in pts]
                for pm in pts:
                    data.points.setdefault(pm.id, pm)
        counts = {}
        for path in (cache / "provinces").glob("*.html"):
            children = parse_province_children(decode(path.read_bytes()))[1]
            counts.update((i, c) for i, _, c in children)
        bad = broken_units(members, counts)
        for unit in units:
            if unit.id in bad:
                meta[f"KML не по своей единице, пропущена: {unit.name}"] = len(members[unit.id])
        data.units = province_index(units, members, counts)
    data.cards = {cid: c for cid, c in load_cards(cache).items() if not c.get("missing")}
    meta["карточек отсутствует на сайте"] = sum(1 for c in load_cards(cache).values()
                                                if c.get("missing"))
    return data, meta


def churches_link(recs: list, path: Path) -> int:
    """`extra.churches` — uid того же храма в слое Викиданных (`link_churches`)."""
    if not path.exists():
        print(f"  {path.relative_to(ROOT)} нет — связи со слоем churches не будет",
              file=sys.stderr)
        return 0
    return link_churches(recs, read_geojson(path))


def finish(recs: list) -> collections.Counter:
    """Губерния 1897 года по точке тем, у кого нет своей, и рамка РИ/СССР."""
    frame = Frame.load(BOUNDARIES)
    counts: collections.Counter = collections.Counter()
    for rec in recs:
        if not rec.has_point:
            continue
        inside, province, _ = frame.place(rec.lat, rec.lon)
        if not rec.region and province:
            rec.region = province
            rec.extra["region_via"] = "губерния 1897 года по точке"
            counts["губерния — по точке (1897)"] += 1
        if not inside:
            rec.confidence = OUTSIDE
            counts["вне рамки РИ/СССР"] += 1
    return counts


def report(recs: list, meta: dict) -> None:
    pts = sum(1 for r in recs if r.has_point)
    print(f"Записей {len(recs)}: с точкой {pts}, без точки {len(recs) - pts}")
    for key, n in meta.items():
        print(f"  {key}: {n}")
    for title, key in (("типы", lambda r: r.category), ("статус", lambda r: r.extra.get("status")),
                       ("исповедание", lambda r: r.extra.get("confession")),
                       ("датировка", lambda r: r.extra.get("date_source") or r.date_precision)):
        print(f"  {title}:")
        for name, n in collections.Counter(map(key, recs)).most_common(8):
            print(f"    {n:>6}  {name}")
    print(f"  с губернией 1917 года: {sum(1 for r in recs if r.extra.get('guberniya_1917'))}, "
          f"с уездом: {sum(1 for r in recs if r.district)}")
    print(f"  карточка прочитана: {sum(1 for r in recs if r.extra.get('card_read'))}")


def build(recs: list, out_dir: Path) -> int:
    slug = TEMPLES_RU.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(recs, geo, layer_title=TEMPLES_RU.title, hoist_shared=True)
    off = [r for r in recs if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    write_records_json(off, json_path, title=f"{TEMPLES_RU.title}: без точки",
                       hoist_shared=True, compact=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(recs, jsonl)
    print(f"«{TEMPLES_RU.title}»: {len(recs)} записей, на карте {n}, без точки {len(off)}")
    for path in (geo, json_path, jsonl):
        print(f"  → {path} ({path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


# --- проба -----------------------------------------------------------------

def check(cache: Path) -> int:
    probe = cache / "probe"
    if probe.exists():
        shutil.rmtree(probe)
    client = Client(probe, pause=1.5)
    regs = dict(regions(client))
    print(f"Форма поиска: {len(regs)} регионов; пробный — {regs.get(PROBE_REGION)}")
    total, got = search_region(client, PROBE_REGION)
    print(f"  выдача по трём типам: счётчики {total}, строк {got}")
    pts = kml(client, "tree", PROBE_REGION)
    print(f"  KML региона: {len(pts)} точек")
    units = province_tree(client, only=PROBE_PROVINCE)
    for unit in units:
        kml(client, "prov", unit.id)
    (probe / "units.json").write_text(json.dumps([u.__dict__ for u in units], ensure_ascii=False),
                                      encoding="utf-8")
    print(f"  ветка дерева 1917 года: {units[0].name}, единиц {len(units)}")
    card = parse_card(decode(client.fetch(f"card.php?ID={PROBE_CARD}")))
    if not card:
        print("Карточка не разобралась: сайт переверстали.", file=sys.stderr)
        return 1
    print(f"  карточка {PROBE_CARD}: {card.get('name')} — {card.get('address_1917')}, "
          f"{card.get('built')}, точка {card.get('lat')}, {card.get('lon')}")
    with (probe / "cards.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(card, ensure_ascii=False) + "\n")
    if total != got or len(pts) > total:
        print("Выдача не сходится со счётчиком: остановка.", file=sys.stderr)
        return 1
    data, meta = collect(probe)
    recs = records(data)
    report(recs, meta)
    print(f"\nЗапросов {client.requests}. Сайт читается, разбор сходится — можно --fetch.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="живая проба на одном регионе — без записи слоя")
    ap.add_argument("--fetch", action="store_true", help="пакетные выгрузки, с продолжением")
    ap.add_argument("--cards", help="дочитать столько карточек (число или all)")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--pause", type=float, default=1.5, help="пауза между запросами, с")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.cards or args.build):
        ap.error("укажите --check, --fetch, --cards или --build")
    if args.pause < 1.0:
        ap.error("пауза меньше секунды — слишком часто для сайта")
    try:
        if args.check:
            return check(args.cache)
        client = Client(args.cache, pause=args.pause)
        if args.fetch:
            fetch(client)
        if args.cards:
            data, _ = collect(args.cache)
            limit = None if args.cards == "all" else int(args.cards)
            fetch_cards(client, data, limit)
    except TemplesError as exc:
        print(f"temples.ru: {exc}", file=sys.stderr)
        return 1
    if args.build:
        data, meta = collect(args.cache)
        recs = records(data)
        if not recs:
            print("В кэше нет ни одной карточки: сначала --fetch.", file=sys.stderr)
            return 1
        meta.update(finish(recs))
        meta["связано со слоем churches (Викиданные)"] = churches_link(recs, CHURCHES)
        report(recs, meta)
        return build(recs, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
