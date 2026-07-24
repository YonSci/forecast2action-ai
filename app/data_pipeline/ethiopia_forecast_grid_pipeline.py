from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.ml.risk_scoring import calculate_risk_score, classify_risk


OUTPUT_PATH = Path("data/sample/ethiopia_forecast_grid_layers.geojson")

# Precomputed real-data grids, built by exposure_data_pipeline.py and
# vulnerability_data_pipeline.py respectively (both import GRID_RESOLUTION/
# LAT_*/LON_* from this module so their cell keys line up exactly with the
# cells iterated below). Defined here rather than in those modules to avoid
# a circular import (they already depend on this module for the shared grid
# definition).
EXPOSURE_GRID_PATH = Path("data/processed/ethiopia_exposure_grid.json")
VULNERABILITY_GRID_PATH = Path("data/processed/ethiopia_vulnerability_grid.json")

LAT_MIN = 3.0
LAT_MAX = 15.0
LON_MIN = 33.0
LON_MAX = 48.0
GRID_RESOLUTION = 0.5


FORECAST_LEADS = [
    {"value": "week_1", "label": "Week 1", "forecast_scale": "subseasonal", "index": 1},
    {"value": "week_2", "label": "Week 2", "forecast_scale": "subseasonal", "index": 2},
    {"value": "week_3", "label": "Week 3", "forecast_scale": "subseasonal", "index": 3},
    {"value": "week_4", "label": "Week 4", "forecast_scale": "subseasonal", "index": 4},
    {"value": "week_1_2", "label": "Week 1-2", "forecast_scale": "subseasonal", "index": 5},
    {"value": "week_2_3", "label": "Week 2-3", "forecast_scale": "subseasonal", "index": 6},
    {"value": "week_3_4", "label": "Week 3-4", "forecast_scale": "subseasonal", "index": 7},
    {"value": "month_1", "label": "Month 1", "forecast_scale": "seasonal", "index": 8},
    {"value": "month_2", "label": "Month 2", "forecast_scale": "seasonal", "index": 9},
    {"value": "month_3", "label": "Month 3", "forecast_scale": "seasonal", "index": 10},
    {"value": "month_4", "label": "Month 4", "forecast_scale": "seasonal", "index": 11},
    {"value": "month_5", "label": "Month 5", "forecast_scale": "seasonal", "index": 12},
    {"value": "month_6", "label": "Month 6", "forecast_scale": "seasonal", "index": 13},
]


def ensure_output_directory() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def frange(start: float, stop: float, step: float) -> List[float]:
    values = []
    value = start

    while value < stop:
        values.append(round(value, 6))
        value += step

    return values


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min(value, max_value), min_value)


def _synthetic_exposure_fallback(lat_center: float, lon_center: float) -> float:
    """Original placeholder formula. Only used if EXPOSURE_GRID_PATH is missing
    (e.g. exposure_data_pipeline.py hasn't been run yet in this environment)."""

    east_component = (lon_center - LON_MIN) / (LON_MAX - LON_MIN)
    lowland_component = 1.0 - ((lat_center - LAT_MIN) / (LAT_MAX - LAT_MIN))
    wave_component = 0.12 * math.sin((lat_center + lon_center) * 0.8)

    exposure = 0.35 + 0.30 * east_component + 0.25 * lowland_component + wave_component

    return round(clamp(exposure, 0.05, 0.95), 3)


def _synthetic_vulnerability_fallback(lat_center: float, lon_center: float) -> float:
    """Original placeholder formula. Only used if VULNERABILITY_GRID_PATH is
    missing (e.g. vulnerability_data_pipeline.py hasn't been run yet)."""

    south_component = 1.0 - ((lat_center - LAT_MIN) / (LAT_MAX - LAT_MIN))
    east_component = (lon_center - LON_MIN) / (LON_MAX - LON_MIN)
    wave_component = 0.10 * math.cos((lat_center * 1.3) - (lon_center * 0.7))

    vulnerability = 0.40 + 0.25 * south_component + 0.25 * east_component + wave_component

    return round(clamp(vulnerability, 0.05, 0.95), 3)


