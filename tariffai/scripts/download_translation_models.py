#!/usr/bin/env python3
"""Download the two specialized OPUS-MT models (Apache-2.0, CTranslate2 int8)."""
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1] / "models" / "translation"
MODELS = {
    "es-en": "michaelfeil/ct2fast-opus-mt-es-en",
    "en-es": "michaelfeil/ct2fast-opus-mt-en-es",
}

for name, repo_id in MODELS.items():
    target = ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    print(f"Descargando {repo_id} -> {target}")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        local_dir_use_symlinks=False,
        ignore_patterns=["*.md", ".gitattributes"],
    )
print("Modelos de traducción listos en", ROOT)
