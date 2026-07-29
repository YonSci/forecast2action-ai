import { useState } from "react";
import { apiUrl } from "../../config.js";

// Surfaces the score breakdown behind EvidenceCitationsList's knowledge
// sources -- app/retrieval/keyword_retriever.py's retrieval_score,
// app/retrieval/reranker.py's authority bonus + final_score, and
// semantic_score when present (it's absent, not zero, whenever
// NullSemanticRetriever contributed nothing -- see semantic_retriever.py).
// Fetches the FULL envelope (GET /api/context/{context_id}, not /audit,
// which omits retrieved_items) lazily on first expand, cached per
// contextId like ContextAuditDrawer.
//
// Scope note: app.retrieval.hybrid_retriever.retrieve only returns the
// final top-k reranked items -- candidates that were scored but not
// selected are discarded, not persisted anywhere. This panel shows the
// score breakdown for what WAS retrieved, not the full candidate pool
// that was considered and rejected.
const AUTHORITY_BONUS = {
  official: 1.0,
  peer_reviewed: 0.8,
  institutional: 0.6,
  expert_validated: 0.6,
  approved: 0.4,
  prototype: 0.0,
  unverified: -0.5,
};

function authorityBonusLabel(authorityStatus) {
  if (!authorityStatus) return "";
  const bonus = AUTHORITY_BONUS[authorityStatus];
  if (bonus === undefined) return authorityStatus;
  return `${authorityStatus} (+${bonus})`;
}

function RetrievalDebugPanel({ contextId }) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [knowledge, setKnowledge] = useState(null);
  const [loadedForContextId, setLoadedForContextId] = useState(null);

  if (!contextId) {
    return null;
  }

  async function handleToggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }

    setExpanded(true);

    if (loadedForContextId === contextId && knowledge) {
      return;
    }

    setLoading(true);
    setErrorMessage("");
    try {
      const response = await fetch(apiUrl(`/api/context/${contextId}`));
      if (!response.ok) {
        throw new Error(`Request failed ${response.status}`);
      }
      const envelope = await response.json();
      setKnowledge(envelope.knowledge || { retrieved_items: [], retrieval_mode: "" });
      setLoadedForContextId(contextId);
    } catch (error) {
      console.error(error);
      setErrorMessage("Could not load retrieval details.");
    } finally {
      setLoading(false);
    }
  }

  const retrievedItems = knowledge?.retrieved_items || [];

  return (
    <div className="retrieval-debug-panel-wrapper">
      <button type="button" className="retrieval-debug-toggle" onClick={handleToggle}>
        {expanded ? "Hide retrieval details" : "View retrieval details"}
      </button>

      {expanded && (
        <div className="retrieval-debug-panel">
          {loading && <p>Loading retrieval details...</p>}
          {errorMessage && <p className="context-audit-error">{errorMessage}</p>}

          {knowledge && (
            <>
              <p className="retrieval-debug-mode">
                Retrieval mode: {knowledge.retrieval_mode || "Not available"}
              </p>

              {retrievedItems.length === 0 && <p>No knowledge items were retrieved.</p>}

              {retrievedItems.map((item, index) => (
                <div className="retrieval-debug-item" key={item.id || index}>
                  <strong>{item.title || item.id}</strong>
                  <div className="retrieval-debug-match">
                    Matched on: hazard={item.hazard || "any"}, risk_level={item.risk_level || "any"}, audience={item.audience || "any"}
                  </div>
                  <div className="retrieval-debug-score-row">
                    Keyword match score: {item.retrieval_score ?? "Not available"}
                  </div>
                  <div className="retrieval-debug-score-row">
                    Authority status: {authorityBonusLabel(item.authority_status) || "Not available"}
                  </div>
                  <div className="retrieval-debug-score-row">
                    Semantic score: {item.semantic_score !== undefined
                      ? item.semantic_score
                      : "Not available (semantic retrieval not yet enabled)"}
                  </div>
                  <div className="retrieval-debug-score-row">
                    Combined rank score: {item.final_score ?? "Not available"}
                  </div>
                  <div className="retrieval-debug-source">
                    {item.source_organization || "Unknown source"}
                    {item.version ? ` (v${item.version})` : ""}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default RetrievalDebugPanel;
