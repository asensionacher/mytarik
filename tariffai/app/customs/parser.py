"""
Traducción de las medidas crudas de TARIC al contrato del motor.

El proveedor devuelve las medidas tal cual las publica la Comisión Europea
(códigos de tipo de medida, fórmulas de derecho, notas al pie y condiciones).
Aquí se convierten en bloques con significado aduanero:

    103                → third_country_duty
    142 / 143          → preferential_duties
    551 / 552 / 554    → trade_defense_measures
    117 / 119 / 122    → third_country_duty.variants
    695 / 696          → third_country_duty.variants (aranceles adicionales)
    condiciones 'Y'    → exemption_y_codes
    'document/list'    → border_controls_and_inspections
    'taxes/get'        → base de IVA e impuestos nacionales
"""

from __future__ import annotations

import re
from typing import Any

from app.customs.knowledge import match_border_controls, match_special_regulations
from app.customs.schemas import (
    BorderControl,
    BorderControlCategory,
    CustomsItem,
    DataSource,
    DefenseKind,
    DutyKind,
    DutyMeasure,
    DutyRate,
    ExemptionCode,
    MeasureCategory,
    MeasureCondition,
    MeasureFootnote,
    PreferentialDuty,
    SpecialRegulation,
    SpecialRegulationKind,
    ItemMeasures,
    ThirdCountryDuty,
    TradeDefenseMeasure,
)
from app.customs.taric_client import ProviderResult, RawMeasure

# ── Etiquetas de tipo de medida ────────────────────────────────────────

MEASURE_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "103": ("Arancel de terceros países (Erga Omnes)", "Third country duty (Erga Omnes)"),
    "107": ("Arancel de envíos de poco valor", "Low-value consignment customs duty"),
    "109": ("Unidad suplementaria", "Supplementary unit"),
    "111": ("Unidad suplementaria", "Supplementary unit"),
    "117": ("Suspensión arancelaria", "Tariff suspension"),
    "119": ("Suspensión arancelaria (aeronavegabilidad)", "Airworthiness tariff suspension"),
    "122": ("Contingente arancelario no preferencial", "Non-preferential tariff quota"),
    "123": ("Contingente arancelario preferencial", "Preferential tariff quota"),
    "142": ("Preferencia arancelaria", "Tariff preference"),
    "143": ("Preferencia arancelaria", "Tariff preference"),
    "551": ("Derecho antidumping provisional", "Provisional anti-dumping duty"),
    "552": ("Derecho antidumping definitivo", "Definitive anti-dumping duty"),
    "553": ("Derecho compensatorio provisional", "Provisional countervailing duty"),
    "554": ("Derecho compensatorio definitivo", "Definitive countervailing duty"),
    "555": ("Derecho de salvaguardia", "Safeguard duty"),
    "695": ("Aranceles adicionales", "Additional duties"),
    "696": ("Aranceles adicionales", "Additional duties"),
}


def measure_label(measure_type: str, language: str) -> str:
    """Nombre legible del tipo de medida, con el texto de la fuente como respaldo."""
    label = MEASURE_TYPE_LABELS.get(measure_type)
    if label:
        return label[0] if language == "es" else label[1]
    return ""


def measure_category(measure_type: str, type_name: str = "") -> MeasureCategory:
    """Familia arancelaria de una medida."""
    if measure_type == "103":
        return MeasureCategory.THIRD_COUNTRY_DUTY
    if measure_type in {"142", "143", "144"}:
        return MeasureCategory.PREFERENTIAL
    if measure_type in {"551", "552", "553", "554", "555"}:
        return MeasureCategory.TRADE_DEFENSE
    if measure_type in {"117", "119", "120"}:
        return MeasureCategory.SUSPENSION
    if measure_type in {"122", "123", "124", "145"}:
        return MeasureCategory.QUOTA
    if measure_type in {"695", "696"}:
        return MeasureCategory.ADDITIONAL_DUTY
    if measure_type in {"109", "111", "112", "113", "114", "115"}:
        return MeasureCategory.SUPPLEMENTARY_UNIT
    lowered = type_name.lower()
    if "anti-dumping" in lowered or "antidumping" in lowered:
        return MeasureCategory.TRADE_DEFENSE
    if "countervailing" in lowered:
        return MeasureCategory.TRADE_DEFENSE
    if "safeguard" in lowered:
        return MeasureCategory.TRADE_DEFENSE
    if "tariff preference" in lowered or "preference" in lowered:
        return MeasureCategory.PREFERENTIAL
    if "third country duty" in lowered:
        return MeasureCategory.THIRD_COUNTRY_DUTY
    return MeasureCategory.OTHER


