from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Tuple


OUTPUT_PATH = Path("data/sample/ethiopia_forecast_grid_layers.geojson")

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


def classify_risk(score: float) -> str:
    if score < 0.35:
        return "no_alert"

    if score < 0.60:
        return "watch"

    if score < 0.80:
        return "warning"

    return "trigger"


def calculate_exposure(lat_center: float, lon_center: float) -> float:
    """
    Prototype exposure surface.

    Higher exposure is assigned to lowland / eastern and southeastern parts
    of the Ethiopia domain. Replace later with population, cropland, livestock,
    infrastructure, and settlement exposure layers.
    """

    east_component = (lon_center - LON_MIN) / (LON_MAX - LON_MIN)
    lowland_component = 1.0 - ((lat_center - LAT_MIN) / (LAT_MAX - LAT_MIN))
    wave_component = 0.12 * math.sin((lat_center + lon_center) * 0.8)

    exposure = 0.35 + 0.30 * east_component + 0.25 * lowland_component + wave_component

    return round(clamp(exposure, 0.05, 0.95), 3)


def calculate_vulnerability(lat_center: float, lon_center: float) -> float:
    """
    Prototype vulnerability surface.

    Replace later with real vulnerability indicators such as poverty,
    livelihood sensitivity, adaptive capacity, water access, food security,
    livestock dependency, and health vulnerability.
    """

    south_component = 1.0 - ((lat_center - LAT_MIN) / (LAT_MAX - LAT_MIN))
    east_component = (lon_center - LON_MIN) / (LON_MAX - LON_MIN)
    wave_component = 0.10 * math.cos((lat_center * 1.3) - (lon_center * 0.7))

    vulnerability = 0.40 + 0.25 * south_component + 0.25 * east_component + wave_component

    return round(clamp(vulnerability, 0.05, 0.95), 3)


def calculate_forecast_indicators(
    lat_center: float,
    lon_center: float,
    lead: Dict,
) -> Dict:
    """
    Prototype gridded forecast indicators.

    These are synthetic but deterministic values for dashboard demonstration.
    In production, replace this with real subseasonal and seasonal forecast
    fields, hindcast climatology, bias correction, and ensemble probabilities.
    """

    lead_index = lead["index"]
    scale = lead["forecast_scale"]

    spatial_wave = math.sin((lat_center - 8.0) * 0.8) + math.cos((lon_center - 39.0) * 0.65)
    east_west_gradient = (lon_center - 40.0) / 8.0
    north_south_gradient = (lat_center - 9.0) / 6.0

    if scale == "subseasonal":
        lead_factor = math.sin(lead_index * 0.75)
        rainfall_anomaly_pct = (
            -12
            + 18 * spatial_wave
            - 10 * east_west_gradient
            + 8 * north_south_gradient
            + 10 * lead_factor
        )
    else:
        lead_factor = math.cos(lead_index * 0.45)
        rainfall_anomaly_pct = (
            -8
            + 16 * spatial_wave
            - 8 * east_west_gradient
            + 6 * north_south_gradient
            + 8 * lead_factor
        )

    rainfall_anomaly_pct = round(clamp(rainfall_anomaly_pct, -70, 70), 1)

    spi = round(clamp(rainfall_anomaly_pct / 25.0, -2.8, 2.8), 2)

    rainfall_percentile = round(
        clamp(50 + rainfall_anomaly_pct * 0.65 + 8 * math.sin(lat_center + lead_index), 1, 99),
        1,
    )

    dry_signal = max(0.0, -rainfall_anomaly_pct)
    wet_signal = max(0.0, rainfall_anomaly_pct)

    cdd = int(round(clamp(4 + dry_signal / 4.2 + 3 * math.sin(lon_center + lead_index), 0, 35)))
    cwd = int(round(clamp(2 + wet_signal / 5.0 + 2 * math.cos(lat_center + lead_index), 0, 24)))

    return {
        "spi": spi,
        "rainfall_anomaly_pct": rainfall_anomaly_pct,
        "rainfall_percentile": rainfall_percentile,
        "cdd": cdd,
        "cwd": cwd,
    }


