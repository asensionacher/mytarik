"""Translation with an explicit provider: Azure Translator or a local LLM.

``TRANSLATION_PROVIDER=azure`` keeps the original managed-identity path and is
the default. ``TRANSLATION_PROVIDER=local`` sends the text to the same
OpenAI-compatible endpoint used for local classification. There is no fallback:
the selected provider either succeeds or the caller receives an explicit error.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from functools import lru_cache

from app.config import (
    AZURE_TRANSLATOR_ENDPOINT,
    LOCAL_LLM_API_KEY,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_TIMEOUT,
    LOCAL_TRANSLATION_DIR,
    TRANSLATION_PROVIDER,
)

_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
}

_LOCAL_SYSTEM_PROMPT = """You are a professional translator specialised in customs,
trade and logistics documents. Translate faithfully and naturally, without adding
or removing information. Preserve product names, HS/TARIC codes, numbers, units,
incoterms, country codes and punctuation. Do not explain, comment or use markdown.
Return only the translation."""


class LocalLLMTranslator:
    """Small OpenAI-compatible client used only for translation."""

    def __init__(self) -> None:
        self.base_url = str(LOCAL_LLM_BASE_URL or "").strip().rstrip("/")
        self.model = str(LOCAL_LLM_MODEL or "").strip()
        self.api_key = str(LOCAL_LLM_API_KEY or "").strip()
        self.timeout = LOCAL_LLM_TIMEOUT
        if not self.base_url or not self.model:
            raise RuntimeError(
                "TRANSLATION_PROVIDER=local requiere LOCAL_LLM_BASE_URL y "
                "LOCAL_LLM_MODEL"
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

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        target_name = _LANGUAGE_NAMES.get(target_language, target_language)
        source_name = (
            _LANGUAGE_NAMES.get(source_language, source_language)
            if source_language
            else "the source language (detect it)"
        )
        user = (
            f"Translate from {source_name} to {target_name}.\n"
            "Return only the translated text.\n\n"
            f"TEXT:\n{text}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _LOCAL_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 2048,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"No se pudo conectar con el traductor local: {exc}") from exc

        try:
            raw = response.read().decode("utf-8")
        except (AttributeError, UnicodeError) as exc:
            raise RuntimeError("El traductor local devolvió una respuesta no UTF-8") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"El traductor local devolvió JSON inválido: {raw[:200]}"
            ) from exc

        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("El traductor local devolvió una respuesta sin alternativas")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise RuntimeError("El traductor local devolvió una respuesta sin alternativas")
        finish_reason = choice.get("finish_reason")
        if finish_reason not in {None, "", "stop", "eos", "end_turn", "none"}:
            raise RuntimeError(
                f"El traductor local no completó la traducción: {finish_reason}"
            )
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        translated = content.strip() if isinstance(content, str) else ""
        if not translated:
            raise RuntimeError("El traductor local devolvió una traducción vacía")
        return translated


@lru_cache(maxsize=1)
def _get_local_translator() -> LocalLLMTranslator:
    return LocalLLMTranslator()


class OPUSMTTranslator:
    """Two specialized OPUS-MT models, converted to CTranslate2 int8.

    ``es-en`` translates Spanish to English; ``en-es`` translates English to
    Spanish. The models are small (~155 MB each) and run on CPU, so Qwen Coder
    can stay loaded for OpenCode.
    """

    def __init__(self, root: str = LOCAL_TRANSLATION_DIR) -> None:
        from pathlib import Path

        self.root = Path(root)
        if not self.root.is_absolute():
            self.root = Path(__file__).resolve().parents[1] / self.root
        self.es_en = self.root / "es-en"
        self.en_es = self.root / "en-es"
        for directory in (self.es_en, self.en_es):
            if not (directory / "model.bin").is_file():
                raise RuntimeError(
                    f"No se encontró el modelo de traducción en {directory}. "
                    "Ejecuta scripts/download_translation_models.py"
                )
        self._engines = {}

    def _engine(self, direction: str):
        if direction in self._engines:
            return self._engines[direction]
        # Imported lazily so Azure-only deployments do not need ctranslate2.
        import ctranslate2
        import sentencepiece as spm

        directory = self.es_en if direction == "es-en" else self.en_es
        translator = ctranslate2.Translator(
            str(directory),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=0,
        )
        source_sp = spm.SentencePieceProcessor(model_file=str(directory / "source.spm"))
        target_sp = spm.SentencePieceProcessor(model_file=str(directory / "target.spm"))
        self._engines[direction] = (translator, source_sp, target_sp)
        return self._engines[direction]

    def _detect_source(self, text: str) -> str:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        try:
            language = detect(text)
        except Exception:
            language = "unknown"
        if language in {"es", "en"}:
            return language
        raise RuntimeError(
            f"El traductor local_mt solo admite español e inglés; se detectó {language!r}"
        )

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        if not text or not text.strip():
            return text

        if target_language == "en":
            source = (source_language or self._detect_source(text)).lower()
            if source == "en":
                return text
            if source != "es":
                raise RuntimeError(
                    f"El traductor local_mt no soporta origen {source!r} hacia inglés"
                )
            direction = "es-en"
        elif target_language == "es":
            source = (source_language or "en").lower()
            if source != "en":
                raise RuntimeError(
                    f"El traductor local_mt no soporta origen {source!r} hacia español"
                )
            direction = "en-es"
        else:
            raise RuntimeError(
                f"El traductor local_mt solo soporta en/es, no {target_language!r}"
            )

        translator, source_sp, target_sp = self._engine(direction)
        tokens = source_sp.encode(text, out_type=str)
        if not tokens:
            raise RuntimeError("El traductor local_mt no pudo tokenizar el texto")
        # OPUS-MT is trained with the source EOS token; without it CTranslate2
        # can enter a repetition loop.
        tokens.append("</s>")
        results = translator.translate_batch(
            [tokens],
            beam_size=4,
            max_decoding_length=512,
        )
        if not results or not results[0].hypotheses:
            raise RuntimeError("El traductor local_mt devolvió una traducción vacía")
        translated = target_sp.decode(results[0].hypotheses[0]).strip()
        if not translated:
            raise RuntimeError("El traductor local_mt devolvió una traducción vacía")
        return translated


@lru_cache(maxsize=1)
def _get_mt_translator() -> OPUSMTTranslator:
    return OPUSMTTranslator()


@lru_cache(maxsize=1)
def _get_azure_translator():
    # Imported lazily so a fully local install does not need the Azure SDK.
    from azure.ai.translation.text import TextTranslationClient
    from azure.identity import ManagedIdentityCredential

    if not AZURE_TRANSLATOR_ENDPOINT:
        raise RuntimeError("AZURE_TRANSLATOR_ENDPOINT es obligatoria")
    return TextTranslationClient(
        endpoint=AZURE_TRANSLATOR_ENDPOINT,
        credential=ManagedIdentityCredential(),
    )


def _azure_translate(
    text: str,
    target_language: str,
    source_language: str | None = None,
) -> str:
    options = {"from_language": source_language} if source_language else {}
    response = _get_azure_translator().translate(
        body=[text],
        to_language=[target_language],
        **options,
    )
    if not response or not response[0].translations:
        raise RuntimeError("Azure Translator devolvió una respuesta sin traducciones")
    translated = response[0].translations[0].text
    if not translated or not translated.strip():
        raise RuntimeError("Azure Translator devolvió una traducción vacía")
    return translated


def _translate(
    text: str,
    target_language: str,
    source_language: str | None = None,
) -> str:
    if not text or not text.strip():
        return text

    selection = (TRANSLATION_PROVIDER or "azure").strip().lower()
    if selection == "azure":
        return _azure_translate(text, target_language, source_language)
    if selection == "local":
        return _get_local_translator().translate(text, target_language, source_language)
    if selection == "local_mt":
        return _get_mt_translator().translate(text, target_language, source_language)
    raise RuntimeError(
        f"TRANSLATION_PROVIDER debe ser 'azure', 'local' o 'local_mt', pero fue {selection!r}"
    )


@lru_cache(maxsize=2048)
def translate_to_en(text: str) -> str:
    return _translate(text, "en")


@lru_cache(maxsize=2048)
def translate_from_en(text: str, target_language: str) -> str:
    if target_language == "en":
        return text
    return _translate(text, target_language, source_language="en")
