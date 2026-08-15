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
from app.context.statistical_evidence import (
    PRIORITY_AREA_TOP_N,
    area_signal_counts,
    build_national_region_evidence,
    build_structured_indicator_summaries,
    build_structured_layer_summaries,
)

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

_SIGNIFICANT_WET_SIGNALS = {"strong_wet", "partial_wet", "mixed"}


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


def _merge_structured_summaries(
    deterministic: List[Dict[str, Any]], narrative: List[Dict[str, Any]], key_field: str,
) -> List[Dict[str, Any]]:
    """Combines the real, deterministic structured summary object
    (national_signal/national_mean/highest_areas/lowest_areas/
    high_or_very_high_area_pct/confidence -- see build_structured_layer_summaries/
    build_structured_indicator_summaries) with ONLY the LLM's own
    interpretation sentence, matched by key_field's real value. Always
    returns one entry per deterministic item, in order -- a missing/
    mismatched/empty narrative entry (LLM error, wrong key echoed back,
    fallback path) degrades to the deterministic object's own template
    interpretation (already grounded in the real numbers, see
    _structured_summary_object) rather than a blank string.

    This is the Stage 1 equivalent of _merge_priority_area_justifications.
    Confirmed live and real, not theoretical: before this merge existed,
    Stage 1's LLM output returned national_mean: 42.61 for a layer whose
    real, deterministic national mean was 3.409 (a ~12x error), used its
    own invented label ("Drought Risk") instead of the real layer
    identifier, and reclassified national_signal from the real "very_low"
    to "Moderate" -- proving prompt instructions alone ("do not modify
    computed values") cannot prevent this; the LLM must not be capable of
    returning these fields at all.
    """
    narrative_by_key = {
        item.get(key_field): item for item in narrative if isinstance(item, dict) and item.get(key_field)
    }
    merged = []
    for entry in deterministic:
        narrative_entry = narrative_by_key.get(entry[key_field], {})
        interpretation = narrative_entry.get("interpretation")
        merged.append({
            **entry,
            "interpretation": interpretation if isinstance(interpretation, str) and interpretation.strip() else entry["interpretation"],
        })
    return merged


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


_CLASSIFICATION_METHOD_CODES = (
    ("quintiles_of_current_period", "quintile_period"),
    ("quintiles_of_real_climatology", "quintile_climatology"),
    ("risk_class_bands", "risk_bands"),
    ("fixed_class_codes", "fixed_codes"),
    ("spi_mckee_category", "spi_mckee"),
    ("population_exposure", "population_exposure"),
)

CLASSIFICATION_METHOD_LEGEND = {
    "quintile_period": "RELATIVE -- this period's own national distribution split into fifths; e.g. 'High' means highest quintile THIS period, not a fixed severity threshold",
    "quintile_climatology": "RELATIVE -- this period's values split into fifths of the real climatology's own distribution; a claim vs the historical baseline, not a fixed severity threshold",
    "risk_bands": "ABSOLUTE -- a real, fixed, upstream-defined 0-100 risk-score scale",
    "fixed_codes": "ABSOLUTE -- a real, fixed, upstream-defined class scale; the raster's pixel value already IS the class",
    "spi_mckee": "ABSOLUTE -- the real, fixed McKee SPI standardized-precipitation-index scale (roughly -2 to +2 std dev), not a 0-100 scale",
    "population_exposure": "not a hazard/climate signal -- no national_signal/national_mean applies",
}


def _classification_method_code(raw_method: Optional[str]) -> Optional[str]:
    """Collapses a verbose classification_method sentence (repeated once per
    layer/indicator, ~30-95 chars each) down to a short, stable code -- the
    real distinction it encodes (relative-quintile vs absolute-fixed-scale)
    is given ONCE via CLASSIFICATION_METHOD_LEGEND instead of spelled out on
    every single entry. Falls through to the raw string for any value that
    doesn't match a known prefix, rather than silently dropping information
    the legend doesn't yet cover.
    """
    if not raw_method:
        return None
    for prefix, code in _CLASSIFICATION_METHOD_CODES:
        if raw_method.startswith(prefix):
            return code
    return raw_method


def _compact_layer_indicator_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    """Stage-2-specific view of one real layer/indicator summary object --
    drops classification_breakpoints (a Stage-1 classification detail
    Stage 2's own task, per build_stage2_prompt's TASK list, never
    references) and replaces the verbose classification_method sentence
    with its short code (see _classification_method_code).
    """
    compact = {key: value for key, value in item.items() if key != "classification_breakpoints"}
    if "classification_method" in compact:
        compact["classification_method"] = _classification_method_code(compact["classification_method"])
    return compact


_STAGE2_PRIORITY_AREA_DROPPED_FIELDS = {
    # Explicitly banned from citation by the DIFFERENTIATOR RULES below --
    # removing it from the evidence itself (not just telling the model not
    # to use it) is the same "prevent, don't just instruct" pattern this
    # project already uses elsewhere (see _merge_structured_summaries).
    "priority_score",
    # Duplicated per-area in REAL, ALREADY-COMPUTED CROSS-INDICATOR
    # AGREEMENT below (same area, same real supporting/contradicting
    # indicators) -- cross_indicator_signal + cross_indicator_confidence
    # stay here as the compact pointer into that block, so nothing is
    # actually lost.
    "supporting_indicators",
    "contradicting_indicators",
    # The DIFFERENTIATOR RULES only ever ask for the boolean
    # low_sample_size_warning ("say so explicitly") -- the raw cell count
    # itself isn't referenced by Stage 2's task (Stage 3's action packet
    # still carries it for UI/audit purposes downstream).
    "valid_cell_count",
}


def _stage2_priority_area_view(item: Dict[str, Any]) -> Dict[str, Any]:
    """Stage-2-specific view of one real priority-area object -- see
    _STAGE2_PRIORITY_AREA_DROPPED_FIELDS for what's excluded and why. This
    only shrinks what's SENT to Stage 2's prompt; the full deterministic
    evidence.priority_area_justifications entry (unchanged) is what Stage
    3's merge and the API response both use, so nothing here is actually
    lost from the app, only from Stage 2's own irrelevant reading.
    """
    return {key: value for key, value in item.items() if key not in _STAGE2_PRIORITY_AREA_DROPPED_FIELDS}


