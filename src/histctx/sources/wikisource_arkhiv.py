"""Метрические книги в описях украинских архивов: Викитека, пространство «Архів».

Зачем этот слой. На вопрос генеалога «в каком архиве, под каким шифром и за
какие годы лежат метрические книги церкви села X» каталог проекта до сих пор
отвечал только косвенно: слой `parishes` знает, что приход был, но не знает,
куда делись его книги. Украинская Викитека ведёт пространство «Архів» —
описи фондов государственных архивов Украины построчно: «№ дела — название —
уезд — годы — листы». Среди 28 тысяч описей полторы тысячи касаются
метрических книг, в них 53 тысячи дел с метрическими книгами в названии, а у
консисторских сводных томов ДАЖО ещё и постраничное «Содержание» — какие
приходы переплетены в дело. Это перечень «приход → архив, фонд, опись, дело,
годы» по Правобережью, Слобожанщине, Новороссии и Галичине.

Откуда берётся. Не из API, а из дампа: `dumps.wikimedia.org/ukwikisource`,
файл `pages-articles-multistream` — сжатые bz2 потоки по сто страниц и к ним
оглавление «смещение:id:заголовок». По оглавлению видно, в каких потоках
лежат страницы пространства 116 («Архів:…»), и сборщик забирает только эти
потоки запросами Range — 128 МБ из 169 и девяносто запросов вместо двухсот
тысяч страниц через API. API Викимедиа отвечает анонимному сборщику 429
уже на первом запросе (общий лимит выхода прокси), а дамп лимита запросов
не имеет и обновляется дважды в месяц; дата дампа пишется в каждую запись.
Сверка дампа — по md5 из `dumpstatus.json`, сверка разбора на `--check` —
одна страница описи через API (`maxlag=5`, `net.USER_AGENT`).

Как устроены страницы. «Архів:ДАЖО/1/80» — опись: шаблон `{{Архіви/опис}}`
(название и годы описи) и вики-таблица дел. Заголовки колонок в описях
разных архивов свои — «№ | Назва | Повіт | Роки | Аркушів», «№ | Назва |
Церква | Нас. пункти | Повіт | Дати | Арк.», «# | Церква | Населений пункт |
Повіт | Назва | Роки | Арк.» — и сводятся к одним именам (`COLUMNS`).
«Архів:ДАЖО/1/80/1» — дело: шаблон `{{Архіви/справа}}` и у сводных томов
таблица «Зміст»: «Аркуш | Назва (село) | Приписні села | Церква | Повіт».
«Архів:ДАЖО/1» — фонд, из него берётся название фонда.

Что берётся и что не берётся:

* **Берутся метаданные дел**: архив, фонд, опись, номер дела, его название
  («Метричні книги церкви с. Бобли Ковельського повіту» — короткое название
  единицы хранения, а не текст), уезд, годы, число листов, тип записей
  (рождение, брак, смерть, развод), из «Содержания» сводных томов — село,
  приписные сёла и посвящение церкви. Ссылка — на страницу описи.
* **Не берутся сканы и тексты**: ссылки на FamilySearch и Commons остаются
  на странице описи, аннотации описей и фондов в слой не идут.
* **Не берутся персоналии.** Дела «о выдаче метрического свидетельства
  такому-то», «о дворянском происхождении рода …», прошения и рапорты —
  это не метрические книги, и в них имена; разбор их отсеивает по названию.
* **Не берутся книги регистрации актов гражданского состояния** советского
  времени («Книга реєстрації актів про народження»): это не метрические
  книги церкви, и у них свой ответ — архив ЗАГС.

Запись — одна на церковь (костёл, синагогу, общину) в описи, а не на дело:
годы — диапазонами, дела — списком с годами и листами. Дела одного прихода
по разным описям — разные записи: шифр у них разный. Сводные тома уезда
(«Метричні книги православних церков Ковельського повіту. Села Б–Я»)
дают свою запись на серию томов, а если у дела есть «Содержание», каждый
приход из него получает это дело в свою запись.

Это территориальные записи: у прихода нет координаты в источнике, есть уезд.
`region` — губерния 1897 года, `district` — уезд по справочнику RISTAT
(`districts_1897.geojson`): украинское «Ковельський повіт» сводится с
«Ковельский» по ключу из согласных (`uezd_key`) внутри губернии, а
расхождения, которых правило не берёт («Овруцький» — «Овручский»,
«Прилуцький» — «Прилукский»), заведены словарём `UEZD_MANUAL`. Не сведённый
уезд остаётся как в источнике с пометкой `district_unmatched`. Галиция,
Буковина и Закарпатье губерний 1897 года не имели: у их записей `region`
пуст, земля — в `place_text` и `extra`, пометка `outside_1897`.

Привязка к точке — только там, где она надёжна: название села (из
«Содержания» или из названия дела) ровно один раз встречается в указателе
написаний GeoNames (`data/out/name_variants.json`) среди мест, лежащих
внутри полигона того же уезда 1897 года. Тогда запись получает координату
села (`confidence = place_level`, способ — в `extra.geo`), иначе остаётся
территориальной.

Права. Тексты Викитеки — CC BY-SA 4.0; описи — перепечатка архивных описей,
то есть фактов о делах. Берутся факты со ссылкой на страницу описи.
"""

from __future__ import annotations

import bz2
import collections
import difflib
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

from ..net import RETRY_CODES, USER_AGENT, wait_for_pause
from ..schema import SCOPE_POINT, SCOPE_REGION, ContextRecord, LayerSpec, clean_text

WIKI = "ukwikisource"
DUMPS_URL = f"https://dumps.wikimedia.org/{WIKI}"
WIKI_URL = "https://uk.wikisource.org/wiki/"
API_URL = "https://uk.wikisource.org/w/api.php"
NS_ARCHIVE = 116
NS_PREFIX = "Архів:"
MULTISTREAM = "pages-articles-multistream.xml.bz2"
MULTISTREAM_INDEX = "pages-articles-multistream-index.txt.bz2"

# Опись, на которой `--check` сверяет разбор с живой страницей: 189 дел,
# дело 177 — «Метричні книги церкви м. Камінь-Каширський Ковельського повіту».
SAMPLE_PAGE = "Архів:ДАЖО/1/80"

# Нужные потоки дампа, между которыми меньше `RANGE_GAP` чужих, забираются
# одним запросом: лишние байты дешевле лишнего запроса. При 4 на дампе
# 20261101 — 91 запрос, 128 МБ вместо 116 МБ одних нужных потоков.
RANGE_GAP = 4

# Права пишутся коротко: строка повторяется в каждой из двадцати тысяч записей
# выгрузки. Что берётся и что нет — в шапке модуля и в описании слоя.
LICENSE = "CC BY-SA 4.0 (Викитека); метаданные дел со ссылкой на опись"

METRIC_BOOKS_UA = LayerSpec(
    slug="metric_books_ua",
    title="Метрические книги в описях архивов Украины",
    group="faith",
    source="Викитека, пространство «Архів»: описи архивов Украины",
    license=LICENSE,
    description=(
        "Где лежат метрические книги прихода: архив, фонд, опись, номера дел, годы и "
        "листы — по описям ЦДИАК, ЦДИАЛ и областных архивов Украины, переписанным в "
        "Викитеке. Одна запись на церковь, костёл, синагогу или общину в описи; сводные "
        "тома консистории разложены по приходам по их «Содержанию». Отвечает, куда "
        "писать запрос о метрике села за нужный год и под каким шифром дело."
    ),
    url=WIKI_URL + "Архів:Архіви",
    status="harvested",
    # Дамп 20261101: 21 826 записей — 19 935 без точки и 1 891 с точкой села.
    expected_rows=21826,
)

# Архивы по сокращению в заголовке страницы → как их называть по-русски.
# Чего нет в словаре, остаётся сокращением.
ARCHIVES = {
    "ЦДІАК": "Центральный государственный исторический архив Украины в Киеве",
    "ЦДІАЛ": "Центральный государственный исторический архив Украины во Львове",
    "ЦДАВО": "Центральный государственный архив высших органов власти Украины",
    "ДААРК": "Государственный архив Автономной Республики Крым",
    "ДАВіО": "Государственный архив Винницкой области",
    "ДАВоО": "Государственный архив Волынской области",
    "ДАДнО": "Государственный архив Днепропетровской области",
    "ДАДоО": "Государственный архив Донецкой области",
    "ДАЖО": "Государственный архив Житомирской области",
    "ДАЗкО": "Государственный архив Закарпатской области",
    "ДАЗпО": "Государственный архив Запорожской области",
    "ДАІФО": "Государственный архив Ивано-Франковской области",
    "ДАК": "Государственный архив города Киева",
    "ДАКО": "Государственный архив Киевской области",
    "ДАКрО": "Государственный архив Кировоградской области",
    "ДАЛО": "Государственный архив Львовской области",
    "ДАЛуО": "Государственный архив Луганской области",
    "ДАМО": "Государственный архив Николаевской области",
    "ДАОО": "Государственный архив Одесской области",
    "ДАПО": "Государственный архив Полтавской области",
    "ДАРО": "Государственный архив Ровенской области",
    "ДАС": "Государственный архив города Севастополя",
    "ДАСО": "Государственный архив Сумской области",
    "ДАТО": "Государственный архив Тернопольской области",
    "ДАХО": "Государственный архив Харьковской области",
    "ДАХеО": "Государственный архив Херсонской области",
    "ДАХмО": "Государственный архив Хмельницкой области",
    "ДАЧвО": "Государственный архив Черновицкой области",
    "ДАЧгО": "Государственный архив Черниговской области",
    "ДАЧкО": "Государственный архив Черкасской области",
}

# Губернии, в которых ищется уезд описи, если губерния в ней не названа: по
# архиву — те, чьи фонды он хранит. Порядок — порядок предпочтения при
# совпадении уезда в двух губерниях (Могилевский — в Подольской и в
# Могилёвской). Архива нет в словаре — ищется по всем `SOUTHWEST`.
ARCHIVE_PROVINCES = {
    "ДАЖО": ("Волынская", "Киевская"),
    "ДАВоО": ("Волынская", "Минская", "Гродненская"),
    "ДАРО": ("Волынская", "Минская"),
    "ДАХмО": ("Подольская", "Волынская"),
    "ДАВіО": ("Подольская", "Киевская"),
    "ДАКО": ("Киевская", "Полтавская", "Черниговская"),
    "ДАК": ("Киевская",),
    "ЦДІАК": ("Киевская", "Волынская", "Подольская", "Полтавская", "Черниговская",
              "Херсонская", "Екатеринославская", "Таврическая", "Харьковская"),
    "ДАЧкО": ("Киевская", "Полтавская", "Херсонская"),
    "ДАЧгО": ("Черниговская", "Полтавская"),
    "ДАПО": ("Полтавская",),
    "ДАХО": ("Харьковская",),
    "ДАСО": ("Харьковская", "Черниговская", "Полтавская", "Курская"),
    "ДАДнО": ("Екатеринославская",),
    "ДАЗпО": ("Екатеринославская", "Таврическая"),
    "ДАДоО": ("Екатеринославская",),
    "ДАЛуО": ("Екатеринославская", "Харьковская"),
    "ДАХеО": ("Херсонская", "Таврическая"),
    "ДАМО": ("Херсонская",),
    "ДАОО": ("Херсонская", "Бессарабская", "Подольская"),
    "ДАКрО": ("Херсонская", "Киевская"),
    "ДААРК": ("Таврическая",),
    "ДАС": ("Таврическая",),
    "ДАТО": ("Волынская", "Подольская"),
    "ДАЧвО": ("Бессарабская",),
}
SOUTHWEST = ("Волынская", "Киевская", "Подольская", "Полтавская", "Черниговская",
             "Харьковская", "Херсонская", "Екатеринославская", "Таврическая",
             "Бессарабская", "Минская", "Гродненская", "Курская", "Воронежская",
             "Могилевская")

