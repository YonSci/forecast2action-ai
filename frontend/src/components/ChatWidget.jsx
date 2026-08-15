import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../config.js";
import "../styles/chatWidget.css";

const MAX_HISTORY_TURNS = 10;

// Lightweight inline-markdown rendering for chat replies -- the model
// naturally writes **bold** around key numbers/labels and `code` around
// field names (both providers do this unprompted), but the bubble was
// rendering that literally as asterisks/backticks instead of formatting
// it. No markdown library dependency: just bold + inline code, split on a
// single capturing regex so the surrounding plain text (and real newlines,
// preserved by the bubble's own white-space: pre-wrap) passes through
// untouched.
const INLINE_MARKDOWN_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`)/g;

function renderInlineMarkdown(text) {
  return text.split(INLINE_MARKDOWN_PATTERN).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

// Real, deterministic "grounded in" caption from the backend's own
// context_summary (see app/api/dashboard_chat.py's _build_context_summary)
// -- describes what evidence was actually available for that reply, not a
// guess about which sentences the model drew on.
function renderContextSummary(summary) {
  if (!summary) return null;
  const parts = [];
  if (summary.priority_area_count) {
    parts.push(`${summary.priority_area_count} priority areas`);
  }
  if (summary.national_cross_indicator_signal) {
    parts.push(`national signal: ${summary.national_cross_indicator_signal.replace(/_/g, " ")}`);
  }
  if (summary.selected_area) {
    parts.push(`focused on ${summary.selected_area}`);
  }
  if (summary.community_reports_areas?.length) {
    parts.push(`community reports: ${summary.community_reports_areas.join(", ")}`);
  }
  if (summary.included_report_narrative) {
    parts.push("generated report narrative included");
  }
  if (!parts.length) return null;
  return <div className="f2a-chat-context-summary">Grounded in: {parts.join(" · ")}</div>;
}

function getStarterQuestions(selectedPriorityArea) {
  const areaName = selectedPriorityArea?.area_name;
  const questions = [];
  if (areaName) {
    questions.push(`Why is ${areaName} a priority this period?`);
    questions.push(`Are there community reports for ${areaName}?`);
  }
  questions.push("What are the top drought priority areas?");
  questions.push("What's the national risk signal this period?");
  return questions.slice(0, 4);
}

function IconChatBubble() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 5h16a1 1 0 011 1v10a1 1 0 01-1 1H9l-4.4 3.3A.6.6 0 013 19.8V6a1 1 0 011-1z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconClose() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function IconSend() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3 11l17-8-8 17-2-7-7-2z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Floating chat widget for the Dashboard -- grounded strictly in this
 * period's real, already-computed evidence (see app/api/dashboard_chat.py),
 * never a general-purpose assistant. Sends the dashboard's own current
 * forecastSelection/selectedPriorityArea as context on every message, so
 * the assistant answers about what the user is actually looking at. When
 * aiReport is set (the user has generated a report this session), its real
 * narrative fields are sent too so the assistant can summarize/quote it.
 */
function ChatWidget({ forecastSelection, selectedPriorityArea, selectedLanguage, aiReport }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  async function sendText(text) {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;

    const nextMessages = [...messages, { role: "user", content: trimmed }];
    setMessages(nextMessages);
    setInput("");
    setIsSending(true);
    setError("");

    const reportContext = aiReport
      ? {
          executive_summary: aiReport.executive_summary || null,
          national_spatial_overview: aiReport.national_spatial_overview || null,
          compound_hazard_interpretation: aiReport.compound_hazard_interpretation || null,
        }
      : null;

    try {
      const response = await fetch(apiUrl("/api/chat/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          history: nextMessages.slice(0, -1).slice(-MAX_HISTORY_TURNS),
          forecast_selection: forecastSelection,
          selected_area: selectedPriorityArea?.area_name || null,
          target_language: selectedLanguage || "en",
          report_context: reportContext,
        }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed ${response.status}`);
      }
      const data = await response.json();
      setMessages([
        ...nextMessages,
        { role: "assistant", content: data.reply, contextSummary: data.context_summary },
      ]);
    } catch (err) {
      setError("The assistant is unavailable right now. Please try again in a moment.");
      console.error(err);
    } finally {
      setIsSending(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    sendText(input);
  }

  return (
    <div className="f2a-chat-root">
      {isOpen && (
        <div className="f2a-chat-panel">
          <div className="f2a-chat-panel-head">
            <div>
              <strong>Dashboard assistant</strong>
              <span>
                Grounded in this period's real evidence
                {selectedPriorityArea?.area_name ? ` — ${selectedPriorityArea.area_name} selected` : ""}
              </span>
            </div>
            <button type="button" className="f2a-chat-icon-btn" onClick={() => setIsOpen(false)} aria-label="Close chat">
              <IconClose />
            </button>
          </div>

          <div className="f2a-chat-messages" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="f2a-chat-empty">
                <p>Ask about the priority areas, risk drivers, or exposure numbers currently shown on this dashboard.</p>
                <div className="f2a-chat-starters">
                  {getStarterQuestions(selectedPriorityArea).map((question) => (
                    <button key={question} type="button" onClick={() => sendText(question)} disabled={isSending}>
                      {question}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`f2a-chat-bubble f2a-chat-bubble-${message.role}`}>
                {renderInlineMarkdown(message.content)}
                {message.role === "assistant" && renderContextSummary(message.contextSummary)}
              </div>
            ))}
            {isSending && <div className="f2a-chat-bubble f2a-chat-bubble-assistant f2a-chat-typing">Thinking…</div>}
          </div>

          {error && <div className="f2a-chat-error">{error}</div>}

          <form className="f2a-chat-input-row" onSubmit={handleSubmit}>
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about this period's forecast…"
              disabled={isSending}
            />
            <button type="submit" className="f2a-chat-icon-btn f2a-chat-send" disabled={isSending || !input.trim()} aria-label="Send">
              <IconSend />
            </button>
          </form>
        </div>
      )}

      <button
        type="button"
        className="f2a-chat-fab"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={isOpen ? "Close dashboard assistant" : "Open dashboard assistant"}
      >
        {isOpen ? <IconClose /> : <IconChatBubble />}
      </button>
    </div>
  );
}

export default ChatWidget;
