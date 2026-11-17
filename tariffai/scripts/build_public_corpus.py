#!/usr/bin/env python3
"""Build a deduplicated public corpus index with type and license metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/seby/mytarik")
OUT = ROOT / "data/public/corpus_manifest.jsonl"
TED = ROOT / "data/public/ted"
SROIE = ROOT / "data/public/sroie"
CORD = ROOT / "data/public/cord"
TRANSPARENCY = ROOT / "data/public/transparency"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    rows = []
    seen = set()
    ted_manifest = TED / "manifest.jsonl"
    if ted_manifest.exists():
        for line in ted_manifest.read_text(encoding="utf-8").splitlines():
            meta = json.loads(line)
            if meta.get("kind") != "pdf":
                continue
            path = Path(meta["path"])
            if not path.is_file():
                continue
            digest = sha256(path)
            if digest in seen:
                continue
            seen.add(digest)
            rows.append({
                "document_id": f"ted-{meta['country']}-{meta['publication_number']}",
                "source": "TED",
                "country": meta["country"],
                "type": "procurement_notice",
                "title": meta.get("title"),
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": digest,
                "license": "TED open data (EU legal notice)",
                "pii": "unknown",
                "tariff_relevance": "low",
                "notes": "procurement notice; no CN8/TARIC10 line items",
            })

    for image in sorted(SROIE.glob("**/img/*")):
        if not image.is_file() or image.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        digest = sha256(image)
        if digest in seen:
            continue
        seen.add(digest)
        rows.append({
            "document_id": f"sroie-{image.stem}",
            "source": "SROIE",
            "country": "MULTI",
            "type": "receipt",
            "path": str(image),
            "bytes": image.stat().st_size,
            "sha256": digest,
            "license": "SROIE dataset terms (verify before redistribution)",
            "pii": "high",
            "tariff_relevance": "medium",
            "notes": "scanned receipt; product line items may be usable after PII redaction",
        })

    for archive in sorted(TRANSPARENCY.glob("**/*.zip")):
        if not archive.is_file():
            continue
        digest = sha256(archive)
        if digest in seen:
            continue
        seen.add(digest)
        rows.append({
            "document_id": f"transparency-{archive.stem}",
            "source": "ITA-open-data",
            "country": "ITA",
            "type": "invoice_table",
            "title": archive.name,
            "path": str(archive),
            "bytes": archive.stat().st_size,
            "sha256": digest,
            "license": "CC BY 4.0 (verify source dataset)",
            "pii": "high",
            "tariff_relevance": "low",
            "notes": "aggregated public invoice CSV inside ZIP; no product/CN lines",
        })

    for parquet in sorted(CORD.glob("data/*.parquet")):
        digest = sha256(parquet)
        if digest in seen:
            continue
        seen.add(digest)
        rows.append({
            "document_id": f"cord-{parquet.stem}",
            "source": "CORD",
            "country": "MULTI",
            "type": "receipt_dataset",
            "path": str(parquet),
            "bytes": parquet.stat().st_size,
            "sha256": digest,
            "license": "CORD dataset card (verify before redistribution)",
            "pii": "high",
            "tariff_relevance": "medium",
            "notes": "receipt images/labels in parquet; PII redaction required",
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} documents -> {OUT}")
    by_type = {}
    by_license = {}
    for row in rows:
        by_type[row["type"]] = by_type.get(row["type"], 0) + 1
        by_license[row["license"]] = by_license.get(row["license"], 0) + 1
    print("types", by_type)
    print("licenses", by_license)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
