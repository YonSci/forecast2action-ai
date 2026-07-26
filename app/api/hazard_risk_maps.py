"""Ethiopia Hazard/Risk raster map service.

Serves the Hazard/Probability_Severity/Exposure/Vulnerability/Risk GeoTIFFs
under data/maps/ as PNG map overlays, following the same
ImageOverlay-per-map architecture as app/api/seasonal_raster_maps.py (see
that module's get_full_image docstring for why: these source grids are tiny,
so a single full-extent image avoids the rendering seams an XYZ tile
pyramid would introduce, and the frontend already standardized on
ImageOverlay for this reason).

All 58 source files were verified (by direct inspection) to already share
one identical grid -- EPSG:4326, north-up, no CRS/flip normalization needed
-- so this module reuses seasonal_raster_maps.py's generic array/rendering
helpers directly instead of re-deriving them, and skips the NetCDF/CSV
conversion and XYZ tile machinery that module needs for its more varied
climate-indicator sources.
"""

import math
import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api.hazard_risk_catalog_shared import (
    CATEGORIES,
    DOMINANT_HAZARD_CODE_BANDS,
    DOMINANT_HAZARD_CODE_BY_CODE,
    LAYER_DEFINITIONS,
    LAYER_BY_VALUE,
    PERIOD_BY_VALUE,
    PERIODS,
    PROJECT_ROOT,
    RISK_CLASS_BANDS,
    RISK_CLASS_BY_CODE,
    STATIC_PERIOD,
    make_id,
    parse_hazard_risk_filename,
    resolve_within,
    safe_rel_path,
)
from app.api.seasonal_raster_maps import (
    DEFAULT_BOUNDS,
    FULL_IMAGE_MIN_LONG_SIDE,
    apply_basic_nodata_mask,
    calculate_statistics_from_array,
    clean_array_for_display,
    clip_array_to_country,
    format_value,
    get_matplotlib_cmap,
    get_raster_bounds,
    hex_from_rgba,
    normalize_geotiff_for_tiles,
    rasterize_country_mask,
    remap_rows_equirect_to_mercator,
    render_array_to_rgba,
    scaled_transform,
    upsample_value_array,
)

router = APIRouter(prefix="/api/hazard-risk", tags=["Ethiopia Hazard/Risk Layers"])

MAPS_ROOT = Path(os.getenv("HAZARD_RISK_ROOT", PROJECT_ROOT / "data" / "maps")).resolve()

# Layers with a fixed discrete color per integer code, rendered/legended via
# render_categorical_rgba below instead of a continuous colormap.
CATEGORICAL_BANDS_BY_LAYER = {
    "population_risk_class": RISK_CLASS_BY_CODE,
    "population_dominant_code": DOMINANT_HAZARD_CODE_BY_CODE,
}
FOLDER_NAMES = ["Hazard", "Probability_Severity", "Exposure", "Vulnerability", "Risk"]


def resolve_project_path(path_value: Any) -> Optional[Path]:
    return resolve_within(path_value, [MAPS_ROOT])


def period_label(period_value: str) -> str:
    if period_value == STATIC_PERIOD:
        return "All periods"
    return PERIOD_BY_VALUE.get(period_value.lower(), {}).get("label", period_value)


def scan_hazard_risk_files() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for folder_name in FOLDER_NAMES:
        folder = MAPS_ROOT / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.tif")):
            parsed = parse_hazard_risk_filename(path.stem)
            if not parsed:
                continue
            definition = LAYER_BY_VALUE[parsed["layer"]]
            period_value = parsed["period"]
            map_id = make_id(definition["category"], period_value, parsed["layer"])
            records.append({
                "id": map_id,
                "category": definition["category"],
                "layer": parsed["layer"],
                "layer_label": definition["label"],
                "hazard_type": definition["hazard_type"],
                "period": period_value,
                "period_label": period_label(period_value),
                "is_static": period_value == STATIC_PERIOD,
                "is_categorical": definition["is_categorical"],
                "units": definition["units"],
                "init_date": parsed["init_date"],
                "source_path": safe_rel_path(path),
                "bounds": DEFAULT_BOUNDS,
                "title": f"{definition['label']} · {period_label(period_value)}",
            })
    return records


@lru_cache(maxsize=1)
def load_catalog_cached() -> Tuple[Tuple[str, Dict[str, Any]], ...]:
    return tuple((record["id"], record) for record in scan_hazard_risk_files())


def catalog_by_id() -> Dict[str, Dict[str, Any]]:
    return dict(load_catalog_cached())


def list_catalog() -> List[Dict[str, Any]]:
    return sorted(catalog_by_id().values(), key=lambda r: (r["category"], str(r["period"]), r["layer"]))


