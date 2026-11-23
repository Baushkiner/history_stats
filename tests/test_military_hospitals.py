"""Справочник дислокации госпиталей РККА 1941–1945 годов (soldat.ru).

Сети в тестах нет. Выдача сайта собирается здесь же, в той же вёрстке (блок
записи, счётчик «Запросу соответствует», форма `frm` со скрытыми полями для
следующих страниц), а обход дерева проверяется на маленьком поддельном
справочнике: тот же поиск по образцу с `*`, без регистра, с обрезкой выдачи —
только порог не 500, а пять записей.

Проверяется то, на чём слой держится: разбор записи и дат, обход с дроблением
по району, типу и месту, сверка по типам (записи без района), сводка по номеру
записи, район военного времени — к нынешним единицам, привязка места только
в своём районе, сроки с открытым концом и пометкой «на ДД.ММ.ГГ».
"""

import fnmatch
import re
import urllib.parse

import pytest

from histctx.registry import BY_SLUG, HARVESTED
from histctx.sources import military_hospitals as mh
from histctx.sources.military_hospitals import (
    F_PLACE, F_REGION, F_TYPE, MILITARY_HOSPITALS, Candidate, Crawler, HospitalsError, Raw,
    candidates_from_rows, check_tree, choose, fits, missing_pids, parse_date, parse_edit,
    parse_page, place_names, query_variants, record, region_hint, snapshot, span, title,
)


# --- поддельная выдача сайта -----------------------------------------------------

def block(r: Raw) -> str:
    stay = ""
    if r.start_raw or r.end_raw:
        parts = []
        if r.start_raw:
            parts.append(f"с <b>{r.start_raw}</b>")
        if r.end_raw:
            parts.append(f"по <b>{r.end_raw}</b>")
        stay = ('<tr align="center"><td valign=top colspan="2">Лечебное учреждение '
                f'находилось в этом районе\n {" ".join(parts)} </td></tr>')
    note = (f"<tr><td align=right valign=top>Дополнительная информация:&nbsp;</td>"
            f"<td><b>\n {r.note} </b></td></tr>" if r.note else "")
    return (
        "<table width=100% align=center cellpadding=2 cellspacing=0 border=0 bgcolor=#660000>"
        "<tr><td>\n<table width=100% border=0 cellpadding=2 cellspacing=0 bgcolor=#eeeeee>"
        "<tr><td colspan=2 bgcolor=#660000 align=center><font color=white><b>Номер\n"
        f" лечебного учреждения: {r.number} </b></font></td></tr>"
        "<tr><td width=40% align=right valign=top>Тип лечебного учреждения:&nbsp;</td>"
        f"<td><b>\n {r.kind} </b></td></tr>"
        "<tr><td width=40% align=right valign=top>Место дислокации:&nbsp;</td>"
        f"<td><b>\n {r.place} </b></td></tr>"
        "<tr><td align=right valign=top>Район дислокации:&nbsp;</td>"
        f"<td><b>\n {r.region} </b></td></tr>{stay}{note}"
        f"<tr><td colspan=2 align=right><form name=editform{r.pid} action=hospital_edit.html "
        f"method=post><input type=hidden name=pid value={r.pid}></form></td></tr>"
        "</table></td></tr></table><br>"
    )


def results_page(recs, count, page, pages, hidden) -> bytes:
    head = "<h1>Справочник дислокации госпиталей РККА в 1941-1945 годах. </h1>"
    if not count:
        body = head + "Запросу соответствует 0 записей Данных, соответствующих запросу, не найдено"
        return body.encode("cp1251")
    inputs = "".join(f"<input type=hidden name={k} value='{v}'>" for k, v in hidden.items())
    form = (f"<form name=frm action=/hospital.html method=post>{inputs}"
            f"<td align=left>Страница: {page + 1} / {pages} </td></form>")
    body = (head + f"<p align=right>Запросу соответствует <b>{count} записей</b></p>"
            + "".join(block(r) for r in recs) + form)
    return body.encode("cp1251")


