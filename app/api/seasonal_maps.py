import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.seasonal_catalog_shared import (
    INDICATOR_BY_VALUE,
    INDICATORS,
    PERIOD_BY_VALUE,
    PERIODS,
    PRODUCT_BY_VALUE,
    PRODUCTS,
    PROJECT_ROOT,
    infer_indicator,
    infer_period,
    infer_product,
    make_id,
    resolve_within,
    safe_read_json,
    safe_rel_path,
)

router = APIRouter(prefix="/api/seasonal-maps", tags=["Seasonal Climate Indicator Maps"])

SEASONAL_MAPS_DIR = Path(
    os.getenv("SEASONAL_MAPS_DIR", PROJECT_ROOT / "data" / "maps" / "Seasonal")
).resolve()
CATALOG_PATH = SEASONAL_MAPS_DIR / "seasonal_maps_catalog.json"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

DEFAULT_BOUNDS = {
    "south": 3.0,
    "west": 33.0,
    "north": 15.0,
    "east": 48.0,
}


def find_related_file(image_path: Path, extensions: set[str]) -> Optional[str]:
    candidates = []
    for extension in extensions:
        candidates.extend(image_path.parent.glob(f"{image_path.stem}{extension}"))
    if candidates:
        return safe_rel_path(candidates[0])
    return None


def enrich_record(record: Dict[str, Any], image_path: Optional[Path] = None) -> Dict[str, Any]:
    stem = image_path.stem if image_path else str(record.get("id") or record.get("image_path") or "seasonal_map")

    indicator = record.get("indicator") or infer_indicator(stem)
    period = record.get("period") or infer_period(stem)
    product = record.get("product") or infer_product(stem)

    indicator_meta = INDICATOR_BY_VALUE.get(indicator, {"value": indicator, "label": indicator.replace("_", " ").title(), "units": ""})
    period_meta = PERIOD_BY_VALUE.get(str(period).lower(), {"value": period, "label": str(period)})
    product_meta = PRODUCT_BY_VALUE.get(product, {"value": product, "label": str(product).replace("_", " ").title()})

    map_id = record.get("id") or make_id(f"{indicator}_{period}_{product}_{stem}")

    image_rel_path = record.get("image_path")
    if image_path:
        image_rel_path = safe_rel_path(image_path)

    geotiff_path = record.get("geotiff_path")
    netcdf_path = record.get("netcdf_path")
    if image_path:
        geotiff_path = geotiff_path or find_related_file(image_path, {".tif", ".tiff"})
        netcdf_path = netcdf_path or find_related_file(image_path, {".nc", ".nc4", ".netcdf"})

    enriched = {
        "id": map_id,
        "title": record.get("title") or f"{indicator_meta['label']} · {period_meta['label']} · {product_meta['label']}",
        "indicator": indicator,
        "indicator_label": record.get("indicator_label") or indicator_meta["label"],
        "period": period_meta["value"],
        "period_label": record.get("period_label") or period_meta["label"],
        "product": product,
        "product_label": record.get("product_label") or product_meta["label"],
        "image_path": image_rel_path,
        "image_url": f"/api/seasonal-maps/image/{map_id}",
        "geotiff_path": geotiff_path,
        "netcdf_path": netcdf_path,
        "bounds": record.get("bounds") or DEFAULT_BOUNDS,
        "units": record.get("units") or indicator_meta.get("units") or "",
        "init_date": record.get("init_date", ""),
        "valid_start": record.get("valid_start", ""),
        "valid_end": record.get("valid_end", ""),
        "forecast_source": record.get("forecast_source", ""),
        "forecast_system_version": record.get("forecast_system_version", ""),
        "n_ensemble_members": record.get("n_ensemble_members", ""),
        "observation_dataset": record.get("observation_dataset", ""),
        "climatology_period": record.get("climatology_period", ""),
        "source_type": record.get("source_type") or ("catalog" if not image_path else "auto_scanned_image"),
    }

    # Preserve any extra metadata fields supplied by a sidecar/catalog file.
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

    enriched = []
    for record in records:
        if not isinstance(record, dict):
            continue
        image_path = resolve_within(record.get("image_path"), [SEASONAL_MAPS_DIR])
        enriched.append(enrich_record(record, image_path if image_path and image_path.exists() else None))

    return enriched


