"""
Stage 4: Deep reasoning over the HS catalogue (LLM) + human in the loop.

The first LLM pass only sees the Top-K candidates returned by retrieval. That
is not enough to settle three very common situations:

1. **Low confidence** (< 0.75): the model is not sure, so it must reason
   again over the official HS descriptions before proposing a code.
2. **Tied candidates**: two or more codes are separated by a razor-thin
   margin (0.1%), so retrieval cannot pick one.
3. **Very short description**: there is not enough information to classify at
   all (e.g. "zapatillas").

This module answers those cases with a second LLM call that receives the
*catalogue view* of the candidate headings (every 6-digit subheading under
them, straight from the ingested Harmonized System CSV) and may:

- resolve the line to a single code with a full reasoning chain, or
- ask the human up to `MAX_CLARIFYING_QUESTIONS` clarifying questions, each
  answerable with buttons and/or free text.

A human is always in front of the screen, so asking is a first-class outcome:
the model is explicitly told to prefer a question over a guess whenever a
single missing attribute is what separates two plausible codes.
"""

import logging
from dataclasses import dataclass, field

from app.config import (
    MAX_CLARIFYING_QUESTIONS,
    MIN_QUERY_CHARS,
    MIN_QUERY_WORDS,
    REASONING_CONFIDENCE_THRESHOLD,
    TIE_MARGIN_THRESHOLD,
)
from app.llm_provider import extract_json, get_provider
from app.schemas import (
    ClarificationAnswer,
    ClarificationOption,
    ClarificationQuestion,
    ClassificationReasoning,
    HSCandidate,
    ResponseLanguage,
    TradeContext,
)
from app.translation import translate_from_en

logger = logging.getLogger(__name__)


# ── Reasons that trigger the deep reasoning stage ───────────────────────
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_TIED_CANDIDATES = "tied_candidates"
REASON_SHORT_QUERY = "short_query"
REASON_HUMAN_ANSWERS = "human_answers"


# ── Prompts ─────────────────────────────────────────────────────────────
REASONING_SYSTEM_PROMPT = """You are TariffAI, an expert customs tariff classification specialist.
You decide the 6-digit Harmonized System (HS) code of a cargo description.

You receive:
- the cargo description,
- the official HS descriptions of the candidate codes and of every subheading
  under their headings (this is the tariff catalogue),
- optionally, clarifying questions that a human broker already answered.

Your output MUST be a single JSON object with this exact schema (no extra fields, no markdown fences):

{
    "outcome": "code" | "questions",
    "primary_code": "620462",
    "primary_description": "The official HS description of the selected code",
    "hierarchy_descriptions": {
        "section": "Description of the selected code's section",
        "chapter": "Description of the selected code's chapter",
        "heading": "Description of the selected code's heading"
    },
    "confidence": 0.86,
    "reasoning": {
        "section_reasoning": "Why this section...",
        "chapter_reasoning": "Why this chapter...",
        "heading_reasoning": "Why this heading...",
        "subheading_reasoning": "Why this specific subheading...",
        "key_factors": ["factor1", "factor2"]
    },
    "alternative_codes": [
        {
            "code": "620463",
            "description": "Alternative description",
            "why_not": "Why this was not selected",
            "trade_off": "What would make this the correct choice instead"
        }
    ],
    "questions": [
        {
            "id": "q1",
            "question": "Short question for the broker",
            "hint": "Why the answer is needed",
            "allow_free_text": true,
            "options": [
                {"value": "cotton", "label": "Cotton", "code": "620462", "description": "Optional extra context"}
            ]
        }
    ]
}

Decision rules:
- "outcome": "code" when the description plus the catalogue let you settle on one code.
- "outcome": "questions" when a specific missing attribute (material, form, use,
  composition, packaging, gender, ...) is what separates two plausible codes.
  In that case "primary_code" MUST be null and "questions" MUST be non-empty.
- Never ask for information that is already in the description or in the answers.
- Ask at most {max_questions} questions. Fewer, well-chosen questions are better.
- Every question must be answerable by picking one of the offered options, by
  typing a free answer, or both. Options must be mutually exclusive and, when
  they point to a code, they MUST carry that "code".
- Use "questions" only when the answer is genuinely obtainable from the human.
  If the catalogue already answers it, do not ask.
- When the broker's answers resolve the line, use "outcome": "code" and ignore
  the remaining ambiguity.

Confidence calibration:
  0.9-1.0: Clear, unambiguous match
  0.75-0.89: Strong match, minor ambiguity only
  0.5-0.74: Ambiguous — multiple valid interpretations
  Below 0.5: Insufficient information to classify reliably

Respond with ONLY the JSON object. No markdown fences, no preamble, no postamble."""


