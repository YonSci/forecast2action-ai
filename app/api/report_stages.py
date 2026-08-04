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
from typing import Any, Dict, List, Optional, Tuple

from app.api.ai_map_interpretation import (
    AIMapInterpretationRequest,
    STAGE1_SCHEMA,
    STAGE2_SCHEMA,
    STAGE3_SCHEMA,
    build_system_prompt,
    call_configured_ai_provider_for_stage,
    clean_model_id,
    compact_json,
    fallback_report,
    get_language_instruction,
    get_language_label,
    normalize_language_code,
    normalize_provider,
    resolve_report_period,
    title_case,
    validate_report_shape,
    validate_stage_shape,
)
from app.api.hazard_risk_catalog_shared import RISK_CLASS_BANDS
from app.api.hazard_risk_maps import find_map_record as find_hazard_risk_record
from app.api.seasonal_raster_maps import find_map_record as find_seasonal_record
from app.context.community_context import build_community_evidence_by_region
from app.context.statistical_evidence import PRIORITY_AREA_TOP_N, build_national_region_evidence

logger = logging.getLogger(__name__)

# Phase 2 revision: Stage 1 used to receive ALL 16 comprehensive map images
# (every hazard/risk layer + the 5 core climate indicators' forecast product)
# alongside real per-layer statistics -- once those statistics became rich
# enough (Phase 1: national + regional stats, real climatology departures,
# real exposed-population counts), the images stopped adding new numeric
# information and just added image-token cost. A small, curated synthesis
# set (the layers that actually drive drought-risk interpretation, plus the
# wet-hazard equivalents ONLY when the real national signal shows they
# matter) is enough for Stage 1 to visually verify spatial form, per the
# system prompt's own SOURCE HIERARCHY rule 3 ("use images only to verify
# spatial form -- never estimate a numerical value from image colors").
STAGE1_IMAGE_CAP = 16  # hard ceiling for select_curated_stage1_images's output; never actually reached in practice (curated list tops out around 8)

# Drought-side layers always included when a real render exists for them.
CURATED_STAGE1_HAZARD_RISK_LAYERS = ["population_r_drought", "p_drought", "h_dry_mean"]
# Wet-side equivalent, added ONLY when _wet_signal_is_significant (below)
# says the real national cross-indicator signal actually shows wet/mixed
# conditions -- otherwise these would just repeat a near-flat, low-signal
# map for a hazard that isn't operationally relevant this period.
CURATED_STAGE1_WET_HAZARD_RISK_LAYERS = ["population_r_wet", "p_wet", "h_wet_mean"]
# One combined map showing WHERE drought vs wet dominates spatially --
# included regardless of which single hazard is more significant, since it
# shows both at once.
CURATED_STAGE1_COMBINED_LAYER = "population_dominant_code"
# (indicator, product) pairs -- "anomaly" (not "forecast") for the 2 with
# real climatology, since the departure from normal is the operationally
# meaningful signal; SPI has no anomaly product (see INDICATORS_WITH_
# CLIMATOLOGY's docstring in statistical_evidence.py), so its own forecast
# IS already the standardized signal.
CURATED_STAGE1_CLIMATE_INDICATORS = [("rainfall_total", "anomaly"), ("spi", "forecast"), ("cdd", "anomaly")]

_SIGNIFICANT_WET_SIGNALS = {"strong_wet", "mixed"}


def _wet_signal_is_significant(evidence: Dict[str, Any]) -> bool:
    """True only when the real, already-computed national cross-indicator
    finding (see build_cross_indicator_findings) actually shows a wet or
    mixed signal -- not a guess, and not re-derived from raw indicators
    here. Drives whether Stage 1's curated image set includes the wet-side
    hazard/risk/probability maps at all.
    """
    findings = evidence.get("cross_indicator_findings") or []
    national = next((item for item in findings if item.get("area") == "National"), None)
    return bool(national and national.get("signal") in _SIGNIFICANT_WET_SIGNALS)


