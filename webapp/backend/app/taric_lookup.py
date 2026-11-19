"""Small read-only Qdrant lookups for TARIC codes and EBTI evidence."""
from __future__ import annotations

import os
import re

import httpx

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _filter(code: str) -> dict:
    conditions = []
    if len(code) == 10:
        conditions.append({"key": "taric10", "match": {"value": code}})
    conditions.append({"key": "cn8", "match": {"value": code[:8]}})
    return {"should": conditions} if len(conditions) > 1 else conditions[0]


async def _scroll(collection: str, code: str, limit: int = 8) -> list[dict]:
    payload = {
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
        "filter": _filter(code),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{QDRANT_URL}/collections/{collection}/points/scroll", json=payload
        )
        response.raise_for_status()
        return response.json().get("result", {}).get("points", [])


async def validate_code(value: str) -> dict:
    code = _digits(value)
    if len(code) not in {8, 10}:
        return {"valid": False, "code": code, "error": "El código debe tener 8 o 10 dígitos"}
    points = await _scroll("eu_taric", code, limit=2)
    if not points:
        return {"valid": False, "code": code, "error": "No encontrado en TARIC"}
    payload = points[0].get("payload") or {}
    return {
        "valid": True,
        "code": code,
        "cn8": payload.get("cn8"),
        "taric10": payload.get("taric10"),
        "description": payload.get("description") or "",
    }


async def ebti_evidence(value: str, limit: int = 5) -> dict:
    code = _digits(value)
    if len(code) not in {8, 10}:
        return {"code": code, "evidence": []}
    points = await _scroll("ebti_decisions", code, limit=limit)
    evidence = []
    for point in points:
        payload = point.get("payload") or {}
        evidence.append({
            "reference": payload.get("reference"),
            "cn8": payload.get("cn8"),
            "taric10": payload.get("taric10"),
            "description": payload.get("description") or "",
            "justification": payload.get("justification") or "",
            "country": payload.get("issuing_country") or "",
            "status": payload.get("status") or "",
            "start_date": payload.get("start_date") or "",
        })
    return {"code": code, "evidence": evidence}
