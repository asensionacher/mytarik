"""Question generation from the children of the TARIC tree."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

TREE_PATH = Path(os.getenv("TARIC_TREE_PATH", "/app/taric_tree.json"))
LABEL = {
    "es": "¿Cuál de estas categorías corresponde al producto?",
    "en": "Which of these categories matches the product?",
    "fr": "Laquelle de ces catégories correspond au produit ?",
    "de": "Welche dieser Kategorien entspricht dem Produkt?",
    "it": "Quale di queste categorie corrisponde al prodotto?",
}


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))[:10].ljust(10, "0")


@lru_cache(maxsize=1)
def _tree() -> dict:
    return json.loads(TREE_PATH.read_text(encoding="utf-8"))


def _node(code: str) -> dict | None:
    return _tree()["nodes"].get(_digits(code))


def tree_question(candidates: list[dict], language: str = "es") -> dict | None:
    if len(candidates) < 2:
        return None
    paths = []
    for candidate in candidates:
        node = _node(str(candidate.get("code") or candidate.get("taric10") or candidate.get("cn8") or ""))
        if not node:
            return None
        paths.append(node["path"])
    common = []
    for items in zip(*paths):
        if len(set(items)) != 1:
            break
        common.append(items[0])
    if not common:
        # Candidates span chapters: ask for the chapter before trying to go
        # deeper. This is still a tree question, not a generic LLM question.
        groups: dict[str, str] = {}
        for candidate in candidates:
            code = str(candidate.get("code") or candidate.get("taric10") or candidate.get("cn8") or "")
            node = _node(code)
            if not node or not node.get("path"):
                return None
            chapter = node["path"][0]
            chapter_node = _node(chapter)
            if chapter_node:
                groups[chapter] = chapter_node.get("description") or chapter
        if len(groups) < 2:
            return None
        ordered = sorted(groups.items())[:12]
        return {
            "question": "¿Cuál de estos capítulos corresponde al producto?",
            "options": [description for _, description in ordered],
            "option_codes": [code for code, _ in ordered],
            "attribute": "tree",
            "parent_code": None,
        }
    parent_code = common[-1]
    parent = _node(parent_code)
    if not parent or int(parent.get("level", 0)) < 4:
        return None
    index = len(common)
    groups: dict[str, str] = {}
    for candidate, path in zip(candidates, paths):
        if len(path) <= index:
            continue
        child = path[index]
        child_node = _node(child)
        if child_node:
            groups[child] = child_node.get("description") or child
    if len(groups) < 2:
        return None
    ordered = sorted(groups.items(), key=lambda item: item[0])[:12]
    return {
        "question": LABEL.get(language, LABEL["es"]),
        "options": [description for _, description in ordered],
        "option_codes": [code for code, _ in ordered],
        "attribute": "tree",
        "parent_code": parent_code,
    }


def filter_by_branch(candidates: list[dict], option_code: str) -> list[dict]:
    selected = _digits(option_code)
    if not selected:
        return candidates
    out = []
    for candidate in candidates:
        node = _node(str(candidate.get("code") or candidate.get("taric10") or candidate.get("cn8") or ""))
        if node and selected in node.get("path", []):
            out.append(candidate)
    return out or candidates
