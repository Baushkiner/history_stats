"""Разбор реестра «Храмы России» (temples.ru).

Сети в тестах нет. Образцы ниже — куски живых страниц 24.11.2026, урезанные
до двух-трёх строк: выдача поиска `cardsearch.php` (в атрибуте подсказки у
ссылки лежит `<img …>` в кавычках — на нём прежний разбор терял класс
исповедания), KML для Google Earth, дерево губерний `provincies.php` и
учётная карточка `card.php`.

Проверяется то, на чём слой держится: строки выдачи с типом, статусом,
исповеданием и датой; точки KML со статусом из подписи; губерния и уезд по
спискам KML единиц (уезд точнее губернии); поля карточки и цепочка
губерния → уезд; разбор дат с римскими веками и скобочным вариантом;
срок записи — от постройки до горизонта, у недатированной из реестра 1917
года — открытый срок до 1917-го; запись без точки — `no_coords`, а не потеря.
"""

from histctx.registry import BY_SLUG
from histctx.sources.temples_ru import (
    CARD_URL, LAYER_ID, OPEN_END, TEMPLES_RU, Collected, Placemark, Row, Unit, broken_units,
    card_units,
    dating, decode, page_count, parse_built, parse_card, parse_kml, parse_province_children,
    parse_regions, parse_search, province_index, record, records, search_query,
)

FORM = """<td VALIGN="top" ALIGN="left"><select id="selectRegionID" name="RegionID" >
<option value="0" ><< все регионы >><option value="717" >Алтайский край
<option value="682" >Амурская область</select></td>"""

