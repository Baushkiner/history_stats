"""Разбор слоя сожжённых деревень: набор Жукова (Harvard Dataverse) и карточки НАРБ.

Сети в тестах нет. Строки главной таблицы сняты с `BELARUS_VILLAGES_Full.tab`
как есть, вместе с кавычками ингеста, и урезаны до нужных колонок: Хатынь,
Абакумы, две «Абразеево» в точке Освеи, пара «Байдино» одного района в
одной точке, Заболотье с задвоенными месячными строками, «Льнозавод "КИМ"»
с экранированной кавычкой и Дубровка без потерь. Помесячные строки собраны
так же, как их испортил ингест: UTF-8 прочитан как latin-1. Карточка НАРБ —
блок «Информация о деревне» карточки «Образеево» без медиафайлов.
"""

import io
import json
import urllib.error

import pytest

from histctx.schema import SCOPE_POINT, SCOPE_REGION
from histctx.net import USER_AGENT
from histctx.sources.burned_villages import (
    BURNED_VILLAGES, CATEGORY_BURNED, CATEGORY_NARB_EMPTY, CATEGORY_NARB_ONLY, CATEGORY_NONE,
    CONFIDENCE_SHARED,
    DATASET_URL, FILES, HOW_EXACT, HOW_RAYON_NUMBERS, LICENSE_NARB, LICENSE_ZHUKOV,
    NARB_USER_AGENT, WORK, BurnedVillagesError, CardCache, MonthScan, NarbClient,
    build_records, card_record, card_urls, check_card, check_manifest, check_scan,
    match_cards, months_text, name_key, parse_card, parse_narb_date, parse_narb_dates,
    point_mates,
    rayon_key, rayons_close, repair_mojibake, scan_months, spread_sample, tab_rows, village_name,
    village_sitemaps,
)

VILLAGES_TAB = (
    "VID\tVIL_ID\tVILLAGE\tOBLAST_PREWAR\tRAYON_PREWAR\tLONG\tLAT\tRAYON_ID\tOBLAST\tRAYON"
    "\tHOUSES_PRE\tPEOPLE_PRE\tHOUSES_DESTROYED\tPEOPLE_KILLED\tREPRISAL\n"
    '1\t"6667"\t"Абакумы"\t"Гомельская"\t"Лоевский"\t30.856007\t51.983011\t115\t"Гомельская"'
    '\t"Лоевский"\t5752.0\t16222.0\t71.0\t2.0\t1.0\n'
    '2\t"482"\t"Абразеево"\t"Витебская"\t"Дриссенский"\t28.1391331\t55.8878082\t99\t"Витебская"'
    '\t"Освейский"\t5256.0\t24395.0\t13.0\t51.0\t1.0\n'
    '3\t"582"\t"Абразеево"\t"Витебская"\t"Верхнедвинский"\t28.1391331\t55.8878082\t99'
    '\t"Витебская"\t"Освейский"\t5256.0\t24395.0\t16.0\t7.0\t1.0\n'
    '192\t"200"\t"Байдино"\t"Витебская"\t"Россонский"\t29.082499\t55.841412\t101\t"Витебская"'
    '\t"Россонский"\t6555.0\t27868.0\t0.0\t21.0\t1.0\n'
    '193\t"241"\t"Байдино"\t"Витебская"\t"Россонский"\t29.082499\t55.841412\t101\t"Витебская"'
    '\t"Россонский"\t6555.0\t27868.0\t12.0\t35.0\t1.0\n'
    '1980\t"2776"\t"Дубровка"\t"Минская"\t"Холопеничский"\t29.091428\t54.525337\t142\t"Минская"'
    '\t"Холопеничский"\t2058.0\t9346.0\t0.0\t0.0\t0.0\n'
    '2217\t"4962"\t"Заболотье"\t"Могилевская"\t"Могилевский"\t31.382402\t53.864803\t158'
    '\t"Могилевская"\t"Мстиславльский"\t6179.0\t24973.0\t56.0\t18.0\t2.0\n'
    '3987\t"1339"\t"Льнозавод \\"\\"КИМ\\"\\""\t"Витебская"\t"Шумилинский"\t29.90991\t55.677687'
    '\t97\t"Витебская"\t"Меховский"\t8046.0\t33660.0\t30.0\t0.0\t1.0\n'
    '7351\t"4231"\t"Хатынь"\t"Минская"\t"Логойский"\t27.9452909\t54.3344874\t134\t"Минская"'
    '\t"Плещеничский"\t1468.0\t6336.0\t26.0\t149.0\t1.0\n'
)


