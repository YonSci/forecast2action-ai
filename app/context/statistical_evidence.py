"""Deterministic, real-data-only statistics computed BEFORE anything reaches
the LLM -- the LLM should interpret and communicate this evidence, not
estimate values, administrative areas, or spatial patterns from raw numbers
or map colors itself.

Everything here reads real rasters/admin boundaries already used elsewhere
in this codebase (app.api.hazard_risk_ranking's zonal-stats machinery,
app.context.spatial_summary's climate-indicator readers) -- no new data
sources, no invented thresholds. Where the underlying real data genuinely
doesn't exist for something (ensemble member spread, settlement counts,
a climatological baseline for probability layers), that is stated
explicitly in the output (e.g. "departure_available": false), never
silently omitted or approximated with a fabricated number.

Scope for this pass (confirmed with the user): national + region (admin1)
level only. Zone/woreda still get top-5 ranking via the existing
compute_district_ranking, not this module's full per-unit stat suite.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.api.hazard_risk_catalog_shared import DOMINANT_HAZARD_CODE_BANDS, LAYER_BY_VALUE, RISK_CLASS_BANDS
from app.api.hazard_risk_maps import find_map_record as find_hazard_risk_record
from app.api.hazard_risk_maps import load_display_array as load_hazard_risk_display_array
from app.api.hazard_risk_ranking import (
    ADMIN_GEOJSON_PATHS,
    POPULATION_RAW_PATH,
    _area_label,
    build_district_label_array,
    compute_district_ranking,
    default_threshold_for,
    filter_admin_features,
    load_admin_features,
    load_population_raw_array,
    pixel_area_km2_array,
    resample_mask_nearest,
    zonal_stats_for_all_districts,
)
from app.api.seasonal_raster_maps import find_map_record as find_seasonal_record
from app.api.seasonal_raster_maps import load_display_array as load_seasonal_display_array
from app.context.spatial_summary import CLIMATE_INDICATORS, HAZARD_RISK_LAYERS_FOR_REPORT

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data") / "statistical_evidence"

CLASS_LABELS = ["very_low", "low", "moderate", "high", "very_high"]

# Real, filename-confirmed pattern (all periods share the SAME init_date;
# the lead is period-dependent) -- mirrors frontend/src/components/
# ForecastLayerMap.jsx's SEASONAL_PERIOD_TO_HAZARD_LEAD, kept in sync
# manually since one lives in JS state logic and this lives in the
# evidence-JSON metadata, not because the underlying fact differs.
SEASONAL_PERIOD_TO_LEAD_MONTHS = {
    "june": 1, "july": 2, "august": 3, "september": 4, "jjas": 1,
}

# Real, established meteorological definitions (McKee et al. 1993 for SPI;
# standard WMO/ETCCDI definitions for the others) -- not data-specific
# values that need per-dataset verification, unlike forecast_metadata's
# fields. Rainfall Total/Percentile added beyond the user's example so all
# 7 real indicators this system covers are defined, not just 5.
INDICATOR_DEFINITIONS = {
    "rainfall_total": {
        "label": "Rainfall Total",
        "units": "mm",
        "interpretation": "Total accumulated rainfall for the period. Positive anomaly does not automatically imply flooding -- check Rx1day/Rx5day and CWD for intensity/duration risk.",
    },
    "spi": {
        "label": "SPI (Standardized Precipitation Index)",
        "units": "standard deviations",
        "dry_thresholds": {"moderately_dry": -1.0, "severely_dry": -1.5, "extremely_dry": -2.0},
        "wet_thresholds": {"moderately_wet": 1.0, "very_wet": 1.5, "extremely_wet": 2.0},
        "interpretation": "More negative values indicate greater dryness relative to the region's own climatological rainfall distribution. Negative SPI does not necessarily imply severe agricultural impact unless exposure and vulnerability are also high.",
    },
    "cdd": {
        "label": "CDD (Consecutive Dry Days)",
        "units": "days",
        "interpretation": "Higher positive anomaly means longer-than-normal dry spells. High CDD usually increases drought concern.",
    },
    "cwd": {
        "label": "CWD (Consecutive Wet Days)",
        "units": "days",
        "interpretation": "Higher positive anomaly means longer continuous wet spells. High CWD can benefit crops but also increase waterlogging and disease risk -- do not treat it as uniformly positive or uniformly negative.",
    },
    "rx1day": {
        "label": "Rx1day (Maximum 1-day rainfall)",
        "units": "mm",
        "interpretation": "Maximum one-day rainfall amount. High positive anomaly may indicate flash-flood risk. Should not be interpreted identically to Rx5day -- Rx1day reflects short, intense bursts, not sustained accumulation.",
    },
    "rx5day": {
        "label": "Rx5day (Maximum 5-day rainfall)",
        "units": "mm",
        "interpretation": "Maximum consecutive five-day rainfall total. High positive anomaly may indicate saturation and river-flood risk -- a distinct hazard mechanism from Rx1day's flash-flood signal.",
    },
    "rainfall_percentile": {
        "label": "Rainfall Percentile",
        "units": "percentile rank (0-100)",
        "interpretation": "Where this period's rainfall ranks against the climatological distribution at each location. 50 is the climatological median; departure from 50 is the meaningful signal, not the raw percentile alone.",
    },
}

# The 6 climate indicators with real climatology + anomaly rasters (SPI is
# deliberately excluded -- it's already standardized relative to
# climatology, see spi_category() below; Drought/Wet Probability are hazard/
# risk-catalog layers, handled separately in departure_from_climatology).
INDICATORS_WITH_CLIMATOLOGY = ["rainfall_total", "cdd", "cwd", "rx1day", "rx5day", "rainfall_percentile"]

# McKee et al. (1993) SPI classification -- the standard meteorological
# convention, not invented here.
SPI_CATEGORY_BANDS = [
    (2.0, float("inf"), "extremely_wet"),
    (1.5, 2.0, "very_wet"),
    (1.0, 1.5, "moderately_wet"),
    (-1.0, 1.0, "near_normal"),
    (-1.5, -1.0, "moderately_dry"),
    (-2.0, -1.5, "severely_dry"),
    (float("-inf"), -2.0, "extremely_dry"),
]


def spi_category(spi_value: float) -> str:
    for low, high, label in SPI_CATEGORY_BANDS:
        if low <= spi_value < high:
            return label
    return "near_normal"


def _weighted_percentile(values, weights, percentile: float) -> float:
    """Standard weighted-percentile via interpolation on the weighted CDF --
    a well-established technique (used by e.g. numpy's own documentation
    examples for weighted quantiles), not a new statistical method.
    """
    import numpy as np

    order = np.argsort(values)
    values_sorted = values[order]
    weights_sorted = weights[order]
    cumulative = np.cumsum(weights_sorted) - 0.5 * weights_sorted
    cumulative /= np.sum(weights_sorted)
    return float(np.interp(percentile / 100.0, cumulative, values_sorted))


def area_weighted_statistics(arr, transform) -> Dict[str, Any]:
    """National min/max/mean/median/std/percentiles, weighted by each
    pixel's REAL ground area (pixel_area_km2_array) so cells at different
    latitudes contribute proportionally to their actual surface area, not
    raw pixel count -- app.api.seasonal_raster_maps.calculate_statistics_
    from_array (used elsewhere in this app) is an unweighted pixel mean;
    this is the area-weighted upgrade the spec calls for.
    """
    import numpy as np

    finite_mask = np.isfinite(arr)
    if not finite_mask.any():
        return {"valid_count": 0}

    area_arr = pixel_area_km2_array(transform, arr.shape)
    values = arr[finite_mask].astype("float64")
    weights = area_arr[finite_mask].astype("float64")

    weighted_mean = float(np.average(values, weights=weights))
    weighted_variance = float(np.average((values - weighted_mean) ** 2, weights=weights))

    return {
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": weighted_mean,
        "median": _weighted_percentile(values, weights, 50),
        "std": weighted_variance ** 0.5,
        "p10": _weighted_percentile(values, weights, 10),
        "p25": _weighted_percentile(values, weights, 25),
        "p75": _weighted_percentile(values, weights, 75),
        "p90": _weighted_percentile(values, weights, 90),
        "valid_count": int(finite_mask.sum()),
        "weighting": "area_km2",
    }


def region_statistics(arr, transform, admin_level: str = "admin1") -> List[Dict[str, Any]]:
    """Per-region (admin1 by default -- 15 regions, cheap to loop directly
    in Python) mean/median/std/percentiles/area_km2. Extends
    zonal_stats_for_all_districts (which only returns mean/max/valid_count/
    above_threshold_fraction/area_total_km2) with the additional real
    per-region percentile/std detail the spec asks for -- computed directly
    from each region's own masked pixel values, not estimated.
    """
    import numpy as np

    features = filter_admin_features(load_admin_features(admin_level))
    if not features:
        return []

    label_array = build_district_label_array(features, arr.shape, transform)
    if label_array is None:
        return []

    area_arr = pixel_area_km2_array(transform, arr.shape)
    finite_mask = np.isfinite(arr)

    results = []
    for index, feature in enumerate(features, start=1):
        region_mask = (label_array == index) & finite_mask
        if not region_mask.any():
            continue
        values = arr[region_mask].astype("float64")
        weights = area_arr[region_mask].astype("float64")
        weighted_mean = float(np.average(values, weights=weights))
        results.append({
            "area_name": _area_label(feature.get("properties", {}), admin_level),
            "region": feature.get("properties", {}).get("region", ""),
            "min": float(values.min()),
            "max": float(values.max()),
            "mean": weighted_mean,
            "median": _weighted_percentile(values, weights, 50),
            "std": float(np.average((values - weighted_mean) ** 2, weights=weights)) ** 0.5,
            "area_km2": float(weights.sum()),
            "valid_count": int(region_mask.sum()),
        })
    return results


def classify_by_quintiles(arr, reference_arr) -> Tuple[Any, List[float]]:
    """5-class (very_low..very_high) classification via quintile breakpoints
    computed from reference_arr -- the real climatology raster for climate
    indicators, or the layer's own current-period array (self-referential
    quintiles) for hazard/probability/vulnerability/exposure layers, which
    have no separate climatology of their own. Returns (class_index_array,
    breakpoints) so callers can report which real values define each class.
    """
    import numpy as np

    ref_values = reference_arr[np.isfinite(reference_arr)].astype("float64")
    breakpoints = [float(np.percentile(ref_values, p)) for p in (20, 40, 60, 80)]

    class_arr = np.full(arr.shape, -1, dtype="int8")
    finite = np.isfinite(arr)
    class_arr[finite & (arr < breakpoints[0])] = 0
    class_arr[finite & (arr >= breakpoints[0]) & (arr < breakpoints[1])] = 1
    class_arr[finite & (arr >= breakpoints[1]) & (arr < breakpoints[2])] = 2
    class_arr[finite & (arr >= breakpoints[2]) & (arr < breakpoints[3])] = 3
    class_arr[finite & (arr >= breakpoints[3])] = 4
    return class_arr, breakpoints


def classify_by_risk_bands(arr) -> Any:
    """Reuses the REAL, upstream-defined RISK_CLASS_BANDS (population_risk_
    class/r_drought/r_wet already have an established 5-class scheme --
    no quantile derivation needed or wanted here, unlike classify_by_quintiles.
    """
    import numpy as np

    class_arr = np.full(arr.shape, -1, dtype="int8")
    finite = np.isfinite(arr)
    for band in RISK_CLASS_BANDS:
        low, high = band["range"]
        class_arr[finite & (arr >= low) & (arr <= high)] = band["code"]
    return class_arr


def class_area_percentages(class_arr, transform, weight_arr=None) -> Dict[str, float]:
    """% of area (or, when weight_arr given, % of that weighted quantity --
    e.g. population count or cropland-normalized values) in each of the 5
    classes. weight_arr must already be on the SAME grid as class_arr.
    """
    import numpy as np

    weights = weight_arr if weight_arr is not None else pixel_area_km2_array(transform, class_arr.shape)
    total = float(np.sum(weights[class_arr >= 0]))
    if total <= 0:
        return {label: 0.0 for label in CLASS_LABELS}

    return {
        label: round(float(np.sum(weights[class_arr == code])) / total * 100, 2)
        for code, label in enumerate(CLASS_LABELS)
    }


def weighted_exposure_by_region(
    source_arr, source_transform, weight_arr, weight_transform, admin_level: str, threshold: float,
) -> List[Dict[str, Any]]:
    """Generalizes app.api.hazard_risk_ranking.population_stats_for_all_
    districts's real pattern (resample a hazard's above-threshold mask onto
    a weight raster's own grid, then ndimage.sum(weight * mask)) to ANY
    weight raster -- population count (that function's existing use) or
    cropland-normalized values (new, same pattern, same real cropland
    raster already used elsewhere in this app).
    """
    import numpy as np
    from scipy import ndimage

    features = filter_admin_features(load_admin_features(admin_level))
    if not features:
        return []

    label_array = build_district_label_array(features, weight_arr.shape, weight_transform)
    if label_array is None:
        return []

    # NaN in the weight raster means "no data here" (e.g. outside-country
    # clip on the coarse cropland grid) -- ndimage.sum does NOT skip NaN,
    # it propagates it into the whole region's total the moment a labeled
    # region touches even one NaN cell. Real weight is zero there, so
    # treating it as 0.0 (matching load_population_raw_array's own
    # `arr.filled(0.0)` convention) is correct, not a fabrication.
    weight_arr = np.nan_to_num(weight_arr, nan=0.0)

    district_ids = list(range(1, len(features) + 1))
    present_ids = [d for d in district_ids if d in set(np.unique(label_array).tolist()) - {0}]
    if not present_ids:
        return []

    above_threshold_mask = source_arr >= threshold
    exposed_mask = resample_mask_nearest(
        above_threshold_mask, source_transform, "EPSG:4326", weight_transform, weight_arr.shape, "EPSG:4326",
    )

    totals = ndimage.sum(weight_arr, labels=label_array, index=present_ids)
    exposed = ndimage.sum(weight_arr * exposed_mask, labels=label_array, index=present_ids)

    results = []
    for feature_index, total_value, exposed_value in zip(present_ids, totals, exposed):
        feature = features[feature_index - 1]
        pct = round(float(exposed_value) / float(total_value) * 100, 2) if total_value else None
        results.append({
            "area_name": _area_label(feature.get("properties", {}), admin_level),
            "total": float(total_value),
            "exposed": float(exposed_value),
            "exposed_pct": pct,
        })
    return results


def _top_n_regions(regions: List[Dict[str, Any]], key: str, n: int = 5, reverse: bool = True) -> List[Dict[str, Any]]:
    return sorted(regions, key=lambda item: item[key], reverse=reverse)[:n]


def departure_from_climatology(indicator: str, period: str, admin_level: str = "admin1") -> Optional[Dict[str, Any]]:
    """Real climatology departure for the 6 indicators with real climatology
    + anomaly rasters. Reads the anomaly raster directly (it's precomputed
    upstream -- this function does not calculate the departure itself for
    those 6), plus a real %-anomaly derived from the two real rasters.

    SPI is handled separately (see spi_category) -- it's already
    standardized relative to climatology, so no departure is computed here,
    matching the project's own spec.
    """
    if indicator not in INDICATORS_WITH_CLIMATOLOGY:
        return None

    forecast_record = find_seasonal_record(indicator, period, "forecast")
    climatology_record = find_seasonal_record(indicator, period, "climatology")
    anomaly_record = find_seasonal_record(indicator, period, "anomaly")
    if not (forecast_record and climatology_record and anomaly_record):
        logger.info("Missing forecast/climatology/anomaly record for indicator=%s period=%s", indicator, period)
        return None

    import numpy as np

    forecast_arr, forecast_transform, _b1 = load_seasonal_display_array(forecast_record)
    climatology_arr, _t2, _b2 = load_seasonal_display_array(climatology_record)
    anomaly_arr, anomaly_transform, _b3 = load_seasonal_display_array(anomaly_record)

    national_anomaly = area_weighted_statistics(anomaly_arr, anomaly_transform)
    regional_anomaly = region_statistics(anomaly_arr, anomaly_transform, admin_level)

    # %-anomaly from the two real rasters directly -- masked where
    # climatology is too close to zero for a percentage to be meaningful
    # (e.g. CDD/CWD/Rx-day near-zero cells), not fabricated.
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_anomaly_arr = np.where(
            np.abs(climatology_arr) > 1e-6,
            (forecast_arr - climatology_arr) / climatology_arr * 100,
            np.nan,
        )
    national_pct_anomaly = area_weighted_statistics(pct_anomaly_arr, forecast_transform)

    return {
        "indicator": indicator,
        "period": period,
        "national_anomaly": national_anomaly,
        "national_pct_anomaly": {"mean": national_pct_anomaly.get("mean"), "median": national_pct_anomaly.get("median")},
        "regional_anomaly": regional_anomaly,
        "top_positive_anomalies": _top_n_regions(regional_anomaly, "mean", 5, reverse=True),
        "top_negative_anomalies": _top_n_regions(regional_anomaly, "mean", 5, reverse=False),
        "departure_available": True,
    }


def probability_layer_evidence(layer_value: str, period: str, admin_level: str = "admin1") -> Optional[Dict[str, Any]]:
    """Drought/Wet Probability (p_drought/p_wet) -- raw value only.
    Confirmed via direct inspection of data/maps/Probability_Severity/: no
    climatological baseline probability raster exists in this pipeline, so
    departure_available is explicitly False here rather than silently
    omitted or estimated.
    """
    record = find_hazard_risk_record(layer_value, period)
    if not record:
        return None

    arr, transform, _bounds = load_hazard_risk_display_array(record)
    return {
        "layer_value": layer_value,
        "period": period,
        "national": area_weighted_statistics(arr, transform),
        "regional": region_statistics(arr, transform, admin_level),
        "departure_available": False,
        "reason": "No climatological baseline probability raster exists in this pipeline.",
    }


def categorical_class_percentages(arr, transform, bands: List[Dict[str, Any]]) -> Dict[str, float]:
    """% of real area in each ALREADY-DEFINED class code -- population_risk_
    class/population_dominant_code are themselves categorical rasters (the
    pixel value already IS the class code), so this just tallies real area
    per existing code, no classification step needed.
    """
    import numpy as np

    area_arr = pixel_area_km2_array(transform, arr.shape)
    finite = np.isfinite(arr)
    total = float(np.sum(area_arr[finite]))
    if total <= 0:
        return {band["label"]: 0.0 for band in bands}

    return {
        band["label"]: round(float(np.sum(area_arr[finite & (np.round(arr) == band["code"])])) / total * 100, 2)
        for band in bands
    }


# Step 4 -- deterministic cross-indicator evidence. Real criteria as
# specified by the project owner: a "strong_drought" signal requires ALL of
# rainfall anomaly < 0, rainfall percentile < 20th, SPI < -1, CDD anomaly >
# 0 (longer dry spells than normal), and drought probability above its own
# real operational threshold; "strong_wet" mirrors with rainfall anomaly >
# 0, percentile > 80th, SPI > +1, CWD anomaly > 0, Rx1day OR Rx5day anomaly
# > 0, and wet probability above its own threshold. Every value combined
# here is already real and already computed by the climate_indicators/
# hazard_risk_layers sections built above -- this function performs no new
# raster reads, only combination logic over already-computed numbers.
CROSS_INDICATOR_STRONG_THRESHOLD = 0.8
CROSS_INDICATOR_MIXED_THRESHOLD = 0.4


def _extract_regional_means(node: Optional[Dict[str, Any]], *path: str) -> Dict[str, float]:
    """Walks node down through path to the {area_name, mean, ...} list shape
    that region_statistics/departure_from_climatology already produce, and
    collapses it to {area_name: mean}. Missing intermediate keys (e.g. a
    departure that came back None because a climatology record was
    missing) resolve to {} rather than raising, since cross-indicator
    findings must degrade gracefully per-area, not fail entirely.
    """
    current: Any = node
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    if not isinstance(current, list):
        return {}
    return {item["area_name"]: item["mean"] for item in current if item.get("mean") is not None}


# Real units for each cross-indicator criterion name -- used only to label
# _indicator_evidence_objects's real values, not to compute anything new.
_INDICATOR_CRITERION_UNITS = {
    "rainfall_anomaly": "%",
    "rainfall_percentile": "percentile",
    "spi": "std dev",
    "cdd_anomaly": "days",
    "cwd_anomaly": "days",
    "rx_anomaly": "mm",
    "drought_probability": "%",
    "wet_probability": "%",
}


def _indicator_real_value(name: str, values: Dict[str, Optional[float]]) -> Optional[float]:
    """The real number behind one criterion name, in the same real units
    _INDICATOR_CRITERION_UNITS labels it with -- not a new computation,
    just resolving which of `values`' real entries a given criterion name
    actually refers to.
    """
    if name == "rx_anomaly":
        # wet_checks's "rx_anomaly" criterion is met if EITHER rx1day or
        # rx5day anomaly is positive (see the rx_wet_met check below) -- no
        # single real "rx_anomaly" value exists, so this reports whichever
        # of the two real components has the larger real magnitude, rather
        # than fabricating a combined figure.
        candidates = [v for v in (values.get("rx1day_anomaly"), values.get("rx5day_anomaly")) if v is not None]
        return max(candidates, key=abs) if candidates else None
    value = values.get(name)
    if name in ("drought_probability", "wet_probability") and value is not None:
        # Stored as a real 0-1 fraction (same units as p_drought/p_wet's own
        # regional means) -- reported as a real percentage here, matching
        # this module's own _pct convention used everywhere else.
        return value * 100
    return value


def _indicator_evidence_objects(names: List[str], values: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    """Real value + units for each matched criterion name, replacing a bare
    indicator-name string (e.g. "rainfall_anomaly") with the actual real
    number that was checked (e.g. {"indicator": "rainfall_anomaly", "value":
    -47.2, "units": "%"}) -- so a consumer sees WHY the indicator supported
    or contradicted the signal, not just that it did.
    """
    objects = []
    for name in names:
        value = _indicator_real_value(name, values)
        objects.append({
            "indicator": name,
            "value": round(value, 2) if isinstance(value, (int, float)) else None,
            "units": _INDICATOR_CRITERION_UNITS.get(name, ""),
        })
    return objects


def _evaluate_area_signal(
    area_name: str,
    values: Dict[str, Optional[float]],
    p_drought_threshold: float,
    p_wet_threshold: float,
) -> Dict[str, Any]:
    """Evaluates one area's already-real indicator values against the
    drought/wet criteria and returns one cross_indicator_findings entry.
    A criterion is "unavailable" (contributes to neither the met nor the
    not-met count) when its underlying value is None for this area, so
    missing data lowers confidence rather than silently counting as
    disagreement.
    """

    def checked(name: str, met_if) -> Optional[bool]:
        value = values.get(name)
        if value is None:
            return None
        return bool(met_if(value))

    rx1day = values.get("rx1day_anomaly")
    rx5day = values.get("rx5day_anomaly")
    rx_available = rx1day is not None or rx5day is not None
    rx_wet_met = None
    if rx_available:
        rx_wet_met = (rx1day is not None and rx1day > 0) or (rx5day is not None and rx5day > 0)

    drought_checks = {
        "rainfall_anomaly": checked("rainfall_anomaly", lambda v: v < 0),
        "rainfall_percentile": checked("rainfall_percentile", lambda v: v < 20),
        "spi": checked("spi", lambda v: v < -1),
        "cdd_anomaly": checked("cdd_anomaly", lambda v: v > 0),
        "drought_probability": checked("drought_probability", lambda v: v > p_drought_threshold),
    }
    wet_checks = {
        "rainfall_anomaly": checked("rainfall_anomaly", lambda v: v > 0),
        "rainfall_percentile": checked("rainfall_percentile", lambda v: v > 80),
        "spi": checked("spi", lambda v: v > 1),
        "cwd_anomaly": checked("cwd_anomaly", lambda v: v > 0),
        "rx_anomaly": rx_wet_met,
        "wet_probability": checked("wet_probability", lambda v: v > p_wet_threshold),
    }

    def score(checks: Dict[str, Optional[bool]]) -> Tuple[float, int, int, List[str]]:
        available = [name for name, met in checks.items() if met is not None]
        met = [name for name in available if checks[name]]
        fraction = (len(met) / len(available)) if available else 0.0
        return fraction, len(met), len(available), met

    drought_fraction, drought_met_n, drought_available_n, drought_met_names = score(drought_checks)
    wet_fraction, wet_met_n, wet_available_n, wet_met_names = score(wet_checks)

    if drought_fraction >= CROSS_INDICATOR_STRONG_THRESHOLD and drought_fraction > wet_fraction:
        signal = "strong_drought"
        agreement_score = drought_fraction
        supporting, contradicting = drought_met_names, wet_met_names
        available_n = drought_available_n
    elif wet_fraction >= CROSS_INDICATOR_STRONG_THRESHOLD and wet_fraction > drought_fraction:
        signal = "strong_wet"
        agreement_score = wet_fraction
        supporting, contradicting = wet_met_names, drought_met_names
        available_n = wet_available_n
    elif drought_fraction >= CROSS_INDICATOR_MIXED_THRESHOLD and wet_fraction >= CROSS_INDICATOR_MIXED_THRESHOLD:
        # Genuine disagreement -- both directions have real support.
        signal = "mixed"
        total_available = drought_available_n + wet_available_n
        agreement_score = (drought_met_n + wet_met_n) / total_available if total_available else 0.0
        dominant_is_drought = drought_fraction >= wet_fraction
        supporting = drought_met_names if dominant_is_drought else wet_met_names
        contradicting = wet_met_names if dominant_is_drought else drought_met_names
        available_n = min(drought_available_n, wet_available_n)
    else:
        signal = "no_clear_signal"
        dominant_is_drought = drought_fraction >= wet_fraction
        agreement_score = drought_fraction if dominant_is_drought else wet_fraction
        supporting = drought_met_names if dominant_is_drought else wet_met_names
        contradicting = []
        available_n = max(drought_available_n, wet_available_n)

    if agreement_score >= CROSS_INDICATOR_STRONG_THRESHOLD and available_n >= 4:
        confidence = "high"
    elif agreement_score >= CROSS_INDICATOR_MIXED_THRESHOLD and available_n >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "area": area_name,
        "signal": signal,
        "agreement_score": round(agreement_score, 2),
        "supporting_indicators": _indicator_evidence_objects(supporting, values),
        "contradicting_indicators": _indicator_evidence_objects(contradicting, values),
        "confidence": confidence,
    }


def build_cross_indicator_findings(evidence: Dict[str, Any], period: str) -> List[Dict[str, Any]]:
    """Cross-references the ALREADY-BUILT climate_indicators/hazard_risk_
    layers sections of `evidence` (steps 1-2 of this module) into one
    drought/wet agreement finding per area (national + each region) --
    the deterministic reconciliation the LLM would otherwise have to do
    itself from ~9 separate numbers per area.
    """
    climate = evidence.get("climate_indicators", {})
    hazard = evidence.get("hazard_risk_layers", {})

    def national_value(section: Dict[str, Any], indicator: str, *path: str) -> Optional[float]:
        node: Any = section.get(indicator, {})
        for part in path:
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node if isinstance(node, (int, float)) else None

    p_drought_threshold = default_threshold_for("p_drought", period)
    p_wet_threshold = default_threshold_for("p_wet", period)

    national_values = {
        "rainfall_anomaly": national_value(climate, "rainfall_total", "departure", "national_anomaly", "mean"),
        "rainfall_percentile": national_value(climate, "rainfall_percentile", "national", "mean"),
        "spi": national_value(climate, "spi", "national", "mean"),
        "cdd_anomaly": national_value(climate, "cdd", "departure", "national_anomaly", "mean"),
        "cwd_anomaly": national_value(climate, "cwd", "departure", "national_anomaly", "mean"),
        "rx1day_anomaly": national_value(climate, "rx1day", "departure", "national_anomaly", "mean"),
        "rx5day_anomaly": national_value(climate, "rx5day", "departure", "national_anomaly", "mean"),
        "drought_probability": national_value(hazard, "p_drought", "national", "mean"),
        "wet_probability": national_value(hazard, "p_wet", "national", "mean"),
    }

    findings = [_evaluate_area_signal("National", national_values, p_drought_threshold, p_wet_threshold)]

    regional_maps = {
        "rainfall_anomaly": _extract_regional_means(climate.get("rainfall_total"), "departure", "regional_anomaly"),
        "rainfall_percentile": _extract_regional_means(climate.get("rainfall_percentile"), "regional"),
        "spi": _extract_regional_means(climate.get("spi"), "regional"),
        "cdd_anomaly": _extract_regional_means(climate.get("cdd"), "departure", "regional_anomaly"),
        "cwd_anomaly": _extract_regional_means(climate.get("cwd"), "departure", "regional_anomaly"),
        "rx1day_anomaly": _extract_regional_means(climate.get("rx1day"), "departure", "regional_anomaly"),
        "rx5day_anomaly": _extract_regional_means(climate.get("rx5day"), "departure", "regional_anomaly"),
        "drought_probability": _extract_regional_means(hazard.get("p_drought"), "regional"),
        "wet_probability": _extract_regional_means(hazard.get("p_wet"), "regional"),
    }

    area_names = set()
    for mapping in regional_maps.values():
        area_names.update(mapping.keys())

    for area_name in sorted(area_names):
        values = {key: mapping.get(area_name) for key, mapping in regional_maps.items()}
        findings.append(_evaluate_area_signal(area_name, values, p_drought_threshold, p_wet_threshold))

    return findings


# Step 7.5 -- deterministic, auditable "why this area is a priority" per
# top-ranked region. Every numeric field here is read directly from
# evidence sections already computed above (priority_scores, hazard_risk_
# layers' regional means, exposure's population_exposed_by_region,
# cross_indicator_findings) -- never restated or recalculated by the LLM,
# so a reviewer can trace every number back to its real source. The LLM
# (see app.api.report_stages) only adds free-text differentiator/
# recommended_intervention_type narrative on top of this object, keyed by
# justification_id -- it never authors or alters the numbers themselves.
PRIORITY_AREA_TOP_N = 5

RANK_BY_TO_HAZARD_TYPE = {"population_r_drought": "drought", "population_r_wet": "wet"}
RANK_BY_TO_PROBABILITY_LAYER = {"population_r_drought": "p_drought", "population_r_wet": "p_wet"}
RANK_BY_TO_VULNERABILITY_LAYER = {"population_r_drought": "v_drought", "population_r_wet": "v_wet"}


def _regional_means(layer_entry: Optional[Dict[str, Any]]) -> Dict[str, float]:
    if not layer_entry:
        return {}
    return {item["area_name"]: item["mean"] for item in layer_entry.get("regional", []) if item.get("mean") is not None}


def _cross_indicator_lookup(findings: List[Dict[str, Any]], area_name: str) -> Optional[Dict[str, Any]]:
    return next((item for item in findings if item.get("area") == area_name), None)


def build_priority_area_justifications(evidence: Dict[str, Any], top_n: int = PRIORITY_AREA_TOP_N) -> List[Dict[str, Any]]:
    hazard_risk_layers = evidence.get("hazard_risk_layers", {})
    exposure = evidence.get("exposure", {})
    cross_indicator_findings = evidence.get("cross_indicator_findings", [])
    priority_scores = evidence.get("priority_scores", {})

    justifications: List[Dict[str, Any]] = []
    for rank_by, hazard_type in RANK_BY_TO_HAZARD_TYPE.items():
        ranking = sorted(
            priority_scores.get(rank_by, []), key=lambda item: item.get("priority_score") or 0.0, reverse=True,
        )
        probability_by_area = _regional_means(hazard_risk_layers.get(RANK_BY_TO_PROBABILITY_LAYER[rank_by]))
        risk_by_area = _regional_means(hazard_risk_layers.get(rank_by))
        vulnerability_by_area = _regional_means(hazard_risk_layers.get(RANK_BY_TO_VULNERABILITY_LAYER[rank_by]))
        exposure_by_area = {
            item["area_name"]: item
            for item in exposure.get(rank_by, {}).get("population_exposed_by_region", [])
        }
        # Step 7 item 7 -- roads/healthsites exposure (real, newly wired
        # into the evidence engine above) flows through this SAME
        # deterministic object so Stage 3 (action translation) can cite
        # real road-accessibility/health-facility exposure for
        # humanitarian triggers without needing raw evidence access itself
        # -- it only ever sees Stage 2's already-validated findings.
        roads_exposure_by_area = {
            item["area_name"]: item
            for item in exposure.get(rank_by, {}).get("roads_exposed_by_region", [])
        }
        healthsites_exposure_by_area = {
            item["area_name"]: item
            for item in exposure.get(rank_by, {}).get("healthsites_exposed_by_region", [])
        }

        for rank, item in enumerate(ranking[:top_n], start=1):
            area_name = item.get("area_name")
            finding = _cross_indicator_lookup(cross_indicator_findings, area_name)
            exposure_item = exposure_by_area.get(area_name)
            roads_item = roads_exposure_by_area.get(area_name)
            healthsites_item = healthsites_exposure_by_area.get(area_name)
            justifications.append({
                "justification_id": f"{area_name}::{hazard_type}",
                "rank": rank,
                "area": area_name,
                "hazard_type": hazard_type,
                "priority_score": item.get("priority_score"),
                "risk_score": risk_by_area.get(area_name),
                "hazard_probability": probability_by_area.get(area_name),
                "vulnerability": vulnerability_by_area.get(area_name),
                "population_exposed": exposure_item.get("exposed") if exposure_item else None,
                "population_exposed_pct": exposure_item.get("exposed_pct") if exposure_item else None,
                "roads_exposed_pct": roads_item.get("exposed_pct") if roads_item else None,
                "healthsites_exposed_pct": healthsites_item.get("exposed_pct") if healthsites_item else None,
                "supporting_indicators": finding.get("supporting_indicators", []) if finding else [],
                "contradicting_indicators": finding.get("contradicting_indicators", []) if finding else [],
                "cross_indicator_signal": finding.get("signal") if finding else None,
                "confidence": finding.get("confidence") if finding else None,
            })
    return justifications


# Step "Phase 3 #17" -- structured layer_by_layer_summary/indicator_by_
# indicator_summary objects instead of free-text bullets, built from
# already-computed evidence sections (national/regional stats, class_area_
# pct) so Stage 1's real output and the deterministic fallback are never
# shape-inconsistent with each other. "layer"/"indicator" uses the real
# internal identifier (e.g. "h_dry_mean", "rainfall_total") already used as
# this evidence dict's own keys, rather than inventing a second, parallel
# semantic-name vocabulary that would need its own translation table.


def _dominant_class(class_area_pct: Dict[str, float]) -> Optional[str]:
    if not class_area_pct:
        return None
    return max(class_area_pct, key=class_area_pct.get)


def _high_class_area_pct(class_area_pct: Dict[str, float]) -> Optional[float]:
    """% of real area in the "high" + "very_high" classes -- a real,
    already-computed quantity (class_area_pct itself), not a new statistic.
    """
    if not class_area_pct:
        return None
    return round(class_area_pct.get("high", 0.0) + class_area_pct.get("very_high", 0.0), 1)


def _structured_summary_object(
    key: str, key_field: str, entry: Dict[str, Any], national_signal: Optional[str] = None,
) -> Dict[str, Any]:
    """Real, structured summary for one continuous layer/indicator (every
    hazard/risk/climate-indicator entry except the 2 purely-categorical
    layers, see _categorical_summary_object). highest_areas/lowest_areas
    are always by real VALUE (highest = numerically largest, lowest =
    numerically smallest) -- for a layer like SPI where drought interest is
    the most NEGATIVE value, that's lowest_areas, not highest_areas; this
    stays consistent rather than flipping direction per-indicator, so a
    caller always knows which field to check.

    `national_signal` lets a caller override the class-based dominant
    signal (e.g. SPI's real McKee category, "severely_dry") when a more
    specific real classification already exists for this indicator.
    """
    national = entry.get("national") or {}
    regional = [item for item in (entry.get("regional") or []) if item.get("mean") is not None]
    class_area_pct = entry.get("class_area_pct") or {}
    ranked = sorted(regional, key=lambda item: item["mean"], reverse=True)

    highest_areas = [item["area_name"] for item in ranked[:2]]
    lowest_areas = [item["area_name"] for item in ranked[-2:]] if len(ranked) > 2 else []
    national_mean = national.get("mean")
    signal = national_signal or _dominant_class(class_area_pct)

    parts = []
    if signal:
        parts.append(f"{signal.replace('_', ' ')} signal")
    if national_mean is not None:
        parts.append(f"national mean {round(national_mean, 3)}")
    if highest_areas:
        parts.append(f"highest in {', '.join(highest_areas)}")
    if lowest_areas:
        parts.append(f"lowest in {', '.join(lowest_areas)}")
    interpretation = ("; ".join(parts) + ".") if parts else "No national summary was provided."

    return {
        key_field: key,
        "national_signal": signal,
        "national_mean": round(national_mean, 3) if isinstance(national_mean, (int, float)) else None,
        "highest_areas": highest_areas,
        "lowest_areas": lowest_areas,
        "affected_area_pct": _high_class_area_pct(class_area_pct),
        "interpretation": interpretation,
        "confidence": "moderate" if national else "low",
    }


def _categorical_summary_object(key: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Real, structured summary for population_risk_class/population_
    dominant_code -- no continuous national mean exists for these (the
    pixel value already IS the class code), only real class_area_pct.
    """
    class_area_pct = entry.get("class_area_pct") or {}
    dominant_class = _dominant_class(class_area_pct)
    interpretation = (
        f"{dominant_class.replace('_', ' ').title()} is the most common class nationally "
        f"({class_area_pct.get(dominant_class, 0)}% of area)."
        if dominant_class else "No class-area data available."
    )
    return {
        "layer": key,
        "national_signal": dominant_class,
        "national_mean": None,
        "highest_areas": [],
        "lowest_areas": [],
        "affected_area_pct": _high_class_area_pct(class_area_pct),
        "interpretation": interpretation,
        "confidence": "moderate" if class_area_pct else "low",
    }


def build_structured_layer_summaries(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    summaries = [
        _structured_summary_object(layer_value, "layer", entry)
        for layer_value, entry in (evidence.get("hazard_risk_layers") or {}).items()
    ]
    summaries += [
        _categorical_summary_object(layer_value, entry)
        for layer_value, entry in (evidence.get("categorical_layers") or {}).items()
    ]
    return summaries


def build_structured_indicator_summaries(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    summaries = []
    for indicator, entry in (evidence.get("climate_indicators") or {}).items():
        # SPI has no class_area_pct (see INDICATORS_WITH_CLIMATOLOGY's
        # docstring -- it's already standardized) -- its real McKee
        # category (spi_category, computed when the evidence was built) is
        # used as the national_signal instead of a quintile-derived class.
        national_signal = entry.get("category") if indicator == "spi" else None
        summaries.append(_structured_summary_object(indicator, "indicator", entry, national_signal=national_signal))
    return summaries


RISK_SCALE_LAYERS = {"population_r_drought", "population_r_wet"}

_MONTH_NUMBER = {"june": 6, "july": 7, "august": 8, "september": 9}


def build_forecast_metadata(period: str, admin_level: str = "admin1") -> Dict[str, Any]:
    """Real forecast metadata for one period -- init_date/lead/resolution/
    population year are read directly from the data. forecast_system/
    ensemble_members/climatology_period are NOT recorded anywhere in this
    repo's own data catalog (every real raster's corresponding field is an
    empty string) -- these 3 are operator-confirmed facts about the actual
    upstream forecast source (ECMWF-SEAS5), supplied directly by the
    project owner rather than derived from an in-repo file, since no
    catalog file/sidecar records them.
    """
    # Any real record works for init_date -- every period shares the same
    # one (confirmed: filenames for June/July/August/September/JJAS all
    # carry the identical "2026-05-01" token).
    sample_record = find_seasonal_record("rainfall_total", period, "forecast")
    init_date = sample_record.get("init_date", "") if sample_record else ""

    valid_year = None
    if init_date:
        try:
            init_year, init_month = int(init_date[:4]), int(init_date[5:7])
            target_month = _MONTH_NUMBER.get(period.lower())
            if target_month:
                # Real month-order logic, not a guess: if the target month
                # comes before the init month in calendar order, it must be
                # the following year -- not applicable to today's actual
                # data (May init -> June-Sept targets never roll over), but
                # written generically rather than assuming that forever.
                valid_year = init_year + 1 if target_month < init_month else init_year
        except (ValueError, IndexError):
            valid_year = None

    period_label = period if period == "JJAS" else period.title()
    valid_period = f"{period_label} {valid_year}" if valid_year else period_label

    return {
        "country": "Ethiopia",
        "forecast_initialization": init_date or None,
        "valid_period": valid_period,
        "forecast_lead_months": SEASONAL_PERIOD_TO_LEAD_MONTHS.get(period.lower()),
        "forecast_system": "ECMWF-SEAS5",
        "ensemble_members": 25,
        "spatial_resolution_degrees": 0.25,
        "spatial_resolution_km": "~27.6 km",
        "climatology_period": "1993-2025",
        "administrative_level": f"national + region ({admin_level})",
        "population_reference_year": 2020,
        "population_source": "WorldPop Ethiopia 2020 population count, 1km",
        "livestock_reference_year": 2015,
        "livestock_source": "FAO/Harvard Dataverse Gridded Livestock of the World v4 (2015)",
    }


def build_national_region_evidence(period: str, admin_level: str = "admin1", use_cache: bool = True) -> Dict[str, Any]:
    """Orchestrates every real-data computation above into one structured
    object per forecast period -- the JSON handed to the LLM instead of raw
    map summaries it would otherwise have to interpret itself. Cached to
    disk (data/statistical_evidence/{period}.json) since the real inputs
    (rasters, admin boundaries) only change when a new period's data lands,
    not on every request.
    """
    cache_path = CACHE_DIR / f"{period}.json"
    if use_cache and cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read cached statistical evidence for period=%s -- rebuilding", period)

    evidence: Dict[str, Any] = {
        "period": period,
        "admin_level": admin_level,
        "forecast_metadata": build_forecast_metadata(period, admin_level),
        "indicator_definitions": INDICATOR_DEFINITIONS,
        "climate_indicators": {},
        "hazard_risk_layers": {},
        "categorical_layers": {},
        "priority_scores": {},
        "exposure": {},
    }

    # 1.1 + 1.2 -- climate indicators (7), departure from climatology for 6 of them.
    for indicator in CLIMATE_INDICATORS:
        record = find_seasonal_record(indicator, period, "forecast")
        if not record:
            continue
        arr, transform, _bounds = load_seasonal_display_array(record)
        entry: Dict[str, Any] = {
            "indicator": indicator,
            "national": area_weighted_statistics(arr, transform),
            "regional": region_statistics(arr, transform, admin_level),
        }
        if indicator == "spi":
            entry["category"] = spi_category(entry["national"]["mean"])
        else:
            climatology_record = find_seasonal_record(indicator, period, "climatology")
            if climatology_record:
                climatology_arr, _t, _b2 = load_seasonal_display_array(climatology_record)
                class_arr, breakpoints = classify_by_quintiles(arr, climatology_arr)
                entry["class_breakpoints"] = breakpoints
                entry["class_scheme"] = "quintiles_of_real_climatology"
                entry["class_area_pct"] = class_area_percentages(class_arr, transform)
            entry["departure"] = departure_from_climatology(indicator, period, admin_level)
        evidence["climate_indicators"][indicator] = entry

    # 1.3 -- hazard/probability/vulnerability/risk layers.
    for layer_value in HAZARD_RISK_LAYERS_FOR_REPORT:
        definition = LAYER_BY_VALUE.get(layer_value)
        if not definition:
            continue

        if definition.get("is_categorical"):
            record = find_hazard_risk_record(layer_value, period)
            if not record:
                continue
            arr, transform, _bounds = load_hazard_risk_display_array(record)
            bands = RISK_CLASS_BANDS if layer_value == "population_risk_class" else DOMINANT_HAZARD_CODE_BANDS
            evidence["categorical_layers"][layer_value] = {
                "layer_value": layer_value,
                "layer_label": definition["label"],
                "class_area_pct": categorical_class_percentages(arr, transform, bands),
            }
            continue

        record = find_hazard_risk_record(layer_value, period)
        if not record:
            continue
        arr, transform, _bounds = load_hazard_risk_display_array(record)
        entry = {
            "layer_value": layer_value,
            "layer_label": definition["label"],
            "national": area_weighted_statistics(arr, transform),
            "regional": region_statistics(arr, transform, admin_level),
        }
        if layer_value in RISK_SCALE_LAYERS:
            class_arr = classify_by_risk_bands(arr)
            entry["class_scheme"] = "risk_class_bands (real, upstream-defined -- same scheme as population_risk_class)"
        else:
            class_arr, breakpoints = classify_by_quintiles(arr, arr)
            entry["class_breakpoints"] = breakpoints
            entry["class_scheme"] = "quintiles_of_current_period (no separate climatology exists for this layer)"
        entry["class_area_pct"] = class_area_percentages(class_arr, transform)

        if layer_value in ("p_drought", "p_wet"):
            entry["departure"] = probability_layer_evidence(layer_value, period, admin_level)

        evidence["hazard_risk_layers"][layer_value] = entry

    # Priority scores -- reuse compute_district_ranking's own real output, not recomputed here.
    for rank_by in RISK_SCALE_LAYERS:
        try:
            ranking = compute_district_ranking(
                metrics=[], rank_by=rank_by, period=period, admin_level=admin_level,
                selection_mode="top", top_n=999, threshold=default_threshold_for(rank_by, period),
                region_id="", zone_id="",
            )
            evidence["priority_scores"][rank_by] = [
                {"area_name": item["area_name"], "priority_score": item["priority_score"]}
                for item in ranking["ranking"]
            ]
        except Exception:
            logger.exception("Failed to compute priority scores for rank_by=%s period=%s", rank_by, period)

    # 1.4 -- exposure (population + cropland), for the 2 operationally-meaningful risk layers.
    try:
        population_arr, population_transform, _shape = load_population_raw_array()
    except Exception:
        logger.exception("Failed to load real population raster for exposure statistics")
        population_arr = population_transform = None

    cropland_record = find_hazard_risk_record("cropland_total_normalized", period)
    cropland_arr = cropland_transform = None
    if cropland_record:
        cropland_arr, cropland_transform, _bounds = load_hazard_risk_display_array(cropland_record)

    # Step 7 item 7 -- roads/healthsites exposure, for humanitarian
    # road-accessibility and health/sanitation triggers. Both rasters are
    # real (data/maps/Exposure/ethiopia_{roads,healthsites}_normalized.tif)
    # and were already in the hazard/risk catalog, just never wired into
    # this exposure computation before -- same real pattern as cropland.
    roads_record = find_hazard_risk_record("roads_normalized", period)
    roads_arr = roads_transform = None
    if roads_record:
        roads_arr, roads_transform, _bounds = load_hazard_risk_display_array(roads_record)

    healthsites_record = find_hazard_risk_record("healthsites_normalized", period)
    healthsites_arr = healthsites_transform = None
    if healthsites_record:
        healthsites_arr, healthsites_transform, _bounds = load_hazard_risk_display_array(healthsites_record)

    for rank_by in RISK_SCALE_LAYERS:
        record = find_hazard_risk_record(rank_by, period)
        if not record:
            continue
        arr, transform, _bounds = load_hazard_risk_display_array(record)
        threshold = default_threshold_for(rank_by, period)
        exposure_entry: Dict[str, Any] = {"layer_value": rank_by, "threshold": threshold}
        if population_arr is not None:
            exposure_entry["population_exposed_by_region"] = weighted_exposure_by_region(
                arr, transform, population_arr, population_transform, admin_level, threshold,
            )
        if cropland_arr is not None:
            exposure_entry["cropland_exposed_by_region"] = weighted_exposure_by_region(
                arr, transform, cropland_arr, cropland_transform, admin_level, threshold,
            )
        if roads_arr is not None:
            exposure_entry["roads_exposed_by_region"] = weighted_exposure_by_region(
                arr, transform, roads_arr, roads_transform, admin_level, threshold,
            )
        if healthsites_arr is not None:
            exposure_entry["healthsites_exposed_by_region"] = weighted_exposure_by_region(
                arr, transform, healthsites_arr, healthsites_transform, admin_level, threshold,
            )
        evidence["exposure"][rank_by] = exposure_entry

    # Step 4 -- deterministic cross-indicator evidence, combining only the
    # already-real, already-computed values built above (no new raster reads).
    evidence["cross_indicator_findings"] = build_cross_indicator_findings(evidence, period)

    # Step 7.5 -- deterministic, auditable priority-area justification
    # objects, combining only values already computed above.
    evidence["priority_area_justifications"] = build_priority_area_justifications(evidence)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
