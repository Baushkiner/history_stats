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

from .geo import SpatialIndex, region_key
from .schema import SCOPE_REGION, SCOPE_STATE, ContextRecord

# Вес записи падает, когда она далеко или относится к другому времени.
DEFAULT_RADIUS_KM = 50.0
DEFAULT_YEAR_WINDOW = 25

# Слои, которые почти всегда стоит показать, даже если они широкие по времени
# (например, губернская принадлежность действует десятилетиями).
BROAD_LAYERS = {"admin_units", "settlements", "settlements_wd", "parishes"}

# Событие, действовавшее на всей территории государства, объясняет обстановку
# слабее, чем названная губерния: под него подходит любой факт этих лет.
STATE_SCOPE_WEIGHT = 0.65

# Сколько ближайших записей опрашивается, когда губерния факта не задана.
REGION_VOTE_DEPTH = 10


@dataclass
class Fact:
    """Генеалогический факт, вокруг которого собирается контекст."""

    lat: float
    lon: float
    year: Optional[int] = None
    year_to: Optional[int] = None
    label: str = ""
    region: Optional[str] = None    # губерния факта, если известна из документа

    @property
    def span(self) -> Optional[tuple[int, int]]:
        if self.year is None:
            return None
        return self.year, self.year_to if self.year_to is not None else self.year


@dataclass
class Match:
    """Запись контекста с объяснением, почему она подошла."""

    record: ContextRecord
    distance_km: Optional[float]     # None у территориальных событий: точки нет
    year_gap: int
    score: float
    reasons: tuple[str, ...]

    @property
    def territorial(self) -> bool:
        return self.distance_km is None

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


def _temporal(gap: Optional[int], window: int) -> tuple[float, str]:
    """Вес совпадения по времени и объяснение для пользователя."""
    if gap is None:
        # Недатированная запись не должна обгонять датированную и подходящую:
        # иначе «Осада Нижнего Новгорода» без года всплывает к факту 1861 года.
        return 0.12, "датировка неизвестна"
    if gap == 0:
        return 1.0, "совпадает по времени"
    weight = max(0.0, 1.0 - gap / window) if window > 0 else 0.0
    return weight, f"разница {gap} лет"


def _specificity(rec: ContextRecord, reasons: list[str]) -> float:
    """Широкие датировки менее информативны: «19 в.» подходит почти ко всему."""
    span_years = (rec.year_to - rec.year_from + 1) if rec.has_time else None
    specificity = 1.0
    if span_years and span_years > 25 and rec.layer not in BROAD_LAYERS:
        specificity = max(0.45, 25 / span_years)
        reasons.append(f"широкая датировка ({span_years} лет)")
    if rec.date_approx:
        specificity *= 0.9
    return specificity


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
    temporal, why = _temporal(gap, window)
    reasons.append(why)

    score = (0.45 * prox + 0.45 * temporal + 0.10) * _specificity(rec, reasons)
    return round(score, 4), tuple(reasons)


def _score_territorial(rec: ContextRecord, gap: Optional[int], window: int,
                       region: Optional[str]) -> tuple[float, tuple[str, ...]]:
    """Оценка события без точки: вместо расстояния — совпадение территории.

    Формула та же, что для точек, и в тех же долях: место, время и базовый
    вес. Меняется только смысл первого слагаемого.
    """
    reasons: list[str] = []

    if rec.scope == SCOPE_STATE:
        territory = STATE_SCOPE_WEIGHT
        reasons.append(f"действовало на всей территории: {rec.place_text or 'государство'}")
    else:
        territory = 1.0
        reasons.append(f"{region} — в числе затронутых" if region else "территория совпадает")

    temporal, why = _temporal(gap, window)
    reasons.append(why)

    score = (0.45 * territory + 0.45 * temporal + 0.10) * _specificity(rec, reasons)
    return round(score, 4), tuple(reasons)


