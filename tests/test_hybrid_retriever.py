from app.retrieval.reranker import rerank
from app.retrieval.semantic_retriever import NullSemanticRetriever
from app.retrieval.hybrid_retriever import retrieve


def test_null_semantic_retriever_always_returns_empty():
    retriever = NullSemanticRetriever()
    assert retriever.embed_query("anything") == []
    assert retriever.retrieve([], top_k=5) == []


def test_rerank_dedupes_by_id_preferring_keyword_result():
    keyword_results = [{"id": "a", "retrieval_score": 5.0, "authority_status": "approved"}]
    semantic_results = [{"id": "a", "retrieval_score": 5.0, "semantic_score": 2.0, "authority_status": "approved"}]

    ranked = rerank(keyword_results, semantic_results, top_k=5)
    assert len(ranked) == 1
    assert ranked[0]["semantic_score"] == 2.0  # merged in from the semantic result


def test_rerank_truncates_to_top_k():
    keyword_results = [
        {"id": str(i), "retrieval_score": float(i), "authority_status": "approved"} for i in range(10)
    ]
    ranked = rerank(keyword_results, [], top_k=3)
    assert len(ranked) == 3
    assert ranked[0]["id"] == "9"  # highest score first


def test_hybrid_retrieve_real_knowledge_base_returns_drought_items_for_drought_query():
    results = retrieve(
        {"hazard": "drought", "risk_level": "trigger", "audience": "disaster_manager", "feedback_signal": "strong_ground_signal"},
        top_k=3,
    )
    assert len(results) > 0
    assert all(item.get("hazard") in ("drought", "any") for item in results)
