"""Границы государств 1600–1885 (Cliopatria, Seshat Global History Databank).

Зачем этот слой. CShapes (`cshapes.py`) отвечает, гражданином какого
государства был предок, но начинается с 1886 года — а ревизские сказки,
первые метрические книги и вся история западных губерний лежат раньше.
Вильно до 1795 года — Речь Посполитая, Бессарабия до 1812-го — Молдавское
княжество под Портой, Крым до 1783-го — ханство, Финляндия до 1809-го —
Швеция. Без этого слоя карта до 1886 года показывает губернии, но не
отвечает, чьё государство вокруг них и в архив какой страны идти.

Набор. Cliopatria — полигоны политий мира с 3400 года до н. э. по 2024 год,
около 14 тысяч строк. У строки — название, годы «с» и «по» включительно,
полигон и ссылки на Википедию и Викиданные: по ним запись проверяется
(условие 4). Шаг строк не постоянный: у России в рамке слоя 82 строки,
от года до десяти лет каждая, и по ним читаются Смута, Переяславская рада,
Ништадтский мир, все три раздела Речи Посполитой, Финляндия 1809 года и
продажа Аляски. Точность ниже, чем у CShapes: год, а не день, и полигон
снят с карт обзорного масштаба. Поэтому с 1886 года первенство за CShapes.

Права. **CC BY 4.0** — файл `LICENSE.md` в самом архиве и карточка записи на
Zenodo. Полигоны выгружаются целиком; цитата и ссылка на запись идут
в выходной файл.

Скачивание. Запись на Zenodo — архив репозитория на 299 МБ, из которых
сам набор — один вложенный zip на 46 МБ, остальное — сканы исходных карт.
До ноября 2026 года Zenodo отдавал файл из архива по отдельности
(`…/container/<путь>`); теперь этот адрес отвечает 403, а сам архив
(`…/content`) по-прежнему отдаётся кусками по заголовку Range. Сбор читает
по Range оглавление архива — оно в последних 128 КБ, один запрос, — сверяет
по нему размер и CRC32 набора с записанными в коде и забирает только его:
ещё три запроса по 16 МБ вместо 299 МБ целиком (`net.RangeFile`). Адрес
лежит под `/api/records/*/files`, который robots.txt Zenodo открывает явно;
карточку записи сбор не запрашивает, лицензия сверена по ней руками.

Что отбирается. Строки, пересекающиеся с рамкой 1600–1885 годов, — по всему
миру: 3 620 строк 424 политий. Первая редакция брала только те, чей полигон
хоть одной вершиной заходит в охват РИ/СССР, — 1 187 строк 121 политии; этот
отбор остался проверкой (`select(..., region_only=True)`, у сборщика —
`--region`). Мир нужен по той же причине, что у CShapes: родословная не
кончается на границе империи, а Cliopatria отвечает «чья земля» и для
Пенсильвании 1700 года, и для Бенгалии, и для Капской колонии. Полигоны не
обрезаются: обрезанная граница государства врала бы на карте. Годы строки
сохраняются как есть: у Российской империи последняя строка — 1885–1894, и
она остаётся такой, а пометка `continues_in` говорит, что с 1886 года та же
граница есть в `state_borders` по дням.

На выходе — GeoJSON в `data/out/boundaries/`: подложка карты, к схеме
контекста не приводится (`docs/HARVEST.md`, раздел «Границы»). Записей слой
не даёт ни одной.
"""

from __future__ import annotations

import json
import urllib.parse
import zipfile
import zlib
from pathlib import Path
from typing import Iterable, Optional

from ..io_formats import feature_collection, write_feature_collection
from ..net import RangeFile
from ..schema import LayerSpec
from .cshapes import STATE_BORDERS, touches_region

# Версия закреплена: у Cliopatria выходят новые версии, и полигоны в них
# правят. Новая версия — это новый RECORD_ID и новые размер и CRC ниже,
# сверенные руками, а не молча подтянутый «последний».
VERSION = "v0.2.1"
RECORD_ID = "23128623"
DOI = "10.5281/zenodo.23128623"
DOI_URL = f"https://doi.org/{DOI}"
REPO_URL = "https://github.com/Seshat-Global-History-Databank/cliopatria"
ARCHIVE_KEY = "Seshat-Global-History-Databank/cliopatria-v0.2.1.zip"
FILES_API = f"https://zenodo.org/api/records/{RECORD_ID}/files"
# Сам архив: отдаётся кусками по Range, из него читаются оглавление и набор.
ARCHIVE_URL = f"{FILES_API}/{ARCHIVE_KEY}/content"
MEMBER = "Seshat-Global-History-Databank-cliopatria-5f43337/cliopatria.geojson.zip"
# Сверено с перечнем содержимого архива 24.10.2026 и с оглавлением самого
# архива 04.11.2026 — числа те же.
MEMBER_SIZE = 46_005_176
MEMBER_CRC = 3_845_452_743
CACHE_NAME = "cliopatria-v0.2.1.geojson.zip"

CITATION = (
    "Bennett J. S., Mutch E., Tollefson A., Chalstrey E., Benam M., Cioni E., "
    "Reddish J., Zsambok J., Levine J., Cook C. J., Francois P., Hoyer D., "
    "Turchin P. «Cliopatria — A geospatial database of world-wide political "
    "entities from 3400BCE to 2024CE». Scientific Data 12, 247 (2025), "
    "doi:10.1038/s41597-025-04516-9; набор — "
    f"Chalstrey E., Bennett J. Cliopatria {VERSION}, Zenodo, doi:{DOI}. CC BY 4.0"
)