SEARCH = """<div Class="Header">Найдено карточек: 52</div><HR SIZE="1"><TABLE BORDER="0"
CELLSPACING="0"><TR ALIGN="center" BGCOLOR="#EAEAEA" CLASS="Small"><TD COLSPAN="2">&nbsp;</TD>
<TD>Современный адрес</TD><TD>Дата постройки</TD></TR><TR BGCOLOR="#FFFFFF"><TD VALIGN="top"><IMG
SRC="../img/monastery.gif" TITLE="действ." ALT="1" WIDTH="17" HEIGHT="17" BORDER="0"></TD><TD
VALIGN="top"> <A onmousemove="position_hint(event);" onmouseover="show_hint(event,'<img
src=http://images.temples.ru/private/preview_list/17/167615s.jpg>');" onmouseout="hide_hint(event);"
CLASS="isp_prav" HREF="/card.php?ID=8360">Богоявленский Каменский женский монастырь</A></TD><TD
VALIGN="top"><a class="Items" href="tree.php?ID=3108">Алтайский край, Каменский р-н, г.
Камень-на-Оби, ул. Декабристов, 19</a></TD><TD VALIGN="top"><NOBR></NOBR></TD></TR><TR
BGCOLOR="#EAEAEA"><TD VALIGN="top"><IMG SRC="../img/church_n.gif" TITLE="не сохр." ALT="3"
WIDTH="17" HEIGHT="17" BORDER="0"></TD><TD VALIGN="top"> <A CLASS="isp_star"
HREF="/card.php?ID=22540">Собор Троицы Живоначальной в Бийске</A><br><span style="font-size: 80%"
class="isp_star">( Церковь Троицкая; Троицкий собор)</span></TD><TD VALIGN="top"><a class="Items"
href="tree.php?ID=3105">Алтайский край, г. Бийск, пл. Фомченко</a></TD><TD
VALIGN="top"><NOBR>кон. XVII - 1-я пол. XVIII вв.</NOBR></TD></TR></TABLE>"""

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://earth.google.com/kml/2.1"><Document><name>Алтайский край</name>
<Placemark>
<!-- Object #9264 -->
<name>Церковь Иконы Божией Матери Всех Скорбящих Радость в Алейске (действ.)</name>
<description>
<![CDATA[<div align="center"><a href="http://www.temples.ru/gallery.php?CardID=9264"><img
src="http://www.temples.ru/private/f000254/254_0015463g.jpg"></a><br><br>
Алтайский край, г. Алейск, ул. Комсомольская, 130<br><br><a
href="http://www.temples.ru/card.php?ID=9264"><nobr><i>Подробная информация</i></nobr></a></div>]]>
</description>
<styleUrl>#style_survive</styleUrl>
<Point><coordinates>82.771120,52.495021,0</coordinates></Point>
</Placemark>
<Placemark>
<!-- Object #22540 -->
<name>Собор Троицы Живоначальной в Бийске (не сохр.)</name>
<styleUrl>#style_destroyed</styleUrl>
<Point><coordinates>85.21,52.54,0</coordinates></Point>
</Placemark>
<Placemark>
<!-- Object #1 -->
<name>Без точки</name>
<Point><coordinates>0.000000,0.000000,0</coordinates></Point>
</Placemark>
</Document></kml>"""

TREE = """<tr class="pr_tree_header_2"> <td class="pr_tree_total" colspan="2">Итого</td>
<td class="pr_tree_object">732</td></tr><tr class="pr_tree_regular_0" style="{RecordStyle}">
<td class="pr_tree_point"><img src="../img/plus_yes.gif"></td> <td class="pr_tree_title"><a
class="branch_title" href="provincies.php?ProvinceID=2845">Вологда, город</a></td>
<td class="pr_tree_object">76</td> <td class="pr_tree_hit"></td></tr>
<td class="pr_tree_title"><a class="branch_title" href="provincies.php?ProvinceID=274">Кадниковский
уезд</a></td> <td class="pr_tree_object">57</td>"""
TREE = TREE.replace("Кадниковский\nуезд", "Кадниковский уезд")

CARD = """<script>Initialization(8248, 59.932985, 41.259142, 13, 'church', '', 1, 0);</script>
<img src="/img/flag_ri.gif"> <a class="locate_link" href="provincies.php?ProvinceID=0">Российская
империя</a> <a class="locate_link" href="provincies.php?ProvinceID=16">Вологодская губерния</a>
<a class="locate_link" href="provincies.php?ProvinceID=274">Кадниковский уезд</a>
<TABLE WIDTH="100%" class="grid"><TR BGCOLOR="#DDDDDD"><TD ALIGN="center" CLASS="Small"
COLSPAN="2">У Ч Е Т Н А Я &nbsp; К А Р Т О Ч К А</TD></TR><TR BGCOLOR="#FFFFFF"><TD valign="top"
CLASS="Bold" WIDTH="30%">Название</TD><TD VALIGN="middle" class="card_h"><h1>Церковь Вознесения
Господня на погосте Евфимиев Монастырь</h1></TD></TR><TR BGCOLOR="#F0F0F0"><TD valign="top"
CLASS="Bold" WIDTH="30%">Тип постройки</TD><TD>церковь</TD></TR><TR BGCOLOR="#F0F0F0"><TD
valign="top" CLASS="Bold" WIDTH="30%">Дата постройки последнего здания</TD><TD>1759&nbsp;
&nbsp;(<a class="small" href="card_hron.php?Year=1759&TreeID=707">см. постройки той же
эпохи</a>)</TD></TR><TR BGCOLOR="#FFFFFF"><TD valign="top" CLASS="Bold"
WIDTH="30%">Архитектор</TD><TD><span style="color: #999">нет данных</span></TD></TR><TR
BGCOLOR="#FFFFFF"><TD valign="top" CLASS="Bold" WIDTH="30%">Историческое
исповедание</TD><TD>Православная</TD></TR><TR BGCOLOR="#FFFFFF"><TD valign="top" CLASS="Bold"
WIDTH="30%">Статус</TD><TD>сохр.</TD></TR><TR BGCOLOR="#F0F0F0"><TD valign="top" CLASS="Bold"
WIDTH="30%">Адрес на 1917 г.</TD><TD>Вологодская губ., Кадниковский у., пог. Евфимиев
Монастырь</TD></TR><TR BGCOLOR="#FFFFFF"><TD valign="top" CLASS="Bold" WIDTH="30%">Краткое
описание</TD><TD>Каменная летняя церковь. Закрыта в конце 1930-х.</TD></TR></TABLE>"""
CARD = CARD.replace("Историческое\nисповедание", "Историческое исповедание")
CARD = CARD.replace("Краткое\nописание", "Краткое описание")


def test_registry_entry():
    assert BY_SLUG[LAYER_ID] is TEMPLES_RU
    assert TEMPLES_RU.status == "harvested"
    assert "согласия владельца" in TEMPLES_RU.license


def test_decode_windows_1251_and_utf8_kml():
    assert decode("Храмы".encode("cp1251")) == "Храмы"
    assert decode(KML.encode("utf-8")).count("Placemark") == 6


def test_regions_from_form():
    assert parse_regions(FORM) == [(717, "Алтайский край"), (682, "Амурская область")]


def test_search_rows():
    total, rows = parse_search(SEARCH)
    assert total == 52 and page_count(total) == 2
    mon, sobor = rows
    assert (mon.id, mon.status, mon.icon, mon.confession) == (8360, "действ.", "monastery",
                                                              "православная")
    assert mon.tree_id == 3108 and mon.address.startswith("Алтайский край, Каменский р-н")
    assert mon.built is None
    assert sobor.confession == "старообрядческая" and sobor.status == "не сохр."
    assert sobor.alt_names == "Церковь Троицкая; Троицкий собор"
    assert sobor.built == "кон. XVII - 1-я пол. XVIII вв."


def test_search_building_status_and_no_confession():
    # У строящегося подпись значка пуста — статус по коду; `isp_none` —
    # исповедание не указано (новые храмы).
    page = ('<div Class="Header">Найдено карточек: 1</div><TABLE><TR BGCOLOR="#FFFFFF"><TD>'
            '<IMG SRC="../img/church_b.gif" TITLE="" ALT="5" WIDTH="17"></TD><TD> '
            '<A CLASS="isp_none" HREF="/card.php?ID=31744">Собор Успения в Нарьян-Маре</A>'
            '</TD><TD><a class="Items" href="tree.php?ID=16450">г. Нарьян-Мар</a></TD>'
            '<TD><NOBR>строится</NOBR></TD></TR></TABLE>')
    (row,) = parse_search(page)[1]
    assert row.status == "строит." and row.confession is None and row.built == "строится"
    assert dating(row.built, False).precision == "unknown"


def test_search_empty_and_query():
    assert parse_search("<span>По данному запросу ничего не найдено</span>") == (0, [])
    q = search_query(717, 5, 3)
    assert "TempleType%5B%5D=5" in q and "RegionID=717" in q and q.endswith("nopage=3")


def test_kml_points():
    pts = parse_kml(KML)
    assert [p.id for p in pts] == [9264, 22540]       # нулевая точка — не точка
    a, b = pts
    assert a.name.endswith("в Алейске") and a.status == "действ." and not a.destroyed
    assert (a.lat, a.lon) == (52.495021, 82.77112)
    assert a.address == "Алтайский край, г. Алейск, ул. Комсомольская, 130"
    assert b.status == "не сохр." and b.destroyed


def test_province_tree():
    total, children = parse_province_children(TREE)
    assert total == 732
    assert children == [(2845, "Вологда, город", 76), (274, "Кадниковский уезд", 57)]


def test_province_index_prefers_uezd():
    units = [Unit(16, "Вологодская губерния"), Unit(274, "Кадниковский уезд", 16)]
    idx = province_index(units, {16: [1, 2], 274: [2]})
    assert idx[2] == ("Вологодская губерния", "Кадниковский уезд")
    assert idx[1] == ("Вологодская губерния", None)


def test_province_index_skips_kml_longer_than_tree():
    # Романово-Борисоглебский уезд: 70 объектов в дереве, а KML — со всей России.
    units = [Unit(371, "Ярославская губерния"), Unit(2674, "Романово-Борисоглебский уезд", 371),
             Unit(2675, "Ростовский уезд", 371)]
    members = {2674: list(range(100, 200)), 2675: [7]}
    assert broken_units(members, {2674: 70, 2675: 1}) == {2674}
    idx = province_index(units, members, {2674: 70, 2675: 1})
    assert idx == {7: ("Ярославская губерния", "Ростовский уезд")}


def test_card_fields():
    card = parse_card(CARD)
    assert card["id"] == 8248 and (card["lat"], card["lon"]) == (59.932985, 41.259142)
    assert card["built"] == "1759"                      # без ссылки «той же эпохи»
    assert "architect" not in card                      # «нет данных» — не значение
    assert card["confession"] == "Православная" and card["status"] == "сохр."
    assert card["address_1917"].startswith("Вологодская губ., Кадниковский у.")
    assert card_units(card) == ("Вологодская губерния", "Кадниковский уезд")
    assert parse_card("<html>Карточка не найдена</html>") is None


def test_built_dates():
    assert parse_built("1759") == (1759, 1759, "year", False)
    assert parse_built("1720-1740")[:2] == (1720, 1740)
    assert parse_built("кон. XVII - 1-я пол. XVIII вв.")[:2] == (1690, 1750)
    assert parse_built("2-я пол. XIX в.")[:2] == (1851, 1900)
    assert parse_built("сер. XVIII в. (?)") == (1740, 1760, "part", True)
    assert parse_built("кон. XIX - нач. ХХ вв.")[:2] == (1890, 1915)   # «ХХ» кириллицей
    assert parse_built("Нач. ХХ в. (?)")[:2] == (1901, 1915)
    # Скобочный вариант расширяет интервал, а не заменяет основную дату.
    assert parse_built("1743 (1749 ?)") == (1743, 1749, "year", True)
    assert parse_built("") is None and parse_built("нет данных") is None


def test_dating_open_and_registry():
    d = dating("1877", False)
    assert (d.year_from, d.year_to, d.precision) == (1877, OPEN_END, "open")
    d = dating("2013-2019", False)
    assert (d.year_from, d.year_to) == (2013, 2019)    # не «2013–1960»
    d = dating(None, True)
    assert (d.year_from, d.year_to, d.precision, d.approx) == (1800, 1917, "open", True)
    assert d.source == "реестр на 1917 год"
    d = dating(None, False)
    assert d.year_from is None and d.precision == "unknown"


def test_record_merges_row_point_units_card():
    _, rows = parse_search(SEARCH)
    row = rows[1]
    row.temple_type = "церковь"
    pm = parse_kml(KML)[1]
    rec = record(row, point=pm, units=("Томская губерния", "Бийский уезд"))
    assert rec.layer == LAYER_ID and rec.category == "церковь"
    assert (rec.lat, rec.lon) == (52.54, 85.21) and rec.confidence == "ok"
    assert rec.region == "Томская губерния" and rec.district == "Бийский уезд"
    assert (rec.year_from, rec.year_to) == (1690, OPEN_END)
    assert rec.extra["lost"] is True and rec.extra["confession"] == "старообрядческая"
    assert rec.url == CARD_URL.format(22540) and rec.source_id == "temples.ru:22540"
    assert "Не сохранился" in rec.summary or "не сохранился" in rec.summary


def test_records_without_point_and_from_card_only():
    card = parse_card(CARD)
    data = Collected(rows={5: Row(id=5, name="Часовня в Шилово", status="не сохр.",
                                  temple_type="часовня")},
                     cards={8248: card},
                     points={9264: Placemark(9264, "Церковь в Алейске", "действ.", None,
                                             52.5, 82.8, False)})
    recs = {r.extra["temples_id"]: r for r in records(data)}
    assert recs[5].confidence == "no_coords" and not recs[5].has_point
    assert recs[5].date_precision == "unknown"
    only_card = recs[8248]
    assert only_card.has_point and only_card.region == "Вологодская губерния"
    assert only_card.category == "церковь" and only_card.year_from == 1759
    assert "Закрыта в конце 1930-х" in only_card.summary
    assert recs[9264].category == "церковь" and recs[9264].extra["status"] == "действ."


def test_link_churches_needs_name_and_distance():
    from histctx.schema import ContextRecord
    from histctx.sources.temples_ru import link_churches

    mine = TEMPLES_RU.new_record(title="Церковь Покрова Пресвятой Богородицы в Сосновке",
                                 lat=60.0, lon=40.0)
    far = TEMPLES_RU.new_record(title="Церковь Покрова в Дальнем", lat=61.0, lon=40.0)
    wd = [ContextRecord(layer="churches", title="Церковь Николая Чудотворца (Сосновка)",
                        lat=60.0005, lon=40.0),
          ContextRecord(layer="churches", title="Покровская церковь (Сосновка)",
                        lat=60.001, lon=40.0)]
    assert link_churches([mine, far], wd) == 1
    assert mine.extra["churches"] == wd[1].uid and "churches" not in far.extra


def test_dating_founded_earlier_than_building():
    d = dating("1877", False, founded="1620")
    assert (d.year_from, d.year_to) == (1620, OPEN_END) and d.raw.startswith("основан 1620")
    d = dating(None, True, founded="кон. 1990-х")
    assert d.year_from == 1997 and d.source is None    # основание важнее реестровой рамки
    assert dating("1877", False, founded="1990").year_from == 1877
