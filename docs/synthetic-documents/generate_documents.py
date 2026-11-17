#!/usr/bin/env python3
"""Generate a coherent synthetic EU trade-document pack.

All names, addresses, EORI/VAT numbers, bank details and declarant data are
fictitious. CN8 codes are real Combined Nomenclature codes; the 10-digit
TARIC suffixes are illustrative and must be checked against the official
TARIC database before any real use.
"""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "pdf"
OUT.mkdir(parents=True, exist_ok=True)

TEAL = colors.HexColor("#0F766E")
DARK = colors.HexColor("#0F3D3E")
LIGHT = colors.HexColor("#F0FDFA")
GREY = colors.HexColor("#475569")
LINE = colors.HexColor("#CBD5E1")
RED = colors.HexColor("#B91C1C")

ss = getSampleStyleSheet()
title = ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=DARK, spaceAfter=2)
subtitle = ParagraphStyle("subtitle", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5, leading=10, textColor=GREY, spaceAfter=6)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=9.5, leading=11, textColor=TEAL, spaceBefore=6, spaceAfter=3)
body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.2, leading=10.2, textColor=colors.black, spaceAfter=2)
small = ParagraphStyle("small", parent=body, fontSize=7.2, leading=8.7)
tiny = ParagraphStyle("tiny", parent=body, fontSize=6.4, leading=7.6, textColor=GREY)
cell = ParagraphStyle("cell", parent=body, fontSize=7.3, leading=8.8)
cell_b = ParagraphStyle("cell_b", parent=cell, fontName="Helvetica-Bold")
right = ParagraphStyle("right", parent=cell, alignment=2)
right_b = ParagraphStyle("right_b", parent=right, fontName="Helvetica-Bold")


def p(text: str, style=body) -> Paragraph:
    return Paragraph(text, style)


def money(value: float) -> str:
    return f"EUR {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def table(data, widths, header=True, font=7.3, align_right_cols=()):
    rows = []
    for ri, row in enumerate(data):
        out = []
        for ci, value in enumerate(row):
            if isinstance(value, Paragraph):
                out.append(value)
            else:
                st = cell_b if (header and ri == 0) else cell
                if ci in align_right_cols and not (header and ri == 0):
                    st = right_b if (header and ri == 0) else right
                out.append(Paragraph(str(value), st))
        rows.append(out)
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ]
    t.setStyle(TableStyle(style))
    return t


def pair_table(rows, widths=(38 * mm, 132 * mm), label_fill=LIGHT):
    data = []
    for label, value in rows:
        data.append([Paragraph(f"<b>{label}</b>", cell), value if isinstance(value, Paragraph) else Paragraph(str(value), cell)])
    t = Table(data, colWidths=list(widths), hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("BACKGROUND", (0, 0), (0, -1), label_fill),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]))
    return t


def decorate(canv: canvas.Canvas, doc):
    canv.saveState()
    w, h = A4
    canv.setFont("Helvetica-Bold", 58)
    canv.setFillColor(colors.Color(0.85, 0.89, 0.89, alpha=0.32))
    canv.translate(w / 2, h / 2)
    canv.rotate(38)
    canv.drawCentredString(0, 0, "SPECIMEN")
    canv.restoreState()

    canv.saveState()
    canv.setStrokeColor(LINE)
    canv.setLineWidth(0.4)
    canv.line(15 * mm, 13 * mm, w - 15 * mm, 13 * mm)
    canv.setFont("Helvetica", 6.7)
    canv.setFillColor(GREY)
    canv.drawString(15 * mm, 9 * mm, "Documento sintetico de muestra - no valido para despacho aduanero ni uso comercial")
    canv.drawRightString(w - 15 * mm, 9 * mm, f"Pagina {doc.page}")
    canv.restoreState()


def doc(path: Path, story):
    d = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=16 * mm,
        title=path.stem, author="Mytarik synthetic dataset",
        subject="Synthetic EU trade document",
    )
    d.build(story, onFirstPage=decorate, onLaterPages=decorate)


