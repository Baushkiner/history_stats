"""Тесты разбора датировок. Все примеры взяты из реальных файлов проекта."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histctx.periods import parse_period, parse_year  # noqa: E402


@pytest.mark.parametrize("text,year_from,year_to", [
    # Точный год во всех встречающихся написаниях.
    ("1771 г.", 1771, 1771),
    ("1917 г", 1917, 1917),
    ("1890", 1890, 1890),
    # Диапазоны лет, в том числе с усечённой второй границей.
    ("1769-1770 гг.", 1769, 1770),
    ("1861 - 1919 гг.", 1861, 1919),
    ("1920-21 гг.", 1920, 1921),
    ("с 1823 по 1827 год", 1823, 1827),
    # Десятилетия.
    ("1770-е гг.", 1770, 1779),
    ("1890-е", 1890, 1899),
    ("1850-60-е гг.", 1850, 1869),
    ("1810-1830-е гг.", 1810, 1839),
    ("30-е годы 19 в.", 1830, 1839),
    # Века и их доли.
    ("19 в.", 1801, 1900),
    ("20 век", 1901, 2000),
    ("15-18 вв.", 1401, 1800),
    ("конец 19 в.", 1890, 1900),
    ("начало 20 в.", 1901, 1915),
    ("середина 19 в.", 1840, 1860),
    ("первая половина 19 в.", 1801, 1850),
    ("вторая половина 19 в.", 1851, 1900),
    ("первая треть 19 в.", 1801, 1833),
    ("первая четверть 20 в.", 1901, 1925),
    ("рубеж 19 и 20 вв.", 1890, 1910),
    # Доли десятилетия.
    ("конец 1830-х - начало 1840-х гг.", 1837, 1843),
    ("начало 1930-х гг.", 1930, 1933),
    ("середина 1950-х гг.", 1954, 1956),
    # Эллипсис единицы: «в.» относится к обеим границам.
    ("конец 18 - начало 19 в.", 1790, 1815),
    ("конец 19 - 20-й века", 1890, 2000),
    ("19 - первая треть 20 в.", 1801, 1933),
    # Косвенные формы и составные конструкции.
    ("с конца 70-х гг. 19 в. по 20-е гг. 20 в.", 1877, 1929),
    ("к. 16 в. - 1917 г.", 1590, 1917),
    # Месяцы и сезоны — до года, точность отражена отдельно.
    ("лето 1918", 1918, 1918),
    ("ноябрь 1941 г.", 1941, 1941),
    # Именованные эпохи.
    ("советское время", 1917, 1991),
    # Даты в ISO из файла сражений.
    ("1445-07-16", 1445, 1445),
])
def test_parse_period_bounds(text, year_from, year_to):
    p = parse_period(text)
    assert (p.year_from, p.year_to) == (year_from, year_to), f"{text!r} -> {p}"


@pytest.mark.parametrize("text", ["-", "", None, "неизвестно", "nan"])
def test_unknown_periods(text):
    p = parse_period(text)
    assert not p.ok
    assert p.precision == "unknown"


@pytest.mark.parametrize("text,precision", [
    ("1771 г.", "year"),
    ("1770-е гг.", "decade"),
    ("19 в.", "century"),
    ("конец 19 в.", "part"),
    ("советское время", "era"),
    ("ноябрь 1941 г.", "month"),
    ("лето 1918", "season"),
    ("1445-07-16", "day"),
])
def test_precision(text, precision):
    assert parse_period(text).precision == precision


@pytest.mark.parametrize("text", [
    "примерно 1872 г.", "около 1900 г.", "накануне 1905 г.", "сразу после 1812 г.",
])
def test_approx_flag(text):
    assert parse_period(text).approx is True


def test_period_never_inverted():
    """Начало интервала никогда не позже конца."""
    for text in ["1861 - 1919 гг.", "конец 18 - начало 19 в.", "15-18 вв.", "1850-60-е гг."]:
        p = parse_period(text)
        assert p.year_from <= p.year_to, text


def test_overlaps():
    p = parse_period("1880-е гг.")          # 1880..1889
    assert p.overlaps(1885, 1885)
    assert p.overlaps(1870, 1882)
    assert not p.overlaps(1890, 1900)
    assert not p.overlaps(1860, 1879)


@pytest.mark.parametrize("value,expected", [
    (1812, 1812), ("1812", 1812), (1812.0, 1812),
    ("1445-07-16", 1445), ("около 1900 года", 1900), (None, None), ("", None), ("нет", None),
])
def test_parse_year(value, expected):
    assert parse_year(value) == expected


def test_real_corpus_coverage():
    """На реальном корпусе файла разбирается не менее 95% значений.

    Порог намеренно ниже фактического результата: тест должен ловить регрессию,
    а не падать от каждой новой строки в данных.
    """
    raw = Path(__file__).resolve().parents[1] / "data" / "raw" / "bookplaces_data.xlsx"
    if not raw.exists():
        pytest.skip("нет исходного файла data/raw/bookplaces_data.xlsx")
    import pandas as pd

    values = (
        pd.read_excel(raw, sheet_name="Литературные места")["Период"]
        .dropna().astype(str).str.strip().unique()
    )
    parsed = sum(1 for v in values if parse_period(v).ok)
    assert parsed / len(values) >= 0.95, f"разобрано {parsed}/{len(values)}"