# Рамка слоя. Нижняя граница — начало XVII века: лента событий проекта
# начинается с 1619 года, а Смута нужна целиком. Верхняя — год до начала
# CShapes, который датирует границы по дням и с 1886 года точнее.
YEAR_MIN, YEAR_MAX = 1600, 1885

REQUIRED_FIELDS = ("Name", "FromYear", "ToYear", "Type", "Wikipedia", "Wikidata")

# Координаты в наборе — с точностью до миллионных долей градуса, а полигоны
# сняты с карт обзорного масштаба. Три знака — это сто метров, и они вдвое
# уменьшают файл, ничего не меняя в границе, которую можно увидеть.
COORD_DIGITS = 3

STATE_BORDERS_EARLY = LayerSpec(
    slug="state_borders_early",
    title="Границы государств 1600–1885",
    group="admin",
    source="Cliopatria (Seshat Global History Databank), Zenodo",
    license=(
        "CC BY 4.0 (LICENSE.md в архиве и карточка записи на Zenodo): брать "
        "можно всё, со ссылкой — цитата и ссылка в выходном файле"
    ),
    description=(
        "Государственные границы по годам до начала CShapes, по всему миру: "
        "3 620 строк 424 политий — Московское царство и империя, Речь "
        "Посполитая, Крымское ханство, Швеция, Порта, грузинские царства, "
        "казахские жузы и среднеазиатские ханства, а с ними германские "
        "княжества, колониальные владения в Америке, Африке и Азии, Цин, "
        "Великие Моголы и сёгунат. Отвечает, в каком государстве лежал приход "
        "в год ревизии или записи до 1886 года; точность — год, а не день."
    ),
    url=DOI_URL,
    status="harvested",
    expected_rows=3620,
    gives_records=False,
)