@lru_cache(maxsize=None)
def load_precomputed_grid(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("cells", {})
    except Exception:
        return None


def calculate_exposure(lat_center: float, lon_center: float) -> float:
    """
    Real exposure value for this grid cell, from exposure_data_pipeline.py's
    WorldPop population + FAO GLW livestock composite (data/processed/
    ethiopia_exposure_grid.json). Falls back to the original synthetic
    lat/lon placeholder only if that file hasn't been generated yet.
    """

    cells = load_precomputed_grid(EXPOSURE_GRID_PATH)
    if cells is None:
        return _synthetic_exposure_fallback(lat_center, lon_center)

    cell = cells.get(f"{lat_center}_{lon_center}")
    if cell is None:
        return _synthetic_exposure_fallback(lat_center, lon_center)

    return cell["exposure"]


def calculate_vulnerability(lat_center: float, lon_center: float) -> float:
    """
    Real vulnerability value for this grid cell, from
    vulnerability_data_pipeline.py's IPC/FEWS NET food-insecurity composite
    (data/processed/ethiopia_vulnerability_grid.json). Falls back to the
    original synthetic lat/lon placeholder only if that file hasn't been
    generated yet.
    """

    cells = load_precomputed_grid(VULNERABILITY_GRID_PATH)
    if cells is None:
        return _synthetic_vulnerability_fallback(lat_center, lon_center)

    cell = cells.get(f"{lat_center}_{lon_center}")
    if cell is None:
        return _synthetic_vulnerability_fallback(lat_center, lon_center)

    return cell["vulnerability"]


# Maps each seasonal hazard lead onto the real forecast raster catalog's
# period token (app/api/seasonal_catalog_shared.py: "June".."September"/"JJAS").
# Subseasonal leads need no such table -- their lead values ("week_1".."week_3_4")
# already match catalog period tokens 1:1. There is no real raster beyond
# September (the catalog only carries June-September + the JJAS aggregate), so
# month_5/month_6 fall back to the nearest available period, September --
# same "fall back to nearest" rule the frontend already applies for
# unmapped seasonal-period combinations.
LEAD_TO_SEASONAL_CATALOG_PERIOD = {
    "month_1": "June",
    "month_2": "July",
    "month_3": "August",
    "month_4": "September",
    "month_5": "September",
    "month_6": "September",
}


def resolve_catalog_period(lead: Dict) -> str:
    if lead["forecast_scale"] == "subseasonal":
        return lead["value"]
    return LEAD_TO_SEASONAL_CATALOG_PERIOD.get(lead["value"], "September")


def load_raster_layer(indicator: str, period: str, product: str):
    """Load one real forecast raster's clipped array + transform, or None if unavailable.

    Reuses app/api/seasonal_raster_maps.py's existing catalog lookup, NetCDF/CSV
    -> GeoTIFF conversion, and Ethiopia border clipping (load_display_array) --
    the same pipeline the interactive seasonal climate maps already rely on --
    instead of re-implementing raster loading here.
    """

    from app.api.seasonal_raster_maps import find_map_record, load_display_array

    record = find_map_record(indicator, period, product)
    if not record:
        return None

    try:
        arr, transform, _bounds = load_display_array(record)
        return arr, transform
    except Exception:
        return None


def build_lead_raster_context(lead: Dict) -> Dict:
    """Load every real raster this lead's hazard calculation needs, once.

    Loaded once per lead and reused across every grid cell for that lead
    (~900 cells) instead of re-opening/re-converting the same raster file
    per cell.
    """

    period = resolve_catalog_period(lead)

    return {
        "spi": load_raster_layer("spi", period, "forecast"),
        "rainfall_total": load_raster_layer("rainfall_total", period, "forecast"),
        "rainfall_percentile": load_raster_layer("rainfall_percentile", period, "forecast"),
        "cdd": load_raster_layer("cdd", period, "forecast"),
        "cwd": load_raster_layer("cwd", period, "forecast"),
        # Real ensemble-derived probabilities. drought_probability/wet_probability
        # (P(SPI<=-1)/P(SPI>=1)) only exist for seasonal periods in the current
        # catalog; dryspell_prob_7d exists for both scales and is used as the
        # real-data probability for dry_spell hazard, and as a drought-probability
        # stand-in at subseasonal lead where no SPI-probability raster exists.
        "drought_probability": load_raster_layer("spi", period, "drought_probability"),
        "wet_probability": load_raster_layer("spi", period, "wet_probability"),
        "dryspell_prob_7d": load_raster_layer("dryspell_prob_7d", period, "forecast"),
    }


def sample_layer(layer, lat: float, lon: float) -> Optional[float]:
    if layer is None:
        return None

    from rasterio.transform import rowcol

    arr, transform = layer
    row, col = rowcol(transform, lon, lat)

    if row < 0 or col < 0 or row >= arr.shape[0] or col >= arr.shape[1]:
        return None

    value = arr[row, col]
    if not math.isfinite(value):
        return None

    return float(value)


def calculate_forecast_indicators(
    lat_center: float,
    lon_center: float,
    context: Dict,
) -> Dict:
    """
    Real gridded forecast indicators, sampled from the same forecast rasters
    (data/maps/geotiff|netcdf|csv, served by app/api/seasonal_raster_maps.py)
    the interactive seasonal climate maps already display.

    A cell/period without a valid raster reading (e.g. right at the coarse
    source grid's masked border, or if a raster is entirely missing) falls
    back to a neutral "no signal" reading so the pipeline always produces a
    complete grid instead of a hole.
    """

    spi = sample_layer(context.get("spi"), lat_center, lon_center)
    rainfall_total = sample_layer(context.get("rainfall_total"), lat_center, lon_center)
    rainfall_percentile = sample_layer(context.get("rainfall_percentile"), lat_center, lon_center)
    cdd = sample_layer(context.get("cdd"), lat_center, lon_center)
    cwd = sample_layer(context.get("cwd"), lat_center, lon_center)

    spi = spi if spi is not None else 0.0
    rainfall_total = rainfall_total if rainfall_total is not None else 0.0
    rainfall_percentile = rainfall_percentile if rainfall_percentile is not None else 50.0
    cdd = cdd if cdd is not None else 5.0
    cwd = cwd if cwd is not None else 3.0

    return {
        "spi": round(spi, 2),
        # Legacy field, kept for API compatibility with the (currently unused)
        # "indicator" dropdown -- approximated from SPI rather than sampled
        # from a dedicated raster, since real %-anomaly rasters only exist
        # for seasonal (not subseasonal) periods. Not used in hazard
        # classification below; SPI is used directly there instead.
        "rainfall_anomaly_pct": round(clamp(spi * 25.0, -70, 70), 1),
        "rainfall_total": round(rainfall_total, 1),
        "rainfall_percentile": round(rainfall_percentile, 1),
        "cdd": int(round(cdd)),
        "cwd": int(round(cwd)),
    }


def calculate_hazard(indicators: Dict, context: Dict, lat_center: float, lon_center: float) -> Tuple[str, float]:
    spi = indicators["spi"]
    rainfall_percentile = indicators["rainfall_percentile"]
    cdd = indicators["cdd"]
    cwd = indicators["cwd"]

    drought_evidence = 0.0
    wet_evidence = 0.0

    # Weights renormalized from the original 4-signal split (spi/anomaly%/
    # percentile/cdd-cwd at 0.35/0.25/0.20/0.20) after dropping the %-anomaly
    # term, which isn't available at subseasonal lead -- SPI already is a
    # standardized anomaly, so this isn't a loss of signal, just of
    # redundancy.
    if spi <= -1.0:
        drought_evidence += min(abs(spi) / 2.5, 1.0) * 0.45

    if rainfall_percentile <= 20:
        drought_evidence += min((20 - rainfall_percentile) / 20.0, 1.0) * 0.30

    if cdd >= 10:
        drought_evidence += min((cdd - 10) / 20.0, 1.0) * 0.25

    if spi >= 1.0:
        wet_evidence += min(spi / 2.5, 1.0) * 0.45

    if rainfall_percentile >= 80:
        wet_evidence += min((rainfall_percentile - 80) / 20.0, 1.0) * 0.30

    if cwd >= 7:
        wet_evidence += min((cwd - 7) / 15.0, 1.0) * 0.25

    drought_probability_real = sample_layer(context.get("drought_probability"), lat_center, lon_center)
    wet_probability_real = sample_layer(context.get("wet_probability"), lat_center, lon_center)
    dryspell_prob_7d_real = sample_layer(context.get("dryspell_prob_7d"), lat_center, lon_center)

    if drought_evidence >= wet_evidence and drought_evidence >= 0.25:
        # drought_probability (P(SPI<=-1)) and dryspell_prob_7d measure
        # related but distinct things (standardized seasonal rainfall deficit
        # vs. a specific dry-spell length), and can legitimately disagree --
        # e.g. a location whose CDD alone triggered "drought" here may still
        # show low SPI-drought probability if its dry season is climatologically
        # normal. Averaging whichever real signals are available uses more of
        # the real data than picking one arbitrarily.
        real_estimates = [value for value in (drought_probability_real, dryspell_prob_7d_real) if value is not None]
        probability = sum(real_estimates) / len(real_estimates) if real_estimates else None
        if probability is None:
            probability = clamp(0.25 + drought_evidence, 0.05, 0.95)
        return "drought", round(probability, 3)

    if wet_evidence > drought_evidence and wet_evidence >= 0.25:
        probability = wet_probability_real
        if probability is None:
            probability = clamp(0.25 + wet_evidence, 0.05, 0.95)
        return "heavy_rainfall", round(probability, 3)

    if cdd >= 12:
        probability = dryspell_prob_7d_real
        if probability is None:
            probability = clamp(0.35 + (cdd - 12) / 25.0, 0.05, 0.85)
        return "dry_spell", round(probability, 3)

    if cwd >= 8:
        return "wet_spell", round(clamp(0.35 + (cwd - 8) / 18.0, 0.05, 0.85), 3)

    return "no_alert", 0.25


def create_grid_cell_polygon(lon: float, lat: float, resolution: float) -> List[List[float]]:
    lon2 = round(lon + resolution, 6)
    lat2 = round(lat + resolution, 6)

    return [
        [lon, lat],
        [lon2, lat],
        [lon2, lat2],
        [lon, lat2],
        [lon, lat],
    ]


def create_feature(lon: float, lat: float, lead: Dict, context: Dict) -> Dict:
    lat_center = round(lat + GRID_RESOLUTION / 2.0, 6)
    lon_center = round(lon + GRID_RESOLUTION / 2.0, 6)

    indicators = calculate_forecast_indicators(
        lat_center=lat_center,
        lon_center=lon_center,
        context=context,
    )

    hazard, hazard_probability = calculate_hazard(indicators, context, lat_center, lon_center)
    exposure = calculate_exposure(lat_center, lon_center)
    vulnerability = calculate_vulnerability(lat_center, lon_center)

    confidence = 0.78 if lead["forecast_scale"] == "subseasonal" else 0.68
    if lead["value"] in ["month_4", "month_5", "month_6"]:
        confidence = 0.58

    risk_score = calculate_risk_score(
        hazard_probability=hazard_probability,
        exposure=exposure,
        vulnerability=vulnerability,
        confidence=confidence,
    )

    risk_level = classify_risk(risk_score)

    feature_id = f"{lead['value']}_{lat_center}_{lon_center}"

    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [create_grid_cell_polygon(lon, lat, GRID_RESOLUTION)],
        },
        "properties": {
            "id": feature_id,
            "forecast_scale": lead["forecast_scale"],
            "lead": lead["value"],
            "lead_label": lead["label"],
            "lat_center": lat_center,
            "lon_center": lon_center,
            "hazard": hazard,
            "hazard_probability": hazard_probability,
            "exposure": exposure,
            "vulnerability": vulnerability,
            "confidence": confidence,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "spi": indicators["spi"],
            "rainfall_anomaly_pct": indicators["rainfall_anomaly_pct"],
            "rainfall_percentile": indicators["rainfall_percentile"],
            "cdd": indicators["cdd"],
            "cwd": indicators["cwd"],
            "data_note": (
                "Hazard and hazard probability are sampled from real subseasonal/"
                "seasonal forecast rasters (SPI, rainfall, CDD/CWD, and ensemble "
                "drought/wet/dry-spell probabilities). Exposure and vulnerability "
                "are still prototype placeholder surfaces -- see "
                "calculate_exposure()/calculate_vulnerability()."
            ),
        },
    }