def _villages() -> list[dict]:
    return list(tab_rows(io.StringIO(VILLAGES_TAB)))


def _broken(text: str) -> str:
    """Название так, как его записал ингест: байты UTF-8, прочитанные как latin-1."""
    return text.encode("utf-8").decode("latin-1")


MONTH_EVENTS = {
    # VID: [(YRMO, дворы, погибшие, акции)]
    "1": [(194310, 71, 2, 1)],
    "2": [(194302, 13, 51, 1)],
    "3": [(194302, 16, 7, 1)],
    "192": [(194208, 0, 21, 1)],
    "193": [(194208, 12, 35, 1)],
    "2217": [(194401, 19, 6, 1), (194401, 37, 12, 1)],
    "3987": [(194306, 30, 0, 1)],
    "7351": [(194303, 26, 149, 1)],
}
NAMES = {row["VID"]: row["VILLAGE"] for row in _villages()}


def _months_lines() -> list[str]:
    """Помесячный файл в миниатюре: по строке на месяц-деревню, повтор у Заболотья."""
    header = "VID\tYRMO\tYEAR\tMONTH\tVILLAGE\tHOUSES_DESTROYED\tPEOPLE_KILLED\tREPRISAL\tVIL_ID"
    lines = [header + "\n"]
    for vid in NAMES:
        events = {e[0]: e for e in MONTH_EVENTS.get(vid, [])}
        for yrmo in (194106, 194208, 194302, 194303, 194306, 194310, 194401, 194505):
            name = _broken(village_name(NAMES[vid]))
            rows = [e for e in MONTH_EVENTS.get(vid, []) if e[0] == yrmo] or [(yrmo, 0, 0, 0)]
            if yrmo not in events:
                rows = [(yrmo, 0, 0, 0)]
            for _, h, p, r in rows:
                line = f'{vid}\t{yrmo}\t{yrmo // 100}\t{yrmo % 100}\t"{name}"\t{h}\t{p}\t{r}\t"x"\n'
                lines.append(line)
                if vid == "2217" and yrmo == 194401:
                    lines.append(line)   # строки января 1944 года задвоены, как в наборе
    return lines


CARD_HTML = """<html><body><section class="village-page"><div class="page__content">
<h2>Образеево</h2>
<div id="village-19189" class="village-page__info village-page__template">
<h3>Информация о деревне</h3>
<div class="village-page__table">
<div class="village-page__table-horiz"><strong>Область</strong><p>Витебская</p></div>
<div class="village-page__table-horiz"><strong>Довоенная область</strong><p>Витебская</p></div>
<div class="village-page__table-horiz"><strong>Район</strong><p>Верхнедвинский</p></div>
<div class="village-page__table-horiz"><strong>Довоенный район</strong><p>Дриссенский</p></div>
<div class="village-page__table-horiz"><strong>Год разрушения</strong><p>1943</p></div>
<div class="village-page__table-horiz"><strong>Дата разрушения</strong><p>февраль 1943 г.</p></div>
<div class="village-page__table-horiz"><strong>Домов до войны</strong><p>13</p></div>
<div class="village-page__table-horiz"><strong>Разрушено домов</strong><p>13</p></div>
<div class="village-page__table-horiz"><strong>Людей до войны</strong><p>53</p></div>
<div class="village-page__table-horiz"><strong>Убито людей</strong><p>51</p></div>
<div class="village-page__table-vert">
<strong class="village-page__table-vert-all">Поисковые данные</strong>
<p class="village-page__table-all">НАРБ. Ф.1403. Оп.1. Д.174. Л.14.</p></div>
<div class="village-page__table-vert">
<strong class="village-page__table-vert-all">Судьба деревни</strong>
<p class="village-page__table-all">не восстановлена</p></div>
<div class="village-page__table-vert">
<strong class="village-page__table-vert-all">Заметки</strong>
<p class="village-page__table-all">Сарьянский с/с</p></div>
</div>
<div class="village-page__media village-page__template">
<strong class="village-page__table-vert-all">Фотографии</strong>
<p>NARB_LA_1403_1_174_014.jpg</p>
</div></div></section></body></html>"""
CARD_URL = "https://db.narb.by/village/obrazeevo/"


