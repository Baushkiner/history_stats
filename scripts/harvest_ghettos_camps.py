#!/usr/bin/env python3
"""Сбор слоя гетто, лагерей и мест заключения: карта USHMM, перечни ZRBG и BEG.

    python3 scripts/harvest_ghettos_camps.py --check    # живой запрос, разбор, сведение, без записи
    python3 scripts/harvest_ghettos_camps.py --build    # записи в data/out

Проверочный первый запуск обязателен, как у остальных сборщиков. `--check`
(он же `--probe`) читает `robots.txt` трёх сайтов (закрытое не запрашивается),
заново скачивает пять томов карты «Энциклопедии лагерей и гетто» USHMM
(`muse.jhu.edu/ushmm/map?json=vol_N.json`), перечень гетто ZRBG
(PDF на `aviv.org.il`, размер и md5 сверяются) и перечень концлагерей по
§ 42 BEG (XML-архив на `gesetze-im-internet.de`, тоже со сверкой), сверяет
число мест в томах, записей ZRBG и BEG с замером 04.11.2026, разбирает,
сводит и печатает, что пришло и что получилось. Расхождение — остановка, а не
подгонка: карту дополнили или перечень переиздали, и прежде чем собирать,
надо понять, что изменилось. Файлов слоя `--check` не пишет.

`--build` собирает слой из кэша (недостающее докачивает) и пишет:

* `geojson/ghettos_camps.geojson` — записи с точкой, в том числе вне рамки
  РИ/СССР (`outside_bbox`);
* `ghettos_camps.json` — записи без точки (места BEG и ZRBG, которых нет на
  карте и которым не нашлось места в GeoNames);
* `jsonl/ghettos_camps.jsonl` — слой целиком (в `.gitignore`).

Нужны: `pdftotext` (poppler-utils) и `pypdf` (`python3 -m pip install pypdf`)
— только для таблицы ZRBG; из проекта — `geojson/settlements.geojson` и
`name_variants.json` (GeoNames), `geojson/occupation_cities.geojson` (рамка
оккупации городов) и полигоны рамки в `boundaries/`. Скачанное лежит в
`data/raw/ghettos_camps/`.

Права. Карта USHMM — CC BY-NC-ND 4.0: берутся название, тип, точка и ссылка
на карту, тексты статей не копируются. Перечень ZRBG — права не выяснены:
место и даты со ссылкой, примечания составителей не копируются. Перечень BEG
— официальный текст закона (§ 5 UrhG). Имён людей в слое нет.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from pathlib import Path

from _paths import ROOT

from histctx.frame import Frame
from histctx.io_formats import write_geojson, write_jsonl, write_records_json
from histctx.net import RETRY_CODES, USER_AGENT, wait_for_pause
from histctx.sources import beg_camps, ushmm, zrbg
from histctx.sources.ghettos_camps import (
    GHETTOS_CAMPS, build_records, load_cities, load_geonames, summary_counts,
)

CACHE = ROOT / "data" / "raw" / "ghettos_camps"
OUT = ROOT / "data" / "out"
SETTLEMENTS = OUT / "geojson" / "settlements.geojson"
VARIANTS = OUT / "name_variants.json"
OCCUPATION = OUT / "geojson" / "occupation_cities.geojson"
BOUNDARIES = OUT / "boundaries"

# Между запросами к одному сайту. Crawl-delay ни один из трёх не просит;
# пауза — вежливость: к карте USHMM идёт шесть запросов подряд.
PAUSE = 2.0


class HarvestError(RuntimeError):
    """Сбор остановлен: сайт не ответил, файл не тот, формат поменялся."""


# --- сеть ---------------------------------------------------------------------

class Client:
    """Запросы с подписью проекта, повтором на 429/5xx и паузой; robots.txt — первым."""

    def __init__(self, pause: float = PAUSE, retries: int = 3, timeout: int = 120) -> None:
        self.pause, self.retries, self.timeout = pause, retries, timeout
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def get(self, url: str) -> bytes:
        host = urllib.parse.urlparse(url).netloc
        for attempt in range(self.retries + 1):
            self._last[host] = wait_for_pause(self._last.get(host, 0.0), self.pause)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_CODES and attempt < self.retries:
                    time.sleep(self.pause * (attempt + 1))
                    continue
                raise HarvestError(f"{url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(self.pause * (attempt + 1))
                    continue
                raise HarvestError(f"{url}: сеть недоступна ({getattr(exc, 'reason', exc)})") \
                    from exc
        raise HarvestError(f"{url}: не ответил за {self.retries + 1} попыток")

    def allowed(self, url: str, robots_url: str) -> bool:
        parser = self._robots.get(robots_url)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser(robots_url)
            parser.parse(self.get(robots_url).decode("utf-8", "replace").splitlines())
            self._robots[robots_url] = parser
            delay = parser.crawl_delay(USER_AGENT)
            if delay:
                self.pause = max(self.pause, float(delay))
        return parser.can_fetch(USER_AGENT, url)

    def fetch(self, url: str, robots_url: str) -> bytes:
        if not self.allowed(url, robots_url):
            raise HarvestError(f"robots.txt закрывает {url}: сбор не идёт")
        return self.get(url)


def cached(client: Client, path: Path, url: str, robots_url: str, *, refresh: bool,
           check=None) -> bytes:
    """Файл из кэша или из сети; в кэш пишется только целый и проверенный ответ."""
    if path.exists() and not refresh:
        return path.read_bytes()
    data = client.fetch(url, robots_url)
    if check:
        check(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


def _pinned(name: str, size: int, md5: str):
    def check(data: bytes) -> None:
        got = hashlib.md5(data).hexdigest()
        if len(data) != size or got != md5:
            raise HarvestError(f"{name}: пришло {len(data)} байт, md5 {got}; ожидалось {size} "
                               f"байт, md5 {md5} — файл переиздан, сверьте и поправьте модуль")
    return check


# --- источники ------------------------------------------------------------------

def load_ushmm(client: Client, cache: Path, *, refresh: bool) -> tuple[list, list]:
    places, problems = [], []
    for v in ushmm.VOLUMES:
        raw = cached(client, cache / f"ushmm_vol_{v}.json", ushmm.JSON_URL.format(volume=v),
                     ushmm.ROBOTS_URL, refresh=refresh)
        got, probs = ushmm.parse_volume(raw, v)
        places += got
        problems += probs
    counts = collections.Counter(p.volume for p in places)
    differ = {v: (counts.get(v, 0), n) for v, n in ushmm.EXPECTED_PLACES.items()
              if counts.get(v, 0) != n}
    if differ:
        raise HarvestError("число мест в томах карты разошлось с замером 04.11.2026 "
                           "(том: пришло, ожидалось): " + str(differ)
                           + " — карту дополнили; посмотрите, что добавилось, и поправьте "
                           "ushmm.EXPECTED_PLACES")
    return places, problems


def load_zrbg(client: Client, cache: Path, *, refresh: bool) -> tuple[list, list]:
    path = cache / zrbg.CACHE_NAME
    cached(client, path, zrbg.PDF_URL, zrbg.ROBOTS_URL, refresh=refresh,
           check=_pinned("перечень ZRBG", zrbg.PDF_SIZE, zrbg.PDF_MD5))
    try:
        tables, loose = zrbg.read_tables(path)
    except zrbg.ZrbgError as exc:
        raise HarvestError(f"перечень ZRBG: {exc}") from exc
    problems = zrbg.check_header(tables)
    if problems:
        raise HarvestError("заголовок таблицы ZRBG не тот:\n  " + "\n  ".join(problems[:10]))
    raws = zrbg.table_entries(tables)
    if len(raws) != zrbg.EXPECTED_ENTRIES:
        raise HarvestError(f"записей ZRBG {len(raws)}, а не {zrbg.EXPECTED_ENTRIES} — "
                           "разбор сетки разошёлся с замером: сначала понять, что изменилось")
    return [zrbg.parse_entry(r) for r in raws], loose


def load_beg(client: Client, cache: Path, *, refresh: bool) -> tuple[list, str]:
    path = cache / beg_camps.CACHE_NAME
    cached(client, path, beg_camps.XML_URL, beg_camps.ROBOTS_URL, refresh=refresh,
           check=_pinned("перечень BEG", beg_camps.ZIP_SIZE, beg_camps.ZIP_MD5))
    with zipfile.ZipFile(path) as zf:
        if beg_camps.XML_NAME not in zf.namelist():
            raise HarvestError(f"в архиве нет {beg_camps.XML_NAME}: {zf.namelist()}")
        xml = zf.read(beg_camps.XML_NAME)
    try:
        entries = beg_camps.entries(xml)
    except beg_camps.BegError as exc:
        raise HarvestError(f"перечень BEG: {exc}") from exc
    refs = sum(1 for e in entries if e.is_reference)
    if len(entries) != beg_camps.EXPECTED_ENTRIES or refs != beg_camps.EXPECTED_SEE:
        raise HarvestError(f"записей BEG {len(entries)} (отсылок {refs}), а ожидалось "
                           f"{beg_camps.EXPECTED_ENTRIES} ({beg_camps.EXPECTED_SEE})")
    return entries, beg_camps.stand(xml) or ""


def load_helpers():
    for path in (SETTLEMENTS, VARIANTS):
        if not path.exists():
            raise HarvestError(f"нет {path.relative_to(ROOT)} — GeoNames нужен для проверки "
                               "точек и мест без пары (scripts/harvest_geonames.py)")
    geo = load_geonames(SETTLEMENTS, VARIANTS)
    cities = load_cities(OCCUPATION)
    if not cities:
        print(f"  нет {OCCUPATION.relative_to(ROOT)}: рамка оккупации городов не подставится, "
              "только рамка территории (scripts/harvest_occupation.py)")
    try:
        frame = Frame.load(BOUNDARIES)
    except (OSError, ValueError) as exc:
        raise HarvestError(f"нет полигонов рамки в {BOUNDARIES.relative_to(ROOT)} ({exc}) — "
                           "scripts/harvest_admin_gis.py и harvest_cshapes.py") from exc
    return geo, cities, frame


def collect(client: Client, cache: Path, *, refresh: bool) -> dict:
    places, uproblems = load_ushmm(client, cache, refresh=refresh)
    zentries, loose = load_zrbg(client, cache, refresh=refresh)
    bentries, stand = load_beg(client, cache, refresh=refresh)
    geo, cities, frame = load_helpers()
    built = build_records(places, zentries, bentries, geo_index=geo, cities=cities,
                          frame_place=frame.place)
    return {"places": places, "ushmm_problems": uproblems, "zrbg": zentries,
            "zrbg_loose": loose, "beg": bentries, "beg_stand": stand, "built": built,
            "cities": len(cities)}


# --- отчёт ----------------------------------------------------------------------

def report(got: dict) -> None:
    places = got["places"]
    print(f"\nКарта USHMM: {len(places)} мест")
    for v in ushmm.VOLUMES:
        vs = [p for p in places if p.volume == v]
        ussr = [p for p in vs if p.country in ushmm.FORMER_USSR]
        print(f"  т. {v}: {len(vs)}; на земле бывшего СССР {len(ussr)} — "
              + ", ".join(f"{c} {n}" for c, n in ushmm.counts_by_country(ussr).items()))
    print("  по странам (все тома): " + ", ".join(
        f"{c} {n}" for c, n in list(ushmm.counts_by_country(places).items())[:12]) + " …")
    print(f"  приблизительная точка: {sum(p.approximate for p in places)}; "
          f"без точки: {sum(p.lat is None for p in places)}")
    for line in got["ushmm_problems"][:10]:
        print(f"    {line}")
    missing = ushmm.untranslated(places)
    if missing:
        print("  нет в словаре типов (пойдут по-английски): " + "; ".join(missing))

    z = got["zrbg"]
    print(f"\nПеречень ZRBG: {len(z)} записей; продолжений через перенос страницы "
          f"{sum(e.continued for e in z)}; без номера {sum(1 for e in z if not e.nr)}")
    print(f"  дата открытия есть у {sum(1 for e in z if e.opened)}, ликвидации — у "
          f"{sum(1 for e in z if e.liquidated)}; точность ликвидации: " + ", ".join(
              f"{k} {v}" for k, v in collections.Counter(
                  e.liquidated.precision for e in z if e.liquidated).most_common()))
    print(f"  правовые даты (по распоряжениям): у {sum(1 for e in z if e.rule)}; "
          f"пометки: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(
              k for e in z for k in e.flags).most_common()))
    print(f"  слов вне сетки (шапка, номера страниц): {len(got['zrbg_loose'])}")
    for e in z[:2]:
        print(f"    № {e.nr} {e.name} — {e.territory[:60]}: {e.opened_raw} — {e.liquidated_raw}")

    b = got["beg"]
    camps = [e for e in b if not e.is_reference]
    print(f"\nПеречень BEG ({got['beg_stand']}): {len(b)} записей — мест {len(camps)}, "
          f"отсылок «siehe» {len(b) - len(camps)}; со сроками {sum(1 for e in camps if e.periods)};"
          f" в рамке по тексту {sum(1 for e in camps if e.frame_hint)}")
    for e in [x for x in camps if x.frame_hint][:3]:
        print(f"    № {e.nr} {e.text[:80]} | {e.main_camp or ''}")

    built = got["built"]
    recs = built.records
    print(f"\nСведение. ZRBG: к местам карты {built.zrbg_matched}, без пары "
          f"{len(built.zrbg_unmatched)} (из них отвязано проверкой территории "
          f"{len(built.zrbg_rejected)}), неоднозначно {len(built.zrbg_ambiguous)}")
    print(f"  BEG: к местам т. I {built.beg_matched}, без пары {len(built.beg_unmatched)}, "
          f"неоднозначно {len(built.beg_ambiguous)}")
    how = collections.Counter((r.extra or {}).get("date_match", "").split(",")[0]
                              for r in recs if (r.extra or {}).get("date_match"))
    for k, v in how.most_common():
        print(f"    {v:>5}  {k}")
    print(f"  рамка оккупации городов: {got['cities']} городов из occupation_cities")

    print(f"\nЗаписей: {len(recs)}; с точкой {sum(r.has_point for r in recs)}; "
          f"в рамке РИ/СССР {sum(1 for r in recs if r.confidence != 'outside_bbox')}; "
          f"с губернией 1897 года {sum(1 for r in recs if r.region)}")
    counts = summary_counts(recs)
    for key in ("confidence", "date_source", "precision"):
        print(f"  {key}: " + ", ".join(f"{k} {v}" for k, v in counts[key].most_common()))
    inside = [r for r in recs if r.confidence != "outside_bbox"]
    print("  в рамке — откуда даты: " + ", ".join(
        f"{k} {v}" for k, v in collections.Counter(
            (r.extra or {}).get("date_source") for r in inside).most_common()))
    for r in recs:
        if r.confidence == "coord_suspect":
            far = r.extra.get("geonames_far") or {}
            print(f"    точка под сомнением: {r.title} — {far.get('km')} км от «{far.get('name')}»")
    print("\n  примеры:")
    seen = set()
    for r in recs:
        key = ((r.extra or {}).get("date_source"), r.source_id.split(":")[0])
        if key in seen or r.confidence == "outside_bbox":
            continue
        seen.add(key)
        print(f"    {r.title} [{r.category}] {r.year_from}–{r.year_to} ({r.date_precision})\n"
              f"      {r.summary[:220]}")


# --- команды --------------------------------------------------------------------

def check(cache: Path) -> int:
    client = Client()
    for url, robots in ((ushmm.JSON_URL.format(volume=1), ushmm.ROBOTS_URL),
                        (zrbg.PDF_URL, zrbg.ROBOTS_URL),
                        (beg_camps.XML_URL, beg_camps.ROBOTS_URL)):
        if not client.allowed(url, robots):
            print(f"robots.txt закрывает {url} — сбор остановлен", file=sys.stderr)
            return 1
    print("robots.txt: тома карты USHMM, PDF ZRBG и XML BEG открыты; "
          f"пауза между запросами {client.pause:g} с")
    got = collect(client, cache, refresh=True)
    report(got)
    print("\nФайлы на месте, числа сходятся с замером, разбор и сведение работают — можно "
          "запускать --build.")
    return 0


def build(cache: Path, out_dir: Path) -> int:
    got = collect(Client(), cache, refresh=False)
    records = got["built"].records
    if not records:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    report(got)
    slug = GHETTOS_CAMPS.slug
    geo = out_dir / "geojson" / f"{slug}.geojson"
    n = write_geojson(records, geo, layer_title=GHETTOS_CAMPS.title)
    off_map = [r for r in records if not r.has_point]
    json_path = out_dir / f"{slug}.json"
    if off_map:
        write_records_json(off_map, json_path, title=f"{GHETTOS_CAMPS.title}: без точки")
    else:
        json_path.unlink(missing_ok=True)
    jsonl = out_dir / "jsonl" / f"{slug}.jsonl"
    write_jsonl(records, jsonl)
    print(f"\nСобрано {len(records)} записей: с точкой {n}, без точки {len(off_map)}.")
    for path in (geo, json_path if off_map else None, jsonl):
        if path:
            print(f"  файл: {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} КБ)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--probe", dest="check", action="store_true",
                    help="живой запрос к трём сайтам, сверка чисел, разбор и сведение")
    ap.add_argument("--build", action="store_true", help="собрать слой в файлы")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cache", type=Path, default=CACHE,
                    help="куда класть скачанные тома, PDF и архив")
    args = ap.parse_args()

    if not args.check and not args.build:
        ap.error("укажите --check (--probe) или --build")
    try:
        if args.check:
            code = check(args.cache)
            if code or not args.build:
                return code
        return build(args.cache, args.out)
    except (HarvestError, ushmm.UshmmError) as exc:
        print(f"Сбор остановлен: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
