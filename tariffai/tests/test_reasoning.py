"""
Tests for the deep reasoning stage (Stage 4/5) and the human-in-the-loop flow.

Conventions follow `test_azure.py`: no fixtures, everything is monkeypatched.
"""

import json
from unittest.mock import Mock

import pytest

from app import hs_catalogue, llm_provider, reasoning
from app.schemas import ClarificationAnswer, HSCandidate


DESCRIPTION = "500 cartons of men's cotton polo shirts, 100% cotton, knitted"

CANDIDATE = HSCandidate(
    code="620462", description="Women's or girls' cotton trousers", chapter_code="62",
    chapter_description="Apparel, other than knitted or crocheted", heading_code="6204",
    heading_description="Women's or girls' suits, ensembles, jackets, blouses, dresses",
    section="XI", section_description="Textiles and textile articles",
    retrieval_score=0.8, retrieval_method="hybrid",
)

SIBLING = HSCandidate(
    code="620463", description="Women's or girls' trousers of other textile materials",
    chapter_code="62", chapter_description="Apparel, other than knitted or crocheted",
    heading_code="6204",
    heading_description="Women's or girls' suits, ensembles, jackets, blouses, dresses",
    section="XI", section_description="Textiles and textile articles",
    retrieval_score=0.7995, retrieval_method="hybrid",
)


def _catalogue_entry(code: str, description: str) -> dict:
    return {
        "code": code,
        "description": description,
        "chapter_code": "62",
        "chapter_description": "Apparel, other than knitted or crocheted",
        "heading_code": "6204",
        "heading_description": "Women's or girls' suits, ensembles, jackets, blouses, dresses",
        "section": "XI",
        "section_description": "Textiles and textile articles",
    }


def _install_catalogue(monkeypatch) -> None:
    """Replace the Qdrant-backed catalogue with an in-memory one."""
    entries = [
        _catalogue_entry("620411", "Women's or girls' suits of wool"),
        _catalogue_entry("620462", "Women's or girls' cotton trousers"),
        _catalogue_entry("620463", "Women's or girls' trousers of other textile materials"),
    ]
    monkeypatch.setattr(hs_catalogue, "_catalogue", {e["code"]: e for e in entries})
    monkeypatch.setattr(
        hs_catalogue, "_siblings_by_heading",
        {"6204": entries},
    )


def _provider(text: str, **kwargs) -> Mock:
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=text, **kwargs)
    return provider


# ── Trigger assessment ──────────────────────────────────────────────────

def test_low_confidence_triggers_the_reasoning_stage():
    reasons = reasoning.assess_reasoning_need(
        confidence=0.6, primary_code="620462", candidates=[CANDIDATE],
        cleaned_text=DESCRIPTION,
    )
    assert reasoning.REASON_LOW_CONFIDENCE in reasons


def test_a_confident_first_pass_does_not_trigger_the_reasoning_stage():
    reasons = reasoning.assess_reasoning_need(
        confidence=0.9, primary_code="620462", candidates=[CANDIDATE],
        cleaned_text=DESCRIPTION,
    )
    assert reasons == []


def test_tied_candidates_trigger_the_reasoning_stage():
    reasons = reasoning.assess_reasoning_need(
        confidence=0.9, primary_code="620462", candidates=[CANDIDATE, SIBLING],
        cleaned_text=DESCRIPTION,
    )
    assert reasoning.REASON_TIED_CANDIDATES in reasons


def test_a_clear_margin_between_candidates_does_not_trigger_the_reasoning_stage():
    clear = SIBLING.model_copy(update={"retrieval_score": 0.7})
    reasons = reasoning.assess_reasoning_need(
        confidence=0.9, primary_code="620462", candidates=[CANDIDATE, clear],
        cleaned_text=DESCRIPTION,
    )
    assert reasoning.REASON_TIED_CANDIDATES not in reasons


def test_a_short_description_triggers_the_reasoning_stage():
    assert reasoning.is_short_query("zapatillas") is True
    reasons = reasoning.assess_reasoning_need(
        confidence=0.9, primary_code="620462", candidates=[CANDIDATE],
        cleaned_text="zapatillas",
    )
    assert reasoning.REASON_SHORT_QUERY in reasons


def test_broker_answers_always_trigger_the_reasoning_stage():
    answers = [ClarificationAnswer(question_id="q1", question="¿Algodón?", answer="Sí")]
    reasons = reasoning.assess_reasoning_need(
        confidence=0.95, primary_code="620462", candidates=[CANDIDATE],
        cleaned_text=DESCRIPTION, answers=answers,
    )
    assert reasons == [reasoning.REASON_HUMAN_ANSWERS]


# ── Deep reasoning ──────────────────────────────────────────────────────

