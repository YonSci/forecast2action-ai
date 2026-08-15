"""Dashboard chatbot -- a grounded Q&A assistant scoped to the SAME real,
deterministic evidence the 3-stage report pipeline already trusts (see
app.context.statistical_evidence, app.api.report_stages).

Deliberately NOT a general-purpose chatbot: every design decision in this
app's report pipeline exists to stop an LLM from inventing a number or a
comparison it wasn't given, and a free-form chat widget bolted on top would
undermine that discipline the moment a user asked it something. This
endpoint reuses the SAME evidence-building functions the report pipeline
uses, hands the model a compact real-evidence packet for the dashboard's
CURRENT period/selection, and applies the SAME forecast-safe-language
repair (app.advisory.response_validator) to its replies before they reach
the user.

Scope, confirmed with the user before building this: grounded-only (not
general knowledge), Gemini-only for v1 (no OpenRouter/OpenAI fallback yet
-- can be added later the same way report_stages/ai_map_interpretation
already do it, once this is proven out), stateless per-request (the
frontend holds conversation history and resends it, capped at
MAX_HISTORY_TURNS -- no server-side session store for a v1).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.ai_map_interpretation import (
    AIMapInterpretationRequest,
    ForecastSelection,
    GEMINI_MODEL_TIERS,
    ProviderError,
    compact_json,
    get_language_instruction,
    get_language_label,
    normalize_language_code,
    resolve_report_period,
)
from app.context.statistical_evidence import (
    area_signal_counts,
    build_national_region_evidence,
    build_structured_indicator_summaries,
    build_structured_layer_summaries,
)

router = APIRouter(prefix="/api/chat", tags=["Dashboard Chat Assistant"])

# Capped, not unlimited -- a real conversation resent in full on every
# message would otherwise grow the prompt unboundedly turn over turn.
MAX_HISTORY_TURNS = 10

# Fields from build_priority_area_justifications' own real per-area object
# actually useful for Q&A -- drops supporting_indicators/contradicting_
# indicators (verbose, already summarized by cross_indicator_signal) the
# same way report_stages._stage2_priority_area_view does for Stage 2.
_CHAT_PRIORITY_AREA_FIELDS = (
    "justification_id", "rank", "area", "hazard_type", "risk_score", "risk_class",
    "action_status", "hazard_probability", "vulnerability", "population_exposed_pct",
    "roads_length_total_km", "roads_length_exposed_km", "healthsites_total_count",
    "healthsites_exposed_count", "cropland_exposed_pct", "livestock_exposed_pct",
    "cross_indicator_signal", "cross_indicator_confidence", "data_quality_confidence",
    "low_sample_size_warning", "highest_among_group", "lowest_among_group",
)


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class DashboardChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = Field(default_factory=list)
    forecast_selection: ForecastSelection = Field(default_factory=ForecastSelection)
    # The area currently open in the dashboard's Selected Area Advisory
    # panel, if any -- lets the assistant default to answering about THAT
    # area when the question is ambiguous ("why is this a priority?").
    selected_area: Optional[str] = None
    target_language: Optional[str] = "en"


class DashboardChatResponse(BaseModel):
    reply: str
    period: str


def _compact_layer_or_indicator_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    """Drops the deterministic filler sentence (interpretation) -- real,
    but redundant once the model already has the real fields it was built
    from; keeps the chat context packet smaller without losing information.
    """
    return {key: value for key, value in item.items() if key != "interpretation"}


def _build_chat_context_packet(evidence: Dict[str, Any], selected_area: Optional[str]) -> Dict[str, Any]:
    """The real, deterministic evidence this endpoint is willing to let the
    model see -- same shape/spirit as report_stages._synthesis_evidence_
    packet, just built fresh here since the chat assistant's own Q&A needs
    don't match Stage 2's narrative-writing needs closely enough to share
    the exact same packet.
    """
    priority_areas = [
        {key: item.get(key) for key in _CHAT_PRIORITY_AREA_FIELDS}
        for item in evidence.get("priority_area_justifications") or []
        if isinstance(item, dict)
    ]
    packet: Dict[str, Any] = {
        "layer_summaries": [_compact_layer_or_indicator_summary(item) for item in build_structured_layer_summaries(evidence)],
        "indicator_summaries": [_compact_layer_or_indicator_summary(item) for item in build_structured_indicator_summaries(evidence)],
        "priority_areas": priority_areas,
        "national_cross_indicator": next(
            (item for item in evidence.get("cross_indicator_findings") or [] if item.get("area") == "National"),
            None,
        ),
        "area_signal_tally": area_signal_counts(evidence.get("cross_indicator_findings") or []),
    }
    if selected_area:
        packet["dashboard_selected_area"] = selected_area
    return packet


def _build_chat_system_prompt(period: str, language_code: str, context_packet: Dict[str, Any]) -> str:
    return f"""You are the Forecast2Action AI dashboard assistant, helping a decision-maker understand the {period} Ethiopia climate-risk forecast currently shown on their dashboard.

