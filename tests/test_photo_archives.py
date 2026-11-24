"""Разбор трёх фотоархивов, собранных с согласия владельцев 24.11.2026.

Сети в тестах нет. Образцы ниже повторяют то, что отдавали сайты в день
сбора: выдача поиска russiainphoto.ru (`html.photos`), ячейки карты на
геохешах, ответ Ajapaik `api/v1/album/nearest/`, блок страницы снимка
«Военного альбома». Проверяется то, на чём держатся слои: место из подписи
`alt`, обход карты до листьев и точка снимка из ячейки, датировка во всех
встретившихся написаниях, горизонт 1960 года, место текстом → точка
населённого пункта и пометка «вне рамки» по стране без точки.
"""

import gzip
import json

from histctx.registry import BY_SLUG, HARVESTED
from histctx.sources import ajapaik, russiainphoto, waralbum
from histctx.sources.photo_common import photo_years


# --- общее -------------------------------------------------------------------

def test_photo_years_reads_archive_datings():
    assert photo_years("1870 - 1887")[:3] == (1870, 1887, "year")
    assert photo_years("1940-е")[:3] == (1940, 1949, "decade")
    assert photo_years("22 июня 1941")[:3] == (1941, 1941, "day")
    assert photo_years("20.06.1945")[:3] == (1945, 1945, "day")
    assert photo_years("июль 1941")[:3] == (1941, 1941, "month")
    # За горизонтом — None; конец, заходящий за горизонт, обрезается.
    assert photo_years("1965") is None
    assert photo_years("1955 - 1970")[:2] == (1955, 1960)
    assert photo_years("") is None


def test_layers_are_registered_as_harvested():
    for slug in ("photos_russiainphoto", "photos_ajapaik", "photos_waralbum"):
        spec = BY_SLUG[slug]
        assert spec in HARVESTED and spec.status == "harvested"
        assert "согласия владельца" in spec.license


# --- russiainphoto -----------------------------------------------------------

ITEM = """
<a class="b-search-result__item" href="/search/photo/?index=1&amp;page=1">
  <div class="b-search-popover-result"><div class="b-search-popover-result__item-title">
  {title}</div></div>
  <img data-width="289" data-height="500" src="https://735606.selcdn.ru/thumbnails/photos/{pid}_500.jpg"
       alt="{alt}">
  <div class="b-search-result__item-desc"><div class="b-search-result__item-desc-wrapper">
    <div class="b-search-result__item-title">{title}</div>
    <div class="b-search-result__item-info"><div class="b-search-result__item-years-wrapper">
      <div class="b-search-result__item-years">
        {years}
      </div></div>
      <div class="b-search-result__item-author">{author}</div>
    </div></div>
    <div class="b-search-result__item-button" data-id="{pid}"></div>
  </div>
</a>"""


def _items(*rows):
    return "".join(ITEM.format(pid=p, title=t, years=y, author=a, alt=alt) for p, t, y, a, alt in rows)


def test_search_items_give_place_from_alt():
    html = _items(
        (4473, "Мужской портрет", "1870 - 1887", "Иван Дьяговченко",
         "Мужской портрет, 1870 - 1887, г. Москва"),
        (4474, "Портрет, атрибутируемый как Серафим Саровский", "1840 - 1859", "",
         "Портрет, атрибутируемый как Серафим Саровский, 1840 - 1859"),
        (4475, "Вид на реку, Волга", "1910-е", "Фотоателье «Карелин»",
         "Вид на реку, Волга, 1910-е, Нижегородская губ., г. Нижний Новгород"),
    )
    items = russiainphoto.parse_items(html)
    assert [i.id for i in items] == [4473, 4474, 4475]
    assert items[0].place == "г. Москва" and items[0].author == "Иван Дьяговченко"
    assert items[1].place is None and items[1].author is None
    # Запятая в названии не сбивает: место — то, что после годов.
    assert items[2].place == "Нижегородская губ., г. Нижний Новгород"
    assert items[0].thumb.endswith("4473_500.jpg")


