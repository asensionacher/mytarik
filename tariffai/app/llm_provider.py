"""Azure Foundry classification with system-assigned managed identity."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import ManagedIdentityCredential

from app.config import AZURE_AI_MODEL_DEPLOYMENT, AZURE_AI_PROJECT_ENDPOINT


@dataclass
class LLMResponse:
    text: str
    thinking: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class FoundryProvider:
    def __init__(self) -> None:
        if not AZURE_AI_PROJECT_ENDPOINT or not AZURE_AI_MODEL_DEPLOYMENT:
            raise RuntimeError(
                "AZURE_AI_PROJECT_ENDPOINT y AZURE_AI_MODEL_DEPLOYMENT son obligatorias"
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
            # Includes the thinking model's reasoning and final JSON.
            max_completion_tokens=16384,
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


@lru_cache(maxsize=1)
def get_provider() -> FoundryProvider:
    return FoundryProvider()


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
