"""PDF text extraction with a PyMuPDF + Tesseract OCR fallback."""
from __future__ import annotations

import pymupdf
import pytesseract
from PIL import Image


def extract_text_from_pdf(pdf_path: str, min_words: int = 20) -> str:
    document = pymupdf.open(pdf_path)
    pages: list[str] = []
    try:
        for page in document:
            text = page.get_text("text").strip()
            if len(text.split()) < min_words:
                pix = page.get_pixmap()
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                ocr = pytesseract.image_to_string(image, lang="eng")
                text = f"{text}\n{ocr}".strip()
            pages.append(text)
    finally:
        document.close()
    return "\n\n".join(pages)
