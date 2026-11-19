#!/usr/bin/env python3
"""Download OPUS-MT models (Apache-2.0) converted to CTranslate2 int8.

Direct pairs: es<->en, en<->fr, en<->de, en<->it. Other pairs pivot via English.
"""
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1] / "models" / "translation"
MODELS = {
    "es-en": "michaelfeil/ct2fast-opus-mt-es-en",
    "en-es": "michaelfeil/ct2fast-opus-mt-en-es",
    "en-fr": "michaelfeil/ct2fast-opus-mt-en-fr",
    "fr-en": "michaelfeil/ct2fast-opus-mt-fr-en",
    "en-de": "michaelfeil/ct2fast-opus-mt-en-de",
    "de-en": "michaelfeil/ct2fast-opus-mt-de-en",
    "it-en": "gaudi/opus-mt-it-en-ctranslate2",
}
# Helsinki publishes EN->IT but not as a ready CT2 artifact; convert it.
EN_IT_SOURCE = "Helsinki-NLP/opus-mt-en-it"
EN_IT_SRC = ROOT / "en-it-src"


def download(name: str, repo_id: str) -> None:
    target = ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    print(f"Descargando {repo_id} -> {target}")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        ignore_patterns=["*.md", ".gitattributes"],
    )


def convert_en_it() -> None:
    from ctranslate2.converters import TransformersConverter

    EN_IT_SRC.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=EN_IT_SOURCE,
        local_dir=str(EN_IT_SRC),
        ignore_patterns=["*.md", ".gitattributes"],
    )
    target = ROOT / "en-it"
    if not (target / "model.bin").is_file():
        print(f"Convirtiendo {EN_IT_SOURCE} -> {target}")
        TransformersConverter(str(EN_IT_SRC)).convert(
            str(target), quantization="int8", force=True
        )
    for name in ("source.spm", "target.spm"):
        source = EN_IT_SRC / name
        if source.is_file():
            (target / name).write_bytes(source.read_bytes())


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, repo_id in MODELS.items():
        download(name, repo_id)
    convert_en_it()
    print("Modelos de traducción listos en", ROOT)
