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
import unicodedata
from dataclasses import dataclass
from typing import Iterable

import pdfplumber
import pytesseract
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


# Cabeceras de una palabra: se comparan con límite de palabra para no confundir
# un producto con una cabecera ("FROMAGE" no es la cabecera "FROM").
HEADER_PREFIXES = (
    "INVOICE",
    "DATE",
    "PAGE",
    "TOTAL",
    "SUBTOTAL",
    "TAX",
    "VAT",
    "BALANCE",
    "FROM",
    "TO",
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
    "ISSUED",
    "CURRENCY",
    "NOTES",
    "DESCRIPTION",
)

# Cabeceras compuestas: si la línea empieza por una de ellas, no es un producto.
HEADER_PREFIX_PHRASES = (
    "INVOICE NUMBER",
    "INVOICE DATE",
    "INVOICE NO",
    "BILLING ADDRESS",
    "SHIPPING ADDRESS",
    "AMOUNT DUE",
    "BILL TO",
    "SHIP TO",
    "PO BOX",
    "PAYMENT TERMS",
    "DUE DATE",
    "EXCHANGE RATE",
    "SUB-TOTAL",
)

# Cabeceras que también pueden iniciar una descripción de producto real
# ("PHONE CASE", "ADDRESS LABELS", "DRIED DATES").
_PRODUCT_CAPABLE_HEADERS = frozenset({"DATE", "PHONE", "ADDRESS", "TOTAL", "TAX"})

# Cabeceras que se detectan por prefijo, aunque el texto siga con letras
# ("EXPIR..." → "EXPIRED", "EXPIRES").
HEADER_STARTSWITH = ("EXPIR",)

# Patrones "no son un producto" (líneas de total, separadores, ...)
_NON_PRODUCT_RE = re.compile(
    r"^(?:"
    r"[\s\-\=\.\_\*\|]+"                # sólo separadores
    r"|page\s+\d+\s*(?:of\s+\d+)?"      # "page 1 of 3"
    r"|\d+\s*/\s*\d+"                   # "1/2"
    r")",
    re.IGNORECASE,
)

# Longitud mínima (en letras) para que una palabra cuente como descripción.
_MIN_TOKEN_LETTERS = 3

# Datos de factura que nunca describen un producto por sí solos: cabeceras,
# importes, impuestos, monedas e incoterms.
_METADATA_TOKENS = frozenset({
    # monedas
    "EUR", "EURS", "USD", "GBP", "CHF", "CNY", "RMB", "JPY", "MXN", "BRL", "INR",
    "ZAR", "SEK", "NOK", "DKK", "PLN",
    # totales, impuestos e importes
    "TOTAL", "TOTALS", "SUBTOTAL", "SUBTOTALES", "IVA", "VAT", "TAX", "TAXES",
    "IMPUESTO", "IMPUESTOS", "IMPORTE", "IMPORTES", "BASE", "IMPONIBLE", "NETO",
    "NET", "BRUTO", "GROSS", "PRECIO", "PRECIOS", "PRICE", "PORTE", "PORTES",
    "TRANSPORTE", "FREIGHT", "FLETE", "SEGURO", "INSURANCE", "AJUSTE", "EMISION",
    "CANCELACION", "RETENCION", "IRPF", "RECARGO", "CUOTA", "COMISION", "GASTOS",
    "CADUCIDAD", "VENCIMIENTO", "DEPOSITO", "TRANSFERENCIA", "CHEQUE", "EFECTIVO",
    "TARJETA", "AMOUNT", "AMT", "BALANCE", "PAYABLE", "VALUE", "DUE", "PLAZO",
    # incoterms y condiciones comerciales
    "INCOTERM", "INCOTERMS", "PVP", "FOB", "CIF", "CFR", "EXW", "FAS", "FCA",
    "CPT", "CIP", "DAP", "DPU", "DDP", "DDU",
    # cabeceras y metadatos de factura
    "FACTURA", "INVOICE", "INVOICES", "FECHA", "DATE", "PAGINA", "PAGE", "NOTAS",
    "NOTES", "DESCRIPCION", "DESCRIPCIONES", "DESCRIPTION", "DESCRIPTIONS",
    "CANTIDAD", "CANTIDADES", "QUANTITY", "QTY", "ARTICULO", "ARTICULOS", "ITEM",
    "REF", "PO", "CLIENTE", "CLIENT", "PROVEEDOR", "SUPPLIER", "EMISOR", "RECEPTOR",
    "DESTINATARIO", "TERMINOS", "TERMS", "CONDICIONES", "CONDITIONS", "PAGO",
    "PAYMENT", "PAYMENTS", "BANCO", "BANK", "IBAN", "BIC", "SWIFT", "CUENTA",
    "ACCOUNT", "REMITENTE", "CONSIGNEE", "EXPORTER", "IMPORTER", "PAIS", "COUNTRY",
    "ORIGEN", "ORIGIN", "DESTINO", "DESTINATION", "PUERTO", "PORT", "FACTURADO",
    "ALBARAN", "ALBARANES", "TERCEDIOS", "PROCEDENCIA", "ADUANAS", "ARANCEL",
    "ARANCELES", "TARIFA", "TARIFAS", "CARGA", "LOADING", "DISCHARGE", "EMBARKATION",
    "LANDING", "NAME", "NAMES", "NUMERO", "NUMBER", "NUM", "NO", "NIF", "CUI",
    "PRODUCT", "PRODUCTS", "PRODUCTO", "PRODUCTOS", "SHIPPER", "CARRIER", "SELLER",
    "BUYER", "VENDOR", "COTIZACION", "QUOTE", "DUTIES", "ARREARS", "CREDITS",
    "DEBITS", "SHIPMENTS", "ORDERS", "DELIVERIES",     "STATEMENT", "BOX", "BOXES",
    "RATE", "RATES", "TASA", "FORM", "FORMAS", "FORMA", "METHOD", "METHODS", "MODO",
    "METODO", "WEIGHT", "PESO", "REMITE", "REMITES", "DESTINATARIO", "OBSERVACIONES",
    "OBSERVATIONS", "COMMENTS", "COMENTARIOS", "REFERENCIA", "REFERENCE", "SERIE",
    "SERIES", "LOTE", "LOT", "BATCH", "MARCA", "BRAND", "MODELO", "MODEL", "COLOR",
    "SIZE", "TALLA", "MEDIDA", "MEASURE", "VOLUMEN", "VOLUME", "PESO",
})

