#!/usr/bin/env python3
"""Deterministic validation of LLM TARIC labels."""
import re, sqlite3, json, unicodedata
from collections import Counter
from pathlib import Path
DB=Path("data/termbase.sqlite")

def norm(text):
    v=unicodedata.normalize("NFKD",text or "")
    v="".join(c for c in v if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+",v))

def main():
    db=sqlite3.connect(DB)
    for sql in ("ALTER TABLE commercial_terms ADD COLUMN review_status TEXT DEFAULT 'unreviewed'",
                "ALTER TABLE commercial_terms ADD COLUMN review_reason TEXT"):
        try: db.execute(sql)
        except sqlite3.OperationalError: pass
    rows=db.execute("""SELECT t.id,t.term,tc.code,c.description
        FROM commercial_terms t JOIN term_code tc ON tc.term_id=t.id
        JOIN taric_codes c ON c.code=tc.code WHERE t.source='llm_code'""").fetchall()
    counts=Counter(norm(r[1]) for r in rows)
    stats={"total":len(rows),"category":0,"scientific_mismatch":0,"too_many_codes":0,"clean":0}
    for tid,term,code,description in rows:
        status,reason="unreviewed",None
        if term.strip().lower().startswith("categoría:"):
            status,reason="needs_review","generic category"; stats["category"]+=1
        for group in re.findall(r"\(([^)]*)\)", term):
            genera=set(re.findall(r"\b([A-Z][a-z]{2,})\b", group))
            if genera and not any(g.lower() in (description or "").lower() for g in genera):
                status,reason="needs_review","scientific name mismatch"; stats["scientific_mismatch"]+=1; break
        if counts[norm(term)] > 5:
            status,reason="needs_review","label reused by many codes"; stats["too_many_codes"]+=1
        if status=="unreviewed": stats["clean"]+=1
        db.execute("UPDATE commercial_terms SET review_status=?, review_reason=? WHERE id=?",(status,reason,tid))
    db.commit()
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    db.close()

if __name__=="__main__": main()
