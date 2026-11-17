"""Parser offline de la Goods Nomenclature de TARIC.

No descarga datos ni consulta Qdrant. Convierte un XLSX oficial en una lista de
``GoodsEntry`` normalizados. Las columnas de entrada son las que publica la
Comisión Europea en ``Goods_Nomenclature_*.xlsx``:

    GOODS CODE, START_DATE, END_DATE, LANG_COD, HIER_POS, INDENTS,
    DESCR_TEXT, PUBLISH, DESCR_START_DATE, REC_SEQ_NUM
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from app.eu_taric.models import GoodsEntry

REQUIRED_COLUMNS = {
    "GOODS CODE",
    "START_DATE",
    "END_DATE",
    "LANG_COD",
    "HIER_POS",
    "INDENTS",
    "DESCR_TEXT",
    "DESCR_START_DATE",
}

_HEADER_ALIASES = {
    "GOODS CODE": {"GOODS CODE", "GOODS_CODE", "GOODSCODE", "CODE"},
    "START_DATE": {"START_DATE", "START DATE"},
    "END_DATE": {"END_DATE", "END DATE"},
    "LANG_COD": {"LANG_COD", "LANG", "LANGUAGE"},
    "HIER_POS": {"HIER_POS", "HIERARCHY", "HIERARCHY POSITION", "HIER. POS.", "HIER POS"},
    "INDENTS": {"INDENTS", "INDENT"},
    "DESCR_TEXT": {"DESCR_TEXT", "DESCRIPTION", "DESCR"},
    "PUBLISH": {"PUBLISH", "PUBLISHED"},
    "DESCR_START_DATE": {"DESCR_START_DATE", "DESCRIPTION START DATE", "DESCR. START DATE"},
    "REC_SEQ_NUM": {"REC_SEQ_NUM", "RECORD SEQUENCE", "SEQUENCE"},
}


def normalize_code(value: Any) -> str:
    """Devuelve solo los dígitos, conservando ceros a la izquierda."""
    if value is None:
        raise ValueError("GOODS CODE vacío")
    text = str(value).strip()
    # El export de CIRCABC añade un sufijo de dos dígitos separado por espacio
    # (p. ej. "6205200000 80"). El código arancelario es la primera parte.
    parts = text.split()
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isdigit() \
            and len("".join(ch for ch in parts[0] if ch.isdigit())) == 10:
        text = parts[0]
    # Los XLSX suelen guardar códigos como números; openpyxl puede devolver
    # 1012100.0. Se elimina la parte decimal solo si es .0.
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    # Excel guarda a veces el código como número y pierde el cero inicial.
    # En la nomenclatura EU, 7 dígitos corresponden a un CN8 y 9 a un TARIC10.
    if len(digits) == 7:
        digits = digits.zfill(8)
    elif len(digits) == 9:
        digits = digits.zfill(10)
    if len(digits) not in {2, 4, 6, 8, 10}:
        raise ValueError(f"código no válido: {value!r} (longitud {len(digits)})")
    return digits


def _parent_code(code: str) -> str | None:
    return code[:-2] if len(code) in {4, 6, 8, 10} else None


def _cn8_and_taric10(code: str) -> tuple[str | None, str | None]:
    if len(code) == 8:
        return code, None
    if len(code) == 10:
        return code[:8], code
    return None, None


def normalize_date(value: Any) -> str | None:
    """Normaliza fechas de Excel o texto a ISO ``YYYY-MM-DD``."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"fecha no válida: {value!r}")


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "s", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _column_map(headers: list[Any]) -> dict[str, int]:
    normalized = {str(h).strip().upper(): i for i, h in enumerate(headers) if h is not None}
    mapping: dict[str, int] = {}
    for canonical, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[canonical] = normalized[alias]
                break
    missing = REQUIRED_COLUMNS - set(mapping)
    if missing:
        raise ValueError(f"faltan columnas obligatorias: {sorted(missing)}")
    return mapping


def parse_goods_nomenclature_xlsx(path: str | Path) -> list[GoodsEntry]:
    """Lee un XLSX oficial y devuelve las filas normalizadas.

    No se descarga nada. El XLSX debe tener la hoja ``Goods_Nomenclature`` (o la
    primera hoja) con las columnas oficiales.
    """
    from openpyxl import load_workbook

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"no existe el XLSX: {file_path}")

    workbook = load_workbook(file_path, read_only=True, data_only=True)
    try:
        sheet = (
            workbook["Goods_Nomenclature"]
            if "Goods_Nomenclature" in workbook.sheetnames
            else workbook.active
        )
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = list(next(rows))
        except StopIteration as exc:
            raise ValueError("el XLSX está vacío") from exc
        columns = _column_map(headers)

        entries: list[GoodsEntry] = []
        for row_number, row in enumerate(rows, start=2):
            if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            try:
                code = normalize_code(row[columns["GOODS CODE"]])
                cn8, taric10 = _cn8_and_taric10(code)
                entries.append(
                    GoodsEntry(
                        code=code,
                        level=len(code),
                        description=str(row[columns["DESCR_TEXT"]] or "").strip(),
                        language=str(row[columns["LANG_COD"]] or "").strip() or None,
                        parent_code=_parent_code(code),
                        cn8=cn8,
                        taric10=taric10,
                        start_date=normalize_date(row[columns["START_DATE"]]),
                        end_date=normalize_date(row[columns["END_DATE"]]),
                        description_start_date=normalize_date(
                            row[columns["DESCR_START_DATE"]]
                        ),
                        hierarchy_position=str(row[columns["HIER_POS"]] or "").strip()
                        or None,
                        indent=_as_int(row[columns["INDENTS"]]),
                        published=_as_bool(row[columns["PUBLISH"]]) if "PUBLISH" in columns else None,
                        sequence_number=_as_int(row[columns["REC_SEQ_NUM"]]) if "REC_SEQ_NUM" in columns else None,
                    )
                )
            except Exception as exc:
                raise ValueError(f"fila {row_number}: {exc}") from exc
        return entries
    finally:
        workbook.close()
