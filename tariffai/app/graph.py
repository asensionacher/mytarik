"""Classification dispatcher: EU-first with an explicit legacy HS6 path.

The EU path (default) uses only ``eu_taric`` and returns CN8/TARIC10 codes.
The legacy HS6 LangGraph pipeline is imported only when
``CLASSIFICATION_MODE=legacy_hs6`` and is never used as a fallback.
"""

from __future__ import annotations

from app.schemas import (
    ClassificationResult,
    ClarificationAnswer,
    EUClassificationResult,
    ResponseLanguage,
    TradeContext,
)


def _mode() -> str:
    """Read the mode at call time so tests and deployments can change it."""
    from app.config import normalize_classification_mode

    return normalize_classification_mode()


def classify_cargo(
    raw_text: str,
    language: ResponseLanguage = "en",
    trade: TradeContext | None = None,
    clarification_answers: list[ClarificationAnswer] | None = None,
) -> EUClassificationResult | ClassificationResult:
    """Classify cargo using the selected pipeline.

    ``eu`` is the operational default. ``legacy_hs6`` exists only for explicit
    backwards-compatible use; an invalid mode or a failure in the selected
    pipeline raises and never falls back to the other pipeline.
    """
    mode = _mode()

    if mode == "eu":
        from app.eu_classifier import classify_eu_cargo

        return classify_eu_cargo(
            raw_text,
            language=language,
            trade=trade,
            clarification_answers=clarification_answers,
        )

    if mode == "legacy_hs6":
        from app.legacy_graph import classify_cargo as classify_legacy

        return classify_legacy(
            raw_text,
            language=language,
            trade=trade,
            clarification_answers=clarification_answers,
        )

    # normalize_classification_mode already rejects this, but keep the guard
    # explicit so a future change cannot introduce a silent fallback.
    raise ValueError(f"Unsupported CLASSIFICATION_MODE: {mode!r}")


def build_classification_graph():
    """Build the legacy graph only when explicitly requested."""
    from app.legacy_graph import build_classification_graph as build_legacy

    return build_legacy()


def get_classification_graph():
    """Return the compiled legacy graph, importing it lazily."""
    from app.legacy_graph import get_classification_graph as get_legacy

    return get_legacy()
