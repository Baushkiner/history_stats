"""Указатель метрических книг Архивов Беларуси: страницы уездов и Excel НИАБ.

Образцы — фрагменты ответов WP REST портала archives.gov.by от 04.11.2026:
таблицы страниц Бобруйского, Минского и Невельского уездов (в том числе
вариант с отдельными колонками «Фонд» и «Опись» и строка, слипшаяся с
заголовком без `</tr>`), заголовки русских и английских страниц и строки
Excel «Единого межфондового указателя» НИАБ в Гродно.
"""

import io

from histctx.sources.archives_by import (
    METRIC_BOOKS_BY, aggregate, entry_to_record, excel_place, excel_records, excel_rows,
    holdings, page_rows, parse_page_title, parse_parish, parse_tables, split_fond,
)
from histctx.sources.wikisource_arkhiv import UezdResolver

BOBRUISK = """<p><b>Национальный исторический архив Беларуси в г. Минске</b></p>
<table border="1" width="100%" class="gen_table">
<tr align="center">
    <td width="30%"><b>Приход/<i>Церковь</i></b> </td>
    <td width="40%"><b>Годы</b> </td>
    <td width="30%"><b>Фонд/Опись</b></td>
  </tr>
  <tr><td>Разных церквей уезда</td><td>1786  &#8211;  1791,   1796  &#8211;  1840</td>
      <td>136/13</td></tr>
  <tr><td> </td><td>1843,  1854,   1856  &#8211;  1866</td><td>136/18</td></tr>
  <tr><td>Бацевичский</td><td>1798  &#8211;  1835</td><td>136/13</td></tr>
  <tr><td>&nbsp;</td><td>1844  &#8211;  1913</td><td>1356</td></tr>
  <tr><td>Бобруйск / <i>Софийская кладбищенская церковь</i></td><td>1831,  1917</td>
      <td>1382</td></tr>
</table>
<p><strong>Национальный исторический архив Беларуси в г. Гродно</strong></p>
<table border="1" class="gen_table">
  <tr><td><b>Приход /церковь</b></td><td><b>Годы</b></td><td><b>Фонд</b></td>
      <td><b>Опись</b></td><td><b>Количество единиц хранения</b></td></tr>
  <tr><td>Бацевичский</td><td>1919-1939</td><td>2345</td><td>1</td><td>12</td></tr>
</table>
"""

# Строка данных без `</tr>` перед ней: ячейки идут подряд за заголовком.
NEVEL = """<p><strong>Национальный исторический архив Беларуси в г. Минске</strong></p>
<table class="gen_table">
  <tr><td><b>Приход / Церковь</b></td><td><b>Годы</b></td><td><b>Фонд/Опись</b></td>
  <td><b>Номера единиц хранения</b></td>
  <td>Невельский (Невлянский) / Крестовоздвиженская</td><td>1840 — 1849, 1851 — 1854</td>
  <td>136 / 14</td><td>380 — 382, 385 — 387</td></tr>
  <tr><td>Язненский</td><td>1869-1874, 1876</td><td>&nbsp;</td><td>12</td></tr>
</table>
"""

DISTRICTS = [
    {"properties": {"prov_RU": "Минская губерния", "Name_RU": n, "Distr_ID": i}}
    for n, i in (("Бобруйский", 305), ("Минский", 307), ("Пинский", 308))
] + [
    {"properties": {"prov_RU": "Виленская губерния", "Name_RU": n, "Distr_ID": i}}
    for n, i in (("Дисненский", 290), ("Лидский", 292), ("Вилейский", 288))
] + [
    {"properties": {"prov_RU": "Гродненская губерния", "Name_RU": n, "Distr_ID": i}}
    for n, i in (("Кобринский", 285), ("Пружанский", 282), ("Слонимский", 284))
] + [
    {"properties": {"prov_RU": "Витебская губерния", "Name_RU": "Велижский", "Distr_ID": 270}},
    {"properties": {"prov_RU": "Могилевская губерния", "Name_RU": "Горецкий", "Distr_ID": 300}},
]


