"""Общее у сборщиков, которые ходят в сеть: подпись, коды повтора, пауза.

Десять источников — десять клиентов, и у каждого своя логика запроса: у
Викиданных gzip и особый разбор 504, у каталога ristat.org — форма с
одноразовой ссылкой, у PastVu — ошибка в теле ответа вместо кода HTTP.
Сводить сами запросы в один клиент незачем. А вот подпись, список кодов, при
которых повтор осмыслен, и пауза между обращениями у всех одни и те же — и
жить им положено в одном месте: подпись, разъехавшаяся по версиям, врёт
источнику о том, кто к нему пришёл.

Сюда же переехало простое скачивание одним запросом (`fetch_bytes`): у
наборов, которые лежат файлом по постоянному адресу — heiDATA, RISTAT,
атласы засух NOAA, — оно было написано трижды слово в слово. Клиенты со
своей логикой повторов это не касается: у них она и есть суть.

И чтение файла кусками по заголовку Range (`RangeFile`): когда нужный набор
лежит внутри большого zip-архива на репозитории данных, из архива берётся
только оглавление и сам набор, а не весь архив.
"""

from __future__ import annotations

import io
import re
import time
import urllib.error
import urllib.request
from typing import Optional

from . import __version__

# Викимедиа требует содержательный User-Agent и блокирует запросы без него;
# остальным источникам подпись тоже не мешает. Только ASCII: заголовки HTTP
# кодируются latin-1, кириллица здесь падает.
USER_AGENT = (
    f"histctx/{__version__} (https://xn----ctbkalderxbemeylx6aq.xn--p1ai/; "
    "historical context harvesting for genealogy)"
)

# Коды, при которых повтор осмыслен: 429 — превышен лимит обращений,
# 5xx — сервису сейчас плохо. Остальное повтором не лечится, и повторять
# такое значит молча ждать вместо того, чтобы показать ошибку.
RETRY_CODES = (429, 500, 502, 503, 504)


def wait_for_pause(last_call: float, pause_sec: float) -> float:
    """Досыпает остаток паузы и возвращает новую отметку времени.

    Отметку держит вызывающий: у PastVu и ristat.org она своя на клиента, у
    Викиданных — одна на процесс, потому что адрес у всех слоёв общий.
    """
    left = pause_sec - (time.monotonic() - last_call)
    if left > 0:
        time.sleep(left)
    return time.monotonic()


def fetch_bytes(url: str, *, error: type[Exception], timeout: int = 300) -> bytes:
    """Скачивает файл одним запросом. Сбой пересказывается ошибкой источника.

    Повторов здесь нет намеренно: наборы лежат на репозиториях данных, которые
    отдают файл с первого раза. Там, где соединение рвётся (CShapes) или ответ
    собирается под запрос (ristat.org), у сборщика свой заход — и он там же,
    в самом сборщике.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise error(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise error(f"{url}: сеть недоступна ({exc.reason})") from exc


_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


class RangeFile(io.RawIOBase):
    """Файл на сервере, который читается кусками по заголовку Range.

    Нужен, чтобы достать один файл из zip-архива, не скачивая архив целиком:
    `zipfile.ZipFile(RangeFile(url))` сам найдёт оглавление в конце архива,
    а `open()` прочитает только нужный файл. Так собирается Cliopatria: на
    Zenodo набор в 46 МБ лежит внутри архива на 299 МБ, и с ноября 2026 года
    выдачу отдельного файла из архива (`…/container/<путь>`) Zenodo закрыл
    ответом 403, а частичное чтение самого архива (`…/content`) отдаёт.

    Читается вперёд кусками по `chunk` байт: оглавление архива помещается в
    первый же запрос к его хвосту, сам набор — в три-четыре, а не в тысячи
    мелких, которыми `zipfile` иначе спрашивал бы сервер. Каждый ответ
    проверяется: сервер, не умеющий Range, отдаёт весь файл с кодом 200, и
    его надо остановить сразу, а не принять за кусок.
    """

    def __init__(self, url: str, *, error: type[Exception], chunk: int = 16 << 20,
                 tail: int = 1 << 17, timeout: int = 300) -> None:
        super().__init__()
        self.url, self.error, self.chunk, self.timeout = url, error, chunk, timeout
        self.pos = 0
        self.requests = 0
        self.size: Optional[int] = None
        self._start, self._buf = 0, b""
        # Первый запрос — хвост файла: он же сообщает размер, а в хвосте у
        # zip-архива лежит оглавление.
        data = self._get(f"bytes=-{tail}")
        self._start, self._buf = self.size - len(data), data

    def _get(self, value: str) -> bytes:
        request = urllib.request.Request(
            self.url, headers={"User-Agent": USER_AGENT, "Range": value})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.requests += 1
                match = _CONTENT_RANGE.match(response.headers.get("Content-Range") or "")
                if response.status != 206 or not match:
                    raise self.error(f"{self.url}: сервер не отдаёт файл кусками "
                                     f"(HTTP {response.status}, Range не поддержан)")
                self.size = int(match.group(3))
                return response.read()
        except urllib.error.HTTPError as exc:
            raise self.error(f"{self.url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise self.error(f"{self.url}: сеть недоступна ({exc.reason})") from exc

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        elif whence == io.SEEK_END:
            self.pos = self.size + offset
        else:
            raise ValueError(f"whence={whence}")
        return self.pos

    def readinto(self, buffer) -> int:
        view = memoryview(buffer).cast("B")
        done = 0
        while done < len(view) and self.pos < self.size:
            if not self._start <= self.pos < self._start + len(self._buf):
                stop = min(self.size, self.pos + max(len(view) - done, self.chunk))
                self._buf, self._start = self._get(f"bytes={self.pos}-{stop - 1}"), self.pos
                if not self._buf:
                    break
            offset = self.pos - self._start
            piece = self._buf[offset:offset + len(view) - done]
            view[done:done + len(piece)] = piece
            done += len(piece)
            self.pos += len(piece)
        return done
