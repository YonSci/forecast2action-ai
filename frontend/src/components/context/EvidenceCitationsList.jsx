// Renders the report's evidence_citations (see app/retrieval/citation_builder.py
// ::build_citation) -- the "Why this recommendation?" knowledge sources
// backing the report's actions, each traceable to a real knowledge_id,
// authority level, and version. Same visual pattern as AIMapInterpretation
// .jsx's own ReportList (a titled <ul> section), just for citation objects
// instead of plain strings.
function EvidenceCitationsList({ citations }) {
  if (!Array.isArray(citations) || citations.length === 0) {
    return null;
  }

  return (
    <div className="ai-report-section">
      <h4>Knowledge sources</h4>
      <ul>
        {citations.map((citation, index) => (
          <li key={citation.knowledge_id || index}>
            <strong>{citation.title || citation.knowledge_id}</strong>
            {citation.authority && ` (${citation.authority})`}
            {citation.source && ` — ${citation.source}`}
            {citation.evidence_passage && (
              <>
                <br />
                <small>{citation.evidence_passage}</small>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default EvidenceCitationsList;
