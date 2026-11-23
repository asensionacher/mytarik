#!/usr/bin/env python3
"""Evaluate commercial-term coverage against a set of known products."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "webapp" / "backend"))
from app.termbase import search_terms  # noqa: E402

CASES = [
    ("camiseta de algodón", ["6109"]),
    ("zapatillas deportivas", ["6404"]),
    ("mochila", ["4202"]),
    ("auriculares Bluetooth", ["8518"]),
    ("vino tinto", ["2204"]),
    ("detergente", ["3402"]),
    ("café molido", ["0901"]),
    ("aceite de oliva", ["1509"]),
    ("juguete de plástico", ["9503"]),
    ("memoria RAM", ["8473", "8542"]),
    ("cable USB-C", ["8544"]),
    ("lona de nylon", ["6306"]),
    ("báscula digital", ["8423"]),
    ("tornillos de titanio", ["8108"]),
    ("motocicleta de gasolina", ["8711"]),
    ("bicicleta", ["8712"]),
    ("bombilla LED", ["8539"]),
    ("reloj de pulsera", ["9102"]),
    ("cargador de portátil", ["8504"]),
    ("tubo de PVC", ["3917"]),
    ("crema solar", ["3304"]),
    ("mesa de madera", ["9403"]),
    ("silla de oficina", ["9401"]),
    ("martillo", ["8205"]),
    ("cable HDMI", ["8544"]),
]

def main() -> int:
    results=[]; hits=0
    for query, expected in CASES:
        matches=search_terms(query, 5)
        codes=[m["code"] for m in matches]
        hit=any(any(code.startswith(prefix) for prefix in expected) for code in codes)
        hits += int(hit)
        results.append({"query": query, "expected": expected, "hit": hit,
                        "top": [(m["term"][:60], m["code"], m["source"]) for m in matches[:3]]})
        print(("OK  " if hit else "MISS") + f" {query}: {codes[:3]}", flush=True)
    summary={"cases": len(CASES), "hits": hits, "coverage": round(hits/len(CASES), 3), "results": results}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    (ROOT.parent / "data" / "termbase_eval.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
