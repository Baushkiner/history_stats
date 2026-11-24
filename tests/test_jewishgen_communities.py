"""Разбор слоя общин JewishGen Communities с подчинением по эпохам.

Сети в тестах нет. Образец — строки выдачи `jgcd.php` в разметке JG40
(ноябрь 2026): нынешнее название и страна, координата до минуты, названия
на языках, колонки «c. 1950», «c. 1930», «c. 1900» через `<br>`, со
ссылками на запросы уезда и губернии. Вторая строка — с номером общины
JewishGen вместо USBGN и без названия на 1950 год. Проверяется разбор
строк, ссылок для обхода волной, координаты и записи по эпохам.
"""

from histctx.registry import BY_SLUG
from histctx.sources.jewishgen_communities import (
    ERAS, JEWISHGEN_COMMUNITIES, coords, describe, page_links, parse_names, parse_rows,
    query_key, query_url, records, result_count,
)

PAGE = """<span class="sr-count"><strong>2</strong> matches</span>
<tbody id="sr-body"><tr class="sr-row sr-row--link" data-href="/Communities/community.php?usbgn=-1943656&amp;scale=K"><td class="shtet" usbgn="-1943656"><a class="sr-rowlink" href="/Communities/community.php?usbgn=-1943656&amp;scale=K" title="More about Ivanava"><b>Ivanava</b></a>, Belarus<br><span class="sr-coords">52&deg;08' N 25&deg;33' E <br>238 km SW of Minsk</span></td><td>Ivanava [Bel], Ivanovo [Rus], Janów [Pol], Yanov [Yid], Janow Polesie</td><td>Ivanovo<br>Soviet&nbsp;Union</td><td>Janów<br><a href='/Communities/jgcd.php?get=y&dist1930=Drohiczyn&prov1930=Polesie'>Drohiczyn</a><br><a href='/Communities/jgcd.php?get=y&prov1930=Polesie'>Polesie</a><br>Poland</td><td>Ivanovo<br><a href='/Communities/jgcd.php?get=y&dist1900=Kobrin&prov1900=Grodno'>Kobrin</a><br><a href='/Communities/jgcd.php?get=y&prov1900=Grodno'>Grodno</a><br>Russian&nbsp;Empire</td><td class="sr-num"><a href="/jgff/jgffform.php?feature=-1943656">1,154</a></td></tr><tr class="sr-row sr-row--link" data-href="/Communities/community.php?usbgn=A0059&amp;scale=K"><td class="shtet" usbgn="A0059"><a class="sr-rowlink" href="/Communities/community.php?usbgn=A0059&amp;scale=K"><b>Lotovo</b></a>, Belarus<br><span class="sr-coords">52&deg;25' N 23&deg;46' E <br>302 km SW of Minsk</span></td><td>Lotovo [Rus], Łotowo [Pol]</td><td><br>Soviet&nbsp;Union</td><td>Łotowo<br><a href='/Communities/jgcd.php?get=y&dist1930=Brześć nad Bugiem&prov1930=Polesie'>Brześć&nbsp;nad&nbsp;Bugiem</a><br><a href='/Communities/jgcd.php?get=y&prov1930=Polesie'>Polesie</a><br>Poland</td><td>Lotovo<br><a href='/Communities/jgcd.php?get=y&dist1900=Brest&prov1900=Grodno'>Brest</a><br><a href='/Communities/jgcd.php?get=y&prov1900=Grodno'>Grodno</a><br>Russian&nbsp;Empire</td><td class="sr-num">0</td></tr></tbody>"""


def test_layer_is_registered_with_rights_in_words():
    assert BY_SLUG["jewishgen_communities"] is JEWISHGEN_COMMUNITIES
    assert "согласия владельца" in JEWISHGEN_COMMUNITIES.license


def test_rows():
    rows = parse_rows(PAGE)
    assert result_count(PAGE) == 2 == len(rows)
    a, b = rows
    assert (a.usbgn, a.name, a.country, a.jgff) == ("-1943656", "Ivanava", "Belarus", 1154)
    assert (a.lat, a.lon) == (52.1333, 25.55)
    assert a.eras["1900"] == {"town": "Ivanovo", "district": "Kobrin", "province": "Grodno",
                              "country": "Russian Empire"}
    assert a.eras["1930"]["district"] == "Drohiczyn"
    assert a.eras["1950"] == {"town": "Ivanovo", "country": "Soviet Union"}
    assert b.usbgn == "A0059"
    assert b.eras["1950"] == {"country": "Soviet Union"}
    assert b.eras["1930"]["district"] == "Brześć nad Bugiem"
    assert b.jgff == 0


def test_names_keep_language_tags():
    assert parse_names("Pinsk [Rus, Bel, Yid], Pińsk [Pol], Karlin-Pinsk") == [
        "Pinsk [Rus, Bel, Yid]", "Pińsk [Pol]", "Karlin-Pinsk"]


def test_links_for_the_wave_are_provinces_not_districts():
    links = page_links(PAGE)
    assert {"prov1930": "Polesie"} in links and {"prov1900": "Grodno"} in links
    assert len(links) == 2
    assert query_url({"prov1900": "Grodno"}).endswith("jgcd.php?get=y&prov1900=Grodno")
    assert query_key({"prov1930": "Pińsk"}) != query_key({"prov1930": "Pinsk"})


def test_coords_south_and_west():
    assert coords("33&deg;35' N 07&deg;37' W") == (33.5833, -7.6167)
    assert coords("нет") == (None, None)


def test_records_by_era():
    recs = records(parse_rows(PAGE)[:1])
    assert len(recs) == len(ERAS)
    r1900, r1930, r1950 = recs
    assert (r1900.year_from, r1900.year_to, r1900.date_precision) == (1880, 1914, "era")
    assert r1900.district == "Kobrin" and r1900.category == "Российская империя"
    assert "уезд Kobrin, губерния Grodno" in r1900.summary
    assert "повят Drohiczyn, воеводство Polesie, Польша" in r1930.summary
    assert r1950.year_from == 1945 and "ныне Ivanava, Belarus" in r1950.summary
    assert len({r.uid for r in recs}) == 3
    assert r1900.url.endswith("community.php?usbgn=-1943656")


def test_describe_without_town():
    assert describe({"country": "Soviet Union"}) == "СССР"
