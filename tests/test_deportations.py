"""Спецпоселенцы 1946 и 1951 годов по районам и перепись 1939 года по районам.

Сети в тестах нет. Строки сняты с таблиц пакета Miho, Jarotschkin,
Zhuravskaya (`deportationsall.dta`, `deports1946_union.dta`,
`1939_census_all.dta`) и урезаны до нужных колонок; архив Zenodo собирается
здесь же, в памяти, и отдаётся только кусками по заголовку Range. Проверяется
то, на чём держится сбор: сверка перечня и оглавления с кодом, чтение файла
из архива по Range со сверкой CRC32, названия районов без выдумки, записи
1951 года (точка — райцентр, даты листов «Алтай 1946» и «Сахалинская обл»),
записи 1946 года (строки одного номера складываются, одноимённые — нет,
съехавшая область исправлена, «прочие» подписаны по месту), воспроизведение
сверочной таблицы авторов с её ошибками, единицы переписи 1939 года с
частями и точка единицы только при двойном совпадении.
"""

import io
import re
import zipfile
import zlib

import pandas as pd
import pytest

from histctx import net
from histctx.schema import GROUPS, SCOPE_POINT, SCOPE_REGION
from histctx.sources import deportations as dep
from histctx.sources.deportations import (
    ARCHIVE_KEY, ARCHIVE_MD5, ARCHIVE_ROOT, ARCHIVE_SIZE, CENSUS_1939, MEMBERS, PRESENT,
    RECORD_URL, SPECIAL_SETTLEMENTS, WORK_1939, DeportationsError, Member, authors_sums_1946,
    cached_member, census_points, census_records, census_units, check_columns, check_listing,
    check_manifest, docx_text, link_sets, name_stem, oblast_totals, open_archive,
    our_sums_1946, raion_title, read_dta, read_member, records_1946, records_1951,
    similar_names,
)


# --- Zenodo: перечень и оглавление ----------------------------------------

def test_manifest_is_checked_against_the_code():
    good = [{"key": ARCHIVE_KEY, "size": ARCHIVE_SIZE, "checksum": f"md5:{ARCHIVE_MD5}"}]
    assert check_manifest(good) == []
    changed = [{"key": ARCHIVE_KEY, "size": 1, "checksum": "md5:0"}]
    problems = check_manifest(changed)
    assert len(problems) == 2 and "размер" in problems[0] and "сумма" in problems[1]
    assert "такого файла нет" in check_manifest([{"key": "other.zip"}])[0]


def _entries():
    entries = [{"path": m.path, "size": m.size, "crc": m.crc} for m in MEMBERS.values()]
    entries += [{"path": p, "size": 1, "crc": 1} for p in PRESENT]
    return entries


def test_listing_needs_every_member_with_its_size_and_crc():
    assert check_listing(_entries(), total=dep.ARCHIVE_ENTRIES) == []
    broken = _entries()
    broken[0] = {**broken[0], "crc": 1}
    assert "CRC32" in check_listing(broken)[0]
    moved = [e for e in _entries() if not e["path"].endswith("deports1946_union.dta")]
    moved.append({"path": "elsewhere/deports1946_union.dta", "size": 1, "crc": 1})
    problem = check_listing(moved)[0]
    assert "settlers_1946" in problem and "elsewhere/deports1946_union.dta" in problem
    assert "ReadMe.pdf" in check_listing(_entries()[:-len(PRESENT)])[0]
    assert "записей" in check_listing(_entries(), total=5)[0]


class _Response:
    def __init__(self, body, headers):
        self.status, self.body, self.headers = 206, body, headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def serve(monkeypatch, archive: bytes, calls: list) -> None:
    """Подменяет Zenodo: архив отдаётся только кусками, по заголовку Range."""
    def urlopen(request, timeout=None):
        value = request.get_header("Range")
        calls.append(value)
        start, stop = re.match(r"bytes=(\d*)-(\d*)", value).groups()
        if not start:
            start, stop = max(0, len(archive) - int(stop)), len(archive) - 1
        start, stop = int(start), min(int(stop), len(archive) - 1)
        return _Response(archive[start:stop + 1],
                         {"Content-Range": f"bytes {start}-{stop}/{len(archive)}"})
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)


