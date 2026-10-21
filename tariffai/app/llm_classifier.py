"""
Stage 3: LLM Classification Node (Single Prompt Call)

Takes the cleaned cargo text + Top-K candidate HS codes from retrieval
and makes ONE LLM call to:
1. Select the best HS code from the candidates
2. Generate a full Chapter → Heading → Subheading reasoning chain
3. Output a calibrated confidence score
4. For ambiguous cases, explain trade-offs between top candidates

Classification uses only the server-configured Azure Foundry deployment.
"""

from app.llm_provider import (
    extract_json,
    get_provider,
)
from app.config import CONFIDENCE_THRESHOLD
from app.schemas import (
    HSCandidate,
    ClassificationResult,
    ClassificationReasoning,
    ResponseLanguage,
)


CLASSIFICATION_SYSTEM_PROMPT = """You are TariffAI, an expert customs tariff classification specialist.
You classify cargo descriptions into 6-digit Harmonized System (HS) codes.

Your output MUST be a single JSON object with this exact schema (no extra fields, no markdown fences):

{
    "primary_code": "620462",
    "primary_description": "The HS description for the selected code",
    "hierarchy_descriptions": {
        "section": "Description of the selected candidate's section",
        "chapter": "Description of the selected candidate's chapter",
        "heading": "Description of the selected candidate's heading"
    },
    "confidence": 0.85,
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
    ]
}

Confidence calibration:
  0.9-1.0: Clear, unambiguous match
  0.7-0.89: Strong match but minor ambiguity possible
  0.5-0.69: Ambiguous — multiple valid interpretations
  Below 0.5: Insufficient information to classify reliably

Respond with ONLY the JSON object. No markdown fences, no preamble, no postamble."""


CLASSIFICATION_USER_TEMPLATE = """## Cargo Description (cleaned)
{cleaned_text}

## Candidate HS Codes
{candidates_text}

## Task
Analyze the cargo description, select the single most accurate 6-digit HS code
from the candidates, walk through the HS hierarchy top-down
(SECTION → CHAPTER → HEADING → SUBHEADING), and report trade-offs with alternatives.

Respond with ONLY the JSON object."""


def _format_candidates(candidates: list[HSCandidate]) -> str:
    """Format candidates into a readable text block for the prompt."""
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"{i}. Code: {c.code}\n"
            f"   Description: {c.description}\n"
            f"   Heading ({c.heading_code}): {c.heading_description}\n"
            f"   Chapter ({c.chapter_code}): {c.chapter_description}\n"
            f"   Section {c.section}: {c.section_description}\n"
            f"   Retrieval Score: {c.retrieval_score} ({c.retrieval_method})"
        )
    return "\n\n".join(lines)


def classify_with_llm(
    cleaned_text: str,
    candidates: list[HSCandidate],
    raw_text: str = "",
    language: ResponseLanguage = "en",
) -> ClassificationResult:
    """
    Make a single LLM call to classify the cargo description.

    Args:
        cleaned_text: Preprocessed cargo text (from Stage 1)
        candidates: Top-K candidate HS codes (from Stage 2)
        raw_text: Original raw text (for the output record)
        language: Language for descriptions, reasoning and alternatives

    Returns:
        ClassificationResult with code, reasoning chain and confidence
    """
    llm = get_provider()

    language_name = {"es": "Spanish", "en": "English"}[language]
    system = (
        f"{CLASSIFICATION_SYSTEM_PROMPT}\n\n"
        f"Response language: {language_name}. Write ALL natural-language output in {language_name}, "
        "including primary_description, hierarchy_descriptions, every reasoning field, "
        "key_factors, alternative descriptions, why_not, trade_off, and any exposed thinking. "
        "Translate the candidate descriptions faithfully, without changing their tariff meaning. "
        "Keep empty hierarchy descriptions empty. Do not translate JSON keys or change HS codes, "
        "numeric values, or the classification decision because of the response language."
    )
    user = CLASSIFICATION_USER_TEMPLATE.format(
        cleaned_text=cleaned_text,
        candidates_text=_format_candidates(candidates),
    )

    response = llm.complete(
        system=system,
        user=user,
    )

    # Parsear JSON, incluso si vino en ```json ... ```
    try:
        result_data = extract_json(response.text)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    # Build the reasoning chain
    reasoning_data = result_data.get("reasoning", {}) or {}
    reasoning = ClassificationReasoning(
        section_reasoning=reasoning_data.get("section_reasoning", ""),
        chapter_reasoning=reasoning_data.get("chapter_reasoning", ""),
        heading_reasoning=reasoning_data.get("heading_reasoning", ""),
        subheading_reasoning=reasoning_data.get("subheading_reasoning", ""),
        key_factors=reasoning_data.get("key_factors", []) or [],
    )

    primary_code = result_data.get("primary_code") or None
    primary_desc = result_data.get("primary_description") or ""
    hierarchy: dict = {}
    if primary_code:
        for c in candidates:
            if c.code == primary_code:
                hierarchy = {
                    "section": {"code": c.section, "description": c.section_description},
                    "chapter": {"code": c.chapter_code, "description": c.chapter_description},
                    "heading": {"code": c.heading_code, "description": c.heading_description},
                    "subheading": {"code": c.code, "description": c.description},
                }
                if language != "en":
                    localized = result_data.get("hierarchy_descriptions")
                    if not isinstance(localized, dict) or not isinstance(primary_desc, str) or not primary_desc.strip():
                        raise ValueError("Foundry omitted localized HS descriptions")
                    for level in ("section", "chapter", "heading"):
                        if hierarchy[level]["description"]:
                            description = localized.get(level)
                            if not isinstance(description, str) or not description.strip():
                                raise ValueError(f"Foundry omitted the localized {level} description")
                            hierarchy[level]["description"] = description
                    hierarchy["subheading"]["description"] = primary_desc
                break

    confidence = float(result_data.get("confidence", 0.5))
    is_ambiguous = confidence < CONFIDENCE_THRESHOLD or primary_code is None

    return ClassificationResult(
        input_text=raw_text or cleaned_text,
        cleaned_text=cleaned_text,
        primary_code=primary_code,
        primary_description=primary_desc,
        confidence=confidence,
        reasoning=reasoning,
        hierarchy=hierarchy,
        alternative_codes=result_data.get("alternative_codes", []) or [],
        is_ambiguous=is_ambiguous,
        prompt_tokens=response.prompt_tokens,
        output_tokens=response.output_tokens,
        total_tokens=response.total_tokens,
        thinking=response.thinking,
    )
