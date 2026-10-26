import json

import pytest

from app.customs import parser
from app.customs.estimation import estimate_taxes
from app.customs.knowledge import match_border_controls, match_special_regulations
from app.customs.schemas import (
    CustomsItem,
    CustomsOperationRequest,
    DataSource,
    DutyKind,
    MeasureCategory,
    SpecialRegulationKind,
)
from app.customs.taric_client import ProviderResult, RawMeasure, RawTaricResult


def measure(**kwargs) -> RawMeasure:
    payload = {
        "measureType": "103",
        "type": "Third country duty",
        "origin": "ERGA OMNES",
        "tariffFormula": "12.00%",
        "footnotes": [],
        "conditions": [],
    }
    payload.update(kwargs)
    return RawMeasure(**payload)


def result(*measures, taxes=None, documents=None) -> ProviderResult:
    return ProviderResult(
        provider="access2markets",
        measures=[RawTaricResult(measures=list(measures), description="Test")],
        taxes=taxes or [],
        documents=documents or [],
        product_description="Test product",
        queried_code="61091000",
    )


@pytest.mark.parametrize("formula,kind,percent,amount,currency,unit", [
    ("12.00%", DutyKind.AD_VALOREM, 12.0, None, None, None),
    ("0%", DutyKind.AD_VALOREM, 0.0, None, None, None),
    ("151.20 EUR / 100 kg", DutyKind.SPECIFIC, None, 151.2, "EUR", "100 kg"),
    ("3.00 EUR", DutyKind.SPECIFIC, None, 3.0, "EUR", None),
    ("13.10 EUR / hl", DutyKind.SPECIFIC, None, 13.1, "EUR", "hl"),
    ("p/st", DutyKind.UNKNOWN, None, None, None, None),
    ("", DutyKind.UNKNOWN, None, None, None, None),
])
def test_duty_formulas(formula, kind, percent, amount, currency, unit):
    rate = parser.parse_duty_formula(formula)

    assert rate.kind is kind
    assert rate.ad_valorem_percent == percent
    assert rate.specific_amount == amount
    assert rate.specific_currency == currency
    assert rate.specific_unit == unit
    assert rate.formula_raw == formula


def test_compound_duty_sums_both_parts():
    rate = parser.parse_duty_formula("12.00% + 1.50 EUR / 100 kg")

    assert rate.kind is DutyKind.COMPOUND
    assert rate.ad_valorem_percent == 12.0
    assert rate.specific_amount == 1.5
    assert rate.specific_currency == "EUR"
    assert rate.specific_unit == "100 kg"


@pytest.mark.parametrize("measure_type,name,expected", [
    ("103", "Third country duty", MeasureCategory.THIRD_COUNTRY_DUTY),
    ("142", "Tariff preference", MeasureCategory.PREFERENTIAL),
    ("552", "Definitive anti-dumping duty", MeasureCategory.TRADE_DEFENSE),
    ("117", "Suspension", MeasureCategory.SUSPENSION),
    ("122", "Non preferential tariff quota", MeasureCategory.QUOTA),
    ("695", "Additional duties", MeasureCategory.ADDITIONAL_DUTY),
    ("109", "Supplementary unit", MeasureCategory.SUPPLEMENTARY_UNIT),
])
def test_measure_categories(measure_type, name, expected):
    assert parser.measure_category(measure_type, name) is expected


def test_measures_are_split_into_duty_preference_and_defense():
    item = CustomsItem(taric_code="4011100000", description="Tyres")
    provider = result(
        measure(measureType="103", tariffFormula="4.50%"),
        measure(
            measureType="142", type="Tariff preference", origin="Chile", tariffFormula="0%",
        ),
        measure(
            measureType="552", type="Definitive anti-dumping duty", origin="China",
            geographicalSigl="CN", tariffFormula=None, additionalCodeId="88CO",
            additionalCodeText="Hankook Group", conditions=[
                {
                    "certificateType": "D", "certificateNumber": "008",
                    "certificateDescription": "Invoice with a signed declaration",
                    "tariffFormula": "4.30%",
                },
                {"certificateType": None, "tariffFormula": "45.30%"},
            ],
        ),
    )

    built = parser.build_item_measures(provider, item, language="en", line_number=1)

    assert built.third_country_duty is not None
    assert built.third_country_duty.duty.ad_valorem_percent == 4.5
    assert [duty.agreement for duty in built.preferential_duties] == ["Chile"]
    assert built.preferential_duties[0].proof_of_origin
    defense = built.trade_defense_measures[0]
    assert defense.additional_code == "88CO"
    assert defense.certificate_code == "D008"
    assert defense.duty.ad_valorem_percent == 4.3
    assert defense.residual_duty.ad_valorem_percent == 45.3


