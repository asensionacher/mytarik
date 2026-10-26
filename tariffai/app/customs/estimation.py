"""
Estimación de derechos y base de IVA.

Con el valor en aduana declarado, el peso neto y las unidades suplementarias se
puede estimar el importe del arancel y la base del IVA de importación
(valor + arancel). Los derechos específicos (por 100 kg, por hl, por unidad)
necesitan una magnitud: se usa el peso neto para los derechos en peso y las
unidades suplementarias para el resto.

Cuando hay un derecho antidumping no se puede saber qué fabricante es el
importador real, así que se deja fuera de la cifra principal y se ofrece el
escenario worst case con la tasa residual.
"""

from __future__ import annotations

import re

from app.customs.schemas import (
    CustomsItem,
    CustomsOperationRequest,
    DutyRate,
    ItemMeasures,
    TaxEstimation,
)

#: Unidades que se resuelven con el peso neto declarado.
_WEIGHT_UNITS = ("kg", "t", "tonne")
#: Unidades que se resuelven con las unidades suplementarias declaradas.
_SUPPLEMENTARY_UNITS = ("p/st", "st", "l", "hl", "m2", "m3", "m", "pair", "pairs")


def _quantity_for(rate: DutyRate, item: CustomsItem) -> tuple[float | None, str | None]:
    """Magnitud que aplica a un derecho específico y de dónde sale."""
    unit = (rate.specific_unit or "").strip().lower()
    if not unit:
        return 1.0, None

    if "kg" in unit or "tonne" in unit or unit == "t":
        if item.net_weight_kg is None:
            return None, "falta el peso neto declarado"
        divisor = 1.0
        numbers = re.findall(r"(\d+(?:[.,]\d+)?)\s*kg", unit)
        if numbers:
            divisor = float(numbers[0].replace(",", ".")) or 1.0
        return item.net_weight_kg / divisor, None

    if unit in _SUPPLEMENTARY_UNITS:
        if item.supplementary_units is None:
            return None, "faltan las unidades suplementarias declaradas"
        if unit == "hl":
            return item.supplementary_units / 100.0, None
        return item.supplementary_units, None

    return 1.0, None


def _duty_amount(rate: DutyRate, item: CustomsItem) -> tuple[float, list[str]]:
    """Importe de un derecho concreto y las notas del cálculo."""
    notes: list[str] = []
    amount = 0.0

    if rate.ad_valorem_percent:
        if item.customs_value is None:
            notes.append("No hay valor en aduana declarado: el arancel ad valorem no se estima.")
        else:
            amount += item.customs_value * rate.ad_valorem_percent / 100.0

    if rate.specific_amount:
        quantity, problem = _quantity_for(rate, item)
        if quantity is None:
            notes.append(
                f"El derecho específico ({rate.formula_raw}) no se estima: {problem}."
            )
        else:
            amount += rate.specific_amount * quantity
            notes.append(
                f"Derecho específico {rate.formula_raw} × {quantity:g} = "
                f"{rate.specific_amount * quantity:.2f} {rate.specific_currency or ''}".strip()
            )

    return amount, notes


def _applicable_duty(item_measures: ItemMeasures, item: CustomsItem) -> tuple[DutyRate | None, list[str]]:
    """Derecho aplicable: el preferencial si existe, si no el de terceros países."""
    notes: list[str] = []
    preferential = item_measures.preferential_duties
    if preferential:
        best = preferential[0]
        notes.append(
            f"Aplicaría el régimen preferencial de {best.agreement or 'la UE'} "
            f"({best.duty.formula_raw or 'sin tasa visible'}) si se acredita la prueba de origen; "
            "la estimación se calcula con esa tasa."
        )
        return best.duty, notes

    third = item_measures.third_country_duty
    if third:
        return third.duty, notes
    return None, notes