# Названия в наборе английские. Словарь покрывает всё, что попадает в отбор
# версии v0.2.1 по всему миру, — 424 политии; незнакомое название идёт как
# есть. Переводится то, что написано, а не то, что имелось в виду: «First
# Hellenic Republic» у Cliopatria тянется до 1907 года, но называть её
# «Греческим королевством» значило бы править источник подписью; так же
# «Kingdom of Monaco» остаётся королевством. Пояснение в скобках добавлено
# там, где голое название ничего не скажет русскому читателю, — так уже были
# «Польские повстанцы» вместо «Poles»: «Хауденосауни (Лига ирокезов)»,
# «Южно-Африканская Республика (Трансвааль)»; «Kamerun» — германская колония,
# и перевод это держит, как у CShapes.
NAMES_RU = {
    "(Allegiance of Kingdom of Hawaï'i to British Empire)":
        "(Присяга Гавайского королевства Британской империи)",
    "(Alliance between Papal States and Spanish Empire)":
        "(Союз Папской области и Испанской империи)",
    "(Batavian Republic)": "(Батавская республика)",
    "(Bourbon Kingdom of France)": "(Французское королевство Бурбонов)",
    "(British Empire)": "(Британская империя)",
    "(Dutch Republic)": "(Голландская республика)",
    "(First French Empire)": "(Первая Французская империя)",
    "(French Consulate)": "(Французская республика времён Консульства)",
    "(French Directory)": "(Французская республика времён Директории)",
    "(French First Republic)": "(Первая французская республика)",
    "(French Second Republic)": "(Вторая французская республика)",
    "(French Third Republic)": "(Третья французская республика)",
    "(Habsburg Monarchy)": "(Габсбургская монархия)",
    "(Holy Roman Empire)": "(Священная Римская империя)",
    "(Kingdom of England)": "(Королевство Англия)",
    "(Kingdom of France)": "(Королевство Франция)",
    "(Netherlands)": "(Нидерланды)",
    "(Portuguese Empire)": "(Португальская империя)",
    "(Second French Empire)": "(Вторая Французская империя)",
    "(Spanish Empire)": "(Испанская империя)",
    "Afsharid Iran": "Иран Афшаридов",
    "Ahmadnagar Sultanate": "Ахмаднагарский султанат",
    "Argentine Confederation": "Аргентинская конфедерация",
    "Ashanti Empire": "Империя Ашанти",
    "Astrakhan Khanate": "Астраханское ханство",
    "Austria-Hungary": "Австро-Венгрия",
    "Austrian Empire": "Австрийская империя",
    "Ayutthaya Kingdom": "Королевство Аюттхая",
    "Bahrain": "Бахрейн",
    "Bali": "Бали",
    "Balinese Kingdom": "Балийское королевство",
    "Bamana Empire": "Империя Бамана",
    "Batavian Republic": "Батавская республика",
    "Bessarabia": "Бессарабия",
    "Beylik of Tunis": "Тунисский бейлик",
    "Bidar Sultanate": "Бидарский султанат",
    "Bijapur Sultanate": "Биджапурский султанат",
    "Blambangan Kingdom": "Королевство Бламбанган",
    "Bolivia": "Боливия",
    "Bornu Empire": "Империя Борну",
    "Bourbon Kingdom of France": "Французское королевство Бурбонов",
    "Brandenburg-Prussia": "Бранденбург-Пруссия",
    "British Africa": "Британская Африка",
    "British Cape Colony": "Британская Капская колония",
    "British Ceylon": "Британский Цейлон",
    "British Colonial Empire": "Британская колониальная империя",
    "British Empire": "Британская империя",
    "British Gold Coast": "Британский Золотой Берег",
    "British Raj": "Британская Индия",
    "Burma": "Бирма",
    "California Republic": "Калифорнийская республика",
    "Cambodia": "Камбоджа",
    "Carnatic Sultanate": "Султанат Карнатик",
    "Catalonia": "Каталония",
    "Caucasian Imamate": "Северо-Кавказский имамат",
    "Centralist Mexico": "Централистская Мексика",
    "Chiangmai": "Чиангмай",
    "Chámpa": "Тямпа",
    "Cisalpine Republic": "Цизальпинская республика",
    "Cispadane Republic": "Циспаданская республика",
    "Commonwealth of England": "Английская республика (Содружество Англии)",
    "Comtat Venaissin": "Конта-Венессен",
    "Confederate States of America": "Конфедеративные Штаты Америки",
    "Confederation of the Rhine": "Рейнский союз",
    "Corsican Republic": "Корсиканская республика",
    "County of Urgell": "Графство Урхель",
    "Crimean Khanate": "Крымское ханство",
    "Cundinamarca": "Кундинамарка",
    "Danish Gold Coast": "Датский Золотой Берег",
    "Danish India": "Датская Индия",
    "Denmark-Norway": "Дания-Норвегия",
    "Dominican Republic": "Доминиканская Республика",
    "Don Cossacks": "Войско Донское",
    "Duchy of Anhalt": "Герцогство Ангальт",
    "Duchy of Bavaria": "Герцогство Бавария",
    "Duchy of Brunswick": "Герцогство Брауншвейг",
    "Duchy of Courland": "Курляндское герцогство",
    "Duchy of Holstein": "Герцогство Гольштейн",
    "Duchy of Lorraine": "Герцогство Лотарингия",
    "Duchy of Mecklenburg": "Герцогство Мекленбург",
    "Duchy of Modena and Reggio": "Герцогство Модена и Реджо",
    "Duchy of Nassau": "Герцогство Нассау",
    "Duchy of Oldenburg": "Герцогство Ольденбург",
    "Duchy of Parma and Piacenza": "Герцогство Парма и Пьяченца",
    "Duchy of Prussia": "Прусское герцогство",
    "Duchy of Warsaw": "Варшавское герцогство",
    "Durrani Dynasty": "Дуррани",
    "Durrani Empire": "Дурранийская держава",
    "Dutch Cape Colony": "Голландская Капская колония",
    "Dutch Ceylon": "Голландский Цейлон",
    "Dutch East Indies": "Нидерландская Ост-Индия",
    "Dutch Gold Coast": "Голландский Золотой Берег",
    "Dutch Republic": "Голландская республика",
    "Dzungar Khanate": "Джунгарское ханство",
    "Eastern Moghulistan": "Восточный Могулистан",
    "Electorate of Baden": "Курфюршество Баден",
    "Electorate of Brandenburg": "Курфюршество Бранденбург",
    "Electorate of Hanover": "Курфюршество Ганновер",
    "Electorate of Hesse": "Курфюршество Гессен",
    "Electorate of Salzburg": "Курфюршество Зальцбург",
    "Electorate of Saxony": "Курфюршество Саксония",
    "Electorate of Trier": "Курфюршество Трир",
    "Electorate of Württemberg": "Курфюршество Вюртемберг",
    "Emirate of Afghanistan": "Афганский эмират",
    "Emirate of Bukhara": "Бухарский эмират",
    "Emirate of Diriyah": "Дирийский эмират",
    "Emirate of Jabal Shammar": "Эмират Джебель-Шаммар",
    "Emirate of Nejd": "Неджедский эмират",
    "Empire of Brazil": "Бразильская империя",
    "Empire of Haiti": "Гаитянская империя",
    "Empire of Japan": "Японская империя",
    "English Colonial Empire": "Английская колониальная империя",
    "Ethiopian Empire": "Эфиопская империя",
    "Federal League": "Федеральная лига",
    "Federated Republic of Mexico": "Федеративная республика Мексика",
    "First French Empire": "Первая Французская империя",
    "First French colonial empire": "Первая французская колониальная империя",
    "First Hellenic Republic": "Первая Греческая республика",
    "First Mexican Empire": "Первая Мексиканская империя",
    "First Spanish Republic": "Первая Испанская республика",
    "First Toungoo Empire": "Первая империя Таунгу",
    "Free City of Bremen": "Бремен, вольный город",
    "Free City of Danzig": "Данциг, вольный город",
    "Free City of Frankfurt": "Франкфурт, вольный город",
    "Free City of Hamburg": "Гамбург, вольный город",
    "Free City of Krakow": "Краков, вольный город",
    "Free City of Lübeck": "Любек, вольный город",
    "Free Orange State": "Оранжевое Свободное государство",
    "Freetown Colony": "Колония Фритаун",
    "French Africa": "Французская Африка",
    "French Algeria": "Французский Алжир",
    "French Colony of Guiana": "Французская колония Гвиана",
    "French Consulate": "Французская республика времён Консульства",
    "French Directory": "Французская республика времён Директории",
    "French First Republic": "Первая французская республика",
    "French India": "Французская Индия",
    "French Indochina": "Французский Индокитай",
    "French Louisiana": "Французская Луизиана",
    "French Second Republic": "Вторая французская республика",
    "French Third Republic": "Третья французская республика",
    "Funj Sultanate": "Султанат Фунг",
    "German Africa": "Германская Африка",
    "German Confederation": "Германский союз",
    "German Empire": "Германская империя",
    "Golconda Sultanate": "Голкондский султанат",
    "Golden Horde": "Золотая Орда",
    "Gorkha Kingdom": "Королевство Горкха",
    "Gran Colombia": "Великая Колумбия",
    "Granadine Confederation": "Гранадская конфедерация",
    "Grand Duchy of Baden": "Великое герцогство Баден",
    "Grand Duchy of Berg": "Великое герцогство Берг",
    "Grand Duchy of Hesse": "Великое герцогство Гессен",
    "Grand Duchy of Saxe-Weimar-Eisenach": "Великое герцогство Саксен-Веймар-Эйзенах",
    "Grand Duchy of Tuscany": "Великое герцогство Тосканское",
    "Grand Duchy of Würzburg": "Великое герцогство Вюрцбург",
    "Greenland": "Гренландия",
    "Guatemala": "Гватемала",
    "Guayaquil Junta": "Гуаякильская хунта",
    "Habsburg Monarchy": "Габсбургская монархия",
    "Haiti": "Гаити",
    "Haudenosaunee": "Хауденосауни (Лига ирокезов)",
    "Helvetic Republic": "Гельветическая республика",
    "Holy Roman Empire": "Священная Римская империя",
    "Holy Roman Empire Minor States": "Малые государства Священной Римской империи",
    "Honduras": "Гондурас",
    "Hotaki Dynasty": "Хотаки",
    "House of Khalifa": "Дом Аль Халифа",
    "House of Savoy": "Савойский дом",
    "Huguenots": "Гугеноты",
    "Hungarian Nationalists": "Венгерские повстанцы",
    "Hyderabad State": "Княжество Хайдарабад",
    "Iberian Union": "Иберийская уния",
    "Imamate of Yemen": "Йеменский имамат",
    "Irish Catholic Confederation": "Ирландская католическая конфедерация",
    "Italian Nationalists": "Итальянские повстанцы",
    "Italian Republic": "Итальянская республика",
    "Itza Mayans": "Майя-ица",
    "Jesuit Reducciones": "Иезуитские редукции",
    "Joseon": "Чосон",
    "Kalmyk Khanate": "Калмыцкое ханство",
    "Kamerun": "Германский Камерун",
    "Karamanli Dynasty": "Караманли",
    "Kashmir and Jammu": "Джамму и Кашмир",
    "Kathmandu": "Катманду",
    "Kazakh Khanate": "Казахское ханство",
    "Kedah-Perlis District": "Кедах-Перлис",
    "Kelantan": "Келантан",
    "Khanate of Bukhara": "Бухарское ханство",
    "Khanate of Khiva": "Хивинское ханство",
    "Khanate of Kokand": "Кокандское ханство",
    "Khanates of the Caucasus": "Закавказские ханства",
    "Khedivate of Egypt": "Египетский хедиват",
    "Khmer Empire": "Кхмерская империя",
    "Khoshut Khanate": "Хошутское ханство",
    "Kingdom of Bavaria": "Королевство Бавария",
    "Kingdom of Belgium": "Королевство Бельгия",
    "Kingdom of Bhutan": "Королевство Бутан",
    "Kingdom of Bulungan": "Королевство Булунган",
    "Kingdom of Champasak": "Королевство Тямпасак",
    "Kingdom of England": "Королевство Англия",
    "Kingdom of Etruria": "Королевство Этрурия",
    "Kingdom of Fiji": "Королевство Фиджи",
    "Kingdom of France": "Королевство Франция",
    "Kingdom of Georgia": "Грузинское царство",
    "Kingdom of Great Britain": "Королевство Великобритания",
    "Kingdom of Hanover": "Королевство Ганновер",
    "Kingdom of Hawaï'i": "Гавайское королевство",
    "Kingdom of Imereti": "Имеретинское царство",
    "Kingdom of Italy": "Королевство Италия",
    "Kingdom of Kakheti": "Кахетинское царство",
    "Kingdom of Kartli": "Картлийское царство",
    "Kingdom of Kongo": "Королевство Конго",
    "Kingdom of Luang Phrabang": "Королевство Луангпхабанг",
    "Kingdom of Lunda": "Королевство Лунда",
    "Kingdom of Monaco": "Королевство Монако",
    "Kingdom of Mrauk U": "Королевство Мраук-У",
    "Kingdom of Mysore": "Королевство Майсур",
    "Kingdom of Naples (Napoleonic)": "Неаполитанское королевство (наполеоновское)",
    "Kingdom of Norway": "Королевство Норвегия",
    "Kingdom of Portugal": "Королевство Португалия",
    "Kingdom of Prussia": "Королевство Пруссия",
    "Kingdom of Sarawak": "Королевство Саравак",
    "Kingdom of Sardinia": "Сардинское королевство",
    "Kingdom of Saxony": "Королевство Саксония",
    "Kingdom of Scotland": "Королевство Шотландия",
    "Kingdom of Serbia": "Королевство Сербия",
    "Kingdom of Spain": "Королевство Испания",
    "Kingdom of Sweden": "Королевство Швеция",
    "Kingdom of Westphalia": "Королевство Вестфалия",
    "Kingdom of Württemberg": "Королевство Вюртемберг",
    "Kingdom of the Two Sicilies": "Королевство Обеих Сицилий",
    "Konbaung Dynasty": "Конбаун",
    "Kutai Kingdom": "Королевство Кутай",
    "Kuwait": "Кувейт",
    "Lan Na": "Ланна",
    "Lan Xang": "Лансанг",
    "Later Jin Dynasty": "Поздняя Цзинь",
    "Li Zicheng": "Ли Цзычэн",
    "Ligurian Republic": "Лигурийская республика",
    "Los Altos": "Лос-Альтос",
    "Majeerteen Sultanate": "Султанат Маджиртин",
    "Mali Empire": "Империя Мали",
    "Maratha Empire": "Империя маратхов",
    "Massina Empire": "Империя Масина",
    "Mataram Sultanate": "Султанат Матарам",
    "Merina Kingdom": "Королевство Мерина",
    "Mexican Monarchists": "Мексиканские монархисты",
    "Mexicans": "Мексиканские повстанцы",
    "Mexico": "Мексика",
    "Ming Dynasty": "Империя Мин",
    "Mongol Khanate": "Монгольское ханство",
    "Montenegro": "Черногория",
    "Morocco": "Марокко",
    "Mosquito Kingdom": "Москитское королевство",
    "Mughal Empire": "Империя Великих Моголов",
    "Muhammad Ali dynasty": "Египет при династии Мухаммеда Али",
    "Napoleonic Batavia Republic": "Батавская республика (наполеоновская)",
    "Natalia Republic": "Республика Наталь",
    "Nawab of Awadh": "Наваб Ауда",
    "Nawabs of Bengal": "Навабы Бенгалии",
    "Nayaks of Madurai": "Наяки Мадурая",
    "Nayaks of Thanjavur": "Наяки Танджавура",
    "Negeri Sembilan": "Негери-Сембилан",
    "Nepal": "Непал",
    "Netherlands": "Нидерланды",
    "Netherlands Antilles": "Нидерландские Антильские острова",
    "New Caledonia": "Новая Каледония",
    "New France": "Новая Франция",
    "New Granada": "Новая Гранада",
    "New Netherland": "Новые Нидерланды",
    "New Sweden": "Новая Швеция",
    "Nguyễn dynasty": "Династия Нгуен",
    "Nguyễn lords": "Сеньоры Нгуен",
    "Nieuwe Republiek": "Новая Республика",
    "North German Confederation": "Северогерманский союз",
    "Oirat Confederation": "Ойратский союз",
    "Omani Slave Coast": "Оманский Невольничий берег",
    "Oriental Republic of Uruguay": "Восточная Республика Уругвай",
    "Ottoman Empire": "Османская империя",
    "Ottoman Tripolitania": "Османская Триполитания",
    "Oyo Empire": "Империя Ойо",
    "Pahang Sultanate": "Султанат Паханг",
    "Panthay Rebellion": "Пантайское восстание",
    "Papal States": "Папская область",
    "Paraguay": "Парагвай",
    "Patani Kingdom": "Королевство Паттани",
    "People's Republic of Zanzibar": "Народная Республика Занзибар",
    "Peru-Bolivian Confederation": "Перуано-боливийская конфедерация",
    "Poles": "Польские повстанцы",
    "Polish-Lithuanian Commonwealth": "Речь Посполитая",
    "Pontianak Kadriyah Sultanate": "Султанат Понтианак",
    "Portuguese Ceylon": "Португальский Цейлон",
    "Portuguese Colonies": "Португальские колонии",
    "Portuguese Empire": "Португальская империя",
    "Principality of Abkhazia": "Абхазское княжество",
    "Principality of Andorra": "Княжество Андорра",
    "Principality of Bulgaria": "Княжество Болгария",
    "Principality of Guria": "Гурийское княжество",
    "Principality of Hohenzollern-Sigmaringen": "Княжество Гогенцоллерн-Зигмаринген",
    "Principality of Lichtenberg": "Княжество Лихтенберг",
    "Principality of Liechtenstein": "Княжество Лихтенштейн",
    "Principality of Lippe": "Княжество Липпе",
    "Principality of Mingrelia": "Мегрельское княжество",
    "Principality of Moldavia": "Молдавское княжество",
    "Principality of Monaco": "Княжество Монако",
    "Principality of Regensberg": "Княжество Регенсберг",
    "Principality of Reuss-Gera": "Княжество Рейсс-Гера",
    "Principality of Schwarzburg-Sonderhausen": "Княжество Шварцбург-Зондерсгаузен",
    "Principality of Svaneti": "Сванетское княжество",
    "Principality of Transylvania": "Трансильванское княжество",
    "Principality of Upper Hungary": "Княжество Верхняя Венгрия",
    "Principality of Waldeck and Pyrmont": "Княжество Вальдек-Пирмонт",
    "Principality of Wallachia": "Валашское княжество",
    "Pro-Habsburg Spain": "Испания сторонников Габсбургов",
    "Pro-Swedish Poland": "Польша сторонников Швеции",
    "Qajar Dynasty": "Каджарский Иран",
    "Qasimids": "Касимиды",
    "Qatar Dynasty": "Катарская династия",
    "Qing Dynasty": "Империя Цин",
    "Rattanakosin Kingdom": "Королевство Раттанакосин",
    "Regency of Algiers": "Алжирское регентство",
    "Republic of Baden": "Баденская республика",
    "Republic of Baja California": "Республика Нижняя Калифорния",
    "Republic of Chile": "Республика Чили",
    "Republic of Colombia": "Республика Колумбия",
    "Republic of Costa Rica": "Республика Коста-Рика",
    "Republic of Ecuador": "Республика Эквадор",
    "Republic of El Salvador": "Республика Сальвадор",
    "Republic of Florence": "Флорентийская республика",
    "Republic of Genoa": "Генуэзская республика",
    "Republic of Liberia": "Республика Либерия",
    "Republic of New Granada": "Республика Новая Гранада",
    "Republic of Nicaragua": "Республика Никарагуа",
    "Republic of Peru": "Республика Перу",
    "Republic of Ragusa": "Рагузская республика",
    "Republic of San Marino": "Республика Сан-Марино",
    "Republic of Texas": "Республика Техас",
    "Republic of Venezuela": "Республика Венесуэла",
    "Republic of Venice": "Венецианская республика",
    "Republic of the Rio Grande": "Республика Рио-Гранде",
    "Revolutionary Roman Republic": "Римская республика (революционная)",
    "Riau-Lingga Sultanate": "Султанат Риау-Лингга",
    "Riograndense Republic": "Риограндийская республика",
    "Russian Empire": "Российская империя",
    "Río de la Plata": "Рио-де-ла-Плата",
    "Saadi Sultanate": "Султанат Саадидов",
    "Safavid Dynasty": "Сефевидское государство",
    "Saxe-Altenburg": "Саксен-Альтенбург",
    "Saxe-Coburg and Gotha": "Саксен-Кобург-Гота",
    "Saxe-Meiningen": "Саксен-Мейнинген",
    "Second French Empire": "Вторая Французская империя",
    "Second Mexican Empire": "Вторая Мексиканская империя",
    "Septinsular Republic": "Республика Семи Островов",
    "Serbs": "Сербские повстанцы",
    "Sikh Confederacy": "Сикхская конфедерация",
    "Sikh Empire": "Сикхская держава",
    "Sikhs": "Сикхи",
    "Sloboda Ukraine": "Слободская Украина",
    "Small Horde": "Малый жуз",
    "Sokoto Caliphate": "Халифат Сокото",
    "Songhai Empire": "Империя Сонгай",
    "South African Republic": "Южно-Африканская Республика (Трансвааль)",
    "Southern Ming": "Южная Мин",
    "Sovereign Principality of the United Netherlands":
        "Суверенное княжество Соединённых Нидерландов",
    "Spanish Empire": "Испанская империя",
    "State of Buenos Aires": "Государство Буэнос-Айрес",
    "Sultan of Yogyakarta": "Султанат Джокьякарта",
    "Sultanate of Aceh": "Султанат Ачех",
    "Sultanate of Banjar": "Султанат Банджар",
    "Sultanate of Banten": "Султанат Бантен",
    "Sultanate of Bima": "Султанат Бима",
    "Sultanate of Bone": "Султанат Боне",
    "Sultanate of Brunei": "Султанат Бруней",
    "Sultanate of Cirebon": "Султанат Черибон",
    "Sultanate of Darfur": "Султанат Дарфур",
    "Sultanate of Gowa": "Султанат Гова",
    "Sultanate of Hobyo": "Султанат Хобьо",
    "Sultanate of Jambi": "Султанат Джамби",
    "Sultanate of Johor": "Султанат Джохор",
    "Sultanate of Kedah": "Султанат Кедах",
    "Sultanate of Kutai Kartanegara": "Султанат Кутай-Картанегара",
    "Sultanate of Maguindanao": "Султанат Магинданао",
    "Sultanate of Malacca": "Малаккский султанат",
    "Sultanate of Mempawah": "Султанат Мемпава",
    "Sultanate of Oman": "Оманский султанат",
    "Sultanate of Palembang": "Султанат Палембанг",
    "Sultanate of Perak": "Султанат Перак",
    "Sultanate of Sambaliung": "Султанат Самбалиунг",
    "Sultanate of Sambas": "Султанат Самбас",
    "Sultanate of Selangor": "Султанат Селангор",
    "Sultanate of Sukadana": "Султанат Сукадана",
    "Sultanate of Sulu": "Султанат Сулу",
    "Sultanate of Terengganu": "Султанат Тренгану",
    "Surakarta Sunanate": "Сунанат Суракарта",
    "Swaziland": "Свазиленд",
    "Swedish Empire": "Шведская держава",
    "Swiss Confederation": "Швейцарская конфедерация",
    "Taiping Heavenly Kingdom": "Тайпинское Небесное государство",
    "Talpur Dynasty": "Талпуры",
    "Thanjavur Maratha Kingdom": "Маратхское королевство Танджавур",
    "Thonburi Kingdom": "Королевство Тхонбури",
    "Tibet": "Тибет",
    "Tokugawa Shogunate": "Сёгунат Токугава",
    "Trucial States": "Договорный Оман",
    "Trịnh lords": "Сеньоры Чинь",
    "Tsardom of Russia": "Русское царство",
    "Tây Sơn dynasty": "Династия Тэйшон",
    "Tümed": "Тумэты",
    "United Kingdoms of Sweden and Norway": "Шведско-норвежская уния",
    "United Principalities of Moldavia and Wallachia": "Соединённое княжество Молдавии и Валахии",
    "United Provinces of Central America": "Соединённые провинции Центральной Америки",
    "United States of America": "Соединённые Штаты Америки",
    "United States of Colombia": "Соединённые Штаты Колумбии",
    "Venezuela": "Венесуэла",
    "Vermont Republic": "Республика Вермонт",
    "Vientiane": "Вьентьян",
    "Wadai Empire": "Империя Вадаи",
    "Warring States Japan": "Япония периода Сэнгоку",
    "Western Moghulistan": "Западный Могулистан",
    "Yarubid dynasty": "Яарибиды",
    "Zand Dynasty": "Иран Зендов",
    "Zaporozhian Cossacks": "Войско Запорожское",
    "Zululand": "Зулуленд",
    "Đại Việt": "Дайвьет",
}