def _card(**changes) -> dict:
    card = parse_card(CARD_HTML, CARD_URL)
    card.update(changes)
    return card


# --- главная таблица и помесячный файл --------------------------------------

def test_layer_card_states_rights_of_both_sources():
    assert BURNED_VILLAGES.slug == "burned_villages_by"
    assert BURNED_VILLAGES.group == "military"
    assert "CC0" in BURNED_VILLAGES.license
    assert "права не выяснены" in BURNED_VILLAGES.license
    assert BURNED_VILLAGES.url == DATASET_URL


def test_quoted_names_are_unescaped():
    rows = {r["VID"]: r for r in _villages()}
    assert village_name(rows["3987"]["VILLAGE"]) == 'Льнозавод "КИМ"'
    raw = list(tab_rows(io.StringIO(
        'VID\tVILLAGE\n7029\t"Тимоново (центр с-за \\"\\"Тимоново\\"\\")"\n')))
    assert village_name(raw[0]["VILLAGE"]) == 'Тимоново (центр с-за "Тимоново")'
    assert village_name(rows["7351"]["VILLAGE"]) == "Хатынь"


def test_mojibake_is_repaired_and_clean_text_is_left_alone():
    assert repair_mojibake(_broken("Абакумы")) == "Абакумы"
    assert repair_mojibake("Абакумы") == "Абакумы"
    assert repair_mojibake(_broken("Гомельская")) == "Гомельская"


def test_month_scan_keeps_only_active_months_and_collapses_duplicates():
    scan = scan_months(_months_lines())
    assert scan.rows == len(_months_lines()) - 1
    assert scan.yrmo_min == 194106 and scan.yrmo_max == 194505
    assert scan.months["7351"] == [(194303, 26, 149, 1)]
    assert "1980" not in scan.months                     # Дубровка: нулей не хранить
    assert scan.months["2217"] == [(194401, 19, 6, 1), (194401, 37, 12, 1)]
    assert scan.duplicates == 2 and scan.duplicate_vids == ["2217"]
    assert scan.names["7351"] == "Хатынь"


def test_month_scan_agrees_with_totals():
    villages = _villages()
    scan = scan_months(_months_lines())
    assert check_scan(scan, villages) == []
    # Без схлопывания повторов сумма Заболотья была бы вдвое больше итога.
    scan.months["2217"] = scan.months["2217"] * 2
    problems = check_scan(scan, villages)
    assert len(problems) == 1 and "VID 2217" in problems[0]


def test_month_scan_roundtrips_through_cache_json():
    scan = scan_months(_months_lines())
    again = MonthScan.from_json(json.loads(json.dumps(scan.to_json())))
    assert again.months == scan.months
    assert again.duplicates == scan.duplicates


def test_month_scan_stops_on_missing_columns():
    with pytest.raises(BurnedVillagesError, match="REPRISAL"):
        scan_months(["VID\tYRMO\tVILLAGE\tHOUSES_DESTROYED\tPEOPLE_KILLED\n"])


