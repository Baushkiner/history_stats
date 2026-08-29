"""Урожай и цены из RISTAT: что попадает в слой и что его останавливает.

Образец таблицы ниже — настоящие строки выгрузки ERRHS, урезанные до колонок,
на которых держится разбор. Сети в тестах нет: каталог `ristat.org` собирает
архив под запрос, и проверять на нём разбор значило бы проверять сеть.

Главное, что здесь закреплено: пара «посеяно / снято» сводится в одну запись
с отношением сам-N, а всё, что свести нельзя, остаётся в слое порознь.
Молчаливая потеря строки — худшая из возможных ошибок этого сборщика:
в выгрузке на десять тысяч записей её никто не заметит.
"""

import io
import zipfile
from pathlib import Path

import pytest

from histctx.geo import region_key
from histctx.schema import SCOPE_REGION
from histctx.sources.errhs import (
    CONFIDENCE_UNMATCHED, HARVEST_PRICES, REQUIRED_COLUMNS, TOPICS, ErrhsError,
    category_of, check_columns, is_matchable, normalize_region, read_figures,
    read_sheet, read_table, region_records, split_role, subject_and_role,
    unit_text, yield_ratio,
)

ROOT = Path(__file__).resolve().parents[1]

# Колонки выгрузки — как их отдаёт файловый каталог ristat.org.
COLUMNS = [
    "ID", "TERRITORY", "TER_CODE", "TOWN", "DISTRICT", "YEAR", "MONTH", "VALUE",
    "VALUE_UNIT", "VALUE_LABEL", "DATATYPE", "HISTCLASS1", "HISTCLASS2", "HISTCLASS3",
    "COMMENT_SOURCE", "SOURCE", "VOLUME", "PAGE", "NABORSHIK_ID", "COMMENT_NABORSHIK",
    "BASE_YEAR",
]


def row(**kwargs) -> dict:
    """Строка выгрузки: пропуск в ERRHS помечен точкой, а не пустой ячейкой."""
    out = dict.fromkeys(COLUMNS, ".")
    out.update({k: str(v) for k, v in kwargs.items()})
    return out


# Тамбовская губерния 1794 года: рожь уродилась сам-3,4, гречиха сам-2,2.
# Картофеля ещё нет — и посев, и урожай нулевые.
SAMPLE = [
    row(ID=1, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=163635,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="рожь озимая в посеве",
        SOURCE="Зябловский Е. Статистическое описание", PAGE=112, BASE_YEAR=1795),
    row(ID=2, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=556359,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="рожь озимая в урожае",
        SOURCE="Зябловский Е. Статистическое описание", PAGE=112, BASE_YEAR=1795),
    row(ID=3, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=50000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="гречиха в посеве",
        BASE_YEAR=1795),
    row(ID=4, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=110000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="гречиха в урожае",
        BASE_YEAR=1795),
    row(ID=5, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=0,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="картофель в посеве",
        COMMENT_NABORSHIK="в источнике показатель пропущен предполагаем ноль",
        BASE_YEAR=1795),
    row(ID=6, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=0,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="картофель в урожае",
        BASE_YEAR=1795),
    # Строка без числа: в источнике показатель пропущен.
    row(ID=7, TERRITORY="Тамбовская губерния", YEAR=1794, VALUE=".",
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="просо в урожае",
        BASE_YEAR=1795),
]

# Срез 1858 года: один и тот же хлеб посчитан отдельно у помещиков и у
# государственных крестьян. Различает эти строки только вторая ступень.
SAMPLE_1858 = [
    row(ID=11, TERRITORY="Тамбовская губерния", YEAR=1858, VALUE=100000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="хлеб озимой (посеяно)",
        HISTCLASS2="у помещиков", BASE_YEAR=1858),
    row(ID=12, TERRITORY="Тамбовская губерния", YEAR=1858, VALUE=400000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="хлеб озимой (снято)",
        HISTCLASS2="у помещиков", BASE_YEAR=1858),
    row(ID=13, TERRITORY="Тамбовская губерния", YEAR=1858, VALUE=200000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="хлеб озимой (посеяно)",
        HISTCLASS2="у государственных крестьян", BASE_YEAR=1858),
    row(ID=14, TERRITORY="Тамбовская губерния", YEAR=1858, VALUE=500000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="хлеб озимой (снято)",
        HISTCLASS2="у государственных крестьян", BASE_YEAR=1858),
    # Опечатка источника: латинская «o» в конце «(посеянo)».
    row(ID=15, TERRITORY="Тамбовская губерния", YEAR=1858, VALUE=1000,
        VALUE_UNIT="четверти", DATATYPE="4.02", HISTCLASS1="капуста (посеянo)",
        BASE_YEAR=1858),
]