# Названия, по которым отчёт о сборе показывает хронологию русской границы.
# Строк с одним номером, как у CShapes, здесь нет; Викиданные надёжнее
# названия, но у трёх эпох три разных Q-номера.
RUSSIA_WIKIDATA = ("Q186096", "Q34266")   # Русское царство, Российская империя


class CliopatriaError(RuntimeError):
    """Набор не скачался, не сошёлся с ожидаемым или пришёл не в том виде."""


# --- запись на Zenodo ------------------------------------------------------

def open_archive(*, url: str = ARCHIVE_URL, timeout: int = 300) -> zipfile.ZipFile:
    """Архив записи на Zenodo, открытый для чтения кусками по Range.

    Открытие стоит одного запроса: оглавление архива на 522 файла лежит в
    его последних 128 КБ. Набор потом читается из того же объекта, поэтому
    `--check` сверяет и скачивает без второго захода за оглавлением.
    """
    try:
        return zipfile.ZipFile(RangeFile(url, error=CliopatriaError, timeout=timeout))
    except zipfile.BadZipFile as exc:
        raise CliopatriaError(f"{url}: архив не разбирается как zip ({exc})") from exc


def listing(archive: zipfile.ZipFile) -> dict:
    """Оглавление архива в том виде, в каком его отдавал Zenodo до ноября 2026
    года: имя, размер, CRC32. Числа те же — Zenodo брал их из того же
    оглавления, — поэтому и сверка с кодом осталась прежней."""
    return {"entries": [{"key": info.filename, "size": info.file_size, "crc": info.CRC}
                        for info in archive.infolist()]}


