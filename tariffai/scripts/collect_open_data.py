#!/usr/bin/env python3
"""Collect public invoice/payment datasets from national open-data portals.

Only public catalogue APIs are used. The collector records dataset metadata and
downloads resources whose declared format is PDF/CSV/XLSX/ZIP. It does not log
in, bypass paywalls, or fetch private invoices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path("/home/seby/mytarik/data/public/transparency")
MANIFEST = OUT / "manifest.jsonl"
UA = "Mytarik-public-corpus/1.0"

SOURCES = {
    "FRA": {
        "api": "https://www.data.gouv.fr/api/1/datasets/",
        "params": {"q": "factures", "page_size": 20},
        "kind": "datagouv",
    },
    "PRT": {
        "api": "https://dados.gov.pt/api/1/datasets/",
        "params": {"q": "faturas", "page_size": 20},
        "kind": "ckan",
    },
    "ITA": {
        "api": "https://www.dati.gov.it/opendata/api/3/action/package_search",
        "params": {"q": "fatture", "rows": 20},
        "kind": "ckan",
    },
    "ESP": {
        "api": "https://datos.gob.es/apidata/catalog/dataset",
        "params": {"q": "facturas", "_pageSize": 20},
        "kind": "datosgob",
    },
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record(source: str, dataset: dict, resource: dict, path: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    row = {
        "source": source,
        "dataset": dataset.get("title") or dataset.get("name"),
        "dataset_url": dataset.get("url") or dataset.get("uri"),
        "license": dataset.get("license") or dataset.get("license_title"),
        "resource_title": resource.get("title") or resource.get("name"),
        "resource_url": resource.get("url"),
        "format": resource.get("format"),
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": digest(path.read_bytes()),
        "type": "public_invoice_or_payment_dataset",
        "pii": "unknown",
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    with MANIFEST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def datasets(source: str, config: dict) -> list[dict]:
    response = requests.get(config["api"], params=config["params"], headers={"User-Agent": UA}, timeout=45)
    response.raise_for_status()
    data = response.json()
    if config["kind"] == "ckan":
        return data.get("result", {}).get("results", [])
    if config["kind"] == "datagouv":
        return data.get("data", [])
    # datos.gob.es: dataset entries are under result.items
    return data.get("result", {}).get("items", []) or data.get("items", [])


def resources(dataset: dict, kind: str) -> list[dict]:
    if kind == "datagouv":
        return dataset.get("resources", [])
    if kind == "ckan":
        return dataset.get("resources", [])
    # datos.gob.es distributions
    out = []
    for dist in dataset.get("distribution", []) or []:
        out.append({"url": dist.get("accessURL"), "format": dist.get("format"), "title": dist.get("title")})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--countries", default="FRA,PRT,ITA")
    parser.add_argument("--max-datasets", type=int, default=5)
    parser.add_argument("--max-resources", type=int, default=3)
    args = parser.parse_args()
    selected = [x.strip().upper() for x in args.countries.split(",") if x.strip()]
    for code in selected:
        if code not in SOURCES:
            print(f"skip {code}")
            continue
        config = SOURCES[code]
        print(f"[{code}] {config['api']}")
        try:
            items = datasets(code, config)
        except Exception as exc:
            print(f"  ! {exc}")
            continue
        print(f"  datasets={len(items)}")
        for dataset in items[: args.max_datasets]:
            for resource in resources(dataset, config["kind"])[: args.max_resources]:
                url = resource.get("url") or resource.get("accessURL")
                if not url:
                    continue
                fmt = (resource.get("format") or "").upper()
                if fmt not in {"PDF", "CSV", "XLSX", "XLS", "ZIP"}:
                    continue
                try:
                    response = requests.get(url, headers={"User-Agent": UA}, timeout=60)
                    response.raise_for_status()
                    if len(response.content) > 50 * 1024 * 1024:
                        print(f"  skip large {url}")
                        continue
                    target = OUT / code / f"{len(list((OUT / code).glob('*'))) + 1:05d}{Path(url.split('?')[0]).suffix or '.bin'}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(response.content)
                    record(code, dataset, resource, target)
                    print(f"  saved {target.name} ({len(response.content)} bytes)")
                except Exception as exc:
                    print(f"  ! resource {url}: {exc}")
                time.sleep(0.3)
    print(f"Manifest: {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
