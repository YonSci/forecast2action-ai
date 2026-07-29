"""Builds stable, structured citation records for retrieved knowledge items.

Factors out the citation-shape logic already duplicated inline in
app.advisory.rag_engine.build_rag_advisory's knowledge_sources list
comprehension, in the shape the project spec calls for so the frontend can
render "Why this recommendation?" evidence consistently.
"""

from typing import Any, Dict, List


def _evidence_passage(item: Dict[str, Any], max_chars: int = 240) -> str:
    rationale = str(item.get("rationale", ""))
    if len(rationale) <= max_chars:
        return rationale
    return rationale[: max_chars - 15].rstrip() + "...TRUNCATED..."


def build_citation(item: Dict[str, Any], matched_metadata: List[str] | None = None) -> Dict[str, Any]:
    return {
        "knowledge_id": item.get("id", ""),
        "title": item.get("title", ""),
        "source": item.get("source_title", "") or item.get("source_organization", ""),
        "authority": item.get("authority_status", "approved"),
        "version": item.get("version", "1.0.0"),
        "retrieval_score": item.get("final_score", item.get("retrieval_score", 0)),
        "matched_metadata": matched_metadata or [],
        "evidence_passage": _evidence_passage(item),
    }


def build_citations(retrieved_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [build_citation(item) for item in retrieved_items]