def figures(rows=SAMPLE, topic="4.02", benchmark=1795):
    return read_figures(rows, topic=topic, benchmark=benchmark)


def by_title(records):
    return {r.title: r for r in records}


# --- формат выгрузки -----------------------------------------------------

def test_missing_column_stops_the_harvest():
    """Переименованная колонка должна ронять сбор, а не давать пустой слой."""
    header = [c for c in COLUMNS if c != "VALUE_UNIT"]
    with pytest.raises(ErrhsError) as exc:
        check_columns(header)
    assert "VALUE_UNIT" in str(exc.value)
    # В сообщении должно быть видно, что пришло на самом деле.
    assert "TERRITORY" in str(exc.value)


def test_all_required_columns_are_present_in_the_sample():
    assert all(c in COLUMNS for c in REQUIRED_COLUMNS)
    check_columns(COLUMNS)


def test_table_is_read_from_the_archive():
    """Каталог отдаёт архив: таблица в XLSX, документация в PDF рядом."""
    header, rows = read_table(_zip_with_table(SAMPLE), what="проба")
    assert header == COLUMNS
    assert len(rows) == len(SAMPLE)
    assert rows[0]["TERRITORY"] == "Тамбовская губерния"


def test_archive_without_a_table_is_an_error():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ERRHS_Introduction.pdf", b"%PDF-1.4")
    with pytest.raises(ErrhsError) as exc:
        read_table(buffer.getvalue(), what="проба")
    assert "PDF" in str(exc.value) or "XLSX" in str(exc.value)


def test_broken_archive_is_an_error():
    with pytest.raises(ErrhsError):
        read_table(b"not a zip at all", what="проба")


# --- разбор показателя ---------------------------------------------------

def test_role_is_split_off_the_indicator():
    assert split_role("рожь озимая в посеве") == ("рожь озимая", "посев")
    assert split_role("хлеб яровой (снято)") == ("хлеб яровой", "урожай")
    assert split_role("падеж скота") == ("падеж скота", None)


def test_latin_letter_in_the_source_does_not_break_the_split():
    """В срезе 1858 года «(посеянo)» набрано с латинской «o»."""
    assert split_role("капуста (посеянo)") == ("капуста", "посев")


def test_indicator_keeps_all_levels_of_the_chain():
    """«у помещиков» и «у государственных крестьян» — разные ряды, не один."""
    subject, role = subject_and_role(SAMPLE_1858[0])
    assert subject == "хлеб озимой, у помещиков"
    assert role == "посев"


# --- сведение посева и урожая -------------------------------------------

def test_sowing_and_harvest_become_one_record_with_the_ratio():
    records = by_title(region_records(figures()))
    title = "Рожь озимая: урожай сам-3,4 — Тамбовская губерния, 1794"
    assert title in records, sorted(records)
    rec = records[title]
    assert rec.extra["посеяно"] == 163635
    assert rec.extra["сам"] == pytest.approx(3.4, abs=0.01)
    assert "недород" not in rec.summary


def test_poor_harvest_is_named_in_the_description():
    """Сам-2,2 — год, после которого до новины не дотянуть. Это надо сказать словами."""
    rec = by_title(region_records(figures()))[
        "Гречиха: урожай сам-2,2 — Тамбовская губерния, 1794"
    ]
    assert "недород" in rec.summary


def test_zero_sowing_keeps_both_rows():
    """Сам-N посчитать нельзя — значит, обе строки идут в слой порознь.

    Слить их в одну значило бы потерять вторую молча.
    """
    titles = by_title(region_records(figures()))
    assert "Картофель: посеяно 0 четвертей — Тамбовская губерния, 1794" in titles
    assert "Картофель: снято 0 четвертей — Тамбовская губерния, 1794" in titles


def test_total_crop_failure_is_still_a_pair():
    """Снято ноль при живом посеве — это сам-0, а не «пары нет».

    Самая говорящая запись слоя: год, после которого не осталось даже семян.
    Если проверять отношение на истинность, а не на None, она развалится на
    две ничего не значащие строки.
    """
    rows = [
        row(ID=60, TERRITORY="Калужская губерния", YEAR=1795, VALUE=100,
            VALUE_UNIT="четверти", HISTCLASS1="полба в посеве", BASE_YEAR=1795),
        row(ID=61, TERRITORY="Калужская губерния", YEAR=1795, VALUE=0,
            VALUE_UNIT="четверти", HISTCLASS1="полба в урожае", BASE_YEAR=1795),
    ]
    records = region_records(read_figures(rows, topic="4.02", benchmark=1795))
    assert len(records) == 1
    assert records[0].extra["сам"] == 0
    assert "недород" in records[0].summary


