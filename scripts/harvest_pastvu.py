#!/usr/bin/env python3
"""Сбор слоя старых фотографий из PastVu.

    python3 scripts/harvest_pastvu.py --probe                       # что реально отдаёт API
    python3 scripts/harvest_pastvu.py --estimate --all              # сколько там записей
    python3 scripts/harvest_pastvu.py --bbox 55.5 37.3 56.0 37.9    # один прямоугольник
    python3 scripts/harvest_pastvu.py --all --step 1.0              # вся территория РИ/СССР
    python3 scripts/harvest_pastvu.py --all --step 1.0 --resume     # продолжить прерванный обход
    python3 scripts/harvest_pastvu.py --all --step 1.0 --restart    # начать заново, отложив журнал

Первым запуском стоит делать `--probe`: он печатает сырой ответ сервиса и
останавливается, если обязательных полей нет. Разбор сверен с живым API
23 августа 2026 года, но сверка — не гарантия на завтра.

Обход всей страны — это часы: около 7 800 клеток по градусу и порядка 686 000
записей. Поэтому записи пишутся на диск по мере обхода, а пройденные клетки
отмечаются в журнале: `--resume` продолжает с того места, где оборвалось.
Терять сутки работы из-за одной сетевой ошибки в середине нельзя.

Права: снимки принадлежат их авторам, PastVu — некоммерческий проект.
Собираются метаданные и ссылки на страницы снимков, файлы не копируются.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from _paths import ROOT

from histctx.geo import BBOX_RU, BBOX_RU_EAST
from histctx.io_formats import HOISTABLE, write_jsonl
from histctx.schema import COLUMNS, ContextRecord
from histctx.sources.pastvu import (
    PASTVU_PHOTOS, YEAR_MAX, YEAR_MIN, PastVuClient, PastVuError,
    check_photo_fields, grid, in_requested_bbox, photos_to_records,
)

# Совсем маленький прямоугольник у Иверских ворот в Москве: снимков там
# заведомо много, и проба возвращает содержательный ответ, не выкачивая
# мегабайты ради проверки имён полей.
PROBE_BBOX = (55.7555, 37.6165, 55.7570, 37.6185)

# Журнал обхода лежит в data/cache: он восстанавливается повторным обходом и
# в репозиторий не идёт (каталог уже в .gitignore).
STATE_DIR = ROOT / "data" / "cache" / "pastvu"

# Отметка в конце списка клеток: обход дошёл до конца — все клетки пройдены.
# Без неё законченный обход не отличить от прерванного, и повторный запуск либо
# ругался бы на пустом месте, либо молча выдавал вчерашние данные за сегодняшние.
DONE_MARK = "готово"


def probe(client: PastVuClient, bbox: tuple, year_to: int) -> int:
    print(f"Проба: {bbox}, годы {YEAR_MIN}–{year_to}\n")
    photos = client.photos_in_bbox(bbox, year_to=year_to)
    print(f"  снимков в ответе: {len(photos)}")
    if not photos:
        print("  Пусто. Возможные причины: слишком мелкий прямоугольник, "
              "перепутанный порядок координат в bounds, изменившийся формат запроса.")
        return 1

    print(f"  поля первого снимка: {sorted(photos[0])}")
    print("  сырая запись:")
    print("   ", json.dumps(photos[0], ensure_ascii=False)[:400])
    check_photo_fields(photos)

    records = photos_to_records(photos, require_bbox=False, year_max=year_to)
    print(f"\n  разобрано в записи: {len(records)} из {len(photos)}")
    for rec in records[:5]:
        print(f"    {rec.year_from}–{rec.year_to}  {rec.lat:.5f},{rec.lon:.5f}  "
              f"{rec.title[:60]}  {rec.url}")
    if not records:
        print("  Ни одна запись не разобрана: проверьте поля geo/year в выводе выше.")
        return 1
    print("\nПоля на месте, разбор работает — можно запускать сбор.")
    return 0


def estimate(client: PastVuClient, bboxes: list, *, step: float, year_to: int) -> int:
    """Считает объём по счётчикам кластеров — не выкачивая сами снимки.

    Нужен для честного `expected_rows` и для оценки времени: обход всей страны
    измеряется часами, и знать заранее, сколько там записей, дешевле, чем
    выяснить это на середине.
    """
    # Кластеры считаются крупными плитками: страна целиком одним запросом
    # сервису не по силам (отвечает ApplicationError), а по клетке в градус
    # это были бы тысячи запросов ради одной цифры. Зум под размер плитки
    # подбирает сам клиент.
    tiles = [t for bbox in bboxes for t in grid(bbox, 20.0)]
    print(f"Оценка объёма: {len(tiles)} плиток по счётчикам кластеров, "
          f"годы {YEAR_MIN}–{year_to}")
    total, failed = 0, 0
    for tile in tiles:
        try:
            n = client.count_in_bbox(tile, year_to=year_to)
        except PastVuError as exc:
            failed += 1
            print(f"  {_key(tile)}: ошибка — {exc}", file=sys.stderr)
            continue
        total += n
        if n:
            print(f"  {_key(tile)}: {n}")
    cells = sum(1 for bbox in bboxes for _ in grid(bbox, step))
    print(f"\nВсего снимков в рамке: около {total} — счёт по кластерам, "
          f"он грубее выгрузки на проценты. Плиток с ошибкой: {failed}.")
    print(f"Обход клетками по {step}° — это {cells} запросов; "
          f"при паузе {client.pause_sec} с и ответе за секунду — примерно "
          f"{cells * (client.pause_sec + 1.0) / 3600:.1f} ч.")
    return 0


def harvest(client: PastVuClient, bboxes: list, *, step: float, year_to: int,
            out_dir: Path, state_dir: Path, max_cells: int | None,
            resume: bool, restart: bool) -> int:
    cells = [cell for bbox in bboxes for cell in grid(bbox, step)]
    if max_cells:
        cells = cells[:max_cells]

    journal = Journal(state_dir, bboxes=bboxes, step=step,
                      year_to=year_to, cells=len(cells))
    done, seen, kept = journal.open(resume=resume, restart=restart)
    todo = [c for c in cells if _key(c) not in done]
    print(f"Сбор: {len(cells)} клеток по {step}°, годы {YEAR_MIN}–{year_to}")
    if done:
        print(f"  продолжаем: пройдено {len(done)} клеток, накоплено {kept} записей")

    failed, passed = 0, len(done)
    try:
        for i, cell in enumerate(todo, 1):
            try:
                photos = client.photos_in_bbox(cell, year_to=year_to)
            except PastVuError as exc:
                failed += 1
                print(f"  [{i}/{len(todo)}] ОШИБКА {_key(cell)}: {exc}", file=sys.stderr)
                continue
            # Ответ просеивается по запрошенному прямоугольнику ещё раз: если
            # порядок осей в bounds окажется другим, чужие точки в слой не пройдут.
            photos = [p for p in photos if _inside(p, cell)]
            fresh = [r for r in photos_to_records(photos, year_max=year_to)
                     if r.source_id not in seen]
            for rec in fresh:
                seen.add(rec.source_id)
            # Сначала записи на диск, потом отметка о клетке: если процесс
            # оборвётся между этим, клетка будет пройдена заново, а повтор
            # отсеется по source_id. Обратный порядок потерял бы записи молча.
            kept += journal.write(fresh)
            journal.mark(cell)
            passed += 1
            if i % 20 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] записей: {kept}")
    except KeyboardInterrupt:
        print(f"\nПрервано. Накоплено {kept} записей, пройдено "
              f"{passed} клеток из {len(cells)}. "
              "Продолжить: тот же запуск с ключом --resume.", file=sys.stderr)
        return 130
    except PastVuError as exc:
        # Сюда попадает не сетевая ошибка (та ловится по клетке), а изменившийся
        # формат ответа: продолжать разбор нечем, но собранное уже на диске.
        print(f"\nРазбор остановлен: {exc}\n"
              f"Накоплено {kept} записей, пройдено {passed} клеток из {len(cells)}. "
              "Поправьте разбор и продолжите тем же запуском с ключом --resume.",
              file=sys.stderr)
        return 1
    finally:
        journal.close()

    if not kept and not failed:
        # Рамка пройдена целиком, снимков в ней просто нет. Обход отмечается
        # законченным, иначе каждый следующий --resume натыкался бы на пустой
        # список клеток и снова сообщал об ошибке.
        journal.mark_finished()
        print("Обход закончен: снимков с датировкой в этой рамке нет, слои не собраны.",
              file=sys.stderr)
        return 1
    if not kept:
        print("Ничего не собрано.", file=sys.stderr)
        return 1
    if failed:
        # Слой с дырами хуже, чем несобранный слой: дыру в семистах тысячах
        # точек потом не найдёшь. Записи остались в журнале, обход к этим
        # клеткам вернётся, а собирать выгрузку из неполного журнала можно
        # только осознанно — ключом --finalize.
        print(f"\nКлеток с ошибкой: {failed}. Пройденными они не отмечены, слои не собраны.\n"
              "  повторить эти клетки:      тот же запуск с ключом --resume\n"
              "  собрать как есть, с дырами: --finalize", file=sys.stderr)
        return 1
    code = finalize(journal, out_dir)
    if code == 0:
        # Отметка ставится только здесь: обход дошёл до конца и слои собраны.
        # После `--finalize` посреди обхода её быть не должно — иначе продолжить
        # прерванный обход станет нельзя.
        journal.mark_finished()
    return code


def finalize(journal: "Journal", out_dir: Path) -> int:
    """Сводит накопленное в готовые слои.

    Записи читаются с диска по одной: их сотни тысяч, и держать их все в
    памяти списком объектов незачем.
    """
    # Журнал могли оборвать на полуслове: чиним до чтения, иначе разбор
    # споткнётся о недописанную строку ровно там, где его позвали спасать
    # трёхчасовой обход.
    journal.repair()
    jsonl_path = out_dir / "jsonl" / f"{PASTVU_PHOTOS.slug}.jsonl"
    geojson_path = out_dir / "geojson" / f"{PASTVU_PHOTOS.slug}.geojson"
    n = write_jsonl(journal.records(), jsonl_path)
    mapped = _write_geojson_stream(journal.records, geojson_path,
                                   layer_title=PASTVU_PHOTOS.title)
    print(f"\nСобрано {n} записей, на карту пойдут {mapped}.")
    print(f"  {jsonl_path}\n  {geojson_path}")
    # data/out/geojson отслеживается git, а GitHub не принимает файлы больше
    # 100 МБ. Сказать об этом здесь дешевле, чем упереться в отказ при push.
    mb = geojson_path.stat().st_size / 1024 / 1024
    print(f"  размер слоя: {mb:.0f} МБ" +
          (" — больше 100 МБ, в репозиторий такой файл не примут: "
           "режьте период ключом --year-to или собирайте по областям"
           if mb > 100 else ""))
    return 0


class Journal:
    """Журнал обхода: накопленные записи и список пройденных клеток.

    Обход всей страны — часы и сотни тысяч записей. Держать их в памяти до
    последней клетки значит потерять всё на первой же ошибке, поэтому записи
    ложатся на диск сразу, а клетка отмечается пройденной только после того,
    как её записи записаны.
    """

    def __init__(self, state_dir: Path, *, bboxes: list, step: float,
                 year_to: int, cells: int) -> None:
        self.dir = state_dir
        self.rows_path = state_dir / f"{PASTVU_PHOTOS.slug}.jsonl"
        self.cells_path = state_dir / f"{PASTVU_PHOTOS.slug}.cells"
        self.head = {"bbox": [list(b) for b in bboxes], "step": step,
                     "year_to": year_to, "cells": cells}
        self._rows = None
        self._cells = None

    def open(self, *, resume: bool, restart: bool) -> tuple[set, set, int]:
        self.dir.mkdir(parents=True, exist_ok=True)
        if restart and self._exists():
            self._archive()
        done: set = set()
        seen: set = set()
        kept = 0
        if self._exists():
            if self.is_finished():
                raise SystemExit(
                    f"Обход по журналу в {self.dir} уже завершён.\n"
                    "  пересобрать слои из него: --finalize\n"
                    "  собрать заново:           --restart (журнал будет отложен в сторону, "
                    "а не удалён)"
                )
            if not resume:
                # Ничего не удаляется молча: прошлый обход мог стоить суток.
                raise SystemExit(
                    f"В {self.dir} лежит незаконченный обход.\n"
                    "  продолжить:     --resume\n"
                    "  начать заново:  --restart (журнал будет отложен в сторону)"
                )
            if not self.cells_path.exists():
                # Записи есть, а списка пройденных клеток нет: неизвестно, что
                # уже собрано, и продолжать вслепую значит собрать слой с дырами.
                raise SystemExit(
                    f"В {self.dir} есть накопленные записи, но нет списка пройденных "
                    "клеток — продолжать нельзя, неизвестно, что уже собрано.\n"
                    "  начать заново: --restart (записи будут отложены в сторону)\n"
                    "  собрать слои из того, что есть: --finalize"
                )
            done = self._read_cells()
            seen, kept = self.repair()
        self._rows = self.rows_path.open("a", encoding="utf-8")
        self._cells = self.cells_path.open("a", encoding="utf-8")
        # Заголовок пишется один раз — по пустому файлу, а не по пустому
        # списку клеток: обход мог оборваться на первой же клетке, и второй
        # заголовок потом прочитался бы как пройденная клетка.
        if self.cells_path.stat().st_size == 0:
            self._cells.write(json.dumps(self.head, ensure_ascii=False) + "\n")
            self._cells.flush()
        return done, seen, kept

    def is_finished(self) -> bool:
        """Дошёл ли прошлый обход до конца и собрал ли слои."""
        if not self.cells_path.exists():
            return False
        with self.cells_path.open(encoding="utf-8") as fh:
            return any(line.strip() == DONE_MARK for line in fh)

    def mark_finished(self) -> None:
        with self.cells_path.open("a", encoding="utf-8") as fh:
            fh.write(DONE_MARK + "\n")

    def _exists(self) -> bool:
        return self.cells_path.exists() or self.rows_path.exists()

    def _archive(self) -> None:
        """Откладывает прошлый журнал в сторону — переименованием, не удалением."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for path in (self.rows_path, self.cells_path):
            if not path.exists():
                continue
            # `rename` молча затирает существующий файл, а два перезапуска
            # в одну секунду — обычное дело при отладке. Ищем свободное имя:
            # отложенный журнал не должен исчезать под таким же отложенным.
            moved = path.with_suffix(path.suffix + f".{stamp}")
            n = 2
            while moved.exists():
                moved = path.with_suffix(path.suffix + f".{stamp}-{n}")
                n += 1
            path.rename(moved)
            print(f"  прошлый журнал отложен: {moved}")

    def write(self, records: list) -> int:
        for rec in records:
            row = rec.to_row()
            if rec.extra:
                row["extra"] = rec.extra
            self._rows.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._rows.flush()
        return len(records)

    def mark(self, cell: tuple) -> None:
        self._cells.write(_key(cell) + "\n")
        self._cells.flush()

    def close(self) -> None:
        for fh in (self._rows, self._cells):
            if fh is not None:
                fh.close()
        self._rows = self._cells = None

    def records(self):
        """Читает накопленные строки обратно записями — по одной за раз."""
        with self.rows_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield _record_from_row(json.loads(line))

    def _read_cells(self) -> set:
        with self.cells_path.open(encoding="utf-8") as fh:
            head = fh.readline().strip()
            try:
                stored = json.loads(head)
            except json.JSONDecodeError:
                stored = None
            if stored != self.head:
                raise SystemExit(
                    "Журнал в {} снят с другого обхода:\n  было:  {}\n  сейчас: {}\n"
                    "Продолжать с другой рамкой или другим шагом нельзя — "
                    "получится слой с дырами.".format(
                        self.dir, json.dumps(stored, ensure_ascii=False),
                        json.dumps(self.head, ensure_ascii=False))
                )
            return {line.strip() for line in fh
                    if line.strip() and line.strip() != DONE_MARK}

    def repair(self) -> tuple[set, int]:
        """Восстанавливает накопленное и отрезает оборванный хвост.

        Процесс могли убить в середине строки: недописанная строка сломала бы
        и подсчёт, и итоговую выгрузку. Хвост отбрасывается, а клетка, которой
        он принадлежал, пройденной не отмечена и будет собрана заново.

        Испорченная строка в середине журнала — другое дело: после неё лежат
        целые записи, и обрезать их значило бы потерять собранное молча.
        Такой журнал чинить вслепую нельзя, и обход останавливается.
        """
        seen: set = set()
        if not self.rows_path.exists():
            return seen, 0
        good_end, n = 0, 0
        broken = None
        with self.rows_path.open("rb") as fh:
            for raw in fh:
                if not raw.endswith(b"\n"):
                    broken = raw
                    break
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    broken = raw
                    break
                sid = row.get("source_id")
                if sid is not None:
                    seen.add(str(sid))
                good_end += len(raw)
                n += 1
        if broken is None:
            return seen, n
        if good_end + len(broken) < self.rows_path.stat().st_size:
            raise SystemExit(
                f"Журнал {self.rows_path} испорчен на записи {n + 1}, а после неё "
                "есть ещё записи: обрезать их — потерять собранное. Разберитесь "
                "с файлом вручную или отложите его в сторону ключом --restart."
            )
        print(f"  журнал оборван на записи {n + 1} — хвост отброшен", file=sys.stderr)
        with self.rows_path.open("r+b") as fh:
            fh.truncate(good_end)
        return seen, n