def test_page_titles_ru_and_en():
    info = parse_page_title(831787, "Метрические книги православных церквей Бобруйского уезда "
                                    "Минской губернии", "orthodox")
    assert (info.uezd, info.province, info.unit) == ("Бобруйский", "Минская губерния", "уезд")
    disna = parse_page_title(171356, "Метрические книги православных церквей Дисненского уезда "
                                     "Минской (с 1845 &#8212; Виленской) губернии", "orthodox")
    assert (disna.uezd, disna.province) == ("Дисненский", "Виленская губерния")
    deanery = parse_page_title(457122, "Метрические книги католических костелов Минской губернии "
                                       "Ошмянский деканат", "catholic")
    assert (deanery.uezd, deanery.unit) == ("Ошмянский", "деканат")
    en = parse_page_title(244567, "Parish records of Orthodox churches<br>Velizh uezd Vitebsk "
                                  "province", "orthodox", english=True)
    assert (en.uezd, en.province, en.english) == ("Velizh", "Витебская губерния", True)


def test_tables_get_their_archive_and_continuation_rows_their_parish():
    tables = parse_tables(BOBRUISK)
    assert [(t[0], t[1]) for t in tables] == [
        ("НИАБ (Минск)", ["parish", "years", "fond_opis"]),
        ("НИАБ (Гродно)", ["parish", "years", "fond", "opis", "units"]),
    ]
    rows = page_rows(BOBRUISK)
    assert [(r.parish, r.fond, r.opis) for r in rows] == [
        ("Разных церквей уезда", "136", "13"), ("Разных церквей уезда", "136", "18"),
        ("Бацевичский", "136", "13"), ("Бацевичский", "1356", None),
        ("Бобруйск / Софийская кладбищенская церковь", "1382", None),
        ("Бацевичский", "2345", "1"),
    ]
    assert rows[-1].archive == "НИАБ (Гродно)" and rows[-1].units == "12"


def test_row_glued_to_the_header_is_split_by_header_width():
    rows = page_rows(NEVEL)
    assert [(r.parish, r.fond, r.opis, r.units) for r in rows] == [
        ("Невельский (Невлянский) / Крестовоздвиженская", "136", "14", "380 — 382, 385 — 387"),
        ("Язненский", None, None, "12"),
    ]


def test_parish_with_church_and_group_rows():
    p = parse_parish("Бобруйск / Софийская кладбищенская церковь")
    assert (p.parish, p.church, p.group) == ("Бобруйск", "Софийская кладбищенская церковь", False)
    assert parse_parish("Разных костелов уезда").group
    assert split_fond("136 / 14") == ("136", "14") and split_fond("1356") == ("1356", None)


def test_record_per_parish_with_all_holdings():
    info = parse_page_title(831787, "Метрические книги православных церквей Бобруйского уезда "
                                    "Минской губернии", "orthodox")
    entries = aggregate(info, page_rows(BOBRUISK), linked=False)
    assert [e.parish.name for e in entries] == [
        "Разных церквей уезда", "Бацевичский", "Бобруйск / Софийская кладбищенская церковь"]
    rec = entry_to_record(entries[1], UezdResolver(DISTRICTS))
    assert rec.layer == METRIC_BOOKS_BY.slug and rec.scope == "region"
    assert (rec.region, rec.district) == ("Минская губерния", "Бобруйский уезд")
    assert (rec.year_from, rec.year_to) == (1798, 1939)
    assert rec.period_raw == "1798–1835, 1844–1913, 1919–1939"
    assert rec.extra["holdings"] == ("НИАБ (Минск) ф. 136, оп. 13: 1798 – 1835; НИАБ (Минск) "
                                     "ф. 1356: 1844 – 1913; НИАБ (Гродно) ф. 2345, оп. 1: "
                                     "1919-1939 (12 ед. хр.)")
    assert rec.extra["archives"] == ["НИАБ (Гродно)", "НИАБ (Минск)"]
    assert rec.extra["linked"] is False
    assert rec.url == "https://archives.gov.by/?page_id=831787"
    group = entry_to_record(entries[0], UezdResolver(DISTRICTS))
    assert group.category == "сводные книги нескольких приходов"


