"""District-level (admin1/admin2/admin3) ranking over the real Hazard/Risk raster catalog.

This is a genuinely different data source from /api/intervention-ranking's
district ranking (which runs over the older, synthetic
ethiopia_forecast_grid_pipeline.py cell grid, with only risk_score/
hazard_probability/exposure/vulnerability/hazard fields) -- this module
zonal-aggregates the real GeoTIFFs (see hazard_risk_catalog_shared.py) into a
per-district mean/max/threshold-fraction, using the same admin boundary
polygons served by /api/admin-boundaries/geojson, then ranks districts by
whichever one metric the caller names as `rank_by`.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from app.data_pipeline.ethiopia_admin_boundary_pipeline import (
    OUTPUT_DIR as ADMIN_BOUNDARY_OUTPUT_DIR,
)

from app.api.hazard_risk_catalog_shared import LAYER_BY_VALUE
from app.api.hazard_risk_maps import find_map_record, load_display_array

router = APIRouter(prefix="/api/hazard-risk", tags=["Ethiopia Hazard/Risk Layers"])

ADMIN_GEOJSON_PATHS = {
    "admin1": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin1.json",
    "admin2": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin2.json",
    "admin3": ADMIN_BOUNDARY_OUTPUT_DIR / "eth_admin3.json",
}

# population_dominant_code is deliberately excluded from ranking: it's a
# nominal code (0=Insignificant, 1=Drought-dominated, 2=Wet-dominated,
# 3=Mixed/compound), not an ordinal scale. Averaging/sorting districts by it
# would produce a meaningless order -- a 100%-drought district (code 1) would
# rank below a 100%-wet district (code 2) purely because of encoding order,
# not actual severity. It's still a fine map layer (see hazard_risk_maps.py),
# just not a ranking metric.
RANKING_EXCLUDED_LAYERS = {"population_dominant_code"}

RANKING_LAYER_VALUES = [
    value for value in LAYER_BY_VALUE if value not in RANKING_EXCLUDED_LAYERS
]


def _area_label(props: Dict[str, Any], admin_level: str) -> str:
    if admin_level == "admin3":
        return props.get("woreda") or props.get("name") or "Unknown Woreda"
    if admin_level == "admin2":
        return props.get("zone") or props.get("name") or "Unknown Zone"
    return props.get("region") or props.get("name") or "Unknown Region"


@lru_cache(maxsize=8)
def load_admin_features(admin_level: str) -> Tuple[Dict[str, Any], ...]:
    path = ADMIN_GEOJSON_PATHS.get(admin_level)
    if not path or not Path(path).exists():
        return tuple()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(feature for feature in data.get("features", []) if feature.get("geometry"))


def filter_admin_features(
    features: Tuple[Dict[str, Any], ...], region_id: str = "", zone_id: str = ""
) -> List[Dict[str, Any]]:
    filtered = []
    for feature in features:
        props = feature.get("properties", {})
        if region_id and props.get("region_id") != region_id:
            continue
        if zone_id and props.get("zone_id") != zone_id:
            continue
        filtered.append(feature)
    return filtered


def build_district_label_array(features: List[Dict[str, Any]], out_shape, transform):
    """Rasterize every district polygon into ONE integer label array (1-indexed; 0 = no district).

    Districts are rasterized in a single pass (rather than one rasterize call
    per district) since scipy.ndimage's labeled reductions below can then
    compute every district's zonal stats for a given layer in one vectorized
    call -- important because admin3 alone has ~1,148 woredas, and this runs
    once per requested metric, on demand.
    """
    from rasterio.features import rasterize

    shapes = [
        (feature["geometry"], index + 1) for index, feature in enumerate(features)
    ]
    if not shapes:
        return None

    return rasterize(
        shapes,
        out_shape=out_shape,
        transform=transform,
        all_touched=True,
        fill=0,
        dtype="int32",
    )


def zonal_stats_for_all_districts(
    arr, label_array, district_ids: List[int], threshold: float
) -> Dict[int, Dict[str, float]]:
    """Per-district {mean, max, valid_count, above_threshold_fraction} for one layer's array.

    all_touched rasterization means a district can claim a raster cell that's
    NaN in this particular layer (e.g. outside Ethiopia's real border, per
    clip_array_to_country) -- those cells are excluded from labels here so
    they don't pull a district's mean/max toward NaN.
    """
    import numpy as np
    from scipy import ndimage

    valid = label_array is not None and district_ids
    if not valid:
        return {}

    finite_mask = np.isfinite(arr)
    labels_valid_only = np.where(finite_mask, label_array, 0)

    # Restrict to IDs that actually claimed >=1 valid pixel -- passing an ID
    # with zero matching pixels into ndimage's labeled reductions divides by
    # a zero count (a real, if rare, possibility: a degenerate/zero-area
    # geometry, or a district whose only overlapping cells are all NaN in
    # this particular layer), which is already handled below (that ID simply
    # never appears in `results`) but emits a noisy RuntimeWarning otherwise.
    present_id_set = set(np.unique(labels_valid_only).tolist()) - {0}
    present_ids = [district_id for district_id in district_ids if district_id in present_id_set]
    if not present_ids:
        return {}

    means = ndimage.mean(arr, labels=labels_valid_only, index=present_ids)
    maxes = ndimage.maximum(arr, labels=labels_valid_only, index=present_ids)
    counts = ndimage.sum(finite_mask.astype("float32"), labels=labels_valid_only, index=present_ids)
    above = (arr >= threshold).astype("float32")
    above_fraction = ndimage.mean(above, labels=labels_valid_only, index=present_ids)

    results: Dict[int, Dict[str, float]] = {}
    for district_id, mean_value, max_value, count_value, fraction_value in zip(
        present_ids, means, maxes, counts, above_fraction
    ):
        if not count_value or count_value <= 0:
            continue
        results[district_id] = {
            "mean": float(mean_value),
            "max": float(max_value),
            "valid_count": int(count_value),
            "above_threshold_fraction": float(fraction_value) if fraction_value == fraction_value else 0.0,
        }
    return results


def default_threshold_for(layer_value: str) -> float:
    definition = LAYER_BY_VALUE[layer_value]
    vmin, vmax = float(definition["vmin"]), float(definition["vmax"])
    return round(vmin + 0.6 * (vmax - vmin), 3)


def compute_district_ranking(
    metrics: List[str],
    rank_by: str,
    period: str,
    admin_level: str,
    selection_mode: str,
    top_n: int,
    threshold: float,
    region_id: str,
    zone_id: str,
) -> Dict[str, Any]:
    ordered_metrics = list(dict.fromkeys([rank_by] + metrics))

    for metric in ordered_metrics:
        if metric not in LAYER_BY_VALUE:
            raise HTTPException(status_code=400, detail=f"Unknown hazard/risk layer: {metric}")
        if metric in RANKING_EXCLUDED_LAYERS:
            raise HTTPException(
                status_code=400,
                detail=f"'{metric}' is a nominal code, not a valid ranking metric.",
            )

    features = filter_admin_features(
        load_admin_features(admin_level), region_id=region_id, zone_id=zone_id
    )
    if not features:
        return {
            "rank_by": rank_by,
            "period": period,
            "admin_level": admin_level,
            "selection_mode": selection_mode,
            "threshold": threshold,
            "ranking": [],
        }

    district_ids = list(range(1, len(features) + 1))
    label_array = None
    metric_stats: Dict[str, Dict[int, Dict[str, float]]] = {}

    for metric in ordered_metrics:
        record = find_map_record(metric, period)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"No hazard/risk map found for layer={metric} period={period}.",
            )
        arr, transform, _bounds = load_display_array(record)

        if label_array is None:
            label_array = build_district_label_array(features, arr.shape, transform)

        metric_threshold = threshold if metric == rank_by else default_threshold_for(metric)
        metric_stats[metric] = zonal_stats_for_all_districts(
            arr, label_array, district_ids, metric_threshold
        )

    items = []
    rank_definition = LAYER_BY_VALUE[rank_by]
    layer_span = max(float(rank_definition["vmax"]) - float(rank_definition["vmin"]), 1e-9)
    layer_vmin = float(rank_definition["vmin"])

    for feature, district_id in zip(features, district_ids):
        rank_stats = metric_stats[rank_by].get(district_id)
        if not rank_stats:
            continue

        props = feature.get("properties", {})
        metrics_out = {
            metric: stats[district_id]["mean"]
            for metric, stats in metric_stats.items()
            if district_id in stats
        }

        priority_score = (
            0.50 * (rank_stats["mean"] - layer_vmin) / layer_span
            + 0.25 * (rank_stats["max"] - layer_vmin) / layer_span
            + 0.25 * rank_stats["above_threshold_fraction"]
        )

        items.append(
            {
                "admin_level": admin_level,
                "area_name": _area_label(props, admin_level),
                "region": props.get("region", ""),
                "zone": props.get("zone", ""),
                "woreda": props.get("woreda", ""),
                "region_id": props.get("region_id", ""),
                "zone_id": props.get("zone_id", ""),
                "woreda_id": props.get("woreda_id", ""),
                "metrics": metrics_out,
                "rank_value": rank_stats["mean"],
                "priority_score": round(max(0.0, min(1.0, priority_score)), 3),
                "boundary_feature": {
                    "type": "Feature",
                    "id": feature.get("id") or props.get("id"),
                    "geometry": feature.get("geometry"),
                    "properties": {
                        **props,
                        "admin_level": admin_level,
                        "name": _area_label(props, admin_level),
                    },
                },
            }
        )

    items.sort(key=lambda item: item["rank_value"], reverse=True)

    if selection_mode == "threshold":
        selected = [item for item in items if item["rank_value"] >= threshold]
    else:
        selected = items[:top_n]

    for index, item in enumerate(selected, start=1):
        item["rank"] = index

    return {
        "rank_by": rank_by,
        "period": period,
        "admin_level": admin_level,
        "selection_mode": selection_mode,
        "threshold": threshold,
        "count": len(selected),
        "ranking": selected,
    }


@router.get("/ranking")
async def get_hazard_risk_ranking(
    rank_by: str = Query(..., description="Layer value to sort districts by, e.g. 'population_r_drought'."),
    metrics: str = Query(
        "",
        description="Comma-separated layer values to also compute per district (for extra table columns). rank_by is always included.",
    ),
    period: str = Query("JJAS"),
    admin_level: str = Query("admin3"),
    selection_mode: str = Query("top"),
    top_n: int = Query(5),
    threshold: Optional[float] = Query(None),
    region_id: str = Query(""),
    zone_id: str = Query(""),
) -> Dict[str, Any]:
    if admin_level not in {"admin1", "admin2", "admin3"}:
        admin_level = "admin3"
    if selection_mode not in {"top", "threshold"}:
        selection_mode = "top"
    top_n = max(3, min(int(top_n), 25))

    metric_list = [item.strip() for item in metrics.split(",") if item.strip()]

    if rank_by not in LAYER_BY_VALUE:
        raise HTTPException(status_code=400, detail=f"Unknown hazard/risk layer: {rank_by}")

    resolved_threshold = (
        float(threshold) if threshold is not None else default_threshold_for(rank_by)
    )

    return compute_district_ranking(
        metrics=metric_list,
        rank_by=rank_by,
        period=period,
        admin_level=admin_level,
        selection_mode=selection_mode,
        top_n=top_n,
        threshold=resolved_threshold,
        region_id=region_id,
        zone_id=zone_id,
    )


@router.get("/ranking-options")
async def get_hazard_risk_ranking_options() -> Dict[str, Any]:
    return {
        "ranking_layers": [
            {**definition, "default_threshold": default_threshold_for(value)}
            for value, definition in LAYER_BY_VALUE.items()
            if value not in RANKING_EXCLUDED_LAYERS
        ],
        "excluded_layers": sorted(RANKING_EXCLUDED_LAYERS),
    }
