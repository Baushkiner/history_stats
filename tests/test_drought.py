"""Реконструкция засух: что попадает в слой, а что его останавливает.

Сети в тестах нет: образец — те же два файла, что лежат у NOAA, урезанные до
десяти узлов и пятнадцати лет. Форматов у наборов два — по шаблону NOAA (ERDA,
с шапкой и комментариями) и голыми столбцами (OWDA), — и проверяются оба:
разбор один, а спотыкается он как раз на таких мелочах.

Главное свойство слоя проверяется первым: обычный год в него не попадает.
Иначе карта заполнится записями «в 1734 году была погода».
"""

from pathlib import Path

import pytest

from histctx.schema import SCOPE_POINT
from histctx.sources.drought import (
    DROUGHT_ATLAS, ERDA, OWDA, Atlas, DroughtError, check_atlas, drought_class,
    edge_points, find_episodes, read_grid, read_matrix, to_records,
)

ROOT = Path(__file__).resolve().parents[1]

# Сетка по шаблону NOAA: комментарии, описание колонок, шапка. Девять узлов
# стоят квадратом 3×3 (середина — узел 5, у него есть все восемь соседей),
# десятый лежит под Лондоном — вне охвата РИ.
GRID_ERDA = """\
# The European Russia Drought Atlas (ERDA)
#---------------------------------------
# Variables
## gridpt\tsample identification,,,,,climate reconstructions,,,N,grid point number
## longitude\tlongitude,,,degree east,,climate reconstructions,,,N,
## latitude\tlatitude,,,degree north,,climate reconstructions,,,N,
#---------------------------------------
gridpt\tlongitude\tlatitude
1\t45.25\t53.25
2\t45.75\t53.25
3\t46.25\t53.25
4\t45.25\t53.75
5\t45.75\t53.75
6\t46.25\t53.75
7\t45.25\t54.25
8\t45.75\t54.25
9\t46.25\t54.25
10\t0.25\t51.75
"""

# Та же сетка в виде, в каком её отдаёт OWDA: ни комментариев, ни шапки —
# долгота, широта и служебные столбцы, номер узла подразумевается порядком.
GRID_OWDA = """\
    45.25   53.25    394   235  scPDSI.dat.
    45.75   53.25    395   235  scPDSI.dat.
    46.25   53.25    396   235  scPDSI.dat.
"""

# Матрица: строка — год, колонка — узел. Норма ровная, испорчены отдельные
# годы: 1601-й — экстремальная засуха в узлах 1, 5 и 10, 1605-й — сильная (по
# умолчанию в слой не идёт), 1609–1610 — два сухих года подряд.
MATRIX_ERDA = """\
# The European Russia Drought Atlas (ERDA)
# Variables
## year\tage,,,years Common Era,,climate reconstructions,,,,
## GP1\tPalmer Drought Severity Index,,,,Jun-Aug,climate reconstructions,,,N,
#---------------------------------------
year\tGP1\tGP2\tGP3\tGP4\tGP5\tGP6\tGP7\tGP8\tGP9\tGP10
1598\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1599\t0.40\t0.40\t0.40\t0.40\t-4.80\t0.40\t0.40\t0.40\t0.40\t0.40
1600\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1601\t-4.40\t0.40\t-99.999\t0.40\t-4.60\t0.40\t0.40\t0.40\t0.40\t-6.00
1602\t0.40\tNaN\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1603\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1604\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1605\t0.40\t0.40\t0.40\t0.40\t-3.20\t0.40\t0.40\t0.40\t0.40\t0.40
1606\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1607\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1608\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1609\t0.40\t0.40\t0.40\t0.40\t-4.10\t0.40\t0.40\t0.40\t0.40\t0.40
1610\t0.40\t0.40\t0.40\t0.40\t-5.30\t0.40\t0.40\t0.40\t0.40\t0.40
1611\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
1612\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40\t0.40
"""

# Матрица OWDA: та же суть, другая шапка и пробелы вместо табуляций.
MATRIX_OWDA = """\
 year__#       1       2       3
    1600   0.400   0.400   0.400
    1601  -4.400 -99.999   0.400
    1602   0.400   0.400   0.400
"""


def atlas(grid=GRID_ERDA, matrix=MATRIX_ERDA, dataset=ERDA, **kwargs) -> Atlas:
    """Разобранный образец: как после скачивания, но без сети."""
    points = read_grid(grid.splitlines())
    years, series = read_matrix(matrix.splitlines(), **kwargs)
    built = Atlas(dataset=dataset, points=points, years=years, series=series)
    check_atlas(built)
    return built


