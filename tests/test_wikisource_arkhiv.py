"""Слой метрических книг из Викитеки («Архів»): дамп, описи, дела, уезды.

Образцы — фрагменты настоящих страниц дампа 20261101: опись ДАЖО ф. 1 оп. 80
(«№ | Назва | Повіт | Роки | Аркушів»), дело 1 той же описи с таблицей
«Зміст», опись ЦДІАК ф. 224 оп. 1 (колонки «Церква» и «Нас. пункти») и
названия дел из описей ДАВоО, ЦДІАЛ и ЦДІАК. Ссылки на FamilySearch и Commons
в образцах оставлены — разбор их не берёт.
"""

import bz2

import pytest

from histctx.sources.wikisource_arkhiv import (
    METRIC_BOOKS_UA, Harvest, IndexEntry, Page, UezdResolver, VillageIndex, aggregate,
    build_entries, case_contents, collect, compact_years, entry_to_record, expand_contents,
    format_cases, inventory_items, is_metric_title, iter_pages, list_rows, page_url,
    parse_dumpstatus, parse_index, parse_inventory, parse_subject, parse_years, read_chunk,
    split_subjects, stream_ranges, strip_markup, uezd_keys,
)

INVENTORY = """{{Архіви/опис
 | назва = Метричні книги Ковельського і Кременецького повітів
 | рік = 1798–1896
 | примітки = [[c:file:ДАЖО фонд 1 опис 80.pdf|ДАЖО фонд 1 опис 80]]
}}
[[Файл:Скит 001.jpg|400px|Старовинна церква (Скит) на Волині]]
== Справи ==
{| class="wikitable sortable"
!№!!Назва!!Повіт!!Роки!!Аркушів
|-
|[[/1/]]||Метричні книги православних церков Ковельського повіту. Села Б–Ш||Ковельський||1797||197
|-
|[[/2/]]||Метричні книги православних церков Ковельського повіту. Села Б–Я||Ковельський||1799||210
|-
|[[/41/]]||Метричні книги церкви с. Бобли Ковельського повіту||Ковельський||1840–1865||424
|-
|[[/177/]]||Метричні книги церкви м. Камінь-Каширський Ковельського повіту||Ковельський\
||1876–1895||791
|-
|[[/178/]]||Про видачу метричного свідоцтва про народження та хрещення Олександра\
||Ковельський||1877||3
|}

[[Категорія:Ковельський повіт]]
"""

CASE_1 = """{{Архіви/справа
 | назва = Метричні книги православних церков Ковельського повіту. Села Б–Ш
 | рік = 1797
 | link_FS = https://www.familysearch.org/records/images/search-results?imageGroupNumbers=122936435
}}
== Зміст ==
{|class="wikitable sortable"
!Аркуш!!Назва!!Приписні села!!Церква!!Повіт
|-
|||Білин||||Різдва Пресвятої Богородиці||Ковельський
|-
|||Бобли||||Покрова Пресвятої Богородиці||Ковельський
|-
|||Вербична||Вулька Вербичанська, Ось, Ревушки||Різдва Пресвятої Богородиці||Ковельський
|-
|||Вижва, м-⁠ко||Мельники, Руда, Хотивель||Преображення Господнього||Ковельський
|}
"""

CDIAK_224 = """{{Архіви/опис
 | назва = Метричні книги церков Подільського і Брацлавського воєводств (до 1793 р.)
 | рік = 1717-1893
}}
==Справи==
{|class="wikitable sortable"
! № !! Назва !! Церква !! Нас. пункти !! Повіт !! Дати !! Арк. !! Примітки \
!! Посилання на FamilySearch
|-
| [[/1/]] || Метрична книга || Святого Василя Великого || с. Адамівка || Летичівський \
|| 1738―1781 || 99 || ||
[https://www.familysearch.org/records/images/search-results?imageGroupNumbers=4810392 Item 2]
|-
| [[/2/]] || Метрична книга || Різдва Пресвятої Богородиці || с. Адамівка || Гайсинський \
|| 1776—1796 || 82 ||  ||
|}
"""

# Справочник уездов 1897 года — кусок `districts_1897.geojson`, только свойства.
DISTRICTS = [
    {"properties": {"prov_RU": "Волынская губерния", "Name_RU": n, "Distr_ID": i}}
    for n, i in (("Ковельский", 312), ("Луцкий", 314), ("Овручский", 323), ("Изяславский", 320),
                 ("Острожский", 319), ("Ровенский", 318))
] + [
    {"properties": {"prov_RU": "Киевская губерния", "Name_RU": n, "Distr_ID": i}}
    for n, i in (("Радомысльский", 340), ("Киевский", 343), ("Бердичевский", 336))
] + [
    {"properties": {"prov_RU": "Подольская губерния", "Name_RU": n, "Distr_ID": i}}
    for n, i in (("Летичевский", 326), ("Гайсинский", 335), ("Каменец-Подольский", 329),
                 ("Могилевский", 331))
] + [
    {"properties": {"prov_RU": "Минская губерния", "Name_RU": "Бобруйский", "Distr_ID": 305}},
    {"properties": {"prov_RU": "Херсонская губерния", "Name_RU": "Одесский", "Distr_ID": 363}},
]


