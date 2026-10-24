"""Слой «Церковные приходы»: заголовок запроса, заимствованная точка, рамка.

Сети в тестах нет: образец — строки, снятые с живого сбора
`python3 scripts/harvest.py --layer parishes` 24.10.2026 и урезанные до
нужных полей. Взяты нарочно разные случаи: польский приход со своей точкой
и датой, приход, чья точка взята у храма (`^P5607`), финский приход, чья
точка взята у церкви, которой он владеет (`^P127`), и приход, у которого
точка — его село (`P131`).

Что здесь удерживается:

* у прихода своя `P625` есть не всегда — у финских почти никогда (14 из
  592), — и первая ступень не должна требовать координату, а вторая обязана
  спросить её у храма и у села, причём у села — только если это населённый
  пункт, а не гмина;
* из трёх храмов прихода на карту идёт всегда один и тот же: иначе точка,
  а с ней `uid`, гуляли бы от сбора к сбору;
* рамка — губернии 1897 года, а не прямоугольник: Краков (Галиция) в него
  попадает, а запад Калишской губернии из него выпадает.
"""

import importlib.util
import json
from pathlib import Path

from histctx.frame import OUTSIDE, Banded, Frame
from histctx.registry import BY_SLUG
from histctx.sources.wikidata import (
    OPEN_END_YEAR, SETTLEMENT, dedupe, details_query, ids_query, rows_to_records,
    sort_by_place,
)

ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "queries" / "parishes.rq"

_META = None
_MOD = None


def _harvest():
    """`harvest.py` при загрузке правит sys.path — грузим один раз."""
    global _MOD
    if _MOD is None:
        spec = importlib.util.spec_from_file_location(
            "harvest_mod", ROOT / "scripts" / "harvest.py")
        _MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MOD)
    return _MOD


def _meta():
    global _META
    if _META is None:
        _META = _harvest().parse_query(QUERY)
    return _META


def _row(qid, title, coord, source, **extra):
    row = {
        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "itemLabel": {"value": title},
        "coord": {"value": coord},
        "coordSource": {"value": source},
        "typeLabel": {"value": "церковный приход"},
    }
    for key, value in extra.items():
        row[key] = {"value": value}
    return row


# Образец ответа второй ступени (details_query с @place и @label).
ROWS = [
    _row("Q11128605", "Parafia Wniebowzięcia Najświętszej Maryi Panny w Węgrowie",
         "Point(22.0187 52.3989)", "own",
         start="1414-01-01T00:00:00Z", adminLabel="Венгрув",
         x_diocese="Епархия Дрохичина"),
    # Тот же приход второй строкой: храм тоже даёт точку, но своя главнее.
    _row("Q11128605", "Parafia Wniebowzięcia Najświętszej Maryi Panny w Węgrowie",
         "Point(22.0190 52.3990)", "^P5607",
         start="1414-01-01T00:00:00Z", adminLabel="Венгрув",
         x_diocese="Епархия Дрохичина"),
    _row("Q106936425", "Приход храма в честь святителя Спиридона Тримифунтского",
         "Point(49.612112 53.510423)", "^P5607",
         adminLabel="Сельское поселение Васильевка",
         x_religion="православие", x_diocese="Тольяттинская епархия"),
    _row("Q10545469", "Kimitoön parish", "Point(22.472749 60.072944)", "^P127",
         x_religion="Евангелическо-лютеранская церковь Финляндии",
         x_diocese="диоцез Порвоо"),
    _row("Q106366790", "Parafia św. Teresy z Ávili w Szczuczynie",
         "Point(24.7425 53.604444)", "P131", adminLabel="Щучин"),
]


def test_header_declares_the_class_and_the_directives():
    meta = _meta()
    assert meta["layer"] == "parishes"
    assert meta["scope"] == "country"
    assert meta["kind"] == "object"
    assert dict(meta["qids"]) == {"Q102496": "церковный приход"}
    # Порядок путей — порядок точности: храм раньше села, село — последним.
    assert _harvest().place_tokens(meta) == ("^P5607", "^P127", "P159", "P276", "P131")
    assert meta["labels"] == [("P708", "diocese"), ("P140", "religion")]
    assert meta["frame"] == "1897"
    assert _harvest().check_directives(meta) == []