def fetch_listing(*, timeout: int = 300) -> dict:
    """Перечень содержимого архива: имена, размеры, CRC32 вложенных файлов."""
    return listing(open_archive(timeout=timeout))


def check_listing(listing: dict) -> list[str]:
    """Расхождения перечня с тем, что записано в коде. Пусто — всё сходится."""
    entries = {e.get("key"): e for e in listing.get("entries") or []}
    got = entries.get(MEMBER)
    if got is None:
        geojsons = sorted(k for k in entries if str(k).endswith(".geojson.zip"))
        return [f"в архиве нет {MEMBER}; похожие: {geojsons or 'нет'}"]
    problems = []
    if got.get("size") != MEMBER_SIZE:
        problems.append(f"размер {got.get('size')}, ожидался {MEMBER_SIZE}")
    if got.get("crc") != MEMBER_CRC:
        problems.append(f"CRC32 {got.get('crc')}, ожидался {MEMBER_CRC}")
    return problems


def download(dest: Path, *, archive: Optional[zipfile.ZipFile] = None,
             timeout: int = 600) -> Path:
    """Достаёт набор из архива на Zenodo, сверяя размер и CRC32. Не сошлось — файла нет.

    Читается только сам набор: `zipfile` находит его по оглавлению и тянет
    его сжатые байты, а `RangeFile` — кусками по 16 МБ. Свою сверку размера
    и CRC32 с кодом сбор делает сам, не полагаясь на ту, что делает `zipfile`
    при чтении: она проверяет архив против его же оглавления, а не против
    версии, записанной здесь.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    crc, size = 0, 0
    try:
        archive = archive or open_archive(timeout=timeout)
        with archive.open(MEMBER) as src, partial.open("wb") as fh:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                crc = zlib.crc32(chunk, crc)
                size += len(chunk)
    except KeyError as exc:
        partial.unlink(missing_ok=True)
        raise CliopatriaError(f"в архиве нет {MEMBER}") from exc
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise CliopatriaError(f"набор из архива не читается: {exc}") from exc
    except CliopatriaError:
        partial.unlink(missing_ok=True)
        raise
    if size != MEMBER_SIZE or crc != MEMBER_CRC:
        partial.unlink(missing_ok=True)
        raise CliopatriaError(f"скачано {size} байт, CRC32 {crc}; ожидалось "
                              f"{MEMBER_SIZE} байт, CRC32 {MEMBER_CRC}")
    partial.replace(dest)
    return dest


def cached(cache_dir: Path, *, archive: Optional[zipfile.ZipFile] = None) -> Path:
    """Файл из кэша; нет его или он другого размера — скачивается заново."""
    path = Path(cache_dir) / CACHE_NAME
    if path.exists() and path.stat().st_size == MEMBER_SIZE:
        return path
    return download(path, archive=archive)


# --- чтение набора ---------------------------------------------------------

def read_member(path: Path) -> list[dict]:
    """Строки набора из вложенного zip: в нём один GeoJSON, имя меняется от версии."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith(".geojson")]
            if len(names) != 1:
                raise CliopatriaError(f"в архиве ждали один .geojson, лежат: {names}")
            with archive.open(names[0]) as fh:
                data = json.load(fh)
    except zipfile.BadZipFile as exc:
        raise CliopatriaError(f"{path}: не разбирается как zip ({exc})") from exc
    except ValueError as exc:
        raise CliopatriaError(f"{path}: GeoJSON не разбирается ({exc})") from exc
    feats = data.get("features") if isinstance(data, dict) else None
    if not feats:
        raise CliopatriaError(f"{path}: в наборе нет ни одной строки")
    check_fields(feats)
    return feats


