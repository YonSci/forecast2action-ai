import asyncio
import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.advisory.rag_engine import build_rag_advisory
from app.ml.risk_scoring import classify_risk, score_districts

from app.api.ai_map_interpretation import router as ai_map_interpretation_router
from app.api.community_reports_store import (
    CANONICAL_REPORT_TYPES,
    CommunityReport,
    REPORTS_PATH,
    VerifyReportRequest,
    canonical_report_type,
    load_reports,
    save_reports,
    summarize_reports,
)
from app.api.context_api import router as context_router
from app.api.decision_api import router as decision_router
from app.api.hazard_risk_maps import router as hazard_risk_maps_router
from app.api.hazard_risk_ranking import router as hazard_risk_ranking_router
from app.api.seasonal_maps import router as seasonal_maps_router
from app.api.seasonal_raster_maps import prewarm_all_maps
from app.api.seasonal_raster_maps import router as seasonal_raster_maps_router
from app.api.action_tracker_shape import (
    canonicalize_context_task,
    canonicalize_legacy_task,
)
from app.api.task_inference import (
    infer_deadline,
    infer_responsible_sector,
    infer_task_basis,
    infer_task_priority,
    slugify,
)
from app.decision.action_selector import build_tasks_from_context, select_actions
from app.decision.approval_engine import approve_task, get_approval_status, reject_task
from app.decision.policy_engine import load_policy_for_hazard
from app.decision.task_store import load_context_tasks, save_context_tasks
from app.decision.trigger_engine import evaluate as evaluate_trigger
from app.context.repository import get_repository

from app.data_pipeline.ethiopia_admin_boundary_pipeline import (
    OUTPUT_DIR as ADMIN_BOUNDARY_OUTPUT_DIR,
    run_ethiopia_admin_boundary_pipeline,
)

from app.data_pipeline.ethiopia_forecast_grid_pipeline import (
    FORECAST_LEADS,
    OUTPUT_PATH as ETHIOPIA_GRID_PATH,
    run_ethiopia_forecast_grid_pipeline,
)


app = FastAPI(
    title="Forecast2Action AI API",
    description=(
        "API for impact-based early warning, AI/RAG advisories, community feedback, "
        "priority actions, persistent implementation tracking, CSV export, climate evidence, "
        "and bulletin generation"
    ),
    version="1.2.0",
)

app.include_router(seasonal_maps_router)
app.include_router(ai_map_interpretation_router)
app.include_router(seasonal_raster_maps_router)
app.include_router(hazard_risk_maps_router)
app.include_router(hazard_risk_ranking_router)
app.include_router(context_router)
app.include_router(decision_router)


@app.on_event("startup")
async def _prewarm_seasonal_raster_cache_on_startup() -> None:
    """Optionally pre-convert seasonal raster maps so the first request is fast.

    Off by default. Set SEASONAL_RASTER_PREWARM_ON_STARTUP=true (e.g. on the
    deployed backend, after data/maps is populated) to build the GeoTIFF/tile
    cache once at boot instead of on each map's first user request. Runs in a
    background thread so it never delays the app from accepting requests.
    """
    if os.getenv("SEASONAL_RASTER_PREWARM_ON_STARTUP", "false").strip().lower() in {"1", "true", "yes"}:
        asyncio.create_task(run_in_threadpool(prewarm_all_maps))

allowed_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "https://forecast2action-ai.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

TASK_STATUS_PATH = Path("data/sample/action_task_status.json")

# Additive over the original 4 -- "Deferred"/"Cancelled" are new (spec §23),
# old stored task records using only the original 4 remain valid.
VALID_TASK_STATUSES = {
    "Not started",
    "In progress",
    "Completed",
    "Blocked",
    "Deferred",
    "Cancelled",
}

VALID_APPROVAL_STATUSES = {
    "Not required",
    "Pending",
    "Approved",
    "Rejected",
}


MAP_LAYER_OPTIONS = [
    {"value": "hazard", "label": "Hazard Map"},
    {"value": "risk_score", "label": "Risk Score Map"},
    {"value": "hazard_probability", "label": "Hazard Probability Map"},
    {"value": "exposure", "label": "Exposure Map"},
    {"value": "vulnerability", "label": "Vulnerability Map"},
]

MAP_INDICATOR_OPTIONS = [
    {"value": "spi", "label": "Standardized Precipitation Index"},
    {"value": "rainfall_anomaly_pct", "label": "Rainfall anomaly"},
    {"value": "rainfall_percentile", "label": "Rainfall percentile"},
    {"value": "cdd", "label": "Consecutive dry days"},
    {"value": "cwd", "label": "Consecutive wet days"},
]

VALID_FORECAST_SCALES = {"subseasonal", "seasonal"}
VALID_MAP_LAYERS = {item["value"] for item in MAP_LAYER_OPTIONS}
VALID_MAP_INDICATORS = {item["value"] for item in MAP_INDICATOR_OPTIONS}
VALID_FORECAST_LEADS = {item["value"] for item in FORECAST_LEADS}



ADMIN_OPTIONS_PATH = ADMIN_BOUNDARY_OUTPUT_DIR / "ethiopia_admin_options.json"
ADMIN_GEOJSON_PATHS = {
    "admin0": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin0.json",
    "admin1": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin1.json",
    "admin2": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin2.json",
    "admin3": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin3.json",
}


RANKING_LAYER_OPTIONS = [
    {"value": "risk_score", "label": "Risk Score Map"},
    {"value": "hazard_probability", "label": "Hazard Probability Map"},
    {"value": "exposure", "label": "Exposure Map"},
    {"value": "vulnerability", "label": "Vulnerability Map"},
]

VALID_RANKING_LAYERS = {item["value"] for item in RANKING_LAYER_OPTIONS}
VALID_RANKING_ADMIN_LEVELS = {"admin1", "admin2", "admin3"}

DEFAULT_RANKING_THRESHOLDS = {
    "risk_score": 0.60,
    "hazard_probability": 0.60,
    "exposure": 0.70,
    "vulnerability": 0.70,
}

CLIMATE_INDICATOR_OPTIONS = {
    "spi": {
        "label": "Standardized Precipitation Index",
        "digits": 2,
        "suffix": "",
    },
    "rainfall_anomaly_pct": {
        "label": "Rainfall anomaly",
        "digits": 1,
        "suffix": "%",
    },
    "rainfall_percentile": {
        "label": "Rainfall percentile",
        "digits": 1,
        "suffix": " percentile",
    },
    "cdd": {
        "label": "Consecutive dry days",
        "digits": 0,
        "suffix": " days",
    },
    "cwd": {
        "label": "Consecutive wet days",
        "digits": 0,
        "suffix": " days",
    },
}

VALID_CLIMATE_INDICATORS = set(CLIMATE_INDICATOR_OPTIONS.keys())


def summarize_numeric_field(rows: list, field_name: str) -> dict:
    values = []

    for row in rows:
      try:
          value = float(row.get(field_name))
      except (TypeError, ValueError):
          continue

      if value == value:
          values.append(value)

    if not values:
        return {
            "mean": None,
            "min": None,
            "max": None,
            "count": 0,
        }

    return {
        "mean": round(sum(values) / len(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "count": len(values),
    }


def build_climate_indicator_summary(rows: list) -> dict:
    return {
        indicator: {
            **summarize_numeric_field(rows, indicator),
            "label": config["label"],
            "suffix": config["suffix"],
            "digits": config["digits"],
        }
        for indicator, config in CLIMATE_INDICATOR_OPTIONS.items()
    }










def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False

    if not ring or len(ring) < 3:
        return False

    j = len(ring) - 1

    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]

        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) + 1e-12) + xi
        )

        if intersects:
            inside = not inside

        j = i

    return inside


def point_in_polygon(lon: float, lat: float, polygon_coordinates: list) -> bool:
    if not polygon_coordinates:
        return False

    exterior = polygon_coordinates[0]

    if not point_in_ring(lon, lat, exterior):
        return False

    for hole in polygon_coordinates[1:]:
        if point_in_ring(lon, lat, hole):
            return False

    return True


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    if not geometry:
        return False

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])

    if geometry_type == "Polygon":
        return point_in_polygon(lon, lat, coordinates)

    if geometry_type == "MultiPolygon":
        return any(
            point_in_polygon(lon, lat, polygon)
            for polygon in coordinates
        )

    return False


