import asyncio
import json
from datetime import date

import httpx
import pytest

from app.customs.cache import TTLDailyMeasureCache, cache_key
from app.customs.taric_client import (
    Access2MarketsProvider,
    ProviderError,
    TaricQuery,
    TaricRealtimeClient,
    UkTradeTariffProvider,
)


QUERY = TaricQuery(
    taric_code="4011100000",
    origin_country="CN",
    destination_country="ES",
    operation_type="IMPORT",
)

TARIFFS_PAYLOAD = [{
    "measures": [{
        "measureType": "103",
        "type": "Third country duty",
        "origin": "ERGA OMNES",
        "tariffFormula": "4.50%",
        "footnotes": [],
        "conditions": [],
    }],
    "description": "Tyres",
    "code": None,
}]


def client_with(handler, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://trade.ec.europa.eu",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_cache_key_contains_the_day_and_the_flow():
    key = cache_key("4011100000", "CN", "ES", "IMPORT", date(2026, 10, 26))

    assert key == "4011100000:CN:ES:IMPORT:2026-10-26"


def test_cache_stores_and_returns_the_measures():
    cache = TTLDailyMeasureCache(ttl=60, maxsize=4)
    key = cache_key(**{"taric_code": "4011100000", "origin_country": "CN",
                       "destination_country": "ES", "operation_type": "IMPORT"})

    assert cache.get(key) is None
    cache.set(key, {"value": 1})
    assert cache.get(key) == {"value": 1}


def test_cache_expires_after_the_ttl():
    cache = TTLDailyMeasureCache(ttl=0, maxsize=4)
    key = cache_key(**{"taric_code": "4011100000", "origin_country": "CN",
                       "destination_country": "ES", "operation_type": "IMPORT"})
    cache.set(key, {"value": 1})

    assert cache.get(key) is None


def test_provider_queries_tariffs_taxes_and_documents():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if "tariffs/get" in request.url.path:
            return httpx.Response(200, json=TARIFFS_PAYLOAD)
        if "taxes/get" in request.url.path:
            return httpx.Response(200, json=[{"taxType": "VAT", "taxRate": "21%"}])
        return httpx.Response(200, json=[{"code": "cominvce", "label": "Invoice", "type": "g"}])

    async def exercise():
        async with client_with(handler) as http:
            provider = Access2MarketsProvider(http)
            return await provider.fetch(QUERY)

    result = asyncio.run(exercise())

    assert result.provider == "access2markets"
    assert result.flat_measures[0].tariffFormula == "4.50%"
    assert result.taxes[0]["taxRate"] == "21%"
    assert result.documents[0]["code"] == "cominvce"
    assert any("tariffs/get" in path for path in seen)
    assert any("taxes/get" in path for path in seen)
    assert any("document/list" in path for path in seen)


def test_provider_falls_back_to_a_shorter_code_when_nothing_matches():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if "tariffs/get" in request.url.path:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    async def exercise():
        async with client_with(handler) as http:
            provider = Access2MarketsProvider(http)
            return await provider.fetch(QUERY)

    result = asyncio.run(exercise())

    assert not result.flat_measures
    assert any(path.endswith("/4011100000/CN/ES") for path in seen)
    assert any(path.endswith("/40111000/CN/ES") for path in seen)
    assert any(path.endswith("/401110/CN/ES") for path in seen)
    assert result.warnings


def test_provider_reads_the_zone_tree_shape():
    payload = {
        "schemas": [{"code": "MFN", "label": "MFN"}],
        "notes": [{"note": "<p>Nota</p>", "type": "editor"}],
        "root": {
            "label": "Uranium",
            "productCode": "284430",
            "children": [{
                "label": "Uranium depleted",
                "productCode": "28443000",
                "tariffs": {"EU": [{"formula": "0%"}], "MFN": [{"formula": "2.5%"}]},
            }],
        },
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    async def exercise():
        async with client_with(handler) as http:
            provider = Access2MarketsProvider(http)
            return await provider.fetch(TaricQuery(
                taric_code="2844300000", origin_country="DE",
                destination_country="MA", operation_type="EXPORT",
            ))

    result = asyncio.run(exercise())

    formulas = {(m.origin, m.tariffFormula) for m in result.flat_measures}
    assert ("EU", "0%") in formulas
    assert ("MFN", "2.5%") in formulas
    assert any("exportación" in warning for warning in result.warnings)


def test_client_uses_the_cache_before_the_network():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=TARIFFS_PAYLOAD)

    async def exercise():
        cache = TTLDailyMeasureCache(ttl=60, maxsize=4)
        async with client_with(handler) as http:
            client = TaricRealtimeClient(
                providers=[Access2MarketsProvider(http)], cache=cache,
            )
            first = await client.get_measures(QUERY)
            second = await client.get_measures(QUERY)
            return first, second

    first, second = asyncio.run(exercise())

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len([call for call in calls if "tariffs/get" in call]) == 1


def test_client_retries_and_then_fails_cleanly(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request.url.path)
        return httpx.Response(503, text="unavailable")

    async def exercise():
        async with client_with(handler) as http:
            client = TaricRealtimeClient(providers=[Access2MarketsProvider(http)])
            return await client.get_measures(QUERY)

    original_sleep = asyncio.sleep
    monkeypatch.setattr(
        "app.customs.taric_client.asyncio.sleep", lambda _: original_sleep(0),
    )
    outcome = asyncio.run(exercise())

    assert outcome.available is False
    assert outcome.warnings
    # Tres intentos con backoff sobre el primer código; un 503 no se reintenta
    # con el código corto porque el fallo es del servidor, no de la partida.
    assert len(attempts) == 3
    assert all("tariffs/get" in attempt for attempt in attempts)


def test_client_falls_back_to_the_secondary_provider():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if "access2markets" in str(request.url):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"duties": [{
            "measure_type": "third", "duty_expression": "3.00%", "origin": "CN",
        }]})

    class FailingPrimary:
        name = "access2markets"

        def supports(self, query):
            return True

        async def fetch(self, query):
            raise ProviderError("primary down")

    class WorkingSecondary:
        name = "uk_trade_tariff"

        def supports(self, query):
            return True

        async def fetch(self, query):
            from app.customs.taric_client import ProviderResult, RawMeasure, RawTaricResult
            return ProviderResult(
                provider=self.name,
                measures=[RawTaricResult(measures=[RawMeasure(
                    measureType="103", type="Third country duty",
                    origin="CN", tariffFormula="3.00%",
                )])],
                queried_code="40111000",
            )

    async def exercise():
        client = TaricRealtimeClient(providers=[FailingPrimary(), WorkingSecondary()])
        return await client.get_measures(QUERY)

    outcome = asyncio.run(exercise())

    assert outcome.available is True
    assert outcome.provider == "uk_trade_tariff"
    assert outcome.result.flat_measures[0].tariffFormula == "3.00%"


def test_uk_provider_stays_disabled_without_credentials():
    provider = UkTradeTariffProvider(None, api_key="")

    assert provider.supports(QUERY) is False


def test_uk_provider_only_serves_flows_that_touch_great_britain():
    provider = UkTradeTariffProvider(None, api_key="key")

    assert provider.supports(QUERY) is False
    assert provider.supports(TaricQuery(
        taric_code="4011100000", origin_country="GB",
        destination_country="ES", operation_type="IMPORT",
    )) is True


def test_queries_run_in_parallel():
    active = 0
    peak = 0

    class SlowProvider:
        name = "slow"

        def supports(self, query):
            return True

        async def fetch(self, query):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            from app.customs.taric_client import ProviderResult
            return ProviderResult(provider=self.name)

    async def exercise():
        client = TaricRealtimeClient(providers=[SlowProvider()])
        return await asyncio.gather(*[
            client.get_measures(TaricQuery(
                taric_code=f"401110000{index}", origin_country="CN",
                destination_country="ES", operation_type="IMPORT",
            ))
            for index in range(3)
        ])

    asyncio.run(exercise())

    assert peak == 3
