"""Перепись 1897 года по уездам и городам: таблицы k-da.dev/russia-1897.

Зачем этот слой. Итоги переписи по губерниям в проекте уже есть (heiDATA,
`admin_1897_gis`), но губерния — это миллион-два жителей, и сказать по ней,
среди кого жил предок, нельзя: в Минской губернии евреи — 16%, а в местечке —
большинство. Слой даёт то же распределение на уровень ниже — по каждому уезду
и по каждому городу, посаду и местечку, у которого перепись вела отдельную
таблицу: население по полу, родной язык, вера, возраст десятилетиями.

Набор. «Перепись 1897» (k-da.dev/russia-1897, авт. Кирилл Конопатов) —
интерактивная визуализация, для которой команда сайта сама перенабрала
погубернские тома переписи по сканам НЭБ. Отдельных файлов данных у сайта
нет: Vite собрал поуездные JSON-модули (`../data/<губерния>/<уезд>.json`,
764 штуки) прямо в сборку приложения — один JS-файл около 5 МБ,
`/russia-1897/assets/index-<хэш>.js`. Других запросов за данными приложение
не делает (в сети страницы — только сборка, стили, карта SVG и гербы).

Каждый модуль уезда — поля `id`, `name_key`, `guberniya` (трёхбуквенный код
сайта: `ZBK`), `area` (кв. вёрсты), `uyezd_population` (м., ж., всего),
`cities` — населённые места с отдельной таблицей (город, посад, местечко,
станица, «административное село» — уездный центр без городских прав; у каждого
тип, население и флаги «уездный/губернский центр»), и три таблицы —
`language_by_sex`, `religion_by_sex`, `age10_by_sex`, каждая по уезду целиком
(`uyezd`) и по каждому месту (`city:<id>`). Русские названия губерний, уездов,
мест, языков и вер — в словаре интерфейса (`i18next`, ресурс `ru`), с
дореформенным написанием (`old_name`: «Читинскій округъ»). Грамотность
(`religion_x_language_x_literacy`) заведена только у двух уездов — на сайте
она в планах.

Как читается сборка. Это не JSON, а минифицированный JavaScript: модули
лежат константами `ewe="Chitinsky",nwe="uezd.Chitinsky.name",…`, собранными в
объект-пространство `uy=Object.freeze(Object.defineProperty({__proto__:null,
…}))`, а пространства — в таблицу `{"../data/ZBK/Chitinsky.json":uy,…}`.
`JsReader` разбирает подмножество JS, которого хватает на литералы данных
(объекты, массивы, строки, числа, `!0`/`!1`, `JSON.parse('…')`, ссылки на
константы и `a.b`), а ссылку ищет по ближайшему предшествующему определению
`имя=`. Хэш в имени сборки меняется с каждой выкладкой, поэтому адрес берётся
со страницы, а формат проверяется: нет таблицы модулей, меньше `MIN_UEZDS`
уездов, нет нужных полей или словаря — `KdaError` «формат сборки изменился»,
а не слой из того, что случайно совпало.

Права. Лицензии сайт не заявляет; сборка взята с согласия владельца,
полученного владельцем проекта (сообщено 24.11.2026). Сами тома переписи —
общественное достояние. В слой идут числа и названия, ссылка на страницу
уезда или места на сайте; сборка в репозиторий не кладётся.

Что попадает в слой. По записи на уезд (764) и на населённое место с
таблицей (около 930). Охват — «уезд» (`scope = region`, губерния в
`region`, уезд в `district`): **координат в данных нет**. Карта сайта — SVG
в собственной системе координат, а не в градусах, и точку по ней проект не
выдумывает. Запись места подбирается так же, как запись уезда, — по губернии,
а название места стоит в заголовке и в `place_text`. Уезд сводится с
уездами 1897 года RISTAT (`uezd_names`) внутри губернии; несведённое —
`district_unmatched`, запись остаётся.
"""

from __future__ import annotations

import bisect
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from ..net import RETRY_CODES, USER_AGENT
from ..schema import SCOPE_REGION, ContextRecord, LayerSpec
from .reforms_1851 import percent, plural, thousands
from .uezd_names import RistatDistricts, genitive

SITE = "https://k-da.dev"
PAGE_URL = f"{SITE}/russia-1897/ru/"
UEZD_URL = f"{SITE}/russia-1897/ru/uyezd/{{gub}}/{{uezd}}"
LOCALITY_URL = f"{SITE}/russia-1897/ru/locality/{{gub}}/{{uezd}}/{{id}}"
LAYER_ID = "census_1897_kda"