REASONING_USER_TEMPLATE = """## Cargo Description (cleaned)
{cleaned_text}

## HS Catalogue View (official descriptions)
{catalogue_context}

{trade_context}{answers_context}
## Task
Walk the catalogue top-down (SECTION → CHAPTER → HEADING → SUBHEADING), decide
whether the description settles on a single code, and either propose it with a
full reasoning chain or ask the broker the minimum number of clarifying
questions needed to settle it.

Respond with ONLY the JSON object."""


# ── Outcome ─────────────────────────────────────────────────────────────

@dataclass
class ReasoningOutcome:
    """Result of the deep reasoning stage."""
    outcome: str = "code"
    primary_code: str | None = None
    primary_description: str = ""
    confidence: float = 0.0
    reasoning: ClassificationReasoning = field(
        default_factory=lambda: ClassificationReasoning(
            section_reasoning="", chapter_reasoning="",
            heading_reasoning="", subheading_reasoning="",
        )
    )
    hierarchy: dict = field(default_factory=dict)
    alternative_codes: list[dict] = field(default_factory=list)
    questions: list[ClarificationQuestion] = field(default_factory=list)
    thinking: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


# ── Trigger assessment ──────────────────────────────────────────────────

def is_short_query(cleaned_text: str) -> bool:
    """True when the description carries too little information to classify."""
    text = (cleaned_text or "").strip()
    if not text:
        return True
    if len(text) < MIN_QUERY_CHARS:
        return True
    return len(text.split()) < MIN_QUERY_WORDS


def has_tied_candidates(candidates: list[HSCandidate]) -> bool:
    """
    True when the two best candidates are separated by a margin of 0.1% or less
    (relative to the best score), i.e. retrieval cannot pick one of them.
    """
    if len(candidates) < 2:
        return False
    top = candidates[0].retrieval_score
    second = candidates[1].retrieval_score
    if top <= 0:
        return second >= top
    return (top - second) / top <= TIE_MARGIN_THRESHOLD


def assess_reasoning_need(
    confidence: float,
    primary_code: str | None,
    candidates: list[HSCandidate],
    cleaned_text: str,
    answers: list[ClarificationAnswer] | None = None,
) -> list[str]:
    """
    Decide whether the deep reasoning stage has to run, and why.

    Returns the list of reasons (empty when the first pass is good enough).
    """
    reasons: list[str] = []

    if answers:
        reasons.append(REASON_HUMAN_ANSWERS)
    if confidence < REASONING_CONFIDENCE_THRESHOLD or not primary_code:
        reasons.append(REASON_LOW_CONFIDENCE)
    if has_tied_candidates(candidates):
        reasons.append(REASON_TIED_CANDIDATES)
    if is_short_query(cleaned_text):
        reasons.append(REASON_SHORT_QUERY)

    return reasons


# ── Prompt helpers ──────────────────────────────────────────────────────

def _format_trade_context(trade: TradeContext | None) -> str:
    if trade is None:
        return ""
    return (
        "## Trade Context\n"
        f"Operation: {trade.trade_mode}\n"
        f"Country of origin (ISO 3166-1 alpha-2): {trade.origin_country}\n"
        f"Country of dispatch (ISO 3166-1 alpha-2): {trade.dispatch_country}\n"
        "Use this context only to resolve ambiguities in the product identity.\n"
    )