def check_fields(feats: list[dict]) -> None:
    """Поля, на которых держится разбор. Нет хоть одного — набор переделали."""
    keys: set = set()
    for feature in feats:
        keys.update(feature.get("properties") or {})
    missing = [f for f in REQUIRED_FIELDS if f not in keys]
    if missing:
        raise CliopatriaError(
            f"в наборе нет обязательных полей {missing}; пришли: {sorted(keys)}. "
            f"Проверьте {REPO_URL} и поправьте разбор."
        )


def overlaps(props: dict, year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> bool:
    """Пересекаются ли годы строки с рамкой слоя (годы набора — включительно)."""
    start, end = props.get("FromYear"), props.get("ToYear")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return start <= year_max and end >= year_min


def select(feats: Iterable[dict], *, year_min: int = YEAR_MIN,
           year_max: int = YEAR_MAX, region_only: bool = False) -> list[dict]:
    """Строки в рамке слоя, приведённые к подписям, понятным читателю файла.

    По умолчанию — весь мир; `region_only` оставляет прежний отбор по охвату
    РИ/СССР.
    """
    out = []
    for feature in feats:
        props = feature.get("properties") or {}
        if not overlaps(props, year_min, year_max):
            continue
        if region_only and not touches_region(feature.get("geometry")):
            continue
        out.append(boundary(feature, year_max=year_max))
    return out


def boundary(feature: dict, *, year_max: int = YEAR_MAX) -> dict:
    """Одна строка набора: русское название, годы, ссылки, связи политий.

    Годы не обрезаются по рамке: строка «1885–1894» остаётся такой, а
    `continues_in` говорит, где та же граница лежит с 1886 года по дням.
    Строки в скобках — у Cliopatria объединения («(British Empire)» — сама
    Британия вместе с владениями); их состав идёт в `components`, а у
    частей — `member_of`, чтобы подложка не рисовала их одну поверх другой
    вслепую.
    """
    props = feature.get("properties") or {}
    name = props.get("Name")
    year_to = props.get("ToYear")
    out = {
        "state": NAMES_RU.get(name, name),
        "state_en": name,
        "year_from": props.get("FromYear"),
        "year_to": year_to,
        "kind": "relation" if props.get("Type") == "RELATION" else "polity",
        "components": _split(props.get("Components")),
        "member_of": _split(props.get("MemberOf")),
        "area_km2": round(props["Area"]) if isinstance(props.get("Area"), (int, float)) else None,
        "wikidata": _wikidata(props.get("Wikidata")),
        "wikipedia": _wikipedia(props.get("Wikipedia")),
        "seshat_id": _split(props.get("SeshatID")),
    }
    if isinstance(year_to, int) and year_to > year_max:
        out["continues_in"] = STATE_BORDERS.slug
    return {
        "type": "Feature",
        "geometry": rounded_geometry(feature.get("geometry")),
        "properties": {k: v for k, v in out.items() if v not in (None, "", [])},
    }


def _split(value) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def _wikidata(value) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return f"https://www.wikidata.org/wiki/{value.strip()}"


def _wikipedia(value) -> Optional[str]:
    """README набора хранит заголовок статьи, а не адрес: адрес собирается здесь."""
    if not isinstance(value, str) or not value.strip():
        return None
    title = value.strip().replace(" ", "_")
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title, safe="_(),'-")