def _write_geojson_stream(records_fn, path: Path, *, layer_title: str) -> int:
    """Тот же FeatureCollection, что и в io_formats, но записью на лету.

    Отдельная реализация нужна из-за объёма: `write_geojson` собирает список
    Feature'ов целиком, а здесь их сотни тысяч.

    Свойства, одинаковые у всех записей (название слоя, источник, права),
    выносятся на уровень коллекции — как в `write_geojson(hoist_shared=True)`
    и в слое населённых мест. На семистах тысячах записей одна только строка
    прав весит больше сотни мегабайт, если повторить её у каждой точки.
    Отсюда два прохода по журналу: сначала выясняем, что общее, потом пишем.
    """
    shared = _shared_layer_props(records_fn())
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {
        "type": "FeatureCollection",
        "name": layer_title or path.stem,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3/CRS84"}},
    }
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(head, ensure_ascii=False)[:-1])
        if shared:
            fh.write(',"layer":' + json.dumps(shared, ensure_ascii=False))
        fh.write(',"features":[')
        for rec in records_fn():
            if not rec.has_point:
                continue
            feat = rec.to_feature()
            for key in shared:
                feat["properties"].pop(key, None)
            fh.write(("," if n else "") +
                     json.dumps(feat, ensure_ascii=False, separators=(",", ":")))
            n += 1
        fh.write("]}")
    return n


