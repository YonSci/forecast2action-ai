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
general knowledge), stateless per-request (the frontend holds conversation
history and resends it, capped at MAX_HISTORY_TURNS -- no server-side
session store for a v1).

Provider fallback (see _chat_provider_attempts): tries Gemini's lite tier
first, then plain OpenAI, then OpenRouter -- confirmed necessary, not
theoretical: the deployed Render backend has GEMINI_API_KEY unset but
OPENAI_API_KEY configured (per /api/ai/provider-status), so a Gemini-only
first version of this endpoint returned 502 there on every real request
even though report generation worked fine. Each provider's raw call is
free-text/multi-turn, NOT the JSON-schema-mode calls app.api.
ai_map_interpretation's own report-pipeline functions make, so this module
has its own small set of raw-call primitives rather than reusing those.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, NamedTuple, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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
from app.api.report_stages import CLASSIFICATION_METHOD_LEGEND, _risk_definition_block
from app.api.seasonal_catalog_shared import PERIODS
from app.context.community_context import build_community_evidence_by_region
from app.context.knowledge_context import build_knowledge_context
from app.context.statistical_evidence import (
    INDICATOR_DEFINITIONS,
    area_signal_counts,
    build_national_region_evidence,
    build_structured_indicator_summaries,
    build_structured_layer_summaries,
)

router = APIRouter(prefix="/api/chat", tags=["Dashboard Chat Assistant"])

# Capped, not unlimited -- a real conversation resent in full on every
# message would otherwise grow the prompt unboundedly turn over turn.
MAX_HISTORY_TURNS = 10

# Per-section prompt budgets, shared between _build_chat_system_prompt (what
# actually gets sent) and _build_context_summary (what the citation is
# allowed to claim) so the two can never drift apart -- real measured sizes
# for a typical period: layer+indicator summaries ~9.1k, priority_areas
# ~8.4k, community reports ~0.9k; each budget below has real headroom above
# that, not the single shared 12000-char pool this used to be (see
# _build_chat_system_prompt's own docstring for the real bug that caused).
_NATIONAL_INDICATORS_MAX_CHARS = 12000
_PRIORITY_AREAS_MAX_CHARS = 14000
_COMMUNITY_REPORTS_MAX_CHARS = 6000
_COMPARISON_PERIOD_MAX_CHARS = 4000

# Real, canonical seasonal period names this app's own raster catalog
# actually serves (app.api.seasonal_catalog_shared.PERIODS) -- not a
# separately-invented list, so a period this endpoint tries to compare
# against is always one build_national_region_evidence can genuinely serve.
_COMPARABLE_PERIODS = [p["value"] for p in PERIODS]
_PERIOD_MENTION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _COMPARABLE_PERIODS) + r")\b", re.IGNORECASE,
)
# Cross-period comparison is a real feature, not unlimited -- capping how
# many EXTRA periods one message can pull in keeps a message that happens
# to mention every month from quadrupling the prompt size.
_MAX_COMPARISON_PERIODS = 2
_MAX_OTHER_AREAS = 3
_COMPARISON_AREA_MAX_CHARS = 2500

# Real audience vocabulary from data/knowledge/action_library.json (confirmed
# by reading the file directly, NOT the "Disaster Risk Manager"/"NGO
# Anticipatory Action Planner"/etc labels from this project's own OLD,
# superseded README -- that document described a much earlier prototype and
# those labels don't exist anywhere in the current app). "general" is this
# endpoint's own neutral default (no audience selected), distinct from the
# library's internal "any" match-everything marker.
_AUDIENCE_INSTRUCTIONS = {
    "disaster_manager": "Answer as if briefing a Disaster Risk Management office coordinator -- prioritize operational thresholds, coordination triggers, and response readiness over general explanation.",
    "extension_officer": "Answer as if briefing an agriculture/livestock extension officer -- prioritize practical, field-level guidance relevant to farmers and agro-pastoral communities.",
    "ngo_planner": "Answer as if briefing an NGO/anticipatory-action planner -- prioritize early-action triggers, pre-positioning needs, and humanitarian relevance.",
}
# Maps a chat audience selection to the action_library's own real audience
# value for retrieval (see _maybe_build_action_guidance) -- "general"/None
# retrieves with "any" rather than narrowing to one real audience's actions.
_AUDIENCE_TO_LIBRARY_VALUE = {
    "disaster_manager": "disaster_manager",
    "extension_officer": "extension_officer",
    "ngo_planner": "ngo_planner",
}

# Deterministic, keyword-based action-intent detection (not an LLM guess) --
# only retrieves from the real action-guidance knowledge base when the
# question actually looks like an action question, so a plain "why" question
# doesn't get padded with unrelated retrieved guidance.
_ACTION_INTENT_PATTERN = re.compile(
    r"\b(what should|what can|what to do|recommend(?:ation)?s?|what action|"
    r"how (?:should|can|do) .*(?:respond|prepare)|early action|response plan)\b",
    re.IGNORECASE,
)

