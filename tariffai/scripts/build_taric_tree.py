#!/usr/bin/env python3
"""Build the complete TARIC tree from the official Nomenclature XLSX."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = Path("/home/seby/taric/2026-11/Nomenclature EN.xlsx")
OUTPUT = ROOT / "taric_tree.json"
LEVEL_NAMES = {2: "chapter", 4: "heading", 6: "subheading", 8: "cn8", 10: "taric10"}


def _date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text or None


def _digits(value):
    return re.sub(r"\D", "", str(value or "").split()[0])[:10]


def build(xlsx_path=DEFAULT_XLSX):
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        code = _digits(row[0])
        if len(code) != 10:
            continue
        try:
            level = int(str(row[4]).strip())
        except (TypeError, ValueError):
            level = len(code.rstrip("0")) or 10
        if level not in LEVEL_NAMES:
            level = next((candidate for candidate in (10, 8, 6, 4, 2) if code[:candidate].rstrip("0")), 10)
        rows.append({
            "code": code,
            "level": level,
            "description": " ".join(str(row[6] or "").split()),
            "indent": str(row[5] or ""),
            "start_date": _date(row[1]),
            "end_date": _date(row[2]),
        })
    workbook.close()

    by_code = {}
    for row in rows:
        previous = by_code.get(row["code"])
        if previous is None or (row["start_date"] or "") >= (previous["start_date"] or ""):
            by_code[row["code"]] = row

    nodes = {}
    for code in sorted(by_code, key=lambda value: (len(value), value)):
        row = by_code[code]
        level = row["level"]
        parent_code = None
        for candidate_level in range(level - 2, 1, -2):
            candidate = code[:candidate_level].ljust(10, "0")
            if candidate in by_code:
                parent_code = candidate
                break
        nodes[code] = {
            "code": code,
            "level": level,
            "level_name": LEVEL_NAMES[level],
            "parent_code": parent_code,
            "children": [],
            "description": row["description"],
            "indent": row["indent"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "path": [],
        }

    for code, node in nodes.items():
        parent = node["parent_code"]
        if parent and parent in nodes:
            nodes[parent]["children"].append(code)

    roots = []
    for code, node in nodes.items():
        if node["parent_code"] is None:
            roots.append(code)
        chain = []
        cursor = node["parent_code"]
        seen = set()
        while cursor and cursor in nodes and cursor not in seen:
            seen.add(cursor)
            chain.append(cursor)
            cursor = nodes[cursor]["parent_code"]
        node["path"] = list(reversed(chain)) + [code]
        node["children"].sort()

    roots.sort()
    leaves = [code for code, node in nodes.items() if not node["children"]]
    by_level = {LEVEL_NAMES[level]: sum(1 for node in nodes.values() if node["level"] == level) for level in LEVEL_NAMES}
    orphan = [code for code, node in nodes.items() if node["parent_code"] and node["parent_code"] not in nodes]
    result = {
        "source": str(xlsx_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "counts": {
            "nodes": len(nodes),
            "roots": len(roots),
            "leaves": len(leaves),
            "orphans": len(orphan),
            "by_level": by_level,
        },
        "roots": roots,
        "leaves": leaves,
        "orphans": orphan,
        "nodes": nodes,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    print("tree:", OUTPUT)
