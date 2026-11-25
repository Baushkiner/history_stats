"""Общее у трёх фотоархивов, собранных с согласия владельцев (24.11.2026).

«Военный альбом» (waralbum.ru), «История России в фотографиях»
(russiainphoto.ru) и Ajapaik (ajapaik.ee) устроены по-разному — страницы
WordPress, JS-приложение с картой на геохешах, API Django, — но сбор у них
одинаковый: одно соединение, пауза не меньше секунды после каждого ответа,
отступ на 429 и 5xx, кэш на диске и продолжение с места. Это и лежит здесь,
вместе с общим правилом датировки снимка и общей формой записи слоя:
схема та же, что у слоя PastVu (`photos_pastvu`), — точка, год, подпись,
автор, ссылка на страницу снимка.

Снимки в репозиторий не кладутся. Согласие владельцев позволяет дать прямую
ссылку на изображение (`image_url`), но файлы остаются на серверах архивов.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from typing import Optional

from ..net import RETRY_CODES, USER_AGENT
from ..periods import parse_period

# Горизонт проекта, как у PastVu: снимки позже 1960 года в слой не идут.
YEAR_MAX = 1960

CONSENT = "собрано с согласия владельца, полученного владельцем проекта (сообщено 24.11.2026)"


class FetchError(RuntimeError):
    pass


class Fetcher:
    """Одно соединение на сайт: пауза после каждого ответа, отступ на сбой.

    Пауза отсчитывается от конца ответа, а не от начала запроса: медленный
    ответ сервера — признак нагрузки, и следующий запрос не должен прийти
    к нему вплотную.
    """

    def __init__(self, *, pause: float = 1.0, attempts: int = 6, backoff: float = 10.0,
                 timeout: int = 120, headers: Optional[dict] = None) -> None:
        self.pause, self.attempts, self.backoff, self.timeout = pause, attempts, backoff, timeout
        self.headers = {"User-Agent": USER_AGENT, **(headers or {})}
        self.requests = 0
        self._last = 0.0
        self.opener = urllib.request.build_opener()

    def _wait(self) -> None:
        left = self.pause - (time.monotonic() - self._last)
        if left > 0:
            time.sleep(left)

    def get(self, url: str, *, data: Optional[bytes] = None, headers: Optional[dict] = None,
            ok404: bool = False) -> Optional[bytes]:
        """Тело ответа. `ok404` — вернуть None на 404 вместо ошибки."""
        last_error = ""
        for attempt in range(self.attempts):
            self._wait()
            request = urllib.request.Request(url, data=data, headers={**self.headers, **(headers or {})})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = response.read()
                self.requests += 1
                self._last = time.monotonic()
                return body
            except urllib.error.HTTPError as exc:
                self._last = time.monotonic()
                if exc.code == 404 and ok404:
                    return None
                if exc.code not in RETRY_CODES:
                    raise FetchError(f"{url}: HTTP {exc.code}") from exc
                last_error = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                self._last = time.monotonic()
                last_error = f"сеть: {getattr(exc, 'reason', exc)}"
            time.sleep(self.backoff * (attempt + 1))
        raise FetchError(f"{url}: {last_error} после {self.attempts} попыток")


def photo_years(text: Optional[str], *, year_max: int = YEAR_MAX):
    """Датировка снимка из подписи архива: (год от, год до, точность, приблизительно, исходник).

    Разбор — общий `histctx.periods.parse_period`: «1943», «июль 1941»,
    «1870 - 1887», «1940-е». Снимок, начатый позже `year_max`, — вне
    горизонта (None); конец, заходящий за горизонт, обрезается, а исходная
    запись остаётся в `period_raw`.
    """
    raw = (text or "").strip()
    day = _day(raw)
    if day is not None:
        return (day, day, "day", False, raw) if day <= year_max else None
    period = parse_period(text)
    if period.year_from is None:
        return None
    lo, hi = period.year_from, period.year_to if period.year_to is not None else period.year_from
    if lo > hi:
        lo, hi = hi, lo
    if lo > year_max:
        return None
    hi = min(hi, year_max)
    return lo, hi, period.precision, bool(period.approx), period.raw.strip()


_MONTHS = {"января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
           "сентября", "октября", "ноября", "декабря"}
_RE_DAY_NUM = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*(?:г\.?|года)?\s*$")
_RE_DAY_WORD = re.compile(r"^\s*(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s*(?:г\.?|года)?\s*$", re.I)


def _day(text: str) -> Optional[int]:
    """Год, если датировка — один названный день: «22 июня 1941», «04-05-1925»."""
    m = _RE_DAY_NUM.match(text)
    if m:
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        return y if 1 <= d <= 31 and 1 <= mo <= 12 else None
    m = _RE_DAY_WORD.match(text)
    if m and 1 <= int(m[1]) <= 31:
        if m[2].lower() in _MONTHS:
            return int(m[3])
    return None
