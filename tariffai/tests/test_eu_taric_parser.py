import sys
from pathlib import Path

import pytest

if "dotenv" not in sys.modules:
    from types import ModuleType

    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eu_taric import normalize_code, normalize_date, parse_goods_nomenclature_xlsx
from app.eu_taric.models import GoodsEntry

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "taric_goods_sample.xlsx"


def test_parse_official_headers_and_codes():
    entries = parse_goods_nomenclature_xlsx(FIXTURE)
    assert len(entries) >= 6

    by_code = {entry.code: entry for entry in entries}
    cn8 = by_code["62052000"]
    assert cn8.cn8 == "62052000"
    assert cn8.taric10 is None
    assert cn8.level == 8
    assert cn8.parent_code == "620520"
    assert cn8.language == "EN"
    assert cn8.start_date == "2026-01-01"
    assert cn8.end_date == "2026-12-31"

    taric = by_code["6205200000"]
    assert taric.cn8 == "62052000"
    assert taric.taric10 == "6205200000"
    assert taric.level == 10
    assert taric.parent_code == "62052000"
    assert taric.description.startswith("Men's or boys'")


def test_leading_zeros_are_preserved():
    entries = parse_goods_nomenclature_xlsx(FIXTURE)
    entry = next(e for e in entries if e.code == "01012100")
    assert entry.code == "01012100"
    assert entry.cn8 == "01012100"
    assert entry.code.startswith("0")


def test_published_boolean():
    entries = parse_goods_nomenclature_xlsx(FIXTURE)
    by_code = {entry.code: entry for entry in entries}
    assert by_code["62052000"].published is True
    assert by_code["85111000"].published is False


def test_normalize_code_accepts_excel_float():
    assert normalize_code(1012100.0) == "01012100"
    assert normalize_code(" 6205 20 00 ") == "62052000"


def test_normalize_code_rejects_invalid_length():
    with pytest.raises(ValueError, match="código no válido"):
        normalize_code("12345")


def test_normalize_date_formats():
    assert normalize_date("2026-01-01") == "2026-01-01"
    assert normalize_date("01/01/2026") == "2026-01-01"
    assert normalize_date(None) is None
    with pytest.raises(ValueError, match="fecha no válida"):
        normalize_date("not-a-date")


def test_missing_required_header_raises(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Goods_Nomenclature"
    ws.append(["GOODS CODE", "DESCR_TEXT"])
    ws.append(["62052000", "shirts"])
    path = tmp_path / "missing.xlsx"
    wb.save(path)

    with pytest.raises(ValueError, match="faltan columnas obligatorias"):
        parse_goods_nomenclature_xlsx(path)


def test_invalid_code_reports_row(tmp_path):
    from openpyxl import Workbook

    headers = [
        "GOODS CODE", "START_DATE", "END_DATE", "LANG_COD", "HIER_POS",
        "INDENTS", "DESCR_TEXT", "PUBLISH", "DESCR_START_DATE", "REC_SEQ_NUM",
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Goods_Nomenclature"
    ws.append(headers)
    ws.append(["12345", "2026-01-01", "2026-12-31", "EN", "", 0, "bad", 1, "2026-01-01", 1])
    path = tmp_path / "bad.xlsx"
    wb.save(path)

    with pytest.raises(ValueError, match="fila 2"):
        parse_goods_nomenclature_xlsx(path)
