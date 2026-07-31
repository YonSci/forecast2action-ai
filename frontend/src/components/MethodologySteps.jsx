// Shared step-list renderer for a methodology entry's `steps` array
// (title/formulas/list/table/note per step) -- used by both
// RasterMethodologyPanel.jsx (compact map-legend sidebar) and the
// TechnicalDocumentation.jsx page (full reference), so the two never
// drift out of sync with each other.
function MethodologySteps({ steps }) {
  return (
    <ol className="hazard-methodology-steps">
      {steps.map((step) => (
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
  );
}

export default MethodologySteps;