def doc_header(title_text, subtitle_text):
    return [p(title_text, title), p(subtitle_text, subtitle)]


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------
seller = "NINGBO GARMENT & HARDWARE CO., LTD.<br/>88 Jiangnan Road, Yinzhou District<br/>Ningbo 315100, Zhejiang, China<br/>USCI 91330200SYNTH0001X<br/>Tel. +86 574 0000 0000 · export@example.cn"
buyer = "IBERICA TEXTIL IMPORT, S.L.<br/>Calle Industria 24, 46020 Valencia, Spain<br/>EORI ESB00000001 · VAT ESB00000001<br/>Tel. +34 960 000 000 · imports@example.es"
declarant = "IBERICA TEXTIL IMPORT, S.L.<br/>Calle Industria 24, 46020 Valencia, Spain<br/>EORI ESB00000001<br/>Customs representative: Aduanas Levante, S.L. · EORI ESA00000002"
invoice_no = "EXP-2026-1042"
invoice_date = "28 October 2026"
bl_no = "COSU-SYN-2026-1042"
container = "CSNU 123456 7 / Seal CN-998877"
vessel = "MSC ALEXANDRIA / Voy. 642W"
pol = "Ningbo, China"
pod = "Valencia, Spain"

lines = [
    {"no": "1", "desc": "Men's woven cotton shirts, long sleeve, 100% cotton, 120 pcs, cartons of 20", "cn8": "6205 20 00", "taric": "6205 20 00 00", "origin": "CN", "qty": 120, "unit": 18.50, "net": 0.30, "gross": 0.36},
    {"no": "2", "desc": "Cotton bed linen, printed, 100% cotton, 80 sets, cartons of 10", "cn8": "6302 21 00", "taric": "6302 21 00 00", "origin": "CN", "qty": 80, "unit": 32.00, "net": 1.20, "gross": 1.32},
    {"no": "3", "desc": "Spark plugs for spark-ignition engines, model SP-208, 500 pcs", "cn8": "8511 10 00", "taric": "8511 10 00 00", "origin": "CN", "qty": 500, "unit": 4.20, "net": 0.10, "gross": 0.12},
    {"no": "4", "desc": "Extra virgin olive oil, 1 L glass bottles, 60 bottles", "cn8": "1509 10 10", "taric": "1509 10 10 00", "origin": "ES", "qty": 60, "unit": 9.50, "net": 1.00, "gross": 1.35},
]
for line in lines:
    line["amount"] = round(line["qty"] * line["unit"], 2)
    line["net_total"] = round(line["qty"] * line["net"], 2)
    line["gross_total"] = round(line["qty"] * line["gross"], 2)

goods_total = round(sum(line["amount"] for line in lines), 2)
freight = 650.00
insurance = 120.00
cif_total = round(goods_total + freight + insurance, 2)
net_total = round(sum(line["net_total"] for line in lines), 2)
gross_total = round(sum(line["gross_total"] for line in lines), 2)

# ---------------------------------------------------------------------------
# 1. Commercial invoice
# ---------------------------------------------------------------------------
story = doc_header("COMMERCIAL INVOICE", "Synthetic specimen · extra-EU import · issuer in China · consignee in Spain")
story += [
    pair_table([
        ("Seller / Exporter", Paragraph(seller, cell)),
        ("Consignee / Buyer", Paragraph(buyer, cell)),
        ("Invoice No. / Date", f"{invoice_no} / {invoice_date}"),
        ("Payment terms", "30% advance by T/T, 70% against copy of B/L"),
        ("Incoterm 2020", "CIF Valencia (Incoterms 2020)"),
        ("Currency", "EUR"),
        ("Country of origin", "CN (lines 1-3); ES (line 4)"),
        ("Port of loading / discharge", f"{pol} / {pod}"),
        ("Vessel / Voyage", vessel),
        ("B/L No. / Container", f"{bl_no} / {container}"),
    ]),
    Spacer(1, 5 * mm),
    p("Line items", h2),
]
items = [["No.", "Description of goods", "CN code (8)", "TARIC (10)", "Origin", "Qty", "Unit price", "Amount"]]
for line in lines:
    items.append([line["no"], line["desc"], line["cn8"], line["taric"], line["origin"], str(line["qty"]), money(line["unit"]), money(line["amount"])])