# Земли вне губерний 1897 года — по архиву, если уезд описи с губерниями не
# свёлся: Галиция и Буковина были австрийскими, Закарпатье — венгерским.
OUTSIDE_LANDS = {
    "ЦДІАЛ": "Галиция (Австро-Венгрия)",
    "ДАЛО": "Галиция (Австро-Венгрия)",
    "ДАІФО": "Галиция (Австро-Венгрия)",
    "ДАТО": "Галиция (Австро-Венгрия)",
    "ДАЧвО": "Буковина (Австро-Венгрия)",
    "ДАЗкО": "Закарпатье (Венгрия)",
}

# Губернии по-украински (основа прилагательного) → как в справочнике 1897 года.
PROVINCES_UK = {
    "волинськ": "Волынская губерния", "київськ": "Киевская губерния",
    "подільськ": "Подольская губерния", "полтавськ": "Полтавская губерния",
    "чернігівськ": "Черниговская губерния", "харківськ": "Харьковская губерния",
    "слобідсько-українськ": "Харьковская губерния",
    "херсонськ": "Херсонская губерния", "катеринославськ": "Екатеринославская губерния",
    "таврійськ": "Таврическая губерния", "бессарабськ": "Бессарабская губерния",
    "мінськ": "Минская губерния", "гродненськ": "Гродненская губерния",
    "могильовськ": "Могилевская губерния", "могилівськ": "Могилевская губерния",
    "курськ": "Курская губерния", "воронізьк": "Воронежская губерния",
    "воронезьк": "Воронежская губерния", "люблінськ": "Люблинская губерния",
    "седлецьк": "Седлецкая губерния",
}

# Уезды, которые ключ из согласных не сводит: украинское название (как в
# колонке «Повіт», именительный падеж) → (уезд справочника 1897 года,
# губерния). Махновский уезд в 1846 году стал Бердичевским (центр перенесён),
# Ново-Ушицкий — прежнее имя Ушицкого; остальное — разное написание.
UEZD_MANUAL = {
    "Овруцький": ("Овручский", "Волынская"),
    "Прилуцький": ("Прилукский", "Полтавская"),
    "Кобеляцький": ("Кобелякский", "Полтавская"),
    "Гадяцький": ("Гадячский", "Полтавская"),
    "Кременчуцький": ("Кременчугский", "Полтавская"),
    "Костянтиноградський": ("Константиноградский", "Полтавская"),
    "Вовчанський": ("Волчанский", "Харьковская"),
    "Ново-Ушицький": ("Ушицкий", "Подольская"),
    "Новоушицький": ("Ушицкий", "Подольская"),
    "Махнівський": ("Бердичевский", "Киевская"),
    "Старокостянтинівський": ("Староконстантиновский", "Волынская"),
    "Старокостянтинівький": ("Староконстантиновский", "Волынская"),
    "Кам'янецький": ("Каменец-Подольский", "Подольская"),
    "Камянецький": ("Каменец-Подольский", "Подольская"),
    "Кам'янець-Подільський": ("Каменец-Подольский", "Подольская"),
    "Проскуровський": ("Проскуровский", "Подольская"),
}

# Колонки описи: заголовок (без разметки, в нижнем регистре) → имя.
COLUMNS = (
    ("case", re.compile(r"^(№|#|номер справи|номер|справа|спр\.?|№ справи)$")),
    ("title", re.compile(r"^(назва( справи)?|назва \(заголовок одиниці зберігання\)|анотація"
                         r"( справи)?|заголовок справ[иі]?)$")),
    ("uezd", re.compile(r"^повіт$")),
    ("gub", re.compile(r"^губернія(/воєводство)?$")),
    ("place", re.compile(r"^(нас\. пункти?|населений пункт|населені пункти|село|місто|місце)$")),
    ("church", re.compile(r"^(церква|храм|парафія)$")),
    ("rtype", re.compile(r"^тип$")),
    ("years", re.compile(r"^(роки|рік|крайні дати|дати|дата)$")),
    ("year_start", re.compile(r"^коли почато$")),
    ("year_end", re.compile(r"^коли закінчено$")),
    ("sheets", re.compile(r"^(аркуші|аркушів|арк\.?|кількість аркушів|листів)$")),
    ("pages", re.compile(r"^(сторінки|сторінок|стор\.?|кількість сторінок)$")),
    ("confession", re.compile(r"^конфесія")),
)


class ArkhivError(RuntimeError):
    """Дамп или страница не такие, какими их ждёт разбор."""


# --- дамп ------------------------------------------------------------

@dataclass(frozen=True)
class DumpFile:
    name: str
    url: str
    size: int
    md5: str


@dataclass(frozen=True)
class Dump:
    """Готовый дамп: дата, сжатые страницы и оглавление к ним."""

    date: str
    pages: DumpFile
    index: DumpFile


_RE_DUMP_DIR = re.compile(r'href="(\d{8})/"')


def dump_dates(listing: str) -> list[str]:
    """Даты дампов из оглавления каталога вики, от новых к старым."""
    return sorted(set(_RE_DUMP_DIR.findall(listing)), reverse=True)


def parse_dumpstatus(payload: dict, date: str) -> Optional[Dump]:
    """`dumpstatus.json` → дамп, если задача multistream в нём завершена."""
    job = (payload.get("jobs") or {}).get("articlesmultistreamdump") or {}
    if job.get("status") != "done":
        return None
    files = job.get("files") or {}
    found = {}
    for name, info in files.items():
        for key, suffix in (("pages", MULTISTREAM), ("index", MULTISTREAM_INDEX)):
            if name.endswith(suffix) and info.get("size") and info.get("md5"):
                found[key] = DumpFile(name, "https://dumps.wikimedia.org" + info["url"],
                                      int(info["size"]), info["md5"])
    if set(found) != {"pages", "index"}:
        return None
    return Dump(date, found["pages"], found["index"])


@dataclass(frozen=True)
class IndexEntry:
    offset: int
    page_id: int
    title: str


def parse_index(lines: Iterable[str]) -> list[IndexEntry]:
    """Оглавление multistream: «смещение:id:заголовок» построчно."""
    out = []
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        offset, page_id, title = line.split(":", 2)
        out.append(IndexEntry(int(offset), int(page_id), title))
    return out


def stream_ranges(entries: list[IndexEntry], size: int, *, prefix: str = NS_PREFIX,
                  gap: int = RANGE_GAP) -> list[tuple[int, int]]:
    """Диапазоны байт `[начало, конец)` с потоками, где есть страницы `prefix`.

    Поток кончается там, где начинается следующий; последний — концом файла.
    Соседние нужные потоки, между которыми меньше `gap` чужих, идут одним
    диапазоном.
    """
    offsets = sorted({e.offset for e in entries})
    pos = {o: i for i, o in enumerate(offsets)}
    need = sorted({e.offset for e in entries if e.title.startswith(prefix)})
    runs: list[list[int]] = []
    for offset in need:
        if runs and pos[offset] - pos[runs[-1][1]] <= gap:
            runs[-1][1] = offset
        else:
            runs.append([offset, offset])

    def end_of(offset: int) -> int:
        i = pos[offset] + 1
        return offsets[i] if i < len(offsets) else size

    return [(a, end_of(b)) for a, b in runs]


@dataclass(frozen=True)
class Page:
    title: str
    ns: int
    page_id: int
    timestamp: str
    text: str


def iter_pages(xml_text: str) -> Iterator[Page]:
    """Страницы из куска дампа: несколько потоков подряд, без корня.

    Первый поток файла несёт ещё и шапку `<mediawiki><siteinfo>`, последний —
    закрывающий `</mediawiki>`: всё, что вне `<page>…</page>`, отрезается.
    """
    start = xml_text.find("<page>")
    end = xml_text.rfind("</page>")
    if start < 0 or end < 0:
        return
    parser = ET.XMLPullParser(events=("end",))
    parser.feed("<root>")
    body = xml_text[start:end + len("</page>")]
    step = 1 << 22
    for i in range(0, len(body), step):
        parser.feed(body[i:i + step])
        for _, elem in parser.read_events():
            if elem.tag == "page":
                yield _page(elem)
                elem.clear()
    parser.feed("</root>")
    for _, elem in parser.read_events():
        if elem.tag == "page":
            yield _page(elem)


def _page(elem) -> Page:
    rev = elem.find("revision")
    return Page(
        title=elem.findtext("title") or "",
        ns=int(elem.findtext("ns") or -1),
        page_id=int(elem.findtext("id") or 0),
        timestamp=(rev.findtext("timestamp") if rev is not None else "") or "",
        text=(rev.findtext("text") if rev is not None else "") or "",
    )


def read_chunk(data: bytes) -> str:
    """Кусок дампа (несколько bz2 потоков подряд) → текст XML."""
    return bz2.decompress(data).decode("utf-8")


# --- сеть ------------------------------------------------------------

@dataclass
class Client:
    """Дамп и проверочные запросы к API: подпись, пауза, повторы."""

    pause: float = 1.0
    timeout: int = 300
    retries: int = 5
    _last: float = field(default=0.0, repr=False)
    requests: int = field(default=0, repr=False)

    def get(self, url: str, *, byte_range: Optional[tuple[int, int]] = None) -> bytes:
        headers = {"User-Agent": USER_AGENT}
        if byte_range:
            headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1] - 1}"
        error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            self._last = wait_for_pause(self._last, self.pause)
            self.requests += 1
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if byte_range and response.status != 206:
                        raise ArkhivError(f"{url}: сервер не отдал кусок (HTTP {response.status})")
                    data = response.read()
                if byte_range and len(data) != byte_range[1] - byte_range[0]:
                    raise ArkhivError(f"{url}: кусок {len(data)} байт вместо "
                                      f"{byte_range[1] - byte_range[0]}")
                return data
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_CODES:
                    raise ArkhivError(f"{url}: HTTP {exc.code}") from exc
                error = exc
                delay = _retry_after(exc) or 5.0 * (attempt + 1)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                error = exc
                delay = 5.0 * (attempt + 1)
            if attempt < self.retries:
                time.sleep(delay)
        raise ArkhivError(f"{url}: не ответил за {self.retries + 1} попыток ({error})")

    def get_json(self, url: str) -> dict:
        try:
            return json.loads(self.get(url).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ArkhivError(f"{url}: ответ не JSON ({exc})") from exc

    def latest_dump(self) -> Dump:
        """Самый новый дамп, в котором multistream уже собран."""
        dates = dump_dates(self.get(DUMPS_URL + "/").decode("utf-8", "replace"))
        for date in dates[:4]:
            payload = self.get_json(f"{DUMPS_URL}/{date}/dumpstatus.json")
            dump = parse_dumpstatus(payload, date)
            if dump:
                return dump
        raise ArkhivError(f"{DUMPS_URL}: среди {dates[:4]} нет дампа с готовым multistream")

    def api_page(self, title: str) -> Optional[str]:
        """Текущий текст страницы через API (для сверки разбора на --check)."""
        query = urllib.parse.urlencode({
            "action": "query", "prop": "revisions", "rvprop": "content|timestamp",
            "rvslots": "main", "titles": title, "format": "json", "formatversion": "2",
            "maxlag": "5",
        })
        for _ in range(3):
            payload = self.get_json(f"{API_URL}?{query}")
            if (payload.get("error") or {}).get("code") == "maxlag":
                time.sleep(5)
                continue
            pages = (payload.get("query") or {}).get("pages") or []
            if not pages or pages[0].get("missing"):
                return None
            return pages[0]["revisions"][0]["slots"]["main"]["content"]
        raise ArkhivError(f"{API_URL}: серверы Викимедиа перегружены (maxlag)")


def _retry_after(exc: urllib.error.HTTPError) -> Optional[float]:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if value and value.strip().isdigit():
        return float(value) + 1.0
    return None


def md5_of(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# --- вики-разметка ------------------------------------------------------------

_RE_REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.S)
_RE_BR = re.compile(r"<br\s*/?>", re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_RE_EXT = re.compile(r"\[(?:https?://\S+)(?:\s+([^\]]*))?\]")
_RE_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


def strip_markup(text: Optional[str]) -> str:
    """Ячейка вики-таблицы → чистый текст: ссылки — подписью, шаблоны прочь."""
    if not text:
        return ""
    s = _RE_REF.sub("", text)
    s = _RE_BR.sub(" ", s)
    s = _RE_TAG.sub("", s)
    s = re.sub(r"'{2,}", "", s)
    s = _RE_LINK.sub(r"\1", s)
    s = _RE_EXT.sub(lambda m: m.group(1) or "", s)
    for _ in range(3):
        s = _RE_TEMPLATE.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&ndash;", "–").replace("&mdash;", "—")
         .replace("⁠", "").replace("­", "").replace("\xa0", " "))
    return re.sub(r"\s+", " ", s).strip()


def split_outside(text: str, sep: str) -> list[str]:
    """Делит строку по `sep`, не заходя внутрь `[[…]]` и `{{…}}`."""
    out, cur, depth, i = [], [], 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two in ("]]", "}}") and depth:
            depth -= 1
            cur.append(two)
            i += 2
            continue
        if depth == 0 and text.startswith(sep, i):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(text[i])
        i += 1
    out.append("".join(cur))
    return out


def template_params(text: str, name: str) -> dict[str, str]:
    """Параметры шаблона `{{name | ключ = значение …}}` первого вхождения."""
    start = re.search(r"\{\{\s*" + re.escape(name) + r"\s*(?=[|}\n])", text)
    if not start:
        return {}
    depth, i = 0, start.start()
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
            continue
        i += 1
    body = text[start.end():i - 2]
    out = {}
    for part in split_outside(body, "|")[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip().lower()] = value.strip()
    return out


_RE_CATEGORY = re.compile(r"\[\[\s*(?:Категорія|Category)\s*:\s*([^\]|]+)", re.I)


def categories(text: str) -> list[str]:
    return [c.strip() for c in _RE_CATEGORY.findall(text)]


_ATTRS = re.compile(r"^\s*(?:[a-zA-Z-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s|]+)\s*)+$")


def _cell(raw: str) -> str:
    """Ячейка без атрибутов: `style="…" | текст` → `текст`."""
    parts = split_outside(raw, "|")
    if len(parts) > 1 and _ATTRS.match(parts[0]):
        return "|".join(parts[1:])
    return raw


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]


