"""
customs_client.py — cliente HTTP asíncrono hacia el motor de medidas aduaneras.

Define los modelos Pydantic espejo de la API de TariffAI (`POST /customs/evaluate`)
para tener tipado fuerte en este backend, y expone:

- `evaluate_operation(request)` — determina las medidas de una operación
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings

logger = logging.getLogger(__name__)

OperationType = Literal["IMPORT", "EXPORT"]
ResponseLanguage = Literal["es", "en"]


# ── Modelos espejo ─────────────────────────────────────────────────────


class CustomsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taric_code: str = Field(..., pattern=r"^\d{10}$")
    description: str
    customs_value: float | None = None
    currency: str | None = None
    net_weight_kg: float | None = None
    supplementary_units: float | None = None


class CustomsOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_type: OperationType
    origin_country: str = Field(..., pattern=r"^[A-Z]{2}$")
    destination_country: str = Field(..., pattern=r"^[A-Z]{2}$")
    incoterm: str | None = None
    language: ResponseLanguage = "en"
    origin_subdivision: str | None = None
    destination_subdivision: str | None = None
    items: list[CustomsItem] = Field(..., min_length=1, max_length=50)


class DutyRate(BaseModel):
    kind: str = "unknown"
    ad_valorem_percent: float | None = None
    specific_amount: float | None = None
    specific_currency: str | None = None
    specific_unit: str | None = None
    formula_raw: str = ""


class MeasureFootnote(BaseModel):
    code: str = ""
    type: str = ""
    text: str = ""


class MeasureCondition(BaseModel):
    sequence_number: str = ""
    description: str = ""
    action_description: str = ""
    certificate_type: str | None = None
    certificate_number: str | None = None
    certificate_description: str = ""
    condition_expression: str | None = None
    tariff_formula: str | None = None


class DutyMeasure(BaseModel):
    measure_type: str = ""
    measure_type_label: str = ""
    category: str = "other"
    origin: str = ""
    geographic_area: str = ""
    description: str = ""
    duty: DutyRate = Field(default_factory=DutyRate)
    valid_from: str | None = None
    valid_to: str | None = None
    regulation_id: str | None = None
    exclusions: str | None = None
    footnotes: list[MeasureFootnote] = Field(default_factory=list)
    conditions: list[MeasureCondition] = Field(default_factory=list)


class ThirdCountryDuty(DutyMeasure):
    variants: list[DutyMeasure] = Field(default_factory=list)


class PreferentialDuty(DutyMeasure):
    agreement: str = ""
    proof_of_origin: list[str] = Field(default_factory=list)


class TradeDefenseMeasure(DutyMeasure):
    defense_kind: str = "ANTI_DUMPING"
    additional_code: str | None = None
    additional_code_text: str | None = None
    certificate_code: str | None = None
    certificate_description: str = ""
    residual_duty: DutyRate | None = None
    proof_of_origin: list[str] = Field(default_factory=list)


class BorderControl(BaseModel):
    category: str = "DOCUMENT"
    code: str = ""
    title: str = ""
    authority: str | None = None
    requirement: str = ""
    mandatory: bool = True
    source: str = "unknown"


class SpecialRegulation(BaseModel):
    regulation: str = "REACH"
    name: str = ""
    applies: bool = True
    reference: str | None = None
    reason: str = ""
    action_required: str | None = None
    source: str = "unknown"


class ExemptionCode(BaseModel):
    code: str = ""
    description: str = ""
    applies_to: str = ""
    action: str = ""


class TaxEstimation(BaseModel):
    currency: str = "EUR"
    customs_value: float = 0.0
    estimated_duty: float = 0.0
    duty_breakdown: list[str] = Field(default_factory=list)
    estimated_vat_base: float = 0.0
    estimated_vat_rate: float | None = None
    estimated_vat: float | None = None
    incoterm_adjustment: str | None = None
    formula: str = ""
    notes: list[str] = Field(default_factory=list)


class ExecutiveSummary(BaseModel):
    duty_to_pay: str = ""
    how_to_reduce_to_zero: str | None = None
    border_controls: list[str] = Field(default_factory=list)
    special_regulations: list[str] = Field(default_factory=list)
    y_codes_to_declare: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    needs_human_review: bool = False


class ItemProvenance(BaseModel):
    provider: str = ""
    source: str = "unknown"
    cache_hit: bool = False
    queried_code: str | None = None
    raw_measure_count: int = 0
    fetched_at: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ItemMeasures(BaseModel):
    line_number: int = 0
    taric_code: str = ""
    description: str = ""
    product_description: str | None = None
    third_country_duty: ThirdCountryDuty | None = None
    preferential_duties: list[PreferentialDuty] = Field(default_factory=list)
    trade_defense_measures: list[TradeDefenseMeasure] = Field(default_factory=list)
    border_controls_and_inspections: list[BorderControl] = Field(default_factory=list)
    environmental_and_special_regulations: list[SpecialRegulation] = Field(default_factory=list)
    exemption_y_codes: list[ExemptionCode] = Field(default_factory=list)
    tax_estimation: TaxEstimation | None = None
    executive_summary: ExecutiveSummary | None = None
    provenance: ItemProvenance = Field(default_factory=ItemProvenance)


class CustomsOperationResponse(BaseModel):
    status: Literal["ok", "partial", "error"] = "ok"
    operation_type: OperationType = "IMPORT"
    origin_country: str = ""
    destination_country: str = ""
    incoterm: str | None = None
    customs_regime: str = "IMPORT_FROM_THIRD_COUNTRY"
    territorial_note: str | None = None
    reporting_requirements: list[str] = Field(default_factory=list)
    items_measures: list[ItemMeasures] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str = ""
    cache_hits: int = 0
    processing_time_ms: float = 0.0
    error: str | None = None


# ── Cliente ────────────────────────────────────────────────────────────


class CustomsClient:
    """Cliente httpx asíncrono de larga vida hacia el motor de medidas."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or settings.tariffai_url).rstrip("/")
        self.timeout = settings.request_timeout_seconds if timeout is None else timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CustomsClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def evaluate_operation(
        self,
        request: CustomsOperationRequest,
    ) -> CustomsOperationResponse:
        """Pide las medidas aduaneras de una operación."""
        payload = request.model_dump(exclude_none=True)
        resp = await self.client.post("/customs/evaluate", json=payload)
        resp.raise_for_status()
        return CustomsOperationResponse.model_validate(resp.json())


def make_customs_client() -> CustomsClient:
    return CustomsClient()


def serialize(response: CustomsOperationResponse) -> dict[str, Any]:
    """Convierte la respuesta en un dict JSON-serializable."""
    return response.model_dump()