# Меньше — значит сборка уже не та: сейчас в ней 764 уезда.
MIN_UEZDS = 700
REQUIRED_FIELDS = ("id", "name_key", "guberniya", "uyezd_population", "cities",
                   "language_by_sex", "religion_by_sex", "age10_by_sex")

WORK = "Первая всеобщая перепись населения Российской империи 1897 года"
PERIOD_RAW = "перепись 28 января (9 февраля) 1897 года"
LICENSE = (
    "© k-da.dev/russia-1897 (К. Конопатов и команда сайта; таблицы перенабраны по "
    "томам переписи из НЭБ, сами тома — общественное достояние); лицензия не "
    "заявлена, собрано с согласия владельца, полученного владельцем проекта "
    "(сообщено 24.11.2026); берутся числа и названия со ссылкой на страницу сайта"
)

CENSUS_1897_KDA = LayerSpec(
    slug=LAYER_ID,
    title="Перепись 1897 года по уездам и городам (k-da.dev)",
    group="admin",
    source="k-da.dev/russia-1897, «Перепись 1897» (К. Конопатов) по томам переписи из НЭБ",
    license=LICENSE,
    description=(
        "Население по полу, родной язык, вера и возраст десятилетиями по каждому из "
        "764 уездов 1897 года и по каждому городу, посаду, местечку и уездному "
        "центру с отдельной таблицей переписи — уровнем ниже губернских итогов "
        "heiDATA. Координат нет: запись подбирается по губернии, уезд сведён с "
        "уездами RISTAT."
    ),
    url=PAGE_URL,
    status="harvested",
    expected_rows=1700,
)

CONFIDENCE_UNMATCHED = "district_unmatched"


class KdaError(RuntimeError):
    """Страница или сборка не скачались, или сборка пришла в другом формате."""


def format_error(what: str) -> KdaError:
    return KdaError(f"формат сборки изменился: {what}")


# --- страница ----------------------------------------------------------------

_RE_BUNDLE = re.compile(
    r'<script[^>]*type="module"[^>]*src="(/russia-1897/assets/index-[\w-]+\.js)"')


def bundle_url(html: str) -> str:
    """Адрес сборки со страницы: хэш в имени меняется с каждой выкладкой."""
    found = _RE_BUNDLE.findall(html or "")
    if len(found) != 1:
        raise format_error(f"на странице {len(found)} сборок index-*.js вместо одной")
    return SITE + found[0]


