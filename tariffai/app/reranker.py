"""Multilingual cross-encoder reranker for EU candidates."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.eu_retriever import EUCandidate

MODEL_DIR = Path(os.getenv("RERANKER_DIR", "models/reranker"))
if not MODEL_DIR.is_absolute():
    MODEL_DIR = Path(__file__).resolve().parents[1] / MODEL_DIR


@lru_cache(maxsize=1)
def _model():
    if not (MODEL_DIR / "config.json").is_file():
        return None
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder(str(MODEL_DIR), num_labels=1, max_length=256, device="cpu")
    except Exception:
        return None


def rerank_candidates(query: str, candidates: list[EUCandidate]) -> list[EUCandidate]:
    model = _model()
    if model is None or not candidates:
        return candidates
    pairs = [[query, candidate.description] for candidate in candidates]
    try:
        scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    except Exception:
        return candidates
    ranked = [candidate for _, candidate in sorted(zip(scores, candidates), key=lambda pair: float(pair[0]), reverse=True)]
    return ranked