# Real action_status -> action_library risk_level mapping. action_status is
# already a real, deterministic tier (see app.context.statistical_evidence.
# _action_status): "action" means risk_class is High/Very high (or Moderate
# with agreeing cross-indicator signal) -- the same real urgency a "trigger"
# risk_level represents in the action library. "preparedness" maps to
# "warning" (elevated but not yet at trigger threshold); anything else
# (monitor_only/not_actionable) maps to "watch" (library's lowest tier) --
# this app never asks the library for the risk_level of forecast is very low.
_ACTION_STATUS_TO_RISK_LEVEL = {"action": "trigger", "preparedness": "warning"}

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


class ReportContext(BaseModel):
    """The real, already-generated (and already response_validator-checked)
    report narrative, if the user has generated one this session -- sent by
    the client because, unlike evidence, this text only exists client-side
    (no server-side "last generated report" store to recompute it from).
    Deliberately narrow to the 3 free-text narrative fields, not the whole
    report schema -- priority_area_justification/etc are already
    reconstructed server-side from the SAME real evidence this endpoint
    trusts, so re-sending them here would just be an unverified duplicate
    of data already available a more trustworthy way.
    """

    executive_summary: Optional[str] = None
    national_spatial_overview: Optional[List[str]] = None
    compound_hazard_interpretation: Optional[List[str]] = None


class DashboardChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = Field(default_factory=list)
    forecast_selection: ForecastSelection = Field(default_factory=ForecastSelection)
    # The area currently open in the dashboard's Selected Area Advisory
    # panel, if any -- lets the assistant default to answering about THAT
    # area when the question is ambiguous ("why is this a priority?").
    selected_area: Optional[str] = None
    target_language: Optional[str] = "en"
    report_context: Optional[ReportContext] = None
    # One of _AUDIENCE_INSTRUCTIONS' real keys ("disaster_manager",
    # "extension_officer", "ngo_planner"), or None/"general" for no
    # audience-specific framing -- any other value is treated as unset
    # rather than raising, since this only changes tone, never grounding.
    audience: Optional[str] = None


class DashboardChatResponse(BaseModel):
    reply: str
    period: str
    # Real, deterministic description of what was actually given to the
    # model for THIS message -- not a claim about which sentences it used,
    # just an honest accounting of the real evidence sections available.
    # Rendered in the UI as a "grounded in" citation under the reply.
    context_summary: Dict[str, Any]


def _compact_layer_or_indicator_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    """Drops the deterministic filler sentence (interpretation) -- real,
    but redundant once the model already has the real fields it was built
    from; keeps the chat context packet smaller without losing information.
    """
    return {key: value for key, value in item.items() if key != "interpretation"}


