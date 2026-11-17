"""Tests for the international HS6 reference lookup endpoint (T4).

These tests are dependency-free: they monkeypatch the *retriever*
(`tariffai.app.hs_retriever.retrieve_candidates`) so no real Qdrant,
embedding model, BM25 index or LLM is required. They also assert that the
European classifier is never invoked from the HS6 lookup path.
"""

from fastapi.testclient import TestClient
from pydantic import BaseModel

# Support both container layout (import app.main from /app) and host layout
# (import tariffai.app.main with tariffai/ on sys.path).
try:  # container: root is /app
    from app.main import app
    import app.hs_retriever as _hs_retriever_mod
    import app.main as main_module
except ImportError:  # host: run from repo root with PYTHONPATH=tariffai
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.main import app
    import app.hs_retriever as _hs_retriever_mod
    import app.main as main_module

# ── Fake retrievable candidate ──────────────────────────────────────────────
class _FakeCandidate(BaseModel):
    code: str
    description: str
    chapter_code: str = ""
    chapter_description: str = ""
    heading_code: str = ""
    heading_description: str = ""
    section: str = ""
    section_description: str = ""
    retrieval_score: float = 0.0
    retrieval_method: str = "hybrid"

client = TestClient(app)


# ── Fixtures -----------------------------------------------------------------
def _patch_retriever(monkeypatch, candidates):
    """Replace retrieve_candidates with a deterministic fake."""
    def fake_retrieve(cleaned_text, top_k=None):
        return list(candidates[:top_k]) if top_k else list(candidates)

    monkeypatch.setattr(_hs_retriever_mod, "retrieve_candidates", fake_retrieve)
    return fake_retrieve


# ── Tests ───────────────────────────────────────────────────────────────────
def test_hs6_lookup_returns_reference_candidates(monkeypatch):
    candidates = [
        _FakeCandidate(code="620462", description="Women's suits", retrieval_score=0.91),
        _FakeCandidate(code="620463", description="Women's ensembles", retrieval_score=0.80),
        _FakeCandidate(code="620469", description="Wool garments", retrieval_score=0.72),
    ]
    _patch_retriever(monkeypatch, candidates)

    resp = client.post("/hs6/lookup", json={"query": "woman suit jacket", "top_k": 5})
    assert resp.status_code == 200

    body = resp.json()
    assert body["query"] == "woman suit jacket"
    assert body["notice"] == "Referencia internacional HS6. No válido para declaración UE."
    assert len(body["candidates"]) == 3
    assert body["candidates"][0] == {
        "hs6": "620462",
        "description": "Women's suits",
        "score": 0.91,
    }


def test_hs6_lookup_respects_top_k(monkeypatch):
    candidates = [
        _FakeCandidate(code=f"62046{i}", description=f"desc {i}", retrieval_score=0.9 - i * 0.1)
        for i in range(10)
    ]
    _patch_retriever(monkeypatch, candidates)

    resp = client.post("/hs6/lookup", json={"query": "test", "top_k": 2})
    body = resp.json()
    assert len(body["candidates"]) == 2
    # Candidates must be sorted by score descending.
    assert body["candidates"][0]["score"] >= body["candidates"][1]["score"]


def test_hs6_lookup_candidates_are_six_digit_codes():
    """The HS6Candidate schema must reject non-6-digit codes."""
    from pydantic import ValidationError
    from app.schemas import HS6Candidate, HS6LookupRequest

    # A valid 6-digit code is accepted.
    ok = HS6Candidate(hs6="620462", description="suit", score=0.9)
    assert ok.hs6 == "620462"

    # A malformed code is rejected by the regex pattern.
    try:
        HS6Candidate(hs6="ABCDEF", description="bad", score=0.4)
    except ValidationError as exc:
        assert "hs6" in str(exc)
    else:
        raise AssertionError("HS6Candidate should reject a non-numeric 6-digit code")

    # The request schema rejects an empty query.
    try:
        HS6LookupRequest(query="", top_k=5)
    except ValidationError:
        pass
    else:
        raise AssertionError("HS6LookupRequest should reject an empty query")


def test_hs6_lookup_rejects_extra_fields():
    resp = client.post("/hs6/lookup", json={"query": "shirt", "top_k": 5, "bogus": 1})
    assert resp.status_code == 422


def test_hs6_lookup_forbids_empty_query():
    resp = client.post("/hs6/lookup", json={"query": ""})
    assert resp.status_code == 422


def test_hs6_lookup_does_not_invoke_classifier(monkeypatch):
    """The HS6 lookup must never call classify_cargo (EU classifier)."""
    called = {"eu": False}

    def _boom(*args, **kwargs):
        called["eu"] = True
        raise AssertionError("classify_cargo should not be called from /hs6/lookup")

    monkeypatch.setattr(main_module, "classify_cargo", _boom)
    _patch_retriever(
        monkeypatch,
        [_FakeCandidate(code="620462", description="suit", retrieval_score=0.9)],
    )

    resp = client.post("/hs6/lookup", json={"query": "suit", "top_k": 1})
    assert resp.status_code == 200
    assert called["eu"] is False


def test_hs6_lookup_default_top_k(monkeypatch):
    """Without top_k, the default of 5 must apply."""
    calls = {"top_k": None}

    def fake_retrieve(cleaned_text, top_k=None):
        calls["top_k"] = top_k
        return [_FakeCandidate(code="620462", description="suit", retrieval_score=0.9)]

    monkeypatch.setattr(_hs_retriever_mod, "retrieve_candidates", fake_retrieve)

    resp = client.post("/hs6/lookup", json={"query": "suit"})
    assert resp.status_code == 200
    assert calls["top_k"] == 5