# ── Fórmulas de derecho ────────────────────────────────────────────────

_AD_VALOREM = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*%\s*$")
_SPECIFIC = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([A-Z]{3})\s*(?:/\s*(.+?))?\s*$")


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def parse_duty_formula(formula: str | None) -> DutyRate:
    """
    Interpreta la fórmula del TARIC.

    "12.00%"               → ad valorem 12 %
    "151.20 EUR / 100 kg"  → específico 151,20 EUR por 100 kg
    "3.00 EUR"             → específico 3,00 EUR a tanto alzado
    "12.00% + 1.50 EUR/t"  → compuesto
    """
    if not formula or not formula.strip():
        return DutyRate(kind=DutyKind.UNKNOWN, formula_raw=formula or "")
    raw = formula.strip()

    parts = [part.strip() for part in raw.split("+") if part.strip()]
    if len(parts) > 1:
        ad_valorem: float | None = None
        amount: float | None = None
        currency: str | None = None
        unit: str | None = None
        for part in parts:
            parsed = parse_duty_formula(part)
            if parsed.ad_valorem_percent is not None:
                ad_valorem = (ad_valorem or 0) + parsed.ad_valorem_percent
            if parsed.specific_amount is not None:
                amount = (amount or 0) + parsed.specific_amount
                currency = currency or parsed.specific_currency
                unit = unit or parsed.specific_unit
        return DutyRate(
            kind=DutyKind.COMPOUND,
            ad_valorem_percent=ad_valorem,
            specific_amount=amount,
            specific_currency=currency,
            specific_unit=unit,
            formula_raw=raw,
        )

    match = _AD_VALOREM.match(raw)
    if match:
        return DutyRate(
            kind=DutyKind.AD_VALOREM,
            ad_valorem_percent=_to_float(match.group(1)),
            formula_raw=raw,
        )

    match = _SPECIFIC.match(raw)
    if match:
        return DutyRate(
            kind=DutyKind.SPECIFIC,
            specific_amount=_to_float(match.group(1)),
            specific_currency=match.group(2),
            specific_unit=(match.group(3) or None),
            formula_raw=raw,
        )

    return DutyRate(kind=DutyKind.UNKNOWN, formula_raw=raw)


# ── Condiciones y notas ────────────────────────────────────────────────


def _conditions(measure: RawMeasure) -> list[MeasureCondition]:
    conditions: list[MeasureCondition] = []
    for raw in measure.conditions or []:
        if not isinstance(raw, dict):
            continue
        conditions.append(MeasureCondition(
            sequence_number=str(raw.get("sequenceNumber") or ""),
            description=_clean_html(str(raw.get("description") or "")),
            action_description=_clean_html(str(raw.get("actionDescription") or "")),
            certificate_type=raw.get("certificateType"),
            certificate_number=(
                str(raw.get("certificateNumber"))
                if raw.get("certificateNumber") not in (None, "")
                else None
            ),
            certificate_description=_clean_html(str(raw.get("certificateDescription") or "")),
            condition_expression=raw.get("conditionExpression"),
            tariff_formula=raw.get("tariffFormula"),
        ))
    return conditions


