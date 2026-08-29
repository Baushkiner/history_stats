"""Засухи по годичным кольцам: реконструкция там, где наблюдений ещё нет.

Зачем этот слой. Инструментальные метеоряды начинаются примерно с 1881 года,
и слой `weather_stations` дальше этой границы не заглядывает. А недороды
XVII–XVIII веков объяснять чем-то надо: «в этом году в приходе умерло втрое
больше обычного» — вопрос, на который до станций отвечать нечем. Годичные
кольца деревьев отвечают: по ширине колец восстанавливается летняя
засушливость на века назад, по сетке и с датировкой до года.

Сверка на известном. Лето 1891 года, с которого начался голод в Поволжье,
стоит в наборе как PDSI −4.4 у Самары, −4.0 у Тамбова и −4.2 у Саратова в
следующем, 1892 году. А про голод 1601–1603 годов слой молчит — и молчит
правильно: тот голод случился не от суши, а от холодных дождливых лет, и
засухи в кольцах за эти годы нет. Слой отвечает за одну причину из нескольких
и чужих на себя не берёт.

Что берётся. Сеточные реконструкции летнего индекса засушливости Палмера
(PDSI) из NOAA Paleoclimatology. По умолчанию — **ERDA**, «Атлас засух
Европейской России» (Cook и др., 2020): 4259 узлов сетки 0.5°, 1400–2016 годы,
Восточно-Европейская равнина от Балтики до Урала. Вторым набором доступен
**OWDA**, Old World Drought Atlas (Cook и др., 2015), — тот самый, что назван
в каталоге: он покрывает Европу и Средиземноморье, но обрывается на 44.75°
в. д., то есть на середине империи, а в общей с ERDA полосе, по словам самих
авторов, менее точен. Поэтому основным взят ERDA, а OWDA включается ключом
`--dataset owda` и нужен ради западной кромки — Царства Польского западнее
22° в. д., куда ERDA не дотягивается. Именно кромки: узлы, которые уже покрыл
основной набор, из второго выбрасываются (`exclude_bbox`), иначе одна и та же
засуха попала бы в слой дважды.

**Покрытие — главное ограничение слоя, и оно не мелочь.** Реконструкция
существует там, где растут долгоживущие деревья и собраны хронологии: густо на
западе и в центре, реже к юго-востоку, где степь, и нигде за Уралом. Восточная
граница ERDA — 62° в. д.: для факта из Тобольска, Иркутска или с Амура этот
слой не даст ничего, и молчание здесь означает «атлас сюда не дотянулся», а не
«засух не было». Узлы на самом краю сетки помечены `confidence="grid_edge"`:
с одной стороны от них хронологий нет вовсе.

В слой идёт не погода, а отклонение от нормы — то же правило, что и у
метеорядов (`histctx.sources.weather`, раздел «Что считается аномалией» в
`docs/HARVEST.md`). Обычный год — шум, который вытеснит на карте всё
остальное. Разница с погодой одна: там аномалию приходилось считать самим — и
в сигмах ряда, и в абсолютной величине, — а PDSI уже нормирован и уже имеет
общепринятую шкалу, так что второе условие излишне. Порог берётся прямо со
шкалы Палмера и меняется ключом `--threshold`.

Точка сетки — не населённое место. Поэтому губерния у записи не заполняется:
`histctx.geo.extract_region` достаёт её из текста, а у координаты текста нет, и
приписать узлу «Самарскую губернию» значило бы её выдумать. Запись остаётся
точечной (`scope="point"`), место названо координатой, а подбор идёт по
расстоянию — шаг сетки (около 30×55 км) мельче обычного радиуса подбора
в 50 км, так что ближайший узел найдётся почти у любого села в охвате атласа.
"""

from __future__ import annotations

import math
import urllib.error
import urllib.request
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..geo import in_bbox, valid_coords
from ..net import USER_AGENT
from ..schema import ContextRecord, LayerSpec