def test_geohash_bounds():
    n, w, s, e = russiainphoto.geohash_bounds("ucfv0")
    assert (round(n, 4), round(w, 4), round(s, 4), round(e, 4)) == (55.7666, 37.6172, 55.7227, 37.6611)


def test_crawl_grid_descends_to_leaves_and_splits_when_answer_is_coarse():
    """Ответ того же уровня — рамка делится на четверти; ячейка в 6 знаков — лист."""
    calls = []
    big = russiainphoto.geohash_bounds("uc")

    def grid(rect):
        calls.append(rect)
        if len(calls) == 1:     # первая рамка: ответ в 2 знака
            return {"results": [{"geohash": "uc", "photos_count": 3, "lat": 55.7, "lon": 37.6,
                                 "photo": {"id": 1}}]}
        if len(calls) == 2:     # та же ячейка, ответ не измельчился
            return {"results": [{"geohash": "uc", "photos_count": 3, "lat": 55.7, "lon": 37.6,
                                 "photo": {"id": 1}}]}
        if rect[0] > 55 and rect[1] < 37.7 < rect[3]:
            return {"results": [
                {"geohash": "ucfv0j", "photos_count": 2, "lat": 55.75, "lon": 37.62, "photo": {"id": 5}},
                {"geohash": "ucfv1", "photos_count": 1, "lat": 55.77, "lon": 37.65, "photo": {"id": 9}},
            ]}
        return {"results": []}

    leaves = russiainphoto.crawl_grid((60.0, 30.0, 50.0, 45.0), grid)
    assert set(leaves) == {"ucfv0j", "ucfv1"}
    assert leaves["ucfv1"].photo_id == 9 and leaves["ucfv1"].count == 1
    assert calls[1] == russiainphoto.intersect((60.0, 30.0, 50.0, 45.0), big)
    assert len(calls) == 2 + 4          # четверти после грубого ответа


def test_records_take_point_from_map_and_keep_the_rest_as_text(tmp_path):
    cells = tmp_path / "cells"
    cells.mkdir()
    (cells / "ucfv0j.json.gz").write_bytes(gzip.compress(json.dumps(
        {"geohash": "ucfv0j", "ids": [4473, 4476]}).encode()))
    leaves = {
        "ucfv0j": russiainphoto.Leaf("ucfv0j", 55.7533, 37.6207, 2, 4473),
        "uf06c1": russiainphoto.Leaf("uf06c1", 56.86, 35.9, 1, 4475),
    }
    pts = russiainphoto.points(leaves, tmp_path)
    assert pts[4476][:2] == (55.7533, 37.6207) and pts[4475][3] == 1
    items = russiainphoto.parse_items(_items(
        (4473, "Мужской портрет", "1870 - 1887", "", "Мужской портрет, 1870 - 1887, г. Москва"),
        (4474, "Портрет", "1850-е", "", "Портрет, 1850-е"),
        (4475, "На палубе", "1880 - 1890", "", "На палубе, 1880 - 1890, г. Тверь"),
        (4477, "Демонстрация", "1975", "", "Демонстрация, 1975, г. Москва"),
        (4473, "Мужской портрет", "1870 - 1887", "", "Мужской портрет, 1870 - 1887, г. Москва"),
    ))
    recs, skipped = russiainphoto.records(items, pts)
    by_id = {r.source_id: r for r in recs}
    assert set(by_id) == {"4473", "4474", "4475"}
    assert skipped == {"повтор": 1, "без года или позже горизонта": 1}
    assert by_id["4473"].extra == {"geohash": "ucfv0j", "cell_photos": 2}
    assert by_id["4474"].confidence == "no_coords" and by_id["4474"].lat is None
    assert by_id["4475"].url == "https://russiainphoto.ru/photos/4475/"
    assert by_id["4475"].date_approx and by_id["4475"].place_text == "г. Тверь"


# --- Ajapaik -----------------------------------------------------------------