def like(value: str, pattern: str) -> bool:
    if not pattern:
        return True
    pat = pattern.replace("?", "_")
    return fnmatch.fnmatchcase(mh.fold(value), mh.fold(pat).replace("_", "?"))


class FakeSite:
    """Поиск по образцу, как на сайте: `*` и `?`, без регистра, обрезка выдачи."""

    def __init__(self, recs, cap, page_size):
        self.recs = recs
        self.cap = cap
        self.page_size = page_size
        self.calls = 0

    def __call__(self, url, fields, **_):
        self.calls += 1
        if "hospital_edit" in url:
            pid = int(fields["pid"])
            r = next((x for x in self.recs if x.pid == pid), None)
            if not r:
                return b"<html>no record</html>"
            return (f"<INPUT name=fields[number] value='{r.number}'>"
                    f"<INPUT name=fields[type] value='{r.kind}'>"
                    f"<INPUT name=fields[point] value='{r.place}'>"
                    f"<INPUT name=fields[obl] value='{r.region}'>"
                    f"<input name=fields[vdate1] value='{r.start_raw or '00.00.0000'}'>"
                    f"<input name=fields[vdate2] value='{r.end_raw or '00.00.0000'}'>"
                    ).encode("cp1251")
        page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("page", [0])[0])
        hits = [r for r in self.recs
                if like(r.region, fields.get(F_REGION, ""))
                and like(r.kind, fields.get(F_TYPE, ""))
                and like(r.place, fields.get(F_PLACE, ""))]
        hits.sort(key=lambda r: (r.number, r.pid))
        hits = hits[:self.cap]
        pages = (len(hits) + self.page_size - 1) // self.page_size
        chunk = hits[page * self.page_size:(page + 1) * self.page_size]
        return results_page(chunk, len(hits), page, pages, dict(fields))


def raw(pid, kind="Эвакуационный госпиталь", place="Вологда", region="Вологодская область",
        number="", start=None, end=None, note=None):
    return Raw(pid=pid, number=number, kind=kind, place=place, region=region,
               start=parse_date(start)[0], end=parse_date(end)[0],
               start_raw=start, end_raw=end, note=note)


# --- разбор ---------------------------------------------------------------------

def test_layer_is_registered_as_harvested():
    assert BY_SLUG["military_hospitals"] is MILITARY_HOSPITALS
    assert MILITARY_HOSPITALS in HARVESTED
    assert "активную ссылку" in MILITARY_HOSPITALS.license
    assert MILITARY_HOSPITALS.group == "military"


def test_parse_page_reads_records_counter_and_hidden_fields():
    recs = [raw(7782, kind="Госпиталь для инвалидов Отечественной войны",
                note="в справочнике так: областной госпиталь для иов 1945 г."),
            raw(38426, number="1016", place="Свердловск", region="Свердловская область",
                start="01.07.1941", end="00.04.1945")]
    page = parse_page(results_page(recs, 147, 0, 8, {F_REGION: "Вологодская*",
                                                     "fields[number]": "0"}))
    assert page.count == 147 and page.pages == 8 and not page.capped
    assert page.hidden == {F_REGION: "Вологодская*", "fields[number]": "0"}
    first, second = page.records
    assert (first.pid, first.number, first.place) == (7782, "", "Вологда")
    assert first.note.startswith("в справочнике так")
    assert (second.number, second.start, second.end) == ("1016", "1941-07-01", "1945-04-01")
    assert second.end_raw == "00.04.1945"


def test_parse_page_without_results_and_foreign_page():
    assert parse_page(results_page([], 0, 0, 0, {})).count == 0
    with pytest.raises(HospitalsError):
        parse_page("<html>что-то другое</html>".encode("cp1251"))


def test_parse_date_precision():
    assert parse_date("01.07.1941") == ("1941-07-01", "day")
    assert parse_date("00.07.1941") == ("1941-07-01", "month")
    assert parse_date("00.00.1942") == ("1942-01-01", "year")
    assert parse_date("00.00.0000") == (None, "")
    assert parse_date("31.02.1943") == ("1943-02-01", "month")


