"""Чтение файла кусками по Range (`histctx.net.RangeFile`).

Сети в тестах нет: сервер подменяется функцией, которая отдаёт куски
заранее собранного zip-архива так, как отдаёт их Zenodo, — с кодом 206 и
заголовком Content-Range. Проверяется то, ради чего класс написан: из
большого архива читаются оглавление и один файл, а не архив целиком, и
сервер, не умеющий Range, останавливает чтение сразу.
"""

import re
import urllib.error
import zipfile
from io import BytesIO

import pytest

from histctx import net
from histctx.net import RangeFile


class Boom(RuntimeError):
    pass


class _Response:
    def __init__(self, status, body, headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def range_server(payload: bytes, calls: list):
    """Отдаёт `payload` кусками по заголовку Range, записывая каждый запрос."""
    def urlopen(request, timeout=None):
        value = request.get_header("Range")
        calls.append(value)
        start, stop = re.match(r"bytes=(\d*)-(\d*)", value).groups()
        if not start:                       # bytes=-N: хвост файла
            start, stop = max(0, len(payload) - int(stop)), len(payload) - 1
        start, stop = int(start), min(int(stop), len(payload) - 1)
        return _Response(206, payload[start:stop + 1],
                         {"Content-Range": f"bytes {start}-{stop}/{len(payload)}"})
    return urlopen


def big_archive() -> tuple[bytes, bytes]:
    """Архив, в котором нужный файл — малая часть: остальное — «сканы»."""
    wanted = b"geojson " * 5000
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for n in range(20):
            archive.writestr(f"scans/map_{n:02d}.tif", bytes([n]) * 50_000)
        archive.writestr("data/wanted.geojson.zip", wanted)
    return buffer.getvalue(), wanted


def test_one_member_is_read_without_the_whole_archive(monkeypatch):
    payload, wanted = big_archive()
    calls = []
    monkeypatch.setattr(net.urllib.request, "urlopen", range_server(payload, calls))
    rf = RangeFile("https://example.org/archive.zip", error=Boom,
                   chunk=64 * 1024, tail=16 * 1024)
    with zipfile.ZipFile(rf) as archive:
        info = archive.getinfo("data/wanted.geojson.zip")
        assert info.file_size == len(wanted)
        with archive.open(info) as fh:
            assert fh.read() == wanted
    # Хвост с оглавлением и один кусок с самим файлом — а не весь мегабайт.
    assert rf.size == len(payload)
    assert rf.requests == len(calls) <= 3
    assert calls[0] == "bytes=-16384"


def test_reads_across_chunk_borders_are_whole(monkeypatch):
    payload = bytes(range(256)) * 100
    monkeypatch.setattr(net.urllib.request, "urlopen", range_server(payload, []))
    rf = RangeFile("https://example.org/f", error=Boom, chunk=1000, tail=500)
    rf.seek(900)
    assert rf.read(2500) == payload[900:3400]
    rf.seek(-10, 2)
    assert rf.read(100) == payload[-10:]
    assert rf.read(5) == b""


def test_server_without_range_is_stopped(monkeypatch):
    """Сервер, отдавший весь файл с кодом 200, — не кусок, а ошибка."""
    monkeypatch.setattr(net.urllib.request, "urlopen",
                        lambda request, timeout=None: _Response(200, b"whole file"))
    with pytest.raises(Boom, match="Range не поддержан"):
        RangeFile("https://example.org/f", error=Boom)


def test_http_error_is_told_in_the_source_terms(monkeypatch):
    def forbidden(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(net.urllib.request, "urlopen", forbidden)
    with pytest.raises(Boom, match="HTTP 403"):
        RangeFile("https://example.org/f", error=Boom)
