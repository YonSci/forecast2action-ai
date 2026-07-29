"""Stage 4 of hybrid retrieval: rerank + dedupe keyword and semantic results.

Phase 1 has semantic_results always empty (NullSemanticRetriever), so this
behaves as a dedupe-by-id + authority/recency-adjusted sort + truncate over
the keyword results alone. Written as a real merge (not a keyword-only
passthrough) so wiring in a real semantic retriever later only requires
changing semantic_retriever.py, not this function.
"""

from typing import Any, Dict, List

AUTHORITY_BONUS = {
    "official": 1.0,
    "peer_reviewed": 0.8,
    "institutional": 0.6,
    "expert_validated": 0.6,
    "approved": 0.4,
    "prototype": 0.0,
    "unverified": -0.5,
}


def _final_score(item: Dict[str, Any]) -> float:
    keyword_score = float(item.get("retrieval_score", 0.0))
    authority_bonus = AUTHORITY_BONUS.get(item.get("authority_status", "approved"), 0.0)
    semantic_score = float(item.get("semantic_score", 0.0))
    return round(keyword_score + authority_bonus + semantic_score, 3)


def rerank(
    keyword_results: List[Dict[str, Any]],
    semantic_results: List[Dict[str, Any]],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    merged_by_id: Dict[str, Dict[str, Any]] = {}

    for item in keyword_results:
        merged_by_id[item["id"]] = dict(item)

    for item in semantic_results:
        existing = merged_by_id.get(item["id"])
        if existing:
            existing["semantic_score"] = item.get("semantic_score", 0.0)
        else:
            merged_by_id[item["id"]] = dict(item)

    for item in merged_by_id.values():
        item["final_score"] = _final_score(item)

    ranked = sorted(merged_by_id.values(), key=lambda item: item["final_score"], reverse=True)
    return ranked[:top_k]