def test_parse_edit_form():
    site = FakeSite([raw(5, number="12", start="01.01.1942")], cap=5, page_size=2)
    rec = parse_edit(site("https://www.soldat.ru/hospital_edit.html", {"pid": "5"}), 5)
    assert (rec.pid, rec.number, rec.start) == (5, "12", "1942-01-01")
    assert parse_edit(site("https://www.soldat.ru/hospital_edit.html", {"pid": "6"}), 6) is None


# --- обход ----------------------------------------------------------------------

@pytest.fixture
def site(monkeypatch):
    recs = []
    pid = 1
    # Вологодская область: больше порога — дробится по типу и месту, а место
    # на «В» — по второй букве («Ве…», «Во…»).
    for i in range(4):
        recs.append(raw(pid, place="Вологда", number=str(100 + i)))
        pid += 1
    for i in range(3):
        recs.append(raw(pid, place="Великий Устюг", number=str(200 + i)))
        pid += 1
    for i in range(3):
        recs.append(raw(pid, kind="Батальон выздоравливающих", place="Вытегра",
                        number=str(i + 1)))
        pid += 1
    # Свердловская — меньше порога: лист.
    for i in range(2):
        recs.append(raw(pid, place="Ирбит", region="Свердловская область", number=str(i)))
        pid += 1
    # Район не указан — находит только сверка по типам.
    recs.append(raw(pid, place="Кузино", region="", number="77"))
    pid += 1
    # Новый тип, которого нет в начальном перечне.
    recs.append(raw(pid, kind="Войсковой лазарет", place="Вологда", number="5"))
    fake = FakeSite(recs, cap=5, page_size=2)
    monkeypatch.setattr(mh, "post", fake)
    monkeypatch.setattr(mh, "CAP", 5)
    monkeypatch.setattr(mh, "KNOWN_KINDS", ("Эвакуационный госпиталь",
                                            "Батальон выздоравливающих"))
    return fake


def test_crawl_finds_every_record_and_tree_checks_out(site, tmp_path):
    crawler = Crawler(tmp_path, pause=0, log=lambda s: None)
    crawler.kinds = set(mh.KNOWN_KINDS)
    trees = crawler.crawl()
    assert sorted(crawler.records) == [r.pid for r in site.recs]
    assert "Войсковой лазарет" in crawler.kinds
    for tree in trees.values():
        assert check_tree(tree) == []
    assert (tmp_path / "records.json").exists() and (tmp_path / "tree.json").exists()
    assert sorted(r.pid for r in mh.load_records(tmp_path)) == [r.pid for r in site.recs]


def test_crawl_repeats_from_cache_without_network(site, tmp_path):
    Crawler(tmp_path, pause=0, log=lambda s: None).crawl()
    calls = site.calls
    again = Crawler(tmp_path, pause=0, log=lambda s: None, offline=True)
    again.crawl()
    assert site.calls == calls and again.requests == 0
    assert len(again.records) == len(site.recs)


def test_interrupted_crawl_is_built_from_cached_pages(site, tmp_path):
    """Прерванный обход: сводки нет, а страницы в кэше — записи берутся с них."""
    Crawler(tmp_path, pause=0, log=lambda s: None).crawl()
    (tmp_path / "records.json").unlink()
    assert sorted(r.pid for r in mh.load_records(tmp_path)) == [r.pid for r in site.recs]
    with pytest.raises(HospitalsError):
        mh.load_records(tmp_path / "нет такого")


def test_check_tree_reports_mismatch():
    node = mh.Node(fields={F_REGION: "А*"}, count=3, got=2)
    assert check_tree(node) == ["{'fields[hospobl.name]': 'А*'}: счётчик 3, найдено 2"]
    assert check_tree(mh.Node(fields={F_REGION: "А*"}, count=5, got=2, capped=True)) == []


def test_missing_pids():
    assert missing_pids([5, 2, 3, 7]) == [4, 6]
    assert missing_pids([]) == []


# --- район и место ----------------------------------------------------------------