def test_manifest_check():
    good = [{"id": f.file_id, "name": f.name, "size": f.size} for f in FILES]
    assert check_manifest(good) == []
    bad = [dict(good[0], size=1), good[1]]
    assert any("размер" in p for p in check_manifest(bad))
    assert any("нет" in p for p in check_manifest(good[:1]))


# --- координата --------------------------------------------------------------

def test_point_is_kept_only_when_no_other_village_shares_it():
    mates = point_mates(_villages())
    assert mates["7351"] == 0                    # Хатынь — своя точка
    assert mates["2"] == 1 and mates["3"] == 1   # «Абразеево» двух районов в одной точке
    assert mates["192"] == 0 and mates["193"] == 0   # одно Байдино одного района дважды


def test_rayon_key_absorbs_spelling():
    assert rayons_close("Дубровенский", "Дубровненский")
    assert not rayons_close("Россонский", "Сиротинский")
    assert rayon_key("Логойский р-н") == rayon_key("Логойский")
    assert not rayons_close("Дриссенский", "Освейский")
    assert name_key("Абразеёво ") == "абразеево"


# --- записи набора -----------------------------------------------------------

def _records(cards=()):
    villages = _villages()
    records, stats = build_records(villages, scan_months(_months_lines()), cards)
    return {r.source_id: r for r in records}, records, stats


def test_khatyn_is_a_point_with_month_and_numbers():
    by_id, _, _ = _records()
    rec = by_id["4231"]
    assert rec.scope == SCOPE_POINT and rec.confidence == "ok"
    assert (rec.lat, rec.lon) == (54.3344874, 27.9452909)
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1943, 1943, "month")
    assert rec.title == "Хатынь, Логойский район: март 1943 — сожжено дворов: 26"
    assert "погибших: 149" in rec.summary
    assert rec.category == CATEGORY_BURNED
    assert rec.region == "Минская область" and rec.district == "Логойский район"
    assert rec.work == WORK
    assert rec.url == DATASET_URL and rec.license == LICENSE_ZHUKOV
    assert rec.extra["months"] == [["1943-03", 26, 149, 1]]
    assert rec.extra["zhukov"] == {"VID": "7351", "VIL_ID": "4231", "OBLAST": "Минская",
                                   "RAYON": "Плещеничский"}


def test_shared_point_goes_without_coordinates_but_stays():
    by_id, _, _ = _records()
    rec = by_id["482"]
    assert rec.lat is None and rec.lon is None
    assert rec.scope == SCOPE_REGION and rec.regions == ["Витебская область"]
    assert rec.confidence == CONFIDENCE_SHARED
    assert rec.extra["zhukov"]["LAT"] == "55.8878082"
    assert rec.extra["point_mates"] == 1
    assert "не место деревни" in rec.summary
    assert rec.usable


def test_village_without_losses_keeps_the_occupation_years():
    by_id, _, _ = _records()
    rec = by_id["2776"]
    assert rec.category == CATEGORY_NONE
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1941, 1944, "year")


def test_no_rayon_level_denominators_in_record():
    """HOUSES_PRE и PEOPLE_PRE — величины района, а не деревни."""
    by_id, _, _ = _records()
    for rec in by_id.values():
        assert "HOUSES_PRE" not in rec.extra.get("zhukov", {})
        assert "5752" not in rec.summary


def test_months_text_long_series():
    months = [(194200 + m, 1, 0, 1) for m in range(1, 13)]
    assert months_text(months) == "с января 1942 по декабрь 1942, 12 месяцев с акциями"
    assert months_text([(194206, 1, 0, 1), (194303, 0, 2, 1)]) == "июнь 1942; март 1943"


# --- карточки НАРБ -----------------------------------------------------------

