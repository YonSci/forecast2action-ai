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
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from app.data_pipeline.ethiopia_admin_boundary_pipeline import (
    OUTPUT_DIR as ADMIN_BOUNDARY_OUTPUT_DIR,
)

from app.api.hazard_risk_catalog_shared import LAYER_BY_VALUE, PROJECT_ROOT
from app.api.hazard_risk_maps import (
    find_map_record,
    get_map_statistics_cached,
    load_display_array,
)

router = APIRouter(prefix="/api/hazard-risk", tags=["Ethiopia Hazard/Risk Layers"])

# Real WorldPop Ethiopia 2020 1km population-count raster (the same source
# app/data_pipeline/exposure_data_pipeline.py uses) -- much finer resolution
# than the 0.25-degree Hazard/Risk grid, so "population exposed" is computed
# by resampling the ranked metric's own above-threshold mask onto this raster
# (see population_exposed_stats_for_all_districts) rather than the other way
# around, to avoid losing the population raster's real spatial detail.
POPULATION_RAW_PATH = PROJECT_ROOT / "data" / "raw" / "exposure" / "eth_population_2020_1km.tif"

KM_PER_DEGREE_LAT = 110.574

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
#
# population_normalized itself stays a valid ranking metric (ranking by "who
# has the most exposed people" is genuinely useful) -- the earlier confusion
# between it and the real population_exposed count is fixed on the frontend
# instead, by dropping the raw normalized Exposure column from the table
# (see TopInterventionAreas.jsx) rather than removing the ranking option.
#
# population_risk_class IS excluded (unlike population_normalized above):
# its hazard_type is "dominant" (drought OR wet, whichever actually
# dominates per area), so ranking by it left the Hazard/Probability/
# Vulnerability columns locked to one arbitrary hazard type that often had
# nothing to do with why a given area's class was high. Still a fine map
# layer (see hazard_risk_maps.py), just not a ranking metric.
RANKING_EXCLUDED_LAYERS = {"population_dominant_code", "population_risk_class"}

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
    arr, label_array, district_ids: List[int], threshold: float, area_array=None
) -> Dict[int, Dict[str, float]]:
    """Per-district {mean, max, valid_count, above_threshold_fraction} for one layer's array.

    all_touched rasterization means a district can claim a raster cell that's
    NaN in this particular layer (e.g. outside Ethiopia's real border, per
    clip_array_to_country) -- those cells are excluded from labels here so
    they don't pull a district's mean/max toward NaN.

    When `area_array` (real ground km^2 per pixel, see pixel_area_km2_array)
    is passed, also returns real-unit `area_total_km2`/`above_threshold_area_km2`
    -- an area-weighted alternative to `above_threshold_fraction` (a plain
    pixel-count fraction), since Ethiopia's 3-15N span means cells near the
    north edge cover meaningfully less real ground than cells near the south
    edge at this grid's coarse (0.25-degree) resolution.
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

    area_totals = area_above = None
    if area_array is not None:
        area_totals = ndimage.sum(area_array, labels=labels_valid_only, index=present_ids)
        area_above = ndimage.sum(area_array * above, labels=labels_valid_only, index=present_ids)

    results: Dict[int, Dict[str, float]] = {}
    for position, (district_id, mean_value, max_value, count_value, fraction_value) in enumerate(
        zip(present_ids, means, maxes, counts, above_fraction)
    ):
        if not count_value or count_value <= 0:
            continue
        entry = {
            "mean": float(mean_value),
            "max": float(max_value),
            "valid_count": int(count_value),
            "above_threshold_fraction": float(fraction_value) if fraction_value == fraction_value else 0.0,
        }
        if area_totals is not None:
            entry["area_total_km2"] = float(area_totals[position])
            entry["above_threshold_area_km2"] = float(area_above[position])
        results[district_id] = entry
    return results


def pixel_area_km2_array(transform, shape: Tuple[int, int]):
    """Per-row real ground area (km^2) for a north-up EPSG:4326 grid.

    Longitude degrees compress with latitude (cos(lat)) while latitude
    degrees don't, so cell area only varies row-by-row (by latitude), not
    column-by-column -- computed once per row and broadcast across columns.
    """
    import numpy as np

    rows, cols = shape
    row_indices = np.arange(rows)
    lat_centers = transform.f + (row_indices + 0.5) * transform.e

    pixel_height_km = abs(transform.e) * KM_PER_DEGREE_LAT
    pixel_width_km = transform.a * KM_PER_DEGREE_LAT * np.cos(np.radians(lat_centers))
    row_area_km2 = pixel_height_km * pixel_width_km

    return np.repeat(row_area_km2[:, None], cols, axis=1)


@lru_cache(maxsize=1)
def load_population_raw_array():
    """Real WorldPop Ethiopia 2020 population count, 1km -- not the coarse
    0.25-degree 'population_normalized' index used elsewhere in this catalog.
    """
    import numpy as np
    import rasterio

    with rasterio.open(POPULATION_RAW_PATH) as src:
        arr = src.read(1, masked=True).astype("float64")
        arr = arr.filled(0.0)
        arr[arr < 0] = 0.0
        transform = src.transform
        shape = arr.shape
    return arr, transform, shape


def resample_mask_nearest(mask, src_transform, src_crs, dst_transform, dst_shape, dst_crs):
    """Nearest-neighbor-resample a boolean/float mask onto a different EPSG:4326 grid."""
    import numpy as np
    from rasterio.warp import Resampling, reproject

    destination = np.zeros(dst_shape, dtype="float32")
    reproject(
        source=mask.astype("float32"),
        destination=destination,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
    )
    return destination > 0.5


def population_stats_for_all_districts(
    features: List[Dict[str, Any]],
    admin_level: str,
    above_threshold_mask,
    hazard_transform,
) -> Dict[int, Dict[str, float]]:
    """Per-district {population_total, population_exposed} using the real WorldPop raster.

    `above_threshold_mask` is the ranked metric's own above-threshold boolean
    array on the (coarse) Hazard/Risk grid -- resampled onto the population
    raster's much finer grid so "population exposed" reflects real population
    distribution within the ranked metric's affected area, not a uniform
    per-pixel assumption.
    """
    import numpy as np
    from scipy import ndimage

    population_arr, population_transform, population_shape = load_population_raw_array()

    label_array = build_district_label_array(features, population_shape, population_transform)
    if label_array is None:
        return {}

    district_ids = list(range(1, len(features) + 1))
    present_id_set = set(np.unique(label_array).tolist()) - {0}
    present_ids = [district_id for district_id in district_ids if district_id in present_id_set]
    if not present_ids:
        return {}

    exposed_mask = resample_mask_nearest(
        above_threshold_mask,
        hazard_transform,
        "EPSG:4326",
        population_transform,
        population_shape,
        "EPSG:4326",
    )

    totals = ndimage.sum(population_arr, labels=label_array, index=present_ids)
    exposed = ndimage.sum(
        population_arr * exposed_mask, labels=label_array, index=present_ids
    )

    results: Dict[int, Dict[str, float]] = {}
    for district_id, total_value, exposed_value in zip(present_ids, totals, exposed):
        results[district_id] = {
            "population_total": float(total_value),
            "population_exposed": float(exposed_value),
        }
    return results


def default_threshold_for(layer_value: str, period: str = "jjas") -> float:
    """60% of the way from vmin to the metric's REAL observed ceiling.

    Not 60% of the fixed catalog vmax -- for population_r_drought/
    population_r_wet (0-100 "score" units), real data never gets anywhere
    near the catalog vmax (confirmed: nationwide max drought/wet risk score
    is only ~54/43 out of 100). A default threshold computed against the
    fixed vmax is literally unreachable for these layers -- every pixel
    always falls below it -- which silently zeroes out
    above_threshold_fraction (25% of priority_score) AND the real
    Population Exposed / Area Extent columns for every area, even the
    single most severe one in the country. See the mean/max ceiling fix in
    compute_district_ranking for the same root cause on priority_score's
    normalization.
    """
    definition = LAYER_BY_VALUE[layer_value]
    vmin = float(definition["vmin"])
    catalog_vmax = float(definition["vmax"])

    vmax = catalog_vmax
    record = find_map_record(layer_value, period)
    if record:
        try:
            observed_max = float(get_map_statistics_cached(record["id"])["max"])
            vmax = max(observed_max, vmin + 1e-9)
        except (KeyError, TypeError):
            vmax = catalog_vmax

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
    # cropland_total_normalized (+ livestock/built-up/roads exposure) is
    # always computed (regardless of what the caller asked for in `metrics`)
    # so every ranked item can carry these real extent percentages alongside
    # whatever's being ranked by -- same reasoning/pattern as cropland,
    # extended for SelectedAreaAdvisory.jsx's "Impact-based risk evidence"
    # cards, which previously had no real livestock/built-up/roads figures.
    ALWAYS_COMPUTED_EXPOSURE_METRICS = [
        "cropland_total_normalized",
        "livestock_cattle_normalized",
        "built_up_normalized",
        "roads_normalized",
    ]
    ordered_metrics = list(
        dict.fromkeys([rank_by, *ALWAYS_COMPUTED_EXPOSURE_METRICS] + metrics)
    )

    for metric in ordered_metrics:
        if metric not in LAYER_BY_VALUE:
            raise HTTPException(status_code=400, detail=f"Unknown hazard/risk layer: {metric}")
        if metric in RANKING_EXCLUDED_LAYERS:
            raise HTTPException(
                status_code=400,
                detail=f"'{metric}' is excluded from ranking (see RANKING_EXCLUDED_LAYERS).",
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
    area_array = None
    rank_by_arr = None
    rank_by_transform = None
    rank_by_record = None
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
            area_array = pixel_area_km2_array(transform, arr.shape)

        if metric == rank_by:
            rank_by_arr = arr
            rank_by_transform = transform
            rank_by_record = record

        metric_threshold = (
            threshold if metric == rank_by else default_threshold_for(metric, period)
        )
        metric_stats[metric] = zonal_stats_for_all_districts(
            arr, label_array, district_ids, metric_threshold, area_array=area_array
        )

    # Real-people/real-ground-area context for whichever metric is being
    # ranked by -- see population_stats_for_all_districts's docstring for why
    # this needs its own (much finer) raster and resampled mask rather than
    # reusing the coarse Hazard/Risk grid's own pixel counts.
    population_stats: Dict[int, Dict[str, float]] = {}
    if rank_by_arr is not None and POPULATION_RAW_PATH.exists():
        above_threshold_mask = rank_by_arr >= threshold
        population_stats = population_stats_for_all_districts(
            features, admin_level, above_threshold_mask, rank_by_transform
        )

    items = []
    rank_definition = LAYER_BY_VALUE[rank_by]
    layer_vmin = float(rank_definition["vmin"])

    # priority_score's mean/max terms normalize against the metric's REAL
    # observed nationwide ceiling, not its fixed catalog vmax -- for a 0-1
    # index like h_dry_mean the two are close (real data reaches ~0.9-0.95),
    # but for the 0-100 Risk score (100 * P * Severity * Exposure *
    # Vulnerability, a product of several 0-1 factors) real values never get
    # near the theoretical 100: the worst observed drought-risk woreda in all
    # of Ethiopia only reaches ~54. Normalizing against a fixed vmax=100
    # would cap every possible priority_score at ~0.40 for that metric,
    # making the Trigger (>=0.8) and Warning (>=0.6) alert levels
    # mathematically unreachable no matter how severe conditions get. Using
    # the metric's own real ceiling (already computed and cached by
    # get_map_statistics_cached for the map legend/statistics endpoints)
    # keeps every rank_by metric's priority_score comparable against the
    # same 0-1 Trigger/Warning/Watch thresholds. Catalog vmax stays the
    # fallback for the rare case statistics can't be computed (e.g. an
    # entirely NaN raster).
    catalog_vmax = float(rank_definition["vmax"])
    try:
        observed_max = float(get_map_statistics_cached(rank_by_record["id"])["max"])
    except (KeyError, TypeError):
        observed_max = catalog_vmax
    layer_vmax = max(observed_max, layer_vmin + 1e-9)
    layer_span = max(layer_vmax - layer_vmin, 1e-9)

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

        pop_stats = population_stats.get(district_id)
        population_total = pop_stats["population_total"] if pop_stats else None
        population_exposed = pop_stats["population_exposed"] if pop_stats else None
        population_exposed_pct = (
            round(population_exposed / population_total * 100, 1)
            if population_total
            else None
        )

        area_total_km2 = rank_stats.get("area_total_km2")
        area_extent_km2 = rank_stats.get("above_threshold_area_km2")
        area_extent_pct = (
            round(area_extent_km2 / area_total_km2 * 100, 1)
            if area_total_km2
            else None
        )

        cropland_stats = metric_stats.get("cropland_total_normalized", {}).get(district_id)
        cropland_extent_pct = (
            round(cropland_stats["above_threshold_fraction"] * 100, 1)
            if cropland_stats
            else None
        )

        livestock_stats = metric_stats.get("livestock_cattle_normalized", {}).get(district_id)
        livestock_extent_pct = (
            round(livestock_stats["above_threshold_fraction"] * 100, 1)
            if livestock_stats
            else None
        )

        built_up_stats = metric_stats.get("built_up_normalized", {}).get(district_id)
        built_up_extent_pct = (
            round(built_up_stats["above_threshold_fraction"] * 100, 1)
            if built_up_stats
            else None
        )

        roads_stats = metric_stats.get("roads_normalized", {}).get(district_id)
        roads_extent_pct = (
            round(roads_stats["above_threshold_fraction"] * 100, 1)
            if roads_stats
            else None
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
                "population_total": round(population_total) if population_total is not None else None,
                "population_exposed": round(population_exposed) if population_exposed is not None else None,
                "population_exposed_pct": population_exposed_pct,
                "area_total_km2": round(area_total_km2, 1) if area_total_km2 is not None else None,
                "area_extent_km2": round(area_extent_km2, 1) if area_extent_km2 is not None else None,
                "area_extent_pct": area_extent_pct,
                "cropland_extent_pct": cropland_extent_pct,
                "livestock_extent_pct": livestock_extent_pct,
                "built_up_extent_pct": built_up_extent_pct,
                "roads_extent_pct": roads_extent_pct,
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
        float(threshold) if threshold is not None else default_threshold_for(rank_by, period)
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
