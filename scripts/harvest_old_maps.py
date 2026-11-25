#!/usr/bin/env python3
"""Сбор каталога старых привязанных карт: Retromap, ЭтоМесто, Kartenforum SLUB.

    python3 scripts/harvest_old_maps.py --check    # малая выборка трёх каталогов, разбор
    python3 scripts/harvest_old_maps.py --fetch    # полный обход (продолжает с места)
    python3 scripts/harvest_old_maps.py --build    # слой old_maps в data/out

Первый запуск — проверочный. `--check` (он же `--probe`) читает перечень
карт Retromap и две пачки сведений о них, весь отбор Kartenforum SLUB по
рамке РИ/СССР (один запрос) и у ЭтоМесто — перечень разделов, первую страницу
одного раздела и три страницы карт; показывает разбор.

`--fetch` — полный обход: Retromap пачками по 50 карт (около 130 запросов),
ЭтоМесто — страницы списков всех разделов по годам от ранних, пока годы не
уйдут за 1960, затем страницы этих карт (тысячи запросов, сайт отвечает с перебоями). Всё кладётся в
`data/raw/old_maps/` по мере получения, и прерванный обход продолжается с
места. Одно соединение, пауза между запросами не меньше секунды, на 429 и
5xx — отступ.

Права: согласие владельцев сайтов сообщено 24.11.2026; тайлы и сканы не
запрашиваются и не копируются, страницы карт Retromap (за проверкой «Я не
робот») — тоже.

На выходе `geojson/old_maps.geojson` — в репозиторий; `jsonl/old_maps.jsonl`
— в `.gitignore`.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.geo import BBOX_RU
from histctx.io_formats import write_geojson, write_jsonl
from histctx.net import RETRY_CODES, USER_AGENT, wait_for_pause
from histctx.sources.ghcn import GhcnError
from histctx.sources.old_maps import (
    ETOMESTO_BASE, ETOMESTO_PAGE, ETOMESTO_SKIP, OLD_MAPS, RETROMAP_DB_URL, RETROMAP_LIST_URL,
    SLUB_SEARCH_URL, YEAR_MAX, YEAR_MIN, OldMapsError, etomesto_page, etomesto_records,
    etomesto_rows, etomesto_sections, retromap_mcodes, retromap_records, slub_query,
    slub_records,
)

CACHE = ROOT / "data" / "raw" / "old_maps"
BOUNDARIES = ROOT / "data" / "out" / "boundaries"
BATCH = 50
# Общие разделы ЭтоМесто — первыми: карты всей России и соседних стран.
FIRST_SECTIONS = ("russia", "belarus", "world")
# Рамка для запроса к SLUB: (запад, юг, восток, север) по BBOX_RU.
FRAME_BOX = (BBOX_RU[1], BBOX_RU[0], BBOX_RU[3], BBOX_RU[2])


class Client:
    """Одно соединение, пауза, повторы на сбой сети, 429 и 5xx."""

    def __init__(self, pause_sec: float = 1.2, attempts: int = 5, timeout: int = 40):
        self.pause_sec, self.attempts, self.timeout = pause_sec, attempts, timeout
        self._last = 0.0
        self.requests = 0

    def get(self, url: str, data: bytes | None = None, *, required: bool = True) -> str:
        error = None
        for attempt in range(self.attempts):
            self._last = wait_for_pause(self._last, self.pause_sec)
            headers = {"User-Agent": USER_AGENT}
            if data is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.requests += 1
                    return response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES:
                    if not required:
                        return ""
                    raise OldMapsError(f"{url}: HTTP {exc.code}") from exc
                error = exc
            except (urllib.error.URLError, OSError) as exc:
                error = exc
            time.sleep(2 * (attempt + 1))
        if not required:
            print(f"  пропуск: {url} ({error})", file=sys.stderr)
            return ""
        raise OldMapsError(f"{url}: не ответил за {self.attempts} попыток ({error})")


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# --- Retromap ---------------------------------------------------------------

def fetch_retromap(client: Client, cache: Path, limit: int | None = None) -> dict:
    path = cache / "retromap.json"
    entries = _load(path, {})
    mcodes = retromap_mcodes(client.get(RETROMAP_LIST_URL))
    _save(cache / "retromap_mcodes.json", mcodes)
    todo = [m for m in mcodes if m not in entries]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    if limit is not None:
        batches = batches[:limit]
    print(f"Retromap: старых карт в перечне {len(mcodes)}, уже в кэше {len(entries)}, "
          f"пачек к запросу {len(batches)}")
    for n, batch in enumerate(batches, 1):
        query = urllib.parse.urlencode({"lang": "ru", "full": "1", "mcodes": " ".join(batch)})
        text = client.get(f"{RETROMAP_DB_URL}?{query}")
        try:
            got = json.loads(text)
        except ValueError as exc:
            raise OldMapsError(f"read_mcodes.php ответил не JSON: {text[:200]!r}") from exc
        for mcode in batch:
            # Карта, о которой сервер промолчал, помечается — чтобы не спрашивать снова.
            entries[mcode] = got.get(mcode) or {"missing": True}
        if n % 10 == 0 or n == len(batches):
            _save(path, entries)
            print(f"  пачка {n}/{len(batches)}")
    _save(path, entries)
    return entries


# --- SLUB ---------------------------------------------------------------------

def fetch_slub(client: Client, cache: Path) -> dict:
    body = json.dumps(slub_query(FRAME_BOX)).encode("utf-8")
    payload = json.loads(client.get(SLUB_SEARCH_URL, data=body))
    total = ((payload.get("hits") or {}).get("total") or {}).get("value")
    got = len((payload.get("hits") or {}).get("hits") or [])
    if total is not None and got < total:
        raise OldMapsError(f"SLUB: отдано {got} из {total} — поднимите size в slub_query")
    _save(cache / "slub.json", payload)
    print(f"SLUB: в рамке карт {total}")
    return payload


# --- ЭтоМесто -----------------------------------------------------------------

def fetch_etomesto_lists(client: Client, cache: Path, *, sections: list | None = None,
                         max_pages: int | None = None) -> dict:
    path = cache / "etomesto_rows.json"
    state = _load(path, {})
    if sections is None:
        sections = etomesto_sections(client.get(f"{ETOMESTO_BASE}/russia/catalog.php"))
        if not sections:
            raise OldMapsError("ЭтоМесто: в каталоге не нашлось разделов — сайт сменился")
    for section in sections:
        entry = state.setdefault(section, {"done": False, "rows": [], "next": 0})
        if entry["done"]:
            continue
        pages = 0
        while max_pages is None or pages < max_pages:
            start = entry["next"]
            text = client.get(f"{ETOMESTO_BASE}/{section}/maps.php?sort=2&start={start}",
                              required=False)
            pages += 1
            if not text:
                break           # не ответил — продолжим с этого места в следующий раз
            rows = etomesto_rows(text)
            known = {r["slug"] for r in entry["rows"]}
            fresh = [dict(r, section=section) for r in rows if r["slug"] not in known]
            entry["rows"] += fresh
            entry["next"] = start + ETOMESTO_PAGE
            # Список идёт по годам от ранних (sort=2). Конец: строк нет, всё уже
            # было (сайт за концом повторяет последнюю страницу) или годы ушли
            # за горизонт проекта — дальше только новые карты.
            if not fresh or all(r["year"] > YEAR_MAX for r in rows):
                entry["done"] = True
                break
        _save(path, state)
        print(f"  {section}: карт {len(entry['rows'])}"
              + ("" if entry["done"] else f", продолжить с {entry['next']}"))
    return state


def etomesto_wanted(state: dict) -> list[dict]:
    out, seen = [], set()
    for section in sorted(state):
        for row in state[section]["rows"]:
            if (row["slug"] in seen or not (YEAR_MIN <= row["year"] <= YEAR_MAX)
                    or row["slug"].startswith(ETOMESTO_SKIP)):
                continue
            seen.add(row["slug"])
            out.append(row)
    return out


def fetch_etomesto_pages(client: Client, cache: Path, rows: list,
                         limit: int | None = None) -> dict:
    path = cache / "etomesto_pages.json"
    pages = _load(path, {})
    todo = [r for r in rows if r["slug"] not in pages]
    if limit is not None:
        todo = todo[:limit]
    print(f"ЭтоМесто: страниц карт до {YEAR_MAX} года {len(rows)}, в кэше "
          f"{sum(1 for r in rows if r['slug'] in pages)}, к запросу {len(todo)}")
    for n, row in enumerate(todo, 1):
        text = client.get(f"{ETOMESTO_BASE}/map-{row['slug']}/", required=False)
        if text:
            pages[row["slug"]] = etomesto_page(text)
        if n % 25 == 0 or n == len(todo):
            _save(path, pages)
            print(f"  страниц {n}/{len(todo)}")
    _save(path, pages)
    return pages


# --- сборка -------------------------------------------------------------------

def collect(cache: Path) -> tuple[list, collections.Counter, collections.Counter]:
    recs = []
    retro = _load(cache / "retromap.json", {})
    recs += retromap_records({k: v for k, v in retro.items() if not v.get("missing")})
    slub = _load(cache / "slub.json", {})
    recs += slub_records(slub)
    state = _load(cache / "etomesto_rows.json", {})
    pages = _load(cache / "etomesto_pages.json", {})
    recs += etomesto_records(etomesto_wanted(state), pages)
    try:
        frame = Frame.load(BOUNDARIES)
    except (GhcnError, OSError, ValueError) as exc:
        raise OldMapsError(f"рамку взять неоткуда ({exc})") from exc
    counts = frame.mark(recs)
    # В слой идут карты с точкой в рамке РИ/СССР: это каталог карт «на это
    # место», и карта Парижа или Америки в нём ничего не объясняет.
    dropped = collections.Counter(r.extra.get("catalog") for r in recs
                                  if r.confidence in ("outside_bbox", "no_coords"))
    recs = [r for r in recs if r.confidence not in ("outside_bbox", "no_coords")]
    return recs, counts, dropped


def report(recs: list, counts, dropped) -> None:
    by = collections.Counter(r.extra.get("catalog") for r in recs)
    print(f"\n«{OLD_MAPS.title}»: {len(recs)} карт в рамке — " + ", ".join(
        f"{k} {v}" for k, v in by.most_common()))
    print("  вне рамки или без точки, не взяты: " + (", ".join(
        f"{k} {v}" for k, v in dropped.most_common()) or "нет"))
    for what, n in counts.most_common():
        print(f"  {what}: {n}")
    decades = collections.Counter((r.year_from // 50) * 50 for r in recs)
    print("  по полувекам: " + ", ".join(f"{k}: {v}" for k, v in sorted(decades.items())))
    for what, n in collections.Counter(r.category for r in recs).most_common():
        print(f"  {n:>5}  {what}")
    print(f"  повторов uid: {len(recs) - len({r.uid for r in recs})}")
    for key in ("retromap", "slub", "etomesto"):
        for rec in [r for r in recs if r.extra.get("catalog") == key][:2]:
            print(f"    {rec.title} [{rec.region or 'вне губерний 1897 года'}]\n"
                  f"      {rec.summary[:300]}")


def check(cache: Path) -> int:
    client = Client()
    fetch_retromap(client, cache, limit=2)
    fetch_slub(client, cache)
    state = fetch_etomesto_lists(client, cache, sections=["belarus"], max_pages=2)
    sections = etomesto_sections(client.get(f"{ETOMESTO_BASE}/russia/catalog.php"))
    print(f"ЭтоМесто: разделов в каталоге {len(sections)}")
    fetch_etomesto_pages(client, cache, etomesto_wanted(state)[:3])
    report(*collect(cache))
    print(f"\nЗапросов: {client.requests}. Разбор работает — можно запускать --fetch.")
    return 0


def fetch(cache: Path, only: str | None) -> int:
    client = Client()
    if only in (None, "retromap"):
        fetch_retromap(client, cache)
    if only in (None, "slub"):
        fetch_slub(client, cache)
    if only in (None, "etomesto"):
        # Раздел за разделом — список, затем страницы его карт: прерванный обход
        # оставляет готовые разделы, а не одни списки без страниц.
        sections = etomesto_sections(client.get(f"{ETOMESTO_BASE}/russia/catalog.php"))
        sections.sort(key=lambda x: (x not in FIRST_SECTIONS, x))
        for section in sections:
            state = fetch_etomesto_lists(client, cache, sections=[section])
            rows = [r for r in etomesto_wanted(state) if r.get("section") == section]
            fetch_etomesto_pages(client, cache, rows)
    print(f"Запросов: {client.requests}.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    recs, counts, dropped = collect(cache)
    if not recs:
        print("old_maps: ничего не собрано.", file=sys.stderr)
        return 1
    report(recs, counts, dropped)
    geo = out_dir / "geojson" / f"{OLD_MAPS.slug}.geojson"
    n = write_geojson(recs, geo, layer_title=OLD_MAPS.title, hoist_shared=True)
    write_jsonl(recs, out_dir / "jsonl" / f"{OLD_MAPS.slug}.jsonl")
    print(f"→ {geo}: {n} на карте "
          f"({geo.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="малая выборка трёх каталогов, разбор")
    ap.add_argument("--fetch", action="store_true", help="полный обход, с продолжением")
    ap.add_argument("--only", choices=("retromap", "slub", "etomesto"),
                    help="с --fetch: только один каталог")
    ap.add_argument("--build", action="store_true", help="записать слой в data/out")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    if not (args.check or args.fetch or args.build):
        ap.error("укажите --check (--probe), --fetch или --build")
    try:
        if args.check and check(args.cache):
            return 1
        if args.fetch and fetch(args.cache, args.only):
            return 1
        return build(args.cache, args.out) if args.build else 0
    except OldMapsError as exc:
        print(f"Старые карты: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
