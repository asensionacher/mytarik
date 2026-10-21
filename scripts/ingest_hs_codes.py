"""Root shim.

Lets ``python -m scripts.ingest_hs_codes`` work from the repository root by
delegating to the real implementation in ``tariffai/scripts/``.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tariffai"))

from scripts.ingest_hs_codes import main  # noqa: E402,F401  (tariffai/scripts)

if __name__ == "__main__":
    main()