@dataclass(frozen=True)
class Dataset:
    """Один атлас засух: где лежит, что покрывает и как на него ссылаться."""

    key: str
    title: str
    grid_url: str            # таблица узлов сетки: номер, долгота, широта
    matrix_url: str          # матрица: строка — год, колонка — узел
    study_url: str           # карточка набора в NOAA Paleoclimatology
    citation: str
    span: tuple[int, int]    # годы, за которые набор вообще что-то говорит
    extent: str              # охват словами — идёт в отчёт сбора
    bbox: tuple              # (широта от, долгота от, широта до, долгота до)
    step: float = 0.5        # шаг сетки в градусах


ERDA = Dataset(
    key="erda",
    title="Атлас засух Европейской России (ERDA)",
    grid_url="https://www.ncei.noaa.gov/pub/data/paleo/drought/cook2020-erda/"
             "cook2020-erda-gridpts.txt",
    matrix_url="https://www.ncei.noaa.gov/pub/data/paleo/drought/cook2020-erda/"
               "cook2020-erda-pdsi.txt",
    study_url="https://www.ncei.noaa.gov/access/paleo-search/study/28630",
    citation=(
        "Cook E. R., Solomina O., Matskovsky V. et al. The European Russia Drought "
        "Atlas (1400–2016 CE). Climate Dynamics, 2020, 54, 2317–2335, "
        "doi:10.1007/s00382-019-05115-2; набор — NOAA/WDS Paleoclimatology, "
        "study 28630, doi:10.25921/jsrz-j704"
    ),
    span=(1400, 2016),
    extent="22–62° в. д., 41–71.5° с. ш. — от Балтики до Урала, за Урал не заходит",
    bbox=(41.0, 22.0, 71.5, 62.0),
)

OWDA = Dataset(
    key="owda",
    title="Old World Drought Atlas (OWDA)",
    grid_url="https://www.ncei.noaa.gov/pub/data/paleo/treering/reconstructions/"
             "europe/owda-xy.txt",
    matrix_url="https://www.ncei.noaa.gov/pub/data/paleo/treering/reconstructions/"
               "europe/owda.txt",
    study_url="https://www.ncei.noaa.gov/access/paleo-search/study/19419",
    citation=(
        "Cook E. R., Seager R., Kushnir Y. et al. Old World megadroughts and pluvials "
        "during the Common Era. Science Advances, 2015, 1(10), e1500561, "
        "doi:10.1126/sciadv.1500561; набор — NOAA/WDS Paleoclimatology, study 19419, "
        "doi:10.25921/rjm6-mq74"
    ),
    span=(0, 2012),
    extent="−11.75–44.75° в. д., 27.25–70.75° с. ш. — Европа и Средиземноморье; "
           "восточнее 44.75° в. д. (это середина империи) не заходит",
    bbox=(27.25, -11.75, 70.75, 44.75),
)

DATASETS = {ERDA.key: ERDA, OWDA.key: OWDA}
DEFAULT_DATASET = ERDA.key

DROUGHT_ATLAS = LayerSpec(
    slug="drought_atlas",
    title="Реконструкция засух по кольцам деревьев",
    group="hardship",
    source="NOAA Paleoclimatology: European Russia Drought Atlas (ERDA), "
           "Old World Drought Atlas (OWDA)",
    license=(
        "данные NOAA — общественное достояние (работа ведомства США); карточка "
        "набора просит ссылаться на публикацию, на страницу набора и указывать "
        "дату обращения — ссылка и цитата проставляются в каждую запись"
    ),
    description=(
        "Летняя засушливость по годичным кольцам деревьев: сеточный индекс PDSI "
        "с датировкой до года, на века раньше первых метеостанций. Объясняет "
        "неурожай и голодные годы XVII–XVIII веков, до которых инструментальные "
        "ряды не достают. Покрытие держится на дендрохронологиях: густо на западе "
        "и в центре, реже к юго-востоку и **ничего за Уралом** — восточная граница "
        "атласа 62° в. д. Для факта из Сибири слой молчит, и это значит «атлас "
        "сюда не дотянулся», а не «засух не было»."
    ),
    url="https://www.ncei.noaa.gov/access/paleo-search/study/28630",
    status="harvested",
    expected_rows=28710,
)

