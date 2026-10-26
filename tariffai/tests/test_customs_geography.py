import pytest

from app.customs.geography import assess_geography, is_intra_union
from app.customs.schemas import CustomsRegime, ReportingRequirement


def test_intra_union_flow_needs_no_customs_declaration():
    assessment = assess_geography("FR", "ES", "IMPORT")

    assert assessment.regime is CustomsRegime.INTRA_UNION
    assert assessment.intra_union is True
    assert assessment.requires_taric_consultation is False
    assert assessment.duties_apply is False
    assert ReportingRequirement.INTRSTAT in assessment.reporting_requirements
    assert ReportingRequirement.VAT_INTRA_COMMUNITY in assessment.reporting_requirements
    assert ReportingRequirement.CUSTOMS_DECLARATION not in assessment.reporting_requirements


def test_same_member_state_reports_no_intrast():
    assessment = assess_geography("ES", "ES", "IMPORT")

    assert assessment.regime is CustomsRegime.INTRA_UNION
    assert ReportingRequirement.INTRSTAT not in assessment.reporting_requirements
    assert ReportingRequirement.VAT_INTRA_COMMUNITY not in assessment.reporting_requirements


def test_third_country_import_consults_taric():
    assessment = assess_geography("CN", "ES", "IMPORT")

    assert assessment.regime is CustomsRegime.IMPORT_FROM_THIRD_COUNTRY
    assert assessment.requires_taric_consultation is True
    assert assessment.duties_apply is True
    assert ReportingRequirement.CUSTOMS_DECLARATION in assessment.reporting_requirements
    assert ReportingRequirement.VAT_IMPORT in assessment.reporting_requirements


def test_export_to_third_country_does_not_levy_eu_duties():
    assessment = assess_geography("DE", "MA", "EXPORT")

    assert assessment.regime is CustomsRegime.EXPORT_TO_THIRD_COUNTRY
    assert ReportingRequirement.VAT_IMPORT not in assessment.reporting_requirements
    assert ReportingRequirement.EXPORT_DECLARATION in assessment.reporting_requirements
    assert "no grava las exportaciones" in assessment.territorial_note


def test_export_to_sanctioned_country_is_flagged():
    assessment = assess_geography("DE", "RU", "EXPORT")

    assert "sanciones" in assessment.territorial_note


def test_canary_islands_are_outside_the_eu_customs_and_vat_territory():
    assessment = assess_geography("CN", "ES", "IMPORT", destination_subdivision="ES-CN")

    assert assessment.regime is CustomsRegime.IMPORT_FROM_THIRD_COUNTRY
    assert assessment.requires_taric_consultation is True
    assert assessment.destination.in_eu_customs_territory is False
    assert assessment.destination.in_eu_vat_territory is False
    assert ReportingRequirement.IGIC in assessment.reporting_requirements
    assert ReportingRequirement.VAT_IMPORT not in assessment.reporting_requirements
    assert "Canarias" in assessment.territorial_note


def test_ceuta_and_melilla_use_aiem():
    for subdivision in ("ES-CE", "ES-ML"):
        assessment = assess_geography("ES", "CN", "EXPORT", origin_subdivision=subdivision)
        assert assessment.regime is CustomsRegime.EXPORT_TO_THIRD_COUNTRY
        assert ReportingRequirement.AIEM in assessment.reporting_requirements


def test_azores_and_madeira_stay_inside_the_customs_union():
    for subdivision in ("PT-20", "PT-30"):
        assessment = assess_geography("PT", "ES", "IMPORT", origin_subdivision=subdivision)

        assert assessment.regime is CustomsRegime.INTRA_UNION_TERRITORIAL_EXCEPTION
        assert assessment.requires_taric_consultation is False
        assert assessment.duties_apply is False
        assert ReportingRequirement.INTRSTAT in assessment.reporting_requirements


def test_aland_is_outside_the_vat_territory_but_inside_the_customs_union():
    assessment = assess_geography("FI", "AX", "IMPORT")

    assert assessment.regime is CustomsRegime.INTRA_UNION_TERRITORIAL_EXCEPTION
    assert assessment.requires_taric_consultation is False
    assert assessment.origin.in_eu_vat_territory is True
    assert assessment.destination.in_eu_vat_territory is False
    assert ReportingRequirement.AX_VAT in assessment.reporting_requirements
    assert ReportingRequirement.VAT_INTRA_COMMUNITY not in assessment.reporting_requirements


@pytest.mark.parametrize("origin,destination,expected", [
    ("FR", "ES", True),
    ("DE", "FR", True),
    ("CN", "ES", False),
    ("ES", "MA", False),
])
def test_is_intra_union_shortcut(origin, destination, expected):
    assert is_intra_union(origin, destination) is expected
