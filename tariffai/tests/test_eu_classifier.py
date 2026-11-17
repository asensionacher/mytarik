import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

if "dotenv" not in sys.modules:
    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import graph
from app.eu_classifier import (
    EU_TARIFF_SYSTEM_PROMPT,
    EUClassificationError,
    classify_eu_with_llm,
)
from app.eu_retriever import EUCandidate
from app.schemas import ClassifyResponse, EUClassificationResult

CANDIDATES = [
    EUCandidate(
        cn8="62052000",
        taric10="6205200000",
        description="Men's or boys' cotton shirts",
        score=0.95,
    )
]


class FakeProvider:
    def __init__(self, payload, *, text=None):
        self.payload = payload
        self.text = text
        self.calls = []

    def complete(self, *, system, user):
        self.calls.append((system, user))
        body = self.text if self.text is not None else json.dumps(self.payload)
        return SimpleNamespace(
            text=body,
            prompt_tokens=100,
            output_tokens=50,
            total_tokens=150,
            thinking=None,
        )


def _eu_payload(**overrides):
    payload = {
        "cn8": "62052000",
        "taric10": "6205200000",
        "description": "Men's cotton shirts",
        "confidence": 0.9,
        "reasoning": {
            "section_reasoning": "Textiles",
            "chapter_reasoning": "Apparel",
            "heading_reasoning": "Shirts",
            "subheading_reasoning": "Cotton shirts",
            "key_factors": ["cotton", "woven"],
        },
        "alternatives": [],
        "clarification_question": None,
        "needs_human_review": False,
    }
    payload.update(overrides)
    return payload


def _classify(provider):
    return classify_eu_with_llm(
        "Men's woven cotton shirts, 120 units",
        "Men's woven cotton shirts, 120 units",
        CANDIDATES,
        language="en",
        provider=provider,
    )


def test_eu_prompt_has_no_hs6_wording():
    assert "6-digit HS codes" not in EU_TARIFF_SYSTEM_PROMPT
    assert "CN8" in EU_TARIFF_SYSTEM_PROMPT
    assert "TARIC10" in EU_TARIFF_SYSTEM_PROMPT


def test_eu_classifier_returns_cn8_and_taric10():
    result = _classify(FakeProvider(_eu_payload()))
    assert isinstance(result, EUClassificationResult)
    assert result.cn8 == "62052000"
    assert result.taric10 == "6205200000"
    assert result.primary_code == "6205200000"
    assert result.classification_mode == "eu"
    assert len(result.primary_code) in {8, 10}
    assert result.prompt_tokens == 100
    assert result.total_tokens == 150


def test_eu_classifier_rejects_candidate_outside_retrieval():
    with pytest.raises(EUClassificationError, match="not present"):
        _classify(FakeProvider(_eu_payload(cn8="99999999", taric10="9999999999")))


def test_eu_classifier_rejects_empty_candidates():
    with pytest.raises(EUClassificationError, match="No valid CN8/TARIC10"):
        classify_eu_with_llm(
            "shirts",
            "shirts",
            [],
            provider=FakeProvider(_eu_payload()),
        )


def test_eu_result_serializes_in_classify_response():
    result = _classify(FakeProvider(_eu_payload()))
    response = ClassifyResponse(status="classified", result=result)
    dumped = response.model_dump()
    assert dumped["result"]["cn8"] == "62052000"
    assert dumped["result"]["taric10"] == "6205200000"
    assert dumped["result"]["primary_code"] == "6205200000"
    assert "hs6" not in dumped["result"]


def test_graph_defaults_to_eu(monkeypatch):
    monkeypatch.delenv("CLASSIFICATION_MODE", raising=False)
    sentinel = object()
    monkeypatch.setattr("app.eu_classifier.classify_eu_cargo", lambda *a, **k: sentinel)
    assert graph.classify_cargo("shirts") is sentinel


def test_graph_uses_legacy_only_when_explicit(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_MODE", "legacy_hs6")
    sentinel = object()
    fake_legacy = ModuleType("app.legacy_graph")
    fake_legacy.classify_cargo = lambda *a, **k: sentinel
    monkeypatch.setitem(sys.modules, "app.legacy_graph", fake_legacy)
    monkeypatch.setattr(
        "app.eu_classifier.classify_eu_cargo",
        lambda *a, **k: pytest.fail("EU path must not run in legacy mode"),
    )
    assert graph.classify_cargo("shirts") is sentinel


def test_graph_does_not_fallback_from_eu(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_MODE", "eu")

    def fail(*args, **kwargs):
        raise EUClassificationError("eu_taric unavailable")

    monkeypatch.setattr("app.eu_classifier.classify_eu_cargo", fail)
    fake_legacy = ModuleType("app.legacy_graph")
    fake_legacy.classify_cargo = lambda *a, **k: pytest.fail("must not fall back to legacy_hs6")
    monkeypatch.setitem(sys.modules, "app.legacy_graph", fake_legacy)
    with pytest.raises(EUClassificationError, match="eu_taric unavailable"):
        graph.classify_cargo("shirts")


def test_invalid_classification_mode_is_explicit(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_MODE", "banana")
    with pytest.raises(ValueError, match="Invalid CLASSIFICATION_MODE"):
        graph.classify_cargo("shirts")