def _clean_html(text: str | None) -> str:
    """La fuente devuelve HTML en algunos campos (saltos de línea, entidades)."""
    if not text:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", text)
    without_tags = (
        without_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", without_tags).strip()


def _footnotes(measure: RawMeasure) -> list[MeasureFootnote]:
    footnotes: list[MeasureFootnote] = []
    for raw in measure.footnotes or []:
        if not isinstance(raw, dict):
            continue
        footnotes.append(MeasureFootnote(
            code=str(raw.get("code") or ""),
            type=str(raw.get("type") or ""),
            text=_clean_html(str(raw.get("text") or "")),
        ))
    return footnotes


def _defense_kind(type_name: str) -> DefenseKind:
    lowered = type_name.lower()
    if "countervailing" in lowered:
        return DefenseKind.COUNTERVAILING
    if "safeguard" in lowered:
        return DefenseKind.SAFEGUARD
    return DefenseKind.ANTI_DUMPING


def _base_measure(measure: RawMeasure, language: str) -> DutyMeasure:
    conditions = _conditions(measure)
    duty = parse_duty_formula(measure.tariffFormula)
    if duty.kind is DutyKind.UNKNOWN and conditions:
        # Hay medidas (por ejemplo los aranceles adicionales 695/696) cuyo tipo
        # no lleva fórmula: el importe real está en sus condiciones.
        for condition in conditions:
            if condition.tariff_formula:
                duty = parse_duty_formula(condition.tariff_formula)
                break
    return DutyMeasure(
        measure_type=measure.measureType,
        measure_type_label=measure_label(measure.measureType, language)
        or measure.type,
        category=measure_category(measure.measureType, measure.type),
        origin=measure.origin,
        geographic_area=measure.geographicalSigl or measure.geographicalArea or "",
        description=measure.type,
        duty=duty,
        valid_from=measure.startDate,
        valid_to=measure.endDate,
        regulation_id=measure.regulationId,
        exclusions=measure.exclusions,
        footnotes=_footnotes(measure),
        conditions=conditions,
    )


def _y_codes(measures: list[RawMeasure], language: str) -> list[ExemptionCode]:
    """Códigos 'Y' exigidos por las condiciones de las medidas."""
    codes: list[ExemptionCode] = []
    seen: set[str] = set()
    for measure in measures:
        for condition in _conditions(measure):
            if (condition.certificate_type or "").upper() != "Y":
                continue
            number = condition.certificate_number or ""
            code = f"Y{number}" if number else "Y"
            if code in seen:
                continue
            seen.add(code)
            codes.append(ExemptionCode(
                code=code,
                description=condition.certificate_description
                or condition.description
                or "Condición arancelaria de exención",
                applies_to=(
                    f"{measure.measureType} {measure.type}".strip()
                    or "medida TARIC"
                ),
                action=(
                    "Declara el código "
                    f"{code} en la casilla 44 del DUA para hacer constar que la "
                    "mercancía cumple la condición de exención."
                    if language == "es" else
                    f"Declare code {code} in box 44 of the customs declaration to state "
                    "that the goods meet the exemption condition."
                ),
            ))
    return codes


# ── Documentos y requisitos ────────────────────────────────────────────

#: Documentos de A2M que son normativa ambiental y no un control fronterizo.
_DOCUMENT_REGULATIONS: dict[str, SpecialRegulationKind] = {
    "spfgg": SpecialRegulationKind.F_GAS,
    "lbltyre": SpecialRegulationKind.ENERGY_LABELLING,
    "stdvehic": SpecialRegulationKind.VEHICLE_TECHNICAL,
    "spwaste": SpecialRegulationKind.WASTE_CONTROL,
}

_DOCUMENT_REGULATION_NAMES: dict[SpecialRegulationKind, tuple[str, str]] = {
    SpecialRegulationKind.F_GAS: (
        "Comercialización de productos con gases fluorados",
        "Marketing of products containing fluorinated greenhouse gases",
    ),
    SpecialRegulationKind.ENERGY_LABELLING: (
        "Etiquetado de eficiencia energética",
        "Energy efficiency labelling",
    ),
    SpecialRegulationKind.VEHICLE_TECHNICAL: (
        "Requisitos técnicos de los vehículos",
        "Technical requirements for motor vehicles",
    ),
    SpecialRegulationKind.WASTE_CONTROL: (
        "Control de residuos",
        "Waste control",
    ),
}


def _documents_to_controls(
    documents: list[dict[str, Any]], language: str
) -> list[BorderControl]:
    controls: list[BorderControl] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        code = str(document.get("code") or "")
        label = str(document.get("label") or "")
        doc_type = str(document.get("type") or "")
        code = code.removesuffix(".html")
        if not code or code == "overview":
            continue
        if code.startswith("preforig") or code == "cernonpreforig":
            controls.append(BorderControl(
                category=BorderControlCategory.DOCUMENT,
                code=code,
                title=label,
                requirement=(
                    "Debe acreditarse el origen de la mercancía para "
                    "aplicar el régimen preferencial o evitar el arancel de terceros países."
                    if language == "es" else
                    "The origin of the goods must be evidenced to claim the preferential "
                    "regime or to avoid the third country duty."
                ),
                mandatory=True,
                source=DataSource.A2M_DOCUMENT,
            ))
            continue
        if doc_type == "s":
            # Requisito sectorial: se trata como normativa especial.
            continue
        controls.append(BorderControl(
            category=BorderControlCategory.DOCUMENT,
            code=code,
            title=label,
            requirement=(
                f"Documento exigible en el despacho: {label}."
                if language == "es" else
                f"Document required for clearance: {label}."
            ),
            mandatory=True,
            source=DataSource.A2M_DOCUMENT,
        ))
    return controls


def _documents_to_regulations(
    documents: list[dict[str, Any]], language: str
) -> list[SpecialRegulation]:
    regulations: list[SpecialRegulation] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        code = str(document.get("code") or "")
        kind = _DOCUMENT_REGULATIONS.get(code)
        if kind is None:
            continue
        name = _DOCUMENT_REGULATION_NAMES.get(kind)
        regulations.append(SpecialRegulation(
            regulation=kind,
            name=(name[0] if language == "es" else name[1]) if name else code,
            applies=True,
            reference=(
                "Requisito publicado por Access2Markets para la partida y el flujo "
                "consultados"
                if language == "es" else
                "Requirement published by Access2Markets for the queried line and flow"
            ),
            reason=(
                f"La fuente en vivo señala este requisito para la partida consultada: "
                f"{document.get('label')}."
                if language == "es" else
                f"The live source flags this requirement for the queried line: "
                f"{document.get('label')}."
            ),
            action_required=(
                "Consulta el texto del requisito en Access2Markets y cumple la "
                "documentación que exige antes del despacho."
                if language == "es" else
                "Read the requirement text in Access2Markets and provide the requested "
                "documentation before clearance."
            ),
            source=DataSource.A2M_DOCUMENT,
        ))
    return regulations


# ── Impuestos nacionales ───────────────────────────────────────────────


def vat_rate(taxes: list[dict[str, Any]]) -> float | None:
    for tax in taxes:
        if not isinstance(tax, dict):
            continue
        if str(tax.get("taxType") or "").upper() != "VAT":
            continue
        rate = str(tax.get("taxRate") or "").strip()
        match = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*%", rate)
        if match:
            return _to_float(match.group(1))
    return None


def _excise_regulations(
    taxes: list[dict[str, Any]], language: str
) -> list[SpecialRegulation]:
    regulations: list[SpecialRegulation] = []
    for tax in taxes:
        if not isinstance(tax, dict):
            continue
        if str(tax.get("taxType") or "").upper() != "EXC":
            continue
        note = str(tax.get("noteFileContent") or "")
        label = str(tax.get("taxLabel") or "")
        is_plastic = "plastic" in note.lower() or "plástico" in note.lower()
        if not is_plastic:
            continue
        regulations.append(SpecialRegulation(
            regulation=SpecialRegulationKind.PLASTIC_TAX,
            name=(
                "Impuesto especial sobre plásticos de un solo uso"
                if language == "es" else
                "Plastic packaging tax"
            ),
            applies=True,
            reference=(
                "Tasa especial del país de destino publicada por la fuente"
                if language == "es" else
                "Special tax of the destination country published by the source"
            ),
            reason=(
                f"El país de destino grava los envases plásticos no reutilizables: "
                f"{label or note[:160]}".strip()
                if language == "es" else
                f"The destination country taxes non-recyclable plastic packaging: "
                f"{label or note[:160]}".strip()
            ),
            action_required=(
                "Incluye el importe del impuesto en el cálculo del coste y comprueba si "
                "la partida está exenta por no contener envases de plástico no reciclable."
                if language == "es" else
                "Include the tax in the cost calculation and check whether the line is "
                "exempt for not containing non-recyclable plastic packaging."
            ),
            source=DataSource.A2M_DOCUMENT,
        ))
    return regulations


# ── Construcción de la partida ─────────────────────────────────────────


def build_item_measures(
    result: ProviderResult,
    item: CustomsItem,
    language: str = "en",
    operation_type: str = "IMPORT",
    destination_country: str = "ES",
    line_number: int = 1,
) -> ItemMeasures:
    """Convierte la respuesta cruda del proveedor en el desglose de la partida."""
    measures = result.flat_measures

    third_country: ThirdCountryDuty | None = None
    base_candidates: list[DutyMeasure] = []
    variants: list[DutyMeasure] = []
    preferential: list[PreferentialDuty] = []
    defense: list[TradeDefenseMeasure] = []

    for measure in measures:
        category = measure_category(measure.measureType, measure.type)
        base = _base_measure(measure, language)

        if category is MeasureCategory.THIRD_COUNTRY_DUTY:
            base_candidates.append(base)
            continue

        if category is MeasureCategory.PREFERENTIAL:
            preferential.append(PreferentialDuty(
                **base.model_dump(),
                agreement=measure.origin or measure.geographicalSigl or "",
            ))
            continue

        if category is MeasureCategory.TRADE_DEFENSE:
            defense.append(_defense_measure(measure, language))
            continue

        if category is MeasureCategory.SUPPLEMENTARY_UNIT:
            continue

        variants.append(base)

    if base_candidates:
        third_country = ThirdCountryDuty(**base_candidates[0].model_dump())
        variants = base_candidates[1:] + variants

    if third_country is not None:
        third_country.variants = _dedupe_measures(variants, [third_country])
    elif variants:
        # Sin arancel base (103) pero con otras medidas aplicables: se conservan
        # como variantes para que no se pierdan (sanciones, contingentes…).
        third_country = ThirdCountryDuty(variants=_dedupe_measures(variants))

    # Prueba de origen: condiciones de las medidas preferenciales + documentos.
    proof_of_origin = _proof_of_origin(measures, result.documents, language)
    for duty in preferential:
        duty.proof_of_origin = list(proof_of_origin)

    controls = _documents_to_controls(result.documents, language)
    controls.extend(match_border_controls(item.taric_code, language, country=destination_country))

    regulations = _documents_to_regulations(result.documents, language)
    regulations.extend(_excise_regulations(result.taxes, language))
    regulations.extend(match_special_regulations(
        item.taric_code,
        language=language,
        operation_type=operation_type,
        destination_country=destination_country,
    ))

    return ItemMeasures(
        line_number=line_number,
        taric_code=item.taric_code,
        description=item.description,
        product_description=result.product_description,
        third_country_duty=third_country,
        preferential_duties=preferential,
        trade_defense_measures=defense,
        border_controls_and_inspections=controls,
        environmental_and_special_regulations=regulations,
        exemption_y_codes=_y_codes(measures, language),
    )


def _measure_key(measure: DutyMeasure) -> tuple:
    return (
        measure.measure_type,
        measure.origin,
        measure.duty.formula_raw,
        measure.duty.ad_valorem_percent,
        measure.duty.specific_amount,
        measure.duty.specific_unit,
        measure.regulation_id,
    )


def _dedupe_measures(
    measures: list[DutyMeasure], already_seen: list[DutyMeasure] | None = None
) -> list[DutyMeasure]:
    """
    Elimina duplicados.

    La fuente devuelve las mismas medidas repetidas en cada rama de la
    nomenclatura por debajo de la partida (por ejemplo, dos subpartidas de vino
    con el mismo arancel): al usuario le interesa una vez.
    """
    seen: set[tuple] = set()
    if already_seen:
        seen.update(_measure_key(measure) for measure in already_seen)
    unique: list[DutyMeasure] = []
    for measure in measures:
        key = _measure_key(measure)
        if key in seen:
            continue
        seen.add(key)
        unique.append(measure)
    return unique


def _defense_measure(measure: RawMeasure, language: str) -> TradeDefenseMeasure:
    """Derecho de defensa comercial, con el tipo por fabricante cuando existe."""
    base = _base_measure(measure, language)
    conditions = base.conditions

    declared: DutyRate | None = None
    residual: DutyRate | None = None
    certificate_code: str | None = None
    certificate_description = ""

    for condition in conditions:
        formula = condition.tariff_formula
        if not formula:
            continue
        parsed = parse_duty_formula(formula)
        if condition.certificate_type:
            if declared is None:
                declared = parsed
                certificate_code = (
                    f"{condition.certificate_type}{condition.certificate_number or ''}"
                )
                certificate_description = condition.certificate_description
        elif residual is None:
            residual = parsed

    duty = declared or base.duty
    if residual is not None and declared is not None:
        base.duty = declared

    return TradeDefenseMeasure(
        **base.model_dump(),
        defense_kind=_defense_kind(measure.type),
        additional_code=measure.additionalCodeId,
        additional_code_text=_clean_html(measure.additionalCodeText),
        certificate_code=certificate_code,
        certificate_description=certificate_description,
        residual_duty=residual,
    )


def _proof_of_origin(
    measures: list[RawMeasure], documents: list[dict[str, Any]], language: str
) -> list[str]:
    """Pruebas de origen exigibles según las medidas y los documentos publicados."""
    proofs: list[str] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        code = str(document.get("code") or "")
        label = str(document.get("label") or "")
        if code.startswith("preforig") or code == "cernonpreforig":
            if label and label not in proofs:
                proofs.append(label)

    for measure in measures:
        if measure_category(measure.measureType, measure.type) is not MeasureCategory.PREFERENTIAL:
            continue
        for condition in _conditions(measure):
            if not condition.certificate_type or condition.certificate_type == "Y":
                continue
            label = condition.certificate_description or condition.description
            if label and label not in proofs:
                proofs.append(label)

    generic = (
        "Prueba de origen exigida por el acuerdo aplicable (EUR.1, declaración en "
        "factura o comunicación REX, según el país de origen)"
        if language == "es" else
        "Proof of origin required by the applicable agreement (EUR.1, invoice "
        "declaration or REX statement, depending on the country of origin)"
    )
    if generic not in proofs:
        proofs.append(generic)
    return proofs
