"""Сбор данных из Викиданных через SPARQL.

Викиданные — основной источник для машинного сбора: лицензия CC0 (можно
использовать без ограничений), есть координаты (P625), даты основания и
упразднения (P571/P576) и привязка к историческим государствам (P17).

Важно: идентификаторы классов (Q-номера) в запросах обязательно проверяются
перед сбором — см. `verify_qids`. Молча собрать не тот класс хуже, чем
упасть с ошибкой.
"""

from __future__ import annotations

import gzip
import hashlib
import http.client
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from ..geo import in_bbox, valid_coords
from ..schema import ContextRecord, LayerSpec, clean_text

ENDPOINT = "https://query.wikidata.org/sparql"

# Сервис запросов держит лимит на время выполнения (около минуты) и
# отдельно — на частоту обращений. Частоту он ограничивает жёстко: пачка
# запросов подряд получает «429 Aggressively rate-limiting to 1 req / min».
# Пауза считается на весь процесс, а не на клиента: клиентов может быть
# несколько, а адрес, с которого мы приходим, один.
MIN_INTERVAL_SEC = 5.0
RATE_LIMIT_PAUSE_SEC = 90.0

# Сколько раз повторять запрос, упёршийся в лимит времени (504). Ровно
# два: один раз сервис бывает занят чужой нагрузкой, но дальше повтор
# бесполезен — тяжёлый запрос лёгким не станет, а адрес у всех слоёв
# общий, и пятикратный повтор отбирает попытки у соседних сборов.
TIMEOUT_ATTEMPTS = 2

