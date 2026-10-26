from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


ResponseLanguage = Literal["es", "en"]
TradeMode = Literal["import", "export"]


class TradeContext(BaseModel):
    """Commercial context shared by the descriptions being classified."""
    model_config = ConfigDict(extra="forbid")

    trade_mode: TradeMode
    origin_country: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    dispatch_country: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")


class HSCodeEntry(BaseModel):
    """A single HS code entry from the tariff schedule."""
    code: str = Field(..., description="6-digit HS code, e.g. '620462'")
    description: str = Field(..., description="Official HS description text")
    chapter_code: str = Field(..., description="2-digit chapter code, e.g. '62'")
    chapter_description: str = Field(..., description="Chapter-level description")
    heading_code: str = Field(..., description="4-digit heading code, e.g. '6204'")
    heading_description: str = Field(..., description="Heading-level description")
    section: str = Field(default="", description="Section number (Roman numeral)")
    section_description: str = Field(default="", description="Section-level description")


class HSCandidate(BaseModel):
    """A candidate HS code returned by the retrieval stage."""
    code: str
    description: str
    chapter_code: str
    chapter_description: str
    heading_code: str
    heading_description: str
    section: str = ""
    section_description: str = ""
    retrieval_score: float = Field(..., description="Combined retrieval score (0-1)")
    retrieval_method: str = Field(..., description="How this candidate was found: 'semantic', 'bm25', or 'hybrid'")


class ClassificationReasoning(BaseModel):
    """Step-by-step reasoning chain for the classification decision."""
    section_reasoning: str = Field(..., description="Why this section was chosen")
    chapter_reasoning: str = Field(..., description="Why this chapter was chosen")
    heading_reasoning: str = Field(..., description="Why this heading was chosen")
    subheading_reasoning: str = Field(..., description="Why this subheading was chosen")
    key_factors: list[str] = Field(default_factory=list, description="Key product attributes that drove the decision")


class ClarificationOption(BaseModel):
    """A selectable answer offered to the human for a clarifying question."""
    value: str = Field(..., description="Machine value sent back when the option is picked")
    label: str = Field(default="", description="Human readable label for the option")
    code: str | None = Field(default=None, pattern=r"^\d{6}$", description="HS code the option points to, if any")
    description: str | None = Field(default=None, description="Extra context shown next to the option")


class ClarificationQuestion(BaseModel):
    """A question the model asks the human to disambiguate the cargo."""
    id: str = Field(..., description="Stable identifier of the question inside the line")
    question: str = Field(..., description="The question shown to the human")
    hint: str = Field(default="", description="Optional hint explaining why it is needed")
    allow_free_text: bool = Field(default=True, description="Whether the human may type a free answer")
    options: list[ClarificationOption] = Field(
        default_factory=list, description="Buttons the human can pick instead of typing",
    )


class ClarificationAnswer(BaseModel):
    """A human answer to a clarifying question, sent back to resolve the line."""
    question_id: str = Field(default="", description="Identifier of the answered question")
    question: str = Field(default="", description="Text of the answered question, for the transcript")
    answer: str = Field(..., min_length=1, description="The answer: option value or free text")


class ClassificationResult(BaseModel):
    """Final classification output for a single cargo description."""
    input_text: str = Field(..., description="Original raw cargo description")
    cleaned_text: str = Field(..., description="Preprocessed cargo text")
    primary_code: str | None = Field(
        default=None, pattern=r"^\d{6}$", description="Recommended 6-digit HS code",
    )
    primary_description: str | None = Field(default="", description="HS description for the primary code")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence (0-1)")
    reasoning: ClassificationReasoning = Field(..., description="Step-by-step reasoning chain")
    hierarchy: dict = Field(
        default_factory=dict,
        description="Full hierarchy: {section, chapter, heading, subheading} with codes and descriptions"
    )
    alternative_codes: list[dict] = Field(
        default_factory=list,
        description="Top alternative candidates with trade-offs (for ambiguous cases)"
    )
    is_ambiguous: bool = Field(default=False, description="True if confidence < threshold")
    processing_time_ms: float = Field(default=0.0, description="Total processing time in milliseconds")
    # Contadores de tokens devueltos por el proveedor LLM.
    # Si la API no los expone, quedan en 0.
    prompt_tokens: int = Field(default=0, ge=0, description="Tokens del prompt")
    output_tokens: int = Field(default=0, ge=0, description="Tokens generados por el modelo")
    total_tokens: int = Field(default=0, ge=0, description="Total de tokens consumidos (prompt + output)")
    # None when the deployment does not expose internal reasoning.
    thinking: str | None = Field(default=None, description="Razonamiento interno del modelo (modo thinking)")
    # ── Human in the loop ──
    clarifying_questions: list[ClarificationQuestion] = Field(
        default_factory=list,
        description="Questions the model needs answered before the code can be settled",
    )
    clarification_answers: list[ClarificationAnswer] = Field(
        default_factory=list,
        description="Answers already provided by the human for this line",
    )
    reasoning_reasons: list[str] = Field(
        default_factory=list,
        description="Why the deep reasoning stage was triggered (low_confidence, tied_candidates, short_query)",
    )


class ClassifyRequest(BaseModel):
    """API request to classify a cargo description."""
    model_config = ConfigDict(extra="forbid")
    language: ResponseLanguage = Field(default="en", description="Language for generated descriptions and reasoning")
    trade: TradeContext | None = Field(default=None, description="Commercial context for the classification")

    description: str = Field(
        ...,
        min_length=3,
        description="Natural language cargo description from B/L or invoice",
        examples=[
            "500 cartons of men's cotton polo shirts, 100% cotton, knitted, sizes M-XXL",
            "1200 bags of basmati rice, long grain, milled, 25kg bags",
            "20 pallets of ceramic floor tiles 30x30cm glazed",
        ]
    )
    clarification_answers: list[ClarificationAnswer] = Field(
        default_factory=list,
        max_length=3,
        description="Answers given by the human to the clarifying questions asked in a previous round",
    )


class BatchClassifyRequest(BaseModel):
    """API request to classify multiple cargo descriptions."""
    model_config = ConfigDict(extra="forbid")
    language: ResponseLanguage = Field(default="en", description="Response language for every description")
    trade: TradeContext | None = Field(default=None, description="Commercial context for every description")

    descriptions: list[str] = Field(..., min_length=1, max_length=50)


class ClassifyResponse(BaseModel):
    """API response for a classification request."""
    status: Literal["classified", "ambiguous", "needs_clarification", "error"]
    result: ClassificationResult | None = None
    error: str | None = None
