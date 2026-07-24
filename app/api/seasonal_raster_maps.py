
import math
import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import Response

from app.api.seasonal_catalog_shared import (
    ALL_PERIODS,
    INDICATOR_BY_VALUE,
    INDICATORS,
    PERIOD_BY_VALUE,
    PROBABILITY_PRODUCTS,
    PRODUCT_BY_VALUE,
    PRODUCTS,
    PROJECT_ROOT,
    SCALES,
    compare_products_for_indicator,
    infer_indicator,
    infer_period,
    infer_product,
    make_id,
    resolve_within,
    safe_read_json,
    safe_rel_path,
)

router = APIRouter(prefix="/api/seasonal-raster", tags=["Interactive Seasonal Climate Raster Maps"])

MAPS_ROOT = Path(os.getenv("SEASONAL_RASTER_ROOT", PROJECT_ROOT / "data" / "maps")).resolve()
GEOTIFF_DIR = Path(os.getenv("SEASONAL_GEOTIFF_DIR", MAPS_ROOT / "geotiff")).resolve()
NETCDF_DIR = Path(os.getenv("SEASONAL_NETCDF_DIR", MAPS_ROOT / "netcdf")).resolve()
CSV_DIR = Path(os.getenv("SEASONAL_CSV_DIR", MAPS_ROOT / "csv")).resolve()
CACHE_DIR = Path(os.getenv("SEASONAL_RASTER_CACHE_DIR", MAPS_ROOT / "cache" / "seasonal_raster")).resolve()
CATALOG_PATH = Path(os.getenv("SEASONAL_RASTER_CATALOG", MAPS_ROOT / "seasonal_raster_catalog.json")).resolve()

# Country outline used to clip rendered maps to Ethiopia's real border instead
# of whatever rough rectangular footprint a source raster happens to have.
# Same shapefile already used by app/data_pipeline/ethiopia_admin_boundary_pipeline.py.
COUNTRY_BOUNDARY_PATH = Path(
    os.getenv("SEASONAL_RASTER_COUNTRY_BOUNDARY", PROJECT_ROOT / "data" / "eth_shapefile" / "eth_admin0.shp")
).resolve()

# Converted GeoTIFFs accumulate in CACHE_DIR forever otherwise -- every distinct
# indicator/period/product combination a user views adds another cached file.
# This trims the oldest files (by mtime) once the cache exceeds a size budget.
SEASONAL_RASTER_CACHE_MAX_MB = float(os.getenv("SEASONAL_RASTER_CACHE_MAX_MB", "512"))

# Rendering safeguards. Many climate rasters exported from NetCDF have fill rows
# or tile-edge fill values that are not encoded as formal NoData. These settings
# make the interactive Leaflet rendering more robust without changing source data.
AUTO_MASK_ZERO_STRIPES = os.getenv("SEASONAL_AUTO_MASK_ZERO_STRIPES", "true").strip().lower() not in {"0", "false", "no"}
ZERO_STRIPE_FRACTION = float(os.getenv("SEASONAL_ZERO_STRIPE_FRACTION", "0.92"))
DEFAULT_TILE_BUFFER_DEGREES = float(os.getenv("SEASONAL_TILE_BOUNDS_BUFFER_DEGREES", "0.15"))
FULL_IMAGE_MIN_LONG_SIDE = int(os.getenv("SEASONAL_FULL_IMAGE_MIN_LONG_SIDE", "480"))

DEFAULT_BOUNDS = {"south": 3.0, "west": 33.0, "north": 15.0, "east": 48.0}

RASTER_EXTENSIONS = {".tif", ".tiff", ".nc", ".nc4", ".netcdf", ".csv"}
GEOTIFF_EXTENSIONS = {".tif", ".tiff"}
NETCDF_EXTENSIONS = {".nc", ".nc4", ".netcdf"}
CSV_EXTENSIONS = {".csv"}

INDICATOR_RENDERING = {
    "rainfall_total": {"cmap": "YlGnBu", "default_vmin": None, "default_vmax": None, "low_label": "Low rainfall", "high_label": "High rainfall"},
    "rx1day": {"cmap": "YlGnBu", "default_vmin": None, "default_vmax": None, "low_label": "Low max 1-day rainfall", "high_label": "High max 1-day rainfall"},
    "rx5day": {"cmap": "YlGnBu", "default_vmin": None, "default_vmax": None, "low_label": "Low max 5-day rainfall", "high_label": "High max 5-day rainfall"},
    "spi": {"cmap": "BrBG", "default_vmin": -2.5, "default_vmax": 2.5, "low_label": "Dry", "high_label": "Wet"},
    "cdd": {"cmap": "YlOrRd", "default_vmin": 0, "default_vmax": None, "low_label": "Few dry days", "high_label": "Long dry spell"},
    "cwd": {"cmap": "Blues", "default_vmin": 0, "default_vmax": None, "low_label": "Few wet days", "high_label": "Long wet spell"},
    "dryspell_prob_5d": {"cmap": "YlOrRd", "default_vmin": 0, "default_vmax": 1, "low_label": "Low probability", "high_label": "High probability"},
    "dryspell_prob_7d": {"cmap": "YlOrRd", "default_vmin": 0, "default_vmax": 1, "low_label": "Low probability", "high_label": "High probability"},
    "dryspell_prob_9d": {"cmap": "YlOrRd", "default_vmin": 0, "default_vmax": 1, "low_label": "Low probability", "high_label": "High probability"},
    "rainfall_percentile": {"cmap": "RdYlBu", "default_vmin": 0, "default_vmax": 100, "low_label": "Low percentile", "high_label": "High percentile"},
}


def resolve_project_path(path_value: Any) -> Optional[Path]:
    """Resolve a catalog-supplied source path, confined to MAPS_ROOT.

    Catalog JSON (seasonal_raster_catalog.json) can name a "source_path" for
    a map. Without this check, a crafted catalog entry could point outside
    data/maps (e.g. "../../.env") and have it opened as if it were a raster.
    Only paths that resolve inside MAPS_ROOT are honored; anything else is
    treated as missing, which surfaces as a normal 404 for that map.
    """
    return resolve_within(path_value, [MAPS_ROOT])


def period_scale(period: Any) -> str:
    return PERIOD_BY_VALUE.get(str(period).lower(), {}).get("scale") or "seasonal"


def label_for(value: str, lookup: Dict[str, Dict[str, str]], fallback: Optional[str] = None) -> str:
    return lookup.get(str(value).lower(), {}).get("label") or fallback or str(value).replace("_", " ").title()


def units_for_indicator(indicator: str) -> str:
    return INDICATOR_BY_VALUE.get(indicator, {}).get("units", "")


def source_format_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in GEOTIFF_EXTENSIONS:
        return "geotiff"
    if suffix in NETCDF_EXTENSIONS:
        return "netcdf"
    if suffix in CSV_EXTENSIONS:
        return "csv"
    return "unknown"


