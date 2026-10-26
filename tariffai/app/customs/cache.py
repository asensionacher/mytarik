"""
Caché diaria de medidas aduaneras.

El TARIC se actualiza una sola vez al día, así que la clave incluye la fecha
de consulta: `f"{taric_code}:{origin}:{destination}:{operation_type}:{date}"`.
Con TTL de 24 h el rollover natural de la fecha invalida lo cacheado sin
necesidad de purgas explícitas.

La implementación por defecto es en memoria (`cachetools.TTLCache`). La
interfaz `MeasureCache` permite sustituirla por Redis o SQLite sin tocar el
resto del motor.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Protocol

from cachetools import TTLCache

from app.config import TARIC_CACHE_MAX_SIZE, TARIC_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)


class MeasureCache(Protocol):
    """Contrato mínimo de la caché de medidas."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...

    def clear(self) -> None: ...


def cache_key(
    taric_code: str,
    origin_country: str,
    destination_country: str,
    operation_type: str,
    on_date: date | None = None,
) -> str:
    """Clave de caché diaria para una partida y un flujo."""
    day = (on_date or date.today()).isoformat()
    return f"{taric_code}:{origin_country}:{destination_country}:{operation_type}:{day}"


class TTLDailyMeasureCache:
    """Caché en memoria con TTL. Sustituible por Redis/SQLite."""

    def __init__(
        self,
        ttl: int = TARIC_CACHE_TTL_SECONDS,
        maxsize: int = TARIC_CACHE_MAX_SIZE,
    ) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        value = self._cache.get(key)
        if value is not None:
            logger.debug("Caché: hit %s", key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


_cache: TTLDailyMeasureCache | None = None


def get_cache() -> TTLDailyMeasureCache:
    """Instancia única de la caché en memoria."""
    global _cache
    if _cache is None:
        _cache = TTLDailyMeasureCache()
    return _cache
