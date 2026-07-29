// WhatsApp-ready message card. IMPORTANT: there is no separate backend
// "whatsapp message" field -- this reformats the SAME report.sms_summary
// text on the frontend into WhatsApp's real markdown (*bold*, _italic_)
// and renders a live preview of how it would actually look once sent. If
// WhatsApp messaging should ever carry different CONTENT than SMS (not
// just different formatting), that needs a real backend field.

const BOLD_PATTERNS = [
  /-?\d+(\.\d+)?%/g, // percentages, e.g. -53.74%
  /SPI[^0-9-]{0,12}-?\d+(\.\d+)?/gi, // SPI values, tolerant of phrasing like "SPI of -1.12" or "SPI: -1.12"
  /\d+(\.\d+)?\s*(?:mm|days?)\b/gi, // rainfall (mm) / day counts
];

function formatForWhatsApp(text) {
  if (!text) {
    return "";
  }

  // Many real sms_summary strings (both LLM-generated and the deterministic
  // fallback) follow an "ALERT LABEL: rest of message" pattern -- split on
  // the first colon within a short prefix window to pull that out as a
  // bold header, rather than trying to parse deeper semantic structure
  // (which wouldn't generalize to arbitrary free-form text).
  const colonIndex = text.indexOf(":");
  let header = "";
  let body = text;
  if (colonIndex > 0 && colonIndex < 80) {
    header = text.slice(0, colonIndex).trim();
    body = text.slice(colonIndex + 1).trim();
  }

  let formattedBody = body;
  for (const pattern of BOLD_PATTERNS) {
    formattedBody = formattedBody.replace(pattern, (match) => `*${match}*`);
  }

  const sentences = formattedBody.split(/(?<=[.;])\s+/).filter(Boolean);
  const bodyText = sentences.join("\n\n");

  return header ? `\u{1F6A8} *${header}*\n\n${bodyText}` : bodyText;
}

function renderFormattedLine(line, lineIndex) {
  const parts = line.split(/(\*[^*]+\*|_[^_]+_)/g).filter((part) => part !== "");
  return (
    <span key={lineIndex}>
      {parts.map((part, index) => {
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return <strong key={index}>{part.slice(1, -1)}</strong>;
        }
        if (part.startsWith("_") && part.endsWith("_") && part.length > 2) {
          return <em key={index}>{part.slice(1, -1)}</em>;
        }
        return part;
      })}
    </span>
  );
}

function WhatsAppMessageCard({ text }) {
  if (!text) {
    return null;
  }

  const formatted = formatForWhatsApp(text);
  const lines = formatted.split("\n");

  return (
    <div className="ai-msg-card ai-wa-card">
      <div className="ai-msg-card-head">
        <span className="ai-msg-icon ai-wa-icon">&#128241;</span>
        <h4>WhatsApp-ready message</h4>
      </div>
      <div className="ai-wa-phone">
        <div className="ai-wa-bubble">
          {lines.map((line, index) =>
            line === "" ? <br key={index} /> : (
              <div key={index}>{renderFormattedLine(line, index)}</div>
            ),
          )}
          <div className="ai-wa-time">
            {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            <span className="ai-wa-check">&#10003;&#10003;</span>
          </div>
        </div>
      </div>
      <div className="ai-msg-actions">
        <button
          type="button"
          className="ai-secondary-action"
          onClick={() => navigator.clipboard?.writeText(formatted)}
        >
          Copy
        </button>
      </div>
    </div>
  );
}

export default WhatsAppMessageCard;
