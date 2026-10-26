import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import graph, llm_classifier, main
from app.llm_provider import LLMResponse
from app.reasoning import reasoning_triggers
from app.schemas import ClassificationReasoning, ClassificationResult, HSCandidate


DESCRIPTION = "Men's knitted cotton polo shirts"


def candidate(code="610510", score=0.9):
    return HSCandidate(
        code=code, description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105",
        heading_description="Shirts", retrieval_score=score, retrieval_method="hybrid",
    )


def output(confidence=0.95, question=None, **extra):
    return LLMResponse(
        text=json.dumps({
            "primary_code": "610510", "primary_description": "Cotton shirts",
            "confidence": confidence, "reasoning": {},
            "hierarchy_descriptions": {"section": "", "chapter": "Prendas de punto", "heading": "Camisas"},
            "clarification_question": question, **extra,
        }),
        prompt_tokens=10, output_tokens=20, total_tokens=30,
    )


@pytest.mark.parametrize("text,confidence,scores,expected", [
    (DESCRIPTION, 0.7499, [0.9, 0.8], ["low_confidence"]),
    (DESCRIPTION, 0.75, [0.9, 0.8], []),
    (DESCRIPTION, 0.95, [0.9, 0.9], ["close_candidates"]),
    (DESCRIPTION, 0.95, [0.9, 0.899], ["close_candidates"]),
    (DESCRIPTION, 0.95, [0.9, 0.8989], []),
    ("camisas de algodón", 0.95, [0.9], ["short_description"]),
    ("shirts 100 cartons", 0.95, [0.9], ["short_description"]),
    ("cotton knitted mens polo", 0.95, [0.9], []),
])
def test_review_trigger_boundaries(text, confidence, scores, expected):
    result = ClassificationResult(
        input_text=text, cleaned_text=text, primary_code="610510", confidence=confidence,
        reasoning=ClassificationReasoning(
            section_reasoning="", chapter_reasoning="", heading_reasoning="", subheading_reasoning="",
        ),
    )
    candidates = [candidate(str(610510 + index), score) for index, score in enumerate(scores)]
    assert reasoning_triggers(text, candidates, result) == expected


@pytest.mark.parametrize("description,confidence,scores,trigger", [
    (DESCRIPTION, 0.74, [0.9, 0.8], "low_confidence"),
    (DESCRIPTION, 0.95, [0.9, 0.899], "close_candidates"),
    ("camisas", 0.95, [0.9, 0.8], "short_description"),
])
def test_review_expands_catalogue_and_returns_one_localized_question(
    monkeypatch, description, confidence, scores, trigger,
):
    retrieve = Mock(return_value=[candidate(score=scores[0]), candidate("610590", scores[1])])
    monkeypatch.setattr(graph, "retrieve_candidates", retrieve)
    provider = Mock()
    question = {"question": "¿Cuál es el material?", "options": ["Algodón", "Sintético"]}
    provider.complete.side_effect = [output(confidence), output(0.65, question)]
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)

    response = TestClient(main.app).post("/classify", json={"description": description, "language": "es"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ambiguous"
    result = data["result"]
    assert trigger in result["reasoning_triggers"]
    assert result["clarification_question"] == question
    assert result["total_tokens"] == 60
    assert result["processing_time_ms"] > 0
    assert retrieve.call_args.kwargs == {"top_k": 25}
    prompt = provider.complete.call_args.kwargs
    assert "CSV catalogue" in prompt["system"]
    assert "Spanish" in prompt["system"]
    assert "610510" in prompt["user"] and "610590" in prompt["user"]


def test_clear_description_does_not_require_second_call(monkeypatch):
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[candidate()]))
    provider = Mock()
    provider.complete.return_value = output()
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    result = graph.classify_cargo(DESCRIPTION)
    assert not result.is_ambiguous
    provider.complete.assert_called_once()


def test_review_can_select_a_new_catalogue_candidate_and_rejects_invented_alternatives(monkeypatch):
    retrieve = Mock(side_effect=[[candidate()], [candidate("610590")]])
    monkeypatch.setattr(graph, "retrieve_candidates", retrieve)
    provider = Mock()
    provider.complete.side_effect = [
        output(0.7),
        output(
            primary_code="610590",
            alternative_codes=[
                {"code": "610510", "description": "Cotton"},
                {"code": "999999", "description": "Invented"},
            ],
        ),
    ]
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    result = graph.classify_cargo(DESCRIPTION)
    assert result.primary_code == "610590"
    assert result.hierarchy["subheading"]["code"] == "610590"
    assert result.alternative_codes == [{"code": "610510", "description": "Cotton"}]
    assert not result.is_ambiguous


