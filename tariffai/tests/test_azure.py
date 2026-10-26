import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
import requests
from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import RequestsTransport
from pydantic import ValidationError

from app import llm_provider, translation
from app.schemas import BatchClassifyRequest, ClassifyRequest, TradeContext


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
        assert result["result"]["total_tokens"] == 60
    assert provider.complete.call_count == 4
    assert set(provider.complete.call_args.kwargs) == {"system", "user"}


def test_trade_context_reaches_the_classification_prompt(monkeypatch):
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
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "610510", "confidence": 0.95,
        "primary_description": "Cotton shirts", "reasoning": {},
    }))
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    trade = TradeContext(
        trade_mode="import", origin_country="ES", dispatch_country="CN",
    )
    client = TestClient(main.app)
    single = client.post("/classify", json={
        "description": "cotton shirts", "trade": trade.model_dump(),
    })
    batch = client.post("/classify/batch", json={
        "descriptions": ["cotton shirts"], "trade": trade.model_dump(),
    })
    assert single.status_code == batch.status_code == 200
    assert provider.complete.call_count == 4
    for call in provider.complete.call_args_list:
        user_prompt = call.kwargs["user"]
        assert "Operation: import" in user_prompt
        assert "Country of origin (ISO 3166-1 alpha-2): ES" in user_prompt
        assert "Country of dispatch (ISO 3166-1 alpha-2): CN" in user_prompt


def test_primary_code_outside_retrieved_candidates_is_discarded(monkeypatch):
    from app import llm_classifier
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105",
        heading_description="Shirts", retrieval_score=1.0, retrieval_method="hybrid",
    )
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "999999", "confidence": 0.99,
        "primary_description": "Invalid code", "reasoning": {},
    }))
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    result = llm_classifier.classify_with_llm("cotton shirts", [candidate])
    assert result.primary_code is None
    assert result.is_ambiguous is True


@pytest.mark.parametrize("schema,payload", [
    (ClassifyRequest, {"description": "cotton shirts"}),
    (BatchClassifyRequest, {"descriptions": ["cotton shirts"]}),
])
@pytest.mark.parametrize("override", [{"provider": "other"}, {"model": "other"}])
def test_requests_reject_provider_and_model_overrides(schema, payload, override):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        schema(**payload, **override)


@pytest.mark.parametrize("language,language_name", [("es", "Spanish"), ("en", "English")])
def test_response_language_flows_through_routes_graph_and_foundry(monkeypatch, language, language_name):
    from fastapi.testclient import TestClient

    from app import graph, llm_classifier, main
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105", heading_description="Shirts",
        section="XI", section_description="Textiles", retrieval_score=1.0, retrieval_method="hybrid",
    )
    spanish = language == "es"
    primary = "Camisas de algodón" if spanish else "Cotton shirts"
    explanation = "La prenda es de algodón." if spanish else "The garment is made of cotton."
    descriptions = {
        "section": "Textiles",
        "chapter": "Prendas de punto" if spanish else "Knitted apparel",
        "heading": "Camisas" if spanish else "Shirts",
    }
    alternative = candidate.model_copy(update={"code": "610590", "retrieval_score": 0.8})
    monkeypatch.setattr(graph, "retrieve_candidates", Mock(return_value=[candidate, alternative]))
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "610510", "primary_description": primary, "confidence": 0.95,
        "hierarchy_descriptions": descriptions,
        "reasoning": {
            **{f"{level}_reasoning": explanation for level in ("section", "chapter", "heading", "subheading")},
            "key_factors": ["algodón" if spanish else "cotton"],
        },
        "alternative_codes": [{"code": "610590", "description": primary, "why_not": explanation, "trade_off": explanation}],
    }), thinking=explanation)
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    client = TestClient(main.app)
    for path, payload in [
        ("/classify", {"description": "camisas de algodón"}),
        ("/classify/batch", {"descriptions": ["camisas de algodón"]}),
    ]:
        response = client.post(path, json={**payload, "language": language})
        assert response.status_code == 200
        body = response.json()
        classification = body[0] if isinstance(body, list) else body
        assert classification["status"] == "classified"
        result = classification["result"]
        assert result["primary_code"] == "610510"
        assert result["primary_description"] == primary
        assert result["hierarchy"]["chapter"] == {"code": "61", "description": descriptions["chapter"]}
        assert result["hierarchy"]["heading"] == {"code": "6105", "description": descriptions["heading"]}
        assert result["hierarchy"]["subheading"] == {"code": "610510", "description": primary}
        assert result["reasoning"]["chapter_reasoning"] == explanation
        assert result["alternative_codes"][0]["trade_off"] == explanation
        assert result["thinking"] == explanation
        assert result["input_text"] == "camisas de algodón"
    for call in provider.complete.call_args_list:
        assert f"Response language: {language_name}" in call.kwargs["system"]
        assert "hierarchy_descriptions" in call.kwargs["system"]


