"""LLM-assisted product analysis for tree-guided retrieval.

The LLM does not choose a TARIC code. It only translates and extracts the
product head, material and synonyms. The tree does the classification.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.llm_provider import extract_json, get_provider

logger = logging.getLogger(__name__)

SYSTEM = """You are a customs product-query analyst.
Return ONLY valid JSON. Do not choose a TARIC code.
Identify the grammatical head noun of the product, not its modifier.

Example: "teléfono móvil" -> head "teléfono", type "móvil".
Example: "tornillos de titanio" -> head "tornillo", material "titanio".
Example: "lona de nylon" -> head "lona", material "nylon".

JSON shape:
{
  "source_language": "es",
  "english_query": "short faithful English translation",
  "head_noun_source": "main product noun in source language",
  "head_noun_english": "main product noun in English",
  "material": null or "material",
  "product_type": null or "type/modifier",
  "synonyms": ["English synonyms or trade terms"],
  "attributes": {"key": "value"}
}
"""


def _fallback(text: str, language: str) -> dict[str, Any]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", text)
    head = words[0].lower() if words else text.lower()
    return {
        "source_language": language,
        "english_query": text,
        "head_noun_source": head,
        "head_noun_english": head,
        "material": None,
        "product_type": None,
        "synonyms": [],
        "attributes": {},
        "fallback": True,
    }


def analyze_product(text: str, language: str = "es", provider: Any | None = None) -> dict[str, Any]:
    if not text.strip():
        return _fallback(text, language)
    try:
        provider = provider or get_provider()
        response = provider.complete(
            system=SYSTEM,
            user=f"Source language: {language}\nProduct: {text}",
        )
        data = extract_json(response.text)
        if not isinstance(data, dict):
            raise ValueError("analysis is not an object")
        cleaned = {
            "source_language": str(data.get("source_language") or language),
            "english_query": str(data.get("english_query") or text).strip(),
            "head_noun_source": str(data.get("head_noun_source") or "").strip().lower(),
            "head_noun_english": str(data.get("head_noun_english") or "").strip().lower(),
            "material": str(data["material"]).strip().lower() if data.get("material") else None,
            "product_type": str(data["product_type"]).strip().lower() if data.get("product_type") else None,
            "synonyms": [str(item).strip().lower() for item in (data.get("synonyms") or []) if str(item).strip()],
            "attributes": data.get("attributes") if isinstance(data.get("attributes"), dict) else {},
            "fallback": False,
        }
        if not cleaned["head_noun_english"]:
            cleaned["head_noun_english"] = cleaned["head_noun_source"] or cleaned["english_query"].split()[0].lower()
        if not cleaned["english_query"]:
            cleaned["english_query"] = text
        logger.info("Product analysis: %s", cleaned)
        return cleaned
    except Exception as exc:  # noqa: BLE001 - fallback keeps classification available
        logger.warning("Product analysis fallback: %s", exc)
        return _fallback(text, language)
