"""Границы государств 1886–1960 по всему миру (CShapes 2.0, ETH Zurich).

Зачем этот слой. Губернии и уезды (`admin_gis.py`, `ristat.py`) отвечают, где
человек жил внутри страны. Этот слой отвечает на вопрос уровнем выше:
гражданином какого государства он при этом был. Для западных губерний вопрос
не праздный — Вильно, Ковно, Гродно, Кишинёв и Львов за одну жизнь меняли
государство по три раза, и от ответа зависит, в архиве какой нынешней страны
лежит метрическая книга.

Почему весь мир. Первая редакция слоя брала только государства, заходящие
территорией в охват РИ/СССР, — 46 из 226. Но родословная не кончается на
границе империи: уезжали в Америку и Палестину, служили в Порт-Артуре и
Маньчжурии, возвращались из Франции и Германии, а запись о венчании в
Буэнос-Айресе или рождении в Харбине — такой же факт на карте. Отвечать на
вопрос «чья это земля» слой должен для любой точки, а не только для своей.
Поэтому с ноября 2026 года берётся весь мир: 591 период 226 государств и
зависимых территорий.

Колонии и чья колония. Набор рисует не только независимые государства, но и
зависимые территории — колонии, протектораты, подмандатные и оккупированные
земли, всего 336 периодов из 591. Называет он их **именем нынешнего
государства-преемника**: «Ghana» в 1886 году — это Золотой Берег, «Tanzania
(Tanganyika)» в 1891-м — Германская Восточная Африка, «Indonesia» —
Нидерландская Ост-Индия. Исторического названия у колонии в наборе нет, и
без статуса и владельца такая подпись вводила бы в заблуждение. Статус и
владельца шейпфайл не несёт, они лежат в R-пакете того же набора
(`cshapes_2.0.tar.gz` на том же сайте, поля `status` и `owner` в
`cshapes_2_gw.topojson.xz`): 710 периодов, по одному на период шейпфайла,
сшиваются по номеру Gleditsch — Ward и датам начала и конца без остатка.
Так у Бухары и Хивы появляется то, чего им не хватало и в первой редакции, —
протекторат России, у Аляски — территория США, у ГДР и Северной Кореи
1945–1949 годов — советская оккупация.

Данные того же порядка точности, что и события: граница здесь меняется не
«примерно тогда-то», а по дате. У России в наборе 17 периодов, попадающих в
рамку слоя, и по ним читается вся хронология: Портсмутский мир (05.09.1905),
протекторат над Урянхайским краем (17.04.1914), Брестский мир (03.03.1918),
перенос столицы в Москву (11.03.1918), присоединения 1940 года, май и август
1945-го. Территории меньше 10 000 км² набор не рисует отдельно (так в его
правилах кодирования): Квантунской области и полосы КВЖД в нём нет.

Права. Набор под **CC BY-NC-SA 4.0** — некоммерческая лицензия с указанием
авторства. Проект некоммерческий, это решение принято и записано в каталоге
(`docs/CATALOG.md`, раздел «Каталог открыт»), поэтому полигоны выгружаются
целиком, а не подменяются ссылкой. Цитата авторов и ссылка на набор
проставляются в выходной файл — этого требует и лицензия, и условие 4
(проверяемость). R-пакет — под GPL (≥ 2), но берутся из него не код, а два
факта о каждом периоде: статус и владелец.

Доступность. Домен `icr.ethz.ch` отвечает, но соединение рвётся с
`Connection reset by peer` примерно на двух запросах из трёх — сбрасывается
именно скачивание, страница набора при этом открывается. Разница между
«источник исчез» и «источник огрызается» здесь ровно одна: повтор. Поэтому
скачивание идёт с несколькими попытками, и это не украшение, а условие
работоспособности сбора.

На выходе — GeoJSON с полигонами в `data/out/boundaries/`: к схеме контекста
границы не приводятся, это подложка карты (`docs/HARVEST.md`, раздел
«Границы»), ровно как у `ristat.py`. Записей слой не даёт ни одной.

Что отбирается. Из 710 периодов набора — те, что попадают в рамку слоя по
времени (1886–1960). Прежний отбор по охвату РИ/СССР остался проверкой
(`select(..., region_only=True)`, у сборщика — `--region`): им пользуются
сито рамки (`histctx.frame`) и отчёт о сборе. Полигоны не обрезаются никогда:
обрезанная граница — это уже не граница государства, а пересечение с рамкой,
и на карте она врала бы.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from http.client import HTTPException
from io import BytesIO
from typing import Iterable, Optional

from ..geo import in_bbox
from ..io_formats import feature_collection, write_feature_collection
from ..net import USER_AGENT
from ..schema import LayerSpec
from .shapefile import ShapefileError, features, read_dbf, read_shapes

DATASET_URL = "https://icr.ethz.ch/data/cshapes/"
ARCHIVE_URL = "https://icr.ethz.ch/data/cshapes/CShapes-2.0.zip"

# R-пакет набора: в нём те же 710 периодов, но со статусом и владельцем.
# Пакет не менялся с 2021 года (на сервере — от 31.08.2024); размер и SHA-256
# сверены 04.11.2026. Другой пакет — это новые числа здесь, сверенные руками,
# а не молча подтянутые поля.
PACKAGE_URL = "https://icr.ethz.ch/data/cshapes/cshapes_2.0.tar.gz"
PACKAGE_MEMBER = "cshapes/inst/extdata/cshapes_2_gw.topojson.xz"
PACKAGE_SIZE = 4_181_760
PACKAGE_SHA256 = "6708b263224888c368aab136cdcae8a24c220bd07929af10f8bd69cf53634caa"


CITATION = (
    "Schvitz, Guy; Girardin, Luc; Rüegger, Seraina; Weidmann, Nils B.; "
    "Cederman, Lars-Erik; Gleditsch, Kristian Skrede. 2022. «Mapping the "
    "International System, 1886-2019: The CShapes 2.0 Dataset». Journal of "
    "Conflict Resolution 66(1): 144–161. CC BY-NC-SA 4.0"
)

# Рамка слоя. Нижняя граница — начало самого набора, верхняя взята из названия
# слоя: после 1960 года для генеалогии по РИ/СССР меняется уже не то, где
# человек жил, а то, как называется его страна сегодня.
YEAR_MIN, YEAR_MAX = 1886, 1960

ARCHIVE_MEMBERS = ("CShapes-2.0.shp", "CShapes-2.0.dbf")

# Номер России в кодировке Gleditsch — Ward. Отчёт о сборе показывает её
# хронологию, и опознавать её по названию нельзя: название переводится, а
# номер в наборе неизменен.
RUSSIA_GWCODE = 365

# Поля таблицы, без которых разбор бессмысленен. Проверяются до него: если
# ETH переделает набор, сбор должен остановиться, а не выдать пустой слой.
REQUIRED_FIELDS = ("cntry_name", "gwcode", "gwsdate", "gwedate", "gwsyear", "gweyear")

# Горизонт набора: 31.12.2019 в поле «конец периода» означает «границa дожила
# до конца данных», а не очередное её изменение. В рамку слоя это не попадает,
# но при чтении файла разница важна, поэтому такой конец помечается отдельно.
DATASET_END = "20191231"

# Статус периода в R-пакете набора. «N/A» стоит у Марокко 1904–1912 годов,
# между независимостью и протекторатом: набор статуса не называет, и слой
# не называет за него.
STATUS_RU = {
    "independent": "независимое государство",
    "colony": "колония",
    "protectorate": "протекторат",
    "mandate": "подмандатная территория",
    "occupied": "оккупированная территория",
    "N/A": "статус в наборе не указан",
}
INDEPENDENT = "independent"

# Владелец — номер Gleditsch — Ward государства-сюзерена. Два номера
# государствами не являются: 0 — Лига Наций (Данциг 1919–1938), 1 — ООН
# (Западный Ириан 1962–1963, за рамкой слоя).
OWNERS_SPECIAL = {0: "Лига Наций", 1: "ООН"}

STATE_BORDERS = LayerSpec(
    slug="state_borders",
    title="Границы государств 1886–1960",
    group="admin",
    source="CShapes 2.0, ETH Zurich (Schvitz, Girardin, Rüegger и др., 2022)",
    license=(
        "CC BY-NC-SA 4.0 — некоммерческая с указанием авторства; проект "
        "некоммерческий, поэтому годится. Цитата и ссылка — в выходном файле"
    ),
    description=(
        "Государственные границы и столицы по датам их изменения по всему "
        "миру: 591 период 226 государств и зависимых территорий, у колоний, "
        "протекторатов, подмандатных и оккупированных земель — статус и "
        "государство-владелец. Отвечает на вопрос, гражданином какой страны "
        "был предок в год записи, — для Вильно, Кишинёва и Львова, менявших "
        "государство по три раза, и для Харбина, Нью-Йорка и Буэнос-Айреса, "
        "куда уезжали."
    ),
    url=DATASET_URL,
    status="harvested",
    expected_rows=591,
    gives_records=False,
)

# Названия государств в наборе английские, и слой от этого читается хуже, чем
# мог бы. Словарь покрывает все 252 названия набора, а не только рамку слоя;
# для незнакомого названия в файл идёт английское как есть — лучше «Danzig»,
# чем выдуманный перевод. Тот же принцип, что у подписей столбцов в
# `admin_gis.py`. Колонии набор называет нынешним государством-преемником, и
# перевод это сохраняет: «Гана» в 1886 году — колония Великобритании, а
# историческое название в слой не дописывается. Варианты в скобках — из
# самого набора («Sri Lanka (Ceylon)»). Одно исключение: «Kamerun» набор пишет
# по-немецки ровно затем, чтобы отличить германскую колонию от «Cameroon»
# после 1919 года, и перевод это различие держит — «Германский Камерун».
NAMES_RU = {
    "Aden": "Аден",
    "Afghanistan": "Афганистан",
    "Alaska": "Аляска",
    "Albania": "Албания",
    "Algeria": "Алжир",
    "Angola": "Ангола",
    "Argentina": "Аргентина",
    "Armenia": "Армения",
    "Australia": "Австралия",
    "Austria": "Австрия",
    "Austria-Hungary": "Австро-Венгрия",
    "Azerbaijan": "Азербайджан",
    "Bahamas": "Багамские Острова",
    "Bahrain": "Бахрейн",
    "Bangladesh": "Бангладеш",
    "Barbados": "Барбадос",
    "Belarus (Byelorussia)": "Белоруссия",
    "Belgium": "Бельгия",
    "Belize": "Белиз",
    "Benin": "Бенин",
    "Bhutan": "Бутан",
    "Bokhara": "Бухарский эмират",
    "Bolivia": "Боливия",
    "Bosnia": "Босния",
    "Bosnia-Herzegovina": "Босния и Герцеговина",
    "Botswana": "Ботсвана",
    "Brazil": "Бразилия",
    "British Bechuanaland": "Британский Бечуаналенд",
    "British Cameroons": "Британский Камерун",
    "British Somaliland (Somaliland Republic)": "Британское Сомали (Сомалиленд)",
    "British Togoland": "Британский Того",
    "Brunei": "Бруней",
    "Bulgaria": "Болгария",
    "Burkina Faso (Upper Volta)": "Буркина-Фасо (Верхняя Вольта)",
    "Burundi": "Бурунди",
    "Cambodia (Kampuchea)": "Камбоджа (Кампучия)",
    "Cameroon": "Камерун",
    "Canada": "Канада",
    "Cape Colony": "Капская колония",
    "Cape Verde": "Кабо-Верде",
    "Central African Republic": "Центральноафриканская Республика",
    "Chad": "Чад",
    "Chile": "Чили",
    "China": "Китай",
    "Colombia": "Колумбия",
    "Comoros": "Коморские Острова",
    "Congo": "Конго",
    "Congo, Democratic Republic of (Zaire)": "Демократическая Республика Конго (Заир)",
    "Costa Rica": "Коста-Рика",
    "Cote D'Ivoire": "Кот-д’Ивуар",
    "Croatia": "Хорватия",
    "Cuba": "Куба",
    "Cyprus": "Кипр",
    "Czech Republic": "Чехия",
    "Czechoslovakia": "Чехословакия",
    "Danzig": "Данциг, вольный город",
    "Denmark": "Дания",
    "Djibouti": "Джибути",
    "Dominican Republic": "Доминиканская Республика",
    "East Aden Protectorate": "Протекторат Восточный Аден",
    "East Timor": "Восточный Тимор",
    "Ecuador": "Эквадор",
    "Egypt": "Египет",
    "El Salvador": "Сальвадор",
    "Equatorial Guinea": "Экваториальная Гвинея",
    "Eritrea": "Эритрея",
    "Estonia": "Эстония",
    "Ethiopia": "Эфиопия",
    "Federated Malay States": "Федерированные малайские государства",
    "Federation of Rhodesia and Nyasaland": "Федерация Родезии и Ньясаленда",
    "Federation of South Arabia": "Федерация Южной Аравии",
    "Fiji": "Фиджи",
    "Finland": "Финляндия",
    "France": "Франция",
    "French Guyana": "Французская Гвиана",
    "French Polynesia": "Французская Полинезия",
    "French West Africa": "Французская Западная Африка",
    "Gabon": "Габон",
    "Gambia": "Гамбия",
    "Gaza": "Сектор Газа",
    "Georgia": "Грузия",
    "German Democratic Republic": "Германская Демократическая Республика",
    "German Federal Republic": "Федеративная Республика Германия",
    "German Solomon Islands": "Германские Соломоновы Острова",
    "German Togoland": "Германский Того",
    "Germany (Prussia)": "Германия (Пруссия)",
    "Ghana": "Гана",
    "Greece": "Греция",
    "Guadeloupe": "Гваделупа",
    "Guatemala": "Гватемала",
    "Guinea": "Гвинея",
    "Guinea-Bissau": "Гвинея-Бисау",
    "Guyana": "Гайана",
    "Haiti": "Гаити",
    "Hawaii": "Гавайи",
    "Herzegovina": "Герцеговина",
    "Honduras": "Гондурас",
    "Hungary": "Венгрия",
    "Iceland": "Исландия",
    "India": "Индия",
    "Indonesia": "Индонезия",
    "Inini": "Инини",
    "Iran (Persia)": "Иран (Персия)",
    "Iraq": "Ирак",
    "Ireland": "Ирландия",
    "Israel": "Израиль",
    "Italian Somaliland": "Итальянское Сомали",
    "Italy/Sardinia": "Италия (Сардинское королевство)",
    "Jamaica": "Ямайка",
    "Jammu and Kashmir": "Джамму и Кашмир",
    "Japan": "Япония",
    "Jordan": "Иордания",
    "Kamerun": "Германский Камерун",
    "Kashmir (North, Azad)": "Кашмир (Азад Кашмир)",
    "Kazakhstan": "Казахстан",
    "Kenya": "Кения",
    "Khiva": "Хивинское ханство",
    "Korea": "Корея",
    "Korea, People's Republic of": "Корея (КНДР)",
    "Korea, Republic of": "Корея (Республика Корея)",
    "Kosovo": "Косово",
    "Kuwait": "Кувейт",
    "Kyrgyz Republic": "Киргизия",
    "Lagos": "Лагос",
    "Laos": "Лаос",
    "Latvia": "Латвия",
    "Lebanon": "Ливан",
    "Lesotho": "Лесото",
    "Liberia": "Либерия",
    "Libya": "Ливия",
    "Lithuania": "Литва",
    "Luxembourg": "Люксембург",
    "Macedonia (FYROM/North Macedonia)": "Македония (Северная Македония)",
    "Madagascar (Malagasy)": "Мадагаскар (Малагасийская Республика)",
    "Malawi": "Малави",
    "Malaysia": "Малайзия",
    "Maldives": "Мальдивы",
    "Mali": "Мали",
    "Malta": "Мальта",
    "Martinique": "Мартиника",
    "Mauritania": "Мавритания",
    "Mauritius": "Маврикий",
    "Mexico": "Мексика",
    "Moldova": "Молдавия",
    "Mongolia": "Монголия",
    "Montenegro": "Черногория",
    "Morocco": "Марокко",
    "Mozambique": "Мозамбик",
    "Myanmar (Burma)": "Мьянма (Бирма)",
    "Namibia": "Намибия",
    "Natal": "Наталь",
    "Nepal": "Непал",
    "Netherlands": "Нидерланды",
    "New Caledonia and Dependencies": "Новая Каледония с зависимыми территориями",
    "New Guinea (German New Guinea) (Kaiser Wilhelmsland)":
        "Новая Гвинея (Германская Новая Гвинея, Земля кайзера Вильгельма)",
    "New South Wales": "Новый Южный Уэльс",
    "New Zealand": "Новая Зеландия",
    "Newfoundland": "Ньюфаундленд",
    "Nicaragua": "Никарагуа",
    "Niger": "Нигер",
    "Nigeria": "Нигерия",
    "Northeastern Rhodesia": "Северо-Восточная Родезия",
    "Northern Nigeria": "Северная Нигерия",
    "Northwestern Rhodesia": "Северо-Западная Родезия",
    "Norway": "Норвегия",
    "Oil Rivers Protectorate": "Протекторат Ойл-Риверс",
    "Oman": "Оман",
    "Orange Free State": "Оранжевое Свободное государство",
    "Pahang": "Паханг",
    "Pakistan": "Пакистан",
    "Palestine": "Палестина",
    "Panama": "Панама",
    "Papua": "Папуа",
    "Papua New Guinea": "Папуа — Новая Гвинея",
    "Paraguay": "Парагвай",
    "Perak": "Перак",
    "Peru": "Перу",
    "Philippines": "Филиппины",
    "Poland": "Польша",
    "Portugal": "Португалия",
    "Puerto Rico": "Пуэрто-Рико",
    "Qatar": "Катар",
    "Queensland": "Квинсленд",
    "Reunion": "Реюньон",
    "Rumania": "Румыния",
    "Russia (Soviet Union)": "Россия (Советский Союз)",
    "Rwanda": "Руанда",
    "Rwanda-Urundi": "Руанда-Урунди",
    "Sabah (North Borneo)": "Сабах (Северное Борнео)",
    "Sarawak": "Саравак",
    "Saudi Arabia": "Саудовская Аравия",
    "Selangore": "Селангор",
    "Senegal": "Сенегал",
    "Serbia": "Сербия",
    "Sierra Leone": "Сьерра-Леоне",
    "Singapore": "Сингапур",
    "Slovakia": "Словакия",
    "Slovenia": "Словения",
    "Solomon Islands": "Соломоновы Острова",
    "Somalia": "Сомали",
    "South Africa": "Южная Африка",
    "South Australia": "Южная Австралия",
    "South Sudan": "Южный Судан",
    "Southern Nigeria": "Южная Нигерия",
    "Southern Sakhalin Island": "Южный Сахалин",
    "Southern zone of Spanish Morocco": "Южная зона Испанского Марокко",
    "Spain": "Испания",
    "Spanish Morocco": "Испанское Марокко",
    "Spanish Sahara": "Испанская Сахара",
    "Spanish West Africa": "Испанская Западная Африка",
    "Sri Lanka (Ceylon)": "Шри-Ланка (Цейлон)",
    "Straits Settlements": "Стрейтс-Сетлментс",
    "Sudan": "Судан",
    "Surinam": "Суринам",
    "Swaziland (Eswatini)": "Свазиленд (Эсватини)",
    "Sweden": "Швеция",
    "Switzerland": "Швейцария",
    "Syria": "Сирия",
    "Taiwan": "Тайвань",
    "Tajikistan": "Таджикистан",
    "Tanzania (Tanganyika)": "Танзания (Танганьика)",
    "Tasmania": "Тасмания",
    "Thailand": "Таиланд",
    "Tibet": "Тибет",
    "Togo": "Того",
    "Transvaal": "Трансвааль",
    "Trinidad and Tobago": "Тринидад и Тобаго",
    "Tunisia": "Тунис",
    "Turkey (Ottoman Empire)": "Турция (Османская империя)",
    "Turkmenistan": "Туркмения",
    "Uganda": "Уганда",
    "Ukraine": "Украина",
    "Unfederated Malay States": "Нефедерированные малайские государства",
    "United Arab Emirates": "Объединённые Арабские Эмираты",
    "United Kingdom": "Великобритания",
    "United States of America": "Соединённые Штаты Америки",
    "Uruguay": "Уругвай",
    "Uzbekistan": "Узбекистан",
    "Venezuela": "Венесуэла",
    "Victoria": "Виктория",
    "Vietnam (Annam/Cochin China/Tonkin)": "Вьетнам (Аннам, Кохинхина, Тонкин)",
    "Vietnam, Democratic Republic of": "Демократическая Республика Вьетнам",
    "Vietnam, Republic of": "Республика Вьетнам",
    "West Bank": "Западный берег реки Иордан",
    "West Irian (Dutch New Guinea)": "Западный Ириан (Нидерландская Новая Гвинея)",
    "Western Australia": "Западная Австралия",
    "Yemen (Arab Republic of Yemen)": "Йемен (Йеменская Арабская Республика)",
    "Yemen, People's Republic of": "Народная Республика Йемен",
    "Yugoslavia": "Югославия",
    "Zambia": "Замбия",
    "Zanzibar": "Занзибар",
    "Zimbabwe (Rhodesia)": "Зимбабве (Родезия)",
}


class CShapesError(RuntimeError):
    """Набор не скачался или пришёл не в том виде, какого мы ждём."""


def download(url: str = ARCHIVE_URL, *, timeout: int = 300, attempts: int = 5,
             pause: float = 2.0) -> bytes:
    """Скачивает файл набора, повторяя попытку при обрыве соединения.

    Повторы здесь обязательны: `icr.ethz.ch` рвёт скачивание чаще, чем отдаёт
    его с первого раза. HTTP-ответ с кодом ошибки, наоборот, не повторяется —
    404 от повтора не исправится, а от 403 повтор только навредит.

    Между попытками выдерживается растущая пауза. Долбить сервер, который и
    так рвёт соединение, — верный способ получить обрыв и в следующий раз:
    причиной сброса вполне может быть сама частота обращений.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total = max(1, attempts)
    last: Optional[Exception] = None
    for made in range(1, total + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise CShapesError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, HTTPException, OSError) as exc:
            last = exc
            if made < total and pause:
                time.sleep(pause * made)
    reason = getattr(last, "reason", last)
    raise CShapesError(
        f"{url}: соединение обрывается ({reason}); попыток сделано {total}"
    )