def fetch(url: str, *, attempts: int = 4, timeout: int = 120) -> bytes:
    """Один запрос с повтором на 429 и 5xx и растущей паузой между попытками."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_CODES or attempt == attempts - 1:
                raise KdaError(f"{url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if attempt == attempts - 1:
                raise KdaError(f"{url}: сеть недоступна ({exc.reason})") from exc
        time.sleep(5 * (attempt + 1))
    raise KdaError(f"{url}: не скачалось")


# --- разбор литералов JS ------------------------------------------------------

@dataclass(frozen=True)
class Ref:
    """Ссылка на константу сборки (`uy`) или её поле (`Ma.SIBERIA`)."""

    name: str
    pos: int
    attrs: tuple = ()


_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_DEFINITION = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)=(?![=>])")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


class JsReader:
    """Читает литералы данных из минифицированной сборки.

    Не интерпретатор: понимает объекты, массивы, строки, числа, `!0`/`!1`,
    `null`, `void 0`, `JSON.parse('…')` и ссылки на константы. Встретив что-то
    другое (функцию, выражение), бросает `KdaError` — значит, в этом месте
    данных нет, и делать вид, что они есть, нельзя.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self._defs: dict[str, list[int]] = {}
        for m in _DEFINITION.finditer(text):
            self._defs.setdefault(m.group(1), []).append(m.end())
        self._cache: dict[int, Any] = {}

    # Позиция значения константы: ближайшее определение `имя=` перед ссылкой,
    # а если перед ссылкой его нет — первое после (так Rollup выносит
    # константы, на которые ссылается функция выше по тексту).
    #
    # Короткие имена (`id`, `e`) переиспользуются во вложенных функциях, и
    # ближайшее `имя=` может оказаться чужим присваиванием; `head` отбирает
    # только определения, которые начинаются с ожидаемого текста.
    def definition(self, name: str, before: int, head: str = "") -> int:
        positions = [p for p in self._defs.get(name) or ()
                     if not head or self.text.startswith(head, p)]
        if not positions:
            raise KdaError(f"в сборке нет определения {name}" + (f" вида {head}…" if head else ""))
        i = bisect.bisect_left(positions, before)
        return positions[i - 1] if i > 0 else positions[0]

    def _ws(self, pos: int) -> int:
        text = self.text
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        return pos

    def value(self, pos: int) -> tuple[Any, int]:
        """Значение, начинающееся с `pos`, и позиция сразу за ним."""
        text = self.text
        pos = self._ws(pos)
        if pos >= len(text):
            raise KdaError("сборка оборвалась посреди значения")
        ch = text[pos]
        if ch == "{":
            return self._object(pos)
        if ch == "[":
            return self._array(pos)
        if ch in "\"'`":
            return self._string(pos)
        if text.startswith("!0", pos):
            return True, pos + 2
        if text.startswith("!1", pos):
            return False, pos + 2
        if ch.isdigit() or ch in ".-":
            m = _NUMBER.match(text, pos)
            if not m:
                raise KdaError(f"не число на позиции {pos}")
            # Минификатор пишет круглые числа порядком: 3000 → `3e3`.
            num = float(m.group(0))
            return (int(num) if num.is_integer() else num), m.end()
        m = _IDENT.match(text, pos)
        if not m:
            raise KdaError(f"неожиданный знак {ch!r} на позиции {pos}")
        name, end = m.group(0), m.end()
        if name == "null":
            return None, end
        if name in ("true", "false"):
            return name == "true", end
        if name == "void" and text.startswith(" 0", end):
            return None, end + 2
        attrs = []
        while end < len(text) and text[end] == "." and _IDENT.match(text, end + 1):
            attr = _IDENT.match(text, end + 1)
            attrs.append(attr.group(0))
            end = attr.end()
        if name == "JSON" and attrs == ["parse"] and text.startswith("(", end):
            arg, end = self.value(end + 1)
            if not isinstance(arg, str) or not text.startswith(")", self._ws(end)):
                raise KdaError(f"JSON.parse не со строкой на позиции {pos}")
            try:
                return json.loads(arg), self._ws(end) + 1
            except json.JSONDecodeError as exc:
                raise KdaError(f"JSON.parse на позиции {pos}: {exc}") from exc
        if end < len(text) and text[end] == "(":
            raise KdaError(f"вызов {name}(…) на позиции {pos} — не литерал")
        return Ref(name, pos, tuple(attrs)), end

    def _object(self, pos: int) -> tuple[dict, int]:
        text, out = self.text, {}
        pos = self._ws(pos + 1)
        while True:
            if text[pos] == "}":
                return out, pos + 1
            if text[pos] in "\"'":
                key, pos = self._string(pos)
            else:
                m = _IDENT.match(text, pos) or _NUMBER.match(text, pos)
                if not m:
                    raise KdaError(f"не ключ объекта на позиции {pos}")
                key, pos = m.group(0), m.end()
            pos = self._ws(pos)
            if text[pos] != ":":
                raise KdaError(f"нет двоеточия после ключа {key!r} на позиции {pos}")
            out[key], pos = self.value(pos + 1)
            pos = self._ws(pos)
            if text[pos] == ",":
                pos = self._ws(pos + 1)
            elif text[pos] != "}":
                raise KdaError(f"объект не закрыт на позиции {pos}")

    def _array(self, pos: int) -> tuple[list, int]:
        text, out = self.text, []
        pos = self._ws(pos + 1)
        while True:
            if text[pos] == "]":
                return out, pos + 1
            item, pos = self.value(pos)
            out.append(item)
            pos = self._ws(pos)
            if text[pos] == ",":
                pos = self._ws(pos + 1)
            elif text[pos] != "]":
                raise KdaError(f"массив не закрыт на позиции {pos}")

    def _string(self, pos: int) -> tuple[str, int]:
        text, quote = self.text, self.text[pos]
        out, i = [], pos + 1
        while True:
            j = i
            while j < len(text) and text[j] not in (quote, "\\") and not (
                    quote == "`" and text.startswith("${", j)):
                j += 1
            out.append(text[i:j])
            if j >= len(text):
                raise KdaError(f"строка с позиции {pos} не закрыта")
            ch = text[j]
            if ch == quote:
                return "".join(out), j + 1
            if ch == "$":
                raise KdaError(f"шаблон с подстановкой на позиции {pos} — не литерал")
            esc = text[j + 1]
            if esc == "u":
                if text[j + 2] == "{":
                    k = text.index("}", j)
                    out.append(chr(int(text[j + 3:k], 16)))
                    i = k + 1
                else:
                    out.append(chr(int(text[j + 2:j + 6], 16)))
                    i = j + 6
            elif esc == "x":
                out.append(chr(int(text[j + 2:j + 4], 16)))
                i = j + 4
            elif esc in "\r\n":
                i = j + 2
            else:
                out.append(_ESCAPES.get(esc, esc))
                i = j + 2

    def resolve(self, ref: Any) -> Any:
        """Значение константы, на которую указывает ссылка (вложенные — тоже)."""
        if isinstance(ref, Ref):
            start = self.definition(ref.name, ref.pos)
            if start not in self._cache:
                self._cache[start] = self.value(start)[0]
            value = self.resolve(self._cache[start])
            for attr in ref.attrs:
                if not isinstance(value, dict) or attr not in value:
                    raise KdaError(f"у {ref.name} нет поля {attr}")
                value = self.resolve(value[attr])
            return value
        if isinstance(ref, dict):
            return {k: self.resolve(v) for k, v in ref.items()}
        if isinstance(ref, list):
            return [self.resolve(v) for v in ref]
        return ref

    def module_fields(self, ref: Ref) -> dict:
        """Поля модуля `uy=Object.freeze(Object.defineProperty({…}, …))`."""
        head = "Object.freeze(Object.defineProperty("
        try:
            start = self.definition(ref.name, ref.pos, head)
        except KdaError as exc:
            raise format_error(f"{ref.name} — не пространство модуля Vite") from exc
        fields, _ = self.value(start + len(head))
        if not isinstance(fields, dict):
            raise format_error(f"у модуля {ref.name} нет объекта полей")
        return {k: self.resolve(v) for k, v in fields.items()
                if k not in ("__proto__", "default")}


