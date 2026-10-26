"""
Capa de interpretación con LLM.

Las medidas que devuelve el TARIC vienen en forma de códigos: `C644`, `N851`,
`L135`, `Y929`, notas al pie con numeración LAW, tipos de medida `552`… Un
usuario de aduanas no puede leer eso. Aquí se pide al deployment de Foundry un
resumen ejecutivo por partida, en el idioma de la petición, con tres preguntas:

1. Qué arancel real se paga y cómo bajarlo al 0 % si hay acuerdo preferencial.
2. Qué controles en frontera o normativas especiales afectan de verdad.
3. Qué códigos "Y" exactos hay que declarar en el DUA.

Reglas de seguridad: el modelo sólo puede mencionar códigos "Y" que aparecen en
los datos de entrada (los que no, se descartan), y los importes y códigos los
copia literalmente. Si el modelo falla, la respuesta se devuelve igualmente
con los datos estructurados y sin resumen.
"""

from __future__ import annotations

import asyncio
import logging

from app.customs.schemas import (
    CustomsOperationRequest,
    CustomsRegime,
    ExecutiveSummary,
    ItemMeasures,
)
from app.llm_provider import extract_json, get_provider

logger = logging.getLogger(__name__)


INTERPRETATION_SYSTEM_PROMPT = """You are a customs compliance analyst for European Union imports and exports.
You receive the real customs measures of one commercial operation, per product line, already
fetched from the EU TARIC / Access2Markets datasets.

Your job is to explain each line in plain customs language. You MUST answer with a single JSON
object (no markdown fences, no preamble) with this exact shape:

{
  "items": [
    {
      "line_number": 1,
      "duty_to_pay": "What the importer really pays on this line, with the amount or rate and the currency, in one or two sentences",
      "how_to_reduce_to_zero": "How the duty can be reduced to 0% (preference agreement, proof of origin, additional code, suspension), or null when nothing applies",
      "border_controls": ["Concrete border controls, certificates or documents that really apply to this line"],
      "special_regulations": ["CBAM, EUDR, dual use, sanctions, F-gas, RoHS… only the ones that really affect this line, with the action required"],
      "y_codes_to_declare": ["Y155"],
      "warnings": ["Anything that can block the clearance or that the declarant must check first"],
      "needs_human_review": false
    }
  ]
}

Rules:
  - Return exactly one entry per input line, with the same line_number.
  - Use ONLY the "Y" codes listed in the input for that line. Never invent a code.
  - Copy rates, amounts, currencies and additional codes exactly as they appear. Do not recalculate.
  - If a line has no duty, say so explicitly and explain why (intra-EU, suspension, 0% preference).
  - If the line is an export to a third country, remember that the EU does not levy export duties:
    focus on prohibitions, sanctions and export licences instead of tariffs.
  - A warning must be actionable: name the regulation or the document the declarant must obtain.
  - Write the prose in the language requested in the instruction below. Keep codes, rates and
    document codes untranslated.
  - If you are not sure about a conclusion, say it plainly in warnings and set needs_human_review."""


def _format_measure(measure: dict) -> str:
    parts = [f"- {measure.get('measure_type', '')} {measure.get('measure_type_label', '')}".strip()]
    if measure.get("origin"):
        parts.append(f"origen={measure['origin']}")
    if measure.get("duty"):
        parts.append(f"fórmula={measure['duty'].get('formula_raw') or measure['duty'].get('kind')}")
    if measure.get("valid_from"):
        parts.append(f"vigente_desde={measure['valid_from']}")
    if measure.get("valid_to"):
        parts.append(f"vigente_hasta={measure['valid_to']}")
    if measure.get("regulation_id"):
        parts.append(f"reglamento={measure['regulation_id']}")
    if measure.get("additional_code"):
        parts.append(f"codigo_adicional={measure['additional_code']}")
    if measure.get("additional_code_text"):
        parts.append(f"descripcion_codigo={measure['additional_code_text'][:120]}")
    if measure.get("exclusions"):
        parts.append(f"exclusiones={measure['exclusions']}")
    if measure.get("proof_of_origin"):
        parts.append(f"prueba_origen={' | '.join(measure['proof_of_origin'])}")
    for condition in measure.get("conditions") or []:
        bits = [str(condition.get("certificate_type") or ""), str(condition.get("certificate_number") or "")]
        code = "".join(bits)
        if code:
            parts.append(f"condicion[{code}]={condition.get('certificate_description') or ''}")
    return " ".join(part for part in parts if part)