_last_request_at = 0.0

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

    def _throttle(self) -> None:
        """Держит паузу между обращениями к сервису — на весь процесс."""
        global _last_request_at
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()

    def _request(self, sparql: str) -> dict:
        data = urllib.parse.urlencode({"query": sparql, "format": "json"}).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT, data=data,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
                # Ответ на десятки тысяч строк сжимается примерно в десять раз.
                # Дело не только в трафике: несжатый ответ дольше течёт по сети
                # и успевает упереться в лимит времени, обрываясь на середине.
                "Accept-Encoding": "gzip",
            },
        )
        delay = 2.0
        last: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                self._throttle()
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
                    return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = exc
                # 429 — превышен лимит, 503 — сервис занят: обе ошибки временные.
                if exc.code not in (429, 500, 502, 503, 504):
                    raise SparqlError(f"HTTP {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}") from exc
                if exc.code == 429:
                    # Обычный отступ здесь не помогает: сервис переводит адрес
                    # на один запрос в минуту и держит это состояние.
                    delay = max(delay, RATE_LIMIT_PAUSE_SEC)
                if exc.code == 504 and attempt + 1 >= TIMEOUT_ATTEMPTS:
                    # 504 — запрос не уложился в лимит времени. Повтор того же
                    # запроса не лечится ожиданием: тяжёлым он и останется.
                    raise SparqlError(
                        "запрос не уложился в лимит времени сервиса (HTTP 504). "
                        "Повтор не поможет — запрос надо дробить: сузить класс, "
                        "добавить @filter или уменьшить чанк"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
            except (json.JSONDecodeError, EOFError, gzip.BadGzipFile,
                    http.client.HTTPException) as exc:
                # Ответ оборвался на середине — сервис не уложился в свой лимит
                # времени. Повтор иногда проходит, но чаще запрос надо дробить.
                # Обрыв сжатого ответа виден не как испорченный JSON, а как
                # обрыв самого gzip-потока: без этих трёх исключений он
                # пролетал мимо повторов и мимо обработчиков SparqlError,
                # роняя весь сбор посреди слоя.
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


# --- сбор в две ступени -----------------------------------------------------
#
# Первая редакция запросов отбирала объекты географической рамкой
# (`SERVICE wikibase:box`) поверх транзитивного замыкания по классу
# (`wdt:P31/wdt:P279*`). Против живого сервиса такой запрос не выполняется:
# рамка РИ/СССР слишком велика, и сбор упирается в лимит времени — 504.
# Проверено на всех одиннадцати запросах, ни один не прошёл.
#
# Замена — отбор по государству (`wdt:P17`) вместо рамки и разделение работы
# на две ступени:
#
#   1. Список Q-номеров с координатами — по одному запросу на государство.
#      Без меток, без OPTIONAL, без сортировки: только то, что дёшево.
#   2. Подробности к ним — чанками по тысяче через `VALUES ?item`.
#      Дорогие соединения выполняются на заранее известном списке, а не на
#      результате поиска, и укладываются в лимит.
#
# Территория РИ/СССР не совпадает ни с одним нынешним государством, поэтому
# отбор идёт по семнадцати государствам-преемникам, а рамка остаётся вторым
# ситом: `rows_to_records` всё равно проверяет координату через `in_bbox`.

COUNTRIES: tuple[tuple[Optional[str], str], ...] = (
    ("Q159", "Россия"), ("Q212", "Украина"), ("Q184", "Беларусь"),
    ("Q232", "Казахстан"), ("Q265", "Узбекистан"), ("Q874", "Туркменистан"),
    ("Q863", "Таджикистан"), ("Q813", "Киргизия"), ("Q230", "Грузия"),
    ("Q399", "Армения"), ("Q227", "Азербайджан"), ("Q217", "Молдавия"),
    ("Q37", "Литва"), ("Q211", "Латвия"), ("Q191", "Эстония"),
    ("Q36", "Польша"), ("Q33", "Финляндия"),
)

# Государства, которых уже нет. У здания `P17` указывает на нынешнюю страну,
# а у события — на ту, что существовала в момент события, и семнадцати
# преемников для событий недостаточно. Проверено на девяти известных
# событиях: у семи `P17` ведёт только на историческое государство и на
# нынешнее не ведёт вовсе.
#
#   Восстание декабристов (Q126306)      P17 = Российская империя
#   Ходынская катастрофа (Q942894)       P17 = Российская империя
#   Чумной бунт (Q4518057)               P17 = Российская империя
#   Кровавое воскресенье (Q185642)       P17 = Российская империя
#   Ленский расстрел (Q578858)           P17 = Российская империя
#   Пожар Москвы 1812 года (Q897785)     P17 = Российская империя
#   Куренёвская трагедия (Q4248274)      P17 = СССР
#   Кронштадтское восстание (Q208300)    P17 = РСФСР и Россия
#   Тамбовское восстание (Q811250)       P17 не проставлен вовсе
#
# То есть отбор по нынешним государствам терял даже восстание декабристов —
# канонический экземпляр класса «восстание». Отсюда этот второй список; он
# добавляется к обходу только для слоёв событий (`kind="event"`), потому что
# менять отбор у слоёв зданий — отдельная работа с пересчётом их объёмов.
# Предложение к общему сбору: те же государства нужны и церквям, и заводам —
# храм с `P17 = Российская империя` сейчас теряется так же.
#
# РСФСР в Викиданных двумя элементами (Q2184 и Q2305208) — это не ошибка
# списка, а дублирование в самих Викиданных; берутся оба.
HISTORICAL_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("Q34266", "Российская империя"), ("Q15180", "СССР"),
    ("Q2184", "РСФСР"), ("Q2305208", "РСФСР (второй элемент)"),
    ("Q139319", "Российская республика"), ("Q172107", "Речь Посполитая"),
)
# Обход без разделения по государствам: одна «страна» со значением None, при
# котором из первой ступени выпадает условие по P17, а сама ступень идёт по
# одному классу за запрос (см. `stage1_plan`). Нужен там, где отбор по
# нынешнему государству мимо цели, — у исторической единицы деления P17
# указывает на историческое государство (Российская империя, РСФСР, СССР),
# а не на нынешнюю Россию, и часто не указан вовсе. Годится только для
# узких классов: без P17 первую ступень сдерживает один класс.
WORLD: tuple[tuple[Optional[str], str], ...] = ((None, "класс"),)

# Тысяча Q-номеров в VALUES — примерно восемь секунд на ответ. Больше берём
# на свой страх: запрос растёт линейно, а лимит времени не двигается.
CHUNK_SIZE = 1000

