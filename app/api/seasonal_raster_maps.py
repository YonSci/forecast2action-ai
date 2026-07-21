
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
    PRODUCT_BY_VALUE,
    PRODUCT_ORDER,
    PRODUCTS,
    PROJECT_ROOT,
    SCALES,
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

DEFAULT_BOUNDS = {"south": 3.0, "west": 33.0, "north": 15.0, "east": 48.0}

RASTER_EXTENSIONS = {".tif", ".tiff", ".nc", ".nc4", ".netcdf", ".csv"}
GEOTIFF_EXTENSIONS = {".tif", ".tiff"}
NETCDF_EXTENSIONS = {".nc", ".nc4", ".netcdf"}
CSV_EXTENSIONS = {".csv"}

INDICATOR_RENDERING = {
    "rainfall_total": {"cmap": "YlGnBu", "default_vmin": None, "default_vmax": None, "low_label": "Low rainfall", "high_label": "High rainfall"},
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
        "units": record.get("units") or indicator_meta.get("units") or "",
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


@lru_cache(maxsize=1)
def load_catalog_cached() -> Tuple[Dict[str, Dict[str, Any]], ...]:
    records = load_catalog_file() + scan_raster_files()
    by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    priority = {"catalog": 0, "geotiff": 1, "netcdf": 2, "csv": 3, "unknown": 4}

    for record in records:
        key = (record["indicator"], str(record["period"]).lower(), record["product"])
        existing = by_key.get(key)
        record_priority = 0 if record.get("source_type") == "catalog" else priority.get(record.get("source_format", "unknown"), 9)
        existing_priority = 99
        if existing:
            existing_priority = 0 if existing.get("source_type") == "catalog" else priority.get(existing.get("source_format", "unknown"), 9)
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


def calculate_statistics_from_path(path: Path) -> Dict[str, Any]:
    try:
        import numpy as np
        import rasterio
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Raster statistics require rasterio and numpy.") from exc

    with rasterio.open(path) as src:
        data = src.read(1, masked=True).astype("float64")
        values = data.compressed()
        values = values[np.isfinite(values)]
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
    path = ensure_geotiff(record)
    return calculate_statistics_from_path(path)


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
    cmap_name = record.get("cmap") or defaults["cmap"]
    if product == "anomaly" and not record.get("cmap") and indicator not in {"spi", "rainfall_percentile"}:
        cmap_name = "RdBu"

    stats = stats or {}
    vmin = record.get("vmin")
    vmax = record.get("vmax")
    if vmin is None:
        vmin = defaults.get("default_vmin")
    if vmax is None:
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

    return {
        "cmap": cmap_name,
        "vmin": float(vmin),
        "vmax": float(vmax),
        "low_label": defaults.get("low_label", "Low"),
        "high_label": defaults.get("high_label", "High"),
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

    return {
        "title": record.get("indicator_label", "Raster value"),
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
    maps: Dict[str, Any] = {}
    for product in PRODUCT_ORDER:
        record = find_map_record(indicator, period, product)
        maps[product] = public_map_record(record, include_statistics=True) if record else None
    return {"indicator": indicator, "period": period, "products": PRODUCT_ORDER, "maps": maps}


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

    scaled = np.zeros_like(band, dtype="float32")
    if float(vmax) != float(vmin):
        scaled = np.clip((band - vmin) / (vmax - vmin), 0, 1)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)

    colormap = get_matplotlib_cmap(config["cmap"])

    if colormap is not None:
        rgba = (colormap(scaled) * 255).astype("uint8")
    else:
        # Safe fallback if Matplotlib colormap lookup is unavailable.
        # This still returns a transparent PNG tile so the dashboard remains usable.
        rgba = np.zeros((scaled.shape[0], scaled.shape[1], 4), dtype="uint8")
        rgba[:, :, 0] = (scaled * 245).astype("uint8")
        rgba[:, :, 1] = (80 + scaled * 135).astype("uint8")
        rgba[:, :, 2] = (245 - scaled * 180).astype("uint8")
        rgba[:, :, 3] = 255

    rgba[:, :, 3] = np.where(valid_mask, rgba[:, :, 3], 0).astype("uint8")
    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(content=buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


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