def _format_item(item: ItemMeasures) -> str:
    lines = [f"### Línea {item.line_number} — TARIC {item.taric_code} — {item.description}"]
    if item.product_description:
        lines.append(f"Denominación CN: {item.product_description}")

    if item.third_country_duty:
        duty = item.third_country_duty
        lines.append(f"Arancel base: {_format_measure(duty.model_dump())}")
        for variant in duty.variants:
            lines.append(f"Variante: {_format_measure(variant.model_dump())}")

    for pref in item.preferential_duties:
        lines.append(f"Preferencial: {_format_measure(pref.model_dump())}")

    defenses = item.trade_defense_measures
    if defenses:
        if len(defenses) <= 8:
            for defense in defenses:
                lines.append(f"Defensa comercial: {_format_measure(defense.model_dump())}")
                if defense.residual_duty:
                    lines.append(
                        f"  derecho residual para el resto de fabricantes: "
                        f"{defense.residual_duty.formula_raw}"
                    )
        else:
            # Un derecho antidumping puede traer decenas de fabricantes: se
            # resumen las tasas y se citan algunos códigos adicionales.
            rates = sorted({
                defense.duty.formula_raw for defense in defenses if defense.duty.formula_raw
            })
            residual = next(
                (
                    defense.residual_duty.formula_raw
                    for defense in defenses
                    if defense.residual_duty is not None
                ),
                None,
            )
            codes = ", ".join(
                defense.additional_code for defense in defenses[:8] if defense.additional_code
            )
            lines.append(
                f"Defensa comercial: {len(defenses)} productores con código adicional "
                f"({codes}…). Tasas declaradas: {', '.join(rates)}."
                + (f" Tasa residual para el resto: {residual}." if residual else "")
            )

    for control in item.border_controls_and_inspections:
        lines.append(
            f"Control fronterizo [{control.category}] {control.code}: {control.title} "
            f"({control.source.value})"
        )

    for regulation in item.environmental_and_special_regulations:
        lines.append(
            f"Normativa [{regulation.regulation}] {regulation.name} "
            f"ref={regulation.reference or 'n/d'} ({regulation.source.value})"
        )

    codes = ", ".join(code.code for code in item.exemption_y_codes) or "ninguno"
    lines.append(f"Códigos Y disponibles: {codes}")
    return "\n".join(lines)


async def interpret_operation(
    request: CustomsOperationRequest,
    items: list[ItemMeasures],
) -> dict[int, ExecutiveSummary]:
    """
    Genera el resumen ejecutivo por partida.

    Devuelve un diccionario `line_number -> ExecutiveSummary`. Ante cualquier
    fallo devuelve un diccionario vacío: la respuesta estructurada sigue siendo
    válida sin resumen.
    """
    if not items:
        return {}

    language_name = {"es": "Spanish", "en": "English"}[request.language]
    system = (
        f"{INTERPRETATION_SYSTEM_PROMPT}\n\n"
        f"Write every prose field in {language_name}. Keep codes, rates, amounts, "
        "currencies and document codes exactly as they appear in the input."
    )

    context = [
        f"Operation: {request.operation_type}",
        f"Origin: {request.origin_country}",
        f"Destination: {request.destination_country}",
        f"Incoterm: {request.incoterm or 'not specified'}",
        "",
    ]
    context.extend(_format_item(item) for item in items)
    user = (
        "## Customs measures of the operation\n\n"
        + "\n\n".join(context)
        + "\n\n## Task\n"
        "Explain each line for a customs declarer who does not know the TARIC codes. "
        "Respond with ONLY the JSON object."
    )

    try:
        response = await asyncio.to_thread(
            get_provider().complete, system=system, user=user
        )
    except Exception:
        logger.exception("Fallo en la interpretación LLM de las medidas aduaneras")
        return {}

    try:
        payload = extract_json(response.text)
    except ValueError:
        logger.exception("La interpretación LLM no devolvió JSON válido")
        return {}

    summaries: dict[int, ExecutiveSummary] = {}
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return {}

    by_line = {item.line_number: item for item in items}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        line_number = raw.get("line_number")
        try:
            line_number = int(line_number)
        except (TypeError, ValueError):
            continue
        item = by_line.get(line_number)
        if item is None:
            continue

        allowed_y = {code.code for code in item.exemption_y_codes}
        declared_y = [str(code) for code in (raw.get("y_codes_to_declare") or [])]
        valid_y = [code for code in declared_y if code in allowed_y]
        discarded = [code for code in declared_y if code not in allowed_y]
        if discarded:
            logger.warning(
                "La interpretación pidió códigos Y no presentes en TARIC (línea %s): %s",
                line_number, ", ".join(discarded),
            )

        warnings = [str(w) for w in (raw.get("warnings") or [])]
        if discarded:
            warnings.append(
                f"El resumen mencionó códigos no verificados "
                f"({', '.join(discarded)}); se han descartado."
                if request.language == "es" else
                f"The summary mentioned unverified codes "
                f"({', '.join(discarded)}); they were discarded."
            )

        summaries[line_number] = ExecutiveSummary(
            duty_to_pay=str(raw.get("duty_to_pay") or ""),
            how_to_reduce_to_zero=(
                str(raw["how_to_reduce_to_zero"]) if raw.get("how_to_reduce_to_zero") else None
            ),
            border_controls=[str(c) for c in (raw.get("border_controls") or [])],
            special_regulations=[str(c) for c in (raw.get("special_regulations") or [])],
            y_codes_to_declare=valid_y,
            warnings=warnings,
            needs_human_review=bool(raw.get("needs_human_review")),
        )
    return summaries