def test_reasoning_settles_the_code_over_the_catalogue(monkeypatch):
    _install_catalogue(monkeypatch)
    provider = _provider(json.dumps({
        "outcome": "code",
        "primary_code": "620462",
        "primary_description": "Women's or girls' cotton trousers",
        "confidence": 0.88,
        "reasoning": {"subheading_reasoning": "Cotton trousers."},
        "alternative_codes": [],
    }), prompt_tokens=100, output_tokens=50, total_tokens=150)
    monkeypatch.setattr(reasoning, "get_provider", lambda: provider)

    outcome = reasoning.reason_over_catalogue(
        DESCRIPTION, [CANDIDATE, SIBLING], raw_text=DESCRIPTION,
    )

    assert outcome.outcome == "code"
    assert outcome.primary_code == "620462"
    assert outcome.confidence == 0.88
    assert outcome.questions == []
    assert outcome.hierarchy["heading"]["code"] == "6204"
    assert outcome.hierarchy["subheading"]["code"] == "620462"

    prompt = provider.complete.call_args.kwargs["user"]
    # The model reasons over the whole heading, not only over the retrieved codes.
    assert "620463" in prompt
    assert "Subheadings under this heading" in prompt
    assert (outcome.prompt_tokens, outcome.output_tokens, outcome.total_tokens) == (100, 50, 150)


def test_reasoning_asks_the_broker_when_a_detail_is_missing(monkeypatch):
    _install_catalogue(monkeypatch)
    provider = _provider(json.dumps({
        "outcome": "questions",
        "primary_code": None,
        "confidence": 0.4,
        "questions": [{
            "id": "q1",
            "question": "¿De qué tejido son los pantalones?",
            "hint": "620462 y 620463 sólo se diferencian por el material.",
            "allow_free_text": True,
            "options": [
                {"value": "cotton", "label": "Algodón", "code": "620462"},
                {"value": "other", "label": "Otra materia textil", "code": "620463"},
            ],
        }],
    }))
    monkeypatch.setattr(reasoning, "get_provider", lambda: provider)

    outcome = reasoning.reason_over_catalogue(
        "pantalon", [CANDIDATE, SIBLING], raw_text="pantalon",
    )

    assert outcome.outcome == "questions"
    assert outcome.primary_code is None
    assert len(outcome.questions) == 1
    question = outcome.questions[0]
    assert question.question == "¿De qué tejido son los pantalones?"
    assert question.hint.startswith("620462")
    assert [option.code for option in question.options] == ["620462", "620463"]
    assert question.options[0].label == "Algodón"


def test_questions_are_capped_by_the_remaining_budget(monkeypatch):
    _install_catalogue(monkeypatch)
    provider = _provider(json.dumps({
        "outcome": "questions",
        "questions": [
            {"question": "Primera"},
            {"question": "Segunda"},
            {"question": "Tercera"},
        ],
    }))
    monkeypatch.setattr(reasoning, "get_provider", lambda: provider)

    outcome = reasoning.reason_over_catalogue("pantalon", [CANDIDATE])

    assert len(outcome.questions) == 3
    assert outcome.questions[0].id == "q1"


def test_only_one_question_is_left_after_two_answers(monkeypatch):
    _install_catalogue(monkeypatch)
    provider = _provider(json.dumps({
        "outcome": "questions",
        "questions": [{"question": "Primera"}, {"question": "Segunda"}],
    }))
    monkeypatch.setattr(reasoning, "get_provider", lambda: provider)

    answers = [
        ClarificationAnswer(question_id="q1", question="¿Material?", answer="Algodón"),
        ClarificationAnswer(question_id="q2", question="¿Uso?", answer="Diaria"),
    ]
    outcome = reasoning.reason_over_catalogue(
        "pantalon", [CANDIDATE], answers=answers,
    )

    assert len(outcome.questions) == 1
    assert "do not ask again what is answered" in provider.complete.call_args.kwargs["user"]


def test_a_question_without_options_always_allows_free_text(monkeypatch):
    _install_catalogue(monkeypatch)
    provider = _provider(json.dumps({
        "outcome": "questions",
        "questions": [{"question": "¿Uso?", "allow_free_text": False}],
    }))
    monkeypatch.setattr(reasoning, "get_provider", lambda: provider)

    outcome = reasoning.reason_over_catalogue("pantalon", [CANDIDATE])

    assert outcome.questions[0].allow_free_text is True


def test_a_code_outside_the_catalogue_is_discarded(monkeypatch):
    _install_catalogue(monkeypatch)
    provider = _provider(json.dumps({
        "outcome": "code",
        "primary_code": "999999",
        "confidence": 0.9,
    }))
    monkeypatch.setattr(reasoning, "get_provider", lambda: provider)

    outcome = reasoning.reason_over_catalogue(DESCRIPTION, [CANDIDATE])

    assert outcome.primary_code is None


# ── Routes ──────────────────────────────────────────────────────────────