def test_ajapaik_years():
    assert ajapaik.years("17-08-1938")[:3] == (1938, 1938, "day")
    assert ajapaik.years("1920-1930")[:4] == (1920, 1930, "year", False)
    assert ajapaik.years("u 1935")[3] is True
    assert ajapaik.years("[[192-?]]")[:4] == (1920, 1929, "decade", True)
    assert ajapaik.years("1930-ndad")[:3] == (1930, 1939, "decade")
    assert ajapaik.years("[arvatav aeg17.8.1998]") is None
    # Без даты — год из подписи, с пометкой.
    assert ajapaik.years(None, "Tallinn. Raekoda. Raesaal 1936. a")[5] == "подпись"
    assert ajapaik.years(None, "Raekoja plats") is None


def test_ajapaik_pages_and_records(tmp_path):
    page = [
        {"id": 1, "title": "Tallinn. Vaekoda", "date": "1939", "author": "C. Sarap",
         "source": {"url": "https://www.muis.ee/museaalView/1", "name": "EFM Fk 1"},
         "latitude": 59.437, "longitude": 24.745, "azimuth": 182.4, "rephotos": [{"x": 1}]},
        {"id": 2, "title": "Protestimiiting", "date": "1988", "author": None, "source": {},
         "latitude": 59.437, "longitude": 24.745, "azimuth": None},
        {"id": 3, "title": "Ljubov", "date": "1930", "author": None, "source": {},
         "latitude": None, "longitude": None, "azimuth": None},
        {"id": 1, "title": "Tallinn. Vaekoda", "date": "1939", "author": "C. Sarap", "source": {},
         "latitude": 59.437, "longitude": 24.745, "azimuth": None},
    ]
    (tmp_path / "nearest").mkdir()
    slim = [ajapaik.slim(p) for p in page]
    assert "rephotos" not in slim[0]
    ajapaik.page_path(tmp_path, 0).write_bytes(gzip.compress(json.dumps(slim).encode()))
    recs, skipped = ajapaik.records(ajapaik.load_pages(tmp_path))
    assert [r.source_id for r in recs] == ["1"]
    assert skipped == {"повтор": 1, "без точки": 1, "без года или позже горизонта": 1}
    rec = recs[0]
    assert rec.actor == "C. Sarap" and rec.extra["azimuth"] == 182.4
    assert rec.url == "https://ajapaik.ee/photo/1/" and rec.image_url.endswith("/photo-thumb/1/800/")


def test_ajapaik_fetch_stops_at_page_without_points(tmp_path):
    pages = {
        0: [{"id": i, "latitude": 59.0, "longitude": 24.0} for i in range(2)],
        2: [{"id": 9, "latitude": None, "longitude": None}, {"id": 10, "latitude": None}],
    }

    class Fake:
        urls = []

        def get(self, url):
            self.urls.append(url)
            start = int(url.rsplit("start=", 1)[1])
            return json.dumps({"error": 0, "photos": pages[start]}).encode()

    fake = Fake()
    assert ajapaik.fetch_pages(tmp_path, fetcher=fake, page=2, log=lambda *_: None) == 2
    assert len(fake.urls) == 2
    # Повторный запуск всё берёт из кэша.
    assert ajapaik.fetch_pages(tmp_path, fetcher=fake, page=2, log=lambda *_: None) == 2
    assert len(fake.urls) == 2


# --- «Военный альбом» --------------------------------------------------------

FRAGMENT = """<h1 class="title">Встреча Знамени Победы на аэродроме в Москве</h2>
<div class="entry"><img alt="Фото" title="" rel="lightbox" src="/photocache/17/3/173-files/173-main.jpg" width="800"/></div>
<div class="wa-content"><!-- no embed --><p>Знамя Победы проносят по Центральному аэродрому &#8212; капитан Варенников.</p> </div>
<div class="cat-info"> Источник: <noindex><a href="http://pobeda.tassphoto.com/x" rel="nofollow">pobeda.tassphoto.com</a></noindex>.<br>
Категория: <a href="https://waralbum.ru/photo/war/east/after_victory/" rel="category tag">После Победы</a><br> </div>
<div class="related-list"> <h3>Информация о фото</h3> <ul>
<li>Место съемки: {place}</li> <li>Время съемки: {time}</li>
<li>Автор: Дмитрий Чернов<noindex>&nbsp;(<a href="/?wpcfs=preset-0" rel="nofollow">40</a>)</noindex></li>
</ul> <h3>Оригинал</h3> <ul><noindex> <li class="yapb_alternative_format"><a href="https://waralbum.ru/wp-content/uploads/2009/06/varennikov.jpg" target="_blank">1417x947</a></li> </ul></noindex> </div>
<div style="margin: 10px auto;">Правообладателем этого фото является <a href="https://www.tassphoto.com/ru/">ТАСС</a>. Использование фото возможно только с разрешения правообладателя.</div>
"""


