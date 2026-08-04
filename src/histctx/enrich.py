"""Подбор исторического контекста вокруг генеалогического факта.

Вход — факт из родословной: место (координаты) и дата. Выход — записи из
всех слоёв, ранжированные по тому, насколько они действительно объясняют
обстановку вокруг этого факта.

Ранжирование намеренно простое и объяснимое: пользователь должен понимать,
почему запись показана. Непрозрачная модель здесь хуже, чем формула из трёх
слагаемых, которую можно описать одной строкой в интерфейсе.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .geo import SpatialIndex, haversine_km
from .schema import ContextRecord

# Вес записи падает, когда она далеко или относится к другому времени.
DEFAULT_RADIUS_KM = 50.0
DEFAULT_YEAR_WINDOW = 25

# Слои, которые почти всегда стоит показать, даже если они широкие по времени
# (например, губернская принадлежность действует десятилетиями).
BROAD_LAYERS = {"admin_units", "settlements", "parishes"}


@dataclass
class Fact:
    """Генеалогический факт, вокруг которого собирается контекст."""

    lat: float
    lon: float
    year: Optional[int] = None
    year_to: Optional[int] = None
    label: str = ""

    @property
    def span(self) -> Optional[tuple[int, int]]:
        if self.year is None:
            return None
        return self.year, self.year_to if self.year_to is not None else self.year


@dataclass
class Match:
    """Запись контекста с объяснением, почему она подошла."""

    record: ContextRecord
    distance_km: float
    year_gap: int
    score: float
    reasons: tuple[str, ...]

    def explain(self) -> str:
        return "; ".join(self.reasons)


def _year_gap(rec: ContextRecord, span: Optional[tuple[int, int]]) -> Optional[int]:
    """На сколько лет запись разминулась с фактом. 0 — пересекается."""
    if span is None or not rec.has_time:
        return None
    fa, fb = span
    if rec.year_from <= fb and fa <= rec.year_to:
        return 0
    # Запись целиком позже факта — считаем от конца факта до её начала,
    # целиком раньше — от её конца до начала факта. Разрыв всегда неотрицателен.
    if rec.year_from > fb:
        return rec.year_from - fb
    return fa - rec.year_to


def _score(distance_km: float, radius_km: float, gap: Optional[int],
           window: int, rec: ContextRecord) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []

    # Близость: 1.0 в точке факта, 0.0 на границе радиуса.
    prox = max(0.0, 1.0 - distance_km / radius_km) if radius_km > 0 else 0.0
    if distance_km < 1:
        reasons.append("в том же населённом пункте")
    elif distance_km < 15:
        reasons.append(f"в {distance_km:.0f} км")
    else:
        reasons.append(f"в {distance_km:.0f} км от места")

    # Время: 1.0 при пересечении, дальше линейный спад до края окна.
    if gap is None:
        # Недатированная запись не должна обгонять датированную и подходящую:
        # иначе «Осада Нижнего Новгорода» без года всплывает к факту 1861 года.
        temporal = 0.12
        reasons.append("датировка неизвестна")
    elif gap == 0:
        temporal = 1.0
        reasons.append("совпадает по времени")
    else:
        temporal = max(0.0, 1.0 - gap / window) if window > 0 else 0.0
        reasons.append(f"разница {gap} лет")

    # Широкие датировки менее информативны: «19 в.» подходит почти ко всему.
    span_years = (rec.year_to - rec.year_from + 1) if rec.has_time else None
    specificity = 1.0
    if span_years and span_years > 25 and rec.layer not in BROAD_LAYERS:
        specificity = max(0.45, 25 / span_years)
        reasons.append(f"широкая датировка ({span_years} лет)")
    if rec.date_approx:
        specificity *= 0.9

    score = (0.45 * prox + 0.45 * temporal + 0.10) * specificity
    return round(score, 4), tuple(reasons)


class ContextEngine:
    """Индекс по всем слоям с поиском контекста вокруг факта."""

    # Записи с такой пометкой в выдачу не идут: это не события на местности.
    EXCLUDED_CONFIDENCE = frozenset({"not_an_event"})

    def __init__(self, records: Iterable[ContextRecord],
                 exclude_confidence: Optional[Iterable[str]] = None) -> None:
        skip = frozenset(exclude_confidence) if exclude_confidence is not None else self.EXCLUDED_CONFIDENCE
        self.records: list[ContextRecord] = [
            r for r in records if r.has_point and r.confidence not in skip
        ]
        self.index = SpatialIndex(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def find(
        self,
        fact: Fact,
        radius_km: float = DEFAULT_RADIUS_KM,
        year_window: int = DEFAULT_YEAR_WINDOW,
        layers: Optional[Sequence[str]] = None,
        limit: int = 50,
        min_score: float = 0.0,
        per_layer_cap: Optional[int] = None,
    ) -> list[Match]:
        """Находит контекст вокруг факта.

        `year_window` — на сколько лет за пределами факта запись ещё считается
        относящейся к делу. `per_layer_cap` не даёт одному плотному слою
        вытеснить все остальные из выдачи.
        """
        span = fact.span
        allowed = set(layers) if layers else None
        out: list[Match] = []

        for rec, dist in self.index.near(fact.lat, fact.lon, radius_km):
            if allowed is not None and rec.layer not in allowed:
                continue
            gap = _year_gap(rec, span)
            if gap is not None and gap > year_window:
                continue
            score, reasons = _score(dist, radius_km, gap, year_window, rec)
            if score < min_score:
                continue
            out.append(Match(rec, round(dist, 2), gap if gap is not None else -1, score, reasons))

        out.sort(key=lambda m: (-m.score, m.distance_km))

        if per_layer_cap:
            kept: list[Match] = []
            seen: dict[str, int] = {}
            for m in out:
                n = seen.get(m.record.layer, 0)
                if n >= per_layer_cap:
                    continue
                seen[m.record.layer] = n + 1
                kept.append(m)
            out = kept

        return out[:limit]

    def summarize(self, matches: Sequence[Match]) -> dict:
        """Сводка по выдаче — для заголовка карточки факта."""
        by_layer: dict[str, int] = {}
        by_group: dict[str, int] = {}
        for m in matches:
            by_layer[m.record.layer_title or m.record.layer] = by_layer.get(m.record.layer_title or m.record.layer, 0) + 1
            if m.record.group:
                by_group[m.record.group] = by_group.get(m.record.group, 0) + 1
        return {
            "total": len(matches),
            "by_layer": dict(sorted(by_layer.items(), key=lambda kv: -kv[1])),
            "by_group": dict(sorted(by_group.items(), key=lambda kv: -kv[1])),
            "nearest_km": min((m.distance_km for m in matches), default=None),
        }
