"""National/layer-by-layer and climate-indicator spatial summaries, built
from REAL data sources -- this replaces AIMapInterpretation.jsx's
buildAllLayerSummaries/buildAllClimateIndicatorSummaries, which currently
make 9+ client-side calls to the OLD /api/intervention-ranking (legacy
synthetic 0.5-degree grid). Everything here reads the same real rasters
already used by the Hazard/Risk Layers viewer and the Priority Intervention
Areas table.
"""

import logging
from typing import Any, Dict, List, Optional

from app.api.hazard_risk_catalog_shared import LAYER_BY_VALUE
from app.api.hazard_risk_maps import find_map_record as find_hazard_risk_record
from app.api.hazard_risk_maps import get_map_statistics_cached as hazard_risk_statistics
from app.api.hazard_risk_ranking import RANKING_EXCLUDED_LAYERS, compute_district_ranking, default_threshold_for
from app.api.seasonal_raster_maps import find_map_record as find_seasonal_record
from app.api.seasonal_raster_maps import get_map_statistics_cached as seasonal_statistics
from app.api.seasonal_raster_maps import load_display_array as load_seasonal_display_array

logger = logging.getLogger(__name__)

# The 7 climate indicators named in the project spec (a subset of
# seasonal_catalog_shared.INDICATORS -- the 3 dryspell_prob_Xd indicators
# aren't in the spec's list, so they're left out of this national-summary
# sweep, though they remain fully available via the existing seasonal
# raster endpoints for direct map viewing).
CLIMATE_INDICATORS = [
    "rainfall_total", "spi", "cdd", "cwd", "rx1day", "rx5day", "rainfall_percentile",
]

# SPI has no climatology/anomaly rasters (it's already a standardized
# index) -- its 3-product view is Forecast/Drought Probability/Wet
# Probability instead, matching seasonal_catalog_shared.INDICATOR_COMPARE_PRODUCTS
# and the project spec's own "SPI (Forecast, Drought Probability, and Wet
# Probability)" wording.
PRODUCTS_BY_INDICATOR = {
    "spi": ["forecast", "drought_probability", "wet_probability"],
}
DEFAULT_PRODUCTS = ["forecast", "climatology", "anomaly"]

TOP_AREAS_PER_LAYER = 3

# The 11 Hazard/Risk layers requested for the comprehensive "send every map"
# report -- NOT all of LAYER_BY_VALUE, which also has 9 exposure sub-layers
# (cropland x3, livestock, built-up, buildings, roads, healthsites,
# population) beyond just population_normalized. Keeping this as an
# explicit list (rather than iterating the whole catalog) avoids leaking
# those extra layers into a report that's only supposed to cover this
# specific set.
HAZARD_RISK_LAYERS_FOR_REPORT = [
    "h_dry_mean", "h_wet_mean",
    "p_drought", "p_wet",
    "population_normalized",
    "v_drought", "v_wet",
    "population_r_drought", "population_r_wet", "population_risk_class", "population_dominant_code",
]


def summarize_hazard_risk_layer(
    layer_value: str, period: str = "JJAS", admin_level: str = "admin1",
) -> Optional[Dict[str, Any]]:
    """National statistics (real raster, via get_map_statistics_cached) plus
    top-ranked admin areas (real, via compute_district_ranking) for one
    Hazard/Risk catalog layer.
    """
    definition = LAYER_BY_VALUE.get(layer_value)
    if not definition:
        return None

    record = find_hazard_risk_record(layer_value, period)
    if not record:
        logger.info("No hazard/risk map found for layer=%s period=%s", layer_value, period)
        return None

    try:
        stats = hazard_risk_statistics(record["id"])
    except Exception:
        logger.exception("Failed to compute statistics for layer=%s period=%s", layer_value, period)
        return None

    top_areas: List[Dict[str, Any]] = []
    if layer_value not in RANKING_EXCLUDED_LAYERS:
        try:
            ranking = compute_district_ranking(
                metrics=[], rank_by=layer_value, period=period, admin_level=admin_level,
                selection_mode="top", top_n=TOP_AREAS_PER_LAYER,
                threshold=default_threshold_for(layer_value, period),
                region_id="", zone_id="",
            )
            top_areas = [
                {"area_name": item["area_name"], "region": item.get("region", ""), "rank_value": item["rank_value"]}
                for item in ranking["ranking"]
            ]
        except Exception:
            logger.exception("Failed to rank layer=%s period=%s for top areas", layer_value, period)

    return {
        "layer_value": layer_value,
        "layer_label": definition["label"],
        "category": definition["category"],
        "hazard_type": definition.get("hazard_type"),
        "units": definition["units"],
        "period": period,
        "init_date": record.get("init_date", ""),
        "statistics": stats,
        "top_areas": top_areas,
    }