def test_route_asks_for_clarification_when_the_reasoning_needs_it(monkeypatch):
    from fastapi.testclient import TestClient

    from app import graph, llm_classifier, main

    _install_catalogue(monkeypatch)
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[CANDIDATE, SIBLING]))
    monkeypatch.setattr(
        llm_classifier, "get_provider",
        lambda: _provider(json.dumps({
            "primary_code": "620462", "confidence": 0.55, "reasoning": {},
        })),
    )
    monkeypatch.setattr(
        reasoning, "get_provider",
        lambda: _provider(json.dumps({
            "outcome": "questions",
            "questions": [{
                "id": "q1",
                "question": "¿De qué tejido son los pantalones?",
                "options": [{"value": "cotton", "label": "Algodón", "code": "620462"}],
            }],
        })),
    )

    client = TestClient(main.app)
    response = client.post("/classify", json={"description": DESCRIPTION})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    result = body["result"]
    assert result["is_ambiguous"] is True
    assert len(result["clarifying_questions"]) == 1
    assert result["clarifying_questions"][0]["question"] == "¿De qué tejido son los pantalones?"
    assert result["clarifying_questions"][0]["options"][0]["code"] == "620462"
    assert reasoning.REASON_LOW_CONFIDENCE in result["reasoning_reasons"]
    assert reasoning.REASON_TIED_CANDIDATES in result["reasoning_reasons"]


def test_route_reasons_again_with_the_broker_answers(monkeypatch):
    from fastapi.testclient import TestClient

    from app import graph, llm_classifier, main

    _install_catalogue(monkeypatch)
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[CANDIDATE, SIBLING]))
    monkeypatch.setattr(
        llm_classifier, "get_provider",
        lambda: _provider(json.dumps({
            "primary_code": "620462", "confidence": 0.55, "reasoning": {},
        })),
    )
    monkeypatch.setattr(
        reasoning, "get_provider",
        lambda: _provider(json.dumps({
            "outcome": "code",
            "primary_code": "620462",
            "primary_description": "Women's or girls' cotton trousers",
            "confidence": 0.9,
            "reasoning": {"subheading_reasoning": "Cotton trousers."},
        })),
    )

    client = TestClient(main.app)
    response = client.post("/classify", json={
        "description": DESCRIPTION,
        "clarification_answers": [{
            "question_id": "q1",
            "question": "¿De qué tejido son los pantalones?",
            "answer": "Algodón",
        }],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "classified"
    result = body["result"]
    assert result["primary_code"] == "620462"
    assert result["confidence"] == 0.9
    assert result["clarifying_questions"] == []
    assert result["clarification_answers"][0]["answer"] == "Algodón"
    assert reasoning.REASON_HUMAN_ANSWERS in result["reasoning_reasons"]


def test_route_keeps_the_first_pass_when_the_reasoning_fails(monkeypatch):
    from fastapi.testclient import TestClient

    from app import graph, llm_classifier, main

    _install_catalogue(monkeypatch)
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[CANDIDATE]))
    monkeypatch.setattr(
        llm_classifier, "get_provider",
        lambda: _provider(json.dumps({
            "primary_code": "620462", "confidence": 0.5, "reasoning": {},
        })),
    )
    monkeypatch.setattr(
        reasoning, "get_provider",
        Mock(side_effect=RuntimeError("Azure Foundry devolvió una respuesta vacía")),
    )

    client = TestClient(main.app)
    response = client.post("/classify", json={"description": DESCRIPTION})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ambiguous"
    assert body["result"]["primary_code"] == "620462"
    assert body["result"]["clarifying_questions"] == []


def test_route_reports_the_answers_transcript_to_the_model(monkeypatch):
    from fastapi.testclient import TestClient

    from app import graph, llm_classifier, main

    _install_catalogue(monkeypatch)
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[CANDIDATE]))
    monkeypatch.setattr(
        llm_classifier, "get_provider",
        lambda: _provider(json.dumps({
            "primary_code": "620462", "confidence": 0.95, "reasoning": {},
        })),
    )
    reasoning_provider = _provider(json.dumps({
        "outcome": "code", "primary_code": "620462", "confidence": 0.95,
    }))
    monkeypatch.setattr(reasoning, "get_provider", lambda: reasoning_provider)

    client = TestClient(main.app)
    client.post("/classify", json={
        "description": DESCRIPTION,
        "clarification_answers": [{
            "question_id": "q1",
            "question": "¿De qué tejido son los pantalones?",
            "answer": "Algodón",
        }],
    })

    prompt = reasoning_provider.complete.call_args.kwargs["user"]
    assert "¿De qué tejido son los pantalones?" in prompt
    assert "Algodón" in prompt


@pytest.mark.parametrize("payload", [
    {"description": DESCRIPTION, "clarification_answers": [{"answer": "a", "question_id": "q1"}] * 4},
])
def test_route_rejects_more_answers_than_the_question_budget(payload):
    from fastapi.testclient import TestClient

    from app import main

    client = TestClient(main.app)
    response = client.post("/classify", json=payload)
    assert response.status_code == 422
