"""Каталог слоёв контекста: что собираем, откуда и на каких правах.

Слои разделены на четыре вида:
  * `CURATED`   — ведутся вручную, лежат в data/raw или data/curated;
  * `HARVESTED` — собраны сборщиком и лежат в data/out, пересобираются командой;
  * `PLANNED`   — есть готовый запрос в queries/, собираются скриптом harvest.py;
  * `EXTERNAL`  — данные уже собраны другими проектами: свой сбор у каждого,
    и препятствие чаще не техническое, а правовое.

Четвёртый список появился поздно, и это была ошибка. Викиданные удобны — CC0,
SPARQL, машинный ответ, — но удобство источника не то же самое, что его
ценность: снимок улицы, полигон уезда 1897 года и карточка лагеря собраны
людьми в других проектах и в Викиданные не попадут. Правовые условия у них
разные и в поле `license` записаны честно: там, где нужно согласование, так
и написано.

Три слоя из этого списка уже переехали в `HARVESTED` — лагерные управления
и два набора границ. Держало их не техническое препятствие и даже не отказ
правообладателя, а непроверенная лицензия: по прежней редакции условия 3
источник без выясненных прав не собирался вовсе. Условие переписано (см.
«Каталог открыт» в `docs/CATALOG.md`), проверка заняла по одному запросу к
карточке набора и дала CC BY 4.0 и CC0.

Четвёртым переехал `state_borders`: его не держало вообще ничего, кроме
ненаписанного сборщика. Лицензия у CShapes была известна с самого начала
(CC BY-NC-SA 4.0), и она подходит — проект некоммерческий.

`expected_rows` — грубая оценка порядка величины, а не обещание. Реальное
число станет известно после первого сбора и должно быть вписано сюда.
"""

from __future__ import annotations

from .schema import LayerSpec

# --- уже собранные слои ---------------------------------------------------

from .adapters.battles import BATTLES                     # noqa: E402
from .adapters.bookplaces import LITERARY, TENISHEV        # noqa: E402
from .adapters.prokudin_gorsky import PROKUDIN             # noqa: E402
from .adapters.state_events import STATE_EVENTS            # noqa: E402
from .sources.errhs import HARVEST_PRICES                 # noqa: E402
from .sources.geonames import SETTLEMENTS                  # noqa: E402
from .sources.admin_gis import ADMIN_GIS                    # noqa: E402
from .sources.cshapes import STATE_BORDERS                  # noqa: E402
from .sources.gulag import GULAG_CAMPS                      # noqa: E402
from .sources.ristat import RISTAT_BOUNDARIES               # noqa: E402
from .sources.pastvu import PASTVU_PHOTOS                  # noqa: E402
from .sources.weather import WEATHER_REGIONS, WEATHER_STATIONS  # noqa: E402

CURATED = [LITERARY, TENISHEV, BATTLES, PROKUDIN, STATE_EVENTS]

# Слои, собранные сборщиком и лежащие в data/out. От CURATED отличаются
# происхождением: их не ведут вручную, их пересобирают командой.
# `admin_boundaries_1897` и `state_borders` — единственные здесь, кто не даёт
# записей схемы: это полигоны для подложки карты, они лежат
# в data/out/boundaries.
HARVESTED = [SETTLEMENTS, GULAG_CAMPS, ADMIN_GIS, RISTAT_BOUNDARIES,
             STATE_BORDERS, HARVEST_PRICES]

# --- слои для сбора из Викиданных ----------------------------------------
# Поле `query` указывает на файл в каталоге queries/.

WD_CC0 = "CC0 (Викиданные)"