def zenodo_archive(files: dict) -> bytes:
    """Архив записи, как на Zenodo: всё под корнем «Data files MS 11805/» и служебный
    `__MACOSX`, который оглавление должно пропускать."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            archive.writestr(ARCHIVE_ROOT + path, data)
        archive.writestr("__MACOSX/" + ARCHIVE_ROOT + "._ReadMe.pdf", b"mac")
    return buffer.getvalue()


def test_member_is_read_by_range_and_checked(tmp_path, monkeypatch):
    payload = b"stata bytes " * 500
    fake = Member("build_intermediary/Data_raw/fake.dta", len(payload), zlib.crc32(payload))
    monkeypatch.setitem(MEMBERS, "fake", fake)
    calls = []
    serve(monkeypatch, zenodo_archive({fake.path: payload, "ReadMe.pdf": b"pdf"}), calls)

    archive = open_archive(url="https://zenodo.example/archive.zip")
    assert calls == ["bytes=-262144"]                  # оглавление — одним запросом к хвосту
    paths = [e["path"] for e in dep.listing(archive)]
    assert paths == [fake.path, "ReadMe.pdf"]          # без корня и без `__MACOSX`
    assert read_member(archive, fake) == payload

    assert cached_member(tmp_path, "fake", archive=archive) == payload
    assert (tmp_path / "fake.dta").read_bytes() == payload
    calls.clear()
    assert cached_member(tmp_path, "fake", archive=archive) == payload
    assert calls == []                                 # второй раз — из кэша

    wrong = Member(fake.path, fake.size, fake.crc + 1)
    with pytest.raises(DeportationsError, match="CRC32"):
        read_member(archive, wrong)
    with pytest.raises(DeportationsError, match="в архиве нет"):
        read_member(archive, Member("nowhere.dta", 1, 1))


def test_sources_note_is_read_from_word():
    xml = ('<w:document><w:body><w:p><w:r><w:t>Данные по переписи были собраны из открытого '
           'источника Demoscope.</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">'
           'Координаты &amp; базы</w:t></w:r></w:p></w:body></w:document>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as doc:
        doc.writestr("word/document.xml", xml)
    assert docx_text(buffer.getvalue()).splitlines() == [
        "Данные по переписи были собраны из открытого источника Demoscope.",
        "Координаты & базы"]
    with pytest.raises(DeportationsError, match="Word"):
        docx_text(b"not a docx")


def test_stata_is_read_with_and_without_value_labels():
    frame = pd.DataFrame({"raion_id": [1, 2], "ID2": pd.Categorical(["CA4187", "R509"]),
                          "latfinal": [52.27, float("nan")]})
    buffer = io.BytesIO()
    frame.to_stata(buffer, write_index=False, version=118)
    rows = read_dta(buffer.getvalue(), labels=True)
    assert rows[0] == {"raion_id": 1, "ID2": "CA4187", "latfinal": 52.27}
    assert rows[1]["latfinal"] is None
    assert read_dta(buffer.getvalue())[1]["ID2"] in (1, 0)      # код, а не метка
    with pytest.raises(DeportationsError, match="нет колонок"):
        check_columns([{"raion_id": 1}], "crosswalk")


# --- названия -------------------------------------------------------------

@pytest.mark.parametrize("raw, title", [
    ("Бескарагайский 210 км", "Бескарагайский район"),       # расстояние слито с названием
    ("Урлютюнский 200", "Урлютюнский район"),
    ("Яны-Курганский 200км", "Яны-Курганский район"),
    ("г.Павлодар", "г. Павлодар"),
    ("гор коканд", "г. Коканд"),
    ("Город Акмолинск", "г. Акмолинск"),
    ("Г. Чимкент 0", "г. Чимкент"),
    ("пос.Джалагали", "пос. Джалагали"),
    ("с Полудено", "с. Полудено"),
    ("рп Ханты-Мансийск", "рп Ханты-Мансийск"),
    ("Галкинский р-н-", "Галкинский район"),
    ("Ново-Покровский район с. Н-Покровка", "Ново-Покровский район с. Н-Покровка"),
    ("Осински й", "Осинский район"),                         # опечатка листа
    ("Ребрихински", "Ребрихинский район"),                   # оборванное «-ски»
    ("им. 28 Гвардейцев", "район им. 28 Гвардейцев"),
    ("Ширинский р-н Хак. АО", "Ширинский район Хак. автономная область"),
    ("Ойротская АО", "Ойротская автономная область"),
    ("Комендатура № 2", "Комендатура № 2"),                  # номер — не расстояние
    ("Горьковская", "Горьковская"),                          # «Г» — не приставка города
    ("Сузак", "Сузак"),                                      # «С» — не приставка села
    ("Северное горнопромышленное управление 545 км до Магадана",
     "Северное горнопромышленное управление 545 км до Магадана"),
])
def test_raion_titles_are_cleaned_but_not_invented(raw, title):
    assert raion_title(raw) == title


def test_name_without_letters_is_no_name():
    assert raion_title("180 км") is None
    assert raion_title(None) is None


def test_names_of_one_raion_are_recognised():
    assert similar_names("г Троицк", "Троицкий")
    assert similar_names("г Кострома", "Костромской гс")
    assert similar_names("Хатырчинский", "Хатарчинский")     # опечатка
    assert not similar_names("Баяндаевский р-н", "Качугский")
    assert not similar_names("Комендатура № 2", "Комендатура № 3")
    assert name_stem("Тюп") == name_stem("Тюпский")


# --- спецпоселенцы 1951 года ------------------------------------------------

def row_1951(**kw):
    """Город Павлодар на 1 января 1951 года (строка набора, урезанная)."""
    row = {"raion_id": 261, "raion_russ": "г.Павлодар", "oblast_russ": "Павлодар",
           "oblast_engl": "pavlodar", "countrydeport": "kazakhstan", "latfinal": 52.27,
           "lonfinal": 77.0, "nbvillagesraion": 1, "germanraion": 1988,
           "northcaucasianraion": 3178, "kalmykraion": 0, "krimraion": 0, "chechenraion": 0,
           "allgermanraion": 1988, "checheningushraion": 3178, "prot": 1988,
           "totaldeportsdistrict": 5166, "totaldeportedethnicdistrict": 5166,
           "totaldeportednonethnicdistrict": 0}
    row.update(kw)
    return row


def test_record_1951_is_a_raion_center_with_contingents():
    rec = records_1951([row_1951()])[0]
    assert rec.title == "Спецпоселенцы: г. Павлодар, Павлодарская область, 1951"
    assert (rec.lat, rec.lon, rec.scope) == (52.27, 77.0, SCOPE_POINT)
    assert rec.confidence == "district_centroid"
    assert rec.region == "Павлодарская область"
    assert rec.place_text == "г. Павлодар, Павлодарская область, Казахская ССР"
    assert (rec.year_from, rec.year_to, rec.date_precision) == (1951, 1951, "year")
    assert "1 января 1951" in rec.period_raw
    assert rec.extra["contingents"] == {"выселенные с Северного Кавказа": 3178, "немцы": 1988}
    assert rec.extra["total"] == 5166 and rec.extra["oblast_source"] == "Павлодар"
    assert rec.summary == ("На 1 января 1951 года в городе учтено 5 166 спецпоселенцев; "
                           "больше всего: выселенные с Северного Кавказа — 3 178, "
                           "немцы — 1 988.")
    assert rec.url == RECORD_URL and rec.source_id == "1951:261"
    # Производные колонки авторов — не категории: немцы не задвоились.
    assert "allgermanraion" not in rec.extra["contingents"]


def test_sheet_dates_other_than_1951_are_kept():
    altai = records_1951([row_1951(raion_id=407, raion_russ="Алейский", oblast_russ="Алтай",
                                   oblast_engl="altay", countrydeport="russia")])[0]
    assert altai.year_from == altai.year_to == 1946
    assert "д. 319" in altai.period_raw and altai.title.endswith("Алтайский край, 1946")
    assert altai.summary.startswith("По листу 1946 года в районе")
    sakhalin = records_1951([row_1951(oblast_russ="Сахалинская", countrydeport="russia")])[0]
    assert sakhalin.year_from == 1950 and "1950" in sakhalin.extra["sheet_date"]


def test_unknown_column_is_kept_under_its_name_and_zero_raion_stays():
    rec = records_1951([row_1951(newgroupraion=7)])[0]
    assert rec.extra["contingents"]["newgroupraion"] == 7
    assert rec.extra["unlabeled_columns"] == ["newgroupraion"]
    empty = records_1951([row_1951(raion_russ="Карабутакский", germanraion=0,
                                   northcaucasianraion=0, totaldeportsdistrict=0)])[0]
    assert empty.extra["contingents"] == {}
    assert "не учтено" in empty.summary and empty.has_point


def test_republic_comes_from_the_oblast_not_from_the_authors_country():
    rec = records_1951([row_1951(raion_russ="Днепродзержинский", oblast_russ="Днепропетровской",
                                 countrydeport="russia")])[0]
    assert rec.place_text.endswith("Днепропетровская область, Украинская ССР")
    tajik = records_1951([row_1951(raion_russ="Кагановичабадский", oblast_russ="Khatlon",
                                   countrydeport="tajikistan")])[0]
    assert tajik.region == "Таджикская ССР" and tajik.extra["oblast_source"] == "Khatlon"


# --- спецпоселенцы 1946 года ------------------------------------------------

def row_1946(ident, oblast, raion, lat=50.0, lon=78.0, country="kazakhstan", **counts):
    return {"id_distr": ident, "country": country, "oblast": oblast, "raion": raion,
            "latitude": lat, "longitude": lon, **counts}


ROWS_1946 = [
    # Дальстрой: один номер района в двух листах — власовцы и остальные.
    row_1946(766, "Дальний Север (Магадан тут", "Магадан", 59.5638, 150.80347, "russia",
             vlasovzisum=5966),
    row_1946(766, "Дальстрой", "гор. Магадан", 59.5638, 150.80347, "russia", germansum=151),
    # Бескарагайский район двумя строками под разными номерами.
    row_1946(388, "Павлодарская область", "Бескарагайский р-н", 50.89317, 78.31079,
             chechensum=778, germansum=1198),
    row_1946(389, "Павлодарская область", "Бескарагайский р-н", 50.89317, 78.31079,
             chechensum=621, germansum=1339),
    # Номер 129 стоит у двух разных мест (так у авторов).
    row_1946(129, "Самаркандская", "гор. Самарканд", 39.65, 66.96, "uzbekistan",
             crimeantatarsum=300),
    row_1946(129, "Сурхан-Дарьинская", "Денауский район", 38.27, 67.9, "uzbekistan",
             crimeantatarsum=40),
    # Карагандинский район под «Кустанайской» — графа области съехала в листе КазССР.
    row_1946(358, "Кустанайская область", "г. Караганда", 49.80187, 73.10211,
             germansum=10, othersum=5, other2sum=8),
    row_1946(1500, "Новосибирская", "Андреевский р-н", 55.0, 77.0, "russia", othersum=3),
    row_1946(189, "Ферганская", "Ферганский р-н", 40.38, 71.78, "uzbekistan", germansum=82),
    row_1946(1438, "Кировская", "Мезянский р-н", None, None, "russia", germansum=12),
]


def test_rows_of_one_district_number_are_summed():
    recs = {r.source_id: r for r in records_1946(ROWS_1946)}
    # Графа страны — своя у каждой записи, а не от соседней строки.
    assert recs["1946:388"].extra["country_source"] == "kazakhstan"
    assert recs["1946:189"].extra["country_source"] == "uzbekistan"
    dalstroy = recs["1946:766"]
    assert dalstroy.extra["contingents"] == {"власовцы": 5966, "немцы": 151}
    assert dalstroy.extra["source_rows"] == 2
    assert dalstroy.region == "Дальстрой (Дальний Север)"
    assert len(recs) == len(ROWS_1946) - 1


def test_namesakes_under_other_numbers_are_linked_not_summed():
    recs = {r.source_id: r for r in records_1946(ROWS_1946)}
    first, second = recs["1946:388"], recs["1946:389"]
    assert first.extra["contingents"] == {"немцы": 1198, "чеченцы": 778}
    assert first.extra["same_raion"] == ["1946:389"] and second.extra["same_raion"] == ["1946:388"]
    assert "числа не сложены" in first.summary
    # Номер 129 у двух мест: две записи, без ссылок друг на друга.
    places = sorted(r.district for r in recs.values() if r.extra.get("id_distr") == [129])
    assert places == ["Денауский район", "г. Самарканд"]


def test_shifted_oblast_is_fixed_and_other_is_labelled_by_place():
    recs = {r.source_id: r for r in records_1946(ROWS_1946)}
    karaganda = recs["1946:358"]
    assert karaganda.region == "Карагандинская область"
    assert "Кустанайская область" in karaganda.extra["oblast_fixed"]
    assert karaganda.extra["contingents"] == {"немцы": 10, "репатрианты": 8, "легионеры": 5}
    assert recs["1946:1500"].extra["contingents"] == {"указники": 3}


def test_fergana_is_dated_1948_and_raion_without_point_stays():
    recs = {r.source_id: r for r in records_1946(ROWS_1946)}
    fergana = recs["1946:189"]
    assert fergana.year_from == fergana.year_to == 1948
    assert "Zamechania" in fergana.extra["sheet_date"]
    lost = recs["1946:1438"]
    assert lost.lat is None and lost.scope == SCOPE_REGION
    assert lost.confidence == "no_coords" and lost.regions == ["Кировская область"]
    assert lost.year_from == 1946


def test_altai_sheet_of_1946_is_linked_to_the_1946_table_not_summed():
    altai_1951 = records_1951([row_1951(raion_id=407, raion_russ="Алейский",
                                        oblast_russ="Алтай", countrydeport="russia")])
    altai_1946 = records_1946([row_1946(614, "Алтайский край", "Алейский район", 52.5, 82.8,
                                        "russia", germansum=2927, kalmyksum=1585)])
    assert link_sets(altai_1951, altai_1946) == 1
    assert altai_1951[0].extra["same_raion_other_set"] == ["1946:614"]
    assert altai_1946[0].extra["same_raion_other_set"] == ["1951:407"]
    assert "числа не сложены" in altai_1951[0].summary
    assert altai_1946[0].extra["contingents"]["немцы"] == 2927


def test_authors_table_is_reproduced_with_its_errors():
    """Таблица авторов теряет районы, записанные двумя строками или с общей точкой,
    и считает карачаевцев дважды; записи слоя не теряют ничего."""
    rows_1951 = [row_1951(oblast_russ="Павлодар", oblast_engl="pavlodar"),
                 row_1951(oblast_russ="Карагандская", oblast_engl="karagandskaya")]
    rows = [
        row_1946(388, "Павлодарская область", "Бескарагайский р-н", 50.9, 78.3,
                 germansum=1198),
        row_1946(389, "Павлодарская область", "Бескарагайский р-н", 50.9, 78.3,
                 germansum=1339),
        row_1946(381, "Павлодарская область", "Лебяжинский район", 51.5, 77.8,
                 germansum=659, karachisum=10),
        row_1946(500, "Павлодарская область", "Иртышский район", 53.3, 75.5, germansum=7),
        row_1946(500, "Павлодарская область", "Иртышский район", 53.3, 75.5, germansum=3),
    ]
    assert authors_sums_1946(rows, rows_1951)["pavlodar"] == (659, 20)
    assert our_sums_1946(rows, rows_1951)["pavlodar"] == (1198 + 1339 + 659 + 10, 10)


# --- перепись 1939 года -----------------------------------------------------

def census_row(ident, oblast, raion, subraion, total, suboblast="", country="", **counts):
    return {"ID": ident, "N": int(ident[2:] if ident.startswith("CA") else ident[1:]),
            "oblast": oblast, "suboblast": suboblast, "raion": raion, "subraion": subraion,
            "total": total, "Russians": 0, "Ukrainians": 0, "Jews": 0, "Poles": 0,
            "Germans": 0, "Kazakhs": 0, "Other": 0, "country": country, "raion1": raion,
            **counts}


# Винницкая область: итог области, Бершадский район с частями (числа — как у
# «Демоскопа»), город Винница, Могилев-Подольский горсовет; Ташкентская без
# слова «область»; Агинский округ, который сам — один район.
CENSUS = [
    census_row("CA1", "Винницкая область", "Винницкая область", "Винницкая область", 200000,
               Ukrainians=180000, Russians=20000),
    census_row("CA2", "Винницкая область", "г. Винница", "весь город", 93032,
               Ukrainians=45776, Jews=33150, Russians=9838, Poles=2837, Other=1431),
    census_row("CA10", "Винницкая область", "Бершадский", "весь район", 65416,
               Russians=3230, Ukrainians=56906, Jews=4545, Poles=250, Other=485),
    census_row("CA11", "Винницкая область", "Бершадский", "пгт Бершадь (рц)", 5805,
               Russians=139, Ukrainians=1322, Jews=4271, Poles=50, Other=23),
    census_row("CA14", "Винницкая область", "Бершадский", "прочие села", 49256,
               Russians=3068, Ukrainians=45312, Jews=225, Poles=192, Other=459),
    census_row("CA3", "Винницкая область", "Могилев-Подольский гс", "весь горсовет", 69104,
               Ukrainians=55475),
    census_row("CA20", "Ташкентская", "Пскентский", "весь район", 40000, Kazakhs=1000,
               Russians=500),
    census_row("R6231", "Читинская область", "Агинский нац.окр.", "весь район", 36910,
               suboblast="Агинский нац.окр.", country="russia", Russians=10000),
    # Единицы без пометки «весь…»: город сам себе итог (с частями) и город без
    # подписи; итог Остяко-Вогульского округа «нац. Округ» — не единица.
    census_row("CA3979", "Джамбульская область", "Джамбульская область",
               "Джамбульская область", 63728),
    census_row("CA3980", "Джамбульская область", "г. Джамбул", "г. Джамбул", 63728,
               Russians=30000, Kazakhs=20000),
    census_row("CA3981", "Джамбульская область", "г. Джамбул", "Центральная часть", 42135),
    census_row("R4140", "Омская область", "нац. Округ", "нац. Округ", 93274,
               suboblast="Остяко-Вогульский (Ханты-Мансийский) нац.окр.", country="russia"),
    census_row("R4161", "Омская область", "г. Салехард (окрц)", None, 12764,
               suboblast="Ямало-Ненецкий нац.окр.", country="russia", Russians=5000),
]


def test_census_units_carry_their_parts_and_skip_oblast_totals():
    units = census_units(CENSUS)
    assert [u["ID"] for u, _ in units] == ["CA2", "CA10", "CA3", "CA20", "R6231", "CA3980",
                                           "R4161"]
    parts = {u["ID"]: [p["ID"] for p in parts] for u, parts in units}
    assert parts["CA10"] == ["CA11", "CA14"] and parts["CA3980"] == ["CA3981"]
    recs = {r.source_id: r for r in census_records(CENSUS)}
    assert recs["1939:CA3980"].extra["unit"]["kind"] == "город"
    assert recs["1939:R4161"].title.startswith("г. Салехард (окрц) (Ямало-Ненецкий")


def test_census_record_is_territorial_with_shares_and_parts():
    recs = {r.source_id: r for r in census_records(CENSUS)}
    bershad = recs["1939:CA10"]
    assert bershad.title == "Бершадский район (Винницкая область): перепись 1939 года"
    assert bershad.scope == SCOPE_REGION and bershad.lat is None
    assert bershad.regions == ["Винницкая область"] and bershad.confidence == "ok"
    assert (bershad.year_from, bershad.date_precision) == (1939, "day")
    assert bershad.work == WORK_1939
    assert bershad.extra["census_1939"] == {"всего": 65416, "украинцы": 56906, "евреи": 4545,
                                            "русские": 3230, "поляки": 250, "прочие": 485}
    assert bershad.extra["shares"] == {"украинцы": 87.0, "евреи": 6.9, "русские": 4.9,
                                       "поляки": 0.4}
    assert [p["name"] for p in bershad.extra["parts"]] == ["пгт Бершадь (рц)", "прочие села"]
    assert bershad.extra["parts"][0]["евреи"] == 4271
    assert bershad.summary == ("Перепись 17 января 1939 года: 65 416 человек. "
                               "Украинцы — 87%, евреи — 6,9%, русские — 4,9%.")
    assert bershad.place_text.endswith("Винницкая область, Украинская ССР")


def test_census_titles_kinds_and_the_other_column():
    recs = {r.source_id: r for r in census_records(CENSUS)}
    city = recs["1939:CA2"]
    assert city.title.startswith("г. Винница (") and city.extra["unit"]["kind"] == "город"
    assert "«прочие») — 1,5%" in city.summary
    assert recs["1939:CA3"].title.startswith("Могилев-Подольский горсовет")
    assert recs["1939:CA20"].region == "Ташкентская область"
    assert recs["1939:CA20"].place_text.endswith("Узбекская ССР")
    aga = recs["1939:R6231"]
    assert aga.title == ("Агинский нац.окр. (Агинский нац.окр., Читинская область): "
                         "перепись 1939 года")


def test_oblast_total_is_compared_with_its_units():
    totals = {t["oblast"]: t for t in oblast_totals(CENSUS)}
    assert totals["Винницкая область"]["total"] == 200000
    assert totals["Винницкая область"]["units"] == 93032 + 65416 + 69104
    assert totals["Ташкентская"]["total"] is None
    assert totals["Джамбульская область"] == {"oblast": "Джамбульская область",
                                              "total": 63728, "units": 63728}


def test_census_point_needs_both_the_authors_link_and_the_same_name():
    settlers = [
        row_1951(raion_id=1, raion_russ="Бершадский", latfinal=48.37, lonfinal=29.52),
        row_1951(raion_id=2, raion_russ="Баяндаевский р-н", latfinal=53.0, lonfinal=105.5),
        row_1951(raion_id=3, raion_russ="Пскентский", latfinal=40.9, lonfinal=69.3),
        row_1951(raion_id=4, raion_russ="Пскентский", latfinal=41.0, lonfinal=69.4),
    ]
    crosswalk = [{"raion_id": 1, "ID2": "CA10"}, {"raion_id": 2, "ID2": "CA2"},
                 {"raion_id": 3, "ID2": "CA20"}, {"raion_id": 4, "ID2": "CA20"},
                 {"raion_id": 1, "ID2": "CA11"}]
    points, stats = census_points(crosswalk, settlers, CENSUS)
    assert set(points) == {"CA10"}
    assert stats == {"links": 5, "names_differ": 1, "link_to_non_unit": 1, "ambiguous": 1,
                     "points": 1}
    rec = {r.source_id: r for r in census_records(CENSUS, points)}["1939:CA10"]
    assert (rec.lat, rec.lon, rec.scope) == (48.37, 29.52, SCOPE_POINT)
    assert rec.confidence == "district_centroid" and rec.regions == []
    assert "по карте 1939 года" in rec.extra["point"]
    assert rec.extra["deport_raion"]["raion_id"] == 1


# --- карточки слоёв -----------------------------------------------------------

def test_layer_cards_state_what_and_on_which_rights():
    for spec in (SPECIAL_SETTLEMENTS, CENSUS_1939):
        assert spec.group in GROUPS and spec.status == "harvested"
        assert len(spec.description) > 40 and spec.expected_rows
        assert "CC BY 4.0" in spec.license
    assert SPECIAL_SETTLEMENTS.group == "hardship" and CENSUS_1939.group == "admin"
    assert "не выяснены" in CENSUS_1939.license
