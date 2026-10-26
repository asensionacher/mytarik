import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.tariffai_client import TariffAIClient


TRADE = {
    "trade_mode": "import",
    "origin_country": "ES",
    "dispatch_country": "CN",
}
TRADE_FORM = {
    "trade_mode": TRADE["trade_mode"],
    "origin_country": TRADE["origin_country"],
    "dispatch_country": TRADE["dispatch_country"],
}


def test_json_endpoints_reject_model_and_provider_overrides():
    client = TestClient(main.app)
    for path, payload in [
        ("/api/classify", {"description": "cotton shirts"}),
        ("/api/classify/raw", {"text": "cotton shirts", "trade": TRADE}),
    ]:
        for field in ("modelo", "proveedor", "model", "provider"):
                    response = client.post(path, json={**payload, field: "other"})
                    assert response.status_code == 422


def test_clarification_history_and_question_survive_backend_proxy(monkeypatch):
    answers = [{"question": "Material?", "answer": "Cotton"}]
    question = {"question": "Construction?", "options": ["Knitted", "Woven"]}
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "status": "ambiguous", "result": {
                "input_text": "shirts", "confidence": 0.7,
                "clarification_answers": answers, "clarification_question": question,
                "reasoning_triggers": ["short_description"],
            },
        })

    class ProxyClient(TariffAIClient):
        async def __aenter__(self):
            self._client = httpx.AsyncClient(
                base_url="http://tariffai", transport=httpx.MockTransport(handle),
            )
            return self

    monkeypatch.setattr(main, "make_client", ProxyClient)
    payload = {
        "description": "shirts", "language": "es", "trade": TRADE,
        "clarification_answers": answers,
    }
    response = TestClient(main.app).post("/api/classify", json=payload)
    assert response.status_code == 200
    assert requests == [payload]
    result = response.json()["result"]
    assert result["clarification_question"] == question
    assert result["clarification_answers"] == answers
    assert result["reasoning_triggers"] == ["short_description"]


@pytest.mark.parametrize("answers", [
    [{"question": "Q", "answer": "A"}] * 4,
    [{"question": "Q", "answer": " "}],
])
def test_clarification_limit_and_nonempty_answers_are_validated(answers):
    response = TestClient(main.app).post("/api/classify", json={
        "description": "shirts", "clarification_answers": answers,
    })
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/api/classify/raw", "/api/invoice/upload"])
def test_invoice_routes_require_trade_details(path):
    client = TestClient(main.app)
    if path == "/api/classify/raw":
        response = client.post(path, json={"text": "cotton shirts"})
    else:
        response = client.post(path, files={
            "file": ("invoice.txt", b"cotton shirts", "text/plain"),
        })
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/api/classify/raw", "/api/invoice/upload"])
def test_trade_details_require_valid_country_codes(path):
    client = TestClient(main.app)
    invalid_trade = {**TRADE, "origin_country": "ESP"}
    if path == "/api/classify/raw":
        response = client.post(path, json={"text": "cotton shirts", "trade": invalid_trade})
    else:
        response = client.post(path, data={
            **TRADE_FORM, "origin_country": "ESP",
        }, files={"file": ("invoice.txt", b"cotton shirts", "text/plain")})
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
        data={**TRADE_FORM, "modelo": "other", "proveedor": "other"},
    )
    assert response.status_code == 200
    assert response.json()["trade"] == TRADE
    tariffai.classify_batch.assert_awaited_once_with(
        ["cotton shirts"], language="en", trade=TRADE,
    )


def test_tariffai_client_sends_descriptions_and_language_and_preserves_batching():
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
            await client.classify_one("cotton shirts", trade=TRADE)
            assert len(await client.classify_batch(["cotton shirts"] * 51, trade=TRADE)) == 51

    asyncio.run(exercise())
    assert requests == [
        ("/classify", {"description": "cotton shirts", "language": "en", "trade": TRADE}),
        ("/classify/batch", {"descriptions": ["cotton shirts"] * 50, "language": "en", "trade": TRADE}),
        ("/classify/batch", {"descriptions": ["cotton shirts"], "language": "en", "trade": TRADE}),
    ]


