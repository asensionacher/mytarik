#!/usr/bin/env python3
"""Genera un lote de facturas sintéticas con su ground truth y manifiesto.

Uso:
    python generate.py --count 500 --batch 1 --out /home/seby/mytarik/data/synthetic

Cada factura produce:

    pdf/inv-b01-0001.pdf            documento (nativo o escaneado)
    ground_truth/inv-b01-0001.json  datos exactos de la factura
    ground_truth.jsonl              todas las facturas del lote
    review_manifest.csv/.xlsx       manifiesto para la revisión manual
    manifest.json                   resumen del lote
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from codebook import build_codebook
from invoices import ARCHETYPE_WEIGHTS, build_invoice
from products import Catalog
from render import LAYOUTS, render_invoice
from scanify import scanify

COLUMNS = [
    ("doc_id", 13), ("archivo", 26), ("tipo", 11), ("idioma", 7), ("plantilla", 17),
    ("escaneada", 10), ("paginas", 8), ("numero", 18), ("fecha", 11), ("proveedor", 40),
    ("pais", 6), ("comprador", 40), ("moneda", 7), ("incoterm", 16), ("lineas", 7),
    ("total", 13), ("total_eur", 13), ("estado", 16), ("tipo_error", 15), ("comentario", 32),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("/home/seby/mytarik/data/synthetic"))
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--no-scan", action="store_true", help="No rasterizar (pruebas)")
    parser.add_argument("--only", help="Genera solo este doc_id, para depurar")
    args = parser.parse_args(argv)

    catalogo = Catalog.load(build_codebook())
    out = args.out / f"batch_{args.batch:02d}"
    pdf_dir = out / "pdf"
    gt_dir = out / "ground_truth"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    gt_dir.mkdir(parents=True, exist_ok=True)

    layouts = LAYOUTS[:]
    random.Random(f"layouts:{args.seed}:{args.batch}").shuffle(layouts)

    used_numbers: set[str] = set()
    used_suppliers: set[str] = set()
    used_buyers: set[str] = set()

    rows: list[dict] = []
    ground_truth: list[dict] = []
    started = time.time()

    for index in range(1, args.count + 1):
        doc_id = f"inv-b{args.batch:02d}-{index:04d}"
        if args.only and args.only != doc_id:
            continue
        rng = random.Random(f"mytarik:{args.seed}:{args.batch}:{index}")
        archetype = rng.choices(
            [pair[0] for pair in ARCHETYPE_WEIGHTS],
            weights=[pair[1] for pair in ARCHETYPE_WEIGHTS],
            k=1,
        )[0]
        layout = layouts[(index - 1) % len(layouts)].key

        edge_case = None
        roll = rng.random()
        if archetype in {"DOMESTIC", "INTRA_EU"} and roll < 0.02:
            edge_case = "credit_note"
        elif roll < 0.07:
            edge_case = "single_line"
        elif roll < 0.13:
            edge_case = "many_lines"

        invoice = build_invoice(
            rng, doc_id, catalogo, archetype, None, layout,
            used_numbers, used_suppliers, used_buyers, edge_case=edge_case,
        )
        if args.no_scan:
            invoice.scan = False

        pdf_path = pdf_dir / f"{doc_id}.pdf"
        if invoice.scan:
            native = pdf_dir / f".{doc_id}.native.pdf"
            pages = render_invoice(invoice, native)
            scanify(native, pdf_path, rng, invoice.scanned_angle)
            native.unlink(missing_ok=True)
            invoice.pages = pages
        else:
            invoice.pages = render_invoice(invoice, pdf_path)

        payload = invoice.as_dict()
        (gt_dir / f"{doc_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        ground_truth.append(payload)

        rows.append({
            "doc_id": doc_id,
            "archivo": f"pdf/{doc_id}.pdf",
            "tipo": archetype,
            "idioma": invoice.language,
            "plantilla": invoice.layout,
            "escaneada": "sí" if invoice.scan else "no",
            "paginas": invoice.pages,
            "numero": invoice.number,
            "fecha": invoice.issue_date.isoformat(),
            "proveedor": invoice.supplier.name,
            "pais": invoice.supplier.country,
            "comprador": invoice.buyer.name,
            "moneda": invoice.currency,
            "incoterm": f"{invoice.incoterm} {invoice.incoterm_place}",
            "lineas": len(invoice.lines),
            "total": f"{invoice.total:.2f}",
            "total_eur": f"{invoice.total_eur:.2f}",
            "estado": "pending_review",
            "tipo_error": "",
            "comentario": "",
        })

        if index % 25 == 0 or index == args.count:
            elapsed = time.time() - started
            print(f"  {index}/{args.count} facturas · {elapsed:.0f} s", flush=True)

    jsonl = out / "ground_truth.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for payload in ground_truth:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    csv_path = out / "review_manifest.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[column for column, _ in COLUMNS])
        writer.writeheader()
        writer.writerows(rows)

    xlsx_path = out / "review_manifest.xlsx"
    _write_xlsx(xlsx_path, rows)

    summary = {
        "batch": args.batch,
        "seed": args.seed,
        "count": len(rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scan_share": round(sum(1 for row in rows if row["escaneada"] == "sí") / max(1, len(rows)), 3),
        "by_archetype": dict(Counter(row["tipo"] for row in rows)),
        "by_language": dict(Counter(row["idioma"] for row in rows)),
        "by_layout": dict(Counter(row["plantilla"] for row in rows)),
        "by_edge_case": dict(Counter(p["edge_case"] for p in ground_truth if p["edge_case"])),
        "currencies": dict(Counter(row["moneda"] for row in rows)),
        "total_pages": sum(row["paginas"] for row in rows),
        "review_status": {"pending_review": len(rows)},
    }
    (out / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    _write_guide(out / "GUIA_REVISION.md", args.batch, summary, rows)

    size_mb = sum(path.stat().st_size for path in pdf_dir.glob("*.pdf")) / 1e6
    print(f"\nLote {args.batch:02d}: {len(rows)} facturas en {out}")
    print(f"  PDF: {size_mb:.1f} MB · páginas: {summary['total_pages']} · "
          f"escaneadas: {summary['scan_share'] * 100:.0f} %")
    print(f"  Tipos: {summary['by_archetype']}")
    print(f"  Idiomas: {summary['by_language']}")
    print(f"  Revisión: {xlsx_path}")
    return 0


def _fmt_counts(counts: dict) -> str:
    return ", ".join(f"{key} {value}" for key, value in counts.items())


def _write_guide(path: Path, batch: int, summary: dict, rows: list[dict]) -> None:
    scan_docs = [row for row in rows if row["escaneada"] == "sí"]
    sample = ", ".join(row["doc_id"] for row in rows[:3])
    text = f"""# Guía de revisión — lote {batch:02d}