def test_rows_from_different_tables_are_never_paired():
    """Пара имеет смысл только внутри одной таблицы.

    Посев из среза 1795 года и урожай из среза 1858-го — это два разных
    источника, и отношение между ними было бы придумано.
    """
    sown = row(ID=70, TERRITORY="Калужская губерния", YEAR=1800, VALUE=100,
               VALUE_UNIT="четверти", HISTCLASS1="овес в посеве", BASE_YEAR=1795)
    reaped = row(ID=71, TERRITORY="Калужская губерния", YEAR=1800, VALUE=300,
                 VALUE_UNIT="четверти", HISTCLASS1="овес в урожае", BASE_YEAR=1858)
    figures_ = (read_figures([sown], topic="4.02", benchmark=1795)
                + read_figures([reaped], topic="4.02", benchmark=1858))
    records = region_records(figures_)
    assert len(records) == 2
    assert all("сам" not in r.extra for r in records)


def test_fallback_row_number_cannot_collide_with_a_real_id():
    """uid записи держится на source_id — запасной номер обязан быть чужим."""
    rows = [
        row(TERRITORY="Калужская губерния", YEAR=1795, VALUE=5, ID=".",
            VALUE_UNIT="четверти", HISTCLASS1="овес в урожае", BASE_YEAR=1795),
        row(ID=1, TERRITORY="Калужская губерния", YEAR=1795, VALUE=7,
            VALUE_UNIT="четверти", HISTCLASS1="рожь в урожае", BASE_YEAR=1795),
    ]
    records = region_records(read_figures(rows, topic="4.02", benchmark=1795))
    assert len({r.source_id for r in records}) == 2
    assert len({r.uid for r in records}) == 2


def test_each_estate_gets_its_own_pair():
    records = by_title(region_records(figures(SAMPLE_1858, benchmark=1858)))
    assert "Хлеб озимой, у помещиков: урожай сам-4,0 — Тамбовская губерния, 1858" in records
    assert ("Хлеб озимой, у государственных крестьян: урожай сам-2,5 — "
            "Тамбовская губерния, 1858") in records


def test_unpaired_sowing_stays_in_the_layer():
    records = region_records(figures(SAMPLE_1858, benchmark=1858))
    lone = [r for r in records if r.title.startswith("Капуста")]
    assert len(lone) == 1
    assert lone[0].category == "посев"


def test_row_without_a_number_does_not_reach_the_layer():
    """Строку без числа показать нечем; сколько их было — печатает сборщик."""
    assert len(figures()) == len(SAMPLE) - 1
    assert not [f for f in figures() if f.subject == "просо"]


def test_ratio_needs_the_same_unit():
    reaped, sown = figures()[1], figures()[0]
    assert yield_ratio(reaped, sown) == pytest.approx(3.4, abs=0.01)
    other = type(sown)(**{**sown.__dict__, "unit": "пуды"})
    assert yield_ratio(reaped, other) is None


# --- запись схемы --------------------------------------------------------

def test_records_are_territorial_and_have_no_point():
    """У урожая губернии координат нет: ставить точку в губернском городе — выдумка."""
    for rec in region_records(figures()):
        assert rec.scope == SCOPE_REGION
        assert rec.lat is None and rec.lon is None
        assert rec.regions == [rec.region]
        assert rec.year_from == rec.year_to == 1794
        assert rec.layer == HARVEST_PRICES.slug


def test_year_comes_from_the_row_not_from_the_benchmark():
    """Срез 1795 года собран из описаний 1782–1805 годов, и год у них свой."""
    assert {f.year for f in figures()} == {1794}
    assert {f.benchmark for f in figures()} == {1795}


def test_year_falls_back_to_the_benchmark_and_is_marked_approximate():
    rows = [row(ID=20, TERRITORY="Тамбовская губерния", YEAR=".", VALUE=100,
                VALUE_UNIT="четверти", HISTCLASS1="овес в урожае", BASE_YEAR=1795)]
    rec = region_records(read_figures(rows, topic="4.02", benchmark=1795))[0]
    assert rec.year_from == 1795
    assert rec.date_approx is True
    assert "опорный срез" in rec.period_raw


