#!/usr/bin/env python3
"""Ingest the official EBTI export into a dedicated Qdrant collection.

EBTI is the EU's public database of Binding Tariff Information decisions. The
European Commission publishes a full ZIP (one CSV per year) and a daily update.
This script deliberately consumes that official CSV export instead of scraping
the HTML search UI.

EBTI is supporting case law, not the TARIC nomenclature. It must not be used as
the authoritative candidate catalogue for the EU classifier; keep it in its own
collection (default: ``ebti_decisions``).

Usage:
    python -m scripts.ingest_ebti --zip /home/seby/ebti/ebti_full.zip --dry-run
    python -m scripts.ingest_ebti --zip /home/seby/ebti/ebti_full.zip --limit 100
    python -m scripts.ingest_ebti --download --recreate
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

EBTI_FULL_URL = (
    "https://ec.europa.eu/taxation_customs/dds2/ebti/"
    "ebti_export_management.jsp?message=extractFull"
)
EBTI_SOURCE = "https://ec.europa.eu/taxation_customs/dds2/ebti/"
DEFAULT_ZIP = Path("/home/seby/ebti/ebti_full.zip")
DEFAULT_COLLECTION = "ebti_decisions"

# Current EU member states. Historical UK (GB) decisions are excluded by default.
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}
CODE_RE = re.compile(r"^(\d{8,10})")


@dataclass(frozen=True)
class EBTIRecord:
    reference: str
    issuing_country: str
    cn8: str
    taric10: str | None
    nomenclature_code: str
    description: str
    justification: str
    keywords: str
    status: str
    language: str
    start_date: str | None
    end_date: str | None
    date_of_issue: str | None
    invalidation_reason: str


def clean(value: object, *, limit: int = 12000) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\x00", " ").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_date(value: object) -> str | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_code(value: object) -> tuple[str, str | None] | None:
    raw = clean(value)
    match = CODE_RE.match(raw)
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 9:
        return None
    cn8 = digits[:8]
    taric10 = digits if len(digits) == 10 else None
    return cn8, taric10


def parse_row(row: dict[str, str]) -> EBTIRecord | None:
    reference = clean(row.get("BTI_REFERENCE"))
    code = parse_code(row.get("NOMENCLATURE_CODE"))
    if not reference or code is None:
        return None
    cn8, taric10 = code
    status = clean(row.get("STATUS")).upper() or "UNKNOWN"
    country = clean(row.get("ISSUING_COUNTRY")).upper()
    return EBTIRecord(
        reference=reference,
        issuing_country=country,
        cn8=cn8,
        taric10=taric10,
        nomenclature_code=clean(row.get("NOMENCLATURE_CODE")),
        description=clean(row.get("DESCRIPTION_OF_GOODS")),
        justification=clean(row.get("CLASSIFICATION_JUSTIFICATION")),
        keywords=clean(row.get("KEYWORDS")),
        status=status,
        language=clean(row.get("LANGUAGE")).lower(),
        start_date=parse_date(row.get("START_DATE_OF_VALIDITY")),
        end_date=parse_date(row.get("END_DATE_OF_VALIDITY")),
        date_of_issue=parse_date(row.get("DATE_OF _ISSUE")),
        invalidation_reason=clean(row.get("INVALIDATION_REASON")),
    )


def iter_records(
    zip_path: Path,
    *,
    valid_only: bool = True,
    eu_only: bool = True,
    since: str | None = None,
    limit: int | None = None,
    skip_refs: set[str] | None = None,
) -> Iterator[EBTIRecord]:
    seen: set[str] = set(skip_refs or ())
    emitted = 0
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist() if name.lower().endswith(".csv"))
        for name in names:
            with archive.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                for row in csv.DictReader(text):
                    # Filter on cheap raw fields before normalizing the large
                    # justification/description columns.
                    reference = clean(row.get("BTI_REFERENCE"))
                    if not reference or reference in seen:
                        continue
                    status = clean(row.get("STATUS")).upper() or "UNKNOWN"
                    country = clean(row.get("ISSUING_COUNTRY")).upper()
                    if valid_only and status != "VALID":
                        continue
                    if eu_only and country not in EU_COUNTRIES:
                        continue
                    record = parse_row(row)
                    if record is None:
                        continue
                    if since and (record.start_date or record.date_of_issue or "") < since:
                        continue
                    seen.add(reference)
                    yield record
                    emitted += 1
                    if limit is not None and emitted >= limit:
                        return


def dry_run(
    zip_path: Path,
    *,
    valid_only: bool,
    eu_only: bool,
    since: str | None,
    limit: int | None,
) -> int:
    counts: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    lengths: Counter[int] = Counter()
    for record in iter_records(
        zip_path,
        valid_only=valid_only,
        eu_only=eu_only,
        since=since,
        limit=limit,
        skip_refs=existing_refs,
    ):
        counts["records"] += 1
        countries[record.issuing_country] += 1
        lengths[10 if record.taric10 else 8] += 1
    print(f"EBTI records: {counts['records']}")
    print(f"Code lengths: {dict(lengths)}")
    print(f"Countries: {dict(countries.most_common(30))}")
    return 0


def download(zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_suffix(zip_path.suffix + ".part")
    request = urllib.request.Request(
        EBTI_FULL_URL,
        headers={"User-Agent": "Mytarik-EBTI-ingest/1.0"},
    )
    print(f"Downloading official EBTI export to {tmp} ...", flush=True)
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(zip_path)
    print(f"Downloaded {zip_path} ({zip_path.stat().st_size} bytes)")


def embed_text(record: EBTIRecord) -> str:
    return (
        f"passage: EBTI {record.reference} | {record.description} | "
        f"{record.justification[:4000]} | keywords: {record.keywords[:500]}"
    )


def ingest(
    zip_path: Path,
    *,
    collection: str,
    recreate: bool,
    resume: bool,
    valid_only: bool,
    eu_only: bool,
    since: str | None,
    limit: int | None,
    batch_size: int,
) -> int:
    from app.config import EMBEDDING_DIM, EMBEDDING_MODEL, QDRANT_HOST, QDRANT_PORT
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    from sentence_transformers import SentenceTransformer

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60.0)
    existing_refs: set[str] = set()
    if client.collection_exists(collection):
        if not recreate and not resume:
            print(
                f"Collection {collection!r} already exists; use --resume or --recreate.",
                file=sys.stderr,
            )
            return 1
        if recreate:
            client.delete_collection(collection)
        else:
            offset = None
            while True:
                points, offset = client.scroll(
                    collection_name=collection,
                    limit=1000,
                    offset=offset,
                    with_payload=["reference"],
                    with_vectors=False,
                )
                existing_refs.update(
                    point.payload.get("reference")
                    for point in points
                    if point.payload and point.payload.get("reference")
                )
                if offset is None:
                    break
            print(f"Resume: {len(existing_refs)} EBTI references already present.", flush=True)
    if not client.collection_exists(collection):
        client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

    model = SentenceTransformer(EMBEDDING_MODEL)
    total = 0
    batch: list[EBTIRecord] = []

    def flush() -> None:
        nonlocal total
        if not batch:
            return
        texts = [embed_text(record) for record in batch]
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=len(texts))
        points = [
            PointStruct(
                id=uuid.uuid5(uuid.NAMESPACE_URL, record.reference),
                vector=list(map(float, vector)),
                payload={
                    "reference": record.reference,
                    "issuing_country": record.issuing_country,
                    "cn8": record.cn8,
                    "taric10": record.taric10,
                    "nomenclature_code": record.nomenclature_code,
                    "description": record.description,
                    "justification": record.justification,
                    "keywords": record.keywords,
                    "status": record.status,
                    "language": record.language,
                    "start_date": record.start_date,
                    "end_date": record.end_date,
                    "date_of_issue": record.date_of_issue,
                    "invalidation_reason": record.invalidation_reason,
                    "source": "EBTI",
                    "source_url": EBTI_SOURCE,
                },
            )
            for record, vector in zip(batch, vectors)
        ]
        client.upload_points(collection, points)
        total += len(points)
        print(f"  ingested {total}", flush=True)
        batch.clear()

    for record in iter_records(
        zip_path,
        valid_only=valid_only,
        eu_only=eu_only,
        since=since,
        limit=limit,
        skip_refs=existing_refs,
    ):
        batch.append(record)
        if len(batch) >= batch_size:
            flush()
    flush()

    info = client.get_collection(collection)
    print(f"Ingested {total} EBTI decisions into {collection!r} (points={info.points_count}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP, help="Official EBTI ZIP")
    parser.add_argument("--download", action="store_true", help="Download the official ZIP first")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Continue an existing collection, skipping loaded references")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-invalid", action="store_true")
    parser.add_argument(
        "--include-non-eu",
        action="store_true",
        help="Include historical non-EU issuing countries such as GB",
    )
    parser.add_argument("--since", default=None, help="YYYY-MM-DD start date filter")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.download or not args.zip.exists():
        download(args.zip)
    if not zipfile.is_zipfile(args.zip):
        print(f"Not a ZIP archive: {args.zip}", file=sys.stderr)
        return 2
    if args.dry_run:
        return dry_run(
            args.zip,
            valid_only=not args.include_invalid,
            eu_only=not args.include_non_eu,
            since=args.since,
            limit=args.limit,
        )
    return ingest(
        args.zip,
        collection=args.collection,
        recreate=args.recreate,
        resume=args.resume,
        valid_only=not args.include_invalid,
        eu_only=not args.include_non_eu,
        since=args.since,
        limit=args.limit,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    raise SystemExit(main())