def _incoterm_note(request: CustomsOperationRequest, language: str) -> str | None:
    incoterm = (request.incoterm or "").upper()
    if not incoterm:
        return None
    if incoterm in {"EXW", "FCA", "FAS", "FOB"}:
        return (
            f"Con {incoterm} el valor en aduana no incluye el transporte internacional: "
            "el flete y el seguro hasta la frontera de la UE se añaden al valor "
            "aduanero, por lo que el arancel y el IVA reales serán mayores."
            if language == "es" else
            f"With {incoterm} the customs value excludes international transport: freight "
            "and insurance to the EU border must be added to the customs value, so the "
            "actual duty and VAT will be higher."
        )
    if incoterm in {"CIF", "CIP", "CFR", "CPT"}:
        return (
            f"Con {incoterm} el valor en aduana ya incluye transporte y seguro hasta la "
            "frontera de la UE."
            if language == "es" else
            f"With {incoterm} the customs value already includes transport and insurance "
            "to the EU border."
        )
    if incoterm in {"DAP", "DPU"}:
        return (
            f"Con {incoterm} el vendedor entrega en el destino: el flete interior "
            "posterior a la entrada en la UE no forma parte del valor en aduana."
            if language == "es" else
            f"With {incoterm} the seller delivers at destination: inland freight after "
            "EU entry is not part of the customs value."
        )
    if incoterm == "DDP":
        return (
            "Con DDP el vendedor paga también los derechos: el valor en aduana debe "
            "reducirse en el importe de los derechos pagados por él."
            if language == "es" else
            "With DDP the seller also pays the duties: the customs value must be reduced "
            "by the duty amount paid by them."
        )
    return None


def estimate_taxes(
    item: CustomsItem,
    item_measures: ItemMeasures,
    request: CustomsOperationRequest,
    vat_rate: float | None = None,
) -> TaxEstimation | None:
    """Estima derechos y base de IVA. `None` si no hay valor declarado."""
    if item.customs_value is None:
        return None

    language = request.language
    notes: list[str] = []
    breakdown: list[str] = []

    duty_rate, duty_notes = _applicable_duty(item_measures, item)
    notes.extend(duty_notes)

    estimated_duty = 0.0
    if duty_rate is not None:
        estimated_duty, duty_notes = _duty_amount(duty_rate, item)
        notes.extend(duty_notes)
        if duty_rate.formula_raw:
            breakdown.append(
                f"Arancel aplicable {duty_rate.formula_raw} → {estimated_duty:.2f} "
                f"{item.currency or 'EUR'}"
            )
    else:
        notes.append(
            "No se ha identificado un arancel aplicable en la fuente para esta partida."
            if language == "es" else
            "No applicable duty was identified in the source for this line."
        )

    # Escenario de defensa comercial: tasa residual para el resto de fabricantes.
    # Se agrega por tasa distinta: un derecho antidumping puede traer decenas de
    # fabricantes y el escenario se calcula una sola vez.
    residual_scenarios: dict[str, float] = {}
    for defense in item_measures.trade_defense_measures:
        residual = defense.residual_duty
        if residual is None or residual.ad_valorem_percent is None:
            continue
        residual_scenarios.setdefault(residual.formula_raw, residual.ad_valorem_percent)
    for formula, percent in residual_scenarios.items():
        worst_case = item.customs_value * percent / 100.0
        notes.append(
            f"Si se aplica el derecho de defensa comercial sin acreditación del "
            f"certificado exigido ({formula}), el coste adicional sería de "
            f"{worst_case:.2f} {item.currency or 'EUR'}; el importe depende del "
            "fabricante (código adicional TARIC)."
            if language == "es" else
            f"If the trade defence duty applies without the required certificate "
            f"({formula}), the additional cost would be {worst_case:.2f} "
            f"{item.currency or 'EUR'}; the amount depends on the producer (TARIC "
            "additional code)."
        )

    vat_base = item.customs_value + estimated_duty
    estimated_vat = vat_base * vat_rate / 100.0 if vat_rate is not None else None

    if vat_rate is None:
        notes.append(
            "El tipo de IVA del país de destino no se ha podido determinar; la base se "
            "calcula pero el importe del IVA no."
            if language == "es" else
            "The VAT rate of the destination country could not be determined; the base is "
            "calculated but the VAT amount is not."
        )
    if item.currency and item.currency != "EUR":
        notes.append(
            f"El valor se ha declarado en {item.currency} y no se ha aplicado ningún tipo "
            "de cambio; el IVA se estima en esa moneda."
            if language == "es" else
            f"The value was declared in {item.currency} and no exchange rate was applied; "
            "the VAT is estimated in that currency."
        )

    incoterm_note = _incoterm_note(request, language)
    if incoterm_note:
        notes.append(incoterm_note)

    formula = (
        "Base imponible de IVA = valor en aduana + derechos"
        if language == "es" else
        "VAT base = customs value + duties"
    )

    return TaxEstimation(
        currency=item.currency or "EUR",
        customs_value=round(item.customs_value, 2),
        estimated_duty=round(estimated_duty, 2),
        duty_breakdown=breakdown,
        estimated_vat_base=round(vat_base, 2),
        estimated_vat_rate=vat_rate,
        estimated_vat=round(estimated_vat, 2) if estimated_vat is not None else None,
        incoterm_adjustment=incoterm_note,
        formula=formula,
        notes=notes,
    )