def _gaz():
    g = waralbum.Gazetteer()
    g.add("Москва", 55.7558, 37.6173, "city_population")
    g.add("Сталинград", 48.708, 44.514, "occupation_cities")
    g.add("Ржев", 56.263, 34.329, "settlements", "Россия")
    g.add("Берлин", 54.006, 61.193, "settlements", "Россия")       # село на Урале
    g.add("Калинин", 56.858, 35.900, "settlements", "Россия")
    g.add("Калинин", 47.246, 39.505, "settlements", "Россия")
    return g


def test_waralbum_fragment():
    page = "<html>…<div class='post'>" + FRAGMENT.format(place="Москва", time="20.06.1945") + \
        "<!-- похожие фото --><div>много ссылок</div>"
    frag = waralbum.fragment(page)
    assert frag.startswith('<h1 class="title"') and "много ссылок" not in frag
    photo = waralbum.parse_fragment(173, frag)
    assert photo.title == "Встреча Знамени Победы на аэродроме в Москве"
    assert photo.place == "Москва" and photo.time == "20.06.1945"
    assert photo.author == "Дмитрий Чернов"
    assert photo.source == "pobeda.tassphoto.com"
    assert photo.categories == ["После Победы"]
    assert photo.original.endswith("varennikov.jpg")
    assert photo.image == "https://waralbum.ru/photocache/17/3/173-files/173-main.jpg"
    assert photo.rights.startswith("Правообладателем этого фото является ТАСС")
    assert "&#8212;" not in photo.caption and "—" in photo.caption


def test_waralbum_place_keys_and_locate():
    assert waralbum.place_keys("район Сталинграда")[:2] == ["сталинграда", "сталинград"]
    assert "ржев" in waralbum.place_keys("под Ржевом")
    g = _gaz()
    assert g.locate("район Сталинграда").name == "Сталинград"
    assert g.locate("Москва, СССР").lat == 55.7558
    assert g.locate("под Ржевом, Калининская область, СССР").name == "Ржев"
    # Тёзки далеко друг от друга — точки нет.
    assert g.locate("Калинин") is None
    # Берлин без страны и «Берлин, Германия» не уходят на Урал.
    assert g.locate("Берлин") is None and g.locate("Берлин, Германия") is None
    assert g.locate("Латвия, СССР") is None
    assert waralbum.country_of("Барроу-ин-Фернесс, графство Камбрия, Великобритания") == "великобритания"


def test_waralbum_records():
    photos = [waralbum.parse_fragment(i, FRAGMENT.format(place=p, time=t)) for i, p, t in (
        (1, "Москва", "20.06.1945"),
        (2, "Берлин, Германия", "май 1945"),
        (3, "Барроу-ин-Фернесс, графство Камбрия, Великобритания", "1943"),
        (4, "Ленинградский фронт", "1942"),
        (5, "Москва", ""),
    )]
    recs, skipped = waralbum.records(photos, _gaz())
    by_id = {r.source_id: r for r in recs}
    assert skipped == {"без года": 1}
    assert by_id["1"].confidence == "place_level" and by_id["1"].date_precision == "day"
    assert by_id["1"].extra["coord_source"] == "city_population: «Москва»"
    assert by_id["2"].confidence == "outside_bbox" and by_id["2"].lat is None
    assert by_id["3"].confidence == "outside_bbox" and "frame_by" in by_id["3"].extra
    assert by_id["4"].confidence == "no_coords" and by_id["4"].place_text == "Ленинградский фронт"
    assert by_id["1"].url == "https://waralbum.ru/1/" and by_id["1"].actor == "Дмитрий Чернов"
