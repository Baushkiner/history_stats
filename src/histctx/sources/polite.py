"""Вежливый обход сайта без выгрузки: пауза, отступ на 429/5xx, кэш с продолжением.

Три источника, подключённые 24.11.2026 с согласия владельцев (JewishGen
Communities, Historic Synagogues of Europe, Kartenmeister), отдают данные
только страницами — формой поиска или карточкой на объект. Обход у всех
устроен одинаково: одно соединение, пауза между запросами не меньше секунды
(у JewishGen — две, по `Crawl-delay` его `robots.txt`), при 429 и 5xx пауза
растёт и запрос повторяется, сброс соединения — повтор с ожиданием. Каждый
ответ ложится в кэш файлом (сжатым gzip — карточек десятки тысяч), так что
оборванный обход продолжается тем же вызовом.

Проверок на бота и капч клиент не решает: такая страница — ошибка
`ProtectionError`, обход останавливается.
"""

from __future__ import annotations

import gzip
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..net import RETRY_CODES, USER_AGENT, wait_for_pause


class HarvestError(RuntimeError):
    """Страница не скачалась или пришла не в том виде."""


class ProtectionError(HarvestError):
    """Вместо данных — проверка на бота или вход по учётной записи."""


@dataclass
class PoliteClient:
    pause: float = 1.0
    timeout: int = 90
    retries: int = 6
    encoding: str = "utf-8"
    ssl_context: Optional[ssl.SSLContext] = None
    error: type = HarvestError
    pause_max: float = 30.0
    requests: int = field(default=0, repr=False)
    backoffs: int = field(default=0, repr=False)
    _last: float = field(default=0.0, repr=False)

    def fetch(self, url: str, data: Optional[dict] = None) -> bytes:
        body = urllib.parse.urlencode(data).encode("ascii") if data is not None else None
        headers = {"User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        for attempt in range(self.retries + 1):
            self._last = wait_for_pause(self._last, self.pause)
            self.requests += 1
            request = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout,
                                            context=self.ssl_context) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_CODES and attempt < self.retries:
                    self.backoffs += 1
                    self.pause = min(self.pause_max, self.pause * 1.5)
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    wait = float(retry_after) if (retry_after or "").isdigit() else 10.0 * (attempt + 1)
                    time.sleep(min(wait, 300.0))
                    continue
                raise self.error(f"{url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    self.backoffs += 1
                    time.sleep(5.0 * (attempt + 1))
                    continue
                reason = getattr(exc, "reason", exc)
                raise self.error(f"{url}: сеть недоступна ({reason})") from exc
        raise self.error(f"{url}: повторы исчерпаны")

    def text(self, url: str, data: Optional[dict] = None) -> str:
        return self.fetch(url, data).decode(self.encoding, errors="replace")


def cache_read(path: Path, encoding: str = "utf-8") -> Optional[str]:
    """Страница из кэша (`.html.gz`) или None, если её там нет."""
    if not path.exists():
        return None
    return gzip.decompress(path.read_bytes()).decode(encoding, errors="replace")


def cache_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(gzip.compress(raw, compresslevel=6))
    tmp.replace(path)
