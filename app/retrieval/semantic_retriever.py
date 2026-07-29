"""Stage 3 of hybrid retrieval: semantic (embedding-based) search.

Phase 1 deliberately ships ONLY a provider-independent interface plus a null
implementation -- no embedding API is called anywhere in this module. This
keeps the app from depending on a paid embedding provider (per the project
spec's explicit constraint) while giving hybrid_retriever.py a stable seam
to call against. Wiring in a real embedding provider later means adding a
new class here and changing the one call site in hybrid_retriever.retrieve
that currently constructs NullSemanticRetriever() -- reranker.py's merge
logic does not need to change, since it already treats semantic_results as a
real (possibly empty) list.
"""

from typing import Any, Dict, List, Protocol


class SemanticRetriever(Protocol):
    def embed_query(self, text: str) -> List[float]:
        ...

    def retrieve(self, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        ...


class NullSemanticRetriever:
    """Phase-1 default. Always returns no results -- callers fall back
    entirely to metadata filtering + keyword scoring, per the spec's
    "must initially fall back to keyword retrieval when embeddings are
    unavailable" requirement.
    """

    def embed_query(self, text: str) -> List[float]:
        return []

    def retrieve(self, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        return []
