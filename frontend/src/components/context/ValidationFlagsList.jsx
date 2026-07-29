// Renders report._metadata.validation_flags (see
// app/advisory/response_validator.py::validate_against_evidence, run
// unconditionally for every staged report). Detect-and-flag, not
// block-and-fail -- a real provider may still occasionally invent a name
// or misquote a number despite the grounding rules in the system prompt,
// so these flags exist to make that visible to whoever reviews the
// report, rather than leaving it silently undetected.

function ValidationFlagsList({ flags }) {
  if (!Array.isArray(flags) || flags.length === 0) {
    return null;
  }

  return (
    <div className="ai-validation-flags">
      <h4>Validation flags</h4>
      <p className="ai-validation-flags-note">
        Automated checks against the real computed evidence found the
        following. This does not block the report -- review these sections
        before relying on them.
      </p>
      <ul>
        {flags.map((flag, index) => (
          <li key={index}>{flag}</li>
        ))}
      </ul>
    </div>
  );
}

export default ValidationFlagsList;
