"""Orchestrate download -> text extraction -> TARIC code parsing -> JSONL."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from crawler import main as crawl_main
from extractor import extract_text_from_pdf
from webapp.backend.app.exporter import ExportResult, export_to_jsonl
from webapp.backend.app.parser import extract_taric_codes


async def orchestrate(urls: list[str], download_dir: str, output_file: str, concurrency_limit: int = 1) -> int:
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    downloaded = await crawl_main(urls, download_dir, concurrency_limit)
    manifest_path = Path(download_dir) / "download_manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as manifest:
        for item in downloaded:
            manifest.write(json.dumps(item, ensure_ascii=False) + "\n")
    records = []
    for item in downloaded:
        text = extract_text_from_pdf(item["path"])
        for parsed in extract_taric_codes(text):
            records.append({
                "source_url": item["url"],
                "pdf_path": item["path"],
                "input": parsed.input,
                "output": parsed.output,
            })
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with Path(output_file).open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: main.py <download_dir> <output.jsonl> <url> [url ...]")
        raise SystemExit(2)
    count = asyncio.run(orchestrate(sys.argv[3:], sys.argv[1], sys.argv[2]))
    print(f"{count} TARIC matches -> {sys.argv[2]}")
