// Renders the report's priority_area_justification (see
// app/context/statistical_evidence.py::build_priority_area_justifications
// for the deterministic rank/scores/supporting-indicators, and
// app/api/report_stages.py's _merge_priority_area_justifications for how
// the LLM's differentiator/recommended_intervention_type narrative gets
// combined onto it). Every number here is real and pre-computed -- only
// the differentiator/recommended_intervention_type lines are LLM-authored
// narrative.
//
// Modernization pass: filtered to confidence: high only (medium/low areas
// are real but noisier signal -- hidden here, not deleted from the
// underlying data), and split into side-by-side Drought / Wet-Flood
// columns for direct comparison, per request.
//
// priority score / risk score / hazard probability / vulnerability used to
// render as bare, unexplained numbers here -- unlike the map/table view,
// which already has a glossary (hazardRiskGlossary.js) for exactly these
// metrics. Reusing that same glossary via title tooltips instead of writing
// new copy, and showing risk_score's real classification (Very low..Very
// high, computed deterministically server-side by classify_risk_score --
// see app/api/hazard_risk_catalog_shared.py) inline, since that
// classification previously only surfaced buried inside the LLM's
// differentiator prose below, disconnected from the number it describes.
import {
  HAZARD_RISK_TERM_DEFINITIONS,
  POPULATION_EXPOSED_DEFINITION,
  PRIORITY_SCORE_DEFINITION,
} from "../../constants/hazardRiskGlossary.js";

function fnum(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return Number(value).toFixed(digits);
}

// supporting_indicators/contradicting_indicators are real {indicator,
// value, units} objects (see app/context/statistical_evidence.py's
// _indicator_evidence_objects) -- e.g. {"indicator": "rainfall_anomaly",
// "value": -47.2, "units": "%"} -- not bare name strings, so the real
// value that made each one match is visible here, not just its name.
function formatIndicatorEvidence(indicators) {
  if (!Array.isArray(indicators) || indicators.length === 0) {
    return "";
  }
  return indicators
    .map((entry) => {
      if (typeof entry === "string") {
        return entry;
      }
      const value = entry?.value;
      const units = entry?.units || "";
      const unitsText = units && units !== "%" ? ` ${units}` : units;
      const valueText = value === null || value === undefined ? "" : ` (${value}${unitsText})`;
      return `${entry?.indicator || ""}${valueText}`;
    })
    .join(", ");
}

function AreaCard({ item }) {
  const riskDefKey = item.hazard_type === "wet" ? "population_r_wet" : "population_r_drought";
  const probabilityDefKey = item.hazard_type === "wet" ? "p_wet" : "p_drought";
  const vulnerabilityDefKey = item.hazard_type === "wet" ? "v_wet" : "v_drought";

  return (
    <div className="ai-priority-justification-item">
      <div className="ai-priority-justification-head">
        <span className="ai-priority-rank">#{item.rank}</span>
        <strong>{item.area}</strong>
        {item.confidence && (
          <span className="ai-priority-confidence">confidence: {item.confidence}</span>
        )}
      </div>

      <div className="ai-priority-justification-stats">
        <span title={PRIORITY_SCORE_DEFINITION}>
          priority score {fnum(item.priority_score, 3)}
        </span>
        <span title={HAZARD_RISK_TERM_DEFINITIONS[riskDefKey]}>
          risk score {fnum(item.risk_score, 1)}
          {item.risk_class ? ` (${item.risk_class})` : ""}
        </span>
        <span title={HAZARD_RISK_TERM_DEFINITIONS[probabilityDefKey]}>
          hazard probability {fnum(item.hazard_probability, 2)}
        </span>
        <span title={HAZARD_RISK_TERM_DEFINITIONS[vulnerabilityDefKey]}>
          vulnerability {fnum(item.vulnerability, 2)}
        </span>
        {item.population_exposed_pct !== null && item.population_exposed_pct !== undefined && (
          <span title={POPULATION_EXPOSED_DEFINITION}>
            {fnum(item.population_exposed_pct, 1)}% population exposed
          </span>
        )}
      </div>

      {item.cross_indicator_signal && (
        <p className="ai-priority-supporting">
          Cross-indicator signal: <strong>{item.cross_indicator_signal.replace(/_/g, " ")}</strong>
          {item.cross_indicator_signal !== `strong_${item.hazard_type}` &&
            " (independent analysis -- may not align with this area's risk-based hazard type)"}
          {Array.isArray(item.supporting_indicators) && item.supporting_indicators.length > 0 &&
            ` · indicators: ${formatIndicatorEvidence(item.supporting_indicators)}`}
        </p>
      )}

      {item.differentiator && <p>{item.differentiator}</p>}
      {item.recommended_intervention_type && (
        <p className="ai-priority-intervention">
          Recommended intervention: {item.recommended_intervention_type}
        </p>
      )}
    </div>
  );
}

function PriorityAreaJustificationList({ items }) {
  if (!Array.isArray(items) || items.length === 0) {
    return null;
  }

  const highConfidenceItems = items.filter((item) => item.confidence === "high");
  const hiddenCount = items.length - highConfidenceItems.length;
  const droughtItems = highConfidenceItems.filter((item) => item.hazard_type === "drought");
  const wetItems = highConfidenceItems.filter((item) => item.hazard_type === "wet");

  return (
    <div className="ai-priority-panel">
      <div className="ai-priority-panel-head">
        <h3>Why priority areas were selected</h3>
        <span className="ai-priority-filter-note">
          Showing high-confidence areas only
          {hiddenCount > 0
            ? ` · ${hiddenCount} area${hiddenCount === 1 ? "" : "s"} hidden (medium/low confidence)`
            : ""}
        </span>
      </div>

      {highConfidenceItems.length === 0 ? (
        <p className="ai-priority-col-empty">No areas met the high-confidence threshold for this report.</p>
      ) : (
        <div className="ai-priority-columns">
          <div>
            <div className="ai-priority-col-head drought">
              <h4>Drought</h4>
              <span className="ai-priority-col-count">
                {droughtItems.length} area{droughtItems.length === 1 ? "" : "s"}
              </span>
            </div>
            {droughtItems.length === 0 ? (
              <p className="ai-priority-col-empty">No high-confidence drought areas.</p>
            ) : (
              droughtItems.map((item) => <AreaCard key={item.justification_id} item={item} />)
            )}
          </div>
          <div>
            <div className="ai-priority-col-head wet">
              <h4>Wet / Flood</h4>
              <span className="ai-priority-col-count">
                {wetItems.length} area{wetItems.length === 1 ? "" : "s"}
              </span>
            </div>
            {wetItems.length === 0 ? (
              <p className="ai-priority-col-empty">No high-confidence wet/flood areas.</p>
            ) : (
              wetItems.map((item) => <AreaCard key={item.justification_id} item={item} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default PriorityAreaJustificationList;