def test_card_is_parsed_without_media():
    card = parse_card(CARD_HTML, CARD_URL)
    assert card["name"] == "Образеево" and card["post_id"] == 19189
    assert card["rayon_prewar"] == "Дриссенский" and card["rayon"] == "Верхнедвинский"
    assert card["date"] == "февраль 1943 г."
    assert card["houses_pre"] == "13" and card["people_killed"] == "51"
    assert card["sources"] == "НАРБ. Ф.1403. Оп.1. Д.174. Л.14."
    assert card["fate"] == "не восстановлена"
    assert "jpg" not in json.dumps(card, ensure_ascii=False)
    assert check_card(card) == []


def test_changed_card_layout_is_reported():
    card = parse_card(CARD_HTML.replace("Убито людей", "Погибло"), CARD_URL)
    problems = check_card(card)
    assert any("people_killed" in p for p in problems)
    assert any("Погибло" in p for p in problems)
    with pytest.raises(BurnedVillagesError):
        parse_card("<html></html>", CARD_URL)


def test_null_cell_is_empty():
    card = parse_card(CARD_HTML.replace("не восстановлена", "NULL"), CARD_URL)
    assert card["fate"] is None


@pytest.mark.parametrize("text,expected", [
    ("24 мая 1943 г.", (1943, 5, 24)),
    ("октябрь 1943 г.", (1943, 10, None)),
    ("мац 1944 г.", (1944, 5, None)),
    ("1942", (1942, None, None)),
    ("", None),
    ("весной", None),
])
def test_narb_dates(text, expected):
    assert parse_narb_date(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("1942 г., август 1943 г.", [(1942, None, None), (1943, 8, None)]),
    ("декабрь 1943 г., июнь 1944 г.", [(1943, 12, None), (1944, 6, None)]),
    ("февраль, май, сентябрь 1943 г.", [(1943, 2, None), (1943, 5, None), (1943, 9, None)]),
    ("5 марта 1943 г.", [(1943, 3, 5)]),
])
def test_narb_date_lists(text, expected):
    assert parse_narb_dates(text) == expected


def test_card_with_two_dates_spans_both_years():
    rec = card_record(_card(name="Х", date="декабрь 1943 г., июнь 1944 г.",
                            url="https://db.narb.by/village/x/"))
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1943, 1944, "month")


def test_one_of_several_card_months_agrees_with_the_set():
    khatyn = _card(name="Хатынь", rayon_prewar="Логойский", rayon="Логойский",
                   houses_destroyed="26", people_killed="149",
                   date="1942 г., март 1943 г.", url="https://db.narb.by/village/hatyn/")
    rec = _records([khatyn])[0]["4231"]
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1943, 1943, "month")
    assert rec.extra["dates_agree"] is True


def test_matching_by_name_rayon_and_numbers():
    villages = _villages()
    abrazeevo = _card(name="Абразеево", rayon_prewar="Освейский", houses_pre="16",
                      houses_destroyed="16", people_killed="7", people_pre="73",
                      url="https://db.narb.by/village/abrazeevo/")
    obrazeevo = _card()
    khatyn = _card(name="Хатынь", rayon_prewar="Логойский", rayon="Логойский",
                   oblast_prewar="Минская", houses_destroyed="26", people_killed="149",
                   date="22 марта 1943 г.", url="https://db.narb.by/village/hatyn/")
    stranger = _card(name="Попельники", rayon_prewar="Юратишковский", rayon="Ивьевский",
                     houses_destroyed=None, people_killed=None, date="май 1944 г.",
                     url="https://db.narb.by/village/popelniki/")
    matched, stats = match_cards(villages, [abrazeevo, obrazeevo, khatyn, stranger])
    # «Абразеево» базы — нынешний Верхнедвинский район, он же стоит у Жукова в VID 3.
    assert matched["3"][0]["url"].endswith("/abrazeevo/") and matched["3"][1] == HOW_EXACT
    # «Образеево» Дриссенского района — у Жукова «Абразеево», сводится районом и числами.
    assert matched["2"][0]["url"] == CARD_URL and matched["2"][1] == HOW_RAYON_NUMBERS
    assert matched["7351"][1] == HOW_EXACT
    assert stats["сведено"] == 3 and stats["без пары"] == 1


