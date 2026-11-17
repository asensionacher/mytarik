import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ingest_ebti import iter_records, parse_code, parse_row

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ebti_sample.csv"


def _zip_fixture(tmp_path: Path) -> Path:
    archive = tmp_path / "ebti_sample.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(FIXTURE, "EBTI_2026.csv")
    return archive


def test_parse_code_8_and_10_digits():
    assert parse_code("62052000") == ("62052000", None)
    assert parse_code("6205200000************") == ("62052000", "6205200000")
    assert parse_code("123456789") is None
    assert parse_code("not-a-code") is None


def test_parse_row_fields():
    import csv

    with FIXTURE.open(encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    record = parse_row(row)
    assert record is not None
    assert record.reference == "DEBTI-DE-2026-0001"
    assert record.cn8 == "62052000"
    assert record.taric10 == "6205200000"
    assert record.status == "VALID"
    assert record.start_date == "2026-02-01"


def test_filters_valid_and_eu_by_default(tmp_path):
    records = list(iter_records(_zip_fixture(tmp_path)))
    assert [record.reference for record in records] == [
        "DEBTI-DE-2026-0001",
        "ESBTI-ES-2026-0002",
    ]


def test_can_include_invalid_and_non_eu(tmp_path):
    records = list(
        iter_records(
            _zip_fixture(tmp_path),
            valid_only=False,
            eu_only=False,
        )
    )
    assert len(records) == 4
    assert {record.reference for record in records} == {
        "DEBTI-DE-2026-0001",
        "ESBTI-ES-2026-0002",
        "FRBTI-FR-2026-0003",
        "GBBTI-GB-2020-0004",
    }
