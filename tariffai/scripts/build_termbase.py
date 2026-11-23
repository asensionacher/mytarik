#!/usr/bin/env python3
"""Build the commercial-term ↔ TARIC ↔ EBTI knowledge base."""
from __future__ import annotations
import argparse, json, re, sqlite3, unicodedata
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DEFAULT_TREE = ROOT / "taric_tree.json"
DEFAULT_EBTI = REPO / "data" / "real" / "ebti_labels.jsonl"
DEFAULT_DB = REPO / "data" / "termbase.sqlite"
GENERIC = {"of","the","and","or","for","with","without","other","others","type","kind","use","used","product","article","articles","parts","part","general"}

def normalize(text):
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))

def digits(value):
    return re.sub(r"\D", "", str(value or ""))[:10].ljust(10, "0")

def schema(db):
    db.executescript("""
    PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS taric_codes (code TEXT PRIMARY KEY, cn8 TEXT, taric10 TEXT, level INTEGER, level_name TEXT, description TEXT, parent_code TEXT, path TEXT, valid_from TEXT, valid_to TEXT);
    CREATE TABLE IF NOT EXISTS ebti_decisions (reference TEXT PRIMARY KEY, code TEXT, cn8 TEXT, taric10 TEXT, description TEXT, justification TEXT, keywords TEXT, language TEXT, country TEXT, status TEXT, start_date TEXT, end_date TEXT, source TEXT);
    CREATE TABLE IF NOT EXISTS commercial_terms (id INTEGER PRIMARY KEY AUTOINCREMENT, term TEXT NOT NULL, normalized TEXT NOT NULL, language TEXT, source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed', confidence REAL NOT NULL DEFAULT 0.5, approved_by TEXT, created_at TEXT NOT NULL, UNIQUE(normalized, language, source));
    CREATE TABLE IF NOT EXISTS term_code (term_id INTEGER NOT NULL, code TEXT NOT NULL, relation_type TEXT, context TEXT, source TEXT, confidence REAL, status TEXT, PRIMARY KEY(term_id, code));
    CREATE TABLE IF NOT EXISTS term_ebti (term_id INTEGER NOT NULL, reference TEXT NOT NULL, PRIMARY KEY(term_id, reference));
    CREATE INDEX IF NOT EXISTS idx_terms_norm ON commercial_terms(normalized);
    CREATE INDEX IF NOT EXISTS idx_term_code_code ON term_code(code);
    CREATE INDEX IF NOT EXISTS idx_ebti_code ON ebti_decisions(code);
    CREATE INDEX IF NOT EXISTS idx_taric_cn8 ON taric_codes(cn8);
    """)

def term_id(db, term, language, source, status, confidence):
    normalized = normalize(term)
    if not normalized or normalized in GENERIC: return 0
    now = datetime.now().isoformat(timespec="seconds")
    db.execute("INSERT OR IGNORE INTO commercial_terms(term,normalized,language,source,status,confidence,created_at) VALUES(?,?,?,?,?,?,?)", (term.strip()[:700], normalized, language, source, status, confidence, now))
    row = db.execute("SELECT id FROM commercial_terms WHERE normalized=? AND language=? AND source=?", (normalized, language, source)).fetchone()
    return int(row[0]) if row else 0

def link(db, tid, code, relation, source, confidence):
    if tid and code:
        db.execute("INSERT OR IGNORE INTO term_code(term_id,code,relation_type,source,confidence,status) VALUES(?,?,?,?,?,'proposed')", (tid, code, relation, source, confidence))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--tree",type=Path,default=DEFAULT_TREE); ap.add_argument("--ebti",type=Path,default=DEFAULT_EBTI); ap.add_argument("--db",type=Path,default=DEFAULT_DB); ap.add_argument("--limit-ebti",type=int,default=0); args=ap.parse_args()
    args.db.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(args.db); schema(db)
    tree=json.loads(args.tree.read_text(encoding="utf-8")); nodes=tree["nodes"]; print("TARIC nodes",len(nodes),flush=True)
    for node in nodes.values():
        code=node["code"]; db.execute("INSERT OR REPLACE INTO taric_codes VALUES(?,?,?,?,?,?,?,?,?,?)",(code,node.get("cn8") or code[:8],code,node.get("level"),node.get("level_name"),node.get("description"),node.get("parent_code"),json.dumps(node.get("path") or []),node.get("start_date"),node.get("end_date")))
        if node.get("description") and normalize(node["description"]) not in GENERIC:
            tid=term_id(db,node["description"],"en","taric","official",1.0); link(db,tid,code,"official_description","taric",1.0)
    db.commit(); print("TARIC terms loaded",flush=True)
    count=0
    with args.ebti.open(encoding="utf-8") as handle:
        for line in handle:
            if args.limit_ebti and count>=args.limit_ebti: break
            try: row=json.loads(line)
            except json.JSONDecodeError: continue
            code=digits(row.get("taric10") or row.get("cn8")); ref=str(row.get("id") or "").strip()
            if not ref: continue
            desc=str(row.get("description") or ""); lang=str(row.get("language") or "").lower() or None
            db.execute("INSERT OR REPLACE INTO ebti_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(ref,code,row.get("cn8"),row.get("taric10"),desc,row.get("justification"),row.get("keywords"),lang,row.get("country"),row.get("status"),row.get("start_date"),row.get("end_date"),row.get("source")))
            tid=term_id(db,desc[:700],lang or "und","ebti_description","proposed",0.5); link(db,tid,code,"ebti_description","ebti",0.5)
            if tid: db.execute("INSERT OR IGNORE INTO term_ebti VALUES(?,?)",(tid,ref))
            for kw in str(row.get("keywords") or "").replace(";",",").split(","):
                kw=" ".join(kw.strip().upper().split())
                if not kw or normalize(kw) in GENERIC: continue
                kid=term_id(db,kw,lang or "und","ebti_keywords","proposed",0.7); link(db,kid,code,"ebti_keyword","ebti",0.7)
                if kid: db.execute("INSERT OR IGNORE INTO term_ebti VALUES(?,?)",(kid,ref))
            count+=1
            if count%5000==0: db.commit(); print("EBTI processed",count,flush=True)
    db.commit(); print("Building FTS5",flush=True)
    db.executescript("""DROP TABLE IF EXISTS term_fts; CREATE VIRTUAL TABLE term_fts USING fts5(term,normalized); INSERT INTO term_fts(rowid,term,normalized) SELECT id,term,normalized FROM commercial_terms;"""); db.commit()
    stats={"taric_codes":db.execute("SELECT COUNT(*) FROM taric_codes").fetchone()[0],"ebti_decisions":db.execute("SELECT COUNT(*) FROM ebti_decisions").fetchone()[0],"commercial_terms":db.execute("SELECT COUNT(*) FROM commercial_terms").fetchone()[0],"term_code_links":db.execute("SELECT COUNT(*) FROM term_code").fetchone()[0],"ebti_links":db.execute("SELECT COUNT(*) FROM term_ebti").fetchone()[0],"db_bytes":args.db.stat().st_size}
    print(json.dumps(stats,indent=2),flush=True); (args.db.parent/"termbase_stats.json").write_text(json.dumps(stats,indent=2),encoding="utf-8"); db.close()
if __name__=="__main__": main()
