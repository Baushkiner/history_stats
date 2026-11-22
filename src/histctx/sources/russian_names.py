"""Русская подпись места по указателю написаний GeoNames.

Карточки ESJF и профили Yahad – In Unum называют село по-нынешнему латиницей
(«Stara Rafalivka», «Andrushivka»). В указателе написаний
(`data/out/name_variants.json`, собирает `harvest_geonames.py`) у места есть
русское название и десятки написаний. Подпись берётся оттуда, только если
рядом с точкой есть место, среди написаний которого есть имя из источника;
иначе остаётся латиница: подставлять ближайший город под чужим именем нельзя.
Общий помощник слоёв `execution_sites` и `jewish_cemeteries`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..geo import haversine_km


class RussianNames:
    """Русское название места по указателю написаний GeoNames.

    Карточки ESJF называют село по-нынешнему латиницей («Stara Rafalivka»).
    В указателе (`data/out/name_variants.json`) у города есть русское название
    и десятки написаний; если в 5 км от кладбища есть место, среди написаний
    которого есть имя из карточки, подпись берётся оттуда. Нет — остаётся
    латиница: подставлять ближайший город под чужим именем нельзя.
    """

    def __init__(self, items: dict, radius_km: float = 5.0) -> None:
        self._dist = haversine_km
        self.radius_km = radius_km
        self.cells: dict[tuple[int, int], list[tuple[float, float, str, frozenset]]] = {}
        for item in items.values():
            lat, lon, title = item.get("lat"), item.get("lon"), item.get("title")
            if lat is None or lon is None or not title:
                continue
            names = frozenset(_norm(n) for n in (item.get("names") or []) + [title])
            self.cells.setdefault((int(lat * 10), int(lon * 10)), []).append(
                (lat, lon, title, names))

    @classmethod
    def load(cls, path: Path, radius_km: float = 5.0) -> "RussianNames":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload.get("items") or {}, radius_km=radius_km)

    def lookup(self, name: Optional[str], lat: float, lon: float) -> Optional[str]:
        if not name:
            return None
        wanted = {_norm(name)} | {_norm(p) for p in re.split(r"[(),/]", name) if p.strip()}
        wanted.discard("")
        best = None
        ci, cj = int(lat * 10), int(lon * 10)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for plat, plon, title, names in self.cells.get((ci + di, cj + dj), ()):
                    if not (wanted & names):
                        continue
                    d = self._dist(lat, lon, plat, plon)
                    if d <= self.radius_km and (best is None or d < best[0]):
                        best = (d, title)
        return best[1] if best else None


def _norm(name: str) -> str:
    return re.sub(r"[\s'’ʼ`-]+", "", (name or "").strip().lower())
