"""Засухи по GEDA за пределами ERDA: какие узлы идут в слой и что в записи.

h5py в тестах не нужен: файл набора в тест не тащится, а всё, что решает —
сито узлов, порог, шкала словами, запись, — работает на списках. Образец —
настоящие значения GEDA за 1914–1920 годы в шести узлах: Фергана и
Самарканд (засуха 1917 года, с которой начался голод в Туркестане), Омск,
Самара (внутри ERDA), Кашгар (Китай) и Каспий (пропуск — заполнитель
NetCDF, а не NaN). Граница «России» в тесте — нарисованный руками
прямоугольник: настоящий полигон CShapes в тест не помещается.
"""

import json
import math
import sys

import pytest

from histctx.registry import BY_SLUG
from histctx.sources.drought import find_episodes
from histctx.sources.drought_geda import (
    DOI_URL, DROUGHT_ATLAS_GEDA, FILE_MD5, FILE_NAME, FILE_SIZE, REASON_ABROAD,
    REASON_ERDA, REASON_SEA, THRESHOLD, Cube, GedaError, Territory, agreement, check_record,
    clean, episodes_to_records, make_keep, node_number, open_netcdf, read_atlas, sigma_class,
)

FILL = 9.969209968386869e36       # _FillValue NetCDF: так в файле записано море

YEARS = (1914, 1915, 1916, 1917, 1918, 1919, 1920)
LATS = (39.25, 39.75, 40.25, 42.25, 53.25, 54.75)
LONS = (50.25, 50.75, 66.75, 71.75, 73.25, 75.75)

# (широта, долгота) → ряд за 1914–1920 годы, как в geda_trim.nc.
REAL = {
    (40.25, 71.75): [-0.17, -0.49, 0.01, -3.05, -2.11, -0.09, 0.67],   # Фергана
    (39.75, 66.75): [-0.05, -0.39, 0.25, -2.49, -1.94, -0.13, 0.78],   # Самарканд
    (39.25, 75.75): [-0.47, 0.06, -0.02, -1.23, -1.0, -0.76, 1.41],    # Кашгар
    (53.25, 50.25): [-0.99, 1.13, 0.24, 0.46, 2.03, -1.29, -0.36],     # Самара
    (42.25, 50.75): [FILL] * 7,                                        # Каспий
    (54.75, 73.25): [0.95, -0.45, -0.5, 0.54, 0.39, 1.19, -0.63],      # Омск
}

# «Россия» для теста: прямоугольник 45–74° в. д., 39.5–60° с. ш. Кашгар
# (75.75° в. д.) за ним, как и настоящий Китай за настоящей границей.
RUSSIA = {"type": "Polygon",
          "coordinates": [[[45, 39.5], [74, 39.5], [74, 60], [45, 60], [45, 39.5]]]}


def fake_cube():
    def read(t, i, j):
        def column(a, b):
            key = (LATS[i.start + a], LONS[j.start + b])
            return REAL.get(key, [FILL] * len(YEARS))[t]
        return column
    return Cube(years=YEARS, lats=LATS, lons=LONS, units="sigma", comment="образец",
                read=read)


def atlas_and_reasons(threshold_years=(1914, 1920)):
    return read_atlas(fake_cube(), keep=make_keep(Territory([RUSSIA])),
                      year_from=threshold_years[0], year_to=threshold_years[1])


def test_layer_takes_only_empire_outside_erda():
    atlas, reasons = atlas_and_reasons()
    places = {(p.lat, p.lon) for p in atlas.points.values()}
    assert places == {(40.25, 71.75), (39.75, 66.75), (54.75, 73.25)}
    # Самара — внутри ERDA, Кашгар — за границей, Каспий — без данных.
    assert reasons[REASON_ERDA] >= 1
    assert reasons[REASON_ABROAD] >= 1
    assert reasons["в слое"] == 3


