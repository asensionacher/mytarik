"""Persistent case memory for confirmed import classifications.

Exact matches only: same normalized product description and same trade context.
The TARIC version is stored with every case so stale codes can be invalidated.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("IMPORT_CASES_DB", "/app/data/import_cases.sqlite"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS import_cases (
            normalized TEXT NOT NULL,
            context_hash TEXT NOT NULL,
            description TEXT NOT NULL,
            context_json TEXT NOT NULL,
            code TEXT NOT NULL,
            agent TEXT,
            confirmations INTEGER NOT NULL DEFAULT 1,
            taric_version TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (normalized, context_hash)
        )
        """
    )
    return connection


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def context_payload(trade: dict | None, language: str, taric_version: str) -> dict:
    trade = trade or {}
    return {
        "trade_mode": trade.get("trade_mode", ""),
        "origin_country": trade.get("origin_country", ""),
        "dispatch_country": trade.get("dispatch_country", ""),
        "language": language,
        "taric_version": taric_version,
    }


def _context_hash(context: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode("utf-8")).hexdigest()


def lookup_case(description: str, trade: dict | None, language: str, taric_version: str) -> dict | None:
    normalized = normalize(description)
    if not normalized:
        return None
    context = context_payload(trade, language, taric_version)
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM import_cases WHERE normalized=? AND context_hash=?",
            (normalized, _context_hash(context)),
        ).fetchone()
    if not row:
        return None
    return {
        "hit": True,
        "code": row["code"],
        "description": row["description"],
        "confirmations": row["confirmations"],
        "agent": row["agent"],
        "updated_at": row["updated_at"],
        "context": json.loads(row["context_json"]),
    }


def store_case(description: str, code: str, trade: dict | None, language: str, taric_version: str, agent: str = "") -> dict:
    normalized = normalize(description)
    if not normalized:
        raise ValueError("La descripción está vacía")
    context = context_payload(trade, language, taric_version)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        existing = connection.execute(
            "SELECT code, confirmations FROM import_cases WHERE normalized=? AND context_hash=?",
            (normalized, _context_hash(context)),
        ).fetchone()
        if existing:
            connection.execute(
                """UPDATE import_cases SET description=?, context_json=?, code=?, agent=?,
                   confirmations=confirmations+1, taric_version=?, updated_at=?
                   WHERE normalized=? AND context_hash=?""",
                (description, json.dumps(context, sort_keys=True), code, agent,
                 taric_version, now, normalized, _context_hash(context)),
            )
        else:
            connection.execute(
                """INSERT INTO import_cases
                   (normalized, context_hash, description, context_json, code, agent,
                    confirmations, taric_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (normalized, _context_hash(context), description,
                 json.dumps(context, sort_keys=True), code, agent, taric_version, now, now),
            )
    return {"hit": True, "code": code, "description": description, "confirmations": (existing["confirmations"] + 1) if existing else 1, "updated_at": now, "context": context}


# ── Semantic layer (Qdrant + shared multilingual-e5-small) ─────────────
TARIFFAI_URL = os.getenv("TARIFFAI_URL", "http://tariffai-api:8004").rstrip("/")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")
CASE_COLLECTION = "import_cases"
EMBEDDING_SIZE = 384


async def _embed(text: str) -> list[float]:
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{TARIFFAI_URL}/embed", json={"text": text})
        response.raise_for_status()
        return response.json()["vector"]


async def _ensure_collection() -> None:
    import httpx

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.put(
            f"{QDRANT_URL}/collections/{CASE_COLLECTION}",
            json={"vectors": {"size": EMBEDDING_SIZE, "distance": "Cosine"}},
        )
        if response.status_code not in (200, 201, 409):
            response.raise_for_status()


async def remember_embedding(description: str, code: str, trade: dict | None, language: str, taric_version: str, confirmations: int = 1) -> None:
    import hashlib
    import uuid

    import httpx

    context = context_payload(trade, language, taric_version)
    context_hash = _context_hash(context)
    vector = await _embed(description)
    await _ensure_collection()
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{normalize(description)}|{context_hash}"))
    payload = {
        "normalized": normalize(description),
        "description": description,
        "code": code,
        "context_hash": context_hash,
        "context": context,
        "confirmations": confirmations,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.put(
            f"{QDRANT_URL}/collections/{CASE_COLLECTION}/points?wait=true",
            json={"points": [{"id": point_id, "vector": vector, "payload": payload}]},
        )
        response.raise_for_status()


async def semantic_lookup(description: str, trade: dict | None, language: str, taric_version: str, threshold: float = 0.90) -> dict | None:
    import httpx

    context = context_payload(trade, language, taric_version)
    context_hash = _context_hash(context)
    vector = await _embed(description)
    await _ensure_collection()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{QDRANT_URL}/collections/{CASE_COLLECTION}/points/query",
            json={
                "query": vector,
                "limit": 3,
                "with_payload": True,
                "filter": {"must": [{"key": "context_hash", "match": {"value": context_hash}}]},
            },
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        points = response.json().get("result", {}).get("points", [])
    if not points:
        return None
    best = max(points, key=lambda point: point.get("score", 0))
    if best.get("score", 0) < threshold:
        return None
    payload = best.get("payload") or {}
    return {
        "hit": True,
        "code": payload.get("code"),
        "description": payload.get("description"),
        "confirmations": payload.get("confirmations", 1),
        "similarity": round(float(best.get("score", 0)), 4),
        "semantic": True,
        "context": payload.get("context"),
    }
