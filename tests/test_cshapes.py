"""Разбор набора CShapes 2.0: границы государств по датам их изменения.

Сети в тестах нет. Формат набора двоичный (шейпфайл в zip-архиве), поэтому
образец собирается здесь же — как в `test_shapefile.py`, откуда и берутся
сборщики .shp и .dbf: дублировать спецификацию ESRI второй раз незачем.

Проверяется то, на чём сбор держится: отбор периодов по рамке слоя — весь
мир и прежняя выборка по охвату РИ/СССР, — статус и владелец из R-пакета
набора, сшитые с периодами шейпфайла, и повтор оборванного скачивания — без
последнего сбор с `icr.ethz.ch` не доходит до конца.
"""

import hashlib
import io
import json
import lzma
import tarfile
import urllib.error
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path

import pytest

from histctx.sources import cshapes
from histctx.sources.cshapes import (
    ARCHIVE_MEMBERS, NAMES_RU, PACKAGE_MEMBER, STATE_BORDERS, CShapesError,
    boundary, check_fields, check_package, collection, download, overlaps,
    owner_index, owner_name, read_archive, read_attributes, rings, select, states,
    touches_region, unmatched, untranslated,
)

from test_shapefile import build_dbf, build_shp

ROOT = Path(__file__).resolve().parents[1]

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


def test_whole_world_is_the_layer():
    """С ноября 2026 года слой — весь мир: уезжали и в Бразилию."""
    picked = select(read_archive(build_archive()))
    assert len(picked) == 4
    assert "Бразилия" in states(picked)


def test_region_selection_keeps_the_former_layer():
    """Прежний отбор по охвату РИ/СССР остался — им пользуется сито рамки."""
    picked = select(read_archive(build_archive()), region_only=True)
    assert states(picked) == ["Данциг, вольный город", "Россия (Советский Союз)"]
    assert len(picked) == 3


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
    assert untranslated([{"properties": props}]) == ["Tannu Tuva"]
    # Дат у этого периода нет, и пустых полей в файл не идёт.
    assert "date_from" not in props and "date_to" not in props
    # Статуса без R-пакета нет — и в файле его тоже нет, а не «независимое».
    assert "status" not in props and "owner" not in props


def test_collection_carries_the_licence_and_the_citation():
    """Лицензия набора требует указания авторства — оно едет в самом файле."""
    payload = collection(select(read_archive(build_archive())))
    assert payload["type"] == "FeatureCollection"
    assert "CC BY-NC-SA 4.0" in payload["license"]
    assert "Schvitz" in payload["citation"]
    assert payload["period"] == "1886–1960"
    assert payload["coverage"] == "весь мир"
    assert payload["url"].startswith("https://icr.ethz.ch/")
    assert payload["status_source"].endswith("cshapes_2.0.tar.gz")


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


# --- статус и владелец из R-пакета ------------------------------------------

def package(props: list[dict]) -> bytes:
    """R-пакет в том виде, в каком его отдаёт ETH: tar.gz с TopoJSON в xz."""
    topo = {"type": "Topology", "arcs": [], "objects": {"cshapes_2_gw": {
        "type": "GeometryCollection",
        "geometries": [{"type": None, "properties": p} for p in props]}}}
    member = lzma.compress(json.dumps(topo).encode())
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(PACKAGE_MEMBER)
        info.size = len(member)
        archive.addfile(info, io.BytesIO(member))
    return buffer.getvalue()


# Статусы к четырём периодам `ROWS`: Россия независима, Бразилия тоже,
# Данциг — под мандатом Лиги Наций (владелец 0) с непроведённой границей.
PACKAGE_PROPS = [
    {"gwcode": 365, "country_name": "Russia (Soviet Union)", "start": "1886-01-01",
     "end": "1918-03-02", "status": "independent", "owner": "365", "b_def": 1},
    {"gwcode": 365, "country_name": "Russia (Soviet Union)", "start": "1918-03-11",
     "end": "1918-11-10", "status": "independent", "owner": "365", "b_def": 1},
    {"gwcode": 140, "country_name": "Brazil", "start": "1886-01-01",
     "end": "2019-12-31", "status": "independent", "owner": "140", "b_def": 1},
    {"gwcode": 999, "country_name": "Danzig", "start": "1945-08-15",
     "end": "2019-12-31", "status": "mandate", "owner": "0", "b_def": 0},
]


