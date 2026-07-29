"""Step 6 -- staged LLM workflow: 3 sequential, narrower calls instead of
one large call producing all 8-10 report sections at once. Each stage's
prompt/schema/image budget is deliberately scoped to just what that stage
needs -- Stage 1 interprets real computed evidence, Stage 2 synthesizes and
explains real priority rankings (it does not invent priority areas from map
appearance), Stage 3 translates the validated findings into audience-
specific action. This module owns the per-stage prompt builders and the
orchestrator; app.api.ai_map_interpretation owns the underlying provider-
calling primitives, reused unchanged by both the legacy single-call path
and this one.
"""

import logging
from typing import Any, Dict, List, Tuple

from app.api.ai_map_interpretation import (
    AIMapInterpretationRequest,
    CLIMATE_INDICATOR_LABELS,
    MAP_LAYER_LABELS,
    STAGE1_SCHEMA,
    STAGE2_SCHEMA,
    STAGE3_SCHEMA,
    build_system_prompt,
    call_configured_ai_provider_for_stage,
    clean_model_id,
    compact_json,
    fallback_report,
    get_all_image_urls,
    get_displayed_map_label,
    get_language_instruction,
    get_language_label,
    get_map_group_label,
    normalize_language_code,
    normalize_provider,
    resolve_report_period,
    title_case,
    validate_report_shape,
    validate_stage_shape,
)
from app.context.statistical_evidence import PRIORITY_AREA_TOP_N, build_national_region_evidence

logger = logging.getLogger(__name__)

# Matches the existing real Hazard/Risk-first, then 5-core-climate-indicator
# priority order already computed by build_all_map_images/get_all_image_urls
# -- Stage 1 is the only one of the 3 stages that receives any image at all.
STAGE1_IMAGE_CAP = 16


def _context_header(request: AIMapInterpretationRequest) -> str:
    """Shared "what's on screen" header every stage's prompt needs for
    consistent output (language, forecast window, admin scope, active
    layer/indicator) -- mirrors the header block the legacy build_user_
    prompt used to build inline, extracted so each stage doesn't re-derive
    it separately.
    """
    forecast_window = title_case(request.forecast_selection.forecastScale)
    lead = title_case(request.forecast_selection.lead)
    admin_scope = request.map_context.admin_scope or "Ethiopia"
    active_layer = MAP_LAYER_LABELS.get(
        request.forecast_selection.layer or "", title_case(request.forecast_selection.layer or "hazard")
    )
    active_indicator = (
        request.forecast_selection.seasonalIndicatorLabel
        or request.map_context.seasonal_indicator_label
        or CLIMATE_INDICATOR_LABELS.get(
            request.forecast_selection.seasonalIndicator or request.forecast_selection.indicator or "",
            title_case(request.forecast_selection.seasonalIndicator or request.forecast_selection.indicator or "spi"),
        )
    )
    active_map_group = request.map_context.active_map_group or get_map_group_label(request.forecast_selection)
    displayed_map = request.map_context.displayed_map or get_displayed_map_label(request.forecast_selection)
    seasonal_period = (
        request.forecast_selection.seasonalPeriodLabel
        or request.map_context.seasonal_period_label
        or request.forecast_selection.seasonalPeriod
        or request.map_context.seasonal_period
        or lead
    )
    language_label = get_language_label(request.target_language)

    return f"""OUTPUT LANGUAGE:
{get_language_instruction(request.target_language)}

CONTEXT:
- Forecast window: {forecast_window}
- Lead / horizon: {lead}
- Admin scope: {admin_scope}
- Active map group: {active_map_group}
- Displayed map: {displayed_map}
- Active map layer: {active_layer}
- Active climate indicator: {active_indicator}
- Seasonal period: {seasonal_period}
- Output language: {language_label}"""