def tables(text: str) -> list[Table]:
    """Все вики-таблицы страницы: заголовок и строки как списки ячеек (с разметкой)."""
    return [_table(m.group(0).split("\n")[1:-1])
            for m in re.finditer(r"^\s*\{\|.*?^\s*\|\}", text, flags=re.S | re.M)]


def _table(lines: list[str]) -> Table:
    header: list[str] = []
    rows: list[list[str]] = []
    cur: Optional[list[str]] = None
    is_header = False
    for line in lines:
        s = line.strip()
        if not s or s.startswith("|+"):
            continue
        if s.startswith("|-"):
            _flush(cur, is_header, header, rows)
            cur, is_header = [], False
            continue
        if s.startswith("!"):
            if cur is None or (cur and not is_header):
                _flush(cur, is_header, header, rows)
                cur = []
            is_header = True
            cells = split_outside(s[1:], "!!")
            if len(cells) == 1:
                cells = split_outside(s[1:], "||")
            cur.extend(_cell(c) for c in cells)
            continue
        if s.startswith("|"):
            if cur is None:
                cur = []
            cur.extend(_cell(c) for c in split_outside(s[1:], "||"))
            continue
        if cur:
            cur[-1] += " " + s
    _flush(cur, is_header, header, rows)
    return Table(header, rows)


def _flush(cur: Optional[list[str]], is_header: bool, header: list[str],
           rows: list[list[str]]) -> None:
    """Готовая строка таблицы — в заголовок (пока строк данных нет) или в строки."""
    if cur:
        if is_header and not rows:
            header.extend(cur)
        elif not is_header:
            rows.append(cur)


def column_name(header_cell: str) -> str:
    """Заголовок колонки → имя из `COLUMNS` или `other:<как есть>`."""
    text = strip_markup(header_cell).lower().replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for name, pattern in COLUMNS:
        if pattern.search(text):
            return name
    return "other:" + text


# Описи без таблицы: «* 1. [[c:File:…|1850 рік. Метрична книга синагоги …]]».
_RE_LIST_ROW = re.compile(r"^\*\s*(\d+[а-яa-z]?)\.\s*\[\[(?:c:)?(?:File|Файл):[^|\]]*"
                          r"\|([^\]]+)\]\]",
                          re.M | re.I)


def list_rows(text: str) -> list[dict]:
    rows = []
    for case, label in _RE_LIST_ROW.findall(text):
        label = strip_markup(label)
        m = re.match(r"^([\d\s,–—-]+)\s*р(?:ік|оки|р)?\.\s*(.*)$", label)
        years, title = (m.group(1), m.group(2)) if m else ("", label)
        rows.append({"case": case, "title": title, "years": years})
    return rows


# --- опись ------------------------------------------------------------

@dataclass
class Inventory:
    """Опись: шифр, название и строки дел с колонками, сведёнными к `COLUMNS`."""

    title: str
    archive: str
    fond: str
    opis: str
    name: Optional[str]
    years: Optional[str]
    categories: list[str]
    rows: list[dict]
    timestamp: str = ""

    @property
    def code(self) -> str:
        return f"{self.archive}/{self.fond}/{self.opis}"


def split_title(title: str) -> Optional[tuple[str, ...]]:
    """«Архів:ДАЖО/1/80/177» → ("ДАЖО", "1", "80", "177")."""
    if not title.startswith(NS_PREFIX):
        return None
    return tuple(title[len(NS_PREFIX):].split("/"))


def parse_case(cell: str) -> str:
    """«[[/237а/]]» → «237а»; «[[Архів:ДАЖО/1/80/5|5]]» → «5»; «12» → «12»."""
    m = re.search(r"\[\[\s*/([^/\]|]+)/?\s*(?:\|[^\]]*)?\]\]", cell)
    if m:
        return m.group(1).strip()
    m = re.search(r"\[\[[^\]|]*/([^/\]|]+)\s*\|", cell)
    if m:
        return m.group(1).strip()
    return strip_markup(cell).strip(" .")


def parse_inventory(page: Page) -> Optional[Inventory]:
    """Страница описи → `Inventory`; не опись — None."""
    parts = split_title(page.title)
    if not parts or len(parts) != 3:
        return None
    params = template_params(page.text, "Архіви/опис")
    if not params and "{{Архіви/опис" not in page.text:
        return None
    rows: list[dict] = []
    for table in tables(page.text):
        names = [column_name(h) for h in table.header]
        if "title" not in names and "church" not in names:
            continue
        for cells in table.rows:
            row: dict = {}
            for name, cell in zip(names, cells):
                if name.startswith("other:") or name in row:
                    continue
                row[name] = parse_case(cell) if name == "case" else strip_markup(cell)
            if row.get("case") or row.get("title"):
                rows.append(row)
    if not rows:
        rows = list_rows(page.text)
    return Inventory(
        title=page.title, archive=parts[0], fond=parts[1], opis=parts[2],
        name=strip_markup(params.get("назва")) or None,
        years=strip_markup(params.get("рік")) or None,
        categories=categories(page.text), rows=rows, timestamp=page.timestamp,
    )


def fond_name(page: Page) -> Optional[str]:
    """Название фонда из `{{Архіви/фонд}}`."""
    return strip_markup(template_params(page.text, "Архіви/фонд").get("назва")) or None


# --- годы ------------------------------------------------------------

YEAR_MIN, YEAR_MAX = 1550, 1960
_RE_YEAR = re.compile(r"(?<!\d)(1[5-9]\d\d)(?!\d)")
_RE_SHORT_RANGE = re.compile(r"(?<!\d)(1[5-9]\d\d)\s*[-–—]\s*(\d\d)(?![\d.])")
_DASHES = "-–—―‐‑"


def parse_years(text: Optional[str]) -> list[tuple[int, int]]:
    """Годы дела: «1840–1865», «1876-1884, 1886-1889», «1881.01.06–1895.12.24».

    Год, за которым (после месяца, числа или их названий) идёт тире, начинает
    промежуток до следующего года; «1937-38» — промежуток 1937–1938; дни и
    месяцы («2 січня – 28 липня 1803») годами не считаются.
    """
    if not text:
        return []
    s = str(text)
    s = _RE_SHORT_RANGE.sub(lambda m: f"{m.group(1)}–{m.group(1)[:2]}{m.group(2)}", s)
    found = [(m.start(), m.end(), int(m.group(1))) for m in _RE_YEAR.finditer(s)]
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(found):
        _, end, year = found[i]
        if i + 1 < len(found):
            between = s[end:found[i + 1][0]]
            # «1881.01.06–1895…», «1919-апрель, август, октябрь 1921»: тире
            # после года (через числа месяца и названия месяцев) — промежуток.
            head = re.match(r"^[\s.\d]*([" + _DASHES + r"]|\s+(?:по|до)\s)", between)
            if head and not re.search(r"[;]", between[:head.end()]):
                last = found[i + 1][2]
                if last >= year:
                    out.append((year, last))
                    i += 2
                    continue
        out.append((year, year))
        i += 1
    return [(a, b) for a, b in out if YEAR_MIN <= a <= YEAR_MAX and YEAR_MIN <= b <= YEAR_MAX]


def compact_years(years: Iterable[int]) -> str:
    """{1840, 1841, 1842, 1850} → «1840–1842, 1850»."""
    ys = sorted(set(years))
    if not ys:
        return ""
    parts, start, prev = [], ys[0], ys[0]
    for y in ys[1:]:
        if y == prev + 1:
            prev = y
            continue
        parts.append(f"{start}–{prev}" if prev > start else str(start))
        start = prev = y
    parts.append(f"{start}–{prev}" if prev > start else str(start))
    return ", ".join(parts)


def expand(intervals: Iterable[tuple[int, int]]) -> set[int]:
    out: set[int] = set()
    for a, b in intervals:
        out.update(range(a, b + 1))
    return out


# --- тип записей ------------------------------------------------------------

RECORD_TYPES = (
    ("рождение", re.compile(r"народж|хрещ|родивш|рожден|урод", re.I)),
    ("брак", re.compile(r"шлюб|одруж|вінчан|бракосоч|брак(?!у)|сочетав", re.I)),
    ("развод", re.compile(r"розлуч|розірв|развод", re.I)),
    ("смерть", re.compile(r"смерт|помер|похов|умерш", re.I)),
)


