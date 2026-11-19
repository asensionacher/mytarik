"""Hierarchical BM25 index over the TARIC tree.

Stage 1: choose the chapter (2 digits).
Stage 2: search headings only inside the winning chapter(s).
This prevents a word such as "gasoline" from sending motorcycles to chapter 38.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from app.taric_tree import load_tree

logger = logging.getLogger(__name__)


STOP = {
    "the", "and", "or", "of", "for", "to", "in", "on", "with", "without",
    "whether", "not", "other", "including", "than", "by", "from", "a", "an",
    "their", "its", "this", "that", "these", "those", "used", "use", "kind",
    "de", "del", "la", "el", "los", "las", "y", "o", "para", "por", "con",
    "sin", "que", "un", "una", "unos", "unas", "al", "en", "se", "su",
}
NEGATIONS = {"not", "without", "excluding", "except", "no", "sin", "non", "nicht", "ohne", "sans", "senza"}
MATERIALS = {"titanium", "steel", "aluminium", "aluminum", "copper", "plastic", "cotton", "wool", "nylon", "polyester", "rubber", "glass", "wood", "leather"}
# Metal articles are classified by material chapter before product form.
MATERIAL_CHAPTERS = {
    "titanium": "81", "steel": "73", "copper": "74",
    "aluminium": "76", "aluminum": "76",
}
PRODUCT_TERMS = (
    ("bascula", "weighing scale balance"),
    ("báscula", "weighing scale balance"),
    ("balanza", "weighing scale balance"),
    ("cable usb c", "usb electric cable conductor"),
    ("cable usb", "usb electric cable conductor"),
    ("cepillo de dientes", "toothbrush"),
    ("lona", "tarpaulin"),
    ("toldo", "awning tarpaulin"),
    ("manillar", "handlebar"),
    ("bicicleta", "bicycle"),
    ("motocicleta", "motorcycle"),
    ("teléfono móvil", "smartphone cellular telephone"),
    ("telefono movil", "smartphone cellular telephone"),
    ("teléfono celular", "smartphone cellular telephone"),
    ("mobile phone", "smartphone cellular telephone"),
    ("smartphone", "smartphone cellular telephone"),
    ("móvil", "smartphone cellular telephone"),
)


def _tokens(text: str, weight_head: bool = True) -> list[str]:
    """Tokenize, remove negation tails, and emphasise the product head noun.

    BM25 otherwise gives the same weight to "not knitted" and "knitted", which
    sends suits to the knitted-apparel chapter. The last content token is the
    product head in product descriptions such as "nylon tarpaulin".
    """
    raw = re.findall(r"[a-z0-9]+", (text or "").lower())
    content = []
    skip = 0
    for token in raw:
        if token in NEGATIONS:
            skip = 3
            continue
        if skip:
            skip -= 1
            continue
        if token not in STOP and len(token) > 1:
            content.append(token)
    # Light singularisation: tarpaulins -> tarpaulin, bicycles -> bicycle.
    def singular(token: str) -> str:
        if len(token) > 5 and token.endswith(("ches", "shes", "sses")):
            return token[:-2]
        if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token
    content = [singular(token) for token in content]
    if not content:
        return []
    if not weight_head:
        return content
    # Head noun gets the strongest weight, its modifier the second strongest.
    weighted = content[:]
    # Material is a hard discriminator: titanium screws are not steel screws.
    weighted.extend([token for token in content if token in MATERIALS] * 4)
    weighted.extend(content[-1:] * 4)
    if len(content) > 1:
        weighted.extend(content[-2:-1] * 2)
    return weighted


@lru_cache(maxsize=1)
def _indexes():
    from rank_bm25 import BM25Okapi

    tree = load_tree()
    chapters = [node for node in tree["nodes"].values() if node["level"] == 2]
    headings = [node for node in tree["nodes"].values() if node["level"] == 4]
    subheadings = [node for node in tree["nodes"].values() if node["level"] == 6]
    by_heading: dict[str, list[str]] = {}
    for node in subheadings:
        by_heading.setdefault(node["code"][:4], []).append(node["description"])
    heading_docs = []
    for node in headings:
        # The heading itself must dominate; child descriptions only add recall.
        doc = _tokens(node["description"]) * 8
        for child_description in by_heading.get(node["code"][:4], []):
            doc.extend(_tokens(child_description))
        heading_docs.append(doc)
    chapter_docs = [_tokens(node["description"]) for node in chapters]
    return chapters, headings, BM25Okapi(chapter_docs), BM25Okapi(heading_docs)


def tree_hints(query_text: str, top_k: int = 20, chapters_to_use: int = 2, original_text: str | None = None) -> list[dict]:
    try:
        chapters, headings, chapter_bm25, heading_bm25 = _indexes()
        # Official tree paths are already structured; only short product
        # queries get the head-noun emphasis.
        expanded = query_text
        plain = f"{original_text or ''} {query_text}".lower()
        for source, target in PRODUCT_TERMS:
            if source in plain:
                expanded = f"{expanded} {target}"
        tokens = _tokens(expanded, weight_head="|" not in expanded)
        if not tokens:
            return []
        # Chapter titles are broad ("VEHICLES"). Aggregate the scores of the
        # headings that belong to each chapter instead.
        scores = heading_bm25.get_scores(tokens)
        by_code = {node["code"]: float(scores[i]) for i, node in enumerate(headings)}
        chapter_scores: dict[str, float] = {}
        for node, score in zip(headings, scores):
            chapter = node["code"][:2]
            chapter_scores[chapter] = max(chapter_scores.get(chapter, 0.0), float(score))
        material_chapter = next((MATERIAL_CHAPTERS[token] for token in tokens if token in MATERIAL_CHAPTERS), None)
        if material_chapter:
            chosen = [material_chapter]
        else:
            chosen = [chapter for chapter, score in sorted(chapter_scores.items(), key=lambda item: item[1], reverse=True)[:chapters_to_use] if score > 0]
        if not chosen:
            return []
        allowed = [node for node in headings if node["code"][:2] in chosen]
        if not allowed:
            return []
        ranked = sorted(allowed, key=lambda node: by_code.get(node["code"], 0.0), reverse=True)
        hints = []
        for node in [item for item in ranked if by_code.get(item["code"], 0.0) > 0][:top_k]:
            hints.append({
                "heading": node["code"][:4],
                "cn8": "",
                "description": node["description"],
                "strict": True,
                "score": round(by_code.get(node["code"], 0.0), 4),
            })
        return hints
    except Exception as exc:
        logger.info("TARIC tree hints unavailable: %s", exc)
        return []
