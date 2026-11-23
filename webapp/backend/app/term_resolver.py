"""Resolve a commercial term to a TARIC code using discriminating attributes."""
from __future__ import annotations
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

DB_PATH = Path(os.getenv("TERMBASE_DB", "/app/data/termbase.sqlite"))
DEFAULT_ATTRS = Path("/app/code_attributes.json")
ATTRS_PATH = Path(os.getenv("TERM_ATTRIBUTES", str(DEFAULT_ATTRS)))
for candidate in [Path("/app/tariffai/code_attributes.json"), Path("/app/code_attributes.json")]:
    if candidate.is_file():
        ATTRS_PATH = candidate
        break


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _load_attrs() -> dict:
    # Prefer the SQLite tables; keep JSON as a development fallback.
    if DB_PATH.is_file():
        try:
            with sqlite3.connect(f"file:{DB_PATH}?mode=ro&immutable=1", uri=True) as db:
                codes: dict[str, dict[str, str]] = {}
                for code, attribute, value in db.execute("SELECT code, attribute, value FROM code_attributes"):
                    codes.setdefault(code, {})[attribute] = value
                templates: dict[str, dict] = {}
                for attribute, question, options in db.execute("SELECT attribute, question, options_json FROM question_templates"):
                    templates[attribute] = {"question": question, "options": json.loads(options)}
                if codes or templates:
                    return {"codes": codes, "templates": templates}
        except Exception:
            pass
    if not ATTRS_PATH.is_file():
        return {"codes": {}, "templates": {}}
    return json.loads(ATTRS_PATH.read_text(encoding="utf-8"))


def _codes(candidates: list[dict]) -> list[str]:
    return sorted({
        str(c.get("code") or c.get("taric10") or c.get("cn8") or "")
        for c in candidates
        if (c.get("code") or c.get("taric10") or c.get("cn8"))
    })


def next_question(candidates: list[dict]) -> dict | None:
    """Return the attribute question that best splits the current candidates."""
    attrs = _load_attrs()
    by_code = attrs.get("codes", {})
    templates = attrs.get("templates", {})
    codes = _codes(candidates)
    if len(codes) < 2:
        return None
    dimensions: dict[str, dict[str, set[str]]] = {}
    for code in codes:
        for key, value in (by_code.get(code) or {}).items():
            dimensions.setdefault(key, {}).setdefault(value, set()).add(code)
    best = None
    for key, values in dimensions.items():
        if len(values) < 2 or key not in templates:
            continue
        sizes = sorted((len(v) for v in values.values()), reverse=True)
        score = 1 - (sizes[0] / len(codes))
        if best is None or score > best[0]:
            best = (score, key, values)
    if not best:
        return None
    _, key, _values = best
    template = templates[key]
    return {
        "question": template["question"],
        "options": [item["label"] for item in template["options"]],
        "attribute": f"term:{key}",
        "option_values": {item["label"]: item["value"] for item in template["options"]},
    }


def filter_candidates(candidates: list[dict], attribute: str, answer: str) -> list[dict]:
    """Filter candidates by a term attribute answer."""
    if not attribute.startswith("term:"):
        return candidates
    key = attribute.split(":", 1)[1]
    attrs = _load_attrs()
    template = (attrs.get("templates") or {}).get(key) or {}
    value = None
    for item in template.get("options", []):
        if _normalize(item.get("label", "")) == _normalize(answer):
            value = item.get("value")
            break
    if value is None:
        value = _normalize(answer)
    return [
        c for c in candidates
        if (attrs.get("codes", {}).get(str(c.get("code") or "")) or {}).get(key) == value
    ]
