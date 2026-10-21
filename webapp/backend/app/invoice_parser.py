"""
invoice_parser.py — extracción de líneas de producto desde facturas.

Soporta:
- PDF con texto embebido (idealmente con tablas): `pdfplumber`
- Texto plano (.txt, .csv): una descripción por línea
- Imágenes (.png, .jpg, .webp): OCR con Tesseract (`pytesseract`)

Devuelve SIEMPRE `list[str]`: descripciones normalizadas listas para enviar
a TariffAI (que aplicará su propio preprocesado regex encima).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Iterable

import pdfplumber
import pytesseract
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


HEADER_PREFIXES = (
    "INVOICE",
    "INVOICE NO",
    "INVOICE NUMBER",
    "DATE",
    "PAGE",
    "TOTAL",
    "SUBTOTAL",
    "SUB-TOTAL",
    "TAX",
    "VAT",
    "AMOUNT DUE",
    "BALANCE",
    "BILL TO",
    "BILLING ADDRESS",
    "SHIP TO",
    "SHIPPING ADDRESS",
    "FROM",
    "TO:",
    "EMAIL",
    "PHONE",
    "FAX",
    "ADDRESS",
    "CUSTOMER",
    "SUPPLIER",
    "VENDOR",
    "SELLER",
    "BUYER",
    "RECEIVER",
    "CONSIGNEE",
    "PO BOX",
    "PAYMENT TERMS",
    "DUE DATE",
    "INVOICE DATE",
    "ISSUED",
    "EXPIR",
    "CURRENCY",
    "EXCHANGE RATE",
    "NOTES",
    "DESCRIPTION",  # Cabecera típica de tabla: "DESCRIPTION | QTY | UNIT PRICE"
)

# Patrones "no son un producto" (líneas de total, separadores, ...)
_NON_PRODUCT_RE = re.compile(
    r"^(?:"
    r"[\s\-\=\.\_\*\|]+"                # sólo separadores
    r"|page\s+\d+\s*(?:of\s+\d+)?"      # "page 1 of 3"
    r"|\d+\s*/\s*\d+"                   # "1/2"
    r")",
    re.IGNORECASE,
)


@dataclass
class ParsedInvoice:
    """Resultado del parseo de una factura."""

    raw_text: str
    descriptions: list[str]
    source: str  # "pdf" | "text" | "image"
    pages: int = 0


# ── Helpers ─────────────────────────────────────────────────────────────

def _is_product_line(line: str) -> bool:
    """Heurística barata: ¿esta línea parece una descripción de producto?"""
    stripped = line.strip()
    if len(stripped) < 6:
        return False
    if _NON_PRODUCT_RE.match(stripped):
        return False
    upper = stripped.upper()
    if any(upper.startswith(prefix) for prefix in HEADER_PREFIXES):
        return False
    # necesitamos algo de texto "real"
    letters = sum(ch.isalpha() for ch in stripped)
    if letters < 5:
        return False
    return True


def _dedup_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


# ── PDF ─────────────────────────────────────────────────────────────────

def _extract_text_from_pdf(content: bytes) -> tuple[str, int]:
    text_parts: list[str] = []
    page_count = 0
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts), page_count


def _extract_descriptions_from_tables(content: bytes) -> list[str]:
    """
    Intento 'estructurado': leer tablas reales con pdfplumber.
    Devuelve la celda con más letras de cada fila de datos (probablemente la descripción).
    Si no encuentra tablas razonables, devuelve `[]`.
    """
    descriptions: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if len(table) < 2:
                    continue

                # Detectar fila de cabecera: la primera con muchas celdas no vacías
                header_idx = 0
                for idx, row in enumerate(table[:3]):
                    if row and sum(1 for c in row if c and c.strip()) >= 3:
                        header_idx = idx
                        break

                for row in table[header_idx + 1:]:
                    if not row:
                        continue
                    # Celdas con algo de texto
                    cells = [(c or "").strip() for c in row]
                    non_empty = [c for c in cells if c]
                    if len(non_empty) < 2:
                        continue
                    # Ignorar filas que son básicamente números (totales por línea)
                    if all(re.fullmatch(r"[\d\.,\-\s€$£¥%]+", c) for c in non_empty):
                        continue

                    # La descripción suele ser la celda más larga con letras mezcladas
                    candidates = sorted(
                        non_empty,
                        key=lambda c: (
                            -sum(ch.isalpha() for ch in c),
                            -len(c),
                        ),
                    )
                    best = candidates[0]
                    if sum(ch.isalpha() for ch in best) >= 5 and len(best) >= 6:
                        descriptions.append(best)

    return descriptions


def parse_pdf(content: bytes) -> ParsedInvoice:
    """Extrae líneas de producto de un PDF.

    Estrategia: primero intenta leer tablas (más fiable); si no encuentra,
    cae al texto plano línea por línea.
    """
    full_text, pages = _extract_text_from_pdf(content)

    descriptions = _extract_descriptions_from_tables(content)
    if not descriptions:
        descriptions = _split_lines_to_descriptions(full_text)

    descriptions = _dedup_preserve_order(descriptions)

    return ParsedInvoice(
        raw_text=full_text,
        descriptions=descriptions,
        source="pdf",
        pages=pages,
    )


# ── Texto plano ─────────────────────────────────────────────────────────

def _split_lines_to_descriptions(text: str) -> list[str]:
    """Estrategia común: partir por líneas y filtrar."""

    # Si el texto viene todo en una línea intenta romper en frases con productos
    # reconocibles (heurística pobre). En general, una factura viene en líneas.
    raw_lines = [ln.strip() for ln in text.splitlines()]
    raw_lines = [ln for ln in raw_lines if _is_product_line(ln)]

    # Si sólo obtuvimos 1 línea y es muy larga, intentar partir por separadores típicos
    if len(raw_lines) == 1 and len(raw_lines[0]) > 200:
        candidate = raw_lines[0]
        chunks = re.split(
            r"\s{2,}|(?<=\S)\s(?=\d+\s*[xX]\s)|(?<=\S)\s{1,}(?=[A-Z][a-z])",
            candidate,
        )
        raw_lines = [c.strip() for c in chunks if _is_product_line(c)]

    return raw_lines


def parse_text(content: bytes) -> ParsedInvoice:
    """Interpreta texto plano o CSV (una descripción por línea)."""
    text = content.decode("utf-8", errors="replace")
    descriptions = _dedup_preserve_order(_split_lines_to_descriptions(text))
    return ParsedInvoice(raw_text=text, descriptions=descriptions, source="text")


# ── Imágenes (OCR) ──────────────────────────────────────────────────────

def parse_image(content: bytes) -> ParsedInvoice:
    """Aplica OCR (Tesseract) a una imagen y extrae las líneas de descripción."""
    try:
        image = Image.open(io.BytesIO(content))
    except Exception as exc:
        raise ValueError(f"No se pudo abrir la imagen: {exc}") from exc

    try:
        text = pytesseract.image_to_string(image, lang=settings.tesseract_langs)
    except pytesseract.TesseractError as exc:
        raise RuntimeError(f"Tesseract falló: {exc}") from exc

    descriptions = _dedup_preserve_order(_split_lines_to_descriptions(text))
    return ParsedInvoice(raw_text=text, descriptions=descriptions, source="image")


# ── Dispatcher ──────────────────────────────────────────────────────────

PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt", ".csv", ".tsv", ".md"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def parse_invoice(filename: str, content: bytes) -> ParsedInvoice:
    """Detecta el tipo por la extensión del filename y dispatcha."""
    name = filename.lower().strip()
    if name.endswith(tuple(PDF_EXTS)):
        return parse_pdf(content)
    if name.endswith(tuple(TEXT_EXTS)):
        return parse_text(content)
    if name.endswith(tuple(IMAGE_EXTS)):
        return parse_image(content)
    raise ValueError(
        f"Extensión no soportada para '{filename}'. "
        f"Use uno de: {sorted(PDF_EXTS | TEXT_EXTS | IMAGE_EXTS)}"
    )


__all__ = ["ParsedInvoice", "parse_invoice", "parse_pdf", "parse_text", "parse_image"]