def scan_image_catalog() -> List[Dict[str, Any]]:
    if not SEASONAL_MAPS_DIR.exists():
        return []

    records = []
    for image_path in sorted(SEASONAL_MAPS_DIR.rglob("*")):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        # Read optional sidecar metadata with the same stem.
        record = safe_read_json(image_path.with_suffix(".json")) or {}
        records.append(enrich_record(record, image_path=image_path))

    return records


def load_catalog() -> List[Dict[str, Any]]:
    catalog_records = load_catalog_file()
    scanned_records = scan_image_catalog()

    by_id: Dict[str, Dict[str, Any]] = {}
    for record in catalog_records + scanned_records:
        by_id[record["id"]] = record

    return sorted(
        by_id.values(),
        key=lambda item: (
            str(item.get("indicator")),
            str(item.get("period")),
            str(item.get("product")),
            str(item.get("title")),
        ),
    )


def option_filter(catalog: List[Dict[str, Any]], base_options: List[Dict[str, str]], key: str) -> List[Dict[str, str]]:
    available = {str(item.get(key)) for item in catalog if item.get(key)}
    options = []
    for option in base_options:
        if not available or option["value"] in available:
            options.append(option)
    # Add any custom options found in file names/catalog.
    existing = {item["value"] for item in options}
    for value in sorted(available):
        if value and value not in existing:
            options.append({"value": value, "label": value.replace("_", " ").title()})
    return options


def find_map_by_id(map_id: str) -> Optional[Dict[str, Any]]:
    for record in load_catalog():
        if record.get("id") == map_id:
            return record
    return None


def image_file_path(record: Dict[str, Any]) -> Path:
    image_path = record.get("image_path")
    if not image_path:
        raise HTTPException(status_code=404, detail="Map image path is missing.")

    # Images are only ever served from SEASONAL_MAPS_DIR, even if a catalog
    # entry names a path elsewhere in the project -- this endpoint must never
    # become a way to read arbitrary files (e.g. .env) via a crafted catalog.
    path = resolve_within(image_path, [SEASONAL_MAPS_DIR])
    if path is None:
        raise HTTPException(status_code=403, detail="Map image path is outside the seasonal maps directory.")

    if not path.exists() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Map image file was not found.")

    return path


@router.get("/catalog")
async def get_seasonal_maps_catalog() -> Dict[str, Any]:
    catalog = load_catalog()
    return {
        "maps_dir": str(SEASONAL_MAPS_DIR),
        "catalog_path": str(CATALOG_PATH),
        "count": len(catalog),
        "maps": catalog,
    }


@router.get("/options")
async def get_seasonal_maps_options() -> Dict[str, Any]:
    catalog = load_catalog()
    return {
        "indicators": option_filter(catalog, INDICATORS, "indicator"),
        "periods": option_filter(catalog, PERIODS, "period"),
        "products": option_filter(catalog, PRODUCTS, "product"),
        "count": len(catalog),
        "maps_dir": str(SEASONAL_MAPS_DIR),
    }


@router.get("/selected")
async def get_selected_seasonal_map(
    indicator: str = Query(...),
    period: str = Query(...),
    product: str = Query(...),
) -> Dict[str, Any]:
    normalized_indicator = indicator.strip()
    normalized_period = period.strip().lower()
    normalized_product = product.strip().lower()

    catalog = load_catalog()
    for record in catalog:
        if (
            str(record.get("indicator", "")).lower() == normalized_indicator.lower()
            and str(record.get("period", "")).lower() == normalized_period
            and str(record.get("product", "")).lower() == normalized_product
        ):
            return {"found": True, "map": record}

    raise HTTPException(
        status_code=404,
        detail=f"No seasonal map found for indicator={indicator}, period={period}, product={product}.",
    )


@router.get("/compare")
async def get_compare_seasonal_maps(
    indicator: str = Query(...),
    period: str = Query(...),
) -> Dict[str, Any]:
    normalized_indicator = indicator.strip().lower()
    normalized_period = period.strip().lower()
    catalog = load_catalog()

    maps: Dict[str, Dict[str, Any]] = {}
    for record in catalog:
        if (
            str(record.get("indicator", "")).lower() == normalized_indicator
            and str(record.get("period", "")).lower() == normalized_period
        ):
            maps[str(record.get("product"))] = record

    return {
        "found": bool(maps),
        "indicator": indicator,
        "period": period,
        "maps": maps,
    }


@router.get("/image/{map_id}")
async def get_seasonal_map_image(map_id: str):
    record = find_map_by_id(map_id)
    if not record:
        raise HTTPException(status_code=404, detail="Seasonal map was not found.")

    path = image_file_path(record)
    return FileResponse(path)