# Порог, ниже которого узел-год попадает в слой.
#
# У PDSI есть общепринятая шкала Палмера: −2 — умеренная засуха, −3 — сильная,
# −4 и ниже — экстремальная. Порог по умолчанию — −4, и вот почему. Сетка
# частая (4259 узлов), а засуха — явление широкое: при −3 условие выполняется у
# каждого шестнадцатого узла-года, и слой перестаёт быть слоем событий,
# превращаясь в поле: 94 248 узлов-лет и 72 602 записи за 1600–1960 годы против
# 33 019 и 28 710 при −4. Экстремальная засуха — это тот случай, когда хлеб не
# родился совсем, и именно он объясняет запись в метрической книге. Кому нужна
# полная картина, ставит `--threshold -3`.
THRESHOLD = -4.0

# Годы по умолчанию. Нижняя граница — начало XVII века: раньше личных
# документов о простых родах почти не остаётся, и объяснять становится нечего.
# Верхняя — та же, что у остальных слоёв проекта: после 1960 года карта не
# идёт. Сам атлас доходит до 1400 года, и `--year-from` это открывает.
YEAR_FROM, YEAR_TO = 1600, 1960

# Шкала Палмера словами. Порядок важен: перебор идёт сверху вниз.
PALMER = (
    (-4.0, "экстремальная засуха"),
    (-3.0, "сильная засуха"),
    (-2.0, "умеренная засуха"),
    (-1.0, "слабая засуха"),
)

# Пропуски в матрице: OWDA пишет их как −99.999, netCDF-выгрузки — как NaN.
# Всё, что по модулю больше этого, значением не считается.
MISSING_ABOVE = 90.0

# PDSI за пределами этой величины не бывает: если такие числа пошли, разбор
# читает не тот столбец или не тот файл.
PDSI_LIMIT = 25.0


class DroughtError(RuntimeError):
    """Набор не скачался или устроен не так, как ждёт разбор."""


@dataclass(frozen=True)
class GridPoint:
    """Узел сетки атласа. Не населённое место — просто точка с координатой."""

    number: int
    lat: float
    lon: float


@dataclass(frozen=True)
class Atlas:
    """Скачанный и разобранный атлас: узлы, годы и ряд PDSI по каждому узлу."""

    dataset: Dataset
    points: dict[int, GridPoint]
    years: tuple[int, ...]
    series: dict[int, array]     # номер узла → PDSI по годам, в порядке `years`


@dataclass(frozen=True)
class Episode:
    """Засуха в одном узле сетки: подряд идущие годы ниже порога.

    Два сухих года подряд — это один голод, а не два события: хлеба не стало
    в первый год, а умирали во второй. Поэтому соседние годы сводятся в один
    эпизод с точными границами.
    """

    point: GridPoint
    year_from: int
    year_to: int
    worst: float          # самый низкий PDSI за эпизод
    worst_year: int
    values: tuple[float, ...]

    @property
    def category(self) -> str:
        return drought_class(self.worst)


# --- скачивание ------------------------------------------------------------