def test_missing_localized_hierarchy_is_recovered_from_catalogue(monkeypatch):
    from app import llm_classifier
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105",
        heading_description="Shirts", retrieval_score=1.0, retrieval_method="hybrid",
    )
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "610510", "primary_description": "Camisas de algodón", "confidence": 0.9,
    }))
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    descriptions = {"Knitted apparel": "Prendas de punto", "Shirts": "Camisas"}
    translate = Mock(side_effect=lambda text, language: descriptions[text])
    monkeypatch.setattr(llm_classifier, "translate_from_en", translate)
    result = llm_classifier.classify_with_llm("cotton shirts", [candidate], language="es")
    assert result.primary_code == "610510"
    assert result.primary_description == "Camisas de algodón"
    assert result.confidence == 0.9
    assert result.hierarchy["section"]["description"] == ""
    assert result.hierarchy["chapter"]["description"] == "Prendas de punto"
    assert result.hierarchy["heading"]["description"] == "Camisas"
    assert result.hierarchy["subheading"]["description"] == "Camisas de algodón"
    assert translate.call_args_list == [call("Knitted apparel", "es"), call("Shirts", "es")]
    provider.complete.assert_called_once()


@pytest.mark.parametrize("level,value", [("section", None), ("chapter", ""), ("heading", "   ")])
def test_only_missing_localized_field_uses_translator(monkeypatch, caplog, level, value):
    from app import llm_classifier
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105", heading_description="Shirts",
        section="XI", section_description="Textiles and textile articles",
        retrieval_score=1.0, retrieval_method="hybrid",
    )
    localized = {"section": "Materias textiles y sus manufacturas", "chapter": "Prendas de punto", "heading": "Camisas"}
    expected = localized.copy()
    if value is None:
        localized.pop(level)
    else:
        localized[level] = value
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "610510", "primary_description": "Camisas de algodón",
        "confidence": 0.91, "hierarchy_descriptions": localized,
    }), prompt_tokens=7, output_tokens=11, total_tokens=18)
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    translate = Mock(return_value=expected[level])
    monkeypatch.setattr(llm_classifier, "translate_from_en", translate)
    result = llm_classifier.classify_with_llm("cotton shirts", [candidate], language="es")
    source = {
        "section": candidate.section_description,
        "chapter": candidate.chapter_description,
        "heading": candidate.heading_description,
    }
    translate.assert_called_once_with(source[level], "es")
    assert {key: result.hierarchy[key]["description"] for key in expected} == expected
    assert result.primary_code == "610510"
    assert result.confidence == 0.91
    assert (result.prompt_tokens, result.output_tokens, result.total_tokens) == (7, 11, 18)
    assert f"localized {level} description" in caplog.text
    provider.complete.assert_called_once()


def test_missing_primary_description_is_translated_from_catalogue(monkeypatch):
    from app import llm_classifier
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105", heading_description="Shirts",
        retrieval_score=1.0, retrieval_method="hybrid",
    )
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "610510", "confidence": 0.9,
        "hierarchy_descriptions": {"chapter": "Prendas de punto", "heading": "Camisas"},
    }))
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    translate = Mock(return_value="Camisas de algodón")
    monkeypatch.setattr(llm_classifier, "translate_from_en", translate)
    result = llm_classifier.classify_with_llm("cotton shirts", [candidate], language="es")
    translate.assert_called_once_with("Cotton shirts", "es")
    assert result.primary_description == result.hierarchy["subheading"]["description"] == "Camisas de algodón"
    assert result.primary_code == "610510"


def test_catalogue_translation_uses_requested_language_and_caches_results(monkeypatch):
    translation.translate_from_en.cache_clear()
    client = Mock()
    client.translate.return_value = [SimpleNamespace(translations=[SimpleNamespace(text="Camisas")])]
    monkeypatch.setattr(translation, "_get_translator", lambda: client)
    try:
        assert translation.translate_from_en("Shirts", "es") == "Camisas"
        assert translation.translate_from_en("Shirts", "es") == "Camisas"
        assert translation.translate_from_en("Shirts", "en") == "Shirts"
        client.translate.assert_called_once_with(body=["Shirts"], to_language=["es"], from_language="en")
    finally:
        translation.translate_from_en.cache_clear()


def test_catalogue_recovery_does_not_hide_translator_errors(monkeypatch):
    from app import llm_classifier
    from app.schemas import HSCandidate

    candidate = HSCandidate(
        code="610510", description="Cotton shirts", chapter_code="61",
        chapter_description="Knitted apparel", heading_code="6105", heading_description="Shirts",
        retrieval_score=1.0, retrieval_method="hybrid",
    )
    provider = Mock()
    provider.complete.return_value = llm_provider.LLMResponse(text=json.dumps({
        "primary_code": "610510", "primary_description": "Camisas de algodón", "confidence": 0.9,
    }))
    monkeypatch.setattr(llm_classifier, "get_provider", lambda: provider)
    translate = Mock(side_effect=HttpResponseError("Translator permission denied"))
    monkeypatch.setattr(llm_classifier, "translate_from_en", translate)
    with pytest.raises(HttpResponseError, match="Translator permission denied"):
        llm_classifier.classify_with_llm("cotton shirts", [candidate], language="es")