def collect_geometry_coordinates(coordinates: list, output: list) -> None:
    if not isinstance(coordinates, list):
        return

    if (
        len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and isinstance(coordinates[1], (int, float))
    ):
        output.append((coordinates[0], coordinates[1]))
        return

    for item in coordinates:
        collect_geometry_coordinates(item, output)


def get_geometry_bbox(geometry: dict) -> Optional[dict]:
    coordinates = []
    collect_geometry_coordinates(geometry.get("coordinates", []), coordinates)

    if not coordinates:
        return None

    lons = [item[0] for item in coordinates]
    lats = [item[1] for item in coordinates]

    return {
        "west": min(lons),
        "east": max(lons),
        "south": min(lats),
        "north": max(lats),
    }


def point_in_bbox(lon: float, lat: float, bbox: dict) -> bool:
    if not bbox:
        return False

    return (
        lon >= bbox["west"]
        and lon <= bbox["east"]
        and lat >= bbox["south"]
        and lat <= bbox["north"]
    )


def classify_priority_level(value: float, layer: str) -> str:
    if layer == "risk_score":
        return classify_risk(value)

    if value >= 0.70:
        return "high"
    if value >= 0.50:
        return "moderate"
    return "low"


def get_intervention_action(layer: str, priority_level: str) -> str:
    if layer == "risk_score":
        if priority_level == "trigger":
            return "Trigger immediate early action, pre-position resources, and intensify coordination."
        if priority_level == "warning":
            return "Prepare targeted early action, verify local conditions, and alert responsible sectors."
        if priority_level == "watch":
            return "Monitor closely and prepare advisory messages for local actors."
        return "Continue routine monitoring."

    if layer == "hazard_probability":
        if priority_level == "high":
            return "Prioritize forecast monitoring, preparedness messaging, and local verification."
        if priority_level == "moderate":
            return "Track forecast evolution and prepare readiness communication."
        return "Continue monitoring."

    if layer == "exposure":
        if priority_level == "high":
            return "Prioritize exposed population, assets, livelihoods, and service-access planning."
        if priority_level == "moderate":
            return "Review exposed settlements, roads, markets, crops, and livestock assets."
        return "Maintain exposure database and routine monitoring."

    if layer == "vulnerability":
        if priority_level == "high":
            return "Prioritize support to vulnerable communities and strengthen coping-capacity measures."
        if priority_level == "moderate":
            return "Target preparedness support and community-level risk communication."
        return "Continue vulnerability monitoring."

    return "Review area for possible intervention."


def get_admin_area_label(properties: dict, admin_level: str) -> str:
    if admin_level == "admin3":
        return properties.get("woreda") or properties.get("name") or "Unknown Woreda"

    if admin_level == "admin2":
        return properties.get("zone") or properties.get("name") or "Unknown Zone"

    return properties.get("region") or properties.get("name") or "Unknown Region"


def get_grid_features_for_forecast(
    forecast_scale: str,
    lead: str,
) -> list:
    grid = load_ethiopia_forecast_grid()

    features = []

    for feature in grid.get("features", []):
        properties = feature.get("properties", {})

        if properties.get("forecast_scale") != forecast_scale:
            continue

        if properties.get("lead") != lead:
            continue

        features.append(feature)

    return features


def safe_float_value(value, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except (TypeError, ValueError):
        return default


def mean_value(values: list) -> float:
    valid_values = [
        safe_float_value(value)
        for value in values
        if value is not None
    ]

    if not valid_values:
        return 0.0

    return sum(valid_values) / len(valid_values)


def max_value(values: list) -> float:
    valid_values = [
        safe_float_value(value)
        for value in values
        if value is not None
    ]

    if not valid_values:
        return 0.0

    return max(valid_values)


def most_common_value(values: list, default: str = "no_alert") -> str:
    counts = {}

    for value in values:
        if value is None or value == "":
            continue

        key = str(value)
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        return default

    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]


def classify_area_risk_level(risk_score: float) -> str:
    return classify_risk(risk_score)


def infer_area_hazard(hazards: list, risk_level: str) -> str:
    hazard = most_common_value(hazards, default="drought")

    if hazard and hazard != "no_alert":
        return hazard

    if risk_level in {"trigger", "warning", "watch"}:
        return "drought"

    return "no_alert"


def infer_area_responsible_sector(hazard: str, risk_level: str) -> str:
    if risk_level == "trigger":
        return "Disaster risk management, agriculture, water, health, and local administration"

    if hazard in {"drought", "dry_spell"}:
        return "Agriculture, water, livestock, disaster risk management, and local administration"

    if hazard in {"heavy_rainfall", "wet_spell", "flood"}:
        return "Disaster risk management, roads, water, health, and local administration"

    return "Disaster risk management and local administration"


def infer_area_deadline(risk_level: str) -> str:
    if risk_level == "trigger":
        return "Within 72 hours"

    if risk_level == "warning":
        return "Within 7 days"

    if risk_level == "watch":
        return "Within 14 days"

    return "Routine monitoring"


def infer_community_signal(cells_above_threshold_pct: float) -> str:
    if cells_above_threshold_pct >= 50:
        return "High forecast signal - ground verification needed"

    if cells_above_threshold_pct > 0:
        return "Emerging forecast signal - monitor locally"

    return "No strong ground signal yet"


def calculate_admin_area_ranking_item(
    admin_feature: dict,
    grid_features: list,
    layer: str,
    threshold: float,
    admin_level: str,
    indicator: str = "spi",
) -> Optional[dict]:
    admin_properties = admin_feature.get("properties", {})
    geometry = admin_feature.get("geometry", {})
    bbox = get_geometry_bbox(geometry)

    if not bbox:
        return None

    exact_rows = []
    fallback_bbox_rows = []

    for grid_feature in grid_features:
        grid_properties = grid_feature.get("properties", {})

        lat = grid_properties.get("lat_center")
        lon = grid_properties.get("lon_center")

        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue

        if not point_in_bbox(lon, lat, bbox):
            continue

        fallback_bbox_rows.append(grid_properties)

        if point_in_geometry(lon, lat, geometry):
            exact_rows.append(grid_properties)

    rows = exact_rows if exact_rows else fallback_bbox_rows

    if not rows:
        return None
    
    if indicator not in VALID_CLIMATE_INDICATORS:
        indicator = "spi"

    climate_indicators = build_climate_indicator_summary(rows)
    selected_indicator_summary = climate_indicators.get(
        indicator,
        climate_indicators["spi"],
    )

    ranking_values = [
        safe_float_value(row.get(layer))
        for row in rows
        if row.get(layer) is not None
    ]

    if not ranking_values:
        return None

    selected_mean_value = sum(ranking_values) / len(ranking_values)
    selected_max_value = max(ranking_values)

    cells_above_threshold = [
        value for value in ranking_values
        if value >= threshold
    ]

    cells_above_threshold_pct = len(cells_above_threshold) / len(ranking_values)

    priority_score = (
        0.50 * selected_mean_value
        + 0.25 * selected_max_value
        + 0.25 * cells_above_threshold_pct
    )

    risk_scores = [row.get("risk_score") for row in rows]
    hazard_probabilities = [row.get("hazard_probability") for row in rows]
    exposure_values = [row.get("exposure") for row in rows]
    vulnerability_values = [row.get("vulnerability") for row in rows]
    hazards = [row.get("hazard") for row in rows]
    risk_levels = [row.get("risk_level") for row in rows]

    risk_score = mean_value(risk_scores)
    hazard_probability = mean_value(hazard_probabilities)
    exposure = mean_value(exposure_values)
    vulnerability = mean_value(vulnerability_values)

    risk_level = most_common_value(
        risk_levels,
        default=classify_area_risk_level(risk_score),
    )

    if risk_level == "no_alert":
        risk_level = classify_area_risk_level(risk_score)

    hazard = infer_area_hazard(hazards, risk_level)
    priority_level = classify_priority_level(priority_score, layer)
    area_name = get_admin_area_label(admin_properties, admin_level)

    boundary_feature = {
        "type": "Feature",
        "id": admin_feature.get("id") or admin_properties.get("id") or area_name,
        "geometry": geometry,
        "properties": {
            **admin_properties,
            "admin_level": admin_level,
            "name": area_name,
        },
    }

    cells_above_threshold_pct_display = round(cells_above_threshold_pct * 100, 1)

    return {
        "admin_level": admin_level,
        "area_name": area_name,
        "region": admin_properties.get("region", ""),
        "zone": admin_properties.get("zone", ""),
        "woreda": admin_properties.get("woreda", ""),
        "region_id": admin_properties.get("region_id", ""),
        "zone_id": admin_properties.get("zone_id", ""),
        "woreda_id": admin_properties.get("woreda_id", ""),

        "hazard": hazard,
        "risk_level": risk_level,
        "risk_score": round(risk_score, 3),
        "hazard_probability": round(hazard_probability, 3),
        "exposure": round(exposure, 3),
        "vulnerability": round(vulnerability, 3),

        "selected_indicator": indicator,
        "selected_indicator_label": CLIMATE_INDICATOR_OPTIONS[indicator]["label"],
        "selected_indicator_value": selected_indicator_summary.get("mean"),
        "selected_indicator_min": selected_indicator_summary.get("min"),
        "selected_indicator_max": selected_indicator_summary.get("max"),
        "selected_indicator_suffix": CLIMATE_INDICATOR_OPTIONS[indicator]["suffix"],
        "selected_indicator_digits": CLIMATE_INDICATOR_OPTIONS[indicator]["digits"],
        "climate_indicators": climate_indicators,

        "mean_value": round(selected_mean_value, 3),
        "max_value": round(selected_max_value, 3),
        "cells_count": len(ranking_values),
        "cells_above_threshold": len(cells_above_threshold),
        "cells_above_threshold_pct": cells_above_threshold_pct_display,
        "priority_score": round(priority_score, 3),
        "priority_level": priority_level,

        "community_signal": infer_community_signal(cells_above_threshold_pct_display),
        "responsible_sector": infer_area_responsible_sector(hazard, risk_level),
        "suggested_deadline": infer_area_deadline(risk_level),
        "recommended_action": get_intervention_action(layer, priority_level),

        "boundary_feature": boundary_feature,
    }