def build_stage1_prompt(
    request: AIMapInterpretationRequest,
    evidence: Dict[str, Any],
) -> Tuple[str, str, List[Dict[str, str]]]:
    """Stage 1: EVIDENCE INTERPRETATION. Sees the real computed evidence
    (climate indicators, hazard/risk layers, categorical layers, exposure,
    forecast metadata, indicator definitions, cross-indicator agreement)
    and a capped, priority-ordered image set -- deliberately NOT given
    priority_scores, so it cannot decide which areas matter (that's Stage
    2's job, using the real ranking, not this stage's raw-data impression).

    Deliberately NOT given retrieved_guidance -- per the system prompt's
    SOURCE HIERARCHY rule 4 ("use retrieved advisory guidance only after
    the climate and risk interpretation is complete"), that belongs in
    Stage 3 (action translation), which runs last, not here.

    system_prompt is IDENTICAL across all 3 stages (just build_system_
    prompt's own text, no per-stage addition) -- each stage's own scoping
    ("this is Stage 1 of 3, only do X, don't do Y") lives in the user
    prompt's TASK section instead, since the user prompt is already
    stage-specific in content (only Stage 1 is even given the raw evidence
    to interpret), so the guardrail loses no real strength by moving.
    """
    system_prompt = build_system_prompt(request.prompt_version)

    evidence_for_stage1 = {key: value for key, value in evidence.items() if key != "priority_scores"}

    user_prompt = f"""{_context_header(request)}

This is Stage 1 of a 3-stage report pipeline: EVIDENCE INTERPRETATION. Only interpret the given evidence layer by layer and indicator by indicator, and flag data-quality/uncertainty issues. Do not write an executive summary, do not decide or explain priority areas, and do not produce advisories -- those happen in later stages you are not performing.

TASK:
1. Provide layer_by_layer_summary with one clear bullet for each map layer (Hazard / Risk Score / Hazard Probability / Exposure / Vulnerability).
2. Provide indicator_by_indicator_summary with one clear bullet for each climate indicator (Rainfall Total / SPI / CDD / CWD / Rx1day / Rx5day / Rainfall Percentile).
3. Provide data_quality_notes flagging any uncertainty, missing climatology departures, or low cross-indicator agreement visible in the evidence below.

REAL COMPUTED EVIDENCE (already computed -- interpret it, do not recalculate or estimate any value):
{compact_json(evidence_for_stage1, max_chars=28000)}

Return only JSON with these keys: layer_by_layer_summary, indicator_by_indicator_summary, data_quality_notes.""".strip()

    images = get_all_image_urls(request)[:STAGE1_IMAGE_CAP]
    return system_prompt, user_prompt, images


def build_stage2_prompt(
    request: AIMapInterpretationRequest,
    evidence: Dict[str, Any],
    stage1_result: Dict[str, Any],
) -> Tuple[str, str]:
    """Stage 2: INTEGRATED RISK SYNTHESIS. No images. Sees Stage 1's
    validated interpretation plus the REAL, already-computed priority
    rankings and cross-indicator findings -- explicitly told to explain
    them, not invent or reorder them. This is the concrete fix for "the LLM
    should not independently decide which places are priorities."
    """
    system_prompt = build_system_prompt(request.prompt_version)

    user_prompt = f"""{_context_header(request)}

This is Stage 2 of a 3-stage report pipeline: INTEGRATED RISK SYNTHESIS. Use Stage 1's validated evidence interpretation plus the real, already-computed priority rankings and cross-indicator findings below. Do not re-interpret raw indicator values, and do not invent, omit, or reorder which areas are priorities -- explain the given ranking as-is.

EXECUTIVE SUMMARY REQUIREMENT:
The executive_summary must explicitly mention the forecast window, lead/horizon, admin scope, active map layer, active climate indicator, seasonal period, and output language listed above.

STAGE 1 VALIDATED EVIDENCE INTERPRETATION:
{compact_json(stage1_result, max_chars=10000)}

REAL, ALREADY-COMPUTED PRIORITY AREAS (top {PRIORITY_AREA_TOP_N} per hazard type, already ranked, already scored -- every number below is real, do NOT recompute, reorder, add, drop, or restate any number). Note: each area's hazard_type reflects its RISK-based ranking (population_r_drought/population_r_wet); its cross_indicator_signal is a SEPARATE, independent analysis and will not always match hazard_type -- if they disagree, say so honestly in the differentiator rather than assuming alignment:
{compact_json(evidence.get("priority_area_justifications", []), max_chars=10000)}

REAL, ALREADY-COMPUTED CROSS-INDICATOR AGREEMENT PER AREA (signal/agreement_score/supporting-contradicting indicators -- use this for compound-hazard interpretation, do not re-derive it from raw indicators):
{compact_json(evidence.get("cross_indicator_findings", []), max_chars=8000)}

TASK:
1. Provide executive_summary per the requirement above.
2. Provide national_spatial_overview for Ethiopia-wide patterns, grounded in Stage 1's summaries.
3. Provide compound_hazard_interpretation explaining where multiple indicators agree or disagree (drought vs. wet signals), using the real cross-indicator agreement data above.
4. Provide priority_area_justification as an array with ONE entry per justification_id listed in "REAL, ALREADY-COMPUTED PRIORITY AREAS" above (echo the exact justification_id back, do not invent new ones or skip any). Each entry must have exactly these 3 keys: justification_id, differentiator (what distinguishes THIS area from the others, in plain language, using the real numbers already given -- do not restate the numbers themselves), recommended_intervention_type (a short category, e.g. "Drought / water-security response" or "Flood / wet-hazard mitigation response").

Return only JSON with these keys: executive_summary, national_spatial_overview, compound_hazard_interpretation, priority_area_justification.""".strip()

    return system_prompt, user_prompt


