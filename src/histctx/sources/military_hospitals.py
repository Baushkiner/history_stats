"""Госпитали РККА 1941–1945 годов: справочник дислокации на soldat.ru.

Зачем этот слой. Строки «умер от ран в ЭГ 3870», «находился на излечении в
ППГ 2331», «направлен в батальон выздоравливающих № 12» стоят в донесениях о
потерях, в похоронках и в карточках раненых. Сами по себе это шифры: номер
госпиталя ничего не говорит о месте, а место решает всё — где искать
захоронение, в каком архиве лежит книга умерших госпиталя, почему семья
оказалась в Свердловске или Кирове. Справочник отвечает именно на это: какое
лечебное учреждение где стояло и с какого по какое число. Другого машинного
свода «номер — место — даты» нет (проход 24.10.2026, `docs/DISCOVERY.md`).

Источник. «Справочник дислокации госпиталей РККА в 1941–1945 годах» составлен
архивом военно-медицинских документов Военно-медицинского музея Министерства
обороны в 1972 году; часть экземпляров машинописи передана в ЦАМО, где её
переписали вручную исследователи Архангельской, Вологодской, Мурманской
областей, Татарстана и Удмуртии; в 2001 году из этих частей собрана
электронная версия. Она лежит на soldat.ru (И. И. Ивлев) формой поиска
`/hospital.html`: POST в cp1251, поля «номер», «тип», «место», «район»,
«дата», «дополнительная информация», метасимволы `*` и `?`.

Права. Права на справочник и его электронную версию не выяснены. Сайт
требует активную ссылку на использованную страницу — она стоит в `url`
каждой записи. Берутся факты: номер, тип учреждения, место и район
дислокации, даты; пометка «в справочнике так: …» — дословная строка
справочника о самом учреждении — идёт в `extra`, персоналий в справочнике нет.

Как устроена выдача. Форма показывает не больше 500 записей на запрос, по 20
на страницу (`?page=N` с теми же скрытыми полями), упорядочив их по номеру
как по строке. Счётчик «Запросу соответствует N записей» тоже обрезан на 500.
Номер ищется точным числом, а не по образцу. Поэтому сбор идёт деревом
запросов (`Crawler.crawl`):

1. каждый тип учреждения целиком: тип меньше 500 записей читается сразу,
   крупные (эвакогоспиталь, ХППГ, ППГ …) помечаются;
2. поиск неизвестных типов: счётчик по началу названия типа («Б*», «Ба*»)
   против суммы известных мелких типов; не сошлось — выдача читается и новые
   типы входят в перечень;
3. первая буква района дислокации; где выдача обрезана — крупные типы по
   одному, дальше первая буква места, следующие буквы и точное место;
4. сверка крупных типов по первой и второй букве места: так находятся
   записи без района — по аннотации справочника у части мест он не
   установлен, и обход по районам их не видит.

Полнота проверяется счётчиком сайта там, где он не обрезан: число записей в
узле равно счётчику (`check_tree`). У каждой записи на сайте есть свой номер
(`pid` формы правки), и записи сводятся по нему: одна запись, найденная двумя
ветками дерева, — одна запись слоя. Форма правки (`/hospital_edit.html`,
POST `pid`) показывает запись по номеру — по выборке из неё проверяются
пропуски в нумерации.

Что попадает в слой. По записи на строку справочника: учреждение в одном
месте на один срок. Госпиталь, переезжавший с фронтом, даёт столько записей,
сколько у него мест. Даты — до дня (`date_precision = day`); если справочник
называет только конец («по 07.08.1943») или только начало, недостающий конец
берётся из рамки справочника — 1941 или 1945 год — с точностью `open`, как
у открытого срока в остальных слоях; без дат вовсе — рамка войны целиком,
`era`. Аннотация справочника предупреждает, что часто известно одно число
(«в справочнике так: на 15.07.44») или месяц («на 00.07.44»): такая запись —
срез на этот день, у неё один год и точность пометки. Исходная запись дат —
в `period_raw`.

Где запись на карте. Точка — населённый пункт дислокации, а не здание
госпиталя: `confidence = place_level`. Место сводится по названию с
Викиданными (метка или другое название, страна, цепочка подчинения P131 —
по ней проверяется район дислокации) и с GeoNames из слоя `settlements`.
Район военного времени переводится в нынешний (Молотовская область —
Пермский край, Чкаловская — Оренбургская, Сталинская — Донецкая). Не
сведённые места остаются в данных без точки (`no_coords`), за пределами
РИ/СССР — с пометкой `outside_bbox`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..geo import haversine_km
from ..net import USER_AGENT
from ..schema import ContextRecord, LayerSpec

SEARCH_URL = "https://www.soldat.ru/hospital.html"
EDIT_URL = "https://www.soldat.ru/hospital_edit.html"
ABBREVIATIONS_URL = "https://www.soldat.ru/hospital_abbr.html"
ENCODING = "cp1251"

# Поля формы поиска.
F_NUMBER = "fields[number]"
F_TYPE = "fields[hosptype.bigname]"
F_PLACE = "fields[hosppoint.name]"
F_REGION = "fields[hospobl.name]"
F_DOP = "fields[dop]"

PAGE_SIZE = 20
CAP = 500

# Рамка справочника: от начала войны до конца 1945 года.
YEAR_MIN, YEAR_MAX = 1941, 1945
WAR_START = dt.date(1941, 6, 22)

CITATION = (
    "Справочник дислокации госпиталей РККА в 1941–1945 годах (архив военно-медицинских "
    "документов Военно-медицинского музея МО, 1972; электронная версия — 2001). "
    "www.soldat.ru (И. И. Ивлев)"
)

LICENSE = (
    "права на справочник и его электронную версию не выяснены; сайт soldat.ru требует "
    "активную ссылку на использованную страницу — она стоит в каждой записи. Взяты "
    "номер, тип, место, район и даты дислокации"
)

MILITARY_HOSPITALS = LayerSpec(
    slug="military_hospitals",
    title="Госпитали РККА 1941–1945 годов",
    group="military",
    source=("«Справочник дислокации госпиталей РККА в 1941–1945 годах» "
            "(Военно-медицинский музей МО, 1972), электронная версия на soldat.ru"),
    license=LICENSE,
    url=SEARCH_URL,
    status="harvested",
    expected_rows=40585,
    description=(
        "Где стояло лечебное учреждение Красной армии и с какого по какое число: "
        "эвакогоспитали, полевые подвижные и хирургические госпитали, батальоны "
        "выздоравливающих, госпитали для инвалидов войны — по записи на каждое место "
        "дислокации, даты до дня. Отвечает, где искать госпиталь из донесения о "
        "потерях («умер от ран в ЭГ 3870») и почему семья раненого оказалась в "
        "тыловом городе. Точка — населённый пункт дислокации."
    ),
)


class HospitalsError(RuntimeError):
    """Справочник не ответил или ответил не в том виде, которого ждёт разбор."""


# --- запросы ----------------------------------------------------------------

def encode_form(fields: dict) -> bytes:
    """Тело POST в кодировке сайта; порядок полей — как передан."""
    return urllib.parse.urlencode(list(fields.items()), encoding=ENCODING).encode("ascii")


def post(url: str, fields: dict, *, attempts: int = 8, pause: float = 1.5,
         timeout: int = 30) -> bytes:
    """POST к soldat.ru. Соединение рвётся примерно на каждом третьем
    запросе (замер 24.10.2026), поэтому повтор — часть сбора, а не исключение.
    Повисшее соединение ждать дольше полуминуты незачем: следующая попытка
    обычно отвечает за секунду."""
    body = encode_form(fields)
    request = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise HospitalsError(f"{url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(min(pause * (attempt + 1), 15.0))
    raise HospitalsError(f"{url}: не ответил за {attempts} попыток ({last})")


# --- разбор выдачи -----------------------------------------------------------

@dataclass(frozen=True)
class Raw:
    """Строка справочника, как её показывает сайт."""

    pid: int
    number: str
    kind: str
    place: str
    region: str
    start: Optional[str] = None      # ISO-дата или None
    end: Optional[str] = None
    start_raw: Optional[str] = None  # как напечатано: «01.07.1941», «00.07.1941»
    end_raw: Optional[str] = None
    note: Optional[str] = None

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}

    @classmethod
    def from_json(cls, data: dict) -> "Raw":
        text = ("number", "kind", "place", "region")
        return cls(**{k: data.get(k, "" if k in text else None)
                      for k in cls.__dataclass_fields__})


@dataclass
class Page:
    """Одна страница выдачи."""

    count: int                       # счётчик сайта (обрезан на CAP)
    pages: int                       # число страниц выдачи
    hidden: dict = field(default_factory=dict)   # скрытые поля для следующих страниц
    records: list = field(default_factory=list)

    @property
    def capped(self) -> bool:
        return self.count >= CAP


_RE_COUNT = re.compile(r"Запросу соответствует\s*<b>\s*(\d+)\s*запис")
_RE_PAGES = re.compile(r"Страница:\s*(\d+)\s*/\s*(\d+)")
_RE_BLOCK_SPLIT = re.compile(r"<table[^>]*bgcolor=#660000[^>]*>\s*<tr>\s*<td>", re.I)
_RE_NUMBER = re.compile(r"Номер\s+лечебного учреждения:(.*?)</b>", re.S)
_RE_FIELD = re.compile(r"<td[^>]*>\s*([^<:]+?):&nbsp;</td>\s*<td>\s*<b>(.*?)</b>", re.S)
_RE_PID = re.compile(r"name=pid value=['\"]?(\d+)")
_RE_STAY = re.compile(r"находилось в этом районе(.*?)</td>", re.S)
_RE_STAY_PART = re.compile(r"(с|по)\s*<b>\s*([\d.]+)\s*</b>")
_RE_FRM = re.compile(r"<form name=frm action=/hospital\.html method=post>(.*?)</form>", re.S | re.I)
_RE_HIDDEN = re.compile(r"<input type=hidden name=(\S+?) value='([^']*)'>", re.I)
_RE_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def clean(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text: Optional[str]) -> tuple[Optional[str], str]:
    """«01.07.1941» → ('1941-07-01', 'day'); «00.07.1941» → ('1941-07-01', 'month');
    «00.00.1942» → ('1942-01-01', 'year'); пусто и «00.00.0000» → (None, '')."""
    m = _RE_DATE.match((text or "").strip())
    if not m:
        return None, ""
    d, mo, y = (int(g) for g in m.groups())
    if y == 0:
        return None, ""
    if mo == 0:
        return dt.date(y, 1, 1).isoformat(), "year"
    if d == 0:
        return dt.date(y, mo, 1).isoformat(), "month"
    try:
        return dt.date(y, mo, d).isoformat(), "day"
    except ValueError:
        return dt.date(y, mo, 1).isoformat(), "month"


def parse_block(block: str) -> Optional[Raw]:
    """Блок одной записи выдачи; без номера записи (`pid`) — None."""
    pid = _RE_PID.search(block)
    if not pid:
        return None
    number = _RE_NUMBER.search(block)
    fields = {clean(k): clean(v) for k, v in _RE_FIELD.findall(block)}
    start_raw = end_raw = None
    stay = _RE_STAY.search(block)
    if stay:
        for word, value in _RE_STAY_PART.findall(stay.group(1)):
            if word == "с":
                start_raw = value
            else:
                end_raw = value
    note = fields.get("Дополнительная информация") or None
    return Raw(
        pid=int(pid.group(1)),
        number=clean(number.group(1)) if number else "",
        kind=fields.get("Тип лечебного учреждения", ""),
        place=fields.get("Место дислокации", ""),
        region=fields.get("Район дислокации", ""),
        start=parse_date(start_raw)[0], end=parse_date(end_raw)[0],
        start_raw=start_raw, end_raw=end_raw, note=note,
    )


def parse_page(raw: bytes) -> Page:
    """Страница выдачи: счётчик, число страниц, скрытые поля и записи."""
    text = raw.decode(ENCODING, errors="replace")
    if "Справочник дислокации госпиталей" not in text:
        raise HospitalsError("ответ не похож на страницу справочника госпиталей")
    m = _RE_COUNT.search(text)
    if not m:
        if "не найдено" in text:
            return Page(count=0, pages=0)
        raise HospitalsError("на странице нет счётчика записей")
    count = int(m.group(1))
    pages = _RE_PAGES.search(text)
    total_pages = int(pages.group(2)) if pages else (1 if count else 0)
    frm = _RE_FRM.search(text)
    hidden = dict(_RE_HIDDEN.findall(frm.group(1))) if frm else {}
    records = []
    for block in _RE_BLOCK_SPLIT.split(text)[1:]:
        rec = parse_block(block)
        if rec is not None:
            records.append(rec)
    return Page(count=count, pages=total_pages, hidden=hidden, records=records)


_RE_EDIT_FIELD = re.compile(r"name=fields\[(\w+)\][^>]*value='([^']*)'", re.I)


def parse_edit(raw: bytes, pid: int) -> Optional[Raw]:
    """Форма правки записи: та же строка справочника по её номеру."""
    text = raw.decode(ENCODING, errors="replace")
    fields = {k: html.unescape(v).strip() for k, v in _RE_EDIT_FIELD.findall(text)}
    if not any(fields.get(k) for k in ("type", "point", "obl")):
        return None
    start_raw = fields.get("vdate1") or None
    end_raw = fields.get("vdate2") or None
    start, end = parse_date(start_raw)[0], parse_date(end_raw)[0]
    return Raw(pid=pid, number=fields.get("number", ""), kind=fields.get("type", ""),
               place=fields.get("point", ""), region=fields.get("obl", ""),
               start=start, end=end,
               start_raw=start_raw if start else None, end_raw=end_raw if end else None,
               note=fields.get("dop") or None)


# --- обход дерева запросов -----------------------------------------------------

# Буквы для дробления образца. Поиск на сайте не различает регистр; первой
# буквой идут прописные, дальше строчные. Пробел, дефис и точка встречаются в
# названиях («Нижний Тагил», «Чечено-Ингушская АССР», «Ст. Русса»).
FIRST = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ"
NEXT = "абвгдежзийклмнопрстуфхцчшщъыьэюя -."

# Типы учреждений, встреченные 22.11.2026 на первых страницах выдачи по
# каждой букве типа. Обход дополняет перечень тем, что встретит в записях, и
# повторяется из кэша, пока перечень не перестанет расти.
KNOWN_KINDS = (
    "Армейский госпиталь легкораненых", "Армейский полевой госпиталь", "Базовый лазарет",
    "Батальон выздоравливающих", "Больница (разные)",
    "Больница для инвалидов Отечественной войны", "Военно-морской госпиталь",
    "Военный госпиталь", "Госпиталь для военнопленных",
    "Госпиталь для инвалидов Отечественной войны", "Дивизион", "Диспансер", "Дом отдыха",
    "Институт (разные)", "Институт для ИОВ", "Инфекционный госпиталь",
    "Клиника (разные)", "Корпусной подвижной госпиталь", "Лазарет",
    "Медико-санитарный батальон", "Научно-исследовательский институт",
    "Полевой подвижной госпиталь", "Полевой подвижный госпиталь", "Психбольница",
    "Родильный дом", "Санаторий", "Санаторий для ИОВ",
    "Терапевтический полевой подвижной госпиталь",
    "Управление головного полевого эвакуационного пункта с эвакоприемником",
    "Хирургический полевой подвижной госпиталь", "Хирургический полевой подвижный госпиталь",
    "Эвакуационный госпиталь", "Эвакуационный приемник",
    "Эвакуационный приемник (в другое время - управление головного полевого "
    "эвакуационного пункта с эвакоприемником)",
)


def query_key(fields: dict, page: int) -> str:
    basis = json.dumps([sorted(fields.items()), page], ensure_ascii=False)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def fold(text: Optional[str]) -> str:
    """Как сравнивает поиск сайта: без регистра, «ё» как «е»."""
    return (text or "").lower().replace("ё", "е")


@dataclass
class Node:
    """Узел дерева запросов: образец, счётчик сайта и сколько записей пришло."""

    fields: dict
    count: int
    got: int = 0
    capped: bool = False
    how: str = ""                 # чем дробился: «тип», «место», «буква места»
    children: list = field(default_factory=list)

    def to_json(self) -> dict:
        out = {"fields": self.fields, "count": self.count, "got": self.got}
        if self.capped:
            out["capped"] = True
        if self.how:
            out["how"] = self.how
        if self.children:
            out["children"] = [c.to_json() for c in self.children]
        return out

    def total(self) -> int:
        self.got = sum(c.got for c in self.children)
        return self.got


class Crawler:
    """Обход справочника с кэшем ответов на диске.

    Каждый ответ ложится в `cache_dir/pages/<ключ>.html`: повторный запуск
    берёт его оттуда и продолжает с места обрыва. Пауза между обращениями к
    сайту — `pause` секунд. Записи сводятся по номеру записи сайта (`pid`).
    """

    def __init__(self, cache_dir: Path, *, pause: float = 1.0,
                 log: Callable[[str], None] = print, offline: bool = False) -> None:
        self.cache = Path(cache_dir)
        self.pause = pause
        self.log = log
        self.offline = offline
        self.requests = 0
        self.hits = 0
        self._last = 0.0
        self.records: dict[int, Raw] = {}
        self.kinds: set[str] = set(KNOWN_KINDS)
        self.big_kinds: set[str] = set()
        self.kind_counts: dict[str, int] = {}
        self.truncated: list[dict] = []

    # -- ответы ---------------------------------------------------------------

    def _get(self, url: str, fields: dict, key: str) -> bytes:
        path = self.cache / "pages" / f"{key}.html"
        if path.exists() and path.stat().st_size > 0:
            self.hits += 1
            return path.read_bytes()
        if self.offline:
            raise HospitalsError(f"в кэше нет ответа на {fields}, а сеть запрещена (--offline)")
        left = self.pause - (time.monotonic() - self._last)
        if left > 0:
            time.sleep(left)
        raw = post(url, fields)
        self._last = time.monotonic()
        self.requests += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return raw

    def page(self, fields: dict, number: int = 0, hidden: Optional[dict] = None) -> Page:
        """Страница `number` (с нуля) выдачи по образцу `fields`."""
        if number == 0:
            raw = self._get(SEARCH_URL, fields, query_key(fields, 0))
        else:
            form = hidden if hidden else fields
            raw = self._get(f"{SEARCH_URL}?page={number}", form, query_key(fields, number))
        page = parse_page(raw)
        for rec in page.records:
            self.records.setdefault(rec.pid, rec)
            if rec.kind:
                self.kinds.add(rec.kind)
        return page

    def all_pages(self, fields: dict, first: Optional[Page] = None) -> tuple[Page, list[Raw]]:
        """Вся выдача по образцу: первая страница и записи со всех страниц."""
        first = first or self.page(fields)
        recs = list(first.records)
        for number in range(1, first.pages):
            recs.extend(self.page(fields, number, first.hidden).records)
        return first, recs

    def edit(self, pid: int) -> Optional[Raw]:
        """Запись по её номеру — через форму правки (в собранное не добавляется)."""
        raw = self._get(EDIT_URL, {"pid": str(pid)}, f"edit-{pid}")
        return parse_edit(raw, pid)

    # -- дерево -----------------------------------------------------------------

    def leaf(self, fields: dict, first: Optional[Page] = None) -> Node:
        """Узел без дробления: выдача меньше 500, читается целиком."""
        first, recs = self.all_pages(fields, first)
        return Node(fields=dict(fields), count=first.count, got=len({r.pid for r in recs}))

    def node(self, fields: dict, then: Callable[[dict, Page], Node]) -> Optional[Node]:
        """Запрос по образцу: пусто — None, меньше 500 — лист, иначе — `then`."""
        p = self.page(fields)
        if not p.count:
            return None
        return then(fields, p) if p.capped else self.leaf(fields, p)

    def by_kind(self, base: dict, first: Page) -> Node:
        """Обрезанная выдача по району — точными типами учреждений.

        Берутся только крупные типы (больше 500 записей во всём справочнике):
        мелкие уже прочитаны целиком проходом по типам (`kinds_pass`), и
        запрашивать их ещё раз по каждой букве района незачем.
        """
        node = Node(fields=dict(base), count=first.count, capped=True, how="тип")
        for kind in sorted(self.big_kinds):
            child = self.node({**base, F_TYPE: kind}, self.by_place)
            if child:
                node.children.append(child)
        node.total()
        return node

    def kinds_pass(self) -> Node:
        """Каждый тип учреждения целиком: мелкий читается сразу, крупный —
        помечается и дальше дробится по району и месту."""
        root = Node(fields={}, count=0, how="тип")
        for kind in sorted(self.kinds):
            fields = {F_TYPE: kind}
            p = self.page(fields)
            self.kind_counts[kind] = p.count
            if not p.count:
                continue
            if p.capped:
                self.big_kinds.add(kind)
                root.children.append(Node(fields=fields, count=p.count, capped=True))
            else:
                root.children.append(self.leaf(fields, p))
        root.total()
        self.log(f"типы: {len(root.children)}, из них больше {CAP} записей — "
                 f"{len(self.big_kinds)}; запросов {self.requests}, записей {len(self.records)}")
        self.save()
        return root

    def discover_kinds(self) -> Node:
        """Типы, которых нет в перечне: счётчик по началу названия типа против
        суммы известных мелких типов с тем же началом.

        Не сошлось — выдача по образцу (меньше 500) читается целиком, и новые
        типы попадают в перечень. Где по первой букве выдача обрезана, то же
        делается по двум буквам; ячейку, обрезанную и по двум буквам, проверить
        нечем — в ней лежит крупный тип.
        """
        root = Node(fields={}, count=0, how="поиск типов")

        def known(prefix: str) -> int:
            return sum(n for k, n in self.kind_counts.items()
                       if fold(k).startswith(fold(prefix)) and k not in self.big_kinds)

        def probe(prefix: str) -> Optional[Page]:
            fields = {F_TYPE: prefix + "*"}
            p = self.page(fields)
            if p.count and not p.capped and p.count > known(prefix):
                self.all_pages(fields, p)
            if p.count:
                got = sum(1 for r in self.records.values()
                          if fold(r.kind).startswith(fold(prefix)))
                root.children.append(Node(fields=fields, count=p.count, got=got,
                                          capped=p.capped))
            return p

        for ch in FIRST:
            p = probe(ch)
            if p is not None and p.capped:
                for ch2 in NEXT:
                    probe(ch + ch2)
        self.log(f"поиск типов: известно {len(self.kinds)}; запросов {self.requests}")
        return root

    def by_place(self, base: dict, first: Page) -> Node:
        """Обрезанная выдача по району и типу — первой буквой места."""
        node = Node(fields=dict(base), count=first.count, capped=True, how="место")
        for ch in FIRST:
            child = self.node({**base, F_PLACE: ch + "*"},
                              lambda f, p, ch=ch: self.by_prefix(base, ch, p))
            if child:
                node.children.append(child)
        node.total()
        return node

    def by_prefix(self, base: dict, prefix: str, first: Page) -> Node:
        """Обрезанная выдача по началу места — следующей буквой.

        Точное значение, равное образцу, проверяется отдельно: «Москва» не
        попадёт ни в «Москва *», ни в «Москваа*».
        """
        node = Node(fields={**base, F_PLACE: prefix + "*"}, count=first.count, capped=True,
                    how="буква места")
        exact = self.node({**base, F_PLACE: prefix}, self.give_up)
        if exact:
            node.children.append(exact)
        for ch in NEXT:
            child = self.node({**base, F_PLACE: prefix + ch + "*"},
                              lambda f, p, ch=ch: self.by_prefix(base, prefix + ch, p))
            if child:
                node.children.append(child)
        node.total()
        return node

    def give_up(self, fields: dict, first: Page) -> Node:
        """Одно место, один тип, одна буква района — и всё равно больше 500.

        Дробить дальше нечем: номер сайт ищет только точным числом. Берутся
        первые 500, узел помечается обрезанным, отчёт его называет.
        """
        self.log(f"  ! {fields}: больше {CAP} записей и дробить нечем — взяты первые {CAP}")
        node = self.leaf(fields, first)
        node.capped, node.how = True, "обрезано"
        self.truncated.append(dict(fields))
        return node

    def crawl_regions(self) -> Node:
        """Обход по первой букве района дислокации; обрезанное — дробится."""
        root = Node(fields={}, count=0, how="район")
        for ch in FIRST:
            child = self.node({F_REGION: ch + "*"}, self.by_kind)
            self.log(f"район «{ch}»: {child.got if child else 0} записей — запросов "
                     f"{self.requests}, из кэша {self.hits}, всего записей {len(self.records)}")
            if child:
                root.children.append(child)
            self.save()
        root.total()
        root.count = root.got
        return root

    def reconcile(self) -> Node:
        """Сверка крупных типов: что тип показывает, а обход по районам не нашёл.

        В аннотации справочника сказано, что у части мест район не установлен,
        — такие записи обход по районам не видит. Мелкие типы прочитаны
        целиком и сверять их незачем; у крупного типа счётчик сайта по первой
        букве места сравнивается с найденным, у обрезанной ячейки «тип — буква»
        — по второй букве. Где найдено меньше, выдача читается целиком.
        """
        root = Node(fields={}, count=0, how="сверка по типам")
        for kind in sorted(self.big_kinds):
            fields = {F_TYPE: kind}
            p = self.page(fields)
            if not p.count:
                continue
            node = self._reconcile_cell(fields, p, lambda r, kind=kind: r.kind == kind)
            if p.capped:
                node.how = "место"
                for ch in FIRST:
                    f2 = {F_TYPE: kind, F_PLACE: ch + "*"}
                    p2 = self.page(f2)
                    if not p2.count:
                        continue
                    child = self._reconcile_cell(
                        f2, p2, lambda r, kind=kind, ch=ch: r.kind == kind
                        and fold(r.place).startswith(fold(ch)))
                    if p2.capped:
                        child.how = "буква места"
                        for ch2 in NEXT:
                            f3 = {F_TYPE: kind, F_PLACE: ch + ch2 + "*"}
                            p3 = self.page(f3)
                            if p3.count:
                                child.children.append(self._reconcile_cell(
                                    f3, p3, lambda r, kind=kind, pre=ch + ch2: r.kind == kind
                                    and fold(r.place).startswith(fold(pre))))
                    node.children.append(child)
            self.log(f"тип «{kind}»: на сайте {p.count}{'+' if p.capped else ''}, "
                     f"найдено {node.got} — всего записей {len(self.records)}")
            root.children.append(node)
            self.save()
        root.count = len(self.records)
        return root

    def _reconcile_cell(self, fields: dict, first: Page, match: Callable[[Raw], bool]) -> Node:
        """Ячейка сверки: найдено столько же, сколько показывает сайт, — ничего
        не делать; меньше (и выдача не обрезана) — прочитать её целиком."""
        have = sum(1 for r in self.records.values() if match(r))
        if not first.capped and have < first.count:
            self.all_pages(fields, first)
            have = sum(1 for r in self.records.values() if match(r))
        return Node(fields=dict(fields), count=first.count, got=have, capped=first.capped)

    def crawl(self, *, rounds: int = 4) -> dict:
        """Типы целиком (с поиском неизвестных), обход по районам и сверка
        крупных типов — круг за кругом, пока перечень типов растёт: новый тип
        находится и в записях обхода. Повторный круг идёт из кэша."""
        trees = {}
        for _ in range(rounds):
            kinds_before = set(self.kinds)
            trees["kinds"] = self.kinds_pass()
            trees["discovery"] = self.discover_kinds()
            if self.kinds != kinds_before:
                self.log(f"новые типы: {sorted(self.kinds - kinds_before)}")
                continue
            trees["regions"] = self.crawl_regions()
            trees["types"] = self.reconcile()
            if self.kinds == kinds_before:
                break
            self.log(f"новые типы: {sorted(self.kinds - kinds_before)} — ещё круг из кэша")
        self.save(trees)
        return trees

    # -- кэш записей -------------------------------------------------------------

    def save(self, trees: Optional[dict] = None) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        payload = [r.to_json() for r in sorted(self.records.values(), key=lambda r: r.pid)]
        (self.cache / "records.json").write_text(json.dumps(payload, ensure_ascii=False),
                                                encoding="utf-8")
        if trees:
            (self.cache / "tree.json").write_text(
                json.dumps({k: v.to_json() for k, v in trees.items()}, ensure_ascii=False),
                encoding="utf-8")


def load_records(cache_dir: Path) -> list[Raw]:
    """Записи справочника: сводка обхода и всё, что лежит в кэше ответов.

    Сводка `records.json` пишется после каждого узла обхода, а прерванный
    обход успевает скачать ещё страницы после последней записи сводки, —
    поэтому записи берутся и со всех страниц кэша, по номеру записи.
    """
    cache_dir = Path(cache_dir)
    out: dict[int, Raw] = {}
    path = cache_dir / "records.json"
    if path.exists():
        for d in json.loads(path.read_text(encoding="utf-8")):
            rec = Raw.from_json(d)
            out[rec.pid] = rec
    for page_path in sorted((cache_dir / "pages").glob("*.html")):
        if page_path.name.startswith("edit-"):
            continue
        try:
            page = parse_page(page_path.read_bytes())
        except HospitalsError:
            continue
        for rec in page.records:
            out.setdefault(rec.pid, rec)
    if not out:
        raise HospitalsError(f"{cache_dir}: нет собранных записей — сначала --fetch")
    return [out[pid] for pid in sorted(out)]


def check_tree(node: Node) -> list[str]:
    """Узлы, где число записей не сошлось со счётчиком сайта.

    Сверяется только необрезанный счётчик: у обрезанного (500) сравнивать не
    с чем. Лист сверяется с тем, сколько записей пришло со всех его страниц.
    """
    problems = []
    for child in node.children:
        problems.extend(check_tree(child))
    if node.fields and not node.capped and node.got != node.count:
        problems.append(f"{node.fields}: счётчик {node.count}, найдено {node.got}")
    return problems


def missing_pids(pids: Iterable[int]) -> list[int]:
    """Номера записей между первым и последним, которых нет в собранном."""
    have = sorted(set(pids))
    if not have:
        return []
    present = set(have)
    return [p for p in range(have[0], have[-1] + 1) if p not in present]


# --- район дислокации: что он значит сегодня -------------------------------------

# Государства в Викиданных, где ищется место дислокации.
COUNTRIES = {
    "Россия": "Q159", "Украина": "Q212", "Белоруссия": "Q184", "Молдавия": "Q217",
    "Литва": "Q37", "Латвия": "Q211", "Эстония": "Q191", "Азербайджан": "Q227",
    "Армения": "Q399", "Грузия": "Q230", "Казахстан": "Q232", "Узбекистан": "Q265",
    "Киргизия": "Q813", "Таджикистан": "Q863", "Туркмения": "Q874", "Абхазия": "Q23334",
    "Польша": "Q36", "Германия": "Q183", "Австрия": "Q40", "Венгрия": "Q28",
    "Румыния": "Q218", "Болгария": "Q219", "Чехия": "Q213", "Словакия": "Q214",
    "Сербия": "Q403", "Хорватия": "Q224", "Словения": "Q215", "Босния и Герцеговина": "Q225",
    "Черногория": "Q236", "Северная Македония": "Q221", "Финляндия": "Q33",
    "Норвегия": "Q20", "Монголия": "Q711", "Иран": "Q794", "Китай": "Q148",
    "КНДР": "Q423", "Республика Корея": "Q884", "Япония": "Q17",
}
USSR = ("Россия", "Украина", "Белоруссия", "Молдавия", "Литва", "Латвия", "Эстония",
        "Азербайджан", "Армения", "Грузия", "Казахстан", "Узбекистан", "Киргизия",
        "Таджикистан", "Туркмения", "Абхазия")

# Районы дислокации, которые называют государство, а не область, — и то, где
# они лежат сегодня. Восточная Пруссия — нынешние Калининградская область,
# север Польши и Клайпедский край Литвы.
STATE_REGIONS = {
    "Азербайджанская ССР": ("Азербайджан",), "Армянская ССР": ("Армения",),
    "Грузинская ССР": ("Грузия", "Абхазия"), "Казахская ССР": ("Казахстан",),
    "Узбекская ССР": ("Узбекистан",), "Киргизская ССР": ("Киргизия",),
    "Таджикская ССР": ("Таджикистан",), "Туркменская ССР": ("Туркмения",),
    "Эстонская ССР": ("Эстония",), "Латвийская ССР": ("Латвия",),
    "Литовская ССР": ("Литва",), "Молдавская ССР": ("Молдавия", "Украина"),
    "Абхазская АССР": ("Абхазия", "Грузия"), "Аджарская АССР": ("Грузия",),
    "Нахичеванская АССР": ("Азербайджан",), "Австрия": ("Австрия",),
    # Государства 1944–1945 годов шире нынешних: Венгрия держала юг Словакии,
    # Закарпатье и Северную Трансильванию, Германия — Судеты, Мемель и земли,
    # отошедшие Польше и СССР, Румыния — Бессарабию и Буковину.
    "Болгария": ("Болгария",),
    "Венгрия": ("Венгрия", "Словакия", "Румыния", "Украина", "Сербия", "Австрия"),
    "Германия": ("Германия", "Польша", "Россия", "Чехия", "Литва"),
    "Восточная Пруссия": ("Россия", "Польша", "Литва"),
    "Польша": ("Польша", "Украина", "Белоруссия", "Германия", "Литва"),
    "Румыния": ("Румыния", "Молдавия", "Украина"),
    "Чехословакия": ("Чехия", "Словакия", "Украина"),
    "Югославия": ("Сербия", "Хорватия", "Словения", "Босния и Герцеговина", "Черногория",
                  "Северная Македония"),
    "Финляндия": ("Финляндия", "Россия"), "Норвегия": ("Норвегия",),
    "Монголия": ("Монголия",), "Иран": ("Иран",), "Китай": ("Китай",),
    "Маньчжурия": ("Китай",), "Корея": ("КНДР", "Республика Корея"),
    "БССР": ("Белоруссия", "Польша"), "УССР": ("Украина",), "РСФСР": ("Россия",),
}

# Области военного времени были больше нынешних: Астрахань до 1943 года
# лежала в Сталинградской области, Кемерово — в Новосибирской, Курган — в
# Челябинской, Новгород и Псков — в Ленинградской. Здесь — что ещё, кроме
# области с тем же названием, принимается за «этот район».
WIDER_REGIONS = {
    "Сталинградская область": ("Волгоградская область", "Астраханская область",
                               "Калмыкия"),
    "Ленинградская область": ("Санкт-Петербург", "Новгородская область",
                              "Псковская область", "Мурманская область"),
    "Московская область": ("Москва",),
    "Новосибирская область": ("Кемеровская область", "Томская область"),
    "Челябинская область": ("Курганская область",),
    "Омская область": ("Тюменская область", "Ханты-Мансийский автономный округ — Югра",
                       "Ямало-Ненецкий автономный округ"),
    "Куйбышевская область": ("Ульяновская область",),
    "Ярославская область": ("Костромская область",),
    "Ивановская область": ("Владимирская область", "Костромская область"),
    "Калининская область": ("Псковская область", "Новгородская область"),
    "Орловская область": ("Брянская область", "Липецкая область", "Курская область"),
    "Курская область": ("Белгородская область",),
    "Воронежская область": ("Липецкая область", "Тамбовская область", "Белгородская область"),
    "Смоленская область": ("Брянская область", "Калужская область"),
    "Тульская область": ("Калужская область",),
    "Хабаровский край": ("Амурская область", "Сахалинская область", "Камчатский край",
                         "Магаданская область", "Еврейская автономная область"),
    "Приморский край": ("Хабаровский край",),
    "Красноярский край": ("Хакасия",), "Алтайский край": ("Республика Алтай",),
    "Крымская АССР": ("Севастополь",),
}
# Города федерального значения в Викиданных не входят в области: у Ленинграда
# в цепочке подчинения нет Ленинградской области.
FEDERAL_CITIES = {"Q656": "Ленинградская область", "Q649": "Московская область",
                  "Q7525": "Крымская АССР"}

# Области военного времени — нынешним названием в цепочке подчинения (P131)
# Викиданных. Совпадающие названия («Вологодская область») сюда не вносятся:
# их проверяет основа названия.
RENAMED_REGIONS = {
    "Молотовская область": ("Пермский край", "Пермская область"),
    "Чкаловская область": ("Оренбургская область",),
    "Куйбышевская область": ("Самарская область",),
    "Горьковская область": ("Нижегородская область",),
    "Калининская область": ("Тверская область",),
    "Сталинградская область": ("Волгоградская область",),
    "Ворошиловградская область": ("Луганская область",),
    "Сталинская область": ("Донецкая область",),
    "Каменец-Подольская область": ("Хмельницкая область",),
    "Измаильская область": ("Одесская область",),
    "Ворошиловский край": ("Ставропольский край",),
    "Орджоникидзевский край": ("Ставропольский край",),
    "Полесская область": ("Гомельская область",),
    "Барановичская область": ("Брестская область", "Гродненская область", "Минская область"),
    "Белостокская область": ("Подляское воеводство", "Гродненская область"),
    "Вилейская область": ("Минская область", "Витебская область"),
    "Молодечненская область": ("Минская область", "Витебская область", "Гродненская область"),
    "Пинская область": ("Брестская область",),
    "Бобруйская область": ("Могилёвская область", "Гомельская область", "Минская область"),
    "Полоцкая область": ("Витебская область",),
    "Грозненская область": ("Чечня", "Ставропольский край", "Дагестан"),
    "Крымская АССР": ("Крым", "Республика Крым", "Автономная Республика Крым"),
    "Крымская область": ("Крым", "Республика Крым", "Автономная Республика Крым"),
    "Татарская АССР": ("Татарстан",), "Башкирская АССР": ("Башкортостан",),
    "Удмуртская АССР": ("Удмуртия",), "Марийская АССР": ("Марий Эл",),
    "Чувашская АССР": ("Чувашия",), "Мордовская АССР": ("Мордовия",),
    "Коми АССР": ("Республика Коми",), "Карело-Финская ССР": ("Карелия",),
    "Бурят-Монгольская АССР": ("Бурятия",), "Якутская АССР": ("Якутия",),
    "Дагестанская АССР": ("Дагестан",), "Северо-Осетинская АССР": ("Северная Осетия",),
    "Кабардинская АССР": ("Кабардино-Балкария",),
    "Кабардино-Балкарская АССР": ("Кабардино-Балкария",),
    "Чечено-Ингушская АССР": ("Чечня", "Ингушетия"), "Калмыцкая АССР": ("Калмыкия",),
    "АССР Немцев Поволжья": ("Саратовская область", "Волгоградская область"),
    "Еврейская АО": ("Еврейская автономная область",),
    "Ойротская АО": ("Республика Алтай",),
    "Хакасская АО": ("Хакасия",),
    "Адыгейская АО": ("Адыгея",),
    "Карачаевская АО": ("Карачаево-Черкесия",),
    "Черкесская АО": ("Карачаево-Черкесия",),
    "Тувинская АО": ("Тыва",),
}

# Республики, в которые сокращения района ставят приставкой: «БССР, Гомельская
# область», «УССР, Сумская область», «Узсср, Самаркандская область».
_RE_REPUBLIC_PREFIX = re.compile(r"^\s*(БССР|УССР|Узсср|УзССР|КазССР|ГССР|АзССР)\s*,\s*", re.I)
PREFIX_COUNTRIES = {"бсср": ("Белоруссия", "Польша"), "усср": ("Украина",),
                    "узсср": ("Узбекистан",), "казсср": ("Казахстан",), "гсср": ("Грузия",),
                    "азсср": ("Азербайджан",)}


@dataclass(frozen=True)
class RegionHint:
    """Что район дислокации говорит о месте: государства и названия единиц."""

    raw: str
    name: str = ""                 # район без приставки республики
    countries: tuple = ()          # названия из COUNTRIES; пусто — весь СССР
    units: tuple = ()              # нынешние названия области (цепочка P131)
    stem: Optional[str] = None     # основа названия области («вологодск»)
    wider: tuple = ()              # что ещё входило в область военного времени

    @property
    def known(self) -> bool:
        return bool(self.units or self.stem or self.countries)


def region_hint(region: Optional[str]) -> RegionHint:
    """Район дислокации военного времени — к тому, по чему проверяется точка."""
    raw = (region or "").strip()
    if not raw:
        return RegionHint(raw="")
    countries: tuple = ()
    m = _RE_REPUBLIC_PREFIX.match(raw)
    name = raw
    if m:
        countries = PREFIX_COUNTRIES.get(m.group(1).lower(), ())
        name = raw[m.end():].strip()
    # «Китай, Маньчжурия» → «Китай»; «Восточная Пруссия (Польша)» → «Восточная
    # Пруссия»; «БССР» без области — вся республика.
    plain = re.sub(r"\([^()]*\)", " ", name)
    head = plain.split(",")[0].strip()
    for key in (name, plain.strip(), head):
        if key in STATE_REGIONS:
            return RegionHint(raw=raw, name=name, countries=STATE_REGIONS[key])
    if not name and countries:
        return RegionHint(raw=raw, name=name, countries=countries)
    units = RENAMED_REGIONS.get(name, ())
    stem = None
    words = name.split()
    if not units and len(words) >= 2 and words[-1].lower() in ("область", "край", "округ"):
        # «Вологодская область» → «вологодск»; «Алтайский край» → «алтайск».
        stem = re.sub(r"(ая|ий|ой)$", "", words[0].lower())
    return RegionHint(raw=raw, name=name, countries=countries, units=units, stem=stem,
                      wider=WIDER_REGIONS.get(name, ()))


# --- место дислокации: названия для поиска -----------------------------------------

# Слова, которыми справочник уточняет вид места: «Бьйорке, Остров», «Ольга,
# Бухта», «Краснофлотский (Форт)». По ним точка не ищется — искать надо само
# название, — но вид идёт в запись.
_FEATURE_WORDS = ("остров", "острова", "бухта", "форт", "мыс", "полуостров", "залив",
                  "губа", "колония", "совхоз", "разъезд", "станция", "ст.", "пос.")


# Города, переименованные после войны, — нынешним названием: у Санкт-
# Петербурга в Викиданных нет русского «другого названия» «Ленинград», и
# без этой подсказки самый частый город справочника не нашёлся бы.
CITY_ALIASES = {
    "Ленинград": "Санкт-Петербург", "Сталинград": "Волгоград", "Горький": "Нижний Новгород",
    "Куйбышев": "Самара", "Свердловск": "Екатеринбург", "Молотов": "Пермь",
    "Калинин": "Тверь", "Чкалов": "Оренбург", "Ворошиловград": "Луганск",
    "Сталино": "Донецк", "Сталинабад": "Душанбе", "Фрунзе": "Бишкек",
    "Орджоникидзе": "Владикавказ", "Молотовск": "Северодвинск",
    "Сталиногорск": "Новомосковск", "Ленинакан": "Гюмри", "Кировабад": "Гянджа",
    "Красноводск": "Туркменбашы", "Чарджоу": "Туркменабат", "Алма-Ата": "Алматы",
    "Акмолинск": "Астана", "Гурьев": "Атырау", "Семипалатинск": "Семей",
    "Днепропетровск": "Днепр", "Проскуров": "Хмельницкий", "Станислав": "Ивано-Франковск",
    "Кировоград": "Кропивницкий", "Кирово": "Кропивницкий",
    "Ворошилов": "Уссурийск", "Ново-Сибирск": "Новосибирск",
    "Куйбышевка-Восточная": "Белогорск",
    # Немецкие названия 1945 года — нынешние польские, русские и литовские
    # (самые частые в справочнике места без точки; в Викиданных у этих
    # городов нет русского «другого названия» по-немецки).
    "Ландсберг": ("Гожув-Велькопольский", "Гожув-Велькопольски"),
    "Хайльсберг": ("Лидзбарк-Варминьский", "Лидзбарк-Варминьски"),
    "Дойтш-Айлау": "Илава", "Дейтш-Айлау": "Илава", "Хейнрихсвальде": "Славск",
    "Реппен": "Жепин", "Шлохау": "Члухув", "Дейтш-Кроне": "Валч", "Дойтш-Кроне": "Валч",
    "Вольденберг": "Добегнев", "Леобщютц": "Глубчице", "Кенигсберг-На-Одере": "Хойна",
    "Ельс": "Олесница", "Эльс": "Олесница", "Кезлин": "Кошалин", "Ной-Руппин": "Нойруппин",
    "Бреслау": "Вроцлав", "Штеттин": "Щецин", "Данциг": "Гданьск", "Позен": "Познань",
    "Бромберг": "Быдгощ", "Торн": "Торунь", "Эльбинг": "Эльблонг", "Алленштейн": "Ольштын",
    "Инстербург": "Черняховск", "Тильзит": "Советск", "Гумбиннен": "Гусев",
    "Кенигсберг": "Калининград", "Пиллау": "Балтийск", "Кранц": "Зеленоградск",
    "Раушен": "Светлогорск", "Тапиау": "Гвардейск", "Велау": "Знаменск",
    "Мемель": "Клайпеда", "Растенбург": "Кентшин", "Лык": "Элк", "Бартенштейн": "Бартошице",
    "Прейсиш-Эйлау": "Багратионовск", "Пр.Эйлау": "Багратионовск",
    "Франкфурт На Одере": "Франкфурт-на-Одере", "Франкфурт-На-Одере": "Франкфурт-на-Одере",
}


def place_names(place: str) -> list[str]:
    """Названия, по которым ищется место: основное и то, что в скобках.

    «Мариуполь (Жданов)» → [«Мариуполь», «Жданов»]; «Даго, Остров (Кярдла)» →
    [«Даго», «Кярдла»]; «Рыбинск (Щербаков)» → [«Рыбинск», «Щербаков»]. У
    переименованного города нынешнее название идёт следом (`CITY_ALIASES`).
    """
    names = _place_names(place)
    out = list(names)
    for name in names:
        alias = CITY_ALIASES.get(name, ())
        for item in (alias,) if isinstance(alias, str) else alias:
            if item not in out:
                out.append(item)
    return out


def _place_names(place: str) -> list[str]:
    text = (place or "").strip()
    if not text:
        return []
    inner = [s.strip() for s in re.findall(r"\(([^()]+)\)", text)]
    main = re.sub(r"\([^()]*\)", " ", text)
    parts = [p.strip() for p in main.split(",")]
    out = []
    for part in parts + inner:
        words = part.split()
        while words and words[0].lower() in _FEATURE_WORDS:
            words = words[1:]
        while words and words[-1].lower() in _FEATURE_WORDS:
            words = words[:-1]
        name = " ".join(words).strip(" .-")
        if name and name.lower() not in _FEATURE_WORDS and not name.startswith("Г."):
            out.append(name)
        elif name.startswith("Г."):
            out.append(name[2:].strip())
    return list(dict.fromkeys(n for n in out if len(n) > 1))


# --- кандидаты из Викиданных -----------------------------------------------------

_RE_POINT = re.compile(r"Point\(([-\d.eE]+)\s+([-\d.eE]+)\)")
# «Район» и «округ» взяты ради районов городов за границей (Чепель и Уйпешт —
# районы Будапешта, Флоридсдорф — Вены): название сверяется точно, и
# «Шипуновский район» с местом «Шипуново» так не спутать.
SETTLEMENT_WORDS = ("город", "посёлок", "поселок", "село", "деревня", "станица", "местечко",
                    "населённый пункт", "населенный пункт", "хутор", "агрогородок", "аул",
                    "курорт", "район", "округ", "микрорайон", "столица", "станция",
                    "железнодорожн", "порт", "остров", "бухта", "форт", "крепость",
                    "кишлак", "коммуна", "гмина", "община", "волость", "аал", "слобода",
                    "выселок", "починок", "поселение", "местность")
_RE_TOWN_TYPE = re.compile(r"(?:^|\s)город(?:\s|$)|^посёлок городского типа|столица|"
                           r"мегаполис|административный центр")


def name_key(name: Optional[str]) -> str:
    """Ключ сравнения названий: без регистра, «ё», скобок и дефисов."""
    if not name:
        return ""
    s = name.lower().replace("ё", "е")
    s = re.sub(r"\([^()]*\)", " ", s)
    s = re.sub(r"[^а-яa-z0-9іїєґ]+", " ", s)
    return s.strip()


def wikidata_query(names: Iterable[str]) -> str:
    """Кандидаты по точному русскому названию: метка или другое название,
    с государством, типом, населением и цепочкой подчинения."""
    values = " ".join(f'"{n}"@ru' for n in names if '"' not in n and "\\" not in n)
    countries = " ".join(f"wd:{q}" for q in COUNTRIES.values())
    return f"""SELECT ?name ?item ?coord ?country ?typeLabel ?pop ?ancLabel WHERE {{
  VALUES ?name {{ {values} }}
  {{ ?item rdfs:label ?name }} UNION {{ ?item skos:altLabel ?name }}
  ?item wdt:P17 ?country .
  VALUES ?country {{ {countries} }}
  ?item wdt:P625 ?coord .
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel .
             FILTER(LANG(?typeLabel) = "ru") }}
  OPTIONAL {{ ?item wdt:P1082 ?pop . }}
  OPTIONAL {{ ?item wdt:P131+ ?anc . ?anc rdfs:label ?ancLabel .
             FILTER(LANG(?ancLabel) = "ru") }}
}}"""


@dataclass
class Candidate:
    """Кандидат в точку места: объект Викиданных или место GeoNames."""

    source: str
    ident: str
    title: str
    lat: float
    lon: float
    country: Optional[str] = None
    population: int = 0
    types: set = field(default_factory=set)
    ancestors: set = field(default_factory=set)

    @property
    def is_place(self) -> bool:
        if self.source == "geonames" or not self.types:
            return True
        return any(any(w in t for w in SETTLEMENT_WORDS) for t in self.types)

    @property
    def is_town(self) -> bool:
        if self.source == "geonames":
            return self.population >= 5000
        return any(_RE_TOWN_TYPE.search(t) for t in self.types)

    @property
    def coord_source(self) -> str:
        return f"{'Викиданные' if self.source == 'wikidata' else 'GeoNames'} {self.ident}"


_COUNTRY_BY_QID = {q: name for name, q in COUNTRIES.items()}


def candidates_from_rows(rows: Iterable[dict]) -> dict[str, list[Candidate]]:
    """Строки SPARQL — в кандидатов по искомому названию (ключ `name_key`)."""
    by_item: dict[tuple[str, str], Candidate] = {}
    for row in rows:
        name = row.get("name", {}).get("value")
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        point = _RE_POINT.match(row.get("coord", {}).get("value", ""))
        if not name or not qid.startswith("Q") or not point:
            continue
        key = (name_key(name), qid)
        cand = by_item.get(key)
        if cand is None:
            country = row.get("country", {}).get("value", "").rsplit("/", 1)[-1]
            cand = Candidate("wikidata", qid, name, float(point.group(2)), float(point.group(1)),
                             _COUNTRY_BY_QID.get(country))
            by_item[key] = cand
        t = row.get("typeLabel", {}).get("value")
        if t:
            cand.types.add(t.lower())
        anc = row.get("ancLabel", {}).get("value")
        if anc:
            cand.ancestors.add(anc)
        pop = row.get("pop", {}).get("value")
        if pop:
            try:
                cand.population = max(cand.population, int(float(pop)))
            except ValueError:
                pass
    out: dict[str, list[Candidate]] = {}
    for (key, _), cand in by_item.items():
        if cand.is_place:
            out.setdefault(key, []).append(cand)
    return out


def geonames_index(features: Iterable[dict], variants: Optional[dict] = None) -> dict:
    """Слой `settlements` (GeoNames) — указатель по названию и написаниям."""
    out: dict[str, list[Candidate]] = {}
    variants = variants or {}
    for feat in features:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        gid = str(props.get("source_id") or "")
        if len(coords) < 2 or not gid:
            continue
        extra = props.get("extra") or {}
        base = dict(source="geonames", ident=gid, title=props.get("title") or "",
                    lat=float(coords[1]), lon=float(coords[0]), country=extra.get("country"),
                    population=int(extra.get("population_modern") or 0))
        keys = {name_key(base["title"])}
        keys.update(name_key(n) for n in (variants.get(gid) or {}).get("names") or [])
        for key in keys:
            if key:
                out.setdefault(key, []).append(Candidate(**base))
    return out


def _fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def fits(cand: Candidate, hint: RegionHint) -> bool:
    """Лежит ли кандидат в районе дислокации — по государству и области.

    Область военного времени шире нынешней (`WIDER_REGIONS`), а город
    федерального значения в своей области не числится (`FEDERAL_CITIES`).
    """
    if hint.countries and cand.country not in hint.countries:
        return False
    if not hint.countries and cand.country and cand.country not in USSR:
        return False
    if not (hint.units or hint.stem):
        return True
    if FEDERAL_CITIES.get(cand.ident) == hint.name:
        return True
    anc = {_fold(a) for a in cand.ancestors}
    # Метка единицы в Викиданных бывает длиннее: «Республика Карелия»,
    # «Республика Северная Осетия — Алания» — поэтому вхождение, а не равенство.
    if any(_fold(u) in a for u in hint.units + hint.wider for a in anc):
        return True
    if hint.stem:
        stem = _fold(hint.stem)
        return any(stem in a for a in anc)
    return False


def query_variants(name: str) -> list[str]:
    """Написания для точного сравнения с метками Викиданных.

    Метки чувствительны к регистру и к «ё»: справочник пишет «Ростов-На-Дону»
    и «Артемовск», метка — «Ростов-на-Дону» и «Артёмовск». Добавляются
    написание со служебными словами строчными и по одной замене «е» на «ё».
    """
    out = [name]
    parts = re.split(r"([- ])", name)
    service = ("на", "над", "под", "у", "де", "и", "по")
    fixed = "".join(p.lower() if p.lower() in service and i else p
                    for i, p in enumerate(parts))
    out.append(fixed)
    # «Франкфурт на Одере» → «Франкфурт-на-Одере»; «Ново-Хоперск» → «Новохоперск».
    out.append(re.sub(r"\s+(на|над|под)\s+", r"-\1-", fixed))
    out.append(re.sub(r"^(Ново|Старо|Верхне|Нижне|Средне|Велико|Мало|Красно|Бело|Черно)-"
                      r"([А-ЯЁа-яё])", lambda m: m.group(1) + m.group(2).lower(), fixed))
    for base in list(dict.fromkeys(out)):
        for i, ch in enumerate(base):
            if ch in "еЕ":
                out.append(base[:i] + ("ё" if ch == "е" else "Ё") + base[i + 1:])
    return list(dict.fromkeys(out))


def _rank(c: Candidate) -> tuple:
    return (not c.is_town, c.source != "wikidata", -c.population)


def same_place(cands: list[Candidate], km: float = 15.0) -> bool:
    """Все кандидаты — одно место: каждый в `km` от первого."""
    if not cands:
        return False
    top = cands[0]
    return all(haversine_km(top.lat, top.lon, c.lat, c.lon) <= km for c in cands)


@dataclass
class Placement:
    """Итог сведения места дислокации с точкой."""

    candidate: Optional[Candidate]
    how: str


def _pick(cands: list[Candidate]) -> tuple[Optional[Candidate], bool]:
    """Лучший кандидат и то, однозначен ли выбор: одно место или один город
    среди сёл. Два города-тёзки или одни сёла в разных местах — неоднозначно."""
    cands = sorted(cands, key=_rank)
    if same_place(cands):
        return cands[0], True
    towns = [c for c in cands if c.is_town]
    if towns and same_place(towns):
        return towns[0], True
    return cands[0], False


def choose(names: list[str], hint: RegionHint, wd: dict, gn: dict) -> Placement:
    """Точка места дислокации.

    Викиданные — с проверкой района: область по цепочке подчинения, республика
    или зарубежное государство — по стране. Внутри области берётся лучший
    кандидат и тёзки, если они есть, отмечаются; по одной стране или вовсе без
    района — только однозначный выбор. GeoNames цепочки подчинения не знает:
    его кандидат берётся по государству и только однозначный.
    """
    by_unit = bool(hint.units or hint.stem)
    for name in names:
        cands = [c for c in wd.get(name_key(name), []) if fits(c, hint)]
        if not cands:
            continue
        found, sure = _pick(cands)
        if sure:
            return Placement(found, f"Викиданные, «{name}»"
                             + ("" if hint.known else ", район не указан"))
        if by_unit:
            return Placement(found, f"Викиданные, «{name}», тёзки в той же области — "
                                    f"выбран больший")
    if by_unit:
        # В названной области кандидата нет: справочник мог дать область по
        # другому делению. Берётся только однозначный кандидат в государстве.
        loose = RegionHint(raw=hint.raw, name=hint.name, countries=hint.countries)
        for name in names:
            cands = [c for c in wd.get(name_key(name), []) if fits(c, loose)]
            found, sure = _pick(cands) if cands else (None, False)
            if sure:
                return Placement(found, f"Викиданные, «{name}», единственный, "
                                        "но не в названной области")
    for name in names:
        pool = [c for c in gn.get(name_key(name), [])
                if (c.country in hint.countries if hint.countries else c.country in USSR)]
        if not pool:
            continue
        found, sure = _pick(pool)
        if sure:
            return Placement(found, f"GeoNames, «{name}», единственный в "
                             + ("государстве" if hint.countries else "СССР")
                             + (", область не проверена" if by_unit else ""))
    return Placement(None, ("не сведено: " + ", ".join(names)) if names else "место не указано")


# --- записи --------------------------------------------------------------------

# Тип учреждения — так, как его пишут в донесениях и на карточках раненых:
# «ЭГ 3870», «ХППГ 4212». Полное название типа — в `category`.
KIND_SHORT = {
    "Эвакуационный госпиталь": "Эвакогоспиталь",
    "Хирургический полевой подвижной госпиталь": "ХППГ",
    "Хирургический полевой подвижный госпиталь": "ХППГ",
    "Полевой подвижной госпиталь": "ППГ",
    "Полевой подвижный госпиталь": "ППГ",
    "Терапевтический полевой подвижной госпиталь": "ТППГ",
    "Корпусной подвижной госпиталь": "КПГ",
    "Армейский госпиталь легкораненых": "Госпиталь легкораненых",
    "Армейский полевой госпиталь": "Армейский полевой госпиталь",
    "Медико-санитарный батальон": "Медсанбат",
    "Госпиталь для инвалидов Отечественной войны": "Госпиталь для инвалидов войны",
    "Больница для инвалидов Отечественной войны": "Больница для инвалидов войны",
    "Управление головного полевого эвакуационного пункта с эвакоприемником": "Управление ГПЭП",
    "Эвакуационный приемник": "Эвакоприёмник",
    "Больница (разные)": "Больница",
    "Институт (разные)": "Институт",
    "Клиника (разные)": "Клиника",
}

MONTHS_GEN = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
              7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
              12: "декабря"}
MONTHS_NOM = {1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
              7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь",
              12: "декабрь"}

# Пометка «в справочнике так: на 15.07.44» — справочник знает одно число
# (или месяц: «на 00.07.44»), а поля «с» и «по» заполнены для формы.
_RE_SNAPSHOT = re.compile(r"(?:^|\s)на\s+(\d{2})\.(\d{2})\.(\d{2,4})")
_RE_FORMATION = re.compile(r"(\d+)\s*формирован", re.I)


def snapshot(note: Optional[str]) -> tuple[Optional[dt.date], str]:
    """День (или месяц) из пометки «на ДД.ММ.ГГ»; нет пометки — (None, '')."""
    m = _RE_SNAPSHOT.search(note or "")
    if not m:
        return None, ""
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 1900 if y < 100 else y
    if not 1 <= mo <= 12:
        return (dt.date(y, 1, 1), "year") if 1930 < y < 1960 else (None, "")
    if d == 0:
        return dt.date(y, mo, 1), "month"
    try:
        return dt.date(y, mo, d), "day"
    except ValueError:
        return dt.date(y, mo, 1), "month"


def human(day: dt.date, prec: str) -> str:
    if prec == "day":
        return f"{day.day} {MONTHS_GEN[day.month]} {day.year}"
    if prec == "month":
        return f"{MONTHS_NOM[day.month]} {day.year}"
    return f"{day.year}"


_PRECISION_ORDER = ("day", "month", "year")


def coarser(a: str, b: str) -> str:
    return max(a or "day", b or "day", key=_PRECISION_ORDER.index)


@dataclass
class Span:
    """Срок дислокации, приведённый к годам схемы."""

    year_from: int
    year_to: int
    precision: str
    period_raw: str
    text: str
    snapshot: Optional[str] = None


def span(raw: Raw) -> Span:
    """Годы, точность и подпись срока; недостающий конец — из рамки справочника."""
    start = dt.date.fromisoformat(raw.start) if raw.start else None
    end = dt.date.fromisoformat(raw.end) if raw.end else None
    p_start = parse_date(raw.start_raw)[1] if start else ""
    p_end = parse_date(raw.end_raw)[1] if end else ""
    shot, p_shot = snapshot(raw.note)
    parts = []
    if raw.start_raw:
        parts.append(f"с {raw.start_raw}")
    if raw.end_raw:
        parts.append(f"по {raw.end_raw}")
    period_raw = " ".join(parts)
    if shot and (not start or not end or start == end):
        note = re.search(r"на\s+[\d.]+", raw.note or "")
        return Span(shot.year, shot.year, p_shot, (period_raw + "; " if period_raw else "")
                    + (note.group(0) if note else ""), f"на {human(shot, p_shot)}",
                    snapshot=shot.isoformat())
    if start and end:
        a, b = (start, end) if start <= end else (end, start)
        prec = coarser(p_start, p_end)
        text = (f"с {human(a, p_start)} по {human(b, p_end)}" if a != b
                else f"{human(a, prec)}")
        return Span(a.year, b.year, prec, period_raw, text)
    if end:
        return Span(min(YEAR_MIN, end.year), end.year, "open", period_raw,
                    f"по {human(end, p_end)}; начало справочник не называет")
    if start:
        return Span(start.year, max(YEAR_MAX, start.year), "open", period_raw,
                    f"с {human(start, p_start)}; конец справочник не называет")
    return Span(YEAR_MIN, YEAR_MAX, "era", "даты не указаны",
                "даты справочник не называет — рамка войны")


def short_number(number: str) -> Optional[str]:
    n = (number or "").strip()
    return None if not n or n.upper() in ("Б/Н", "Б/Н.", "0") else n


def title(raw: Raw) -> str:
    kind = KIND_SHORT.get(raw.kind, raw.kind) or "Лечебное учреждение"
    num = short_number(raw.number)
    names = place_names(raw.place)
    where = names[0] if names else (raw.place or "место не указано")
    return f"{kind}{f' № {num}' if num else ''} — {where}"


def record(raw: Raw, place: Placement, spec: LayerSpec = MILITARY_HOSPITALS) -> ContextRecord:
    s = span(raw)
    cand = place.candidate
    num = short_number(raw.number)
    formation = _RE_FORMATION.search(raw.note or "")
    where = ", ".join(p for p in (raw.place, raw.region) if p) or "место не указано"
    summary = f"{raw.kind or 'Лечебное учреждение'}{f' № {num}' if num else ''}: {where}; {s.text}"
    extra = {
        "pid": raw.pid,
        "number": num,
        "number_raw": raw.number if raw.number and raw.number != num else None,
        "region_wartime": raw.region or None,
        "start": raw.start, "end": raw.end,
        "snapshot": s.snapshot,
        "note": raw.note,
        "formation": int(formation.group(1)) if formation else None,
        "place_match": place.how,
        "coord_source": cand.coord_source if cand else None,
    }
    return spec.new_record(
        title=title(raw),
        category=raw.kind or "лечебное учреждение",
        lat=round(cand.lat, 6) if cand else None,
        lon=round(cand.lon, 6) if cand else None,
        place_text=where,
        year_from=s.year_from, year_to=s.year_to,
        date_precision=s.precision,
        period_raw=s.period_raw,
        work="Великая Отечественная война",
        summary=summary,
        url=SEARCH_URL,
        source_id=f"soldat-hospital:{raw.pid}",
        confidence="place_level" if cand else "no_coords",
        extra={k: v for k, v in extra.items() if v is not None},
    )


def lookup_names(raws: Iterable[Raw]) -> list[str]:
    """Все написания мест, по которым ищутся кандидаты в Викиданных."""
    out = set()
    for raw in raws:
        for name in place_names(raw.place):
            out.update(query_variants(name))
    return sorted(out)