@lru_cache(maxsize=128)
def build_intervention_ranking_cached(
    forecast_scale: str,
    lead: str,
    layer: str,
    admin_level: str,
    selection_mode: str,
    top_n: int,
    threshold: float,
    region_id: str,
    zone_id: str,
    indicator: str,
) -> dict:
    if indicator not in VALID_CLIMATE_INDICATORS:
        indicator = "spi"

    grid_features = get_grid_features_for_forecast(
        forecast_scale=forecast_scale,
        lead=lead,
    )

    admin_data = load_admin_json(ADMIN_GEOJSON_PATHS[admin_level])

    admin_features = filter_admin_features(
        admin_data.get("features", []),
        region_id=region_id,
        zone_id=zone_id,
    )

    ranking_items = []

    for admin_feature in admin_features:
        item = calculate_admin_area_ranking_item(
            admin_feature=admin_feature,
            grid_features=grid_features,
            layer=layer,
            threshold=threshold,
            admin_level=admin_level,
            indicator=indicator,

        )

        if item:
            ranking_items.append(item)

    if selection_mode == "threshold":
        ranking_items = [
            item for item in ranking_items
            if item["mean_value"] >= threshold
            or item["max_value"] >= threshold
            or item["cells_above_threshold_pct"] > 0
        ]

    ranking_items = sorted(
        ranking_items,
        key=lambda item: item["priority_score"],
        reverse=True,
    )

    if selection_mode == "top":
        ranking_items = ranking_items[:top_n]

    for index, item in enumerate(ranking_items, start=1):
        item["rank"] = index

    return {
        "forecast_scale": forecast_scale,
        "lead": lead,
        "layer": layer,
        "admin_level": admin_level,
        "indicator": indicator,
        "selection_mode": selection_mode,
        "top_n": top_n,
        "threshold": threshold,
        "region_id": region_id,
        "zone_id": zone_id,
        "indicator": indicator,
        "ranking": ranking_items,
        "metadata": {
            "grid_cells_used": len(grid_features),
            "admin_features_evaluated": len(admin_features),
            "ranking_count": len(ranking_items),
            "method": (
                "Priority score = 0.50 × mean value + 0.25 × max value + "
                "0.25 × share of grid cells above threshold. Exact point-in-polygon "
                "matching is used where grid-cell centers fall inside boundaries; "
                "bounding-box fallback is used for very small areas with no grid center."
            ),
        },
    }


def ensure_admin_boundaries() -> None:
    # Also checks admin0 specifically (not just the options file) so existing
    # deployments/local checkouts that already have eth_admin1/2/3.json from
    # before the Country tier was added still self-heal by regenerating once,
    # instead of staying stuck without eth_admin0.json forever.
    if not ADMIN_OPTIONS_PATH.exists() or not ADMIN_GEOJSON_PATHS["admin0"].exists():
        run_ethiopia_admin_boundary_pipeline()


@lru_cache(maxsize=16)
def load_admin_json_cached(path_string: str) -> dict:
    ensure_admin_boundaries()

    with Path(path_string).open("r", encoding="utf-8") as file:
        return json.load(file)


def load_admin_json(path: Path) -> dict:
    return load_admin_json_cached(str(path))


def filter_admin_features(
    features: list,
    region_id: str = "",
    zone_id: str = "",
    woreda_id: str = "",
) -> list:
    filtered_features = []

    for feature in features:
        props = feature.get("properties", {})

        if region_id and props.get("region_id") != region_id:
            continue

        if zone_id and props.get("zone_id") != zone_id:
            continue

        if woreda_id and props.get("woreda_id") != woreda_id:
            continue

        filtered_features.append(feature)

    return filtered_features


@lru_cache(maxsize=128)
def get_filtered_admin_boundary_cached(
    level: str,
    region_id: str,
    zone_id: str,
    woreda_id: str,
) -> dict:
    if level not in ADMIN_GEOJSON_PATHS:
        level = "admin1"

    data = load_admin_json(ADMIN_GEOJSON_PATHS[level])

    features = filter_admin_features(
        data.get("features", []),
        region_id=region_id,
        zone_id=zone_id,
        woreda_id=woreda_id,
    )

    return {
        "type": "FeatureCollection",
        "metadata": {
            "level": level,
            "region_id": region_id,
            "zone_id": zone_id,
            "woreda_id": woreda_id,
            "feature_count": len(features),
        },
        "features": features,
    }

def filter_admin_features(
    features: list,
    region_id: str = "",
    zone_id: str = "",
    woreda_id: str = "",
) -> list:
    filtered_features = []

    for feature in features:
        props = feature.get("properties", {})

        if region_id and props.get("region_id") != region_id:
            continue

        if zone_id and props.get("zone_id") != zone_id:
            continue

        if woreda_id and props.get("woreda_id") != woreda_id:
            continue

        filtered_features.append(feature)

    return filtered_features



def ensure_ethiopia_forecast_grid() -> None:
    if not ETHIOPIA_GRID_PATH.exists():
        run_ethiopia_forecast_grid_pipeline()


def load_ethiopia_forecast_grid() -> dict:
    ensure_ethiopia_forecast_grid()

    with ETHIOPIA_GRID_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


class TaskStatusUpdate(BaseModel):
    task_id: str
    status: str
    district: str = ""
    country: str = ""
    hazard: str = ""
    risk_level: str = ""
    audience: str = ""
    action: str = ""
    responsible_sector: str = ""
    priority: str = ""
    suggested_deadline: str = ""
    updated_by: str = "dashboard_user"


class ContextTaskStatusUpdate(BaseModel):
    task_id: str
    status: str
    updated_by: str = "dashboard_user"


class ApprovalDecision(BaseModel):
    task_id: str
    decision: str  # "approve" | "reject"
    approver: str = "dashboard_user"
    reason: str = ""


def model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()


def load_scored_data() -> pd.DataFrame:
    data_path = Path("data/sample/hazard_indicators.csv")

    if not data_path.exists():
        raise FileNotFoundError(
            "data/sample/hazard_indicators.csv not found. "
            "Run: python app\\data_pipeline\\load_sample_data.py"
        )

    df = pd.read_csv(data_path)
    return score_districts(df)