{summary['count']} facturas sintéticas de importación a la UE, pendientes de tu revisión
antes de usarlas para entrenar el LLM de mytarik.

Todos los datos son ficticios (empresas, direcciones, identificadores, números de
factura) y cada página lleva la marca **SPECIMEN**. Ningún documento es válido.

Composición del lote:

- Idiomas: {_fmt_counts(summary['by_language'])}
- Arquetipos: {_fmt_counts(summary['by_archetype'])}
- Monedas: {_fmt_counts(summary['currencies'])}
- Plantillas visuales: {len(summary['by_layout'])} de 25
- Escaneadas (sin texto embebido, como un escáner de oficina): {len(scan_docs)} de {summary['count']}
- Páginas totales: {summary['total_pages']}

## Archivos

| Ruta | Contenido |
| --- | --- |
| `pdf/` | La factura en PDF (`{sample}`, …) |
| `ground_truth/` | Datos exactos de cada factura en JSON |
| `ground_truth.jsonl` | Los mismos JSON, una línea por factura |
| `review_manifest.xlsx` | **Hoja de revisión** (empieza por aquí) |
| `review_manifest.csv` | La misma hoja en CSV |
| `validation/` | Comprobaciones automáticas previas (ver abajo) |
| `parser_check/` | Extracción del parser de la app contra el ground truth |
| `GUIA_REVISION.md` | Este documento |