def test_first_stage_does_not_ask_for_a_coordinate():
    """Своя точка есть у 14 финских приходов из 592 — её ищут на второй ступени."""
    meta = _meta()
    sparql = ids_query([q for q, _ in meta["qids"]], "Q33", meta["filters"],
                       need_coord=False)
    assert "P625" not in sparql
    assert "wdt:P17 wd:Q33" in sparql
    assert "wdt:P31/wdt:P279* ?cls" in sparql
    # Дата отсекается, как у ярмарок, с тем же порогом и той же оговоркой
    # про пустой узел «дата неизвестна».
    assert f"YEAR(?founded) <= {OPEN_END_YEAR}" in sparql
    assert "!isLiteral(?founded)" in sparql


def test_other_layers_keep_the_coordinate_in_the_first_stage():
    assert "wdt:P625 ?coord" in ids_query(["Q16970"], "Q159")


def test_second_stage_borrows_the_point_in_declared_order():
    meta = _meta()
    sparql = details_query(["Q1"], place=_harvest().place_tokens(meta),
                           labels=tuple(meta["labels"]))
    assert "OPTIONAL { ?item wdt:P625 ?ownCoord . }" in sparql
    # Обратные пути: храм сам указывает на приход.
    assert "?pb1 wdt:P5607 ?item ; wdt:P625 ?pc1 ." in sparql
    assert "?pb2 wdt:P127 ?item ; wdt:P625 ?pc2 ." in sparql
    # Прямые пути — только к населённому пункту: гмина дала бы точку в своей
    # середине, а выглядела бы на карте как настоящая.
    assert f"?pp5 wdt:P31/wdt:P279* wd:{SETTLEMENT}" in sparql
    assert "COALESCE(?ownCoord, ?pc1, ?pc2, ?pc3, ?pc4, ?pc5)" in sparql
    assert "FILTER(BOUND(?coord))" in sparql
    assert "?coordSource" in sparql
    assert "?x_diocese" in sparql and "p:P708" in sparql
    assert "?x_religion" in sparql and "p:P140" in sparql


def test_plain_layers_get_the_same_second_stage_as_before():
    """Слои без @place и @label запрос не меняют: по нему считаются `uid`."""
    sparql = details_query(["Q1"])
    assert "?coordSource" not in sparql
    assert "x_" not in sparql
    assert "  ?item wdt:P625 ?coord .\n" in sparql


def test_rows_become_records_with_borrowed_points_marked():
    spec = BY_SLUG["parishes"]
    place = _harvest().place_tokens(_meta())
    records = {r.source_id: r for r in dedupe(rows_to_records(
        sort_by_place(ROWS, place), spec, require_bbox=False))}
    assert len(records) == 4

    wegrow = records["Q11128605"]
    assert wegrow.confidence == "ok", "своя точка главнее точки храма"
    assert (round(wegrow.lon, 4), round(wegrow.lat, 4)) == (22.0187, 52.3989)
    assert "coord_via" not in wegrow.extra
    assert wegrow.extra["diocese"] == "Епархия Дрохичина"
    assert wegrow.year_from == 1414 and wegrow.year_to == OPEN_END_YEAR

    church = records["Q106936425"]
    assert church.confidence == "place_level"
    assert church.extra == {"coord_via": "^P5607", "religion": "православие",
                            "diocese": "Тольяттинская епархия"}

    assert records["Q10545469"].extra["coord_via"] == "^P127"
    village = records["Q106366790"]
    assert village.extra["coord_via"] == "P131"
    assert village.place_text == "Щучин"


def test_the_same_church_wins_whatever_order_the_service_answers():
    """Три храма у прихода — на карте всегда один и тот же."""
    rows = [
        _row("Q5", "Приход", f"Point(2{n} 52)", "^P5607") for n in (3, 1, 2)
    ]
    place = ("^P5607", "P131")
    first = dedupe(rows_to_records(sort_by_place(rows, place), BY_SLUG["parishes"],
                                   require_bbox=False))
    again = dedupe(rows_to_records(sort_by_place(rows[::-1], place), BY_SLUG["parishes"],
                                   require_bbox=False))
    assert first[0].lon == again[0].lon == 21
    assert first[0].uid == again[0].uid