def find_map_record(layer: str, period: str) -> Optional[Dict[str, Any]]:
    layer_lower = str(layer).lower()
    period_lower = str(period).lower()
    for record in list_catalog():
        if record["layer"].lower() != layer_lower:
            continue
        # Exposure/Vulnerability ship one static file that answers for every
        # period, so period is ignored once the layer itself matches.
        if record["is_static"] or str(record["period"]).lower() == period_lower:
            return record
    return None


def require_map(map_id: str) -> Dict[str, Any]:
    record = catalog_by_id().get(map_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Hazard/Risk map '{map_id}' was not found.")
    return record


def ensure_geotiff(record: Dict[str, Any]) -> Path:
    source_path = resolve_project_path(record.get("source_path"))
    if not source_path or not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Source raster file not found for map {record.get('id')}: {record.get('source_path')}")
    # Every source file here already verified as north-up EPSG:4326 with a
    # valid CRS, so this hits normalize_geotiff_for_tiles's early return
    # (source_path unchanged) in practice -- kept for defensive parity with
    # seasonal_raster_maps.py in case a future file doesn't conform.
    return normalize_geotiff_for_tiles(record, source_path)


def load_display_array(record: Dict[str, Any]) -> Tuple[Any, Any, Dict[str, float]]:
    import numpy as np
    import rasterio

    path = ensure_geotiff(record)
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).astype("float32")
        arr = arr.filled(np.nan)
        transform = src.transform
        nodata = src.nodata

    bounds = get_raster_bounds(path)
    if record["is_categorical"]:
        # clean_array_for_display's auto_mask_fill_stripes heuristic blanks
        # rows/columns that are >=92% exact zero, assuming that means an
        # export fill artifact -- true for continuous climate variables, but
        # 0 is a real, legitimate class here (risk_class's "Very low"), and
        # an entire row can genuinely be all class 0. Only the real-nodata
        # mask applies to categorical layers; the zero-stripe heuristic is
        # skipped entirely.
        arr = apply_basic_nodata_mask(arr, source_nodata=nodata)
    else:
        arr = clean_array_for_display(arr, source_nodata=nodata)
    arr = clip_array_to_country(arr, transform)
    return arr, transform, bounds


@lru_cache(maxsize=256)
def get_map_statistics_cached(map_id: str) -> Dict[str, Any]:
    record = require_map(map_id)
    arr, _transform, _bounds = load_display_array(record)
    return calculate_statistics_from_array(arr)


def get_render_config(record: Dict[str, Any]) -> Dict[str, Any]:
    definition = LAYER_BY_VALUE[record["layer"]]
    if record["layer"] in CATEGORICAL_BANDS_BY_LAYER:
        return {"cmap": f"categorical_{record['layer']}", "vmin": definition["vmin"], "vmax": definition["vmax"], "low_label": definition["low_label"], "high_label": definition["high_label"]}
    return {
        "cmap": definition["cmap"],
        "vmin": definition["vmin"],
        "vmax": definition["vmax"],
        "low_label": definition["low_label"],
        "high_label": definition["high_label"],
    }


def build_legend(record: Dict[str, Any]) -> Dict[str, Any]:
    definition = LAYER_BY_VALUE[record["layer"]]

    if record["layer"] == "population_risk_class":
        return {
            "title": "Risk Class",
            "units": "class",
            "type": "categorical",
            "cmap": "categorical_population_risk_class",
            "items": [
                {"value": band["code"], "label": band["label"], "color": band["color"], "range": list(band["range"])}
                for band in RISK_CLASS_BANDS
            ],
        }

    if record["layer"] == "population_dominant_code":
        return {
            "title": "Dominant Hazard Code",
            "units": "dominant_code",
            "type": "categorical",
            "cmap": "categorical_population_dominant_code",
            "items": [
                {"value": band["code"], "label": band["label"], "color": band["color"]}
                for band in DOMINANT_HAZARD_CODE_BANDS
            ],
        }

    config = get_render_config(record)
    vmin, vmax = config["vmin"], config["vmax"]
    steps = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    values = [vmin + (vmax - vmin) * frac for frac in steps]
    colormap = get_matplotlib_cmap(config["cmap"])

    if colormap is not None:
        items = [{"value": v, "label": f"{v:.2f}", "color": hex_from_rgba(colormap(i / (len(steps) - 1)))} for i, v in enumerate(values)]
    else:
        fallback_colors = ["#b42318", "#f79009", "#fec84b", "#12b76a", "#0e9384", "#1570ef"]
        items = [{"value": v, "label": f"{v:.2f}", "color": fallback_colors[i]} for i, v in enumerate(values)]

    return {
        "title": definition["label"],
        "units": definition["units"],
        "type": "continuous",
        "vmin": vmin,
        "vmax": vmax,
        "cmap": config["cmap"],
        "low_label": config["low_label"],
        "high_label": config["high_label"],
        "items": items,
    }