## Cómo revisar

1. Abre `review_manifest.xlsx`. Cada fila es una factura; la columna `archivo`
   indica el PDF.
2. Abre el PDF y compáralo con lo que muestra la hoja. Si quieres ver el dato
   exacto que se espera (código TARIC de 10 dígitos, desglose de IVA, etc.),
   está en `ground_truth/<doc_id>.json`.
3. Rellena solo estas columnas:
   - `estado`: `ok` si la factura es correcta; `error` si algo no cuadra.
   - `tipo_error` (solo si `estado` = `error`): `importe`, `iva`, `descripcion`,
     `codigo_cn`, `identificador`, `formato` u `otro`.
   - `comentario`: explica el problema (p. ej. "la suma de importes no cuadra").
4. No cambies `doc_id` ni el resto de columnas: son la referencia para corregir
   y regenerar.

## Qué comprobar en cada factura

- **Líneas**: descripción legible, cantidad, unidad, precio e importe.
- **Código CN**: 8 dígitos coherentes con el producto (capítulo correcto); si
  aparece el TARIC de 10, que empiece por el CN y termine en una subpartida
  válida (`00` la mayoría de las veces).
- **Aritmética**: cantidad × precio = importe; suma de importes = valor de
  mercancía; base imponible + IVA = total.
- **IVA**: 0 % en importaciones (EXTRA_EU) con mención de importación/ISP;
  21 %, 10 % o 4 % en operaciones nacionales; el desglose por tipo cuadra con
  la base.
- **Pesos y bultos**: peso bruto ≥ neto por línea; la suma coincide con la
  cabecera de transporte.
- **Fechas**: entrega ≤ emisión ≤ vencimiento.
- **Partes**: exportador fuera de la UE / comprador español; EORI del
  importador (`ES` + NIF cuando es español).
- **Moneda**: si no es EUR debe verse el tipo de cambio y el total en EUR debe
  cuadrar.
- **Escaneadas**: que sigan siendo legibles (son fotos de escáner: ligeramente
  giradas, con ruido y marca de agua).
- **Marcas**: `SPECIMEN` visible en cada página.

## Comprobaciones automáticas ya hechas

`validation/issues.csv` (vacío si todo está bien) recoge errores internos:
sumas, IVA, TARIC contra el catálogo, identificadores, pesos, fechas y marca
SPECIMEN. `parser_check/parser_report.json` mide cuánto recupera el parser
actual de la app respecto al ground truth.

## Qué hago con tu revisión

- Filas `ok`: quedan como conjunto de entrenamiento/evaluación.
- Filas `error`: corrijo el generador, regenero esas facturas concretas y te las
  vuelvo a pasar.
- Cuando el lote esté aprobado, genero el lote 2 (otras 500) y el evaluador de
  precisión final del LLM.
"""
    path.write_text(text, encoding="utf-8")


def _write_xlsx(path: Path, rows: list[dict]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "revision"
    header_fill = PatternFill("solid", fgColor="1F3864")
    for column, (key, width) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=key)
        cell.font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[cell.column_letter].width = width
    for row_index, row in enumerate(rows, start=2):
        for column, (key, _) in enumerate(COLUMNS, start=1):
            sheet.cell(row=row_index, column=column, value=row[key])
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = f"A1:T{len(rows) + 1}"
    sheet.row_dimensions[1].height = 28

    status_validation = DataValidation(
        type="list", formula1='"pending_review,ok,error"', allow_blank=False,
        showDropDown=False, promptTitle="Estado de revisión",
        prompt="ok / error / pending_review",
    )
    error_validation = DataValidation(
        type="list",
        formula1='"ninguno,importe,iva,descripcion,codigo_cn,identificador,formato,otro"',
        allow_blank=True, promptTitle="Tipo de error",
    )
    sheet.add_data_validation(status_validation)
    sheet.add_data_validation(error_validation)
    status_validation.add(f"R2:R{len(rows) + 1}")
    error_validation.add(f"S2:S{len(rows) + 1}")
    book.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