# Real per-indicator units (see app.context.statistical_evidence's
# _INDICATOR_CRITERION_UNITS, the single source of truth this mirrors) for
# _compact_indicator_criteria's self-describing compact keys -- baking the
# unit into the key name (e.g. "rainfall_anomaly_mm") removes the need for
# a separate repeated "units" string on every one of up to ~16 real
# regions' criteria. rainfall_percentile is intentionally absent (already
# self-describing, unitless 0-100); rx1day_anomaly/rx5day_anomaly are
# intentionally absent (handled directly in _compact_indicator_criteria,
# not via this suffix map -- see its own comment).
_CRITERION_UNIT_SUFFIX = {
    "rainfall_anomaly": "mm",
    "spi": "stddev",
    "cdd_anomaly": "days",
    "cwd_anomaly": "days",
    "drought_probability": "pct",
    "wet_probability": "pct",
}


def _compact_indicator_criteria(objects: Optional[List[Dict[str, Any]]]) -> Dict[str, float]:
    """Compacts one real cross_indicator_findings entry's supporting_
    indicators/contradicting_indicators (see app.context.statistical_
    evidence._indicator_evidence_objects) -- an array of verbose
    {indicator, value, units, ...} objects that repeats the same handful
    of unit strings on every single criterion, across up to 16 real
    regions (Stage 2) or every priority area (Stage 3) -- into one compact
    dict with the unit baked directly into the key (e.g.
    "rainfall_anomaly_mm": -28.27) instead of a separate units string.
    Every real value is kept; only the repeated unit-label boilerplate is
    removed. Shared by both Stage 2's cross-indicator block and Stage 3's
    action packet, since both consume the same real object shape.
    """
    compact: Dict[str, float] = {}
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        name = obj.get("indicator")
        if name in ("rx1day_anomaly", "rx5day_anomaly"):
            # Both real sibling values are always attached to this wrapper
            # (see _indicator_evidence_objects's rx_anomaly special-case)
            # -- report them directly rather than also keeping the
            # wrapper's own redundant indicator/value/units triplet.
            for sibling in ("rx1day_anomaly", "rx5day_anomaly"):
                sibling_value = obj.get(sibling)
                if sibling_value is not None:
                    compact[f"{sibling}_mm"] = sibling_value
            continue
        value = obj.get("value")
        if value is not None and name:
            suffix = _CRITERION_UNIT_SUFFIX.get(name)
            compact[f"{name}_{suffix}" if suffix else name] = value
        if name == "rainfall_anomaly" and obj.get("value_pct") is not None:
            compact["rainfall_anomaly_pct"] = obj["value_pct"]
    return compact