def upsample_value_array_nearest(arr: Any, scale_factor: float) -> Tuple[Any, Any]:
    """Nearest-neighbor NaN-safe upsample, for categorical (class-code) arrays.

    upsample_value_array (imported) uses a cubic spline, which would invent
    fictitious in-between class values at edges between two classes (e.g.
    blending class 0 and class 2 into a fake "class 1" pixel) -- nearest
    neighbor preserves exact integer codes everywhere.
    """
    import numpy as np
    from scipy import ndimage

    valid = np.isfinite(arr)
    if not valid.any():
        empty_shape = (round(arr.shape[0] * scale_factor), round(arr.shape[1] * scale_factor))
        return np.full(empty_shape, np.nan, dtype="float32"), np.zeros(empty_shape, dtype="float32")

    filled = arr.astype("float32", copy=True)
    if not valid.all():
        _, indices = ndimage.distance_transform_edt(~valid, return_distances=True, return_indices=True)
        filled = filled[tuple(indices)]

    upsampled_values = ndimage.zoom(filled, scale_factor, order=0, mode="nearest")
    upsampled_valid = ndimage.zoom(valid.astype("float32"), scale_factor, order=0, mode="nearest")
    return upsampled_values.astype("float32"), upsampled_valid


def render_categorical_rgba(band: Any, valid_mask: Any, bands_by_code: Dict[int, Dict[str, Any]]):
    import numpy as np

    rgba = np.zeros((band.shape[0], band.shape[1], 4), dtype="uint8")
    codes = np.rint(np.nan_to_num(band, nan=-1.0)).astype("int32")
    for code, class_meta in bands_by_code.items():
        color = class_meta["color"]
        r, g, b = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        sel = valid_mask & (codes == code)
        rgba[sel] = (r, g, b, 255)
    return rgba


def format_hazard_risk_value(value: Optional[float], record: Dict[str, Any]) -> str:
    """Format a raw cell value for display, using this module's own units vocabulary.

    seasonal_raster_maps.py's imported format_value only special-cases
    "probability" -- units like "score" or "class" are specific to this
    catalog and would otherwise render as e.g. "0.82 score".
    """
    if value is None or not math.isfinite(float(value)):
        return "No data"

    units = record.get("units", "")
    if units == "score":
        return f"{float(value):.1f} / 100"
    if units == "class":
        band = RISK_CLASS_BY_CODE.get(int(round(float(value))))
        return band["label"] if band else f"{float(value):.0f}"
    if units == "dominant_code":
        band = DOMINANT_HAZARD_CODE_BY_CODE.get(int(round(float(value))))
        return band["label"] if band else f"{float(value):.0f}"
    return format_value(value, units if units not in {"index", "normalized"} else "")


def public_map_record(record: Dict[str, Any], include_statistics: bool = True) -> Dict[str, Any]:
    output = dict(record)
    map_id = record["id"]
    output["image_url"] = f"/api/hazard-risk/image/{map_id}.png"
    output["grid_url"] = f"/api/hazard-risk/grid/{map_id}"
    output["value_url"] = f"/api/hazard-risk/value/{map_id}?lat={{lat}}&lon={{lon}}"
    output["statistics_url"] = f"/api/hazard-risk/statistics/{map_id}"
    try:
        path = ensure_geotiff(record)
        output["bounds"] = get_raster_bounds(path)
        if include_statistics:
            output["statistics"] = get_map_statistics_cached(map_id)
        output["legend"] = build_legend(record)
        output["rendering"] = get_render_config(record)
    except HTTPException as exc:
        output["availability_error"] = exc.detail
        output["legend"] = build_legend(record)
    return output


@router.get("/health")
async def get_hazard_risk_health() -> Dict[str, Any]:
    catalog = list_catalog()
    return {
        "status": "ok",
        "router_registered": True,
        "maps_root": safe_rel_path(MAPS_ROOT),
        "maps_root_absolute": str(MAPS_ROOT),
        "discovered_map_count": len(catalog),
        "available": [
            {"category": r["category"], "layer": r["layer"], "period": r["period"]}
            for r in catalog
        ],
        "directories": {
            name: {
                "path": safe_rel_path(MAPS_ROOT / name),
                "exists": (MAPS_ROOT / name).exists(),
            }
            for name in FOLDER_NAMES
        },
    }


@router.get("/options")
async def get_hazard_risk_options() -> Dict[str, Any]:
    return {
        "categories": CATEGORIES,
        "periods": PERIODS,
        "layers": LAYER_DEFINITIONS,
    }


