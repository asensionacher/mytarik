"""
EU CN8/TARIC10 classification stage.

The EU path uses only CN8/TARIC10 candidates retrieved from `eu_taric` and
returns the same request-local contract used by the API response models.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Sequence

from app.cargo_preprocessor import preprocess_cargo_text
from app.eu_retriever import EUCandidate, retrieve_eu_candidates
from app.llm_provider import extract_json, get_provider
from app.schemas import (
    ClarificationAnswer,
    ClarificationQuestion,
    ClassificationReasoning,
    EUAlternativeCode,
    EUClassificationResult,
    TradeContext,
)

EU_TARIFF_SYSTEM_PROMPT = """
You are an EU customs classification assistant.

Classify the cargo into one CN8 and one TARIC10 code from the retrieved
`eu_taric` candidates. The candidate list is the only allowed source of codes.

Return JSON only, with this shape:
{
  "cn8": "8-digit CN code or null",
  "taric10": "10-digit TARIC code or null",
  "description": "clear product description in the requested language",
  "confidence": 0.0,
  "reasoning": {
    "section_reasoning": "why the EU section/area is appropriate",
    "chapter_reasoning": "why the CN chapter is appropriate",
    "heading_reasoning": "why the CN heading is appropriate",
    "subheading_reasoning": "why the CN/TARIC subdivision is appropriate",
    "key_factors": ["factor 1", "factor 2"]
  },
  "alternatives": [
    {
      "cn8": "candidate CN8 or null",
      "taric10": "candidate TARIC10 or null",
      "description": "candidate description",
      "why_not": "why this candidate was not selected",
      "trade_off": "commercial or classification trade-off"
    }
  ],
  "clarification_question": {
    "question": "short question needed to disambiguate, or null",
    "options": ["option A", "option B"]
  },
  "needs_human_review": false
}

Rules:
- Select only CN8 or TARIC10 codes that appear in the candidate list.
- If the selected value is a CN8 code, the TARIC10 may be the matching candidate
  TARIC10 extension when it is present in the candidate list.
- If no retrieved candidate is reliable, return null codes and needs_human_review
  true.
- Never invent, expand, shorten or transform codes.
- Prefer a TARIC10 code when the retrieved candidates provide it.
- If key product attributes are missing, ask exactly one concise clarification
  question.
- Do not ask for tariff rates, invoices, taxes, or transport documents.
""".strip()

EU_TARIFF_PROMPT = EU_TARIFF_SYSTEM_PROMPT

_STOP_WORDS = {
    "a", "an", "and", "de", "del", "the", "con", "en", "for",
    "from", "in", "of", "on", "or", "para", "por", "to", "type", "with", "y",
}


class EUClassificationError(RuntimeError):
    """Raised when the EU CN8/TARIC10 path cannot produce a safe result."""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _valid_cn8(value: Any) -> str | None:
    text = _clean(value)
    return text if re.fullmatch(r"\d{8}", text) else None


def _valid_taric10(value: Any) -> str | None:
    text = _clean(value)
    return text if re.fullmatch(r"\d{10}", text) else None


def _candidate_valid(candidate: EUCandidate) -> bool:
    return bool(_valid_cn8(candidate.cn8) or _valid_taric10(candidate.taric10))


def _candidate_codes(candidate: EUCandidate) -> set[str]:
    codes = set()
    for code in (_valid_cn8(candidate.cn8), _valid_taric10(candidate.taric10)):
        if code:
            codes.add(code)
    return codes


def _candidate_lookup(candidates: Sequence[EUCandidate]) -> dict[str, EUCandidate]:
    lookup: dict[str, EUCandidate] = {}
    for candidate in candidates:
        for code in _candidate_codes(candidate):
            lookup.setdefault(code, candidate)
    return lookup


def _candidate_primary_code(candidate: EUCandidate) -> str | None:
    return _valid_taric10(candidate.taric10) or _valid_cn8(candidate.cn8)


def _format_candidates(candidates: Sequence[EUCandidate]) -> str:
    lines: list[str] = []
    for index, candidate in enumerate(candidates[:12], start=1):
        cn8 = _clean(candidate.cn8) or "null"
        taric10 = _clean(candidate.taric10) or "null"
        description = _clean(candidate.description) or "no description"
        lines.append(
            f"{index}. cn8={cn8} | taric10={taric10} | "
            f"score={float(candidate.score):.4f} | {description}"
        )
    return "\n".join(lines)


def _format_trade(trade: TradeContext | dict[str, Any] | None) -> str:
    if trade is None:
        return "none"

    if isinstance(trade, dict):
        mode = trade.get("trade_mode")
        origin = trade.get("origin_country")
        dispatch = trade.get("dispatch_country")
    else:
        mode = getattr(trade, "trade_mode", None)
        origin = getattr(trade, "origin_country", None)
        dispatch = getattr(trade, "dispatch_country", None)

    return f"mode={_clean(mode) or 'unknown'}, origin={_clean(origin) or 'unknown'}, dispatch={_clean(dispatch) or 'unknown'}"


def _format_answers(answers: Sequence[ClarificationAnswer] | Sequence[dict[str, Any]] | None) -> str:
    if not answers:
        return "none"

    lines = []
    for answer in answers:
        if isinstance(answer, dict):
            question = answer.get("question")
            value = answer.get("answer")
        else:
            question = getattr(answer, "question", None)
            value = getattr(answer, "answer", None)
        lines.append(f"- {_clean(question) or 'Question'}: {_clean(value) or 'Answer missing'}")
    return "\n".join(lines)


def _language_instruction(language: str) -> str:
    if _clean(language).lower().startswith("es"):
        return "Write the user-facing description and reasoning in Spanish."
    return "Write the user-facing description and reasoning in English."


def _build_user_prompt(
    *,
    raw_text: str,
    cleaned_text: str,
    candidates: Sequence[EUCandidate],
    language: str,
    trade: TradeContext | dict[str, Any] | None,
    clarification_answers: Sequence[ClarificationAnswer] | Sequence[dict[str, Any]] | None,
) -> str:
    return f"""{EU_TARIFF_SYSTEM_PROMPT}

