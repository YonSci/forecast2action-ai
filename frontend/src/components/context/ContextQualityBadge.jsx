// Shows the Decision Context Envelope's quality_score + quality_flags
// (see app/context/validators.py::compute_quality_score) next to the
// AI report -- lets the user see at a glance whether the report is backed
// by real, complete evidence before trusting its content.
function formatFlag(flag) {
  return flag.replaceAll("_", " ");
}

function ContextQualityBadge({ contextInfo }) {
  if (!contextInfo?.quality) {
    return null;
  }

  const { score, flags } = contextInfo.quality;
  const percent = Math.round((score ?? 0) * 100);
  const tone = percent >= 80 ? "high" : percent >= 50 ? "medium" : "low";

  return (
    <div className={`context-quality-badge context-quality-${tone}`}>
      <span className="context-quality-score">Context quality: {percent}%</span>
      {Array.isArray(flags) && flags.length > 0 && (
        <span className="context-quality-flags">
          {flags.map(formatFlag).join(", ")}
        </span>
      )}
    </div>
  );
}

export default ContextQualityBadge;
