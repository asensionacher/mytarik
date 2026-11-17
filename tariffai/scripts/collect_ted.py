#!/usr/bin/env python3
"""Collect public TED procurement notices for every EU member state.

TED is the EU's official public procurement journal. This collector uses its
public, keyless search API, downloads only public notice documents, records a
manifest with checksum/provenance, and never uses authentication.

It does NOT collect private invoices, personal data, or documents behind a
login. Public procurement notices are not customs invoices; they are useful
for document layout/OCR and for building a legally sourced corpus.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

API = "https://api.ted.europa.eu/v3/notices/search"
OUT = Path("/home/seby/mytarik/data/public/ted")
MANIFEST = OUT / "manifest.jsonl"

COUNTRIES = {
    "AUT": "Austria", "BEL": "Belgium", "BGR": "Bulgaria", "HRV": "Croatia",
    "CYP": "Cyprus", "CZE": "Czechia", "DNK": "Denmark", "EST": "Estonia",
    "FIN": "Finland", "FRA": "France", "DEU": "Germany", "GRC": "Greece",
    "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "LVA": "Latvia",
    "LTU": "Lithuania", "LUX": "Luxembourg", "MLT": "Malta", "NLD": "Netherlands",
    "POL": "Poland", "PRT": "Portugal", "ROU": "Romania", "SVK": "Slovakia",
    "SVN": "Slovenia", "ESP": "Spain", "SWE": "Sweden",
}

LICENSE = "TED open data / European Union — verify TED legal notice before reuse"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def search(country: str, limit: int) -> list[dict[str, Any]]:
    payload = {
        "query": f"buyer-country={country} AND PD>=20250101 SORT BY publication-date DESC",
        "fields": [
            "publication-number", "notice-title", "notice-type",
            "buyer-country", "buyer-name", "links",
        ],
        "limit": limit,
        "scope": "ALL",
        "paginationMode": "PAGE_NUMBER",
    }
    response = requests.post(API, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("notices", [])[:limit]


def download(url: str, target: Path) -> bool:
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        if not response.content:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return True
    except Exception as exc:
        print(f"  ! {url}: {exc}")
        return False


def record(
    country: str,
    notice: dict[str, Any],
    kind: str,
    url: str,
    path: Path,
    notice_title: dict[str, Any] | None,
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    title = None
    if isinstance(notice_title, dict):
        for lang in ("ENG", "eng", "SPA", "FRA", "DEU"):
            value = notice_title.get(lang)
            if value:
                title = value[0] if isinstance(value, list) else value
                break
    row = {
        "source": "TED",
        "country": country,
        "country_name": COUNTRIES[country],
        "publication_number": notice.get("publication-number"),
        "notice_type": notice.get("notice-type"),
        "title": title,
        "kind": kind,
        "url": url,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "license": LICENSE,
        "type": "procurement_notice",
        "pii": "unknown",
        "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-per-country", type=int, default=1)
    parser.add_argument("--countries", default="", help="Comma-separated ISO3 codes")
    args = parser.parse_args()
    selected = [code.strip().upper() for code in args.countries.split(",") if code.strip()] or list(COUNTRIES)
    OUT.mkdir(parents=True, exist_ok=True)

    for code in selected:
        if code not in COUNTRIES:
            print(f"skip unknown country {code}")
            continue
        print(f"[{code}] {COUNTRIES[code]}")
        try:
            notices = search(code, args.limit_per_country)
        except Exception as exc:
            print(f"  search failed: {exc}")
            continue
        for notice in notices:
            number = notice.get("publication-number", "unknown")
            links = notice.get("links") or {}
            xml = (links.get("xml") or {}).get("MUL")
            pdfs = links.get("pdf") or {}
            pdf = pdfs.get("ENG") or next(iter(pdfs.values()), None)
            if xml:
                path = OUT / code / f"{number}.xml"
                if download(xml, path):
                    record(code, notice, "xml", xml, path, notice.get("notice-title"))
                    print(f"  xml {number}")
            if pdf:
                path = OUT / code / f"{number}.pdf"
                if download(pdf, path):
                    record(code, notice, "pdf", pdf, path, notice.get("notice-title"))
                    print(f"  pdf {number}")
            time.sleep(0.5)
        time.sleep(0.5)
    print(f"Manifest: {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