@pytest.mark.parametrize("use_context_manager", [False, True])
def test_classification_waits_longer_but_health_and_connection_stay_bounded(monkeypatch, use_context_manager):
    observed = {}
    original_client = httpx.AsyncClient

    def handle(request):
        observed[request.url.path] = request.extensions["timeout"]
        return httpx.Response(200, json={"status": "error", "error": "test response"})

    def make_http_client(**kwargs):
        return original_client(
            transport=httpx.MockTransport(handle), trust_env=False, **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", make_http_client)

    async def exercise():
        client = TariffAIClient(base_url="http://tariffai")
        if use_context_manager:
            async with client:
                await client.classify_one("cotton shirts")
                await client.health()
        else:
            try:
                await client.classify_one("cotton shirts")
                await client.health()
            finally:
                await client.client.aclose()

    asyncio.run(exercise())
    assert observed["/classify"]["read"] == 600
    assert observed["/classify"]["connect"] == 10
    assert observed["/health"]["read"] == observed["/health"]["connect"] == 3


def test_batch_deadline_covers_all_pages_without_retrying():
    calls = []

    async def handle(request):
        calls.append(request)
        await asyncio.sleep(0.15)
        count = len(json.loads(request.content)["descriptions"])
        return httpx.Response(200, json=[{"status": "error", "error": "test"}] * count)

    async def exercise():
        client = TariffAIClient(base_url="http://tariffai", timeout=0.25)
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            with pytest.raises(TimeoutError):
                await client.classify_batch(["cotton shirts"] * 51)

    asyncio.run(exercise())
    assert len(calls) == 2


@pytest.mark.parametrize("timeout", [httpx.ReadTimeout(""), TimeoutError()])
@pytest.mark.parametrize("path", ["/api/classify", "/api/classify/raw", "/api/invoice/upload"])
def test_classification_timeout_returns_explicit_504(monkeypatch, timeout, path):
    tariffai = Mock()
    tariffai.classify_one = AsyncMock(side_effect=timeout)
    tariffai.classify_batch = AsyncMock(side_effect=timeout)
    context = AsyncMock()
    context.__aenter__.return_value = tariffai
    monkeypatch.setattr(main, "make_client", lambda: context)
    monkeypatch.setattr(main, "parse_invoice", Mock(return_value=Mock(
        source="text", pages=None, descriptions=["cotton shirts"],
    )))

    client = TestClient(main.app)
    if path == "/api/invoice/upload":
        response = client.post(
            path, files={"file": ("invoice.txt", b"cotton shirts", "text/plain")},
            data=TRADE_FORM,
        )
    else:
        field = "description" if path == "/api/classify" else "text"
        payload = {field: "cotton shirts"}
        if path == "/api/classify/raw":
            payload["trade"] = TRADE
        response = client.post(path, json=payload)
    assert response.status_code == 504
    assert "tiempo de espera" in response.json()["detail"]


def test_progress_is_concurrent_bounded_and_deduplicated():
    async def exercise():
        active = 0
        peak = 0
        calls = []
        release_first = asyncio.Event()
        cancelled = []

        async def handle(request):
            nonlocal active, peak
            description = json.loads(request.content)["description"]
            calls.append(description)
            active += 1
            peak = max(peak, active)
            try:
                if description == "first":
                    await release_first.wait()
                else:
                    await asyncio.sleep(0)
                return httpx.Response(200, json={"status": "error", "error": description})
            except asyncio.CancelledError:
                cancelled.append(description)
                raise
            finally:
                active -= 1

        client = TariffAIClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            results = client.classify_progress(["first", "second", "third", "second", "fourth"])
            first_index, _ = await anext(results)
            assert first_index != 0
            assert peak == 3
            assert active > 0
            release_first.set()
            completed = [(first_index, None)] + [entry async for entry in results]
        assert sorted(index for index, _ in completed) == [0, 1, 2, 3, 4]
        assert len(calls) == 4
        assert calls.count("second") == 1
        assert peak <= 3
        assert active == 0
        assert not cancelled

    asyncio.run(exercise())


def test_progress_cancellation_stops_remaining_requests():
    async def exercise():
        active = 0
        started = []
        gate = asyncio.Event()

        async def handle(request):
            nonlocal active
            description = json.loads(request.content)["description"]
            started.append(description)
            active += 1
            try:
                if description != "fast":
                    await gate.wait()
                return httpx.Response(200, json={"status": "error", "error": "test"})
            finally:
                active -= 1

        client = TariffAIClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            results = client.classify_progress(["fast", "slow", "slower", "not started"])
            assert (await anext(results))[0] == 0
            await results.aclose()
        assert active == 0
        assert "not started" not in started

    asyncio.run(exercise())


def test_progress_deadline_cancels_inflight_requests():
    async def exercise():
        cancelled = []

        async def handle(request):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(request)

        client = TariffAIClient(base_url="http://tariffai", timeout=0.02)
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            results = client.classify_progress(["first", "second"])
            with pytest.raises(TimeoutError):
                await anext(results)
        assert len(cancelled) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("path", ["/api/classify/raw", "/api/invoice/upload"])
def test_streaming_routes_send_stages_and_out_of_order_results(monkeypatch, path):
    from app.tariffai_client import ClassifyResponse

    async def classify_progress(descriptions, language="en", trade=None):
        assert descriptions == ["first shirt", "second shirt"]
        assert trade == TRADE
        yield 1, ClassifyResponse(status="error", error="test result")
        yield 0, ClassifyResponse(status="error", error="test result")

    tariffai = Mock(classify_progress=classify_progress)
    context = AsyncMock()
    context.__aenter__.return_value = tariffai
    monkeypatch.setattr(main, "make_client", lambda: context)
    monkeypatch.setattr(main, "parse_invoice", Mock(return_value=Mock(
        source="text", pages=1, descriptions=["first shirt", "second shirt"],
    )))
    client = TestClient(main.app)
    headers = {"accept": "application/x-ndjson"}
    if path == "/api/invoice/upload":
        response = client.post(path, headers=headers, files={
            "file": ("invoice.txt", b"first shirt\nsecond shirt", "text/plain"),
        }, data=TRADE_FORM)
    else:
        response = client.post(path, headers=headers, json={
            "text": "first shirt\nsecond shirt", "trade": TRADE,
        })
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["stage", "ready", "item", "item", "done"]
    assert events[0]["stage"] == "parsing"
    assert events[1]["total"] == 2
    assert events[1]["invoice"]["trade"] == TRADE
    assert [event["index"] for event in events if event["type"] == "item"] == [1, 0]
    assert events[2]["item"]["line_number"] == 2


def test_streaming_error_preserves_previous_events(monkeypatch):
    from app.tariffai_client import ClassifyResponse

    async def classify_progress(descriptions, language="en", trade=None):
        yield 0, ClassifyResponse(status="error", error="test result")
        raise TimeoutError()

    context = AsyncMock()
    context.__aenter__.return_value = Mock(classify_progress=classify_progress)
    monkeypatch.setattr(main, "make_client", lambda: context)
    response = TestClient(main.app).post(
        "/api/classify/raw", json={"text": "first shirt\nsecond shirt", "trade": TRADE},
        headers={"accept": "application/x-ndjson"},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["stage", "ready", "item", "error"]
    assert events[-1]["status"] == 504


def test_live_http_stream_delivers_events_before_classification_finishes(monkeypatch):
    import socket

    import uvicorn
    from app.tariffai_client import ClassifyResponse

    async def exercise():
        first_result = asyncio.Event()
        finish = asyncio.Event()

        async def classify_progress(descriptions, language="en", trade=None):
            await first_result.wait()
            yield 1, ClassifyResponse(status="error", error="test result")
            await finish.wait()
            yield 0, ClassifyResponse(status="error", error="test result")

        context = AsyncMock()
        context.__aenter__.return_value = Mock(classify_progress=classify_progress)
        monkeypatch.setattr(main, "make_client", lambda: context)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                main.app, log_level="error", access_log=False, lifespan="off",
            ))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        await asyncio.sleep(0.01)
                    async with httpx.AsyncClient(trust_env=False) as client:
                        async with client.stream(
                            "POST", f"http://127.0.0.1:{port}/api/classify/raw",
                            json={"text": "first shirt\nsecond shirt", "trade": TRADE},
                            headers={"accept": "application/x-ndjson"},
                        ) as response:
                            lines = response.aiter_lines()
                            assert json.loads(await anext(lines))["type"] == "stage"
                            assert json.loads(await anext(lines))["type"] == "ready"
                            first_result.set()
                            assert json.loads(await anext(lines))["index"] == 1
                            assert not finish.is_set()
                            finish.set()
                            assert json.loads(await anext(lines))["index"] == 0
                            assert json.loads(await anext(lines))["type"] == "done"
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, timeout=5)

    asyncio.run(exercise())


