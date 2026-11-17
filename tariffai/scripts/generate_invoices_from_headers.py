#!/usr/bin/env python3
"""Generate synthetic invoices from real Italian public-invoice headers.

The header amounts/dates/tax are taken from the public CC BY 4.0 dataset.
Product lines and CN8/TARIC10 labels are sampled from the official TARIC
nomenclature, so labels are deterministic by construction, not inferred.

PII (recipient names, tax IDs, invoice numbers) is replaced with synthetic data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path("/home/seby/mytarik")
SOURCE = ROOT / "data/public/transparency/ITA"
OUT = ROOT / "data/synthetic/invoices"
NOMENCLATURE = Path("/home/seby/taric/2026-11/Nomenclature EN.xlsx")

CUSTOMERS = [
    "Ente Pubblico Sintetico Alfa", "Comune Sintetico Beta", "Azienda Sanitaria Sintetica Gamma",
    "Università Sintetica Delta", "Regione Sintetica Epsilon", "Ministero Sintetico Zeta",
]
SUPPLIERS = [
    "Fornitore Sintetico Uno S.r.l.", "Industria Sintetica Due S.p.A.",
    "Servizi Sintetici Tre S.r.l.", "Commercio Sintetico Quattro S.r.l.",
]
ADDRESSES = ["Via Sintetica 1, 00100 Roma", "Piazza Sintetica 2, 20100 Milano", "Corso Sintetico 3, 10100 Torino"]

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Product:
    cn8: str
    taric10: str
    description: str


def load_products() -> list[Product]:
    wb = openpyxl.load_workbook(NOMENCLATURE, read_only=True, data_only=True)
    ws = wb.active
    by_code: dict[str, str] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        raw = str(row[0] or "").split()[0]
        if raw.endswith(".0"):
            raw = raw[:-2]
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) != 10:
            continue
        description = str(row[6] or "").strip()
        if not description or description.lower() in {"other", "others"}:
            continue
        by_code[digits] = max(by_code.get(digits, ""), description, key=len)
    wb.close()
    return [Product(code[:8], code, desc) for code, desc in by_code.items()]


def read_headers() -> list[dict]:
    rows: list[dict] = []
    for archive in sorted(SOURCE.glob("*.zip")):
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name) as handle:
                    text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
                    for row in csv.DictReader(text):
                        try:
                            net = Decimal(str(row["imponibile"]).replace(",", "."))
                            tax = Decimal(str(row["imposta"]).replace(",", "."))
                            total = Decimal(str(row["importototaledocumento"]).replace(",", "."))
                            rate = Decimal(str(row["aliquotaiva"]).replace(",", ".").replace("%", "").strip())
                        except Exception:
                            continue
                        if net <= 0 or total <= 0 or rate <= 0:
                            continue
                        rows.append(row)
    return rows


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def allocate(total: Decimal, count: int, rng: random.Random) -> list[Decimal]:
    weights = [rng.uniform(0.7, 1.8) for _ in range(count)]
    s = sum(weights)
    parts = [((total * Decimal(str(w / s))).quantize(CENT, rounding=ROUND_HALF_UP)) for w in weights]
    parts[-1] += total - sum(parts)
    return parts


def make_lines(net: Decimal, products: list[Product], rng: random.Random) -> list[dict]:
    count = rng.randint(1, 5)
    selected = rng.sample(products, count)
    amounts = allocate(net, count, rng)
    lines = []
    for product, amount in zip(selected, amounts):
        quantity = rng.randint(1, 20)
        unit = (amount / quantity).quantize(CENT, rounding=ROUND_HALF_UP)
        line_amount = (unit * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
        lines.append({
            "cn8": product.cn8,
            "taric10": product.taric10,
            "description": product.description,
            "quantity": quantity,
            "unit_price": str(unit),
            "line_net": str(line_amount),
        })
    # Reconcile the rounding difference on the last line.
    diff = net - sum(Decimal(line["line_net"]) for line in lines)
    if diff:
        last = lines[-1]
        last["line_net"] = str((Decimal(last["line_net"]) + diff).quantize(CENT))
        last["unit_price"] = str((Decimal(last["line_net"]) / last["quantity"]).quantize(CENT))
    return lines


def pdf_path(doc_id: str, variant: int, ground_truth: dict, lines: list[dict]) -> Path:
    target = OUT / "pdf" / f"{doc_id}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    accent = colors.HexColor("#0f766e" if variant == 0 else "#1d4ed8")
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, textColor=colors.HexColor("#475569"))
    title = ParagraphStyle("title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=accent, spaceAfter=2)

    doc = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=16*mm, rightMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm)
    story = [
        Paragraph("FATTURA / INVOICE", title),
        Paragraph("<b>DOCUMENTO SINTETICO — NON VALIDO AI FINI FISCALI</b>", small),
        Spacer(1, 5*mm),
    ]
    parties = Table([
        [Paragraph(f"<b>Fornitore</b><br/>{ground_truth['supplier']}<br/>{ground_truth['supplier_address']}<br/>P.IVA {ground_truth['supplier_vat']}", body),
         Paragraph(f"<b>Cliente</b><br/>{ground_truth['customer']}<br/>{ground_truth['customer_address']}<br/>C.F. {ground_truth['customer_tax_id']}", body)],
    ], colWidths=[88*mm, 88*mm])
    parties.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 0)]))
    story += [parties, Spacer(1, 5*mm)]

    meta = Table([
        [f"Numero: {ground_truth['invoice_number']}", f"Data: {ground_truth['invoice_date']}"],
        [f"Scadenza: {ground_truth['due_date']}", f"Valuta: EUR"],
    ], colWidths=[88*mm, 88*mm])
    meta.setStyle(TableStyle([("FONTSIZE", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 3)]))
    story += [meta, Spacer(1, 4*mm)]

    rows = [[Paragraph("<b>Descrizione</b>", body), Paragraph("<b>CN8/TARIC10</b>", body), Paragraph("<b>Q.tà</b>", body), Paragraph("<b>Prezzo</b>", body), Paragraph("<b>Importo</b>", body)]]
    for line in lines:
        rows.append([
            Paragraph(line["description"], body),
            Paragraph(f"{line['cn8']} / {line['taric10']}", body),
            Paragraph(str(line["quantity"]), body),
            Paragraph(money(Decimal(line["unit_price"])), body),
            Paragraph(money(Decimal(line["line_net"])), body),
        ])
    table = Table(rows, colWidths=[70*mm, 32*mm, 15*mm, 25*mm, 25*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), accent),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7.5),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (2,1), (-1,-1), "RIGHT"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story += [table, Spacer(1, 5*mm)]
    totals = Table([
        ["Imponibile", money(Decimal(ground_truth["net_total"]))],
        [f"IVA {ground_truth['vat_rate']}%", money(Decimal(ground_truth["tax_total"]))],
        ["Totale", money(Decimal(ground_truth["gross_total"]))],
    ], colWidths=[140*mm, 36*mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("LINEABOVE", (0,-1), (-1,-1), 0.8, colors.HexColor("#0f172a")),
        ("TOPPADDING", (0,0), (-1,-1), 2),
    ]))
    story += [totals, Spacer(1, 6*mm), Paragraph("Documento generato per addestramento. Nessun dato personale reale.", small)]
    doc.build(story)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261115)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    headers = read_headers()
    products = load_products()
    if not headers or not products:
        raise SystemExit("missing headers or products")
    rng.shuffle(headers)
    OUT.mkdir(parents=True, exist_ok=True)
    truth_path = OUT / "ground_truth.jsonl"
    index_path = OUT / "index.csv"
    truth_rows = []
    with truth_path.open("w", encoding="utf-8") as tf, index_path.open("w", newline="", encoding="utf-8") as idx:
        writer = csv.DictWriter(idx, fieldnames=["document_id", "pdf", "split", "net_total", "gross_total", "lines"])
        writer.writeheader()
        for i in range(args.limit):
            source = headers[i]
            net = Decimal(str(source["imponibile"]).replace(",", ".")).quantize(CENT)
            tax = Decimal(str(source["imposta"]).replace(",", ".")).quantize(CENT)
            gross = (net + tax).quantize(CENT)
            rate = str(source["aliquotaiva"]).replace(",", ".").strip()
            lines = make_lines(net, products, rng)
            doc_id = f"SYN-IT-{i+1:05d}"
            variant = i % 2
            truth = {
                "document_id": doc_id,
                "source": "Italian public invoice headers (CC BY 4.0) + TARIC nomenclature",
                "synthetic": True,
                "supplier": SUPPLIERS[i % len(SUPPLIERS)],
                "supplier_address": ADDRESSES[i % len(ADDRESSES)],
                "supplier_vat": f"IT{i+1:011d}",
                "customer": CUSTOMERS[i % len(CUSTOMERS)],
                "customer_address": ADDRESSES[(i+1) % len(ADDRESSES)],
                "customer_tax_id": f"{i+1:011d}",
                "invoice_number": doc_id,
                "invoice_date": str(source.get("data", ""))[:10],
                "due_date": str(source.get("datascadenzapagamento", ""))[:10],
                "vat_rate": rate,
                "net_total": str(net),
                "tax_total": str(tax),
                "gross_total": str(gross),
                "currency": "EUR",
                "lines": lines,
            }
            path = pdf_path(doc_id, variant, truth, lines)
            truth["pdf"] = str(path)
            truth["split"] = "train" if i % 10 < 8 else ("val" if i % 10 == 8 else "test")
            tf.write(json.dumps(truth, ensure_ascii=False) + "\n")
            writer.writerow({"document_id": doc_id, "pdf": str(path), "split": truth["split"], "net_total": str(net), "gross_total": str(gross), "lines": len(lines)})
            truth_rows.append(truth)
    print(f"{len(truth_rows)} PDFs -> {OUT/'pdf'}")
    print(f"ground truth -> {truth_path}")
    print(f"index -> {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
