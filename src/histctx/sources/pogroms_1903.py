"""Погромы 1903–1906 годов: таблица «From Kishineff to Bialystok» (AJYB, т. 8).

Зачем этот слой. Дата смерти в метрической книге раввината — «19 апреля
1903 года, Кишинёв», «18 октября 1905 года, Одесса», «1 июня 1906 года,
Белосток» — объясняется одной строкой: в этот день в городе был погром. Тот
же день объясняет и обрыв записей, и отъезд семьи: волна 1903–1906 годов —
главная причина еврейской эмиграции в Америку. Кураторское событие о
погромах знает перечень губерний; таблица называет город и день.

Источник. «From Kishineff to Bialystok: A Table of Pogroms from 1903 to 1906»
— American Jewish Year Book, т. 8 (5667, 1906–1907), с. 34–89, составитель
выпуска — Henrietta Szold, издатель — Jewish Publication Society of America.
Таблица: 254 погрома, у каждого номер, дата (месяц и день, «?» — день не
установлен), город и губерния в транслитерации 1906 года, население города и
еврейское население, ущерб («47 Jews killed; 424 wounded; 700 houses
burned …») и замечания составителя. Ниже таблицы — алфавитный указатель,
дополнительный список городов, где погромы были в ноябре 1905 года, но дата
или положение не установлены, и губернии с населением. Скан книги — на
archive.org (`americanjewishye0008henr`), таблица набрана заново на сайте
Museum of Family History; сборщик разбирает набранную таблицу, а
дополнительный список — текстовый слой скана.

Права. Книга 1906 года — общественное достояние в США. Перепечатка —
«Copyright © 2009 Museum of Family History»: из неё берутся только данные
книги — место, дата, числа, — а ссылка в каждой записи ведёт на скан
(первая страница таблицы, с. 38). Строки ущерба и замечаний — текст 1906
года — идут в `extra` как есть, по-английски.

Даты. Составитель сам предупреждает, что старый и новый стиль в газетах
перемешаны и одно событие могло попасть в таблицу дважды; по сверке
с известными датами (Кишинёв — 6–7 апреля по старому стилю, в таблице
«April 19»; Белосток — 1 июня, в таблице «June 14») таблица в основном
пишет новый стиль. Дата остаётся как напечатана (`period_raw`), «?» в дне —
точность `month`, «? ?» — `year`. Записи дополнительного списка — ноябрь
1905 года с пометкой `date_approx`.

Где запись на карте. Точка — город погрома (`confidence = place_level`).
Город ищется по русскому названию своего времени (словарь `TOWNS_RU`,
1906 → 1905 по-русски, с нынешним названием для переименованных) в
Викиданных и по латинскому написанию — в вариантах названий GeoNames, и в
обоих случаях — только внутри губернии 1897 года, названной таблицей.
Город, которого так найти не удалось, остаётся без точки, но с губернией.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..geo import haversine_km
from ..net import USER_AGENT
from ..schema import ContextRecord, LayerSpec

TABLE_URL = "https://www.museumoffamilyhistory.com/ajc-yb-v08-pogroms.htm"
SCAN_ID = "americanjewishye0008henr"
SCAN_URL = f"https://archive.org/details/{SCAN_ID}"
# Первая страница таблицы в скане: с. 38 (статья начинается на с. 34).
TABLE_PAGE_URL = f"{SCAN_URL}/page/38/mode/1up"
TEXT_URL = f"https://archive.org/download/{SCAN_ID}/{SCAN_ID}_djvu.txt"

CITATION = (
    "«From Kishineff to Bialystok: A Table of Pogroms from 1903 to 1906». American Jewish "
    "Year Book, vol. 8 (5667, 1906–1907), pp. 34–89. Philadelphia: Jewish Publication "
    "Society of America, 1906"
)

LICENSE = (
    "книга 1906 года — общественное достояние в США; набранная таблица на сайте Museum of "
    "Family History — «Copyright © 2009»: из неё взяты только данные книги (место, дата, "
    "числа), ссылка ведёт на скан книги на archive.org"
)

POGROMS_1903 = LayerSpec(
    slug="pogroms_1903",
    title="Погромы 1903–1906 годов",
    group="hardship",
    source=("«A Table of Pogroms from 1903 to 1906», American Jewish Year Book, т. 8 "
            "(1906); скан — archive.org, набор таблицы — Museum of Family History"),
    license=LICENSE,
    url=SCAN_URL,
    status="harvested",
    expected_rows=323,
    description=(
        "Погромы от Кишинёва 1903 года до Белостока 1906-го: город, день, губерния, "
        "население и еврейское население, убитые и раненые, разрушения — 254 строки "
        "таблицы 1906 года и дополнительный список городов ноября 1905 года. Отвечает, "
        "совпадает ли дата смерти или отъезда семьи с днём погрома в этом городе. "
        "Точка — город погрома."
    ),
)

YEARS = (1903, 1904, 1905, 1906)
EXPECTED_ROWS = 254

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "june": 6,
    "jun": 6, "july": 7, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11,
    "dec": 12,
}
MONTHS_RU = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
             7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
             12: "декабря"}
MONTHS_RU_NOM = {1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
                 7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь",
                 12: "декабрь"}


class PogromsError(RuntimeError):
    """Таблица не скачалась или устроена не так, как ожидает разбор."""


# --- скачивание -------------------------------------------------------------

def fetch(url: str, *, attempts: int = 5, pause: float = 3.0, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise PogromsError(f"{url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(pause * (attempt + 1))
    raise PogromsError(f"{url}: не скачалось за {attempts} попыток ({last})")


def cached(url: str, path: Path, *, refresh: bool = False) -> bytes:
    """Файл из кэша; нет его (или `refresh`) — скачивается и кладётся туда."""
    path = Path(path)
    if path.exists() and path.stat().st_size and not refresh:
        return path.read_bytes()
    data = fetch(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


# --- разбор таблицы -----------------------------------------------------------

@dataclass(frozen=True)
class Row:
    """Строка таблицы, как напечатана."""

    number: int
    year: int
    date_raw: str
    town: str
    gubernia: str
    population: Optional[int]
    jewish_population: Optional[int]
    damage: str
    remarks: str

    @property
    def month(self) -> Optional[int]:
        return parse_date(self.date_raw)[0]

    @property
    def day(self) -> Optional[int]:
        return parse_date(self.date_raw)[1]


def _cell(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def table_cells(page: str) -> list[list[str]]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I)
    return [[_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
            for r in rows]


def number(text: str) -> Optional[int]:
    """«147,962» → 147962; пусто и прочерк — None."""
    digits = re.sub(r"[,.\s]", "", text or "")
    return int(digits) if digits.isdigit() else None


_RE_DATE = re.compile(r"^\s*([A-Za-z?]+)\.?\s*(\d{1,2}|\?)?\s*$")


def parse_date(raw: str) -> tuple[Optional[int], Optional[int]]:
    """«April 19» → (4, 19); «Oct. ?» → (10, None); «Oct.26» → (10, 26); «? ?» → (None, None)."""
    text = (raw or "").replace("\xa0", " ").strip()
    m = _RE_DATE.match(text)
    if not m:
        return None, None
    month = MONTHS.get(m.group(1).lower().rstrip("."))
    day = int(m.group(2)) if m.group(2) and m.group(2).isdigit() else None
    if month is None:
        return None, None
    return month, day


def parse_table(raw: bytes) -> list[Row]:
    """Набранная таблица: строки «№ — дата — город — губерния — …» по годам.

    Год в таблице — отдельной строкой («1903», «1904» …) перед погромами этого
    года; у строки погрома девять ячеек, восьмая всегда пустая.
    """
    page = raw.decode("utf-8", errors="replace")
    out, year = [], None
    for cells in table_cells(page):
        if len(cells) < 9:
            continue
        if not cells[0] and cells[1] in {str(y) for y in YEARS}:
            year = int(cells[1])
            continue
        if not re.fullmatch(r"\d+", cells[0]):
            continue
        if year is None:
            raise PogromsError(f"строка № {cells[0]} стоит раньше первой строки года")
        out.append(Row(
            number=int(cells[0]), year=year, date_raw=cells[1], town=cells[2],
            gubernia=cells[3], population=number(cells[4]),
            jewish_population=number(cells[5]), damage=cells[6], remarks=cells[8],
        ))
    return out


def check_table(rows: list[Row]) -> list[str]:
    """Сверка с напечатанным: 254 строки подряд, годы 1903–1906, даты разбираются."""
    problems = []
    if len(rows) != EXPECTED_ROWS:
        problems.append(f"строк {len(rows)}, в книге {EXPECTED_ROWS}")
    numbers = [r.number for r in rows]
    if numbers != list(range(1, len(rows) + 1)):
        problems.append("номера строк идут не подряд")
    bad = [f"№ {r.number} «{r.date_raw}»" for r in rows
           if r.date_raw.strip() not in ("? ?", "?") and r.month is None]
    if bad:
        problems.append("даты не разобраны: " + ", ".join(bad))
    return problems


# --- дополнительный список (текстовый слой скана) ------------------------------

_SUPPLEMENT_HEAD = "SUPPLEMENTARY LIST OF TOWNS IN WHICH POGROMS"
_SUPPLEMENT_END = "THE GUBERNIAS IN WHICH POGROMS OCCURRED"


def parse_supplement(text: str) -> list[str]:
    """Города дополнительного списка (ноябрь 1905 года) — как распознаны в скане.

    Список набран в книге одним абзацем через запятую, с переносами
    («Kroy-\\nevez»); вводная фраза в скобках отбрасывается.
    """
    start = text.find(_SUPPLEMENT_HEAD)
    end = text.find(_SUPPLEMENT_END, start)
    if start < 0 or end < 0:
        raise PogromsError("в тексте скана нет дополнительного списка городов")
    block = text[start:end]
    block = block[block.find(")") + 1:] if ")" in block else block
    block = re.sub(r"-\s*\n\s*", "", block)          # перенос по слогам
    block = re.sub(r"\s+", " ", block)
    names = [n.strip(" .") for n in block.split(",")]
    return [n for n in names if n and not n.isdigit()]


# --- губернии и города ---------------------------------------------------------

# Губернии таблицы — к губерниям переписи 1897 года (`provinces_1897.geojson`).
# «Zhitomir» таблица ставит вместо Волыни (Житомир — губернский город),
# «Crimea» — вместо Таврической губернии.
GUBERNIAS = {
    "Arkhangelsk": "Архангельская губерния", "Baku": "Бакинская губерния",
    "Bessarabia": "Бессарабская губерния", "Crimea": "Таврическая губерния",
    "Curland": "Курляндская губерния", "District of the Don": "Земля войска Донского",
    "Ekaterinoslav": "Екатеринославская губерния", "Ekaterioslav": "Екатеринославская губерния",
    "Grodno": "Гродненская губерния", "Irkutsk": "Иркутская губерния",
    "Kalish": "Калишская губерния", "Kazan": "Казанская губерния",
    "Kherson": "Херсонская губерния", "Kielce": "Келецкая губерния",
    "Kiev": "Киевская губерния", "Kostroma": "Костромская губерния",
    "Kovno": "Ковенская губерния", "Kursk": "Курская губерния",
    "Lomza": "Ломжинская губерния", "Minsk": "Минская губерния",
    "Mohilev": "Могилевская губерния", "Nishni-Novgorod": "Нижегородская губерния",
    "Orel": "Орловская губерния", "Orenburg": "Оренбургская губерния",
    "Petrikov": "Петроковская губерния", "Plotsk": "Плоцкая губерния",
    "Podolia": "Подольская губерния", "Poltava": "Полтавская губерния",
    "Pskov": "Псковская губерния", "Radom": "Радомская губерния",
    "Ryazan": "Рязанская губерния", "Samara": "Самарская губерния",
    "Saratov": "Саратовская губерния", "Siedlce": "Седлецкая губерния",
    "Smolensk": "Смоленская губерния", "Taurida": "Таврическая губерния",
    "Tchernigov": "Черниговская губерния", "Tomsk": "Томская губерния",
    "Tula": "Тульская губерния", "Vilna": "Виленская губерния",
    "Vitebsk": "Витебская губерния", "Vladimir": "Владимирская губерния",
    "Volhynia": "Волынская губерния", "Volynia": "Волынская губерния",
    "Voronezh": "Воронежская губерния", "Vyatka": "Вятская губерния",
    "Warsaw": "Варшавская губерния", "Yaroslav": "Ярославская губерния",
    "Zhitomir": "Волынская губерния",
}

# Города таблицы — по-русски своего времени, и нынешнее название, если оно
# другое (по нему город ищется в Викиданных). Написания 1906 года, которые
# с уверенностью не опознаются, сюда не внесены: такой город ищется по
# латинице в GeoNames, а не найден — остаётся без точки.
TOWNS_RU: dict[str, tuple] = {
    "Akkerman": ("Аккерман", "Белгород-Днестровский"),
    "Alexandria": ("Александрия",), "Alexandrovsk": ("Александровск", "Запорожье"),
    "Amtchislav": ("Мстиславль",), "Ananiev": ("Ананьев",), "Arkhangelsk": ("Архангельск",),
    "Bakhmut": ("Бахмут",), "Baku": ("Баку",), "Balta": ("Балта",),
    "Bayramcha": ("Байрамча",), "Bender": ("Бендеры",), "Berditchev": ("Бердичев",),
    "Beresovka": ("Березовка",), "Berezna": ("Березна",), "Bershad": ("Бершадь",),
    "Bialystok": ("Белосток",), "Biela Tserkov": ("Белая Церковь",),
    "Birsula": ("Бирзула", "Подольск"), "Bogopol": ("Богополь", "Первомайск"),
    "Boguslav": ("Богуслав",), "Boyary": ("Бояры",),
    "Brest-Litovsk": ("Брест-Литовск", "Брест"), "Bryansk": ("Брянск",),
    "Bunitchi": ("Буничи",), "Bykhova": ("Быхов",), "Czeladz": ("Челядзь",),
    "Czenstochova": ("Ченстохов", "Ченстохова"), "Daragonovo": ("Дараганово",),
    "Diemer": ("Димер", "Дымер"), "Dikovka": ("Диковка",), "Dobrianka": ("Добрянка",),
    "Dusyaty": ("Дусяты", "Дусетос"), "Dvinsk": ("Двинск", "Даугавпилс"),
    "Ekaterinoslav": ("Екатеринослав", "Днепр"),
    "Elisabetgrad": ("Елисаветград", "Кропивницкий"), "Eupatoria": ("Евпатория",),
    "Gadiatch": ("Гадяч",), "Golta": ("Голта", "Первомайск"), "Gomel": ("Гомель",),
    "Gorki": ("Горки",), "Gorodishche": ("Городище",), "Gostomol": ("Гостомель",),
    "Gostynin": ("Гостынин",), "Irkutsk": ("Иркутск",), "Ismail": ("Измаил",),
    "Ivanitzy": ("Иваница",), "Ivanovo-Voznesensk": ("Иваново-Вознесенск", "Иваново"),
    "Juravitch": ("Журавичи",), "KISHINEFF": ("Кишинёв",), "Kishineff": ("Кишинёв",),
    "Kalarash": ("Калараш",), "Kamenetz-Podolsk": ("Каменец-Подольский",),
    "Kanev": ("Канев",), "Kazan": ("Казань",), "Kertch": ("Керчь",),
    "Kherson": ("Херсон",), "Khotimsk": ("Хотимск",), "Khotin": ("Хотин",),
    "Kielce": ("Кельцы",), "Kiev": ("Киев",), "Klintzy": ("Клинцы",),
    "Knyazhitza": ("Княжицы",), "Kostroma": ("Кострома",), "Kovel": ("Ковель",),
    "Kozeletz": ("Козелец",), "Kremenetz": ("Кременец",), "Krementchug": ("Кременчуг",),
    "Kriukov": ("Крюков", "Кременчуг"), "Krolevetz": ("Кролевец",), "Kroshna": ("Крошня",),
    "Kursk": ("Курск",), "Kutno": ("Кутно",), "Likhovka": ("Лиховка",), "Lodz": ("Лодзь",),
    "Lomza": ("Ломжа",), "Lovitch": ("Лович",), "Lugansk": ("Луганск",),
    # Макарьев Нижегородской губернии — ныне село Макарьево; город Макарьев
    # Костромской губернии в другой губернии и сюда не подойдёт.
    "Lyskovo": ("Лысково",), "Lyutsin": ("Люцин", "Лудза"),
    "Makariev": ("Макарьев", "Макарьево"),
    "Mardarovka": ("Мардаровка",), "Mariopol": ("Мариуполь",),
    "Melitopol": ("Мелитополь",), "Minsk": ("Минск",), "Mohilev": ("Могилёв",),
    "Nevel": ("Невель",), "Niezhin": ("Нежин",), "Nikolayev": ("Николаев",),
    "Nikopol": ("Никополь",), "Nosovka": ("Носовка",), "Nossovitch": ("Носовичи",),
    "Novgorod-Seversk": ("Новгород-Северский",),
    "Novo-Alexandrovsk": ("Ново-Александровск", "Зарасай"),
    "Novo-Vilaysk": ("Ново-Вилейск", "Новая Вильня", "Науйойи-Вильня"),
    "Novogeorgievsk": ("Новогеоргиевск",), "Novomoskovsk": ("Новомосковск",),
    "Novoradomsk": ("Новорадомск", "Радомско"), "Novosybhov": ("Новозыбков",),
    "Novotcherkask": ("Новочеркасск",), "Obukhov": ("Обухов",), "Odessa": ("Одесса",),
    "Okna": ("Окны",), "Olviopol": ("Ольвиополь", "Первомайск"), "Orel": ("Орёл",),
    "Orsha": ("Орша",), "Ovidiopol": ("Овидиополь",),
    "Parczev": ("Парчев",), "Petrikov": ("Петроков", "Пётркув-Трыбунальский"),
    "Pinczov": ("Пинчов",), "Pinsk": ("Пинск",), "Plotsk": ("Плоцк",),
    "Polotsk": ("Полоцк",), "Poltava": ("Полтава",), "Radomysl": ("Радомысль",),
    "Posin": ("Посинь", "Пасиене"), "Ostrov": ("Остров", "Остров-Мазовецка"),
    "Ostrovitz": ("Островец", "Островец-Свентокшиский"), "Stepenitz": ("Степанцы",),
    "Rakishek": ("Ракишки", "Рокишкис"), "Razdelnaya": ("Раздельная",),
    "Repka": ("Репки",), "Rezhitza": ("Режица", "Резекне"), "Riga": ("Рига",),
    "Rishkahn": ("Рышканы",), "Romny": ("Ромны",), "Rostov-on-Don": ("Ростов-на-Дону",),
    "Rovno": ("Ровно",), "Ryazan": ("Рязань",), "Samara": ("Самара",),
    "Saratov": ("Саратов",), "Semyanovka": ("Семёновка",), "Simferopol": ("Симферополь",),
    "Slonim": ("Слоним",), "Smiela": ("Смела",), "Smolensk": ("Смоленск",),
    "Soflevka": ("Софиевка",), "Sosnoviec": ("Сосновец",), "Srebny": ("Сребное",),
    "Starodub": ("Стародуб",), "Staroselzy": ("Старосельцы",), "Surazh": ("Сураж",),
    "Tchausy": ("Чаусы",), "Tchelyabinsk": ("Челябинск",), "Tcherikov": ("Чериков",),
    "Tchernigov": ("Чернигов",), "Tchetchersk": ("Чечерск",), "Tchudnov": ("Чуднов",),
    "Tchutchuleny": ("Чучулены",), "Theodosia": ("Феодосия",), "Tiraspol": ("Тирасполь",),
    "Tomsk": ("Томск",), "Troyanov": ("Троянов",), "Tula": ("Тула",),
    "Tultshin": ("Тульчин",), "Uman": ("Умань",), "Vasilikov": ("Васильков",),
    "Velikie-Luki": ("Великие Луки",), "Vesiely-Terny": ("Весёлые Терны",),
    "Vilkomir": ("Вилькомир", "Укмерге"), "Vilna": ("Вильна", "Вильнюс"),
    "Vinnitza": ("Винница",), "Vitebsk": ("Витебск",), "Vladimir": ("Владимир",),
    "Voronezh": ("Воронеж",), "Voronok": ("Воронок",), "Voronovka": ("Вороновка",),
    "Vyatka": ("Вятка", "Киров"), "Vyazma": ("Вязьма",), "Warsaw": ("Варшава",),
    "Yablonovka": ("Яблоновка",), "Yaroslav": ("Ярославль",), "Yartzev": ("Ярцево",),
    "Yegoryevsk": ("Егорьевск",), "Yenitchek": ("Геническ",), "Yuryevich": ("Юревичи",),
    "Yusovka": ("Юзовка", "Донецк"), "Zdunskaya-Volya": ("Здунская Воля",),
    "Zhitomir": ("Житомир",), "Zhmerinka": ("Жмеринка",), "Zolotonosha": ("Золотоноша",),
}

# Дополнительный список ноября 1905 года: губернии в нём нет, и город берётся,
# только если его можно назвать уверенно, — с губернией, в которой он лежал.
SUPPLEMENT_RU: dict[str, tuple] = {
    "Ataki": ("Атаки", "Бессарабская губерния"),
    "Dubrovna": ("Дубровна", "Могилевская губерния"),
    "Ekaterinburg": ("Екатеринбург", "Пермская губерния"),
    "Fursy": ("Фурсы", "Киевская губерния"),
    "Ganchesi": ("Ганчешты", "Бессарабская губерния"),
    "Grozny": ("Грозный", "Терская область"),
    "Kaluga": ("Калуга", "Калужская губерния"),
    "Kamenskye": ("Каменское", "Екатеринославская губерния"),
    "Krivoi-Rog": ("Кривой Рог", "Херсонская губерния"),
    "Kronstadt": ("Кронштадт", "Санкт-Петербургская губерния"),
    "Lozovia-Pavlovka": ("Лозово-Павловка", "Екатеринославская губерния"),
    "Mstislavl": ("Мстиславль", "Могилевская губерния"),
    "Nishni-Novgorod": ("Нижний Новгород", "Нижегородская губерния"),
    "Oboyany": ("Обоянь", "Курская губерния"),
    "Onikst": ("Аникщяй", "Ковенская губерния"),
    "Orgiev": ("Оргеев", "Бессарабская губерния"),
    "Priluki": ("Прилуки", "Полтавская губерния"),
    "Reval": ("Ревель", "Эстляндская губерния", "Таллин"),
    "Sebastopol": ("Севастополь", "Таврическая губерния"),
    "Sklov": ("Шклов", "Могилевская губерния"),
    "Strascheng": ("Страшены", "Бессарабская губерния"),
    "Strasheni": ("Страшены", "Бессарабская губерния"),
    "Sudzo": ("Суджа", "Курская губерния"),
    "Talsen": ("Тальсен", "Курляндская губерния", "Талси"),
    "Tiflis": ("Тифлис", "Тифлисская губерния", "Тбилиси"),
    "Tuckum": ("Туккум", "Курляндская губерния", "Тукумс"),
    "Ungeni": ("Унгены", "Бессарабская губерния"),
    "Unitscha": ("Унеча", "Черниговская губерния"),
    "Vladikavkas": ("Владикавказ", "Терская область"),
    "Zgierz": ("Згеж", "Петроковская губерния"),
    # Златополь Чигиринского уезда — ныне часть Новомиргорода; село с тем же
    # названием под Кривым Рогом — другое место.
    "Zlatopol": ("Златополь", "Киевская губерния", "Новомиргород"),
    "Zlynka": ("Злынка", "Черниговская губерния"),
}


# --- латиница: ключ сравнения ---------------------------------------------------

_CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґў",
                ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m",
                 "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch",
                 "", "y", "", "e", "yu", "ya", "i", "i", "e", "g", "u"]))

# Звуковые соответствия транслитераций 1906 года (английской, немецкой,
# польской) и нынешних: «tch» и «cz» — «ч», «w» и конечное «ff» — «в».
_SOUNDS = (
    ("shch", "S"), ("szcz", "S"), ("tsch", "C"), ("tch", "C"), ("sch", "S"), ("cz", "C"),
    ("ch", "C"), ("sz", "S"), ("sh", "S"), ("zh", "Z"), ("kh", "H"), ("ts", "c"),
    ("tz", "c"), ("ph", "f"), ("ff", "v"), ("w", "v"), ("j", "i"), ("y", "i"), ("h", "H"),
)


def latin(text: str) -> str:
    """Кириллица — в латиницу, у латиницы снимаются знаки (ł — l)."""
    s = (text or "").lower().replace("ł", "l")
    s = "".join(_CYR.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def skeleton(text: str) -> str:
    """Ключ сравнения написаний: согласные в звуковых классах, без гласных.

    «Kishineff», «Kishinev», «Kischinew» → одно и то же; «Smiela» и «Smila»
    — тоже. Ключ грубый намеренно: сравнение идёт только внутри губернии.
    """
    s = re.sub(r"[^a-z]", "", latin(text))
    for a, b in _SOUNDS:
        s = s.replace(a, b)
    # Двойные буквы сводятся до выброса гласных, а не после: иначе
    # «Tatarinovka» (т-т-р-н-в-к) совпала бы с «Troyanovka» (т-р-н-в-к).
    s = re.sub(r"(.)\1+", r"\1", s)
    return re.sub(r"[aeiouy]", "", s)


# --- места: кандидаты и выбор ------------------------------------------------------

@dataclass
class Place:
    """Кандидат в точку города: объект Викиданных или место GeoNames."""

    source: str          # «wikidata» | «geonames»
    ident: str
    title: str
    lat: float
    lon: float
    population: int = 0
    town: bool = False
    names: list = field(default_factory=list)

    @property
    def coord_source(self) -> str:
        return f"{'Викиданные' if self.source == 'wikidata' else 'GeoNames'} {self.ident}"


def geonames_places(features: Iterable[dict], variants: Optional[dict] = None) -> list[Place]:
    """Слой `settlements` с написаниями из `name_variants.json`."""
    variants = variants or {}
    out = []
    for feat in features:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        gid = str(props.get("source_id") or "")
        if len(coords) < 2 or not gid:
            continue
        extra = props.get("extra") or {}
        pop = int(extra.get("population_modern") or 0)
        names = [props.get("title") or "", extra.get("name_latin") or ""]
        names += (variants.get(gid) or {}).get("names") or []
        out.append(Place("geonames", gid, props.get("title") or "", float(coords[1]),
                         float(coords[0]), pop, pop >= 5000, [n for n in names if n]))
    return out


def skeleton_index(places: Iterable[Place]) -> dict[str, list[Place]]:
    out: dict[str, list[Place]] = {}
    for place in places:
        for key in {skeleton(n) for n in place.names}:
            if len(key) >= 2:
                out.setdefault(key, []).append(place)
    return out


_RE_POINT = re.compile(r"Point\(([-\d.eE]+)\s+([-\d.eE]+)\)")
_RE_TOWN = re.compile(r"(?:^|\s)город(?:\s|$)|посёлок городского типа|местечко|столица|"
                      r"административный центр")
SETTLEMENT_WORDS = ("город", "посёлок", "поселок", "село", "деревня", "станица", "местечко",
                    "населённый пункт", "населенный пункт", "хутор", "агрогородок",
                    "район города", "столица", "микрорайон", "исторический район")

# Государства, где лежат города таблицы: империя 1906 года в нынешних границах.
WD_COUNTRIES = ("Q159", "Q212", "Q184", "Q217", "Q37", "Q211", "Q191", "Q36", "Q227",
                "Q230", "Q399", "Q33")


def wikidata_query(names: Iterable[str], countries: Iterable[str] = WD_COUNTRIES) -> str:
    """Кандидаты по точному русскому названию: метка или другое название."""
    values = " ".join(f'"{n}"@ru' for n in names if '"' not in n)
    cvalues = " ".join(f"wd:{q}" for q in countries)
    return f"""SELECT ?name ?item ?coord ?typeLabel ?pop WHERE {{
  VALUES ?name {{ {values} }}
  {{ ?item rdfs:label ?name }} UNION {{ ?item skos:altLabel ?name }}
  ?item wdt:P17 ?country .
  VALUES ?country {{ {cvalues} }}
  ?item wdt:P625 ?coord .
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel .
             FILTER(LANG(?typeLabel) = "ru") }}
  OPTIONAL {{ ?item wdt:P1082 ?pop . }}
}}"""


def name_key(name: Optional[str]) -> str:
    """Ключ сравнения русских названий: без регистра, «ё», скобок и дефисов."""
    if not name:
        return ""
    s = name.lower().replace("ё", "е")
    s = re.sub(r"\([^()]*\)", " ", s)
    s = re.sub(r"[^а-яa-z0-9іїєґ]+", " ", s)
    return s.strip()


def wikidata_places(rows: Iterable[dict]) -> dict[str, list[Place]]:
    """Строки SPARQL — в кандидатов по искомому названию (`name_key`)."""
    by_item: dict[tuple[str, str], Place] = {}
    types: dict[tuple[str, str], set] = {}
    for row in rows:
        name = row.get("name", {}).get("value")
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        point = _RE_POINT.match(row.get("coord", {}).get("value", ""))
        if not name or not qid.startswith("Q") or not point:
            continue
        key = (name_key(name), qid)
        place = by_item.get(key)
        if place is None:
            place = Place("wikidata", qid, name, float(point.group(2)), float(point.group(1)))
            by_item[key] = place
            types[key] = set()
        t = row.get("typeLabel", {}).get("value")
        if t:
            types[key].add(t.lower())
        pop = row.get("pop", {}).get("value")
        if pop:
            try:
                place.population = max(place.population, int(float(pop)))
            except ValueError:
                pass
    out: dict[str, list[Place]] = {}
    for key, place in by_item.items():
        kinds = types[key]
        if kinds and not any(any(w in t for w in SETTLEMENT_WORDS) for t in kinds):
            continue
        place.town = any(_RE_TOWN.search(t) for t in kinds)
        out.setdefault(key[0], []).append(place)
    return out


def best(cands: list[Place]) -> Optional[Place]:
    """Город раньше села, Викиданные раньше GeoNames, больший раньше меньшего."""
    if not cands:
        return None
    return sorted(cands, key=lambda c: (not c.town, c.source != "wikidata",
                                        -c.population))[0]


@dataclass
class Placement:
    place: Optional[Place]
    how: str


def one_place(cands: list[Place], km: float = 15.0) -> Optional[Place]:
    """Кандидаты — одно место (все в `km` друг от друга)? Тогда лучший из них."""
    top = best(cands)
    if top and all(haversine_km(top.lat, top.lon, c.lat, c.lon) <= km for c in cands):
        return top
    return None


class Locator:
    """Поиск города: по русскому названию в Викиданных и по латинице в GeoNames,
    внутри названной губернии 1897 года.

    Полигоны губерний 1897 года грубые на реках-границах: Бендеры у них — в
    Херсонской губернии, Двинск — в Курляндской, Никополь — в Таврической. А
    таблица 1906 года сама ошибается в губернии (Рига — «Curland», Бердичев —
    «Volhynia»). Поэтому, если в самой губернии кандидата нет, берётся город у её
    края — в рамке губернии с запасом в полградуса, — и это записывается.
    Без губернии город берётся, только если кандидат один.
    """

    MARGIN = 0.5

    def __init__(self, provinces, wd: dict[str, list[Place]],
                 gn: dict[str, list[Place]]) -> None:
        self.provinces = provinces
        self.wd = wd
        self.gn = gn
        self._bounds = {name: bounds for name, _, bounds in getattr(provinces, "_areas", [])}

    def in_province(self, place: Place, province: Optional[str]) -> bool:
        return self.provinces.region_for(place.lat, place.lon) == province

    def near_province(self, place: Place, province: str, margin: Optional[float] = None) -> bool:
        """Точка в рамке губернии, расширенной на `margin` градуса."""
        bounds = self._bounds.get(province)
        if not bounds:
            return False
        lon_min, lat_min, lon_max, lat_max = bounds
        m = self.MARGIN if margin is None else margin
        return lon_min - m <= place.lon <= lon_max + m and lat_min - m <= place.lat <= lat_max + m

    def locate(self, names_ru: Iterable[str], latin_names: Iterable[str],
               province: Optional[str]) -> Placement:
        names_ru, latin_names = list(names_ru), list(latin_names)
        if not province:
            for name in names_ru:
                found = one_place(self.wd.get(name_key(name), []))
                if found:
                    return Placement(found, f"Викиданные, «{name}», единственный кандидат")
            return Placement(None, "не найден: губерния не названа, а кандидатов несколько")
        for name in names_ru:
            cands = [c for c in self.wd.get(name_key(name), []) if self.in_province(c, province)]
            if cands:
                return Placement(best(cands), f"Викиданные, «{name}»")
        for name in latin_names:
            cands = [c for c in self.gn.get(skeleton(name), []) if self.in_province(c, province)]
            if cands:
                return Placement(best(cands), f"GeoNames по написанию «{name}»")
        # У края губернии: город раньше села, внутри рамки губернии раньше
        # полосы запаса; село берётся, только если кандидат у края один.
        near = [(name, c) for name in names_ru for c in self.wd.get(name_key(name), [])
                if self.near_province(c, province)]
        if near:
            towns = [(n, c) for n, c in near if c.town]
            pool = towns or near
            if towns or one_place([c for _, c in near]):
                name, found = sorted(pool, key=lambda nc: (
                    not self.near_province(nc[1], province, 0.0), -nc[1].population))[0]
                return Placement(found, f"Викиданные, «{name}», у края губернии")
        return Placement(None, "не найден")


def lookup_names() -> list[str]:
    """Все русские названия, по которым города ищутся в Викиданных."""
    out = set()
    for names in TOWNS_RU.values():
        out.update(names)
    for entry in SUPPLEMENT_RU.values():
        out.add(entry[0])
        out.update(entry[2:])
    return sorted(out)


# --- записи --------------------------------------------------------------------

_RE_KILLED = re.compile(r"(\d[\d,]*)\s+(?:Jews\s+|persons\s+|people\s+)?(?:were\s+)?killed", re.I)
_RE_WOUNDED = re.compile(r"(\d[\d,]*)\s+(?:Jews\s+|persons\s+|people\s+)?(?:were\s+)?"
                         r"(?:wounded|injured)", re.I)


def casualties(damage: str) -> tuple[Optional[int], Optional[int]]:
    """Убитые и раненые из строки ущерба: «47 Jews killed; 424 wounded» → (47, 424)."""
    k = _RE_KILLED.search(damage or "")
    w = _RE_WOUNDED.search(damage or "")
    return (number(k.group(1)) if k else None, number(w.group(1)) if w else None)


def human_date(year: int, month: Optional[int], day: Optional[int]) -> str:
    if month and day:
        return f"{day} {MONTHS_RU[month]} {year} года"
    if month:
        return f"{MONTHS_RU_NOM[month]} {year} года"
    return f"{year} год"


def precision(month: Optional[int], day: Optional[int]) -> str:
    return "day" if month and day else "month" if month else "year"


def row_names(row: Row) -> tuple[list[str], str]:
    """Русские названия для поиска и подпись города в заголовке."""
    entry = TOWNS_RU.get(row.town)
    if entry:
        return list(entry), entry[0]
    return [], row.town


def table_record(row: Row, place: Placement, spec: LayerSpec = POGROMS_1903) -> ContextRecord:
    names, label = row_names(row)
    province = GUBERNIAS.get(row.gubernia)
    killed, wounded = casualties(row.damage)
    month, day = row.month, row.day
    bits = [f"Погром {human_date(row.year, month, day)}"]
    if killed is not None:
        bits.append(f"убито {killed}")
    if wounded is not None:
        bits.append(f"ранено {wounded}")
    summary = ", ".join(bits)
    if row.population:
        # Разряды — пробелом; заменять запятые во всей строке нельзя: вместе с
        # разделителем тысяч пропала бы и запятая перед «евреев».
        summary += f"; население города {row.population:,}".replace(",", " ")
        if row.jewish_population:
            summary += ", евреев " + f"{row.jewish_population:,}".replace(",", " ")
    summary += f". Таблица American Jewish Year Book, т. 8, строка № {row.number}"
    cand = place.place
    extra = {
        "table_number": row.number,
        "town_1906": row.town,
        "gubernia_1906": row.gubernia or None,
        "population_1906_table": row.population,
        "jewish_population": row.jewish_population,
        "killed": killed,
        "wounded": wounded,
        "damage_en": row.damage or None,
        "remarks_en": row.remarks or None,
        "modern_name": names[1] if len(names) > 1 else None,
        "place_match": place.how,
        "coord_source": cand.coord_source if cand else None,
        "reprint_url": TABLE_URL,
    }
    return spec.new_record(
        title=f"Погром — {label}, {row.year}",
        category="погром",
        lat=round(cand.lat, 6) if cand else None,
        lon=round(cand.lon, 6) if cand else None,
        place_text=", ".join(p for p in (row.town, row.gubernia) if p),
        region=province,
        year_from=row.year, year_to=row.year,
        date_precision=precision(month, day),
        period_raw=f"{row.date_raw} {row.year}",
        work="Погромы 1903–1906 годов",
        summary=summary,
        url=TABLE_PAGE_URL,
        source_id=f"ajyb8:{row.number}",
        confidence="place_level" if cand else "no_coords",
        extra={k: v for k, v in extra.items() if v is not None},
    )


def supplement_record(name: str, place: Placement,
                      spec: LayerSpec = POGROMS_1903) -> ContextRecord:
    entry = SUPPLEMENT_RU.get(name)
    label = entry[0] if entry else name
    province = entry[1] if entry else None
    cand = place.place
    extra = {
        "town_1906": name,
        "list": "дополнительный список: ноябрь 1905 года, дата или положение не установлены",
        "modern_name": entry[2] if entry and len(entry) > 2 else None,
        "place_match": place.how,
        "coord_source": cand.coord_source if cand else None,
        "reprint_url": TABLE_URL,
    }
    return spec.new_record(
        title=f"Погром — {label}, ноябрь 1905",
        category="погром, дата или положение не установлены составителем",
        lat=round(cand.lat, 6) if cand else None,
        lon=round(cand.lon, 6) if cand else None,
        place_text=name,
        region=province,
        year_from=1905, year_to=1905,
        date_precision="month", date_approx=True,
        period_raw="November, 1905 (Supplementary list)",
        work="Погромы 1903–1906 годов",
        summary=("Погром в ноябре 1905 года по дополнительному списку American Jewish Year "
                 "Book, т. 8: составитель не установил дня или положения города"),
        url=TABLE_PAGE_URL,
        source_id=f"ajyb8:suppl:{name}",
        confidence="place_level" if cand else "no_coords",
        extra={k: v for k, v in extra.items() if v is not None},
    )


def build_records(rows: list[Row], supplement: list[str], locator: Locator) -> list[ContextRecord]:
    out = []
    for row in rows:
        names, _ = row_names(row)
        place = locator.locate(names, [row.town], GUBERNIAS.get(row.gubernia))
        out.append(table_record(row, place))
    seen = set()
    for name in supplement:
        if name in seen:
            continue
        seen.add(name)
        entry = SUPPLEMENT_RU.get(name)
        if entry:
            place = locator.locate([entry[0], *entry[2:]], [name], entry[1])
        else:
            place = Placement(None, "дополнительный список: город уверенно не опознан")
        out.append(supplement_record(name, place))
    return out


def date_of(rec: ContextRecord) -> Optional[dt.date]:
    """День погрома, если он назван (для сверок и тестов)."""
    raw = rec.period_raw or ""
    m = re.match(r"^\s*([A-Za-z?]+)\.?\s*(\d{1,2})\s+(\d{4})", raw)
    if not m or not MONTHS.get(m.group(1).lower()):
        return None
    return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
