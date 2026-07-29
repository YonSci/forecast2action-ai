"""Main entry point for the hybrid retrieval pipeline.

Stages: metadata filter -> keyword scoring -> (semantic, phase-1 no-op) ->
rerank/dedupe. This is what app/context/knowledge_context.py and
app/decision/action_selector.py call -- neither of them talks to
metadata_filters/keyword_retriever/reranker directly.
"""

from typing import Any, Dict, List, Optional

from app.advisory.rag_engine import load_action_library
from app.advisory.knowledge_compat import ensure_new_fields
from app.retrieval import keyword_retriever, metadata_filters, reranker
from app.retrieval.semantic_retriever import NullSemanticRetriever, SemanticRetriever


def retrieve(
    query: Dict[str, Any],
    top_k: int = 5,
    *,
    country: Optional[str] = None,
    language: Optional[str] = None,
    semantic: Optional[SemanticRetriever] = None,
) -> List[Dict[str, Any]]:
    """Returns up to top_k knowledge items, reranked and deduplicated.

    `query` uses the same shape as app.advisory.rag_engine.score_entry's
    context argument (hazard, risk_level, audience, feedback_signal, spi,
    rainfall_anomaly_pct).
    """
    library = [ensure_new_fields(entry) for entry in load_action_library()]
    filtered = metadata_filters.filter_by_metadata(
        library, country=country, language=language,
    )

    keyword_results = keyword_retriever.retrieve(query, filtered, top_k=top_k * 2)

    semantic_retriever = semantic or NullSemanticRetriever()
    semantic_results = semantic_retriever.retrieve(
        semantic_retriever.embed_query(_query_to_text(query)), top_k=top_k * 2,
    )

    return reranker.rerank(keyword_results, semantic_results, top_k=top_k)


def _query_to_text(query: Dict[str, Any]) -> str:
    return " ".join(
        str(query.get(key, "")) for key in ("hazard", "risk_level", "audience", "feedback_signal")
    ).strip()
