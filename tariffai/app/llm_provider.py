"""Azure Foundry or local OpenAI-compatible classification selected by LLM_PROVIDER."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

try:
    from azure.ai.projects import AIProjectClient
except ImportError:
    AIProjectClient = None
try:
    from azure.identity import ManagedIdentityCredential
except ImportError:
    ManagedIdentityCredential = None

from app.config import (
    AZURE_AI_MODEL_DEPLOYMENT,
    AZURE_AI_PROJECT_ENDPOINT,
    LLM_PROVIDER,
    LOCAL_LLM_API_KEY,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_TIMEOUT,
)

_MAX_COMPLETION_TOKENS = 16384


@dataclass
class LLMResponse:
    text: str
    thinking: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class FoundryProvider:
    def __init__(self) -> None:
        if not AZURE_AI_PROJECT_ENDPOINT or not AZURE_AI_MODEL_DEPLOYMENT:
            raise RuntimeError(
                "AZURE_AI_PROJECT_ENDPOINT y AZURE_AI_MODEL_DEPLOYMENT son obligatorias"
            )
        if AIProjectClient is None or ManagedIdentityCredential is None:
            raise RuntimeError(
                "azure-ai-projects y azure-identity son obligatorios para Azure Foundry"
            )
        self._credential = ManagedIdentityCredential()
        self._project = AIProjectClient(
            endpoint=AZURE_AI_PROJECT_ENDPOINT,
            credential=self._credential,
        )
        self._client = self._project.get_openai_client()

    def complete(self, *, system: str, user: str) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=AZURE_AI_MODEL_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
        )
        if not response.choices:
            raise RuntimeError("Azure Foundry devolvió una respuesta sin alternativas")
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise RuntimeError(
                f"Azure Foundry no completó la clasificación: {choice.finish_reason}"
            )
        text = (choice.message.content or "").strip()
        if not text:
            raise RuntimeError("Azure Foundry devolvió una respuesta vacía")
        reasoning = (choice.message.model_extra or {}).get("reasoning_content")
        usage = response.usage
        return LLMResponse(
            text=text,
            thinking=reasoning if isinstance(reasoning, str) else None,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )


class LocalOpenAIProvider:
    def __init__(self) -> None:
        self.base_url = str(LOCAL_LLM_BASE_URL or "").strip().rstrip("/")
        self.model = str(LOCAL_LLM_MODEL or "").strip()
        self.api_key = str(LOCAL_LLM_API_KEY or "").strip()
        self.timeout = LOCAL_LLM_TIMEOUT
        if not self.base_url or not self.model:
            raise RuntimeError(
                "LOCAL_LLM_BASE_URL y LOCAL_LLM_MODEL son obligatorios cuando LLM_PROVIDER=local"
            )

    def _endpoint(self) -> str:
        base = self.base_url
        if not base.startswith(("http://", "https://")):
            base = f"http://{base}"
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def complete(self, *, system: str, user: str) -> LLMResponse:
        endpoint = self._endpoint()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": _MAX_COMPLETION_TOKENS,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Error al conectar con el LLM local: {exc}") from exc

        raw = ""
        try:
            raw = response.read().decode("utf-8")
        except (AttributeError, UnicodeError) as exc:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            raise RuntimeError("La respuesta del LLM local no es UTF-8 válido") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"El LLM local devolvió JSON inválido: {raw[:200]}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("El LLM local devolvió una respuesta sin alternativas")

        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("El LLM local devolvió una respuesta sin alternativas")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise RuntimeError("El LLM local devolvió una respuesta sin alternativas")

        finish_reason = choice.get("finish_reason")
        if finish_reason not in {None, "", "stop", "eos", "end_turn", "none"}:
            raise RuntimeError(f"El LLM local no completó la clasificación: {finish_reason}")

        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        text = content.strip() if isinstance(content, str) else ""
        if not text:
            raise RuntimeError("El LLM local devolvió una respuesta vacía")

        reasoning = message.get("reasoning_content")
        model_extra = message.get("model_extra")
        if isinstance(model_extra, dict) and not isinstance(reasoning, str):
            reasoning = model_extra.get("reasoning_content")
        if not isinstance(reasoning, str):
            reasoning = message.get("reasoning")
        if not isinstance(reasoning, str):
            reasoning = None

        usage_value = parsed.get("usage")
        usage = usage_value if isinstance(usage_value, dict) else {}
        prompt_tokens = _as_int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        output_tokens = _as_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        total_tokens = _as_int(usage.get("total_tokens", 0)) or prompt_tokens + output_tokens
        return LLMResponse(
            text=text,
            thinking=reasoning,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )


Provider = FoundryProvider | LocalOpenAIProvider


@lru_cache(maxsize=1)
def get_provider() -> Provider:
    selection = (LLM_PROVIDER or "azure").strip().lower()
    if selection == "azure":
        return FoundryProvider()
    if selection == "local":
        return LocalOpenAIProvider()
    raise RuntimeError(f"LLM_PROVIDER debe ser 'azure' o 'local', pero fue {selection!r}")


def extract_json(text: str) -> dict[str, Any]:
    """Parse `text` as JSON, including responses wrapped in markdown fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1).strip())
        raise ValueError(f"LLM devolvió JSON inválido: {text[:200]}")
