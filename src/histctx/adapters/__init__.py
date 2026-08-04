"""Адаптеры: исходные файлы проекта -> единая схема ContextRecord."""

from .bookplaces import load_literary_places, load_tenishev
from .battles import load_battles
from .prokudin_gorsky import load_prokudin_gorsky

ADAPTERS = {
    "literary_places": load_literary_places,
    "tenishev": load_tenishev,
    "battles": load_battles,
    "prokudin_gorsky": load_prokudin_gorsky,
}

__all__ = [
    "ADAPTERS",
    "load_literary_places",
    "load_tenishev",
    "load_battles",
    "load_prokudin_gorsky",
]
