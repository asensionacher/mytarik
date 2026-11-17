#!/usr/bin/env python3
"""Mide la extracción de líneas de la app (parse_invoice) contra el ground truth.

Uso:
    python check_parser.py --batch /home/seby/mytarik/data/synthetic/batch_01

Escribe parser_check/parser_report.json y parser_check/misses.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

MYTARIK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MYTARIK / "webapp" / "backend"))

from app.invoice_parser import parse_invoice  # noqa: E402


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def matches(gt: str, parsed: str) -> bool:
    key, cand = norm(gt), norm(parsed)
    head = key[:38]
    return head in cand or (len(cand) > 20 and cand[:38] in key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--min-precision", type=float, default=0.98)
    args = parser.parse_args(argv)

    batch: Path = args.batch
    docs = []
    misses = []
    totals = Counter()
    by_scan = Counter()
    by_language = Counter()
    for gt_path in sorted((batch / "ground_truth").glob("*.json")):
        gt = json.loads(gt_path.read_text())
        pdf = batch / "pdf" / f"{gt['doc_id']}.pdf"
        parsed = parse_invoice(pdf.name, pdf.read_bytes())
        gt_desc = [line["description"] for line in gt["lines"]]
        hit_gt = [any(matches(d, p) for p in parsed.descriptions) for d in gt_desc]
        hit_parsed = [any(matches(d, p) for d in gt_desc) for p in parsed.descriptions]
        recall = sum(hit_gt) / len(gt_desc) if gt_desc else 0.0
        precision = sum(hit_parsed) / len(parsed.descriptions) if parsed.descriptions else 0.0
        ok = (len(parsed.descriptions) == len(gt_desc)
              and all(hit_gt) and precision >= args.min_precision)
        docs.append({
            "doc_id": gt["doc_id"], "scan": gt["scan"], "language": gt["language"],
            "layout": gt["layout"], "pages": gt["pages"],
            "expected": len(gt_desc), "parsed": len(parsed.descriptions),
            "recall": round(recall, 4), "precision": round(precision, 4), "ok": ok,
        })
        totals["docs"] += 1
        totals["ok_docs"] += ok
        totals["gt_lines"] += len(gt_desc)
        totals["found"] += sum(hit_gt)
        totals["parsed_lines"] += len(parsed.descriptions)
        key = "scan" if gt["scan"] else "native"
        by_scan[key + "_docs"] += 1
        by_scan[key + "_found"] += sum(hit_gt)
        by_scan[key + "_gt"] += len(gt_desc)
        by_language[gt["language"] + "_docs"] += 1
        by_language[gt["language"] + "_found"] += sum(hit_gt)
        by_language[gt["language"] + "_gt"] += len(gt_desc)
        if not ok:
            for desc, found in zip(gt_desc, hit_gt):
                if not found:
                    misses.append([gt["doc_id"], gt["scan"], gt["layout"], desc])
            for cand, found in zip(parsed.descriptions, hit_parsed):
                if not found:
                    misses.append([gt["doc_id"], gt["scan"], gt["layout"], f"[extra] {cand}"])

    def share(counter: Counter, prefix: str) -> float:
        denom = counter[prefix + "_gt"]
        return round(counter[prefix + "_found"] / denom, 4) if denom else 0.0

    summary = {
        "docs": totals["docs"], "docs_ok": totals["ok_docs"],
        "recall": round(totals["found"] / totals["gt_lines"], 4) if totals["gt_lines"] else 0.0,
        "precision": round(totals["found"] / totals["parsed_lines"], 4) if totals["parsed_lines"] else 0.0,
        "recall_by_source": {
            "native": share(by_scan, "native"), "scan": share(by_scan, "scan"),
        },
        "recall_by_language": {
            "en": share(by_language, "en"), "es": share(by_language, "es"),
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    out = batch / "parser_check"
    out.mkdir(exist_ok=True)
    (out / "parser_report.json").write_text(json.dumps(
        {"summary": summary, "docs": docs}, ensure_ascii=False, indent=1))
    with (out / "misses.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["doc_id", "escaneada", "plantilla", "descripcion"])
        writer.writerows(misses)

    print(f"{summary['docs_ok']}/{summary['docs']} facturas exactas · "
          f"recall {summary['recall']:.1%} · precisión {summary['precision']:.1%}")
    print("  recall nativas {native:.1%} · escaneadas {scan:.1%} · EN {en:.1%} · ES {es:.1%}".format(
        **summary["recall_by_source"], **summary["recall_by_language"]))
    return 0 if summary["docs_ok"] == summary["docs"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
