"""Tree-child questions and branch filtering shared by the API and benchmark."""
from __future__ import annotations

from app.taric_tree import node_view

LABEL = {
    "es": "¿Cuál de estas categorías corresponde al producto?",
    "en": "Which of these categories matches the product?",
    "fr": "Laquelle de ces catégories correspond au produit ?",
    "de": "Welche dieser Kategorien entspricht dem Produkt?",
    "it": "Quale di queste categorie corrisponde al prodotto?",
}


def question_from_candidates(candidates, language: str = "es") -> dict | None:
    paths = []
    for candidate in candidates:
        code = str(getattr(candidate, "taric10", "") or getattr(candidate, "cn8", "") or "")
        view = node_view(code)
        if not view:
            return None
        paths.append(view["path"])
    if len(paths) < 2:
        return None
    common = []
    for items in zip(*paths):
        if len(set(items)) != 1:
            break
        common.append(items[0])
    if not common:
        return None
    parent = node_view(common[-1])
    if not parent or int(parent.get("level", 0)) < 4:
        return None
    index = len(common)
    groups = {}
    for candidate in candidates:
        view = node_view(str(getattr(candidate, "taric10", "") or getattr(candidate, "cn8", "") or ""))
        if not view or len(view["path"]) <= index:
            continue
        child = view["path"][index]
        child_view = node_view(child)
        if child_view:
            groups[child] = child_view.get("description") or child
    if len(groups) < 2:
        return None
    ordered = sorted(groups.items())[:12]
    return {
        "question": LABEL.get(language, LABEL["es"]),
        "options": [description for _, description in ordered],
        "option_codes": [code for code, _ in ordered],
        "attribute": "tree",
        "parent_code": common[-1],
    }