# --- сборка целиком -----------------------------------------------------------

_RE_MODULE_MAP = re.compile(r'\{"\.\./data/[A-Z]{3}/[\w-]+\.json":')
_RE_MAP_KEY = re.compile(r"\.\./data/([A-Z]{3})/([\w-]+)\.json")
_RE_LOCALE = re.compile(r"resources:\{ru:\{translation:([A-Za-z_$][\w$]*)\}")
_RE_PROVINCES = re.compile(r'([A-Za-z_$][\w$]*)=\{[A-Z]{3}:\{type:"(?:guberniya|oblast)"')


@dataclass
class Bundle:
    """Что взято из сборки: модули уездов, коды губерний и русский словарь."""

    uezds: list[dict]
    provinces: dict[str, dict]          # ZBK → {"type": "oblast", "nameKey": "…"}
    locale: dict[str, dict]             # guberniya, uezd, locality, language, religion, settlement
    module_paths: int = 0
    notes: list = field(default_factory=list)

    def province_name(self, code: str) -> Optional[str]:
        key = (self.provinces.get(code) or {}).get("nameKey")
        return ((self.locale.get("guberniya") or {}).get(key) or {}).get("name") if key else None

    def names(self, section: str, item: dict) -> dict:
        """Русское и дореформенное название по `name_key` («locality.Chita.name»).

        Ключ словаря — не всегда `id`: у Свенцян id «Sventsiany», а ключ
        «SventsianyCity». Без `name_key` — по `id`.
        """
        key = str(item.get("name_key") or "")
        parts = key.split(".")
        word = parts[1] if len(parts) == 3 and parts[0] == section else item.get("id")
        value = (self.locale.get(section) or {}).get(word)
        return value if isinstance(value, dict) else {}

    def label(self, section: str, key: str, fallback: Optional[str] = None) -> str:
        value = (self.locale.get(section) or {}).get(key)
        if isinstance(value, dict):
            value = value.get("name")
        return value or fallback or key


LOCALE_SECTIONS = ("guberniya", "uezd", "locality", "language", "religion", "settlement")