def _build_chat_context_packet(
    evidence: Dict[str, Any],
    selected_area: Optional[str],
    community_evidence: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
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
    if community_evidence:
        # Only ever present for a real region name -- "not in this dict"
        # already means "no reports" (see build_community_evidence_by_
        # region's own docstring), so no empty-entry padding here either.
        packet["community_ground_truth_by_area"] = community_evidence
    return packet


def _detect_comparison_periods(message: str, history: List[Dict[str, str]], current_period: str) -> List[str]:
    """Real, deterministic period-name detection (regex word-match against
    app.api.seasonal_catalog_shared.PERIODS' own canonical values) -- not an
    LLM guessing which periods the user means. Scans the current message
    plus the last few history turns (a user might say "compare July" then,
    next turn, "...to August" -- the mention could be a turn or two back).
    Deliberately capped at _MAX_COMPARISON_PERIODS so a message that happens
    to mention every month doesn't multiply the prompt size unboundedly.
    """
    recent_text = message + " " + " ".join(turn.get("content", "") for turn in history[-4:])
    mentioned = {match.upper() if match.upper() == "JJAS" else match.title() for match in _PERIOD_MENTION_PATTERN.findall(recent_text)}
    extra = [period for period in _COMPARABLE_PERIODS if period in mentioned and period.lower() != current_period.lower()]
    return extra[:_MAX_COMPARISON_PERIODS]


def _build_comparison_period_packet(period: str, selected_area: Optional[str]) -> Optional[Dict[str, Any]]:
    """Compact, real evidence for an OTHER period the user mentioned, for
    cross-period comparison only -- deliberately much smaller than the
    primary period's own packet (just the national aggregate, plus one
    area's record if the dashboard has a selected area, or the real top-3-
    ranked areas per hazard type otherwise) since a comparison question is
    normally about one area or the national picture, not a full re-dump of
    every area for a second period. Returns None if this period genuinely
    has no real underlying raster data (build_national_region_evidence
    raises/degrades for a period this app's catalog doesn't actually serve)
    -- the caller skips it rather than sending the model a broken packet.
    """
    try:
        evidence = build_national_region_evidence(period.lower(), admin_level="admin1", use_cache=True)
    except Exception:
        return None

    packet: Dict[str, Any] = {
        "national_cross_indicator": next(
            (item for item in evidence.get("cross_indicator_findings") or [] if item.get("area") == "National"),
            None,
        ),
    }
    priority_areas = evidence.get("priority_area_justifications") or []
    if selected_area:
        match = next((item for item in priority_areas if item.get("area") == selected_area), None)
        if match:
            packet["selected_area_record"] = {key: match.get(key) for key in _CHAT_PRIORITY_AREA_FIELDS}
    else:
        packet["top_ranked_areas"] = [
            {key: item.get(key) for key in _CHAT_PRIORITY_AREA_FIELDS}
            for item in priority_areas
            if isinstance(item.get("rank"), int) and item["rank"] <= 3
        ]
    return packet


def _real_admin1_area_names(evidence: Dict[str, Any]) -> List[str]:
    """Every real admin1 region name this period's evidence actually covers
    -- cross_indicator_findings includes ALL real regions (see
    app.context.statistical_evidence.build_cross_indicator_findings, which
    iterates every region with real raster coverage), not just the top-
    ranked ones priority_areas is limited to. This is the real, authoritative
    list _detect_other_areas matches user messages against.
    """
    return sorted({
        item.get("area") for item in evidence.get("cross_indicator_findings") or []
        if item.get("area") and item.get("area") != "National"
    })


def _detect_other_areas(
    message: str, history: List[Dict[str, str]], all_area_names: List[str], already_included: List[str],
) -> List[str]:
    """Real, deterministic area-name detection (case-insensitive substring
    match against this period's own real admin1 region names) -- not an LLM
    guess. Only returns areas NOT already fully present in priority_areas
    (the top-ranked areas already get full real detail; this is purely for
    a real area the user names that didn't rank top-5 for either hazard).
    """
    recent_text = (message + " " + " ".join(turn.get("content", "") for turn in history[-4:])).lower()
    already = {name.lower() for name in already_included}
    mentioned = [
        name for name in all_area_names
        if name.lower() not in already and name.lower() in recent_text
    ]
    return mentioned[:_MAX_OTHER_AREAS]


def _build_other_area_packet(evidence: Dict[str, Any], area_name: str) -> Optional[Dict[str, Any]]:
    """Compact real evidence for a real admin1 region that didn't rank in
    this period's top-5-per-hazard-type priority_areas -- built from
    cross_indicator_findings (real for every region) and hazard_risk_layers'
    real regional means (also real for every region, not just top-ranked
    ones), since that area has no real priority_area_justifications entry
    to draw from at all.
    """
    finding = next(
        (item for item in evidence.get("cross_indicator_findings") or [] if item.get("area") == area_name), None,
    )
    if not finding:
        return None

    hazard_risk_layers = evidence.get("hazard_risk_layers") or {}

    def regional_mean(layer_key: str) -> Optional[float]:
        layer = hazard_risk_layers.get(layer_key) or {}
        return next(
            (item.get("mean") for item in layer.get("regional") or [] if item.get("area_name") == area_name), None,
        )

    return {
        "area": area_name,
        "cross_indicator_signal": finding.get("signal"),
        "cross_indicator_confidence": finding.get("cross_indicator_confidence"),
        "agreement_score": finding.get("agreement_score"),
        "drought_risk_score": regional_mean("population_r_drought"),
        "wet_risk_score": regional_mean("population_r_wet"),
        "drought_hazard_probability": regional_mean("p_drought"),
        "wet_hazard_probability": regional_mean("p_wet"),
        "drought_vulnerability": regional_mean("v_drought"),
        "wet_vulnerability": regional_mean("v_wet"),
        "note": "Did not rank in this period's top-5-per-hazard priority areas -- fewer real fields available than a ranked area.",
    }


def _maybe_build_action_guidance(
    message: str, target_area: Optional[Dict[str, Any]], audience: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """Retrieves real early-action guidance from this app's own knowledge
    base (data/knowledge/action_library.json, via the SAME app.context.
    knowledge_context.build_knowledge_context/app.retrieval.hybrid_retriever
    Stage 3 already uses) -- only when the message actually looks like an
    action question (see _ACTION_INTENT_PATTERN) AND a real target area's
    hazard_type/action_status is available to build a real query from.
    Deliberately omits spi/rainfall_anomaly_pct from the query (score_entry
    treats them as minor refinements, defaulting to 0.0 itself when absent)
    -- hazard/risk_level/audience already carry the real primary matching
    weight, and this endpoint's compact priority-area packet doesn't carry
    those two raw indicator values through in the first place.
    """
    if not _ACTION_INTENT_PATTERN.search(message) or not target_area:
        return None

    hazard_type = target_area.get("hazard_type")
    if not hazard_type:
        return None

    query = {
        "hazard": "drought" if hazard_type == "drought" else "heavy_rainfall",
        "risk_level": _ACTION_STATUS_TO_RISK_LEVEL.get(target_area.get("action_status"), "watch"),
        "audience": _AUDIENCE_TO_LIBRARY_VALUE.get(audience, "any"),
    }
    try:
        knowledge = build_knowledge_context(query, top_k=3, country="ethiopia")
    except Exception:
        return None
    return knowledge.retrieved_items or None


# Real, fixed reference material -- not period-specific evidence, so built
# once at import time rather than re-serialized on every chat message.
# Reuses the SAME definitions the report pipeline itself already shows a
# reader (INDICATOR_DEFINITIONS's own real indicator interpretations,
# report_stages._risk_definition_block's real risk formula/classes,
# CLASSIFICATION_METHOD_LEGEND's real relative-vs-absolute distinction) --
# not new copy invented for the chatbot, so this can never drift from what
# the report itself already says.
_METHODOLOGY_REFERENCE = {
    "indicator_definitions": INDICATOR_DEFINITIONS,
    "risk_score_formula": _risk_definition_block(),
    "classification_methods": CLASSIFICATION_METHOD_LEGEND,
}
_METHODOLOGY_REFERENCE_BLOCK = f"""

METHODOLOGY REFERENCE (real, fixed definitions from this app's own documentation -- use these to answer "what is X" / "how is X computed" / "what does classification_method Y mean" questions. This is NOT period-specific evidence -- never cite a value from here as if it were real forecast data for the current period, and never let it override a real number given elsewhere in this prompt):
{compact_json(_METHODOLOGY_REFERENCE, max_chars=6000)}"""


def _build_chat_system_prompt(
    period: str,
    language_code: str,
    context_packet: Dict[str, Any],
    report_context: Optional[ReportContext],
    comparison_packets: Optional[Dict[str, Dict[str, Any]]] = None,
    other_area_packets: Optional[Dict[str, Dict[str, Any]]] = None,
    audience: Optional[str] = None,
    action_guidance: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Confirmed real gap, fixed: this used to serialize the WHOLE context_
    packet through one shared compact_json(..., max_chars=12000) call --
    real measured size for a typical period is ~21k chars, so
    priority_areas (10 real areas x ~20 fields, ~8.4k alone) silently
    crowded out community_ground_truth_by_area (~0.9k) before it ever
    reached the model on a real live request, even though _build_context_
    summary (computed from the SAME untruncated context_packet) kept
    reporting it as included -- an honest-sounding citation for evidence
    the model never actually saw. Same bug class report_stages.py already
    fixed once for Stage 2's own prompt (see its own "Blind mid-JSON
    truncation" comment) -- same fix here: each section gets its OWN
    budget, sized with real headroom above the real measured content, so
    one large section can never starve a smaller one.
    """
    layer_and_indicator_summaries = {
        "layer_summaries": context_packet.get("layer_summaries") or [],
        "indicator_summaries": context_packet.get("indicator_summaries") or [],
    }
    selected_area = context_packet.get("dashboard_selected_area")
    selected_area_line = f"\n\ndashboard_selected_area: {selected_area}" if selected_area else ""

    community = context_packet.get("community_ground_truth_by_area")
    community_block = ""
    if community:
        community_block = f"""

REAL COMMUNITY GROUND-TRUTH REPORTS (field observations submitted by community members, keyed by area name -- an area not listed here has zero submitted reports):
{compact_json(community, max_chars=_COMMUNITY_REPORTS_MAX_CHARS)}"""

    report_block = ""
    report_narrative = (report_context.model_dump(exclude_none=True) if report_context else {})
    if report_narrative:
        report_block = f"""

ALREADY-GENERATED REPORT NARRATIVE (real AI-authored text from a previous report generation, already checked by this app's own response validator -- you may quote or summarize it, but if it ever conflicts with REAL EVIDENCE below, the evidence wins; the evidence is always the more authoritative, more current source):
{compact_json(report_narrative, max_chars=4000)}"""

    comparison_block = ""
    if comparison_packets:
        comparison_block = f"""

CROSS-PERIOD COMPARISON EVIDENCE (the user's message mentioned {", ".join(comparison_packets.keys())} -- real evidence for those OTHER periods, kept smaller/scoped than the primary period's own evidence above. When comparing, ALWAYS name which period each number belongs to; never blend numbers from different periods into one unlabeled claim):
{compact_json(comparison_packets, max_chars=len(comparison_packets) * _COMPARISON_PERIOD_MAX_CHARS)}"""

    other_area_block = ""
    if other_area_packets:
        other_area_block = f"""

OTHER AREA EVIDENCE (the user's message named {", ".join(other_area_packets.keys())} -- real region(s) that did NOT rank in this period's top-5-per-hazard PRIORITY AREAS above, so fewer real fields exist for them; each entry's own "note" field says so. Never imply a ranked priority area's full detail exists for one of these):
{compact_json(other_area_packets, max_chars=len(other_area_packets) * _COMPARISON_AREA_MAX_CHARS)}"""

    audience_block = ""
    audience_instruction = _AUDIENCE_INSTRUCTIONS.get(audience or "")
    if audience_instruction:
        audience_block = f"\n\nAUDIENCE FOCUS: {audience_instruction}"

    action_guidance_block = ""
    if action_guidance:
        action_guidance_block = f"""

RETRIEVED EARLY-ACTION GUIDANCE (real entries from this app's own action knowledge base, data/knowledge/action_library.json -- the SAME source Stage 3 report generation draws from. Use these to inform what to recommend; do not invent an action not grounded in here or in the real evidence above, and say so if nothing relevant was retrieved):
{compact_json(action_guidance, max_chars=4000)}"""

    sms_char_budget = 70 if language_code in ("am", "ti") else 155
    sms_rule = f"""

SMS RULE: If the user asks for an SMS-ready / SMS version of an answer, write it as a separate block starting with "SMS:" on its own line, respecting a strict {sms_char_budget}-character budget (this app's own real per-segment budget for {get_language_label(language_code)} -- Amharic/Tigrinya require UCS-2 encoding at 70 chars/segment, other supported languages use GSM-7 at up to 155/segment, same rule Stage 3 report generation already follows). Count characters -- do not guess."""

    return f"""You are the Forecast2Action AI dashboard assistant, helping a decision-maker understand the {period} Ethiopia climate-risk forecast currently shown on their dashboard.{audience_block}

{get_language_instruction(language_code)}

STRICT GROUNDING RULE: You may ONLY answer using the real, already-computed evidence and METHODOLOGY REFERENCE given below -- never invent, estimate, or guess a number, ranking, or comparison that isn't directly present in them. If a question still can't be answered (general knowledge outside this project, a different country, anything requiring speculation), say so plainly and offer what you CAN answer instead -- never guess to seem helpful.

FORECAST-SAFE LANGUAGE: Everything below describes a FORECAST for {period} (and, if present, the other real periods in CROSS-PERIOD COMPARISON EVIDENCE), not something that has already happened. Never say a hazard "has occurred," "was observed," or is "ongoing" -- describe it as forecast, projected, or expected.

SUPERLATIVE RULE: Only say an area has the "highest"/"lowest" value of a metric (hazard_probability, vulnerability, population_exposed_pct, risk_score) if that exact metric name appears in that area's own real highest_among_group/lowest_among_group list below -- you cannot reliably compare raw numbers across areas yourself.

NATIONAL VS AREA-LEVEL RULE: national_cross_indicator is its own real, independently-computed aggregate -- never describe it as "strong" just because several individual areas are; use area_signal_tally for any area-level count, and never count the priority_areas list yourself.

COMMUNITY REPORTS RULE: REAL COMMUNITY GROUND-TRUTH REPORTS below (if present) is real, user-submitted field observations, keyed by area name -- corroborating evidence, not proof, unless a report's own verification_status shows it was actually reviewed. If that section is absent entirely from this prompt, you have NOT been given any community-report data at all -- say so plainly rather than guessing whether reports exist. If it IS present, an area with no entry in it has zero submitted reports.

OTHER-AREA RULE: If OTHER AREA EVIDENCE is present below, treat it as real but genuinely thinner than PRIORITY AREAS -- never claim a rank, risk_class, or exposure number for one of those areas, since none was computed for it this period.

ACTION-GUIDANCE RULE: If RETRIEVED EARLY-ACTION GUIDANCE is present below, ground any "what should be done" answer in it plus the real evidence above -- never invent an action beyond what's given in either. If it's absent and the user asks what to do, say you don't have retrieved action guidance for this question rather than improvising.

FORMATTING RULE: The chat UI renders only **bold** and `inline code` -- never use LaTeX/math notation (no $...$, \times, \text{{}}), tables, or headings. Write formulas as plain text (e.g. "risk score = 100 x hazard probability x severity x exposure x vulnerability").{sms_rule}

Keep answers conversational and concise (2-4 sentences) unless the user asks for more detail. If dashboard_selected_area is set below and the user's question doesn't name a specific area, assume they mean that one.

NATIONAL INDICATORS FOR {period.upper()}:
{compact_json(layer_and_indicator_summaries, max_chars=_NATIONAL_INDICATORS_MAX_CHARS)}

PRIORITY AREAS FOR {period.upper()} (real, already-ranked):
{compact_json(context_packet.get("priority_areas") or [], max_chars=_PRIORITY_AREAS_MAX_CHARS)}

NATIONAL CROSS-INDICATOR AGGREGATE (its own real, independently-computed signal -- see NATIONAL VS AREA-LEVEL RULE above):
{compact_json(context_packet.get("national_cross_indicator"), max_chars=1500)}

AREA-LEVEL SIGNAL TALLY (real, deterministic counts by signal -- never count priority_areas yourself):
{compact_json(context_packet.get("area_signal_tally"), max_chars=1500)}{selected_area_line}{community_block}{report_block}{comparison_block}{other_area_block}{action_guidance_block}{_METHODOLOGY_REFERENCE_BLOCK}
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


def _call_openai_compatible_chat_raw(
    *, api_key_env: str, base_url: Optional[str], model: str,
    system_prompt: str, history: List[Dict[str, str]], user_message: str,
) -> str:
    """Free-text (not JSON-schema) multi-turn chat call, shared by plain
    OpenAI and any OpenAI-compatible provider (OpenRouter) via base_url --
    same client pattern app.api.ai_map_interpretation already uses for the
    report pipeline, but that module's own callers are all JSON-schema-mode
    only (report generation), so this is a separate, free-text primitive
    rather than a reuse of those functions.
    """
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ProviderError(f"{api_key_env} is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise ProviderError("OpenAI Python package is required. Run: pip install openai") from exc

    client = OpenAI(base_url=base_url, api_key=api_key) if base_url else OpenAI(api_key=api_key)

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    response = client.responses.create(
        model=model,
        input=messages,
        max_output_tokens=int(os.getenv("AI_CHAT_MAX_TOKENS", "1024")),
    )
    return (response.output_text or "").strip()


# Ordered (provider_label, call) factories tried in turn -- mirrors the
# same "try each configured provider, fall through to the next on any real
# error" resilience already used by call_configured_ai_provider_for_stage
# for the report pipeline. Confirmed real gap this closes: the deployed
# Render backend has GEMINI_API_KEY unset but OPENAI_API_KEY configured
# (see /api/ai/provider-status), so a Gemini-only chat assistant failed
# there every time even though the rest of the AI pipeline works fine.
def _chat_provider_attempts(system_prompt: str, history: List[Dict[str, str]], user_message: str):
    for model in GEMINI_MODEL_TIERS["lite"]:
        if model:
            yield f"gemini:{model}", lambda m=model: _call_gemini_chat_raw(m, system_prompt, history, user_message)
    openai_model = os.getenv("OPENAI_MAP_AI_MODEL", "gpt-5")
    yield f"openai:{openai_model}", lambda: _call_openai_compatible_chat_raw(
        api_key_env="OPENAI_API_KEY", base_url=None, model=openai_model,
        system_prompt=system_prompt, history=history, user_message=user_message,
    )
    openrouter_model = os.getenv("OPENROUTER_AI_MODEL", "google/gemini-2.5-flash-lite")
    yield f"openrouter:{openrouter_model}", lambda: _call_openai_compatible_chat_raw(
        api_key_env="OPENROUTER_API_KEY",
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model=openrouter_model,
        system_prompt=system_prompt, history=history, user_message=user_message,
    )


def _build_context_summary(
    context_packet: Dict[str, Any],
    community_evidence: Dict[str, Any],
    report_context: Optional[ReportContext],
    comparison_packets: Optional[Dict[str, Dict[str, Any]]] = None,
    other_area_packets: Optional[Dict[str, Dict[str, Any]]] = None,
    action_guidance: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Real, deterministic accounting of what THIS message's context packet
    actually contained -- not a claim about which parts the model's reply
    drew on (that would require guessing at the model's own reasoning),
    just an honest list of the real sections it was given. Rendered as a
    "grounded in" citation under the reply in the chat UI.

    Confirmed real gap, fixed: this used to read straight from context_
    packet (pre-truncation) -- a real live request showed the citation
    claiming "community reports: South Ethiopia" while compact_json's
    per-prompt budget had actually cut that whole section before the model
    ever saw it (see _build_chat_system_prompt's own docstring). Now
    independently re-renders the community block with the SAME real budget
    the prompt uses and only claims what actually survived -- the citation
    can no longer promise evidence the model was never given.
    """
    priority_areas = context_packet.get("priority_areas") or []
    national_signal = (context_packet.get("national_cross_indicator") or {}).get("signal")

    community_reports_areas: List[str] = []
    community_reports_truncated = False
    if community_evidence:
        rendered = compact_json(community_evidence, max_chars=_COMMUNITY_REPORTS_MAX_CHARS)
        if "...TRUNCATED..." in rendered:
            community_reports_truncated = True
        else:
            community_reports_areas = sorted(community_evidence.keys())

    return {
        "priority_area_count": len(priority_areas),
        "priority_area_names": [item.get("area") for item in priority_areas if item.get("area")],
        "national_cross_indicator_signal": national_signal,
        "selected_area": context_packet.get("dashboard_selected_area"),
        "community_reports_areas": community_reports_areas,
        "community_reports_truncated": community_reports_truncated,
        "included_report_narrative": bool(report_context and report_context.model_dump(exclude_none=True)),
        "comparison_periods": sorted(comparison_packets.keys()) if comparison_packets else [],
        "other_areas_included": sorted(other_area_packets.keys()) if other_area_packets else [],
        "action_guidance_count": len(action_guidance) if action_guidance else 0,
    }


class _PreparedChatPrompt(NamedTuple):
    """Everything both /message and /stream need to actually call a
    provider and, afterward, build a context_summary -- extracted once so
    the two endpoints can never build the evidence/prompt two different
    ways and quietly drift apart.
    """

    period: str
    system_prompt: str
    history: List[Dict[str, str]]
    context_packet: Dict[str, Any]
    community_evidence: Dict[str, Any]
    comparison_packets: Dict[str, Dict[str, Any]]
    other_area_packets: Dict[str, Dict[str, Any]]
    action_guidance: Optional[List[Dict[str, Any]]]


def _prepare_chat_prompt(payload: DashboardChatRequest) -> _PreparedChatPrompt:
    period = resolve_report_period(AIMapInterpretationRequest(forecast_selection=payload.forecast_selection))

    try:
        evidence = build_national_region_evidence(period.lower(), admin_level="admin1", use_cache=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load real evidence for period={period}: {exc}") from exc

    # Real, freshly-read (never cached) community reports -- same function
    # and same "restrict to this period's real priority areas" pattern
    # report_stages.py already uses for Stage 2, not a client-trusted blob.
    priority_area_names = [
        item["area"] for item in evidence.get("priority_area_justifications") or [] if item.get("area")
    ]
    community_evidence = build_community_evidence_by_region(priority_area_names)

    context_packet = _build_chat_context_packet(evidence, payload.selected_area, community_evidence)
    language_code = normalize_language_code(payload.target_language)
    history = [turn.model_dump() for turn in payload.history[-MAX_HISTORY_TURNS:]]

    comparison_period_names = _detect_comparison_periods(payload.message, history, period)
    comparison_packets: Dict[str, Dict[str, Any]] = {}
    for comparison_period in comparison_period_names:
        comparison_packet = _build_comparison_period_packet(comparison_period, payload.selected_area)
        if comparison_packet:
            comparison_packets[comparison_period] = comparison_packet

    other_area_names = _detect_other_areas(
        payload.message, history, _real_admin1_area_names(evidence), priority_area_names,
    )
    other_area_packets: Dict[str, Dict[str, Any]] = {}
    for other_area in other_area_names:
        other_area_packet = _build_other_area_packet(evidence, other_area)
        if other_area_packet:
            other_area_packets[other_area] = other_area_packet

    # Real target area for an action-guidance retrieval: the dashboard's own
    # selected priority area if it's one of this period's real ranked areas,
    # else the #1-ranked real priority area -- never an area with no real
    # hazard_type/action_status to build a real query from.
    priority_areas = context_packet.get("priority_areas") or []
    target_area = next(
        (item for item in priority_areas if item.get("area") == payload.selected_area),
        next((item for item in priority_areas if item.get("rank") == 1), None),
    )
    action_guidance = _maybe_build_action_guidance(payload.message, target_area, payload.audience)

    system_prompt = _build_chat_system_prompt(
        period, language_code, context_packet, payload.report_context, comparison_packets,
        other_area_packets, payload.audience, action_guidance,
    )
    return _PreparedChatPrompt(
        period, system_prompt, history, context_packet, community_evidence,
        comparison_packets, other_area_packets, action_guidance,
    )


@router.post("/message", response_model=DashboardChatResponse)
def post_chat_message(payload: DashboardChatRequest) -> DashboardChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty.")

    prepared = _prepare_chat_prompt(payload)

    reply_text: Optional[str] = None
    errors: List[str] = []
    for provider_label, call in _chat_provider_attempts(prepared.system_prompt, prepared.history, payload.message):
        try:
            reply_text = call()
            if reply_text:
                break
        except Exception as exc:  # noqa: BLE001 -- real provider errors vary by SDK/network, all equally "try next provider"
            errors.append(f"{provider_label}: {exc}")
            continue

    if not reply_text:
        raise HTTPException(status_code=502, detail=f"Chat assistant is unavailable right now: {' | '.join(errors)}")

    # Same deterministic forecast-safe-language repair the report pipeline
    # applies, reused directly rather than re-implemented -- a free-text
    # chat reply is exactly the kind of TEXT_FIELDS-shaped content these
    # functions were built to scan and rewrite in place.
    from app.advisory.response_validator import _repair_confirmed_language_in_text, _repair_observational_present_in_text

    reply_text, _ = _repair_confirmed_language_in_text(reply_text)
    reply_text, _ = _repair_observational_present_in_text(reply_text)

    context_summary = _build_context_summary(
        prepared.context_packet, prepared.community_evidence, payload.report_context, prepared.comparison_packets,
        prepared.other_area_packets, prepared.action_guidance,
    )
    return DashboardChatResponse(reply=reply_text, period=prepared.period, context_summary=context_summary)


def _stream_gemini_chat_raw(model: str, system_prompt: str, history: List[Dict[str, str]], user_message: str):
    """Streaming counterpart to _call_gemini_chat_raw -- yields real text
    deltas as Gemini generates them (confirmed live: generate_content_
    stream yields GenerateContentResponse chunks, .text per chunk), instead
    of blocking for the full response. Same auth/contents/config
    construction as the non-streaming call.
    """
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
        stream = client.models.generate_content_stream(
            model=model, contents=contents, config=types.GenerateContentConfig(**config_kwargs),
        )
    except TypeError:
        stream = client.models.generate_content_stream(model=model, contents=contents, config=config_kwargs)

    for chunk in stream:
        if chunk.text:
            yield chunk.text


def _stream_openai_compatible_chat_raw(
    *, api_key_env: str, base_url: Optional[str], model: str,
    system_prompt: str, history: List[Dict[str, str]], user_message: str,
):
    """Streaming counterpart to _call_openai_compatible_chat_raw -- confirmed
    live: client.responses.create(..., stream=True) returns an iterator of
    typed events; only "response.output_text.delta" events carry real text
    (the others are lifecycle markers -- created/in_progress/output_item.*/
    content_part.*/output_text.done/completed), so those are the only ones
    yielded here.
    """
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ProviderError(f"{api_key_env} is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise ProviderError("OpenAI Python package is required. Run: pip install openai") from exc

    client = OpenAI(base_url=base_url, api_key=api_key) if base_url else OpenAI(api_key=api_key)

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    stream = client.responses.create(
        model=model, input=messages, stream=True,
        max_output_tokens=int(os.getenv("AI_CHAT_MAX_TOKENS", "1024")),
    )
    for event in stream:
        if event.type == "response.output_text.delta":
            yield event.delta


# Same ordering/resilience story as _chat_provider_attempts, streaming
# variant -- each factory returns a GENERATOR (not yet started), so the
# caller can tell a provider that fails before yielding anything (safe to
# just try the next one) apart from a provider that fails PARTWAY through
# (already streamed real content to the client -- can't silently restart
# with a different provider without the UI showing a broken half-answer).
def _chat_provider_stream_attempts(system_prompt: str, history: List[Dict[str, str]], user_message: str):
    for model in GEMINI_MODEL_TIERS["lite"]:
        if model:
            yield f"gemini:{model}", lambda m=model: _stream_gemini_chat_raw(m, system_prompt, history, user_message)
    openai_model = os.getenv("OPENAI_MAP_AI_MODEL", "gpt-5")
    yield f"openai:{openai_model}", lambda: _stream_openai_compatible_chat_raw(
        api_key_env="OPENAI_API_KEY", base_url=None, model=openai_model,
        system_prompt=system_prompt, history=history, user_message=user_message,
    )
    openrouter_model = os.getenv("OPENROUTER_AI_MODEL", "google/gemini-2.5-flash-lite")
    yield f"openrouter:{openrouter_model}", lambda: _stream_openai_compatible_chat_raw(
        api_key_env="OPENROUTER_API_KEY",
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model=openrouter_model,
        system_prompt=system_prompt, history=history, user_message=user_message,
    )


def _sse_line(payload: Dict[str, Any]) -> str:
    """Real Server-Sent-Events framing (data: <json>\\n\\n), not bare NDJSON.
    Confirmed real gap, fixed while first testing this endpoint: with
    media_type="application/x-ndjson", every delta arrived at once instead
    of progressively (measured directly against a real local server, byte
    offsets included) -- root cause was app.api.main's global
    GZipMiddleware(minimum_size=1000), whose underlying gzip.GzipFile
    buffers small writes internally and only flushes near the end,
    defeating streaming for a response made of many tiny chunks.
    "text/event-stream" is in Starlette's own GZipMiddleware
    DEFAULT_EXCLUDED_CONTENT_TYPES (confirmed by reading its source), so
    switching to real SSE framing/media type skips compression for this
    endpoint entirely -- no main.py middleware change needed. Real SSE
    framing is also the standards-correct choice for surviving a reverse
    proxy in front of the deployed backend, several of which specifically
    special-case text/event-stream to avoid buffering it too.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/stream")
def post_chat_stream(payload: DashboardChatRequest) -> StreamingResponse:
    """Streaming twin of /message -- same evidence/prompt, real upstream
    token streaming for perceived-latency (report generation and manual
    testing both showed 5-14s full-response waits; a floating chat widget
    with no progress indicator reads as broken far sooner than that).

    Still safety-first, not "stream whatever the model says": the client is
    told to treat streamed deltas as a live PREVIEW only, never the final
    committed text -- the SAME forecast-safe-language repair /message
    applies runs here too, against the full accumulated text once the
    stream ends, and the real, possibly-corrected final_reply is sent as
    the closing SSE event. A rare visible "flash" correction beats silently
    skipping the repair just to keep every streamed token final.
    """
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty.")

    prepared = _prepare_chat_prompt(payload)

    def event_stream():
        chunks: List[str] = []
        started = False
        errors: List[str] = []
        for provider_label, make_stream in _chat_provider_stream_attempts(
            prepared.system_prompt, prepared.history, payload.message,
        ):
            try:
                for delta in make_stream():
                    started = True
                    chunks.append(delta)
                    yield _sse_line({"delta": delta})
                if started:
                    break
            except Exception as exc:  # noqa: BLE001 -- same "try next provider" reasoning as _chat_provider_attempts
                if started:
                    yield _sse_line({"error": f"{provider_label} stream failed partway through: {exc}"})
                    return
                errors.append(f"{provider_label}: {exc}")
                continue

        if not started:
            yield _sse_line({"error": f"Chat assistant is unavailable right now: {' | '.join(errors)}"})
            return

        from app.advisory.response_validator import _repair_confirmed_language_in_text, _repair_observational_present_in_text

        full_text = "".join(chunks).strip()
        repaired_text, changed_1 = _repair_confirmed_language_in_text(full_text)
        repaired_text, changed_2 = _repair_observational_present_in_text(repaired_text)

        context_summary = _build_context_summary(
            prepared.context_packet, prepared.community_evidence, payload.report_context, prepared.comparison_packets,
            prepared.other_area_packets, prepared.action_guidance,
        )
        yield _sse_line({
            "done": True,
            "final_reply": repaired_text,
            "was_repaired": changed_1 or changed_2,
            "period": prepared.period,
            "context_summary": context_summary,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disables response buffering in nginx-style reverse proxies --
            # a real, common gotcha for streaming responses deployed behind
            # one (Render's own edge may or may not proxy this way, but the
            # header is a documented no-op when it doesn't apply, so there's
            # no real downside to setting it defensively).
            "X-Accel-Buffering": "no",
        },
    )