def _format_answers(answers: list[ClarificationAnswer]) -> str:
    if not answers:
        return ""
    lines = ["## Clarifying Questions Already Answered by the Broker"]
    for index, answer in enumerate(answers, 1):
        question = (answer.question or "").strip() or "(pregunta sin texto)"
        lines.append(f"{index}. Q: {question}\n   A: {answer.answer}")
    lines.append("Use these answers to settle the classification; do not ask again what is answered.")
    return "\n".join(lines) + "\n"


def _format_catalogue_context(candidates: list[HSCandidate]) -> str:
    from app.hs_catalogue import build_catalogue_context

    context = build_catalogue_context(candidates)
    if context.strip():
        return context
    lines = []
    for candidate in candidates:
        lines.append(
            f"- {candidate.code}: {candidate.description} "
            f"(heading {candidate.heading_code}: {candidate.heading_description}, "
            f"chapter {candidate.chapter_code}: {candidate.chapter_description})"
        )
    return "\n".join(lines)


# ── Response parsing ────────────────────────────────────────────────────

def _parse_questions(raw: object, max_questions: int) -> list[ClarificationQuestion]:
    """Normalize the questions returned by the model, enforcing the budget."""
    if not isinstance(raw, list):
        return []

    questions: list[ClarificationQuestion] = []
    for index, item in enumerate(raw[:max_questions], 1):
        if not isinstance(item, dict):
            continue
        text = item.get("question")
        if not isinstance(text, str) or not text.strip():
            continue

        options: list[ClarificationOption] = []
        raw_options = item.get("options")
        if isinstance(raw_options, list):
            for raw_option in raw_options:
                if not isinstance(raw_option, dict):
                    continue
                value = raw_option.get("value")
                if not isinstance(value, str) or not value.strip():
                    continue
                code = raw_option.get("code")
                options.append(ClarificationOption(
                    value=value.strip(),
                    label=(raw_option.get("label") or value).strip(),
                    code=code if isinstance(code, str) and len(code) == 6 and code.isdigit() else None,
                    description=raw_option.get("description") or None,
                ))

        allow_free_text = item.get("allow_free_text")
        if not isinstance(allow_free_text, bool):
            allow_free_text = True
        if not options and not allow_free_text:
            # Never leave a question the human cannot answer.
            allow_free_text = True

        identifier = item.get("id")
        questions.append(ClarificationQuestion(
            id=identifier.strip() if isinstance(identifier, str) and identifier.strip() else f"q{index}",
            question=text.strip(),
            hint=(item.get("hint") or "").strip() if isinstance(item.get("hint"), str) else "",
            allow_free_text=allow_free_text,
            options=options,
        ))
    return questions


def _hierarchy_from_entry(entry: dict) -> dict:
    return {
        "section": {"code": entry.get("section", ""), "description": entry.get("section_description", "")},
        "chapter": {"code": entry.get("chapter_code", ""), "description": entry.get("chapter_description", "")},
        "heading": {"code": entry.get("heading_code", ""), "description": entry.get("heading_description", "")},
        "subheading": {"code": entry.get("code", ""), "description": entry.get("description", "")},
    }


def _entry_for_code(code: str, candidates: list[HSCandidate]) -> dict | None:
    """Find the catalogue entry for a code, first among the candidates."""
    for candidate in candidates:
        if candidate.code == code:
            return {
                "code": candidate.code,
                "description": candidate.description,
                "chapter_code": candidate.chapter_code,
                "chapter_description": candidate.chapter_description,
                "heading_code": candidate.heading_code,
                "heading_description": candidate.heading_description,
                "section": candidate.section,
                "section_description": candidate.section_description,
            }
    from app.hs_catalogue import get_entry

    return get_entry(code)


# ── Deep reasoning ──────────────────────────────────────────────────────

