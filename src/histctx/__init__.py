"""histctx — сбор и нормализация исторического контекста для генеалогии.

Задача пакета: превратить разрозненные исторические данные в один массив
записей вида «что произошло, где и когда», чтобы к любому факту из
родословной можно было подобрать обстановку вокруг него.
"""

from .schema import SCHEMA_VERSION, ContextRecord, LayerSpec, GROUPS
from .periods import Period, parse_period, parse_year
from .enrich import ContextEngine, Fact, Match
from .geo import haversine_km, SpatialIndex

__version__ = "0.1.0"

__all__ = [
    "SCHEMA_VERSION", "__version__",
    "ContextRecord", "LayerSpec", "GROUPS",
    "Period", "parse_period", "parse_year",
    "ContextEngine", "Fact", "Match",
    "haversine_km", "SpatialIndex",
]