def test_ambiguous_card_is_not_matched():
    villages = _villages()
    # Две «Байдино» одного района; без чисел карточка не различает их.
    card = _card(name="Байдино", rayon_prewar="Россонский", rayon="Россонский",
                 houses_destroyed="5", people_killed="5")
    matched, stats = match_cards(villages, [card])
    assert matched == {} and stats["неоднозначно"] == 1


def test_matched_card_adds_day_date_and_card_link():
    khatyn = _card(name="Хатынь", rayon_prewar="Логойский", rayon="Логойский",
                   houses_pre="26", people_pre="156", houses_destroyed="26",
                   people_killed="149", date="22 марта 1943 г.", fate=None,
                   url="https://db.narb.by/village/hatyn/")
    by_id, _, _ = _records([khatyn])
    rec = by_id["4231"]
    assert rec.date_precision == "day" and (rec.year_from, rec.year_to) == (1943, 1943)
    assert "НАРБ: 22 марта 1943 г." in rec.period_raw
    assert rec.url == "https://db.narb.by/village/hatyn/"
    assert "до войны 26 дворов и 156 жителей" in rec.summary
    assert rec.extra["narb"]["houses_pre"] == "26"
    assert rec.extra["dates_agree"] is True
    assert "права не выяснены" in rec.license


def test_disagreeing_dates_widen_the_interval():
    khatyn = _card(name="Хатынь", rayon_prewar="Логойский", rayon="Логойский",
                   houses_destroyed="26", people_killed="149", date="май 1944 г.",
                   url="https://db.narb.by/village/hatyn/")
    rec = _records([khatyn])[0]["4231"]
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1943, 1944, "month")
    assert rec.extra["dates_agree"] is False


def test_unmatched_card_becomes_a_record_without_point():
    stranger = _card(name="Попельники", oblast_prewar="Барановичская",
                     rayon_prewar="Юратишковский", rayon="Ивьевский", houses_destroyed="40",
                     people_killed=None, date="май 1944 г.", sources=None, fate=None,
                     url="https://db.narb.by/village/popelniki/", post_id=777)
    _, records, _ = _records([stranger])
    rec = records[-1]
    assert rec.title == "Попельники, Юратишковский район: май 1944 г. — сожжено дворов: 40"
    assert rec.scope == SCOPE_REGION and rec.regions == ["Барановичская область"]
    assert (rec.year_from, rec.date_precision) == (1944, "month")
    assert rec.category == CATEGORY_NARB_ONLY
    assert rec.license == LICENSE_NARB and rec.url.endswith("/popelniki/")
    assert rec.source_id == "narb:777"
    assert card_record(stranger).uid == rec.uid


def test_sitemaps_give_only_card_addresses():
    index = ("<sitemapindex><sitemap><loc>https://db.narb.by/post-sitemap.xml</loc></sitemap>"
             "<sitemap><loc>https://db.narb.by/village-sitemap.xml</loc></sitemap>"
             "<sitemap><loc>https://db.narb.by/village-sitemap2.xml</loc></sitemap>"
             "<sitemap><loc>https://db.narb.by/old_region-sitemap.xml</loc></sitemap>"
             "</sitemapindex>")
    assert village_sitemaps(index) == ["https://db.narb.by/village-sitemap.xml",
                                       "https://db.narb.by/village-sitemap2.xml"]
    sitemap = ("<urlset><url><loc>https://db.narb.by/village/</loc></url>"
               "<url><loc>https://db.narb.by/village/abakumy/</loc></url>"
               "<url><loc>https://db.narb.by/village/budy-3/</loc></url></urlset>")
    assert card_urls(sitemap) == ["https://db.narb.by/village/abakumy/",
                                  "https://db.narb.by/village/budy-3/"]