@pytest.fixture(scope="module")
def resolver():
    return UezdResolver(DISTRICTS)


def _inventory(text=INVENTORY, title="Архів:ДАЖО/1/80"):
    return parse_inventory(Page(title, 116, 1, "2026-10-01T00:00:00Z", text))


# --- дамп ------------------------------------------------------------------------

def test_index_and_ranges_take_only_archive_streams():
    entries = parse_index(["600:1:Головна\n", "600:2:Архів:ДАЖО\n", "9000:3:Шевченко\n",
                           "12000:4:Архів:ДАЖО/1/80\n", "15000:5:Франко\n"])
    assert entries[1] == IndexEntry(600, 2, "Архів:ДАЖО")
    # поток 600 и поток 12000 — нужные, между ними один чужой: один диапазон
    assert stream_ranges(entries, 20000, gap=4) == [(600, 15000)]
    # без допуска на чужие потоки — два диапазона
    assert stream_ranges(entries, 20000, gap=1) == [(600, 9000), (12000, 15000)]


def test_dumpstatus_requires_finished_multistream():
    files = {
        "ukwikisource-20261101-pages-articles-multistream.xml.bz2": {
            "size": 169198859, "md5": "bae5", "url": "/ukwikisource/20261101/a.xml.bz2"},
        "ukwikisource-20261101-pages-articles-multistream-index.txt.bz2": {
            "size": 3421360, "md5": "32d7", "url": "/ukwikisource/20261101/i.txt.bz2"},
    }
    done = {"jobs": {"articlesmultistreamdump": {"status": "done", "files": files}}}
    dump = parse_dumpstatus(done, "20261101")
    assert dump.pages.size == 169198859 and dump.index.md5 == "32d7"
    assert dump.pages.url == "https://dumps.wikimedia.org/ukwikisource/20261101/a.xml.bz2"
    running = {"jobs": {"articlesmultistreamdump": {"status": "in-progress", "files": files}}}
    assert parse_dumpstatus(running, "20261101") is None


def _page_xml(title, ns, pid, text):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f"  <page>\n    <title>{title}</title>\n    <ns>{ns}</ns>\n    <id>{pid}</id>\n"
            f"    <revision><id>1</id><timestamp>2026-10-01T00:00:00Z</timestamp>"
            f"<text bytes=\"1\" xml:space=\"preserve\">{text}</text></revision>\n  </page>\n")


def test_two_bz2_streams_read_as_one_chunk_of_pages():
    first = bz2.compress(_page_xml("Архів:ДАЖО/1/80", 116, 7, INVENTORY).encode())
    second = bz2.compress((_page_xml("Шевченко", 0, 8, "текст") + "</mediawiki>\n").encode())
    pages = list(iter_pages(read_chunk(first + second)))
    assert [(p.title, p.ns, p.page_id) for p in pages] == [("Архів:ДАЖО/1/80", 116, 7),
                                                           ("Шевченко", 0, 8)]
    assert "Бобли" in pages[0].text


# --- опись и дела ------------------------------------------------------------------

def test_inventory_columns_are_named_and_markup_stripped():
    inv = _inventory()
    assert (inv.archive, inv.fond, inv.opis) == ("ДАЖО", "1", "80")
    assert inv.name == "Метричні книги Ковельського і Кременецького повітів"
    assert inv.categories == ["Ковельський повіт"]
    assert inv.rows[2] == {"case": "41",
                           "title": "Метричні книги церкви с. Бобли Ковельського повіту",
                           "uezd": "Ковельський", "years": "1840–1865", "sheets": "424"}


def test_church_and_place_columns_win_over_the_bare_title():
    inv = _inventory(CDIAK_224, "Архів:ЦДІАК/224/1")
    items = inventory_items(inv)
    assert [(it.subject.settlement, it.subject.dedication, it.uezd_uk) for it in items] == [
        ("Адамівка", "Святого Василя Великого", "Летичівський"),
        ("Адамівка", "Різдва Пресвятої Богородиці", "Гайсинський"),
    ]
    assert items[0].years == [(1738, 1781)]


