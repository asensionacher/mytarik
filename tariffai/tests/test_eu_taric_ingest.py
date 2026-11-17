import sys
from pathlib import Path

import pytest

if "dotenv" not in sys.modules:
    from types import ModuleType

    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eu_taric import GoodsEntry, parse_goods_nomenclature_xlsx
from scripts.ingest_eu_taric import is_operative, main, summarize, to_payload, verify_count

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "taric_goods_sample.xlsx")


def _operative_fixture_entries():
    entries = parse_goods_nomenclature_xlsx(FIXTURE)
    return [entry for entry in entries if is_operative(entry)]


def test_to_payload_excludes_hs6():
    entry = _operative_fixture_entries()[0]
    payload = to_payload(entry)
    assert "hs6" not in payload


def test_to_payload_includes_required_keys():
    entry = _operative_fixture_entries()[0]
    payload = to_payload(entry)
    for key in ("cn8", "taric10", "description", "level", "parent_code"):
        assert key in payload


def test_is_operative_accepts_cn8_and_taric10():
    entries = parse_goods_nomenclature_xlsx(FIXTURE)
    by_code = {entry.code: entry for entry in entries}
    cn8_only = by_code["62052000"]
    assert cn8_only.cn8 is not None
    assert cn8_only.taric10 is None
    assert is_operative(cn8_only)

    taric = by_code["6205200000"]
    assert taric.taric10 is not None
    assert is_operative(taric)


def test_summarize_counts_six_operative_rows():
    entries = parse_goods_nomenclature_xlsx(FIXTURE)
    assert summarize(entries)["operative_rows"] == 6


def test_dry_run_returns_zero():
    assert main(["--xlsx", FIXTURE, "--dry-run"]) == 0


def test_collection_hs_codes_guard():
    with pytest.raises(SystemExit):
        main(["--xlsx", FIXTURE, "--collection", "hs_codes"])


def test_dry_run_does_not_import_qdrant_client():
    assert main(["--xlsx", FIXTURE, "--dry-run"]) == 0
    assert "qdrant_client" not in sys.modules


class _LaggingCountClient:
    def __init__(self, total, lag, *, final=None):
        self.total = total
        self.lag = lag
        self.final = total if final is None else final
        self.calls = 0

    def collection_exists(self, collection):
        return True

    def count(self, collection, exact=False):
        self.calls += 1
        return self.final if self.calls > self.lag else self.final - 1


def test_count_verification_retries_until_qdrant_reflects_points():
    client = _LaggingCountClient(total=6, lag=3)
    assert verify_count(client, "eu_taric", 6, recreate=False, interval=0.0) == 6


def test_count_verification_raises_when_count_stays_wrong():
    client = _LaggingCountClient(total=6, lag=999)
    with pytest.raises(SystemExit, match="fewer points"):
        verify_count(client, "eu_taric", 6, recreate=False, interval=0.0)


class _CountResult:
    def __init__(self, count):
        self.count = count


class _CountResultClient:
    def collection_exists(self, collection):
        return True

    def count(self, collection, exact=False):
        return _CountResult(6)


def test_count_verification_accepts_qdrant_count_result():
    assert verify_count(
        _CountResultClient(), "eu_taric", 6, recreate=True, interval=0.0
    ) == 6
