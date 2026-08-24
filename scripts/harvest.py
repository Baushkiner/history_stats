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
    COUNTRIES, HISTORICAL_COUNTRIES, WORLD, SparqlClient, SparqlError,
    collect_layer, rows_to_records, verify_qids,
)

QUERY_DIR = ROOT / "queries"

# Способы сбора, идущие в две ступени: запрос строит движок, тело файла не
# используется. Различаются только первой ступенью — см. `layer_countries`.
TWO_STAGE = ("country", "class")

# Все допустимые значения @scope. Список закрытый: см. проверку в parse_query.
SCOPES = TWO_STAGE + ("box",)

# Сколько объектов берёт проба. Сервис ограничивает частоту обращений, а
# полная проба крупного слоя — это двенадцать чанков подряд, то есть цена
# самого сбора. Тысячи хватает, чтобы увидеть, что разбор работает.
PROBE_OBJECTS = 1000
# Значение необязательно (`\s*`, а не `\s+`) нарочно: директива без значения
# — `# @owner` — иначе была бы неотличима от обычного комментария и пропала
# бы молча. Так она доходит до проверки заголовка пустой строкой и там же
# получает жалобу.
_RE_META = re.compile(r"^#\s*@(\w+)\s*(.*)$")


def parse_query(path: Path) -> dict:
    """Читает .rq вместе с заголовочными директивами @layer/@title/@qid.

    Директивы:
      @layer   машинный код слоя (по умолчанию — имя файла);
      @title   название слоя;
      @qid     Q-номер класса и его русское название, можно повторять.
               При `@scope country` и `@scope class` эти же классы
               и собираются;
      @kind    `event` — слой событий, даты берутся из P580/P582/P585;
      @scope   `country` — сбор в две ступени по государствам-преемникам,
               запрос строится движком, тело файла не используется;
               `class` — те же две ступени, но первая идёт без разделения
               по государствам: для узких классов отбор ведёт сам класс;
               `box` (по умолчанию) — старый способ, тело файла выполняется
               как есть;
      @filter  дополнительная строка условия для первой ступени,
               можно повторять. Только при `@scope country` и `@scope class`;
      @owner   `P127` — добавить владельца в поле «действующее лицо».
               Только при `@scope country`, см. пояснение в
               `sources/wikidata.py` и в `queries/estates.rq`.
    """
    meta: dict = {"qids": [], "filters": [], "path": path}
    body: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _RE_META.match(line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            if key == "qid":
                qid, _, label = value.partition(" ")
                meta["qids"].append((qid.strip(), label.strip()))
            elif key == "filter":
                meta["filters"].append(value)
            else:
                meta[key] = value
        elif not line.startswith("#"):
            body.append(line)
    meta["sparql"] = "\n".join(body).strip()
    meta.setdefault("layer", path.stem)
    meta.setdefault("title", path.stem)
    # @kind event — слой событий: открытая дата не дотягивается до 1960 года.
    meta.setdefault("kind", "object")
    # @scope country и class — сбор в две ступени; см. sources/wikidata.py.
    meta.setdefault("scope", "box")
    if meta["scope"] not in SCOPES:
        # Опечатка в директиве иначе тихо откатывает слой к телу файла, а тело
        # у переведённых слоёв оставлено ручным вариантом на малой рамке —
        # получился бы правдоподобный, но неверный сбор вместо ошибки.
        raise ValueError(
            f"{path.name}: неизвестный @scope «{meta['scope']}», "
            f"допустимы {', '.join(SCOPES)}")
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
        # Директивы сверяются здесь же, а не при сборе: `--check` — это тот
        # самый проверочный первый запуск из docs/HARVEST.md, и он обязан
        # ловить описку в заголовке до того, как начнётся обход стран.
        for line in check_directives(meta):
            print(line)
            ok = False
    print()
    return ok


def layer_countries(meta: dict, countries: tuple = COUNTRIES) -> tuple:
    """По каким государствам идёт первая ступень.

    При `@scope class` — ни по каким: условие по P17 из запроса выпадает.
    Это нужно слоям, где отбор по нынешнему государству мимо цели: у
    исторической единицы деления P17 указывает на Российскую империю или
    СССР, а то и вовсе не указан.
    """
    return WORLD if meta["scope"] == "class" else countries
def check_directives(meta: dict) -> list[str]:
    """Проверяет директивы заголовка, кроме `@qid`. Возвращает жалобы."""
    bad = []
    owner = meta.get("owner")
    if owner is not None:
        # Пустая строка — директива без значения (`# @owner`). Такая строка
        # не должна проходить молча: слой собрался бы без владельцев, а
        # пустое поле читается как «в Викиданных владелец не указан».
        if owner != "P127":
            bad.append(f"  [НЕ ТО]    @owner понимает только P127, а не «{owner}»"
                       f"  ({meta['layer']})")
        elif meta["scope"] != "country":
            # При `@scope box` тело файла выполняется как есть, и движок в
            # запрос ничего не добавляет: директива не сработала бы.
            bad.append(f"  [НЕ ТАМ]   @owner работает только при @scope country"
                       f"  ({meta['layer']})")
    return bad


def collect(client: SparqlClient, meta: dict, spec: LayerSpec, *,
            paged: bool, page_size: int,
            countries: tuple = COUNTRIES,
            history: tuple = (),
            max_objects: int = None) -> list:
    """Собирает записи слоя — тем способом, который объявлен в `@scope`."""
    classes = [qid for qid, _ in meta["qids"]]
    # Заголовок уже проверен `check_queries`, и сбор сюда не дошёл бы, если
    # проверка не прошла. Здесь остаётся страховка на прямой вызов.
    bad = check_directives(meta)
    if bad:
        raise SparqlError(f"{meta['layer']}: {'; '.join(s.strip() for s in bad)}")
    if meta["scope"] in TWO_STAGE:
        if not classes:
            raise SparqlError(
                f"{meta['layer']}: при @scope {meta['scope']} нужен хотя бы один "
                "@qid — именно эти классы и собираются")
        return collect_layer(
            client, classes, spec,
            kind=meta["kind"], countries=layer_countries(meta, countries),
            history=history,
            extra=meta["filters"], with_owner=bool(meta.get("owner")),
            max_objects=max_objects, progress=print,
        )

    if max_objects is not None:
        # Проба на непереведённом слое. Тело такого файла отбирает объекты
        # географической рамкой, и целиком оно не выполняется — именно из-за
        # этого слои и переводятся на @scope country. Без LIMIT проба тут не
        # экономит ничего: она повторяет тот самый запрос, который падает.
        rows = client.query(f"{meta['sparql']}\nLIMIT {max_objects}")
    elif paged:
        rows = list(client.query_paged(meta["sparql"], page_size=page_size))
    else:
        rows = client.query(meta["sparql"])
    print(f"  получено строк: {len(rows)}")
    return rows_to_records(rows, spec, kind=meta["kind"])


def probe(client: SparqlClient, meta: dict, spec: LayerSpec) -> int:
    """Живая проба: одно государство, файлы не пишутся.

    Нужна до полного сбора. Запрос, который не выполняется или отдаёт пусто,
    должен быть виден сразу, а не через сорок минут обхода семнадцати стран.

    Государство для пробы выбирается по виду слоя. Здания пробуются по
    России, а события — по Российской империи: у события `P17` указывает на
    государство времён события, и проба слоя восстаний по нынешней России
    показала бы пустоту, которая ничего не значит. Обращений к сервису это
    не добавляет — государство по-прежнему одно.

    При `@scope class` сузить пробу нечем: государств в обходе нет, а классы
    объявлены все и каждый нужен. Первая ступень идёт целиком — зато она там
    из коротких запросов (доли секунды на класс), и вторая по-прежнему
    ограничена `PROBE_OBJECTS`.
    """
    one = HISTORICAL_COUNTRIES[:1] if meta["kind"] == "event" else COUNTRIES[:1]
    print(f"Проба слоя «{meta['title']}» ({meta['layer']}), "
          f"способ: {meta['scope']}, государство: {one[0][1]}")
    records = collect(client, meta, spec, paged=False, page_size=5000,
                      countries=one, max_objects=PROBE_OBJECTS)
    print(f"\n  разобрано записей: {len(records)}")
    if not records:
        print(f"  Ничего не разобрано по государству «{one[0][1]}»: проверьте "
              "класс, @scope и @filter. Для слоя событий пусто здесь может "
              "означать и то, что в Викиданных такого просто нет.",
              file=sys.stderr)
        return 1

    dated = sum(1 for r in records if r.has_time)
    with_region = sum(1 for r in records if r.region)
    print(f"  с датировкой: {dated} ({dated * 100 // len(records)}%)")
    print(f"  с губернией или областью: {with_region}")
    # Сколько записей встало на карту по координате места события, а не по
    # собственной: у слоёв событий это и есть разница между слоем и пустотой.
    borrowed = sum(1 for r in records if r.confidence == "place_level")
    if borrowed:
        print(f"  координата взята у места события (P276): {borrowed}")
    print("\n  примеры:")
    for rec in records[:5]:
        years = rec.period_raw or "без даты"
        print(f"    {years:12s}  {rec.lat:7.3f},{rec.lon:8.3f}  {rec.title[:44]}")
    print("\nЗапрос работает — можно запускать сбор.")
    return 0


def harvest(client: SparqlClient, meta: dict, spec: LayerSpec, out_dir: Path,
            paged: bool, page_size: int) -> int:
    print(f"Сбор слоя «{meta['title']}» ({meta['layer']})…")
    # У события P17 указывает на государство времён события, а не на нынешнее,
    # поэтому слои событий обходят ещё и исторические государства. Проба этого
    # не делает намеренно: она стоит два обращения к сервису, и так и должно
    # остаться.
    records = collect(client, meta, spec, paged=paged, page_size=page_size,
                      history=HISTORICAL_COUNTRIES if meta["kind"] == "event" else ())
    print(f"  с координатами в границах РИ/СССР: {len(records)}")
    dated = sum(1 for r in records if r.has_time)
    print(f"  с датировкой: {dated}")

    if not records:
        # Ошибка на отдельном государстве или чанке сбор не отменяет — иначе
        # одна осечка сервиса стоила бы всего слоя. Но пустой результат может
        # означать и то, что не прошло вообще ничего, а запись пустого слоя
        # затрёт прошлую удачную выгрузку. Молча подменять данные пустотой
        # нельзя: файлы остаются как были.
        print(f"  ПУСТО — файлы {spec.slug}.* не перезаписаны "
              f"(прошлая выгрузка сохранена)", file=sys.stderr)
        return 0

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
    ap.add_argument("--probe", action="store_true",
                    help="живая проба по одному государству (при @scope class — "
                         "по всем классам), без записи файлов")
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
    elif not args.all and not args.check and not args.probe:
        ap.error("укажите --layer <слой>, --all, --check или --probe")

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

    if args.probe:
        code = 0
        for meta in metas:
            spec = BY_SLUG.get(meta["layer"])
            if spec is None:
                print(f"  слой {meta['layer']} не описан в registry.py — пропускаю",
                      file=sys.stderr)
                continue
            try:
                code |= probe(client, meta, spec)
            except SparqlError as exc:
                print(f"  ОШИБКА при пробе {meta['layer']}: {exc}", file=sys.stderr)
                code = 1
        return code

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