story += [table(items, [8*mm, 57*mm, 20*mm, 24*mm, 11*mm, 11*mm, 19*mm, 21*mm], align_right_cols=(5, 6, 7))]
story += [
    Spacer(1, 3 * mm),
    table([
        ["Goods value", money(goods_total)],
        ["Freight to Valencia", money(freight)],
        ["Marine insurance", money(insurance)],
        ["CIF total", money(cif_total)],
    ], [50*mm, 35*mm], header=False, align_right_cols=(1,)),
    Spacer(1, 3 * mm),
    pair_table([
        ("Total net weight", f"{net_total:,.2f} kg"),
        ("Total gross weight", f"{gross_total:,.2f} kg"),
        ("Number of packages", "28 cartons / 1 pallet"),
        ("Bank beneficiary", "Ningbo Garment & Hardware Co., Ltd."),
        ("Bank / SWIFT", "Bank of Synth, Ningbo Branch / SYNBCCNBXXX"),
        ("Account (IBAN)", "CN00 0000 0000 0000 0000 0000 (synthetic)"),
        ("Declaration", "We certify that the information in this invoice is true and correct and that the goods are of the stated origin."),
    ]),
    Spacer(1, 4 * mm),
    p("Authorised signature: ______________________________     Ningbo, 28 October 2026", body),
    p("SPECIMEN: all names, addresses, bank details and identifiers are fictitious. CN8 codes are real nomenclature codes; TARIC suffixes must be verified in the official TARIC database.", tiny),
]
doc(OUT / "01_commercial_invoice_CN_ES.pdf", story)

# ---------------------------------------------------------------------------
# 2. Packing list
# ---------------------------------------------------------------------------
story = doc_header("PACKING LIST", "Synthetic specimen · linked to commercial invoice EXP-2026-1042")
story += [
    pair_table([
        ("Seller / Exporter", Paragraph(seller, cell)),
        ("Consignee / Buyer", Paragraph(buyer, cell)),
        ("Invoice No. / Date", f"{invoice_no} / {invoice_date}"),
        ("B/L No. / Container", f"{bl_no} / {container}"),
        ("Marks and numbers", "ITX/EXP-2026-1042<br/>VALENCIA<br/>C/NO. 1-28"),
        ("Total packages", "28 cartons on 1 pallet"),
    ]),
    Spacer(1, 5 * mm),
    p("Package detail", h2),
]
pack_rows = [["Carton / package", "Contents", "Qty", "Net kg", "Gross kg", "Dimensions (cm)"]]
pack_rows += [
    ["1-6", "Men's cotton shirts", "120 pcs", "36.00", "43.20", "60 x 40 x 35"],
    ["7-12", "Cotton bed linen sets", "80 sets", "96.00", "105.60", "55 x 40 x 30"],
    ["13-20", "Spark plugs SP-208", "500 pcs", "50.00", "60.00", "40 x 30 x 25"],
    ["21-28", "Olive oil 1 L (on pallet)", "60 bottles", "60.00", "81.00", "60 x 40 x 30"],
]
pack_rows.append(["TOTAL", "", "", f"{net_total:,.2f}", f"{gross_total:,.2f}", "1 pallet / 1.80 m3"])
story += [table(pack_rows, [32*mm, 46*mm, 22*mm, 19*mm, 21*mm, 37*mm], align_right_cols=(2, 3, 4))]
story += [
    Spacer(1, 4 * mm),
    pair_table([
        ("Handling", "Keep dry. Do not stack more than 3 cartons high."),
        ("Pallet dimensions", "120 x 80 x 145 cm"),
        ("Total gross weight", f"{gross_total:,.2f} kg"),
        ("Total net weight", f"{net_total:,.2f} kg"),
        ("Remarks", "Goods packed for sea freight. No dangerous goods."),
    ]),
    Spacer(1, 4 * mm),
    p("Prepared by: ______________________________     Ningbo, 28 October 2026", body),
]
doc(OUT / "02_packing_list_CN_ES.pdf", story)