def reason_over_catalogue(
    cleaned_text: str,
    candidates: list[HSCandidate],
    raw_text: str = "",
    language: ResponseLanguage = "en",
    trade: TradeContext | None = None,
    answers: list[ClarificationAnswer] | None = None,
    max_questions: int = MAX_CLARIFYING_QUESTIONS,
) -> ReasoningOutcome:
    """
    Reason over the HS catalogue to settle the classification, or ask the
    human the questions needed to settle it.

    Args:
        cleaned_text: Preprocessed cargo description (Stage 1 output)
        candidates: Top-K candidate HS codes (Stage 2 output)
        raw_text: Original raw text (kept for the record)
        language: Language for descriptions, reasoning and questions
        trade: Commercial context for disambiguation
        answers: Answers already given by the human in a previous round
        max_questions: Remaining budget of clarifying questions

    Returns:
        ReasoningOutcome with either a resolved code or clarifying questions.
    """
    llm = get_provider()
    answers = answers or []
    budget = max(0, max_questions - len(answers))

    language_name = {"es": "Spanish", "en": "English"}[language]
    system = (
        f"{REASONING_SYSTEM_PROMPT.replace('{max_questions}', str(budget))}\n\n"
        f"Response language: {language_name}. Write ALL natural-language output in {language_name}, "
        "including primary_description, hierarchy_descriptions, every reasoning field, key_factors, "
        "alternative descriptions, why_not, trade_off, the questions, their hints and their option "
        "labels. Translate the official HS descriptions faithfully, without changing their tariff "
        "meaning. Do not translate JSON keys or change HS codes, numeric values, or the "
        "classification decision because of the response language."
    )
    user = REASONING_USER_TEMPLATE.format(
        cleaned_text=cleaned_text,
        catalogue_context=_format_catalogue_context(candidates),
        trade_context=_format_trade_context(trade),
        answers_context=_format_answers(answers),
    )

    response = llm.complete(system=system, user=user)

    try:
        data = extract_json(response.text)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    questions = _parse_questions(data.get("questions"), budget)
    outcome = "questions" if questions else "code"

    reasoning_data = data.get("reasoning") or {}
    reasoning = ClassificationReasoning(
        section_reasoning=reasoning_data.get("section_reasoning", "") or "",
        chapter_reasoning=reasoning_data.get("chapter_reasoning", "") or "",
        heading_reasoning=reasoning_data.get("heading_reasoning", "") or "",
        subheading_reasoning=reasoning_data.get("subheading_reasoning", "") or "",
        key_factors=reasoning_data.get("key_factors", []) or [],
    )

    primary_code = data.get("primary_code") or None
    primary_description = data.get("primary_description") or ""
    hierarchy: dict = {}

    if primary_code:
        entry = _entry_for_code(primary_code, candidates)
        if entry is None:
            logger.warning("Foundry returned a code outside the HS catalogue: %s", primary_code)
            primary_code = None
        else:
            hierarchy = _hierarchy_from_entry(entry)
            if not isinstance(primary_description, str) or not primary_description.strip():
                primary_description = entry.get("description", "")
            if language != "en":
                localized = data.get("hierarchy_descriptions")
                for level in ("section", "chapter", "heading"):
                    if not hierarchy[level]["description"]:
                        continue
                    description = localized.get(level) if isinstance(localized, dict) else None
                    if not isinstance(description, str) or not description.strip():
                        description = translate_from_en(hierarchy[level]["description"], language)
                    hierarchy[level]["description"] = description
                if isinstance(primary_description, str) and primary_description.strip():
                    hierarchy["subheading"]["description"] = primary_description

    if outcome == "questions":
        primary_code = None

    confidence = data.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return ReasoningOutcome(
        outcome=outcome,
        primary_code=primary_code,
        primary_description=primary_description or "",
        confidence=confidence,
        reasoning=reasoning,
        hierarchy=hierarchy,
        alternative_codes=data.get("alternative_codes", []) or [],
        questions=questions,
        thinking=response.thinking,
        prompt_tokens=response.prompt_tokens,
        output_tokens=response.output_tokens,
        total_tokens=response.total_tokens,
    )
