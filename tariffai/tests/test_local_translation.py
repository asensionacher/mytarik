import json
import sys
from pathlib import Path
from types import ModuleType
from urllib.error import URLError

import pytest

if "dotenv" not in sys.modules:
    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import translation


class _JSONResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.raw

    def close(self):
        return None


def _use_local(monkeypatch, *, base="http://host/v1", model="model", api_key=""):
    monkeypatch.setattr("app.translation.TRANSLATION_PROVIDER", "local")
    monkeypatch.setattr("app.translation.LOCAL_LLM_BASE_URL", base)
    monkeypatch.setattr("app.translation.LOCAL_LLM_MODEL", model)
    monkeypatch.setattr("app.translation.LOCAL_LLM_API_KEY", api_key)
    monkeypatch.setattr("app.translation.LOCAL_LLM_TIMEOUT", 1)
    translation._get_local_translator.cache_clear()
    translation.translate_to_en.cache_clear()
    translation.translate_from_en.cache_clear()


def test_local_translation_to_english(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append((request.full_url, json.loads(request.data.decode("utf-8"))))
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": "Men's cotton shirts"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch)

    assert translation.translate_to_en("Camisas de algodón para hombre") == "Men's cotton shirts"
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "http://host/v1/chat/completions"
    assert payload["messages"][1]["content"].startswith("Translate from the source language")
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["stream"] is False


def test_local_translation_from_english_to_spanish(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(json.loads(request.data.decode("utf-8")))
        return _JSONResponse(
            {
                "choices": [
                    {
                        "message": {"content": "Camisas de algodón para hombre"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch)

    result = translation.translate_from_en("Men's cotton shirts", "es")
    assert result == "Camisas de algodón para hombre"
    prompt = calls[0]["messages"][1]["content"]
    assert "from English to Spanish" in prompt
    assert "TEXT:\nMen's cotton shirts" in prompt


def test_local_translation_requires_config(monkeypatch):
    _use_local(monkeypatch, base="", model="model")
    with pytest.raises(RuntimeError, match="LOCAL_LLM_BASE_URL"):
        translation.LocalLLMTranslator()


def test_local_translation_does_not_import_azure(monkeypatch):
    _use_local(monkeypatch)
    # The module can be imported and constructed without the Azure SDK.
    translator = translation.LocalLLMTranslator()
    assert callable(translator.translate)


def test_local_translation_errors_are_explicit(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch)

    with pytest.raises(RuntimeError, match="No se pudo conectar con el traductor local"):
        translation.translate_to_en("Camisas")


def test_local_translation_does_not_call_for_empty_text(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        return _JSONResponse({"choices": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _use_local(monkeypatch)

    assert translation.translate_to_en("   ") == "   "
    assert calls == []


def test_local_mt_uses_dedicated_translator(monkeypatch):
    calls = []

    class FakeMT:
        def translate(self, text, target_language, source_language=None):
            calls.append((text, target_language, source_language))
            return "TRANSLATED"

    monkeypatch.setattr("app.translation.TRANSLATION_PROVIDER", "local_mt")
    monkeypatch.setattr("app.translation._get_mt_translator", lambda: FakeMT())
    translation.translate_to_en.cache_clear()
    translation.translate_from_en.cache_clear()

    assert translation.translate_to_en("Camisas") == "TRANSLATED"
    assert translation.translate_from_en("Shirts", "es") == "TRANSLATED"
    assert calls == [
        ("Camisas", "en", None),
        ("Shirts", "es", "en"),
    ]