def deterministic_summary(
    item: ItemMeasures,
    request: CustomsOperationRequest,
    regime: CustomsRegime | None = None,
) -> ExecutiveSummary:
    """
    Resumen sin LLM.

    Se usa en operaciones intracomunitarias, cuando el modelo no está
    disponible o cuando su respuesta no es utilizable.
    """
    language = request.language
    duties: list[str] = []
    warnings: list[str] = []

    if regime in (CustomsRegime.INTRA_UNION, CustomsRegime.INTRA_UNION_TERRITORIAL_EXCEPTION):
        duty_text = (
            "No se aplican aranceles: la operación es intracomunitaria y no requiere DUA."
            if language == "es" else
            "No duties apply: the operation is intra-EU and no customs declaration is required."
        )
    elif request.operation_type == "EXPORT":
        duty_text = (
            "La Unión Europea no grava las exportaciones: no hay arancel de importación "
            "que aplicar en esta operación. El arancel del país de destino no está en "
            "el TARIC."
            if language == "es" else
            "The European Union does not levy export duties: there is no import duty to "
            "apply in this operation. The destination country's duty is not in the TARIC."
        )
    else:
        base = item.third_country_duty
        if base is not None and base.duty.formula_raw:
            duties.append(f"Arancel base: {base.duty.formula_raw} ({base.measure_type_label})")
        for preference in item.preferential_duties:
            duties.append(
                f"Régimen preferencial de {preference.agreement or 'la UE'}: "
                f"{preference.duty.formula_raw or 'sin tasa visible'}"
            )
        for defense in item.trade_defense_measures[:3]:
            duties.append(
                f"Derecho de defensa comercial ({defense.measure_type_label}) con tasa "
                f"{defense.duty.formula_raw} para el código adicional "
                f"{defense.additional_code or 'no especificado'}"
            )
        if len(item.trade_defense_measures) > 3:
            duties.append(
                f"Y otros {len(item.trade_defense_measures) - 3} derechos de defensa "
                "comercial con códigos de fabricante distintos."
            )
        if duties:
            duty_text = " | ".join(duties)
        elif language == "es":
            duty_text = "No se ha identificado un arancel aplicable en la fuente para esta partida."
        else:
            duty_text = "No applicable duty was identified in the source for this line."

    if item.exemption_y_codes:
        warnings.append(
            "Códigos Y a declarar en la casilla 44 del DUA: "
            + ", ".join(code.code for code in item.exemption_y_codes)
            if language == "es" else
            "Y codes to declare in box 44 of the customs declaration: "
            + ", ".join(code.code for code in item.exemption_y_codes)
        )

    return ExecutiveSummary(
        duty_to_pay=duty_text,
        how_to_reduce_to_zero=None,
        border_controls=[control.title for control in item.border_controls_and_inspections[:5]],
        special_regulations=[
            regulation.name for regulation in item.environmental_and_special_regulations[:5]
        ],
        y_codes_to_declare=[code.code for code in item.exemption_y_codes],
        warnings=warnings,
        needs_human_review=False,
    )
