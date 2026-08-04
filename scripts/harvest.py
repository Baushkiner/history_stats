#!/usr/bin/env python3
"""Сбор новых слоёв из Викиданных по запросам из каталога queries/.

    python3 scripts/harvest.py --check                 # только сверить Q-номера
    python3 scripts/harvest.py --layer churches        # собрать один слой
    python3 scripts/harvest.py --all --paged           # собрать всё постранично

Перед сбором каждый Q-номер из заголовка запроса сверяется с Викиданными.
Если класс называется не тем, что объявлено в файле, сбор не начинается:
молча собрать не тот класс хуже, чем остановиться с ошибкой.

Требуется доступ в интернет к query.wikidata.org.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.io_formats import write_geojson, write_jsonl, write_xlsx  # noqa: E402
from histctx.registry import BY_SLUG  # noqa: E402
from histctx.schema import LayerSpec  # noqa: E402
from histctx.sources.wikidata import (  # noqa: E402
    SparqlClient, SparqlError, rows_to_records, verify_qids,
)

QUERY_DIR = ROOT / "queries"
_RE_META = re.compile(r"^#\s*@(\w+)\s+(.*)$")


def parse_query(path: Path) -> dict:
    """Читает .rq вместе с заголовочными директивами @layer/@title/@qid."""
    meta: dict = {"qids": [], "path": path}
    body: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _RE_META.match(line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            if key == "qid":
                qid, _, label = value.partition(" ")
                meta["qids"].append((qid.strip(), label.strip()))
            else:
                meta[key] = value
        elif not line.startswith("#"):
            body.append(line)
    meta["sparql"] = "\n".join(body).strip()
    meta.setdefault("layer", path.stem)
    meta.setdefault("title", path.stem)
    # @kind event — слой событий: открытая дата не дотягивается до 1960 года.
    meta.setdefault("kind", "object")
    return meta


def _same(declared: str, actual: str) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"[^а-яa-z]", "", s.lower().replace("ё", "е"))
    a, b = norm(declared), norm(actual)
    return bool(a) and bool(b) and (a in b or b in a)


def check_queries(client: SparqlClient, metas: list[dict]) -> bool:
    """Сверяет объявленные Q-номера с реальными названиями классов."""
    pairs = [(q, lbl) for m in metas for q, lbl in m["qids"]]
    labels = verify_qids(client, [q for q, _ in pairs])

    ok = True
    print("Сверка классов Викиданных:\n")
    for meta in metas:
        for qid, declared in meta["qids"]:
            actual = labels.get(qid)
            if actual is None:
                print(f"  [НЕТ]      {qid:10s} не найден  ({meta['layer']})")
                ok = False
            elif declared in {"?", ""}:
                print(f"  [УТОЧНИТЬ] {qid:10s} = «{actual}»  ({meta['layer']}) — впишите название в .rq")
                ok = False
            elif _same(declared, actual):
                print(f"  [ок]       {qid:10s} = «{actual}»  ({meta['layer']})")
            else:
                print(f"  [НЕ ТОТ]   {qid:10s} объявлен «{declared}», на деле «{actual}»  ({meta['layer']})")
                ok = False
    print()
    return ok


def harvest(client: SparqlClient, meta: dict, spec: LayerSpec, out_dir: Path,
            paged: bool, page_size: int) -> int:
    print(f"Сбор слоя «{meta['title']}» ({meta['layer']})…")
    if paged:
        rows = list(client.query_paged(meta["sparql"], page_size=page_size))
    else:
        rows = client.query(meta["sparql"])
    print(f"  получено строк: {len(rows)}")

    records = rows_to_records(rows, spec, kind=meta["kind"])
    print(f"  с координатами в границах РИ/СССР: {len(records)}")
    dated = sum(1 for r in records if r.has_time)
    print(f"  с датировкой: {dated}")

    slug = spec.slug
    write_geojson(records, out_dir / "geojson" / f"{slug}.geojson", layer_title=spec.title)
    write_jsonl(records, out_dir / "jsonl" / f"{slug}.jsonl")
    write_xlsx(records, out_dir / "xlsx" / f"{slug}.xlsx", sheet_name=spec.title)
    print(f"  записано в {out_dir}/{{geojson,jsonl,xlsx}}/{slug}.*")
    return len(records)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", action="append", help="слой для сбора (можно повторять)")
    ap.add_argument("--all", action="store_true", help="собрать все слои из queries/")
    ap.add_argument("--check", action="store_true", help="только сверить Q-номера и выйти")
    ap.add_argument("--paged", action="store_true", help="постраничный сбор для больших слоёв")
    ap.add_argument("--page-size", type=int, default=5000)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "cache")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    files = sorted(QUERY_DIR.glob("*.rq"))
    if not files:
        print(f"В {QUERY_DIR} нет файлов запросов.", file=sys.stderr)
        return 1

    metas = [parse_query(p) for p in files]
    if args.layer:
        wanted = set(args.layer)
        metas = [m for m in metas if m["layer"] in wanted]
        unknown = wanted - {m["layer"] for m in metas}
        if unknown:
            print(f"Неизвестные слои: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
    elif not args.all and not args.check:
        ap.error("укажите --layer <слой>, --all или --check")

    client = SparqlClient(cache_dir=None if args.no_cache else args.cache)

    try:
        ok = check_queries(client, metas)
    except SparqlError as exc:
        print(f"Не удалось связаться с Викиданными: {exc}", file=sys.stderr)
        return 2

    if args.check:
        return 0 if ok else 1
    if not ok:
        print("Сверка не пройдена — сбор отменён. Исправьте Q-номера в queries/*.rq.", file=sys.stderr)
        return 1

    total = 0
    for meta in metas:
        spec = BY_SLUG.get(meta["layer"])
        if spec is None:
            print(f"  слой {meta['layer']} не описан в registry.py — пропускаю", file=sys.stderr)
            continue
        try:
            total += harvest(client, meta, spec, args.out, args.paged, args.page_size)
        except SparqlError as exc:
            print(f"  ОШИБКА при сборе {meta['layer']}: {exc}", file=sys.stderr)

    print(f"\nВсего собрано записей: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
