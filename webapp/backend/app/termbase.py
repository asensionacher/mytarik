"""Read-only commercial-term search over the termbase database."""
from __future__ import annotations
import os, re, sqlite3, unicodedata
from pathlib import Path
DB_PATH = Path(os.getenv("TERMBASE_DB", "/app/data/termbase.sqlite"))

def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))

def search_terms(query: str, limit: int = 10) -> list[dict]:
    if not DB_PATH.is_file(): return []
    normalized = normalize(query)
    if not normalized: return []
    tokens = [t for t in normalized.split() if len(t) > 1][:8]
    if not tokens: return []
    fts_query = " AND ".join(f'"{token}"' for token in tokens)
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT t.id, t.term, t.normalized, t.source, t.status, t.confidence,
                   tc.code, c.description AS code_description, tc.relation_type, tc.context,
                   GROUP_CONCAT(DISTINCT e.reference) AS ebti_refs
            FROM commercial_terms t
            JOIN term_code tc ON tc.term_id = t.id
            LEFT JOIN taric_codes c ON c.code = tc.code
            LEFT JOIN ebti_decisions e ON e.code = tc.code
            WHERE t.rowid IN (SELECT rowid FROM term_fts WHERE term_fts MATCH ?)
               OR t.normalized = ?
            GROUP BY t.id, tc.code
            ORDER BY CASE WHEN t.normalized = ? THEN 0 ELSE 1 END, t.confidence DESC, tc.confidence DESC
            LIMIT ?
        """, (fts_query, normalized, normalized, limit)).fetchall()
    return [{
        "term": row["term"], "normalized": row["normalized"], "code": row["code"],
        "description": row["code_description"], "source": row["source"],
        "status": row["status"], "confidence": row["confidence"],
        "relation": row["relation_type"], "context": row["context"],
        "ebti": [ref for ref in (row["ebti_refs"] or "").split(",") if ref],
    } for row in rows]
