import { useState } from "react";
import { apiUrl } from "../../config.js";

// Surfaces GET /api/context/{context_id}/audit (see app/api/context_api.py)
// -- the provenance/policy/validation trail behind the quality score shown
// by ContextQualityBadge, so a user can inspect where the numbers came
// from without calling the API by hand. Fetched lazily on first expand,
// then cached per contextId so re-toggling doesn't refetch.
function formatThresholds(thresholds) {
  if (!thresholds || typeof thresholds !== "object") return "";
  return Object.entries(thresholds)
    .map(([key, value]) => `${key}: ${value}`)
    .join(", ");
}

function ContextAuditDrawer({ contextId }) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [audit, setAudit] = useState(null);
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

    if (loadedForContextId === contextId && audit) {
      return;
    }

    setLoading(true);
    setErrorMessage("");
    try {
      const response = await fetch(apiUrl(`/api/context/${contextId}/audit`));
      if (!response.ok) {
        throw new Error(`Request failed ${response.status}`);
      }
      const data = await response.json();
      setAudit(data);
      setLoadedForContextId(contextId);
    } catch (error) {
      console.error(error);
      setErrorMessage("Could not load the context audit trail.");
    } finally {
      setLoading(false);
    }
  }

  const provenance = audit?.provenance || {};
  const policy = audit?.policy || {};
  const validation = audit?.validation || {};

  return (
    <div className="context-audit-drawer">
      <button type="button" className="context-audit-toggle" onClick={handleToggle}>
        {expanded ? "Hide audit trail" : "View context audit trail"}
      </button>

      {expanded && (
        <div className="context-audit-panel">
          {loading && <p>Loading audit trail...</p>}
          {errorMessage && <p className="context-audit-error">{errorMessage}</p>}

          {audit && (
            <>
              <dl className="context-audit-fields">
                <dt>Created</dt>
                <dd>{provenance.created_at || "Not available"}</dd>

                <dt>Prompt version</dt>
                <dd>{provenance.prompt_version || "Not available"}</dd>

                <dt>Context fingerprint</dt>
                <dd
                  className="context-audit-fingerprint"
                  title={provenance.context_fingerprint || ""}
                >
                  {provenance.context_fingerprint
                    ? `${provenance.context_fingerprint.slice(0, 16)}...`
                    : "Not available"}
                </dd>

                <dt>AI provider / model</dt>
                <dd>{[provenance.ai_provider, provenance.ai_model].filter(Boolean).join(" / ") || "Not available"}</dd>

                <dt>Policy</dt>
                <dd>
                  {policy.policy_id || "Not available"}
                  {policy.trigger_status ? ` (trigger status: ${policy.trigger_status})` : ""}
                </dd>

                <dt>Policy thresholds</dt>
                <dd>{formatThresholds(policy.thresholds) || "Not available"}</dd>

                <dt>Knowledge items used</dt>
                <dd>{audit.knowledge_items_count ?? 0}</dd>
              </dl>

              {Array.isArray(provenance.source_endpoints) && provenance.source_endpoints.length > 0 && (
                <div className="context-audit-endpoints">
                  <strong>Source endpoints</strong>
                  <ul>
                    {provenance.source_endpoints.map((endpoint) => (
                      <li key={endpoint}>{endpoint}</li>
                    ))}
                  </ul>
                </div>
              )}

              {Array.isArray(validation.errors) && validation.errors.length > 0 && (
                <div className="context-audit-error">
                  {validation.errors.map((error) => (
                    <div key={error}>{error}</div>
                  ))}
                </div>
              )}

              {Array.isArray(validation.warnings) && validation.warnings.length > 0 && (
                <div className="context-audit-warning">
                  {validation.warnings.map((warning) => (
                    <div key={warning}>{warning}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default ContextAuditDrawer;