@pytest.mark.parametrize("count", [1, 2, 3])
def test_answers_resume_review_and_stop_at_three(monkeypatch, count):
    retrieve = Mock(return_value=[candidate()])
    monkeypatch.setattr(graph, "retrieve_candidates", retrieve)
    provider = Mock()
    provider.complete.return_value = output(
        0.6, {"question": "Next product fact?", "options": ["A", "B"]},
    )
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    answers = [{"question": f"Product fact {index}?", "answer": f"Fact {index}"} for index in range(count)]
    response = TestClient(main.app).post("/classify", json={
        "description": "shirts", "clarification_answers": answers,
        "trade": {"trade_mode": "export", "origin_country": "ES", "dispatch_country": "FR"},
    })
    result = response.json()["result"]
    assert response.json()["status"] == "ambiguous"
    assert result["clarification_answers"] == answers
    assert bool(result["clarification_question"]) is (count < 3)
    assert result["needs_human_review"] is (count == 3)
    provider.complete.assert_called_once()
    assert "Fact 0" in retrieve.call_args.args[0]
    prompt = provider.complete.call_args.kwargs
    assert "Fact 0" in prompt["user"]
    assert "Operation: export" in prompt["user"]


def test_answer_can_resolve_the_classification(monkeypatch):
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[candidate()]))
    provider = Mock()
    provider.complete.return_value = output()
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    response = TestClient(main.app).post("/classify", json={
        "description": "shirts",
        "clarification_answers": [{"question": "Material and construction?", "answer": "Knitted cotton"}],
    }).json()
    assert response["status"] == "classified"
    assert response["result"]["clarification_question"] is None
    assert response["result"]["needs_human_review"] is False


def test_model_cannot_ask_fourth_question_even_with_high_confidence(monkeypatch):
    provider = Mock()
    provider.complete.return_value = output(0.99, {"question": "Fourth?", "options": []})
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    from app.schemas import ClarificationAnswer
    result = llm_classifier.classify_with_llm(
        "shirts", [candidate()], review=True,
        clarification_answers=[ClarificationAnswer(question=f"Q{i}", answer="Unknown") for i in range(3)],
    )
    assert result.clarification_question is None
    assert result.is_ambiguous and result.needs_human_review


def test_low_confidence_without_model_question_has_non_repeating_fallback(monkeypatch):
    provider = Mock()
    provider.complete.return_value = output(0.6)
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    from app.schemas import ClarificationAnswer
    answers = []
    for _ in range(3):
        result = llm_classifier.classify_with_llm(
            "shirts", [candidate()], review=True, clarification_answers=answers,
        )
        question = result.clarification_question.question
        assert question not in [a.question for a in answers]
        answers.append(ClarificationAnswer(question=question, answer="Unknown"))
    result = llm_classifier.classify_with_llm(
        "shirts", [candidate()], review=True, clarification_answers=answers,
    )
    assert result.clarification_question is None
    assert result.needs_human_review


def test_repeated_model_question_does_not_silently_resolve_ambiguity(monkeypatch):
    from app.schemas import ClarificationAnswer

    provider = Mock()
    provider.complete.return_value = output(0.99, {"question": "Material?", "options": []})
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    result = llm_classifier.classify_with_llm(
        "shirts", [candidate()], review=True,
        clarification_answers=[ClarificationAnswer(question="Material?", answer="Unknown")],
    )
    assert result.is_ambiguous
    assert result.clarification_question is not None
    assert result.clarification_question.question != "Material?"


@pytest.mark.parametrize("answers", [
    [{"question": "Q", "answer": "A"}] * 4,
    [{"question": "Q", "answer": "  "}],
    [{"question": "", "answer": "A"}],
    [{"question": "Q", "answer": "A", "provider": "other"}],
])
def test_invalid_answer_history_is_rejected(answers):
    response = TestClient(main.app).post("/classify", json={
        "description": "shirts", "clarification_answers": answers,
    })
    assert response.status_code == 422