PLANNED = [
    # Группа: церкви, приходы и религиозные общины
    LayerSpec(
        slug="churches", title="Храмы и церкви", group="faith",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=12000,
        description=(
            "Приходские церкви и соборы. Ключевой слой для генеалогии: метрические "
            "книги велись по приходам, и храм привязывает предка к конкретному приходу."
        ),
    ),
    LayerSpec(
        slug="monasteries", title="Монастыри и пустыни", group="faith",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=1200,
        description="Монастыри, лавры и пустыни — центры паломничества, землевладения и призрения.",
    ),
    LayerSpec(
        slug="other_faiths", title="Мечети, синагоги, кирхи, костёлы", group="faith",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=2500,
        description=(
            "Неправославные общины. Для многих родов это единственный способ найти "
            "нужный тип метрических записей: раввинат, мечеть, приход костёла."
        ),
    ),
    LayerSpec(
        slug="cemeteries", title="Кладбища и некрополи", group="faith",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=1500,
        description="Места захоронений, включая иноверческие и военные.",
    ),

    # Группа: административное деление и населённые места
    LayerSpec(
        slug="admin_units", title="Губернии, уезды, волости", group="admin",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=3000,
        description=(
            "Единицы деления с датами учреждения и упразднения. Без них нельзя "
            "понять, в каком архиве искать: подчинённость менялась."
        ),
    ),
    LayerSpec(
        slug="settlements_wd", title="Населённые места: год основания", group="admin",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=1031,
        description=(
            "Второй источник к слою «Населённые места»: у GeoNames года основания нет, "
            "и по времени такое место не подобрать. Здесь берутся только места с датой "
            "(P571), и пока это города: класс «населённый пункт» целиком сервис запросов "
            "не отдаёт — замеры в queries/settlements_wd.rq. Slug отдельный, чтобы сбор "
            "не затирал собранный слой GeoNames и не проставлял его записям чужую "
            "лицензию; сводятся два слоя по координате и названию — отдельной работой."
        ),
    ),
    LayerSpec(
        slug="renamed_places", title="Переименования населённых мест", group="admin",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=8000,
        description=(
            "Прежние названия и годы переименования. Частая причина тупика в поиске: "
            "село в метрике названо иначе, чем на современной карте."
        ),
    ),

    # Группа: бедствия и потрясения
    LayerSpec(
        slug="famines", title="Голод и неурожаи", group="hardship",
        source="Справочная литература и урожайная статистика по губерниям",
        license="права не выяснены: источник слоя ещё не выбран",
        status="planned", expected_rows=120,
        description=(
            "Местные неурожаи по уездам. Шесть больших голодов — от Самарского "
            "1873 года до 1946–47 — уже собраны вручную в слое «Указы, реформы "
            "и потрясения» с перечнем затронутых губерний. Из Викиданных слой "
            "не собирается: измерено на живом сервисе 23.08.2026, разбор — "
            "в docs/DISCOVERY.md. Уездного разрешения ни один проверенный "
            "источник пока не даёт, поэтому ближайший путь — погодовые сборы "
            "хлебов по губерниям и отклонение от нормы, как сделано с погодой; "
            "те же ряды питают слой harvest_prices, и заводить под них второй "
            "сбор не нужно."
        ),
    ),
    LayerSpec(
        slug="epidemics", title="Эпидемии", group="hardship",
        source="Викиданные + справочная литература", license=WD_CC0, status="planned", expected_rows=250,
        description=(
            "Холера, тиф, оспа, испанка. В метрических книгах видны как всплеск "
            "смертей за короткий срок — слой объясняет причину."
        ),
    ),
    LayerSpec(
        slug="uprisings", title="Восстания и волнения", group="hardship",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=400,
        description="Крестьянские, рабочие и национальные выступления с привязкой к местности.",
    ),
    LayerSpec(
        slug="repressions", title="Места репрессий и спецпоселений", group="hardship",
        source="Викиданные", license=WD_CC0,
        status="planned", expected_rows=600,
        description=(
            "Тюрьмы и пересыльные пункты, расстрельные полигоны, места массовых "
            "убийств и братские могилы жертв террора. Лагеря сюда не берутся — "
            "они уже собраны в слое gulag_camps; спецпосёлков в Викиданных нет."
        ),
    ),
    LayerSpec(
        slug="disasters", title="Пожары, наводнения, катастрофы", group="hardship",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=600,
        description="Городские пожары, наводнения, крушения — заметные события местной памяти.",
    ),

    # Группа: экономика и пути сообщения
    LayerSpec(
        slug="factories", title="Заводы и фабрики", group="economy",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=3500,
        description=(
            "Промышленные предприятия с годом основания. Объясняет, куда уходили "
            "на заработки и почему род перебрался в город."
        ),
    ),
    LayerSpec(
        slug="fairs", title="Ярмарки и торги", group="economy",
        source="Викиданные + справочная литература", license=WD_CC0, status="planned", expected_rows=400,
        description="Ярмарки — узлы торговых и брачных связей между волостями.",
    ),
    LayerSpec(
        slug="railway_stations", title="Железнодорожные станции", group="economy",
        # Прежняя оценка в 6 000 взята на глаз и вдвое ниже одной России: проба
        # 23.08.2026 дала по ней 12 013 объектов с координатой. Остальные
        # шестнадцать государств считает координатор при полном сборе.
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=20000,
        description=(
            "Станции с годом открытия. Железная дорога резко меняла судьбу села: "
            "появлялся отход, менялась география браков."
        ),
    ),
    LayerSpec(
        slug="mines", title="Рудники, копи, промыслы", group="economy",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=1200,
        description="Горные заводы, копи, соляные и рыбные промыслы — места отхожих заработков.",
    ),
    LayerSpec(
        slug="estates", title="Усадьбы и имения", group="economy",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=2500,
        description=(
            "Дворянские усадьбы. До 1861 года крепостной род почти всегда привязан "
            "к конкретному владельцу и имению."
        ),
    ),
]