def build_stage3_prompt(
    request: AIMapInterpretationRequest,
    stage1_result: Dict[str, Any],
    stage2_result: Dict[str, Any],
    retrieved_guidance: List[Dict[str, str]],
) -> Tuple[str, str]:
    """Stage 3: ACTION TRANSLATION. No images, no raw evidence -- pure
    translation of Stage 1 + Stage 2's already-validated findings into
    audience-specific advisories, so it cannot introduce a hazard or area
    that wasn't already established upstream. Receives retrieved_guidance
    here (not Stage 1) per the system prompt's SOURCE HIERARCHY rule 4 --
    it informs recommended actions, not the climate/risk interpretation.
    """
    system_prompt = build_system_prompt(request.prompt_version)

    user_prompt = f"""This is Stage 3 of a 3-stage report pipeline: ACTION TRANSLATION. Translate Stage 1 and Stage 2's validated findings into audience-specific advisories. Do not introduce new evidence, hazards, or areas that are not already present in the given findings.

OUTPUT LANGUAGE:
{get_language_instruction(request.target_language)}

AUDIENCE FOCUS:
{request.audience_focus}

STAGE 1 VALIDATED EVIDENCE INTERPRETATION:
{compact_json(stage1_result, max_chars=8000)}

STAGE 2 VALIDATED SYNTHESIS (includes, per priority area: risk_score, hazard_probability, vulnerability, population_exposed_pct, roads_exposed_pct, healthsites_exposed_pct, confidence -- all real, already computed):
{compact_json(stage2_result, max_chars=8000)}

RETRIEVED EARLY-ACTION GUIDANCE (use to inform the actions below, not to introduce new hazards or areas):
{compact_json(retrieved_guidance, max_chars=6000)}

GROUNDING NOTES FOR THIS STAGE:
- `vulnerability` in the findings above is a real FEWS NET IPC food-security-phase-derived index, not a generic composite score -- use it explicitly when a priority is food-security-linked.
- `roads_exposed_pct`/`healthsites_exposed_pct` are the real share of road/health-facility infrastructure exposed to this hazard in that area -- use them for road-accessibility and health/sanitation triggers, not just population/exposure percentages.
- Livestock mortality risk has no real measured rate available -- describe it only qualitatively (e.g. "elevated livestock mortality risk"), grounded in the real livestock exposure and hazard severity already given, never state a fabricated numeric rate.
- Do not recommend pre-positioning or immediate humanitarian action based on rainfall anomaly alone -- require it to be corroborated by real exposure, vulnerability, or hazard-probability values from the findings above.
- Write conditional advice using the REAL numbers already given (e.g. "given a CDD anomaly of +N days and drought probability of X"), not an invented fixed agronomic threshold -- no such universal threshold exists in the supplied evidence.

TASK:
1. Provide farmer_advisory as an object with 3 keys -- immediate (next 7 days), near_term (next 2-4 weeks), preparedness (remainder of the forecast period) -- each a list of bullets for rainfed-agriculture farmers.
2. Provide agro_pastoral_advisory in the SAME 3-key (immediate/near_term/preparedness) shape, for agro-pastoral / livestock-keeping communities specifically -- distinct guidance from farmer_advisory, not a repeat of the same bullets.
3. Provide humanitarian_priorities as an object with 4 keys -- monitoring, preparedness, pre_positioning, immediate_action -- each a list of bullets, explicitly linked to the real triggers given (population exposed, vulnerability/food-security, road/health exposure, hazard probability, confidence).
4. Provide a short sms_summary in the output language.

Return only JSON with these keys: farmer_advisory, agro_pastoral_advisory, humanitarian_priorities, sms_summary.""".strip()

    return system_prompt, user_prompt


