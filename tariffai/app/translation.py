"""Azure Translator text translation with system-assigned managed identity."""

from functools import lru_cache

from azure.ai.translation.text import TextTranslationClient
from azure.identity import ManagedIdentityCredential

from app.config import AZURE_TRANSLATOR_ENDPOINT


@lru_cache(maxsize=1)
def _get_translator() -> TextTranslationClient:
    if not AZURE_TRANSLATOR_ENDPOINT:
        raise RuntimeError("AZURE_TRANSLATOR_ENDPOINT es obligatoria")
    return TextTranslationClient(
        endpoint=AZURE_TRANSLATOR_ENDPOINT,
        credential=ManagedIdentityCredential(),
    )


def _translate(text: str, target_language: str, source_language: str | None = None) -> str:
    if not text or not text.strip():
        return text
    options = {"from_language": source_language} if source_language else {}
    response = _get_translator().translate(body=[text], to_language=[target_language], **options)
    if not response or not response[0].translations:
        raise RuntimeError("Azure Translator devolvió una respuesta sin traducciones")
    translated = response[0].translations[0].text
    if not translated or not translated.strip():
        raise RuntimeError("Azure Translator devolvió una traducción vacía")
    return translated


@lru_cache(maxsize=2048)
def translate_to_en(text: str) -> str:
    return _translate(text, "en")


@lru_cache(maxsize=2048)
def translate_from_en(text: str, target_language: str) -> str:
    if target_language == "en":
        return text
    return _translate(text, target_language, source_language="en")
