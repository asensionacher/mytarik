#!/usr/bin/env python3
"""Load a Gemini-generated commercial-name CSV into the termbase as provisional."""
from __future__ import annotations
import csv
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

CONF = {"alta": 0.80, "media": 0.55, "baja": 0.30}


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/termbase.sqlite")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--source", default="gemini_csv_1k")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    known = {row[0] for row in db.execute("SELECT code FROM taric_codes")}
    rows = list(csv.DictReader(Path(args.csv).open(encoding="utf-8", newline="")))
    stats = {"rows": len(rows), "valid_codes": 0, "invalid_codes": 0,
             "terms": 0, "links": 0, "duplicates": 0}
    now = datetime.now().isoformat(timespec="seconds")

    for row in rows:
        code = str(row.get("code") or "").strip().zfill(10)
        if code not in known:
            stats["invalid_codes"] += 1
            continue
        stats["valid_codes"] += 1
        name = " ".join(str(row.get("commercial_name_es") or "").split())[:180]
        if not name:
            continue
        confidence = CONF.get(str(row.get("confidence") or "").lower(), 0.40)
        notes = " ".join(str(row.get("notes") or "").split())[:300]
        for term in [name] + [x.strip() for x in str(row.get("synonyms") or "").split(";") if x.strip()]:
            normalized = normalize(term)
            if len(normalized) < 3:
                continue
            db.execute("""INSERT OR IGNORE INTO commercial_terms
                (term, normalized, language, source, status, confidence, created_at, review_status, review_reason)
                VALUES (?, ?, 'es', ?, 'provisional', ?, ?, 'unreviewed', ?)""",
                (term[:180], normalized, args.source, confidence, now, notes))
            tid = db.execute("SELECT id FROM commercial_terms WHERE normalized=? AND language='es' AND source=?",
                             (normalized, args.source)).fetchone()
            if not tid:
                continue
            tid = tid[0]
            before = db.total_changes
            db.execute("""INSERT OR IGNORE INTO term_code
                (term_id, code, relation_type, source, confidence, status)
                VALUES (?, ?, 'gemini_commercial_name', ?, ?, 'provisional')""",
                (tid, code, args.source, confidence))
            if db.total_changes == before:
                stats["duplicates"] += 1
            else:
                stats["links"] += 1
            stats["terms"] += 1
    db.commit()
    db.executescript("""DROP TABLE IF EXISTS term_fts;
        CREATE VIRTUAL TABLE term_fts USING fts5(term,normalized);
        INSERT INTO term_fts(rowid,term,normalized) SELECT id,term,normalized FROM commercial_terms;""")
    db.commit()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