def select_curated_stage1_images(
    request: AIMapInterpretationRequest, evidence: Dict[str, Any], period: str,
) -> List[Dict[str, str]]:
    """Selects ~6-8 real map images from request.map_images (already
    rendered by populate_comprehensive_map_data for this exact period --
    this never re-renders anything) by looking up each curated layer's/
    indicator's REAL catalog record id via find_hazard_risk_record/
    find_seasonal_record and matching on that id, not by reconstructing or
    guessing a map_id string pattern -- so this stays correct even if the
    underlying id format ever changes.
    """
    images_by_map_id = {image["map_id"]: image for image in request.map_images if image.get("map_id")}

    selected: List[Dict[str, str]] = []
    seen_map_ids = set()

    def add_hazard_risk(layer_value: str) -> None:
        record = find_hazard_risk_record(layer_value, period)
        image = images_by_map_id.get(record["id"]) if record else None
        if image and image["map_id"] not in seen_map_ids:
            selected.append(image)
            seen_map_ids.add(image["map_id"])

    def add_climate(indicator: str, product: str) -> None:
        record = find_seasonal_record(indicator, period, product)
        image = images_by_map_id.get(record["id"]) if record else None
        if image and image["map_id"] not in seen_map_ids:
            selected.append(image)
            seen_map_ids.add(image["map_id"])

    for layer_value in CURATED_STAGE1_HAZARD_RISK_LAYERS:
        add_hazard_risk(layer_value)
    for indicator, product in CURATED_STAGE1_CLIMATE_INDICATORS:
        add_climate(indicator, product)
    if _wet_signal_is_significant(evidence):
        for layer_value in CURATED_STAGE1_WET_HAZARD_RISK_LAYERS:
            add_hazard_risk(layer_value)
    add_hazard_risk(CURATED_STAGE1_COMBINED_LAYER)

    return selected[:STAGE1_IMAGE_CAP]


def _required_layers_list(evidence: Dict[str, Any]) -> List[str]:
    """The real layer labels this evidence actually contains -- so Stage
    1's task instruction can say EXACTLY which/how many layer bullets are
    required, instead of a hardcoded 5-item list ("Hazard / Risk Score /
    Hazard Probability / Exposure / Vulnerability") that undercounted the
    real 11 distinct entries this evidence engine computes (drought AND
    wet versions of hazard/probability/vulnerability/risk, plus population
    exposure and 2 categorical layers) -- a confirmed real mismatch between
    Stage 1's task text and the evidence it was actually given.
    """
    labels = [
        entry["layer_label"]
        for entry in (evidence.get("hazard_risk_layers") or {}).values()
        if entry.get("layer_label")
    ]
    labels += [
        entry["layer_label"]
        for entry in (evidence.get("categorical_layers") or {}).values()
        if entry.get("layer_label")
    ]
    return labels

# Every staged report evaluates ALL real ranked areas nationwide -- there is
# no code path today where a dashboard-selected area actually narrows Stage
# 1/2's evidence (build_national_region_evidence always runs national/admin1).
# Stating this explicitly, rather than echoing whatever map layer/admin
# scope happened to be on screen, avoids implying a narrower or different
# scope than what was actually evaluated.
REPORT_SCOPE_LABEL = "National (Ethiopia) -- every real ranked area nationwide, not a single dashboard selection"


def _round_floats(value: Any, ndigits: int = 3) -> Any:
    """Recursively rounds every float in a JSON-shaped structure to
    `ndigits` decimal places before it's serialized into a prompt --
    real evidence is computed and cached at full precision (see
    app.context.statistical_evidence), but 15 decimal places of a weighted
    mean adds tokens without adding anything a report reader could act on.
    Full precision stays in the cached evidence file/API responses; this
    builds and returns an entirely new structure rather than mutating the
    input in place, so the original evidence dict is never altered.
    """
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, dict):
        return {key: _round_floats(item, ndigits) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item, ndigits) for item in value]
    return value


