"""
FastAPI app — expone:
    GET  /health
    POST /api/invoice/upload   (multipart/form-data: file)
    POST /api/classify        (json: { "description": "..." })
    POST /api/classify/raw    (json: { "text": "línea1\nlínea2" })
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.invoice_parser import parse_invoice
from app.tariffai_client import TariffAIClient, make_client

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("webapp.backend")

app = FastAPI(
    title="MyTarik — Backend",
    description=(
        "Backend que parsea facturas (PDF / texto / imagen) y consulta la API "
        "TariffAI para clasificar cada línea en un código HS."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ────────────────────────────────────────────────────────────

class ClassifyBody(BaseModel):
    description: str = Field(..., min_length=3, description="Descripción de una línea de factura")
    proveedor: str | None = Field(
        default=None,
        description="Proveedor LLM ('gemini' | 'minimax'). Vacío = usa LLM_PROVIDER del .env",
    )
    modelo: str | None = Field(
        default=None,
        description="Override del modelo LLM (ej. 'gemini-2.5-pro'). Vacío = usa el default del proveedor",
    )

class RawBody(BaseModel):
    text: str = Field(..., min_length=1, description="Texto completo de la factura")
    proveedor: str | None = Field(default=None, description="Proveedor LLM")
    modelo: str | None = Field(default=None, description="Override del modelo LLM")


# ── Endpoints ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Estado del backend y alcanzabilidad de TariffAI."""
    tariffai_ok = False
    tariffai_info: Any = None
    try:
        async with make_client() as client:
            tariffai_info = await client.health()
            tariffai_ok = True
    except Exception as exc:
        logger.warning("TariffAI unreachable: %s", exc)
        tariffai_info = {"error": str(exc)}

    return {
        "service": "webapp-backend",
        "status": "healthy" if tariffai_ok else "degraded",
        "tariffai_url": settings.tariffai_url,
        "tariffai_reachable": tariffai_ok,
        "tariffai": tariffai_info,
    }


def _serialize(responses) -> list[dict[str, Any]]:
    """Convierte la lista de ClassifyResponse (Pydantic) en dicts JSON-serializables."""
    return [r.model_dump() for r in responses]


@app.post("/api/invoice/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    proveedor: str | None = Form(default=None),
    modelo: str | None = Form(default=None),
) -> dict[str, Any]:
    """Recibe una factura, la parsea y clasifica cada línea vía TariffAI.

    Acepta campos multipart opcionales `proveedor` y `modelo` para override del LLM.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Fichero vacío")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"El fichero supera el límite de {settings.max_upload_bytes // (1024 * 1024)} MB",
        )

    filename = file.filename or "invoice"
    model = (modelo or "").strip() or None
    provider = (proveedor or "").strip() or None

    try:
        parsed = parse_invoice(filename, raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Fallo parseando la factura")
        raise HTTPException(500, f"No se pudo parsear la factura: {exc}") from exc

    if not parsed.descriptions:
        return {
            "filename": filename,
            "source": parsed.source,
            "pages": parsed.pages,
            "items_count": 0,
            "items": [],
            "warning": (
                "No se detectaron líneas con descripción de producto. "
                "Prueba con un PDF con tablas o revisa la calidad de la imagen."
            ),
        }

    try:
        async with make_client() as client:
            classified = await client.classify_batch(
                parsed.descriptions, model=model, provider=provider,
            )
    except Exception as exc:
        logger.exception("Fallo llamando a TariffAI")
        raise HTTPException(
            502,
            f"TariffAI no respondió correctamente: {exc}",
        ) from exc

    items: list[dict[str, Any]] = []
    for line, response in zip(parsed.descriptions, classified):
        item: dict[str, Any] = {"description": line, "classification": _serialize([response])[0]}
        items.append(item)

    return {
        "filename": filename,
        "source": parsed.source,
        "pages": parsed.pages,
        "items_count": len(items),
        "items": items,
    }


@app.post("/api/classify")
async def classify_single(body: ClassifyBody) -> dict[str, Any]:
    """Clasifica una única descripción (atajo para pruebas)."""
    try:
        async with make_client() as client:
            response = await client.classify_one(
                body.description,
                model=body.modelo,
                provider=body.proveedor,
            )
    except Exception as exc:
        logger.exception("Fallo llamando a TariffAI")
        raise HTTPException(502, f"TariffAI no respondió: {exc}") from exc
    return _serialize([response])[0]


@app.post("/api/classify/raw")
async def classify_raw(body: RawBody) -> dict[str, Any]:
    """Pega texto plano (una descripción por línea)."""
    # Reutilizamos el parser de texto directamente sobre el body
    from app.invoice_parser import parse_text

    parsed = parse_text(body.text.encode("utf-8"))
    if not parsed.descriptions:
        return {
            "source": "raw",
            "items_count": 0,
            "items": [],
            "warning": "No se detectaron descripciones válidas en el texto.",
        }

    try:
        async with make_client() as client:
            responses = await client.classify_batch(
                parsed.descriptions,
                model=body.modelo,
                provider=body.proveedor,
            )
    except Exception as exc:
        logger.exception("Fallo llamando a TariffAI")
        raise HTTPException(502, f"TariffAI no respondió: {exc}") from exc

    items = [
        {"description": line, "classification": _serialize([r])[0]}
        for line, r in zip(parsed.descriptions, responses)
    ]
    return {
        "source": "raw",
        "items_count": len(items),
        "items": items,
    }


# Catch-all visible para depurar excepciones no manejadas (útil en dev)
@app.exception_handler(Exception)
async def _unhandled(request, exc):  # type: ignore[no-untyped-def]
    logger.error("Unhandled error: %s\n%s", exc, traceback.format_exc())
    return HTTPException(500, "Internal server error")
