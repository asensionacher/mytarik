"""
Stage 4 support: full HS catalogue access (no LLM).

The retrieval stage only returns the Top-K candidates found by hybrid search.
That is not enough to *reason* about a close call: two subheadings of the same
heading often differ by a single attribute ("of cotton" vs "of other textile
materials"), and the discriminating attribute is usually a sibling of the
proposed code rather than the proposed code itself.

This module keeps an in-memory copy of the HS catalogue that was ingested from
the Harmonized System CSV into Qdrant (`hs_codes` collection) and renders it as
prompt context: for every candidate heading, the whole set of 6-digit
subheadings under it.

The catalogue is a cache of the very same CSV that produced the Qdrant points,
so it never diverges from what the retriever can propose.
"""

import logging

from app.config import QDRANT_COLLECTION, QDRANT_HOST, QDRANT_PORT
from app.schemas import HSCandidate

logger = logging.getLogger(__name__)


# Maximum headings rendered in the reasoning context (keeps the prompt bounded).
MAX_CONTEXT_HEADINGS = 6


# ── Lazy catalogue ──────────────────────────────────────────────────────
_catalogue: dict[str, dict] | None = None
_siblings_by_heading: dict[str, list[dict]] | None = None


def _load_catalogue() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """
    Scroll the Qdrant collection once and index every 6-digit entry by code
    and by heading. Returns (by_code, siblings_by_heading).
    """
    from qdrant_client import QdrantClient

    client = QdrantClient(
        host=QDRANT_HOST, port=QDRANT_PORT, timeout=30.0, check_compatibility=False,
    )
    by_code: dict[str, dict] = {}
    siblings: dict[str, list[dict]] = {}

    offset = None
    while True:
        results, next_offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in results:
            payload = point.payload
            code = payload.get("code", "")
            if not code:
                continue
            by_code[code] = payload
            heading = payload.get("heading_code", "")
            if heading:
                siblings.setdefault(heading, []).append(payload)
        if next_offset is None:
            break
        offset = next_offset

    for heading in siblings:
        siblings[heading].sort(key=lambda entry: entry.get("code", ""))

    return by_code, siblings


def get_catalogue() -> dict[str, dict]:
    """Return the HS catalogue indexed by 6-digit code (empty if unavailable)."""
    global _catalogue, _siblings_by_heading
    if _catalogue is None:
        try:
            _catalogue, _siblings_by_heading = _load_catalogue()
            logger.info("[TariffAI] HS catalogue loaded: %d entries", len(_catalogue))
        except Exception as exc:
            logger.warning("Could not load the HS catalogue: %s", exc)
            _catalogue = {}
            _siblings_by_heading = {}
    return _catalogue


def get_siblings(heading_code: str) -> list[dict]:
    """Return every 6-digit subheading that belongs to the given 4-digit heading."""
    get_catalogue()
    if not _siblings_by_heading:
        return []
    return list(_siblings_by_heading.get(heading_code, []))


def get_entry(code: str) -> dict | None:
    """Return a single catalogue entry by 6-digit code."""
    return get_catalogue().get(code)


def initialize_catalogue() -> int:
    """Pre-warm the catalogue cache. Returns the number of entries loaded."""
    return len(get_catalogue())


# ── Prompt rendering ────────────────────────────────────────────────────

def _render_heading(entry: dict, siblings: list[dict]) -> str:
    lines = [
        f"Chapter {entry.get('chapter_code', '')}: {entry.get('chapter_description', '')}",
        f"Heading {entry.get('heading_code', '')}: {entry.get('heading_description', '')}",
    ]
    if siblings:
        lines.append("Subheadings under this heading (official HS descriptions):")
        for sibling in siblings:
            code = sibling.get("code", "")
            description = sibling.get("description", "")
            marker = "  <- retrieved" if code == entry.get("code") else ""
            lines.append(f"  - {code}: {description}{marker}")
    else:
        lines.append(f"  - {entry.get('code', '')}: {entry.get('description', '')}")
    return "\n".join(lines)


def build_catalogue_context(candidates: list[HSCandidate]) -> str:
    """
    Render the catalogue view used by the deep reasoning stage.

    For every distinct heading among the candidates, the full list of 6-digit
    subheadings is shown so the model can compare siblings that differ only by
    a material, a form or a use. Falls back to the candidates themselves when
    the catalogue is not reachable.
    """
    if not candidates:
        return ""

    get_catalogue()
    blocks: list[str] = []
    seen_headings: set[str] = set()

    for candidate in candidates:
        heading = candidate.heading_code
        if not heading or heading in seen_headings:
            continue
        seen_headings.add(heading)
        entry = {
            "code": candidate.code,
            "description": candidate.description,
            "chapter_code": candidate.chapter_code,
            "chapter_description": candidate.chapter_description,
            "heading_code": candidate.heading_code,
            "heading_description": candidate.heading_description,
        }
        siblings = get_siblings(heading)
        blocks.append(_render_heading(entry, siblings))
        if len(blocks) >= MAX_CONTEXT_HEADINGS:
            break

    if not blocks:
        lines = []
        for candidate in candidates:
            lines.append(
                f"- {candidate.code}: {candidate.description} "
                f"(heading {candidate.heading_code}: {candidate.heading_description})"
            )
        return "\n".join(lines)

    return "\n\n".join(blocks)
