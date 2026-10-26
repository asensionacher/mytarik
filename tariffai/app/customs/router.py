"""
Router del motor de medidas aduaneras.

    POST /customs/evaluate

Payload estricto (`extra="forbid"`), el mismo que viaja desde el backend de la
webapp. La respuesta es un desglose por partida.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter

from app.customs.schemas import CustomsOperationRequest, CustomsOperationResponse
from app.customs.service import evaluate_operation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customs", tags=["customs"])


@router.post("/evaluate", response_model=CustomsOperationResponse)
async def evaluate(req: CustomsOperationRequest) -> CustomsOperationResponse:
    """Determina las medidas aduaneras vigentes de cada partida de la operación."""
    started = time.time()
    try:
        response = await evaluate_operation(req)
    except Exception as exc:
        logger.exception("Fallo evaluando la operación aduanera")
        return CustomsOperationResponse(
            status="error",
            operation_type=req.operation_type,
            origin_country=req.origin_country,
            destination_country=req.destination_country,
            incoterm=req.incoterm,
            error=str(exc) or type(exc).__name__,
            processing_time_ms=round((time.time() - started) * 1000, 2),
        )
    logger.info(
        "Operación evaluada: %s partidas, régimen %s, %s ms",
        len(response.items_measures),
        response.customs_regime.value,
        response.processing_time_ms,
    )
    return response