def parse_bundle(text: str) -> Bundle:
    reader = JsReader(text)
    m = _RE_MODULE_MAP.search(text)
    if not m:
        raise format_error("нет таблицы модулей \"../data/<губерния>/<уезд>.json\"")
    table, _ = reader.value(m.start())
    paths = {k: v for k, v in table.items() if _RE_MAP_KEY.fullmatch(k)}
    if len(paths) < MIN_UEZDS:
        raise format_error(f"в таблице модулей {len(paths)} уездов, ждали не меньше {MIN_UEZDS}")
    uezds = []
    for path, ref in sorted(paths.items()):
        if not isinstance(ref, Ref):
            raise format_error(f"{path} подключён не константой (ленивый импорт?)")
        fields = reader.module_fields(ref)
        missing = [f for f in REQUIRED_FIELDS if f not in fields]
        if missing:
            raise format_error(f"у {path} нет полей {', '.join(missing)}")
        gub, file_id = _RE_MAP_KEY.fullmatch(path).groups()
        if fields["guberniya"] != gub or fields["id"] != file_id:
            raise format_error(
                f"{path}: в модуле id={fields['id']}, guberniya={fields['guberniya']}")
        check_module(path, fields)
        fields["path"] = path
        uezds.append(fields)

    m = _RE_LOCALE.search(text)
    if not m:
        raise format_error("нет русского словаря i18next (resources.ru.translation)")
    root = reader.resolve(Ref(m.group(1), m.start()))
    if not isinstance(root, dict):
        raise format_error("словарь интерфейса — не объект")
    missing = [s for s in LOCALE_SECTIONS if not isinstance(root.get(s), dict)]
    if missing:
        raise format_error(f"в словаре нет разделов {', '.join(missing)}")
    locale = {s: root[s] for s in LOCALE_SECTIONS}

    m = _RE_PROVINCES.search(text)
    if not m:
        raise format_error("нет таблицы кодов губерний {ARH:{type:…,nameKey:…}}")
    provinces = reader.resolve(reader.value(m.end(1) + 1)[0])
    if not all(isinstance(v, dict) and v.get("nameKey") for v in provinces.values()):
        raise format_error("в таблице кодов губерний нет nameKey")
    bundle = Bundle(uezds, provinces, locale, module_paths=len(paths))
    unknown = sorted({u["guberniya"] for u in uezds if not bundle.province_name(u["guberniya"])})
    if unknown:
        raise format_error(f"коды губерний без названия: {', '.join(unknown)}")
    return bundle


def check_module(path: str, fields: dict) -> None:
    pop = fields["uyezd_population"]
    if not isinstance(pop, dict) or not isinstance(pop.get("total"), int):
        raise format_error(f"{path}: uyezd_population без total")
    if not isinstance(fields["cities"], list):
        raise format_error(f"{path}: cities — не список")
    for city in fields["cities"]:
        if not isinstance(city, dict) or not city.get("id") or not isinstance(
                (city.get("population") or {}).get("total"), int):
            raise format_error(f"{path}: место без id или населения")
    for table, key in (("language_by_sex", "lang"), ("religion_by_sex", "religion"),
                       ("age10_by_sex", "age")):
        value = fields[table]
        if not isinstance(value, dict) or not isinstance(value.get("uyezd"), list):
            raise format_error(f"{path}: у {table} нет строк uyezd")
        for row in value["uyezd"]:
            if not isinstance(row, dict) or key not in row or "m" not in row or "f" not in row:
                raise format_error(f"{path}: строка {table} без {key}/m/f")


# --- таблицы ------------------------------------------------------------------

TABLES = (("language_by_sex", "lang", "язык"), ("religion_by_sex", "religion", "вера"),
          ("age10_by_sex", "age", "возраст"))


def table_rows(module: dict, table: str, unit: str) -> list[dict]:
    return list((module.get(table) or {}).get(unit) or [])


def sex_table(rows: Iterable[dict], key: str) -> dict:
    """[{lang, m, f}] → {lang: {"м": m, "ж": f}} в порядке источника."""
    out = {}
    for row in rows:
        out[str(row[key])] = {"м": int(row.get("m") or 0), "ж": int(row.get("f") or 0)}
    return out


def age_label(code: str) -> str:
    return {"0": "до года", "110+": "110 лет и старше",
            "unknown": "возраст не указан"}.get(code, f"{code} лет")