def test_units_agree_with_the_number():
    assert unit_text("четверти", 1) == "четверть"
    assert unit_text("пуды", 3) == "пуда"
    assert unit_text("пуды", 12) == "пудов"
    assert unit_text("рубли", 38704) == "рубля"
    assert unit_text("рубли", 1.9) == "рубля"
    # «число» — не единица, а пометка «просто количество».
    assert unit_text("число", 5) == ""
    # Незнакомая единица пишется как в источнике: это видно глазом.
    assert unit_text("осьмины", 5) == "осьмины"


def test_categories_follow_the_topic_and_the_unit():
    assert category_of(figures()[1]) == "урожай"
    assert category_of(figures()[0]) == "посев"
    price = read_figures(
        [row(ID=30, TERRITORY="Курская губерния", YEAR=1897, VALUE=96,
             VALUE_UNIT="рубли", HISTCLASS1="рублей за десятину", BASE_YEAR=1897)],
        topic="7.03", benchmark=1897)[0]
    assert category_of(price) == "цена земли"
    murrain = read_figures(
        [row(ID=31, TERRITORY="Курская губерния", YEAR=1858, VALUE=1200,
             VALUE_UNIT="головы", HISTCLASS1="падеж скота", BASE_YEAR=1858)],
        topic="4.02", benchmark=1858)[0]
    assert category_of(murrain) == "падёж скота"


# --- сопоставление губерний ---------------------------------------------

def test_qualifier_is_stripped_from_the_region_but_kept_in_the_place():
    rows = [row(ID=40, TERRITORY="Астраханская губерния (1802>)", YEAR=1805,
                VALUE=10, VALUE_UNIT="четверти", HISTCLASS1="овес в урожае",
                BASE_YEAR=1795)]
    rec = region_records(read_figures(rows, topic="4.02", benchmark=1795))[0]
    assert rec.region == "Астраханская губерния"
    assert rec.place_text == "Астраханская губерния (1802>)"
    assert normalize_region("Астраханская губерния") == "Астраханская губерния"


def test_region_of_a_record_matches_the_same_name_from_a_document():
    """Подбор сравнивает ключи: название из таблицы и из метрики должны сойтись."""
    rec = region_records(figures())[0]
    assert region_key(rec.region) == region_key("Тамбовской губернии")


def test_composite_territory_is_marked_not_dropped():
    """«Земля войска Донского» под правило подбора не подходит — но остаётся в слое."""
    rows = [row(ID=50, TERRITORY="Земля войска Донского", YEAR=1858, VALUE=7,
                VALUE_UNIT="четверти", HISTCLASS1="овес в урожае", BASE_YEAR=1858)]
    records = region_records(read_figures(rows, topic="4.02", benchmark=1858))
    assert len(records) == 1
    assert records[0].confidence == CONFIDENCE_UNMATCHED
    assert records[0].region == "Земля войска Донского"
    assert not is_matchable("Земля войска Донского")


def test_single_stem_name_is_considered_matchable():
    """«Татарская АССР» извлекатель не знает, но ключ у неё один — «татарск»."""
    assert is_matchable("Татарская АССР")
    assert is_matchable("Тамбовская губерния")
    assert not is_matchable("Адыгейская автономная область Краснодарского края")


# --- слой в каталоге -----------------------------------------------------

def test_topics_and_benchmarks_are_inside_the_project_window():
    """Срез 2002 года в слой не идёт: он за пределами окна проекта."""
    years = {y for _, benchmarks in TOPICS.values() for y in benchmarks}
    assert years == {1795, 1858, 1897, 1959}


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    spec = BY_SLUG[HARVEST_PRICES.slug]
    assert spec is HARVEST_PRICES
    assert spec.status == "harvested"
    assert spec.group == "economy"
    assert "CC BY-NC-SA" in spec.license
    assert spec.url and spec.expected_rows


def _zip_with_table(rows: list[dict]) -> bytes:
    """Собирает архив в том виде, в каком его отдаёт каталог: таблица и PDF."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Данные"
    sheet.append(COLUMNS)
    for item in rows:
        sheet.append([item[c] for c in COLUMNS])
    table = io.BytesIO()
    book.save(table)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ERRHS_4_02_data_1795-ru.xlsx", table.getvalue())
        archive.writestr("ERRHS_Introduction_2023_RUS.pdf", b"%PDF-1.4")
    return buffer.getvalue()


def test_sheet_reader_checks_columns_too():
    from openpyxl import Workbook

    book = Workbook()
    book.active.append(["ID", "TERRITORY"])
    data = io.BytesIO()
    book.save(data)
    with pytest.raises(ErrhsError):
        read_sheet(data.getvalue(), what="обрезанная таблица")