def _national_population_exposure_summary(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Real national population-exposure totals (people, not a normalized
    0-1 index) for drought and wet risk, summed from evidence["exposure"]'s
    real per-region population_exposed_by_region lists -- the same real
    numbers Stage 2's priority_area_justifications already cite per area,
    aggregated to a national total so Stage 1's "Exposure" layer bullet has
    an interpretable number to cite instead of just population_normalized's
    raw 0-1 index mean.
    """
    exposure = evidence.get("exposure", {})
    summary: Dict[str, Any] = {}
    for rank_by, hazard_type in (("population_r_drought", "drought"), ("population_r_wet", "wet")):
        regions = exposure.get(rank_by, {}).get("population_exposed_by_region", [])
        total_population = sum(item.get("total") or 0 for item in regions)
        exposed_population = sum(item.get("exposed") or 0 for item in regions)
        exposed_pct = round(exposed_population / total_population * 100, 1) if total_population else None
        summary[hazard_type] = {
            "total_population": round(total_population),
            "exposed_population": round(exposed_population),
            "exposed_population_pct": exposed_pct,
        }
    return summary


def _risk_definition_block() -> Dict[str, Any]:
    """The real, upstream-confirmed classification for population_r_drought/
    population_r_wet/population_risk_class's 0-100 risk score (RISK_CLASS_
    BANDS -- see app.api.hazard_risk_catalog_shared, confirmed directly
    against the data, not invented here) so the model can say whether a
    given risk score is Low/Moderate/High rather than just repeating the
    bare number. This is deliberately NOT the same as the dashboard's
    Trigger/Warning/Watch alert thresholds (app.api.hazard_risk_ranking's
    raw_layer_classification_thresholds), which are recalibrated per period
    against the real observed ceiling for operational alerting -- this
    block describes the fixed, upstream-defined meaning of the score itself.
    """
    return {
        "formula": "100 x hazard_probability x severity x exposure x vulnerability",
        "scale": "0-100 (a relative risk score; real data has not been observed to approach 100)",
        "classes": [
            {"code": band["code"], "label": band["label"], "range": list(band["range"])}
            for band in RISK_CLASS_BANDS
        ],
    }


def _compact_community_reports(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapses an empty/zero-report community_reports object down to
    {"available": false} for prompt purposes -- a real report with data
    still gets its real fields, just relabeled with an explicit
    "available": true rather than making a reader infer "zero" from
    several empty containers (total_reports=0, by_severity={}, etc).
    """
    if not entry or not entry.get("total_reports"):
        return {"available": False}
    return {
        "available": True,
        "reports": entry.get("total_reports"),
        "feedback_signal": entry.get("feedback_signal"),
        "by_severity": entry.get("by_severity"),
        "by_type": entry.get("by_type"),
    }