def test_bad_directives_are_caught_by_check():
    mod = _harvest()
    base = {"layer": "x", "scope": "country", "kind": "object", "labels": []}
    assert mod.check_directives({**base, "place": "P131 храм"})
    assert mod.check_directives({**base, "place": ""})
    assert mod.check_directives({**base, "place": "P131", "kind": "event"})
    assert mod.check_directives({**base, "place": "P131", "scope": "box"})
    assert mod.check_directives({**base, "labels": [("P708", "")]})
    assert mod.check_directives({**base, "frame": "1926"})
    assert mod.check_directives({**base, "place": "^P5607 P131",
                                 "labels": [("P708", "diocese")], "frame": "1897"}) == []


# --- рамка ------------------------------------------------------------------

def _square(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def _boundaries(tmp_path):
    """Губернии и государства в миниатюре, с теми же полями, что у настоящих.

    Калишская губерния заходит западнее 18-го меридиана, Келецкая — рядом с
    Галицией; Россия (СССР) берёт «Львов»; Австро-Венгрия — «Краков»;
    Финляндия — «Аланды»; между Финляндией и губерниями — вода.
    """
    provinces = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"prov_RU": "Калишская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(17.5, 51.5, 19.0, 52.5)}},
        {"type": "Feature", "properties": {"prov_RU": "Келецкая губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(19.5, 50.3, 21.0, 51.2)}},
        {"type": "Feature", "properties": {"prov_RU": "Нюландская губерния"},
         "geometry": {"type": "Polygon", "coordinates": _square(23.0, 60.0, 26.0, 61.0)}},
    ]}
    states = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"state": "Россия (Советский Союз)"},
         "geometry": {"type": "MultiPolygon", "coordinates": [
             _square(23.5, 49.0, 25.0, 50.3)]}},
        {"type": "Feature", "properties": {"state": "Австро-Венгрия"},
         "geometry": {"type": "Polygon", "coordinates": _square(18.5, 49.0, 23.4, 50.29)}},
        {"type": "Feature", "properties": {"state": "Финляндия"},
         "geometry": {"type": "Polygon", "coordinates": _square(19.5, 60.0, 20.5, 60.5)}},
    ]}
    (tmp_path / "provinces_1897.geojson").write_text(json.dumps(provinces), encoding="utf-8")
    (tmp_path / "state_borders.geojson").write_text(json.dumps(states), encoding="utf-8")
    return Frame.load(tmp_path)


def test_frame_follows_provinces_not_the_rectangle(tmp_path):
    frame = _boundaries(tmp_path)
    spec = BY_SLUG["parishes"]

    def rec(lat, lon):
        return spec.new_record(title="p", lat=lat, lon=lon, region="село")

    kalisz = rec(52.0, 17.7)     # западнее 18° — прямоугольник бы выбросил
    kielce = rec(50.8, 20.5)
    lviv = rec(49.8, 24.0)       # СССР, но не губерния 1897 года
    krakow = rec(50.06, 19.94)   # Галиция: внутри прямоугольника, вне рамки
    aland = rec(60.2, 19.7)      # Финляндия по CShapes
    coast = rec(60.5, 22.92)     # в воде у берега Нюландской губернии
    counts = frame.mark([kalisz, kielce, lviv, krakow, aland, coast])

    assert kalisz.region == "Калишская губерния" and kalisz.confidence == "ok"
    assert kielce.region == "Келецкая губерния"
    assert lviv.region is None and lviv.confidence == "ok"
    assert krakow.confidence == OUTSIDE, "соседний приход помечается, а не выбрасывается"
    assert krakow.region is None
    assert aland.confidence == "ok"
    assert coast.region == "Нюландская губерния" and coast.extra["frame"] == "по берегу"
    assert counts["вне рамки РИ/СССР"] == 1
    assert counts["в губерниях 1897 года"] == 3


def test_banded_ring_respects_holes():
    outer = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hole = [(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)]
    shape = Banded([outer, hole])
    assert shape.contains(2.0, 2.0)
    assert not shape.contains(5.0, 5.0)
    assert not shape.contains(11.0, 5.0)


def test_layer_is_registered_next_to_churches():
    spec = BY_SLUG["parishes"]
    assert spec.title == "Церковные приходы"
    assert spec.group == BY_SLUG["churches"].group == "faith"
    assert spec.license.startswith("CC0")
    # Живой счёт 24.10.2026, а не оценка: 7 884 записи, из них 3 294 в рамке.
    assert 7000 <= spec.expected_rows <= 9000, spec.expected_rows
