#!/usr/bin/env python3
"""Valida la coherencia interna de un lote de facturas sintéticas.

Uso:
    python validate.py --batch /home/seby/mytarik/data/synthetic/batch_01
    python validate.py --batch ... --ocr     # además OCR de los escaneos

Comprueba aritmética de líneas y totales, IVA, códigos TARIC contra el
codebook, identificadores (NIF/CIF, IBAN, USCI, EORI), pesos y bultos,
fechas, coherencia origen/arquetipo y que cada página lleve "SPECIMEN".

Escribe validation/validation.json, validation/issues.csv y actualiza
manifest.json con un resumen.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdfplumber
import pytesseract
from PIL import ImageOps

import parties
from codebook import build_codebook

CENT = Decimal("0.01")
EU = {"ES", "DE", "FR", "IT", "PT", "NL", "PL", "BE"}
ORIGIN_COUNTRIES = {"ES", "DE", "FR", "IT", "PT", "NL", "PL", "BE", "GB", "CN", "IN",
                    "TR", "US", "VN", "BD", "PK", "MA", "TW", "KR", "JP", "TH"}
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_LETTERS = "JABCDEFGHI"
_USCI_ALPHABET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCI_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def dec(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def dnum(value) -> Decimal:
    return Decimal(str(value))


def check_nif(value: str) -> bool:
    value = (value or "").strip().upper()
    if re.fullmatch(r"\d{8}[A-Z]", value):
        return _DNI_LETTERS[int(value[:8]) % 23] == value[8]
    if re.fullmatch(r"[A-Z]\d{7}[0-9A-Z]", value):
        digits, control = value[1:8], value[8]
        total = 0
        for i, ch in enumerate(digits, start=1):
            digit = int(ch)
            if i % 2 == 1:
                total += digit * 2 // 10 + digit * 2 % 10
            else:
                total += digit
        expected = (10 - total % 10) % 10
        return control in (str(expected), _CIF_LETTERS[expected])
    return False


def check_usci(value: str) -> bool:
    value = (value or "").strip().upper()
    if len(value) != 18 or any(ch not in _USCI_ALPHABET for ch in value):
        return False
    total = sum(_USCI_ALPHABET.index(ch) * w for ch, w in zip(value[:17], _USCI_WEIGHTS))
    return _USCI_ALPHABET[(31 - total % 31) % 31] == value[17]


def normalize_words(text: str) -> str:
    text = text.upper().replace("DÓLARES", "DOLARES")
    return re.sub(r"\s+", " ", text).strip()


def check_doc(gt: dict, page_texts: list[str] | None, codebook: dict[str, set[str]]) -> list[dict]:
    issues: list[dict] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    lines = gt["lines"]
    totals = gt["totals"]
    inv = gt["invoice"]
    customs = gt["customs"]
    buyer = gt["buyer"]
    supplier = gt["supplier"]
    archetype = gt["archetype"]

    if not lines:
        issue("NO_LINES", "la factura no tiene líneas")
        return issues

    sum_amount = Decimal(0)
    sum_net = Decimal(0)
    sum_gross = Decimal(0)
    sum_packages = 0
    for index, line in enumerate(lines, start=1):
        if line.get("line_no") != index:
            issue("LINE_SEQ", f"línea {index} numerada {line.get('line_no')}")
        qty, price, amount = dec(line["quantity"]), dec(line["unit_price"]), dec(line["amount"])
        if abs(qty * price - amount) > CENT:
            issue("LINE_MATH", f"línea {index}: {qty} x {price} != {amount}")
        sum_amount += amount
        sum_net += dec(line["net_weight_kg"])
        sum_gross += dec(line["gross_weight_kg"])
        sum_packages += int(line["packages"])
        if dec(line["net_weight_kg"]) <= 0 or dec(line["gross_weight_kg"]) <= 0:
            issue("WEIGHT_POSITIVE", f"línea {index}: pesos no positivos")
        elif dec(line["gross_weight_kg"]) < dec(line["net_weight_kg"]):
            issue("WEIGHT_ORDER", f"línea {index}: bruto < neto")
        cn8, taric10 = line.get("cn8", ""), line.get("taric10", "")
        if cn8 not in codebook:
            issue("TARIC_MISSING", f"línea {index}: cn8 {cn8} no está en el codebook")
        elif taric10 not in codebook[cn8]:
            issue("TARIC_MISMATCH", f"línea {index}: taric10 {taric10} no pertenece a {cn8}")
        if line.get("hs6") != cn8[:6]:
            issue("HS6", f"línea {index}: hs6 {line.get('hs6')} != {cn8[:6]}")
        if line.get("origin") not in ORIGIN_COUNTRIES:
            issue("ORIGIN", f"línea {index}: origen {line.get('origin')} desconocido")
        if len(line.get("description", "")) < 6:
            issue("DESC_SHORT", f"línea {index}: descripción demasiado corta")
        if "SPECIMEN" in line.get("description", "").upper():
            issue("DESC_SPECIMEN", f"línea {index}: la descripción contiene SPECIMEN")

    goods = dec(totals["goods_amount"])
    if abs(sum_amount - goods) > CENT * max(1, len(lines)):
        issue("GOODS_SUM", f"suma de líneas {sum_amount} != goods_amount {goods}")

    discount = dec(totals["discount"])
    if abs(dec(goods * Decimal(str(totals["discount_pct"])) / 100) - discount) > CENT:
        issue("DISCOUNT", f"descuento {discount} no cuadra con {totals['discount_pct']}%")
    base = dec(goods - discount + dec(totals["freight"]) + dec(totals["insurance"])
               + dec(totals["other_costs"]))
    if abs(base - dec(totals["taxable_base"])) > CENT:
        issue("BASE", f"base imponible {totals['taxable_base']} != {base}")

    vat_sum = Decimal(0)
    vat_base_sum = Decimal(0)
    for group in totals["vat"]:
        group_base, rate = dec(group["base"]), dec(group["rate"])
        expected = dec(group_base * rate / 100)
        if abs(dec(group["amount"]) - expected) > CENT:
            issue("VAT_AMOUNT", f"IVA {group['rate']}%: {group['amount']} != {expected}")
        vat_sum += dec(group["amount"])
        vat_base_sum += group_base
    if abs(vat_base_sum - dec(totals["taxable_base"])) > CENT * max(1, len(totals["vat"])):
        issue("VAT_BASE", f"bases de IVA suman {vat_base_sum} != base {totals['taxable_base']}")
    if abs(vat_sum - dec(totals["vat_amount"])) > CENT:
        issue("VAT_SUM", f"cuotas de IVA suman {vat_sum} != {totals['vat_amount']}")
    total = dec(dec(totals["taxable_base"]) + dec(totals["vat_amount"]))
    if abs(total - dec(totals["total"])) > CENT:
        issue("TOTAL", f"total {totals['total']} != base + IVA {total}")

    fx = dnum(customs["fx_rate_eur"])
    if dnum(customs["fx_rate_eur"]) != dnum(inv["fx_rate_eur"]):
        issue("FX_MISMATCH", "fx distinto entre invoice y customs")
    if inv["currency"] == "EUR" and fx != 1:
        issue("FX_EUR", f"moneda EUR con fx {fx}")
    if fx <= 0:
        issue("FX_ZERO", "fx no positivo")
    elif abs(dec(dnum(totals["total"]) / fx) - dec(totals["total_eur"])) > CENT:
        issue("TOTAL_EUR", f"total_eur {totals['total_eur']} != total/fx")

    words_fn = parties.amount_in_words_es if gt["language"] == "es" else parties.amount_in_words_en
    expected_words = normalize_words(words_fn(abs(float(totals["total"])), inv["currency"]))
    if normalize_words(totals["total_in_words"]) != expected_words:
        issue("WORDS", f"importe en letras no cuadra: {totals['total_in_words']!r}")

    if customs["currency"] != inv["currency"]:
        issue("CUSTOMS_CURRENCY", "moneda de aduana distinta de la factura")
    if customs["incoterm"] != inv["incoterm"]:
        issue("CUSTOMS_INCOTERM", "incoterm de aduana distinto de la factura")
    if customs.get("eori_importer") != buyer.get("eori"):
        issue("EORI", f"EORI importador {customs.get('eori_importer')} != {buyer.get('eori')}")
    if buyer["country"] == "ES" and buyer.get("eori") != f"ES{buyer['tax_id']}":
        issue("EORI_FORMAT", f"EORI español {buyer.get('eori')} != ES{buyer['tax_id']}")

    if buyer["country"] == "ES" and not check_nif(buyer["tax_id"]):
        issue("NIF", f"NIF comprador inválido: {buyer['tax_id']}")
    if supplier["country"] == "ES" and not check_nif(supplier["tax_id"]):
        issue("NIF", f"NIF proveedor inválido: {supplier['tax_id']}")
    if supplier["country"] == "CN" and len(supplier["tax_id"]) == 18:
        if not check_usci(supplier["tax_id"]):
            issue("USCI", f"USCI inválido: {supplier['tax_id']}")

    transport = gt["transport"]
    if abs(sum_gross - dec(transport["gross_weight"])) > CENT * max(1, len(lines)):
        issue("TRANSPORT_WEIGHT", f"peso bruto {transport['gross_weight']} != suma {sum_gross}")
    if sum_packages != transport["packages"]:
        issue("TRANSPORT_PACKAGES", f"bultos {transport['packages']} != suma {sum_packages}")
    if sum_net > sum_gross + CENT:
        issue("WEIGHT_TOTAL", f"peso neto {sum_net} > bruto {sum_gross}")

    try:
        supply = date.fromisoformat(inv["supply_date"])
        issued = date.fromisoformat(inv["issue_date"])
        due = date.fromisoformat(inv["due_date"])
        if supply > issued:
            issue("DATE_ORDER", f"entrega {supply} posterior a emisión {issued}")
        if issued > due:
            issue("DATE_ORDER", f"vencimiento {due} anterior a emisión {issued}")
        if not date(2024, 1, 1) <= issued <= date(2027, 12, 31):
            issue("DATE_RANGE", f"fecha de emisión fuera de rango: {issued}")
    except ValueError as exc:
        issue("DATE_FORMAT", f"fecha inválida: {exc}")

    origins = {line["origin"] for line in lines}
    if archetype == "EXTRA_EU":
        if origins & EU:
            issue("ARCHETYPE_ORIGIN", f"EXTRA_EU con origen UE: {origins & EU}")
        if supplier["country"] in EU:
            issue("ARCHETYPE_SUPPLIER", f"EXTRA_EU con proveedor UE: {supplier['country']}")
        if totals["vat_amount"]:
            issue("IMPORT_VAT", f"importación con IVA soportado {totals['vat_amount']}")
    elif archetype == "INTRA_EU":
        if not origins <= EU:
            issue("ARCHETYPE_ORIGIN", f"INTRA_EU con origen no UE: {origins - EU}")
        if supplier["country"] not in EU:
            issue("ARCHETYPE_SUPPLIER", f"INTRA_EU con proveedor {supplier['country']}")
        if buyer["country"] != "ES":
            issue("ARCHETYPE_BUYER", "INTRA_EU con comprador no ES")
    elif archetype == "DOMESTIC":
        if origins != {"ES"}:
            issue("ARCHETYPE_ORIGIN", f"DOMESTIC con origen {origins}")
        if supplier["country"] != "ES" or buyer["country"] != "ES":
            issue("ARCHETYPE_PARTY", "DOMESTIC con partes no españolas")

    if page_texts is not None:
        if len(page_texts) != gt["pages"]:
            issue("PDF_PAGES", f"{len(page_texts)} páginas, se esperaban {gt['pages']}")
        for number, text in enumerate(page_texts, start=1):
            if sum(ch.isalpha() for ch in text) < 40:
                continue  # página escaneada sin OCR
            flat = re.sub(r"\s+", " ", text.replace("\u00a0", " "))
            if not _SPECIMEN_RE.search(flat):
                issue("PDF_SPECIMEN", f"página {number} sin marca SPECIMEN")
        if page_texts:
            flat = re.sub(r"\s+", " ", page_texts[0].replace("\u00a0", " "))
            if inv["number"] not in flat:
                # Un OCR a 150-200 ppp confunde I con 1 y l ("CI-" → "C1-");
                # el documento sigue siendo correcto, no es un error del lote.
                folded = _fold_confusables(inv["number"])
                if folded not in _fold_confusables(flat):
                    issue("PDF_NUMBER", f"número {inv['number']} no aparece en la página 1")

    return issues


# El OCR pierde la primera letra del sello ("RECEIVED PECIME"); la raíz sigue
# siendo inequívoca.
_SPECIMEN_RE = re.compile(r"SPECIM|PECIMEN", re.IGNORECASE)


def _fold_confusables(text: str) -> str:
    return re.sub(r"[1lI|!]", "1", text)


def _ocr_page(page, resolution: int, threshold: int | None = None) -> str:
    image = page.to_image(resolution=resolution).original.convert("L")
    if threshold is not None:
        image = ImageOps.autocontrast(image).point(
            lambda value: 255 if value > threshold else 0)
    return pytesseract.image_to_string(image, lang="eng", config="--psm 6")


def pdf_texts(path: Path, ocr: bool) -> list[str] | None:
    with pdfplumber.open(path) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]
        if sum(ch.isalpha() for text in texts for ch in text) >= 40 * len(texts):
            return texts
        if not ocr:
            return None
        parts = []
        for page in pdf.pages:
            text = _ocr_page(page, 250)
            if not _SPECIMEN_RE.search(text):
                # Páginas casi vacías: el ruido del escaneo domina y Tesseract
                # no lee nada; binarizar y ampliar sí rescata la marca.
                text = _ocr_page(page, 450, threshold=180)
            parts.append(text)
        return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--ocr", action="store_true", help="OCR de las páginas escaneadas")
    args = parser.parse_args(argv)

    batch: Path = args.batch
    manifest_path = batch / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    gt_files = sorted((batch / "ground_truth").glob("*.json"))
    if not gt_files:
        print(f"No hay ground truth en {batch}", file=sys.stderr)
        return 1

    entries = build_codebook()
    taric_index = {entry.cn8: set(entry.taric10) for entry in entries}

    results = []
    issues_csv = []
    seen_numbers: dict[str, str] = {}
    for path in gt_files:
        gt = json.loads(path.read_text())
        doc_id = gt["doc_id"]
        texts = None
        pdf = batch / "pdf" / f"{doc_id}.pdf"
        if pdf.exists():
            try:
                texts = pdf_texts(pdf, args.ocr)
            except Exception as exc:
                results.append({"doc_id": doc_id, "ok": False,
                                "issues": [{"code": "PDF_OPEN", "message": str(exc)}]})
                continue
        else:
            results.append({"doc_id": doc_id, "ok": False,
                            "issues": [{"code": "PDF_MISSING", "message": str(pdf)}]})
            continue

        issues = check_doc(gt, texts, taric_index)
        number = gt["invoice"]["number"]
        if number in seen_numbers:
            issues.append({"code": "NUMBER_DUP",
                           "message": f"número repetido con {seen_numbers[number]}"})
        seen_numbers[number] = doc_id
        for item in issues:
            issues_csv.append([doc_id, item["code"], item["message"]])
        results.append({"doc_id": doc_id, "ok": not issues, "issues": issues})

    out = batch / "validation"
    out.mkdir(exist_ok=True)
    by_code = Counter(item["code"] for result in results for item in result["issues"])
    summary = {
        "checked": len(results),
        "ok": sum(1 for result in results if result["ok"]),
        "with_issues": sum(1 for result in results if not result["ok"]),
        "issues_by_code": dict(sorted(by_code.items())),
        "ocr_pages": args.ocr,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out / "validation.json").write_text(json.dumps(
        {"summary": summary, "docs": results}, ensure_ascii=False, indent=1))
    with (out / "issues.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["doc_id", "codigo", "detalle"])
        writer.writerows(issues_csv)

    manifest["validation"] = summary
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    print(f"Validados {summary['checked']} documentos: {summary['ok']} sin errores, "
          f"{summary['with_issues']} con incidencias")
    if by_code:
        print("  " + ", ".join(f"{code}={count}" for code, count in by_code.most_common()))
    if not args.ocr:
        print("  (páginas escaneadas sin OCR: usa --ocr para comprobar SPECIMEN en ellas)")
    return 0 if not summary["with_issues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
