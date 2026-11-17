"""
Stage 2 (EU): Hybrid CN8/TARIC10 Retriever (No LLM)

Retrieves candidate EU nomenclature entries (CN8 + TARIC10) from the
`eu_taric` Qdrant collection populated by `scripts/ingest_eu_taric.py`.

This retriever is deliberately narrow:
  * It reads ONLY the `eu_taric` collection. It never queries `hs_codes`.
  * It exposes NO parameter to select a different collection, so a caller
    cannot point it at the 6-digit HS6 catalogue.

It reuses the same hybrid strategy as the HS6 retriever (dense
multilingual-e5-small vectors fused with BM25 keyword search via Reciprocal
Rank Fusion), but returns CN8/TARIC10 candidates instead of 6-digit codes.

Dependency injection (`client`, `embedder`) keeps the retrieval logic unit-
testable against a fake Qdrant client without a running Qdrant or a network
round-trip.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Sequence

from app.config import TOP_K_CANDIDATES, SEMANTIC_WEIGHT, BM25_WEIGHT

logger = logging.getLogger(__name__)

# This module only ever talks to the EU nomenclature collection.
EU_TARIC_COLLECTION = "eu_taric"

# Guard: the EU retriever must never read the 6-digit HS catalogue.
_HS6_COLLECTION = "hs_codes"

Embedder = Callable[[str], list[float]]

# RRF smoothing constant and the normalization denominator mirror hs_retriever.
_RRF_K = 60
_MAX_SCORE = (SEMANTIC_WEIGHT + BM25_WEIGHT) / (_RRF_K + 1)  # k=60, rank=0


@dataclass(frozen=True)
class EUCandidate:
    """A CN8/TARIC10 candidate returned by the EU retrieval stage."""
    cn8: str
    taric10: str
    description: str
    score: float


# ── Lazy-loaded singletons (only used when no dependency is injected) ───
_qdrant_client = None
_embed_model = None


def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient

        from app.config import QDRANT_HOST, QDRANT_PORT

        _qdrant_client = QdrantClient(
            host=QDRANT_HOST, port=QDRANT_PORT, timeout=30.0, check_compatibility=False
        )
    return _qdrant_client


def _get_embedder() -> Embedder:
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        from app.config import EMBEDDING_MODEL

        _embed_model = SentenceTransformer(EMBEDDING_MODEL)

    model = _embed_model

    def _embed(text: str) -> list[float]:
        return model.encode(text).tolist()

    return _embed


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alphanumeric (EU descriptions are comma-heavy)."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _entry_key(payload: dict) -> str:
    return str(payload.get("taric10") or payload.get("cn8") or payload.get("description", ""))


# ── Semantic Search ─────────────────────────────────────────────────────

def _search_semantic(
    query_text: str, top_k: int, client, embedder: Embedder
) -> list[tuple[dict, float]]:
    query_vec = embedder(f"query: {query_text}")

    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=EU_TARIC_COLLECTION,
            query=query_vec,
            limit=top_k * 2,
            with_payload=True,
        )
        hits = response.points
    else:
        hits = client.search(
            collection_name=EU_TARIC_COLLECTION,
            query_vector=query_vec,
            limit=top_k * 2,
            with_payload=True,
        )
    return [(hit.payload, float(hit.score)) for hit in hits]


# ── BM25 Search ─────────────────────────────────────────────────────────

def _scroll_payloads(client) -> list[dict]:
    payloads: list[dict] = []
    offset = None
    while True:
        results, next_offset = client.scroll(
            collection_name=EU_TARIC_COLLECTION,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in results:
            payloads.append(point.payload)
        if next_offset is None:
            break
        offset = next_offset
    return payloads


def _search_bm25(query_text: str, top_k: int, client) -> list[tuple[dict, float]]:
    from rank_bm25 import BM25Okapi

    payloads = _scroll_payloads(client)
    if not payloads:
        return []

    corpus = [_tokenize(p.get("description", "")) for p in payloads]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query_text))

    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: top_k * 2]
    return [(payloads[i], float(scores[i])) for i in top_indices if scores[i] > 0]


# ── Reciprocal Rank Fusion ──────────────────────────────────────────────

def _reciprocal_rank_fusion(
    semantic_results: Sequence[tuple[dict, float]],
    bm25_results: Sequence[tuple[dict, float]],
) -> list[tuple[dict, float]]:
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for rank, (payload, _score) in enumerate(semantic_results):
        key = _entry_key(payload)
        scores[key] = scores.get(key, 0.0) + SEMANTIC_WEIGHT * (1.0 / (_RRF_K + rank + 1))
        payloads[key] = payload

    for rank, (payload, _score) in enumerate(bm25_results):
        key = _entry_key(payload)
        scores[key] = scores.get(key, 0.0) + BM25_WEIGHT * (1.0 / (_RRF_K + rank + 1))
        payloads[key] = payload

    return [(payloads[key], scores[key]) for key in sorted(scores, key=scores.get, reverse=True)]


# ── Public API ──────────────────────────────────────────────────────────

def retrieve_eu_candidates(
    query_text: str,
    top_k: int | None = None,
    *,
    client=None,
    embedder: Embedder | None = None,
) -> list[EUCandidate]:
    """
    Retrieve Top-K CN8/TARIC10 candidates from the `eu_taric` collection using
    hybrid semantic + BM25 search fused with RRF.

    Args:
        query_text: Cargo description to match against the EU nomenclature.
        top_k: Number of candidates to return (default: from config).
        client: Optional Qdrant client (defaults to the configured one).
        embedder: Optional callable(text) -> vector (defaults to e5-small).

    There is deliberately no collection parameter: this retriever only reads
    `eu_taric` and must never be pointed at the 6-digit HS6 catalogue.
    """
    if EU_TARIC_COLLECTION == _HS6_COLLECTION:  # pragma: no cover - defensive
        raise RuntimeError("EU retriever is misconfigured to read the HS6 collection.")

    if top_k is None:
        top_k = TOP_K_CANDIDATES
    client = client if client is not None else _get_qdrant()
    embedder = embedder if embedder is not None else _get_embedder()

    semantic_results = _search_semantic(query_text, top_k, client, embedder)
    bm25_results = _search_bm25(query_text, top_k, client)
    fused = _reciprocal_rank_fusion(semantic_results, bm25_results)

    candidates: list[EUCandidate] = []
    for payload, score in fused[:top_k]:
        normalized = min(score / _MAX_SCORE, 1.0) if _MAX_SCORE > 0 else 0.0
        candidates.append(
            EUCandidate(
                cn8=str(payload.get("cn8") or ""),
                taric10=str(payload.get("taric10") or ""),
                description=str(payload.get("description") or ""),
                score=round(normalized, 4),
            )
        )
    return candidates


def initialize_eu_retriever() -> None:
    """Pre-warm the embedding model so the first request isn't slow."""
    _get_embedder()
    logger.info("[TariffAI] EU retriever initialized: embedding model loaded.")
