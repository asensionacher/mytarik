#!/usr/bin/env python3
"""Blind termbase evaluation with products NOT present in seed_terms.json."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "webapp" / "backend"))
from app.termbase import search_terms  # noqa: E402

CASES = [
    ("silla de comedor", ["9401"]),
    ("mesa de oficina", ["9403"]),
    ("cable de red", ["8544"]),
    ("altavoz Bluetooth", ["8518"]),
    ("ratón inalámbrico", ["8471"]),
    ("teclado mecánico", ["8471"]),
    ("monitor LED", ["8528"]),
    ("nevera", ["8418"]),
    ("lavadora", ["8450"]),
    ("zapatos de cuero", ["6403"]),
    ("bolso de mano", ["4202"]),
    ("gafas de sol", ["9004"]),
    ("reloj inteligente", ["8517", "9102"]),
    ("aspiradora", ["8508"]),
    ("ventilador", ["8414"]),
    ("bombilla halógena", ["8539"]),
    ("cepillo de dientes", ["9603"]),
    ("silla de jardín", ["9401"]),
    ("cable de alimentación", ["8544"]),
    ("crema hidratante", ["3304"]),
]

def main() -> int:
    results=[]; hits=0
    for query, expected in CASES:
        matches=search_terms(query, 5)
        codes=[m["code"] for m in matches]
        hit=any(any(code.startswith(prefix) for prefix in expected) for code in codes)
        hits += int(hit)
        results.append({"query":query,"expected":expected,"hit":hit,"top":[(m["term"][:60],m["code"],m["source"]) for m in matches[:3]]})
        print(("OK  " if hit else "MISS")+f" {query}: {codes[:3]}", flush=True)
    summary={"cases":len(CASES),"hits":hits,"coverage":round(hits/len(CASES),3),"results":results}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    (ROOT.parent/"data"/"termbase_blind_eval.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0
if __name__=="__main__": raise SystemExit(main())
