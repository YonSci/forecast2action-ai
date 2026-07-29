"""Builds KnowledgeContext by delegating to app.retrieval.hybrid_retriever
-- this module never reads data/knowledge/action_library.json directly.
"""

from typing import Any, Dict, Optional

from app.context.schemas import KnowledgeContext
from app.retrieval.hybrid_retriever import retrieve


def build_knowledge_context(
    query: Dict[str, Any], top_k: int = 5, country: Optional[str] = None,
) -> KnowledgeContext:
    items = retrieve(query, top_k=top_k, country=country)
    return KnowledgeContext(retrieved_items=items, retrieval_mode="keyword_metadata")