# ---------------------------------------------------------------------------
# 3. Bill of lading
# ---------------------------------------------------------------------------
story = doc_header("BILL OF LADING", "Synthetic specimen · combined transport / port-to-port sea carriage")
story += [
    pair_table([
        ("B/L No. / Booking", f"{bl_no} / BKG-SYN-77881"),
        ("Shipper", Paragraph(seller, cell)),
        ("Consignee", Paragraph(buyer, cell)),
        ("Notify party", Paragraph("Aduanas Levante, S.L.<br/>Avenida del Puerto 10, 46011 Valencia, Spain<br/>Tel. +34 960 000 001", cell)),
        ("Vessel / Voyage", vessel),
        ("Port of loading", pol),
        ("Port of discharge", pod),
        ("Place of delivery", "Valencia, Spain"),
        ("Container / Seal", container),
        ("Freight", "PREPAID"),
        ("No. of originals", "3 (three)"),
    ]),
    Spacer(1, 5 * mm),
    p("Description of goods as declared by shipper", h2),
]
bl_rows = [["Marks", "Description", "Packages", "Gross kg", "Measurement"]]
bl_rows += [
    ["ITX/EXP-2026-1042", "Men's woven cotton shirts", "6 cartons", "43.20", "0.50 m3"],
    ["VALENCIA", "Cotton bed linen", "6 cartons", "105.60", "0.40 m3"],
    ["C/NO. 1-28", "Spark plugs for engines", "8 cartons", "60.00", "0.30 m3"],
    ["", "Extra virgin olive oil", "8 cartons", "81.00", "0.60 m3"],
]
bl_rows.append(["", "TOTAL", "28 cartons / 1 pallet", f"{gross_total:,.2f}", "1.80 m3"])
story += [table(bl_rows, [34*mm, 48*mm, 28*mm, 27*mm, 28*mm], align_right_cols=(3,))]
story += [
    Spacer(1, 5 * mm),
    p("SHIPPED on board the vessel named above in apparent good order and condition for carriage to the port of discharge. One original bill of lading must be surrendered duly endorsed in exchange for the goods.", small),
    Spacer(1, 4 * mm),
    pair_table([
        ("Place and date of issue", "Ningbo, 30 October 2026"),
        ("Signed for the carrier", "Synth Ocean Lines Co., Ltd. — as agent for the carrier"),
        ("Freight payable", "Prepaid at Ningbo"),
        ("Declared value", "Not declared"),
    ]),
    Spacer(1, 4 * mm),
    p("SPECIMEN: not a negotiable transport document. All parties, vessel, container and booking data are fictitious.", tiny),
]
doc(OUT / "03_bill_of_lading_CN_ES.pdf", story)