def records(**kwargs):
    return to_records(atlas(), year_from=1600, year_to=1960, **kwargs)


def without_droughts(matrix: str) -> str:
    """Тот же образец, из которого убраны все испорченные годы."""
    out = []
    for line in matrix.splitlines():
        head = line.split()[0] if line.split() else ""
        if head.isdigit() and ("-" in line or "NaN" in line):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


# --- разбор двух форматов --------------------------------------------------

def test_grid_with_a_header_is_read_by_column_names():
    points = read_grid(GRID_ERDA.splitlines())
    assert len(points) == 10
    assert (points[5].lat, points[5].lon) == (53.75, 45.75)


def test_grid_without_a_header_is_read_by_position():
    """У OWDA шапки нет вовсе: долгота, широта, номер — по порядку строк."""
    points = read_grid(GRID_OWDA.splitlines())
    assert len(points) == 3
    assert (points[1].lat, points[1].lon) == (53.25, 45.25)
    assert points[3].number == 3


def test_matrix_columns_are_tied_to_grid_points():
    """«GP5» у ERDA и «5» у OWDA — это один и тот же пятый узел сетки."""
    years, series = read_matrix(MATRIX_ERDA.splitlines())
    assert years[0] == 1598 and years[-1] == 1612
    assert sorted(series) == list(range(1, 11))
    owda_years, owda_series = read_matrix(MATRIX_OWDA.splitlines())
    assert owda_years == (1600, 1601, 1602)
    assert sorted(owda_series) == [1, 2, 3]


def test_gaps_are_not_droughts():
    """−99.999 и NaN — это «сведений нет», а не «сушь под минус сто»."""
    recs = records()
    assert not [r for r in recs if r.source_id.startswith("erda:3:")]
    assert not [r for r in recs if r.source_id.startswith("erda:2:")]


# --- что считается засухой -------------------------------------------------

def test_dry_year_becomes_a_record():
    rec = [r for r in records() if r.source_id == "erda:5:1601"][0]
    assert (rec.lat, rec.lon) == (53.75, 45.75)
    assert (rec.year_from, rec.year_to) == (1601, 1601)
    assert rec.category == "экстремальная засуха"
    assert rec.title == "Экстремальная засуха 1601 года"
    assert "PDSI −4.6" in rec.summary
    assert rec.mappable and rec.usable


def test_ordinary_years_produce_nothing():
    """Год без засухи — не событие: в слое ему делать нечего."""
    assert to_records(atlas(matrix=without_droughts(MATRIX_ERDA))) == []


def test_consecutive_dry_years_are_one_episode():
    """Два сухих года подряд — один голод, а не два события."""
    episode = [r for r in records() if r.source_id == "erda:5:1609"][0]
    assert (episode.year_from, episode.year_to) == (1609, 1610)
    assert episode.period_raw == "1609–1610"
    assert "сухих лет подряд 2" in episode.summary
    assert "тяжелее всего 1610-й" in episode.summary
    assert episode.extra["pdsi"] == [-4.1, -5.3]


def test_threshold_is_adjustable():
    """Порог со шкалы Палмера: при −3 в слой входит и сильная засуха."""
    assert not [r for r in records() if r.source_id == "erda:5:1605"]
    softer = to_records(atlas(), threshold=-3.0, year_from=1600, year_to=1960)
    mild = [r for r in softer if r.source_id == "erda:5:1605"][0]
    assert mild.category == "сильная засуха"
    assert drought_class(-2.5) == "умеренная засуха"


def test_positive_threshold_is_refused():
    """Порог засухи не бывает положительным — это ошибка вызова, а не пустой слой."""
    with pytest.raises(DroughtError):
        find_episodes(atlas(), threshold=1.0)


def test_year_window_cuts_the_ends():
    """1599 год за окном по умолчанию, но набор его знает."""
    assert not [r for r in records() if r.source_id == "erda:5:1599"]
    early = to_records(atlas(), year_from=1500, year_to=1960)
    assert [r for r in early if r.source_id == "erda:5:1599"]


# --- место, которого нет ---------------------------------------------------

def test_grid_node_is_not_a_settlement():
    """Узел сетки — координата, а не село: губернию по нему не выдумываем."""
    rec = [r for r in records() if r.source_id == "erda:5:1601"][0]
    assert rec.scope == SCOPE_POINT
    assert rec.region is None and rec.district is None and rec.regions == []
    assert rec.place_text == "узел сетки 53.75° с. ш., 45.75° в. д."


