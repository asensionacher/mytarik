"""
Orquestador del motor de medidas aduaneras.

Flujo:
    1. Validación geográfica (intracomunitario vs. país tercero vs. excepción).
    2. Consulta en caché o en tiempo real, en paralelo por partida.
    3. Interpretación de las medidas crudas (parser + base regulatoria).
    4. Enriquecimiento con LLM (una llamada por operación).
    5. Respuesta estructurada.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.config import CUSTOMS_LLM_ENABLED
from app.customs.cache import get_cache
from app.customs.estimation import estimate_taxes
from app.customs.geography import assess_geography
from app.customs.interpreter import deterministic_summary, interpret_operation
from app.customs.parser import build_item_measures, vat_rate
from app.customs.schemas import (
    CustomsOperationRequest,
    CustomsOperationResponse,
    CustomsRegime,
    DataSource,
    ItemMeasures,
    ItemProvenance,
)
from app.customs.taric_client import (
    ProviderResult,
    QueryOutcome,
    TaricQuery,
    TaricRealtimeClient,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_client: TaricRealtimeClient | None = None


def get_client() -> TaricRealtimeClient:
    """
    Cliente de medidas compartido.

    Se reutiliza entre peticiones para mantener el pool de conexiones y la
    caché diaria del proceso.
    """
    global _client
    if _client is None:
        _client = TaricRealtimeClient(cache=get_cache())
    return _client


async def close_client() -> None:
    """Cierra el cliente compartido (fin de vida del proceso)."""
    global _client
    if _client is not None:
        await _client.__aexit__(None, None, None)
        _client = None


def _intra_union_item(
    item,
    index: int,
    request: CustomsOperationRequest,
    regime: CustomsRegime,
) -> ItemMeasures:
    """Partida de una operación intracomunitaria: sin medidas arancelarias."""
    measures = ItemMeasures(
        line_number=index + 1,
        taric_code=item.taric_code,
        description=item.description,
        provenance=ItemProvenance(
            provider="none",
            source=DataSource.NOT_APPLICABLE,
            fetched_at=_now(),
            warnings=["Operación intracomunitaria: no se consultan medidas arancelarias."],
        ),
    )
    measures.executive_summary = deterministic_summary(measures, request, regime)
    return measures


async def evaluate_operation(
    request: CustomsOperationRequest,
    client: TaricRealtimeClient | None = None,
) -> CustomsOperationResponse:
    """Evalúa una operación aduanera completa."""
    started = time.time()
    assessment = assess_geography(
        request.origin_country,
        request.destination_country,
        request.operation_type,
        request.origin_subdivision,
        request.destination_subdivision,
    )
    logger.info(
        "Evaluando operación %s %s → %s (régimen %s)",
        request.operation_type, request.origin_country,
        request.destination_country, assessment.regime.value,
    )

    warnings: list[str] = []
    items_measures: list[ItemMeasures] = []
    cache_hits = 0
    provider_name = "none"

    if not assessment.requires_taric_consultation:
        items_measures = [
            _intra_union_item(item, index, request, assessment.regime)
            for index, item in enumerate(request.items)
        ]
        provider_name = "none"
        warnings.append(
            "No se ha consultado ninguna fuente externa: el régimen territorial lo "
            "dispensa de medidas arancelarias."
        )
    else:
        active_client = client or get_client()
        active_client.ensure_ready()
        outcomes = await asyncio.gather(*[
            active_client.get_measures(TaricQuery(
                taric_code=item.taric_code,
                origin_country=request.origin_country,
                destination_country=request.destination_country,
                operation_type=request.operation_type,
            ))
            for item in request.items
        ])

        for index, (item, outcome) in enumerate(zip(request.items, outcomes)):
            items_measures.append(
                _build_item(item, index, outcome, request, assessment)
            )
            if outcome.cache_hit:
                cache_hits += 1
            if outcome.provider:
                provider_name = outcome.provider
            for warning in outcome.warnings:
                warnings.append(f"Línea {index + 1}: {warning}")

    # Interpretación LLM (una llamada para toda la operación).
    if CUSTOMS_LLM_ENABLED and any(
        item.third_country_duty
        or item.preferential_duties
        or item.trade_defense_measures
        or item.environmental_and_special_regulations
        for item in items_measures
    ):
        summaries = await interpret_operation(request, items_measures)
        for item in items_measures:
            summary = summaries.get(item.line_number)
            if summary is not None:
                item.executive_summary = summary
    for item in items_measures:
        if item.executive_summary is None:
            item.executive_summary = deterministic_summary(item, request, assessment.regime)

    status: str = "ok"
    if any(item.provenance.source is DataSource.UNKNOWN for item in items_measures):
        status = "partial"
    if not items_measures:
        status = "error"

    return CustomsOperationResponse(
        status=status,
        operation_type=request.operation_type,
        origin_country=request.origin_country,
        destination_country=request.destination_country,
        incoterm=request.incoterm,
        customs_regime=assessment.regime,
        territorial_note=assessment.territorial_note,
        reporting_requirements=assessment.reporting_requirements,
        items_measures=items_measures,
        warnings=warnings,
        provider=provider_name,
        cache_hits=cache_hits,
        processing_time_ms=round((time.time() - started) * 1000, 2),
    )


def _build_item(
    item,
    index: int,
    outcome: QueryOutcome,
    request: CustomsOperationRequest,
    assessment,
) -> ItemMeasures:
    """Construye el desglose de una partida a partir del resultado del proveedor."""
    if not outcome.available or outcome.result is None:
        measures = ItemMeasures(
            line_number=index + 1,
            taric_code=item.taric_code,
            description=item.description,
            provenance=ItemProvenance(
                provider=outcome.provider,
                source=DataSource.UNKNOWN,
                fetched_at=_now(),
                warnings=outcome.warnings or ["No se pudo consultar la fuente de medidas."],
            ),
        )
        measures.executive_summary = deterministic_summary(measures, request, assessment.regime)
        return measures

    result: ProviderResult = outcome.result
    measures = build_item_measures(
        result,
        item,
        language=request.language,
        operation_type=request.operation_type,
        destination_country=request.destination_country,
        line_number=index + 1,
    )
    measures.provenance = ItemProvenance(
        provider=result.provider,
        source=DataSource.CACHE if outcome.cache_hit else DataSource.LIVE,
        cache_hit=outcome.cache_hit,
        queried_code=result.queried_code,
        raw_measure_count=len(result.flat_measures),
        fetched_at=_now(),
        warnings=list(result.warnings),
    )

    vat_percentage = None
    if assessment.regime is CustomsRegime.IMPORT_FROM_THIRD_COUNTRY:
        vat_percentage = vat_rate(result.taxes)
    measures.tax_estimation = estimate_taxes(item, measures, request, vat_percentage)
    return measures
