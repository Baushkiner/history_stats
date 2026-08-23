"""Разбор набора CShapes 2.0: границы государств по датам их изменения.

Сети в тестах нет. Формат набора двоичный (шейпфайл в zip-архиве), поэтому
образец собирается здесь же — как в `test_shapefile.py`, откуда и берутся
сборщики .shp и .dbf: дублировать спецификацию ESRI второй раз незачем.

Проверяется три вещи, на которых сбор держится: отбор периодов по рамке слоя,
отбор государств по охвату РИ/СССР и повтор оборванного скачивания — без
последнего сбор с `icr.ethz.ch` не доходит до конца.
"""

import sys
import urllib.error
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histctx.sources import cshapes  # noqa: E402
from histctx.sources.cshapes import (  # noqa: E402
    ARCHIVE_MEMBERS, STATE_BORDERS, CShapesError, boundary, check_fields,
    collection, download, overlaps, read_archive, rings, select, states,
    touches_region,
)

from test_shapefile import build_dbf, build_shp  # noqa: E402

# Квадраты по часовой стрелке — внешние границы. Первый лежит в охвате
# РИ/СССР (`geo.BBOX_RU`), второй — в Южной Америке, заведомо вне его.
IN_FRAME = [[30.0, 50.0], [30.0, 60.0], [40.0, 60.0], [40.0, 50.0], [30.0, 50.0]]
OUT_OF_FRAME = [[-50.0, -20.0], [-50.0, -10.0], [-40.0, -10.0], [-40.0, -20.0],
                [-50.0, -20.0]]

FIELDS = [
    ("cntry_name", "C", 32, 0), ("gwcode", "N", 6, 0),
    ("gwsdate", "C", 8, 0), ("gwedate", "C", 8, 0),
    ("gwsyear", "N", 6, 0), ("gweyear", "N", 6, 0),
    ("capname", "C", 24, 0), ("caplong", "N", 12, 5), ("caplat", "N", 12, 5),
]

# Четыре периода: два российских внутри рамки слоя, один заокеанский (в рамке
# по времени, но вне охвата) и один послевоенный с концом на краю данных.
ROWS = [
    ["Russia (Soviet Union)", 365, "18860101", "19180302", 1886, 1918,
     "Saint Petersburg (Petrograd)", 30.31413, 59.93863],
    ["Russia (Soviet Union)", 365, "19180311", "19181110", 1918, 1918,
     "Moscow", 37.61556, 55.75222],
    ["Brazil", 140, "18860101", "20191231", 1886, 2019, "Brasilia", -47.9, -15.78],
    ["Danzig", 999, "19450815", "20191231", 1945, 2019, "Danzig", 18.65, 54.35],
]

SHAPES = [[IN_FRAME], [IN_FRAME], [OUT_OF_FRAME], [IN_FRAME]]


