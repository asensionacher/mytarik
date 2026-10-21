"""
llm_provider.py — abstracción sobre los proveedores LLM soportados.

Estrategia:
- `LLMProvider` define un contrato común (`complete`)
- `GeminiProvider` envuelve `google.genai` (legacy, default si no se cambia LLM_PROVIDER)
- `MinimaxProvider` envuelve el SDK de Anthropic con `base_url` apuntando al endpoint de MiniMax
- `get_provider()` cachea singletons por nombre para evitar reconstruir el cliente en cada request

Esto permite cambiar de proveedor sin tocar el resto del pipeline (LangGraph / schemas).
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.config import (
    GOOGLE_API_KEY,
    LLM_MODEL,
    LLM_PROVIDER,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    MINIMAX_DEFAULT_MODEL,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Respuesta normalizada de cualquier proveedor."""

    text: str                          # el texto "útil" (esperamos JSON)
    thinking: str | None = None        # razonamiento interno (solo MiniMax con effort=max)
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str = ""                    # qué modelo respondió realmente
    raw: Any = field(default=None, repr=False)  # respuesta cruda para debugging


class LLMProvider(ABC):
    """Interfaz común para todos los proveedores LLM."""

    name: str = "abstract"

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Ejecuta una llamada de completion y devuelve la respuesta normalizada."""


# ───────────────────────────── Gemini ─────────────────────────────


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        # Import perezoso: la SDK pesada solo se carga si eligen este provider.
        from google import genai  # noqa: WPS433

        self._client = genai.Client(api_key=api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        from google.genai import types

        # Gemini acepta un único `contents` string; concatenamos system + user.
        # El proveedor Gemini sabe forzar JSON vía response_mime_type.
        prompt = f"{system}\n\n{user}" if system else user

        response = self._client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=max_tokens,
            ),
        )

        text = (response.text or "").strip()

        usage = getattr(response, "usage_metadata", None)
        pt = int(getattr(usage, "prompt_token_count", 0) or 0)
        ot = int(getattr(usage, "candidates_token_count", 0) or 0)
        tt = int(getattr(usage, "total_token_count", 0) or 0) or (pt + ot)

        return LLMResponse(
            text=text,
            thinking=None,
            prompt_tokens=pt,
            output_tokens=ot,
            total_tokens=tt,
            model=model,
            raw=response,
        )


# ───────────────────────────── MiniMax ─────────────────────────────


class MinimaxProvider(LLMProvider):
    """
    MiniMax servido vía SDK de Anthropic (compatible Messages API).

    El SDK de Anthropic separa `system` de `messages[].content`.
    La respuesta es una lista de bloques; los `thinking` exponen el razonamiento
    interno y los `text` el contenido final (que pedimos en formato JSON).
    """

    name = "minimax"

    # Esfuerzo de razonamiento. Lo dejamos fijo en "max" porque es la opción
    # recomendada del proveedor en la doc actual.
    DEFAULT_EFFORT = "max"

    def __init__(self, api_key: str, base_url: str) -> None:
        # Import perezoso.
        import anthropic  # noqa: WPS433

        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or "You are a helpful assistant.",
            output_config={"effort": self.DEFAULT_EFFORT},
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user}],
                }
            ],
        )

        # Extraer bloques de texto y (si existe) el primer bloque de thinking
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        for block in message.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype == "thinking":
                thinking_parts.append(getattr(block, "thinking", "") or "")
            else:
                # Bloques tool_use / server_tool_use / etc. — los ignoramos por ahora.
                logger.debug("Minimax: ignorando bloque tipo %s", btype)

        text = "\n".join(p for p in text_parts if p).strip()
        thinking = "\n".join(p for p in thinking_parts if p).strip() or None

        usage = getattr(message, "usage", None) or {}
        pt = int(getattr(usage, "input_tokens", 0) or 0)
        ot = int(getattr(usage, "output_tokens", 0) or 0)
        tt = pt + ot

        # El modelo real que respondió (algunos endpoints lo completan o sobrescriben).
        used_model = getattr(message, "model", None) or model

        return LLMResponse(
            text=text,
            thinking=thinking,
            prompt_tokens=pt,
            output_tokens=ot,
            total_tokens=tt,
            model=used_model,
            raw=message,
        )


# ──────────────────────── Factory / Singleton ────────────────────────


_providers: dict[str, LLMProvider] = {}


def default_model_for(name: str) -> str:
    """Modelo por defecto según proveedor."""
    if name == "minimax":
        return MINIMAX_DEFAULT_MODEL
    if name == "gemini":
        return LLM_MODEL
    raise ValueError(f"Proveedor LLM desconocido: {name!r}")


def get_provider(name: str | None = None) -> LLMProvider:
    """
    Devuelve un provider cacheado. Si `name` es None, usa `LLM_PROVIDER` del entorno.

    Raises:
        RuntimeError: si falta configuración del proveedor solicitado.
    """
    target = (name or LLM_PROVIDER).strip().lower()
    if target in _providers:
        return _providers[target]

    if target == "gemini":
        if not GOOGLE_API_KEY:
            raise RuntimeError(
                "Proveedor 'gemini' solicitado pero GOOGLE_API_KEY no está definida"
            )
        _providers[target] = GeminiProvider(api_key=GOOGLE_API_KEY)

    elif target == "minimax":
        if not MINIMAX_API_KEY:
            raise RuntimeError(
                "Proveedor 'minimax' solicitado pero MINIMAX_API_KEY no está definida"
            )
        if not MINIMAX_BASE_URL:
            raise RuntimeError(
                "Proveedor 'minimax' solicitado pero MINIMAX_BASE_URL no está definida"
            )
        _providers[target] = MinimaxProvider(
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
        )

    else:
        raise ValueError(f"Proveedor LLM desconocido: {target!r}")

    logger.info("LLMProvider[%s] inicializado", target)
    return _providers[target]


def list_providers() -> list[str]:
    """Lista de nombres de proveedores soportados."""
    return ["minimax", "gemini"]


def reset_provider_cache() -> None:
    """Limpia el cache (útil en tests)."""
    _providers.clear()


# Helper para extraer JSON de respuestas LLM, aunque venga envuelto en markdown fences.


def extract_json(text: str) -> dict[str, Any]:
    """Parsea `text` como JSON. Si viene en ```json ... ``` lo extrae primero."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1).strip())
        raise ValueError(f"LLM devolvió JSON inválido: {text[:200]}")
