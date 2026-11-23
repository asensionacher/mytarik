#!/usr/bin/env python3
"""Generate short commercial terms from EBTI descriptions with the local LLM."""
from __future__ import annotations
import argparse, json, re, sqlite3, urllib.request
from datetime import datetime
from pathlib import Path

def normalize(text: str) -> str:
    value = text.lower()
    return " ".join(re.findall(r"[a-z0-9áéíóúñü]+", value))

def call_llm(url: str, model: str, batch: list[dict]) -> list[dict]:
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": "You extract commercial product names from customs decisions. Return ONLY valid JSON: a list of objects with keys reference and terms. terms must be 1 to 3 short commercial product names of 2 to 7 words, in the language of the description. Do not return legal headings, attributes, materials or explanations."},
            {"role": "user", "content": json.dumps([{"reference": r["reference"], "code": r["code"], "description": (r["description"] or "")[:1400]} for r in batch], ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as response:
        data = json.loads(response.read().decode())
    content = data["choices"][0]["message"].get("content") or ""
    match = re.search(r"\[.*\]", content, re.S)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/termbase.sqlite")
    ap.add_argument("--api", default="http://127.0.0.1:8000/v1/chat/completions")
    ap.add_argument("--model", default="qwen38uncensored")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=5)
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    rows = db.execute("""
      SELECT reference, code, description FROM ebti_decisions
      WHERE description IS NOT NULL AND LENGTH(description) > 40
      ORDER BY RANDOM() LIMIT ?
    """, (args.limit,)).fetchall()
    created = 0
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        try:
            results = call_llm(args.api, args.model, batch)
        except Exception as exc:
            print(f"batch {start}: ERROR {exc}", flush=True)
            continue
        by_ref = {str(item.get("reference")): item for item in results if isinstance(item, dict)}
        for row in batch:
            for term in (by_ref.get(row["reference"], {}).get("terms") or [])[:3]:
                term = " ".join(str(term).split())[:180]
                normalized = normalize(term)
                if len(normalized) < 4:
                    continue
                now = datetime.now().isoformat(timespec="seconds")
                db.execute("INSERT OR IGNORE INTO commercial_terms(term,normalized,language,source,status,confidence,created_at) VALUES(?,?,?,?,?,?,?)",
                           (term, normalized, "und", "llm", "proposed", 0.6, now))
                tid = db.execute("SELECT id FROM commercial_terms WHERE normalized=? AND language='und' AND source='llm'", (normalized,)).fetchone()[0]
                db.execute("INSERT OR IGNORE INTO term_code(term_id,code,relation_type,source,confidence,status) VALUES(?,?,?,?,?,'proposed')",
                           (tid, row["code"], "llm_commercial_name", "llm", 0.6))
                db.execute("INSERT OR IGNORE INTO term_ebti(term_id,reference) VALUES(?,?)", (tid, row["reference"]))
                created += 1
        db.commit()
        print(f"processed {min(start + args.batch_size, len(rows))}/{len(rows)}; terms={created}", flush=True)
    db.executescript("DROP TABLE IF EXISTS term_fts; CREATE VIRTUAL TABLE term_fts USING fts5(term,normalized); INSERT INTO term_fts(rowid,term,normalized) SELECT id,term,normalized FROM commercial_terms;")
    db.commit()
    print(json.dumps({"created": created, "terms": db.execute("SELECT COUNT(*) FROM commercial_terms").fetchone()[0]}, ensure_ascii=False))
    db.close()
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
