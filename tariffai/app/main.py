"""
TariffAI — FastAPI Application

Endpoints:
    POST /classify         — Classify a single cargo description
    POST /classify/batch   — Classify multiple descriptions
    POST /customs/evaluate — Determine the customs measures of an operation
    GET  /health           — Health check with Qdrant status
"""

import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.schemas import (
    ClassifyRequest, BatchClassifyRequest,
    ClassifyResponse, ClassificationResult,
    HS6LookupRequest, HS6LookupResponse, HS6Candidate,
)
from app.graph import classify_cargo
from app.hs_retriever import initialize_retriever
from app.taric_tree import get_node, node_view, tree_summary
from app.config import QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION
from app.customs.router import router as customs_router
from app.customs.service import close_client as close_customs_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm the retriever on startup."""
    print("[TariffAI] Starting up...")
    try:
        initialize_retriever()
        print("[TariffAI] ✅ Ready to classify!")
    except Exception as e:
        print(f"[TariffAI] ⚠️  Retriever init failed (Qdrant may not be running): {e}")
        print("[TariffAI]    The API will start but /classify will fail until Qdrant is available.")
    yield
    await close_customs_client()
    print("[TariffAI] Shutting down.")


app = FastAPI(
    title="TariffAI",
    description=(
        "Intelligent HS Code Classification Engine for Trade Compliance. "
        "Part of the TradeGuard platform (Week 4)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customs_router)


@app.post("/classify", response_model=ClassifyResponse)
def classify_endpoint(req: ClassifyRequest):
    """
    Classify a cargo description into a 6-digit HS code.

    The pipeline:
    1. Preprocesses the raw text (regex, no LLM)
    2. Retrieves top candidates via hybrid search (Qdrant + BM25, no LLM)
    3. Selects the best code with the LLM and reviews uncertain cases
    4. Asks up to three product questions if decisive attributes are missing

    Returns the classification result including:
    - The recommended HS code
    - Full Chapter → Heading → Subheading reasoning chain
    - Confidence score
    - Alternative codes (for ambiguous cases)

    Uses the server-configured Azure Foundry deployment only.
    """
    try:
        result = classify_cargo(
            req.description, language=req.language, trade=req.trade,
            clarification_answers=req.clarification_answers,
        )
        status = "ambiguous" if result.is_ambiguous else "classified"
        return ClassifyResponse(status=status, result=result)
    except Exception as e:
        traceback.print_exc()
        return ClassifyResponse(status="error", error=str(e))


@app.post("/classify/batch", response_model=list[ClassifyResponse])
def batch_classify_endpoint(req: BatchClassifyRequest):
    """
    Classify multiple cargo descriptions in one request.
    Each description is processed independently through the full pipeline.
    """
    results = []
    for desc in req.descriptions:
        try:
            result = classify_cargo(desc, language=req.language, trade=req.trade)
            status = "ambiguous" if result.is_ambiguous else "classified"
            results.append(ClassifyResponse(status=status, result=result))
        except Exception as e:
            results.append(ClassifyResponse(status="error", error=str(e)))
    return results


class EmbedRequest(BaseModel):
    text: str


class TranslateRequest(BaseModel):
    text: str
    target_language: str
    source_language: str | None = None


@app.post("/translate")
def translate_endpoint(request: TranslateRequest) -> dict[str, str]:
    """Internal endpoint for TARIC descriptions and EBTI evidence."""
    from app.translation import _get_mt_translator

    translator = _get_mt_translator()
    text = translator.translate(
        request.text,
        request.target_language,
        source_language=request.source_language,
    )
    return {"text": text}


@app.post("/embed")
def embed(request: EmbedRequest) -> dict[str, list[float]]:
    """Internal endpoint: embedding for the shared multilingual e5 model."""
    from app.eu_retriever import _get_embedder

    return {"vector": _get_embedder()(request.text)}


@app.get("/taric/tree")
def taric_tree_summary() -> dict:
    return tree_summary()


@app.get("/taric/tree/{code}")
def taric_tree_node(code: str) -> dict:
    node = node_view(code)
    if not node:
        raise HTTPException(404, "Código no encontrado en el árbol TARIC")
    return node


@app.get("/health")
def health_check():
    """Health check with Qdrant connectivity status."""
    from qdrant_client import QdrantClient

    qdrant_ok = False
    collection_count = 0
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5.0, check_compatibility=False)
        info = client.get_collection(QDRANT_COLLECTION)
        qdrant_ok = True
        collection_count = info.points_count
    except Exception:
        pass

    return {
        "service": "TariffAI",
        "status": "healthy" if qdrant_ok else "degraded",
        "qdrant": {
            "connected": qdrant_ok,
            "collection": QDRANT_COLLECTION,
            "points_count": collection_count,
        },
    }


@app.post("/hs6/lookup", response_model=HS6LookupResponse)
def hs6_lookup(req: HS6LookupRequest):
    """
    Retrieve international HS6 candidate codes for a cargo description.

    Uses the Stage 2 hybrid retriever (Qdrant semantic + BM25, no LLM) to
    find the top-K 6-digit HS codes whose official descriptions best match
    the query. This is a *reference* lookup: the returned codes are
    international HS6 codes and are NOT valid for an EU customs declaration
    (which requires a CN8 or TARIC10 code). The EU classifier is never
    invoked here.
    """
    from app.hs_retriever import retrieve_candidates

    candidates = retrieve_candidates(req.query, top_k=req.top_k)
    top_k = sorted(candidates, key=lambda c: c.retrieval_score, reverse=True)[: req.top_k]
    notice = "Referencia internacional HS6. No válido para declaración UE."
    return HS6LookupResponse(
        query=req.query,
        candidates=[
            HS6Candidate(hs6=c.code, description=c.description, score=c.retrieval_score)
            for c in top_k
        ],
        notice=notice,
    )
