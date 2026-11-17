#!/usr/bin/env python3
"""Create a manual tariff-labeling queue from the public corpus.

This script never invents CN8/TARIC10 labels. It selects documents that may
contain product lines and writes an empty label record for human review.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/home/seby/mytarik")
CORPUS = ROOT / "data/public/corpus_manifest.jsonl"
OUT = ROOT / "data/labeling/tariff_queue.jsonl"

# Product-like terms that make a document worth a human look. This is a
# triage filter, not a classifier and not a tariff label.
PRODUCT_HINTS = re.compile(
    r"\b(shirt|polo|t-shirt|textile|garment|trousers|bed linen|cotton|"
    r"olive oil|oil|food|spark plug|engine|part|machinery|electronic|"
    r"chemical|plastic|furniture|shoe|footwear|pump|valve|motor|"
    r"camisa|aceite|motor|repuesto|textil|calzado|mueble)\b",
    re.IGNORECASE,
)


def main() -> int:
    rows = []
    if not CORPUS.exists():
        raise SystemExit(f"Missing corpus index: {CORPUS}")
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        path = Path(record["path"])
        excerpt = ""
        if record["type"] == "procurement_notice":
            excerpt = str(record.get("title") or path.stem)
        priority = 0
        if record["type"] in {"receipt", "receipt_dataset", "invoice", "invoice_table"}:
            priority = 2
        if PRODUCT_HINTS.search(excerpt or path.name):
            priority = max(priority, 1)
        if priority == 0:
            continue
        rows.append({
            "document_id": record["document_id"],
            "source": record["source"],
            "country": record["country"],
            "type": record["type"],
            "path": record["path"],
            "license": record["license"],
            "pii": record["pii"],
            "excerpt": excerpt,
            "priority": priority,
            "expected_cn8": None,
            "expected_taric10": None,
            "status": "pending_human_review",
            "reviewer": None,
            "notes": "Assign only after reading product lines; do not infer from filename.",
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} documents -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
