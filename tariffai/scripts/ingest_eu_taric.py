from __future__ import annotations

import argparse
import sys
import time

from app.eu_taric import GoodsEntry, parse_goods_nomenclature_xlsx

OPERATIVE_PAYLOAD_KEYS = {
    "cn8",
    "taric10",
    "description",
    "language",
    "start_date",
    "end_date",
    "description_start_date",
    "hierarchy_position",
    "parent_code",
    "level",
}


def to_payload(entry: GoodsEntry) -> dict:
    code = str(entry.cn8 or entry.taric10 or "")
    return {
        "cn8": entry.cn8,
        "taric10": entry.taric10,
        "chapter": code[:2] if len(code) >= 2 else "",
        "heading": code[:4] if len(code) >= 4 else "",
        "subheading": code[:6] if len(code) >= 6 else "",
        "description": entry.description,
        "language": entry.language,
        "start_date": entry.start_date,
        "end_date": entry.end_date,
        "description_start_date": entry.description_start_date,
        "hierarchy_position": entry.hierarchy_position,
        "parent_code": entry.parent_code,
        "level": entry.level,
    }


def is_operative(entry: GoodsEntry) -> bool:
    return entry.cn8 is not None or entry.taric10 is not None


def summarize(entries: list[GoodsEntry]) -> dict:
    operative = [entry for entry in entries if is_operative(entry)]
    return {
        "total_rows": len(entries),
        "operative_rows": len(operative),
        "cn8_rows": sum(1 for entry in operative if entry.cn8 is not None),
        "taric10_rows": sum(1 for entry in operative if entry.taric10 is not None),
        "levels": {level: sum(1 for entry in operative if entry.level == level) for level in (8, 10)},
        "languages": sorted({entry.language for entry in operative}),
    }


def print_summary(summary: dict) -> None:
    print(
        "Dry-run summary for EU TARIC Goods Nomenclature ingest:\n"
        f"  total rows: {summary['total_rows']}\n"
        f"  operative rows: {summary['operative_rows']}\n"
        f"  CN8 rows: {summary['cn8_rows']}\n"
        f"  TARIC10 rows: {summary['taric10_rows']}\n"
        f"  levels: {summary['levels']}\n"
        f"  languages: {', '.join(summary['languages']) or 'n/a'}"
    )


COUNT_VERIFY_ATTEMPTS = 10
COUNT_VERIFY_INTERVAL_SECONDS = 0.2


def _count_value(result) -> int:
    """Qdrant devuelve CountResult(count=N), no un entero."""
    value = getattr(result, "count", result)
    return int(value)


def verify_count(
    client,
    collection: str,
    total: int,
    *,
    recreate: bool,
    attempts: int = COUNT_VERIFY_ATTEMPTS,
    interval: float = COUNT_VERIFY_INTERVAL_SECONDS,
) -> int:
    def matches(count: int) -> bool:
        if not recreate and client.collection_exists(collection):
            return count >= total
        return count == total

    count = _count_value(client.count(collection, exact=True))
    for _ in range(attempts):
        if matches(count):
            return count
        time.sleep(interval)
        count = _count_value(client.count(collection, exact=True))

    if not matches(count):
        if not recreate and client.collection_exists(collection):
            raise SystemExit(f"Qdrant collection {collection!r} has fewer points than ingested ({count} < {total}).")
        raise SystemExit(f"Qdrant collection {collection!r} count mismatch after ingest: {count} != {total}.")
    return count


def ingest(
    *,
    xlsx_path: str,
    collection: str,
    recreate: bool,
    batch_size: int,
) -> int:
    from app.config import EMBEDDING_DIM, EMBEDDING_MODEL, QDRANT_HOST, QDRANT_PORT
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    from sentence_transformers import SentenceTransformer

    entries = parse_goods_nomenclature_xlsx(xlsx_path)
    operative = [entry for entry in entries if is_operative(entry)]
    payload_entries = [entry for entry in operative]
    payload_dicts = [to_payload(entry) for entry in payload_entries]

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    if client.collection_exists(collection):
        if recreate:
            client.delete_collection(collection)
            client.recreate_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
        else:
            print(f"Collection {collection!r} exists; reusing it.")
    else:
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )

    model = SentenceTransformer(EMBEDDING_MODEL)

    points = []
    for start in range(0, len(payload_dicts), batch_size):
        chunk = payload_entries[start : start + batch_size]
        texts = [f"passage: {entry.description}" for entry in chunk]
        vectors = model.encode(texts, normalize_embeddings=True)
        for offset, (entry, payload, vector) in enumerate(zip(chunk, payload_dicts[start : start + batch_size], vectors)):
            points.append(
                PointStruct(
                    id=start + offset,
                    vector=list(map(float, vector)),
                    payload=payload,
                )
            )
        client.upload_points(collection, points)
        points = []

    total = len(payload_dicts)
    verify_count(client, collection, total, recreate=recreate)

    print(f"Ingested {total} EU TARIC entries into collection {collection!r}.")
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest EU TARIC Goods Nomenclature into Qdrant.")
    parser.add_argument("--xlsx", required=True, help="Path to the official EU TARIC Goods Nomenclature XLSX.")
    parser.add_argument("--collection", default="eu_taric", help="Qdrant collection to create/update. Default: eu_taric.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate only the selected collection.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Parse and print a summary without writing to Qdrant.")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size for embeddings/uploads.")
    args = parser.parse_args(argv)

    if args.collection == "hs_codes":
        raise SystemExit("Refusing to touch hs_codes collection. Use the HS ingest flow for hs_codes.")

    entries = parse_goods_nomenclature_xlsx(args.xlsx)
    if args.dry_run:
        print_summary(summarize(entries))
        return 0

    ingest(
        xlsx_path=args.xlsx,
        collection=args.collection,
        recreate=args.recreate,
        batch_size=args.batch_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
