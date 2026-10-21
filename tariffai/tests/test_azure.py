import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import RequestsTransport
from pydantic import ValidationError

from app import llm_provider, translation
from app.schemas import BatchClassifyRequest, ClassifyRequest


def test_foundry_uses_project_managed_identity_and_server_deployment(monkeypatch):
    credential = Mock()
    credential_class = Mock(return_value=credential)
    project = Mock()
    project_class = Mock(return_value=project)
    monkeypatch.setattr(llm_provider, "ManagedIdentityCredential", credential_class)
    monkeypatch.setattr(llm_provider, "AIProjectClient", project_class)
    monkeypatch.setattr(llm_provider, "AZURE_AI_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/default")
    monkeypatch.setattr(llm_provider, "AZURE_AI_MODEL_DEPLOYMENT", "MAI-Thinking-1")
    project.get_openai_client.return_value.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content='{"confidence": 0.9}', model_extra={"reasoning_content": "Comparison of candidates"},
            )
        )],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=30, total_tokens=50),
    )

    response = llm_provider.FoundryProvider().complete(system="JSON only", user="cotton shirts")

    credential_class.assert_called_once_with()
    project_class.assert_called_once_with(
        endpoint="https://test.services.ai.azure.com/api/projects/default",
        credential=credential,
    )
    request = project.get_openai_client.return_value.chat.completions.create.call_args.kwargs
    assert request["model"] == "MAI-Thinking-1"
    assert request["messages"] == [
        {"role": "system", "content": "JSON only"},
        {"role": "user", "content": "cotton shirts"},
    ]
    assert response.text == '{"confidence": 0.9}'
    assert response.thinking == "Comparison of candidates"
    assert (response.prompt_tokens, response.output_tokens, response.total_tokens) == (20, 30, 50)


@pytest.mark.parametrize("finish_reason,content", [("length", "{}"), ("content_filter", None), ("stop", "")])
def test_foundry_rejects_incomplete_or_empty_output(monkeypatch, finish_reason, content):
    project_class = Mock()
    monkeypatch.setattr(llm_provider, "AIProjectClient", project_class)
    monkeypatch.setattr(llm_provider, "ManagedIdentityCredential", Mock())
    monkeypatch.setattr(llm_provider, "AZURE_AI_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/default")
    project_class.return_value.get_openai_client.return_value.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
    )
    with pytest.raises(RuntimeError, match="Azure Foundry"):
        llm_provider.FoundryProvider().complete(system="JSON", user="shirts")


def test_translator_uses_managed_identity_and_caches_english_translation(monkeypatch):
    translation._get_translator.cache_clear()
    translation.translate_to_en.cache_clear()
    credential = Mock()
    credential_class = Mock(return_value=credential)
    client_class = Mock()
    monkeypatch.setattr(translation, "ManagedIdentityCredential", credential_class)
    monkeypatch.setattr(translation, "TextTranslationClient", client_class)
    monkeypatch.setattr(translation, "AZURE_TRANSLATOR_ENDPOINT", "https://test.cognitiveservices.azure.com")
    client_class.return_value.translate.return_value = [
        SimpleNamespace(translations=[SimpleNamespace(text="cotton shirts")])
    ]
    try:
        assert translation.translate_to_en("camisas de algodon") == "cotton shirts"
        assert translation.translate_to_en("camisas de algodon") == "cotton shirts"
        credential_class.assert_called_once_with()
        client_class.assert_called_once_with(
            endpoint="https://test.cognitiveservices.azure.com", credential=credential,
        )
        client_class.return_value.translate.assert_called_once_with(
            body=["camisas de algodon"], to_language=["en"],
        )
    finally:
        translation._get_translator.cache_clear()
        translation.translate_to_en.cache_clear()


@pytest.mark.parametrize("empty_result", [[], [SimpleNamespace(translations=[])], [SimpleNamespace(translations=[SimpleNamespace(text="")])]])
def test_translator_rejects_empty_translation(monkeypatch, empty_result):
    translation.translate_to_en.cache_clear()
    client = Mock()
    client.translate.return_value = empty_result
    monkeypatch.setattr(translation, "_get_translator", lambda: client)
    with pytest.raises(RuntimeError, match="Azure Translator"):
        translation.translate_to_en("camisas")


def test_translator_propagates_service_failure_without_fallback(monkeypatch):
    translation.translate_to_en.cache_clear()
    client = Mock()
    client.translate.side_effect = HttpResponseError("Access denied")
    monkeypatch.setattr(translation, "_get_translator", lambda: client)
    with pytest.raises(HttpResponseError, match="Access denied"):
        translation.translate_to_en("camisas")
    client.translate.side_effect = None
    client.translate.return_value = [SimpleNamespace(translations=[SimpleNamespace(text="shirts")])]
    assert translation.translate_to_en("camisas") == "shirts"
    translation.translate_to_en.cache_clear()


def test_translator_sdk_sends_resource_endpoint_and_entra_token(monkeypatch):
    translation.translate_to_en.cache_clear()
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("test-token", int(time.time()) + 3600)
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = b'[{"translations": [{"text": "shirts", "to": "en"}]}]'
    response._content_consumed = True
    response.raw = Mock()
    session = requests.Session()
    session.request = Mock(return_value=response)
    with TextTranslationClient(
        endpoint="https://test.cognitiveservices.azure.com",
        credential=credential,
        transport=RequestsTransport(session=session),
    ) as client:
        monkeypatch.setattr(translation, "_get_translator", lambda: client)
        assert translation.translate_to_en("camisas") == "shirts"
    request = session.request.call_args.kwargs
    url = session.request.call_args.args[1]
    assert url.startswith("https://test.cognitiveservices.azure.com/translator/text/v3.0/translate?")
    assert "to=en" in url
    assert request["headers"]["Authorization"] == "Bearer test-token"
    assert json.loads(request["data"]) == [{"text": "camisas"}]
    assert credential.get_token.call_args.args == ("https://cognitiveservices.azure.com/.default",)
    translation.translate_to_en.cache_clear()


def test_classification_routes_use_foundry_and_preserve_result(monkeypatch):
    from fastapi.testclient import TestClient

    from app import graph, llm_classifier, main
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105",
        heading_description="Shirts", retrieval_score=1.0, retrieval_method="hybrid",
    )
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[candidate]))
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(
        text=json.dumps({
            "primary_code": "610510", "confidence": 0.95,
            "primary_description": "Cotton shirts", "reasoning": {},
        }),
        prompt_tokens=10, output_tokens=20, total_tokens=30,
    )
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    client = TestClient(main.app)
    single = client.post("/classify", json={"description": "cotton shirts"})
    batch = client.post("/classify/batch", json={"descriptions": ["cotton shirts"]})
    assert single.status_code == batch.status_code == 200
    for result in (single.json(), batch.json()[0]):
        assert result["status"] == "classified"
        assert result["result"]["primary_code"] == "610510"
        assert result["result"]["hierarchy"]["heading"]["code"] == "6105"
        assert result["result"]["total_tokens"] == 30
    assert provider.complete.call_count == 2
    assert set(provider.complete.call_args.kwargs) == {"system", "user"}


@pytest.mark.parametrize("schema,payload", [
    (ClassifyRequest, {"description": "cotton shirts"}),
    (BatchClassifyRequest, {"descriptions": ["cotton shirts"]}),
])
@pytest.mark.parametrize("override", [{"provider": "other"}, {"model": "other"}])
def test_requests_reject_provider_and_model_overrides(schema, payload, override):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        schema(**payload, **override)