@router.get("/catalog")
async def get_hazard_risk_catalog(include_statistics: bool = Query(False)) -> Dict[str, Any]:
    maps = [public_map_record(item, include_statistics=include_statistics) for item in list_catalog()]
    return {"maps": maps, "count": len(maps)}


@router.get("/map")
async def get_selected_hazard_risk_map(
    layer: str = Query(..., description="Layer token, e.g. 'population_r_drought', 'h_dry_mean', 'v_wet'."),
    period: str = Query("JJAS"),
) -> Dict[str, Any]:
    record = find_map_record(layer, period)
    if not record:
        return {"map": None, "message": f"No hazard/risk map found for layer={layer} period={period}."}
    return {"map": public_map_record(record, include_statistics=True)}


@router.get("/statistics/{map_id}")
async def get_hazard_risk_statistics(map_id: str) -> Dict[str, Any]:
    record = require_map(map_id)
    return {"map_id": map_id, "statistics": get_map_statistics_cached(map_id), "units": record.get("units", "")}


@router.get("/value/{map_id}")
async def get_hazard_risk_value_at_point(
    map_id: str,
    lat: float = Query(...),
    lon: float = Query(...),
) -> Dict[str, Any]:
    try:
        import rasterio
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Point sampling requires rasterio.") from exc

    record = require_map(map_id)
    path = ensure_geotiff(record)
    with rasterio.open(path) as src:
        row, col = src.index(lon, lat)
        if row < 0 or col < 0 or row >= src.height or col >= src.width:
            value = None
        else:
            arr = src.read(1, masked=True)
            cell = arr[row, col]
            value = None if getattr(cell, "mask", False) else float(cell)
    units = record.get("units", "")
    return {
        "map_id": map_id,
        "lat": lat,
        "lon": lon,
        "value": value,
        "units": units,
        "formatted_value": format_hazard_risk_value(value, record),
    }


@router.get("/grid/{map_id}")
async def get_hazard_risk_value_grid(map_id: str) -> Dict[str, Any]:
    record = require_map(map_id)
    arr, transform, bounds = load_display_array(record)
    height, width = arr.shape

    lons = [transform.c + (col + 0.5) * transform.a for col in range(width)]
    lats = [transform.f + (row + 0.5) * transform.e for row in range(height)]
    values = [
        [None if not math.isfinite(value) else round(float(value), 4) for value in row]
        for row in arr.tolist()
    ]

    return {
        "map_id": map_id,
        "bounds": bounds,
        "lons": lons,
        "lats": lats,
        "values": values,
        "units": record.get("units", ""),
    }


@router.get("/image/{map_id}.png")
async def get_hazard_risk_image(map_id: str) -> Response:
    """Render the entire map as a single PNG, clipped to Ethiopia's border.

    Used by the frontend as a Leaflet ImageOverlay -- see this module's
    docstring for why tiling is skipped entirely for this data.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Raster image rendering requires pillow, rasterio, numpy, and matplotlib.") from exc

    record = require_map(map_id)
    arr, transform, bounds = load_display_array(record)
    config = get_render_config(record)
    categorical_bands = CATEGORICAL_BANDS_BY_LAYER.get(record["layer"])

    long_side = max(arr.shape)
    scale_factor = max(1.0, FULL_IMAGE_MIN_LONG_SIDE / long_side) if long_side else 1.0

    if scale_factor > 1.0:
        if categorical_bands is not None:
            render_arr, upsampled_valid_fraction = upsample_value_array_nearest(arr, scale_factor)
        else:
            render_arr, upsampled_valid_fraction = upsample_value_array(arr, scale_factor)
        high_res_transform = scaled_transform(transform, scale_factor)
        country_mask = rasterize_country_mask(render_arr.shape, high_res_transform)
        valid_mask = (upsampled_valid_fraction > 0.5) & country_mask
    else:
        render_arr = arr
        valid_mask = np.isfinite(arr)

    # Nearest-neighbor row remap (order=0) for categorical layers, for the
    # same class-integrity reason as upsample_value_array_nearest above.
    render_arr = remap_rows_equirect_to_mercator(render_arr, bounds["south"], bounds["north"], order=(0 if categorical_bands is not None else 1))
    valid_mask = remap_rows_equirect_to_mercator(valid_mask.astype("float32"), bounds["south"], bounds["north"], order=0) > 0.5

    if categorical_bands is not None:
        rgba = render_categorical_rgba(render_arr, valid_mask, categorical_bands)
    else:
        rgba = render_array_to_rgba(render_arr, valid_mask, config["vmin"], config["vmax"], config["cmap"])

    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(content=buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/refresh")
async def refresh_hazard_risk_catalog() -> Dict[str, Any]:
    load_catalog_cached.cache_clear()
    get_map_statistics_cached.cache_clear()
    return {"status": "refreshed", "count": len(list_catalog())}
