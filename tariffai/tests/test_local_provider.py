import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock
from urllib.error import URLError

import pytest

if "dotenv" not in sys.modules:
    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm_provider


def _use_local(monkeypatch, *, base="http://host", model="model", api_key=""):
    monkeypatch.setattr("app.llm_provider.LLM_PROVIDER", "local")
    monkeypatch.setattr("app.llm_provider.LOCAL_LLM_BASE_URL", base)
    monkeypatch.setattr("app.llm_provider.LOCAL_LLM_MODEL", model)
    monkeypatch.setattr("app.llm_provider.LOCAL_LLM_API_KEY", api_key)
    monkeypatch.setattr("app.llm_provider.LOCAL_LLM_TIMEOUT", 1)


def _call_get_provider():
    llm_provider.get_provider.cache_clear()
    return llm_provider.get_provider()


class _JSONResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.raw

    def close(self):
        return None


class _RawResponse:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw

    def close(self):
        return None


def test_get_provider_selects_local(monkeypatch):
    _use_local(monkeypatch, base="http://host/v1", model="model")
    provider = _call_get_provider()
    assert callable(provider.complete)


def test_get_provider_selects_azure(monkeypatch):
    monkeypatch.setattr("app.llm_provider.LLM_PROVIDER", "azure")
    monkeypatch.setattr("app.llm_provider.AZURE_AI_PROJECT_ENDPOINT", "https://azure")
    monkeypatch.setattr("app.llm_provider.AZURE_AI_MODEL_DEPLOYMENT", "model")
    monkeypatch.setattr("app.llm_provider.AIProjectClient", MagicMock())
    monkeypatch.setattr("app.llm_provider.ManagedIdentityCredential", MagicMock())

    provider = _call_get_provider()
    assert callable(provider.complete)


def test_get_provider_rejects_unknown_selection(monkeypatch):
    monkeypatch.setattr("app.llm_provider.LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError):
        _call_get_provider()


def test_local_provider_requires_local_config(monkeypatch):
    _use_local(monkeypatch, base="", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider()


def test_local_provider_accepts_v1_base(monkeypatch):
    called = []

    def fake_urlopen(request, timeout=None):
        called.append(request.full_url)
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    provider = llm_provider.LocalOpenAIProvider()
    provider.complete(system="system", user="user")

    assert called == ["http://host/v1/chat/completions"]


def test_local_provider_accepts_root_base(monkeypatch):
    called = []

    def fake_urlopen(request, timeout=None):
        called.append(request.full_url)
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host", model="model")
    provider = llm_provider.LocalOpenAIProvider()
    provider.complete(system="system", user="user")

    assert called == ["http://host/v1/chat/completions"]


def test_local_provider_accepts_explicit_completion_endpoint(monkeypatch):
    called = []

    def fake_urlopen(request, timeout=None):
        called.append(request.full_url)
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1/chat/completions", model="model")
    provider = llm_provider.LocalOpenAIProvider()
    provider.complete(system="system", user="user")

    assert called == ["http://host/v1/chat/completions"]


def test_local_provider_normalizes_missing_scheme(monkeypatch):
    called = []

    def fake_urlopen(request, timeout=None):
        called.append(request.full_url)
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="host/v1", model="model")
    provider = llm_provider.LocalOpenAIProvider()
    provider.complete(system="system", user="user")

    assert called == ["http://host/v1/chat/completions"]


def test_local_provider_complete_success(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"code":"123456"}',
                            "reasoning_content": "because it is machinery",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    response = llm_provider.LocalOpenAIProvider().complete(
        system="system",
        user="user",
    )

    assert response.text == '{"code":"123456"}'
    assert response.thinking == "because it is machinery"
    assert response.prompt_tokens == 11
    assert response.output_tokens == 7
    assert response.total_tokens == 18


def test_local_provider_reads_model_extra_reasoning(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"code":"123456"}',
                            "model_extra": {"reasoning_content": "nested"},
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    response = llm_provider.LocalOpenAIProvider().complete(
        system="system",
        user="user",
    )

    assert response.thinking == "nested"


def test_local_provider_reads_alternative_usage(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 3,
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    response = llm_provider.LocalOpenAIProvider().complete(
        system="system",
        user="user",
    )

    assert response.prompt_tokens == 2
    assert response.output_tokens == 3
    assert response.total_tokens == 5


def test_local_provider_accepts_eos_finish_reason(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "eos",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    response = llm_provider.LocalOpenAIProvider().complete(
        system="system",
        user="user",
    )

    assert response.text == '{"code":"123456"}'


def test_local_provider_rejects_empty_choices(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse({"choices": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider().complete(system="system", user="user")


def test_local_provider_rejects_non_dict_choice(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse({"choices": ["nope"]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider().complete(system="system", user="user")


def test_local_provider_rejects_bad_finish_reason(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "length",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider().complete(system="system", user="user")


def test_local_provider_rejects_empty_content(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": "   "},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider().complete(system="system", user="user")


def test_local_provider_rejects_non_json_response(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _RawResponse(b"not json")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider().complete(system="system", user="user")


def test_local_provider_wraps_network_errors(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model")
    with pytest.raises(RuntimeError):
        llm_provider.LocalOpenAIProvider().complete(system="system", user="user")


def test_local_provider_keeps_authorization_when_api_key_set(monkeypatch):
    called = []

    def fake_urlopen(request, timeout=None):
        called.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer secret"
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": '{"code":"123456"}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch, base="http://host/v1", model="model", api_key="secret")
    provider = llm_provider.LocalOpenAIProvider()
    provider.complete(system="system", user="user")

    assert called == ["http://host/v1/chat/completions"]
