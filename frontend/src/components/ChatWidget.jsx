import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../config.js";
import { HAZARD_RISK_TERM_DEFINITIONS } from "../constants/hazardRiskGlossary.js";
import "../styles/chatWidget.css";

// Real audience vocabulary matching app/api/dashboard_chat.py's
// _AUDIENCE_INSTRUCTIONS keys (confirmed against data/knowledge/
// action_library.json, not the "Disaster Risk Manager"/etc labels from
// this project's own old, superseded README).
const AUDIENCE_OPTIONS = [
  { value: "", label: "General" },
  { value: "disaster_manager", label: "Disaster manager" },
  { value: "extension_officer", label: "Extension officer" },
  { value: "ngo_planner", label: "NGO planner" },
];

const MAX_HISTORY_TURNS = 10;

// Persists the conversation across a page refresh -- capped, not
// unlimited, so a long-lived tab doesn't grow localStorage forever.
const STORAGE_KEY = "f2a-chat-history";
const MAX_STORED_MESSAGES = 40;

function loadStoredMessages() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveStoredMessages(messages) {
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(messages.slice(-MAX_STORED_MESSAGES)),
    );
  } catch {
    // Storage full/unavailable (private browsing, quota) -- the
    // conversation just won't survive a refresh; not worth surfacing.
  }
}

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

// Real local device time, not a server round-trip -- a greeting doesn't
// need to be grounded in anything, so this stays a plain client-side
// function rather than a backend field.
function getTimeBasedGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
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

// Shown under the LAST assistant reply only (not every past one) once a
// real conversation is underway -- a grounded-only assistant otherwise
// relies on the user guessing what's in scope after the first answer.
function getFollowUpQuestions(selectedPriorityArea) {
  const areaName = selectedPriorityArea?.area_name;
  const questions = areaName
    ? [
        `Compare ${areaName} to last period`,
        `What should be done about this?`,
        `Give me an SMS-ready version`,
      ]
    : ["What's changed since last period?", "What should be done about this?"];
  return questions.slice(0, 3);
}

