import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
from fastapi.testclient import TestClient

from app import main
from app.tariffai_client import TariffAIClient


def test_json_endpoints_reject_model_and_provider_overrides():
    client = TestClient(main.app)
    for path, payload in [
        ("/api/classify", {"description": "cotton shirts"}),
        ("/api/classify/raw", {"text": "cotton shirts"}),
    ]:
        for field in ("modelo", "proveedor", "model", "provider"):
            response = client.post(path, json={**payload, field: "other"})
            assert response.status_code == 422


def test_upload_cannot_forward_model_selection(monkeypatch):
    parsed = Mock(source="text", pages=None, descriptions=["cotton shirts"])
    monkeypatch.setattr(main, "parse_invoice", Mock(return_value=parsed))
    tariffai = Mock()
    tariffai.classify_batch = AsyncMock(return_value=[])
    context = AsyncMock()
    context.__aenter__.return_value = tariffai
    monkeypatch.setattr(main, "make_client", lambda: context)
    response = TestClient(main.app).post(
        "/api/invoice/upload",
        files={"file": ("invoice.txt", b"cotton shirts", "text/plain")},
        data={"modelo": "other", "proveedor": "other"},
    )
    assert response.status_code == 200
    tariffai.classify_batch.assert_awaited_once_with(["cotton shirts"])


def test_tariffai_client_sends_only_descriptions_and_preserves_batching():
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        result = {"status": "error", "error": "test response"}
        return httpx.Response(200, json=[result] * len(payload["descriptions"]) if "descriptions" in payload else result)

    async def exercise():
        client = TariffAIClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            await client.classify_one("cotton shirts")
            assert len(await client.classify_batch(["cotton shirts"] * 51)) == 51

    asyncio.run(exercise())
    assert requests == [
        ("/classify", {"description": "cotton shirts"}),
        ("/classify/batch", {"descriptions": ["cotton shirts"] * 50}),
        ("/classify/batch", {"descriptions": ["cotton shirts"]}),
    ]
