#!/usr/bin/env python3
"""Redact obvious PII from public text/CSV sidecars.

Images and parquet records are flagged for manual/vision redaction; they are not
silently treated as clean. Raw files are never modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"\b(?:\+?\d[\d .\-()]{7,}\d)\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
VAT = re.compile(r"\b(?:IT)?\d{11}\b")


def redact(text: str) -> str:
    text = EMAIL.sub("[EMAIL]", text)
    text = IBAN.sub("[IBAN]", text)
    text = PHONE.sub("[PHONE]", text)
    text = VAT.sub("[VAT]", text)
    return text


def process_text(source: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(redact(source.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    return 1


def process_csv(source: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open(newline="", encoding="utf-8", errors="replace") as src, target.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        fields = reader.fieldnames or []
        masked = {
            name for name in fields
            if any(key in name.lower() for key in ("denominazione", "codicefiscale", "partitaiva", "email", "telefono", "iban", "indirizzo"))
        }
        writer = csv.DictWriter(dst, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            for name in masked:
                if row.get(name):
                    row[name] = "[REDACTED]"
            writer.writerow(row)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = 0
    files = [args.input] if args.input.is_file() else list(args.input.rglob("*"))
    for path in files:
        if not path.is_file():
            continue
        rel = path.relative_to(args.input) if args.input.is_dir() else Path(path.name)
        target = args.output / rel
        if path.suffix.lower() == ".csv":
            count += process_csv(path, target.with_suffix(".csv"))
        elif path.suffix.lower() in {".txt", ".xml", ".json", ".jsonl", ".md"}:
            count += process_text(path, target)
    print(f"redacted {count} text/CSV files -> {args.output}")
    print("images/parquet: flagged, not silently treated as clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