def tables_for(module: dict, unit: str, bundle: Bundle) -> dict:
    """Три таблицы единицы по-русски: язык, вера, возраст — {подпись: {м, ж}}."""
    out = {}
    for table, key, title in TABLES:
        rows = sex_table(table_rows(module, table, unit), key)
        if not rows:
            continue
        if key == "age":
            out[title] = {age_label(k): v for k, v in rows.items()}
        else:
            section = "language" if key == "lang" else "religion"
            out[title] = {bundle.label(section, k): v for k, v in rows.items()}
    literacy = literacy_totals(module, unit)
    if literacy:
        out["грамотность"] = literacy
    return out


def literacy_totals(module: dict, unit: str) -> Optional[dict]:
    """Грамотные из таблицы «вера × язык × грамотность», если она заполнена.

    Таблица заведена у одного уезда (Архангельский) и заполнена только по
    Архангельску; по уезду без города в ней нули — это «не перенабрано», а
    не «неграмотны все», и такие таблицы не берутся.
    """
    rows = (module.get("religion_x_language_x_literacy") or {}).get(unit) or []
    sums = {"всего": {"м": 0, "ж": 0}, "грамотных": {"м": 0, "ж": 0}}
    for row in rows:
        for cell in row.get("langs") or []:
            if cell.get("is_group"):
                continue
            target = {"total": "всего", "literate": "грамотных"}.get(cell.get("metric"))
            if target:
                sums[target]["м"] += int(cell.get("m") or 0)
                sums[target]["ж"] += int(cell.get("f") or 0)
    return sums if sum(sums["всего"].values()) > 0 else None


def top_shares(rows: dict, total: int, *, limit: int = 3, floor: float = 1.0) -> str:
    """«великорусский — 47%, бурятский — 28%»: до трёх групп не меньше 1%."""
    if not rows or total <= 0:
        return ""
    ranked = sorted(((v["м"] + v["ж"], k) for k, v in rows.items()), key=lambda x: -x[0])
    parts = []
    for n, name in ranked[:limit]:
        if n <= 0 or 100.0 * n / total < floor and parts:
            break
        parts.append(f"{name[0].lower() + name[1:]} — {percent(n, total)}")
    return ", ".join(parts)


def summary_text(pop: dict, tables: dict, *, area: Optional[float] = None,
                 lead: str = "") -> str:
    total = int(pop.get("total") or 0)
    parts = [f"{lead}Перепись 1897 года: {thousands(total)} "
             f"{plural(total, 'житель', 'жителя', 'жителей')} "
             f"({thousands(pop.get('m') or 0)} муж., {thousands(pop.get('f') or 0)} жен.)"]
    if area:
        density = total / area
        shown = f"{density:.1f}".replace(".", ",") if density < 10 else f"{density:.0f}"
        parts[0] += f", {thousands(area)} кв. вёрст, {shown} чел. на кв. версту"
    langs = top_shares(tables.get("язык") or {}, total)
    if langs:
        parts.append(f"Родной язык: {langs}")
    faith = top_shares(tables.get("вера") or {}, total)
    if faith:
        parts.append(f"Вера: {faith}")
    ages = tables.get("возраст") or {}
    children = sum(v["м"] + v["ж"] for k, v in ages.items() if k in ("до года", "1-9 лет"))
    if children and total:
        parts.append(f"Детей до 10 лет — {percent(children, total)}")
    literacy = tables.get("грамотность")
    if literacy:
        base = sum(literacy["всего"].values())
        parts.append(f"Грамотных — {percent(sum(literacy['грамотных'].values()), base)}")
    return ". ".join(parts) + "."


# --- записи -------------------------------------------------------------------

UNIT_TAILS = ("уезд", "округ", "отдел", "приставство", "участок", "уезд(округ)")


def bare_name(name: str) -> str:
    """«Читинский округ» → «Читинский»: так уезд назван в справочнике RISTAT."""
    words = name.split()
    return " ".join(words[:-1]) if len(words) > 1 and words[-1].lower() in UNIT_TAILS else name


@dataclass(frozen=True)
class Unit:
    """Губерния и уезд записи и пара в справочнике RISTAT."""

    province: str
    district: str
    head: str                  # «Читинский округ Забайкальской области»
    distr_id: Optional[str]
    ristat_name: Optional[str]
    how: Optional[str]


# Губерния так, как её зовут остальные слои: сайт пишет Подольскую губернию
# по губернскому городу, а Карсскую — с одной «с». Название сайта остаётся
# в `extra.province_on_site`.
PROVINCE_NAMES = {"Каменец-Подольская губерния": "Подольская губерния",
                  "Карская область": "Карсская область"}

