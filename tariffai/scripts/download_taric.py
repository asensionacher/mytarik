#!/usr/bin/env python3
"""Download official TARIC/CN extracts and inventory their sheets.

The European Commission exposes:
  * daily TARIC extracts on the public TARIC consultation site
  * the full TARIC database through CIRCABC

CIRCABC requires an authenticated browser session for the full database; it is
not an anonymous HTML scrape. This script downloads the public daily extract
and accepts a full CIRCABC ZIP downloaded once by the operator. It never
invents codes and never falls back to a different catalogue.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

import requests

DAILY_PAGE = "https://ec.europa.eu/taxation_customs/dds2/taric/daily_publications.jsp?Lang=en"
FULL_LIBRARY = (
    "https://circabc.europa.eu/ui/group/0e5f18c2-4b2f-42e9-aed4-dfe50ae1263b/"
    "library/64db9d0f-e7c9-4084-afe9-f47e70e53c10?p=1&n=-1&sort=name_ASC"
)
LINK_RE = re.compile(
    r"https://ec\.europa\.eu/taxation_customs/dds2/taric/"
    r"taric_management\.jsp\?publicationDate=[^\"']+&message=extract"
)
EXPECTED = (
    "Goods_Nomenclature_",
    "Measures_",
    "Measure_Conditions_",
    "Add_Codes_",
    "Certificates_",
    "Footnotes_",
)


def latest_daily_url(session: requests.Session) -> str:
    response = session.get(DAILY_PAGE, timeout=60)
    response.raise_for_status()
    links = LINK_RE.findall(response.text)
    if not links:
        raise RuntimeError("No TARIC daily extract link found")
    return links[0]


def download_daily(out: Path, date: str | None = None) -> Path:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mytarik-TARIC/1.0"})
    page = session.get(DAILY_PAGE, timeout=60)
    page.raise_for_status()
    url = latest_daily_url(session)
    if date:
        url = re.sub(r"publicationDate=[^&]+", f"publicationDate={date}", url)
    response = session.get(url, headers={"Referer": DAILY_PAGE}, timeout=180)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise RuntimeError(f"TARIC daily extract is not a ZIP: {response.headers.get('content-type')}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.content)
    print(f"Downloaded {out} ({out.stat().st_size} bytes)")
    return out


def inventory(zip_path: Path) -> None:
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(f"Not a ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for name in names:
            print(f"  {name}")
        missing = [prefix for prefix in EXPECTED if not any(name.startswith(prefix) for name in names)]
    if missing:
        print(f"WARNING: missing expected sheets: {missing}", file=sys.stderr)
    else:
        print("All expected TARIC sheets are present.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", action="store_true", help="Download the latest public daily extract")
    parser.add_argument("--date", help="Optional daily publicationDate, e.g. '2026-11-13 19:14'")
    parser.add_argument("--full-zip", type=Path, help="Full CIRCABC TARIC ZIP downloaded by the operator")
    parser.add_argument("--out", type=Path, default=Path("/home/seby/taric/latest_daily.zip"))
    args = parser.parse_args(argv)

    if args.daily:
        path = download_daily(args.out, args.date)
        inventory(path)
        return 0

    if args.full_zip:
        inventory(args.full_zip)
        print(f"Full database: {args.full_zip}")
        print(f"CIRCABC source: {FULL_LIBRARY}")
        return 0

    parser.print_help()
    print("\nFull database: download the CIRCABC ZIP once (EU Login/browser session) and pass --full-zip.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