def test_sea_is_a_fill_value_not_nan():
    assert math.isnan(clean(FILL))
    assert math.isnan(clean(float("nan")))
    assert clean(-3.05) == -3.05
    # Узел с одними заполнителями внутри «России» — море, а не узел.
    keep = make_keep(Territory([RUSSIA]), exclude_bbox=None)
    cube = fake_cube()
    atlas, reasons = read_atlas(cube, keep=keep, year_from=1914, year_to=1920)
    assert (42.25, 50.75) not in {(p.lat, p.lon) for p in atlas.points.values()}
    assert reasons[REASON_SEA] >= 1


def test_node_number_is_its_place_in_the_whole_file():
    atlas, _ = atlas_and_reasons()
    fergana = next(p for p in atlas.points.values() if (p.lat, p.lon) == (40.25, 71.75))
    assert fergana.number == node_number(LATS.index(40.25), LONS.index(71.75), len(LONS))


def test_1917_turkestan_drought_is_found_and_ordinary_years_are_not():
    atlas, _ = atlas_and_reasons()
    episodes = find_episodes(atlas, threshold=THRESHOLD, year_from=1914, year_to=1920)
    # Фергана: −3.05σ в 1917 году. Самарканд с −2.49σ до порога −2.5 не дотянул,
    # а Омск засухи не знал вовсе.
    assert [(e.point.lat, e.year_from, e.year_to, e.worst) for e in episodes] == \
        [(40.25, 1917, 1917, -3.05)]
    # При −2σ засуха двухлетняя и у Ферганы, и у Самарканда — один эпизод на узел.
    wider = find_episodes(atlas, threshold=-1.9, year_from=1914, year_to=1920)
    assert sorted((e.point.lat, e.year_from, e.year_to) for e in wider) == \
        [(39.75, 1917, 1918), (40.25, 1917, 1918)]


def test_record_says_sigma_not_palmer_and_cites_the_set():
    atlas, _ = atlas_and_reasons()
    episodes = find_episodes(atlas, threshold=-1.9, year_from=1914, year_to=1920)
    records = episodes_to_records(episodes)
    rec = next(r for r in records if r.lat == 40.25)
    assert rec.layer == "drought_atlas_geda"
    assert rec.title == "Исключительная засуха 1917–1918 годов"
    assert rec.category == "исключительная засуха"
    assert "σ от нормы 1000–2020 годов" in rec.summary and "Палмер" not in rec.summary
    assert "тяжелее всего 1917-й" in rec.summary
    assert rec.year_from == 1917 and rec.year_to == 1918 and rec.date_precision == "year"
    assert rec.url == DOI_URL
    assert "10.5281/zenodo.11059894" in rec.source and "Journal of Climate" in rec.source
    assert "CC BY 4.0" in rec.license
    assert rec.extra == {"sigma": [-3.05, -2.11], "gridpt": node_number(2, 3, len(LONS))}
    assert rec.source_id.startswith("geda:")
    # Губерния не выдумывается: узел сетки — не населённое место.
    assert not rec.region
    # Заголовок и uid стабильны: пересборка не меняет ссылок на запись.
    again = episodes_to_records(episodes)
    assert [r.uid for r in again] == [r.uid for r in records]


def test_sigma_scale_in_words():
    assert sigma_class(-3.05) == "исключительная засуха"
    assert sigma_class(-2.5) == "исключительная засуха"
    assert sigma_class(-2.49) == "экстремальная засуха"
    assert sigma_class(-2.0) == "экстремальная засуха"
    assert sigma_class(-1.5) == "сильная засуха"
    assert sigma_class(-1.0) == "умеренная засуха"
    assert sigma_class(-0.5) == "сухой год"


def test_territory_handles_holes_and_several_periods():
    square = {"type": "Polygon", "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],          # дырка
    ]}
    later = {"type": "MultiPolygon", "coordinates": [
        [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]],
    ]}
    territory = Territory([square, later])
    assert territory.contains(2.25, 2.25)
    assert not territory.contains(5.25, 5.25)          # в дырке
    assert territory.contains(5.25, 25.25)             # во втором периоде
    assert not territory.contains(5.25, 15.25)         # между ними
    assert not territory.contains(12.25, 2.25)