def enrich_record(record: Dict[str, Any], source_path: Optional[Path] = None) -> Dict[str, Any]:
    source_path = source_path or resolve_project_path(record.get("source_path") or record.get("path") or record.get("geotiff_path") or record.get("netcdf_path") or record.get("csv_path"))
    stem = source_path.stem if source_path else str(record.get("id") or "seasonal_raster")

    indicator = record.get("indicator") or infer_indicator(stem)
    period = record.get("period") or infer_period(stem)
    product = record.get("product") or infer_product(stem)

    period_meta = PERIOD_BY_VALUE.get(str(period).lower(), {"value": period, "label": str(period)})
    product_meta = PRODUCT_BY_VALUE.get(product, {"value": product, "label": str(product).replace("_", " ").title()})
    indicator_meta = INDICATOR_BY_VALUE.get(indicator, {"value": indicator, "label": str(indicator).replace("_", " ").title(), "units": ""})

    map_id = record.get("id") or make_id(indicator, period_meta["value"], product, stem)

    bounds = record.get("bounds") or DEFAULT_BOUNDS
    if isinstance(bounds, list) and len(bounds) == 4:
        bounds = {"west": bounds[0], "south": bounds[1], "east": bounds[2], "north": bounds[3]}

    source_format = record.get("source_format") or (source_format_for_path(source_path) if source_path else "unknown")

    enriched = {
        "id": map_id,
        "title": record.get("title") or f"{indicator_meta['label']} · {period_meta['label']} · {product_meta['label']}",
        "indicator": indicator,
        "indicator_label": record.get("indicator_label") or indicator_meta["label"],
        "period": period_meta["value"],
        "period_label": record.get("period_label") or period_meta["label"],
        "scale": record.get("scale") or period_meta.get("scale") or "seasonal",
        "product": product,
        "product_label": record.get("product_label") or product_meta["label"],
        "source_format": source_format,
        "source_path": safe_rel_path(source_path) if source_path else "",
        "variable": record.get("variable") or record.get("variable_name") or "",
        "bounds": bounds,
        "units": record.get("units") or (
            "probability" if product in PROBABILITY_PRODUCTS
            # rainfall_percentile's Anomaly product is a %-anomaly of
            # rainfall (see INDICATOR_PATTERNS' percent_anomaly/pctanomaly
            # comment), not a percentile rank like its Forecast/Climatology
            # products -- format_value would otherwise render it as
            # "-45.00 percentile", which misreads as an impossible
            # percentile value instead of a -45% rainfall anomaly.
            else "%" if (indicator == "rainfall_percentile" and product == "anomaly")
            else indicator_meta.get("units")
        ) or "",
        "init_date": record.get("init_date", ""),
        "valid_start": record.get("valid_start", ""),
        "valid_end": record.get("valid_end", ""),
        "forecast_source": record.get("forecast_source", ""),
        "forecast_system_version": record.get("forecast_system_version", ""),
        "n_ensemble_members": record.get("n_ensemble_members", ""),
        "observation_dataset": record.get("observation_dataset", ""),
        "climatology_period": record.get("climatology_period", ""),
        "vmin": record.get("vmin"),
        "vmax": record.get("vmax"),
        "cmap": record.get("cmap"),
        "attribution": record.get("attribution") or "Seasonal climate raster",
        "source_type": record.get("source_type") or "auto_scanned_raster",
    }

    for key, value in record.items():
        if key not in enriched:
            enriched[key] = value

    return enriched