# Дата основания (P571) — не единственная, которой датируют объект. У станций
# она почти не заполнена: на выборке в 2003 объекта по России P571 нашлась
# у 124 (6%), а дата официального открытия P1619 — у 1291 (64%).
# Условие про isBlank — не украшение: у P571 бывает значение «известно, что
# есть, но какое — нет». В ответе оно приходит пустым узлом, COALESCE счёл бы
# его настоящей датой и заслонил бы им дату открытия.
_DATES_OBJECT = """  OPTIONAL { ?item wdt:P571 ?founded . FILTER(!isBlank(?founded)) }
  OPTIONAL { ?item wdt:P1619 ?opened . }
  OPTIONAL { ?item wdt:P576 ?end . }
  BIND(COALESCE(?founded, ?opened) AS ?start)"""

# Класс «населённый пункт»: им ограничено место, у которого событию можно
# занять координату. Без ограничения `P276` приводит и губернии — у
# Кыштымского волнения там Пермская губерния, у Лучайского бунта Виленская, —
# а точка в середине губернии выглядит на карте достоверно и врёт
# (`docs/SCHEMA.md`, раздел про `scope`). Город, село и посад проходят,
# губерния и уезд — нет.
SETTLEMENT = "Q486972"


def _coord_via_place(var: str, indent: str) -> str:
    """Координата населённого пункта, в котором произошло событие."""
    return (
        f"{indent}?item wdt:P276 ?place .\n"
        f"{indent}?place wdt:P31/wdt:P279* wd:{SETTLEMENT} ;\n"
        f"{indent}       wdt:P625 {var} .\n"
    )


# У события даты лежат в P580/P582 или в P585 — см. пояснение в rows_to_records.
_DATES_EVENT = """  OPTIONAL { ?item wdt:P580 ?startTime . }
  OPTIONAL { ?item wdt:P582 ?endTime . }
  OPTIONAL { ?item wdt:P585 ?pointInTime . }
  BIND(COALESCE(?startTime, ?pointInTime) AS ?start)
  BIND(COALESCE(?endTime, ?pointInTime) AS ?end)"""

# Владелец (P127) — только там, где слой его просит директивой `@owner`.
# Нужен он пока одним усадьбам: до 1861 года крепостной род привязан к
# владельцу имения, и без имени владельца слой отвечает «где», но не
# отвечает «у кого искать». Остальным слоям это лишнее соединение, поэтому
# по умолчанию его нет.
#
# Имена собираются подзапросом, а не соединением в теле запроса. У имения
# бывает несколько владельцев, и обычное соединение дало бы по строке на
# каждого; `dedupe` оставляет первую строку объекта, то есть одного
# владельца — какого придётся, по порядку ответа сервиса. Подзапрос
# сворачивает всех в одно значение, и набор имён перестаёт зависеть от
# порядка ответа. Порядок внутри строки от него зависеть не перестаёт:
# `GROUP_CONCAT` ничего не сортирует, поэтому «Вульфы; Полторацкие» и
# «Полторацкие; Вульфы» — один и тот же ответ. Это список владельцев за всё
# время, а не цепочка: кто из них владел усадьбой в нужный год, по полю не
# определить — за этим надо идти в саму карточку Викиданных по ссылке.
#
# `VALUES` внутри подзапроса обязателен: без него он считал бы P127 по всем
# Викиданным, а не по нашей тысяче Q-номеров. Условие на координату там же:
# подзапрос считается сам по себе, и без этой строки он собирал бы владельцев
# и тем объектам, которые внешний запрос всё равно отбросит.
#
# Берётся не `wdt:P127`, а полное утверждение `p:P127/ps:P127`. `wdt:` отдаёт
# только значения высшего ранга, и там, где кто-то пометил предпочтительным
# нынешнего владельца — музей, район, монастырь, — прежние владельцы молча
# исчезли бы. Для генеалогии важны как раз прежние: усадьба ищется по тому,
# кому она принадлежала до 1861 года. Поэтому собираются все владельцы, кроме
# отклонённых (deprecated).
_OWNERS = """  OPTIONAL {{
    SELECT ?item (GROUP_CONCAT(DISTINCT ?ownerName; separator="; ") AS ?owners) WHERE {{
      VALUES ?item {{ {values} }}
      ?item wdt:P625 [] .
      ?item p:P127 ?ownerStatement .
      ?ownerStatement ps:P127 ?owner .
      FILTER NOT EXISTS {{ ?ownerStatement wikibase:rank wikibase:DeprecatedRank }}
      OPTIONAL {{ ?owner rdfs:label ?ownerRu . FILTER(LANG(?ownerRu) = "ru") }}
      OPTIONAL {{ ?owner rdfs:label ?ownerEn . FILTER(LANG(?ownerEn) = "en") }}
      BIND(COALESCE(?ownerRu, ?ownerEn) AS ?ownerName)
      FILTER(BOUND(?ownerName))
    }}
    GROUP BY ?item
  }}"""