Product description (raw): {raw_text}
Product description (cleaned): {cleaned_text}
Trade context: {_format_trade(trade)}
Clarification answers: {_format_answers(clarification_answers)}
Language instruction: {_language_instruction(language)}

EU candidate list:
{_format_candidates(candidates)}

Return the JSON object now.
""".strip()


def _reasoning_object(raw: Any, language: str) -> ClassificationReasoning:
    data = raw if isinstance(raw, dict) else {}

    def first(*keys: str) -> str:
        for key in keys:
            value = _clean(data.get(key))
            if value:
                return value
        return ""

    key_factors = data.get("key_factors")
    if isinstance(key_factors, str):
        factors = [part.strip() for part in re.split(r"[,;|]", key_factors) if part.strip()]
    elif isinstance(key_factors, list):
        factors = [_clean(item) for item in key_factors if _clean(item)]
    else:
        factors = []

    missing = (
        "Sin atributos suficientes; revisión humana recomendada."
        if _clean(language).lower().startswith("es")
        else "Insufficient product attributes; human review is recommended."
    )
    return ClassificationReasoning(
        section_reasoning=first("section_reasoning", "section") or missing,
        chapter_reasoning=first("chapter_reasoning", "chapter") or missing,
        heading_reasoning=first("heading_reasoning", "heading") or missing,
        subheading_reasoning=first("subheading_reasoning", "subheading") or missing,
        key_factors=factors,
    )


def _confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _word_count(text: str) -> int:
    words = re.findall(r"[a-záéíóúñü0-9]+", text.lower())
    return len([word for word in words if word not in _STOP_WORDS])


def _eu_reasoning_triggers(
    cleaned_text: str,
    candidates: Sequence[EUCandidate],
    confidence: float,
    primary_code: str | None,
) -> list[str]:
    triggers: list[str] = []
    if confidence < 0.75:
        triggers.append("low_confidence")

    if len(candidates) >= 2:
        gap = abs(float(candidates[0].score) - float(candidates[1].score))
        if gap <= 0.001 + 1e-9:
            triggers.append("close_candidates")

    if _word_count(cleaned_text) < 4:
        triggers.append("short_description")

    if primary_code is None:
        triggers.append("missing_code")

    return triggers


def _normalize_clarification_question(raw: Any, language: str) -> ClarificationQuestion | None:
    data = raw if isinstance(raw, dict) else {}
    question = _clean(data.get("question"))
    if not question:
        return None

    options = data.get("options")
    if isinstance(options, str):
        options = [part.strip() for part in re.split(r"[,;|]", options) if part.strip()]
    elif not isinstance(options, list):
        options = []

    normalized_options = [_clean(option)[:120] for option in options if _clean(option)]
    return ClarificationQuestion(
        question=question[:500],
        options=normalized_options[:6],
    )


def _default_clarification_question(
    triggers: Sequence[str],
    alternatives: Sequence[EUAlternativeCode],
    language: str,
) -> ClarificationQuestion:
    es = _clean(language).lower().startswith("es")
    options = [alt.description[:120] for alt in alternatives if alt.description][:6]

    if "missing_code" in triggers:
        question = (
            "¿Cuál es el material, composición o uso exacto del producto?"
            if es
            else "What is the exact material, composition, or intended use of the product?"
        )
    elif "close_candidates" in triggers:
        question = (
            "¿Qué descripción describe mejor el producto realmente enviado?"
            if es
            else "Which description best matches the goods actually shipped?"
        )
    elif "short_description" in triggers:
        question = (
            "¿De qué está hecho el producto y para qué se usa?"
            if es
            else "What is the product made of, and what is it used for?"
        )
    else:
        question = (
            "¿Puede confirmar el material, presentación o función principal del producto?"
            if es
            else "Can you confirm the material, presentation, or main function of the product?"
        )

    return ClarificationQuestion(question=question, options=options)


def _primary_codes_from_payload(data: dict[str, Any]) -> tuple[str | None, str | None]:
    cn8 = _valid_cn8(data.get("cn8"))
    taric10 = _valid_taric10(data.get("taric10"))
    fallback = _clean(data.get("primary_code") or data.get("code"))
    if _valid_taric10(fallback):
        taric10 = taric10 or _valid_taric10(fallback)
    if _valid_cn8(fallback):
        cn8 = cn8 or _valid_cn8(fallback)
    if not cn8 and taric10:
        cn8 = _valid_cn8(taric10[:8])
    return cn8, taric10


def _selected_candidate(
    data: dict[str, Any],
    candidates: Sequence[EUCandidate],
    lookup: dict[str, EUCandidate],
) -> tuple[str | None, str | None]:
    cn8, taric10 = _primary_codes_from_payload(data)
    if not cn8 and not taric10:
        return None, None

    valid_codes = set(lookup)
    selected_value = _valid_taric10(taric10) or _valid_cn8(cn8)
    if selected_value not in valid_codes:
        raise EUClassificationError(
            "The EU model selected code "
            f"{selected_value!r}, which is not present in the retrieved eu_taric candidates."
        )

    candidate = lookup[selected_value]
    candidate_cn8 = _valid_cn8(candidate.cn8) or cn8
    candidate_taric10 = _valid_taric10(candidate.taric10) or taric10

    if candidate_taric10 and not candidate_cn8:
        candidate_cn8 = _valid_cn8(candidate_taric10[:8])

    if candidate_cn8 and candidate_taric10 and not candidate_taric10.startswith(candidate_cn8):
        raise EUClassificationError(
            f"Retrieved eu_taric candidate is inconsistent: cn8={candidate_cn8!r}, "
            f"taric10={candidate_taric10!r}."
        )

    return candidate_cn8, candidate_taric10


def _normalize_alternative(
    raw: Any,
    lookup: dict[str, EUCandidate],
    excluded_codes: Iterable[str],
) -> EUAlternativeCode | None:
    data = raw if isinstance(raw, dict) else {"code": raw}
    code = _clean(data.get("taric10") or data.get("cn8") or data.get("code"))
    if not code or code in set(excluded_codes):
        return None

    candidate = lookup.get(code)
    if candidate is None:
        return None

    cn8 = _valid_cn8(candidate.cn8) or _valid_cn8(data.get("cn8"))
    taric10 = _valid_taric10(candidate.taric10) or _valid_taric10(data.get("taric10"))
    if cn8 and taric10 and not taric10.startswith(cn8):
        return None

    description = _clean(data.get("description") or candidate.description)
    return EUAlternativeCode(
        cn8=cn8,
        taric10=taric10,
        description=description,
        why_not=_clean(data.get("why_not")) or None,
        trade_off=_clean(data.get("trade_off")) or None,
    )


def _fallback_alternatives(
    candidates: Sequence[EUCandidate],
    excluded_codes: Iterable[str],
    limit: int = 4,
) -> list[EUAlternativeCode]:
    excluded = set(excluded_codes)
    alternatives: list[EUAlternativeCode] = []
    seen: set[str] = set()

    for candidate in candidates:
        primary = _candidate_primary_code(candidate)
        if not primary or primary in excluded or primary in seen:
            continue
        seen.add(primary)
        alternatives.append(
            EUAlternativeCode(
                cn8=_valid_cn8(candidate.cn8),
                taric10=_valid_taric10(candidate.taric10),
                description=_clean(candidate.description),
                why_not="Not selected by the EU classification model.",
                trade_off=f"Retrieval score {float(candidate.score):.4f}.",
            )
        )
        if len(alternatives) >= limit:
            break

    return alternatives


def classify_eu_with_llm(
    raw_text: str,
    cleaned_text: str,
    candidates: Sequence[EUCandidate],
    *,
    language: str = "en",
    trade: TradeContext | dict[str, Any] | None = None,
    clarification_answers: Sequence[ClarificationAnswer] | Sequence[dict[str, Any]] | None = None,
    provider: Any | None = None,
) -> EUClassificationResult:
    valid_candidates = [candidate for candidate in candidates if _candidate_valid(candidate)]
    if not valid_candidates:
        raise EUClassificationError(
            "No valid CN8/TARIC10 candidates were retrieved from eu_taric. "
            "Ingest or repair the eu_taric collection before classifying in EU mode."
        )

    lookup = _candidate_lookup(valid_candidates)
    provider = provider or get_provider()
    started = time.time()
    response = provider.complete(
        system=EU_TARIFF_SYSTEM_PROMPT,
        user=_build_user_prompt(
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            candidates=valid_candidates,
            language=language,
            trade=trade,
            clarification_answers=clarification_answers,
        ),
    )

    try:
        data = extract_json(response.text)
    except Exception as exc:  # noqa: BLE001 - convert provider parsing failure into EU error.
        raise EUClassificationError(f"The EU model did not return valid JSON: {exc}") from exc

    cn8, taric10 = _selected_candidate(data, valid_candidates, lookup)
    primary_code = taric10 or cn8
    confidence = _confidence(data.get("confidence"))
    reasoning = _reasoning_object(data.get("reasoning"), language)

    candidate_description = ""
    if primary_code and lookup.get(primary_code) is not None:
        candidate_description = _clean(lookup[primary_code].description)

    description = _clean(data.get("description") or candidate_description)
    if not description:
        description = candidate_description

    excluded_codes = {code for code in (cn8, taric10) if code}
    raw_alternatives = data.get("alternatives")
    if not isinstance(raw_alternatives, list):
        raw_alternatives = []

    alternatives: list[EUAlternativeCode] = []
    seen_alternatives: set[str] = set(excluded_codes)
    for raw_alternative in raw_alternatives:
        alternative = _normalize_alternative(raw_alternative, lookup, seen_alternatives)
        if alternative is None:
            continue
        alternative_code = alternative.taric10 or alternative.cn8
        if alternative_code and alternative_code not in seen_alternatives:
            alternatives.append(alternative)
            seen_alternatives.add(alternative_code)

    if not alternatives:
        alternatives = _fallback_alternatives(valid_candidates, seen_alternatives)

    triggers = _eu_reasoning_triggers(cleaned_text, valid_candidates, confidence, primary_code)
    is_ambiguous = bool(triggers)
    needs_human_review = bool(data.get("needs_human_review")) or is_ambiguous

    clarification_question = _normalize_clarification_question(data.get("clarification_question"), language)
    if is_ambiguous and not clarification_question:
        clarification_question = _default_clarification_question(triggers, alternatives, language)

    normalized_answers: list[ClarificationAnswer] = []
    for answer in clarification_answers or []:
        if isinstance(answer, ClarificationAnswer):
            normalized_answers.append(answer)
        elif isinstance(answer, dict):
            normalized_answers.append(ClarificationAnswer(**answer))

    return EUClassificationResult(
        input_text=raw_text,
        cleaned_text=cleaned_text,
        classification_mode="eu",
        primary_code=primary_code,
        primary_description=description,
        confidence=confidence,
        reasoning=reasoning,
        hierarchy={},
        alternative_codes=[alternative.model_dump() for alternative in alternatives],
        is_ambiguous=is_ambiguous,
        reasoning_triggers=triggers,
        clarification_question=clarification_question if is_ambiguous else None,
        clarification_answers=normalized_answers,
        needs_human_review=needs_human_review,
        processing_time_ms=(time.time() - started) * 1000,
        prompt_tokens=getattr(response, "prompt_tokens", 0),
        output_tokens=getattr(response, "output_tokens", 0),
        total_tokens=getattr(response, "total_tokens", 0),
        thinking=getattr(response, "thinking", None),
        cn8=cn8,
        taric10=taric10,
        description=description,
        alternatives=alternatives,
    )


def classify_eu_cargo(
    raw_text: str,
    language: str = "en",
    trade: TradeContext | dict[str, Any] | None = None,
    clarification_answers: Sequence[ClarificationAnswer] | Sequence[dict[str, Any]] | None = None,
    *,
    provider: Any | None = None,
) -> EUClassificationResult:
    started = time.time()
    cleaned_text = preprocess_cargo_text(raw_text)
    query = cleaned_text
    for answer in clarification_answers or []:
        if isinstance(answer, dict):
            question = answer.get("question")
            value = answer.get("answer")
        else:
            question = getattr(answer, "question", None)
            value = getattr(answer, "answer", None)
        if question and value:
            query = f"{query}\n{question}: {value}"

    candidates = retrieve_eu_candidates(query)
    if not candidates:
        raise EUClassificationError(
            "No candidates were retrieved from eu_taric. Ingest or repair the "
            "eu_taric collection before classifying in EU mode."
        )

    result = classify_eu_with_llm(
        raw_text,
        cleaned_text,
        candidates,
        language=language,
        trade=trade,
        clarification_answers=clarification_answers,
        provider=provider,
    )
    result.processing_time_ms = (time.time() - started) * 1000
    return result
