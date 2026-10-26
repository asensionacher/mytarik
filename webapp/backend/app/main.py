"""
FastAPI app — expone:
    GET  /health
    POST /api/invoice/upload   (multipart/form-data: file)
    POST /api/classify        (json: { "description": "..." })
    POST /api/classify/raw    (json: { "text": "línea1\nlínea2" })
"""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Callable
from typing import Any, Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.invoice_parser import ParsedInvoice, parse_invoice, parse_text
from app.tariffai_client import ClarificationAnswer, ResponseLanguage, TariffAIClient, make_client

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

class TradeDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_mode: Literal["import", "export"]
    origin_country: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    dispatch_country: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")


class ClassifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=3, description="Descripción de una línea de factura")
    language: ResponseLanguage = "en"
    trade: TradeDetails | None = None
    clarification_answers: list[ClarificationAnswer] = Field(default_factory=list, max_length=3)

class RawBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="Texto completo de la factura")
    language: ResponseLanguage = "en"
    trade: TradeDetails


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


def _progress_response(
    parser: Callable[[], ParsedInvoice], filename: str, trade: TradeDetails,
    source: str | None = None, language: ResponseLanguage = "en",
) -> StreamingResponse:
    def event(event_type: str, **data: Any) -> str:
        return json.dumps({"type": event_type, **data}, ensure_ascii=False) + "\n"

    async def events():
        try:
            yield event("stage", stage="parsing")
            parsed = await run_in_threadpool(parser)
            total = len(parsed.descriptions)
            invoice = {
                "filename": filename, "source": source or parsed.source,
                "pages": parsed.pages, "items_count": 0, "items": [],
                "trade": trade.model_dump(),
            }
            if not total:
                invoice["warning"] = (
                    "No se detectaron descripciones válidas en la factura."
                    if language == "es" else "No valid product descriptions were found in the invoice."
                )
            logger.info("Factura extraída: %s líneas; clasificación con hasta 3 llamadas en paralelo", total)
            yield event("ready", invoice=invoice, total=total)
            if total:
                async with make_client() as client:
                    results = client.classify_progress(
                        parsed.descriptions, language=language, trade=trade.model_dump(),
                    )
                    try:
                        completed = 0
                        async for index, response in results:
                            completed += 1
                            logger.info("Clasificación: %s/%s; línea %s; %s", completed, total, index + 1, response.status)
                            yield event(
                                "item", index=index,
                                item={
                                    "line_number": index + 1,
                                    "description": parsed.descriptions[index],
                                    "classification": response.model_dump(),
                                },
                            )
                    finally:
                        await results.aclose()
            yield event("done")
        except (httpx.TimeoutException, TimeoutError):
            logger.exception("Tiempo de espera agotado durante la clasificación en directo")
            yield event("error", status=504, message="TariffAI superó el tiempo de espera de clasificación")
        except ValueError as exc:
            logger.exception("Factura inválida durante la extracción en directo")
            yield event("error", status=400, message=str(exc))
        except Exception as exc:
            logger.exception("Fallo durante la clasificación en directo")
            yield event("error", status=502, message=str(exc) or type(exc).__name__)

    return StreamingResponse(
        events(), media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/invoice/upload", response_model=None)
async def upload_invoice(
    request: Request,
    file: UploadFile = File(...),
    trade_mode: Literal["import", "export"] = Form(...),
    origin_country: str = Form(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
    dispatch_country: str = Form(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
    language: ResponseLanguage = Form(default="en"),
) -> dict[str, Any] | StreamingResponse:
    """Recibe una factura, la parsea y clasifica cada línea vía TariffAI."""
    trade = TradeDetails(
        trade_mode=trade_mode,
        origin_country=origin_country,
        dispatch_country=dispatch_country,
    )
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Fichero vacío")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"El fichero supera el límite de {settings.max_upload_bytes // (1024 * 1024)} MB",
        )

    filename = file.filename or "invoice"

    if "application/x-ndjson" in request.headers.get("accept", ""):
        return _progress_response(
            lambda: parse_invoice(filename, raw), filename, trade, language=language,
        )

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
            "trade": trade.model_dump(),
            "warning": (
                "No se detectaron líneas con descripción de producto. "
                "Prueba con un PDF con tablas o revisa la calidad de la imagen."
                if language == "es" else
                "No product description lines were found. Try a PDF with tables or check the image quality."
            ),
        }

    try:
        async with make_client() as client:
            classified = await client.classify_batch(
                parsed.descriptions,
                language=language,
                trade=trade.model_dump(),
            )
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.exception("Tiempo de espera agotado clasificando la factura")
        raise HTTPException(504, "TariffAI superó el tiempo de espera de clasificación") from exc
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
        "trade": trade.model_dump(),
    }


@app.post("/api/classify")
async def classify_single(body: ClassifyBody) -> dict[str, Any]:
    """Clasifica una única descripción (atajo para pruebas)."""
    try:
        async with make_client() as client:
            clarification = (
                {"clarification_answers": [a.model_dump() for a in body.clarification_answers]}
                if body.clarification_answers else {}
            )
            response = await client.classify_one(
                body.description,
                language=body.language,
                trade=body.trade.model_dump() if body.trade else None,
                **clarification,
            )
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.exception("Tiempo de espera agotado clasificando la descripción")
        raise HTTPException(504, "TariffAI superó el tiempo de espera de clasificación") from exc
    except Exception as exc:
        logger.exception("Fallo llamando a TariffAI")
        raise HTTPException(502, f"TariffAI no respondió: {exc}") from exc
    return _serialize([response])[0]


@app.post("/api/classify/raw", response_model=None)
async def classify_raw(body: RawBody, request: Request) -> dict[str, Any] | StreamingResponse:
    """Pega texto plano (una descripción por línea)."""
    if "application/x-ndjson" in request.headers.get("accept", ""):
        return _progress_response(
            lambda: parse_text(body.text.encode("utf-8")), "text", body.trade,
            source="raw", language=body.language,
        )

    parsed = parse_text(body.text.encode("utf-8"))
    if not parsed.descriptions:
        return {
            "source": "raw",
            "items_count": 0,
            "items": [],
            "trade": body.trade.model_dump(),
            "warning": (
                "No se detectaron descripciones válidas en el texto."
                if body.language == "es" else "No valid descriptions were found in the text."
            ),
        }

    try:
        async with make_client() as client:
            responses = await client.classify_batch(
                parsed.descriptions,
                language=body.language,
                trade=body.trade.model_dump(),
            )
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.exception("Tiempo de espera agotado clasificando el texto")
        raise HTTPException(504, "TariffAI superó el tiempo de espera de clasificación") from exc
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
        "trade": body.trade.model_dump(),
    }


# Catch-all visible para depurar excepciones no manejadas (útil en dev)
@app.exception_handler(Exception)
async def _unhandled(request, exc):  # type: ignore[no-untyped-def]
    logger.error("Unhandled error: %s\n%s", exc, traceback.format_exc())
    return HTTPException(500, "Internal server error")
