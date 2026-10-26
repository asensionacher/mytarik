import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.customs import service
from app.customs.router import router as customs_router
from app.customs.schemas import CustomsRegime, DataSource
from app.customs.taric_client import ProviderResult, RawMeasure, RawTaricResult


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch):
    """Sin Foundry en los tests: la capa LLM se activa sólo donde se prueba."""
    monkeypatch.setattr(service, "CUSTOMS_LLM_ENABLED", False)


def build_app() -> FastAPI:
    """App mínima con el router de medidas (sin las dependencias de ML)."""
    app = FastAPI()
    app.include_router(customs_router)
    return app


def provider_result(*measures) -> ProviderResult:
    return ProviderResult(
        provider="access2markets",
        measures=[RawTaricResult(measures=list(measures), description="Tyres")],
        taxes=[{"taxType": "VAT", "taxRate": "21%"}],
        documents=[{"code": "cominvce", "label": "Commercial invoice", "type": "g"}],
        product_description="Tyres",
        queried_code="40111000",
    )


def measure(**kwargs) -> RawMeasure:
    payload = {
        "measureType": "103",
        "type": "Third country duty",
        "origin": "ERGA OMNES",
        "tariffFormula": "4.50%",
        "footnotes": [],
        "conditions": [],
    }
    payload.update(kwargs)
    return RawMeasure(**payload)


class FakeClient:
    """Cliente de medidas con respuestas preparadas, sin tocar la red."""

    def __init__(self, result=None, available=True):
        self.result = result
        self.available = available
        self.queries = []

    def ensure_ready(self) -> None:
        return None

    async def get_measures(self, query):
        from app.customs.taric_client import QueryOutcome

        self.queries.append(query)
        if not self.available:
            return QueryOutcome(
                available=False, warnings=["Proveedor no disponible"],
            )
        return QueryOutcome(
            available=True, provider="access2markets", result=self.result,
        )


def request_payload(**overrides):
    payload = {
        "operation_type": "IMPORT",
        "origin_country": "CN",
        "destination_country": "ES",
        "language": "es",
        "items": [{
            "taric_code": "4011100000",
            "description": "Neumáticos de turismo",
            "customs_value": 12000,
            "currency": "EUR",
            "net_weight_kg": 900,
        }],
    }
    payload.update(overrides)
    return payload


def test_endpoint_returns_the_measures_of_every_line(monkeypatch):
    fake = FakeClient(provider_result(measure()))
    monkeypatch.setattr(service, "get_client", lambda: fake)

    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["customs_regime"] == CustomsRegime.IMPORT_FROM_THIRD_COUNTRY.value
    assert body["provider"] == "access2markets"
    item = body["items_measures"][0]
    assert item["line_number"] == 1
    assert item["third_country_duty"]["duty"]["ad_valorem_percent"] == 4.5
    assert item["provenance"]["source"] == DataSource.LIVE.value
    assert item["tax_estimation"]["estimated_duty"] == 540.0
    assert item["tax_estimation"]["estimated_vat_base"] == 12540.0
    assert item["tax_estimation"]["estimated_vat_rate"] == 21.0
    assert fake.queries[0].taric_code == "4011100000"


def test_intra_union_flow_does_not_call_the_source(monkeypatch):
    fake = FakeClient(provider_result(measure()))
    monkeypatch.setattr(service, "get_client", lambda: fake)

    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload(
        origin_country="FR", destination_country="ES",
    ))

    assert response.status_code == 200
    body = response.json()
    assert body["customs_regime"] == CustomsRegime.INTRA_UNION.value
    assert "INTRSTAT" in body["reporting_requirements"]
    assert "VAT_INTRA_COMMUNITY" in body["reporting_requirements"]
    assert body["items_measures"][0]["third_country_duty"] is None
    assert fake.queries == []


def test_unavailable_provider_degrades_to_a_partial_answer(monkeypatch):
    fake = FakeClient(available=False)
    monkeypatch.setattr(service, "get_client", lambda: fake)

    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["items_measures"][0]["third_country_duty"] is None
    assert body["warnings"]


