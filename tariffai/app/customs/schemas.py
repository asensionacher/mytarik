"""
Modelos Pydantic v2 del motor de medidas aduaneras.

Contrato de entrada: el frontend envía el contexto comercial de la operación
(una sola `trade` por factura) y la lista de partidas ya clasificadas.
Contrato de salida: un desglose por partida con aranceles, preferencias,
defensas comerciales, controles fronterizos, normativa especial, códigos "Y"
y la estimación de impuestos.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResponseLanguage = Literal["es", "en"]
OperationType = Literal["IMPORT", "EXPORT"]


class CustomsRegime(StrEnum):
    """Régimen aduanero que se aplica a la operación."""

    INTRA_UNION = "INTRA_UNION"
    INTRA_UNION_TERRITORIAL_EXCEPTION = "INTRA_UNION_TERRITORIAL_EXCEPTION"
    IMPORT_FROM_THIRD_COUNTRY = "IMPORT_FROM_THIRD_COUNTRY"
    EXPORT_TO_THIRD_COUNTRY = "EXPORT_TO_THIRD_COUNTRY"


class ReportingRequirement(StrEnum):
    """Obligaciones de información statistics/fiscal que genera la operación."""

    INTRSTAT = "INTRSTAT"
    VAT_INTRA_COMMUNITY = "VAT_INTRA_COMMUNITY"
    VAT_IMPORT = "VAT_IMPORT"
    IGIC = "IGIC"
    AIEM = "AIEM"
    AX_VAT = "AX_VAT"
    CUSTOMS_DECLARATION = "CUSTOMS_DECLARATION"
    EXPORT_DECLARATION = "EXPORT_DECLARATION"


class DutyKind(StrEnum):
    AD_VALOREM = "ad_valorem"
    SPECIFIC = "specific"
    COMPOUND = "compound"
    UNKNOWN = "unknown"


class MeasureCategory(StrEnum):
    """Familia arancelaria de una medida TARIC."""

    THIRD_COUNTRY_DUTY = "third_country_duty"
    PREFERENTIAL = "preferential"
    TRADE_DEFENSE = "trade_defense"
    SUSPENSION = "suspension"
    QUOTA = "quota"
    ADDITIONAL_DUTY = "additional_duty"
    SUPPLEMENTARY_UNIT = "supplementary_unit"
    OTHER = "other"


class DefenseKind(StrEnum):
    ANTI_DUMPING = "ANTI_DUMPING"
    COUNTERVAILING = "COUNTERVAILING"
    SAFEGUARD = "SAFEGUARD"


class BorderControlCategory(StrEnum):
    SPS = "SPS"
    TBT = "TBT"
    DOCUMENT = "DOCUMENT"
    INSPECTION = "INSPECTION"
    CUSTOMS_CONTROL = "CUSTOMS_CONTROL"


class SpecialRegulationKind(StrEnum):
    CBAM = "CBAM"
    EUDR = "EUDR"
    ROHS = "ROHS"
    F_GAS = "F_GAS"
    PLASTIC_TAX = "PLASTIC_TAX"
    DUAL_USE = "DUAL_USE"
    SANCTIONS = "SANCTIONS"
    REACH = "REACH"
    WEEE = "WEEE"
    ENERGY_LABELLING = "ENERGY_LABELLING"
    WASTE_CONTROL = "WASTE_CONTROL"
    VEHICLE_TECHNICAL = "VEHICLE_TECHNICAL"


class DataSource(StrEnum):
    """Origen de un dato, para que la UI distinga lo verificado de lo inferido."""

    LIVE = "live"
    CACHE = "cache"
    TARIC_MEASURE = "taric_measure"
    A2M_DOCUMENT = "a2m_document"
    KNOWLEDGE_BASE = "knowledge_base"
    LLM = "llm"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


# ── Entrada ────────────────────────────────────────────────────────────


class CustomsItem(BaseModel):
    """Una partida ya clasificada sobre la que se determina la medida."""

    model_config = ConfigDict(extra="forbid")

    taric_code: str = Field(
        ..., pattern=r"^\d{10}$", description="Código TARIC de 10 dígitos, p. ej. '0210113100'",
    )
    description: str = Field(..., min_length=1, max_length=1000)
    customs_value: float | None = Field(
        default=None, gt=0, description="Valor en aduana de la mercancía",
    )
    currency: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$", description="Moneda del valor, p. ej. 'EUR'",
    )
    net_weight_kg: float | None = Field(
        default=None, gt=0, description="Peso neto en kg (necesario para derechos específicos)",
    )
    supplementary_units: float | None = Field(
        default=None, ge=0, description="Unidades suplementarias (litros, pares, piezas…)",
    )


class CustomsOperationRequest(BaseModel):
    """Contexto comercial y partidas de una operación aduanera."""

    model_config = ConfigDict(extra="forbid")

    operation_type: OperationType = Field(..., description="'IMPORT' o 'EXPORT'")
    origin_country: str = Field(
        ..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$",
        description="País de origen (ISO 3166-1 alfa-2)",
    )
    destination_country: str = Field(
        ..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$",
        description="País de destino (ISO 3166-1 alfa-2)",
    )
    incoterm: str | None = Field(
        default=None, max_length=3, pattern=r"^[A-Z]{3}$",
        description="Incoterm (EXW, FCA, FOB, CFR, CIF, CPT, CIP, DAP, DPU, DDP)",
    )
    language: ResponseLanguage = Field(default="en", description="Idioma de la interpretación")
    origin_subdivision: str | None = Field(
        default=None, max_length=6, pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$",
        description="Subdivisión ISO 3166-2 del origen (p. ej. 'ES-CN' Canarias, 'PT-20' Açores)",
    )
    destination_subdivision: str | None = Field(
        default=None, max_length=6, pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$",
        description="Subdivisión ISO 3166-2 del destino",
    )
    items: list[CustomsItem] = Field(..., min_length=1, max_length=50)


# ── Piezas de medida ───────────────────────────────────────────────────


class DutyRate(BaseModel):
    """Tipo de derecho: ad valorem, específico o compuesto."""

    kind: DutyKind = DutyKind.UNKNOWN
    ad_valorem_percent: float | None = Field(default=None, ge=0, le=1000)
    specific_amount: float | None = Field(default=None, ge=0)
    specific_currency: str | None = None
    specific_unit: str | None = Field(
        default=None, description="Unidad del derecho específico, p. ej. '100 kg net'",
    )
    formula_raw: str = Field(default="", description="Fórmula original devuelta por la fuente")


class MeasureFootnote(BaseModel):
    code: str = ""
    type: str = ""
    text: str = ""


class MeasureCondition(BaseModel):
    """Condición de aplicación de una medida (certificados, requisitos)."""

    sequence_number: str = ""
    description: str = ""
    action_description: str = ""
    certificate_type: str | None = Field(
        default=None, description="Tipo de certificado TARIC: 'Y', 'D', 'A'…",
    )
    certificate_number: str | None = None
    certificate_description: str = ""
    condition_expression: str | None = None
    tariff_formula: str | None = None


class DutyMeasure(BaseModel):
    """Medida arancelaria genérica (base de la que derivan los bloques)."""

    measure_type: str = Field(default="", description="Código de tipo de medida TARIC (103, 142…)")
    measure_type_label: str = Field(default="", description="Tipo de medida en lenguaje claro")
    category: MeasureCategory = MeasureCategory.OTHER
    origin: str = Field(default="", description="Origen aplicable, p. ej. 'ERGA OMNES' o 'Chile'")
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
    """Arancel base Erga Omnes (medida 103) aplicable a la partida."""

    duty: DutyRate = Field(default_factory=DutyRate)
    variants: list[DutyMeasure] = Field(
        default_factory=list,
        description="Medidas arancelarias alternativas (suspensiones, contingentes, valor bajo)",
    )


class PreferentialDuty(DutyMeasure):
    """Arancel preferencial o contingente por acuerdo (medidas 142/143)."""

    agreement: str = Field(default="", description="Acuerdo UE de origen")
    proof_of_origin: list[str] = Field(
        default_factory=list, description="Prueba de origen exigida (EUR.1, REX, factura…)",
    )


class TradeDefenseMeasure(DutyMeasure):
    """Derecho antidumping o compensatorio (medidas 551–554)."""

    defense_kind: DefenseKind = DefenseKind.ANTI_DUMPING
    additional_code: str | None = Field(
        default=None, description="Código adicional TARIC (p. ej. '88CO')",
    )
    additional_code_text: str | None = Field(
        default=None, description="Descripción del código adicional (fabricante)",
    )
    certificate_code: str | None = Field(
        default=None, description="Certificado exigido, p. ej. 'D008'",
    )
    certificate_description: str = ""
    residual_duty: DutyRate | None = Field(
        default=None, description="Derecho residual aplicable a los demás productores",
    )
    proof_of_origin: list[str] = Field(default_factory=list)


class BorderControl(BaseModel):
    """Control fronterizo, inspección o documento exigible en el despacho."""

    category: BorderControlCategory = BorderControlCategory.DOCUMENT
    code: str = Field(default="", description="Código del requisito (p. ej. 'spfgg', 'CHED-P')")
    title: str = ""
    authority: str | None = Field(
        default=None, description="Autoridad competente (SOIVRE, PCF, CHED, autoridad nacional)",
    )
    requirement: str = Field(default="", description="Qué hay que cumplir en la frontera")
    mandatory: bool = True
    source: DataSource = DataSource.UNKNOWN


class SpecialRegulation(BaseModel):
    """Normativa no arancelaria que puede bloquear o encarecer el despacho."""

    regulation: SpecialRegulationKind = SpecialRegulationKind.REACH
    name: str = ""
    applies: bool = True
    reference: str | None = Field(default=None, description="Reglamento o directiva aplicable")
    reason: str = ""
    action_required: str | None = None
    source: DataSource = DataSource.UNKNOWN


class ExemptionCode(BaseModel):
    """Código "Y" a declarar en la casilla 44 del DUA."""

    code: str = Field(default="", description="Código completo, p. ej. 'Y155'")
    description: str = ""
    applies_to: str = Field(default="", description="Medida que lo exige")
    action: str = Field(default="", description="Qué hacer con él en el DUA")


class TaxEstimation(BaseModel):
    """Estimación de derechos y base de IVA a partir del valor declarado."""

    currency: str = "EUR"
    customs_value: float = 0.0
    estimated_duty: float = Field(default=0.0, ge=0)
    duty_breakdown: list[str] = Field(default_factory=list)
    estimated_vat_base: float = Field(default=0.0, ge=0)
    estimated_vat_rate: float | None = Field(default=None, ge=0, le=100)
    estimated_vat: float | None = Field(default=None, ge=0)
    incoterm_adjustment: str | None = None
    formula: str = ""
    notes: list[str] = Field(default_factory=list)


class ExecutiveSummary(BaseModel):
    """Resumen ejecutivo en lenguaje aduanero generado por el LLM."""

    duty_to_pay: str = ""
    how_to_reduce_to_zero: str | None = None
    border_controls: list[str] = Field(default_factory=list)
    special_regulations: list[str] = Field(default_factory=list)
    y_codes_to_declare: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    needs_human_review: bool = False


class ItemProvenance(BaseModel):
    """Trazabilidad del dato de cada partida."""

    provider: str = Field(default="", description="Proveedor que atendió la consulta")
    source: DataSource = DataSource.UNKNOWN
    cache_hit: bool = False
    queried_code: str | None = Field(default=None, description="Código realmente consultado")
    raw_measure_count: int = 0
    fetched_at: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ItemMeasures(BaseModel):
    """Desglose de medidas de una partida."""

    line_number: int = Field(..., ge=1, description="Número de línea en el DUA")
    taric_code: str
    description: str
    product_description: str | None = Field(
        default=None, description="Descripción de la nomenclatura combinada devuelta por la fuente",
    )
    third_country_duty: ThirdCountryDuty | None = None
    preferential_duties: list[PreferentialDuty] = Field(default_factory=list)
    trade_defense_measures: list[TradeDefenseMeasure] = Field(default_factory=list)
    border_controls_and_inspections: list[BorderControl] = Field(default_factory=list)
    environmental_and_special_regulations: list[SpecialRegulation] = Field(default_factory=list)
    exemption_y_codes: list[ExemptionCode] = Field(default_factory=list)
    tax_estimation: TaxEstimation | None = None
    executive_summary: ExecutiveSummary | None = None
    provenance: ItemProvenance = Field(default_factory=ItemProvenance)


# ── Salida ─────────────────────────────────────────────────────────────


class CustomsOperationResponse(BaseModel):
    """Respuesta del motor de medidas aduaneras."""

    status: Literal["ok", "partial", "error"] = "ok"
    operation_type: OperationType
    origin_country: str
    destination_country: str
    incoterm: str | None = None
    customs_regime: CustomsRegime = CustomsRegime.IMPORT_FROM_THIRD_COUNTRY
    territorial_note: str | None = Field(
        default=None, description="Explicación del régimen territorial aplicado",
    )
    reporting_requirements: list[ReportingRequirement] = Field(default_factory=list)
    items_measures: list[ItemMeasures] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str = ""
    cache_hits: int = 0
    processing_time_ms: float = 0.0
    error: str | None = None
