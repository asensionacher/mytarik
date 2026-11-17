import inspect
import sys
from pathlib import Path

if "dotenv" not in sys.modules:
    from types import ModuleType

    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import eu_retriever
from app.eu_retriever import EUCandidate, retrieve_eu_candidates


class _Point:
    def __init__(self, payload, score=0.0):
        self.payload = payload
        self.score = score


class _Response:
    def __init__(self, points):
        self.points = points


def _entry(cn8, taric10, description):
    return {"cn8": cn8, "taric10": taric10, "description": description}


class FakeQdrant:
    """Minimal duck-typed Qdrant client that only ever serves eu_taric data."""

    def __init__(self, entries, semantic_scores=None):
        self._entries = entries
        self._semantic_scores = semantic_scores or {e["taric10"]: 0.9 for e in entries}
        self.collections_queried = []

    def query_points(self, collection_name, query, limit, with_payload=True):
        self.collections_queried.append(collection_name)
        assert len(query) == 384, "embedder output must be a fixed-length vector"
        ordered = sorted(
            self._entries,
            key=lambda e: self._semantic_scores.get(e["taric10"], 0.0),
            reverse=True,
        )
        return _Response([_Point(e, self._semantic_scores.get(e["taric10"], 0.0)) for e in ordered[:limit]])

    def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        self.collections_queried.append(collection_name)
        page = self._entries if offset is None else []
        return ([_Point(e) for e in page], None)


def _fake_embedder(text):
    assert text.startswith("query: "), "semantic search must use the e5 query prefix"
    return [0.1] * 384


OLIVE = _entry("85444210", "8544421010", "Electrical cables with connectors for olive presses")
CABLE = _entry("85444290", "8544429090", "Other electric cables fitted with connectors")
MACHINE = _entry("84778000", "8477800000", "Machinery for working rubber or plastics")


def test_returns_candidate_fields():
    client = FakeQdrant([OLIVE, CABLE, MACHINE])
    results = retrieve_eu_candidates("cables with connectors", top_k=3, client=client, embedder=_fake_embedder)

    assert results, "expected at least one candidate"
    for cand in results:
        assert isinstance(cand, EUCandidate)
        assert cand.cn8 and len(cand.cn8) == 8
        assert cand.taric10 and len(cand.taric10) == 10
        assert cand.description
        assert 0.0 <= cand.score <= 1.0


def test_only_reads_eu_taric_collection():
    client = FakeQdrant([OLIVE, CABLE, MACHINE])
    retrieve_eu_candidates("cables", top_k=3, client=client, embedder=_fake_embedder)

    assert client.collections_queried, "retriever must query Qdrant"
    assert set(client.collections_queried) == {eu_retriever.EU_TARIC_COLLECTION}
    assert "hs_codes" not in client.collections_queried


def test_collection_constant_is_eu_taric():
    assert eu_retriever.EU_TARIC_COLLECTION == "eu_taric"


def test_public_api_has_no_hs6_collection_param():
    params = inspect.signature(retrieve_eu_candidates).parameters
    assert "collection" not in params
    assert "collection_name" not in params


def test_fusion_boosts_entry_present_in_both_signals():
    # Semantic puts OLIVE first; BM25 (query word "olive") matches only OLIVE.
    client = FakeQdrant([OLIVE, CABLE], semantic_scores={OLIVE["taric10"]: 0.99, CABLE["taric10"]: 0.90})
    results = retrieve_eu_candidates("olive", top_k=2, client=client, embedder=_fake_embedder)

    assert results[0].taric10 == OLIVE["taric10"], "entry matched by both signals must rank first"
    scores = [c.score for c in results]
    assert scores == sorted(scores, reverse=True)
