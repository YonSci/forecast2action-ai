import MethodologySteps from "./MethodologySteps.jsx";

function RasterMethodologyPanel({ methodology, sourceUrl }) {
  if (!methodology) {
    return null;
  }

  return (
    <div className="hazard-methodology-panel">
      <h4>{methodology.title}</h4>
      <MethodologySteps steps={methodology.steps} />
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noreferrer"
          className="hazard-methodology-source-link"
        >
          Full methodology reference ↗
        </a>
      )}
    </div>
  );
}

export default RasterMethodologyPanel;