# Unidades de medida y embalajes: no mantienen viva una línea corta, pero sí
# pueden aparecer dentro de una descripción ("10 CAJAS DE JAMÓN").
_UNIT_TOKENS = frozenset({
    "UDS", "UND", "UNITS", "UNIT", "UNIDADES", "PCS", "PC", "CTN", "CTNS", "PLT",
    "PLTS", "PAL", "PALLET", "PALLETS", "CAJA", "CAJAS", "BOL", "BOLS", "BOLSAS",
    "BAG", "BAGS", "CARTON", "CARTONS", "DRUM", "DRUMS", "KGS", "MT", "TON",
    "TONS", "CBM", "ROLL", "ROLLS", "BALE", "BALES", "KG", "LT", "ML", "CM", "MM",
    "UNITARIO", "UNITARIA", "PAGAR", "PORTAFOLIO",
})

# Conectores: prolongan una cabecera ("DATE DE EMISIÓN") pero no describen un
# producto por sí solos.
_CONNECTOR_TOKENS = frozenset({
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "OF", "AND", "BY", "PARA", "CON",
    "EN", "A", "TO", "FOR", "NO", "NR", "MAS", "N", "ON", "AT", "IN", "PER",
    "WITH", "FROM",
})

# Etiquetas de campo cuyo valor nunca es un producto ("Remitente: Juan Pérez").
# Si la línea empieza por una de ellas, se descarta entera.
_LABEL_HEAD_TOKENS = frozenset({
    "REMITENTE", "REMITE", "RECEPTOR", "DESTINATARIO", "CLIENTE", "PROVEEDOR",
    "EMISOR", "EXPORTER", "IMPORTER", "CONSIGNEE", "BUYER", "SELLER", "VENDOR",
    "BANCO", "IBAN", "BIC", "SWIFT", "CUENTA", "FORMA", "MODO", "METODO",
    "PLAZO", "VENCIMIENTO", "FECHA", "FACTURA", "INVOICE", "NUMERO", "REF",
    "PO", "PAGO", "PAGAR", "SERIE", "LOTE", "REFERENCIA", "OBSERVACIONES",
    "NOTAS", "COMENTARIOS", "INCOTERM", "COTIZACION", "PRESUPUESTO", "OFERTA",
    "DESCUENTO", "PORT", "PUERTO", "COUNTRY", "PAIS", "ORIGIN", "ORIGEN",
    "DESTINATION", "DESTINO", "ADDRESS", "DOMICILIO", "DOMICILIACION",
})