def _synthesis_evidence_packet(stage1_result: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Stage 2's compact, purpose-built evidence packet -- the Stage-2
    equivalent of _action_evidence_packet (Stage 3's own compact view).

    Confirmed real problem this replaces: the previous approach dumped
    stage1_result and priority_area_justifications as-is into compact_json
    with a fixed max_chars ceiling, and both routinely exceeded it (real
    measured sizes: ~12.2k and ~12.0k against 10k ceilings) -- meaning
    compact_json's blind character-count truncation was silently cutting
    real evidence MID-OBJECT, handing Stage 2 invalid trailing JSON on 2 of
    its 5 evidence blocks on every real run, not just a hypothetical edge
    case. This packet fixes that by shrinking the real content (dropping
    fields Stage 2's own TASK never uses, see _compact_layer_indicator_
    summary/_stage2_priority_area_view) so the real payload fits with
    headroom, rather than truncating blindly at a fixed character ceiling.
    """
    return {
        "layer_summaries": [_compact_layer_indicator_summary(item) for item in stage1_result.get("layer_by_layer_summary") or [] if isinstance(item, dict)],
        "indicator_summaries": [_compact_layer_indicator_summary(item) for item in stage1_result.get("indicator_by_indicator_summary") or [] if isinstance(item, dict)],
        "data_quality_notes": stage1_result.get("data_quality_notes"),
        "priority_areas": [_stage2_priority_area_view(item) for item in evidence.get("priority_area_justifications") or [] if isinstance(item, dict)],
    }


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


def _evidence_interpretation_packet(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Stage 1's compact, purpose-built evidence packet -- the Stage-1
    equivalent of _synthesis_evidence_packet (Stage 2) and
    _action_evidence_packet (Stage 3), all 3 following the same "give the
    model only what its own TASK actually reads" discipline.

    Confirmed real bug this fixes, in two parts (found via a live capture
    of the actual Stage 1 prompt sent to Gemini, not by inspection alone):

    1. TRUNCATION: the previous approach spread the ENTIRE raw evidence
       dict (climate_indicators + hazard_risk_layers + categorical_layers,
       real measured size ~136k chars combined) on top of the already-
       compact real_layer_summaries/real_indicator_summaries derived FROM
       that exact same raw data via build_structured_layer_summaries/
       build_structured_indicator_summaries -- fully redundant, since
       Stage 1's own TASK only ever reads the given real_signal/mean/
       highest_areas/lowest_areas fields per entry, never a raw region's
       min/max/std. Real captured prompt size (~32.6k) against the old
       28k ceiling meant compact_json's blind truncation was cutting real
       evidence mid-object on every real run.
    2. INVARIANT VIOLATION: the raw spread's exclusion list only named
       `priority_scores`/`exposure` -- NOT `priority_area_justifications`,
       directly contradicting this module's own documented Stage 1 design
       above ("deliberately NOT given priority_scores, so it cannot decide
       which areas matter"), since priority_area_justifications IS the
       already-ranked priority-area list, an even more direct leak than
       priority_scores itself. This never actually reached a real prompt
       (bug 1's truncation always cut the JSON before reaching that late
       dict key first, confirmed via the same live capture) -- but relying
       on one bug to accidentally mask another is not a fix.

    Keeps forecast_metadata (TASK item 3 explicitly requires flagging its
    real population_temporal_lag_years/livestock_temporal_lag_years),
    indicator_definitions (grounds TASK item 2's indicator interpretation
    in the real definitions), and cross_indicator_findings (TASK item 3's
    "low cross-indicator agreement" flagging) -- all real, all genuinely
    used by this stage's own TASK, none of them redundant with the
    layer/indicator summaries the way the raw per-region dumps were.
    """
    return {
        "real_layer_summaries": build_structured_layer_summaries(evidence),
        "real_indicator_summaries": build_structured_indicator_summaries(evidence),
        "population_exposure_summary": _national_population_exposure_summary(evidence),
        "risk_definition": _risk_definition_block(),
        "forecast_metadata": evidence.get("forecast_metadata"),
        "indicator_definitions": evidence.get("indicator_definitions"),
        "cross_indicator_findings": evidence.get("cross_indicator_findings"),
    }


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

    # Confirmed real, live bug (not theoretical): asking the LLM to
    # reproduce national_signal/national_mean/highest_areas/lowest_areas/
    # high_or_very_high_area_pct/confidence itself -- even with "do not modify
    # computed values" stated explicitly -- let a real Gemini response
    # return national_mean: 42.61 for a layer whose real, deterministic
    # value was 3.409 (a ~12x error), reclassify national_signal from the
    # real "very_low" to "Moderate", and use an invented layer label
    # instead of the real identifier. real_layer_summaries/real_indicator_
    # summaries (see _evidence_interpretation_packet) are computed here, by
    # Python, from the exact same real evidence -- never by the model --
    # and _merge_structured_summaries (below, after this stage's real
    # response comes back) keeps them authoritative regardless of what the
    # model returns. The model is only ever asked for interpretation text.
    evidence_for_stage1 = _round_floats(_evidence_interpretation_packet(evidence))

    user_prompt = f"""{_context_header(request)}

This is Stage 1 of a 3-stage report pipeline: EVIDENCE INTERPRETATION. Only interpret the given evidence layer by layer and indicator by indicator, and flag data-quality/uncertainty issues. Do not write an executive summary, do not decide or explain priority areas, and do not produce advisories -- those happen in later stages you are not performing.

TASK:
1. Provide layer_by_layer_summary as an array with exactly ONE object per entry in real_layer_summaries below, each with EXACTLY 2 keys: "layer" (echo that entry's real "layer" value back EXACTLY -- do not invent, relabel, or use its human-readable name) and "interpretation" (1-2 plain-language sentences explaining what that entry already shows -- do not restate every number, explain what they mean, and do not state a different number, class, or area name than what is given for that entry). Do not omit any entry, and do not add layers not listed. The population_normalized entry is population EXPOSURE, not a hazard/climate signal -- it has no national_signal/national_mean/highest_areas/lowest_areas; ground its interpretation ONLY in its own real total_population/drought_exposed_population/drought_exposed_pct/wet_exposed_population/wet_exposed_pct fields, and never describe it as "high"/"low" the way a hazard layer is described. For any risk-score layer, its national_signal already IS the real risk_definition class -- reference it, do not reclassify it yourself.
2. Provide indicator_by_indicator_summary in the SAME 2-key shape (key "indicator" instead of "layer") for every entry in real_indicator_summaries below. Where an indicator's real anomaly figures are shown in its entry, ground the interpretation in that real departure, not the forecast value alone.
3. Provide data_quality_notes flagging any uncertainty or low cross-indicator agreement visible in the evidence below. Only flag a climatology departure as unavailable where the evidence actually shows "departure_available": false -- do not claim data is missing when a real departure is present. Also flag forecast_metadata's real population_temporal_lag_years/livestock_temporal_lag_years explicitly whenever either is 3+ years -- population/livestock exposure figures are computed from real but temporally static datasets (a fixed reference year), not updated for the current forecast year, and a reader needs that distinction even when spatial data completeness is otherwise good.

You do not compute, reclassify, or invent national_signal, national_mean, highest_areas, lowest_areas, high_or_very_high_area_pct, or confidence for any entry in real_layer_summaries/real_indicator_summaries -- those are already real, authoritative values and are used exactly as given regardless of what you return for them. Your only job for each entry is its interpretation sentence, and it must not contradict the real values already given for that entry.

Each entry's real classification_method tells you whether its national_signal AND its high_or_very_high_area_pct are an ABSOLUTE severity claim or a RELATIVE one -- phrase your interpretation accordingly: "risk_class_bands"/"fixed_class_codes"/"spi_mckee_category" are real, fixed, upstream-defined scales (an absolute claim like "High", or SPI's own real category, is accurate as stated, and high_or_very_high_area_pct is a real share of area above a fixed severity band); "quintiles_of_current_period" or "quintiles_of_real_climatology" mean the class is this period's own distribution split into fifths (phrase it relatively, e.g. "one of the highest nationally this period" / "the top fifth of areas by area extent this period", not as an absolute severity claim, since no universal threshold defines what counts as objectively "high" hazard probability or vulnerability in this pipeline).

A curated set of real map images is attached (drought-side hazard/probability/risk maps always; wet-side equivalents only when the real national cross-indicator signal shows they matter this period; rainfall/CDD shown as their real anomaly against climatology, not just the raw forecast). Per this app's own SOURCE HIERARCHY rule, use them only to verify spatial form -- every number you cite must come from the evidence below, never estimated from image colors.

REAL COMPUTED EVIDENCE (already computed -- interpret it, do not recalculate or estimate any value):
{compact_json(evidence_for_stage1, max_chars=36000)}

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

    synthesis_packet = _round_floats(_synthesis_evidence_packet(stage1_result, evidence))
    # Compacted (see _compact_indicator_criteria) -- confirmed real gap,
    # fixed: this block used to send the FULL verbose supporting_
    # indicators/contradicting_indicators objects (indicator/value/units/
    # value_pct/units_pct repeated per criterion) for all ~16 real admin1
    # regions, making it the single largest block in Stage 2's real prompt
    # (measured: ~10.9k of ~36.5k total chars). Every real value is still
    # here, just without the repeated unit-label boilerplate.
    cross_indicator_for_prompt = _round_floats([
        {
            "area": item.get("area"),
            "signal": item.get("signal"),
            "agreement_score": item.get("agreement_score"),
            "cross_indicator_confidence": item.get("cross_indicator_confidence"),
            "supporting": _compact_indicator_criteria(item.get("supporting_indicators")),
            "contradicting": _compact_indicator_criteria(item.get("contradicting_indicators")),
        }
        for item in evidence.get("cross_indicator_findings", []) or []
        if isinstance(item, dict)
    ])
    community_for_prompt = {
        area: _compact_community_reports(data) for area, data in community_evidence.items()
    }
    real_area_signal_counts = area_signal_counts(evidence.get("cross_indicator_findings", []) or [])

    user_prompt = f"""{_context_header(request)}

This is Stage 2 of a 3-stage report pipeline: INTEGRATED RISK SYNTHESIS. Use Stage 1's validated evidence interpretation plus the real, already-computed priority rankings and cross-indicator findings below. Do not re-interpret raw indicator values, and do not invent, omit, or reorder which areas are priorities -- explain the given ranking as-is.

EXECUTIVE SUMMARY REQUIREMENT:
The executive_summary must explicitly mention the forecast window, lead/horizon, report scope, valid period, and output language listed above.

CLASSIFICATION_METHOD LEGEND (every layer_summaries/indicator_summaries entry's classification_method is one of these short codes -- use it to tell whether that entry's national_signal is an ABSOLUTE severity claim or a RELATIVE one, phrasing your interpretation accordingly, e.g. a RELATIVE "High" should read as "one of the highest nationally this period", not as an absolute severity claim):
{compact_json(CLASSIFICATION_METHOD_LEGEND, max_chars=1200)}

FORECAST VS CLIMATOLOGY LABELING (every layer_summaries/indicator_summaries entry with a real "departure" block carries forecast_mean, climatology_mean, anomaly_mean, and anomaly_pct -- these are four DIFFERENT real numbers, never interchangeable labels for the same one: forecast_mean is THIS PERIOD's real forecast value; climatology_mean is the real long-term historical baseline it is compared against; anomaly_mean/anomaly_pct is the real difference between them. The word "climatology"/"climatologically" must always introduce climatology_mean's own value, never forecast_mean's:
BAD (labels the FORECAST value as the climatological one): "Climatologically, total rainfall averages 101.429 mm against a baseline of 129.697 mm."
GOOD: "Forecast rainfall averages 101.429 mm, compared with a climatological baseline of 129.697 mm, a departure of -28.268 mm (-53.74%)."
101.429/129.697/-28.268 above are illustrative placeholders, not real values for this period -- use whichever real forecast_mean/climatology_mean/anomaly_mean figures are actually given to you.)

VULNERABILITY CAUSALITY RULE (vulnerability and hazard are SEPARATE real components of the risk formula in REAL RISK SCORE CLASSIFICATION below -- "100 x hazard_probability x severity x exposure x vulnerability". The real vulnerability layers (v_drought/v_wet) are built from real, independent baseline food-security/livelihood data, NOT from rainfall or any other climate indicator -- so forecast rainfall, SPI, CDD, Rx1day, Rx5day, drought_probability, and wet_probability never CAUSE, DRIVE, or EXPLAIN a vulnerability value, no matter how naturally they read together in one sentence:
BAD (attributes a baseline vulnerability score to a forecast climate value): "Drought vulnerability is classified as very high nationally, driven by severe rainfall deficits."
GOOD: "Drought vulnerability is very high nationally, reflecting baseline food-security and livelihood sensitivity -- where this pre-existing vulnerability overlaps with the separate forecast rainfall deficit described above, overall drought risk increases."
Never use "driven by"/"because of"/"due to"/"caused by" to connect a vulnerability statement to a climate/hazard value -- state them as two separate, coinciding facts instead.)

STAGE 1 VALIDATED EVIDENCE INTERPRETATION (layer_summaries/indicator_summaries/data_quality_notes -- every number is real, do not recompute, reclassify, or invent any field; only the interpretation sentences were LLM-authored, everything else is deterministic):
{compact_json({"layer_summaries": synthesis_packet["layer_summaries"], "indicator_summaries": synthesis_packet["indicator_summaries"], "data_quality_notes": synthesis_packet["data_quality_notes"]}, max_chars=16000)}

REAL RISK SCORE CLASSIFICATION (use these classes when describing a priority area's risk_score below, rather than stating the bare number alone):
{compact_json(_risk_definition_block(), max_chars=1500)}

REAL, ALREADY-COMPUTED PRIORITY AREAS (top {PRIORITY_AREA_TOP_N} per hazard type, already ranked, already scored -- every number below is real, do NOT recompute, reorder, add, drop, or restate any number). Note: each area's hazard_type reflects its RISK-based ranking (population_r_drought/population_r_wet); its cross_indicator_signal is a SEPARATE, independent analysis and will not always match hazard_type -- if they disagree, say so honestly in the differentiator rather than assuming alignment. This area's real supporting/contradicting indicator detail lives in the CROSS-INDICATOR AGREEMENT block below, keyed by the same area name -- look it up there rather than assuming:
{compact_json(synthesis_packet["priority_areas"], max_chars=16000)}

REAL, ALREADY-COMPUTED CROSS-INDICATOR AGREEMENT PER AREA (signal/agreement_score/cross_indicator_confidence, for every real admin1 region -- use this for compound-hazard interpretation AND for a priority area's own supporting/contradicting indicator detail, do not re-derive it from raw indicators. cross_indicator_confidence measures ONLY how strongly this area's indicators agree with each other -- it is NOT a measure of data completeness (see that area's own real low_sample_size_warning/data_quality_confidence for that) or forecast/ensemble skill (no real ensemble-spread data exists anywhere in this pipeline -- never report or invent a "forecast confidence" value). "supporting"/"contradicting" are compact {{criterion: real_value}} dicts -- the unit is baked into each key name, e.g. "rainfall_anomaly_mm": -28.27, "spi_stddev": -1.12, "cdd_anomaly_days": 3.25, "drought_probability_pct": 80.0; "rainfall_percentile" is already a unitless 0-100 value):
{compact_json(cross_indicator_for_prompt, max_chars=16000)}

REAL, ALREADY-COUNTED AREA SIGNAL TALLY (a deterministic count of the per-area rows above, by signal -- "counts" gives the real number of areas for each signal, "areas" gives the real area names behind each count. NEVER count or tally the CROSS-INDICATOR AGREEMENT rows yourself: any statement of the form "N areas/zones/regions independently show a strong/partial drought/wet signal" MUST use the exact number from "counts" for that signal, and if you name areas, MUST use exactly (and only) the names from "areas" for that signal -- not a subset, not a guess, not a different number):
{compact_json(real_area_signal_counts, max_chars=2000)}

REAL COMMUNITY GROUND-TRUTH REPORTS PER AREA (field observations submitted by community focal points, extension workers, kebele/woreda officials, and NGO partners -- keyed by the same area name as the priority areas above; "available": false means zero submitted reports for that area, which is itself worth stating plainly rather than ignoring. Reports are corroborating evidence, not proof, unless verification_status shows they were actually reviewed -- say so if you cite one):
{compact_json(community_for_prompt, max_chars=6000)}

TASK:
1. Provide executive_summary per the requirement above.
2. Provide national_spatial_overview for Ethiopia-wide patterns, grounded in Stage 1's summaries.
3. Provide compound_hazard_interpretation explaining where multiple indicators agree or disagree (drought vs. wet signals), using the real cross-indicator agreement data above. The "National" entry in that data is its own real, independently-computed aggregate signal/agreement_score (e.g. "partial_drought", 0.6) -- it is NOT the same thing as counting how many individual areas independently show a strong signal, and the two must never be conflated into one claim. State the National entry's own real signal/agreement_score explicitly (e.g. "a partial national drought signal, agreement score 0.6") as a SEPARATE statement from how many areas show a strong area-level signal. Never describe the national aggregate itself as "strong" just because several areas individually are strong, and never describe it as "partial"/weak if its own real signal is actually strong_drought/strong_wet -- always use the National entry's own real signal value, not an impression formed from the area-level rows. For the area-level count and any named areas, use the REAL, ALREADY-COUNTED AREA SIGNAL TALLY given above exactly as given -- do not count the CROSS-INDICATOR AGREEMENT rows yourself under any circumstances.
4. Provide priority_area_justification as an array with ONE entry per justification_id listed in "REAL, ALREADY-COMPUTED PRIORITY AREAS" above (echo the exact justification_id back, do not invent new ones or skip any). Each entry must have exactly these 3 keys: justification_id, differentiator, recommended_intervention_type. Each area's real, already-computed action_status tells you how strong recommended_intervention_type should sound -- do not give every top-5-ranked area a full response label regardless of real signal strength: action_status "action" -> a real response category (e.g. "Drought / water-security response"); "preparedness" -> a preparedness-framed category (e.g. "Drought preparedness monitoring"); "monitor_only" or "not_actionable" -> state plainly that this area is ranked but not currently actionable (e.g. "Monitoring only -- not currently actionable this period"), and your differentiator must say WHY (e.g. real risk_score in the Very low class, and/or cross_indicator_signal not agreeing with this area's own hazard_type) rather than inventing an operational response the real numbers don't support. It is normal and expected for some or all areas within one hazard type to be not_actionable in a given period -- do not treat a top-5 rank as proof that real action is warranted.

DIFFERENTIATOR RULES (this is the most commonly violated rule -- follow it exactly):
- priority_score is deliberately not included in the evidence above -- it is an internal ranking composite with no standalone meaning to a reader, so it cannot be cited. Explain the ranking using the REAL, independently-meaningful drivers instead: risk_score's class (from the classification above), hazard_probability, vulnerability, exposure, or specific indicator values.
- Do NOT restate numbers the reader already sees elsewhere (risk_score, hazard_probability, vulnerability, population_exposed_pct are already shown separately) -- reference them in WORDS ("a high hazard probability relative to other drought areas"), not by repeating the digits.
- SUPERLATIVE WORDS (highest/largest/greatest/maximum/lowest/smallest/least/minimum) for hazard_probability, vulnerability, population_exposed_pct, or risk_score are ONLY allowed when that exact metric name appears in THIS area's own real highest_among_group (for highest/largest/greatest/maximum) or lowest_among_group (for lowest/smallest/least/minimum) field, given per-area in the REAL, ALREADY-COMPUTED PRIORITY AREAS block below -- these are real, deterministic comparisons already computed against every OTHER area in this same top-{PRIORITY_AREA_TOP_N} batch. You cannot correctly compare raw numbers across areas yourself (confirmed real gap: a real run once claimed a top-ranked area held "the highest hazard probability" when another real area in that same batch actually had a higher one). When a metric is NOT in either list for this area, describe it in non-comparative terms instead (e.g. "a high hazard probability", not "the highest hazard probability").
- BAD (restates numbers, cites priority_score): "Area A holds the highest drought priority score (0.600) and risk score (30.188, Low) nationally, defined by a 1.00 hazard probability, an extreme SPI of -4.47 std dev..."
- GOOD (explains WHY in plain language, no restated numbers, superlative used only because "population_exposed_pct" is really in this area's own highest_among_group): "Area A ranks first for drought despite its risk score falling in the Low class, because it has the highest exposed-population share of any drought area this period among the REAL comparisons given -- that combination of scale and a high hazard probability is what keeps it at the top of the ranking even though its risk score alone looks moderate."
- Area A/Area B above are abstract placeholders, not real area names -- do not copy this specific claim into your own answer. Real areas differ every period in which factor actually drives their rank; state whichever real driver(s) the REAL numbers (and REAL highest_among_group/lowest_among_group flags) given to you for THIS area actually show, never assume it must be hazard probability or any other single field.
- When this area has real community reports above, mention whether they corroborate or contradict the forecast-based signal, naming the report count and type -- e.g. "consistent with 3 community reports of pasture stress"; when it has none, do not claim ground-truth confirmation.
- When this area's real low_sample_size_warning is true, say so explicitly (e.g. "based on a small real sample of grid cells for this area, so treat this as a coarser estimate") -- do not describe data completeness as unqualifiedly robust for an area flagged this way, and never invent a data-quality claim for an area not flagged.

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

    Confirmed real gap, fixed: every priority area used to get the SAME
    full ~16-field detail regardless of action_status, even though a real
    period typically has only 1-2 actionable areas out of 10 (measured:
    July's real data -- 1 actionable, 9 monitor_only/not_actionable) --
    Stage 3's own TASK already forbids writing a real response
    recommendation for a non-actionable area, so the full risk/exposure/
    indicator breakdown for those 9 was pure unused weight. Split into
    `actionable_areas` (action_status "action"/"preparedness" -- full real
    detail, unchanged from before) and `monitor_only_areas` (everything
    else -- just enough real detail for a generic monitoring bullet:
    area/hazard/rank/risk_class/cross_indicator_signal/cross_indicator_
    confidence/reason, no exposure/vulnerability/indicator numbers or
    data_quality_confidence, since none of those were ever meant to
    justify an operational response for these areas anyway).
    humanitarian_priorities' monitoring tier is the only one allowed to
    draw from monitor_only_areas -- see this stage's own TASK
    instructions.

    actionable_areas deliberately drops `differentiator` (Stage 2's
    free-text narrative restating the same numbers already in this packet
    -- Stage 3 doesn't need a sentence explaining a number it can already
    see) and `justification_id` (an internal join key with no translation
    value). Keeps `recommended_intervention_type` (a real categorical
    judgment, not a restatement of a number) and folds in
    `livelihood_context: "not_available"` explicitly, per this app's own
    real-data constraint -- no crop-type, crop-stage, or livestock-
    species-beyond-cattle data exists anywhere in this pipeline, so Stage 3
    is told that plainly rather than silently omitting the field and
    risking an invented "maize/sorghum" guess. `supporting_indicators` is
    compacted the same way as Stage 2's cross-indicator block (see
    _compact_indicator_criteria) for the same real reason -- this field is
    literally the same verbose object shape, copied through unchanged from
    cross_indicator_findings by build_priority_area_justifications.
    """
    actionable_areas = []
    monitor_only_areas = []
    for item in stage2_result.get("priority_area_justification") or []:
        if not isinstance(item, dict):
            continue
        action_status = item.get("action_status")
        if action_status in ("action", "preparedness"):
            hazard_probability = item.get("hazard_probability")
            actionable_areas.append({
                "area": item.get("area"),
                "rank": item.get("rank"),
                "hazard": item.get("hazard_type"),
                "risk_score": item.get("risk_score"),
                "hazard_probability_pct": round(hazard_probability * 100, 1) if isinstance(hazard_probability, (int, float)) else None,
                "vulnerability": item.get("vulnerability"),
                "cross_indicator_confidence": item.get("cross_indicator_confidence"),
                "data_quality_confidence": item.get("data_quality_confidence"),
                "recommended_intervention_type": item.get("recommended_intervention_type"),
                "population_exposed": item.get("population_exposed"),
                "population_exposed_pct": item.get("population_exposed_pct"),
                "roads_exposed_pct": item.get("roads_exposed_pct"),
                # Real denominators (see build_priority_area_justifications'
                # exposure-loop comment) -- real OSM-derived km/count, not
                # just the density share above.
                "roads_length_total_km": item.get("roads_length_total_km"),
                "roads_length_exposed_km": item.get("roads_length_exposed_km"),
                "healthsites_exposed_pct": item.get("healthsites_exposed_pct"),
                "healthsites_total_count": item.get("healthsites_total_count"),
                "healthsites_exposed_count": item.get("healthsites_exposed_count"),
                "cropland_exposed_pct": item.get("cropland_exposed_pct"),
                "livestock_exposed_pct": item.get("livestock_exposed_pct"),
                "low_sample_size_warning": item.get("low_sample_size_warning"),
                "cross_indicator_signal": item.get("cross_indicator_signal"),
                "supporting_indicators": _compact_indicator_criteria(item.get("supporting_indicators")),
                "ground_truth": _compact_community_reports(item.get("community_reports")),
                "livelihood_context": "not_available",
            })
        else:
            monitor_only_areas.append({
                "area": item.get("area"),
                "hazard": item.get("hazard_type"),
                "rank": item.get("rank"),
                "risk_class": item.get("risk_class"),
                "cross_indicator_signal": item.get("cross_indicator_signal"),
                # Only cross_indicator_confidence, not data_quality_
                # confidence -- monitor_only_areas is deliberately minimal
                # (see this function's own docstring); this one field is
                # included only because the monitoring-tier bullet schema
                # requires SOME real confidence value to echo.
                "cross_indicator_confidence": item.get("cross_indicator_confidence"),
                "reason": action_status or "monitor_only",
            })

    return {
        "executive_summary": stage2_result.get("executive_summary"),
        "data_quality_notes": stage1_result.get("data_quality_notes"),
        "actionable_areas": actionable_areas,
        "monitor_only_areas": monitor_only_areas,
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

    # Real single-SMS-segment character budgets, not a single hardcoded
    # 160: Amharic/Tigrinya render in Ethiopic script, which is outside the
    # GSM-7 alphabet and forces UCS-2 encoding (70 chars/segment, not 160)
    # -- a fixed 160-char target would silently double the real SMS cost
    # for those 2 languages. Oromifa/Somali/English stay in the GSM-7 range.
    sms_char_budget = 70 if request.target_language in ("am", "ti") else 155
    language_label = get_language_label(request.target_language)

    user_prompt = f"""{_context_header(request)}

This is Stage 3 of a 3-stage report pipeline: ACTION TRANSLATION. Translate Stage 1 and Stage 2's validated findings into audience-specific advisories. Do not introduce new evidence, hazards, or areas that are not already present in the given findings.

AUDIENCE FOCUS:
{request.audience_focus}

ACTION EVIDENCE PACKET (the real, validated executive summary plus every priority area's real numbers -- everything you need is here; every number is real and already computed, do NOT recompute, reorder, add, or drop any). Split into two real groups by this period's actual action_status, not just top-N rank: `actionable_areas` (action_status "action"/"preparedness" -- full real risk/exposure/climate-signal detail, the only areas that may receive a real response recommendation) and `monitor_only_areas` (every other real priority area -- area/hazard/rank/risk_class/cross_indicator_signal/cross_indicator_confidence/reason only; no exposure, indicator, or data_quality_confidence numbers were computed for these since none of them justify an operational response this period). `supporting_indicators` within `actionable_areas` is a compact {{criterion: real_value}} dict, unit baked into each key name (e.g. "spi_stddev": -1.12, "cdd_anomaly_days": 3.25) -- same convention as Stage 2's cross-indicator block:
{compact_json(action_packet, max_chars=16000)}

RETRIEVED EARLY-ACTION GUIDANCE (use to inform the actions below, not to introduce new hazards or areas):
{compact_json(retrieved_guidance_for_stage3, max_chars=6000)}

GROUNDING NOTES FOR THIS STAGE:
- `cross_indicator_confidence` measures ONLY how strongly this area's climate indicators agree with each other -- it is NOT a measure of data completeness (`data_quality_confidence`, present on `actionable_areas` -- "low" means this area's real statistics came from a small real number of grid cells, treat as a coarser estimate) or forecast/ensemble skill. No real ensemble-spread or forecast-skill data exists anywhere in this pipeline -- never report, cite, or invent a "forecast confidence" value; if you need a single confidence value for an output bullet's `cross_indicator_confidence` field, always use the real value already given for that area, never synthesize one from other signals.
- `vulnerability` in the findings above is a real FEWS NET IPC food-security-phase-derived index, not a generic composite score -- use it explicitly when a priority is food-security-linked.
- `roads_length_total_km`/`roads_length_exposed_km` and `healthsites_total_count`/`healthsites_exposed_count` are REAL denominators, not just a density share -- real OSM major-road length (km) and real OSM health-facility counts, fetched live and rasterized onto this pipeline's real grid (see app.data_pipeline.infrastructure_data_pipeline). You MAY now phrase these as real counts, e.g. "3 of 3 real health facilities in Harari fall within the exposed area" or "70.6 of 276.3 km of major road exposed" -- these are genuinely real numbers, not an estimate dressed up as one. Two real scope caveats to disclose when citing them, not silently ignore: (1) roads cover ONLY motorway/trunk/primary/secondary/tertiary classes (real major roads only, deliberately excluding residential/service/minor roads); (2) real road length per pixel is an interval-sampling approximation of each real road's real geometry, not exact surveyed length -- close, not exact. `healthsites_total_count`/`roads_length_total_km` reflect real OSM coverage for Ethiopia, which can vary by area -- do not imply a real facility/road exists if the real count is 0, but also do not claim 0 real facilities means no real access, only that none are mapped in OSM for that area.
- `roads_exposed_pct`/`healthsites_exposed_pct`/`cropland_exposed_pct`/`livestock_exposed_pct` are each the real share of the above (or, for cropland/livestock, a normalized 0-1 DENSITY index) that falls within this hazard's exposure threshold in that area. `cropland_exposed_pct`/`livestock_exposed_pct` specifically are NOT a real count of hectares or animals (no real cropland-area or livestock-headcount dataset exists anywhere in this pipeline) -- never phrase THOSE two as "N hectares of cropland" or "N head of livestock", say "a high share of the area's cropland/cattle density" instead. Treat a small area's percentage or count (e.g. Harari, Dire Dawa, Addis Ababa -- each covered by only a handful of raster cells) as a coarser estimate than a large region's. `cropland_exposed_pct` is the most operationally relevant for farmer_advisory; `livestock_exposed_pct` is the most operationally relevant for agro_pastoral_advisory -- ground those advisories in them directly rather than only the generic hazard/risk numbers.
- `livestock_exposed_pct` is CATTLE ONLY (the only livestock species with its own raster in this pipeline) -- never describe it as covering sheep, goats, or livestock generally; say "cattle density exposure" or similar, not "livestock exposure". It is also still only a density-exposure share, not a headcount or mortality rate -- livestock mortality risk has no real measured rate anywhere in this pipeline, so describe mortality risk only qualitatively (e.g. "elevated livestock mortality risk"), grounded in the real hazard severity/probability and `livestock_exposed_pct` already given for that area, never a fabricated mortality number.
- Do not recommend pre-positioning or immediate humanitarian action based on rainfall anomaly alone -- require it to be corroborated by real exposure, vulnerability, or hazard-probability values from the findings above.
- Write conditional advice using the REAL numbers already given (e.g. "given a CDD anomaly of +N days and drought probability of X"), not an invented fixed agronomic threshold -- no such universal threshold exists in the supplied evidence.
- Every area's livelihood_context is "not_available" -- no crop-type, crop-stage, or livestock-species-beyond-cattle data exists in this pipeline. Do not invent specific crops (e.g. "maize", "sorghum") or livestock species beyond cattle -- write farmer/agro-pastoral advice in terms of the real signals you do have (rainfall, drought/wet risk, `livestock_exposed_pct`'s real cattle-density share), not fabricated agronomic specifics.
- The evidence above comes from the forecast window/lead stated at the top (CONTEXT), not a short-range weather forecast -- for a Seasonal window, "immediate" bullets must be no-regret PREPARATION actions justified by the seasonal signal (e.g. "conserve water given this period's drought signal"), never phrased as predicting weather on specific days within the next 7 days, since no day-specific forecast was supplied. Only for a Subseasonal window (week-level lead) is day-specific framing within "immediate" appropriate.
- Keep each sms_messages "message" to at most {sms_char_budget} characters in {language_label} -- this is the real single-SMS-segment budget for this output language (Amharic/Tigrinya use Ethiopic script, which forces the 70-character UCS-2 SMS limit rather than the 160-character GSM-7 limit Latin-script languages get). A message that needs 2 segments to say less is worse than a shorter one that fits in 1.

TASK:
1. Provide farmer_advisory as an object with 3 keys -- immediate (next 7 days), near_term (next 2-4 weeks), preparedness (remainder of the forecast period) -- each an ARRAY OF OBJECTS (not bare strings), one per distinct piece of advice, each with exactly these keys: "area" (array of the real area name(s) from actionable_areas above this specific advice applies to -- never invented, never a generic national bullet with no real area attached, and never an area that only appears in monitor_only_areas), "action" (the advice itself, in plain language, for rainfed-agriculture farmers), "trigger" (that area's real cross_indicator_signal or hazard, e.g. "strong_drought"), "evidence" (array of that area's real supporting_indicators dict KEYS, e.g. ["spi_stddev", "cdd_anomaly_days"]), "cross_indicator_confidence" (that area's real cross_indicator_confidence value, echoed back -- never its data_quality_confidence, a different real signal).
2. Provide agro_pastoral_advisory in the SAME object-per-bullet shape, for agro-pastoral / livestock-keeping communities specifically -- distinct guidance from farmer_advisory, not a repeat of the same bullets. Same actionable_areas-only rule as above.
3. Provide humanitarian_priorities as an object with 4 keys -- monitoring, preparedness, pre_positioning, immediate_action -- each in the SAME object-per-bullet shape as above (area/action/trigger/evidence/cross_indicator_confidence). The monitoring tier is the ONLY one that may draw from BOTH actionable_areas AND monitor_only_areas (every real priority area is worth watching, even a non-actionable one) -- for a monitor_only_areas entry, ground its bullet only in the real hazard/risk_class/cross_indicator_signal/reason given (its "evidence" array may be empty, since no exposure/indicator numbers exist for it). The other 3 tiers (preparedness, pre_positioning, immediate_action) must draw ONLY from actionable_areas, explicitly linked to the real triggers given (population exposed, vulnerability/food-security, road/health exposure, hazard probability, cross_indicator_confidence, and data_quality_confidence when it's "low") -- never write a preparedness/pre_positioning/immediate_action bullet for a monitor_only_areas entry, since that would imply a stronger response than its real risk signal supports.
4. Provide sms_messages as an array of objects, one per area in actionable_areas above ONLY (never for an area that only appears in monitor_only_areas, and never invent an area not listed in either), each with exactly these keys: "area" (the real area name), "audience" ("farmer", "agro_pastoral", "humanitarian", or "general"), "hazard" (that area's real hazard), "valid_period" (echo the real valid period from CONTEXT above), "cross_indicator_confidence" (that area's real cross_indicator_confidence), "message" (a short, real, actionable SMS text in the output language, grounded only in that area's real numbers -- do not restate every number, explain what they mean). It is normal and expected to return FEWER messages than the number of areas in actionable_areas, or zero when nothing is really actionable this period -- do not pad this list to look complete.

Return only JSON with these keys: farmer_advisory, agro_pastoral_advisory, humanitarian_priorities, sms_messages.""".strip()

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


def _finalize_sms_messages(
    messages: List[Dict[str, Any]], priority_areas: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Real, server-side finalization for Stage 3's sms_messages. Unlike
    layer summaries/priority areas, sms_messages has no fixed deterministic
    per-slot merge target -- the model itself decides how many messages to
    write and for which real areas, per build_stage3_prompt's task
    instructions -- so this does two things instead of a 1:1 merge:
    1. character_count is always computed here, never trusted from the
       model -- there is exactly one real right answer (len(message)).
    2. Any message whose "area" doesn't match a real priority area name is
       dropped entirely, rather than letting an invented area reach an
       end-user-facing SMS -- the one remaining safety net for this field.
    """
    real_area_names = {item.get("area") for item in priority_areas if item.get("area")}
    finalized = []
    for item in messages:
        if not isinstance(item, dict) or item.get("area") not in real_area_names:
            continue
        message_text = item.get("message") or ""
        finalized.append({**item, "character_count": len(message_text)})
    return finalized


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
    # layer_by_layer_summary/indicator_by_indicator_summary from run_stage
    # are narrative-only (either real LLM output -- just {layer/indicator,
    # interpretation} pairs now, see build_stage1_prompt -- or the
    # deterministic fallback's own already-complete objects) -- always
    # merge onto the real deterministic summaries before use, so the
    # numbers/classes/area names shown are never LLM-authored.
    stage1["layer_by_layer_summary"] = _merge_structured_summaries(
        build_structured_layer_summaries(evidence), stage1.get("layer_by_layer_summary", []), "layer",
    )
    stage1["indicator_by_indicator_summary"] = _merge_structured_summaries(
        build_structured_indicator_summaries(evidence), stage1.get("indicator_by_indicator_summary", []), "indicator",
    )

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
    # sms_messages has no deterministic per-slot merge target the way
    # layer summaries/priority areas do (the model decides how many
    # messages to write, for which areas) -- character_count is always
    # computed here, never trusted from the model (there is exactly one
    # real right answer), and any message for an area that isn't a real
    # priority area is dropped rather than reaching an end-user-facing SMS.
    stage3["sms_messages"] = _finalize_sms_messages(stage3.get("sms_messages", []), priority_areas)

    merged: Dict[str, Any] = {**_base_report_fields(request), **stage1, **stage2, **stage3}
    merged = validate_report_shape(merged)

    # Which stages (if any) silently dropped to the deterministic rule-based
    # path -- e.g. one transient provider error on Stage 2 alone. Surfaced
    # explicitly here (not just buried in "stages" below) because the old
    # single "ai_engine": "staged_workflow" value was true even when every
    # stage had fallen back, giving the UI no honest way to say so -- and
    # fallback_report() never translates, so a fallback stage's text is
    # always English regardless of target_language.
    fallback_stages = [name for name, meta in stage_metadata.items() if meta.get("ai_engine") == "rule_based_fallback"]
    if not fallback_stages:
        ai_engine = "staged_workflow"
    elif len(fallback_stages) == len(stage_metadata):
        ai_engine = "staged_workflow_full_fallback"
    else:
        ai_engine = "staged_workflow_partial_fallback"

    stage1_meta = stage_metadata.get("stage1", {})
    merged["_metadata"] = {
        "ai_engine": ai_engine,
        "provider": stage1_meta.get("provider"),
        "model": stage1_meta.get("model"),
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
        "period": period,
        "fallback_stages": fallback_stages,
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