def ids_query(classes: list[str], country: Optional[str],
              extra: Optional[list[str]] = None, kind: str = "object") -> str:
    """Ступень 1: Q-номера объектов класса с координатами в одном государстве.

    `country` = None — без условия по P17, разом по всему миру (см. `WORLD`).
    `extra` — дополнительные строки условия из директив `@filter` в `.rq`:
    ими слой сужается там, где одного класса мало.

    `kind="event"` меняет то, откуда берётся координата: у события своей
    `P625` часто нет, оно привязано к месту через `P276`. Тогда координата
    берётся у места — см. пояснение в `details_query`.
    """
    values = " ".join(f"wd:{c}" for c in classes)
    tail = "".join(f"  {line}\n" for line in (extra or []))
    p17 = f"        wdt:P17 wd:{country} ;\n" if country else ""
    if kind == "event":
        # У события координата бывает не своя, а места, где оно случилось:
        # без этого UNION слой терял почти всё. Точку с запятой в конце P17
        # здесь заменяет точка — дальше идёт отдельный шаблон.
        where = (
            "  ?item wdt:P31/wdt:P279* ?cls ;\n"
            + (p17.rstrip(" ;\n") + " .\n" if country else "")
            + "  { ?item wdt:P625 ?coord }\n"
            "  UNION {\n"
            f"{_coord_via_place('?coord', '    ')}"
            "  }\n"
        )
    else:
        where = (
            "  ?item wdt:P31/wdt:P279* ?cls ;\n"
            f"{p17}"
            "        wdt:P625 ?coord .\n"
        )
    return (
        "SELECT ?item ?coord WHERE {\n"
        f"  VALUES ?cls {{ {values} }}\n"
        f"{where}"
        f"{tail}"
        "}"
    )


def stage1_plan(classes: list[str],
                countries: tuple[tuple[Optional[str], str], ...],
                ) -> list[tuple[list[str], Optional[str], str]]:
    """Из чего складывается первая ступень: что спрашивать и одним ли запросом.

    При обходе по государствам все классы спрашиваются разом: опорой для
    планировщика служит условие по P17. Без него (`WORLD`) опоры нет, и
    несколько классов в одном `VALUES` кладут запрос в лимит времени.
    Проверено живьём на слое `admin_units`: девять классов сразу — HTTP 504
    через 65 секунд, тот же отбор по одному классу — 0.6 секунды на класс.
    Поэтому без P17 первая ступень идёт по одному классу за запрос.
    """
    plan: list[tuple[list[str], Optional[str], str]] = []
    for country, name in countries:
        if country is None:
            plan.extend(([cls], None, f"{name} {cls}") for cls in classes)
        else:
            plan.append((classes, country, name))
    return plan


