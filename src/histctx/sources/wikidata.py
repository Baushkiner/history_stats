"""Сбор данных из Викиданных через SPARQL.

Викиданные — основной источник для машинного сбора: лицензия CC0 (можно
использовать без ограничений), есть координаты (P625), даты основания и
упразднения (P571/P576) и привязка к историческим государствам (P17).

Важно: идентификаторы классов (Q-номера) в запросах обязательно проверяются
перед сбором — см. `verify_qids`. Молча собрать не тот класс хуже, чем
упасть с ошибкой.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from ..geo import in_bbox, valid_coords
from ..schema import ContextRecord, LayerSpec, clean_text

ENDPOINT = "https://query.wikidata.org/sparql"

# Верхняя граница интересующего периода. До неё дотягиваются объекты с
# открытой датировкой: храм основан в 1800 году и не упразднён.
OPEN_END_YEAR = 1960

# Викимедиа требует содержательный User-Agent и блокирует запросы без него.
# Только ASCII: заголовки HTTP кодируются latin-1, кириллица здесь падает.
USER_AGENT = (
    "histctx/0.1 (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

_RE_POINT = re.compile(r"Point\(([-\d.eE]+)\s+([-\d.eE]+)\)")
_RE_QID = re.compile(r"/entity/(Q\d+)$")


class SparqlError(RuntimeError):
    """Запрос к Викиданным не выполнен."""


@dataclass
class SparqlClient:
    """Клиент SPARQL с кэшем на диске и повторами при перегрузке сервиса."""

    cache_dir: Optional[Path] = None
    timeout: int = 120
    max_retries: int = 5
    pause_sec: float = 1.0

    def query(self, sparql: str, *, use_cache: bool = True) -> list[dict]:
        """Выполняет запрос и возвращает список привязок (bindings)."""
        key = hashlib.sha1(sparql.encode("utf-8")).hexdigest()[:16]
        cached = self._cache_path(key)
        if use_cache and cached and cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))

        payload = self._request(sparql)
        rows = payload.get("results", {}).get("bindings", [])
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows

    def query_paged(self, sparql: str, page_size: int = 5000,
                    max_pages: int = 200) -> Iterator[dict]:
        """Постранично забирает большой результат.

        В шаблоне не должно быть своих LIMIT/OFFSET — они добавляются здесь.
        """
        if re.search(r"\bLIMIT\b", sparql, re.IGNORECASE):
            raise ValueError("Шаблон для постраничной выгрузки не должен содержать LIMIT")
        for page in range(max_pages):
            chunk = self.query(f"{sparql}\nLIMIT {page_size}\nOFFSET {page * page_size}")
            if not chunk:
                return
            yield from chunk
            if len(chunk) < page_size:
                return
            time.sleep(self.pause_sec)

    def _cache_path(self, key: str) -> Optional[Path]:
        return None if self.cache_dir is None else Path(self.cache_dir) / f"{key}.json"

    def _request(self, sparql: str) -> dict:
        data = urllib.parse.urlencode({"query": sparql, "format": "json"}).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT, data=data,
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        )
        delay = 2.0
        last: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = exc
                # 429 — превышен лимит, 503 — сервис занят: обе ошибки временные.
                if exc.code not in (429, 500, 502, 503, 504):
                    raise SparqlError(f"HTTP {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
            except UnicodeEncodeError as exc:
                # Заголовки HTTP кодируются latin-1: повтор ничего не изменит.
                raise SparqlError(f"Недопустимый символ в заголовке запроса: {exc}") from exc
            if attempt < self.max_retries - 1:
                time.sleep(delay)
                delay *= 2
        raise SparqlError(f"Не удалось выполнить запрос после {self.max_retries} попыток: {last}")


def verify_qids(client: SparqlClient, qids: list[str]) -> dict[str, Optional[str]]:
    """Возвращает русские названия классов по их Q-номерам.

    Нужно, чтобы до сбора убедиться: Q-номер в запросе означает то, что мы
    думаем. Отсутствие метки (None) — повод перепроверить запрос вручную.
    """
    if not qids:
        return {}
    values = " ".join(f"wd:{q}" for q in sorted(set(qids)))
    rows = client.query(
        f"""
        SELECT ?item ?itemLabel WHERE {{
          VALUES ?item {{ {values} }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
        }}
        """,
        use_cache=False,
    )
    out: dict[str, Optional[str]] = {q: None for q in qids}
    for row in rows:
        qid = _qid(row.get("item", {}).get("value"))
        if qid:
            out[qid] = row.get("itemLabel", {}).get("value")
    return out


def rows_to_records(rows: list[dict], spec: LayerSpec, *,
                    require_bbox: bool = True, kind: str = "object") -> list[ContextRecord]:
    """Преобразует ответ SPARQL в записи единой схемы.

    Ожидаемые переменные запроса: ?item ?itemLabel ?coord ?start ?end
    ?admin ?adminLabel ?typeLabel ?article ?image ?description.

    `kind` различает два способа существовать во времени. Здание стоит от
    основания до упразднения, и открытый конец разумно дотянуть до конца
    интересующего периода. Событие — эпидемия, восстание, пожар — случается
    и заканчивается; дотягивать его до 1960 года нельзя, иначе холера 1848
    года окажется «подходящей» к факту 1950 года.
    """
    is_event = kind == "event"
    out: list[ContextRecord] = []
    for row in rows:
        lat, lon = _point(_val(row, "coord"))
        if lat is None or not valid_coords(lat, lon):
            continue
        if require_bbox and not in_bbox(lat, lon):
            continue

        year_from = _year(_val(row, "start"))
        year_to = _year(_val(row, "end"))
        precision = "year" if (year_from or year_to) else "unknown"
        if year_from and not year_to:
            if is_event:
                # У события известно только начало: считаем его однолетним,
                # а не длящимся до конца периода.
                year_to = year_from
            else:
                # Объект основан и не упразднён — считаем его существующим до
                # конца интересующего нас периода, иначе он выпадет из подбора.
                year_to = OPEN_END_YEAR
                precision = "part"
        if year_to and not year_from:
            year_from = year_to if is_event else min(year_to, 1800)
            precision = "year" if is_event else "part"

        qid = _qid(_val(row, "item"))
        out.append(spec.new_record(
            title=clean_text(_val(row, "itemLabel")) or qid or "Без названия",
            category=clean_text(_val(row, "typeLabel")),
            lat=lat, lon=lon,
            place_text=clean_text(_val(row, "adminLabel")),
            region=clean_text(_val(row, "adminLabel")),
            year_from=year_from,
            year_to=year_to,
            date_precision=precision,
            date_approx=precision == "part",
            period_raw=_raw_period(_val(row, "start"), _val(row, "end")),
            summary=clean_text(_val(row, "description")),
            url=clean_text(_val(row, "article")) or (f"https://www.wikidata.org/wiki/{qid}" if qid else None),
            image_url=clean_text(_val(row, "image")),
            source_id=qid,
        ))
    return out


def _val(row: dict, key: str) -> Optional[str]:
    node = row.get(key)
    return node.get("value") if isinstance(node, dict) else None


def _qid(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    m = _RE_QID.search(uri)
    return m.group(1) if m else None


def _point(literal: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """WKT `Point(долгота широта)` -> (широта, долгота)."""
    if not literal:
        return None, None
    m = _RE_POINT.search(literal)
    if not m:
        return None, None
    try:
        return float(m.group(2)), float(m.group(1))
    except ValueError:
        return None, None


def _year(literal: Optional[str]) -> Optional[int]:
    """Достаёт год из даты Викиданных, включая годы до нашей эры со знаком."""
    if not literal:
        return None
    m = re.match(r"^(-?\d{1,4})-", str(literal))
    if not m:
        return None
    year = int(m.group(1))
    return year if 1000 <= year <= 2100 else None


def _raw_period(start: Optional[str], end: Optional[str]) -> Optional[str]:
    a, b = _year(start), _year(end)
    if a and b:
        return str(a) if a == b else f"{a}–{b}"
    if a:
        return f"с {a}"
    if b:
        return f"до {b}"
    return None