def test_region_hint_maps_wartime_regions():
    assert region_hint("Молотовская область").units == ("Пермский край", "Пермская область")
    assert region_hint("Вологодская область").stem == "вологодск"
    h = region_hint("БССР, Гомельская область")
    assert h.countries == ("Белоруссия", "Польша") and h.stem == "гомельск"
    assert region_hint("Грузинская ССР").countries == ("Грузия", "Абхазия")
    assert region_hint("Китай, Маньчжурия").countries == ("Китай",)
    assert region_hint("Восточная Пруссия (Польша)").countries == ("Россия", "Польша", "Литва")
    assert not region_hint("").known
    assert "Астраханская область" in region_hint("Сталинградская область").wider


def test_place_names():
    assert place_names("Мариуполь (Жданов)") == ["Мариуполь", "Жданов"]
    assert place_names("Даго, Остров (Кярдла)") == ["Даго", "Кярдла"]
    assert place_names("Ольга, Бухта") == ["Ольга"]
    assert place_names("Ленинград") == ["Ленинград", "Санкт-Петербург"]
    assert place_names("") == []


def test_query_variants_fix_case_and_yo():
    v = query_variants("Ростов-На-Дону")
    assert "Ростов-на-Дону" in v
    assert "Артёмовск" in query_variants("Артемовск")
    assert "Франкфурт-на-Одере" in query_variants("Франкфурт На Одере")
    v = query_variants("Ново-Хоперск")
    assert "Новохоперск" in v and "Новохопёрск" in v


def test_german_names_of_1945_get_todays_names():
    assert place_names("Ландсберг")[:2] == ["Ландсберг", "Гожув-Велькопольский"]
    assert "Черняховск" in place_names("Инстербург")
    assert "Словакия" in region_hint("Венгрия").countries
    assert "Молдавия" in region_hint("Румыния").countries


def cand(ident, title, lat, lon, *, country="Россия", types=("город",), anc=(), pop=0):
    return Candidate("wikidata", ident, title, lat, lon, country, pop, set(types), set(anc))


def test_fits_checks_country_and_region():
    vologda = cand("Q1", "Вологда", 59.2, 39.9, anc={"Вологодская область", "Россия"})
    assert fits(vologda, region_hint("Вологодская область"))
    assert not fits(vologda, region_hint("Свердловская область"))
    perm = cand("Q2", "Пермь", 58.0, 56.2, anc={"Пермский край"})
    assert fits(perm, region_hint("Молотовская область"))
    spb = cand("Q656", "Санкт-Петербург", 59.9, 30.3, anc={"Северо-Западный федеральный округ"})
    assert fits(spb, region_hint("Ленинградская область"))
    berlin = cand("Q64", "Берлин", 52.5, 13.4, country="Германия")
    assert fits(berlin, region_hint("Германия"))
    assert not fits(berlin, region_hint(""))          # без района — только СССР
    karelia = cand("Q3", "Петрозаводск", 61.8, 34.3, anc={"Республика Карелия"})
    assert fits(karelia, region_hint("Карело-Финская ССР"))


def test_choose_prefers_named_region_and_marks_namesakes():
    wd = {"михайловка": [
        cand("Q10", "Михайловка", 52.9, 32.0, types=("село",), anc={"Брянская область"}, pop=900),
        cand("Q11", "Михайловка", 53.5, 33.0, types=("деревня",), anc={"Брянская область"},
             pop=20),
        cand("Q12", "Михайловка", 50.0, 44.0, anc={"Волгоградская область"}, pop=50000),
    ]}
    found = choose(["Михайловка"], region_hint("Брянская область"), wd, {})
    assert found.candidate.ident == "Q10" and "тёзки" in found.how
    # Без района один город среди сёл — однозначен, два города — нет.
    assert choose(["Михайловка"], region_hint(""), wd, {}).candidate.ident == "Q12"
    wd["михайловка"].append(cand("Q14", "Михайловка", 47.0, 40.0, anc={"Ростовская область"}))
    assert choose(["Михайловка"], region_hint(""), wd, {}).candidate is None


def test_choose_falls_back_to_single_candidate_in_state():
    wd = {"астрахань": [cand("Q13", "Астрахань", 46.35, 48.04, anc={"Астраханская область"},
                             pop=470000)]}
    found = choose(["Астрахань"], region_hint("Тамбовская область"), wd, {})
    assert found.candidate.ident == "Q13" and "не в названной области" in found.how


