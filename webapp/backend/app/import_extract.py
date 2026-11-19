"""Extract product descriptions from supplier files (not invoices).

Supports PDF (text/scan), XLSX, CSV, TXT, DOCX and ODT. Each non-empty row
becomes one product candidate; the caller applies the 100-item limit.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path


def _clean(value: object) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def _is_header(text: str) -> bool:
    low = text.lower()
    return low in {
        "descripcion", "descripción", "description", "producto", "product",
        "articulo", "artículo", "item", "artículos", "products",
    } or (len(text) < 4 and not any(ch.isdigit() for ch in text))


def _pdf_descriptions(raw: bytes, filename: str) -> list[str]:
    from app.invoice_parser import parse_invoice

    parsed = parse_invoice(filename, raw)
    return [_clean(line) for line in parsed.descriptions if _clean(line)]


def _text_descriptions(raw: bytes) -> list[str]:
    text = raw.decode("utf-8-sig", errors="replace")
    return [_clean(line) for line in text.splitlines() if _clean(line) and not _is_header(line)]


def _csv_descriptions(raw: bytes) -> list[str]:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    rows = csv.reader(io.StringIO(text), delimiter=delimiter)
    out: list[str] = []
    for index, row in enumerate(rows):
        values = [_clean(cell) for cell in row if _clean(cell)]
        if not values:
            continue
        # Longest cell is almost always the product description; skip header row.
        candidate = max(values, key=len)
        if index == 0 or _is_header(candidate):
            continue
        out.append(candidate)
    return out


def _xlsx_descriptions(raw: bytes) -> list[str]:
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    out: list[str] = []
    try:
        for sheet in workbook.worksheets:
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                values = [_clean(cell) for cell in row if _clean(cell)]
                if not values:
                    continue
                candidate = max(values, key=len)
                if index == 0 or _is_header(candidate):
                    continue
                out.append(candidate)
    finally:
        workbook.close()
    return out


def _docx_descriptions(raw: bytes) -> list[str]:
    import docx

    document = docx.Document(io.BytesIO(raw))
    out = [_clean(p.text) for p in document.paragraphs if _clean(p.text)]
    for table in document.tables:
        for row in table.rows:
            values = [_clean(cell.text) for cell in row.cells if _clean(cell.text)]
            if values:
                candidate = max(values, key=len)
                if not _is_header(candidate):
                    out.append(candidate)
    return out


def _odt_descriptions(raw: bytes) -> list[str]:
    from odf import teletype
    from odf.opendocument import load

    document = load(io.BytesIO(raw))
    out = []
    for paragraph in document.getElementsByType(teletype.Text):
        value = _clean(teletype.extractText(paragraph))
        if value and not _is_header(value):
            out.append(value)
    # ODT text nodes are usually inside paragraphs; dedupe consecutive fragments.
    return list(dict.fromkeys(out))


def extract_descriptions(filename: str, raw: bytes) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        values = _pdf_descriptions(raw, filename)
    elif suffix in {".txt", ".md"}:
        values = _text_descriptions(raw)
    elif suffix == ".csv":
        values = _csv_descriptions(raw)
    elif suffix in {".xlsx", ".xlsm"}:
        values = _xlsx_descriptions(raw)
    elif suffix == ".docx":
        values = _docx_descriptions(raw)
    elif suffix == ".odt":
        values = _odt_descriptions(raw)
    else:
        raise ValueError(f"Formato no soportado: {suffix or 'sin extensión'}")

    cleaned = []
    seen = set()
    for value in values:
        value = _clean(value)
        if not value or _is_header(value) or value in seen:
            continue
        seen.add(value)
        cleaned.append({"description": value})
        if len(cleaned) >= 100:
            break
    if not cleaned:
        raise ValueError("No se encontraron artículos en el documento")
    return cleaned