def test_certificate_cases_with_names_are_not_metric_books():
    items = inventory_items(_inventory())
    assert "178" not in {it.case for it in items}
    assert not is_metric_title("За скаргою на священника д. Ковельнич, Григорія Дверницького "
                               "за видачу актів із метричних книг")
    assert not is_metric_title("Йосифінська метрика с. Бобли")
    assert is_metric_title("1928 рік. Метрична книга парафіян Свято-Іллінської церкви")
    assert is_metric_title("Церква св. Георгія Победоносця м. Кам'янець-Подільський. "
                           "Метричні книги")


def test_contents_spread_a_consolidated_volume_over_its_parishes():
    inv = _inventory()
    items = inventory_items(inv)
    rows = case_contents(CASE_1)
    assert rows[3].village == "Вижва, м-ко"
    assert rows[2].attached == ("Вулька Вербичанська", "Ось", "Ревушки")
    expanded = expand_contents(items, {"1": rows})
    assert {it.subject.settlement for it in expanded} == {"Білин", "Бобли", "Вербична", "Вижва"}
    entries = aggregate(inv, items + expanded)
    bobly = [e for e in entries if e.subject.settlement == "Бобли"]
    # «церкви с. Бобли» без посвящения слилась с приходом из «Змісту»
    assert len(bobly) == 1
    assert {it.case for it in bobly[0].items} == {"1", "41"}
    assert bobly[0].subject.dedication == "Покрова Пресвятої Богородиці"
    group = [e for e in entries if e.subject.kind == "group"]
    assert len(group) == 1 and group[0].subject.uezd_uk == "Ковельський"
    assert {it.subject.letters for it in group[0].items} == {"Б–Ш", "Б–Я"}


def test_list_inventory_without_a_table():
    text = ("* 1. [[c:File:Выписи 1850г.pdf|1850 рік. Метрична книга синагоги м. Ківшовата "
            "(народження, шлюб, розлучення, смерть)]]\n")
    assert list_rows(text) == [{"case": "1", "years": "1850 ",
                                "title": "Метрична книга синагоги м. Ківшовата "
                                         "(народження, шлюб, розлучення, смерть)"}]


# --- названия дел ---------------------------------------------------------------------

def test_subject_of_a_single_church():
    s = parse_subject("Метрична книга церкви Покрови Пресвятої Богородиці с. Чаплинка "
                      "Дніпровського повіту. Народження")
    assert (s.kind, s.marker, s.settlement, s.dedication, s.uezd_uk) == (
        "church", "с.", "Чаплинка", "Покрови Пресвятої Богородиці", "Дніпровський")
    jews = parse_subject("Метрична книга єврейської громади м. Олександрівська Катеринославської "
                         "губернії про народження")
    assert jews.church == "синагога, еврейская община" and jews.gub_uk == "Катеринославська"
    assert parse_subject("Метрична книга").kind == "unknown"


def test_several_parishes_in_one_case():
    parts = split_subjects("Метрична книга запису народжень, шлюбів та смерті Михайлівської "
                           "церкви в с. Дроздні та Успенської церкви в с. Доротище Ковельського "
                           "повіту за 1843 рік")
    assert [(p.subject.settlement, p.subject.dedication) for p in parts] == [
        ("Дроздні", "Михайлівської"), ("Доротище", "Успенської")]
    # годы названы только у последнего села — они общие для дела
    assert all(p.years == () for p in parts)


def test_villages_with_their_own_years():
    parts = split_subjects("Метричні книги с. Вовків за 1858 р.; с. Плетеничі за 1836-1839, "
                           "1857-1858 рр., повіт Перемишляни. Копії")
    assert [(p.subject.settlement, p.years) for p in parts] == [
        ("Вовків", ((1858, 1858),)), ("Плетеничі", ((1836, 1839), (1857, 1858)))]
    assert parts[1].subject.uezd_uk == "Перемишляни"


def test_attached_villages_stay_with_their_parish():
    parts = split_subjects("Метрична книга парафіян церкви Святого Архістратига Михаїла села "
                           "Зачернеччя та сіл Вигнанка, Рудня та хуторів Довгий Ліс")
    assert len(parts) == 1
    assert parts[0].subject.settlement == "Зачернеччя"
    assert parts[0].attached == ("Вигнанка", "Рудня", "Довгий Ліс")


@pytest.mark.parametrize("raw, expected", [
    ("1840–1865", [(1840, 1865)]),
    ("1876-1884, 1886-1889", [(1876, 1884), (1886, 1889)]),
    ("1909, 1912", [(1909, 1909), (1912, 1912)]),
    ("1881.01.06–1895.12.24", [(1881, 1895)]),
    ("2 січня –<br />28 липня 1803", [(1803, 1803)]),
    ("1830 – 1832 1885 – 1889", [(1830, 1832), (1885, 1889)]),
    ("1860-80, 1851", [(1860, 1880), (1851, 1851)]),
    ("", []),
])
def test_years(raw, expected):
    assert parse_years(raw) == expected