def _context_header(request: AIMapInterpretationRequest) -> str:
    """Shared header every stage's prompt needs for consistent output
    (language, forecast window, report scope, period). Deliberately does
    NOT include which map layer/indicator/group happens to be selected on
    the dashboard right now -- that is UI state, not scientific evidence,
    and including it risked biasing interpretation toward whatever was on
    screen when the report was generated (a comprehensive report should
    read identically regardless of which layer a user happened to be
    looking at when they clicked Generate).
    """
    forecast_window = title_case(request.forecast_selection.forecastScale)
    lead = title_case(request.forecast_selection.lead)
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
- Report scope: {REPORT_SCOPE_LABEL}
- Valid period: {seasonal_period}
- Output language: {language_label}"""


def build_stage1_prompt(
    request: AIMapInterpretationRequest,
    evidence: Dict[str, Any],
) -> Tuple[str, str, List[Dict[str, str]]]:
    """Stage 1: EVIDENCE INTERPRETATION. Sees the real computed evidence
    (climate indicators, hazard/risk layers, categorical layers, exposure,
    forecast metadata, indicator definitions, cross-indicator agreement)
    and a small, curated set of real map images (see
    select_curated_stage1_images) -- deliberately NOT given priority_scores,
    so it cannot decide which areas matter (that's Stage 2's job, using the
    real ranking, not this stage's raw-data impression).

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
    system_prompt = build_system_prompt(request.prompt_version, stage="stage1")

    # population_exposure_summary/risk_definition are placed FIRST, not
    # appended at the end -- compact_json truncates this dict's serialized
    # JSON at a fixed character count (see its own implementation), and the
    # full per-region breakdowns in climate_indicators/hazard_risk_layers
    # routinely exceed that limit on their own. A field appended after them
    # would silently never reach the model at all once truncation kicks in
    # (confirmed happening in practice) -- these two compact, high-value
    # summaries must survive truncation, so they go first; the bulkier
    # regional detail can afford to be what gets cut off, not these.
    # `exposure` is excluded here (same reasoning as `priority_scores`) --
    # Stage 1 doesn't discuss per-area breakdowns at all (that's Stage 2's
    # job, via priority_area_justifications, which already extracts ONLY
    # the real _pct fields). Leaving it in would put evidence["exposure"]'s
    # raw cropland_exposed_by_region/roads_exposed_by_region/healthsites_
    # exposed_by_region total/exposed sums in front of the model -- these
    # are weighted sums of a unitless 0-1 normalized index (see roads_
    # normalized/healthsites_normalized/cropland_total_normalized's real
    # "units": "normalized" in hazard_risk_catalog_shared.py), NOT real
    # hectares/road-segment/facility counts, unlike population_exposed_by_
    # region's total/exposed (real WorldPop people counts) -- a real risk
    # of the model citing a fabricated-sounding "hectares exposed" number
    # that was never actually computed anywhere in this pipeline.
    required_layers = _required_layers_list(evidence)
    evidence_for_stage1 = {
        "required_layers": required_layers,
        "population_exposure_summary": _national_population_exposure_summary(evidence),
        "risk_definition": _risk_definition_block(),
        **{key: value for key, value in evidence.items() if key not in ("priority_scores", "exposure")},
    }
    evidence_for_stage1 = _round_floats(evidence_for_stage1)

    user_prompt = f"""{_context_header(request)}

This is Stage 1 of a 3-stage report pipeline: EVIDENCE INTERPRETATION. Only interpret the given evidence layer by layer and indicator by indicator, and flag data-quality/uncertainty issues. Do not write an executive summary, do not decide or explain priority areas, and do not produce advisories -- those happen in later stages you are not performing.

TASK:
1. Provide layer_by_layer_summary as an array with exactly ONE object per entry in required_layers below (echo each real layer identifier back as "layer") -- do not omit any of them, and do not add layers not listed. Each object must have exactly these keys: layer (echoed back), national_signal (a short real classification, e.g. "high"/"moderate"/a real class label -- never invented), national_mean (the real national mean, or null if not applicable to this layer), highest_areas (array of the real area names with the highest values), lowest_areas (real area names with the lowest values), affected_area_pct (real % of area in the high/very-high classes, or null), interpretation (1-2 plain-language sentences grounded ONLY in the real numbers already given for this specific layer -- do not restate every number, explain what they mean), confidence ("high"/"moderate"/"low", reflecting real data completeness for this layer, not a guess). For the population_normalized entry specifically, ground the interpretation in the real population_exposure_summary figures (exposed population count and %) given separately below, not just the normalized index. For any risk-score layer, classify national_mean using risk_definition's real classes in the interpretation.
2. Provide indicator_by_indicator_summary in the SAME object shape (key "indicator" instead of "layer") with exactly one entry per climate indicator (Rainfall Total / SPI / CDD / CWD / Rx1day / Rx5day / Rainfall Percentile). Where an indicator's "departure" section is present, ground the interpretation in the real anomaly (absolute and/or %) against climatology, not just the forecast value alone. For SPI specifically, national_signal must be its real category (e.g. "severely_dry"), not an invented label.
3. Provide data_quality_notes flagging any uncertainty or low cross-indicator agreement visible in the evidence below. Only flag a climatology departure as unavailable where the evidence actually shows "departure_available": false -- do not claim data is missing when a real departure is present.

A curated set of real map images is attached (drought-side hazard/probability/risk maps always; wet-side equivalents only when the real national cross-indicator signal shows they matter this period; rainfall/CDD shown as their real anomaly against climatology, not just the raw forecast). Per this app's own SOURCE HIERARCHY rule, use them only to verify spatial form -- every number you cite must come from the evidence below, never estimated from image colors.

REAL COMPUTED EVIDENCE (already computed -- interpret it, do not recalculate or estimate any value):
{compact_json(evidence_for_stage1, max_chars=28000)}

Return only JSON with these keys: layer_by_layer_summary, indicator_by_indicator_summary, data_quality_notes.""".strip()

    images = select_curated_stage1_images(request, evidence, resolve_report_period(request))
    return system_prompt, user_prompt, images


def build_stage2_prompt(
    request: AIMapInterpretationRequest,
    evidence: Dict[str, Any],
    stage1_result: Dict[str, Any],
    community_evidence: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    """Stage 2: INTEGRATED RISK SYNTHESIS. No images. Sees Stage 1's
    validated interpretation plus the REAL, already-computed priority
    rankings and cross-indicator findings -- explicitly told to explain
    them, not invent or reorder them. This is the concrete fix for "the LLM
    should not independently decide which places are priorities."

    community_evidence (real, freshly-read community ground-truth reports,
    keyed by the same area name used in priority_area_justifications -- see
    app.context.community_context.build_community_evidence_by_region) is
    given here, not Stage 1, because Stage 1 stays area-agnostic (layer-by-
    layer/indicator-by-indicator only); this is the first stage that
    discusses specific named areas at all, so it's the only place a
    community report can be honestly attributed to the area it was
    submitted for.
    """
    system_prompt = build_system_prompt(request.prompt_version, stage="stage2")

    priority_areas_for_prompt = _round_floats(evidence.get("priority_area_justifications", []))
    cross_indicator_for_prompt = _round_floats(evidence.get("cross_indicator_findings", []))
    community_for_prompt = {
        area: _compact_community_reports(data) for area, data in community_evidence.items()
    }

    user_prompt = f"""{_context_header(request)}

This is Stage 2 of a 3-stage report pipeline: INTEGRATED RISK SYNTHESIS. Use Stage 1's validated evidence interpretation plus the real, already-computed priority rankings and cross-indicator findings below. Do not re-interpret raw indicator values, and do not invent, omit, or reorder which areas are priorities -- explain the given ranking as-is.

EXECUTIVE SUMMARY REQUIREMENT:
The executive_summary must explicitly mention the forecast window, lead/horizon, report scope, valid period, and output language listed above.

STAGE 1 VALIDATED EVIDENCE INTERPRETATION:
{compact_json(stage1_result, max_chars=10000)}

REAL RISK SCORE CLASSIFICATION (use these classes when describing a priority area's risk_score below, rather than stating the bare number alone):
{compact_json(_risk_definition_block(), max_chars=1500)}

REAL, ALREADY-COMPUTED PRIORITY AREAS (top {PRIORITY_AREA_TOP_N} per hazard type, already ranked, already scored -- every number below is real, do NOT recompute, reorder, add, drop, or restate any number). Note: each area's hazard_type reflects its RISK-based ranking (population_r_drought/population_r_wet); its cross_indicator_signal is a SEPARATE, independent analysis and will not always match hazard_type -- if they disagree, say so honestly in the differentiator rather than assuming alignment:
{compact_json(priority_areas_for_prompt, max_chars=10000)}

REAL, ALREADY-COMPUTED CROSS-INDICATOR AGREEMENT PER AREA (signal/agreement_score/supporting-contradicting indicators -- use this for compound-hazard interpretation, do not re-derive it from raw indicators):
{compact_json(cross_indicator_for_prompt, max_chars=8000)}

REAL COMMUNITY GROUND-TRUTH REPORTS PER AREA (field observations submitted by community focal points, extension workers, kebele/woreda officials, and NGO partners -- keyed by the same area name as the priority areas above; "available": false means zero submitted reports for that area, which is itself worth stating plainly rather than ignoring. Reports are corroborating evidence, not proof, unless verification_status shows they were actually reviewed -- say so if you cite one):
{compact_json(community_for_prompt, max_chars=6000)}

TASK:
1. Provide executive_summary per the requirement above.
2. Provide national_spatial_overview for Ethiopia-wide patterns, grounded in Stage 1's summaries.
3. Provide compound_hazard_interpretation explaining where multiple indicators agree or disagree (drought vs. wet signals), using the real cross-indicator agreement data above.
4. Provide priority_area_justification as an array with ONE entry per justification_id listed in "REAL, ALREADY-COMPUTED PRIORITY AREAS" above (echo the exact justification_id back, do not invent new ones or skip any). Each entry must have exactly these 3 keys: justification_id, differentiator (what distinguishes THIS area from the others, in plain language, using the real numbers already given -- do not restate the numbers themselves; when this area has real community reports above, mention whether they corroborate or contradict the forecast-based signal, naming the report count and type -- e.g. "consistent with 3 community reports of pasture stress"; when it has none, do not claim ground-truth confirmation), recommended_intervention_type (a short category, e.g. "Drought / water-security response" or "Flood / wet-hazard mitigation response").

Return only JSON with these keys: executive_summary, national_spatial_overview, compound_hazard_interpretation, priority_area_justification.""".strip()

    return system_prompt, user_prompt


def _action_evidence_packet(stage1_result: Dict[str, Any], stage2_result: Dict[str, Any]) -> Dict[str, Any]:
    """A compact, Stage-3-specific view of Stage 1+2's findings, instead of
    handing Stage 3 the full Stage 1 (layer-by-layer/indicator-by-indicator
    prose it never uses) and full Stage 2 (national_spatial_overview/
    compound_hazard_interpretation prose it never uses either) dumps.
    Stage 3's real job is audience-specific ACTION for the real priority
    areas -- it needs the numbers behind each area, the national executive
    summary for overall framing, and Stage 1's data-quality caveats; it
    never needed the rest.

    Deliberately drops `differentiator` (Stage 2's free-text narrative
    restating the same numbers already in this packet -- Stage 3 doesn't
    need a sentence explaining a number it can already see) and
    `justification_id` (an internal join key with no translation value).
    Keeps `recommended_intervention_type` (a real categorical judgment, not
    a restatement of a number) and folds in `livelihood_context:
    "not_available"` explicitly, per this app's own real-data constraint --
    no crop-type, crop-stage, or livestock-species-beyond-cattle data exists
    anywhere in this pipeline, so Stage 3 is told that plainly rather than
    silently omitting the field and risking an invented "maize/sorghum"
    guess.
    """
    packet_areas = []
    for item in stage2_result.get("priority_area_justification") or []:
        if not isinstance(item, dict):
            continue
        hazard_probability = item.get("hazard_probability")
        packet_areas.append({
            "area": item.get("area"),
            "rank": item.get("rank"),
            "hazard": item.get("hazard_type"),
            "risk_score": item.get("risk_score"),
            "hazard_probability_pct": round(hazard_probability * 100, 1) if isinstance(hazard_probability, (int, float)) else None,
            "vulnerability": item.get("vulnerability"),
            "confidence": item.get("confidence"),
            "recommended_intervention_type": item.get("recommended_intervention_type"),
            "population_exposed": item.get("population_exposed"),
            "population_exposed_pct": item.get("population_exposed_pct"),
            "roads_exposed_pct": item.get("roads_exposed_pct"),
            "healthsites_exposed_pct": item.get("healthsites_exposed_pct"),
            "cross_indicator_signal": item.get("cross_indicator_signal"),
            "supporting_indicators": item.get("supporting_indicators"),
            "ground_truth": _compact_community_reports(item.get("community_reports")),
            "livelihood_context": "not_available",
        })

    return {
        "executive_summary": stage2_result.get("executive_summary"),
        "data_quality_notes": stage1_result.get("data_quality_notes"),
        "priority_areas": packet_areas,
    }


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
    system_prompt = build_system_prompt(request.prompt_version, stage="stage3")

    action_packet = _round_floats(_action_evidence_packet(stage1_result, stage2_result))
    retrieved_guidance_for_stage3 = _round_floats(retrieved_guidance)

    user_prompt = f"""This is Stage 3 of a 3-stage report pipeline: ACTION TRANSLATION. Translate Stage 1 and Stage 2's validated findings into audience-specific advisories. Do not introduce new evidence, hazards, or areas that are not already present in the given findings.

OUTPUT LANGUAGE:
{get_language_instruction(request.target_language)}

AUDIENCE FOCUS:
{request.audience_focus}

ACTION EVIDENCE PACKET (the real, validated executive summary plus every priority area's real risk/exposure/climate-signal numbers -- everything you need is here; every number is real and already computed, do NOT recompute, reorder, add, or drop any):
{compact_json(action_packet, max_chars=8000)}

RETRIEVED EARLY-ACTION GUIDANCE (use to inform the actions below, not to introduce new hazards or areas):
{compact_json(retrieved_guidance_for_stage3, max_chars=6000)}

GROUNDING NOTES FOR THIS STAGE:
- `vulnerability` in the findings above is a real FEWS NET IPC food-security-phase-derived index, not a generic composite score -- use it explicitly when a priority is food-security-linked.
- `roads_exposed_pct`/`healthsites_exposed_pct` are the real share of road/health-facility infrastructure exposed to this hazard in that area -- use them for road-accessibility and health/sanitation triggers, not just population/exposure percentages.
- Livestock mortality risk has no real measured rate available -- describe it only qualitatively (e.g. "elevated livestock mortality risk"), grounded in the real livestock exposure and hazard severity already given, never state a fabricated numeric rate.
- Do not recommend pre-positioning or immediate humanitarian action based on rainfall anomaly alone -- require it to be corroborated by real exposure, vulnerability, or hazard-probability values from the findings above.
- Write conditional advice using the REAL numbers already given (e.g. "given a CDD anomaly of +N days and drought probability of X"), not an invented fixed agronomic threshold -- no such universal threshold exists in the supplied evidence.
- Every area's livelihood_context is "not_available" -- no crop-type, crop-stage, or livestock-species-beyond-cattle data exists in this pipeline. Do not invent specific crops (e.g. "maize", "sorghum") or livestock species -- write farmer/agro-pastoral advice in terms of the real signals you do have (rainfall, drought/wet risk, livestock exposure generally), not fabricated agronomic specifics.

TASK:
1. Provide farmer_advisory as an object with 3 keys -- immediate (next 7 days), near_term (next 2-4 weeks), preparedness (remainder of the forecast period) -- each a list of bullets for rainfed-agriculture farmers.
2. Provide agro_pastoral_advisory in the SAME 3-key (immediate/near_term/preparedness) shape, for agro-pastoral / livestock-keeping communities specifically -- distinct guidance from farmer_advisory, not a repeat of the same bullets.
3. Provide humanitarian_priorities as an object with 4 keys -- monitoring, preparedness, pre_positioning, immediate_action -- each a list of bullets, explicitly linked to the real triggers given (population exposed, vulnerability/food-security, road/health exposure, hazard probability, confidence).
4. Provide a short sms_summary in the output language.

Return only JSON with these keys: farmer_advisory, agro_pastoral_advisory, humanitarian_priorities, sms_summary.""".strip()

    return system_prompt, user_prompt


_NO_COMMUNITY_REPORTS = {
    "total_reports": 0,
    "by_severity": {},
    "by_type": {},
    "feedback_signal": "no_ground_signal",
    "recent_reports": [],
    "verified_count": 0,
}


def _merge_priority_area_justifications(
    deterministic: List[Dict[str, Any]],
    narrative: List[Dict[str, Any]],
    community_evidence: Dict[str, Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Combines the real, deterministic per-area object (rank/scores/
    supporting indicators -- see build_priority_area_justifications) with
    the LLM's own differentiator/recommended_intervention_type narrative,
    matched by justification_id. Always returns one entry per deterministic
    area, in order -- a missing/mismatched narrative entry (LLM error,
    fallback path) degrades to empty narrative strings rather than dropping
    or corrupting the real numbers, since those numbers must always be
    trustworthy regardless of what the LLM did.

    Also attaches the real (non-LLM-authored) community_reports summary for
    this area from community_evidence -- keyed by area name, same as the
    prompt Stage 2 was given -- defaulting to an explicit zero-report shape
    (_NO_COMMUNITY_REPORTS) rather than omitting the key, so a consumer
    never has to guess whether "missing" means "no reports" or "not
    computed".
    """
    community_evidence = community_evidence or {}
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
            "community_reports": community_evidence.get(entry.get("area"), _NO_COMMUNITY_REPORTS),
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

    # Real, freshly-read (never cached) community ground-truth reports for
    # this period's real priority areas -- see build_community_evidence_by_
    # region's docstring for why this can't live inside the cached
    # build_national_region_evidence() call above.
    priority_areas = evidence.get("priority_area_justifications", [])
    community_evidence = build_community_evidence_by_region(
        [item["area"] for item in priority_areas if item.get("area")],
    )

    # Step 9 -- Stage 2 (integrated synthesis: reconciling dry/wet signals,
    # hazard-exposure-vulnerability relationships, real priority rankings)
    # gets the "strong" model tier; Stage 1/3 (extraction, translation) stay
    # on the fast/free "lite" tier -- see GEMINI_MODEL_TIERS in
    # ai_map_interpretation.py.
    system2, user2 = build_stage2_prompt(request, evidence, stage1, community_evidence)
    stage2 = run_stage("stage2", STAGE2_SCHEMA, system2, user2, [], model_tier="strong")
    # priority_area_justification from run_stage is narrative-only (either
    # real LLM output or the deterministic fallback's own narrative-only
    # shape, see _fallback_priority_area_justification_narrative) -- always
    # merge it onto the real deterministic objects before it's used
    # downstream, so the numbers shown are never LLM-authored.
    stage2["priority_area_justification"] = _merge_priority_area_justifications(
        priority_areas, stage2.get("priority_area_justification", []), community_evidence,
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