def test_y_codes_come_from_measure_conditions():
    item = CustomsItem(taric_code="0210113100", description="Ham")
    provider = result(
        measure(
            measureType="695", type="Additional duties", tariffFormula=None,
            conditions=[
                {
                    "certificateType": "Y", "certificateNumber": "155",
                    "certificateDescription": "Products exported from Russia or Belarus",
                    "tariffFormula": "50.00%",
                },
                {"certificateType": None, "tariffFormula": "0%"},
            ],
        ),
    )

    built = parser.build_item_measures(provider, item, language="es")

    assert [code.code for code in built.exemption_y_codes] == ["Y155"]
    assert "casilla 44" in built.exemption_y_codes[0].action
    assert built.exemption_y_codes[0].applies_to.startswith("695")
    # Sin arancel base (103) la medida 695 queda como variante con su importe.
    assert built.third_country_duty is not None
    assert built.third_country_duty.duty.formula_raw == ""
    assert [variant.measure_type for variant in built.third_country_duty.variants] == ["695"]
    assert built.third_country_duty.variants[0].duty.formula_raw == "50.00%"


def test_repeated_measures_are_not_duplicated():
    item = CustomsItem(taric_code="2204216800", description="Wine")
    provider = result(
        measure(measureType="103", tariffFormula="13.10 EUR / hl"),
        measure(measureType="107", type="Low-value consignment customs duty", tariffFormula="3.00 EUR"),
    )
    provider.measures.append(RawTaricResult(measures=[
        measure(measureType="103", tariffFormula="13.10 EUR / hl"),
        measure(measureType="107", type="Low-value consignment customs duty", tariffFormula="3.00 EUR"),
    ], description="Other branch"))

    built = parser.build_item_measures(provider, item, language="en")

    variants = built.third_country_duty.variants
    assert [variant.measure_type for variant in variants] == ["107"]


def test_documents_become_controls_and_regulations():
    item = CustomsItem(taric_code="4011100000", description="Tyres")
    provider = result(
        measure(),
        documents=[
            {"code": "preforigrosa", "label": "Proof of preferential origin for ROSA countries", "type": "g"},
            {"code": "spfgg", "label": "Marketing of products containing fluorinated greenhouse gases", "type": "s"},
            {"code": "cominvce", "label": "Commercial invoice", "type": "g"},
        ],
    )

    built = parser.build_item_measures(provider, item, language="en")

    codes = [control.code for control in built.border_controls_and_inspections]
    assert "preforigrosa" in codes
    assert "cominvce" in codes
    assert "spfgg" not in codes
    regulations = {r.regulation: r for r in built.environmental_and_special_regulations}
    assert regulations[SpecialRegulationKind.F_GAS].source is DataSource.A2M_DOCUMENT


def test_html_is_stripped_from_measure_texts():
    item = CustomsItem(taric_code="4011100000", description="Tyres")
    provider = result(measure(
        additionalCodeText="Hankook Group:<br>– Chongqing",
        footnotes=[{"code": 1066, "type": "TM", "text": "First line.<br>(a) Second line."}],
    ))

    built = parser.build_item_measures(provider, item, language="en")

    defense_text = built.third_country_duty.footnotes[0].text
    assert "<br>" not in defense_text
    assert "First line. (a) Second line." == defense_text


def test_border_controls_depend_on_the_product_origin():
    animal = match_border_controls("0207140000", language="es")
    plant = match_border_controls("0805205000", language="es")
    industrial = match_border_controls("6109100000", language="es", country="ES")

    assert animal[0].code == "CHED-A"
    assert plant[0].code == "CHED-P"
    assert [c.code for c in industrial] == ["SOIVRE"]
    assert match_border_controls("6109100000", language="es", country="DE") == []


def test_special_regulations_flag_cbam_and_dual_use():
    cbam = match_special_regulations("7202411000", language="es")
    dual_use = match_special_regulations("2844300000", language="es", destination_country="RU")

    assert SpecialRegulationKind.CBAM in {rule.regulation for rule in cbam}
    assert SpecialRegulationKind.DUAL_USE in {rule.regulation for rule in dual_use}
    assert SpecialRegulationKind.SANCTIONS in {rule.regulation for rule in dual_use}
    assert all(rule.source is DataSource.KNOWLEDGE_BASE for rule in cbam)