def build_feature_collection() -> Dict:
    features = []

    lats = frange(LAT_MIN, LAT_MAX, GRID_RESOLUTION)
    lons = frange(LON_MIN, LON_MAX, GRID_RESOLUTION)

    for lead in FORECAST_LEADS:
        context = build_lead_raster_context(lead)
        for lat in lats:
            for lon in lons:
                features.append(create_feature(lon=lon, lat=lat, lead=lead, context=context))

    return {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Ethiopia Forecast Risk Layers",
            "domain": {
                "lat_min": LAT_MIN,
                "lat_max": LAT_MAX,
                "lon_min": LON_MIN,
                "lon_max": LON_MAX,
                "resolution_degrees": GRID_RESOLUTION,
            },
            "forecast_leads": FORECAST_LEADS,
            "layers": [
                {"value": "hazard", "label": "Hazard Map"},
                {"value": "risk_score", "label": "Risk Score Map"},
                {"value": "hazard_probability", "label": "Hazard Probability Map"},
                {"value": "exposure", "label": "Exposure Map"},
                {"value": "vulnerability", "label": "Vulnerability Map"},
            ],
            "indicators": [
                {"value": "spi", "label": "Standardized Precipitation Index"},
                {"value": "rainfall_anomaly_pct", "label": "Rainfall anomaly"},
                {"value": "rainfall_percentile", "label": "Rainfall percentile"},
                {"value": "cdd", "label": "Consecutive dry days"},
                {"value": "cwd", "label": "Consecutive wet days"},
            ],
            "data_note": (
                "Hazard and Hazard Probability are derived from real ingested "
                "subseasonal/seasonal forecast rasters (see app/api/seasonal_raster_maps.py "
                "and data/maps/{geotiff,netcdf,csv}). Exposure and Vulnerability "
                "are still prototype placeholder surfaces pending real population/"
                "livestock/food-security data ingestion."
            ),
        },
        "features": features,
    }


def run_ethiopia_forecast_grid_pipeline() -> Dict:
    ensure_output_directory()

    feature_collection = build_feature_collection()

    OUTPUT_PATH.write_text(
        json.dumps(feature_collection, indent=2),
        encoding="utf-8",
    )

    print("Ethiopia forecast grid layer pipeline completed.")
    print(f"Output GeoJSON: {OUTPUT_PATH}")
    print(f"Features: {len(feature_collection['features'])}")

    return feature_collection


if __name__ == "__main__":
    run_ethiopia_forecast_grid_pipeline()