def test_compact_years():
    assert compact_years({1840, 1841, 1842, 1850, 1852, 1853}) == "1840–1842, 1850, 1852–1853"


# --- уезды ----------------------------------------------------------------------------

def test_uezd_keys_join_ukrainian_and_russian_spelling():
    assert uezd_keys("Заславський") & uezd_keys("Изяславский")
    assert uezd_keys("Луцький") & uezd_keys("Луцкий")
    assert uezd_keys("Одеський") & uezd_keys("Одесский")
    assert not uezd_keys("Ковельський") & uezd_keys("Кобринский")


def test_resolver(resolver):
    place = resolver.resolve("Заславський", "Волинська", "ДАЖО")
    assert (place.province, place.district, place.how) == (
        "Волынская губерния", "Изяславский уезд", "exact")
    assert resolver.resolve("Овруцький", None, "ДАЖО").how == "manual"
    # Радомысльский уезд описи «Волинської губернії» 1795 года — в 1897-м Киевский
    radomysl = resolver.resolve("Радомисльський", "Волинська", "ДАЖО")
    assert radomysl.province == "Киевская губерния"
    # галицкий повит не сводится с белорусским уездом даже похожим ключом
    galicia = resolver.resolve("Бібрка", None, "ЦДІАЛ")
    assert galicia.district is None and galicia.land == "Галиция (Австро-Венгрия)"
    # приход в уездном городе без уезда в описи — уезд по городу
    assert resolver.resolve(None, None, "ДАЖО", town="Ковель").how == "town"
    assert resolver.resolve("Любомльський", None, "ДАВоО").how == "interwar"


# --- запись схемы ------------------------------------------------------------------------

class _Districts:
    """Вместо полигонов уездов: точка → номер уезда."""

    def region_for(self, lat, lon):
        return "312" if lat > 51 else None


def test_record_is_territorial_with_cases_and_link(resolver):
    harvest = collect([Page("Архів:ДАЖО/1/80", 116, 1, "", INVENTORY),
                       Page("Архів:ДАЖО/1/80/1", 116, 2, "", CASE_1),
                       Page("Архів:ДАЖО/1", 116, 3, "", "{{Архіви/фонд\n | назва = Волинська "
                                                       "духовна консисторія\n}}")])
    assert harvest.fond_names == {"ДАЖО/1": "Волинська духовна консисторія"}
    entries = build_entries(harvest)
    bobly = next(e for e in entries if e.subject.settlement == "Бобли")
    rec = entry_to_record(bobly, resolver, fond_names=harvest.fond_names, dump_date="20261101")
    assert rec.layer == METRIC_BOOKS_UA.slug and rec.scope == "region"
    assert (rec.region, rec.district) == ("Волынская губерния", "Ковельский уезд")
    assert rec.regions == ["Волынская губерния"]
    assert (rec.year_from, rec.year_to, rec.period_raw) == (1797, 1865, "1797, 1840–1865")
    assert rec.extra["cases"] == "1 (1797); 41 (1840–1865, 424 арк.)"
    assert rec.extra["fond_name"] == "Волинська духовна консисторія"
    assert rec.url == page_url("Архів:ДАЖО/1/80")
    assert rec.url.startswith("https://uk.wikisource.org/wiki/%D0%90")
    assert rec.source_id.startswith("ДАЖО/1/80/церковь|бобли|")
    assert "Ковельский уезд" in rec.summary and rec.confidence == "ok"


def test_village_point_only_when_unique_in_its_uezd(resolver):
    entries = build_entries(Harvest(inventories={"ДАЖО/1/80": _inventory()}))
    bobly = next(e for e in entries if e.subject.settlement == "Бобли")
    items = {"1": {"title": "Бобли", "lat": 51.3, "lon": 24.9, "names": ["Bobli"]},
             "2": {"title": "Камінь-Каширський", "lat": 51.6, "lon": 24.96, "names": []},
             "3": {"title": "Камінь-Каширський", "lat": 51.62, "lon": 24.97, "names": []}}
    villages = VillageIndex(items, _Districts())
    rec = entry_to_record(bobly, resolver, villages=villages)
    assert (rec.lat, rec.lon, rec.scope, rec.confidence) == (51.3, 24.9, "point", "place_level")
    assert rec.extra["geo"]["method"] == "name_variants+uezd_1897"
    kamin = next(e for e in entries if e.subject.settlement == "Камінь-Каширський")
    # два места с одним названием в уезде — точки нет
    assert entry_to_record(kamin, resolver, villages=villages).lat is None


def test_markup_and_case_formatting():
    assert strip_markup("[[/41/]] ''Метричні'' книги<br/>церкви") == "/41/ Метричні книги церкви"
    items = inventory_items(_inventory())
    assert format_cases([i for i in items if i.case == "177"]) == "177 (1876–1895, 791 арк.)"
