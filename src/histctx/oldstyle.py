"""Старый стиль: дата григорианского календаря → дата юлианского.

До 14 февраля 1918 года метрическая книга в России датирована по юлианскому
календарю, а источники слоёв — каталог затмений, ряды ледостава — дают
григорианскую дату. Разница в 10–13 дней решает, в какой месяц попадает
событие и совпадает ли оно с записью о крещении. Слой, у которого дата
известна до дня, пишет оба стиля, и считается это в одном месте.

Перевод идёт через номер юлианского дня — целочисленно, без таблицы
«в XIX веке 12 дней»: на стыке веков таблица ошибается на сутки.
"""

from __future__ import annotations

import datetime as dt

MONTHS_GENITIVE = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                   "августа", "сентября", "октября", "ноября", "декабря")

# С этого дня в Советской России счёт григорианский: за 31 января 1918 года
# сразу шло 14 февраля.
SWITCH = dt.date(1918, 2, 14)


def julian_day_number(date: dt.date) -> int:
    """Номер юлианского дня (в полдень) для даты григорианского календаря."""
    a = (14 - date.month) // 12
    y = date.year + 4800 - a
    m = date.month + 12 * a - 3
    return date.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def old_style(date: dt.date) -> tuple[int, int, int]:
    """(год, месяц, день) по юлианскому календарю.

    Кортеж, а не `date`: 29 февраля 1900 года по старому стилю существует, а
    в григорианском `datetime.date` его нет.
    """
    c = julian_day_number(date) + 32082
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1


def format_ru(year: int, month: int, day: int, *, with_year: bool = True) -> str:
    text = f"{day} {MONTHS_GENITIVE[month - 1]}"
    return f"{text} {year} года" if with_year else text


def both_styles(date: dt.date, *, russia: bool = True) -> str:
    """«19 августа 1887 года (7 августа ст. ст.)»; после перехода — одна дата."""
    text = format_ru(date.year, date.month, date.day)
    if not russia or date >= SWITCH:
        return text
    year, month, day = old_style(date)
    return f"{text} ({format_ru(year, month, day, with_year=year != date.year)} ст. ст.)"