def record_types(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    return {name for name, pattern in RECORD_TYPES if pattern.search(text)}


# --- кто вёл книгу ------------------------------------------------------------

# Название дела про метрические книги и названия, которые на них только
# ссылаются («Про видачу метричного свідоцтва …», «Справа про надання
# довідки з метричної книги …»): первые берутся, вторые — нет.
_RE_METRIC = re.compile(r"(?<![а-яіїєґ'])метри[чк]\w*\s+(книг|книж|запис)", re.I)
_RE_METRIC_ANY = re.compile(r"(?<![а-яіїєґ'])метри[чк]", re.I)
_RE_NOT_BOOK = re.compile(
    r"^\s*(про|справа|справи|по|документи|відомост|рапорт|указ|листуван|прохан|"
    r"переписк|журнал|протокол|постанов|розпорядж|клопотан|скарг|о\s|об\s|дело|статистичн)\b|"
    r"свідоцтв|довідк|виписк|випис[иі]|витяг|выпис|справк|екстракт",
    re.I)
_RE_LEAD = re.compile(
    r"^\s*(?:\d+(?:\s*,\s*\d+)*\s+)?(?:копі[яії]\s+|чорнов\w+\s+|дублікат\w*\s+|алфавіт\w*\s+"
    r"(?:журнал\w*\s+)?(?:до\s+)?|покажчик\w*\s+(?:до\s+)?)?(?:єврейськ\w+\s+|додатков\w+\s+|"
    r"римо-католицьк\w+\s+|православн\w+\s+)?(?:церковно[- ]?)?метри[чк]\w*\s+"
    r"(?:книг\w*|книжк\w*|запис\w*)\s*",
    re.I)
# Служебное начало ячейки перед названием: «|», номера и «№», «1928 рік.»,
# «ЦДІАК фонд 1165, опис 1, справа 10.».
_RE_JUNK_HEAD = re.compile(
    r"^\s*(?:\|+\s*|1[5-9]\d\d\s*рік\.?\s*|ЦДІАК\s+фонд\s+\d+,\s*опис\s+\d+,\s*справа\s+\d+\w*\.\s*|"
    r"(?:[\d][\d\s,.\-–]*\s*(?:№\s*\d+\.?)?\s+)(?=[А-ЯІЇЄҐа-яіїєґ])|№\s*\d+\.?\s+)+")
_RE_TAIL_METRIC = re.compile(r"[.,]?\s*(?:копі[яї]\s+)?(?:церковно[- ]?)?метри[чк]\w*\s+"
                             r"(?:книг\w*|запис\w*)\s*\.?\s*$", re.I)
_RE_CONTINUATION = re.compile(r"^\s*(?:те\s+(?:ж\s+)?саме|те\s+ж|то\s+же|тоже)\b\s*[.,]?\s*(.*)$",
                              re.I)

_RTYPE_WORD = (r"(?:народжен\w*|народжень|хрещен\w*|шлюб\w*|одружен\w*|розлучен\w*|розірван\w*"
               r"(?:\s+шлюб\w*)?|смерт\w*|померл\w*|бракосочетавш\w*|родивш\w*|умерш\w*|вінчан\w*|"
               r"рождени\w*|браках?|смерти)")
# Тип записей и служебные хвосты в названии: снимаются, чтобы «Метрична книга
# церкви … . Народження» и «… про смерть» легли в одну запись прихода.
_RE_RTYPE = re.compile(
    r"[.,;:]?\s*\(?\s*(?:запис\w*\s+)?(?:про|о|об)?\s*(?:реєстрації\s+актів\s+(?:про\s+)?)?"
    + _RTYPE_WORD + r"(?:\s*(?:,|та|і|й|&|и|–|-)\s*(?:про\s+)?" + _RTYPE_WORD + r")*\s*\)?",
    re.I)
_RE_SERVICE = re.compile(
    r"\s*[.,]?\s*(?:копі[яї]|копії|частина справи|чорновик\w*|дублікат\w*|фрагмент\w*|"
    r"(?:\(|\s)вибула\)?|т(?:ом)?\.?\s*\d+|ч(?:астина)?\.?\s*\d+|перша частина|друга частина|"
    r"один запис|\(\s*\))\s*\.?\s*$", re.I)
_MONTHS_UK = (r"(?:січ\w*|лют\w*|берез\w*|квіт\w*|трав\w*|черв\w*|лип\w*|серп\w*|верес\w*|жовт\w*|"
              r"листоп\w*|груд\w*)")
_RE_YEARS_PHRASE = re.compile(
    r"\s*[,;(–-]?\s*(?:за\s+)?(?:\d{1,2}\s+)?(?:" + _MONTHS_UK + r"\s*)?[–—-]?\s*"
    r"(?:\d{1,2}\.\d{1,2}\.)?1[5-9]\d\d(?:\s*[-–—,]\s*(?:" + _MONTHS_UK + r"\s*)?"
    r"(?:\d{1,2}\.\d{1,2}\.)?"
    r"1?[5-9]?\d?\d)*\s*(?:рр?\.|роки|рік|років|р\.|року)?\s*\)?", re.I)
_RE_UEZD = re.compile(
    r"\s*,?\s*([А-ЯІЇЄҐ][\w'’ʼ-]*?(?:ськ|цьк|зьк|ск|цк|зк)(?:ого|ому|ий|ій))\s+"
    r"(?:повіту|повіт|пов\b\.?|уезда|у\.)", re.U)
_RE_UEZD_AFTER = re.compile(r"\s*,?\s*(?:повіт|п\.)\s+([А-ЯІЇЄҐ][\w'’ʼ-]+"
                            r"(?:[ -][А-ЯІЇЄҐ][\w'’ʼ-]+)?)",
                            re.U)
_RE_GUB = re.compile(r"\s*,?\s*([А-ЯІЇЄҐ][\w'’ʼ-]*?(?:ськ|цьк|зьк)(?:ої|ій|а))\s+"
                     r"(?:губернії|губ\.)",
                     re.U)
_RE_VOIV = re.compile(r"\s*,?\s*([А-ЯІЇЄҐ][\w'’ʼ-]*?(?:ськ|цьк|зьк)(?:ого|ому|е))\s+"
                      r"(?:воєводства|воєв\.|воєводство)", re.U)
_RE_OTHER_UNIT = re.compile(
    r"\s*,?\s*([А-ЯІЇЄҐ][\w'’ʼ-]*?(?:ськ|цьк|зьк)(?:ої|ого|ій))\s+"
    r"(?:волості|області|району|округу|намісництва|протопопії|сотні|сот\.|полку|п\.|"
    r"єпархії|духовної консисторії|деканату|благочиння)", re.U)
_RE_LETTERS = re.compile(r"\s*[.,]?\s*(?:Села|Села\s+на\s+літери|Літери)\s+"
                         r"([А-ЯІЇЄҐ]\s*[–—-]\s*[А-ЯІЇЄҐ]|"
                         r"[А-ЯІЇЄҐ](?:\s*,\s*[А-ЯІЇЄҐ])*)\s*\.?", re.U)

# Пометы поселения: «с.», «м-ко», «містечка» … → короткая форма. Множественные
# («сс.», «сіл») открывают перечень названий через запятую.
SETTLEMENT_MARKS = {
    "с": "с.", "с.": "с.", "село": "с.", "селі": "с.", "сел.": "с.", "селя": "с.", "селища": "с.",
    "сс.": "сс.", "сіл": "сс.", "села": "с.",
    "м": "м.", "м.": "м.", "міста": "м.", "місто": "м.", "г.": "м.",
    "м-ко": "м-ко", "м-ка": "м-ко", "м-ку": "м-ко", "мст.": "м-ко", "містечка": "м-ко",
    "містечко": "м-ко", "смт": "смт",
    "сл.": "сл.", "слободи": "сл.", "слобода": "сл.",
    "х.": "х.", "хут.": "х.", "хутора": "х.", "хутір": "х.", "хуторів": "хх.",
    "кол.": "кол.", "колонії": "кол.", "колонія": "кол.", "д.": "д.",
    "пос.": "пос.", "посаду": "пос.", "ст.": "ст.", "станиці": "ст.",
}
_PLURAL_MARKS = {"сс.", "хх."}
_MARKS_RX = "|".join(sorted((re.escape(k) for k in SETTLEMENT_MARKS), key=len, reverse=True))
_NAME_WORD = r"[А-ЯІЇЄҐ][\w'’ʼ\-⁠]*"
_NAME = _NAME_WORD + r"(?:[\s-](?:" + _NAME_WORD + r"|на|над|під|при|біля))*"
_RE_SETTLEMENT = re.compile(
    r"(?<![\w-])(" + _MARKS_RX + r")(?=[\s ]|(?<=\.)[А-ЯІЇЄҐ])\s*(" + _NAME + r")", re.U)
_RE_NAME_LIST = re.compile(r"\s*(?:,|та|і|й|и)\s*(" + _NAME + r")", re.U)

# Города в косвенном падеже («у м. Києві», «м. Житомира») → именительный.
CITY_FORMS = {
    "києві": "Київ", "києва": "Київ", "житомира": "Житомир", "житомирі": "Житомир",
    "харкова": "Харків", "харкові": "Харків", "одеси": "Одеса", "одесі": "Одеса",
    "полтави": "Полтава", "полтаві": "Полтава", "чернігова": "Чернігів", "чернігові": "Чернігів",
    "луцька": "Луцьк", "луцьку": "Луцьк", "херсона": "Херсон", "херсоні": "Херсон",
    "катеринослава": "Катеринослав", "миколаєва": "Миколаїв", "вінниці": "Вінниця",
    "бердичева": "Бердичів", "умані": "Умань", "черкас": "Черкаси", "кременчука": "Кременчук",
    "єлисаветграда": "Єлисаветград", "ромен": "Ромни", "ніжина": "Ніжин", "сум": "Суми",
    "ізюма": "Ізюм", "олександрівська": "Олександрівськ", "севастополя": "Севастополь",
    "сімферополя": "Сімферополь", "феодосії": "Феодосія", "тирасполя": "Тирасполь",
    "рівного": "Рівне", "ровно": "Рівне", "дубна": "Дубно", "острога": "Острог",
    "ковеля": "Ковель", "кременця": "Кременець", "лубен": "Лубни", "прилук": "Прилуки",
}

# Вид храма или общины → как его назвать по-русски, и конфессия, если названа.
CHURCH_KINDS = (
    ("синагога, еврейская община", re.compile(
        r"синагог|рабин|равин|єврей|євреї|іудей|иудей|молитовн\w+\s+(?:школ|будин)|"
        r"молитвенн|караїм", re.I), "иудейская"),
    ("костёл", re.compile(r"костел|костьол|костёл|римо-?католи|римсько-?католи|"
                          r"францискан|бернардин|домінікан|капуцин", re.I), "римско-католическая"),
    ("кирха, протестантский приход", re.compile(
        r"кірх|кирх|лютеран|євангел|евангел|реформат|менонит|баптист", re.I), "протестантская"),
    ("мечеть", re.compile(r"мечет|магометан|мусульман", re.I), "мусульманская"),
    ("старообрядческая община", re.compile(r"старообряд|розкольн|раскольн|єдиновір", re.I),
     "старообрядческая"),
    ("греко-католическая церковь", re.compile(r"уніат|греко-?католи|униат", re.I),
     "греко-католическая"),
    ("армянская церковь", re.compile(r"вірмен|армян", re.I), "армяно-григорианская"),
    ("церковь", re.compile(r"церк|собор|храм|каплиц|монастир|парафі|приход|лавр", re.I), None),
)
_RE_ORTHODOX = re.compile(r"православн", re.I)
GROUP_LABEL = "сводные книги нескольких приходов"

# Признаки сводной книги нескольких приходов: «церков … повіту», «Села Б–Я».
_RE_GROUP = re.compile(
    r"(?<![\w'])(?:церков|костелів|парафій|синагог|громад|сіл|різних|деканат\w*|благочин\w*|"
    r"протопопі\w*|округ\w*|римо-католицьких|православних|уніатських|греко-католицьких)(?![\w'])",
    re.I)
_RE_ATTACHED = re.compile(r"приписн|приписан|приєднан|філіал|(?:^|\s)(?:та|і|й)\s*$", re.I)


@dataclass(frozen=True)
class Subject:
    """Кто вёл книги: церковь села, община, сводная книга уезда."""

    kind: str                      # church | group | unknown
    text: str                      # фраза источника: «церкви с. Бобли»
    church: str                    # вид по-русски: церковь, костёл, синагога…
    confession: Optional[str] = None
    marker: Optional[str] = None   # «с.», «м.», «м-ко» …
    settlement: Optional[str] = None
    dedication: Optional[str] = None
    uezd_uk: Optional[str] = None
    gub_uk: Optional[str] = None
    voiv_uk: Optional[str] = None
    letters: Optional[str] = None

    @property
    def key(self) -> str:
        """Ключ записи внутри описи: у прихода — село и посвящение, у сводных
        книг — их название и уезд (у каждого уезда свои тома)."""
        if self.kind == "church" and self.settlement:
            return "|".join((self.church, name_key(self.settlement), norm_key(self.dedication)))
        return "|".join((self.kind, self.church, norm_key(self.text), norm_key(self.uezd_uk)))


def norm_key(text: Optional[str]) -> str:
    """Нормализация для ключей: регистр, апострофы, пробелы, знаки по краям."""
    if not text:
        return ""
    s = text.lower().replace("ё", "е").replace("’", "'").replace("ʼ", "'").replace("`", "'")
    s = s.replace("⁠", "").replace("\xa0", " ")
    s = re.sub(r"\bсв\.\s*", "св. ", s)
    s = re.sub(r"[«»\"“”()]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .,;:-–—")


def name_key(name: Optional[str]) -> str:
    """Ключ названия поселения: «Вижва, м-⁠ко» и «Вижва» — одно и то же."""
    s = norm_key(name)
    s = re.sub(r",?\s*(м-ко|м\.|с\.|сл\.|х\.|мст\.)$", "", s)
    return s.replace("-", " ").strip()


def church_kind(text: str) -> tuple[str, Optional[str]]:
    for label, pattern, confession in CHURCH_KINDS:
        if pattern.search(text):
            if confession is None and _RE_ORTHODOX.search(text):
                return label, "православная"
            return label, confession
    return "церковь", "православная" if _RE_ORTHODOX.search(text) else None


def uk_nominative(adjective: Optional[str]) -> Optional[str]:
    """«Ковельського» / «Ковельському» → «Ковельський»; «Київської» → «Київська»."""
    if not adjective:
        return None
    a = adjective.strip()
    for tail, repl in (("ського", "ський"), ("ському", "ський"), ("цького", "цький"),
                       ("цькому", "цький"), ("зького", "зький"), ("зькому", "зький"),
                       ("ської", "ська"), ("цької", "цька"), ("зької", "зька"),
                       ("ській", "ська"), ("ького", "ький"), ("ькому", "ький"),
                       ("ське", "ське")):
        if a.endswith(tail):
            return a[: -len(tail)] + repl
    return a


def city_name(name: Optional[str]) -> Optional[str]:
    """«Києві» → «Київ»; остальное — как есть."""
    if not name:
        return name
    return CITY_FORMS.get(name.lower().replace("’", "'"), name)


@dataclass
class _Clean:
    text: str
    with_years: str
    letters: Optional[str]
    uezd: Optional[str]
    gub: Optional[str]
    voiv: Optional[str]


def _clean_title(title: str) -> _Clean:
    """Название дела без слов «метрична книга», типа записей и служебных хвостов;
    уезд, губерния, воеводство и буквы сводного тома — отдельно."""
    s = (clean_text(title) or "").replace("⁠", "")
    # «Церква св. Георгія м. Кам'янець-Подільський. Метричні книги»: приход до
    # слов «метричні книги», а не после.
    tail = _RE_TAIL_METRIC.search(s)
    if tail and tail.start() > 0 and not _RE_LEAD.match(s):
        s = s[: tail.start()]
    else:
        s = _RE_LEAD.sub("", s, count=1)
    s = re.sub(r"(?i)\b(?:парафіян\w*|прихожан\w*|парафіяльн\w+)\s+", "", s)
    s = re.sub(r"(?i)^\s*(?:запис\w*\s+)?(?:про\s+)?", "", s)
    letters = None
    m = _RE_LETTERS.search(s)
    if m:
        letters = re.sub(r"\s+", "", m.group(1))
        s = s[: m.start()] + " " + s[m.end():]
    for _ in range(4):
        s2 = _RE_SERVICE.sub("", _RE_RTYPE.sub(" ", s)).strip(" .,;:")
        if s2 == s:
            break
        s = s2
    gub = voiv = uezd = None
    m = _RE_GUB.search(s)
    if m:
        gub = uk_nominative(m.group(1))
        s = s[: m.start()] + s[m.end():]
    m = _RE_VOIV.search(s)
    if m:
        voiv = uk_nominative(m.group(1))
        s = s[: m.start()] + s[m.end():]
    m = _RE_UEZD.search(s)
    if m:
        uezd = uk_nominative(m.group(1))
    else:
        m = _RE_UEZD_AFTER.search(s)
        if m:
            uezd = m.group(1).strip()
    s = _RE_UEZD.sub(" ", s)
    with_years = re.sub(r"\s+", " ", _RE_OTHER_UNIT.sub(" ", s)).strip(" .,;:–—-")
    s = _RE_UEZD_AFTER.sub(" ", s)
    s = _RE_OTHER_UNIT.sub(" ", s)
    s = _RE_YEARS_PHRASE.sub(" ", s)
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;:–—-")
    return _Clean(s, with_years, letters, uezd, gub, voiv)


def parse_subject(title: str) -> Subject:
    """Название дела → кто вёл книги (один приход или сводная книга).

    «Метричні книги церкви с. Бобли Ковельського повіту» → церковь, село
    Бобли, уезд «Ковельський». «Метричні книги православних церков
    Ковельського повіту. Села Б–Я» → сводная книга уезда, буквы «Б–Я».
    «Метрична книга» без продолжения → `unknown`: приход в названии не назван.
    Названия с несколькими сёлами раскладывает `split_subjects`.
    """
    c = _clean_title(title)
    text = c.text
    kind_label, confession = church_kind(text or title)
    settlement = marker = dedication = None
    found = list(_RE_SETTLEMENT.finditer(text))
    if found:
        first = found[0]
        marker = SETTLEMENT_MARKS.get(first.group(1).lower(), first.group(1))
        settlement = city_name(_trim_name(first.group(2)))
        dedication = _dedication(text[: first.start()])
    group = bool(_RE_GROUP.search(text)) or bool(c.letters) or marker in _PLURAL_MARKS \
        or len(found) > 1
    if not text:
        kind = "group" if c.uezd else "unknown"
        text = f"{c.uezd} повіт" if c.uezd and _is_adjective(c.uezd) else (
            f"повіт {c.uezd}" if c.uezd else "")
    elif group:
        kind = "group"
    elif settlement:
        kind = "church"
    else:
        # «Одеського рабинату», «костелу Коростишів»: поселение без пометы —
        # слово с большой буквы после вида храма, если оно одно.
        m = re.search(r"(?:костел\w*|церкв\w*|синагог\w*|собор\w*|громад\w*|рабинат\w*)\s+("
                      + _NAME_WORD + r")$", text, re.I)
        if m:
            settlement = city_name(m.group(1))
            dedication = _dedication(text[: m.start()])
        kind = "church"
    return Subject(kind=kind, text=text, church=kind_label if kind != "group" else GROUP_LABEL,
                   confession=confession, marker=marker, settlement=settlement,
                   dedication=dedication, uezd_uk=c.uezd, gub_uk=c.gub, voiv_uk=c.voiv,
                   letters=c.letters)


@dataclass(frozen=True)
class Part:
    """Один приход из названия дела с несколькими сёлами."""

    subject: Subject
    years: tuple[tuple[int, int], ...] = ()
    attached: tuple[str, ...] = ()


def split_subjects(title: str) -> list[Part]:
    """Название дела с несколькими сёлами → приход на каждое село.

    «Метрична книга церкви Різдва Богородиці с. Андрушівка та приписної
    церкви Троїцької с. Гардишівка» — приход Андрушівки с приписной
    Гардишівкой; «… Михайлівської церкви в с. Дроздні та Успенської церкви
    в с. Доротище» — два прихода; «Метричні книги с. Вовків за 1858 р.;
    с. Плетеничі за 1836-1839 рр.» — два села, у каждого свои годы.
    Сводная книга уезда без названных сёл остаётся одной частью.
    """
    base = parse_subject(title)
    c = _clean_title(title)
    text = c.with_years
    found = list(_RE_SETTLEMENT.finditer(text))
    plural = any(SETTLEMENT_MARKS.get(m.group(1).lower()) in _PLURAL_MARKS for m in found)
    if len(found) < 2 and not plural:
        return [Part(base)]
    parts: list[Part] = []
    pos = 0
    first_church = attaching = False
    for i, m in enumerate(found):
        before = text[pos:m.start()]
        marker = SETTLEMENT_MARKS.get(m.group(1).lower(), m.group(1))
        names = [_trim_name(m.group(2))]
        end = m.end()
        if marker in _PLURAL_MARKS:
            for nm in _RE_NAME_LIST.finditer(text, end):
                if nm.start() != end:
                    break
                names.append(_trim_name(nm.group(1)))
                end = nm.end()
        stop = found[i + 1].start() if i + 1 < len(found) else len(text)
        after = text[end:stop]
        years = tuple(parse_years(after.split(";")[0]))
        uezd = None
        um = _RE_UEZD.search(after) or _RE_UEZD_AFTER.search(after)
        if um:
            uezd = uk_nominative(um.group(1)) if um.re is _RE_UEZD else um.group(1).strip()
        # Посвящение — из куска перед пометой; у второго и следующих сёл — после
        # последней запятой или скобки: «м. Сміле (… церков), Троїцької церкви с. …».
        own = before if not parts else re.split(r"[,;)]", before)[-1]
        dedication = _dedication(own)
        has_church = bool(dedication) or bool(re.search(
            r"(?i)церк|костел|синагог|собор|каплиц|громад", own))
        if not parts or has_church:
            attached = False
        elif re.search(r"(?i)приписн|приписан|приєднан", before) or (
                "(" in before and ")" not in before):
            attached = True
        elif marker in _PLURAL_MARKS and first_church:
            attached = True
        else:
            attached = attaching and not before.strip(" ,;.іта")
        if not parts:
            first_church = has_church or bool(re.search(r"(?i)церк|костел|синагог", before))
        attaching = attached
        single = "с." if marker == "сс." else ("х." if marker == "хх." else marker)
        for name in names:
            if not name:
                continue
            name = city_name(name)
            if attached and parts:
                prev = parts[-1]
                parts[-1] = Part(prev.subject, prev.years, prev.attached + (name,))
                continue
            label, confession = church_kind(before + " " + base.text)
            if label == GROUP_LABEL:
                label = "церковь"
            subject = Subject(kind="church", text=f"{single} {name}" + (
                f", {dedication}" if dedication else ""), church=label,
                confession=confession or base.confession, marker=single, settlement=name,
                dedication=dedication, uezd_uk=uezd or c.uezd, gub_uk=c.gub, voiv_uk=c.voiv)
            parts.append(Part(subject, years))
        pos = stop if marker in _PLURAL_MARKS else end
    # «… в с. Дроздні та … в с. Доротище … за 1843 рік»: годы названы только у
    # последнего села и относятся ко всему делу, а не к нему одному.
    with_years = [i for i, p in enumerate(parts) if p.years]
    if with_years == [len(parts) - 1] and len(parts) > 1:
        parts = [Part(p.subject, (), p.attached) for p in parts]
    return parts or [Part(base)]


def _is_adjective(word: str) -> bool:
    return bool(re.search(r"(ський|цький|зький|ська|цька)$", word))


def _trim_name(name: str) -> str:
    """«Мала Глуша Ковельського» → «Мала Глуша»: прилагательное уезда — не имя."""
    words = name.split()
    while len(words) > 1 and re.search(r"(ського|цького|зького|ської|цької|ському|ській)$",
                                       words[-1]):
        words.pop()
    return " ".join(words).strip(" ,.-")


def _dedication(before: str) -> Optional[str]:
    """«Покровської церкви» / «церкви Покрови Пресвятої Богородиці» → посвящение."""
    s = re.sub(r"(?i)\b(?:православн\w*|римо-?католицьк\w*|греко-?католицьк\w*|уніатськ\w*|"
               r"парафіяльн\w*|приходськ\w*|соборн\w*|кладовищенськ\w*|приписн\w*|приписан\w*|"
               r"волинськ\w+ духовн\w+ консисторії|поліськ\w+ духовн\w+ консисторії)\b",
               " ", before)
    s = re.sub(r"(?i)\b(?:церкв[аиіу]|церков|костел\w*|синагог\w*|собор\w*|каплиц\w*|храм\w*|"
               r"парафі\w*|кірх\w*|монастир\w*|громад\w*|єврейськ\w*|рабинат\w*|євреїв)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.;:–—-")
    s = re.sub(r"(?i)^(?:по|при|у|в|та|і|й|и|а також)\s+", "", s)
    s = re.sub(r"(?i)\s+(?:у|в|на|та|і|й|при|по)$", "", s).strip(" ,.;:()[]+")
    if not s or len(s) > 90 or re.search(r"\d", s) or s.lower() in _STOPWORDS:
        return None
    # Посвящение называет святого или праздник: без заглавной буквы это
    # обрывок перечня («сіл +»), а не посвящение.
    if not re.search(r"[А-ЯІЇЄҐ]", s):
        return None
    return s


_STOPWORDS = {"та", "і", "й", "и", "по", "у", "в", "при", "на", "а", "також", "ін", "та ін"}


# --- строки описи → дела ------------------------------------------------------

@dataclass
class Item:
    """Дело про метрические книги одного прихода (или сводная книга)."""

    case: str
    title: str
    years: list[tuple[int, int]]
    years_raw: str
    sheets: Optional[int]
    unit: str
    rtypes: set[str]
    subject: Subject
    uezd_uk: Optional[str]
    gub_uk: Optional[str]
    villages: tuple[str, ...] = ()
    via_contents: bool = False


def _number(text: Optional[str]) -> Optional[int]:
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else None


def strip_head(title: str) -> str:
    """Название без служебного начала ячейки («|», «1-55», «1928 рік.»)."""
    return _RE_JUNK_HEAD.sub("", title or "", count=1)


def is_metric_title(title: str) -> bool:
    """Название дела говорит о самих метрических книгах, а не о справке из них.

    Метрическая книга — если название с неё начинается («Метрична книга …»,
    «Копії метричних книг …», «Алфавіт метричних книг …») или ею кончается
    после названия храма («Церква св. Георгія … . Метричні книги»). Слова
    «метричних книг» в середине названия — это дело о книгах («За скаргою
    на священника … за видачу актів із метричних книг», «Листування … про
    надсилання метричних книг»), в нём нет самих записей, зато бывают имена.
    «Метрика» без «книги» — тоже не метрическая книга: Литовская и Коронная
    метрики — канцелярские архивы, Иосифинская и Францисканская — кадастры.
    """
    if not title or not _RE_METRIC_ANY.search(title):
        return False
    head = strip_head(title)
    if _RE_LEAD.match(head):
        return True
    tail = _RE_TAIL_METRIC.search(head)
    if tail and tail.start() > 0:
        before = head[: tail.start()]
        return bool(re.search(r"(?i)церк|костел|синагог|собор|громад|парафі|рабин|кірх", before)) \
            and not _RE_NOT_BOOK.search(before)
    return False


def metric_collection(inv: Inventory) -> bool:
    """Опись целиком из метрических книг — по её названию."""
    name = inv.name or ""
    return bool(re.search(r"(?i)метри[чк]\w*\s+(книг|запис)", name)) and not re.search(
        r"(?i)свідоцтв|довідк|виписк", name)


def inventory_items(inv: Inventory, fond: Optional[str] = None) -> list[Item]:
    """Дела описи про метрические книги.

    Берутся строки с метрическими книгами в названии; строки «Те саме
    (смерті)» — продолжение предыдущей; в описях-коллекциях метрических книг
    (по названию описи) — и строки с одним типом записей («народження»),
    если приход назван в колонках «Церква» или «Нас. пункт». Приход, не
    названный в строке, берётся из названия описи или фонда («Церква
    Покрови … с. Чаплинка», «Синагога, м. Олександрівськ»).
    """
    out: list[Item] = []
    collection = metric_collection(inv)
    owner = _owner(inv, fond)
    prev: list[Item] = []
    for row in inv.rows:
        title = row.get("title") or ""
        cont = _RE_CONTINUATION.match(title)
        place = row.get("place") or ""
        church = row.get("church") or ""
        years_raw = row.get("years") or ""
        if not years_raw and (row.get("year_start") or row.get("year_end")):
            years_raw = "–".join(x for x in (row.get("year_start"), row.get("year_end")) if x)
        sheets = _number(row.get("sheets"))
        unit = "арк."
        if sheets is None and row.get("pages"):
            sheets, unit = _number(row.get("pages")), "стор."
        row_years = parse_years(years_raw) or parse_years(_years_in_title(title))
        rest = None
        if cont:
            # «Те саме, за 1851-1856 рр. Метричні книги сс. Букавина, …»: продолжение
            # предыдущей строки за свои годы и новое дело в той же ячейке.
            m = re.search(r"(?i)(?:копі[яї]\s+)?(?:церковно[- ]?)?метри[чк]\w*\s+(?:книг|запис)",
                          cont.group(1))
            if m and m.start() > 0:
                rest = cont.group(1)[m.start():]
        if cont and prev:
            cont_years = parse_years(cont.group(1)[:-len(rest)] if rest else cont.group(1))
            rtypes = record_types(cont.group(1) if not rest else cont.group(1)[:-len(rest)])
            items = [Item(case=row.get("case") or "", title=p.title,
                          years=cont_years if rest and cont_years else row_years,
                          years_raw=compact_years(expand(cont_years)) if rest and cont_years
                          else years_raw, sheets=sheets, unit=unit,
                          rtypes=rtypes or set(p.rtypes), subject=p.subject, uezd_uk=p.uezd_uk,
                          gub_uk=p.gub_uk, villages=p.villages) for p in prev]
            out.extend(items)
            if not rest:
                continue
        if rest:
            title = rest
        if not (is_metric_title(title) or (collection and (place or church)
                                           and not _RE_NOT_BOOK.search(title)
                                           and not re.search(r"(?i)реєстрац\w+\s+акт", title))):
            prev = []
            continue
        rtypes = record_types(title) | record_types(row.get("rtype"))
        uezd_cell = _uezd_cell(row.get("uezd"))
        gub_cell, voiv_cell = _gub_cell(row.get("gub"))
        title = strip_head(title)
        if place or church:
            parts = subject_parts_from_row(title, place, church, row.get("uezd"))
        else:
            parts = split_subjects(title)
        if owner is not None and len(parts) == 1 and parts[0].subject.kind == "unknown":
            parts = [Part(owner)]
        items = []
        for part in parts:
            subject = part.subject
            if voiv_cell and not subject.voiv_uk:
                subject = _replace(subject, voiv_uk=voiv_cell)
            items.append(Item(
                case=row.get("case") or "", title=title,
                years=list(part.years) or row_years, years_raw=years_raw if not part.years
                else compact_years(expand(part.years)),
                sheets=sheets, unit=unit, rtypes=rtypes, subject=subject,
                uezd_uk=subject.uezd_uk or uezd_cell, gub_uk=gub_cell or subject.gub_uk,
                villages=part.attached,
            ))
        out.extend(items)
        prev = items
    return out


def _replace(subject: Subject, **changes) -> Subject:
    from dataclasses import replace
    return replace(subject, **changes)


def _owner(inv: Inventory, fond: Optional[str]) -> Optional[Subject]:
    """Приход, которому принадлежит вся опись (или весь фонд), если он назван."""
    for name in (inv.name, fond):
        if not name:
            continue
        subject = parse_subject(re.sub(r"(?i)^\s*опис\s*\d*\w*\.?\s*", "", name))
        if subject.kind == "church" and subject.settlement and not _RE_GROUP.search(name):
            return subject
    return None


def _years_in_title(title: str) -> str:
    m = re.search(r"за\s+([\d\s,–—-]+)\s*(?:рр?\.|роки|рік|р\.)", title or "")
    return m.group(1) if m else ""


def _uezd_cell(text: Optional[str]) -> Optional[str]:
    """Колонка «Повіт»: «Ковельський»; «Бердичівський, Житомирський» — первый."""
    s = clean_text(text)
    if not s:
        return None
    s = re.split(r"[,;/]", s)[0].strip()
    s = re.sub(r"\s+повіт$", "", s)
    return uk_nominative(s) or None


def _gub_cell(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Колонка «Губернія/воєводство» → (губерния, воеводство) по-украински."""
    s = clean_text(text)
    if not s:
        return None, None
    s = re.split(r"[,;/]", s)[0].strip()
    if re.search(r"(?i)воєводств|намісництв", s):
        return None, re.sub(r"(?i)\s+(воєводство|намісництво)$", "", s)
    return uk_nominative(re.sub(r"(?i)\s+губернія$", "", s)), None


def subject_parts_from_row(title: str, place: str, church: str, uezd: Optional[str]) -> list[Part]:
    """Приход из колонок «Церква» / «Нас. пункт», а если их нет — из названия.

    В колонке поселения бывает несколько сёл («Косонь, Запсонь, Баркасово» у
    ДАЗкО) — тогда у каждого своя часть.
    """
    parsed = parse_subject(title)
    place_s = (clean_text(place) or "").replace("⁠", "")
    church_s = clean_text(church) or ""
    label, confession = church_kind(" ".join((church_s, title, place_s)))
    if re.fullmatch(r"(?i)\s*(рацс|загс)\s*", church_s):
        label, confession = "орган записи актов гражданского состояния", None
    dedication = church_s if church_s and label not in (
        "синагога, еврейская община", "орган записи актов гражданского состояния") \
        and not re.fullmatch(r"(?i)\s*(євреї|римо-католицький костел|костел)\s*", church_s) \
        else None
    names: list[tuple[Optional[str], str]] = []
    for chunk in re.split(r"\s*[,;]\s*|\s+та\s+|\s+і\s+", place_s):
        chunk = chunk.strip(" .")
        if not chunk:
            continue
        m = _RE_SETTLEMENT.match(chunk)
        if m:
            names.append((SETTLEMENT_MARKS.get(m.group(1).lower(), m.group(1)),
                          _trim_name(m.group(2))))
        elif re.match(r"^[А-ЯІЇЄҐA-Z]", chunk):
            names.append((None, re.split(r"[(]", chunk)[0].strip()))
    if not names:
        return [Part(parsed)]
    out = []
    for marker, name in names:
        marker = {"сс.": "с.", "хх.": "х."}.get(marker or "", marker)
        name = city_name(name)
        out.append(Part(Subject(
            kind="church", text=", ".join(p for p in (church_s, f"{marker} {name}" if marker
                                                       else name) if p),
            church=label if label != GROUP_LABEL else "церковь",
            confession=confession or parsed.confession, marker=marker, settlement=name,
            dedication=dedication, uezd_uk=_uezd_cell(uezd) or parsed.uezd_uk,
            gub_uk=parsed.gub_uk, voiv_uk=parsed.voiv_uk)))
    return out


# --- «Зміст» сводных томов ----------------------------------------------------

@dataclass(frozen=True)
class ContentRow:
    """Приход из «Содержания» дела: село, приписные сёла, церковь, уезд."""

    village: str
    attached: tuple[str, ...]
    dedication: Optional[str]
    uezd_uk: Optional[str]


def case_contents(text: str) -> list[ContentRow]:
    """Таблица «Зміст» страницы дела → приходы в нём."""
    if not re.search(r"==\s*Зміст\s*==", text):
        return []
    section = re.split(r"==\s*Зміст\s*==", text, maxsplit=1)[1]
    out = []
    for table in tables(section)[:1]:
        names = [strip_markup(h).lower() for h in table.header]
        idx = {n: i for i, n in enumerate(names)}
        vi = idx.get("назва", idx.get("село"))
        if vi is None:
            continue
        ai, ci, ui = idx.get("приписні села"), idx.get("церква"), idx.get("повіт")

        def get(cells, i):
            return strip_markup(cells[i]) if i is not None and i < len(cells) else ""

        for cells in table.rows:
            village = get(cells, vi)
            if not village or len(village) > 80:
                continue
            attached = tuple(a.strip() for a in re.split(r"[,;]", get(cells, ai)) if a.strip())
            out.append(ContentRow(village=village, attached=attached,
                                  dedication=get(cells, ci) or None,
                                  uezd_uk=_uezd_cell(get(cells, ui))))
    return out


def content_subject(row: ContentRow, parent: Item) -> Subject:
    """Приход из «Содержания» → `Subject` той же формы, что из названия дела."""
    name = row.village.replace("⁠", "")
    marker = "с."
    m = re.match(r"^(.*?),\s*(м-ко|м\.|мст\.|с\.|сл\.|х\.)\s*$", name)
    if m:
        name, marker = m.group(1).strip(), SETTLEMENT_MARKS.get(m.group(2), m.group(2))
    label, confession = church_kind(parent.title)
    if label == GROUP_LABEL:
        label = "церковь"
    return Subject(kind="church", text=f"{marker} {name}" + (f", {row.dedication}"
                                                            if row.dedication else ""),
                   church=label, confession=confession or parent.subject.confession,
                   marker=marker, settlement=name, dedication=row.dedication,
                   uezd_uk=row.uezd_uk or parent.uezd_uk, gub_uk=parent.gub_uk)


def expand_contents(items: list[Item], contents: dict[str, list[ContentRow]]) -> list[Item]:
    """Каждый приход из «Содержания» дела получает это дело своей строкой."""
    out = []
    seen: set[str] = set()
    for item in items:
        if item.case in seen:
            continue
        seen.add(item.case)
        for row in contents.get(item.case, ()):
            subject = content_subject(row, item)
            out.append(Item(
                case=item.case, title=item.title, years=item.years, years_raw=item.years_raw,
                sheets=None, unit=item.unit, rtypes=item.rtypes, subject=subject,
                uezd_uk=subject.uezd_uk, gub_uk=item.gub_uk, villages=row.attached,
                via_contents=True,
            ))
    return out


# --- запись на приход ---------------------------------------------------------

@dataclass
class Entry:
    """Все дела одного прихода в одной описи."""

    inventory: Inventory
    subject: Subject
    items: list[Item]

    @property
    def years(self) -> set[int]:
        return expand(y for item in self.items for y in item.years)


def aggregate(inv: Inventory, items: list[Item]) -> list[Entry]:
    """Дела → записи по приходу.

    Строка без посвящения («церкви с. Бобли») присоединяется к записи того же
    села с посвящением, если такая в описи одна; иначе остаётся своей записью.
    """
    groups: dict[str, Entry] = {}
    for item in items:
        key = item.subject.key
        if key not in groups:
            groups[key] = Entry(inv, item.subject, [])
        groups[key].items.append(item)
    by_place: dict[tuple, list[str]] = collections.defaultdict(list)
    for key, entry in groups.items():
        s = entry.subject
        if s.kind == "church" and s.settlement:
            by_place[(s.church, name_key(s.settlement))].append(key)
    for keys in by_place.values():
        bare = [k for k in keys if not groups[k].subject.dedication]
        named = [k for k in keys if groups[k].subject.dedication]
        if len(named) == 1:
            for k in bare:
                groups[named[0]].items.extend(groups.pop(k).items)
    return list(groups.values())


# --- губерния и уезд ----------------------------------------------------------

_UK_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "є": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h",
    "ц": "c", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "i", "ь": "", "э": "e",
    "ю": "u", "я": "a",
}
_RE_ADJ_SK = re.compile(r"(?:ськ|ск|зьк|зк|ьск)(?:ий|ій|ого|ому|ая|ое|а)?$")
_RE_ADJ_CK = re.compile(r"(?:цьк|цк)(?:ий|ій|ого|ому|ая|ое|а)?$")


def _skeleton(stem: str) -> str:
    s = "".join(_UK_LAT.get(ch, ch if ch.isascii() else "") for ch in stem)
    s = re.sub(r"[^a-z]", "", s)
    s = re.sub(r"[aeiouy]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def uezd_keys(name: Optional[str]) -> set[str]:
    """Ключи уезда из согласных основы — общие для украинского и русского написания.

    «Ковельський» и «Ковельский» → «kvl»; «Заславський» и «Изяславский» →
    «zslv»; «Охтирський» и «Ахтырский» → «htr»; «Одеський» (Одеса + ський)
    даёт ещё и «ds», как «Одесский». Гласные у двух языков расходятся
    (і/е/и/ы, ів/ов), согласные — почти нет.
    """
    s = (name or "").lower().replace("'", "").replace("’", "").replace("ʼ", "")
    s = re.sub(r"\s*(повіт|уезд|округ)$", "", s.strip())
    if _RE_ADJ_CK.search(s):
        stems = {_RE_ADJ_CK.sub("ц", s)}
    else:
        stem = _RE_ADJ_SK.sub("", s)
        stems = {stem, stem + "с"} if stem != s else {s}
    return {k for k in (_skeleton(x) for x in stems) if k}


def uezd_key(name: Optional[str]) -> str:
    """Основной ключ уезда (без варианта со «с»)."""
    keys = sorted(uezd_keys(name), key=len)
    return keys[0] if keys else ""


# Повиты межвоенной Польши, которых в 1897 году не было: губерния — по
# воеводству (их земли входили в эти губернии), уезд не подбирается.
INTERWAR_POWIATS = {
    "Любомльський": "Волынская", "Горохівський": "Волынская", "Рожищенський": "Волынская",
    "Костопільський": "Волынская", "Сарненський": "Волынская", "Здолбунівський": "Волынская",
    "Камінь-Каширський": "Волынская", "Камінь-Коширський": "Волынская",
    "Шумський": "Волынская", "Любешівський": "Волынская",
}


@dataclass(frozen=True)
class Place:
    province: Optional[str]     # «Волынская губерния» — как в справочнике 1897 года
    district: Optional[str]     # «Ковельский уезд»
    distr_id: Optional[str]
    how: Optional[str]          # exact | prefix | fuzzy | manual | town | interwar
    land: Optional[str] = None  # земля вне губерний 1897 года


class UezdResolver:
    """Украинское название уезда → уезд справочника RISTAT 1897 года."""

    def __init__(self, features: Iterable[dict]) -> None:
        self.by_province: dict[str, list[tuple[set, str, str]]] = collections.defaultdict(list)
        self.province_names: dict[str, str] = {}
        for feature in features:
            props = feature.get("properties") or {}
            province, name = props.get("prov_RU"), props.get("Name_RU")
            distr_id = props.get("Distr_ID")
            if not province or not name or distr_id is None:
                continue
            name = " ".join(str(name).split())
            short = province.split()[0]
            self.province_names[short] = province
            self.by_province[short].append((uezd_keys(name), name, str(distr_id)))

    @classmethod
    def load(cls, path: Path) -> "UezdResolver":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload.get("features") or [])

    def province(self, gub_uk: Optional[str]) -> Optional[str]:
        """«Київська» → «Киевская губерния» (как в справочнике)."""
        if not gub_uk:
            return None
        stem = gub_uk.lower().replace("’", "'")
        stem = re.sub(r"(а|ої|ій|е)$", "", stem)
        name = PROVINCES_UK.get(stem)
        if not name:
            return None
        return self.province_names.get(name.split()[0], name)

    def resolve(self, uezd_uk: Optional[str], gub_uk: Optional[str] = None,
                archive: Optional[str] = None, town: Optional[str] = None) -> Place:
        """Губерния и уезд 1897 года.

        Порядок: ручной словарь; губерния из описи; губернии архива; все
        губернии юго-запада. Уезд, не найденный в названной губернии, ищется и
        в соседних: Радомысльский уезд в 1795 году числился за Волынью, а в
        1897-м — за Киевской губернией, и губерния записи — та, что в 1897-м.
        Уезда нет вовсе, а приход — в городе (`town`), — уезд по городу.
        """
        province = self.province(gub_uk)
        land = OUTSIDE_LANDS.get(archive or "")
        if not uezd_uk and town:
            place = self._match(town, ARCHIVE_PROVINCES.get(archive or "", ()) or SOUTHWEST,
                                exact_only=True)
            if place is not None:
                return Place(place.province, place.district, place.distr_id, "town")
        if not uezd_uk:
            return Place(province, None, None, None, None if province else land)
        clean = uezd_uk.replace("’", "'").strip()
        manual = UEZD_MANUAL.get(clean)
        if manual:
            name, short = manual
            for _, ristat, distr_id in self.by_province.get(short, ()):
                if ristat == name:
                    return Place(self.province_names.get(short), _uezd_ru(ristat), distr_id,
                                 "manual")
        interwar = INTERWAR_POWIATS.get(clean)
        if interwar:
            return Place(self.province_names.get(interwar), None, None, "interwar")
        # Сначала губерния описи (или губернии архива) — со всеми видами
        # совпадения; затем весь юго-запад, но только точным ключом: нечёткое
        # совпадение в чужой губернии сводит галицкий повит Бібрка с Бобруйским
        # уездом. Галицкие, буковинские и закарпатские архивы дальше своих
        # губерний не ищут вовсе.
        own = (province.split()[0],) if province else ARCHIVE_PROVINCES.get(archive or "", ())
        if own:
            place = self._match(clean, own, exact_only=bool(land))
            if place is not None:
                return place
        if not land:
            place = self._match(clean, SOUTHWEST, exact_only=True)
            if place is not None:
                return place
        return Place(province, None, None, None, None if province else land)

    def match_in(self, name: Optional[str], province: Optional[str], *,
                 exact_only: bool = False) -> Place:
        """Уезд по названию внутри губернии, названной по-русски («Минская
        губерния»): так сводит уезды и указатель Архивов Беларуси."""
        if not name or not province:
            return Place(self.province_names.get((province or " ").split()[0]), None, None, None)
        short = province.split()[0]
        place = self._match(name, (short,), exact_only=exact_only)
        return place or Place(self.province_names.get(short), None, None, None)

    def _match(self, uezd_uk: str, provinces: Iterable[str], *,
               exact_only: bool = False) -> Optional[Place]:
        keys = uezd_keys(uezd_uk)
        if not keys:
            return None
        provinces = tuple(provinces)
        for how in ("exact",) if exact_only else ("exact", "prefix", "fuzzy"):
            for short in provinces:
                units = self.by_province.get(short, ())
                if how == "exact":
                    found = [(n, d) for ks, n, d in units if ks & keys]
                elif how == "prefix":
                    found = [(n, d) for ks, n, d in units
                             if any(min(len(k), len(q)) >= 3
                                    and (k.startswith(q) or q.startswith(k))
                                    for k in ks for q in keys)]
                else:
                    scored = sorted(((max(difflib.SequenceMatcher(None, q, k).ratio()
                                          for k in ks for q in keys), n, d) for ks, n, d in units),
                                    reverse=True)
                    found = []
                    if scored and scored[0][0] >= 0.8 and (
                            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1):
                        found = [scored[0][1:]]
                if len(found) == 1:
                    # Первая губерния цепочки, где уезд нашёлся однозначно,
                    # решает: порядок цепочки — предпочтение архива.
                    name, distr_id = found[0]
                    return Place(self.province_names.get(short), _uezd_ru(name), distr_id, how)
        return None


def _uezd_ru(name: str) -> str:
    """«Ковельский» → «Ковельский уезд»."""
    if name.endswith(("уезд", "округ", "ое", "ая")):
        return name
    return f"{name} уезд"


# --- точка села ------------------------------------------------------------

class VillageIndex:
    """Сёла указателя написаний GeoNames, разложенные по уездам 1897 года.

    Точка села берётся, только если название ровно один раз встречается
    среди мест внутри полигона уезда: тёзка в том же уезде — отказ.
    `districts` — `ghcn.Provinces` на `districts_1897.geojson` с полем
    `Distr_ID`: уезд узнаётся по точке, а не по названию.
    """

    def __init__(self, items: dict, districts) -> None:
        self.by_district: dict[str, dict[str, set]] = collections.defaultdict(
            lambda: collections.defaultdict(set))
        self.points: dict[str, tuple[float, float, str]] = {}
        for gid, item in items.items():
            lat, lon = item.get("lat"), item.get("lon")
            if lat is None or lon is None:
                continue
            distr = districts.region_for(lat, lon)
            if not distr:
                continue
            self.points[gid] = (lat, lon, item.get("title") or "")
            for name in {item.get("title") or "", *(item.get("names") or [])}:
                key = name_key(name)
                if key:
                    self.by_district[str(distr)][key].add(gid)

    def locate(self, settlement: Optional[str], district_id: Optional[str]):
        if not settlement or not district_id:
            return None
        hits = self.by_district.get(str(district_id), {}).get(name_key(settlement))
        if not hits or len(hits) != 1:
            return None
        gid = next(iter(hits))
        lat, lon, title = self.points[gid]
        return gid, lat, lon, title


# --- запись схемы ------------------------------------------------------------

def page_url(title: str) -> str:
    return WIKI_URL + urllib.parse.quote(title.replace(" ", "_"), safe=";@$!*(),/~:")


def entry_place_label(subject: Subject, uezd_uk: Optional[str] = None) -> str:
    """«с. Бобли, церковь» / «м. Іллінці, синагога» / «сводные книги: …»."""
    if subject.kind == "group":
        uezd = _uezd_text(uezd_uk or subject.uezd_uk)
        if uezd and (uezd_uk or subject.uezd_uk or "") not in subject.text:
            return f"сводные книги: {subject.text} ({uezd})"
        return f"сводные книги: {subject.text}"
    if subject.kind == "unknown":
        return "приход в описи не назван"
    if subject.settlement:
        head = f"{subject.marker} {subject.settlement}" if subject.marker else subject.settlement
        church = subject.church
        if subject.dedication:
            church += f" ({subject.dedication})"
        return f"{head}, {church}"
    return subject.text


def format_cases(items: list[Item]) -> str:
    """Дела записи строкой: «177 (1876–1895, 791 арк.); 178 (1876–1898)»."""
    out = []
    seen = set()
    for it in sorted(items, key=lambda it: (_case_sort(it.case), it.case)):
        years = it.years_raw or compact_years(expand(it.years))
        sig = (it.case, years)
        if sig in seen:
            continue
        seen.add(sig)
        inner = ", ".join(p for p in (years, f"{it.sheets} {it.unit}" if it.sheets else None) if p)
        out.append(f"{it.case} ({inner})" if inner else it.case)
    return "; ".join(out)


def entry_to_record(entry: Entry, resolver: Optional[UezdResolver] = None, *,
                    fond_names: Optional[dict] = None, villages: Optional[VillageIndex] = None,
                    dump_date: str = "", spec: LayerSpec = METRIC_BOOKS_UA) -> ContextRecord:
    """Запись слоя: приход в описи, годы диапазонами, дела строкой."""
    inv, subject = entry.inventory, entry.subject
    items = entry.items
    years = entry.years
    years_text = compact_years(years)
    uezd_uk = _most_common(it.uezd_uk for it in items) or subject.uezd_uk \
        or _uezd_from_inventory(inv)
    gub_uk = _most_common(it.gub_uk for it in items) or subject.gub_uk \
        or _gub_from_inventory(inv)
    town = subject.settlement if subject.kind == "church" and subject.marker == "м." else None
    place = resolver.resolve(uezd_uk, gub_uk, inv.archive, town=town) if resolver \
        else Place(None, None, None, None)
    rtypes = sorted({t for it in items for t in it.rtypes},
                    key=lambda t: [x[0] for x in RECORD_TYPES].index(t))
    attached = sorted({v for it in items for v in it.villages})
    label = entry_place_label(subject, uezd_uk)
    code = f"{inv.archive}, ф. {inv.fond}, оп. {inv.opis}"
    fond = (fond_names or {}).get(f"{inv.archive}/{inv.fond}")
    district_text = _uezd_text(uezd_uk)
    place_text = ", ".join(p for p in (
        subject.text if subject.kind != "unknown" else None, district_text,
        f"{gub_uk} губернія" if gub_uk else None,
        f"{subject.voiv_uk} воєводство" if subject.voiv_uk else None, place.land) if p) or None
    n_cases = len({it.case for it in items})
    # В записи — шифр и дела; название описи, губерния и земля по-украински
    # есть в `place_text` и на странице описи и второй раз не пишутся: запись
    # повторяется двадцать тысяч раз, и каждый лишний ключ — мегабайт выгрузки.
    extra = {
        "archive": inv.archive,
        "fond": inv.fond, "fond_name": _short(fond, 90),
        "opis": inv.opis,
        "cases": format_cases(items),
        "n_cases": n_cases,
        "record_types": rtypes or None,
        "confession": subject.confession,
        "settlement": subject.settlement,
        "dedication": subject.dedication,
        "attached_villages": attached or None,
        "letters": sorted({it.subject.letters for it in items if it.subject.letters}) or None,
        "uezd_uk": uezd_uk,
        "district_match": place.how,
        "from_contents": sum(1 for it in items if it.via_contents) or None,
        "dump": dump_date or None,
    }
    if not years and inv.years:
        extra["years_inventory"] = inv.years
    extra = {k: v for k, v in extra.items() if v not in (None, [], "")}

    confidence = "ok"
    if place.land and not place.province:
        confidence = "outside_1897"
    elif place.how == "interwar":
        confidence = "district_interwar"
    elif uezd_uk and not place.district:
        confidence = "district_unmatched"
    elif not place.province:
        confidence = "region_unmatched"
    if not years:
        confidence = "no_date"

    lat = lon = None
    scope = SCOPE_REGION
    if villages is not None and subject.kind == "church" and place.distr_id:
        hit = villages.locate(subject.settlement, place.distr_id)
        if hit:
            gid, lat, lon, gtitle = hit
            scope = SCOPE_POINT
            extra["geo"] = {"method": "name_variants+uezd_1897", "geonameid": gid,
                            "title": gtitle}
            if confidence == "ok":
                confidence = "place_level"

    summary = build_summary(years_text, inv, n_cases, rtypes, place, uezd_uk,
                            bool(extra.get("from_contents")))
    return spec.new_record(
        title=f"Метрические книги: {label} — {code}",
        category=subject.church,
        scope=scope, lat=lat, lon=lon,
        place_text=place_text,
        region=place.province,
        regions=[place.province] if place.province and scope == SCOPE_REGION else [],
        district=place.district or district_text,
        year_from=min(years) if years else None,
        year_to=max(years) if years else None,
        date_precision="year" if years else "unknown",
        period_raw=years_text or None,
        summary=summary,
        url=page_url(inv.title),
        source_id=f"{inv.code}/{subject.key}",
        confidence=confidence,
        extra=extra,
    )


def _uezd_text(uezd_uk: Optional[str]) -> Optional[str]:
    if not uezd_uk:
        return None
    if uezd_uk.endswith("повіт"):
        return uezd_uk
    return f"{uezd_uk} повіт" if _is_adjective(uezd_uk) else f"повіт {uezd_uk}"


def _short(text: Optional[str], limit: int = 160) -> Optional[str]:
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_summary(years_text: str, inv: Inventory, n_cases: int,
                  rtypes: list[str], place: Place, uezd_uk: Optional[str],
                  from_contents: bool) -> str:
    """Своя фраза из полей: за какие годы, где лежит, какой уезд."""
    parts = [f"{years_text or 'годы не указаны'}: {inv.archive}, ф. {inv.fond}, оп. {inv.opis}, "
             f"{n_cases} {_plural(n_cases, 'дело', 'дела', 'дел')}"
             + (" — сводные тома, приход найден по их «Содержанию»" if from_contents else "")]
    if rtypes:
        parts.append("записи: " + ", ".join(rtypes))
    if place.district and place.province:
        parts.append(f"{place.district}, {place.province}")
    elif place.province:
        parts.append(place.province)
    elif uezd_uk:
        parts.append(f"уезд по описи — {uezd_uk}")
    return "Метрические книги " + "; ".join(parts) + "."


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _case_sort(case: str) -> int:
    m = re.match(r"\d+", case or "")
    return int(m.group(0)) if m else 10 ** 9


def _most_common(values: Iterable[Optional[str]]) -> Optional[str]:
    counter = collections.Counter(v for v in values if v)
    return counter.most_common(1)[0][0] if counter else None


def _uezd_from_inventory(inv: Inventory) -> Optional[str]:
    """Уезд из названия описи или из её категорий («Ковельський повіт»)."""
    if inv.name:
        c = _clean_title(inv.name)
        if c.uezd:
            return c.uezd
    uezds = [c[: -len(" повіт")] for c in inv.categories if c.endswith(" повіт")]
    return uezds[0] if len(uezds) == 1 else None


def _gub_from_inventory(inv: Inventory) -> Optional[str]:
    if inv.name:
        m = _RE_GUB.search(inv.name)
        if m:
            return uk_nominative(m.group(1))
    gubs = [c[: -len(" губернія")] for c in inv.categories if c.endswith(" губернія")]
    return gubs[0] if len(gubs) == 1 else None


# --- весь разбор ------------------------------------------------------------

@dataclass
class Harvest:
    """Что разбор достал из страниц пространства 116."""

    inventories: dict[str, Inventory] = field(default_factory=dict)
    contents: dict[str, dict[str, list[ContentRow]]] = field(default_factory=dict)
    fond_names: dict[str, str] = field(default_factory=dict)
    pages: int = 0


def collect(pages: Iterable[Page], harvest: Optional[Harvest] = None) -> Harvest:
    """Страницы → описи с метрическими книгами, «Содержание» дел, названия фондов."""
    harvest = harvest or Harvest()
    for page in pages:
        if page.ns != NS_ARCHIVE:
            continue
        harvest.pages += 1
        parts = split_title(page.title)
        if not parts:
            continue
        if len(parts) == 2 and "{{Архіви/фонд" in page.text:
            name = fond_name(page)
            if name:
                harvest.fond_names[f"{parts[0]}/{parts[1]}"] = name
        elif len(parts) == 3 and _RE_METRIC_ANY.search(page.text):
            inv = parse_inventory(page)
            if inv is not None:
                harvest.inventories[inv.code] = inv
        elif len(parts) == 4 and "Зміст" in page.text and _RE_METRIC_ANY.search(page.text):
            rows = case_contents(page.text)
            if rows:
                harvest.contents.setdefault("/".join(parts[:3]), {})[parts[3]] = rows
    return harvest


def build_entries(harvest: Harvest) -> list[Entry]:
    entries: list[Entry] = []
    for code, inv in sorted(harvest.inventories.items()):
        items = inventory_items(inv, harvest.fond_names.get(f"{inv.archive}/{inv.fond}"))
        if not items:
            continue
        items += expand_contents(items, harvest.contents.get(code, {}))
        entries.extend(aggregate(inv, items))
    return entries