def test_spread_sample_covers_the_whole_list():
    urls = [f"u{i}" for i in range(100)]
    picked = spread_sample(urls, 4)
    assert picked == ["u0", "u25", "u50", "u75"]
    assert spread_sample(urls[:3], 10) == urls[:3]


ROBOTS = """User-agent: *
Disallow: /wp-json/
Disallow: /search
Disallow: /page/
Disallow: /*?
"""


def _client(pages: dict, failures: int = 0) -> NarbClient:
    calls = {"n": 0}

    def opener(url, timeout):
        calls["n"] += 1
        if url.endswith("robots.txt"):
            return ROBOTS.encode()
        if calls["n"] <= failures + 1:
            raise ConnectionResetError("reset by peer")
        return pages[url].encode()

    return NarbClient(pause=0, retries=4, opener=opener)


def test_client_respects_robots_and_retries_resets():
    client = _client({CARD_URL: CARD_HTML}, failures=2)
    assert client.get(CARD_URL) == CARD_HTML
    assert client.resets == 2
    for closed in ("https://db.narb.by/wp-json/wp/v2/village",
                   "https://db.narb.by/search/?s=x", "https://db.narb.by/village/?p=1"):
        with pytest.raises(BurnedVillagesError, match="robots"):
            client.get(closed)


def test_client_does_not_retry_refusals():
    def opener(url, timeout):
        if url.endswith("robots.txt"):
            return ROBOTS.encode()
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    client = NarbClient(pause=0, retries=4, opener=opener)
    with pytest.raises(BurnedVillagesError, match="403"):
        client.get(CARD_URL)
    assert client.requests == 2   # robots.txt и одна попытка


def test_signature_names_the_project_without_the_filtered_word():
    # Сайт отказывает подписи сборщика — подпись под фильтр не подгоняется.
    assert NARB_USER_AGENT == USER_AGENT


def test_card_cache_appends_and_reloads(tmp_path):
    cache = CardCache(tmp_path / "cards.jsonl")
    cache.add(_card())
    again = CardCache(tmp_path / "cards.jsonl")
    assert CARD_URL in again and again.cards[CARD_URL]["name"] == "Образеево"


def test_card_without_numbers_or_date_keeps_the_occupation_years():
    bare = _card(name="Попельники", houses_destroyed=None, people_killed=None, date=None,
                 year=None, url="https://db.narb.by/village/popelniki/")
    rec = card_record(bare)
    assert rec.category == CATEGORY_NARB_EMPTY
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1941, 1944, "year")
    assert rec.title.endswith("дата не указана — потери не указаны")


def test_card_cache_skips_a_truncated_line(tmp_path):
    path = tmp_path / "cards.jsonl"
    path.write_text(json.dumps(_card(), ensure_ascii=False) + "\n{\"url\": \"https://db.n",
                    encoding="utf-8")
    assert list(CardCache(path).cards) == [CARD_URL]


def test_settlement_kind_is_dropped_from_the_name_key():
    assert name_key("Староселье, пос.") == name_key("Староселье")
    assert name_key("Антоново, хут.") == "антоново"


def test_card_goes_to_both_rows_of_a_duplicated_village():
    second = dict(_villages()[-1], VID="9999", VIL_ID="9998")   # Хатынь второй строкой
    villages = _villages() + [second]
    card = _card(name="Хатынь", rayon_prewar="Логойский", rayon="Логойский",
                 houses_destroyed="26", people_killed="149", url="https://db.narb.by/village/h/")
    matched, stats = match_cards(villages, [card])
    assert set(matched) == {"7351", "9999"}
    assert stats["сведено"] == 1 and stats["деревень с карточкой"] == 2