# Уезды, которые по ключу не сводятся или сводятся не туда. Значение — название
# в справочнике RISTAT. Справочник местами подписан названиями после 1897
# года: Маргеланский уезд у него Скобелевский (город переименован в 1907
# году), Калмыковский — Лбищенский (1899), Санкт-Петербургский — Петроградский.
# Нерчинско-Заводский ключом «prefix» попадал бы в Нерчинский.
KDA_DISTRICTS = {
    ("Ферганская область", "Маргеланский уезд"): "Скобелевский",
    ("Уральская область", "Калмыковский уезд"): "Лбищенский",
    ("Санкт-Петербургская губерния", "Санкт-Петербургский уезд"): "Петроградский",
    ("Область Войска Донского", "1-й Донской округ"): "Донской 1-й",
    ("Область Войска Донского", "2-й Донской округ"): "Донской 2-й",
    ("Вологодская губерния", "Велико-Устюгский уезд"): "Устюжский",
    ("Забайкальская область", "Нерчинско-Заводский округ"): "Нерчинский-Заводский",
}
# Не сводятся вовсе — единица 1897 года у RISTAT разбита на несколько, и
# выбрать одну из них значило бы приписать всё население части:
# Туруханский край (у RISTAT — Верхне-Инбатский, Дудинский и Тазовский
# участки) и «Территория кочующих народов» Ставропольской губернии
# (Ачикулакское, Большедербетовское и Трухменское приставства).


def locate(province: str, district: str, index: Optional[RistatDistricts]) -> Unit:
    head = f"{district} {genitive(province)}"
    match = None
    if index is not None:
        manual = KDA_DISTRICTS.get((province, district))
        if manual:
            match = index.by_name(province, manual)
        else:
            match = (index.by_name(province, bare_name(district))
                     or index.match(province, district))
    if match is None:
        return Unit(province, district, head, None, None, None)
    # `by_name` помечает любое совпадение по русскому названию как «manual»;
    # ручное здесь — только то, что заведено в KDA_DISTRICTS.
    how = "manual" if (province, district) in KDA_DISTRICTS else (
        "exact" if match.how == "manual" else match.how)
    return Unit(province, district, head, match.district.distr_id, match.district.name, how)


# Опечатки в типе места у сайта: тип сохраняется в `extra` как есть, а
# подпись берётся по исправленному.
TYPE_FIXES = {"adm_vuillage": "adm_village"}


def settlement_type(city: dict) -> str:
    raw = str(city.get("type") or "")
    return TYPE_FIXES.get(raw, raw)


def locality_kind(city: dict, bundle: Bundle) -> str:
    stype = settlement_type(city)
    kind = bundle.label("settlement", stype, "населённое место")
    flags = city.get("flags") or {}
    if flags.get("guberniya_center"):
        return "губернский город" if stype == "city" else f"{kind}, губернский центр"
    if flags.get("uyezd_center"):
        return "уездный город" if stype == "city" else f"{kind}, уездный центр"
    return "заштатный город" if stype == "city" else kind