# ---------------------------------------------------------------------------
# 4. EU import declaration (SAD extract)
# ---------------------------------------------------------------------------
story = doc_header("EU IMPORT DECLARATION — SAD/DAU EXTRACT", "Synthetic specimen · release for free circulation · customs office ES002001")
story += [
    p("This is a readable extract of the data elements in a Single Administrative Document (SAD/DAU). It is not an official declaration and cannot be lodged with customs.", small),
    Spacer(1, 3 * mm),
    p("Header data", h2),
]
story += [pair_table([
    ("Box 1 — Declaration type", "IM / A / 4000 (release for free circulation)"),
    ("Box 2 — Exporter", "Ningbo Garment & Hardware Co., Ltd., China"),
    ("Box 8 — Consignee / importer", "Iberica Textil Import, S.L. — EORI ESB00000001"),
    ("Box 14 — Declarant / representative", "Aduanas Levante, S.L. — EORI ESA00000002"),
    ("Box 15 — Country of dispatch", "CN"),
    ("Box 17 — Country of destination", "ES"),
    ("Box 20 — Delivery terms", "CIF Valencia (Incoterms 2020)"),
    ("Box 22 — Invoice / currency", f"{invoice_no} / EUR"),
    ("Box 29 — Office of entry", "ES002001 — Valencia"),
])]
story += [Spacer(1, 3 * mm), p("Items", h2)]
sad_rows = [["Item", "Box 33 — CN/TARIC", "Box 34 origin", "Box 31 packages", "Box 38 net kg", "Box 42 value", "Duty (illustrative)"]]
duties = [266.40, 307.20, 67.20, 0.00]
for i, line in enumerate(lines):
    sad_rows.append([line["no"], f"{line['cn8']} / {line['taric']}", line["origin"], "cartons", f"{line['net_total']:,.2f}", money(line["amount"]), money(duties[i])])
sad_rows.append(["", "TOTAL", "", "28 cartons", f"{net_total:,.2f}", money(goods_total), money(sum(duties))])
story += [table(sad_rows, [10*mm, 38*mm, 15*mm, 25*mm, 18*mm, 24*mm, 30*mm], align_right_cols=(4, 5, 6))]
story += [
    Spacer(1, 3 * mm),
    pair_table([
        ("Box 43 — Valuation method", "1 — transaction value of the imported goods"),
        ("Box 44 — Additional documents", f"Commercial invoice {invoice_no}; packing list; B/L {bl_no}; certificate of origin"),
        ("Box 46 — Statistical value", money(cif_total)),
        ("Box 47 — Taxes (illustrative)", f"Customs duty: {money(sum(duties))}; import VAT 21%: {money((cif_total + sum(duties)) * 0.21)}"),
        ("Box 48 — Deferred payment", "None"),
        ("Box 49 — Warehouse", "Not applicable"),
        ("Box 54 — Place / date / signature", "Valencia, 13 November 2026 — Aduanas Levante, S.L."),
    ]),
    Spacer(1, 4 * mm),
    p("Illustrative duty rates only. The applicable duty and import VAT must be calculated from the official TARIC measures in force on the date of acceptance of the declaration. This specimen is not a customs decision.", tiny),
]
doc(OUT / "04_eu_import_declaration_SAD.pdf", story)

# ---------------------------------------------------------------------------
# 5. Certificate of origin
# ---------------------------------------------------------------------------
story = doc_header("CERTIFICATE OF ORIGIN", "Synthetic specimen · non-preferential certificate · issued in China")
story += [
    pair_table([
        ("Certificate No.", "CO-SYN-2026-1042"),
        ("Exporter", "Ningbo Garment & Hardware Co., Ltd., Ningbo, China"),
        ("Consignee", "Iberica Textil Import, S.L., Valencia, Spain"),
        ("Country of origin", "People's Republic of China (CN)"),
        ("Transport", f"Sea freight — {vessel} — {pol} to {pod}"),
        ("Invoice No. / Date", f"{invoice_no} / {invoice_date}"),
        ("B/L No.", bl_no),
    ]),
    Spacer(1, 5 * mm),
    p("Goods", h2),
]
co_rows = [["Marks & numbers", "Description", "CN code", "Quantity", "Gross weight"]]
co_rows += [
    ["ITX/EXP-2026-1042", "Men's woven cotton shirts", "6205 20 00", "120 pcs", "43.20 kg"],
    ["VALENCIA", "Cotton bed linen", "6302 21 00", "80 sets", "105.60 kg"],
    ["C/NO. 1-28", "Spark plugs for engines", "8511 10 00", "500 pcs", "60.00 kg"],
]
co_rows.append(["", "TOTAL (China-origin goods)", "", "700 units", "208.80 kg"])
story += [table(co_rows, [35*mm, 50*mm, 24*mm, 25*mm, 30*mm], align_right_cols=(4,))]
story += [
    Spacer(1, 5 * mm),
    pair_table([
        ("Declaration by exporter", "The undersigned declares that the goods described above originate in the country shown and that the information is correct."),
        ("Certification", "The China Council for the Promotion of International Trade (CCPIT) certifies the origin of the goods described above."),
        ("Place / date", "Ningbo, 29 October 2026"),
        ("Authorised signature / stamp", "_____________________________  (synthetic stamp)"),
    ]),
    Spacer(1, 4 * mm),
    p("SPECIMEN: not a real certificate of origin. The olive oil line is excluded because it is of Spanish origin.", tiny),
]
doc(OUT / "05_certificate_of_origin_CN.pdf", story)