def test_tax_estimation_uses_value_duty_and_vat_base():
    request = CustomsOperationRequest(
        operation_type="IMPORT", origin_country="CN", destination_country="ES",
        language="es",
        items=[{"taric_code": "0210113100", "description": "Ham"}],
    )
    item = request.items[0]
    provider = result(measure(tariffFormula="151.20 EUR / 100 kg"))
    built = parser.build_item_measures(provider, item, language="es")
    item.customs_value = 5000.0
    item.net_weight_kg = 200.0

    estimation = estimate_taxes(item, built, request, vat_rate=10.0)

    assert estimation.estimated_duty == 302.4
    assert estimation.estimated_vat_base == 5302.4
    assert estimation.estimated_vat == 530.24
    assert estimation.estimated_vat_rate == 10.0


def test_tax_estimation_prefers_the_preferential_rate():
    request = CustomsOperationRequest(
        operation_type="IMPORT", origin_country="CL", destination_country="ES",
        language="en", items=[{"taric_code": "2204216800", "description": "Wine"}],
    )
    item = request.items[0]
    item.customs_value = 1000.0
    provider = result(
        measure(measureType="103", tariffFormula="13.10 EUR / hl"),
        measure(measureType="142", type="Tariff preference", origin="Chile", tariffFormula="0%"),
    )
    built = parser.build_item_measures(provider, item, language="en")

    estimation = estimate_taxes(item, built, request, vat_rate=21.0)

    assert estimation.estimated_duty == 0.0
    assert estimation.estimated_vat_base == 1000.0
    assert any("preferential" in note or "preferencial" in note for note in estimation.notes)


def test_tax_estimation_needs_a_customs_value():
    request = CustomsOperationRequest(
        operation_type="IMPORT", origin_country="CN", destination_country="ES",
        items=[{"taric_code": "0210113100", "description": "Ham"}],
    )
    item = request.items[0]
    built = parser.build_item_measures(result(measure()), item)

    assert estimate_taxes(item, built, request) is None


def test_incoterm_changes_the_customs_value_note():
    request = CustomsOperationRequest(
        operation_type="IMPORT", origin_country="CN", destination_country="ES",
        incoterm="EXW", language="es",
        items=[{"taric_code": "0210113100", "description": "Ham", "customs_value": 100.0}],
    )
    item = request.items[0]
    built = parser.build_item_measures(result(measure()), item, language="es")

    estimation = estimate_taxes(item, built, request, vat_rate=10.0)

    assert estimation.incoterm_adjustment
    assert any("EXW" in note for note in estimation.notes)


def test_llm_cannot_invent_y_codes(monkeypatch):
    from app.customs import interpreter
    from app.customs.schemas import ItemMeasures

    request = CustomsOperationRequest(
        operation_type="IMPORT", origin_country="CN", destination_country="ES",
        language="es", items=[{"taric_code": "0210113100", "description": "Ham"}],
    )
    item = ItemMeasures(
        line_number=1, taric_code="0210113100", description="Ham",
        exemption_y_codes=[{"code": "Y155", "description": "Russia", "applies_to": "695"}],
    )
    provider = type("Provider", (), {})()
    provider.complete = lambda **kwargs: type(
        "Response", (), {"text": json.dumps({
            "items": [{
                "line_number": 1,
                "duty_to_pay": "50%",
                "y_codes_to_declare": ["Y155", "Y929"],
                "warnings": [],
            }],
        })}
    )()
    monkeypatch.setattr(interpreter, "get_provider", lambda: provider)

    import asyncio

    summaries = asyncio.run(interpreter.interpret_operation(request, [item]))

    assert summaries[1].y_codes_to_declare == ["Y155"]
    assert any("Y929" in warning for warning in summaries[1].warnings)


def test_llm_failure_keeps_the_structured_answer(monkeypatch):
    from app.customs import interpreter
    from app.customs.schemas import ItemMeasures

    request = CustomsOperationRequest(
        operation_type="IMPORT", origin_country="CN", destination_country="ES",
        items=[{"taric_code": "0210113100", "description": "Ham"}],
    )
    item = ItemMeasures(line_number=1, taric_code="0210113100", description="Ham")
    provider = type("Provider", (), {})()
    provider.complete = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(interpreter, "get_provider", lambda: provider)

    import asyncio

    assert asyncio.run(interpreter.interpret_operation(request, [item])) == {}