def load_catalog_file() -> List[Dict[str, Any]]:
    data = safe_read_json(CATALOG_PATH)
    if not data:
        return []
    records = data.get("maps") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return []
    output: List[Dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        source_path = resolve_project_path(record.get("source_path") or record.get("path") or record.get("geotiff_path") or record.get("netcdf_path") or record.get("csv_path"))
        output.append(enrich_record({**record, "source_type": "catalog"}, source_path=source_path))
    return output


def scan_raster_files() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for folder in [GEOTIFF_DIR, NETCDF_DIR, CSV_DIR]:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in RASTER_EXTENSIONS:
                continue
            sidecar = safe_read_json(path.with_suffix(".json"))
            record = sidecar if isinstance(sidecar, dict) else {}
            records.append(enrich_record(record, source_path=path))
    return records


# When a period/indicator has both a "_mean.tif" and a "_median.tif" forecast
# raster (e.g. rainfall_total), they represent different statistics of the
# same ensemble and are NOT interchangeable: climatology/anomaly rasters here
# are built against the median. Preferring median on a tie keeps the
# displayed Forecast consistent with Climatology and Anomaly (Anomaly =
# Forecast - Climatology only holds when Forecast is the same statistic the
# anomaly was derived from).
STAT_TOKEN_PRIORITY = {"median": 0, "mean": 1}


def stat_token_priority(record: Dict[str, Any]) -> int:
    stem = str(record.get("source_path", "")).lower()
    for token, rank in STAT_TOKEN_PRIORITY.items():
        if token in stem:
            return rank
    return 2


@lru_cache(maxsize=1)
def load_catalog_cached() -> Tuple[Dict[str, Dict[str, Any]], ...]:
    records = load_catalog_file() + scan_raster_files()
    by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    priority = {"catalog": 0, "geotiff": 1, "netcdf": 2, "csv": 3, "unknown": 4}

    for record in records:
        key = (record["indicator"], str(record["period"]).lower(), record["product"])
        existing = by_key.get(key)
        record_priority = (
            0 if record.get("source_type") == "catalog" else priority.get(record.get("source_format", "unknown"), 9),
            stat_token_priority(record),
        )
        existing_priority = (99, 99)
        if existing:
            existing_priority = (
                0 if existing.get("source_type") == "catalog" else priority.get(existing.get("source_format", "unknown"), 9),
                stat_token_priority(existing),
            )
        if existing is None or record_priority < existing_priority:
            by_key[key] = record

    by_id: Dict[str, Dict[str, Any]] = {}
    used_ids = set()
    for record in by_key.values():
        base_id = record["id"]
        map_id = base_id
        count = 2
        while map_id in used_ids:
            map_id = f"{base_id}_{count}"
            count += 1
        record["id"] = map_id
        used_ids.add(map_id)
        by_id[map_id] = record
    return tuple(by_id.items())


def catalog_by_id() -> Dict[str, Dict[str, Any]]:
    return dict(load_catalog_cached())


def list_catalog() -> List[Dict[str, Any]]:
    return sorted(catalog_by_id().values(), key=lambda r: (r["indicator"], str(r["period"]), r["product"]))


def find_map_record(indicator: str, period: str, product: str) -> Optional[Dict[str, Any]]:
    period_lower = str(period).lower()
    product_lower = str(product).lower()
    indicator_lower = str(indicator).lower()
    for record in list_catalog():
        if (
            str(record.get("indicator", "")).lower() == indicator_lower
            and str(record.get("period", "")).lower() == period_lower
            and str(record.get("product", "")).lower() == product_lower
        ):
            return record
    return None


def require_map(map_id: str) -> Dict[str, Any]:
    record = catalog_by_id().get(map_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Seasonal raster map '{map_id}' was not found.")
    return record


def geotiff_cache_path(record: Dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{record['id']}.tif"


def geotiff_tile_cache_path(record: Dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{record['id']}_north_up_tiles.tif"


def enforce_cache_size_limit() -> None:
    """Evict the oldest cached GeoTIFFs once CACHE_DIR exceeds its size budget.

    Cached files are cheap to regenerate (the next request just re-converts
    the source NetCDF/CSV/oriented-GeoTIFF), so a simple oldest-first eviction
    by mtime is enough -- no need for LRU bookkeeping.
    """
    if not CACHE_DIR.exists():
        return

    budget_bytes = SEASONAL_RASTER_CACHE_MAX_MB * 1024 * 1024
    files = [path for path in CACHE_DIR.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes <= budget_bytes:
        return

    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        if total_bytes <= budget_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total_bytes -= size
        except Exception:
            continue


def apply_basic_nodata_mask(arr: Any, source_nodata: Any = None):
    """Convert common raster fill values to NaN before tile rendering."""
    import numpy as np

    cleaned = arr.astype("float32", copy=True)
    valid = np.isfinite(cleaned)

    fill_values = [-9999, -9999.0, -999, -32768, 32767, 65535, 1.0e20, 9.96921e36]
    if source_nodata is not None:
        try:
            fill_values.append(float(source_nodata))
        except Exception:
            pass

    for fill in fill_values:
        try:
            valid &= ~np.isclose(cleaned, float(fill), rtol=0.0, atol=1.0e-6)
        except Exception:
            continue

    cleaned[~valid] = np.nan
    return cleaned


def auto_mask_fill_stripes(arr: Any):
    """Mask likely export/fill stripes that appear as thick white bands on the map.

    This targets rows/columns dominated by exact zero values. It is deliberately
    conservative and only removes long, nearly uniform bands. It does not alter
    the original source file; it only improves the cached display GeoTIFF used by
    the web map.
    """
    import numpy as np

    if not AUTO_MASK_ZERO_STRIPES:
        return arr

    cleaned = arr.astype("float32", copy=True)
    if cleaned.ndim != 2 or cleaned.size == 0:
        return cleaned

    finite = np.isfinite(cleaned)
    if finite.sum() == 0:
        return cleaned

    zero_like = finite & np.isclose(cleaned, 0.0, rtol=0.0, atol=1.0e-7)
    height, width = cleaned.shape

    row_zero_fraction = zero_like.sum(axis=1) / max(width, 1)
    col_zero_fraction = zero_like.sum(axis=0) / max(height, 1)

    # Mask only a limited share of rows/columns so legitimate near-normal SPI
    # values are not removed at national scale.
    rows_to_mask = np.where(row_zero_fraction >= ZERO_STRIPE_FRACTION)[0]
    cols_to_mask = np.where(col_zero_fraction >= ZERO_STRIPE_FRACTION)[0]

    if rows_to_mask.size and rows_to_mask.size / max(height, 1) <= 0.35:
        cleaned[rows_to_mask, :] = np.nan

    if cols_to_mask.size and cols_to_mask.size / max(width, 1) <= 0.35:
        cleaned[:, cols_to_mask] = np.nan

    return cleaned


def clean_array_for_display(arr: Any, source_nodata: Any = None):
    cleaned = apply_basic_nodata_mask(arr, source_nodata=source_nodata)
    cleaned = auto_mask_fill_stripes(cleaned)
    return cleaned


@lru_cache(maxsize=1)
def load_country_geometries() -> Tuple[Dict[str, Any], ...]:
    """Return Ethiopia's national boundary geometry (EPSG:4326) for raster clipping.

    Falls back to an empty tuple (no clipping applied) if the shapefile or
    geopandas is unavailable, so a missing optional dependency degrades to the
    previous behavior instead of breaking map rendering entirely.
    """
    if not COUNTRY_BOUNDARY_PATH.exists():
        return tuple()
    try:
        import geopandas as gpd
    except Exception:
        return tuple()

    try:
        gdf = gpd.read_file(COUNTRY_BOUNDARY_PATH)
        if gdf.crs and str(gdf.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
            gdf = gdf.to_crs("EPSG:4326")
        return tuple(geom.__geo_interface__ for geom in gdf.geometry if geom is not None)
    except Exception:
        return tuple()


def rasterize_country_mask(shape: Tuple[int, int], transform: Any):
    """Return a boolean array, True where a pixel (given shape/transform) is inside Ethiopia.

    Rasterizing directly at the caller's resolution (rather than reusing a
    mask computed at some other resolution and resampling it) is what keeps
    the border crisp and accurate even when the caller asks at a much higher
    resolution than the source forecast grid -- the national border is a
    precise vector shape, independent of how coarse the climate data is.
    """
    import numpy as np

    geometries = load_country_geometries()
    if not geometries:
        return np.ones(shape, dtype=bool)

    try:
        from rasterio.features import geometry_mask
        return geometry_mask(geometries, out_shape=shape, transform=transform, invert=True)
    except Exception:
        return np.ones(shape, dtype=bool)


def scaled_transform(transform: Any, scale_factor: float):
    """Return a transform for the same origin/extent at scale_factor times the resolution."""
    from rasterio import Affine

    return Affine(
        transform.a / scale_factor, transform.b, transform.c,
        transform.d, transform.e / scale_factor, transform.f,
    )


def clip_array_to_country(arr: Any, transform: Any):
    """Set every pixel outside Ethiopia's real border to NaN.

    Source rasters only carry a rough rectangular/blocky footprint (whatever
    NaN pattern the forecast export happened to have), which lets the map
    visibly bleed into neighboring countries. This masks against the actual
    admin0 polygon instead.
    """
    import numpy as np

    inside = rasterize_country_mask(arr.shape, transform)
    clipped = arr.astype("float32", copy=True)
    clipped[~inside] = np.nan
    return clipped


def mercator_y_from_lat(lat_deg: float) -> float:
    lat_rad = math.radians(max(min(lat_deg, 89.9), -89.9))
    return math.log(math.tan(math.pi / 4 + lat_rad / 2))


def remap_rows_equirect_to_mercator(arr: Any, south: float, north: float, order: int = 1):
    """Resample rows so a linear stretch between (south, north) matches Web Mercator.

    `arr`'s rows are assumed evenly spaced in latitude, north (row 0) to south
    (last row) -- the natural convention for our north-up display arrays.
    Leaflet's ImageOverlay always stretches an image linearly between two
    lat/lng corners onto the map's Web Mercator projection, which is linear in
    Mercator Y but not in latitude. Without this remap, the raster visibly
    drifts away from the true basemap geography away from the image's
    vertical center -- small per degree of latitude, but clearly visible over
    Ethiopia's ~12 degree span.
    """
    import numpy as np
    from scipy import ndimage

    height = arr.shape[0]
    if height < 2 or south == north:
        return arr

    merc_north = mercator_y_from_lat(north)
    merc_south = mercator_y_from_lat(south)

    row_fracs = np.linspace(0.0, 1.0, height)
    target_merc_y = merc_north + row_fracs * (merc_south - merc_north)
    target_lat = np.degrees(2 * np.arctan(np.exp(target_merc_y)) - np.pi / 2)

    # Each output row needs the value from wherever that latitude falls in
    # the source's linear-latitude row spacing.
    source_row_index = (north - target_lat) / (north - south) * (height - 1)
    col_index = np.arange(arr.shape[1])
    row_grid, col_grid = np.meshgrid(source_row_index, col_index, indexing="ij")

    return ndimage.map_coordinates(arr, [row_grid, col_grid], order=order, mode="nearest")


def upsample_value_array(arr: Any, scale_factor: float) -> Tuple[Any, Any]:
    """NaN-safe smooth upsample of a 2D array. Returns (values, valid_fraction).

    Plain interpolation propagates NaN outward from every missing cell, so
    NaNs are first filled from their nearest valid neighbor (this only feeds
    the interpolation -- validity itself is tracked and upsampled separately
    in valid_fraction, so still-invalid areas end up transparent regardless
    of what value was used to fill them for interpolation purposes).
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

    upsampled_values = ndimage.zoom(filled, scale_factor, order=3, mode="nearest")
    upsampled_valid = ndimage.zoom(valid.astype("float32"), scale_factor, order=1, mode="nearest")
    return upsampled_values.astype("float32"), upsampled_valid


def load_display_array(record: Dict[str, Any]) -> Tuple[Any, Any, Dict[str, float]]:
    """Return (clipped array, affine transform, EPSG:4326 bounds) for a map record.

    This is the single shared source of truth for "what should render/count as
    data" -- used by the full-image endpoint, the client hover value grid, and
    statistics, so all three agree on the same country-clipped footprint.
    """
    import numpy as np
    import rasterio

    path = ensure_geotiff(record)
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).astype("float32")
        arr = arr.filled(np.nan)
        transform = src.transform
        nodata = src.nodata

    bounds = get_raster_bounds(path)
    arr = clean_array_for_display(arr, source_nodata=nodata)
    arr = clip_array_to_country(arr, transform)
    return arr, transform, bounds


def normalize_geotiff_for_tiles(record: Dict[str, Any], source_path: Path) -> Path:
    """Return a CRS-aware north-up GeoTIFF suitable for Web Mercator tiling.

    Some climate rasters are written with latitude increasing downward in the
    file transform. Rasterio then reports bounds such as south=15 and north=3.
    Leaflet/rio-tiler expect a normal north-up raster, so we create a cached
    north-up copy when needed. Already valid GeoTIFFs are returned unchanged.
    """
    try:
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds
    except Exception as exc:
        raise HTTPException(status_code=500, detail="GeoTIFF normalization requires rasterio and numpy.") from exc

    with rasterio.open(source_path) as src:
        bounds = src.bounds
        transform = src.transform
        needs_vertical_flip = bool(transform.e > 0 or bounds.bottom > bounds.top)
        needs_horizontal_flip = bool(bounds.left > bounds.right)
        needs_crs = src.crs is None

        if not needs_vertical_flip and not needs_horizontal_flip and not needs_crs:
            return source_path

        cache_path = geotiff_tile_cache_path(record)
        if cache_path.exists() and cache_path.stat().st_mtime >= source_path.stat().st_mtime:
            return cache_path

        data = src.read(1, masked=True).astype("float32")
        arr = data.filled(np.nan).astype("float32")
        arr = clean_array_for_display(arr, source_nodata=src.nodata)

        if needs_vertical_flip:
            arr = np.flipud(arr)

        if needs_horizontal_flip:
            arr = np.fliplr(arr)

        arr = clean_array_for_display(arr, source_nodata=src.nodata)

        west = float(min(bounds.left, bounds.right))
        east = float(max(bounds.left, bounds.right))
        south = float(min(bounds.bottom, bounds.top))
        north = float(max(bounds.bottom, bounds.top))

        nodata = -9999.0
        arr = np.where(np.isfinite(arr), arr, nodata).astype("float32")

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=arr.shape[0],
            width=arr.shape[1],
            count=1,
            dtype="float32",
            crs=src.crs or "EPSG:4326",
            transform=from_bounds(west, south, east, north, arr.shape[1], arr.shape[0]),
            nodata=nodata,
            compress="deflate",
            tiled=True,
            blockxsize=256,
            blockysize=256,
        )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(cache_path, "w", **profile) as dst:
            dst.write(arr, 1)

    enforce_cache_size_limit()
    return cache_path


def ensure_geotiff(record: Dict[str, Any]) -> Path:
    source_path = resolve_project_path(record.get("source_path"))
    if not source_path or not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Source raster file not found for map {record.get('id')}: {record.get('source_path')}")

    source_format = record.get("source_format") or source_format_for_path(source_path)

    if source_format == "geotiff":
        candidate_path = source_path
    else:
        cache_path = geotiff_cache_path(record)
        if cache_path.exists() and cache_path.stat().st_mtime >= source_path.stat().st_mtime:
            candidate_path = cache_path
        elif source_format == "netcdf":
            candidate_path = convert_netcdf_to_geotiff(record, source_path, cache_path)
        elif source_format == "csv":
            candidate_path = convert_csv_to_geotiff(record, source_path, cache_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported source format: {source_format}")

    return normalize_geotiff_for_tiles(record, candidate_path)


def detect_spatial_dims(da: Any) -> Tuple[str, str]:
    dims = list(da.dims)
    x_candidates = ["lon", "longitude", "x", "LONGITUDE", "LON"]
    y_candidates = ["lat", "latitude", "y", "LATITUDE", "LAT"]
    x_dim = next((dim for dim in dims if dim in x_candidates or dim.lower() in {"lon", "longitude", "x"}), None)
    y_dim = next((dim for dim in dims if dim in y_candidates or dim.lower() in {"lat", "latitude", "y"}), None)
    if not x_dim or not y_dim:
        raise HTTPException(status_code=400, detail=f"Could not detect longitude/latitude dimensions in NetCDF variable with dims {dims}")
    return x_dim, y_dim


def choose_netcdf_variable(ds: Any, requested: str = "") -> str:
    if requested and requested in ds.data_vars:
        return requested
    for name, da in ds.data_vars.items():
        dims = set(str(dim).lower() for dim in da.dims)
        if {"lat", "lon"}.issubset(dims) or {"latitude", "longitude"}.issubset(dims) or {"y", "x"}.issubset(dims):
            return name
    for name in ds.data_vars:
        return name
    raise HTTPException(status_code=400, detail="No data variables were found in the NetCDF file.")


def convert_netcdf_to_geotiff(record: Dict[str, Any], source_path: Path, cache_path: Path) -> Path:
    try:
        import xarray as xr
        import rioxarray  # noqa: F401
    except Exception as exc:
        raise HTTPException(status_code=500, detail="NetCDF support requires xarray and rioxarray. Install: pip install xarray rioxarray netCDF4 h5netcdf") from exc

    ds = xr.open_dataset(source_path)
    variable = choose_netcdf_variable(ds, record.get("variable") or "")
    da = ds[variable]

    x_dim, y_dim = detect_spatial_dims(da)
    for dim in list(da.dims):
        if dim not in {x_dim, y_dim}:
            da = da.isel({dim: 0})

    da = da.squeeze(drop=True)
    da = da.rio.set_spatial_dims(x_dim=x_dim, y_dim=y_dim)
    if not da.rio.crs:
        da = da.rio.write_crs("EPSG:4326")
    da.rio.to_raster(cache_path)
    enforce_cache_size_limit()
    return cache_path


def detect_csv_columns(df: Any, record: Dict[str, Any]) -> Tuple[str, str, str]:
    columns = list(df.columns)
    lower = {str(col).lower(): col for col in columns}
    lon_col = record.get("lon_column") or next((lower[name] for name in ["lon", "longitude", "x"] if name in lower), None)
    lat_col = record.get("lat_column") or next((lower[name] for name in ["lat", "latitude", "y"] if name in lower), None)
    value_col = record.get("value_column") or record.get("variable")
    if not value_col:
        excluded = {lon_col, lat_col}
        for col in columns:
            if col in excluded:
                continue
            try:
                if df[col].dropna().astype(float).shape[0] > 0:
                    value_col = col
                    break
            except Exception:
                continue
    if not lon_col or not lat_col or not value_col:
        raise HTTPException(status_code=400, detail="CSV must include lon/longitude, lat/latitude, and a numeric value column.")
    return lon_col, lat_col, value_col


def convert_csv_to_geotiff(record: Dict[str, Any], source_path: Path, cache_path: Path) -> Path:
    try:
        import numpy as np
        import pandas as pd
        import rasterio
        from rasterio.transform import from_origin
    except Exception as exc:
        raise HTTPException(status_code=500, detail="CSV raster support requires pandas, numpy, and rasterio.") from exc

    df = pd.read_csv(source_path)
    lon_col, lat_col, value_col = detect_csv_columns(df, record)
    df = df[[lon_col, lat_col, value_col]].dropna()
    df[lon_col] = df[lon_col].astype(float)
    df[lat_col] = df[lat_col].astype(float)
    df[value_col] = df[value_col].astype(float)

    lons = np.sort(df[lon_col].unique())
    lats = np.sort(df[lat_col].unique())[::-1]
    if len(lons) < 2 or len(lats) < 2:
        raise HTTPException(status_code=400, detail="CSV must contain a regular grid with at least two longitudes and two latitudes.")

    grid = df.pivot_table(index=lat_col, columns=lon_col, values=value_col, aggfunc="mean").reindex(index=lats, columns=lons)
    arr = grid.to_numpy(dtype="float32")
    dx = float(np.median(np.diff(lons)))
    dy = float(abs(np.median(np.diff(np.sort(df[lat_col].unique())))))
    transform = from_origin(float(lons.min() - dx / 2), float(lats.max() + dy / 2), dx, dy)

    with rasterio.open(
        cache_path,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
        compress="deflate",
    ) as dst:
        dst.write(arr, 1)
    enforce_cache_size_limit()
    return cache_path


def calculate_statistics_from_array(arr: Any) -> Dict[str, Any]:
    import numpy as np

    values = arr[np.isfinite(arr)].astype("float64")
    if values.size == 0:
        return {"valid_count": 0}
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "p10": float(np.percentile(values, 10)),
        "p25": float(np.percentile(values, 25)),
        "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)),
        "valid_count": int(values.size),
    }


@lru_cache(maxsize=256)
def get_map_statistics_cached(map_id: str) -> Dict[str, Any]:
    record = require_map(map_id)
    arr, _transform, _bounds = load_display_array(record)
    return calculate_statistics_from_array(arr)


def get_raster_bounds(path: Path) -> Dict[str, float]:
    try:
        import rasterio
        from rasterio.warp import transform_bounds
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Raster bounds require rasterio.") from exc

    with rasterio.open(path) as src:
        bounds = src.bounds
        crs = src.crs
        if crs and str(crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
            west, south, east, north = transform_bounds(crs, "EPSG:4326", bounds.left, bounds.bottom, bounds.right, bounds.top, densify_pts=21)
        else:
            west, south, east, north = bounds.left, bounds.bottom, bounds.right, bounds.top
    west2 = float(min(west, east))
    east2 = float(max(west, east))
    south2 = float(min(south, north))
    north2 = float(max(south, north))
    return {"west": west2, "south": south2, "east": east2, "north": north2}


def get_render_config(record: Dict[str, Any], stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    indicator = record.get("indicator", "spi")
    product = record.get("product", "forecast")
    defaults = INDICATOR_RENDERING.get(indicator, INDICATOR_RENDERING["spi"])
    probability_defaults = PROBABILITY_PRODUCTS.get(product)

    cmap_name = record.get("cmap") or (probability_defaults["cmap"] if probability_defaults else defaults["cmap"])
    # Most indicators here are "wetness" quantities (higher = wetter: rainfall
    # total, CWD/consecutive wet days), where RdBu's natural low=red/high=blue
    # already matches this app's drought=red/wet=blue convention (see
    # HAZARD_COLORS on the frontend). CDD (consecutive DRY days) and the dry
    # spell probabilities are the opposite -- higher means DRIER -- so using
    # plain RdBu there would paint "more dry days than normal" blue and "fewer
    # dry days than normal" red, backwards from every other drought signal in
    # the app. Flip to RdBu_r for those so red always means "drier than normal"
    # everywhere, regardless of which raw quantity is being measured.
    dryness_oriented = indicator in {"cdd", "dryspell_prob_5d", "dryspell_prob_7d", "dryspell_prob_9d"}
    # SPI never has an anomaly product (it's already a standardized anomaly),
    # so it stays excluded. rainfall_percentile now has a real one though (the
    # "percent_anomaly"/pctanomaly rasters -- a %-anomaly of rainfall, not a
    # second percentile computation), so it needs the same diverging
    # treatment as every other wetness-oriented anomaly.
    if product == "anomaly" and not record.get("cmap") and indicator != "spi":
        cmap_name = "RdBu_r" if dryness_oriented else "RdBu"

    stats = stats or {}
    vmin = record.get("vmin")
    vmax = record.get("vmax")

    # rainfall_percentile's own vmin/vmax defaults (0-100) describe a
    # percentile rank and only make sense for its Forecast/Climatology
    # products. Its Anomaly product is a %-anomaly of rainfall with a
    # completely different range (can be negative, can exceed 100), so it
    # must fall through to the data-driven percentile-based scaling below
    # instead of being forced onto the fixed 0-100 scale.
    skip_fixed_defaults = indicator == "rainfall_percentile" and product == "anomaly"

    # Drought/wet probability rasters are bounded [0, 1] by construction
    # (P(SPI <= -1.0) / P(SPI >= +1.0)), so the color scale is always fixed to
    # the full 0-1 range instead of being derived from this map's own
    # min/max/percentiles -- deriving it from the data would make a 65% chance
    # of drought in one period render as "maximum red" while a 90% chance in
    # another period renders the same, losing the actual probability scale.
    if probability_defaults:
        if vmin is None:
            vmin = probability_defaults["vmin"]
        if vmax is None:
            vmax = probability_defaults["vmax"]
    else:
        if vmin is None and not skip_fixed_defaults:
            vmin = defaults.get("default_vmin")
        if vmax is None and not skip_fixed_defaults:
            vmax = defaults.get("default_vmax")
        if vmin is None and stats.get("p10") is not None:
            vmin = stats.get("p10")
        if vmax is None and stats.get("p90") is not None:
            vmax = stats.get("p90")
        if vmin is None and stats.get("min") is not None:
            vmin = stats.get("min")
        if vmax is None and stats.get("max") is not None:
            vmax = stats.get("max")
    if vmin is None or vmax is None or float(vmin) == float(vmax):
        vmin, vmax = 0.0, 1.0

    vmin = float(vmin)
    vmax = float(vmax)

    # Anomaly rasters are a deviation from climatology (forecast - climatology),
    # so zero is the meaningful midpoint. Without forcing a symmetric range, an
    # asymmetric min/max (typical when derived from data percentiles) would
    # shift the diverging colormap's neutral color away from true zero,
    # making equal-magnitude dry/wet anomalies look like different intensities.
    is_diverging_anomaly = product == "anomaly" and cmap_name in {"RdBu", "RdBu_r"}
    if is_diverging_anomaly and not (
        record.get("vmin") is not None and record.get("vmax") is not None
    ):
        max_abs = max(abs(vmin), abs(vmax))
        if max_abs > 0:
            vmin, vmax = -max_abs, max_abs

    if probability_defaults:
        low_label = probability_defaults["low_label"]
        high_label = probability_defaults["high_label"]
    elif is_diverging_anomaly and dryness_oriented:
        # CDD/dry-spell-probability anomalies are day counts/probabilities,
        # not rainfall amounts -- "fewer/longer [days]" reads naturally here.
        low_label = "Fewer than normal"
        high_label = "Longer than normal"
    elif is_diverging_anomaly:
        # Every other anomaly (rainfall total, rx1day/rx5day, rainfall
        # percentile) is a rainfall-amount deviation, where "drier/wetter"
        # is the correct framing -- this branch previously duplicated the
        # dryness-oriented one above verbatim, mislabeling all of these.
        low_label = "Drier than normal"
        high_label = "Wetter than normal"
    else:
        low_label = defaults.get("low_label", "Low")
        high_label = defaults.get("high_label", "High")

    return {
        "cmap": cmap_name,
        "vmin": vmin,
        "vmax": vmax,
        "low_label": low_label,
        "high_label": high_label,
    }


def hex_from_rgba(rgba: Tuple[float, float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255))


def get_matplotlib_cmap(cmap_name: str):
    """Return a Matplotlib colormap across old and new Matplotlib versions.

    Some Matplotlib builds no longer expose matplotlib.cm.get_cmap. This helper
    first tries the modern matplotlib.colormaps API, then pyplot.get_cmap, then
    the older cm.get_cmap API. If all fail, it returns None so the API can still
    serve a safe fallback legend/tile instead of crashing with HTTP 500.
    """
    try:
        import matplotlib
        colormaps = getattr(matplotlib, "colormaps", None)
        if colormaps is not None:
            return colormaps.get_cmap(cmap_name)
    except Exception:
        pass

    try:
        import matplotlib.pyplot as plt
        return plt.get_cmap(cmap_name)
    except Exception:
        pass

    try:
        import matplotlib.cm as cm
        get_cmap = getattr(cm, "get_cmap", None)
        if get_cmap is not None:
            return get_cmap(cmap_name)
    except Exception:
        pass

    return None


def render_array_to_rgba(band: Any, valid_mask: Any, vmin: float, vmax: float, cmap_name: str):
    """Colormap a float array into an RGBA uint8 array, alpha=0 outside valid_mask.

    Shared by the XYZ tile endpoint and the full-extent image endpoint so both
    render identically (same clip/scale/colormap/fallback behavior).
    """
    import numpy as np

    scaled = np.zeros_like(band, dtype="float32")
    if float(vmax) != float(vmin):
        scaled = np.clip((band - vmin) / (vmax - vmin), 0, 1)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)

    colormap = get_matplotlib_cmap(cmap_name)
    if colormap is not None:
        rgba = (colormap(scaled) * 255).astype("uint8")
    else:
        # Safe fallback if Matplotlib colormap lookup is unavailable.
        rgba = np.zeros((scaled.shape[0], scaled.shape[1], 4), dtype="uint8")
        rgba[:, :, 0] = (scaled * 245).astype("uint8")
        rgba[:, :, 1] = (80 + scaled * 135).astype("uint8")
        rgba[:, :, 2] = (245 - scaled * 180).astype("uint8")
        rgba[:, :, 3] = 255

    rgba[:, :, 3] = np.where(valid_mask, rgba[:, :, 3], 0).astype("uint8")
    return rgba


def build_legend(record: Dict[str, Any], stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = get_render_config(record, stats)
    vmin = config["vmin"]
    vmax = config["vmax"]
    values = [vmin + (vmax - vmin) * frac for frac in [0, 0.2, 0.4, 0.6, 0.8, 1.0]]

    colormap = get_matplotlib_cmap(config["cmap"])

    if colormap is not None:
        items = [{"value": value, "label": f"{value:.2f}", "color": hex_from_rgba(colormap(i / 5))} for i, value in enumerate(values)]
    else:
        fallback_colors = ["#b42318", "#f79009", "#fec84b", "#12b76a", "#0e9384", "#1570ef"]
        items = [{"value": value, "label": f"{value:.2f}", "color": fallback_colors[i]} for i, value in enumerate(values)]

    indicator_label = record.get("indicator_label", "Raster value")
    product = record.get("product")
    if product == "anomaly":
        title = f"{indicator_label} Anomaly"
    elif product == "drought_probability":
        title = "Drought Probability (SPI ≤ -1.0)"
    elif product == "wet_probability":
        title = "Wet Probability (SPI ≥ +1.0)"
    else:
        title = indicator_label

    return {
        "title": title,
        "units": record.get("units", ""),
        "vmin": vmin,
        "vmax": vmax,
        "cmap": config["cmap"],
        "low_label": config["low_label"],
        "high_label": config["high_label"],
        "items": items,
    }


def public_map_record(record: Dict[str, Any], include_statistics: bool = True) -> Dict[str, Any]:
    output = dict(record)
    map_id = record["id"]
    output["tile_url"] = f"/api/seasonal-raster/tiles/{map_id}/{{z}}/{{x}}/{{y}}.png"
    output["image_url"] = f"/api/seasonal-raster/image/{map_id}.png"
    output["grid_url"] = f"/api/seasonal-raster/grid/{map_id}"
    output["value_url"] = f"/api/seasonal-raster/value/{map_id}?lat={{lat}}&lon={{lon}}"
    output["statistics_url"] = f"/api/seasonal-raster/statistics/{map_id}"
    try:
        path = ensure_geotiff(record)
        output["bounds"] = get_raster_bounds(path)
        if include_statistics:
            stats = get_map_statistics_cached(map_id)
            output["statistics"] = stats
        else:
            stats = None
        output["legend"] = build_legend(record, output.get("statistics"))
        output["rendering"] = get_render_config(record, output.get("statistics"))
        output["geotiff_cache_path"] = safe_rel_path(path)
    except HTTPException as exc:
        output["availability_error"] = exc.detail
        output["legend"] = build_legend(record, None)
    return output


def format_value(value: Optional[float], units: str = "") -> str:
    if value is None or not math.isfinite(float(value)):
        return "No data"
    if units == "probability":
        return f"{float(value) * 100:.1f}%"
    if units:
        return f"{float(value):.2f} {units}"
    return f"{float(value):.2f}"


def directory_file_summary() -> Dict[str, Any]:
    """Return a lightweight diagnostic summary for troubleshooting map discovery."""
    folders = {
        "geotiff": GEOTIFF_DIR,
        "netcdf": NETCDF_DIR,
        "csv": CSV_DIR,
    }
    summary: Dict[str, Any] = {}
    for name, folder in folders.items():
        extensions = GEOTIFF_EXTENSIONS if name == "geotiff" else NETCDF_EXTENSIONS if name == "netcdf" else CSV_EXTENSIONS
        files = []
        if folder.exists():
            files = [path for path in sorted(folder.rglob("*")) if path.is_file() and path.suffix.lower() in extensions]
        summary[name] = {
            "path": safe_rel_path(folder),
            "absolute_path": str(folder),
            "exists": folder.exists(),
            "file_count": len(files),
            "sample_files": [safe_rel_path(path) for path in files[:12]],
        }
    return summary




@router.get("/health")
async def get_raster_health() -> Dict[str, Any]:
    catalog = list_catalog()
    available = {(item["indicator"], str(item["period"]), item["product"]) for item in catalog}
    return {
        "status": "ok",
        "router_registered": True,
        "maps_root": safe_rel_path(MAPS_ROOT),
        "maps_root_absolute": str(MAPS_ROOT),
        "catalog_path": safe_rel_path(CATALOG_PATH),
        "catalog_path_absolute": str(CATALOG_PATH),
        "catalog_file_exists": CATALOG_PATH.exists(),
        "discovered_map_count": len(catalog),
        "available": [
            {"indicator": indicator, "period": period, "product": product, "scale": period_scale(period)}
            for indicator, period, product in sorted(available)
        ],
        "directories": directory_file_summary(),
        "expected_examples": [
            "rainfall_total_june_forecast.tif",
            "rainfall_total_june_climatology.tif",
            "rainfall_total_june_anomaly.tif",
            "spi_jjas_forecast.tif",
            "dryspell_prob_7d_jjas_forecast.tif",
            "rainfall_percentile_july_climatology.tif",
            "rainfall_total_week1_forecast.tif",
            "spi_week1_2_forecast.tif",
        ],
    }


@router.get("/options")
async def get_raster_options() -> Dict[str, Any]:
    catalog = list_catalog()
    available = {(item["indicator"], str(item["period"]), item["product"]) for item in catalog}
    return {
        "indicators": INDICATORS,
        "periods": ALL_PERIODS,
        "products": PRODUCTS,
        "scales": SCALES,
        "available_count": len(catalog),
        "available": [
            {"indicator": indicator, "period": period, "product": product, "scale": period_scale(period)}
            for indicator, period, product in sorted(available)
        ],
        "source_directories": {
            "geotiff": safe_rel_path(GEOTIFF_DIR),
            "netcdf": safe_rel_path(NETCDF_DIR),
            "csv": safe_rel_path(CSV_DIR),
            "cache": safe_rel_path(CACHE_DIR),
            "catalog": safe_rel_path(CATALOG_PATH),
        },
    }


@router.get("/catalog")
async def get_raster_catalog(include_statistics: bool = Query(False)) -> Dict[str, Any]:
    maps = [public_map_record(item, include_statistics=include_statistics) for item in list_catalog()]
    return {"maps": maps, "count": len(maps)}


@router.get("/map")
async def get_selected_raster_map(
    indicator: str = Query("spi"),
    period: str = Query("JJAS"),
    product: str = Query("forecast"),
) -> Dict[str, Any]:
    record = find_map_record(indicator, period, product)
    if not record:
        return {"map": None, "message": f"No raster map found for {indicator} {period} {product}."}
    return {"map": public_map_record(record, include_statistics=True)}


@router.get("/compare")
async def get_raster_compare(
    indicator: str = Query("spi"),
    period: str = Query("JJAS"),
) -> Dict[str, Any]:
    products = compare_products_for_indicator(indicator)
    maps: Dict[str, Any] = {}
    for product in products:
        record = find_map_record(indicator, period, product)
        maps[product] = public_map_record(record, include_statistics=True) if record else None

    # SPI's compare view reuses the "forecast" slot to show the median SPI
    # raster (there's no separate "median" product key -- see
    # STAT_TOKEN_PRIORITY, which already makes "forecast" resolve to the
    # _median file for SPI). Relabel just the display text here so the panel
    # reads "Median" instead of the generic "Forecast" the rest of the app uses.
    if indicator == "spi" and maps.get("forecast"):
        relabeled = dict(maps["forecast"])
        relabeled["product_label"] = "Median"
        relabeled["title"] = f"{relabeled.get('indicator_label', 'SPI')} · {relabeled.get('period_label', period)} · Median"
        maps["forecast"] = relabeled

    return {"indicator": indicator, "period": period, "products": products, "maps": maps}


@router.get("/statistics/{map_id}")
async def get_statistics(map_id: str) -> Dict[str, Any]:
    record = require_map(map_id)
    return {"map_id": map_id, "statistics": get_map_statistics_cached(map_id), "units": record.get("units", "")}


@router.get("/value/{map_id}")
async def get_value_at_point(
    map_id: str,
    lat: float = Query(...),
    lon: float = Query(...),
) -> Dict[str, Any]:
    try:
        import rasterio
        from rasterio.warp import transform
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Point sampling requires rasterio.") from exc

    record = require_map(map_id)
    path = ensure_geotiff(record)
    with rasterio.open(path) as src:
        x, y = lon, lat
        if src.crs and str(src.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
            xs, ys = transform("EPSG:4326", src.crs, [lon], [lat])
            x, y = xs[0], ys[0]
        row, col = src.index(x, y)
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
        "formatted_value": format_value(value, units),
    }


def mercator_tile_lonlat_bounds(x: int, y: int, z: int) -> Tuple[float, float, float, float]:
    """Return XYZ tile bounds as west, south, east, north in EPSG:4326."""
    n = 2.0 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def tile_y_to_lat(tile_y: int) -> float:
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n)))
        return math.degrees(lat_rad)

    north = tile_y_to_lat(y)
    south = tile_y_to_lat(y + 1)
    return west, south, east, north


def tile_intersects_record_bounds(record: Dict[str, Any], x: int, y: int, z: int) -> bool:
    bounds = record.get("bounds") or DEFAULT_BOUNDS
    if isinstance(bounds, list) and len(bounds) == 4:
        west, south, east, north = bounds[0], bounds[1], bounds[2], bounds[3]
    else:
        west = bounds.get("west", DEFAULT_BOUNDS["west"])
        east = bounds.get("east", DEFAULT_BOUNDS["east"])
        south = bounds.get("south", DEFAULT_BOUNDS["south"])
        north = bounds.get("north", DEFAULT_BOUNDS["north"])

    raw_west, raw_east, raw_south, raw_north = float(west), float(east), float(south), float(north)
    west = min(raw_west, raw_east) - DEFAULT_TILE_BUFFER_DEGREES
    east = max(raw_west, raw_east) + DEFAULT_TILE_BUFFER_DEGREES
    south = min(raw_south, raw_north) - DEFAULT_TILE_BUFFER_DEGREES
    north = max(raw_south, raw_north) + DEFAULT_TILE_BUFFER_DEGREES

    tw, ts, te, tn = mercator_tile_lonlat_bounds(x, y, z)
    return not (te < west or tw > east or tn < south or ts > north)


def transparent_png_tile(note: str = "") -> Response:
    try:
        from PIL import Image
        image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        headers = {"Cache-Control": "public, max-age=86400"}
        if note:
            headers["X-Seasonal-Raster-Tile-Note"] = note[:180]
        return Response(content=buffer.getvalue(), media_type="image/png", headers=headers)
    except Exception:
        return Response(content=b"", media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/tiles/{map_id}/{z}/{x}/{y}.png")
async def get_tile(map_id: str, z: int, x: int, y: int) -> Response:
    try:
        import numpy as np
        from PIL import Image
        from rio_tiler.io import Reader
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Raster tile service requires rio-tiler, rasterio, pillow, numpy, and matplotlib. Install: pip install rio-tiler rasterio pillow numpy matplotlib") from exc

    record = require_map(map_id)
    if not tile_intersects_record_bounds(record, x, y, z):
        return transparent_png_tile("outside raster bounds")

    path = ensure_geotiff(record)
    stats = get_map_statistics_cached(map_id)
    config = get_render_config(record, stats)
    vmin = config["vmin"]
    vmax = config["vmax"]

    try:
        with Reader(str(path)) as src:
            tile = src.tile(x, y, z, indexes=1)
    except Exception as exc:
        # Leaflet requests neighboring tiles outside the raster footprint while panning/zooming.
        # Returning a transparent 200 PNG avoids visible broken white bands and console 404 noise.
        return transparent_png_tile(f"empty or outside raster extent: {exc}")

    band = tile.data[0].astype("float32")
    band = clean_array_for_display(band)
    mask = tile.mask
    valid_mask = (mask > 0) & np.isfinite(band)

    rgba = render_array_to_rgba(band, valid_mask, vmin, vmax, config["cmap"])
    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(content=buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/image/{map_id}.png")
async def get_full_image(map_id: str) -> Response:
    """Render the entire map as a single PNG, clipped to Ethiopia's border.

    Used by the frontend as a Leaflet ImageOverlay instead of an XYZ tile
    pyramid. For a small, fixed-extent raster like this, tiling is unnecessary
    machinery that introduces its own rendering seams (see mapSwitcher.css
    history); one image avoids that entirely and lets the browser's normal
    image scaling smooth the coarse source grid for free.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Raster image rendering requires pillow, rasterio, numpy, and matplotlib.") from exc

    record = require_map(map_id)
    arr, transform, bounds = load_display_array(record)
    stats = get_map_statistics_cached(map_id)
    config = get_render_config(record, stats)

    # Source grids are extremely coarse (often ~48x60 px for all of Ethiopia).
    # Smoothly upsampling the *values* -- while rasterizing the country border
    # mask directly at the upsampled resolution, rather than stretching the
    # coarse one -- gives a clean gradient with a crisp, accurate border. A
    # naive post-hoc resize of the whole colored+masked image (tried first)
    # instead revealed the coarse mask's own blocky edges as visible ringing.
    long_side = max(arr.shape)
    scale_factor = max(1.0, FULL_IMAGE_MIN_LONG_SIDE / long_side) if long_side else 1.0

    if scale_factor > 1.0:
        render_arr, upsampled_valid_fraction = upsample_value_array(arr, scale_factor)
        high_res_transform = scaled_transform(transform, scale_factor)
        country_mask = rasterize_country_mask(render_arr.shape, high_res_transform)
        valid_mask = (upsampled_valid_fraction > 0.5) & country_mask
    else:
        render_arr = arr
        valid_mask = np.isfinite(arr)

    # The frontend displays this image with a plain Leaflet ImageOverlay,
    # which stretches it linearly between lat/lng corners onto the map's Web
    # Mercator projection. Our rows are evenly spaced in latitude, which is
    # NOT linear in Mercator Y, so without this the raster visibly drifts
    # away from the true basemap geography away from the vertical center.
    render_arr = remap_rows_equirect_to_mercator(render_arr, bounds["south"], bounds["north"], order=1)
    valid_mask = remap_rows_equirect_to_mercator(valid_mask.astype("float32"), bounds["south"], bounds["north"], order=0) > 0.5

    rgba = render_array_to_rgba(render_arr, valid_mask, config["vmin"], config["vmax"], config["cmap"])
    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    # This endpoint's rendering logic is still actively changing during
    # development; a long max-age here previously meant fixes silently didn't
    # show up in an already-open tab until the browser's HTTP cache expired.
    # ImageOverlay only fetches this once per map view anyway (unlike XYZ
    # tiles), so there's no real caching benefit worth trading for that.
    return Response(content=buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/grid/{map_id}")
async def get_value_grid(map_id: str) -> Dict[str, Any]:
    """Return the map's clipped values as a compact native-resolution grid.

    Lets the frontend look up a value under the cursor instantly on hover
    (nearest-cell lookup, client side) instead of calling /value on every
    mousemove. The source forecast grids are coarse (tens of cells per side),
    so this payload stays small even though it is the full array.
    """
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


@router.post("/refresh")
async def refresh_raster_catalog() -> Dict[str, Any]:
    load_catalog_cached.cache_clear()
    get_map_statistics_cached.cache_clear()
    return {"status": "refreshed", "count": len(list_catalog())}


def prewarm_all_maps() -> List[Dict[str, Any]]:
    """Convert and cache every catalog map's display GeoTIFF and statistics.

    Without this, the first user to view any indicator/period/product pays
    the NetCDF/CSV -> GeoTIFF conversion cost inline in their request (see
    ensure_geotiff). Calling this once after deploy or on a schedule moves
    that cost out of the request path.
    """
    results: List[Dict[str, Any]] = []
    for record in list_catalog():
        try:
            ensure_geotiff(record)
            get_map_statistics_cached(record["id"])
            results.append({"id": record["id"], "status": "ok"})
        except HTTPException as exc:
            results.append({"id": record.get("id"), "status": "error", "detail": exc.detail})
        except Exception as exc:  # pragma: no cover - defensive: keep prewarming other maps
            results.append({"id": record.get("id"), "status": "error", "detail": str(exc)})
    enforce_cache_size_limit()
    return results


@router.post("/prewarm")
async def prewarm_raster_cache(background_tasks: BackgroundTasks, wait: bool = Query(False)) -> Dict[str, Any]:
    """Pre-convert and cache all catalog maps so the first map view is fast.

    By default this queues the work as a background task and returns
    immediately, since prewarming every map can take a while the first time.
    Pass ?wait=true to run synchronously and get per-map results back.
    """
    catalog = list_catalog()
    if wait:
        return {"status": "completed", "count": len(catalog), "results": prewarm_all_maps()}

    background_tasks.add_task(prewarm_all_maps)
    return {"status": "queued", "count": len(catalog)}
