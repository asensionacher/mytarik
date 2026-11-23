#!/usr/bin/env python3
"""Estimate LLM label precision on a sample. LLM judge, not human review."""
import argparse, json, re, sqlite3, urllib.request
from pathlib import Path

def judge(url, model, rows):
    prompt=json.dumps([{"code":r[1],"official":(r[2] or "")[:700],"label":r[0]} for r in rows],ensure_ascii=False)
    payload={"model":model,"temperature":0.1,"max_tokens":2500,"messages":[
      {"role":"system","content":"You are a customs nomenclature reviewer. For each code+official description+proposed commercial label, decide whether the label is a correct, specific commercial name for that code. Reject labels that name a different product, a different species, a generic category, or a legal heading. Return ONLY JSON: [{code, valid: true/false, reason}]."},
      {"role":"user","content":prompt}]}
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=300) as resp: data=json.loads(resp.read().decode())
    content=data["choices"][0]["message"].get("content") or ""
    m=re.search(r"\[.*\]",content,re.S)
    try: return json.loads(m.group(0)) if m else []
    except json.JSONDecodeError: return []

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--db",default="data/termbase.sqlite"); ap.add_argument("--limit",type=int,default=100); ap.add_argument("--api",default="http://127.0.0.1:8000/v1/chat/completions"); ap.add_argument("--model",default="qwen38uncensored"); args=ap.parse_args()
    db=sqlite3.connect(f"file:{args.db}?mode=ro&immutable=1",uri=True)
    rows=db.execute("""SELECT t.term,tc.code,c.description FROM commercial_terms t JOIN term_code tc ON tc.term_id=t.id
      JOIN taric_codes c ON c.code=tc.code WHERE t.source='llm_code' AND t.review_status='unreviewed' ORDER BY RANDOM() LIMIT ?""",(args.limit,)).fetchall()
    yes=0; out=[]
    for i in range(0,len(rows),10):
        try: judged=judge(args.api,args.model,rows[i:i+10])
        except Exception as exc: print("judge error",exc,flush=True); continue
        by={str(x.get("code")):x for x in judged if isinstance(x,dict)}
        for term,code,desc in rows[i:i+10]:
            valid=bool(by.get(str(code),{}).get("valid"))
            yes+=int(valid); out.append({"code":code,"label":term,"valid":valid,"reason":by.get(str(code),{}).get("reason")})
        print(f"judged {min(i+10,len(rows))}/{len(rows)} valid={yes}",flush=True)
    summary={"sample":len(out),"valid":yes,"precision":round(yes/len(out),3) if out else None,"results":out}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    Path("data/label_precision.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": raise SystemExit(main())
