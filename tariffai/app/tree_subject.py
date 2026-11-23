"""Tree retrieval guided by the analysed product head and attributes."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from app.taric_tree import load_tree

MATERIAL_CHAPTERS = {
    "titanium": "81", "titanio": "81",
    "steel": "73", "acero": "73",
    "copper": "74", "cobre": "74",
    "aluminium": "76", "aluminum": "76", "aluminio": "76",
}
GENERIC_HEADS = {"scale", "other", "article", "product", "item", "set"}
STOP = {"the", "and", "or", "of", "for", "to", "in", "on", "with", "other", "including", "a", "an", "de", "del", "la", "el", "los", "las", "y", "o", "para", "por", "con", "sin"}


def _plain(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _terms(text: str) -> set[str]:
    return {term for term in _plain(text).split() if term not in STOP and len(term) > 1}


@lru_cache(maxsize=1)
def _headings() -> list[dict]:
    tree = load_tree()
    nodes = tree["nodes"]
    result = []
    for node in nodes.values():
        if node["level"] != 4:
            continue
        child_text = " ".join(
            nodes[child]["description"] for child in node["children"]
            if child in nodes and nodes[child]["level"] == 6
        )
        result.append({**node, "search_text": f"{node['description']} {child_text}"})
    return result


def hints_from_analysis(analysis: dict, top_k: int = 10, original_text: str = "") -> list[dict]:
    commercial = _plain(f"{original_text} {analysis.get('english_query', '')} {head if 'head' in locals() else ''}")
    if any(term in commercial for term in ("memoria ram", "memory ram", "dimm", "so-dimm", "random access memory")):
        return [
            {"heading": "8473", "cn8": "", "description": "RAM module / computer part", "strict": True, "score": 10},
            {"heading": "8542", "cn8": "", "description": "RAM chip / integrated circuit", "strict": True, "score": 10},
        ]
    head = _plain(str(analysis.get("head_noun_english") or analysis.get("head_noun_source") or ""))
    synonyms = " ".join(str(item) for item in analysis.get("synonyms") or [])
    material = _plain(str(analysis.get("material") or ""))
    subject_terms = _terms(f"{head} {synonyms} {analysis.get('english_query', '')}")
    if not subject_terms:
        return []
    # Safety aliases for product nouns whose English form is ambiguous.
    if "scale" in head:
        subject_terms.update({"weighing", "balance"})
    if "phone" in head:
        subject_terms.update({"telephone", "cellular"})
    if "screw" in head or "bolt" in head:
        subject_terms.add("screw")
    material_chapter = next((chapter for token, chapter in MATERIAL_CHAPTERS.items() if token in material.split()), None)
    candidates = [node for node in _headings() if not material_chapter or node["code"][:2] == material_chapter]
    if not candidates:
        candidates = _headings()
    scored = []
    for node in candidates:
        description = _plain(node["search_text"])
        doc_terms = _terms(description)
        overlap = len(subject_terms & doc_terms)
        head_hit = 4 if head and head not in GENERIC_HEADS and head in description else 0
        if not overlap and not head_hit:
            continue
        synonym_hit = 2 if any(_plain(s) and _plain(s) in description for s in analysis.get("synonyms") or []) else 0
        material_hit = 2 if material and material in description else 0
        chapter_bonus = 3 if material_chapter and node["code"][:2] == material_chapter else 0
        score = overlap + head_hit + synonym_hit + material_hit + chapter_bonus
        scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"heading": node["code"][:4], "cn8": "", "description": node["description"],
         "strict": True, "score": score}
        for score, node in scored[:top_k]
    ]
