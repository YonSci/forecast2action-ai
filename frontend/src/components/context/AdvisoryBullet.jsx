// Shared bullet renderer for TimescaledAdvisoryList (farmer_advisory /
// agro_pastoral_advisory) and CategorizedHumanitarianList
// (humanitarian_priorities). Each bullet is a real structured object
// (area/action/trigger/evidence/cross_indicator_confidence -- see
// _ADVISORY_ITEM_SCHEMA in app/api/ai_map_interpretation.py), not a bare
// string -- renders the real area/trigger/evidence/cross_indicator_
// confidence as tags so a reader can see WHICH real area and evidence
// justify each bullet, not just its text. cross_indicator_confidence
// (renamed from the old generic "confidence") measures ONLY how strongly
// this area's climate indicators agree with each other -- see
// app.context.statistical_evidence._evaluate_area_signal. Still renders a
// bare string directly (a stale cached report from before this change),
// so nothing breaks for an older saved report.

function AdvisoryBullet({ item }) {
  if (typeof item === "string") {
    return <li>{item}</li>;
  }
  const areas = Array.isArray(item.area) ? item.area.filter(Boolean).join(", ") : item.area;
  const evidence = Array.isArray(item.evidence) ? item.evidence.filter(Boolean).join(", ") : item.evidence;
  return (
    <li className="ai-advisory-item">
      <span className="ai-advisory-action">{item.action}</span>
      <span className="ai-advisory-meta">
        {areas && <span className="ai-advisory-tag ai-advisory-area">{areas}</span>}
        {item.trigger && <span className="ai-advisory-tag ai-advisory-trigger">{item.trigger}</span>}
        {evidence && <span className="ai-advisory-tag ai-advisory-evidence">{evidence}</span>}
        {item.cross_indicator_confidence && (
          <span className={`ai-advisory-tag ai-advisory-confidence confidence-${item.cross_indicator_confidence}`}>
            {item.cross_indicator_confidence} cross-indicator confidence
          </span>
        )}
      </span>
    </li>
  );
}

export default AdvisoryBullet;