def build_all_layer_summaries(period: str = "JJAS", admin_level: str = "admin1") -> List[Dict[str, Any]]:
    summaries = []
    for layer_value in HAZARD_RISK_LAYERS_FOR_REPORT:
        summary = summarize_hazard_risk_layer(layer_value, period=period, admin_level=admin_level)
        if summary:
            summaries.append(summary)
    return summaries


def climate_indicator_region_breakdown(
    arr: Any, transform: Any, admin_level: str = "admin1", top_n: int = 3,
) -> Dict[str, List[Dict[str, Any]]]:
    """Top/bottom admin_level regions by mean value for one raster array.

    Reuses app.api.hazard_risk_ranking's zonal-stats machinery
    (load_admin_features/build_district_label_array/
    zonal_stats_for_all_districts) -- those functions are raster-agnostic
    (take any array + matching transform), not specific to the Hazard/Risk
    catalog, so this needs no new rasterization logic, only wiring against
    a seasonal climate-indicator raster's own array/transform instead of a
    hazard/risk one.
    """
    from app.api.hazard_risk_ranking import (
        _area_label, build_district_label_array, filter_admin_features,
        load_admin_features, zonal_stats_for_all_districts,
    )
    import numpy as np

    features = filter_admin_features(load_admin_features(admin_level))
    if not features:
        return {"top_areas": [], "bottom_areas": []}

    label_array = build_district_label_array(features, arr.shape, transform)
    district_ids = list(range(1, len(features) + 1))
    # threshold is a required zonal_stats_for_all_districts parameter, but
    # its above_threshold_fraction output isn't used here -- ranking is by
    # mean value, not by a hazard-style threshold-exceedance fraction. Any
    # finite value works; the array's own mean keeps it a real number
    # rather than an arbitrary sentinel.
    stats = zonal_stats_for_all_districts(
        arr, label_array, district_ids, threshold=float(np.nanmean(arr)),
    )

    ranked = sorted(
        (
            {
                "area_name": _area_label(features[district_id - 1].get("properties", {}), admin_level),
                "region": features[district_id - 1].get("properties", {}).get("region", ""),
                "mean_value": round(entry["mean"], 3),
            }
            for district_id, entry in stats.items()
        ),
        key=lambda item: item["mean_value"],
    )
    return {"top_areas": ranked[-top_n:][::-1], "bottom_areas": ranked[:top_n]}


def summarize_climate_indicator(
    indicator: str, period: str = "JJAS", product: str = "forecast",
) -> Optional[Dict[str, Any]]:
    """National statistics plus a real per-region (admin1) breakdown for one
    climate-indicator raster, via app.api.seasonal_raster_maps -- this data
    is already real (not synthetic), it just wasn't previously used by the
    AI's national-summary construction. The region breakdown gives the LLM
    actual named regions to cite instead of only a national min/max/mean,
    matching what summarize_hazard_risk_layer already does for hazard/risk
    layers via top_areas.
    """
    record = find_seasonal_record(indicator, period, product)
    if not record:
        logger.info("No seasonal raster found for indicator=%s period=%s product=%s", indicator, period, product)
        return None

    try:
        stats = seasonal_statistics(record["id"])
    except Exception:
        logger.exception("Failed to compute statistics for indicator=%s period=%s product=%s", indicator, period, product)
        return None

    top_areas: List[Dict[str, Any]] = []
    bottom_areas: List[Dict[str, Any]] = []
    try:
        arr, transform, _bounds = load_seasonal_display_array(record)
        breakdown = climate_indicator_region_breakdown(arr, transform)
        top_areas = breakdown["top_areas"]
        bottom_areas = breakdown["bottom_areas"]
    except Exception:
        logger.exception(
            "Failed to compute regional breakdown for indicator=%s period=%s product=%s", indicator, period, product,
        )

    return {
        "indicator": indicator,
        "period": period,
        "product": product,
        "init_date": record.get("init_date", ""),
        "statistics": stats,
        "top_areas": top_areas,
        "bottom_areas": bottom_areas,
    }