def records(bundle: Bundle, index: Optional[RistatDistricts]) -> list[ContextRecord]:
    out = []
    for module in bundle.uezds:
        gub, uid = module["guberniya"], module["id"]
        site_province = bundle.province_name(gub)
        province = PROVINCE_NAMES.get(site_province, site_province)
        uezd_names = bundle.names("uezd", module)
        district = uezd_names.get("name") or uid
        unit = locate(province, district, index)
        confidence = "ok" if (index is None or unit.distr_id) else CONFIDENCE_UNMATCHED
        pop = module["uyezd_population"]
        area = (module.get("area") or {}).get("verst2")
        tables = tables_for(module, "uyezd", bundle)
        cities = module.get("cities") or []
        localities = []
        for city in cities:
            names = bundle.names("locality", city)
            localities.append({"id": city["id"], "name": names.get("name") or city["id"],
                               "type": city.get("type"),
                               "population": int(city["population"]["total"])})
        place_text = f"{district}, {province}"
        lead_cities = ", ".join(f"{c['name']} ({thousands(c['population'])})"
                                for c in localities)
        text = summary_text(pop, tables, area=area)
        if lead_cities:
            word = "Место" if len(localities) == 1 else "Места"
            text += f" {word} с отдельной таблицей переписи: {lead_cities}."
        extra = {
            "kda_guberniya": gub, "kda_id": uid,
            "province_on_site": site_province if site_province != province else None,
            "old_name": uezd_names.get("old_name"),
            "population": {"м": pop.get("m"), "ж": pop.get("f"), "оба": pop.get("total")},
            "area_verst2": area,
            "census_1897": tables,
            "localities": localities,
            "unit": "уезд",
        }
        if unit.distr_id:
            extra.update(ristat_distr_id=unit.distr_id, ristat_name=unit.ristat_name,
                         ristat_match=unit.how)
        out.append(CENSUS_1897_KDA.new_record(
            title=f"{unit.head}: перепись 1897 года",
            category="уезд: население, язык, вера, возраст",
            scope=SCOPE_REGION, place_text=place_text,
            region=province, regions=[province], district=district,
            year_from=1897, year_to=1897, date_precision="day", period_raw=PERIOD_RAW,
            work=WORK, summary=text, url=UEZD_URL.format(gub=gub, uezd=uid),
            source_id=f"{gub}/{uid}", confidence=confidence,
            extra={k: v for k, v in extra.items() if v not in (None, {}, [])},
        ))
        for city in cities:
            cid = city["id"]
            names = bundle.names("locality", city)
            name = names.get("name") or cid
            kind = locality_kind(city, bundle)
            cpop = city["population"]
            ctables = tables_for(module, f"city:{cid}", bundle)
            ctext = summary_text(cpop, ctables, lead=f"{name[0].upper() + name[1:]} — {kind}. ")
            cextra = {
                "kda_guberniya": gub, "kda_uezd": uid, "kda_id": cid,
                "old_name": names.get("old_name"),
                "settlement_type": settlement_type(city),
                "settlement_type_on_site": (city.get("type")
                                            if city.get("type") != settlement_type(city) else None),
                "settlement_type_ru": bundle.label("settlement", settlement_type(city)),
                "flags": city.get("flags") or None,
                "population": {"м": cpop.get("m"), "ж": cpop.get("f"), "оба": cpop.get("total")},
                "census_1897": ctables,
                "unit": "населённое место",
                "coordinates": "в данных нет: запись подбирается по уезду и губернии",
            }
            if unit.distr_id:
                cextra.update(ristat_distr_id=unit.distr_id, ristat_name=unit.ristat_name,
                              ristat_match=unit.how)
            out.append(CENSUS_1897_KDA.new_record(
                title=f"{name} ({unit.head}): перепись 1897 года",
                category=f"{bundle.label('settlement', settlement_type(city))}: "
                         "население, язык, вера, возраст",
                scope=SCOPE_REGION, place_text=f"{name}, {place_text}",
                region=province, regions=[province], district=district,
                year_from=1897, year_to=1897, date_precision="day", period_raw=PERIOD_RAW,
                work=WORK, summary=ctext, url=LOCALITY_URL.format(gub=gub, uezd=uid, id=cid),
                source_id=f"{gub}/{uid}/{cid}", confidence=confidence,
                extra={k: v for k, v in cextra.items() if v not in (None, {}, [])},
            ))
    return out


# --- сверка -------------------------------------------------------------------

def consistency(bundle: Bundle) -> dict:
    """Сходятся ли таблицы с населением: сколько единиц, где сумма равна итогу.

    Перенабор томов — ручная работа, и расхождение суммы строк с итогом —
    первое, что выдаст опечатку. В слой это идёт счётом в отчёте, а не правкой
    чисел: исправлять чужой перенабор по своему разумению нельзя.
    """
    counts = {"units": 0}
    for module in bundle.uezds:
        units = [("uyezd", module["uyezd_population"])] + [
            (f"city:{c['id']}", c["population"]) for c in module.get("cities") or []]
        for unit, pop in units:
            counts["units"] += 1
            for table, _key, title in TABLES:
                rows = table_rows(module, table, unit)
                if not rows:
                    counts[f"{title}: таблицы нет"] = counts.get(f"{title}: таблицы нет", 0) + 1
                    continue
                total = sum(int(r.get("m") or 0) + int(r.get("f") or 0) for r in rows)
                name = f"{title}: сумма = итогу" if total == pop.get("total") else \
                    f"{title}: сумма ≠ итогу"
                counts[name] = counts.get(name, 0) + 1
    return counts