def test_reused_results_do_not_count_tokens_twice():
    async def exercise():
        calls = []

        async def handle(request):
            calls.append(request)
            return httpx.Response(200, json={
                "status": "classified",
                "result": {
                    "input_text": "same shirt", "confidence": 0.9,
                    "prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30,
                },
            })

        client = TariffAIClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            results = [response async for _, response in client.classify_progress(["same shirt", "same shirt"])]
        assert len(calls) == 1
        assert len(results) == 2
        assert results[0].result.total_tokens == 30
        assert results[1].result.total_tokens == 0
        assert results[0].result.input_text == results[1].result.input_text

    asyncio.run(exercise())


def test_progress_reports_line_errors_without_dropping_other_lines():
    async def exercise():
        async def handle(request):
            description = json.loads(request.content)["description"]
            if description == "bad shirt":
                raise httpx.ReadTimeout("")
            return httpx.Response(200, json={
                "status": "classified", "result": {"input_text": description, "confidence": 0.9},
            })

        client = TariffAIClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            results = {index: response async for index, response in client.classify_progress(
                ["bad shirt", "good shirt"],
            )}
        assert results[0].status == "error"
        assert results[0].error == "ReadTimeout"
        assert results[1].status == "classified"

    asyncio.run(exercise())


@pytest.mark.parametrize("language", ["es", "en"])
@pytest.mark.parametrize("path,streaming", [
    ("/api/classify", False),
    ("/api/classify/raw", False),
    ("/api/classify/raw", True),
    ("/api/invoice/upload", False),
    ("/api/invoice/upload", True),
])
def test_response_language_reaches_tariffai_on_every_route(monkeypatch, language, path, streaming):
    from contextlib import asynccontextmanager

    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        result = {"status": "error", "error": "test response"}
        return httpx.Response(200, json=[result] if request.url.path.endswith("/batch") else result)

    @asynccontextmanager
    async def make_client():
        client = TariffAIClient(base_url="http://tariffai")
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=httpx.MockTransport(handle),
        ) as transport:
            client._client = transport
            yield client

    monkeypatch.setattr(main, "make_client", make_client)
    client = TestClient(main.app)
    headers = {"accept": "application/x-ndjson"} if streaming else {}
    if path == "/api/invoice/upload":
        response = client.post(path, headers=headers, data={**TRADE_FORM, "language": language}, files={
            "file": ("invoice.txt", b"cotton shirts", "text/plain"),
        })
    else:
        field = "description" if path == "/api/classify" else "text"
        payload = {field: "cotton shirts", "language": language, "trade": TRADE}
        response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 200
    assert requests
    assert all(request["language"] == language for request in requests)
    assert all(request["trade"] == TRADE for request in requests)
    if streaming:
        assert json.loads(response.text.splitlines()[-1])["type"] == "done"


@pytest.mark.parametrize("path", ["/api/classify", "/api/classify/raw", "/api/invoice/upload"])
def test_unsupported_response_language_is_rejected(path):
    client = TestClient(main.app)
    if path == "/api/invoice/upload":
        response = client.post(path, data={**TRADE_FORM, "language": "fr"}, files={
            "file": ("invoice.txt", b"cotton shirts", "text/plain"),
        })
    else:
        field = "description" if path == "/api/classify" else "text"
        payload = {field: "cotton shirts", "language": "fr"}
        if path == "/api/classify/raw":
            payload["trade"] = TRADE
        response = client.post(path, json=payload)
    assert response.status_code == 422