def build_all_climate_indicator_summaries(period: str = "JJAS") -> List[Dict[str, Any]]:
    summaries = []
    for indicator in CLIMATE_INDICATORS:
        for product in PRODUCTS_BY_INDICATOR.get(indicator, DEFAULT_PRODUCTS):
            summary = summarize_climate_indicator(indicator, period=period, product=product)
            if summary:
                summaries.append(summary)
    return summaries


# Some providers (confirmed: NVIDIA NIM, hard 400 at >16 images per
# request) can't take all 32 comprehensive images in one call. Rather than
# dropping images arbitrarily when a provider needs a cap, every image is
# tagged with a priority so callers can slice the front of the list and
# still get a sensible subset: all 11 Hazard/Risk layers (operational
# priority -- these drive trigger/policy decisions) first, then the
# Forecast-product image for the 5 "core" climate indicators, then
# everything else (Climatology/Anomaly variants, Rx1day/Rx5day -- more
# specialized extreme-rainfall signals) last.
CORE_CLIMATE_INDICATORS_FOR_IMAGE_PRIORITY = ["rainfall_total", "spi", "cdd", "cwd", "rainfall_percentile"]


async def build_all_map_images(period: str = "JJAS", admin_level: str = "admin1") -> List[Dict[str, str]]:
    """Renders every Hazard/Risk layer (HAZARD_RISK_LAYERS_FOR_REPORT) and
    every climate-indicator combo (CLIMATE_INDICATORS x its real products)
    for one period as a base64 PNG, reusing the SAME full-country image
    renderer already used for the on-screen Leaflet ImageOverlay --
    app.api.seasonal_raster_maps.get_full_image / app.api.hazard_risk_maps
    .get_hazard_risk_image. No new rendering pipeline; this just calls
    those route functions in-process instead of over HTTP, for every
    map_id in the catalog instead of just the one currently displayed.

    Returns images in priority order (see CORE_CLIMATE_INDICATORS_FOR_IMAGE_
    PRIORITY above) so a caller needing to cap the list for a provider's
    per-request image limit can just take the first N.

    Each image is independently wrapped in try/except (logged, skipped) so
    one broken/missing raster doesn't block the other ~31.
    """
    import base64

    from app.api.hazard_risk_maps import get_hazard_risk_image
    from app.api.seasonal_raster_maps import get_full_image

    images: List[Dict[str, str]] = []

    async def add_hazard_risk_image(layer_value: str) -> None:
        record = find_hazard_risk_record(layer_value, period)
        if not record:
            return
        try:
            response = await get_hazard_risk_image(record["id"])
            images.append({
                "map_id": record["id"],
                "label": f"{LAYER_BY_VALUE[layer_value]['label']} ({period})",
                "data_url": f"data:image/png;base64,{base64.b64encode(response.body).decode('ascii')}",
            })
        except Exception:
            logger.exception("Failed to render hazard/risk image for layer=%s period=%s", layer_value, period)

    async def add_climate_image(indicator: str, product: str) -> None:
        record = find_seasonal_record(indicator, period, product)
        if not record:
            return
        try:
            response = await get_full_image(record["id"])
            images.append({
                "map_id": record["id"],
                "label": f"{record.get('indicator_label', indicator)} - {record.get('product_label', product)} ({period})",
                "data_url": f"data:image/png;base64,{base64.b64encode(response.body).decode('ascii')}",
            })
        except Exception:
            logger.exception(
                "Failed to render seasonal image for indicator=%s period=%s product=%s", indicator, period, product,
            )

    for layer_value in HAZARD_RISK_LAYERS_FOR_REPORT:
        await add_hazard_risk_image(layer_value)

    included_combos = set()
    for indicator in CORE_CLIMATE_INDICATORS_FOR_IMAGE_PRIORITY:
        await add_climate_image(indicator, "forecast")
        included_combos.add((indicator, "forecast"))

    for indicator in CLIMATE_INDICATORS:
        for product in PRODUCTS_BY_INDICATOR.get(indicator, DEFAULT_PRODUCTS):
            if (indicator, product) in included_combos:
                continue
            await add_climate_image(indicator, product)

    return images
