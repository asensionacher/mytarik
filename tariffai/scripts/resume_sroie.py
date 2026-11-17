#!/usr/bin/env python3
"""Resume the public SROIE image download without re-fetching existing files."""
from __future__ import annotations

import time
from pathlib import Path

import requests
from huggingface_hub import HfApi

REPO = "ryanznie/SROIE_2019_with_labels"
DEST = Path("/home/seby/mytarik/data/public/sroie")
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main"


def main() -> int:
    api = HfApi()
    files = [
        f for f in api.list_repo_files(REPO, repo_type="dataset")
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    missing = [f for f in files if not (DEST / f).is_file()]
    print(f"repo={len(files)} present={len(files)-len(missing)} missing={len(missing)}", flush=True)
    session = requests.Session()
    session.headers["User-Agent"] = "Mytarik-public-corpus/1.0"
    for index, name in enumerate(missing, start=1):
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(6):
            try:
                response = session.get(f"{BASE}/{name}", timeout=60)
                if response.status_code == 429:
                    wait = 20 * (attempt + 1)
                    print(f"429 {name}; sleep {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                target.write_bytes(response.content)
                if index % 25 == 0:
                    print(f"{index}/{len(missing)}", flush=True)
                break
            except Exception as exc:
                print(f"! {name}: {exc}", flush=True)
                time.sleep(5)
        time.sleep(0.3)
    print(f"done; present={sum(1 for f in files if (DEST/f).is_file())}/{len(files)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
