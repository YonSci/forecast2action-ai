"""Builds ForecastContext, GeographicContext, HazardEvidence, and
ImpactContext from ONE real data source: app.api.hazard_risk_ranking's
compute_district_ranking -- the real WorldPop/GLW4-based ranking system,
NOT app.api.main's build_intervention_ranking_cached (the old synthetic
0.5-degree grid, same legacy system behind /api/risk).

app/context/geographic_context.py and app/context/impact_context.py both
re-export build_hazard_geo_impact_context from here rather than
reimplementing any part of it, since all four context pieces come from the
exact same ranking-item lookup.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.api.hazard_risk_catalog_shared import LAYER_BY_VALUE
from app.api.hazard_risk_maps import find_map_record, get_map_statistics_cached
from app.api.hazard_risk_ranking import compute_district_ranking, default_threshold_for
from app.context.schemas import ForecastContext, GeographicContext, HazardEvidence, ImpactContext

logger = logging.getLogger(__name__)


def _select_item(ranking: List[Dict], target_area_name: Optional[str]) -> Optional[Dict]:
    if not ranking:
        return None

    if target_area_name:
        for item in ranking:
            if item.get("area_name", "").lower() == target_area_name.lower():
                return item
        logger.info(
            "target_area_name=%s not found in top-%d ranking -- falling back to rank #1",
            target_area_name, len(ranking),
        )

    return ranking[0]


def _observed_ceiling(layer_value: str, period: str) -> Optional[float]:
    record = find_map_record(layer_value, period)
    if not record:
        return None
    try:
        return float(get_map_statistics_cached(record["id"])["max"])
    except (KeyError, TypeError):
        return None


def build_hazard_geo_impact_context(
    *,
    rank_by: str,
    period: str = "JJAS",
    admin_level: str = "admin3",
    region_id: str = "",
    zone_id: str = "",
    top_n: int = 5,
    selection_mode: str = "top",
    threshold: Optional[float] = None,
    target_area_name: Optional[str] = None,
    forecast_scale: str = "subseasonal",
    lead: str = "",
) -> Tuple[ForecastContext, GeographicContext, HazardEvidence, ImpactContext]:
    """Real evidence for one ranked area, via app.api.hazard_risk_ranking's
    compute_district_ranking -- the SAME data source TopInterventionAreas.jsx
    renders on screen, so the AI reasons about the same areas/numbers the
    user sees in the actual table.
    """
    if rank_by not in LAYER_BY_VALUE:
        raise ValueError(f"Unknown hazard/risk layer: {rank_by}")

    resolved_threshold = threshold if threshold is not None else default_threshold_for(rank_by, period)

    result = compute_district_ranking(
        metrics=[],
        rank_by=rank_by,
        period=period,
        admin_level=admin_level,
        selection_mode=selection_mode,
        top_n=top_n,
        threshold=resolved_threshold,
        region_id=region_id,
        zone_id=zone_id,
    )

    item = _select_item(result["ranking"], target_area_name)

    if item is None:
        raise ValueError(
            f"No ranked areas found for rank_by={rank_by} period={period} "
            f"admin_level={admin_level} region_id={region_id} zone_id={zone_id}."
        )

    definition = LAYER_BY_VALUE[rank_by]

    forecast = ForecastContext(
        forecast_scale=forecast_scale,
        lead=lead,
        hazard_risk_period=period,
        rank_by=rank_by,
        admin_selection_mode=selection_mode,
        top_n=top_n,
        threshold=resolved_threshold,
        evidence_status="forecast_signal",
    )

    geography = GeographicContext(
        admin_level=admin_level,
        area_name=item["area_name"],
        region=item.get("region", ""),
        zone=item.get("zone", ""),
        woreda=item.get("woreda", ""),
        region_id=item.get("region_id", ""),
        zone_id=item.get("zone_id", ""),
        woreda_id=item.get("woreda_id", ""),
        boundary_feature=item.get("boundary_feature"),
    )

    hazard_evidence = HazardEvidence(
        layer_value=rank_by,
        layer_label=definition["label"],
        hazard_type=definition.get("hazard_type"),
        category=definition["category"],
        units=definition["units"],
        rank_value=item["rank_value"],
        priority_score=item["priority_score"],
        rank=item.get("rank"),
        metrics=item.get("metrics", {}),
        observed_ceiling=_observed_ceiling(rank_by, period),
        drought_risk=item.get("drought_risk"),
        wet_risk=item.get("wet_risk"),
    )

    impact = ImpactContext(
        population_total=item.get("population_total"),
        population_exposed=item.get("population_exposed"),
        population_exposed_pct=item.get("population_exposed_pct"),
        area_total_km2=item.get("area_total_km2"),
        area_extent_km2=item.get("area_extent_km2"),
        area_extent_pct=item.get("area_extent_pct"),
        cropland_extent_pct=item.get("cropland_extent_pct"),
    )

    return forecast, geography, hazard_evidence, impact