// Real glossary terms (frontend/src/constants/hazardRiskGlossary.js --
// already used elsewhere on the dashboard for the same real definitions),
// phrased as natural questions the grounded assistant can actually answer
// via its own METHODOLOGY REFERENCE block -- not invented terminology.
const GLOSSARY_CHIP_LAYERS = [
  "population_risk_class",
  "v_drought",
  "p_drought",
];
function getGlossaryQuestions() {
  return GLOSSARY_CHIP_LAYERS.filter(
    (layer) => HAZARD_RISK_TERM_DEFINITIONS[layer],
  ).map((layer) => `What does ${layer} mean?`);
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
      <path
        d="M6 6l12 12M18 6L6 18"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconSend() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 11l17-8-8 17-2-7-7-2z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconClearChat() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 7h14M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m2 0-.7 12.1a2 2 0 01-2 1.9H8.7a2 2 0 01-2-1.9L6 7h12z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
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
function ChatWidget({
  forecastSelection,
  selectedPriorityArea,
  selectedLanguage,
  aiReport,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState(loadStoredMessages);
  const [input, setInput] = useState("");
  const [audience, setAudience] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  useEffect(() => {
    saveStoredMessages(messages);
  }, [messages]);

  // Keyboard shortcut ("/") to open the assistant, matching the common
  // search-shortcut convention -- guarded against firing while the user is
  // already typing anywhere else on the page (an input/textarea/
  // contenteditable), so it never steals a literal "/" keystroke.
  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key !== "/" || isOpen) return;
      const target = event.target;
      const isTyping =
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable;
      if (isTyping) return;
      event.preventDefault();
      setIsOpen(true);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  function clearChatHistory() {
    setMessages([]);
    setError("");
    window.localStorage.removeItem(STORAGE_KEY);
  }

  function updateLastAssistantMessage(patch) {
    setMessages((current) => {
      const updated = [...current];
      const lastIndex = updated.length - 1;
      if (lastIndex >= 0 && updated[lastIndex].role === "assistant") {
        updated[lastIndex] = { ...updated[lastIndex], ...patch };
      }
      return updated;
    });
  }

  async function sendText(text) {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;

    const nextMessages = [...messages, { role: "user", content: trimmed }];
    setMessages([
      ...nextMessages,
      { role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setIsSending(true);
    setError("");

    const reportContext = aiReport
      ? {
          executive_summary: aiReport.executive_summary || null,
          national_spatial_overview: aiReport.national_spatial_overview || null,
          compound_hazard_interpretation:
            aiReport.compound_hazard_interpretation || null,
        }
      : null;

    const requestBody = JSON.stringify({
      message: trimmed,
      history: nextMessages.slice(0, -1).slice(-MAX_HISTORY_TURNS),
      forecast_selection: forecastSelection,
      selected_area: selectedPriorityArea?.area_name || null,
      target_language: selectedLanguage || "en",
      report_context: reportContext,
      audience: audience || null,
    });

    let receivedAnything = false;
    try {
      const response = await fetch(apiUrl("/api/chat/stream"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: requestBody,
      });
      if (!response.ok || !response.body) {
        const detail = await response.text();
        throw new Error(detail || `Request failed ${response.status}`);
      }

      // Real Server-Sent-Events parsing: the network doesn't guarantee
      // chunk boundaries line up with SSE event boundaries, so incoming
      // bytes are buffered and split on the real "\n\n" event delimiter,
      // not assumed to arrive as one event per read().
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accumulated = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const line = rawEvent.startsWith("data: ")
            ? rawEvent.slice(6)
            : rawEvent;
          boundary = buffer.indexOf("\n\n");
          if (!line.trim()) continue;

          let payload;
          try {
            payload = JSON.parse(line);
          } catch {
            continue;
          }

          if (payload.error) {
            throw new Error(payload.error);
          }
          if (payload.delta) {
            receivedAnything = true;
            accumulated += payload.delta;
            updateLastAssistantMessage({
              content: accumulated,
              streaming: true,
            });
          }
          if (payload.done) {
            // The server re-runs the SAME forecast-safe-language repair
            // /message applies against the full accumulated text -- the
            // streamed preview above is provisional; final_reply is the
            // one actually committed, even if it differs (rare).
            updateLastAssistantMessage({
              content: payload.final_reply,
              contextSummary: payload.context_summary,
              streaming: false,
            });
          }
        }
      }
    } catch (err) {
      setError(
        "The assistant is unavailable right now. Please try again in a moment.",
      );
      console.error(err);
      if (!receivedAnything) {
        // Never got any real content -- drop the empty placeholder bubble
        // rather than leaving a blank assistant turn in the transcript.
        setMessages((current) => current.slice(0, -1));
      }
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
                {selectedPriorityArea?.area_name
                  ? ` — ${selectedPriorityArea.area_name} selected`
                  : ""}
              </span>
            </div>
            <div className="f2a-chat-panel-head-actions">
              {messages.length > 0 && (
                <button
                  type="button"
                  className="f2a-chat-icon-btn"
                  onClick={clearChatHistory}
                  aria-label="Clear chat history"
                  title="Clear chat history"
                >
                  <IconClearChat />
                </button>
              )}
              <button
                type="button"
                className="f2a-chat-icon-btn"
                onClick={() => setIsOpen(false)}
                aria-label="Close chat"
              >
                <IconClose />
              </button>
            </div>
          </div>

          <div
            className="f2a-chat-messages"
            ref={scrollRef}
            role="log"
            aria-live="polite"
          >
            {messages.length === 0 && (
              <div className="f2a-chat-empty">
                <p className="f2a-chat-greeting">
                  {getTimeBasedGreeting()}! I'm your AI assistant, how can I
                  help you today?
                </p>
                {/* <p>
                  Ask about the priority areas, risk drivers, or exposure
                  numbers currently shown on this dashboard.
                </p> */}
                <div className="f2a-chat-starters">
                  {getStarterQuestions(selectedPriorityArea).map((question) => (
                    <button
                      key={question}
                      type="button"
                      onClick={() => sendText(question)}
                      disabled={isSending}
                    >
                      {question}
                    </button>
                  ))}
                  {getGlossaryQuestions().map((question) => (
                    <button
                      key={question}
                      type="button"
                      className="f2a-chat-starter-glossary"
                      onClick={() => sendText(question)}
                      disabled={isSending}
                    >
                      {question}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => {
              const isLast = index === messages.length - 1;
              const showFollowUps =
                isLast &&
                message.role === "assistant" &&
                !message.streaming &&
                !isSending;
              return (
                <div key={index}>
                  <div
                    className={`f2a-chat-bubble f2a-chat-bubble-${message.role}`}
                  >
                    {message.streaming && !message.content ? (
                      <span className="f2a-chat-typing-dots">Thinking…</span>
                    ) : (
                      renderInlineMarkdown(message.content)
                    )}
                    {message.streaming && message.content && (
                      <span className="f2a-chat-cursor" aria-hidden="true" />
                    )}
                  </div>
                  {showFollowUps && (
                    <div className="f2a-chat-starters f2a-chat-followups">
                      {getFollowUpQuestions(selectedPriorityArea).map(
                        (question) => (
                          <button
                            key={question}
                            type="button"
                            onClick={() => sendText(question)}
                          >
                            {question}
                          </button>
                        ),
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {error && <div className="f2a-chat-error">{error}</div>}

          <div className="f2a-chat-audience-row">
            <label htmlFor="f2a-chat-audience">Answering as</label>
            <select
              id="f2a-chat-audience"
              value={audience}
              onChange={(event) => setAudience(event.target.value)}
              disabled={isSending}
            >
              {AUDIENCE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <form className="f2a-chat-input-row" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about this period's forecast…"
              disabled={isSending}
            />
            <button
              type="submit"
              className="f2a-chat-icon-btn f2a-chat-send"
              disabled={isSending || !input.trim()}
              aria-label="Send"
            >
              <IconSend />
            </button>
          </form>
        </div>
      )}

      <button
        type="button"
        className="f2a-chat-fab"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={
          isOpen ? "Close dashboard assistant" : "Open dashboard assistant"
        }
        title={isOpen ? undefined : "Open dashboard assistant (/)"}
      >
        {isOpen ? <IconClose /> : <IconChatBubble />}
      </button>
    </div>
  );
}

export default ChatWidget;