def test_choose_uses_geonames_only_when_unique():
    gn = {"кузино": [Candidate("geonames", "500", "Кузино", 57.0, 59.4, "Россия", 2000)]}
    found = choose(["Кузино"], region_hint("Свердловская область"), {}, gn)
    assert found.candidate.ident == "500" and "область не проверена" in found.how
    assert choose(["Нигде"], region_hint(""), {}, gn).candidate is None


def test_candidates_from_rows_drop_non_places():
    rows = [
        {"name": {"value": "Ирбит"}, "item": {"value": "http://www.wikidata.org/entity/Q20"},
         "coord": {"value": "Point(63.06 57.67)"}, "country": {"value": "http://www.wikidata.org/entity/Q159"},
         "typeLabel": {"value": "город"}, "ancLabel": {"value": "Свердловская область"},
         "pop": {"value": "37000"}},
        {"name": {"value": "Ирбит"}, "item": {"value": "http://www.wikidata.org/entity/Q21"},
         "coord": {"value": "Point(63 57)"}, "country": {"value": "http://www.wikidata.org/entity/Q159"},
         "typeLabel": {"value": "река"}},
    ]
    out = candidates_from_rows(rows)
    assert [c.ident for c in out["ирбит"]] == ["Q20"]
    c = out["ирбит"][0]
    assert c.country == "Россия" and c.population == 37000 and c.is_town


# --- сроки и записи ---------------------------------------------------------------

def test_span_full_open_era_and_snapshot():
    s = span(raw(1, start="01.07.1941", end="01.04.1945"))
    assert (s.year_from, s.year_to, s.precision) == (1941, 1945, "day")
    s = span(raw(2, end="07.08.1943"))
    assert (s.year_from, s.year_to, s.precision) == (1941, 1943, "open")
    s = span(raw(3, start="01.12.1945"))
    assert (s.year_from, s.year_to, s.precision) == (1945, 1945, "open")
    s = span(raw(4))
    assert (s.year_from, s.year_to, s.precision) == (1941, 1945, "era")
    s = span(raw(5, end="07.08.1943", note="в справочнике так: бл онежской вф на 07.08.43"))
    assert (s.year_from, s.year_to, s.precision, s.snapshot) == (1943, 1943, "day", "1943-08-07")
    assert s.text == "на 7 августа 1943"


def test_snapshot_month_and_absent():
    assert snapshot("в справочнике так: на 00.07.44") == (snapshot("на 01.07.44")[0], "month")
    assert snapshot("1 формирование") == (None, "")


def test_title_and_record():
    r = raw(38426, number="3870", place="Свердловск", region="Свердловская область",
            start="01.07.1941", end="01.04.1945", note="2 формирование")
    assert title(r) == "Эвакогоспиталь № 3870 — Свердловск"
    assert title(raw(1, kind="Хирургический полевой подвижной госпиталь", number="Б/Н",
                     place="Мариуполь (Жданов)")) == "ХППГ — Мариуполь"
    place = mh.Placement(cand("Q5", "Екатеринбург", 56.84, 60.6), "Викиданные, «Екатеринбург»")
    rec = record(r, place)
    assert rec.confidence == "place_level" and rec.url == mh.SEARCH_URL
    assert rec.source_id == "soldat-hospital:38426"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1941, 1945, "day")
    assert rec.extra["formation"] == 2 and rec.extra["region_wartime"] == "Свердловская область"
    assert rec.summary.startswith("Эвакуационный госпиталь № 3870: Свердловск")
    lost = record(raw(2, place="Нигде"), mh.Placement(None, "не сведено: Нигде"))
    assert lost.confidence == "no_coords" and not lost.has_point


def test_encode_form_is_cp1251():
    body = mh.encode_form({F_REGION: "Вологодская*"})
    assert re.fullmatch(r"fields%5Bhospobl\.name%5D=[%0-9A-F]+", body.decode())
    assert urllib.parse.unquote_to_bytes(body.decode().split("=")[1]).decode("cp1251") \
        == "Вологодская*"
