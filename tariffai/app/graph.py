"""
LangGraph Classification Pipeline

Orchestrates the 3-stage TariffAI pipeline as a LangGraph state machine:

    START → preprocess → retrieve → classify → [disambiguation review] → END

Review low confidence, close retrieval candidates and short descriptions.
Human answers remain request-local and resume catalogue-grounded classification.
"""

import time
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END

from app.cargo_preprocessor import preprocess_cargo_text
from app.hs_retriever import retrieve_candidates
from app.llm_classifier import classify_with_llm
from app.schemas import HSCandidate, ClassificationResult, ResponseLanguage, TradeContext, ClarificationAnswer
from app.reasoning import reasoning_triggers


# ── LangGraph State ─────────────────────────────────────────────────────

class ClassificationState(TypedDict):
    """State that flows through the classification pipeline."""
    # Inputs
    raw_text: str
    language: ResponseLanguage
    trade: dict | None
    clarification_answers: list[dict]

    # Stage 1 output
    cleaned_text: str

    # Stage 2 output
    candidates: list[dict]  # Serialized HSCandidate dicts (LangGraph needs serializable state)

    # Stage 3 output
    result: dict | None  # Serialized ClassificationResult

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
    return {
        "cleaned_text": cleaned,
        "start_time": time.time(),
    }


def retrieve_node(state: ClassificationState) -> dict:
    """
    Stage 2: Retrieve Top-K candidate HS codes.
    Qdrant semantic search + BM25 keyword search, fused via RRF.
    No LLM involved.
    """
    cleaned = state["cleaned_text"]
    answers = state.get("clarification_answers", [])
    query = cleaned + "".join(f"\n{a['question']}: {a['answer']}" for a in answers)
    candidates = retrieve_candidates(query, top_k=25) if answers else retrieve_candidates(query)

    # Serialize candidates for LangGraph state
    candidates_dicts = [c.model_dump() for c in candidates]
    return {"candidates": candidates_dicts}


def classify_node(state: ClassificationState) -> dict:
    """
    Stage 3: Classify, or resume a review using the human's answers.
    """
    cleaned = state["cleaned_text"]
    raw = state["raw_text"]

    # Deserialize candidates
    candidates = [HSCandidate(**c) for c in state["candidates"]]
    trade_data = state.get("trade")
    trade = TradeContext(**trade_data) if trade_data else None
    answers = [ClarificationAnswer(**a) for a in state.get("clarification_answers", [])]

    result = classify_with_llm(
        cleaned, candidates,
        raw_text=raw,
        language=state["language"],
        trade=trade,
        clarification_answers=answers,
        review=bool(answers),
    )
    result.reasoning_triggers = reasoning_triggers(cleaned, candidates, result)
    if state.get("clarification_answers"):
        result.reasoning_triggers.append("human_answers")

    # Calculate total processing time
    elapsed = (time.time() - state.get("start_time", time.time())) * 1000
    result.processing_time_ms = elapsed

    return {"result": result.model_dump(), "processing_time_ms": elapsed}


# ── Conditional Edge ────────────────────────────────────────────────────

def check_ambiguity(state: ClassificationState) -> str:
    """
    Start a second review only for initial classifications requiring it.
    """
    result = state.get("result")
    if result and result.get("reasoning_triggers") and not state.get("clarification_answers"):
        return "ambiguous"
    return "done"


def ambiguous_output_node(state: ClassificationState) -> dict:
    """Re-evaluate a broader set of entries from the CSV-backed catalogue."""
    answers = [ClarificationAnswer(**a) for a in state.get("clarification_answers", [])]
    query = state["cleaned_text"] + "".join(f"\n{a.question}: {a.answer}" for a in answers)
    expanded = retrieve_candidates(query, top_k=25)
    candidates = {c["code"]: HSCandidate(**c) for c in state["candidates"]}
    candidates.update({c.code: c for c in expanded})
    previous = ClassificationResult(**state["result"])
    trade = TradeContext(**state["trade"]) if state.get("trade") else None
    result = classify_with_llm(
        state["cleaned_text"], list(candidates.values()),
        raw_text=state["raw_text"], language=state["language"], trade=trade,
        clarification_answers=answers, review=True,
    )
    result.reasoning_triggers = previous.reasoning_triggers
    for field in ("prompt_tokens", "output_tokens", "total_tokens"):
        setattr(result, field, getattr(result, field) + getattr(previous, field))
    result.processing_time_ms = (time.time() - state["start_time"]) * 1000
    return {"result": result.model_dump(), "processing_time_ms": result.processing_time_ms}


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
    graph.add_node("ambiguous_output", ambiguous_output_node)

    # Wire edges
    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "retrieve")
    graph.add_edge("retrieve", "classify")

    # Conditional routing after classification
    graph.add_conditional_edges(
        "classify",
        check_ambiguity,
        {
            "done": END,
            "ambiguous": "ambiguous_output",
        }
    )
    graph.add_edge("ambiguous_output", END)

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

    This is the function the FastAPI endpoint calls.
    """
    graph = get_classification_graph()

    initial_state: ClassificationState = {
        "raw_text": raw_text,
        "language": language,
        "trade": trade.model_dump() if trade else None,
        "clarification_answers": [a.model_dump() for a in clarification_answers or []],
        "cleaned_text": "",
        "candidates": [],
        "result": None,
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
