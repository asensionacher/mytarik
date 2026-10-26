"""
LangGraph Classification Pipeline

Orchestrates the TariffAI pipeline as a LangGraph state machine:

    START → preprocess → retrieve → classify → assess → finalize → END
                                                 │
                                          (needs reasoning)
                                                 │
                                                 ▼
                                              reason ──→ finalize

Stages:
    1. preprocess  — regex cleanup of the raw cargo text (no LLM)
    2. retrieve    — Top-K HS candidates via hybrid search (no LLM)
    3. classify    — first LLM pass: pick a code and explain it
    4. assess      — decide whether the first pass is good enough
    5. reason      — second LLM pass over the HS catalogue; it either
                     settles the code or asks the human up to three
                     clarifying questions
    6. finalize    — stamp timing, questions, answers and status

The state machine provides:
- Clear node boundaries for debugging and logging
- Checkpointing support for auditing
- Clean separation of concerns (no LLM in stages 1-2)
"""

import logging
import time
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from app.cargo_preprocessor import preprocess_cargo_text
from app.hs_retriever import retrieve_candidates
from app.llm_classifier import classify_with_llm
from app.reasoning import assess_reasoning_need, reason_over_catalogue
from app.schemas import (
    ClarificationAnswer,
    HSCandidate,
    ClassificationResult,
    ResponseLanguage,
    TradeContext,
)
from app.config import CONFIDENCE_THRESHOLD


logger = logging.getLogger(__name__)


# ── LangGraph State ─────────────────────────────────────────────────────

class ClassificationState(TypedDict):
    """State that flows through the classification pipeline."""
    # Inputs
    raw_text: str
    language: ResponseLanguage
    trade: dict | None
    clarification_answers: list[dict]  # Serialized ClarificationAnswer dicts

    # Stage 1 output
    cleaned_text: str

    # Stage 2 output
    candidates: list[dict]  # Serialized HSCandidate dicts (LangGraph needs serializable state)

    # Stage 3 output
    result: dict | None  # Serialized ClassificationResult

    # Stage 4/5 output
    reasoning_reasons: list[str]  # Why the deep reasoning stage ran
    questions: list[dict]  # Serialized ClarificationQuestion dicts

    # Metadata
    start_time: float
    processing_time_ms: float


# ── Node Functions ──────────────────────────────────────────────────────

def preprocess_node(state: ClassificationState) -> dict:
    """
    Stage 1: Clean the raw cargo text.
    Pure Python/regex — no LLM, no network calls, sub-millisecond.
    """
    raw = state["raw_text"]
    cleaned = preprocess_cargo_text(raw)
    return {"cleaned_text": cleaned}


def retrieve_node(state: ClassificationState) -> dict:
    """
    Stage 2: Retrieve Top-K candidate HS codes.
    Qdrant semantic search + BM25 keyword search, fused via RRF.
    No LLM involved.
    """
    cleaned = state["cleaned_text"]
    candidates = retrieve_candidates(cleaned)

    # Serialize candidates for LangGraph state
    candidates_dicts = [c.model_dump() for c in candidates]
    return {"candidates": candidates_dicts}


def classify_node(state: ClassificationState) -> dict:
    """
    Stage 3: LLM classification.
    Single LLM call with cleaned text + candidates → first code + reasoning.
    """
    cleaned = state["cleaned_text"]
    raw = state["raw_text"]

    # Deserialize candidates
    candidates = [HSCandidate(**c) for c in state["candidates"]]
    trade_data = state.get("trade")
    trade = TradeContext(**trade_data) if trade_data else None

    result = classify_with_llm(
        cleaned, candidates,
        raw_text=raw,
        language=state["language"],
        trade=trade,
    )

    return {"result": result.model_dump()}


def assess_node(state: ClassificationState) -> dict:
    """
    Stage 4: Decide whether the first pass is good enough.

    The deep reasoning stage runs when the confidence is below the reasoning
    threshold, when the best candidates are tied, when the description is too
    short to classify, or when the broker already answered questions.
    """
    result = state.get("result") or {}
    candidates = [HSCandidate(**c) for c in state.get("candidates", [])]
    answers = [ClarificationAnswer(**a) for a in state.get("clarification_answers", [])]

    reasons = assess_reasoning_need(
        confidence=float(result.get("confidence", 0.0)),
        primary_code=result.get("primary_code"),
        candidates=candidates,
        cleaned_text=state.get("cleaned_text", ""),
        answers=answers,
    )
    return {"reasoning_reasons": reasons}


def route_after_assess(state: ClassificationState) -> str:
    """Route to the deep reasoning stage only when it is needed."""
    return "reason" if state.get("reasoning_reasons") else "finalize"


