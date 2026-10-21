"""
tariffai_client.py — cliente HTTP asíncrono hacia la API TariffAI.

Define los modelos Pydantic espejo de la API de TariffAI para tener
tipado fuerte en este backend, y expone dos funciones:

- `health()` — ping al servicio
- `classify_batch(descriptions)` — clasifica varias descripciones en una llamada
- `classify_one(description)` — clasifica una sola descripción
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── Modelos espejo (subset suficiente para nuestro uso) ──────────────────

def _build_models():
    """Construye los modelos Pydantic localmente para evitar imports circulares."""
    from pydantic import BaseModel, Field
    from typing import Literal

    class ClassificationReasoning(BaseModel):
        section_reasoning: str = ""
        chapter_reasoning: str = ""
        heading_reasoning: str = ""
        subheading_reasoning: str = ""
        key_factors: list[str] = Field(default_factory=list)

    class AlternativeCode(BaseModel):
        code: str = ""
        description: str = ""
        why_not: str | None = None
        trade_off: str | None = None

    class HierarchyLevel(BaseModel):
        code: str = ""
        description: str = ""

    class ClassificationResult(BaseModel):
        input_text: str
        cleaned_text: str = ""
        primary_code: str | None = None
        primary_description: str | None = None
        confidence: float = 0.0
        reasoning: ClassificationReasoning = ClassificationReasoning()
        hierarchy: dict = Field(default_factory=dict)
        alternative_codes: list[AlternativeCode] = Field(default_factory=list)
        is_ambiguous: bool = False
        processing_time_ms: float = 0.0
        prompt_tokens: int = 0
        output_tokens: int = 0
        total_tokens: int = 0
        thinking: str | None = None

    class ClassifyResponse(BaseModel):
        status: Literal["classified", "ambiguous", "error"]
        result: ClassificationResult | None = None
        error: str | None = None

    return ClassifyResponse, ClassificationResult, AlternativeCode


ClassifyResponse, ClassificationResult, AlternativeCode = _build_models()  # type: ignore[assignment]


# ── Cliente ─────────────────────────────────────────────────────────────

class TariffAIClient:
    """Cliente httpx asíncrono de larga vida."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or settings.tariffai_url).rstrip("/")
        self.timeout = timeout or settings.request_timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TariffAIClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Si se usa fuera de un `async with`, igualmente creamos uno
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def health(self) -> dict[str, Any]:
        resp = await self.client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def classify_one(
        self,
        description: str,
    ) -> ClassifyResponse:
        payload: dict = {"description": description}
        resp = await self.client.post("/classify", json=payload)
        resp.raise_for_status()
        return ClassifyResponse.model_validate(resp.json())

    async def classify_batch(
        self,
        descriptions: list[str],
    ) -> list[ClassifyResponse]:
        if not descriptions:
            return []
        # La API acepta un máximo de 50 por request → paginar por si acaso.
        page_size = 50
        out: list[ClassifyResponse] = []
        for start in range(0, len(descriptions), page_size):
            chunk = descriptions[start : start + page_size]
            payload: dict = {"descriptions": chunk}
            resp = await self.client.post("/classify/batch", json=payload)
            resp.raise_for_status()
            for item in resp.json():
                out.append(ClassifyResponse.model_validate(item))
        return out


def make_client() -> TariffAIClient:
    return TariffAIClient()