def details_query(qids: list[str], kind: str = "object", *,
                  with_owner: bool = False) -> str:
    """Ступень 2: подробности к готовому списку Q-номеров.

    У события координата берётся из двух мест. Своей `P625` у него часто нет —
    ни у Чумного бунта, ни у Кровавого воскресенья, — тогда берётся координата
    `P276`, места события, а запись помечается `confidence = place_level`:
    точка указывает на населённый пункт, а не на само место события.

    Место при этом обязано быть населённым пунктом. `P276` сплошь и рядом
    указывает на губернию, и ставить точку в её середине нельзя: выглядит
    она как настоящая, а не как «где-то в губернии».

    `with_owner` добавляет владельца (P127) — нужен усадьбам, где до 1861 года
    род привязан к владельцу. Слои, которые его не просят, запрос не меняют:
    их выгрузка обязана остаться прежней, по ней считаются `uid`.
    """
    values = " ".join(f"wd:{q}" for q in qids)
    dates = _DATES_EVENT if kind == "event" else _DATES_OBJECT
    owner_col = " ?owners" if with_owner else ""
    owners = f"{_OWNERS.format(values=values)}\n" if with_owner else ""
    if kind == "event":
        coord = (
            "  OPTIONAL { ?item wdt:P625 ?ownCoord . }\n"
            "  OPTIONAL {\n"
            f"{_coord_via_place('?placeCoord', '    ')}"
            "  }\n"
            "  BIND(COALESCE(?ownCoord, ?placeCoord) AS ?coord)\n"
            '  BIND(IF(BOUND(?ownCoord), "own", "place") AS ?coordSource)\n'
        )
        head = ("SELECT ?item ?itemLabel ?coord ?coordSource ?start ?end "
                "?adminLabel ?typeLabel ?article ?image ?description"
                f"{owner_col} WHERE {{\n")
    else:
        coord = "  ?item wdt:P625 ?coord .\n"
        head = ("SELECT ?item ?itemLabel ?coord ?start ?end ?adminLabel "
                "?typeLabel ?article ?image ?description"
                f"{owner_col} WHERE {{\n")
    return (
        f"{head}"
        f"  VALUES ?item {{ {values} }}\n"
        f"{coord}"
        f"{dates}\n"
        "  OPTIONAL { ?item wdt:P131 ?admin . }\n"
        "  OPTIONAL { ?item wdt:P31 ?type . }\n"
        "  OPTIONAL { ?item wdt:P18 ?image . }\n"
        "  OPTIONAL { ?article schema:about ?item ; "
        "schema:isPartOf <https://ru.wikipedia.org/> . }\n"
        '  OPTIONAL { ?item schema:description ?description . '
        'FILTER(LANG(?description) = "ru") }\n'
        f"{owners}"
        '  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }\n'
        "}"
    )


