#!/usr/bin/env python3
"""Index a CIRCABC TARIC measures XLSX into a local SQLite database.

The measure files are large (hundreds of thousands of rows) and contain one
row per goods code / origin / measure type. This is a local reference index,
not a replacement for the official TARIC consultation API.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

import openpyxl

SCHEMA = """
CREATE TABLE IF NOT EXISTS measures (
    goods_code TEXT NOT NULL,
    add_code TEXT,
    order_no TEXT,
    start_date TEXT,
    end_date TEXT,
    red_ind TEXT,
    origin TEXT,
    measure_type TEXT,
    legal_base TEXT,
    duty TEXT,
    origin_code TEXT,
    measure_type_code TEXT,
    sheet TEXT
);
CREATE INDEX IF NOT EXISTS idx_measures_goods ON measures(goods_code);
CREATE INDEX IF NOT EXISTS idx_measures_origin ON measures(goods_code, origin_code);
"""

HEADERS = (
    "Goods code", "Add code", "Order No.", "Start date", "End date",
    "RED_IND", "Origin", " Measure type", "Legal base", "Duty",
    "Origin code", " Meas. type code",
)


def text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    raw = str(value).strip()
    return raw or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("/home/seby/taric/taric_measures_2026.sqlite"))
    args = parser.parse_args()

    con = sqlite3.connect(args.out)
    con.executescript(SCHEMA)
    total = 0
    wb = openpyxl.load_workbook(args.xlsx, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = [str(c).strip() if c is not None else "" for c in next(rows, [])]
            if not header:
                continue
            index = {name.strip(): i for i, name in enumerate(header)}
            if "Goods code" not in index:
                continue
            missing = [name for name in HEADERS if name.strip() not in index]
            if missing:
                print(f"{ws.title}: missing {missing}", flush=True)
            batch = []
            for row in rows:
                code = text(row[index["Goods code"]])
                if not code:
                    continue
                batch.append(tuple(
                    text(row[index[name.strip()]]) if name.strip() in index and index[name.strip()] < len(row) else None
                    for name in HEADERS
                ) + (ws.title,))
                if len(batch) >= 5000:
                    con.executemany("INSERT INTO measures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                    total += len(batch)
                    con.commit()
                    batch.clear()
                    print(f"{ws.title}: {total}", flush=True)
            if batch:
                con.executemany("INSERT INTO measures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                total += len(batch)
                con.commit()
    finally:
        wb.close()
        con.close()
    print(f"Indexed {total} measures into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