def reason_node(state: ClassificationState) -> dict:
    """
    Stage 5: Deep reasoning over the HS catalogue.

    The model sees the official descriptions of the candidate headings and
    their sibling subheadings, plus the broker's answers when there are any.
    It either settles on a code (refining the result) or asks the human the
    minimum number of clarifying questions.
    """
    cleaned = state["cleaned_text"]
    candidates = [HSCandidate(**c) for c in state["candidates"]]
    answers = [ClarificationAnswer(**a) for a in state.get("clarification_answers", [])]
    trade_data = state.get("trade")
    trade = TradeContext(**trade_data) if trade_data else None

    result = ClassificationResult(**state["result"])

    try:
        outcome = reason_over_catalogue(
            cleaned, candidates,
            raw_text=state["raw_text"],
            language=state["language"],
            trade=trade,
            answers=answers,
        )
    except Exception as exc:
        # A failure in the deep reasoning pass must not lose the first pass:
        # the broker still gets the proposal of the initial classification.
        logger.warning("Deep reasoning failed, keeping the first pass: %s", exc)
        return {"result": result.model_dump(), "questions": []}

    result.prompt_tokens += outcome.prompt_tokens
    result.output_tokens += outcome.output_tokens
    result.total_tokens += outcome.total_tokens
    if outcome.thinking:
        result.thinking = outcome.thinking

    if outcome.outcome == "questions":
        # The line cannot be settled yet: keep the tentative proposal from the
        # first pass and attach the questions the broker has to answer.
        result.clarifying_questions = outcome.questions
    else:
        result.primary_code = outcome.primary_code
        result.primary_description = outcome.primary_description
        result.confidence = outcome.confidence
        result.reasoning = outcome.reasoning
        if outcome.hierarchy:
            result.hierarchy = outcome.hierarchy
        if outcome.alternative_codes:
            result.alternative_codes = outcome.alternative_codes
        result.clarifying_questions = []

    return {
        "result": result.model_dump(),
        "questions": [q.model_dump() for q in outcome.questions],
    }


def finalize_node(state: ClassificationState) -> dict:
    """
    Stage 6: Stamp the outcome — timing, questions, answers and ambiguity.
    """
    result = ClassificationResult(**state["result"])
    result.clarification_answers = [
        ClarificationAnswer(**a) for a in state.get("clarification_answers", [])
    ]
    result.reasoning_reasons = list(state.get("reasoning_reasons", []))

    if result.clarifying_questions or result.primary_code is None:
        result.is_ambiguous = True
    else:
        result.is_ambiguous = result.confidence < CONFIDENCE_THRESHOLD

    elapsed = (time.time() - state.get("start_time", time.time())) * 1000
    result.processing_time_ms = elapsed

    return {"result": result.model_dump(), "processing_time_ms": elapsed}


# ── Build the Graph ─────────────────────────────────────────────────────

def build_classification_graph() -> StateGraph:
    """
    Construct the LangGraph state machine for HS code classification.
    """
    graph = StateGraph(ClassificationState)

    # Add nodes
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("classify", classify_node)
    graph.add_node("assess", assess_node)
    graph.add_node("reason", reason_node)
    graph.add_node("finalize", finalize_node)

    # Wire edges
    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "retrieve")
    graph.add_edge("retrieve", "classify")
    graph.add_edge("classify", "assess")

    # Conditional routing after the assessment
    graph.add_conditional_edges(
        "assess",
        route_after_assess,
        {
            "reason": "reason",
            "finalize": "finalize",
        }
    )
    graph.add_edge("reason", "finalize")
    graph.add_edge("finalize", END)

    return graph


# ── Compiled Graph (singleton) ──────────────────────────────────────────

_compiled_graph = None


def get_classification_graph():
    """Get or create the compiled classification graph."""
    global _compiled_graph
    if _compiled_graph is None:
        graph = build_classification_graph()
        _compiled_graph = graph.compile()
    return _compiled_graph


def classify_cargo(
    raw_text: str,
    language: ResponseLanguage = "en",
    trade: TradeContext | None = None,
    clarification_answers: list[ClarificationAnswer] | None = None,
) -> ClassificationResult:
    """
    Main entry point: classify a raw cargo description.

    This is the function the FastAPI endpoint calls. When `clarification_answers`
    are supplied, the deep reasoning stage runs again with the broker's answers
    in the transcript and settles the line (or asks the remaining questions).
    """
    graph = get_classification_graph()

    initial_state: ClassificationState = {
        "raw_text": raw_text,
        "language": language,
        "trade": trade.model_dump() if trade else None,
        "clarification_answers": [a.model_dump() for a in (clarification_answers or [])],
        "cleaned_text": "",
        "candidates": [],
        "result": None,
        "reasoning_reasons": [],
        "questions": [],
        "start_time": time.time(),
        "processing_time_ms": 0.0,
    }

    # Run the graph
    final_state = graph.invoke(initial_state)

    # Deserialize the result
    result_dict = final_state.get("result")
    if result_dict is None:
        raise RuntimeError("Classification pipeline produced no result")

    return ClassificationResult(**result_dict)