def dedupe(records: list[ContextRecord]) -> list[ContextRecord]:
    """Оставляет по одной записи на объект Викиданных.

    Ступень 2 множит строки: у объекта бывает несколько значений P31, P131
    и даже P625, и каждое сочетание приходит отдельной строкой. Тысяча
    Q-номеров даёт около двух тысяч строк.

    Ключ — Q-номер (`source_id`), а не `uid`. Второй координаты не переживёт:
    `uid` считается в том числе от широты и долготы, поэтому объект с двумя
    значениями P625 получил бы два разных `uid` и остался бы на карте дважды.
    Один элемент Викиданных — одно место; лишние значения это варианты, а не
    вторая церковь. Записи без `source_id` (такого быть не должно, но схема
    его не требует) сравниваются по `uid`.
    """
    seen: set[str] = set()
    out: list[ContextRecord] = []
    for rec in records:
        key = rec.source_id or rec.uid
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def collect_layer(client: SparqlClient, classes: list[str], spec: LayerSpec, *,
                  kind: str = "object",
                  countries: tuple[tuple[Optional[str], str], ...] = COUNTRIES,
                  history: tuple[tuple[Optional[str], str], ...] = (),
                  chunk_size: int = CHUNK_SIZE,
                  require_bbox: bool = True,
                  extra: Optional[list[str]] = None,
                  with_owner: bool = False,
                  max_objects: Optional[int] = None,
                  progress: Optional[Callable[[str], None]] = None) -> list[ContextRecord]:
    """Собирает слой в две ступени по всем государствам-преемникам.

    `history` — государства, которых уже нет (`HISTORICAL_COUNTRIES`). Обход
    по ним идёт тем же способом и добавляется к нынешним, а не заменяет их:
    у Кронштадтского восстания `P17` указывает и на РСФСР, и на Россию, и
    терять ни то, ни другое нельзя. Повторы отсеиваются по Q-номеру.
    `countries=WORLD` — обход без разделения по государствам, одной ступенью
    по классу.

    Ошибка на одном государстве или на одном чанке не отменяет сбор: она
    печатается и работа идёт дальше. Потерять область хуже, чем потерять всё,
    но молча терять нельзя — поэтому о каждой потере сообщается.
    """
    say = progress or (lambda _: None)

    qids: list[str] = []
    seen: set[str] = set()
    for step_classes, country, name in stage1_plan(
            classes, tuple(countries) + tuple(history)):
        try:
            rows = client.query(ids_query(step_classes, country, extra, kind))
        except SparqlError as exc:
            say(f"    {name}: ОШИБКА — {exc}")
            continue
        fresh = 0
        for row in rows:
            qid = _qid(_val(row, "item"))
            if qid and qid not in seen:
                seen.add(qid)
                qids.append(qid)
                fresh += 1
        if rows:
            say(f"    {name}: {len(rows)} с координатой, новых {fresh}")
        elif country is None:
            # Пустая страна — обычное дело и молчания стоит. Пустой класс —
            # нет: он объявлен в .rq директивой @qid, и если он не даёт
            # ничего, это надо увидеть, а не пропустить глазами.
            say(f"    {name}: ничего не нашлось")

    say(f"  всего объектов: {len(qids)}")
    if max_objects is not None and len(qids) > max_objects:
        # Проба: обращений к сервису должно быть немного. Сервис ограничивает
        # частоту, и полная проба крупного слоя (двенадцать чанков) стоит
        # столько же, сколько сам сбор.
        qids = qids[:max_objects]
        say(f"  проба: берём первые {len(qids)}")
    if not qids:
        return []

    records: list[ContextRecord] = []
    for start in range(0, len(qids), chunk_size):
        chunk = qids[start:start + chunk_size]
        try:
            rows = client.query(details_query(chunk, kind, with_owner=with_owner))
        except SparqlError as exc:
            say(f"    подробности {start}–{start + len(chunk)}: ОШИБКА — {exc}")
            continue
        records.extend(rows_to_records(rows, spec, require_bbox=require_bbox, kind=kind))
        say(f"    подробности {start + len(chunk)}/{len(qids)}")

    return dedupe(records)


def rows_to_records(rows: list[dict], spec: LayerSpec, *,
                    require_bbox: bool = True, kind: str = "object") -> list[ContextRecord]:
    """Преобразует ответ SPARQL в записи единой схемы.

    Ожидаемые переменные запроса: ?item ?itemLabel ?coord ?start ?end
    ?admin ?adminLabel ?typeLabel ?article ?image ?description и
    необязательная ?owners. Последнюю спрашивают только слои с директивой
    `@owner` — у остальных её в ответе нет, и поле остаётся пустым.

    `kind` различает два способа существовать во времени. Здание стоит от
    основания до упразднения, и открытый конец разумно дотянуть до конца
    интересующего периода. Событие — эпидемия, восстание, пожар — случается
    и заканчивается; дотягивать его до 1960 года нельзя, иначе холера 1848
    года окажется «подходящей» к факту 1950 года.

    `?coordSource` приходит только у событий (см. `details_query`). Значение
    `place` означает, что координата взята у места события, а не у самого
    события: запись помечается `place_level` и остаётся в слое.
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
                # Но тянуть конец назад нельзя: основанный позже 1960 года
                # получил бы вывернутый наизнанку срок — «2018–1960», — и
                # `overlaps_years` не нашёл бы объект даже в его собственном
                # году, хотя в выгрузку он всё равно попал бы.
                year_to = max(year_from, OPEN_END_YEAR)
                precision = "part"
        if year_to and not year_from:
            year_from = year_to if is_event else min(year_to, 1800)
            precision = "year" if is_event else "part"

        qid = _qid(_val(row, "item"))
        borrowed = _val(row, "coordSource") == "place"
        out.append(spec.new_record(
            confidence="place_level" if borrowed else "ok",
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
            # Владелец имения — признак самого места, а не отдельная запись
            # о человеке: персоналии проект не собирает. Поле то же, что у
            # автора литературного места и у Прокудина-Горского на снимке.
            actor=clean_text(_val(row, "owners")),
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
