"""Каталог слоёв контекста: что собираем, откуда и на каких правах.

Слои разделены на два вида:
  * `curated` — уже собраны и лежат в data/raw;
  * `planned`  — есть готовый запрос в queries/, собираются скриптом harvest.py.

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

CURATED = [LITERARY, TENISHEV, BATTLES, PROKUDIN, STATE_EVENTS]

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
        slug="settlements", title="Населённые места", group="admin",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=60000,
        description=(
            "Города, сёла, деревни, посады, станицы, слободы. Скелет всей карты: "
            "к населённому месту привязываются остальные слои и сами факты из метрик."
        ),
    ),
    LayerSpec(
        slug="admin_units", title="Губернии, уезды, волости", group="admin",
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=3000,
        description=(
            "Единицы деления с датами учреждения и упразднения. Без них нельзя "
            "понять, в каком архиве искать: подчинённость менялась."
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
        source="Викиданные + справочная литература", license=WD_CC0, status="planned", expected_rows=120,
        description=(
            "Местные неурожаи по уездам. Четыре больших голода — 1891–92, 1921–22, "
            "1932–33, 1946–47 — уже собраны вручную в слое «Указы, реформы и "
            "потрясения» с перечнем затронутых губерний: в Викиданных у них нет "
            "ни координат, ни территориальной привязки."
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
        source="Викиданные, «Мемориал», Открытый список", license="уточняется по каждому источнику",
        status="planned", expected_rows=2000,
        description=(
            "Лагеря, спецпосёлки, места массовых захоронений, точки депортаций. "
            "Требует отдельной проверки лицензий — источники разнородны."
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
        source="Викиданные", license=WD_CC0, status="planned", expected_rows=6000,
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

ALL_LAYERS = CURATED + PLANNED
BY_SLUG = {spec.slug: spec for spec in ALL_LAYERS}


def layers_in_group(group: str) -> list[LayerSpec]:
    return [s for s in ALL_LAYERS if s.group == group]


def planned_slugs() -> list[str]:
    return [s.slug for s in PLANNED]
