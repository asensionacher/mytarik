#!/usr/bin/env python3
"""Load approved commercial seed terms into an existing termbase."""
import json, re, sqlite3, sys, unicodedata
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def normalize(text):
    value=unicodedata.normalize("NFKD",text or "")
    value="".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+",value))

def main(db_path,seed_path):
    db=sqlite3.connect(db_path); now=datetime.now().isoformat(timespec="seconds")
    seeds=json.loads(Path(seed_path).read_text(encoding="utf-8"))
    for item in seeds:
        lang=item.get("language","es")
        for term in [item.get("term","")]+list(item.get("synonyms") or []):
            n=normalize(term)
            if not n: continue
            db.execute("INSERT OR IGNORE INTO commercial_terms(term,normalized,language,source,status,confidence,created_at) VALUES(?,?,?,?,?,?,?)",(term[:700],n,lang,"seed","approved",0.95,now))
            tid=db.execute("SELECT id FROM commercial_terms WHERE normalized=? AND language=? AND source='seed'",(n,lang)).fetchone()[0]
            for rel in item.get("codes",[]):
                db.execute("INSERT OR IGNORE INTO term_code(term_id,code,relation_type,context,source,confidence,status) VALUES(?,?,?,?,?,?,'approved')",(tid,rel["code"],rel.get("relation","commercial_name"),rel.get("context"),"seed",0.95))
                db.execute("UPDATE term_code SET context=?,status='approved' WHERE term_id=? AND code=?",(rel.get("context"),tid,rel["code"]))
    db.commit()
    db.executescript("DROP TABLE IF EXISTS term_fts; CREATE VIRTUAL TABLE term_fts USING fts5(term,normalized); INSERT INTO term_fts(rowid,term,normalized) SELECT id,term,normalized FROM commercial_terms;")
    db.commit()
    print(json.dumps({"seeds":len(seeds),"terms":db.execute("SELECT COUNT(*) FROM commercial_terms").fetchone()[0],"links":db.execute("SELECT COUNT(*) FROM term_code").fetchone()[0],"db_bytes":Path(db_path).stat().st_size},indent=2))
    db.close()
if __name__=="__main__": main(sys.argv[1],sys.argv[2])
