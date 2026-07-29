"""Adapts REAL Hazard/Risk ranking + spatial-summary data into the exact
shape app.api.ai_map_interpretation.AIMapInterpretationRequest already
expects for top_admin_areas / all_map_layer_summaries /
all_climate_indicator_summaries.

This is the concrete fix for the two data-alignment gaps found before this
work started: that endpoint previously sourced this data from
app.api.main.build_intervention_ranking_cached (the OLD synthetic
0.5-degree grid, same legacy system as /api/risk) instead of the REAL
WorldPop/GLW4-based app.api.hazard_risk_ranking.compute_district_ranking
data the on-screen Priority Intervention Areas table actually renders.

Field names in the returned top_admin_areas dicts (risk_score,
hazard_probability, exposure, vulnerability, region/zone/woreda) are kept
backward-compatible with what ai_map_interpretation.py's fallback_report()
and retrieve_guidance() already read via .get() -- only the SOURCE of the
numbers changes, not the shape old code expects.
"""

from typing import Any, Dict, List, Optional

from app.api.hazard_risk_catalog_shared import LAYER_BY_VALUE
from app.api.hazard_risk_ranking import compute_district_ranking, default_threshold_for
from app.context.spatial_summary import summarize_climate_indicator, summarize_hazard_risk_layer

# Maps the OLD legacy top_admin_areas field names (risk_score/
# hazard_probability/exposure/vulnerability) onto the real ranking item's
# metrics dict keys, for whichever hazard_type (drought/wet) is active.
LEGACY_FIELD_ALIASES_BY_HAZARD_TYPE = {
    "drought": {"hazard": "h_dry_mean", "probability": "p_drought", "vulnerability": "v_drought", "risk": "population_r_drought"},
    "wet": {"hazard": "h_wet_mean", "probability": "p_wet", "vulnerability": "v_wet", "risk": "population_r_wet"},
}

# MAP_LAYER_LABELS keys (app.api.ai_map_interpretation) -> real catalog
# layer_value, resolved per hazard_type at call time.
LEGACY_MAP_LAYER_KEY_TO_CATALOG = {
    "hazard": "hazard",
    "risk_score": "risk",
    "hazard_probability": "probability",
    "exposure": "population_normalized",  # not hazard-type-specific
    "vulnerability": "vulnerability",
}

# CLIMATE_INDICATOR_LABELS keys (app.api.ai_map_interpretation) that overlap
# with app.context.spatial_summary.CLIMATE_INDICATORS -- dryspell_prob_Xd
# and rainfall_anomaly_pct aren't in that list (see spatial_summary.py's
# docstring for why), so those legacy keys are left unpopulated here
# (existing code already renders "no national summary was provided" for an
# absent key, which is honest rather than a forced/wrong mapping). rx1day/
# rx5day WERE missing from this mapping until found alongside the
# dryspell_prob_Xd stale-list drift -- they're real, currently-visible
# indicators (see ai_map_interpretation.VISIBLE_CLIMATE_INDICATORS), so
# they must resolve to real summaries here, not silently fall through to
# "no national summary was provided" like the genuinely-hidden ones.
LEGACY_CLIMATE_KEY_TO_INDICATOR = {
    "rainfall_total": "rainfall_total",
    "spi": "spi",
    "cdd": "cdd",
    "cwd": "cwd",
    "rx1day": "rx1day",
    "rx5day": "rx5day",
    "rainfall_percentile": "rainfall_percentile",
}


def build_top_admin_areas(
    rank_by: str,
    period: str,
    admin_level: str,
    top_n: int,
    threshold: Optional[float] = None,
    region_id: str = "",
    zone_id: str = "",
) -> List[Dict[str, Any]]:
    definition = LAYER_BY_VALUE.get(rank_by, {})
    hazard_type = definition.get("hazard_type") or "drought"
    aliases = LEGACY_FIELD_ALIASES_BY_HAZARD_TYPE.get(hazard_type, LEGACY_FIELD_ALIASES_BY_HAZARD_TYPE["drought"])

    resolved_threshold = threshold if threshold is not None else default_threshold_for(rank_by, period)
    metrics = [aliases["hazard"], aliases["probability"], aliases["vulnerability"], "population_normalized"]

    result = compute_district_ranking(
        metrics=metrics, rank_by=rank_by, period=period, admin_level=admin_level,
        selection_mode="top", top_n=top_n, threshold=resolved_threshold,
        region_id=region_id, zone_id=zone_id,
    )

    areas = []
    for item in result["ranking"]:
        item_metrics = item.get("metrics", {})
        areas.append({
            "area_name": item["area_name"],
            "region": item.get("region", ""),
            "zone": item.get("zone", ""),
            "woreda": item.get("woreda", ""),
            "hazard": hazard_type,
            "risk_score": item["priority_score"],
            "hazard_probability": item_metrics.get(aliases["probability"]),
            "exposure": item_metrics.get("population_normalized"),
            "vulnerability": item_metrics.get(aliases["vulnerability"]),
            "population_exposed": item.get("population_exposed"),
            "population_exposed_pct": item.get("population_exposed_pct"),
            "area_extent_km2": item.get("area_extent_km2"),
            "rank": item.get("rank"),
            "rank_value": item.get("rank_value"),
        })
    return areas


def build_legacy_layer_summaries(period: str, hazard_type: str = "drought") -> Dict[str, Any]:
    aliases = LEGACY_FIELD_ALIASES_BY_HAZARD_TYPE.get(hazard_type, LEGACY_FIELD_ALIASES_BY_HAZARD_TYPE["drought"])
    resolved_by_category = {
        "hazard": aliases["hazard"],
        "risk_score": aliases["risk"],
        "hazard_probability": aliases["probability"],
        "exposure": "population_normalized",
        "vulnerability": aliases["vulnerability"],
    }

    summaries: Dict[str, Any] = {}
    for legacy_key, layer_value in resolved_by_category.items():
        summary = summarize_hazard_risk_layer(layer_value, period=period)
        if summary:
            summaries[legacy_key] = summary
    return summaries


def build_legacy_climate_indicator_summaries(period: str) -> Dict[str, Any]:
    summaries: Dict[str, Any] = {}
    for legacy_key, indicator in LEGACY_CLIMATE_KEY_TO_INDICATOR.items():
        summary = summarize_climate_indicator(indicator, period=period, product="forecast")
        if summary:
            summaries[legacy_key] = summary
    return summaries