# Token de una línea: sólo letras (soporta acentos: "jamón" es un único token).
_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _normalize_token(token: str) -> str:
    """Mayúsculas sin acentos, para comparar contra las listas de ruido."""
    decomposed = unicodedata.normalize("NFKD", token.upper())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass
class ParsedInvoice:
    """Resultado del parseo de una factura."""

    raw_text: str
    descriptions: list[str]
    source: str  # "pdf" | "text" | "image"
    pages: int = 0


# ── Helpers ─────────────────────────────────────────────────────────────

def _starts_with_word(text: str, prefix: str) -> bool:
    """¿La línea empieza por `prefix` y la palabra termina ahí?"""
    if not text.upper().startswith(prefix):
        return False
    return not text[len(prefix):len(prefix) + 1].isalpha()


def _is_header_line(stripped: str) -> bool:
    """¿La línea empieza por una cabecera de factura?"""
    upper = stripped.upper()
    if any(upper.startswith(prefix) for prefix in HEADER_STARTSWITH):
        return True
    if any(_starts_with_word(stripped, phrase) for phrase in HEADER_PREFIX_PHRASES):
        return True

    for prefix in HEADER_PREFIXES:
        if not _starts_with_word(stripped, prefix):
            continue
        rest = stripped[len(prefix):].strip()
        if not rest or rest[0] in ":|/=-–—":
            return True
        first = _TOKEN_RE.findall(rest)
        if not first:
            return True
        normalized = _normalize_token(first[0])
        if normalized in _CONNECTOR_TOKENS or normalized in _METADATA_TOKENS:
            return True
        # Una cabecera que puede iniciar un producto ("PHONE CASE") sólo se
        # descarta si lo que sigue no es una descripción.
        return prefix not in _PRODUCT_CAPABLE_HEADERS
    return False


def _is_label_line(stripped: str) -> bool:
    """¿Es una etiqueta de metadato con valor? ("Forma de pago: transferencia")

    Se descarta si la línea empieza por una etiqueta de campo cuyo valor nunca
    es un producto, o si lo anterior a los dos puntos es sólo cabecera o
    conectores y el valor no describe un producto. Una descripción con dos
    puntos ("Jamón: cocido") se conserva.
    """
    tokens = _TOKEN_RE.findall(stripped)
    if tokens and _normalize_token(tokens[0]) in _LABEL_HEAD_TOKENS:
        return True
    head, sep, value = stripped.partition(":")
    if not sep:
        return False
    head_tokens = _TOKEN_RE.findall(head)
    if not head_tokens:
        return False
    if not all(
        _normalize_token(token) in _METADATA_TOKENS
        or _normalize_token(token) in _CONNECTOR_TOKENS
        for token in head_tokens
    ):
        return False
    # El valor decide: si describe un producto, la línea es una descripción.
    return not _has_content_token(_TOKEN_RE.findall(value))


def _has_content_token(tokens: list[str]) -> bool:
    """¿Algún token describe un producto (y no es un dato de la factura)?"""
    return any(
        len(token) >= _MIN_TOKEN_LETTERS
        and _normalize_token(token) not in _METADATA_TOKENS
        and _normalize_token(token) not in _CONNECTOR_TOKENS
        for token in tokens
    )


def _is_product_line(line: str) -> bool:
    """Heurística barata: ¿esta línea parece una descripción de producto?

    Una línea es producto si contiene alguna palabra que describa un producto
    (al menos 3 letras y que no sea un dato de la factura: cabecera, importe o
    conector). Así "jamón" se conserva y "1.234,56 EUR", "IVA 21%" o
    "IBAN ES91 2100 ..." siguen fuera.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if _NON_PRODUCT_RE.match(stripped):
        return False
    if _is_header_line(stripped):
        return False
    if _is_label_line(stripped):
        return False
    tokens = _TOKEN_RE.findall(stripped)
    if not tokens:
        return False
    content = [
        token for token in tokens
        if len(token) >= _MIN_TOKEN_LETTERS
        and _normalize_token(token) not in _METADATA_TOKENS
        and _normalize_token(token) not in _CONNECTOR_TOKENS
    ]
    if not content:
        return False
    # Una línea que sólo enumera embalajes ("20 CTNS") no describe un producto.
    only_units = all(_normalize_token(token) in _UNIT_TOKENS for token in content)
    return not (only_units and any(ch.isdigit() for ch in stripped))


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
                    for best in candidates:
                        if _is_product_line(best):
                            descriptions.append(best)
                            break

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