def read_archive(data: bytes) -> list[dict]:
    """Достаёт из zip-архива шейпфайл и сшивает геометрию с таблицей."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            missing = [m for m in ARCHIVE_MEMBERS if m not in names]
            if missing:
                raise CShapesError(
                    f"в архиве нет файлов {missing}; лежат: {sorted(names)}"
                )
            shp, dbf = (archive.read(m) for m in ARCHIVE_MEMBERS)
    except zipfile.BadZipFile as exc:
        raise CShapesError(f"скачанное не разбирается как zip ({exc})") from exc

    try:
        feats = features(read_shapes(shp), read_dbf(dbf))
    except ShapefileError as exc:
        raise CShapesError(f"шейпфайл не разбирается: {exc}") from exc
    check_fields(feats)
    return feats


def load(cache_dir, *, timeout: int = 300) -> list[dict]:
    """Периоды набора; скачанный архив остаётся в кэше.

    Набор весит 13 МБ и с версией 2.0 не меняется, поэтому качается один раз:
    при рвущемся соединении это ещё и способ не дёргать сервер лишний раз.

    В кэш архив кладётся только после того, как разобрался. Иначе оборванное
    скачивание отравило бы кэш навсегда: следующий запуск нашёл бы файл на
    месте, снова споткнулся о него и снова — а совет «просто запустите ещё
    раз» перестал бы работать.
    """
    path = cache_dir / "CShapes-2.0.zip"
    if path.exists():
        try:
            return read_archive(path.read_bytes())
        except CShapesError as exc:
            raise CShapesError(
                f"кэш повреждён: {exc}. Удалите {path} и запустите сбор снова."
            ) from exc
    data = download(timeout=timeout)
    feats = read_archive(data)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return feats


# --- статус и владелец из R-пакета -----------------------------------------

def period_key(gwcode, start, end) -> Optional[tuple[int, str, str]]:
    """Ключ периода: номер и даты «ГГГГММДД». В шейпфайле даты без дефисов,
    в R-пакете — с дефисами; ключ у обоих один."""
    try:
        code = int(gwcode)
    except (TypeError, ValueError):
        return None
    return code, str(start).replace("-", ""), str(end).replace("-", "")


def check_package(data: bytes) -> None:
    """Пакет тот, что сверен руками: размер и SHA-256. Иначе — остановка."""
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != PACKAGE_SIZE or digest != PACKAGE_SHA256:
        raise CShapesError(
            f"{PACKAGE_URL}: {len(data)} байт, SHA-256 {digest}; ожидалось "
            f"{PACKAGE_SIZE} байт, SHA-256 {PACKAGE_SHA256}. Пакет обновили — "
            f"сверьте поля status и owner и обновите числа в sources/cshapes.py"
        )


def read_attributes(data: bytes) -> dict[tuple, dict]:
    """Статус, владелец и определённость границы каждого периода из R-пакета.

    Из архива читается один файл и только в память: ни на диск, ни в путь,
    указанный самим архивом, ничего не распаковывается. Геометрия TopoJSON не
    разбирается вовсе — она загрублена под R, у шейпфайла она точнее.
    """
    try:
        with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
            member = archive.extractfile(PACKAGE_MEMBER)
            if member is None:
                raise KeyError(PACKAGE_MEMBER)
            topo = json.loads(lzma.decompress(member.read()))
    except KeyError as exc:
        raise CShapesError(f"в пакете нет {PACKAGE_MEMBER}") from exc
    except (tarfile.TarError, lzma.LZMAError, OSError, ValueError) as exc:
        raise CShapesError(f"пакет не разбирается: {exc}") from exc

    objects = topo.get("objects") if isinstance(topo, dict) else None
    if not objects:
        raise CShapesError("в TopoJSON пакета нет ни одного объекта")
    out: dict[tuple, dict] = {}
    for obj in objects.values():
        for geometry in obj.get("geometries") or []:
            props = geometry.get("properties") or {}
            key = period_key(props.get("gwcode"), props.get("start"), props.get("end"))
            if key is None or "status" not in props:
                continue
            out[key] = {"status": props.get("status"),
                        "owner": _int(props.get("owner")),
                        "b_def": _int(props.get("b_def"))}
    if not out:
        raise CShapesError("в TopoJSON пакета нет полей status и owner")
    return out


def load_attributes(cache_dir, *, timeout: int = 300) -> dict[tuple, dict]:
    """Статус и владелец по периодам; пакет кладётся в кэш после сверки."""
    path = cache_dir / "cshapes_2.0.tar.gz"
    if path.exists():
        data = path.read_bytes()
        try:
            check_package(data)
        except CShapesError as exc:
            raise CShapesError(
                f"кэш не тот: {exc}. Удалите {path} и запустите сбор снова."
            ) from exc
        return read_attributes(data)
    data = download(PACKAGE_URL, timeout=timeout)
    check_package(data)
    attrs = read_attributes(data)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return attrs


def unmatched(feats: Iterable[dict], attrs: dict) -> list[tuple]:
    """Периоды шейпфайла, которым в пакете не нашлось статуса.

    Пусто — сшивка без остатка, как на версии 2.0 (710 из 710). Не пусто —
    наборы разошлись, и слой со статусом у части стран врал бы молчанием у
    остальных: сборщик останавливается.
    """
    out = []
    for feature in feats:
        props = feature.get("properties") or {}
        key = period_key(props.get("gwcode"), props.get("gwsdate"), props.get("gwedate"))
        if key is None or key not in attrs:
            out.append(key or (props.get("cntry_name"),))
    return out


def owner_index(feats: Iterable[dict]) -> dict[int, list[tuple[str, str, str]]]:
    """Номер государства → его названия по периодам: (начало, конец, название).

    Владельца набор пишет номером, а название у номера со временем меняется
    (Германия под номером 255 — «Germany (Prussia)»), поэтому название берётся
    на дату начала периода колонии, а не первое попавшееся.
    """
    index: dict[int, list[tuple[str, str, str]]] = {}
    for feature in feats:
        props = feature.get("properties") or {}
        key = period_key(props.get("gwcode"), props.get("gwsdate"), props.get("gwedate"))
        name = props.get("cntry_name")
        if key and name:
            index.setdefault(key[0], []).append((key[1], key[2], name))
    return index


def owner_name(code: Optional[int], date: Optional[str],
               index: dict[int, list[tuple[str, str, str]]]) -> Optional[str]:
    """Название государства-владельца по-русски на дату «ГГГГММДД»."""
    if code is None:
        return None
    if code in OWNERS_SPECIAL:
        return OWNERS_SPECIAL[code]
    periods = index.get(code) or []
    for start, end, name in periods:
        if date and start <= date <= end:
            return NAMES_RU.get(name, name)
    if periods:
        name = periods[0][2]
        return NAMES_RU.get(name, name)
    return None


# --- отбор и запись ----------------------------------------------------------

def check_fields(feats: list[dict]) -> None:
    """Проверяет, что в таблице есть поля, на которых держится разбор.

    Смотрит на все записи, а не на первую: пустое значение до свойств не
    доезжает (`shapefile.features` выбрасывает None), и одна незаполненная
    клетка в первой строке выглядела бы как переделанный набор.
    """
    if not feats:
        raise CShapesError("в наборе нет ни одного полигона")
    keys = set()
    for feature in feats:
        keys.update(feature.get("properties") or {})
    missing = [f for f in REQUIRED_FIELDS if f not in keys]
    if missing:
        raise CShapesError(
            f"в таблице набора нет обязательных полей {missing}; пришли: "
            f"{sorted(keys)}. Проверьте {DATASET_URL} и поправьте разбор."
        )


def rings(geometry: Optional[dict]) -> list[list]:
    """Все кольца полигона одним списком — и внешние, и дырки."""
    if not isinstance(geometry, dict):
        return []
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return list(coords)
    if geometry.get("type") == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def touches_region(geometry: Optional[dict]) -> bool:
    """Заходит ли государство хоть одной точкой границы в охват РИ/СССР.

    Проверка по вершинам, а не по описанному прямоугольнику: у России
    прямоугольник растянут от −180° до 180° (Чукотка за меридианом), и по нему
    в отбор попало бы полмира.
    """
    return any(in_bbox(lat, lon) for ring in rings(geometry) for lon, lat in ring)


def overlaps(props: dict, year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> bool:
    """Пересекается ли период существования границы с рамкой слоя."""
    start, end = props.get("gwsyear"), props.get("gweyear")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return start <= year_max and end >= year_min


def select(feats: Iterable[dict], *, attrs: Optional[dict] = None,
           year_min: int = YEAR_MIN, year_max: int = YEAR_MAX,
           region_only: bool = False) -> list[dict]:
    """Периоды в рамке слоя, приведённые к подписям, понятным читателю файла.

    По умолчанию — весь мир; `region_only` оставляет прежний отбор по охвату
    РИ/СССР. Владелец ищется по всему набору, а не по отобранному: колония
    в охват заходит, а её метрополия — нет (Франция и Великобритания).
    """
    feats = list(feats)
    index = owner_index(feats)
    out = []
    for feature in feats:
        props = feature.get("properties") or {}
        if not overlaps(props, year_min, year_max):
            continue
        if region_only and not touches_region(feature.get("geometry")):
            continue
        key = period_key(props.get("gwcode"), props.get("gwsdate"), props.get("gwedate"))
        extra = (attrs or {}).get(key) if key else None
        out.append(boundary(feature, extra, index))
    return out


def boundary(feature: dict, extra: Optional[dict] = None,
             index: Optional[dict] = None) -> dict:
    """Один период с русским названием, датами, столицей, статусом и владельцем.

    Даты набора сохраняются как есть, без обрезки по рамке слоя: период
    «1945–1991» на карте 1950 года всё равно отберётся по году, а подмена его
    конца на 1960-й была бы выдумкой про данные.

    Владелец пишется только у зависимой территории: у независимого
    государства набор ставит владельцем его самого, и повторять это в каждом
    из 253 периодов незачем. `border_defined = false` — граница в этот период
    проведена не на всём протяжении (так у многих колоний конца XIX века);
    линия на карте здесь — допущение набора, а не договор.
    """
    props = feature.get("properties") or {}
    name = props.get("cntry_name")
    date_from, date_to = _date(props.get("gwsdate")), _date(props.get("gwedate"))
    out = {
        "state": NAMES_RU.get(name, name),
        "state_en": name,
        "gwcode": props.get("gwcode"),
        "year_from": props.get("gwsyear"),
        "year_to": props.get("gweyear"),
        "date_from": date_from,
        "date_to": date_to,
        "capital": props.get("capname"),
        "caplat": props.get("caplat"),
        "caplon": props.get("caplong"),
    }
    if extra:
        status = extra.get("status")
        out["status"] = STATUS_RU.get(status, status)
        out["status_en"] = status
        owner = extra.get("owner")
        if status != INDEPENDENT and owner is not None and owner != props.get("gwcode"):
            out["owner"] = owner_name(owner, str(props.get("gwsdate") or ""), index or {})
            out["owner_gwcode"] = owner
        if extra.get("b_def") in (0, 1):
            out["border_defined"] = extra["b_def"] == 1
    if str(props.get("gwedate")) == DATASET_END:
        # Не изменение границы, а край данных: важно для того, кто станет
        # читать файл и увидит у полигона конец «2019».
        out["open_end"] = True
    return {
        "type": "Feature",
        "geometry": feature.get("geometry"),
        "properties": {k: v for k, v in out.items() if v is not None},
    }


def _date(value) -> Optional[str]:
    """«18860101» → «1886-01-01»; в таблице поле строковое, но бывает и число."""
    if value is None:
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"


def _int(value) -> Optional[int]:
    """Номер из пакета: «200» и 200 — одно и то же, пустое и «NA» — ничего."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def states(feats: Iterable[dict]) -> list[str]:
    """Государства отбора по-русски, по алфавиту — для отчёта о сборе."""
    return sorted({(f.get("properties") or {}).get("state") for f in feats
                   if (f.get("properties") or {}).get("state")})


def untranslated(feats: Iterable[dict]) -> list[str]:
    """Английские названия, которых нет в словаре: новая версия набора их добавит."""
    return sorted({(f.get("properties") or {}).get("state_en") for f in feats}
                  - set(NAMES_RU) - {None})


def collection(feats: list[dict], *, year_min: int = YEAR_MIN,
               year_max: int = YEAR_MAX) -> dict:
    return feature_collection(
        STATE_BORDERS.slug, feats,
        license=STATE_BORDERS.license, source=STATE_BORDERS.source,
        citation=CITATION, url=DATASET_URL,
        extra={"period": f"{year_min}–{year_max}", "coverage": "весь мир",
               "status_source": PACKAGE_URL},
    )


def write(collection_dict: dict, path) -> int:
    """Пишет коллекцию сжатым JSON: у 940 тысяч вершин пробелы — это мегабайты."""
    return write_feature_collection(collection_dict, path, compact=True)