def test_coastal_cell_is_kept_but_a_border_cell_abroad_is_not():
    # Обобщённый полигон кончается на 60.1° с. ш., а GEDA видит сушу в клетке
    # 60.25: её центр — в «море», угол — в России. Клетка же с центром в «Китае»
    # не берётся, хоть её угол и заходит в Россию.
    china = {"type": "Polygon",
             "coordinates": [[[74, 30], [100, 30], [100, 50], [74, 50], [74, 30]]]}
    # Граница «России» здесь не по линиям углов клеток (.0 и .5), а между ними:
    # точка ровно на ребре полигона внутренней не считается.
    land = {"type": "Polygon",
            "coordinates": [[[45, 39.6], [74.1, 39.6], [74.1, 60.1], [45, 60.1], [45, 39.6]]]}
    russia, foreign = Territory([land]), Territory([china])
    keep = make_keep(russia, foreign=foreign, exclude_bbox=None)
    assert keep(60.25, 70.25) is None                       # побережье
    assert keep(45.25, 74.25) == REASON_ABROAD              # центр в «Китае»
    assert keep(70.25, 70.25) == REASON_ABROAD              # далеко от границы
    # Без списка чужих государств правило строгое — только центр.
    assert make_keep(russia, exclude_bbox=None)(60.25, 70.25) == REASON_ABROAD


def test_territory_takes_only_russia_from_cshapes(tmp_path):
    china = {"type": "Polygon",
             "coordinates": [[[74, 30], [100, 30], [100, 50], [74, 50], [74, 30]]]}
    path = tmp_path / "state_borders.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"gwcode": 365}, "geometry": RUSSIA},
        {"type": "Feature", "properties": {"gwcode": 710}, "geometry": china},
    ]}), encoding="utf-8")
    territory = Territory.load(path)
    assert len(territory) == 1
    assert territory.contains(40.25, 71.75)
    assert not territory.contains(39.25, 75.75)
    others = Territory.load(path, others=True)
    assert others.contains(39.25, 75.75) and not others.contains(40.25, 71.75)


def test_missing_borders_stop_the_harvest(tmp_path):
    with pytest.raises(GedaError, match="harvest_cshapes"):
        Territory.load(tmp_path / "нет.geojson")


def record(**overrides):
    base = {
        "entries": [{"key": FILE_NAME, "size": FILE_SIZE, "checksum": f"md5:{FILE_MD5}"}],
    }
    base.update(overrides)
    return base


def test_zenodo_record_is_checked_against_the_code():
    assert check_record(record()) == []
    changed = record(entries=[{"key": FILE_NAME, "size": 1, "checksum": "md5:0"}])
    assert len(check_record(changed)) == 2
    assert check_record(record(entries=[]))


def test_without_h5py_the_error_says_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "h5py", None)
    with pytest.raises(GedaError, match="pip install h5py"):
        open_netcdf(tmp_path / FILE_NAME)


def test_agreement_finds_the_sigma_of_equal_rarity():
    # ERDA и GEDA в одном узле: GEDA — тот же ряд, делённый на два.
    erda = [-5.0, -4.0, -3.0, -1.0, 0.0, 1.0, 2.0, 3.0, 0.5, -0.5]
    geda = [v / 2 for v in erda]
    got = agreement([(erda, geda)], palmer=(-4.0,))
    share, sigma, hit = got.levels[-4.0]
    assert got.nodes == 1 and got.pairs == 10
    assert share == pytest.approx(0.2)
    assert sigma == pytest.approx(-2.0)
    assert hit == 1.0
    assert got.median_r == pytest.approx(1.0)


def test_layer_is_registered_with_rights_in_words():
    spec = BY_SLUG["drought_atlas_geda"]
    assert spec is DROUGHT_ATLAS_GEDA
    assert spec.status == "harvested" and spec.expected_rows
    assert "CC BY 4.0" in spec.license
    assert spec.url == DOI_URL
