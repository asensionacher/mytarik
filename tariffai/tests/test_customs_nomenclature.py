import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.customs import nomenclature, service
from app.customs.router import router as customs_router
from app.customs.taric_client import Access2MarketsProvider


TREE = [{
    "code": "61",
    "description": "Apparel",
    "children": [{
        "code": "610910",
        "description": "Of cotton",
        "children": [
            {"code": "6109100010", "description": "T-shirts", "hasChildren": False},
            {"code": "6109100090", "description": "Other", "hasChildren": False},
        ],
    }],
}]


def build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(customs_router)
    return app


def test_collect_nodes_walks_the_whole_tree():
    nodes = nomenclature.collect_nodes(TREE)

    assert [(node.code, node.description) for node in nodes] == [
        ("61", "Apparel"),
        ("610910", "Of cotton"),
        ("6109100010", "T-shirts"),
        ("6109100090", "Other"),
    ]


def test_ten_digit_nodes_are_used_as_they_are():
    candidates = nomenclature.build_candidates(
        nomenclature.collect_nodes(TREE), "610910",
    )

    assert [c.taric_code for c in candidates] == ["6109100010", "6109100090"]
    assert all(c.exact for c in candidates)
    assert candidates[0].description == "T-shirts"


def test_eight_digit_nodes_get_the_default_taric_suffix():
    tree = [{"code": "02101131", "description": "Hams and cuts thereof"}]

    candidates = nomenclature.build_candidates(nomenclature.collect_nodes(tree), "021011")

    assert [c.taric_code for c in candidates] == ["0210113100"]
    assert candidates[0].exact is True


def test_without_nomenclature_the_code_is_inferred_and_flagged():
    candidates = nomenclature.build_candidates([], "401110")

    assert [c.taric_code for c in candidates] == ["4011100000"]
    assert candidates[0].exact is False
    assert candidates[0].source == "inferred"


def test_provider_queries_the_nomenclature_endpoint():
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=TREE)

    async def exercise():
        async with httpx.AsyncClient(
            base_url="https://trade.ec.europa.eu",
            transport=httpx.MockTransport(handler),
        ) as http:
            provider = Access2MarketsProvider(http)
            return await provider.resolve_nomenclature("610910", "ES")

    nodes = asyncio.run(exercise())

    assert seen[0][0].endswith("/api/v2/nomenclature/productsByCode")
    assert seen[0][1]["code"] == "610910"
    assert seen[0][1]["country"] == "ES"
    assert [node.code for node in nodes][-1] == "6109100090"


def test_endpoint_returns_the_candidates(monkeypatch):
    class FakeClient:
        def ensure_ready(self) -> None:
            return None

        async def resolve_taric_codes(self, hs_code, country):
            from app.customs.schemas import TaricCandidate

            assert hs_code == "610910"
            assert country == "ES"
            return (
                [
                    TaricCandidate(taric_code="6109100010", description="T-shirts"),
                    TaricCandidate(taric_code="6109100090", description="Other"),
                ],
                [],
            )

    monkeypatch.setattr(service, "get_client", lambda: FakeClient())

    response = TestClient(build_app()).post("/customs/resolve-taric-codes", json={
        "hs_code": "610910", "country": "ES", "language": "es",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["hs_code"] == "610910"
    assert [c["taric_code"] for c in body["candidates"]] == ["6109100010", "6109100090"]


@pytest.mark.parametrize("payload", [
    {"hs_code": "61091", "country": "ES"},
    {"hs_code": "610910", "country": "ESP"},
    {"hs_code": "610910", "country": "ES", "provider": "other"},
])
def test_invalid_resolution_requests_are_rejected(payload):
    response = TestClient(build_app()).post("/customs/resolve-taric-codes", json=payload)

    assert response.status_code == 422


def test_resolution_failures_do_not_break_the_endpoint(monkeypatch):
    class FailingClient:
        def ensure_ready(self) -> None:
            return None

        async def resolve_taric_codes(self, hs_code, country):
            raise RuntimeError("nomenclatura caída")

    monkeypatch.setattr(service, "get_client", lambda: FailingClient())

    response = TestClient(build_app()).post("/customs/resolve-taric-codes", json={
        "hs_code": "610910", "country": "ES",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == []
    assert body["warnings"]