def fetch(url: str, *, timeout: int = 300) -> str:
    """Забирает текстовый файл набора."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8-sig", errors="replace")
    except urllib.error.HTTPError as exc:
        raise DroughtError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DroughtError(f"{url}: сеть недоступна ({exc.reason})") from exc


def load(dataset: Dataset, *, cache_dir: Optional[Path] = None,
         year_from: Optional[int] = None, year_to: Optional[int] = None) -> Atlas:
    """Скачивает (или берёт из кэша) оба файла набора и разбирает их.

    Матрица OWDA весит 87 МБ и покрывает две тысячи лет, из которых нам нужны
    три-четыре века, поэтому годы отсеиваются прямо при чтении: строка, не
    попавшая в окно, дальше первого числа не разбирается.
    """
    grid_text = _cached(dataset.grid_url, f"{dataset.key}-grid.txt", cache_dir)
    matrix_text = _cached(dataset.matrix_url, f"{dataset.key}-pdsi.txt", cache_dir)

    points = read_grid(grid_text.splitlines())
    years, series = read_matrix(matrix_text.splitlines(),
                                year_from=year_from, year_to=year_to)
    atlas = Atlas(dataset=dataset, points=points, years=years, series=series)
    check_atlas(atlas)
    return atlas


def _cached(url: str, name: str, cache_dir: Optional[Path]) -> str:
    """Наборы весят десятки мегабайт и не меняются — второй раз не качаем."""
    if cache_dir is None:
        return fetch(url)
    path = Path(cache_dir) / name
    if path.exists() and path.stat().st_size:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    text = fetch(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


# --- разбор ----------------------------------------------------------------

def read_grid(lines: Iterable[str]) -> dict[int, GridPoint]:
    """Читает таблицу узлов сетки.

    Оба набора NOAA дают её в двух видах: ERDA — по шаблону NOAA, с шапкой
    `gridpt longitude latitude` после строк-комментариев; OWDA — голыми
    столбцами `долгота широта i j файл` без шапки вовсе. Разбирается и то, и
    другое: если первая значащая строка начинается не с числа, она считается
    шапкой и колонки ищутся по именам, иначе колонки позиционные — в обоих
    наборах долгота стоит перед широтой.
    """
    rows = [line.split() for line in lines
            if line.strip() and not line.lstrip().startswith("#")]
    if not rows:
        raise DroughtError("таблица узлов сетки пуста")

    order = {"number": None, "lon": 0, "lat": 1}
    if _float(rows[0][0]) is None:
        header = [cell.strip().lower() for cell in rows.pop(0)]
        order = {
            "number": _index_of(header, ("gridpt", "point", "id", "номер")),
            "lon": _index_of(header, ("longitude", "lon", "долгота")),
            "lat": _index_of(header, ("latitude", "lat", "широта")),
        }
        if order["lon"] is None or order["lat"] is None:
            raise DroughtError(
                f"в шапке таблицы узлов нет долготы и широты; пришло: {header}. "
                "Формат набора изменился — поправьте разбор."
            )

    width = max(value for value in order.values() if value is not None) + 1
    points: dict[int, GridPoint] = {}
    for position, row in enumerate(rows, start=1):
        # Короткая строка — это оборванный файл (кэш дописался наполовину) или
        # другой формат. И то и другое должно остановить сбор своими словами,
        # а не упасть по IndexError где-то в разборе.
        if len(row) < width:
            raise DroughtError(
                f"в строке {position} таблицы узлов {len(row)} столбцов, нужно {width}: "
                f"{' '.join(row)[:80]!r}. Файл оборван или формат изменился."
            )
        number = _int(row[order["number"]]) if order["number"] is not None else position
        lat, lon = _float(row[order["lat"]]), _float(row[order["lon"]])
        if number is None or lat is None or lon is None or not valid_coords(lat, lon):
            raise DroughtError(f"узел сетки не разобран: {' '.join(row)[:80]!r}")
        points[number] = GridPoint(number=number, lat=lat, lon=lon)
    if not points:
        raise DroughtError("в таблице узлов сетки нет ни одной строки с координатами")
    return points


def read_matrix(lines: Iterable[str], *, year_from: Optional[int] = None,
                year_to: Optional[int] = None) -> tuple[tuple[int, ...], dict[int, array]]:
    """Читает матрицу «строка — год, колонка — узел сетки».

    Шапка обязательна: по ней колонка связывается с номером узла (`GP17` у
    ERDA, `17` у OWDA). Без шапки непонятно, какому узлу принадлежит столбец, —
    и это как раз тот случай, когда сбор должен остановиться, а не гадать.
    """
    header: Optional[list[int]] = None
    years: list[int] = []
    columns: list[array] = []

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if header is None:
            if _int(parts[0]) is not None:
                raise DroughtError(
                    "первая строка матрицы начинается с числа — шапки с номерами "
                    "узлов нет. Формат набора изменился, разбор остановлен."
                )
            header = [_column_number(cell, position)
                      for position, cell in enumerate(parts[1:], start=1)]
            columns = [array("f") for _ in header]
            continue

        year = _int(parts[0])
        if year is None:
            continue
        if year_from is not None and year < year_from:
            continue
        if year_to is not None and year > year_to:
            continue
        values = parts[1:]
        if len(values) != len(header):
            raise DroughtError(
                f"в строке за {year} год {len(values)} значений, а в шапке "
                f"{len(header)} узлов — матрица бьётся не так, как ожидалось."
            )
        years.append(year)
        for column, cell in zip(columns, values):
            column.append(_value(cell))

    if header is None:
        raise DroughtError("в матрице нет ни одной значащей строки")
    if not years:
        raise DroughtError("в матрице нет строк с годами в заданном окне")
    return tuple(years), dict(zip(header, columns))


def check_atlas(atlas: Atlas) -> None:
    """Проверяет то, на чём держится разбор. Не сошлось — сбор останавливается.

    Слой большой и однообразный: если набор переедет или сменит формат,
    молчаливая пустая (или, того хуже, сдвинутая на колонку) выгрузка потом не
    отыщется. Дешевле остановиться здесь.
    """
    if not atlas.points:
        raise DroughtError("в наборе нет узлов сетки")
    if not atlas.series:
        raise DroughtError("в наборе нет рядов PDSI")

    missing = sorted(set(atlas.series) - set(atlas.points))[:5]
    if missing:
        raise DroughtError(
            f"в матрице {len(atlas.series)} колонок, в сетке {len(atlas.points)} узлов; "
            f"колонкам {missing} узел не сопоставлен. Проверьте {atlas.dataset.grid_url}."
        )
    if len(atlas.series) < len(atlas.points):
        raise DroughtError(
            f"в сетке {len(atlas.points)} узлов, а в матрице только "
            f"{len(atlas.series)} колонок — файлы набора из разных выпусков."
        )

    finite = 0
    for column in atlas.series.values():
        for value in column:
            if math.isnan(value):
                continue
            finite += 1
            if abs(value) > PDSI_LIMIT:
                raise DroughtError(
                    f"значение PDSI {value} выходит за всякую шкалу — разбор читает "
                    "не тот столбец. Формат набора изменился."
                )
    if not finite:
        raise DroughtError("в матрице нет ни одного значения — одни пропуски")


# --- отбор аномалий --------------------------------------------------------

def usable_points(atlas: Atlas, *, require_bbox: bool = True,
                  exclude_bbox: Optional[tuple] = None) -> list[GridPoint]:
    """Узлы, которые вообще идут в слой: в охвате карты и не покрытые другим набором."""
    out = []
    for _, point in sorted(atlas.points.items()):
        if require_bbox and not in_bbox(point.lat, point.lon):
            continue
        if exclude_bbox is not None and in_bbox(point.lat, point.lon, exclude_bbox):
            continue
        out.append(point)
    return out


def find_episodes(atlas: Atlas, *, threshold: float = THRESHOLD,
                  year_from: int = YEAR_FROM, year_to: int = YEAR_TO,
                  require_bbox: bool = True,
                  exclude_bbox: Optional[tuple] = None) -> list[Episode]:
    """Годы, когда в узле было суше порога. Обычные годы в слой не идут.

    `exclude_bbox` выбрасывает узлы, которые уже покрыты другим набором:
    атласы перекрываются, и без этого одна и та же засуха попала бы в слой
    дважды — от ERDA и от OWDA.
    """
    if threshold >= 0:
        raise DroughtError(f"порог засухи должен быть отрицательным, задан {threshold}")

    window = [(position, year) for position, year in enumerate(atlas.years)
              if year_from <= year <= year_to]
    out: list[Episode] = []
    for point in usable_points(atlas, require_bbox=require_bbox,
                               exclude_bbox=exclude_bbox):
        column = atlas.series.get(point.number)
        if column is None:
            continue
        run: list[tuple[int, float]] = []
        for position, year in window:
            value = column[position]
            if not math.isnan(value) and value <= threshold:
                # Год отделён от предыдущего сухого пропуском — значит, это уже
                # другая засуха, а не продолжение той же.
                if run and year != run[-1][0] + 1:
                    out.append(_episode(point, run))
                    run = []
                run.append((year, value))
            elif run:
                out.append(_episode(point, run))
                run = []
        if run:
            out.append(_episode(point, run))
    return out


def _episode(point: GridPoint, run: Sequence[tuple[int, float]]) -> Episode:
    worst_year, worst = min(run, key=lambda pair: pair[1])
    return Episode(
        point=point,
        year_from=run[0][0],
        year_to=run[-1][0],
        worst=round(worst, 2),
        worst_year=worst_year,
        values=tuple(round(value, 2) for _, value in run),
    )


def edge_points(points: dict[int, GridPoint], step: float = 0.5) -> frozenset[int]:
    """Узлы на краю сетки: у них меньше восьми соседей.

    Реконструкция в таком узле опирается на хронологии только с одной стороны,
    а за краем её нет вовсе. Для восточной границы атласа это и есть «покрытие
    редеет к востоку», выраженное числом, а не оговоркой в описании.
    """
    grid = {(_cell(p.lon, step), _cell(p.lat, step)) for p in points.values()}
    out = set()
    for number, point in points.items():
        x, y = _cell(point.lon, step), _cell(point.lat, step)
        neighbours = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                         if (dx, dy) != (0, 0) and (x + dx, y + dy) in grid)
        if neighbours < 8:
            out.add(number)
    return frozenset(out)


def drought_class(pdsi: float) -> str:
    """Шкала Палмера словами."""
    for limit, name in PALMER:
        if pdsi <= limit:
            return name
    return "сухой год"


# --- записи единой схемы ---------------------------------------------------

def episodes_to_records(episodes: Iterable[Episode], dataset: Dataset, *,
                        edge: frozenset[int] = frozenset(),
                        spec: LayerSpec = DROUGHT_ATLAS) -> list[ContextRecord]:
    """Переводит эпизоды в записи схемы — по записи на узел и эпизод."""
    out = []
    for episode in episodes:
        point = episode.point
        span = f"{episode.year_from}" if episode.year_from == episode.year_to \
            else f"{episode.year_from}–{episode.year_to}"
        word = "года" if episode.year_from == episode.year_to else "годов"
        at_edge = point.number in edge
        out.append(spec.new_record(
            title=f"{episode.category.capitalize()} {span} {word}",
            category=episode.category,
            lat=point.lat, lon=point.lon,
            place_text=place_text(point),
            # Губерния и уезд намеренно пустые: у координаты нет текста, из
            # которого их достают, а приписать узлу губернию — значит её
            # выдумать. Подбор для этого слоя идёт по расстоянию.
            summary=build_summary(episode, at_edge),
            year_from=episode.year_from, year_to=episode.year_to,
            # Границы эпизода известны точно, огрублять нечего: атлас даёт
            # значение на каждый год.
            date_precision="year",
            period_raw=span,
            # Ссылка на публикацию у NOAA обязательна, и она идёт в само поле
            # источника: у всех записей набора оно одинаково, а `write_geojson`
            # такие поля выносит на уровень слоя — цитата пишется один раз.
            source=f"{dataset.title}, NOAA Paleoclimatology. {dataset.citation}",
            url=dataset.study_url,
            source_id=f"{dataset.key}:{point.number}:{episode.year_from}",
            confidence="grid_edge" if at_edge else "ok",
            extra={"pdsi": list(episode.values), "gridpt": point.number},
        ))
    return out


def to_records(atlas: Atlas, *, threshold: float = THRESHOLD,
               year_from: int = YEAR_FROM, year_to: int = YEAR_TO,
               require_bbox: bool = True, exclude_bbox: Optional[tuple] = None,
               spec: LayerSpec = DROUGHT_ATLAS) -> list[ContextRecord]:
    """Весь путь: атлас → выраженные засухи → записи схемы."""
    episodes = find_episodes(atlas, threshold=threshold, year_from=year_from,
                             year_to=year_to, require_bbox=require_bbox,
                             exclude_bbox=exclude_bbox)
    return episodes_to_records(episodes, atlas.dataset,
                               edge=edge_points(atlas.points, atlas.dataset.step),
                               spec=spec)


def place_text(point: GridPoint) -> str:
    """Место называется координатой: узел сетки не населённый пункт."""
    return (f"узел сетки {abs(point.lat):.2f}° {'с' if point.lat >= 0 else 'ю'}. ш., "
            f"{abs(point.lon):.2f}° {'в' if point.lon >= 0 else 'з'}. д.")


def build_summary(episode: Episode, at_edge: bool = False) -> str:
    """Короткая фраза: чем был год и откуда это известно.

    Коротко она не из скупости: запись в слое одна на узел и эпизод, их
    десятки тысяч, и всё, что повторяется в каждой, слой утяжеляет вдвое.
    Общее объяснение — что это реконструкция, чем ограничено покрытие и зачем
    слой нужен — стоит один раз в карточке слоя (`description`).
    """
    parts = [f"Летний индекс засушливости PDSI {_num(episode.worst)} — "
             f"{episode.category} по шкале Палмера"]
    if episode.year_to > episode.year_from:
        parts.append(f"сухих лет подряд {episode.year_to - episode.year_from + 1}, "
                     f"тяжелее всего {episode.worst_year}-й")
    if at_edge:
        parts.append("узел на краю атласа")
    return "; ".join(parts) + (". Реконструкция по кольцам деревьев в узле сетки, "
                               "а не наблюдение на месте: отсюда неурожай и всплеск "
                               "смертности в метрике.")


# --- мелочи ----------------------------------------------------------------

def _num(value: float) -> str:
    """Минус в подписи — типографский, как в остальных текстах проекта."""
    return f"{value:.1f}".replace("-", "−")


def _cell(value: float, step: float) -> int:
    """Номер ячейки сетки. Округление своё: round() у .5 ходит к чётному и
    склеивает соседние узлы в один — соседство после этого не считается."""
    return math.floor(value / step + 0.5)


def _index_of(header: Sequence[str], names: Sequence[str]) -> Optional[int]:
    for position, cell in enumerate(header):
        if cell in names:
            return position
    return None


def _column_number(cell: str, position: int) -> int:
    """«GP17» и «17» — это узел 17. Всё остальное — смена формата."""
    digits = cell.strip().lstrip("GPgp#").strip()
    number = _int(digits)
    if number is None:
        raise DroughtError(
            f"колонка {position} названа {cell!r} — номер узла из неё не читается. "
            "Формат набора изменился, разбор остановлен."
        )
    return number


def _int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _value(cell: str) -> float:
    """Значение PDSI или NaN, если это пропуск."""
    number = _float(cell)
    if number is None or math.isnan(number) or abs(number) >= MISSING_ABOVE:
        return float("nan")
    return number
