#!/usr/bin/env python3
"""Validate manual CN8/TARIC10 labels against the loaded TARIC nomenclature."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import openpyxl

NOMENCLATURE = Path("/home/seby/taric/2026-11/Nomenclature EN.xlsx")


def load_codes() -> set[str]:
    wb = openpyxl.load_workbook(NOMENCLATURE, read_only=True, data_only=True)
    ws = wb.active
    codes = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        raw = str(row[0] or "").split()[0]
        if raw.endswith(".0"):
            raw = raw[:-2]
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) in {8, 10}:
            codes.add(digits)
    wb.close()
    return codes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    codes = load_codes()
    print(f"TARIC codes loaded: {len(codes)}")
    rows = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    valid = invalid = pending = 0
    for row in rows:
        cn8 = row.get("expected_cn8")
        taric = row.get("expected_taric10")
        if not cn8 and not taric:
            pending += 1
            continue
        cn8_text = str(cn8) if cn8 else None
        taric_text = str(taric) if taric else None
        cn8_ok = (
            not cn8_text
            or cn8_text in codes
            or any(code.startswith(cn8_text) for code in codes)
        )
        taric_ok = not taric_text or taric_text in codes
        ok = cn8_ok and taric_ok
        if not ok:
            print(f"INVALID {row.get('document_id')} cn8={cn8} taric10={taric}")
            invalid += 1
        else:
            valid += 1
    print(json.dumps({"valid": valid, "invalid": invalid, "pending": pending}, ensure_ascii=False))
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
