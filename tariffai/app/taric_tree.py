"""Read-only access to the complete TARIC tree."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

TREE_PATH = Path(os.getenv("TARIC_TREE_PATH", Path(__file__).resolve().parents[1] / "taric_tree.json"))


@lru_cache(maxsize=1)
def load_tree() -> dict:
    if not TREE_PATH.is_file():
        raise RuntimeError(f"No se encontró el árbol TARIC en {TREE_PATH}")
    return json.loads(TREE_PATH.read_text(encoding="utf-8"))


def normalize_code(code: str) -> str:
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits.ljust(10, "0")[:10] if digits else ""


def get_node(code: str) -> dict | None:
    return load_tree()["nodes"].get(normalize_code(code))


def tree_summary() -> dict:
    data = load_tree()
    return {"counts": data["counts"], "roots": data["roots"]}


def node_view(code: str) -> dict | None:
    data = load_tree()
    node = data["nodes"].get(normalize_code(code))
    if not node:
        return None
    return {
        **node,
        "path_nodes": [
            {"code": item, "description": data["nodes"].get(item, {}).get("description", "")}
            for item in node["path"]
        ],
        "children_nodes": [
            {"code": item, "description": data["nodes"].get(item, {}).get("description", "")}
            for item in node["children"]
        ],
    }