def _merge_priority_area_justifications(
    deterministic: List[Dict[str, Any]], narrative: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Combines the real, deterministic per-area object (rank/scores/
    supporting indicators -- see build_priority_area_justifications) with
    the LLM's own differentiator/recommended_intervention_type narrative,
    matched by justification_id. Always returns one entry per deterministic
    area, in order -- a missing/mismatched narrative entry (LLM error,
    fallback path) degrades to empty narrative strings rather than dropping
    or corrupting the real numbers, since those numbers must always be
    trustworthy regardless of what the LLM did.
    """
    narrative_by_id = {
        item.get("justification_id"): item for item in narrative if isinstance(item, dict) and item.get("justification_id")
    }
    merged = []
    for entry in deterministic:
        narrative_entry = narrative_by_id.get(entry["justification_id"], {})
        merged.append({
            **entry,
            "differentiator": narrative_entry.get("differentiator") or "",
            "recommended_intervention_type": narrative_entry.get("recommended_intervention_type") or "",
        })
    return merged


def _base_report_fields(request: AIMapInterpretationRequest) -> Dict[str, Any]:
    return {
        "title": "AI Map Interpretation & Advisory",
        "target_language": get_language_label(request.target_language),
    }


def run_staged_report_generation(
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Orchestrates the 3-stage workflow, merging all 3 validated stage
    outputs into one flat dict shaped exactly like the legacy single-call
    report -- generate_ai_map_interpretation and everything downstream of it
    (envelope citation override, response_validator, frontend) needs no
    changes to consume this.

    Per-stage failure handling: if a stage's real LLM call throws (all
    configured providers exhausted), that stage's fields are pulled from
    fallback_report() -- computed lazily, at most once, no LLM call -- so a
    single-stage failure degrades gracefully instead of aborting the whole
    report, and downstream stages still get real (if deterministic) input
    to build on.
    """
    period = resolve_report_period(request)
    try:
        evidence = build_national_region_evidence(period.lower(), admin_level="admin1", use_cache=True)
    except Exception:
        logger.exception("Failed to build statistical evidence for staged report generation, period=%s", period)
        evidence = {}

    deterministic_fallback: Dict[str, Any] = {}

    def get_fallback() -> Dict[str, Any]:
        nonlocal deterministic_fallback
        if not deterministic_fallback:
            deterministic_fallback = fallback_report(request, retrieved_guidance, evidence=evidence)
        return deterministic_fallback

    stage_metadata: Dict[str, Any] = {}

    def run_stage(
        name: str,
        schema: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        images: List[Dict[str, str]],
        model_tier: str = "lite",
    ) -> Dict[str, Any]:
        try:
            raw = call_configured_ai_provider_for_stage(request, system_prompt, user_prompt, images, schema, model_tier=model_tier)
            stage_metadata[name] = raw.get("_metadata", {})
            validated = validate_stage_shape(raw, schema)
        except Exception as error:
            logger.warning("Staged report %s failed, using deterministic fallback: %s", name, error)
            validated = get_fallback()
            stage_metadata[name] = {"ai_engine": "rule_based_fallback", "provider": None, "model": None, "model_tier": model_tier, "error": str(error)}
        # Only the stage's own declared fields are carried forward -- keeps
        # _metadata (and any stray provider output) out of the next stage's
        # prompt, which would otherwise bloat it with irrelevant JSON.
        return {key: validated.get(key) for key in schema["properties"]}

    system1, user1, images1 = build_stage1_prompt(request, evidence)
    stage1 = run_stage("stage1", STAGE1_SCHEMA, system1, user1, images1, model_tier="lite")

    # Step 9 -- Stage 2 (integrated synthesis: reconciling dry/wet signals,
    # hazard-exposure-vulnerability relationships, real priority rankings)
    # gets the "strong" model tier; Stage 1/3 (extraction, translation) stay
    # on the fast/free "lite" tier -- see GEMINI_MODEL_TIERS in
    # ai_map_interpretation.py.
    system2, user2 = build_stage2_prompt(request, evidence, stage1)
    stage2 = run_stage("stage2", STAGE2_SCHEMA, system2, user2, [], model_tier="strong")
    # priority_area_justification from run_stage is narrative-only (either
    # real LLM output or the deterministic fallback's own narrative-only
    # shape, see _fallback_priority_area_justification_narrative) -- always
    # merge it onto the real deterministic objects before it's used
    # downstream, so the numbers shown are never LLM-authored.
    stage2["priority_area_justification"] = _merge_priority_area_justifications(
        evidence.get("priority_area_justifications", []), stage2.get("priority_area_justification", []),
    )

    system3, user3 = build_stage3_prompt(request, stage1, stage2, retrieved_guidance)
    stage3 = run_stage("stage3", STAGE3_SCHEMA, system3, user3, [], model_tier="lite")

    merged: Dict[str, Any] = {**_base_report_fields(request), **stage1, **stage2, **stage3}
    merged = validate_report_shape(merged)

    stage1_meta = stage_metadata.get("stage1", {})
    merged["_metadata"] = {
        "ai_engine": "staged_workflow",
        "provider": stage1_meta.get("provider"),
        "model": stage1_meta.get("model"),
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
        "period": period,
        "stages": stage_metadata,
    }

    # Step 11 -- automated output validation, run unconditionally (not
    # gated on a Decision Context Envelope like the older validate_
    # against_context) since real evidence is now available for every
    # report. Detect-and-flag, not block-and-fail -- see response_
    # validator's module docstring.
    from app.advisory.response_validator import validate_against_evidence

    merged, _violations = validate_against_evidence(merged, evidence, request.top_admin_areas)

    return merged
