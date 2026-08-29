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
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

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
