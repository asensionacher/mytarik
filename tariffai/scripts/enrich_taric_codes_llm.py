#!/usr/bin/env python3
"""Give TARIC leaf codes a canonical commercial label using the local LLM.

This is a bulk, resumable pass. Every generated term is 'proposed', never
'automatically approved'. Run in batches and review before trusting it.
"""
from __future__ import annotations
import argparse, json, re, sqlite3, urllib.request
from datetime import datetime
from pathlib import Path

def call(url: str, model: str, batch: list[dict]) -> list[dict]:
    prompt = json.dumps([{"code": r["code"], "official": (r["description"] or "")[:1000]} for r in batch], ensure_ascii=False)
    payload = {"model": model, "temperature": 0.1, "max_tokens": 3500, "messages": [
        {"role": "system", "content": "For each TARIC code, propose ONE short commercial product label (2 to 8 words) a Spanish importer would use. Preserve scientific names exactly if present. If the code is generic, residual, 'other', parts, a species you are not sure about, or not a standalone product, prefix the label with 'Categoría: '. Never invent a common species name. Return ONLY JSON: [{code, label}]. Do not invent a different legal code."},
        {"role": "user", "content": prompt},
    ]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as response:
        data = json.loads(response.read().decode())
    content = data["choices"][0]["message"].get("content") or ""
    match = re.search(r"\[.*\]", content, re.S)
    if not match: return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--db", default="data/termbase.sqlite")
    ap.add_argument("--tree", default="tariffai/taric_tree.json")
    ap.add_argument("--api", default="http://127.0.0.1:8000/v1/chat/completions")
    ap.add_argument("--model", default="qwen38uncensored")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--batch-size", type=int, default=10)
    args=ap.parse_args()
    tree=json.loads(Path(args.tree).read_text(encoding="utf-8"))["nodes"]
    leaves=[n for n in tree.values() if not n.get("children") and n.get("description")]
    db=sqlite3.connect(args.db)
    done={row[0] for row in db.execute("""
        SELECT tc.code FROM term_code tc
        JOIN commercial_terms t ON t.id=tc.term_id
        WHERE t.source='llm_code'
    """)}
    leaves=[n for n in leaves if n["code"] not in done]
    created=0
    for start in range(0,min(args.limit,len(leaves)),args.batch_size):
        batch=leaves[start:start+args.batch_size]
        try:
            results=call(args.api,args.model,batch)
        except Exception as exc:
            print(f"batch {start} ERROR {exc}",flush=True); continue
        by_code={str(x.get("code")):str(x.get("label") or "").strip() for x in results if isinstance(x,dict)}
        for node in batch:
            label=" ".join(by_code.get(node["code"],"").split())[:180]
            if len(label)<3: continue
            norm=" ".join(re.findall(r"[a-z0-9áéíóúñü]+",label.lower()))
            now=datetime.now().isoformat(timespec="seconds")
            db.execute("INSERT OR IGNORE INTO commercial_terms(term,normalized,language,source,status,confidence,created_at) VALUES(?,?,?,?,?,?,?)",(label,norm,"es","llm_code","proposed",0.45,now))
            tid=db.execute("SELECT id FROM commercial_terms WHERE normalized=? AND language='es' AND source='llm_code'",(norm,)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO term_code(term_id,code,relation_type,source,confidence,status) VALUES(?,?,?,?,?,'proposed')",(tid,node["code"],"canonical_label","llm_code",0.45))
            created+=1
        db.commit()
        print(f"processed {min(start+args.batch_size,len(leaves))}/{min(args.limit,len(leaves))}; labels={created}",flush=True)
    db.executescript("DROP TABLE IF EXISTS term_fts; CREATE VIRTUAL TABLE term_fts USING fts5(term,normalized); INSERT INTO term_fts(rowid,term,normalized) SELECT id,term,normalized FROM commercial_terms;")
    db.commit(); print(json.dumps({"created":created},ensure_ascii=False)); db.close(); return 0
if __name__=="__main__": raise SystemExit(main())