class ContextEngine:
    """Индекс по всем слоям с поиском контекста вокруг факта."""

    # Записи с такой пометкой в выдачу не идут: это не события на местности.
    EXCLUDED_CONFIDENCE = frozenset({"not_an_event"})

    def __init__(self, records: Iterable[ContextRecord],
                 exclude_confidence: Optional[Iterable[str]] = None) -> None:
        skip = (frozenset(exclude_confidence) if exclude_confidence is not None
                else self.EXCLUDED_CONFIDENCE)
        kept = [r for r in records if r.confidence not in skip]
        self.records: list[ContextRecord] = [r for r in kept if r.has_point]
        # События без точки — голод, ревизия, воинская повинность — подбираются
        # не по расстоянию, а по губернии и годам.
        self.territorial: list[ContextRecord] = [
            r for r in kept if not r.has_point and r.is_territorial
        ]
        self.index = SpatialIndex(self.records)

    def __len__(self) -> int:
        return len(self.records) + len(self.territorial)

    def find(
        self,
        fact: Fact,
        radius_km: float = DEFAULT_RADIUS_KM,
        year_window: int = DEFAULT_YEAR_WINDOW,
        layers: Optional[Sequence[str]] = None,
        limit: int = 50,
        min_score: float = 0.0,
        per_layer_cap: Optional[int] = None,
        include_territorial: bool = True,
    ) -> list[Match]:
        """Находит контекст вокруг факта.

        `year_window` — на сколько лет за пределами факта запись ещё считается
        относящейся к делу. `per_layer_cap` не даёт одному плотному слою
        вытеснить все остальные из выдачи. `include_territorial` отключает
        события без точки — голод, ревизии, реформы.
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

        if include_territorial and self.territorial:
            region, _ = self.resolve_region(fact, radius_km)
            out.extend(self._territorial_matches(span, year_window, allowed, min_score, region))

        # Территориальные события идут после точек при равном весе: конкретная
        # запись рядом с местом полезнее, чем указ, действовавший везде.
        out.sort(key=lambda m: (-m.score, m.distance_km if m.distance_km is not None else 1e9))

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

    def resolve_region(self, fact: Fact,
                       radius_km: float = DEFAULT_RADIUS_KM) -> tuple[Optional[str], str]:
        """Губерния факта и то, откуда она взялась.

        Прямо заданная губерния всегда важнее вычисленной. Если её нет,
        спрашиваем ближайшие записи: у материалов Тенишева и литературных мест
        губерния проставлена, и по соседям она определяется надёжно.

        Опрашивается весь индекс, а не выдача: губерния — свойство местности,
        и от того, какие слои попросил пользователь, она не зависит.
        """
        if fact.region:
            return fact.region, "задана"

        nearby = [(rec, dist) for rec, dist in self.index.near(fact.lat, fact.lon, radius_km)
                  if rec.region]
        if not nearby:
            return None, "не определена"

        # Голосуют ближайшие записи; при равенстве голосов побеждает ближайшая,
        # потому что её счётчик доходит до максимума первым.
        votes: dict[str, int] = {}
        for rec, _ in nearby[:REGION_VOTE_DEPTH]:
            votes[rec.region] = votes.get(rec.region, 0) + 1
        return max(votes, key=lambda name: votes[name]), "по ближайшим записям"

    def _territorial_matches(self, span: Optional[tuple[int, int]], year_window: int,
                             allowed: Optional[set], min_score: float,
                             region: Optional[str]) -> list[Match]:
        """События без точки: отбор по территории и годам."""
        key = region_key(region)
        out: list[Match] = []
        for rec in self.territorial:
            if allowed is not None and rec.layer not in allowed:
                continue
            if rec.scope == SCOPE_REGION:
                # Губерния неизвестна — молча приписать факту губернское
                # событие нельзя: это было бы выдумкой, а не подбором.
                if key is None or key not in {region_key(r) for r in rec.regions}:
                    continue
            gap = _year_gap(rec, span)
            if gap is not None and gap > year_window:
                continue
            score, reasons = _score_territorial(rec, gap, year_window, region)
            if score < min_score:
                continue
            out.append(Match(rec, None, gap if gap is not None else -1, score, reasons))
        return out

    def summarize(self, matches: Sequence[Match]) -> dict:
        """Сводка по выдаче — для заголовка карточки факта."""
        by_layer: dict[str, int] = {}
        by_group: dict[str, int] = {}
        for m in matches:
            layer = m.record.layer_title or m.record.layer
            by_layer[layer] = by_layer.get(layer, 0) + 1
            if m.record.group:
                by_group[m.record.group] = by_group.get(m.record.group, 0) + 1
        return {
            "total": len(matches),
            "by_layer": dict(sorted(by_layer.items(), key=lambda kv: -kv[1])),
            "by_group": dict(sorted(by_group.items(), key=lambda kv: -kv[1])),
            "territorial": sum(1 for m in matches if m.territorial),
            "nearest_km": min((m.distance_km for m in matches if not m.territorial), default=None),
        }
