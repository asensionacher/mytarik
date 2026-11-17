#!/usr/bin/env python3
"""Export all EBTI decisions from Qdrant as a real TARIC ground-truth dataset."""
from __future__ import annotations

import json
from pathlib import Path

from qdrant_client import QdrantClient

OUT = Path("/home/seby/mytarik/data/real/ebti_labels.jsonl")


def main() -> int:
    client = QdrantClient(host="127.0.0.1", port=6333)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    offset = None
    count = 0
    with OUT.open("w", encoding="utf-8") as handle:
        while True:
            points, offset = client.scroll(
                collection_name="ebti_decisions",
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                p = point.payload or {}
                description = str(p.get("description") or "").strip()
                cn8 = str(p.get("cn8") or "").strip()
                taric = str(p.get("taric10") or "").strip()
                if not description or not cn8:
                    continue
                row = {
                    "id": p.get("reference") or str(point.id),
                    "description": description,
                    "cn8": cn8,
                    "taric10": taric or None,
                    "justification": p.get("justification") or "",
                    "keywords": p.get("keywords") or "",
                    "language": p.get("language") or "",
                    "country": p.get("issuing_country") or "",
                    "status": p.get("status") or "",
                    "start_date": p.get("start_date") or "",
                    "end_date": p.get("end_date") or "",
                    "source": "EBTI",
                    "source_url": p.get("source_url") or "https://ec.europa.eu/taxation_customs/dds2/ebti/",
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
            if offset is None:
                break
    print(f"{count} EBTI rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