def test_edge_of_the_grid_is_marked():
    """Покрытие кончается краем сетки, и это видно в самой записи."""
    edge = edge_points(atlas().points)
    assert 5 not in edge and 1 in edge
    by_id = {r.source_id: r for r in records()}
    assert by_id["erda:5:1601"].confidence == "ok"
    assert by_id["erda:1:1601"].confidence == "grid_edge"
    assert "узел на краю атласа" in by_id["erda:1:1601"].summary


def test_point_outside_the_country_is_skipped():
    """Атлас захватывает и Западную Европу — её узлы на нашу карту не идут."""
    assert not [r for r in records() if r.source_id.startswith("erda:10:")]
    assert [r for r in to_records(atlas(), year_from=1600, year_to=1960,
                                  require_bbox=False)
            if r.source_id.startswith("erda:10:")]


# --- права и проверяемость -------------------------------------------------

def test_record_carries_the_link_and_the_citation():
    """Условие 4 каталога: до источника можно дойти от любой записи."""
    rec = records()[0]
    assert rec.url == ERDA.study_url
    assert "doi:10.1007/s00382-019-05115-2" in rec.source
    assert "общественное достояние" in rec.license
    assert rec.layer == DROUGHT_ATLAS.slug


def test_overlap_of_two_atlases_is_not_counted_twice():
    """Второй набор берётся кромкой: в общей полосе точнее основной."""
    covered = ERDA.bbox
    assert not to_records(atlas(), year_from=1600, year_to=1960,
                          exclude_bbox=covered)
    # Тот же образец, сдвинутый западнее ERDA, в кромку попадает.
    west = GRID_ERDA.replace("45.25", "18.25").replace("45.75", "18.75")
    assert to_records(atlas(grid=west), year_from=1600, year_to=1960,
                      exclude_bbox=covered)


def test_second_atlas_names_itself_in_the_record():
    years, series = read_matrix(MATRIX_OWDA.splitlines())
    owda = Atlas(dataset=OWDA, points=read_grid(GRID_OWDA.splitlines()),
                 years=years, series=series)
    rec = to_records(owda, year_from=1600, year_to=1960)[0]
    assert rec.source_id == "owda:1:1601"
    assert "Old World Drought Atlas" in rec.source
    assert rec.url == OWDA.study_url


# --- смена формата останавливает сбор --------------------------------------

def test_matrix_without_a_header_stops_the_harvest():
    with pytest.raises(DroughtError, match="шапки"):
        read_matrix(["1601\t-4.40\t0.40"])


def test_unreadable_column_name_stops_the_harvest():
    with pytest.raises(DroughtError, match="номер узла"):
        read_matrix(["year\tPDSI_west\tPDSI_east", "1601\t-4.40\t0.40"])


def test_short_row_stops_the_harvest():
    with pytest.raises(DroughtError, match="значений"):
        read_matrix(["year\tGP1\tGP2", "1601\t-4.40"])


def test_truncated_grid_row_stops_the_harvest():
    """Оборванный кэш — тоже смена формата: падать по IndexError нельзя."""
    with pytest.raises(DroughtError, match="столбцов"):
        read_grid(["gridpt\tlongitude\tlatitude", "1\t45.25\t53.25", "2\t45.75"])


def test_grid_without_coordinates_stops_the_harvest():
    with pytest.raises(DroughtError, match="долготы и широты"):
        read_grid(["gridpt\tname\tregion", "1\tМосква\tМосковская"])


def test_grid_and_matrix_from_different_releases_stop_the_harvest():
    """Колонок больше, чем узлов, — файлы из разных выпусков набора."""
    points = read_grid(GRID_OWDA.splitlines())          # три узла
    years, series = read_matrix(MATRIX_ERDA.splitlines())  # десять колонок
    with pytest.raises(DroughtError, match="узел не сопоставлен"):
        check_atlas(Atlas(dataset=ERDA, points=points, years=years, series=series))


def test_impossible_pdsi_stops_the_harvest():
    """Шкала PDSI не уходит за пределы двух десятков — значит, читается не то."""
    broken = MATRIX_ERDA.replace("1601\t-4.40", "1601\t-44.0")
    with pytest.raises(DroughtError, match="шкалу"):
        atlas(matrix=broken)


# --- слой в каталоге -------------------------------------------------------

def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    assert DROUGHT_ATLAS.slug in BY_SLUG
    assert BY_SLUG[DROUGHT_ATLAS.slug].status == "harvested"
    assert "Урал" in BY_SLUG[DROUGHT_ATLAS.slug].description