# --- слои из внешних проектов --------------------------------------------
# Не Викиданные: у каждого источника свой сбор и свои условия. Оценки объёма
# взяты из описаний самих проектов и подлежат проверке при первом сборе.

EXTERNAL = [
    PASTVU_PHOTOS,
    WEATHER_STATIONS,
    WEATHER_REGIONS,
    LayerSpec(
        slug="photos_russiainphoto", title="История России в фотографиях", group="culture",
        source="russiainphoto.ru (Мультимедиа Арт Музей)",
        license="права музея и правообладателей на снимки — нужна договорённость; "
                "публичного API нет, метаданные без него не забрать",
        status="planned", expected_rows=200000,
        url="https://russiainphoto.ru/",
        description=(
            "Архив с датировкой и указанием места по каждому снимку, включая частные "
            "и семейные фотографии XIX — XX веков. Публичного API нет; условия "
            "использования выясняются с музеем, а не выводятся из открытости сайта."
        ),
    ),
    LayerSpec(
        slug="weather_chronicles", title="Погода по летописям до инструментальных наблюдений",
        group="hardship",
        source="Е. П. Борисенков, В. М. Пасецкий. Тысячелетняя летопись необычайных явлений "
               "природы; летописные своды и губернские хроники",
        license="сам свод — авторское право составителей; факт «год, место, явление» "
                "охране не подлежит и берётся со ссылкой на издание",
        status="planned", expected_rows=1500,
        description=(
            "Засухи, бескормицы, ранние морозы, «великие дожди» и мор скота, записанные "
            "летописями и хрониками. Закрывает то, чего не закроют станции: до 1881 года "
            "инструментальных рядов почти нет, а голодные годы XVII–XVIII веков объяснять "
            "чем-то надо."
        ),
    ),
    LayerSpec(
        slug="drought_atlas", title="Реконструкция засух по кольцам деревьев", group="hardship",
        source="Old World Drought Atlas, NOAA Paleoclimatology",
        license="данные NOAA — общественное достояние; ссылка на публикацию обязательна",
        status="planned", expected_rows=400,
        url="https://www.ncei.noaa.gov/products/paleoclimatology",
        description=(
            "Сеточная реконструкция летней засушливости по годичным кольцам, на века "
            "назад. Покрытие плотное в западной части империи и редеет к востоку — "
            "это ограничение, а не мелочь, и его надо показывать в карточке слоя."
        ),
    ),
]

ALL_LAYERS = CURATED + HARVESTED + PLANNED + EXTERNAL
BY_SLUG = {spec.slug: spec for spec in ALL_LAYERS}


def layers_in_group(group: str) -> list[LayerSpec]:
    return [s for s in ALL_LAYERS if s.group == group]


def planned_slugs() -> list[str]:
    return [s.slug for s in PLANNED]


def external_slugs() -> list[str]:
    return [s.slug for s in EXTERNAL]
