"""Сбор слоя переименований населённых мест из Викиданных.

Зачем слой. Село в метрической книге названо не так, как на нынешней карте:
Царицын, Сталинград и Волгоград — одно место, а поиск по современному
названию не находит ни первого, ни второго. Указатель написаний из GeoNames
(`data/out/name_variants.json`) отвечает на половину вопроса — он знает, что
у места есть другое написание, но не знает, **в каком году** оно сменилось.
Год здесь и есть главное: он говорит, какое название стояло в документе того
года, который ищет исследователь.

Почему отдельный сборщик, а не запрос в `queries/*.rq`. Годы переименований
лежат не в самих значениях, а в квалификаторах времени к ним: у заявления
«официальное название» (`P1448`) стоят `P580` и `P582` — с какого по какой
год название держалось. Через `wdt:` квалификаторы не достаются вовсе, нужен
полный путь `p:` → `ps:` → `pq:`, а вторая ступень движка
(`sources/wikidata.py`, `details_query`) умеет только `wdt:`. Переделать её
мало: там строка ответа становится записью один к одному и записи
схлопываются по Q-номеру (`dedupe`), а здесь всё наоборот — из нескольких
заявлений одного места собирается цепочка названий, и **каждое звено цепочки
становится отдельной записью**: Царицын → Сталинград (1925) и
Сталинград → Волгоград (1961) — это два разных факта для двух разных лет.

Что берётся. Ступени две, как и у остальных слоёв Викиданных:

  1. Q-номера мест с координатой, у которых есть официальное название с
     датой конца (`pq:P582`), — по одному запросу на каждое из 17
     государств-преемников;
  2. все заявления о названиях этих мест целиком — чанками, через
     `VALUES ?item`, вместе с квалификаторами.

Проверка класса («это населённое место, а не улица и не река») стоит на
второй ступени, и это не небрежность. Транзитивное замыкание
`wdt:P31/wdt:P279*` в первой ступени — ровно то, из-за чего прежние запросы
не выполнялись: против живого сервиса отбор по классу поверх всей России
упирается в лимит времени и отдаёт 504. На второй ступени тот же вопрос
задаётся о пятистах уже известных местах и стоит копейки.

Дальше заявления выстраиваются в цепочку по годам, и на каждое звено, у
которого есть преемник, пишется запись: старое название, новое, год смены.
Границы записи — годы, когда старое название держалось: факт 1899 года
подбирается к записи «Царицын, 1589–1925», а не к году самого переименования.

Чего в слое не будет. Место, переименование которого записано только датами
начала (`P580`) у обоих названий или вовсе без `P1448`, в первую ступень не
попадёт: отбор по «официальному названию с датой конца» — единственный
дешёвый способ не тащить все населённые места подряд. Такие места остаются в
Викиданных и ждут второго захода; это ограничение способа отбора, а не
решение выбросить данные.

Что попадает лишнего. В Викиданных сельские поселения и сельсоветы стоят
под тем же классом «населённый пункт», поэтому вместе с сёлами приезжают и
они — по пробе около шестой части записей, и почти все это переименования
1990-х годов вроде «Аджимский сельсовет → Аджимский сельский округ». Молча
отсеивать их нечем: отдельного класса для муниципального образования в
отборе нет, а угадывать по названию — заведомо ошибаться. Вид места
записан в `category`, там такая запись и видна.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

from ..geo import extract_district, extract_region, in_bbox, valid_coords
from ..schema import ContextRecord, LayerSpec, clean_text
# Разбор Point(), Q-номеров и дат Викиданных уже написан для основного сбора.
# Второй такой же разбор — второе место, где его чинить.
from .wikidata import (
    COUNTRIES, LABEL_LANGS, SparqlClient, SparqlError, _point, _qid, _val, _year,
)

# Класс отбора. Транзитивное замыкание `wdt:P31/wdt:P279*` покрывает город,
# село, деревню, посёлок городского типа и прочие виды населённых мест.
SETTLEMENT_CLASS = "Q486972"

# Свойство, по которому идёт отбор на первой ступени. Проба против живого
# сервиса показала, что переименования записаны в нём почти целиком, а
# перебор четырёх свойств через `wikibase:claim` первую ступень не переживает:
# оптимизатор не может оценить `?item ?p ?st` с несвязанным свойством.
LOOKUP_PROPERTY = "P1448"

# Названия, которые собираются на второй ступени.
NAME_PROPERTIES: tuple[str, ...] = ("P1448", "P2561", "P1705", "P1813")
NAME_PROPERTY_TITLES = {
    "P1448": "официальное название",
    "P2561": "название",
    "P1705": "родное название",
    "P1813": "краткое название",
}

# Из чего строится цепочка переименований, а из чего — только варианты
# написания. Разделение вынужденное и проверено на живом ответе: у мест
# Северного Кавказа и Поволжья рядом с русским названием стоит родное
# (`P1705`) — кабардинское, осетинское, башкирское, — и оно описывает то же
# самое место в то же самое время. Пока `P1705` был звеном цепочки, «Теучежск»
# и адыгейское «Адыгэкъал» выглядели как переименование, которого не было.
CHAIN_PROPERTIES: tuple[str, ...] = ("P1448", "P2561")

# Чанк меньше, чем у основного сбора (там 1000): каждое место приносит не одну
# строку, а по строке на каждое заявление о названии и на каждый его язык.
NAMES_CHUNK_SIZE = 500

# Проба берёт один чанк: этого хватает, чтобы увидеть, что разбор работает,
# а сервис ограничивает частоту обращений — лишний запрос стоит дорого.
PROBE_OBJECTS = NAMES_CHUNK_SIZE

# Докуда тянуть начало прежнего названия, если оно неизвестно и цепочка
# ничего не подсказывает. То же число, что и в основном сборе (OPEN_END_YEAR
# с другой стороны шкалы): интерес проекта начинается около 1800 года, и
# расширять интервал безопаснее, чем сужать (`docs/SCHEMA.md`).
OPEN_START_YEAR = 1800

# Язык названия для показа: русский, затем без языка, затем английский.
# Метрическая книга написана по-русски, и искать будут по русскому написанию.
LANG_ORDER = ("ru", "", "en")

# Номер свойства из его URI. В `wikidata._qid` такого разбора нет: там ждут
# только Q-номера, а здесь в ответе приходит ещё и P-номер свойства.
_RE_PID = re.compile(r"/entity/(P\d+)$")


def _pid(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    m = _RE_PID.search(uri)
    return m.group(1) if m else None


def ids_query(country: str, *, lookup_property: str = LOOKUP_PROPERTY) -> str:
    """Ступень 1: места одного государства, у которых название сменилось.

    Дешёвая на вид `DISTINCT` здесь обязательна: место, сменившее название
    дважды, даёт две строки.

    Ни классов, ни меток, ни `OPTIONAL` — только то, что отбирает. Всё
    остальное спрашивается второй ступенью по готовому списку.
    """
    return (
        "SELECT DISTINCT ?item WHERE {\n"
        f"  ?item wdt:P17 wd:{country} ;\n"
        "        wdt:P625 ?coord ;\n"
        f"        p:{lookup_property} ?st .\n"
        "  ?st pq:P582 ?end .\n"
        "}"
    )


def names_query(qids: list[str], *,
                properties: Iterable[str] = NAME_PROPERTIES,
                settlement_class: str = SETTLEMENT_CLASS) -> str:
    """Ступень 2: все заявления о названиях у готового списка мест.

    Заявления берутся целиком, а не только те, у которых есть дата конца:
    новое название — это соседнее звено цепочки, и без него переименование
    не описать. `wikibase:claim`/`wikibase:statementProperty` избавляют от
    четырёх почти одинаковых UNION-веток на четыре свойства.

    Класс проверяется через `FILTER EXISTS`, а не третьим условием в теле:
    условием в теле `wdt:P31/wdt:P279*` дало бы по строке на каждый путь до
    класса — одно место приходило бы пятью одинаковыми строками.
    """
    items = " ".join(f"wd:{q}" for q in qids)
    props = " ".join(f"wd:{p}" for p in properties)
    return (
        "SELECT ?item ?itemLabel ?coord ?adminLabel ?typeLabel ?article "
        "?st ?prop ?name ?start ?end WHERE {\n"
        f"  VALUES ?item {{ {items} }}\n"
        f"  VALUES ?prop {{ {props} }}\n"
        "  ?prop wikibase:claim ?p ; wikibase:statementProperty ?ps .\n"
        "  ?item wdt:P625 ?coord ;\n"
        "        ?p ?st .\n"
        "  ?st ?ps ?name .\n"
        f"  FILTER EXISTS {{ ?item wdt:P31/wdt:P279* wd:{settlement_class} . }}\n"
        "  OPTIONAL { ?st pq:P580 ?start . }\n"
        "  OPTIONAL { ?st pq:P582 ?end . }\n"
        "  OPTIONAL { ?item wdt:P131 ?admin . }\n"
        "  OPTIONAL { ?item wdt:P31 ?type . }\n"
        "  OPTIONAL { ?article schema:about ?item ; "
        "schema:isPartOf <https://ru.wikipedia.org/> . }\n"
        '  SERVICE wikibase:label { bd:serviceParam wikibase:language "' + LABEL_LANGS + '". }\n'
        "}"
    )


class _Place:
    """Место и всё, что о его названиях пришло из ответа."""

    __slots__ = ("qid", "label", "points", "admins", "kinds", "article", "statements")

    def __init__(self, qid: str) -> None:
        self.qid = qid
        self.label: Optional[str] = None
        # P625 тоже бывает многозначным. Координата входит в `uid`, поэтому
        # брать первую попавшуюся строку нельзя: порядок строк в ответе не
        # обещан, и `uid` поехал бы от сборки к сборке.
        self.points: set[tuple[float, float]] = set()
        # P131 и P31 многозначны: у места бывает и нынешнее подчинение, и
        # историческое. Собираем все значения и выбираем ниже.
        self.admins: set[str] = set()
        self.kinds: set[str] = set()
        self.article: Optional[str] = None
        # ключ — URI заявления: одно заявление приходит столько раз, сколько
        # у места значений P131 и P31.
        self.statements: dict[str, dict] = {}

    @property
    def point(self) -> tuple[Optional[float], Optional[float]]:
        """Координата места — наименьшая из пришедших, чтобы выбор не плавал."""
        return min(self.points) if self.points else (None, None)

    @property
    def admin(self) -> Optional[str]:
        """Территория, к которой отнесено место.

        Из нескольких значений P131 берётся самое крупное из узнаваемых:
        подбор контекста идёт по губернии и области (`histctx.geo.region_key`),
        и «Свердловская область» для этого годится, а «Городской округ
        Верхняя Пышма» — нет, хотя формально округ тоже единица.

        Порядок строк в ответе не обещан, поэтому выбор детерминированный —
        иначе `uid` записи менялся бы от сборки к сборке.
        """
        if not self.admins:
            return None
        return min(sorted(self.admins), key=_admin_rank)

    @property
    def district(self) -> Optional[str]:
        """Уезд или район — из любого значения P131, не только из выбранного.

        У Верхней Пышмы среди значений стоят и «Свердловская область», и
        «Екатеринбургский уезд». Губерния идёт в `region`, уезд — сюда: для
        поиска в архиве уезд и есть рабочая единица, в нём лежит фонд.
        """
        for value in sorted(self.admins):
            district = extract_district(value)
            if district:
                return district
        return None

    @property
    def kind(self) -> Optional[str]:
        """Вид места. Из нескольких значений P31 берётся самое короткое:
        «город», а не «город республиканского подчинения в Адыгейской
        Республике»."""
        return min(sorted(self.kinds), key=len) if self.kinds else None


# Единицы деления в порядке пригодности для подбора контекста: по губернии и
# области он идёт, по городскому округу — нет. Числа проставлены руками, а не
# позицией в списке, потому что между узнаваемыми единицами и округом стоит
# ещё одна ступень — то, чего `extract_region` не узнаёт вовсе.
_ADMIN_RANKS = {
    "губерния": 0, "область": 1, "край": 2, "наместничество": 3, "войско": 4,
    "округ": 6,
}
# Республика, автономия, район: слова «губерния» или «область» в названии нет,
# и `extract_region` возвращает пустоту. Территорией они быть могут, поэтому
# идут впереди округов, но позади узнаваемых единиц.
_ADMIN_RANK_UNKNOWN = 5
# Единицы, для которых приведение к именительному падежу что-то даёт.
_REGION_UNITS = frozenset(("губерния", "область", "край", "наместничество", "войско"))


def _admin_rank(value: str) -> tuple:
    """Чем меньше, тем ценнее значение P131 как территория записи."""
    region = extract_region(value)
    if not region:
        return (_ADMIN_RANK_UNKNOWN, value)
    unit = region.rsplit(" ", 1)[-1].lower()
    return (_ADMIN_RANKS.get(unit, _ADMIN_RANK_UNKNOWN), value)


def _region_of(admin: Optional[str]) -> Optional[str]:
    """Губерния или область записи.

    `extract_region` приводит название к именительному падежу, и это нужно:
    по нему сходятся территории из разных источников. Но у «Городского округа
    Адыгейск» он оставляет одно слово «Городской округ» — такое приведение
    отнимает больше, чем даёт, и текст остаётся как есть.
    """
    region = extract_region(admin)
    if region and region.rsplit(" ", 1)[-1].lower() in _REGION_UNITS:
        return region
    return admin


def _language(node: Optional[dict]) -> str:
    return (node or {}).get("xml:lang") or ""


def group_rows(rows: list[dict]) -> dict[str, _Place]:
    """Складывает строки ответа по местам, а внутри места — по заявлениям."""
    places: dict[str, _Place] = {}
    for row in rows:
        qid = _qid(_val(row, "item"))
        if not qid:
            continue
        place = places.get(qid)
        if place is None:
            place = places[qid] = _Place(qid)
        lat, lon = _point(_val(row, "coord"))
        if lat is not None and valid_coords(lat, lon):
            place.points.add((lat, lon))
        label = clean_text(_val(row, "itemLabel"))
        # Метки нет — служба меток отдаёт сам Q-номер; это не название.
        if label and label != qid and not place.label:
            place.label = label
        admin = clean_text(_val(row, "adminLabel"))
        if admin:
            place.admins.add(admin)
        kind = clean_text(_val(row, "typeLabel"))
        if kind:
            place.kinds.add(kind)
        place.article = place.article or clean_text(_val(row, "article"))

        statement = _val(row, "st")
        name = clean_text(_val(row, "name"))
        if not statement or not name:
            continue
        place.statements.setdefault(statement, {
            "name": name,
            "lang": _language(row.get("name")),
            "prop": _pid(_val(row, "prop")),
            "start": _year(_val(row, "start")),
            "end": _year(_val(row, "end")),
        })
    return places


def chain_language(statements: Iterable[dict], *,
                   chain_properties: Iterable[str] = CHAIN_PROPERTIES) -> Optional[str]:
    """Язык, на котором строится цепочка названий.

    Русский — если на нём вообще есть что выстраивать: метрическая книга
    написана по-русски, и искать будут по русскому написанию. Но одного
    русского названия без дат мало: на эстонских, грузинских и латышских
    карточках такое стоит почти всегда, а даты — при местном названии. Если
    предпочесть русский по одному его наличию, место молча выпадет из слоя.

    Поэтому языки сначала делятся на те, из которых цепочка выходит, и
    остальные, и лишь среди годных действует предпочтение: русский, без
    языка, английский, затем — где сказано больше, при равенстве первый по
    алфавиту (порядок строк в ответе не обещан, а разбор должен быть
    повторяемым).
    """
    chain_properties = tuple(chain_properties)
    counts: dict[str, int] = {}
    dated: dict[str, int] = {}
    ended: dict[str, int] = {}
    for st in statements:
        if st.get("prop") not in chain_properties:
            continue
        lang = st.get("lang") or ""
        counts[lang] = counts.get(lang, 0) + 1
        if st.get("end") is not None:
            ended[lang] = ended.get(lang, 0) + 1
        if st.get("end") is not None or st.get("start") is not None:
            dated[lang] = dated.get(lang, 0) + 1
    if not counts:
        return None

    def rank(lang: str) -> tuple:
        # Цепочка выходит, если известен год конца хотя бы одного названия
        # (тогда преемник найдётся хоть в нынешней метке) или если датированы
        # хотя бы два названия — год смены даст начало следующего.
        usable = ended.get(lang, 0) >= 1 or dated.get(lang, 0) >= 2
        order = LANG_ORDER.index(lang) if lang in LANG_ORDER else len(LANG_ORDER)
        return (not usable, order, -counts[lang], lang)

    return min(sorted(counts), key=rank)


def name_chain(statements: Iterable[dict], *,
               chain_properties: Iterable[str] = CHAIN_PROPERTIES) -> list[dict]:
    """Выстраивает названия места в цепочку по годам.

    Цепочка строится **на одном языке**, и это главное решение здесь.
    Переименование — это смена русского названия на русское: «Энсо» стало
    «Светогорском». Финское «Enso», адыгейское «Адыгэкъал» и немецкое
    «Groß Dirschkeim» стоят в тех же карточках теми же заявлениями, и пока
    они были звеньями цепочки, из них выходили переименования, которых не
    было: «Теучежск → Адыгэкъал». Иноязычные написания — это варианты, они
    прирастают к звену того же периода и уходят в `extra`; искать по ним
    тоже будут, но годом смены названия они не являются.

    Внутри языка звено — это период, а не заявление: два заявления об одном
    и том же сроке сводятся в одно звено.
    """
    statements = list(statements)
    chain_properties = tuple(chain_properties)
    primary = chain_language(statements, chain_properties=chain_properties)
    links: dict[object, dict] = {}
    variants: list[dict] = []
    for st in statements:
        lang = st.get("lang") or ""
        if st.get("prop") not in chain_properties or lang != primary:
            variants.append(st)
            continue
        end, start = st.get("end"), st.get("start")
        # Ключ — весь период, а не один год конца. У Ялты «Ялта» кончилась
        # 20 января 1921 года, а «Красноармейск» — 25 августа того же года:
        # по году конца эти два названия слиплись бы в одно звено, и
        # переименование пропало бы.
        key = (end, start)
        link = links.get(key)
        if link is None:
            links[key] = {
                "start": start, "end": end, "name": st["name"], "lang": lang,
                "prop": st.get("prop"), "variants": [],
            }
        else:
            _merge_into_link(link, st)

    chain = sorted(links.values(), key=_order)
    _attach_variants(chain, variants)
    return chain


def _order(link: dict) -> tuple:
    """Порядок звеньев — по времени, когда название держалось.

    Год начала неизвестен — звено встаёт перед своим годом окончания. Дат нет
    вовсе — звено уходит в самый конец: название без дат это нынешнее
    название, записанное без подробностей. Поставить его в начало значило бы
    выдумать переименование: «Волгоград → Царицын, до 1589 года».
    """
    start, end = link["start"], link["end"]
    if start is None:
        start = end - 1 if end is not None else 9999
    return (start, end if end is not None else 9999, link["name"])


def _attach_variants(chain: list[dict], variants: Iterable[dict]) -> None:
    """Раскладывает иноязычные написания по звеньям того же периода.

    Написание без дат — это нынешнее название на другом языке, оно идёт к
    последнему звену. Написание с датами — к звену, у которого тот же год
    окончания или тот же год начала. Всё остальное отбрасывается: привязать
    его не к чему, а выдумывать период нельзя.
    """
    if not chain:
        return
    for st in variants:
        end, start = st.get("end"), st.get("start")
        link = None
        if end is None and start is None:
            link = chain[-1]
        else:
            for candidate in chain:
                if (end is not None and candidate["end"] == end) or \
                        (start is not None and candidate["start"] == start):
                    link = candidate
                    break
        if link is not None and st["name"] != link["name"]:
            link["variants"].append(st["name"])


def _merge_into_link(link: dict, st: dict) -> None:
    """Добавляет заявление к звену цепочки с тем же сроком.

    Сроки у звена и заявления совпадают — по сроку звено и найдено, — так что
    выбирать приходится только между написаниями.
    """
    if st["name"] < link["name"]:
        # Язык у звена и заявления один, выбирать не по чему — берётся
        # написание, меньшее по алфавиту. Это не вкусовщина: порядок строк в
        # ответе SPARQL не обещан, а `uid` записи считается от названия, и без
        # устойчивого правила один и тот же объект менял бы `uid` от сборки
        # к сборке.
        link["variants"].append(link["name"])
        link["name"] = st["name"]
        link["prop"] = st.get("prop") or link["prop"]
    elif st["name"] != link["name"]:
        link["variants"].append(st["name"])


def _successor(chain: list[dict], index: int,
               current: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """Название, которое пришло на смену звену, и год смены.

    Год смены — это год конца прежнего названия; если он не проставлен,
    подойдёт год начала следующего. Когда известны оба и они спорят между
    собой (следующее название началось раньше, чем кончилось прежнее),
    пара считается несогласованной и записи не даёт.
    """
    link = chain[index]
    following = chain[index + 1] if index + 1 < len(chain) else None
    if following is None:
        # Преемника среди заявлений нет: значит, место так и называется.
        return (current, link["end"]) if current else (None, link["end"])
    year = link["end"] if link["end"] is not None else following["start"]
    if link["end"] is not None and following["start"] is not None \
            and following["start"] < link["end"]:
        return None, None
    return following["name"], year


def build_summary(old: str, new: str, year: int, start: Optional[int],
                  current: Optional[str]) -> str:
    if start == year:
        # Название продержалось меньше года — так бывает: Ялта успела побыть
        # Красноармейском и вернуться обратно в пределах 1921 года.
        held = f"название {year} года"
    elif start:
        held = f"название с {start} по {year} год"
    else:
        held = f"название до {year} года"
    text = f"{old}: {held}, затем {new}"
    if current and current not in (new, old):
        text += f"; ныне {current}"
    return text + "."


def _period_raw(start: Optional[int], year: int) -> str:
    if start is None:
        return f"до {year}"
    return str(year) if start == year else f"{start}–{year}"


def rows_to_records(rows: list[dict], spec: LayerSpec, *,
                    require_bbox: bool = True) -> list[ContextRecord]:
    """Превращает ответ SPARQL в записи: по записи на каждое переименование.

    Место без координаты, без года смены названия или без второго названия
    в запись не идёт: на карту его не поставить и годом не сопоставить.
    """
    out: list[ContextRecord] = []
    for place in group_rows(rows).values():
        lat, lon = place.point
        if lat is None:
            continue
        if require_bbox and not in_bbox(lat, lon):
            continue
        chain = name_chain(place.statements.values())
        found: list[ContextRecord] = []
        previous_end: Optional[int] = None
        for index, link in enumerate(chain):
            new, year = _successor(chain, index, place.label)
            # Год начала не проставлен — название держалось с прошлого
            # переименования: цепочка знает то, чего не знает заявление.
            start = link["start"] if link["start"] is not None else previous_end
            if link["end"] is not None:
                previous_end = link["end"]
            if not new or year is None:
                continue
            record = _rename_record(place, link, new, year, start, spec)
            if record is not None:
                found.append(record)
        out.extend(_mark_disputed(found))
    return out


def _mark_disputed(records: list[ContextRecord]) -> list[ContextRecord]:
    """Помечает записи, спорящие друг с другом о годе переименования.

    У закрытого города Голицыно-2 в Викиданных два ответа на один вопрос: он
    стал Краснознаменском в 1977 году и он же стал им в 1994-м. Выбрать
    правильный нечем, выбросить оба нельзя — ничего не удаляется молча. Обе
    записи остаются и получают `confidence = "dates_disputed"`.

    Спор — это пересечение сроков, а не повтор названий. Прикумск становился
    Будённовском дважды, Выборг и Виипури менялись местами четыре раза, и
    это не ошибка данных, а история места: сроки таких записей не
    пересекаются, потому что одно название не может держаться дважды разом.
    """
    for index, record in enumerate(records):
        for other in records[index + 1:]:
            if record.title != other.title:
                continue
            if record.overlaps_years(other.year_from, other.year_to):
                record.confidence = other.confidence = "dates_disputed"
    return records


def _rename_record(place: _Place, link: dict, new: str, year: int,
                   start: Optional[int], spec: LayerSpec) -> Optional[ContextRecord]:
    lat, lon = place.point
    old = link["name"]
    if old == new:
        return None
    if start is not None and start > year:
        # Начало позже конца — в данных путаница; год начала отбрасываем,
        # а не чиним догадкой, и запись помечается приблизительной.
        # Равенство при этом законно: Ялту переименовали в Красноармейск и
        # обратно в пределах 1921 года, и такой интервал — не ошибка.
        start = None
    year_from = start if start is not None else min(year, OPEN_START_YEAR)
    extra = {
        "old_name": old,
        "new_name": new,
        "renamed_year": year,
    }
    if link["prop"]:
        # Откуда взято название: «официальное название» весомее «краткого».
        extra["property"] = NAME_PROPERTY_TITLES.get(link["prop"], link["prop"])
    if place.label and place.label not in (old, new):
        extra["current_name"] = place.label
    if link["variants"]:
        # Иноязычные написания того же названия: Гросс-Диршкайм и
        # Groß Dirschkeim — по ним тоже ищут.
        extra["name_variants"] = sorted(set(link["variants"]))

    return spec.new_record(
        title=f"{old} → {new}",
        category=place.kind,
        lat=lat, lon=lon,
        place_text=place.admin,
        region=_region_of(place.admin),
        district=place.district,
        year_from=year_from,
        year_to=year,
        # Год начала неизвестен — интервал растянут до начала интересующего
        # периода, и это «часть века», а не год. Если растягивать некуда
        # (переименование раньше 1800 года), запись сжимается в сам год смены.
        date_precision="year" if start is not None or year_from == year else "part",
        date_approx=start is None,
        period_raw=_period_raw(start, year),
        summary=build_summary(old, new, year, start, place.label),
        url=place.article or f"https://www.wikidata.org/wiki/{place.qid}",
        # Q-номер, год и прежнее название. Года мало: Ялта успела в 1921 году
        # стать Красноармейском и вернуться обратно, и по ключу «место + год»
        # второе переименование затёрло бы первое.
        source_id=f"{place.qid}:{year}:{old}",
        extra=extra,
    )


def collect(client: SparqlClient, spec: LayerSpec, *,
            countries: tuple[tuple[str, str], ...] = COUNTRIES,
            chunk_size: int = NAMES_CHUNK_SIZE,
            require_bbox: bool = True,
            max_objects: Optional[int] = None,
            progress: Optional[Callable[[str], None]] = None) -> list[ContextRecord]:
    """Собирает слой в две ступени по всем государствам-преемникам.

    Ошибка на одном государстве или на одном чанке сбор не отменяет: она
    печатается, и работа идёт дальше. Потерять область хуже, чем потерять
    всё, но молча терять нельзя.
    """
    say = progress or (lambda _: None)

    qids: list[str] = []
    seen: set[str] = set()
    for country, name in countries:
        try:
            rows = client.query(ids_query(country))
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
            say(f"    {name}: мест с прежним названием {len(rows)}, новых {fresh}")

    say(f"  всего мест: {len(qids)}")
    if max_objects is not None and len(qids) > max_objects:
        qids = qids[:max_objects]
        say(f"  проба: берём первые {len(qids)}")
    if not qids:
        return []

    records: list[ContextRecord] = []
    for start in range(0, len(qids), chunk_size):
        chunk = qids[start:start + chunk_size]
        try:
            rows = client.query(names_query(chunk))
        except SparqlError as exc:
            say(f"    названия {start}–{start + len(chunk)}: ОШИБКА — {exc}")
            continue
        records.extend(rows_to_records(rows, spec, require_bbox=require_bbox))
        say(f"    названия {start + len(chunk)}/{len(qids)}: записей {len(records)}")

    return dedupe(records)


def dedupe(records: list[ContextRecord]) -> list[ContextRecord]:
    """Одно переименование — одна запись.

    Ключ — `source_id` (`<Q-номер>:<год смены>`), а не `uid`: `uid` считается
    в том числе от координаты, и место с двумя значениями P625 осталось бы на
    карте дважды.
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
