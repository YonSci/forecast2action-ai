// SMS-ready message card for report.sms_messages. Shows the real message
// alongside a real segment count. Amharic/Tigrinya render in Ethiopic
// script, which falls outside the GSM-7 alphabet and forces UCS-2 encoding
// (70 chars/segment, 67/segment once concatenated) -- using the GSM-7
// 160/153 figures for those 2 languages would understate the real SMS cost
// by more than 2x. English/Oromifa/Somali stay in the GSM-7 range.
// Copy-only -- no "send" action, since no SMS gateway integration exists
// in this app.

const UCS2_LANGUAGES = new Set(["am", "ti"]);

const ENCODING_LIMITS = {
  gsm7: { single: 160, multi: 153, label: "GSM-7 encoding" },
  ucs2: { single: 70, multi: 67, label: "UCS-2 encoding (Ethiopic script)" },
};

function segmentCount(length, limits) {
  if (length === 0) {
    return 0;
  }
  if (length <= limits.single) {
    return 1;
  }
  return Math.ceil(length / limits.multi);
}

function SmsMessageCard({ text, languageCode = "en" }) {
  if (!text) {
    return null;
  }

  const encoding = UCS2_LANGUAGES.has(languageCode) ? "ucs2" : "gsm7";
  const limits = ENCODING_LIMITS[encoding];
  const length = text.length;
  const segments = segmentCount(length, limits);
  const overLimit = length > limits.single;

  return (
    <div className="ai-msg-card ai-sms-card">
      <div className="ai-msg-card-head">
        <span className="ai-msg-icon ai-sms-icon">&#128172;</span>
        <h4>SMS-ready message</h4>
      </div>
      <div className="ai-sms-bubble">{text}</div>
      <div className="ai-sms-meta">
        <span className={overLimit ? "ai-sms-over" : ""}>
          {length} / {limits.single} characters
          {overLimit ? ` · will send as ${segments} SMS segments` : ""}
        </span>
        <span>{limits.label}</span>
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