def test_export_flow_explains_that_the_eu_does_not_levy_export_duties(monkeypatch):
    fake = FakeClient(provider_result())
    monkeypatch.setattr(service, "get_client", lambda: fake)

    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload(
        operation_type="EXPORT", origin_country="DE", destination_country="MA",
    ))

    body = response.json()
    assert body["customs_regime"] == CustomsRegime.EXPORT_TO_THIRD_COUNTRY.value
    assert "EXPORT_DECLARATION" in body["reporting_requirements"]
    assert "VAT_IMPORT" not in body["reporting_requirements"]


def test_request_rejects_unknown_fields():
    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload(
        provider="other",
    ))

    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    request_payload(origin_country="ESP"),
    request_payload(destination_country="es"),
    request_payload(items=[]),
    request_payload(items=[{"taric_code": "401110000", "description": "x"}]),
    request_payload(incoterm="EXW0"),
    request_payload(language="fr"),
])
def test_invalid_requests_are_rejected(payload):
    response = TestClient(build_app()).post("/customs/evaluate", json=payload)

    assert response.status_code == 422


def test_lines_are_evaluated_in_parallel_and_keep_their_order(monkeypatch):
    fake = FakeClient(provider_result(measure()))
    monkeypatch.setattr(service, "get_client", lambda: fake)

    payload = request_payload(items=[
        {"taric_code": "4011100000", "description": "Neumático"},
        {"taric_code": "0210113100", "description": "Jamón"},
        {"taric_code": "6109100000", "description": "Camiseta"},
    ])

    response = TestClient(build_app()).post("/customs/evaluate", json=payload)

    body = response.json()
    assert [item["line_number"] for item in body["items_measures"]] == [1, 2, 3]
    assert [item["taric_code"] for item in body["items_measures"]] == [
        "4011100000", "0210113100", "6109100000",
    ]
    assert len(fake.queries) == 3


def test_llm_summary_is_attached_and_unverified_y_codes_are_dropped(monkeypatch):
    fake = FakeClient(provider_result(measure(
        measureType="695", type="Additional duties", tariffFormula=None,
        conditions=[{
            "certificateType": "Y", "certificateNumber": "155",
            "certificateDescription": "Russia or Belarus", "tariffFormula": "50.00%",
        }],
    )))
    monkeypatch.setattr(service, "get_client", lambda: fake)

    from app.customs import interpreter

    provider = type("Provider", (), {})()
    provider.complete = lambda **kwargs: type(
        "Response", (), {"text": json.dumps({"items": [{
            "line_number": 1,
            "duty_to_pay": "Arancel del 50 % por el veto a Rusia.",
            "how_to_reduce_to_zero": None,
            "border_controls": ["Factura comercial"],
            "special_regulations": [],
            "y_codes_to_declare": ["Y155", "Y999"],
            "warnings": [],
        }]})}
    )()
    monkeypatch.setattr(interpreter, "get_provider", lambda: provider)
    monkeypatch.setattr(service, "CUSTOMS_LLM_ENABLED", True)

    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload())

    summary = response.json()["items_measures"][0]["executive_summary"]
    assert summary["y_codes_to_declare"] == ["Y155"]
    assert summary["duty_to_pay"].startswith("Arancel del 50 %")
    assert any("Y999" in warning for warning in summary["warnings"])


def test_llm_failure_does_not_break_the_endpoint(monkeypatch):
    fake = FakeClient(provider_result(measure()))
    monkeypatch.setattr(service, "get_client", lambda: fake)

    from app.customs import interpreter

    provider = type("Provider", (), {})()
    provider.complete = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(interpreter, "get_provider", lambda: provider)
    monkeypatch.setattr(service, "CUSTOMS_LLM_ENABLED", True)

    response = TestClient(build_app()).post("/customs/evaluate", json=request_payload())

    assert response.status_code == 200
    item = response.json()["items_measures"][0]
    assert item["third_country_duty"] is not None
    assert item["executive_summary"] is not None
