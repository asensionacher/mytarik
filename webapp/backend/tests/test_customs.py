import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.customs_client import CustomsOperationRequest, CustomsOperationResponse


PAYLOAD = {
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

RESPONSE = {
    "status": "ok",
    "operation_type": "IMPORT",
    "origin_country": "CN",
    "destination_country": "ES",
    "customs_regime": "IMPORT_FROM_THIRD_COUNTRY",
    "reporting_requirements": ["INTRSTAT", "VAT_IMPORT", "CUSTOMS_DECLARATION"],
    "items_measures": [{
        "line_number": 1,
        "taric_code": "4011100000",
        "description": "Neumáticos de turismo",
        "third_country_duty": {
            "measure_type": "103",
            "measure_type_label": "Arancel de terceros países (Erga Omnes)",
            "category": "third_country_duty",
            "origin": "ERGA OMNES",
            "duty": {
                "kind": "ad_valorem", "ad_valorem_percent": 4.5,
                "specific_amount": None, "specific_currency": None,
                "specific_unit": None, "formula_raw": "4.50%",
            },
            "variants": [],
        },
        "preferential_duties": [],
        "trade_defense_measures": [],
        "border_controls_and_inspections": [],
        "environmental_and_special_regulations": [],
        "exemption_y_codes": [{"code": "Y155", "description": "x", "applies_to": "695", "action": "y"}],
        "tax_estimation": None,
        "executive_summary": None,
        "provenance": {
            "provider": "access2markets", "source": "live", "cache_hit": False,
            "queried_code": "40111000", "raw_measure_count": 3,
            "fetched_at": "2026-10-26T10:00:00+00:00", "warnings": [],
        },
    }],
    "warnings": [],
    "provider": "access2markets",
    "cache_hits": 0,
    "processing_time_ms": 812.4,
    "error": None,
}


def fake_client(monkeypatch, captured=None, response=None, error=None):
    client = Mock()

    async def evaluate_operation(request):
        if captured is not None:
            captured.append(request)
        if error is not None:
            raise error
        return CustomsOperationResponse.model_validate(response or RESPONSE)

    client.evaluate_operation = evaluate_operation
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(main, "make_customs_client", lambda: context)


def test_endpoint_forwards_the_operation_and_returns_the_measures(monkeypatch):
    captured = []
    fake_client(monkeypatch, captured)

    response = TestClient(main.app).post("/api/v1/customs/evaluate-operation", json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["customs_regime"] == "IMPORT_FROM_THIRD_COUNTRY"
    assert body["items_measures"][0]["third_country_duty"]["duty"]["ad_valorem_percent"] == 4.5
    assert body["items_measures"][0]["exemption_y_codes"][0]["code"] == "Y155"
    assert len(captured) == 1
    assert captured[0].items[0].taric_code == "4011100000"
    assert captured[0].origin_country == "CN"


def test_endpoint_rejects_invalid_operations():
    client = TestClient(main.app)
    for payload in [
        {**PAYLOAD, "origin_country": "ESP"},
        {**PAYLOAD, "operation_type": "transfer"},
        {**PAYLOAD, "items": []},
        {**PAYLOAD, "items": [{"taric_code": "401110000", "description": "x"}]},
        {**PAYLOAD, "provider": "other"},
    ]:
        response = client.post("/api/v1/customs/evaluate-operation", json=payload)
        assert response.status_code == 422


def test_endpoint_reports_an_unreachable_engine(monkeypatch):
    fake_client(monkeypatch, error=httpx.ConnectError("connection refused"))

    response = TestClient(main.app).post("/api/v1/customs/evaluate-operation", json=PAYLOAD)

    assert response.status_code == 502
    assert "no respondió" in response.json()["detail"]


def test_endpoint_reports_a_timeout(monkeypatch):
    fake_client(monkeypatch, error=httpx.ReadTimeout("timeout"))

    response = TestClient(main.app).post("/api/v1/customs/evaluate-operation", json=PAYLOAD)

    assert response.status_code == 504


def test_endpoint_surfaces_an_engine_error(monkeypatch):
    payload = {**RESPONSE, "status": "error", "error": "motor caído"}
    fake_client(monkeypatch, response=payload)

    response = TestClient(main.app).post("/api/v1/customs/evaluate-operation", json=PAYLOAD)

    assert response.status_code == 502
    assert "motor caído" in response.json()["detail"]


def test_client_sends_the_strict_payload_to_tariffai():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=RESPONSE)

    async def exercise():
        from app.customs_client import CustomsClient

        client = CustomsClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            request = CustomsOperationRequest(**PAYLOAD)
            return await client.evaluate_operation(request)

    response = asyncio_run(exercise())

    assert requests[0]["operation_type"] == "IMPORT"
    assert requests[0]["items"][0]["taric_code"] == "4011100000"
    assert response.status == "ok"
    assert response.items_measures[0].third_country_duty.duty.ad_valorem_percent == 4.5


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)
