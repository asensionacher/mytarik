#!/usr/bin/env python3
"""Export a human review packet for the tariff labeling queue."""
from __future__ import annotations

import csv
import json
from pathlib import Path

QUEUE = Path("/home/seby/mytarik/data/labeling/tariff_queue.jsonl")
OUT = Path("/home/seby/mytarik/data/labeling/review_packet.csv")


def main() -> int:
    rows = [json.loads(line) for line in QUEUE.read_text(encoding="utf-8").splitlines() if line.strip()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "document_id", "source", "type", "priority", "path",
            "expected_cn8", "expected_taric10", "status", "reviewer", "notes",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in writer.fieldnames})
    print(f"{len(rows)} rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
