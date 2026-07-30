import {
  getMethodologyForLayer,
  RASTER_METHODOLOGY_SOURCE_URL,
} from "../constants/rasterMethodology.js";

function RasterMethodologyPanel({ category, layerValue }) {
  const methodology = getMethodologyForLayer(category, layerValue);

  if (!methodology) {
    return null;
  }

  return (
    <div className="hazard-methodology-panel">
      <h4>{methodology.title}</h4>
      <ol className="hazard-methodology-steps">
        {methodology.steps.map((step) => (
          <li key={step.title}>
            <span className="hazard-methodology-step-title">{step.title}</span>
            {(step.formulas || []).map((formula) => (
              <code key={formula} className="hazard-methodology-formula">
                {formula}
              </code>
            ))}
            {step.list && (
              <ul className="hazard-methodology-indicator-list">
                {step.list.map((entry) => (
                  <li key={entry}>{entry}</li>
                ))}
              </ul>
            )}
            {step.table && (
              <table className="hazard-methodology-table">
                <tbody>
                  {step.table.map((row) => (
                    <tr key={row[0]}>
                      <td>{row[0]}</td>
                      <td>{row[1]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {step.note && <p className="hazard-methodology-note">{step.note}</p>}
          </li>
        ))}
      </ol>
      <a
        href={RASTER_METHODOLOGY_SOURCE_URL}
        target="_blank"
        rel="noreferrer"
        className="hazard-methodology-source-link"
      >
        Full methodology reference ↗
      </a>
    </div>
  );
}

export default RasterMethodologyPanel;