{get_language_instruction(language_code)}

STRICT GROUNDING RULE: You may ONLY answer using the real, already-computed evidence given below -- never invent, estimate, or guess a number, ranking, or comparison that isn't directly present in it. If a question can't be answered from this evidence (general knowledge, a different period, a different country, or anything requiring speculation), say so plainly and offer what you CAN answer instead -- never guess to seem helpful.

FORECAST-SAFE LANGUAGE: Everything below describes a FORECAST for {period}, not something that has already happened. Never say a hazard "has occurred," "was observed," or is "ongoing" -- describe it as forecast, projected, or expected.

SUPERLATIVE RULE: Only say an area has the "highest"/"lowest" value of a metric (hazard_probability, vulnerability, population_exposed_pct, risk_score) if that exact metric name appears in that area's own real highest_among_group/lowest_among_group list below -- you cannot reliably compare raw numbers across areas yourself.

NATIONAL VS AREA-LEVEL RULE: national_cross_indicator is its own real, independently-computed aggregate -- never describe it as "strong" just because several individual areas are; use area_signal_tally for any area-level count, and never count the priority_areas list yourself.

Keep answers conversational and concise (2-4 sentences) unless the user asks for more detail. If dashboard_selected_area is set below and the user's question doesn't name a specific area, assume they mean that one.

REAL EVIDENCE FOR {period.upper()}:
{compact_json(context_packet, max_chars=12000)}
""".strip()


def _call_gemini_chat_raw(model: str, system_prompt: str, history: List[Dict[str, str]], user_message: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ProviderError("GEMINI_API_KEY or GOOGLE_API_KEY is not set.")

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise ProviderError("Google Gen AI package is required. Run: pip install google-genai") from exc

    client = genai.Client(api_key=api_key)

    contents: List[Any] = []
    for turn in history:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=turn.get("content", ""))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

    config_kwargs = {
        "system_instruction": system_prompt,
        "temperature": float(os.getenv("AI_CHAT_TEMPERATURE", "0.3")),
        "top_p": float(os.getenv("AI_TOP_P", "0.8")),
        "max_output_tokens": int(os.getenv("AI_CHAT_MAX_TOKENS", "1024")),
    }
    try:
        response = client.models.generate_content(
            model=model, contents=contents, config=types.GenerateContentConfig(**config_kwargs),
        )
    except TypeError:
        # Older SDK versions may prefer a plain dict for config.
        response = client.models.generate_content(model=model, contents=contents, config=config_kwargs)

    return (response.text or "").strip()


@router.post("/message", response_model=DashboardChatResponse)
def post_chat_message(payload: DashboardChatRequest) -> DashboardChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty.")

    period = resolve_report_period(AIMapInterpretationRequest(forecast_selection=payload.forecast_selection))

    try:
        evidence = build_national_region_evidence(period.lower(), admin_level="admin1", use_cache=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load real evidence for period={period}: {exc}") from exc

    context_packet = _build_chat_context_packet(evidence, payload.selected_area)
    language_code = normalize_language_code(payload.target_language)
    system_prompt = _build_chat_system_prompt(period, language_code, context_packet)
    history = [turn.model_dump() for turn in payload.history[-MAX_HISTORY_TURNS:]]

    reply_text: Optional[str] = None
    last_error: Optional[Exception] = None
    for model in GEMINI_MODEL_TIERS["lite"]:
        if not model:
            continue
        try:
            reply_text = _call_gemini_chat_raw(model, system_prompt, history, payload.message)
            break
        except Exception as exc:  # noqa: BLE001 -- real provider errors vary by SDK/network, all equally "try next model"
            last_error = exc
            continue

    if not reply_text:
        raise HTTPException(status_code=502, detail=f"Chat assistant is unavailable right now: {last_error}")

    # Same deterministic forecast-safe-language repair the report pipeline
    # applies, reused directly rather than re-implemented -- a free-text
    # chat reply is exactly the kind of TEXT_FIELDS-shaped content these
    # functions were built to scan and rewrite in place.
    from app.advisory.response_validator import _repair_confirmed_language_in_text, _repair_observational_present_in_text

    reply_text, _ = _repair_confirmed_language_in_text(reply_text)
    reply_text, _ = _repair_observational_present_in_text(reply_text)

    return DashboardChatResponse(reply=reply_text, period=period)