def test_status_and_owner_are_read_from_the_package():
    attrs = read_attributes(package(PACKAGE_PROPS))
    assert attrs[(999, "19450815", "20191231")] == {"status": "mandate", "owner": 0,
                                                   "b_def": 0}
    assert attrs[(365, "18860101", "19180302")]["status"] == "independent"
    assert unmatched(read_archive(build_archive()), attrs) == []


def test_period_without_status_is_reported():
    """Наборы разошлись — сборщик должен это увидеть, а не промолчать."""
    attrs = read_attributes(package(PACKAGE_PROPS[:3]))
    assert unmatched(read_archive(build_archive()), attrs) == [(999, "19450815", "20191231")]


def test_broken_package_stops_the_harvest():
    with pytest.raises(CShapesError, match="не разбирается"):
        read_attributes(b"not a tarball")
    empty = BytesIO()
    with tarfile.open(fileobj=empty, mode="w:gz"):
        pass
    with pytest.raises(CShapesError, match="нет cshapes/inst"):
        read_attributes(empty.getvalue())
    with pytest.raises(CShapesError, match="status и owner"):
        read_attributes(package([{"gwcode": 365, "start": "1886-01-01",
                                  "end": "1918-03-02"}]))


def test_package_of_another_version_is_refused():
    with pytest.raises(CShapesError, match="SHA-256"):
        check_package(package(PACKAGE_PROPS))


def test_package_is_cached_only_after_the_check(tmp_path, monkeypatch):
    data = package(PACKAGE_PROPS)
    monkeypatch.setattr(cshapes, "download", lambda url, **kw: data)
    with pytest.raises(CShapesError, match="SHA-256"):
        cshapes.load_attributes(tmp_path)
    assert not (tmp_path / "cshapes_2.0.tar.gz").exists()

    monkeypatch.setattr(cshapes, "PACKAGE_SIZE", len(data))
    monkeypatch.setattr(cshapes, "PACKAGE_SHA256", hashlib.sha256(data).hexdigest())
    assert len(cshapes.load_attributes(tmp_path)) == 4
    assert (tmp_path / "cshapes_2.0.tar.gz").exists()
    # Второй запуск берёт пакет из кэша и в сеть не ходит.
    monkeypatch.setattr(cshapes, "download", None)
    assert len(cshapes.load_attributes(tmp_path)) == 4


def test_dependency_gets_its_status_and_owner():
    """Колония набора названа преемником — без владельца подпись врала бы."""
    attrs = read_attributes(package(PACKAGE_PROPS))
    picked = {f["properties"]["state_en"]: f["properties"]
              for f in select(read_archive(build_archive()), attrs=attrs)}
    danzig = picked["Danzig"]
    assert danzig["status"] == "подмандатная территория"
    assert danzig["status_en"] == "mandate"
    assert danzig["owner"] == "Лига Наций" and danzig["owner_gwcode"] == 0
    assert danzig["border_defined"] is False
    # У независимого государства владелец — оно само, и в файл это не пишется.
    brazil = picked["Brazil"]
    assert brazil["status"] == "независимое государство"
    assert "owner" not in brazil and brazil["border_defined"] is True


def test_owner_is_named_as_it_was_on_the_date():
    """Название у номера меняется: владелец ищется на дату начала колонии."""
    feats = [{"properties": {"cntry_name": "Austria-Hungary", "gwcode": 300,
                             "gwsdate": "18860101", "gwedate": "19181111"}},
             {"properties": {"cntry_name": "Austria", "gwcode": 300,
                             "gwsdate": "19181112", "gwedate": "19380312"}}]
    index = owner_index(feats)
    assert owner_name(300, "19000101", index) == "Австро-Венгрия"
    assert owner_name(300, "19300101", index) == "Австрия"
    assert owner_name(300, "18000101", index) == "Австро-Венгрия"   # вне всех дат
    assert owner_name(0, "19200101", index) == "Лига Наций"
    assert owner_name(777, "19200101", index) is None
    assert owner_name(None, "19200101", index) is None


def test_dictionary_translates_and_never_merges_two_states():
    for en, ru in NAMES_RU.items():
        assert ru and ru != en, en
    clashes = [ru for ru, n in Counter(NAMES_RU.values()).items() if n > 1]
    assert clashes == []
    # Германская колония и Камерун после 1919 года — разные подписи.
    assert NAMES_RU["Kamerun"] != NAMES_RU["Cameroon"]