def rounded_geometry(geometry: Optional[dict], digits: int = COORD_DIGITS) -> Optional[dict]:
    """Координаты до `digits` знаков; кольцо, которое округление схлопнуло, — как было.

    Повторы подряд после округления убираются: в GeoJSON соседние одинаковые
    вершины ничего не значат, а файл утяжеляют.
    """
    if not isinstance(geometry, dict):
        return geometry
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        return {"type": kind, "coordinates": [_ring(r, digits) for r in coords]}
    if kind == "MultiPolygon":
        return {"type": kind,
                "coordinates": [[_ring(r, digits) for r in polygon] for polygon in coords]}
    return geometry


def _ring(ring: list, digits: int) -> list:
    out: list = []
    for point in ring:
        q = [round(point[0], digits), round(point[1], digits)]
        if not out or q != out[-1]:
            out.append(q)
    if len(out) < 4:
        return [list(p[:2]) for p in ring]
    return out


def states(feats: Iterable[dict]) -> list[str]:
    """Политии отбора по-русски, по алфавиту — для отчёта о сборе."""
    return sorted({(f.get("properties") or {}).get("state") for f in feats
                   if (f.get("properties") or {}).get("state")})


def untranslated(feats: Iterable[dict]) -> list[str]:
    """Английские названия, которых нет в словаре: новая версия набора их добавит."""
    return sorted({(f.get("properties") or {}).get("state_en") for f in feats} - set(NAMES_RU)
                  - {None})


def collection(feats: list[dict], *, year_min: int = YEAR_MIN,
               year_max: int = YEAR_MAX) -> dict:
    return feature_collection(
        STATE_BORDERS_EARLY.slug, feats,
        license=STATE_BORDERS_EARLY.license, source=STATE_BORDERS_EARLY.source,
        citation=CITATION, url=DOI_URL,
        extra={"period": f"{year_min}–{year_max}", "coverage": "весь мир",
               "version": VERSION, "continues_in": STATE_BORDERS.slug},
    )


def write(collection_dict: dict, path) -> int:
    """Пишет коллекцию сжатым JSON: у 1,4 млн вершин пробелы — это мегабайты."""
    return write_feature_collection(collection_dict, path, compact=True)