# ---------------------------------------------------------------------------
# 6. Intra-EU invoice
# ---------------------------------------------------------------------------
story = doc_header("INVOICE — INTRA-EU SUPPLY", "Synthetic specimen · Germany to Spain · reverse charge · no import declaration")
story += [
    pair_table([
        ("Supplier", "Rhein Textil GmbH<br/>Hafenstrasse 12, 40213 Düsseldorf, Germany<br/>VAT DE000000001 · EORI DE000000001"),
        ("Customer", "Iberica Textil Import, S.L.<br/>Calle Industria 24, 46020 Valencia, Spain<br/>VAT ESB00000001 · EORI ESB00000001"),
        ("Invoice No. / Date", "RT-2026-0457 / 3 November 2026"),
        ("Supply date", "3 November 2026"),
        ("Incoterm 2020", "DAP Valencia (Incoterms 2020)"),
        ("Currency", "EUR"),
        ("VAT treatment", "Intra-Community supply; reverse charge. Spanish VAT self-assessed by the customer."),
    ]),
    Spacer(1, 5 * mm),
    p("Line items", h2),
]
eu_rows = [["No.", "Description", "CN code (8)", "Qty", "Unit price", "Amount"]]
eu_rows += [
    ["1", "Men's woven cotton shirts, 100% cotton, 200 pcs", "6205 20 00", "200", money(17.20), money(3440.00)],
    ["2", "Cotton bed linen, 100% cotton, 50 sets", "6302 21 00", "50", money(29.00), money(1450.00)],
]
eu_total = 3440.00 + 1450.00
eu_rows.append(["", "TOTAL", "", "", "", money(eu_total)])
story += [table(eu_rows, [10*mm, 64*mm, 25*mm, 16*mm, 22*mm, 25*mm], align_right_cols=(3, 4, 5))]
story += [
    Spacer(1, 4 * mm),
    pair_table([
        ("Total net / gross weight", "230.00 kg / 252.00 kg"),
        ("Packages", "18 cartons on 1 pallet"),
        ("Transport", "Road — CMR No. CMR-SYN-2026-0457"),
        ("Payment terms", "30 days net by SEPA transfer"),
        ("Bank", "DE00 0000 0000 0000 0000 00 (synthetic)"),
        ("VAT note", "VAT exempt intra-Community supply. Article 138 of Directive 2006/112/EC."),
        ("Declaration", "The supplier declares that the goods are supplied to a taxable person in another Member State and that the transport is documented."),
    ]),
    Spacer(1, 4 * mm),
    p("Authorised signature: ______________________________     Düsseldorf, 3 November 2026", body),
]
doc(OUT / "06_intra_eu_invoice_DE_ES.pdf", story)

