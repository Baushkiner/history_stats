"""Население городов 1800–1959 годов (пакет Buggle, Nafziger) и названия по GeoNames.

Сети нет. Строки панели сняты с `city_pop_panel.dta` как есть: Агрыз
(city_id 2, срезы с 1926 года), Волгоград (642, все срезы) и безымянная
точка в 10 км от любого места GeoNames. Места GeoNames — точки слоя
`settlements` (с их кириллицей, которая бывает не русской: «Валгаград»),
русские имена — строки `alternatenames/RU.txt`. Проверяется, что население
восстанавливается из логарифма до человека, что записи — точки по годам
до 1960 года, что название берётся русское, историческое — по году, а
ненадёжное сведение в заголовок не идёт.
"""

import pytest

from histctx.geo import SpatialIndex
from histctx.sources.city_population import (
    CITY_POPULATION, CityPopulationError, check_columns, cities, name_in_year, name_match,
    population, read_alt_names, records,
)
from histctx.sources.geonames import SETTLEMENTS
from histctx.sources.uezd_names import RistatDistricts


def _panel(city_id, lat, lon, uezd, province, pops):
    years = (1800, 1850, 1897, 1926, 1939, 1959, 1970, 1979, 1989, 2002)
    return [{"city_id": city_id, "year": y, "latitude_city": lat, "longitude_city": lon,
             "uezd": uezd, "province": province, "log_pop": pops.get(y)} for y in years]


AGRYZ = _panel(2, 56.52000045776367, 52.9900016784668, "Sarapul'skii", "Viatka",
               {1926: 8.901230812072754, 1939: 9.642706871032715, 1959: 9.91689682006836,
                2002: 9.831991195678711})
VOLGOGRAD = _panel(642, 48.720001220703125, 44.4900016784668, "Tsaritsynskii", "Saratov",
                   {1800: 8.294049263000488, 1850: 8.853665351867676, 1897: 10.918464660644531,
                    1926: 11.907464027404785, 1939: 13.00653076171875,
                    1959: 13.29190731048584, 2002: 13.826863288879395})
LONELY = _panel(999, 60.0, 60.0, "Verkhotur'skii", "Perm", {1959: 8.0})


def _settlement(gid, title, lat, lon, latin):
    return SETTLEMENTS.new_record(title=title, lat=lat, lon=lon, source_id=gid,
                                  url=f"https://www.geonames.org/{gid}",
                                  extra={"country": "Россия", "name_latin": latin})


SETTLEMENTS_INDEX = SpatialIndex([
    _settlement("583983", "Агриз", 56.5234, 52.99431, "Agryz"),
    _settlement("472757", "Валгаград", 48.71378, 44.4976, "Volgograd"),
])

ALT_LINES = [
    "2181373\t472757\tru\tВолгоград\t1\t\t\t\t\t\n",
    "2432961\t472757\tru\tЦарицын\t\t\t\t1\t\t\n",
    "2432962\t472757\tru\tСталинград\t\t\t\t1\t\t\n",
    "7584704\t472757\ttt\tВолгоград\t\t\t\t\t\t\n",
    "9528154\t472757\ten\tVolgograd\t1\t\t\t\t1961\t\n",
    "13634199\t472757\ten\tTsaritsyn\t\t\t\t1\t1589\t1925\n",
    "13634200\t472757\ten\tStalingrad\t\t\t\t1\t1925\t1961\n",
    "1717162\t583983\ten\tAgryz\t\t\t\t\t\t\n",
    "1934957\t583983\tru\tАгрыз\t\t\t\t\t\t\n",
    "8720177\t583983\ttt\tӘгерҗе\t\t\t\t\t\t\n",
]
NAMES_RU = read_alt_names(ALT_LINES, {"472757", "583983"})

DISTRICTS = RistatDistricts([
    {"properties": {"Distr_ID": 198, "Name_RU": "Сарапульский", "Name_ENG": "Sarapulskii",
                    "prov_RU": "Вятская губерния", "RISTAT_ID": "1897_95"}},
    {"properties": {"Distr_ID": 300, "Name_RU": "Царицынский", "Name_ENG": "Tsaritsynskii",
                    "prov_RU": "Саратовская губерния", "RISTAT_ID": "1897_70"}},
])


@pytest.fixture(scope="module")
def recs():
    return records(AGRYZ + VOLGOGRAD + LONELY, DISTRICTS, SETTLEMENTS_INDEX, NAMES_RU)


