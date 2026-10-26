"""
Cliente asíncrono de medidas aduaneras en tiempo real.

Access2Markets no publica una API REST oficial para TARIC, pero el portal
oficial de la Comisión Europea (Access2Markets) sí expone los JSON que
alimentan su propio frontend. Son la fuente primaria:

    GET {A2M}/api/tariffs/get/{code}/{origin}/{destination}?lang=EN
    GET {A2M}/api/taxes/get/{code}/{origin}/{destination}
    GET {A2M}/api/v2/document/list?destinationCountry=&originCountry=&product=&lang=EN

`tariffs/get` devuelve las medidas arancelarias vigentes: arancel de terceros
países (103), preferencias (142/143), derechos antidumping y compensatorios
(551–554), suspensiones, contingentes, aranceles adicionales por sanciones
(695/696) y, en cada medida, sus notas al pie y sus condiciones con los
certificados y códigos "Y" exigidos.

La secondary fuente es el UK Trade Tariff (útil cuando el origen o el destino
es Gran Bretaña). El servicio SOAP DDS2 de TAXUD ya no expone esa ruta, así que
queda como adaptador opcional y configurable.

Los datos se piden siempre en inglés: la clave de caché no incluye el idioma
de la respuesta y la localización la aporta la capa de interpretación LLM.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import (
    A2M_BASE_URL,
    TARIC_HTTP_MAX_CONCURRENCY,
    TARIC_HTTP_RETRIES,
    TARIC_HTTP_TIMEOUT,
    UK_TARIFF_API_KEY,
    UK_TARIFF_API_URL,
)
from app.customs.cache import MeasureCache, cache_key

logger = logging.getLogger(__name__)

#: Idioma con el que se piden los datos crudos (estable para la caché).
SOURCE_LANGUAGE = "EN"


class ProviderError(RuntimeError):
    """El proveedor no pudo atender la consulta."""


# ── Formato cable ──────────────────────────────────────────────────────


class RawMeasure(BaseModel):
    """Medida arancelaria tal y como la devuelve la fuente."""

    model_config = ConfigDict(extra="allow")

    measureType: str = ""
    type: str = ""
    origin: str = ""
    geographicalArea: str | None = None
    geographicalSigl: str | None = None
    regulationRoleType: str | None = None
    regulationId: str | None = None
    regulationOrderNumber: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    additionalCodeId: str | None = None
    additionalCodeText: str | None = None
    exclusions: str | None = None
    tariffFormula: str | None = None
    footnotes: list[dict[str, Any]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class RawTaricResult(BaseModel):
    """Bloque de la respuesta de `tariffs/get` (una rama de la nomenclatura)."""

    model_config = ConfigDict(extra="allow")

    measures: list[RawMeasure] = Field(default_factory=list)
    description: str = ""
    code: str | None = None


# ── Consulta y resultado ───────────────────────────────────────────────


@dataclass(frozen=True)
class TaricQuery:
    """Lo que se pide a los proveedores."""

    taric_code: str
    origin_country: str
    destination_country: str
    operation_type: str


@dataclass
class ProviderResult:
    """Respuesta normalizada de un proveedor."""

    provider: str
    measures: list[RawTaricResult] = field(default_factory=list)
    taxes: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    product_description: str | None = None
    queried_code: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def flat_measures(self) -> list[RawMeasure]:
        return [m for block in self.measures for m in block.measures]

    def to_dict(self) -> dict[str, Any]:
        """Forma serializable (para cachés Redis/SQLite)."""
        return {
            "provider": self.provider,
            "measures": [block.model_dump() for block in self.measures],
            "taxes": self.taxes,
            "documents": self.documents,
            "product_description": self.product_description,
            "queried_code": self.queried_code,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderResult":
        return cls(
            provider=payload.get("provider", ""),
            measures=[RawTaricResult.model_validate(b) for b in payload.get("measures", [])],
            taxes=payload.get("taxes") or [],
            documents=payload.get("documents") or [],
            product_description=payload.get("product_description"),
            queried_code=payload.get("queried_code"),
            warnings=payload.get("warnings") or [],
        )


@dataclass
class QueryOutcome:
    """Resultado de `TaricRealtimeClient.get_measures`."""

    available: bool
    provider: str = ""
    result: ProviderResult | None = None
    cache_hit: bool = False
    warnings: list[str] = field(default_factory=list)


# ── Proveedores ────────────────────────────────────────────────────────


class TaricProvider(Protocol):
    """Adaptador de una fuente de medidas."""

    name: str

    async def fetch(self, query: TaricQuery) -> ProviderResult: ...

    def supports(self, query: TaricQuery) -> bool: ...


def _candidate_codes(taric_code: str) -> list[str]:
    """
    Códigos que se prueban contra la fuente, del más al menos específico.

    Access2Markets resuelve nomenclatura combinada (8 dígitos): un TARIC de 10
    dígitos que no coincide con un nodo real devuelve lista vacía, así que se
    degrada al nivel de 8 y luego de 6 dígitos.
    """
    candidates: list[str] = []
    for length in (10, 8, 6):
        candidate = taric_code[:length]
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _zone_tree_to_blocks(payload: dict[str, Any]) -> list[RawTaricResult]:
    """
    Convierte la forma "árbol de zonas" de `tariffs/get` en bloques de medidas.

    Cuando la fuente no resuelve el código a una partida concreta (por ejemplo
    un código de 6 dígitos o un flujo de exportación), responde con el árbol de
    zonas arancelarias del país de destino:

        {"schemas": [...], "notes": [...], "root": {"children": [...]}}

    Cada nodo lleva `tariffs` con una entrada por zona (MFN, EU, ERGA OMNES…)
    y su fórmula. Se convierte en medidas de tipo 103 con el nombre de la zona
    como origen.
    """
    blocks: list[RawTaricResult] = []
    notes = [
        {
            "code": str(note.get("type") or ""),
            "type": str(note.get("type") or ""),
            "text": str(note.get("note") or ""),
        }
        for note in (payload.get("notes") or [])
        if isinstance(note, dict)
    ]

    def walk(node: dict[str, Any]) -> None:
        tariffs = node.get("tariffs")
        if isinstance(tariffs, dict):
            measures: list[RawMeasure] = []
            for zone, entries in tariffs.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    measures.append(RawMeasure(
                        measureType="103",
                        type="Third country duty",
                        origin=str(zone),
                        geographicalSigl=str(zone),
                        tariffFormula=entry.get("formula"),
                        footnotes=notes,
                    ))
            if measures:
                blocks.append(RawTaricResult(
                    measures=measures,
                    description=str(node.get("label") or ""),
                    code=node.get("productCode"),
                ))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    root = payload.get("root")
    if isinstance(root, dict):
        walk(root)
    return blocks


class Access2MarketsProvider:
    """Proveedor principal: JSON del portal Access2Markets de la Comisión Europea."""

    name = "access2markets"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = A2M_BASE_URL,
        timeout: float = TARIC_HTTP_TIMEOUT,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def supports(self, query: TaricQuery) -> bool:
        return True

    async def fetch(self, query: TaricQuery) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        code_used: str | None = None

        for candidate in _candidate_codes(query.taric_code):
            payload = await self._get_json(
                f"/api/tariffs/get/{candidate}/{query.origin_country}/{query.destination_country}",
                params={"lang": SOURCE_LANGUAGE},
            )
            if isinstance(payload, dict):
                # Forma de árbol de zonas (el código no resuelve a una partida).
                blocks = _zone_tree_to_blocks(payload)
            else:
                blocks = [RawTaricResult.model_validate(block) for block in payload]
            if any(block.measures for block in blocks):
                result.measures = blocks
                result.product_description = next(
                    (b.description for b in blocks if b.description), None
                )
                code_used = candidate
                break
            if code_used is None and blocks:
                # Respuesta válida pero sin medidas: se conserva como contexto.
                result.measures = blocks
                result.product_description = next(
                    (b.description for b in blocks if b.description), None
                )
                code_used = candidate

        result.queried_code = code_used or query.taric_code[:8]

        if query.operation_type == "EXPORT" and result.flat_measures:
            result.warnings.append(
                "En un flujo de exportación la fuente devuelve el arancel del país de "
                "destino, no un arancel de la Unión Europea: la Unión no grava las "
                "exportaciones."
            )

        result.taxes = await self._get_json(
            f"/api/taxes/get/{result.queried_code}/{query.origin_country}/{query.destination_country}",
            params=None,
            optional=True,
        )
        result.documents = await self._get_json(
            "/api/v2/document/list",
            params={
                "destinationCountry": query.destination_country,
                "originCountry": query.origin_country,
                "product": result.queried_code,
                "lang": SOURCE_LANGUAGE,
            },
            optional=True,
        )
        if not result.flat_measures:
            result.warnings.append(
                f"La fuente no devolvió medidas arancelarias para {query.taric_code} "
                f"({query.origin_country} → {query.destination_country})."
            )
        return result

    async def _get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
        optional: bool = False,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.get(url, params=params, timeout=self._timeout)
        except httpx.HTTPError as exc:
            if optional:
                logger.warning("Access2Markets: fallo opcional en %s: %s", path, exc)
                return []
            raise ProviderError(f"Access2Markets falló en {path}: {exc}") from exc

        if response.status_code == 404:
            if optional:
                return []
            raise ProviderError(f"Access2Markets devolvió 404 en {path}")
        if response.status_code >= 500:
            if optional:
                logger.warning("Access2Markets: %s en %s", response.status_code, path)
                return []
            raise ProviderError(
                f"Access2Markets devolvió {response.status_code} en {path}"
            )
        try:
            return response.json()
        except ValueError as exc:
            if optional:
                logger.warning("Access2Markets: respuesta no JSON en %s", path)
                return []
            raise ProviderError(f"Access2Markets devolvió una respuesta no JSON en {path}") from exc


class UkTradeTariffProvider:
    """
    Proveedor secundario: UK Trade Tariff.

    Sólo se usa cuando el flujo involucra a Gran Bretaña (`GB`). Necesita
    credencial (`UK_TARIFF_API_KEY`); sin ella queda desactivado.
    """

    name = "uk_trade_tariff"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = UK_TARIFF_API_URL,
        api_key: str = UK_TARIFF_API_KEY,
        timeout: float = TARIC_HTTP_TIMEOUT,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def supports(self, query: TaricQuery) -> bool:
        if not self._api_key:
            return False
        return "GB" in (query.origin_country, query.destination_country)

    async def fetch(self, query: TaricQuery) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        code = query.taric_code[:8]
        url = f"{self._base_url}/lookup/commodities/{code}/duty"
        headers = {"Authorization": f"ApiKey {self._api_key}"}

        try:
            response = await self._client.get(
                url,
                headers=headers,
                params={"country": query.origin_country},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"UK Trade Tariff falló: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"UK Trade Tariff devolvió {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("UK Trade Tariff devolvió una respuesta no JSON") from exc

        duties = payload.get("duties") or payload.get("measures") or []
        if isinstance(duties, dict):
            duties = [duties]
        measures: list[RawMeasure] = []
        for duty in duties:
            if not isinstance(duty, dict):
                continue
            measures.append(RawMeasure(
                measureType=str(duty.get("measure_type", "103")),
                type=str(duty.get("measure_type", "Third country duty")),
                origin=str(duty.get("origin", query.origin_country)),
                geographicalSigl=str(duty.get("geographical_area", "")),
                tariffFormula=str(duty.get("duty_expression", "")) or None,
                startDate=duty.get("valid_from"),
                endDate=duty.get("valid_to"),
                regulationId=duty.get("regulation_id"),
                footnotes=duty.get("footnotes") or [],
                conditions=duty.get("conditions") or [],
            ))
        result.measures = [RawTaricResult(measures=measures)]
        result.queried_code = code
        result.product_description = payload.get("description") or None
        return result


# ── Cliente ────────────────────────────────────────────────────────────


class TaricRealtimeClient:
    """
    Orquesta caché, proveedores y reintentos.

    La caché se consulta antes de la red; si falla, se encadenan los
    proveedores en orden de prioridad. Un fallo total no revienta la petición:
    devuelve `available=False` con los avisos acumulados.
    """

    def __init__(
        self,
        providers: list[TaricProvider] | None = None,
        cache: MeasureCache | None = None,
        client: httpx.AsyncClient | None = None,
        max_concurrency: int = TARIC_HTTP_MAX_CONCURRENCY,
    ) -> None:
        self._cache = cache
        self._client = client
        self._owns_client = client is None
        self._providers = providers or []
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> "TaricRealtimeClient":
        self.ensure_ready()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def ensure_ready(self) -> None:
        """Crea el cliente HTTP y los proveedores si aún no existen."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    TARIC_HTTP_TIMEOUT, connect=min(10.0, TARIC_HTTP_TIMEOUT)
                ),
                headers={"Accept": "application/json"},
                follow_redirects=True,
            )
        if not self._providers:
            self._providers = [
                Access2MarketsProvider(self._client),
                UkTradeTariffProvider(self._client),
            ]

    @property
    def providers(self) -> list[TaricProvider]:
        return self._providers

    async def get_measures(self, query: TaricQuery) -> QueryOutcome:
        """Devuelve las medidas de una partida, usando caché y proveedores."""
        self.ensure_ready()
        key = cache_key(
            query.taric_code,
            query.origin_country,
            query.destination_country,
            query.operation_type,
        )
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                logger.info("Caché: hit para %s", key)
                result = (
                    ProviderResult.from_dict(cached)
                    if isinstance(cached, dict)
                    else cached
                )
                return QueryOutcome(
                    available=True,
                    provider=result.provider,
                    result=result,
                    cache_hit=True,
                )

        warnings: list[str] = []
        for provider in self._providers:
            if not provider.supports(query):
                continue
            try:
                result = await self._fetch_with_retry(provider, query)
            except ProviderError as exc:
                logger.warning("Proveedor %s falló: %s", provider.name, exc)
                warnings.append(f"{provider.name}: {exc}")
                continue
            if self._cache is not None:
                self._cache.set(key, result)
            return QueryOutcome(
                available=True,
                provider=provider.name,
                result=result,
                warnings=list(result.warnings),
            )

        return QueryOutcome(available=False, warnings=warnings)

    async def _fetch_with_retry(
        self, provider: TaricProvider, query: TaricQuery
    ) -> ProviderResult:
        """Reintentos con backoff exponencial y jitter."""
        attempts = max(1, TARIC_HTTP_RETRIES)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._semaphore:
                    return await provider.fetch(query)
            except (ProviderError, httpx.HTTPError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                delay = min(2 ** attempt, 8) + random.uniform(0, 0.5)
                logger.warning(
                    "Reintento %s/%s tras fallo de %s: %s",
                    attempt + 1, attempts, provider.name, exc,
                )
                await asyncio.sleep(delay)
        raise ProviderError(
            f"{provider.name} agotó {attempts} intentos: {last_error}"
        ) from last_error