def _shared_layer_props(records) -> dict:
    """Значения из HOISTABLE, одинаковые у всех записей — как в io_formats."""
    shared: dict | None = None
    for rec in records:
        row = {k: v for k, v in rec.to_row().items() if v is not None and v != ""}
        current = {k: row[k] for k in HOISTABLE if k in row}
        if shared is None:
            shared = current
        else:
            shared = {k: v for k, v in shared.items() if k in current and current[k] == v}
        if not shared:
            break
    return shared or {}


def _record_from_row(row: dict) -> ContextRecord:
    """Строка выгрузки обратно в запись: поля те же, что пишет `to_row`."""
    data = {k: row.get(k) for k in COLUMNS if row.get(k) is not None}
    regions = data.pop("regions", None)
    return ContextRecord(
        **data,
        regions=[r.strip() for r in str(regions).split(";") if r.strip()] if regions else [],
        extra=row.get("extra") or {},
    )


def _key(cell: tuple) -> str:
    return ",".join(f"{c:.4f}" for c in cell)


def _inside(photo: dict, bbox: tuple) -> bool:
    geo = photo.get("geo")
    if not isinstance(geo, (list, tuple)) or len(geo) != 2:
        return False
    try:
        return in_requested_bbox(float(geo[0]), float(geo[1]), bbox)
    except (TypeError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="один запрос и разбор ответа, без сбора")
    ap.add_argument("--estimate", action="store_true",
                    help="сосчитать объём по кластерам, ничего не выкачивая")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"))
    ap.add_argument("--all", action="store_true", help="вся территория РИ/СССР — это надолго")
    # Градус, а не полградуса: ограничения на число снимков в ответе у сервиса
    # нет (самая плотная клетка, Москва, — около 121 000 снимков и 25 МБ),
    # а клеток при шаге 0.5° вчетверо больше и почти все пустые.
    ap.add_argument("--step", type=float, default=1.0, help="сторона клетки в градусах")
    ap.add_argument("--year-to", type=int, default=YEAR_MAX, help="верхняя граница датировки")
    ap.add_argument("--pause", type=float, default=0.5, help="пауза между запросами, секунды")
    ap.add_argument("--max-cells", type=int, default=None, help="ограничить число клеток")
    ap.add_argument("--resume", action="store_true",
                    help="продолжить прерванный обход по журналу в data/cache/pastvu")
    ap.add_argument("--restart", action="store_true",
                    help="начать обход заново: прошлый журнал откладывается в сторону")
    ap.add_argument("--finalize", action="store_true",
                    help="собрать слои из журнала, не продолжая обход")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out")
    ap.add_argument("--state", type=Path, default=STATE_DIR, help="каталог журнала обхода")
    args = ap.parse_args()

    client = PastVuClient(pause_sec=args.pause)
    # `--all` — это две рамки: основная и заходящая за 180-й меридиан Чукотка
    # (BBOX_RU_EAST). Снимков там всего десятки, но «вся территория» — значит
    # вся: молча отрезать угол страны нельзя.
    if args.bbox:
        bboxes = [tuple(args.bbox)]
    elif args.all:
        bboxes = [BBOX_RU, BBOX_RU_EAST]
    else:
        bboxes = [PROBE_BBOX]

    try:
        if args.probe:
            return probe(client, tuple(args.bbox) if args.bbox else PROBE_BBOX, args.year_to)
        if args.finalize:
            journal = Journal(args.state, bboxes=bboxes, step=args.step,
                              year_to=args.year_to, cells=0)
            if not journal.rows_path.exists():
                print(f"Журнал {journal.rows_path} пуст — нечего сводить.", file=sys.stderr)
                return 1
            return finalize(journal, args.out)
        if not args.bbox and not args.all:
            ap.error("укажите --probe, --bbox или --all "
                     "(оценка объёма — --estimate вместе с --bbox или --all)")
        if args.estimate:
            return estimate(client, bboxes, step=args.step, year_to=args.year_to)
        return harvest(client, bboxes, step=args.step, year_to=args.year_to,
                       out_dir=args.out, state_dir=args.state,
                       max_cells=args.max_cells, resume=args.resume,
                       restart=args.restart)
    except PastVuError as exc:
        print(f"PastVu: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
