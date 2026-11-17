#!/usr/bin/env python3
"""T5: end-to-end evaluation of the synthetic EU documents.

Uploads each synthetic PDF through the real webapp API, compares the returned
CN8/TARIC10 codes with docs/synthetic-documents/ground_truth.json and writes a
JSON report. It never invents codes and never falls back to HS6 for matching.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "synthetic-documents"
PDF_DIR = DOCS / "pdf"
TRUTH = DOCS / "ground_truth.json"
DEFAULT_BASE = "http://127.0.0.1:8005"


def words(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "women", "men", "s", "de", "del", "y", "para", "con"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if token not in stop and len(token) > 2
    }


def best_truth_match(description: str, expected: list[dict]) -> dict | None:
    """Return the expected line whose description best overlaps."""
    target = words(description)
    if not target:
        return None
    best: tuple[float, dict] | None = None
    for line in expected:
        candidate = words(line.get("description", ""))
        if not candidate:
            continue
        score = len(target & candidate) / max(1, len(target | candidate))
        if best is None or score > best[0]:
            best = (score, line)
    if best is None or best[0] < 0.18:
        return None
    return best[1]


def result_codes(result: dict | None) -> tuple[str | None, str | None, str | None]:
    if not result:
        return None, None, None
    primary = result.get("primary_code")
    cn8 = result.get("cn8")
    taric10 = result.get("taric10")
    if not cn8 and isinstance(primary, str) and len(primary) == 8:
        cn8 = primary
    if not taric10 and isinstance(primary, str) and len(primary) == 10:
        taric10 = primary
    return cn8, taric10, primary


def upload(base_url: str, path: Path, timeout: int) -> dict:
    with path.open("rb") as handle:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/invoice/upload",
            files={"file": (path.name, handle, "application/pdf")},
            data={
                "trade_mode": "import",
                "origin_country": "ES",
                "dispatch_country": "ES",
                "language": "es",
            },
            timeout=timeout,
        )
    response.raise_for_status()
    return response.json()


def evaluate(base_url: str, limit: int | None, timeout: int, include: list[str] | None = None) -> dict:
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    expected = truth.get("lines", [])
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if include:
        pdfs = [p for p in pdfs if any(token in p.name for token in include)]
    if limit is not None:
        pdfs = pdfs[:limit]

    documents: list[dict] = []
    total_lines = matched_lines = 0
    cn8_hits = taric_hits = 0
    errors: list[str] = []

    for path in pdfs:
        doc = {
            "file": path.name,
            "status": "ok",
            "items": [],
            "error": None,
        }
        try:
            payload = upload(base_url, path, timeout)
        except Exception as exc:  # keep going; one bad PDF must not abort T5
            doc["status"] = "error"
            doc["error"] = str(exc)
            errors.append(f"{path.name}: {exc}")
            documents.append(doc)
            continue

        items = payload.get("items", []) or []
        for item in items:
            total_lines += 1
            classification = item.get("classification") or {}
            status = classification.get("status")
            result = classification.get("result") or {}
            pred_cn8, pred_taric, primary = result_codes(result)
            match = best_truth_match(item.get("description", ""), expected)
            expected_cn8 = match.get("cn8") if match else None
            expected_taric = match.get("taric10") if match else None
            matched = match is not None
            cn8_ok = bool(matched and pred_cn8 and expected_cn8 == pred_cn8)
            taric_ok = bool(matched and pred_taric and expected_taric == pred_taric)
            if matched:
                matched_lines += 1
                cn8_hits += int(cn8_ok)
                taric_hits += int(taric_ok)
            else:
                errors.append(f"{path.name}: sin coincidencia ground truth para {item.get('description', '')[:90]!r}")
            doc["items"].append(
                {
                    "description": item.get("description", ""),
                    "status": status,
                    "predicted_cn8": pred_cn8,
                    "predicted_taric10": pred_taric,
                    "primary_code": primary,
                    "expected_cn8": expected_cn8,
                    "expected_taric10": expected_taric,
                    "matched": matched,
                    "cn8_hit": cn8_ok,
                    "taric10_hit": taric_ok,
                    "confidence": result.get("confidence"),
                    "error": classification.get("error"),
                }
            )
        documents.append(doc)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pack_id": truth.get("pack_id"),
        "warning": truth.get("warning"),
        "documents_processed": len(documents),
        "documents_requested": len(pdfs),
        "lines_total": total_lines,
        "lines_matched_to_ground_truth": matched_lines,
        "cn8_hits": cn8_hits,
        "taric10_hits": taric_hits,
        "errors": errors,
        "documents": documents,
    }



def evaluate_ground_truth_lines(base_url: str, timeout: int) -> dict:
    """Clasifica las descripciones del ground truth una a una.

    Es el modo rápido y determinista: usa el mismo /api/classify EU que la
    factura, pero evita que un batch de 10-20 líneas agote el timeout HTTP.
    """
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    expected = truth.get("lines", [])
    items: list[dict] = []
    errors: list[str] = []
    cn8_hits = taric_hits = 0
    for line in expected:
        description = line.get("description", "")
        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/api/classify",
                json={"description": description, "language": "es"},
                timeout=timeout,
            )
            response.raise_for_status()
            classification = response.json()
        except Exception as exc:
            errors.append(f"{description[:80]!r}: {exc}")
            classification = {"status": "error", "error": str(exc), "result": None}
        result = classification.get("result") or {}
        pred_cn8, pred_taric, primary = result_codes(result)
        expected_cn8 = line.get("cn8")
        expected_taric = line.get("taric10")
        cn8_ok = bool(pred_cn8 and pred_cn8 == expected_cn8)
        taric_ok = bool(pred_taric and pred_taric == expected_taric)
        cn8_hits += int(cn8_ok)
        taric_hits += int(taric_ok)
        items.append({
            "description": description,
            "status": classification.get("status"),
            "predicted_cn8": pred_cn8,
            "predicted_taric10": pred_taric,
            "primary_code": primary,
            "expected_cn8": expected_cn8,
            "expected_taric10": expected_taric,
            "matched": True,
            "cn8_hit": cn8_ok,
            "taric10_hit": taric_ok,
            "confidence": result.get("confidence"),
            "error": classification.get("error"),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pack_id": truth.get("pack_id"),
        "warning": truth.get("warning"),
        "evaluation_mode": "classify_ground_truth",
        "documents_processed": 1,
        "documents_requested": 1,
        "lines_total": len(expected),
        "lines_matched_to_ground_truth": len(expected),
        "cn8_hits": cn8_hits,
        "taric10_hits": taric_hits,
        "errors": errors,
        "documents": [{"file": "ground_truth.json", "status": "ok", "error": None, "items": items}],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--mode", choices=["classify", "upload"], default="classify")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--include", default="", help="Comma-separated PDF name fragments")
    parser.add_argument("--output", type=Path, default=DOCS / "eval_results.json")
    args = parser.parse_args(argv)

    include = [part.strip() for part in args.include.split(",") if part.strip()]
    if args.mode == "classify":
        report = evaluate_ground_truth_lines(args.base_url, args.timeout)
    else:
        report = evaluate(args.base_url, args.limit, args.timeout, include or None)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Documentos procesados: {report['documents_processed']}")
    print(f"Líneas totales:        {report['lines_total']}")
    print(f"Líneas emparejadas:    {report['lines_matched_to_ground_truth']}")
    print(f"Aciertos CN8:          {report['cn8_hits']}")
    print(f"Aciertos TARIC10:      {report['taric10_hits']}")
    print(f"Errores:               {len(report['errors'])}")
    for error in report["errors"][:8]:
        print(f"  - {error}")
    print(f"Resultados:            {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