def build_archive(rows=None, shapes=None, fields=None, members=ARCHIVE_MEMBERS) -> bytes:
    """Собирает zip с .shp и .dbf — ровно в том виде, в каком его отдаёт ETH."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(members[0], build_shp(shapes if shapes is not None else SHAPES))
        archive.writestr(members[1], build_dbf(fields or FIELDS,
                                               rows if rows is not None else ROWS))
    return buffer.getvalue()


def test_archive_is_read_into_features():
    feats = read_archive(build_archive())
    assert len(feats) == 4
    assert feats[0]["properties"]["cntry_name"] == "Russia (Soviet Union)"
    assert feats[0]["geometry"]["type"] == "Polygon"


def test_broken_archive_stops_the_harvest():
    """Переделают набор — сбор должен упасть с внятным сообщением, а не выдать пусто."""
    with pytest.raises(CShapesError, match="zip"):
        read_archive(b"not a zip at all")
    with pytest.raises(CShapesError, match="CShapes-2.0.shp"):
        read_archive(build_archive(members=("other.shp", "other.dbf")))
    with pytest.raises(CShapesError, match="gwsdate"):
        check_fields([{"properties": {"cntry_name": "Russia", "gwcode": 365}}])
    with pytest.raises(CShapesError, match="ни одного полигона"):
        check_fields([])


def test_empty_cell_in_the_first_row_is_not_a_redesigned_dataset():
    """Пустое значение до свойств не доезжает — поля ищутся по всем записям."""
    check_fields([
        {"properties": {"cntry_name": "Danzig", "gwcode": 999,
                        "gwsdate": "19450815", "gwsyear": 1945, "gweyear": 2019}},
        {"properties": {"cntry_name": "Russia", "gwcode": 365,
                        "gwsdate": "18860101", "gwedate": "19180302",
                        "gwsyear": 1886, "gweyear": 1918}},
    ])


def test_period_is_matched_against_the_layer_window():
    assert overlaps({"gwsyear": 1886, "gweyear": 1918})
    assert overlaps({"gwsyear": 1945, "gweyear": 2019})      # начался в рамке
    assert not overlaps({"gwsyear": 1991, "gweyear": 2019})  # весь позже рамки
    assert not overlaps({"gwsyear": 1886, "gweyear": 2019}, 1700, 1800)
    # Год не число — период не разбирается и в отбор не идёт.
    assert not overlaps({"gwsyear": None, "gweyear": 1918})


def test_state_outside_the_frame_is_dropped():
    """Бразилия во времена империи существовала — к её карте отношения не имеет."""
    picked = select(read_archive(build_archive()))
    assert states(picked) == ["Данциг, вольный город", "Россия (Советский Союз)"]
    assert len(picked) == 3
    assert "Бразилия" not in states(picked)


def test_whole_world_is_kept_on_demand():
    picked = select(read_archive(build_archive()), region_only=False)
    assert len(picked) == 4


def test_polygon_is_not_clipped_by_the_frame():
    """Обрезанная граница — уже не граница государства, а пересечение с рамкой."""
    picked = select(read_archive(build_archive()))
    assert picked[0]["geometry"]["coordinates"][0] == IN_FRAME


def test_region_check_looks_at_vertices_not_at_the_bounding_box():
    """У России описанный прямоугольник растянут от −180° до 180° — по нему
    в отбор попал бы весь мир, поэтому проверяются сами вершины."""
    across_meridian = {"type": "MultiPolygon", "coordinates": [[OUT_OF_FRAME],
                                                              [IN_FRAME]]}
    assert touches_region(across_meridian)
    assert len(rings(across_meridian)) == 2
    assert not touches_region({"type": "Polygon", "coordinates": [OUT_OF_FRAME]})
    assert not touches_region({"type": "LineString", "coordinates": []})
    assert not touches_region(None)


def test_dates_are_written_the_way_a_reader_expects():
    props = boundary({"geometry": None, "properties": dict(zip(
        [f[0] for f in FIELDS], ROWS[0]))})["properties"]
    assert props["date_from"] == "1886-01-01"
    assert props["date_to"] == "1918-03-02"
    assert props["state"] == "Россия (Советский Союз)"
    assert props["state_en"] == "Russia (Soviet Union)"
    assert props["capital"] == "Saint Petersburg (Petrograd)"
    assert "open_end" not in props


def test_end_of_data_is_not_a_border_change():
    """31.12.2019 в конце периода — край набора, а не очередное изменение границы."""
    props = boundary({"geometry": None, "properties": dict(zip(
        [f[0] for f in FIELDS], ROWS[3]))})["properties"]
    assert props["open_end"] is True
    assert props["date_to"] == "2019-12-31"


def test_unknown_state_keeps_its_english_name():
    """Лучше нерасшифрованное название, чем выдуманный перевод."""
    props = boundary({"geometry": None, "properties": {
        "cntry_name": "Tannu Tuva", "gwsyear": 1921, "gweyear": 1944}})["properties"]
    assert props["state"] == "Tannu Tuva"
    # Дат у этого периода нет, и пустых полей в файл не идёт.
    assert "date_from" not in props and "date_to" not in props


def test_collection_carries_the_licence_and_the_citation():
    """Лицензия набора требует указания авторства — оно едет в самом файле."""
    payload = collection(select(read_archive(build_archive())))
    assert payload["type"] == "FeatureCollection"
    assert "CC BY-NC-SA 4.0" in payload["license"]
    assert "Schvitz" in payload["citation"]
    assert payload["period"] == "1886–1960"
    assert payload["url"].startswith("https://icr.ethz.ch/")


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload


def test_download_repeats_a_broken_connection(monkeypatch):
    """Ради этого повтора всё и затевалось: ETH рвёт соединение чаще, чем отдаёт."""
    calls, waits = [], []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise urllib.error.URLError(
                ConnectionResetError(104, "Connection reset by peer"))
        return _Response(b"archive bytes")

    monkeypatch.setattr(cshapes.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cshapes.time, "sleep", waits.append)
    assert download(attempts=5) == b"archive bytes"
    assert len(calls) == 3
    # Пауза растёт, и после удачной попытки её не ждут.
    assert waits == [2.0, 4.0]


def test_download_gives_up_with_a_readable_message(monkeypatch):
    def always_reset(request, timeout=None):
        raise urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))

    monkeypatch.setattr(cshapes.urllib.request, "urlopen", always_reset)
    with pytest.raises(CShapesError, match="попыток сделано 2"):
        download(attempts=2, pause=0)


def test_http_error_is_not_repeated(monkeypatch):
    """404 от повтора не исправится — повторять стоит только обрыв связи."""
    calls = []

    def not_found(request, timeout=None):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(cshapes.urllib.request, "urlopen", not_found)
    with pytest.raises(CShapesError, match="404"):
        download(attempts=5, pause=0)
    assert len(calls) == 1


def test_broken_download_does_not_poison_the_cache(tmp_path, monkeypatch):
    """Оборванное скачивание не должно оставлять после себя нечитаемый кэш:
    иначе совет «запустите ещё раз» перестал бы работать навсегда."""
    monkeypatch.setattr(cshapes, "download", lambda **kw: b"truncated archive")
    with pytest.raises(CShapesError, match="zip"):
        cshapes.load(tmp_path)
    assert not (tmp_path / "CShapes-2.0.zip").exists()

    monkeypatch.setattr(cshapes, "download", lambda **kw: build_archive())
    assert len(cshapes.load(tmp_path)) == 4
    assert (tmp_path / "CShapes-2.0.zip").exists()


def test_damaged_cache_names_the_file_to_delete(tmp_path):
    (tmp_path / "CShapes-2.0.zip").write_bytes(b"not a zip")
    with pytest.raises(CShapesError, match="Удалите"):
        cshapes.load(tmp_path)


def test_layer_is_described_in_registry():
    from histctx.registry import BY_SLUG

    assert STATE_BORDERS.slug in BY_SLUG
    assert BY_SLUG[STATE_BORDERS.slug].status == "harvested"
