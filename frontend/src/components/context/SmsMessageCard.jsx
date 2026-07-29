// SMS-ready message card for report.sms_summary. Shows the real message
// alongside a real GSM-7 segment count (single SMS = 160 chars; messages
// over that split into 153-char segments because each segment needs a
// concatenation header) so whoever sends it knows the real cost/segment
// count before dispatch. Copy-only -- no "send" action, since no SMS
// gateway integration exists in this app.

const SINGLE_SEGMENT_LIMIT = 160;
const MULTI_SEGMENT_LIMIT = 153;

function segmentCount(length) {
  if (length === 0) {
    return 0;
  }
  if (length <= SINGLE_SEGMENT_LIMIT) {
    return 1;
  }
  return Math.ceil(length / MULTI_SEGMENT_LIMIT);
}

function SmsMessageCard({ text }) {
  if (!text) {
    return null;
  }

  const length = text.length;
  const segments = segmentCount(length);
  const overLimit = length > SINGLE_SEGMENT_LIMIT;

  return (
    <div className="ai-msg-card ai-sms-card">
      <div className="ai-msg-card-head">
        <span className="ai-msg-icon ai-sms-icon">&#128172;</span>
        <h4>SMS-ready message</h4>
      </div>
      <div className="ai-sms-bubble">{text}</div>
      <div className="ai-sms-meta">
        <span className={overLimit ? "ai-sms-over" : ""}>
          {length} / {SINGLE_SEGMENT_LIMIT} characters
          {overLimit ? ` · will send as ${segments} SMS segments` : ""}
        </span>
        <span>GSM-7 encoding</span>
      </div>
      <div className="ai-msg-actions">
        <button
          type="button"
          className="ai-secondary-action"
          onClick={() => navigator.clipboard?.writeText(text)}
        >
          Copy
        </button>
      </div>
    </div>
  );
}

export default SmsMessageCard;