def test_holdings_lists_unit_numbers_as_they_are():
    rows = page_rows(NEVEL)
    assert holdings(rows[:1]) == ("НИАБ (Минск) ф. 136, оп. 14: 1840 — 1849, 1851 — 1854 "
                                  "(ед. хр. 380 — 382, 385 — 387)")
    assert holdings(rows[1:]) == "НИАБ (Минск), шифр не указан: 1869-1874, 1876 (12 ед. хр.)"


def _xlsx(rows):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(['Государственное учреждение "Национальный исторический архив Беларуси в г. Гродно"'])
    ws.append([None, "Крайние даты"])
    ws.append(["Церкви", "о родившихся", "о бракосоче-тавшихся", "об умерших"])
    ws.append(["1", "2", "3", "4"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


EXCEL = _xlsx([
    ["Андроновская церковь Кобринского у. Гродненской губ., с 1921 г. Кобринского повета "
     "Полесского воеводства ", "1802-1818, 1832-1860 гг.", "1835-1860 гг.", "1835-1860, 1924 гг."],
    ["Альбертинская униатская церковь Слонимского повета Новогрудского воеводства",
     "декабрь 1924- 1939 гг.", "1925-1926 гг.", "1925-1939 гг."],
    ["Камень-Шляхетская церковь Пружанскогоу. Гродненской губ.", "1890-1913 гг.", None, None],
    ["Октябрьская церковь (см. Камень-Шляхетская церковь)", None, None, None],
    ["Бесовицкая церковь Могилёвской губ.", "1850 г.", "1850 г.", "1850 г."],
])


def test_excel_rows_and_places():
    rows = excel_rows(EXCEL)
    assert [r.name for r in rows] == ["Андроновская церковь", "Альбертинская униатская церковь",
                                      "Камень-Шляхетская церковь", "Октябрьская церковь",
                                      "Бесовицкая церковь"]
    assert rows[3].see == "Камень-Шляхетская церковь"
    assert excel_place(rows[0].location) == ("Кобринский", "Гродненская губерния", None)
    assert excel_place(rows[1].location) == (None, None,
                                             "Слонимский повет Новогрудского воеводства")
    assert excel_place(rows[2].location) == ("Пружанский", "Гродненская губерния", None)
    assert excel_place(rows[4].location) == (None, "Могилевская губерния", None)


def test_excel_records_keep_dates_by_type_and_aliases():
    recs = excel_records(excel_rows(EXCEL), "orthodox", UezdResolver(DISTRICTS))
    by_name = {r.title.split(": ", 1)[1].rsplit(" — ", 1)[0]: r for r in recs}
    # отсылка «см.» — не своя запись, а другое имя прихода
    assert "Октябрьская церковь" not in by_name
    stone = by_name["Камень-Шляхетская церковь"]
    assert stone.extra["aliases"] == ["Октябрьская церковь"]
    andr = by_name["Андроновская церковь"]
    assert (andr.region, andr.district, andr.confidence) == (
        "Гродненская губерния", "Кобринский уезд", "ok")
    assert (andr.year_from, andr.year_to) == (1802, 1924)
    assert andr.extra["births"] == "1802-1818, 1832-1860 гг."
    alb = by_name["Альбертинская униатская церковь"]
    assert alb.region is None and alb.confidence == "district_interwar"
    assert alb.extra["confession"].startswith("греко-католическая")
    assert by_name["Бесовицкая церковь"].region == "Могилевская губерния"
