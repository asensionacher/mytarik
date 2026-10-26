"""Deterministic triggers for a catalogue-grounded disambiguation review."""

import re

from app.schemas import ClassificationResult, HSCandidate


_STOP_WORDS = {
    "a", "an", "the", "of", "for", "with", "and", "in", "de", "del",
    "el", "la", "los", "las", "un", "una", "y", "con", "para", "en",
}


def reasoning_triggers(
    text: str, candidates: list[HSCandidate], result: ClassificationResult,
) -> list[str]:
    triggers = []
    if result.confidence < 0.75:
        triggers.append("low_confidence")
    scores = sorted(
        {candidate.code: candidate.retrieval_score for candidate in candidates}.values(),
        reverse=True,
    )
    if len(scores) > 1 and scores[0] - scores[1] <= 0.001 + 1e-9:
        triggers.append("close_candidates")
    words = [
        word for word in re.findall(r"[^\W\d_]+", text.lower())
        if word not in _STOP_WORDS
    ]
    if len(words) < 4:
        triggers.append("short_description")
    if result.primary_code is None:
        triggers.append("missing_code")
    return triggers