def calculate_hazard(indicators: Dict) -> Tuple[str, float]:
    spi = indicators["spi"]
    rainfall_anomaly_pct = indicators["rainfall_anomaly_pct"]
    rainfall_percentile = indicators["rainfall_percentile"]
    cdd = indicators["cdd"]
    cwd = indicators["cwd"]

    drought_evidence = 0.0
    wet_evidence = 0.0

    if spi <= -1.0:
        drought_evidence += min(abs(spi) / 2.5, 1.0) * 0.35

    if rainfall_anomaly_pct <= -20:
        drought_evidence += min(abs(rainfall_anomaly_pct) / 60.0, 1.0) * 0.25

    if rainfall_percentile <= 20:
        drought_evidence += min((20 - rainfall_percentile) / 20.0, 1.0) * 0.20

    if cdd >= 10:
        drought_evidence += min((cdd - 10) / 20.0, 1.0) * 0.20

    if spi >= 1.0:
        wet_evidence += min(spi / 2.5, 1.0) * 0.35

    if rainfall_anomaly_pct >= 20:
        wet_evidence += min(rainfall_anomaly_pct / 60.0, 1.0) * 0.25

    if rainfall_percentile >= 80:
        wet_evidence += min((rainfall_percentile - 80) / 20.0, 1.0) * 0.20

    if cwd >= 7:
        wet_evidence += min((cwd - 7) / 15.0, 1.0) * 0.20

    drought_probability = clamp(0.25 + drought_evidence, 0.05, 0.95)
    wet_probability = clamp(0.25 + wet_evidence, 0.05, 0.95)

    if drought_evidence >= wet_evidence and drought_evidence >= 0.25:
        return "drought", round(drought_probability, 3)

    if wet_evidence > drought_evidence and wet_evidence >= 0.25:
        return "heavy_rainfall", round(wet_probability, 3)

    if cdd >= 12:
        return "dry_spell", round(clamp(0.35 + (cdd - 12) / 25.0, 0.05, 0.85), 3)

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


def create_feature(lon: float, lat: float, lead: Dict) -> Dict:
    lat_center = round(lat + GRID_RESOLUTION / 2.0, 6)
    lon_center = round(lon + GRID_RESOLUTION / 2.0, 6)

    indicators = calculate_forecast_indicators(
        lat_center=lat_center,
        lon_center=lon_center,
        lead=lead,
    )

    hazard, hazard_probability = calculate_hazard(indicators)
    exposure = calculate_exposure(lat_center, lon_center)
    vulnerability = calculate_vulnerability(lat_center, lon_center)

    confidence = 0.78 if lead["forecast_scale"] == "subseasonal" else 0.68
    if lead["value"] in ["month_4", "month_5", "month_6"]:
        confidence = 0.58

    risk_score = round(
        clamp(
            0.40 * hazard_probability
            + 0.25 * exposure
            + 0.25 * vulnerability
            + 0.10 * confidence,
            0.0,
            1.0,
        ),
        3,
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
                "Prototype gridded Ethiopia forecast layer. Replace with real "
                "subseasonal and seasonal ensemble forecast data for operations."
            ),
        },
    }


def build_feature_collection() -> Dict:
    features = []

    lats = frange(LAT_MIN, LAT_MAX, GRID_RESOLUTION)
    lons = frange(LON_MIN, LON_MAX, GRID_RESOLUTION)

    for lead in FORECAST_LEADS:
        for lat in lats:
            for lon in lons:
                features.append(create_feature(lon=lon, lat=lat, lead=lead))

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
                "Synthetic deterministic prototype data for dashboard testing. "
                "The production version should ingest real forecast and hindcast datasets."
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