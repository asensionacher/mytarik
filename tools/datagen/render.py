"""Presentación de la factura en PDF con 25 plantillas distintas.

Todo lo que se dibuja sale de ``Invoice``; aquí no se inventan datos. Cada
página lleva la marca de agua y el pie «SPECIMEN». Los encabezados de la tabla
de líneas usan las palabras que el parser de mytarik reconoce (Description /
Descripción, Quantity / Cantidad, CN Code, Amount / Importe).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from invoices import Invoice

W, H = A4

_MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
              "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Layout:
    key: str
    font: str
    accent: str
    header_mode: str
    table_mode: str
    parties: str
    totals: str
    margin: float
    fs: float
    title_en: str
    title_es: str
    title_align: str
    code_mode: str
    logo: str
    stamp: bool
    accent2: str = ""
    show_info_grid: bool = True


LAYOUTS: list[Layout] = [
    Layout("classic_grid", "Times-Roman", "#1A1A1A", "plain", "grid", "columns", "plain",
           42, 8.2, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_spaced", "square", False),
    Layout("modern_band", "Helvetica", "#1F3864", "band", "hlines", "columns", "box",
           36, 8.0, "INVOICE", "FACTURA", "right", "cn8_plain", "rounded", True),
    Layout("minimal_rule", "Helvetica", "#444444", "plain", "rows", "stacked", "plain",
           50, 8.4, "Invoice", "Factura", "left", "cn8_spaced", "none", False),
    Layout("boxed_parties", "Times-Roman", "#7A1F2B", "plain", "boxed", "boxes", "box",
           34, 7.9, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "center", "cn8_spaced", "square", True),
    Layout("sidebar_teal", "Helvetica", "#0E6E6E", "band", "zebra", "columns", "box",
           36, 8.1, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_plain", "circle", False,
           accent2="#0B4F4F"),
    Layout("zebra_green", "Helvetica", "#2E5E3A", "plain", "zebra", "columns", "plain",
           40, 8.2, "INVOICE", "FACTURA", "right", "cn8_spaced", "rounded", False),
    Layout("courier", "Courier", "#222222", "plain", "grid", "stacked", "double",
           44, 8.0, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_plain", "none", True),
    Layout("letterhead_center", "Times-Roman", "#243B53", "center", "hlines", "columns", "plain",
           46, 8.5, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "center", "cn8_spaced", "circle", True),
    Layout("dark_header", "Helvetica", "#2B2B2B", "dark", "hlines", "columns", "box",
           34, 8.0, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_spaced", "square", False),
    Layout("split_meta", "Helvetica", "#1B4F8A", "split", "rows", "columns", "box",
           38, 7.9, "INVOICE", "FACTURA", "right", "cn8_plain", "rounded", True),
    Layout("compact", "Helvetica", "#333333", "plain", "hlines", "columns", "plain",
           30, 7.4, "INVOICE", "FACTURA", "left", "cn8_spaced", "none", False),
    Layout("spacious_serif", "Times-Roman", "#3A2A1A", "plain", "rows", "columns", "plain",
           54, 9.2, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "center", "cn8_spaced", "none", True),
    Layout("factura_qr", "Helvetica", "#A61B29", "band", "grid", "boxes", "double",
           36, 8.0, "INVOICE", "FACTURA", "left", "cn8_plain", "square", True,
           accent2="#7C111C"),
    Layout("grey_band", "Helvetica", "#4A5568", "band", "boxed", "columns", "plain",
           38, 8.2, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "right", "cn8_spaced", "rounded", False),
    Layout("double_border", "Times-Roman", "#1A1A1A", "plain", "grid", "columns", "double",
           44, 8.1, "INVOICE", "FACTURA", "center", "cn8_spaced", "none", True),
    Layout("green_accent", "Helvetica", "#1F6F4A", "split", "zebra", "columns", "box",
           36, 8.0, "INVOICE", "FACTURA", "left", "cn8_plain", "rounded", True),
    Layout("purple_boxed", "Helvetica", "#4B2E6B", "plain", "boxed", "boxes", "box",
           38, 7.9, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "right", "cn8_spaced", "diamond", False),
    Layout("teal_minimal", "Helvetica", "#146C6C", "plain", "rows", "stacked", "plain",
           48, 8.4, "Invoice", "Factura", "right", "cn8_spaced", "circle", False),
    Layout("warm_serif", "Times-Roman", "#6B4423", "split", "hlines", "columns", "box",
           42, 8.6, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_spaced", "square", True),
    Layout("industrial", "Helvetica", "#263238", "dark", "grid", "columns", "double",
           34, 7.8, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "right", "cn8_plain", "square", False,
           accent2="#37474F"),
    Layout("elegant_serif", "Times-Roman", "#2F2F2F", "center", "rows", "columns", "plain",
           52, 9.0, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "center", "cn8_spaced", "diamond", True),
    Layout("factura_es", "Helvetica", "#C0392B", "band", "grid", "boxes", "double",
           34, 8.0, "INVOICE", "FACTURA", "right", "cn8_spaced", "square", True,
           accent2="#8E2418"),
    Layout("mono_boxed", "Courier", "#1A1A1A", "plain", "boxed", "stacked", "plain",
           42, 7.8, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_spaced", "none", True),
    Layout("wide_desc", "Helvetica", "#1F3864", "plain", "hlines", "columns", "box",
           28, 8.0, "COMMERCIAL INVOICE", "FACTURA COMERCIAL", "left", "cn8_plain", "rounded", False),
    Layout("two_tone", "Helvetica", "#0D3B66", "band", "zebra", "columns", "box",
           36, 8.0, "INVOICE", "FACTURA", "left", "cn8_spaced", "circle", True,
           accent2="#0A2A47"),
]

LAYOUT_BY_KEY = {layout.key: layout for layout in LAYOUTS}


def _bold(font: str) -> str:
    return {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold",
            "Courier": "Courier-Bold"}[font]


def _italic(font: str) -> str:
    return {"Helvetica": "Helvetica-Oblique", "Times-Roman": "Times-Italic",
            "Courier": "Courier-Oblique"}[font]


def money(value: float, lang: str) -> str:
    negative = value < 0
    text = f"{abs(value):,.2f}"
    if lang == "es":
        text = text.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")
    return ("-" if negative else "") + text


def num(value: float, lang: str) -> str:
    if float(value).is_integer():
        text = f"{abs(value):,.0f}"
    else:
        text = f"{abs(value):,.2f}"
    if lang == "es":
        text = text.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")
    return ("-" if value < 0 else "") + text


def fmt_date(value: date, lang: str, style: str) -> str:
    if style == "iso":
        return value.isoformat()
    if style == "long":
        if lang == "es":
            return f"{value.day} de {_MONTHS_ES[value.month - 1]} de {value.year}"
        return f"{value.day} {_MONTHS_EN[value.month - 1]} {value.year}"
    return value.strftime("%d/%m/%Y")


def _qr(data: str, size: float) -> Drawing:
    widget = QrCodeWidget(data, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    width, height = x1 - x0, y1 - y0
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    return drawing


class _Spacer(Flowable):
    def __init__(self, height: float):
        super().__init__()
        self.height = height

    def draw(self):
        pass


_FONT_DIRS = ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/TTF/")


def _pil_font(bold: bool, size: int):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for directory in _FONT_DIRS:
        try:
            return ImageFont.truetype(directory + name, size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=64)
def _text_image(text: str, bold: bool, rgb: tuple[int, int, int], alpha: int,
                px: int, angle: float):
    """Texto rasterizado. No queda como texto en el PDF, así que pdfplumber no
    puede mezclar sus glifos con las columnas de la tabla (marca de agua, sello)."""
    font = _pil_font(bold, px)
    probe = ImageDraw.Draw(Image.new("L", (4, 4)))
    box = probe.multiline_textbbox((0, 0), text, font=font, spacing=px // 4)
    image = Image.new(
        "RGBA",
        (box[2] - box[0] + px // 3, box[3] - box[1] + px // 3),
        (0, 0, 0, 0),
    )
    ImageDraw.Draw(image).multiline_text(
        (image.width / 2, image.height / 2),
        text,
        font=font,
        fill=rgb + (alpha,),
        spacing=px // 4,
        align="center",
        anchor="mm",
    )
    if angle:
        image = image.rotate(angle, expand=True, resample=Image.BICUBIC)
    return ImageReader(image), image.width, image.height


def _draw_text(c: canvas.Canvas, text: str, x: float, y: float, size: float, *,
               bold: bool = False, rgb: tuple[int, int, int] = (0, 0, 0),
               alpha: int = 255, align: str = "center", angle: float = 0.0):
    reader, width_px, height_px = _text_image(
        text, bold, rgb, alpha, max(8, int(size * 5)), angle
    )
    width = width_px / 5
    height = height_px / 5
    if align == "center":
        x -= width / 2
    elif align == "right":
        x -= width
    c.drawImage(reader, x, y - height * 0.32, width, height, mask="auto")


class _Stamp(Flowable):
    """Sello de goma ficticio, con la palabra SPECIMEN bien visible."""

    def __init__(self, name: str, size: float = 78):
        super().__init__()
        self.width = size * 1.55
        self.height = size
        self.name = name

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(self.width / 2, self.height / 2)
        c.rotate(-7)
        c.setStrokeColor(colors.Color(0.55, 0.15, 0.15, alpha=0.55))
        c.setLineWidth(1.6)
        c.roundRect(-self.width / 2 + 2, -self.height / 2 + 2, self.width - 4,
                    self.height - 4, 8, stroke=1, fill=0)
        c.setLineWidth(0.7)
        c.roundRect(-self.width / 2 + 6, -self.height / 2 + 6, self.width - 12,
                    self.height - 12, 6, stroke=1, fill=0)
        ink = (140, 38, 38)
        _draw_text(c, self.name[:30].upper(), 0, 12, 9.5, bold=True, rgb=ink, alpha=140)
        _draw_text(c, "RECEIVED", 0, 1, 7.5, rgb=ink, alpha=140)
        _draw_text(c, "SPECIMEN", 0, -11, 7, bold=True, rgb=ink, alpha=140)
        c.restoreState()


def _logo(layout: Layout, supplier_name: str, size: float = 40) -> Drawing:
    drawing = Drawing(size, size)
    initials = "".join(word[0] for word in supplier_name.replace(".", " ").split()[:2]).upper()
    accent = HexColor(layout.accent)
    if layout.logo == "square":
        drawing.add(Rect(0, 0, size, size, fillColor=accent, strokeColor=None))
        drawing.add(String(size / 2, size / 2 - 5, initials, fontName="Helvetica-Bold",
                           fontSize=size * 0.38, fillColor=colors.white, textAnchor="middle"))
    elif layout.logo == "rounded":
        drawing.add(Rect(0, 0, size, size, rx=7, ry=7, fillColor=accent, strokeColor=None))
        drawing.add(String(size / 2, size / 2 - 5, initials, fontName="Helvetica-Bold",
                           fontSize=size * 0.36, fillColor=colors.white, textAnchor="middle"))
    elif layout.logo == "circle":
        drawing.add(Circle(size / 2, size / 2, size / 2 - 1, fillColor=accent, strokeColor=None))
        drawing.add(String(size / 2, size / 2 - 5, initials, fontName="Helvetica-Bold",
                           fontSize=size * 0.34, fillColor=colors.white, textAnchor="middle"))
    elif layout.logo == "diamond":
        drawing.add(Circle(size / 2, size / 2, 0, fillColor=accent, strokeColor=None))
        points = [size / 2, size - 1, size - 1, size / 2, size / 2, 1, 1, size / 2]
        from reportlab.graphics.shapes import Polygon

        drawing.add(Polygon(points, fillColor=accent, strokeColor=None))
        drawing.add(String(size / 2, size / 2 - 5, initials, fontName="Helvetica-Bold",
                           fontSize=size * 0.30, fillColor=colors.white, textAnchor="middle"))
    return drawing


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw_total(total)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_total(self, total: int):
        self.setFont("Helvetica", 6.5)
        self.setFillColor(HexColor("#666666"))
        self.drawRightString(W - self._margin, 28, f"page {self._pageNumber} / {total}")


def render_invoice(invoice: Invoice, out_path: Path) -> int:
    layout = LAYOUT_BY_KEY[invoice.layout]
    lang = invoice.language
    lib = invoice.totals_labels if hasattr(invoice, "totals_labels") else {}
    accent = HexColor(layout.accent)
    accent2 = HexColor(layout.accent2 or layout.accent)
    margin = layout.margin
    fs = layout.fs

    styles = {
        "body": ParagraphStyle("body", fontName=layout.font, fontSize=fs, leading=fs + 2,
                               textColor=HexColor("#1A1A1A")),
        "small": ParagraphStyle("small", fontName=layout.font, fontSize=fs - 0.8,
                                leading=fs + 0.6, textColor=HexColor("#333333")),
        "tiny": ParagraphStyle("tiny", fontName=layout.font, fontSize=fs - 1.4,
                               leading=fs - 0.2, textColor=HexColor("#555555")),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=fs - 1.5,
                                leading=fs - 0.5, textColor=HexColor("#555555")),
        "title": ParagraphStyle("title", fontName=_bold(layout.font), fontSize=max(15, fs + 6.5),
                                leading=max(17, fs + 8.5), textColor=accent,
                                alignment={"left": 0, "right": 2, "center": 1}[layout.title_align]),
        "white_title": ParagraphStyle("white_title", fontName=_bold(layout.font),
                                      fontSize=max(14, fs + 5.5), leading=max(16, fs + 7),
                                      textColor=colors.white),
        "name": ParagraphStyle("name", fontName=_bold(layout.font), fontSize=fs + 0.8,
                               leading=fs + 2.8, textColor=HexColor("#111111")),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=fs - 0.9,
                             leading=fs + 0.2, textColor=colors.white, alignment=1),
        "th_l": ParagraphStyle("th_l", fontName="Helvetica-Bold", fontSize=fs - 0.9,
                               leading=fs + 0.2, textColor=colors.white, alignment=0),
        "cell": ParagraphStyle("cell", fontName=layout.font, fontSize=fs - 0.5,
                               leading=fs + 1.1, textColor=HexColor("#1A1A1A")),
        "cell_r": ParagraphStyle("cell_r", fontName=layout.font, fontSize=fs - 0.5,
                                 leading=fs + 1.1, textColor=HexColor("#1A1A1A"), alignment=2),
        "cell_b": ParagraphStyle("cell_b", fontName=_bold(layout.font), fontSize=fs - 0.5,
                                 leading=fs + 1.1, textColor=HexColor("#1A1A1A"), alignment=2),
    }

    def p(text: str, style: str = "body") -> Paragraph:
        return Paragraph(escape(str(text)), styles[style])

    def label_text(key: str, fallback: str) -> str:
        return lib.get(key, fallback)

    labels = {
        "en": {
            "supplier": "SUPPLIER / EXPORTER", "buyer": "BUYER / IMPORTER",
            "invoice_no": "Invoice No.", "invoice_date": "Invoice date", "due": "Due date",
            "order": "Customer order", "ref": "Our reference", "incoterm": "Incoterm",
            "currency": "Currency", "payment": "Payment terms", "origin": "Country of origin",
            "eori": "EORI", "vat": "VAT", "tax": "Tax ID", "contact": "Contact",
            "phone": "Tel.", "email": "E-mail", "bank": "BANK DETAILS",
            "beneficiary": "Beneficiary", "account": "Account", "swift": "SWIFT",
            "iban": "IBAN", "notes": "Notes", "shipping": "SHIPPING DETAILS",
            "page": "Page", "signature": "Authorised signature", "supply_date": "Supply date",
        },
        "es": {
            "supplier": "PROVEEDOR / EXPORTADOR", "buyer": "COMPRADOR / IMPORTADOR",
            "invoice_no": "Nº de factura", "invoice_date": "Fecha de factura",
            "due": "Vencimiento", "order": "Pedido del cliente", "ref": "Nuestra referencia",
            "incoterm": "Incoterm", "currency": "Moneda", "payment": "Forma de pago",
            "origin": "País de origen", "eori": "EORI", "vat": "NIF-IVA", "tax": "NIF",
            "contact": "Contacto", "phone": "Tel.", "email": "Correo electrónico",
            "bank": "DATOS BANCARIOS", "beneficiary": "Beneficiario", "account": "Cuenta",
            "swift": "SWIFT", "iban": "IBAN", "notes": "Observaciones",
            "shipping": "DATOS DE TRANSPORTE", "page": "Página",
            "signature": "Firma autorizada", "supply_date": "Fecha de entrega",
        },
    }[lang]

    # ── Cabecera ─────────────────────────────────────────────────────────
    supplier = invoice.supplier
    buyer = invoice.buyer
    country_label = supplier.country_name_es if lang == "es" else supplier.country_name_en
    buyer_country = buyer.country_name_es if lang == "es" else buyer.country_name_en

    supplier_lines = [
        p(supplier.name, "name"),
        p(supplier.address, "small"),
        p(f"{supplier.postcode} {supplier.city}, {country_label}", "small"),
    ]
    if supplier.tax_id:
        supplier_lines.append(p(f"{supplier.tax_label}: {supplier.tax_id}", "small"))
    if supplier.eori:
        supplier_lines.append(p(f"EORI: {supplier.eori}", "small"))
    supplier_lines.append(p(f"{labels['contact']}: {supplier.contact} · {supplier.phone}", "tiny"))
    supplier_lines.append(p(supplier.email, "tiny"))

    buyer_lines = [
        p(buyer.name, "name"),
        p(buyer.address, "small"),
        p(f"{buyer.postcode} {buyer.city}, {buyer_country}", "small"),
        p(f"{buyer.tax_label}: {buyer.tax_id}", "small"),
        p(f"EORI: {buyer.eori}", "small"),
        p(f"{labels['contact']}: {buyer.contact}", "tiny"),
    ]

    def party_box(party_lines: list, role: str) -> Table:
        table = Table([[p(role, "label")], [party_lines]], colWidths=["100%"])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LINEBELOW", (0, 0), (0, 0), 0.6, accent),
        ]))
        return table

    date_style = "dmy" if layout.key not in {"classic_grid", "dark_header"} else "long"
    meta_pairs = [
        (labels["invoice_no"], invoice.number),
        (labels["invoice_date"], fmt_date(invoice.issue_date, lang, date_style)),
        (labels["due"], fmt_date(invoice.due_date, lang, "dmy")),
        (labels["incoterm"], f"{invoice.incoterm} {invoice.incoterm_place}"),
        (labels["currency"], invoice.currency),
        (labels["payment"], invoice.payment_terms),
        (labels["order"], invoice.customer_ref),
        (labels["ref"], invoice.reference),
    ]
    if invoice.currency != "EUR":
        meta_pairs.append(("FX", f"1 EUR = {invoice.fx_rate:.4f} {invoice.currency}"))

    def meta_table(width: float, columns: int = 2) -> Table:
        rows = []
        for i in range(0, len(meta_pairs), columns):
            chunk = meta_pairs[i:i + columns]
            row = []
            for key, value in chunk:
                row.append(p(key, "label"))
                row.append(p(value, "small"))
            while len(row) < columns * 2:
                row.append("")
            rows.append(row)
        table = Table(rows, colWidths=[width * 0.24, width * 0.26] * columns)
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 0.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
        ]))
        return table

    story: list = []
    title = layout.title_es if lang == "es" else layout.title_en
    usable = W - 2 * margin

    header = None
    if layout.header_mode == "band":
        title_cell = p(title, "white_title")
        number_cell = p(invoice.number, "white_title")
        rows = [[title_cell, number_cell]]
        header = Table(rows, colWidths=[usable * 0.6, usable * 0.4])
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), accent2),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story += [header, Spacer(1, 8)]
        parties = Table([[party_box(supplier_lines, labels["supplier"]),
                          party_box(buyer_lines, labels["buyer"])]],
                        colWidths=[usable * 0.5, usable * 0.5])
        parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("LEFTPADDING", (0, 0), (0, 0), 0),
                                     ("RIGHTPADDING", (-1, 0), (-1, 0), 0)]))
        story += [parties, Spacer(1, 6), meta_table(usable, 2), Spacer(1, 8)]
    elif layout.header_mode == "dark":
        logo_cell = _logo(layout, supplier.name, 44)
        dark = Table(
            [[logo_cell, [p(title, "white_title"), p(invoice.number, "small")],
              [p(f"{labels['invoice_date']}: {fmt_date(invoice.issue_date, lang, 'dmy')}", "small"),
               p(f"{labels['due']}: {fmt_date(invoice.due_date, lang, 'dmy')}", "small")]]],
            colWidths=[52, usable * 0.55, usable - 52 - usable * 0.55],
        )
        dark.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), accent2),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story += [dark, Spacer(1, 8)]
        parties = Table([[party_box(supplier_lines, labels["supplier"]),
                          party_box(buyer_lines, labels["buyer"])]],
                        colWidths=[usable * 0.52, usable * 0.48])
        parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [parties, Spacer(1, 6), meta_table(usable, 2), Spacer(1, 8)]
    elif layout.header_mode == "center":
        logo = _logo(layout, supplier.name, 46)
        story += [Table([[logo]], colWidths=[usable], rowHeights=[48],
                        style=[("ALIGN", (0, 0), (-1, -1), "CENTER"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]), Spacer(1, 4)]
        story.append(p(supplier.name.upper(), "name"))
        story.append(p(f"{supplier.address} · {supplier.postcode} {supplier.city} · {country_label}", "small"))
        story.append(p(f"{supplier.tax_label}: {supplier.tax_id}" +
                       (f" · EORI: {supplier.eori}" if supplier.eori else ""), "small"))
        story.append(Spacer(1, 8))
        story.append(p(title, "title"))
        story.append(Spacer(1, 6))
        story += [meta_table(usable, 2), Spacer(1, 8)]
        parties = Table([[party_box(supplier_lines[1:], labels["supplier"]),
                          party_box(buyer_lines, labels["buyer"])]],
                        colWidths=[usable * 0.5, usable * 0.5])
        parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("BOX", (0, 0), (0, 0), 0.4, colors.HexColor("#BBBBBB")),
                                     ("BOX", (1, 0), (1, 0), 0.4, colors.HexColor("#BBBBBB")),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                     ("TOPPADDING", (0, 0), (-1, -1), 5),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [parties, Spacer(1, 8)]
    elif layout.header_mode == "split":
        split_logo = _logo(layout, supplier.name, 38)
        split_supplier = [
            p(supplier.name, "name"),
            p(f"{supplier.address}, {supplier.postcode} {supplier.city}", "small"),
            p(f"{supplier.tax_label}: {supplier.tax_id}" +
              (f" · EORI: {supplier.eori}" if supplier.eori else ""), "small"),
        ]
        split_title = [p(title, "title"), p(invoice.number, "body")]
        top = Table(
            [[split_logo, split_supplier, split_title]],
            colWidths=[44, usable * 0.5, usable - 44 - usable * 0.5],
        )
        top.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 1.0, accent),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [top, Spacer(1, 8)]
        parties = Table([[party_box(supplier_lines[1:], labels["supplier"]),
                          party_box(buyer_lines, labels["buyer"])]],
                        colWidths=[usable * 0.5, usable * 0.5])
        parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [parties, Spacer(1, 6), meta_table(usable, 2), Spacer(1, 8)]
    else:  # plain
        logo = _logo(layout, supplier.name, 36)
        title_cell = [p(title, "title"), p(invoice.number, "body")]
        top = Table([[logo, "", title_cell]],
                    colWidths=[40, usable * 0.52, usable - 40 - usable * 0.52])
        top.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        story += [top, Spacer(1, 6)]
        parties = Table([[party_box(supplier_lines, labels["supplier"]),
                          party_box(buyer_lines, labels["buyer"])]],
                        colWidths=[usable * 0.52, usable * 0.48])
        parties.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (1, 0), (1, 0), 0.4, colors.HexColor("#C8C8C8")),
            ("LEFTPADDING", (1, 0), (1, 0), 6),
            ("RIGHTPADDING", (1, 0), (1, 0), 6),
            ("TOPPADDING", (1, 0), (1, 0), 4),
            ("BOTTOMPADDING", (1, 0), (1, 0), 4),
        ]))
        story += [parties, Spacer(1, 6), meta_table(usable, 2), Spacer(1, 8)]

    # ── Transporte ───────────────────────────────────────────────────────
    shipping = invoice.transport
    ship_pairs: list[tuple[str, str]] = []
    if shipping["mode"] == "sea":
        ship_pairs = [
            ("Vessel / Voyage" if lang == "en" else "Buque / Viaje",
             f"{shipping['vessel']} / {shipping['voyage']}"),
            ("B/L No." if lang == "en" else "Nº B/L", shipping["bl_number"]),
            ("Container / Seal" if lang == "en" else "Contenedor / Precinto",
             f"{shipping['container']} / {shipping['seal']}"),
            ("Port of loading" if lang == "en" else "Puerto de carga", shipping["origin_port"]),
            ("Port of discharge" if lang == "en" else "Puerto de descarga", shipping["destination_port"]),
            ("Gross weight" if lang == "en" else "Peso bruto", f"{num(shipping['gross_weight'], lang)} kg"),
            ("Packages" if lang == "en" else "Bultos", str(shipping["packages"])),
            ("Customs office" if lang == "en" else "Aduana", shipping["customs_office"]),
        ]
    elif shipping["mode"] == "air":
        ship_pairs = [
            ("AWB", shipping["awb"]),
            ("From" if lang == "en" else "Origen", shipping["origin_airport"]),
            ("To" if lang == "en" else "Destino", shipping["destination_airport"]),
            ("Carrier" if lang == "en" else "Compañía", shipping["carrier"]),
            ("Gross weight" if lang == "en" else "Peso bruto", f"{num(shipping['gross_weight'], lang)} kg"),
            ("Pieces" if lang == "en" else "Bultos", str(shipping["packages"])),
            ("Customs office" if lang == "en" else "Aduana", shipping["customs_office"]),
        ]
    else:
        ship_pairs = [
            ("CMR", shipping["cmr_number"]),
            ("Carrier" if lang == "en" else "Transportista", shipping["carrier"]),
            ("Truck" if lang == "en" else "Camión", shipping["truck_plate"]),
            ("Route" if lang == "en" else "Ruta", shipping["route"]),
            ("Gross weight" if lang == "en" else "Peso bruto", f"{num(shipping['gross_weight'], lang)} kg"),
            ("Packages" if lang == "en" else "Bultos", str(shipping["packages"])),
        ]
    ship_rows = []
    for i in range(0, len(ship_pairs), 4):
        row = []
        for key, value in ship_pairs[i:i + 4]:
            row += [p(key, "label"), p(value, "tiny")]
        while len(row) < 8:
            row.append("")
        ship_rows.append(row)
    ship_table = Table(ship_rows, colWidths=[usable / 8] * 8)
    ship_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F4F2")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D0D0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story += [ship_table, Spacer(1, 8)]

    # ── Tabla de líneas ──────────────────────────────────────────────────
    header_label = {
        "en": ["No.", "Description", "CN Code", "Origin", "Quantity", "Unit",
               "Unit price", "Amount"],
        "es": ["Nº", "Descripción", "Código CN", "Origen", "Cantidad", "Unidad",
               "Precio unit.", "Importe"],
    }[lang]
    if layout.key in {"minimal_rule", "spacious_serif", "elegant_serif"}:
        header_label[1] = "Description of goods" if lang == "en" else "Descripción de la mercancía"
    if layout.key in {"compact", "wide_desc", "courier"}:
        header_label[1] = "Description of goods" if lang == "en" else "Descripción de la mercancía"

    cell_size = fs - 0.5
    amounts = [money(line.amount, lang) for line in invoice.lines] or ["0.00"]
    prices = [money(line.unit_price, lang) for line in invoice.lines] or ["0.00"]
    quantities = [num(line.quantity, lang) for line in invoice.lines] or ["0"]

    def head_width(text: str) -> float:
        return stringWidth(text, "Helvetica-Bold", fs - 0.9) + 8

    amount_w = max(62, head_width(header_label[7]),
                   max(stringWidth(a, layout.font, cell_size) for a in amounts) + 7)
    price_w = max(50, head_width(header_label[6]),
                  max(stringWidth(p, layout.font, cell_size) for p in prices) + 7)
    qty_w = max(38, head_width(header_label[4]),
                max(stringWidth(q, layout.font, cell_size) for q in quantities) + 7)
    unit_w = max(34, head_width(header_label[5]))
    origin_w = max(30, head_width(header_label[3]))
    code_w = max(52, head_width(header_label[2]))
    if layout.key == "wide_desc":
        widths = [22, 0, code_w, origin_w, qty_w, unit_w, price_w, amount_w]
    else:
        widths = [24, 0, code_w, origin_w, qty_w, unit_w, price_w, amount_w]
    widths[1] = usable - sum(widths)
    scale = usable / sum(widths)
    widths = [w * scale for w in widths]

    head_row = [p(h, "th") for h in header_label]
    head_row[1] = p(header_label[1], "th_l")

    rows: list[list] = [head_row]
    for line in invoice.lines:
        if layout.code_mode == "taric10_spaced":
            code = f"{line.taric10[:4]} {line.taric10[4:6]} {line.taric10[6:8]} {line.taric10[8:]}"
        elif layout.code_mode == "cn8_plain":
            code = line.cn8
        else:
            code = f"{line.cn8[:4]} {line.cn8[4:6]} {line.cn8[6:8]}"
        rows.append([
            p(str(line.line_no), "cell_r"),
            p(line.description, "cell"),
            p(code, "cell_r"),
            p(line.origin, "cell"),
            p(num(line.quantity, lang), "cell_r"),
            p(line.unit, "cell"),
            p(money(line.unit_price, lang), "cell_r"),
            p(money(line.amount, lang), "cell_b"),
        ])

    items = Table(rows, colWidths=widths, repeatRows=1)
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
    ]
    if layout.table_mode == "grid":
        commands += [("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9A9A9A")),
                     ("BACKGROUND", (0, 0), (-1, 0), accent)]
    elif layout.table_mode == "hlines":
        commands += [("LINEBELOW", (0, 0), (-1, 0), 1.0, accent),
                     ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#C8C8C8")),
                     ("BACKGROUND", (0, 0), (-1, 0), accent)]
    elif layout.table_mode == "zebra":
        commands += [("BACKGROUND", (0, 0), (-1, 0), accent),
                     ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DCDCDC"))]
        for i in range(2, len(rows), 2):
            commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F3F5F7")))
    elif layout.table_mode == "boxed":
        commands += [("BOX", (0, 0), (-1, -1), 0.8, accent),
                     ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B0B0B0")),
                     ("BACKGROUND", (0, 0), (-1, 0), accent)]
    else:  # rows
        commands += [("LINEBELOW", (0, 0), (-1, 0), 1.2, accent)]
    items.setStyle(TableStyle(commands))
    story += [items, Spacer(1, 6)]

    # ── Totales ──────────────────────────────────────────────────────────
    t = lib
    total_rows: list[list] = []
    adjustments = (
        invoice.discount or invoice.freight or invoice.insurance or invoice.other_costs
        or (invoice.archetype == "EXTRA_EU" and invoice.incoterm in {"CIF", "CFR"})
    )
    if adjustments:
        total_rows.append([p(t["goods"], "cell"), p(money(invoice.goods_amount, lang), "cell_b")])
        if invoice.discount:
            total_rows.append([p(f"{t['discount']} ({num(invoice.discount_pct, lang)} %)",
                                 "cell"), p(money(-invoice.discount, lang), "cell_b")])
        if invoice.freight or invoice.archetype == "EXTRA_EU" and invoice.incoterm in {"CIF", "CFR"}:
            total_rows.append([p(t["freight"], "cell"), p(money(invoice.freight, lang), "cell_b")])
        if invoice.insurance or invoice.archetype == "EXTRA_EU" and invoice.incoterm == "CIF":
            total_rows.append([p(t["insurance"], "cell"), p(money(invoice.insurance, lang), "cell_b")])
        if invoice.other_costs:
            total_rows.append([p(t["other"], "cell"), p(money(invoice.other_costs, lang), "cell_b")])
        total_rows.append([p(t["base"], "cell_b"), p(money(invoice.taxable_base, lang), "cell_b")])
    else:
        zero_rated = bool(invoice.vat_breakdown) and invoice.vat_breakdown[0]["rate"] == 0
        label = t["goods"] if zero_rated else t["base"]
        total_rows.append([p(label, "cell_b"), p(money(invoice.taxable_base, lang), "cell_b")])
    for group in invoice.vat_breakdown:
        label = f"{t['vat']} {group['rate']} %"
        if group["rate"] == 0:
            label = f"{t['vat']} 0 %" + (" (import)" if invoice.archetype == "EXTRA_EU" else " (ISP)")
        total_rows.append([p(label, "cell"), p(money(group["amount"], lang), "cell_b")])
    total_rows.append([p(t["total"] + " " + invoice.currency, "name"),
                       p(money(invoice.total, lang), "name")])

    totals = Table(total_rows, colWidths=[150, 96])
    total_commands = [
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent),
    ]
    if layout.totals == "box":
        total_commands += [("BOX", (0, 0), (-1, -1), 0.6, accent),
                           ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F0F0EC"))]
    elif layout.totals == "double":
        total_commands += [("BOX", (0, 0), (-1, -1), 1.6, accent),
                           ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#BEBEBE"))]
    else:
        total_commands += [("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor("#999999")),
                           ("LINEBELOW", (0, len(total_rows) - 2), (-1, len(total_rows) - 2),
                            0.4, colors.HexColor("#999999"))]
    totals.setStyle(TableStyle(total_commands))

    words = Table(
        [[p(f"{t['words']}: {invoice.words}", "tiny")]],
        colWidths=[usable - 260],
    )
    words.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 6)]))

    totals_block = Table([[words, totals]], colWidths=[usable - 250, 250])
    totals_block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [totals_block, Spacer(1, 6)]

    # ── QR, notas, banco, firma ──────────────────────────────────────────
    bottom_stuff: list = []
    if invoice.qr:
        qr_drawing = _qr(invoice.qr, 62)
        qr_table = Table([[qr_drawing, p(
            ("Factura verificable en la sede electrónica de la AEAT" if lang == "es"
             else "Invoice verifiable at the AEAT electronic site"), "tiny")]],
            colWidths=[66, usable - 66])
        qr_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        bottom_stuff += [qr_table, Spacer(1, 4)]

    if invoice.notes:
        note_cells = [p(note, "tiny") for note in invoice.notes]
        notes_table = Table([[p(labels["notes"], "label")], [note_cells]], colWidths=[usable])
        notes_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
        ]))
        bottom_stuff += [notes_table, Spacer(1, 6)]

    bank = invoice.bank_details
    if bank.get("iban") or bank.get("account"):
        bank_left = [p(labels["bank"], "label"), p(bank["beneficiary"], "small")]
        if bank.get("iban"):
            bank_left.append(p(f"{labels['iban']}: {bank['iban']}", "small"))
        if bank.get("account"):
            bank_left.append(p(f"{labels['account']}: {bank['account']}", "small"))
        bank_right = [p(bank["bank"], "small")]
        if bank.get("swift"):
            bank_right.append(p(f"{labels['swift']}: {bank['swift']}", "small"))
        if invoice.currency != "EUR":
            bank_right.append(p(f"Amounts in {invoice.currency}", "tiny"))
        bank_table = Table([[bank_left, bank_right, _Stamp(supplier.name) if layout.stamp else ""]],
                           colWidths=[usable * 0.48, usable * 0.30, usable * 0.22])
        bank_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("LINEABOVE", (0, 0), (-1, 0), 0.4, colors.HexColor("#BBBBBB")),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
        ]))
        bottom_stuff += [bank_table]
    elif layout.stamp:
        bottom_stuff += [Table([["", _Stamp(supplier.name)]], colWidths=[usable * 0.6, usable * 0.4],
                               style=[("ALIGN", (1, 0), (1, 0), "RIGHT")])]

    if invoice.correction:
        correction_text = (
            f"Rectificativa de la factura {invoice.correction['original_number']} "
            f"de {invoice.correction['original_date']}. Motivo: {invoice.correction['reason']}."
            if lang == "es" else
            f"Credit note relating to invoice {invoice.correction['original_number']} "
            f"dated {invoice.correction['original_date']}. Reason: {invoice.correction['reason']}."
        )
        bottom_stuff.insert(0, p(correction_text, "body"))
        bottom_stuff.insert(1, Spacer(1, 4))

    story += [KeepTogether(bottom_stuff)] if bottom_stuff else []

    # ── Documento ────────────────────────────────────────────────────────
    def on_page(c: canvas.Canvas, doc):
        c.saveState()
        c.setStrokeColor(accent)
        c.setLineWidth(2.2)
        c.line(margin, H - 24, W - margin, H - 24)
        # marca de agua (imagen: no queda texto extraíble encima de la tabla)
        c.saveState()
        reader, wm_w, wm_h = _text_image("SPECIMEN", True, (150, 150, 150), 40, 342, 38)
        wm_width = 330
        wm_height = wm_h * wm_width / wm_w
        c.drawImage(reader, W / 2 - wm_width / 2, H / 2 - wm_height / 2,
                    wm_width, wm_height, mask="auto")
        c.restoreState()
        # pie (rasterizado: tampoco se mezcla con la tabla al extraer texto)
        c.setStrokeColor(colors.HexColor("#CCCCCC"))
        c.setLineWidth(0.5)
        c.line(margin, 44, W - margin, 44)
        if lang == "es":
            centre = "SPECIMEN · DOCUMENTO SINTÉTICO · NO VÁLIDO COMO FACTURA"
        else:
            centre = "SPECIMEN · SYNTHETIC DOCUMENT · NOT A VALID INVOICE"
        _draw_text(c, invoice.number, margin, 32, 6.5, rgb=(119, 119, 119), align="left")
        _draw_text(c, centre, W / 2, 32, 6.5, rgb=(119, 119, 119), align="center")
        # Capa de texto invisible, como el OCR de un escaneo: permite
        # verificar por extracción que la página es sintética.
        marker = c.beginText(margin, 7)
        marker.setFont("Helvetica", 5)
        marker.setTextRenderMode(3)
        marker.textOut(f"{centre} · {invoice.number}")
        c.drawText(marker)
        c.restoreState()

    template = PageTemplate(
        id="main",
        frames=[Frame(margin, 52, W - 2 * margin, H - 52 - 40, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
        onPage=on_page,
    )

    document = BaseDocTemplate(
        str(out_path),
        pagesize=A4,
        pageTemplates=[template],
        leftMargin=margin,
        rightMargin=margin,
        topMargin=40,
        bottomMargin=52,
        title=f"{invoice.number} — SPECIMEN",
        author=supplier.name,
        subject="Synthetic commercial invoice (SPECIMEN)",
        creator="mytarik datagen",
    )
    document.build(story, canvasmaker=type("SpecimenCanvas", (NumberedCanvas,),
                                           {"_margin": margin}))
    pages = int(getattr(document, "page", 1))
    invoice.pages = pages
    return pages
