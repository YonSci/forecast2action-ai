"""Regression guard: app.retrieval.keyword_retriever.score_entry is a
deliberate PORT of app.advisory.rag_engine.score_entry (see that module's
docstring for why it's a copy, not a shared import) -- this test ensures
the two never silently drift apart on the same inputs.
"""

from app.advisory.rag_engine import score_entry as legacy_score_entry
from app.retrieval.keyword_retriever import retrieve, score_entry

ENTRY = {
    "hazard": "drought",
    "risk_level": "trigger",
    "audience": "disaster_manager",
    "actions": ["Verify community water points."],
    "rationale": "Local verification needed.",
}

QUERY = {
    "hazard": "drought", "risk_level": "trigger", "audience": "disaster_manager",
    "feedback_signal": "strong_ground_signal", "spi": -1.5, "rainfall_anomaly_pct": -25,
}


def test_score_entry_matches_legacy_rag_engine_implementation():
    assert score_entry(ENTRY, QUERY) == legacy_score_entry(ENTRY, QUERY)


def test_score_entry_matches_legacy_for_mismatched_hazard():
    query = {**QUERY, "hazard": "heavy_rainfall"}
    assert score_entry(ENTRY, query) == legacy_score_entry(ENTRY, query)


def test_score_entry_matches_legacy_for_any_audience():
    entry = {**ENTRY, "audience": "any"}
    assert score_entry(entry, QUERY) == legacy_score_entry(entry, QUERY)


def test_retrieve_only_returns_positive_scores():
    library = [ENTRY, {**ENTRY, "hazard": "heat_stress", "risk_level": "watch", "audience": "any"}]
    results = retrieve(QUERY, library, top_k=5)
    assert all(item["retrieval_score"] > 0 for item in results)


def test_retrieve_sorts_descending_by_score():
    library = [
        {**ENTRY, "audience": "any"},
        ENTRY,  # exact audience match scores higher
    ]
    results = retrieve(QUERY, library, top_k=5)
    scores = [item["retrieval_score"] for item in results]
    assert scores == sorted(scores, reverse=True)
