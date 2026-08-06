// Shared bullet renderer for TimescaledAdvisoryList (farmer_advisory /
// agro_pastoral_advisory) and CategorizedHumanitarianList
// (humanitarian_priorities). Each bullet is a real structured object
// (area/action/trigger/evidence/confidence -- see _ADVISORY_ITEM_SCHEMA in
// app/api/ai_map_interpretation.py), not a bare string -- renders the real
// area/trigger/evidence/confidence as tags so a reader can see WHICH real
// area and evidence justify each bullet, not just its text. Still renders
// a bare string directly (a stale cached report from before this change),
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
        {item.confidence && (
          <span className={`ai-advisory-tag ai-advisory-confidence confidence-${item.confidence}`}>
            {item.confidence} confidence
          </span>
        )}
      </span>
    </li>
  );
}

export default AdvisoryBullet;