def ensure_task_status_file() -> None:
    TASK_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not TASK_STATUS_PATH.exists():
        TASK_STATUS_PATH.write_text(
            json.dumps({"statuses": {}}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def load_task_statuses() -> dict:
    ensure_task_status_file()

    try:
        data = json.loads(TASK_STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    if isinstance(data, dict) and isinstance(data.get("statuses"), dict):
        return data["statuses"]

    return {}


def save_task_statuses(statuses: dict) -> None:
    ensure_task_status_file()

    payload = {
        "statuses": statuses,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    TASK_STATUS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def safe_float(value, default=None):
    try:
        if pd.isna(value):
            return default
        return round(float(value), 4)
    except Exception:
        return default


def safe_text(value, default="Not available"):
    try:
        if value is None or pd.isna(value):
            return default
        return str(value)
    except Exception:
        return default


def format_coordinate(value):
    value = safe_float(value)

    if value is None:
        return "Not available"

    return str(value)


def build_osm_link(latitude, longitude):
    lat = safe_float(latitude)
    lon = safe_float(longitude)

    if lat is None or lon is None:
        return ""

    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=8/{lat}/{lon}"


def build_climate_evidence(row: dict) -> dict:
    return {
        "year": safe_text(row.get("year")),
        "season": safe_text(row.get("season")),
        "rainfall_mm": safe_float(row.get("rainfall_mm")),
        "baseline_mean_mm": safe_float(row.get("baseline_mean_mm")),
        "baseline_std_mm": safe_float(row.get("baseline_std_mm")),
        "rainfall_anomaly_mm": safe_float(row.get("rainfall_anomaly_mm")),
        "rainfall_anomaly_pct": safe_float(row.get("rainfall_anomaly_pct")),
        "spi": safe_float(row.get("spi")),
        "indicator_source": safe_text(row.get("indicator_source")),
        "data_note": safe_text(row.get("data_note")),
    }


def build_input_indicators(row: dict) -> dict:
    return {
        "hazard_probability": safe_float(row.get("hazard_probability")),
        "exposure": safe_float(row.get("exposure")),
        "vulnerability": safe_float(row.get("vulnerability")),
        "confidence": safe_float(row.get("confidence")),
        "risk_score": safe_float(row.get("risk_score")),
    }


def build_why_this_alert(row: dict, hazard_label: str, risk_level: str) -> str:
    climate_evidence = build_climate_evidence(row)

    climate_clause = ""

    if climate_evidence["rainfall_anomaly_pct"] is not None:
        climate_clause = (
            f" Rainfall anomaly is {climate_evidence['rainfall_anomaly_pct']}% "
            f"and the SPI-like score is {climate_evidence['spi']} for "
            f"{climate_evidence['season']} {climate_evidence['year']}."
        )

    return (
        f"{row['district']} is classified as {risk_level} for {hazard_label} "
        f"because hazard probability is {row['hazard_probability']}, exposure is "
        f"{row['exposure']}, vulnerability is {row['vulnerability']}, and forecast "
        f"confidence is {row['confidence']}. The combined risk score is {row['risk_score']}."
        f"{climate_clause}"
    )


def build_action_tasks_from_advisory(advisory: dict, audience: str) -> list[dict]:
    tasks = []
    saved_statuses = load_task_statuses()

    district = advisory.get("district", "")
    country = advisory.get("country", "")
    hazard = advisory.get("hazard", "")
    risk_level = advisory.get("risk_level", "")
    recommended_actions = advisory.get("recommended_actions", [])

    district_slug = slugify(district)
    audience_slug = slugify(audience)

    for index, action in enumerate(recommended_actions, start=1):
        task_id = f"{district_slug}_{audience_slug}_task_{index}"

        saved = saved_statuses.get(task_id, {})

        responsible_sector = infer_responsible_sector(action, hazard)
        priority = infer_task_priority(action, risk_level)
        suggested_deadline = infer_deadline(action, risk_level)

        task = {
            "id": task_id,
            "rank": index,
            "district": district,
            "country": country,
            "hazard": hazard,
            "risk_level": risk_level,
            "audience": audience,
            "action": action,
            "responsible_sector": responsible_sector,
            "priority": priority,
            "suggested_deadline": suggested_deadline,
            "status": saved.get("status", "Not started"),
            "updated_at": saved.get("updated_at"),
            "updated_by": saved.get("updated_by"),
            "basis": infer_task_basis(action, hazard, risk_level),
        }

        tasks.append(task)

    return tasks


@app.get("/")
def home():
    return {
        "message": "Forecast2Action AI API is running",
        "version": "1.2.0",
    }




# @app.get("/api/map-layers/options")
# def get_map_layer_options():
#     return {
#         "forecast_scales": [
#             {"value": "subseasonal", "label": "Subseasonal"},
#             {"value": "seasonal", "label": "Seasonal"},
#         ],
#         "leads": FORECAST_LEADS,
#         "layers": MAP_LAYER_OPTIONS,
#         "indicators": MAP_INDICATOR_OPTIONS,
#         "domain": {
#             "lat_min": 3.0,
#             "lat_max": 15.0,
#             "lon_min": 33.0,
#             "lon_max": 48.0,
#         },
#     }


@app.get("/api/admin-boundaries/options")
def get_admin_boundary_options(
    region_id: str = "",
    zone_id: str = "",
):
    options = load_admin_json(ADMIN_OPTIONS_PATH)

    regions = options.get("regions", [])
    zones = options.get("zones", [])
    woredas = options.get("woredas", [])

    if region_id:
        zones = [
            item for item in zones
            if item.get("region_id") == region_id
        ]

        woredas = [
            item for item in woredas
            if item.get("region_id") == region_id
        ]

    if zone_id:
        woredas = [
            item for item in woredas
            if item.get("zone_id") == zone_id
        ]

    return {
        "regions": regions,
        "zones": zones,
        "woredas": woredas,
    }

@app.get("/api/admin-boundaries/geojson")
def get_admin_boundary_geojson(
    level: str = "admin1",
    region_id: str = "",
    zone_id: str = "",
    woreda_id: str = "",
):
    if level not in ADMIN_GEOJSON_PATHS:
        level = "admin1"

    return get_filtered_admin_boundary_cached(
        level=level,
        region_id=region_id,
        zone_id=zone_id,
        woreda_id=woreda_id,
    )



@app.get("/api/map-layers/ethiopia")
def get_ethiopia_map_layer(
    forecast_scale: str = "subseasonal",
    lead: str = "week_1",
    layer: str = "hazard",
    indicator: str = "spi",
):
    if forecast_scale not in VALID_FORECAST_SCALES:
        forecast_scale = "subseasonal"

    if lead not in VALID_FORECAST_LEADS:
        lead = "week_1" if forecast_scale == "subseasonal" else "month_1"

    if layer not in VALID_MAP_LAYERS:
        layer = "hazard"

    if indicator not in VALID_MAP_INDICATORS:
        indicator = "spi"

    grid = load_ethiopia_forecast_grid()

    filtered_features = []

    for feature in grid.get("features", []):
        properties = feature.get("properties", {})

        if properties.get("forecast_scale") != forecast_scale:
            continue

        if properties.get("lead") != lead:
            continue

        selected_feature = dict(feature)
        selected_properties = dict(properties)

        selected_properties["selected_layer"] = layer
        selected_properties["selected_indicator"] = indicator
        selected_properties["selected_indicator_value"] = selected_properties.get(indicator)

        selected_feature["properties"] = selected_properties
        filtered_features.append(selected_feature)

    return {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Ethiopia Forecast Risk Layers",
            "forecast_scale": forecast_scale,
            "lead": lead,
            "layer": layer,
            "indicator": indicator,
            "domain": {
                "lat_min": 3.0,
                "lat_max": 15.0,
                "lon_min": 33.0,
                "lon_max": 48.0,
            },
            "feature_count": len(filtered_features),
            "data_note": (
                "Prototype 0.5-degree Ethiopia forecast grid. Replace with real "
                "subseasonal and seasonal ensemble forecasts for operational use."
            ),
        },
        "features": filtered_features,
    }

@app.get("/api/intervention-ranking")
def get_intervention_ranking(
    forecast_scale: str = "subseasonal",
    lead: str = "week_1",
    layer: str = "risk_score",
    admin_level: str = "admin1",
    selection_mode: str = "top",
    top_n: int = 5,
    threshold: Optional[float] = None,
    region_id: str = "",
    zone_id: str = "",
    indicator: str = "spi",
):
    if forecast_scale not in VALID_FORECAST_SCALES:
        forecast_scale = "subseasonal"

    if lead not in VALID_FORECAST_LEADS:
        lead = "week_1" if forecast_scale == "subseasonal" else "month_1"

    if layer not in VALID_RANKING_LAYERS:
        layer = "risk_score"

    if admin_level not in VALID_RANKING_ADMIN_LEVELS:
        admin_level = "admin1"

    if selection_mode not in {"top", "threshold"}:
        selection_mode = "top"

    top_n = max(3, min(int(top_n), 25))

    if threshold is None:
        threshold = DEFAULT_RANKING_THRESHOLDS.get(layer, 0.60)

    threshold = float(threshold)

    return build_intervention_ranking_cached(
        forecast_scale=forecast_scale,
        lead=lead,
        layer=layer,
        admin_level=admin_level,
        selection_mode=selection_mode,
        top_n=top_n,
        threshold=threshold,
        region_id=region_id,
        zone_id=zone_id,
        indicator=indicator,
    )

@app.get("/api/risk")
def get_risk_scores():
    scored = load_scored_data()
    return scored.to_dict(orient="records")


@app.get("/api/advisory/{district}")
def get_advisory(
    district: str,
    audience: str = Query(default="disaster_manager"),
    language: str = Query(default="en"),
):
    scored = load_scored_data()
    matched = scored[scored["district"].str.lower() == district.lower()]

    if matched.empty:
        return {
            "found": False,
            "district": district,
            "message": "No advisory found for this district.",
        }

    row: dict[str, Any] = {
        str(key): value
        for key, value in matched.iloc[0].to_dict().items()
    }

    hazard_label = row["hazard"].replace("_", " ")
    risk_level = row["risk_level"]

    feedback_summary = summarize_reports(district=district)

    rag_advisory = build_rag_advisory(
        row=row,
        audience=audience,
        feedback_summary=feedback_summary,
    )

    if feedback_summary["feedback_signal"] in [
        "emerging_ground_signal",
        "strong_ground_signal",
    ]:
        ground_truth_note = (
            f"Community reports indicate "
            f"{feedback_summary['feedback_signal'].replace('_', ' ')} "
            f"for {district}. Local officers should verify this information."
        )
    else:
        ground_truth_note = (
            "No strong community ground signal is currently available for this district."
        )

    if language == "am":
        community_message = (
            f"ቅድመ ማስጠንቀቂያ ለ {district}: የ {hazard_label} ስጋት "
            f"{risk_level} ደረጃ ላይ ነው። የአካባቢ መመሪያዎችን ይከተሉ።"
        )
    elif language == "sw":
        community_message = (
            f"Tahadhari ya mapema kwa {district}: Hatari ya {hazard_label} "
            f"iko katika kiwango cha {risk_level}. Fuata maelekezo ya eneo."
        )
    else:
        community_message = (
            f"Early warning for {district}: {hazard_label} risk is currently "
            f"at {risk_level} level. Follow local guidance and prepare early."
        )

    climate_evidence = build_climate_evidence(row)
    input_indicators = build_input_indicators(row)

    return {
        "found": True,
        "district": row["district"],
        "country": row["country"],
        "hazard": row["hazard"],
        "hazard_label": hazard_label,
        "risk_score": row["risk_score"],
        "risk_level": risk_level,
        "hazard_probability": row.get("hazard_probability"),
        "exposure": row.get("exposure"),
        "vulnerability": row.get("vulnerability"),
        "confidence": row.get("confidence"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "climate_evidence": climate_evidence,
        "input_indicators": input_indicators,
        "audience": audience,
        "audience_label": audience.replace("_", " ").title(),
        "language": language,
        "why_this_alert": build_why_this_alert(
            row=row,
            hazard_label=hazard_label,
            risk_level=risk_level,
        ),
        "recommended_actions": rag_advisory["recommended_actions"],
        "role_specific_advisory": rag_advisory["role_specific_advisory"],
        "retrieval_summary": rag_advisory["retrieval_summary"],
        "retrieved_guidance": rag_advisory["retrieved_guidance"],
        "knowledge_sources": rag_advisory["knowledge_sources"],
        "community_message": community_message,
        "ground_truth_note": ground_truth_note,
        "community_feedback_summary": feedback_summary,
        "mode": rag_advisory["mode"],
    }


@app.get("/api/action-tracker/{district}")
def get_action_tracker(
    district: str,
    audience: str = Query(default="disaster_manager"),
    language: str = Query(default="en"),
    context_id: str = Query(default=""),
):
    if context_id:
        # New, context-driven path: serve canonical-schema tasks tied to a
        # real Decision Context Envelope, with live status/approval merged
        # in. Falls through to the legacy rag_engine-based path below only
        # if this context_id has no persisted tasks yet.
        all_context_tasks = load_context_tasks()
        district_tasks = [
            task for task in all_context_tasks.values()
            if task.get("context_id") == context_id and task.get("district", "").lower() == district.lower()
        ]
        if district_tasks:
            for task in district_tasks:
                task["approval_status"] = get_approval_status(task["task_id"], task.get("approval_status", "Not required"))
                canonicalize_context_task(task, audience)

            return {
                "found": True,
                "district": district,
                "context_id": context_id,
                "audience": audience,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "total_tasks": len(district_tasks),
                    "urgent_tasks": len([t for t in district_tasks if t["priority"] == "Urgent"]),
                    "high_priority_tasks": len([t for t in district_tasks if t["priority"] == "High"]),
                    "in_progress_tasks": len([t for t in district_tasks if t["status"] == "In progress"]),
                    "completed_tasks": len([t for t in district_tasks if t["status"] == "Completed"]),
                    "blocked_tasks": len([t for t in district_tasks if t["status"] == "Blocked"]),
                },
                "tasks": district_tasks,
            }

    advisory = get_advisory(
        district=district,
        audience=audience,
        language=language,
    )

    if not advisory.get("found"):
        return {
            "found": False,
            "district": district,
            "tasks": [],
            "summary": {
                "total_tasks": 0,
                "urgent_tasks": 0,
                "high_priority_tasks": 0,
                "in_progress_tasks": 0,
                "completed_tasks": 0,
                "blocked_tasks": 0,
            },
        }

    tasks = build_action_tasks_from_advisory(
        advisory=advisory,
        audience=audience,
    )
    for task in tasks:
        canonicalize_legacy_task(task)

    urgent_tasks = len([task for task in tasks if task["priority"] == "Urgent"])
    high_priority_tasks = len([task for task in tasks if task["priority"] == "High"])
    in_progress_tasks = len([task for task in tasks if task["status"] == "In progress"])
    completed_tasks = len([task for task in tasks if task["status"] == "Completed"])
    blocked_tasks = len([task for task in tasks if task["status"] == "Blocked"])

    return {
        "found": True,
        "district": advisory.get("district"),
        "country": advisory.get("country"),
        "hazard": advisory.get("hazard"),
        "hazard_label": advisory.get("hazard_label"),
        "risk_level": advisory.get("risk_level"),
        "audience": audience,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_tasks": len(tasks),
            "urgent_tasks": urgent_tasks,
            "high_priority_tasks": high_priority_tasks,
            "in_progress_tasks": in_progress_tasks,
            "completed_tasks": completed_tasks,
            "blocked_tasks": blocked_tasks,
        },
        "tasks": tasks,
    }


@app.get("/api/action-tracker/{district}/csv")
def export_action_tracker_csv(
    district: str,
    audience: str = Query(default="disaster_manager"),
    language: str = Query(default="en"),
    context_id: str = Query(default=""),
):
    action_tracker = get_action_tracker(
        district=district,
        audience=audience,
        language=language,
        context_id=context_id,
    )

    safe_district = slugify(action_tracker.get("district", district))
    safe_audience = slugify(audience)

    output = io.StringIO()

    fieldnames = [
        "rank",
        "task_id",
        "district",
        "country",
        "hazard",
        "risk_level",
        "audience",
        "action",
        "responsible_sector",
        "priority",
        "suggested_deadline",
        "status",
        "updated_at",
        "updated_by",
        "basis",
        # Appended, not inserted -- existing columns keep their original
        # order for any positional CSV consumer. Present on both legacy and
        # context tasks after app.api.action_tracker_shape's canonicalization.
        "source",
        "context_id",
        "approval_status",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for task in action_tracker.get("tasks", []):
        writer.writerow(
            {
                "rank": task.get("rank", ""),
                "task_id": task.get("task_id", ""),
                "district": task.get("district", ""),
                "country": task.get("country", ""),
                "hazard": task.get("hazard", ""),
                "risk_level": task.get("risk_level", ""),
                "audience": task.get("audience", audience),
                "action": task.get("action", ""),
                "responsible_sector": task.get("responsible_sector", ""),
                "priority": task.get("priority", ""),
                "suggested_deadline": task.get("suggested_deadline", ""),
                "status": task.get("status", ""),
                "updated_at": task.get("updated_at", ""),
                "updated_by": task.get("updated_by", ""),
                "basis": task.get("basis", ""),
                "source": task.get("source", ""),
                "context_id": task.get("context_id") or "",
                "approval_status": task.get("approval_status", ""),
            }
        )

    csv_content = output.getvalue()

    filename = f"forecast2action_action_tracker_{safe_district}_{safe_audience}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@app.patch("/api/action-tracker/status")
def update_action_task_status(update: TaskStatusUpdate):
    payload = model_to_dict(update)

    status = payload.get("status")

    if status not in VALID_TASK_STATUSES:
        return {
            "success": False,
            "message": (
                f"Invalid status '{status}'. Valid statuses are: "
                f"{', '.join(sorted(VALID_TASK_STATUSES))}."
            ),
        }

    task_id = payload["task_id"]
    statuses = load_task_statuses()

    record = {
        "task_id": task_id,
        "district": payload.get("district", ""),
        "country": payload.get("country", ""),
        "hazard": payload.get("hazard", ""),
        "risk_level": payload.get("risk_level", ""),
        "audience": payload.get("audience", ""),
        "action": payload.get("action", ""),
        "responsible_sector": payload.get("responsible_sector", ""),
        "priority": payload.get("priority", ""),
        "suggested_deadline": payload.get("suggested_deadline", ""),
        "status": status,
        "updated_by": payload.get("updated_by", "dashboard_user"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    statuses[task_id] = record
    save_task_statuses(statuses)

    return {
        "success": True,
        "message": "Task status updated successfully.",
        "task": record,
    }


@app.patch("/api/action-tracker/context-status")
def update_context_task_status(update: ContextTaskStatusUpdate):
    """Status updates for the NEW context-driven tasks (see
    build_tasks_from_context). Storage stays separate from
    PATCH /api/action-tracker/status (the legacy rag_engine-based tasks) by
    design -- the two task sources have different persistence lifecycles
    (see app.decision.task_store's module docstring) -- but both are
    normalized to the same response shape by app.api.action_tracker_shape
    when read back via GET /api/action-tracker/{district}.
    """
    if update.status not in VALID_TASK_STATUSES:
        return {
            "success": False,
            "message": f"Invalid status '{update.status}'. Valid statuses are: {', '.join(sorted(VALID_TASK_STATUSES))}.",
        }

    tasks = load_context_tasks()
    task = tasks.get(update.task_id)
    if not task:
        return {"success": False, "message": f"Unknown task_id '{update.task_id}'."}

    task["status"] = update.status
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    task["updated_by"] = update.updated_by
    if update.status == "Completed":
        task["completed_at"] = task["updated_at"]

    tasks[update.task_id] = task
    save_context_tasks(tasks)

    return {"success": True, "message": "Task status updated successfully.", "task": task}


@app.patch("/api/action-tracker/approval")
def update_task_approval(decision: ApprovalDecision):
    if decision.decision not in ("approve", "reject"):
        return {"success": False, "message": "decision must be 'approve' or 'reject'."}

    if decision.decision == "approve":
        record = approve_task(decision.task_id, decision.approver)
    else:
        record = reject_task(decision.task_id, decision.approver, decision.reason)

    tasks = load_context_tasks()
    if decision.task_id in tasks:
        tasks[decision.task_id]["approval_status"] = record["approval_status"]
        save_context_tasks(tasks)

    return {"success": True, "approval": record}


@app.get("/api/report-types")
def get_report_types():
    return CANONICAL_REPORT_TYPES


@app.post("/api/community-reports")
def post_community_report(report: CommunityReport):
    reports = load_reports()

    new_report = model_to_dict(report)
    new_report["id"] = str(uuid4())
    new_report["created_at"] = datetime.now(timezone.utc).isoformat()
    new_report["status"] = "new"

    reports.insert(0, new_report)
    save_reports(reports)

    return {
        "success": True,
        "message": "Community report submitted successfully.",
        "report": new_report,
    }


@app.patch("/api/community-reports/{report_id}/verify")
def verify_community_report(report_id: str, request: VerifyReportRequest):
    if request.status not in ("verified", "disputed"):
        raise HTTPException(status_code=400, detail="status must be 'verified' or 'disputed'")

    reports = load_reports()
    for report in reports:
        if report.get("id") == report_id:
            report["verification_status"] = request.status
            report["verified_by"] = request.verified_by
            report["verified_at"] = datetime.now(timezone.utc).isoformat()
            save_reports(reports)
            return {"success": True, "report": report}

    raise HTTPException(status_code=404, detail=f"No community report with id={report_id}")


@app.get("/api/community-reports")
def list_community_reports(
    district: str | None = Query(default=None),
    country: str | None = Query(default=None),
    limit: int = Query(default=50),
):
    reports = load_reports()

    if district:
        reports = [
            report
            for report in reports
            if str(report.get("district", "")).lower() == district.lower()
        ]

    if country:
        reports = [
            report
            for report in reports
            if str(report.get("country", "")).lower() == country.lower()
        ]

    return {
        "count": len(reports[:limit]),
        "reports": reports[:limit],
    }


@app.get("/api/community-feedback-summary")
def get_community_feedback_summary(
    district: str | None = Query(default=None),
):
    return summarize_reports(district=district)


@app.get("/api/priority-actions")
def get_priority_actions():
    scored = load_scored_data()

    feedback_boosts = {
        "strong_ground_signal": 0.10,
        "emerging_ground_signal": 0.06,
        "limited_ground_signal": 0.03,
        "no_ground_signal": 0.00,
    }

    priority_items = []

    for _, row in scored.iterrows():
        district = row["district"]

        feedback = summarize_reports(district=district)
        feedback_signal = feedback["feedback_signal"]
        feedback_boost = feedback_boosts.get(feedback_signal, 0.0)

        risk_score = round(float(row["risk_score"]), 3)
        priority_score = round(min(risk_score + feedback_boost, 1.0), 3)

        risk_level = row["risk_level"]
        hazard_label = row["hazard"].replace("_", " ")

        if risk_level == "trigger":
            priority_label = "Urgent early action priority"
            recommended_next_step = (
                "Activate anticipatory action review, validate local conditions, "
                "coordinate responsible sector offices, and prepare immediate community advisories."
            )

        elif risk_level == "warning":
            priority_label = "Preparedness priority"
            recommended_next_step = (
                "Increase monitoring, brief local officers, prepare sector-specific preparedness "
                "messages, and verify whether local impacts are emerging."
            )

        elif risk_level == "watch":
            priority_label = "Monitoring priority"
            recommended_next_step = (
                "Continue close monitoring, collect additional community observations, "
                "and prepare advisory messages if risk increases."
            )

        else:
            priority_label = "Routine monitoring"
            recommended_next_step = (
                "Maintain routine monitoring and update local preparedness information."
            )

        if feedback_signal in ["strong_ground_signal", "emerging_ground_signal"]:
            recommended_next_step += (
                " Community reports indicate field-level stress and should be verified by local officers."
            )

        priority_items.append(
            {
                "country": row["country"],
                "district": district,
                "hazard": row["hazard"],
                "hazard_label": hazard_label,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "feedback_signal": feedback_signal,
                "community_reports": feedback["total_reports"],
                "priority_score": priority_score,
                "priority_label": priority_label,
                "recommended_next_step": recommended_next_step,
                "latitude": safe_float(row.get("latitude")),
                "longitude": safe_float(row.get("longitude")),
                "rainfall_anomaly_pct": safe_float(row.get("rainfall_anomaly_pct")),
                "spi": safe_float(row.get("spi")),
            }
        )

    priority_items = sorted(
        priority_items,
        key=lambda item: item["priority_score"],
        reverse=True,
    )

    for index, item in enumerate(priority_items, start=1):
        item["rank"] = index

    return priority_items


@app.get("/api/bulletin/{district}")
def generate_bulletin(
    district: str,
    audience: str = Query(default="disaster_manager"),
    language: str = Query(default="en"),
    output_format: str = Query(default="html"),
):
    scored = load_scored_data()
    matched = scored[scored["district"].str.lower() == district.lower()]

    if matched.empty:
        return {
            "found": False,
            "district": district,
            "message": "No bulletin could be generated because the district was not found.",
        }

    selected_row = matched.iloc[0].to_dict()

    advisory = get_advisory(
        district=district,
        audience=audience,
        language=language,
    )

    action_tracker = get_action_tracker(
        district=district,
        audience=audience,
        language=language,
    )

    priority_items = get_priority_actions()

    total_countries = scored["country"].nunique()
    total_hazards = scored["hazard"].nunique()
    total_warnings = int((scored["risk_level"] == "warning").sum())
    total_triggers = int((scored["risk_level"] == "trigger").sum())

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    priority_rows_html = ""
    priority_rows_md = ""

    for item in priority_items:
        priority_rows_html += f"""
        <tr>
            <td>{item["rank"]}</td>
            <td>{escape(item["district"])}</td>
            <td>{escape(item["country"])}</td>
            <td>{escape(item["hazard_label"])}</td>
            <td>{escape(item["risk_level"])}</td>
            <td>{item["risk_score"]}</td>
            <td>{item["priority_score"]}</td>
            <td>{item["community_reports"]}</td>
            <td>{item.get("rainfall_anomaly_pct", "NA")}</td>
            <td>{item.get("spi", "NA")}</td>
        </tr>
        """

        priority_rows_md += (
            f'| {item["rank"]} | {item["district"]} | {item["country"]} | '
            f'{item["hazard_label"]} | {item["risk_level"]} | '
            f'{item["risk_score"]} | {item["priority_score"]} | '
            f'{item["community_reports"]} | {item.get("rainfall_anomaly_pct", "NA")} | '
            f'{item.get("spi", "NA")} |\n'
        )

    action_task_rows_html = ""
    action_task_rows_md = ""

    for task in action_tracker.get("tasks", []):
        action_task_rows_html += f"""
        <tr>
            <td>{task["rank"]}</td>
            <td>{escape(task["action"])}</td>
            <td>{escape(task["responsible_sector"])}</td>
            <td>{escape(task["priority"])}</td>
            <td>{escape(task["suggested_deadline"])}</td>
            <td>{escape(task["status"])}</td>
        </tr>
        """

        action_task_rows_md += (
            f'| {task["rank"]} | {task["action"]} | {task["responsible_sector"]} | '
            f'{task["priority"]} | {task["suggested_deadline"]} | {task["status"]} |\n'
        )

    actions_html = "".join(
        f"<li>{escape(action)}</li>"
        for action in advisory.get("recommended_actions", [])
    )

    actions_md = "\n".join(
        f"- {action}" for action in advisory.get("recommended_actions", [])
    )

    knowledge_sources = advisory.get("knowledge_sources", [])
    retrieval_summary = advisory.get("retrieval_summary", "")

    knowledge_sources_html = "".join(
        f"""
        <li>
            <strong>{escape(str(source.get("title", "Knowledge item")))}</strong>
            — {escape(str(source.get("sector", "")))}.
            Retrieval score: {source.get("retrieval_score", "NA")}.
            <br />
            <span>{escape(str(source.get("source_note", "")))}</span>
        </li>
        """
        for source in knowledge_sources
    )

    knowledge_sources_md = "\n".join(
        f"- **{source.get('title', 'Knowledge item')}** "
        f"({source.get('sector', '')}); retrieval score: "
        f"{source.get('retrieval_score', 'NA')}. {source.get('source_note', '')}"
        for source in knowledge_sources
    )

    district_name = advisory.get("district", district)
    country = advisory.get("country", "")
    hazard_label = advisory.get("hazard_label", "")
    risk_level = advisory.get("risk_level", "")
    risk_score = advisory.get("risk_score", "")
    why_this_alert = advisory.get("why_this_alert", "")
    ground_truth_note = advisory.get("ground_truth_note", "")
    role_specific_advisory = advisory.get("role_specific_advisory", "")
    community_message = advisory.get("community_message", "")
    mode = advisory.get("mode", "template")

    latitude = safe_float(selected_row.get("latitude"))
    longitude = safe_float(selected_row.get("longitude"))
    latitude_text = format_coordinate(latitude)
    longitude_text = format_coordinate(longitude)
    osm_link = build_osm_link(latitude, longitude)

    hazard_probability = safe_float(selected_row.get("hazard_probability"))
    exposure = safe_float(selected_row.get("exposure"))
    vulnerability = safe_float(selected_row.get("vulnerability"))
    confidence = safe_float(selected_row.get("confidence"))

    rainfall_mm = safe_float(selected_row.get("rainfall_mm"))
    baseline_mean_mm = safe_float(selected_row.get("baseline_mean_mm"))
    baseline_std_mm = safe_float(selected_row.get("baseline_std_mm"))
    rainfall_anomaly_mm = safe_float(selected_row.get("rainfall_anomaly_mm"))
    rainfall_anomaly_pct = safe_float(selected_row.get("rainfall_anomaly_pct"))
    spi = safe_float(selected_row.get("spi"))
    year = safe_text(selected_row.get("year"))
    season = safe_text(selected_row.get("season"))
    indicator_source = safe_text(selected_row.get("indicator_source"))
    data_note = safe_text(selected_row.get("data_note"))

    safe_filename = district_name.replace(" ", "_").replace("/", "_")

    if output_format.lower() == "markdown":
        map_line = (
            f"[Open selected location in OpenStreetMap]({osm_link})"
            if osm_link
            else "Map location not available."
        )

        markdown_content = f"""# Forecast2Action AI Early Warning Bulletin

**Generated:** {generated_at}  
**District:** {district_name}, {country}  
**Hazard:** {hazard_label}  
**Risk level:** {risk_level}  
**Risk score:** {risk_score}  
**Audience:** {audience.replace("_", " ").title()}  
**Language:** {language}  
**Advisory mode:** {mode}

---

## Executive Summary

Forecast2Action AI classified **{district_name}, {country}** as **{risk_level}** for **{hazard_label}**.

## System Overview

| Indicator | Value |
|---|---:|
| Countries monitored | {total_countries} |
| Hazards monitored | {total_hazards} |
| SPI-like score | {spi} |

## Risk Indicator Values

| Indicator | Value |
|---|---:|
| Hazard probability | {hazard_probability} |
| Exposure | {exposure} |
| Vulnerability | {vulnerability} |
| Forecast confidence | {confidence} |
| Combined risk score | {risk_score} |

## Priority Action Queue

| Rank | District | Country | Hazard | Risk Level | Risk Score | Priority Score | Community Reports | Rainfall Anomaly % | SPI |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
{priority_rows_md}

## Recommended Early Actions

{actions_md}

## Action Implementation Tracker

| Rank | Action | Responsible Sector | Priority | Suggested Deadline | Status |
|---:|---|---|---|---|---|
{action_task_rows_md}

## Why This Alert?

{why_this_alert}

## Community Ground-Truth Signal

{ground_truth_note}

## Role-Specific Advisory

{role_specific_advisory}

## Knowledge-Guided Advisory Basis

{retrieval_summary}

{knowledge_sources_md}

## SMS / WhatsApp-ready Community Message

{community_message}

## Prototype Data Note

**Indicator source:** {indicator_source}

{data_note}

---

*Generated by Forecast2Action AI prototype for IGAD Hackathon 2026.*
"""

        return Response(
            content=markdown_content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="forecast2action_bulletin_{safe_filename}.md"'
                )
            },
        )

    map_reference_html = (
        f'<a href="{escape(osm_link)}" target="_blank">Open selected location in OpenStreetMap</a>'
        if osm_link
        else "Map location not available."
    )

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8" />
    <title>Forecast2Action AI Bulletin - {escape(district_name)}</title>
    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            margin: 40px;
            color: #0b1f3a;
            line-height: 1.55;
            background: #f5f7fb;
        }}

        .toolbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            background: #ffffff;
            border: 1px solid #e5e9f2;
            border-radius: 16px;
            padding: 14px 18px;
            margin-bottom: 24px;
            position: sticky;
            top: 12px;
            z-index: 10;
            box-shadow: 0 10px 30px rgba(20, 34, 66, 0.08);
        }}

        .toolbar-text {{
            color: #475467;
            font-size: 14px;
        }}

        .print-button {{
            border: none;
            border-radius: 12px;
            padding: 12px 18px;
            background: #172033;
            color: #ffffff;
            font-weight: bold;
            cursor: pointer;
        }}

        .header {{
            background: linear-gradient(135deg, #16233d, #294f87);
            color: white;
            padding: 32px;
            border-radius: 20px;
            margin-bottom: 28px;
        }}

        .header h1 {{
            margin: 0;
            font-size: 34px;
        }}

        .header p {{
            margin: 8px 0 0;
            color: #e4ecff;
        }}

        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            margin: 22px 0;
        }}

        .meta-card {{
            border: 1px solid #e5e9f2;
            border-radius: 14px;
            padding: 16px;
            background: #ffffff;
        }}

        .meta-card span {{
            display: block;
            color: #667085;
            font-size: 13px;
        }}

        .meta-card strong {{
            display: block;
            font-size: 22px;
            margin-top: 6px;
        }}

        .section {{
            margin-top: 28px;
            padding: 22px;
            border: 1px solid #e5e9f2;
            border-radius: 18px;
            background: #ffffff;
        }}

        .note-section {{
            background: #fff8e6;
            border-color: #fedf89;
        }}

        h2 {{
            margin-top: 0;
            color: #0b1f3a;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }}

        th, td {{
            text-align: left;
            padding: 10px;
            border-bottom: 1px solid #e5e9f2;
            font-size: 14px;
            vertical-align: top;
        }}

        th {{
            color: #667085;
        }}

        .badge {{
            display: inline-block;
            padding: 7px 12px;
            border-radius: 999px;
            background: #fee4e2;
            color: #b42318;
            font-weight: bold;
            text-transform: uppercase;
        }}

        .sms {{
            background: #eef4ff;
            border: 1px solid #d7e4ff;
            border-radius: 14px;
            padding: 16px;
            font-weight: bold;
        }}

        .map-card {{
            background: #f8fafc;
            border: 1px solid #e5e9f2;
            border-radius: 14px;
            padding: 16px;
        }}

        .map-card a {{
            color: #175cd3;
            font-weight: bold;
            text-decoration: none;
        }}

        .footer {{
            margin-top: 30px;
            color: #667085;
            font-size: 13px;
        }}

        @media print {{
            body {{
                margin: 18px;
                background: #ffffff;
            }}

            .toolbar {{
                display: none !important;
            }}

            .header {{
                background: #16233d !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}

            .section {{
                page-break-inside: avoid;
            }}

            .meta-grid {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="toolbar">
        <div class="toolbar-text">
            Open the print dialog and choose <strong>Save as PDF</strong> to export this bulletin.
        </div>
        <button class="print-button" onclick="window.print()">Print / Save as PDF</button>
    </div>

    <div class="header">
        <h1>Forecast2Action AI Early Warning Bulletin</h1>
        <p>Generated: {generated_at}</p>
        <p>Smarter early warning, stronger communities</p>
    </div>

    <div class="section">
        <h2>Executive Summary</h2>
        <p>
            Forecast2Action AI classified <strong>{escape(district_name)}, {escape(country)}</strong>
            as <span class="badge">{escape(risk_level)}</span>
            for <strong>{escape(hazard_label)}</strong>.
        </p>
        <p>
            This bulletin summarizes climate evidence, risk scoring, RAG-style advisory retrieval,
            recommended actions, implementation tasks, and community communication messages.
        </p>
    </div>

    <div class="meta-grid">
        <div class="meta-card">
            <span>Countries monitored</span>
            <strong>{total_countries}</strong>
        </div>
        <div class="meta-card">
            <span>Hazards monitored</span>
            <strong>{total_hazards}</strong>
        </div>
        <div class="meta-card">
            <span>Warning areas</span>
            <strong>{total_warnings}</strong>
        </div>
        <div class="meta-card">
            <span>Trigger areas</span>
            <strong>{total_triggers}</strong>
        </div>
    </div>

    <div class="section">
        <h2>Selected District Alert</h2>
        <table>
            <tr><th>District</th><td>{escape(district_name)}</td></tr>
            <tr><th>Country</th><td>{escape(country)}</td></tr>
            <tr><th>Hazard</th><td>{escape(hazard_label)}</td></tr>
            <tr><th>Risk Level</th><td>{escape(risk_level)}</td></tr>
            <tr><th>Risk Score</th><td>{risk_score}</td></tr>
            <tr><th>Target Audience</th><td>{escape(audience.replace("_", " ").title())}</td></tr>
            <tr><th>Advisory Mode</th><td>{escape(mode)}</td></tr>
        </table>
    </div>

    <div class="section">
        <h2>Selected District Location</h2>
        <div class="map-card">
            <table>
                <tr><th>Latitude</th><td>{escape(latitude_text)}</td></tr>
                <tr><th>Longitude</th><td>{escape(longitude_text)}</td></tr>
                <tr><th>Map reference</th><td>{map_reference_html}</td></tr>
            </table>
        </div>
    </div>

    <div class="section">
        <h2>Climate Evidence</h2>
        <table>
            <tr><th>Year</th><td>{year}</td></tr>
            <tr><th>Season</th><td>{season}</td></tr>
            <tr><th>Seasonal rainfall</th><td>{rainfall_mm} mm</td></tr>
            <tr><th>Baseline mean rainfall</th><td>{baseline_mean_mm} mm</td></tr>
            <tr><th>Baseline rainfall standard deviation</th><td>{baseline_std_mm} mm</td></tr>
            <tr><th>Rainfall anomaly</th><td>{rainfall_anomaly_mm} mm</td></tr>
            <tr><th>Rainfall anomaly percent</th><td>{rainfall_anomaly_pct}%</td></tr>
            <tr><th>SPI-like score</th><td>{spi}</td></tr>
        </table>
    </div>

    <div class="section">
        <h2>Risk Indicator Values</h2>
        <table>
            <tr><th>Hazard probability</th><td>{hazard_probability}</td></tr>
            <tr><th>Exposure</th><td>{exposure}</td></tr>
            <tr><th>Vulnerability</th><td>{vulnerability}</td></tr>
            <tr><th>Forecast confidence</th><td>{confidence}</td></tr>
            <tr><th>Combined risk score</th><td>{risk_score}</td></tr>
        </table>
    </div>

    <div class="section">
        <h2>Priority Action Queue</h2>
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>District</th>
                    <th>Country</th>
                    <th>Hazard</th>
                    <th>Risk Level</th>
                    <th>Risk Score</th>
                    <th>Priority Score</th>
                    <th>Reports</th>
                    <th>Anomaly %</th>
                    <th>SPI</th>
                </tr>
            </thead>
            <tbody>
                {priority_rows_html}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Recommended Early Actions</h2>
        <ul>
            {actions_html}
        </ul>
    </div>

    <div class="section">
        <h2>Action Implementation Tracker</h2>
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Action</th>
                    <th>Responsible Sector</th>
                    <th>Priority</th>
                    <th>Suggested Deadline</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {action_task_rows_html}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Why This Alert?</h2>
        <p>{escape(why_this_alert)}</p>
    </div>

    <div class="section">
        <h2>Community Ground-Truth Signal</h2>
        <p>{escape(ground_truth_note)}</p>
    </div>

    <div class="section">
        <h2>Role-Specific Advisory</h2>
        <p>{escape(role_specific_advisory)}</p>
    </div>

    <div class="section">
        <h2>Knowledge-Guided Advisory Basis</h2>
        <p>{escape(retrieval_summary)}</p>
        <ul>
            {knowledge_sources_html}
        </ul>
    </div>

    <div class="section">
        <h2>SMS / WhatsApp-ready Community Message</h2>
        <div class="sms">{escape(community_message)}</div>
    </div>

    <div class="section note-section">
        <h2>Prototype Data Note</h2>
        <p><strong>Indicator source:</strong> {escape(indicator_source)}</p>
        <p>{escape(data_note)}</p>
    </div>

    <div class="footer">
        Generated by Forecast2Action AI prototype for IGAD Hackathon 2026.
    </div>
</body>
</html>
"""

    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": (
                f'attachment; filename="forecast2action_bulletin_{safe_filename}.html"'
            )
        },
    )