def test_population_restored_from_log():
    # Целые числа второй таблицы пакета: Царицын 1897 года — 55 186 человек
    # (по exp от float32 логарифма — 55 185,99…).
    assert population(10.918464660644531) == 55186
    assert population(None) is None
    assert cities(VOLGOGRAD)[642]["population"][1897] == 55186


def test_russian_names_and_dated_history():
    assert NAMES_RU["583983"] == {"name": "Агрыз", "historic": []}
    volgograd = NAMES_RU["472757"]
    assert volgograd["name"] == "Волгоград"
    # Годы — от английских двойников русских исторических названий.
    assert {"name": "Царицын", "from": 1589, "to": 1925} in volgograd["historic"]
    assert {"name": "Сталинград", "from": 1925, "to": 1961} in volgograd["historic"]
    match = {"names_historic": volgograd["historic"]}
    assert name_in_year(match, 1897) == "Царицын"
    assert name_in_year(match, 1939) == "Сталинград"
    assert name_in_year(match, 1961) is None


def test_name_match_kinds():
    town = name_match(48.72, 44.49, "Tsaritsynskii", SETTLEMENTS_INDEX, NAMES_RU)
    assert town["how"] == "nearest" and town["name"] == "Волгоград"
    assert town["title_settlements"] == "Валгаград"        # кириллица слоя — не русская
    agryz = name_match(56.52, 52.99, "Sarapul'skii", SETTLEMENTS_INDEX, NAMES_RU)
    assert agryz["how"] == "nearest" and agryz["name"] == "Агрыз"
    far = name_match(56.52 + 0.05, 52.99, None, SETTLEMENTS_INDEX, NAMES_RU)
    assert far["how"] == "uncertain"                       # ~5,5 км
    assert name_match(60.0, 60.0, None, SETTLEMENTS_INDEX, NAMES_RU) == {"how": "none"}
    # Корень уезда: «Сарапульский» → место «Сарапул» было бы uezd_town.
    sarapul = SpatialIndex([_settlement("1", "Сарапул", 56.47, 53.8, "Sarapul")])
    assert name_match(56.47, 53.8, "Sarapul'skii", sarapul)["how"] == "uezd_town"


def test_records_are_points_per_year_before_1960(recs):
    agryz = [r for r in recs if r.extra["city_id"] == 2]
    assert [r.year_from for r in agryz] == [1926, 1939, 1959]   # 2002 — за горизонтом
    assert all(r.has_point and r.scope == "point" for r in recs)
    rec = agryz[0]
    assert rec.title == "Агрыз: население в 1926 году"
    assert rec.category == "население города: перепись 1926 года"
    assert rec.district == "Сарапульский уезд" and rec.region == "Вятская губерния"
    assert "7 341 человек (перепись)" in rec.summary
    assert "Ряд по пакету: 1926 — 7 341; 1939 — 15 409; 1959 — 20 270." in rec.summary
    assert rec.extra["population"]["2002"] == 18620
    assert rec.extra["ristat_distr_id"] == "198"
    assert (rec.lat, rec.lon) == (56.52, 52.99)


def test_historic_name_in_title(recs):
    volgograd = {r.year_from: r for r in recs if r.extra["city_id"] == 642}
    assert sorted(volgograd) == [1800, 1850, 1897, 1926, 1939, 1959]
    assert volgograd[1897].title == "Царицын (ныне Волгоград): население в 1897 году"
    assert volgograd[1939].title == "Сталинград (ныне Волгоград): население в 1939 году"
    assert volgograd[1800].category == "население города: 1800 год (до переписей)"
    assert "оценка статьи" in volgograd[1800].summary
    assert "Прежние названия по GeoNames: Царицын (1589–1925)" in volgograd[1897].summary


def test_unnamed_city_is_marked(recs):
    lonely = [r for r in recs if r.extra["city_id"] == 999]
    assert len(lonely) == 1 and lonely[0].confidence == "name_uncertain"
    assert lonely[0].title.startswith("Город (")
    assert "в GeoNames ничего нет" in lonely[0].summary


def test_layer_and_columns():
    assert CITY_POPULATION.group == "admin" and "GeoNames" in CITY_POPULATION.license
    with pytest.raises(CityPopulationError, match="log_pop"):
        check_columns(["city_id", "year"])
