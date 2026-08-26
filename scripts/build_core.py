#!/usr/bin/env python3
"""Собирает исходные файлы проекта в единый нормализованный массив.

    python3 scripts/build_core.py --raw data/raw --out data/out
    python3 scripts/build_core.py --report-only     # только отчёт, из data/out

Из data/raw и data/curated читаются пять слоёв, которые ведутся вручную.
Остальные собираются своими сборщиками (`harvest*.py`) и к моменту запуска
уже лежат в data/out — они читаются оттуда и попадают в общий массив и в
отчёт. Иначе отчёт описывал бы три процента выгрузки и вводил в заблуждение
ровно там, где он должен предупреждать.

На выходе:
    data/out/geojson/<слой>.geojson   — по файлу на слой для карты
    data/out/jsonl/<слой>.jsonl       — слой целиком, включая записи без точки
    data/out/territorial_events.json  — события без точки: губернии и государство
    data/out/all_layers.xlsx          — все слои, по вкладке на слой
    data/out/context.jsonl            — общий массив для загрузки в базу
    data/out/report.md                — отчёт о качестве всей выгрузки
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.adapters import (  # noqa: E402
    load_battles, load_literary_places, load_prokudin_gorsky, load_state_events, load_tenishev,
)
from histctx.adapters.battles import BATTLES  # noqa: E402
from histctx.adapters.bookplaces import LITERARY, TENISHEV  # noqa: E402
from histctx.adapters.prokudin_gorsky import PROKUDIN  # noqa: E402
from histctx.adapters.state_events import STATE_EVENTS  # noqa: E402
from histctx.geo import extract_region  # noqa: E402
from histctx.io_formats import (  # noqa: E402
    read_layers, write_geojson, write_jsonl, write_records_json, write_xlsx_multi,
)
from histctx.registry import ALL_LAYERS, BY_SLUG  # noqa: E402
from histctx.schema import GROUPS, ContextRecord, LayerSpec  # noqa: E402
from histctx.sources.wikidata import OPEN_END_YEAR  # noqa: E402

# Какой файл каким адаптером читать. Имена ищутся подстрокой, чтобы работали
# и «bookplaces_data.xlsx», и выгрузка с префиксом.
SOURCES = [
    ("bookplaces", LITERARY, load_literary_places),
    ("bookplaces", TENISHEV, load_tenishev),
    ("battles", BATTLES, load_battles),
    ("prokudin", PROKUDIN, load_prokudin_gorsky),
]


def find_file(raw_dir: Path, needle: str) -> Path | None:
    hits = sorted(p for p in raw_dir.glob("*.xlsx") if needle in p.name.lower())
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--curated", type=Path, default=ROOT / "data" / "curated",
                    help="подборки, которые ведутся вручную и лежат в репозитории")
    ap.add_argument("--report-only", action="store_true",
                    help="не пересобирать слои, только перечитать data/out и переписать отчёт")
    args = ap.parse_args()

    if args.report_only:
        return report_only(args.out)

    if not args.raw.is_dir():
        print(f"Нет каталога с исходными файлами: {args.raw}", file=sys.stderr)
        return 1

    layers: dict[str, list] = {}
    specs: dict[str, LayerSpec] = {}
    missing: list[str] = []

    # Территориальные события лежат в самом репозитории: их не выгрузишь
    # запросом, и xlsx для них не нужен.
    events_path = args.curated / "state_events.json"
    if events_path.exists():
        records = load_state_events(events_path)
        layers[STATE_EVENTS.slug] = records
        specs[STATE_EVENTS.slug] = STATE_EVENTS
        print(f"  {STATE_EVENTS.title}: {len(records)} записей  <- {events_path.name}")
    else:
        missing.append(f"{STATE_EVENTS.title} (ожидался файл {events_path})")

    for needle, spec, loader in SOURCES:
        path = find_file(args.raw, needle)
        if path is None:
            missing.append(f"{spec.title} (ожидался файл *{needle}*.xlsx)")
            continue
        records = loader(path)
        layers[spec.slug] = records
        specs[spec.slug] = spec
        print(f"  {spec.title}: {len(records)} записей  <- {path.name}")

    if missing:
        for m in missing:
            print(f"  ПРОПУЩЕН: {m}", file=sys.stderr)
    if not layers:
        print("Не найдено ни одного исходного файла.", file=sys.stderr)
        return 1

    geo_dir = args.out / "geojson"
    total_features = 0
    territorial: list = []
    for slug, records in layers.items():
        # Слой целиком — как у любого сборщика: в geojson попадает не всё,
        # а без jsonl записи без координаты остались бы только в общем файле,
        # и отчёт по одной выгрузке их бы не увидел.
        write_jsonl(records, args.out / "jsonl" / f"{slug}.jsonl")
        # На карту отдаём только то, что реально можно показать.
        mappable = [r for r in records if r.has_point and r.confidence != "not_an_event"]
        territorial += [r for r in records if not r.has_point and r.is_territorial]
        if not mappable:
            continue
        n = write_geojson(mappable, geo_dir / f"{slug}.geojson", layer_title=specs[slug].title)
        total_features += n
        print(f"  geojson/{slug}.geojson: {n} точек")

    if territorial:
        # У этих событий нет геометрии, поэтому в GeoJSON им места нет:
        # на карте они показываются лентой времени, а не точками.
        # Пишутся только свои: чужие слои свою выгрузку ведут сами.
        write_records_json(territorial, args.out / "territorial_events.json",
                           title="События без точки: губернии и государство")
        print(f"  territorial_events.json: {len(territorial)} событий без точки")

    own = [r for recs in layers.values() for r in recs]
    # Остальные слои уже собраны своими сборщиками. Читаем их из data/out —
    # свои записи при этом придут второй раз, через только что написанный
    # geojson, и отсеиваются по uid.
    before = len(layers)
    harvested = add_harvested(layers, specs, args.out, skip={r.uid for r in own})
    if harvested:
        print(f"  из {args.out}: {harvested} записей в {len(layers) - before} уже собранных слоях")

    all_records = [r for recs in layers.values() for r in recs]
    write_jsonl(all_records, args.out / "context.jsonl")
    counts = write_xlsx_multi({specs[s].title: r for s, r in layers.items()}, args.out / "all_layers.xlsx")

    write_report(layers, specs, args.out)

    print(f"\nВсего записей: {len(all_records)}, точек на карте: {total_features}, "
          f"событий без точки: {len(territorial)}")
    print(f"XLSX: {sum(counts.values())} строк на {len(counts)} вкладках")
    print(f"Отчёт: {args.out / 'report.md'}")
    return 0


def report_only(out_dir: Path) -> int:
    """Переписывает отчёт по тому, что лежит в data/out, ничего не пересобирая.

    Нужен, когда исходных xlsx под рукой нет, а слои собраны: отчёт должен
    описывать выгрузку, а не то, что удалось прочитать из data/raw.
    """
    layers: dict[str, list] = {}
    specs: dict[str, LayerSpec] = {}
    n = add_harvested(layers, specs, out_dir, skip=set())
    if not n:
        print(f"В {out_dir} нет собранных слоёв.", file=sys.stderr)
        return 1
    write_report(layers, specs, out_dir)
    print(f"Прочитано {n} записей в {len(layers)} слоях из {out_dir}")
    print(f"Отчёт: {out_dir / 'report.md'}")
    return 0


def add_harvested(layers: dict, specs: dict, out_dir: Path, *, skip: set[str]) -> int:
    """Добавляет к слоям то, что уже собрано и лежит в out_dir.

    Записи с совпавшим `uid` не схлопываются: у пяти материалов бюро Тенишева
    идентификатор совпадает при разном содержании, и молча оставить одну —
    ровно то, чего проект не делает. Повтором считается только буквально та
    же строка, пришедшая вторым файлом (слой лежит и в `geojson/`, и в `jsonl/`).
    """
    seen: dict[str, set] = {}
    added = 0
    for rec in read_layers(out_dir, dedupe=False):
        if rec.uid in skip:
            continue
        key = tuple(sorted((k, _hashable(v)) for k, v in rec.to_row().items()))
        if key in seen.setdefault(rec.uid, set()):
            continue
        seen[rec.uid].add(key)
        layers.setdefault(rec.layer, []).append(rec)
        specs.setdefault(rec.layer, BY_SLUG.get(rec.layer) or _spec_from_record(rec))
        added += 1
    return added


def _hashable(value):
    """Значение поля в виде, пригодном для сравнения строк из разных файлов.

    Координаты в GeoJSON округлены до шести знаков, а в JSONL лежат как есть,
    и без округления одна и та же запись, прочитанная из обоих файлов,
    считалась бы двумя разными.
    """
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, float):
        return round(value, 6)
    return value


def _spec_from_record(rec: ContextRecord) -> LayerSpec:
    """Описание слоя по самой записи — на случай, если в реестре его ещё нет."""
    return LayerSpec(slug=rec.layer, title=rec.layer_title or rec.layer, group=rec.group,
                     source=rec.source or "", license=rec.license or "", status="harvested")


def write_report(layers: dict, specs: dict, out_dir: Path) -> None:
    (out_dir / "report.md").write_text(build_report(layers, specs), encoding="utf-8")


# Порядок групп в отчёте: сначала то, что ищут чаще.
GROUP_ORDER = ["state", "admin", "faith", "hardship", "economy", "military", "culture"]

# Почему запись не встанет на карту.
BLOCKERS = {
    "no_coords": "нет координат — точка не встанет на карту",
    "outside_bbox": "координаты вне территории РИ/СССР — вероятно, не наш контекст",
    "not_an_event": "это воинская часть или корабль, а не событие на местности",
    "no_period": "не разобрана датировка — запись не участвует в подборе по времени",
}

# Оговорки: запись показывается, но чем-то ненадёжна. Формулировки — из
# сборщиков, которые эти пометки ставят.
MARKS = {
    "place_level": "координата указывает на населённый пункт, а не на само место события",
    "grid_edge": "узел реконструкции засух на краю сетки — с одной стороны от него данных нет",
    "thin_coverage": "погодный год, за который говорит одна станция губернии",
    "unpublished_source": "карточка «Карты ГУЛАГа» не опубликована — по составу полей не хуже, но не проверена",
    "region_unmatched": "составное название губернии не сводится к ключу: величина верна, привязка по названию ненадёжна",
    "dates_disputed": "источник даёт два разных года одного переименования; обе записи оставлены",
}

PRECISION_RU = {
    "day": "до дня", "month": "до месяца", "season": "до сезона", "year": "до года",
    "decade": "до десятилетия", "part": "часть века или открытый срок",
    "century": "век целиком", "era": "именованная эпоха", "unknown": "не определена",
}


def build_report(layers: dict, specs: dict) -> str:
    lines = ["# Отчёт о качестве данных", ""]
    lines.append("Пересобирается скриптом `scripts/build_core.py`; только отчёт, "
                 "без пересборки слоёв — `--report-only`.")
    lines.append("")
    lines.append(f"Всего слоёв: {len(layers)}. Числа посчитаны по тому, что лежит "
                 "в `data/out`, а не по оценкам каталога.")
    lines.append("")
    lines.append("| Слой | Записей | С координатами | С датировкой | Годно для подбора |")
    lines.append("|---|---:|---:|---:|---:|")

    grand = Counter()
    for group in _groups_in_order(layers, specs):
        in_group = sorted((s for s in layers if specs[s].group == group),
                          key=lambda s: -len(layers[s]))
        lines.append(f"| **{GROUPS.get(group, group or 'без группы')}** | | | | |")
        for slug in in_group:
            records = layers[slug]
            n = len(records)
            pts = sum(1 for r in records if r.has_point)
            tm = sum(1 for r in records if r.has_time)
            ok = sum(1 for r in records
                     if r.usable and r.confidence not in {"not_an_event", "outside_bbox"})
            grand["n"] += n
            grand["pts"] += pts
            grand["tm"] += tm
            grand["ok"] += ok
            # Территориальному событию координаты не нужны — прочерк вместо нуля,
            # иначе слой выглядит сломанным.
            coords = ("—" if pts == 0 and all(r.is_territorial for r in records)
                      else f"{pts} ({_pct(pts, n)})")
            lines.append(f"| {specs[slug].title} | {n} | {coords} | "
                         f"{tm} ({_pct(tm, n)}) | {ok} ({_pct(ok, n)}) |")
    lines.append(f"| **Итого** | **{grand['n']}** | **{grand['pts']}** "
                 f"| **{grand['tm']}** | **{grand['ok']}** |")
    lines.append("")

    territorial = [r for records in layers.values() for r in records if r.is_territorial]
    if territorial:
        lines.append("## События без точки")
        lines.append("")
        lines.append(f"Всего {len(territorial)}: подбираются по губернии и годам, а не по расстоянию.")
        lines.append("")
        by_scope = Counter(r.scope for r in territorial)
        lines.append(f"- на всё государство: {by_scope.get('state', 0)}")
        lines.append(f"- на названные губернии: {by_scope.get('region', 0)}")
        named = sorted({name for r in territorial for name in r.regions})
        lines.append(f"- различных губерний и областей в перечнях: {len(named)}")
        lines.append("")
        by_layer = Counter(r.layer_title or r.layer for r in territorial)
        for title, cnt in by_layer.most_common():
            lines.append(f"- {title}: {cnt}")
        lines.append("")

    problems = Counter()
    marks = Counter()
    for records in layers.values():
        for r in records:
            if r.confidence in MARKS:
                marks[r.confidence] += 1
            elif not r.is_territorial and r.confidence != "ok":
                problems[r.confidence] += 1
            if not r.has_time:
                problems["no_period"] += 1

    lines.append("## Что мешает показу на карте")
    lines.append("")
    for key, cnt in problems.most_common():
        lines.append(f"- **{cnt}** — {BLOCKERS.get(key, key)}")
    lines.append("")

    if marks:
        lines.append("## Пометки о надёжности")
        lines.append("")
        lines.append("Эти записи показываются, но с оговоркой. Ничего не удаляется "
                     "молча: сомнение записано в поле `confidence` и остаётся в выгрузке.")
        lines.append("")
        for key, cnt in marks.most_common():
            lines.append(f"- **{cnt}** — {MARKS[key]}")
        lines.append("")

    lines.append("## Точность датировок")
    lines.append("")
    prec = Counter(r.date_precision for records in layers.values() for r in records)
    for key, cnt in prec.most_common():
        lines.append(f"- {PRECISION_RU.get(key, key)}: {cnt}")
    lines.append("")
    open_ended = sum(1 for records in layers.values() for r in records
                     if r.date_precision == "part" and r.year_to == OPEN_END_YEAR
                     and r.year_from != r.year_to)
    if open_ended:
        lines.append(f"Из них {open_ended} — открытый срок: у объекта известен год "
                     f"основания, а конца нет, и он растянут до {OPEN_END_YEAR} года, "
                     "чтобы объект не выпал из подбора. Это не измеренная датировка, "
                     "и при ранжировании такая запись понижается наравне с «19 в.».")
        lines.append("")

    lines.append("## Покрытие по территориям")
    lines.append("")
    historical = Counter()
    modern = Counter()
    for records in layers.values():
        for r in records:
            for name in filter(None, [r.region, *r.regions]):
                (historical if extract_region(name) else modern)[name] += 1
    lines.append(f"Территория названа у {sum(historical.values()) + sum(modern.values())} "
                 f"записей. Из них губерния, область, край или округ — "
                 f"{sum(historical.values())} записей, различных единиц: {len(historical)}.")
    lines.append("")
    for region, cnt in historical.most_common(15):
        lines.append(f"- {region}: {cnt}")
    lines.append("")
    if modern:
        lines.append(f"Ещё {sum(modern.values())} записей ({len(modern)} различных названий) "
                     "привязаны к нынешней единице — району, гмине, повяту, муниципалитету: "
                     "в Викиданных у объекта стоит сегодняшнее подчинение, а не то, что "
                     "было в год постройки. Для подбора по губернии такая привязка "
                     "не работает, и перевод её в историческую единицу — отдельная работа.")
        lines.append("")

    lines.append("## На каких правах")
    lines.append("")
    lines.append("Права записаны так, как их сформулировал источник: невыясненные "
                 "не отклоняют слой, а очерчивают, что из него берётся.")
    lines.append("")
    licenses = Counter()
    for records in layers.values():
        for r in records:
            licenses[(r.license or "права не выяснены").split(";")[0].strip()] += 1
    for name, cnt in licenses.most_common():
        lines.append(f"- {name}: {cnt}")
    lines.append("")

    collisions = _uid_collisions(layers)
    if collisions:
        lines.append("## Совпавшие идентификаторы")
        lines.append("")
        lines.append("Разные записи, у которых совпал `uid`: он считается по слою, "
                     "названию, координате и году, и различить записи, у которых "
                     "всё это одинаково, не может. Обе остаются в выгрузке, но "
                     "загрузка в базу по ключу `uid` потеряет одну из них.")
        lines.append("")
        for title, cnt in collisions.most_common():
            lines.append(f"- {title}: {cnt}")
        lines.append("")

    empty = _registry_gaps(layers)
    if empty:
        lines.append("## Чего в выгрузке нет")
        lines.append("")
        lines.append("Слои, которые реестр считает собранными, но записей от них "
                     "в `data/out` не пришло: сбор не запускался, либо его выгрузка "
                     "в репозиторий не идёт (`data/out/jsonl/`).")
        lines.append("")
        for spec in empty:
            lines.append(f"- {spec.title} (`{spec.slug}`)"
                         + (f" — ожидалось около {spec.expected_rows}" if spec.expected_rows else ""))
        lines.append("")

    return "\n".join(lines)


def _groups_in_order(layers: dict, specs: dict) -> list[str]:
    present = {specs[s].group for s in layers}
    ordered = [g for g in GROUP_ORDER if g in present]
    return ordered + sorted(present - set(ordered), key=str)


def _uid_collisions(layers: dict) -> Counter:
    """Слои, в которых один `uid` достался нескольким разным записям."""
    out = Counter()
    for slug, records in layers.items():
        repeats = len(records) - len({r.uid for r in records})
        if repeats:
            out[records[0].layer_title or slug] = repeats
    return out


def _registry_gaps(layers: dict) -> list:
    """Слои реестра, от которых записей не пришло вовсе."""
    return [spec for spec in ALL_LAYERS
            if spec.status in {"curated", "harvested"}
            and spec.gives_records and spec.slug not in layers]


def _pct(part: int, total: int) -> str:
    return "0%" if not total else f"{100 * part / total:.0f}%"


if __name__ == "__main__":
    raise SystemExit(main())