# ---------------------------------------------------------------------------
# 7. CMR
# ---------------------------------------------------------------------------
story = doc_header("CMR CONSIGNMENT NOTE", "Synthetic specimen · road transport · Germany to Spain")
story += [
    pair_table([
        ("CMR No.", "CMR-SYN-2026-0457"),
        ("1. Sender", "Rhein Textil GmbH, Düsseldorf, Germany"),
        ("2. Consignee", "Iberica Textil Import, S.L., Valencia, Spain"),
        ("3. Place of delivery", "Valencia, Spain"),
        ("4. Place and date of loading", "Düsseldorf, 4 November 2026"),
        ("5. Documents attached", "Invoice RT-2026-0457; packing list"),
        ("6. Marks and numbers", "RT/2026-0457 / 18 cartons / 1 pallet"),
        ("7. Number of packages", "18 cartons"),
        ("8. Method of packing", "Cartons on pallet"),
        ("9. Nature of goods", "Cotton shirts and bed linen"),
        ("10. Gross weight", "252.00 kg"),
        ("11. Volume", "1.10 m3"),
    ]),
    Spacer(1, 5 * mm),
    p("Carrier and delivery", h2),
]
story += [pair_table([
    ("13. Instructions", "Deliver to Iberica Textil Import, Calle Industria 24, 46020 Valencia. Contact: imports@example.es."),
    ("14. Carrier", "Synth Road Transport GmbH — truck plate SYN-1234"),
    ("15. Successive carrier", "Not applicable"),
    ("16. Freight", "Prepaid by sender"),
    ("17. Special agreements", "Goods to be kept dry; no customs formalities (intra-EU movement)."),
])]
story += [Spacer(1, 6 * mm), p("Signatures", h2)]
sign = Table([
    [p("<b>Sender</b>", cell), p("<b>Carrier</b>", cell), p("<b>Consignee</b>", cell)],
    [p("Rhein Textil GmbH<br/>Düsseldorf, 4 Nov 2026<br/><br/>__________________", cell), p("Synth Road Transport<br/>Düsseldorf, 4 Nov 2026<br/><br/>__________________", cell), p("Iberica Textil Import<br/>Valencia, 6 Nov 2026<br/><br/>__________________", cell)],
], colWidths=[57*mm, 57*mm, 57*mm])
sign.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.4, LINE), ("BACKGROUND", (0,0), (-1,0), LIGHT), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4), ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
story += [sign]
doc(OUT / "07_cmr_DE_ES.pdf", story)

# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
ground = {
    "pack_id": "EU-SYN-2026-11",
    "description": "Synthetic EU trade documents for Mytarik testing. All identifiers are fictitious.",
    "currency": "EUR",
    "invoice": {
        "number": invoice_no,
        "date": invoice_date,
        "incoterm": "CIF Valencia (Incoterms 2020)",
        "goods_total": goods_total,
        "freight": freight,
        "insurance": insurance,
        "cif_total": cif_total,
        "net_weight_kg": round(net_total, 2),
        "gross_weight_kg": round(gross_total, 2),
    },
    "lines": [
        {
            "line": line["no"],
            "description": line["desc"],
            "cn8": line["cn8"].replace(" ", ""),
            "taric10": line["taric"].replace(" ", ""),
            "hs6": line["cn8"].replace(" ", "")[:6],
            "origin": line["origin"],
            "quantity": line["qty"],
            "unit_price": line["unit"],
            "amount": line["amount"],
        }
        for line in lines
    ],
    "intra_eu_invoice": {
        "number": "RT-2026-0457",
        "date": "2026-11-03",
        "total": eu_total,
        "vat_treatment": "reverse charge",
    },
    "documents": {
        "commercial_invoice": "01_commercial_invoice_CN_ES.pdf",
        "packing_list": "02_packing_list_CN_ES.pdf",
        "bill_of_lading": "03_bill_of_lading_CN_ES.pdf",
        "eu_import_declaration": "04_eu_import_declaration_SAD.pdf",
        "certificate_of_origin": "05_certificate_of_origin_CN.pdf",
        "intra_eu_invoice": "06_intra_eu_invoice_DE_ES.pdf",
        "cmr": "07_cmr_DE_ES.pdf",
    },
    "warning": "TARIC 10-digit suffixes are illustrative. Verify against the official TARIC database before production or real customs use.",
}
(ROOT / "ground_truth.json").write_text(json.dumps(ground, ensure_ascii=False, indent=2))
print("PDFs generados en", OUT)
for path in sorted(OUT.glob("*.pdf")):
    print(path.name, path.stat().st_size)
