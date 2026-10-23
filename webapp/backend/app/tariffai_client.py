"""
tariffai_client.py — cliente HTTP asíncrono hacia la API TariffAI.

Define los modelos Pydantic espejo de la API de TariffAI para tener
tipado fuerte en este backend, y expone dos funciones:

- `health()` — ping al servicio
- `classify_batch(descriptions)` — clasifica varias descripciones en una llamada
- `classify_one(description)` — clasifica una sola descripción
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

ResponseLanguage = Literal["es", "en"]


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
        self.timeout = settings.request_timeout_seconds if timeout is None else timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TariffAIClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
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
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def health(self) -> dict[str, Any]:
        resp = await self.client.get("/health", timeout=3.0)
        resp.raise_for_status()
        return resp.json()

    async def classify_one(
        self,
        description: str,
        language: ResponseLanguage = "en",
        trade: dict[str, Any] | None = None,
    ) -> ClassifyResponse:
        payload: dict = {"description": description, "language": language}
        if trade is not None:
            payload["trade"] = trade
        async with asyncio.timeout(self.timeout):
            resp = await self.client.post("/classify", json=payload)
            resp.raise_for_status()
            return ClassifyResponse.model_validate(resp.json())

    async def classify_batch(
        self,
        descriptions: list[str],
        language: ResponseLanguage = "en",
        trade: dict[str, Any] | None = None,
    ) -> list[ClassifyResponse]:
        if not descriptions:
            return []
        # La API acepta un máximo de 50 por request → paginar por si acaso.
        page_size = 50
        out: list[ClassifyResponse] = []
        # One deadline for the whole invoice, including every page.
        async with asyncio.timeout(self.timeout):
            for start in range(0, len(descriptions), page_size):
                chunk = descriptions[start : start + page_size]
                payload: dict = {"descriptions": chunk, "language": language}
                if trade is not None:
                    payload["trade"] = trade
                resp = await self.client.post("/classify/batch", json=payload)
                resp.raise_for_status()
                for item in resp.json():
                    out.append(ClassifyResponse.model_validate(item))
        return out

    async def classify_progress(
        self, descriptions: list[str], language: ResponseLanguage = "en",
        trade: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[int, ClassifyResponse]]:
        groups: dict[str, list[int]] = {}
        for index, description in enumerate(descriptions):
            groups.setdefault(description, []).append(index)
        work = iter(groups.items())
        pending: dict[asyncio.Task[ClassifyResponse], list[int]] = {}

        def start_next() -> None:
            entry = next(work, None)
            if entry is not None:
                description, indices = entry
                pending[asyncio.create_task(self.classify_one(
                    description, language=language, trade=trade,
                ))] = indices

        try:
            async with asyncio.timeout(self.timeout):
                for _ in range(3):
                    start_next()
                while pending:
                    done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        indices = pending.pop(task)
                        try:
                            response = task.result()
                        except (httpx.HTTPError, TimeoutError, ValidationError) as exc:
                            logger.exception("Fallo clasificando la línea %s", indices[0] + 1)
                            response = ClassifyResponse(
                                status="error", error=str(exc) or type(exc).__name__,
                            )
                        for position, index in enumerate(indices):
                            line_response = response
                            if position and response.result is not None:
                                line_response = response.model_copy(update={
                                    "result": response.result.model_copy(update={
                                        "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                                    }),
                                })
                            yield index, line_response
                        start_next()
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


def make_client() -> TariffAIClient:
    return TariffAIClient()
