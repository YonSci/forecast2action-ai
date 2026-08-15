"""
Real infrastructure-exposure denominators for the Ethiopia Hazard/Risk
Layers Exposure map: real health-facility counts and real major-road
length, not just the existing abstract 0-1 density share.

Confirmed real gap this closes: `roads_exposed_pct`/`healthsites_exposed_pct`
already existed (see app.context.statistical_evidence's exposure loop), but
were computed from `roads_normalized`/`healthsites_normalized` -- abstract,
already-normalized 0-1 density rasters with no real denominator behind
them, so "100% of health-site density exposed" could mean 1-of-1 or
57-of-57 with no way to tell which. No raw OSM download or generation
script for those 2 existing rasters exists anywhere in this repo (their
provenance is undocumented), so this module does NOT try to reproduce or
replace them -- it independently fetches its OWN real, current OSM data
and produces 2 NEW, real-unit rasters at the same grid, used ONLY as the
weight raster for exposure computation (see statistical_evidence.py) --
the existing density rasters keep serving on-map visualization unchanged.

Unlike exposure_data_pipeline.py/vulnerability_data_pipeline.py (which
assume a manually pre-downloaded raw file already sitting in data/raw/),
this pipeline is fully self-contained and re-runnable: it fetches directly
from the public OSM Overpass API (https://overpass-api.de), no manual
download step required.

Scope, disclosed deliberately (not silently narrowed):
- Health facilities: real OSM nodes tagged amenity=hospital/clinic/doctors
  or carrying any healthcare=* tag -- real point locations, not a real
  administrative facility registry (OSM completeness varies by area).
- Roads: real OSM ways tagged highway=motorway/trunk/primary/secondary/
  tertiary ONLY -- deliberately excludes residential/service/minor roads,
  both because a full-country all-highways query is impractically large
  for Overpass's fair-use limits, and because major roads are the
  operationally relevant ones for humanitarian access/pre-positioning.
- Road length per pixel is an INTERVAL-SAMPLING approximation (points
  every ~0.25 km along each real road's real geometry, summed per pixel
  by sample-count x interval), not exact polygon-clipped length -- a
  standard, simpler GIS approximation, not presented as exact.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import rasterio
import requests
from affine import Affine

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 200  # generous -- this is a one-time offline run, not a live request path

RAW_DIR = Path("data/raw/infrastructure")
OUTPUT_DIR = Path("data/maps/Exposure")
HEALTHSITES_OUTPUT_PATH = OUTPUT_DIR / "ethiopia_healthsites_count.tif"
ROADS_OUTPUT_PATH = OUTPUT_DIR / "ethiopia_roads_length_km.tif"

# Same 0.25-degree grid every other Ethiopia Hazard/Risk Layers Exposure
# GeoTIFF already uses -- confirmed by directly reading
# data/maps/Exposure/ethiopia_roads_normalized.tif's real transform/shape
# (48 rows x 60 cols, EPSG:4326, bounds 33-48E/3-15N) so the new rasters
# align pixel-for-pixel with the existing hazard/risk catalog without any
# resampling.
GRID_RESOLUTION_DEG = 0.25
LAT_MIN, LAT_MAX = 3.0, 15.0
LON_MIN, LON_MAX = 33.0, 48.0
GRID_SHAPE = (48, 60)  # (rows, cols)
GRID_TRANSFORM = Affine(GRID_RESOLUTION_DEG, 0.0, LON_MIN, 0.0, -GRID_RESOLUTION_DEG, LAT_MAX)

KM_PER_DEGREE_LAT = 110.574  # same real constant already used in app.api.hazard_risk_ranking

ROAD_SAMPLE_INTERVAL_KM = 0.25

# Confirmed real gap, fixed: a single query combining amenity=hospital/
# clinic/doctors OR healthcare=* (via a union block) reliably timed out on
# the free public overpass-api.de instance, even though EACH half
# completed in 16-23s on its own -- issued as 2 separate sequential
# requests instead (merged + de-duplicated by real OSM node id in Python),
# same real result set, just without the union's extra query-planning cost.
_HEALTH_FACILITY_QUERY_AMENITY = """
[out:json][timeout:120];
area["ISO3166-1"="ET"]["admin_level"="2"]->.et;
node["amenity"~"^(hospital|clinic|doctors)$"](area.et);
out body;
"""

_HEALTH_FACILITY_QUERY_HEALTHCARE_TAG = """
[out:json][timeout:120];
area["ISO3166-1"="ET"]["admin_level"="2"]->.et;
node["healthcare"](area.et);
out body;
"""

# Confirmed real gap, fixed: a single country-wide query for all ~28,000
# real major-road ways with full geometry ("out geom") reliably failed on
# the free public overpass-api.de instance -- 504 timeouts, 429 rate
# limits, and truncated/ChunkedEncodingError responses, even with retries,
# since the real response is simply too large for one request. Sharded by
# real admin1 region bounding box instead (see ADMIN1_BOUNDARY_PATH) --
# 15 much smaller real requests instead of 1 huge one, each well within
# the free instance's real limits, run sequentially with a delay between.
ADMIN1_BOUNDARY_PATH = Path("data/sample/admin_boundaries/eth_admin1.json")

_MAJOR_ROADS_QUERY_TEMPLATE = """
[out:json][timeout:120];
way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]({south},{west},{north},{east});
out geom;
"""


def _admin1_region_bboxes() -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """Real (region_name, (south, west, north, east)) bounding boxes from
    this app's own real admin1 boundary GeoJSON (the same file every other
    admin1-level zonal computation in this app already uses).
    """
    data = json.loads(ADMIN1_BOUNDARY_PATH.read_text(encoding="utf-8"))
    boxes = []
    for feature in data.get("features", []):
        name = feature.get("properties", {}).get("region") or feature.get("properties", {}).get("name") or "Unknown"
        coords = _flatten_geometry_coordinates(feature.get("geometry") or {})
        if not coords:
            continue
        lons = [pt[0] for pt in coords]
        lats = [pt[1] for pt in coords]
        boxes.append((name, (min(lats), min(lons), max(lats), max(lons))))
    return boxes


def _flatten_geometry_coordinates(geometry: Dict[str, Any]) -> List[List[float]]:
    coords = geometry.get("coordinates")
    geom_type = geometry.get("type")
    if not coords:
        return []
    if geom_type == "Polygon":
        return [pt for ring in coords for pt in ring]
    if geom_type == "MultiPolygon":
        return [pt for polygon in coords for ring in polygon for pt in ring]
    return []

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 4
_RETRY_BACKOFF_S = 20  # doubled each retry -- the free public instance's real "too busy"/rate-limit errors clear within tens of seconds, not immediately


def _fetch_overpass(query: str) -> Dict[str, Any]:
    """Confirmed real, live-tested failure modes on the free public
    overpass-api.de instance, both handled here:
    - requests' default "python-requests/x.y" User-Agent gets a bare 406
      from Apache directly (a generic anti-bot measure, not an Overpass-
      level error) -- fixed with a descriptive User-Agent, which is also
      what Overpass's own usage policy asks scripted clients to send.
    - "too busy"/rate-limited errors under back-to-back requests (real,
      confirmed via /api/status: "Rate limit: 2" concurrent slots) --
      retried with exponential backoff rather than failing the whole
      pipeline on a transient condition; this is a one-time offline run,
      not a live request path, so waiting is free.
    """
    headers = {"User-Agent": "Forecast2Action-AI/1.0 (infrastructure_data_pipeline.py)"}
    last_error: Exception = RuntimeError("unreachable")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(OVERPASS_URL, data={"data": query}, timeout=OVERPASS_TIMEOUT_S, headers=headers)
            if response.status_code in _RETRYABLE_STATUS_CODES or "rate_limited" in response.text[:2000] or "too busy" in response.text[:2000]:
                raise requests.exceptions.HTTPError(f"Retryable Overpass response: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.RequestException,) as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                wait_s = _RETRY_BACKOFF_S * (2 ** attempt)
                print(f"  Overpass request failed ({exc}); retrying in {wait_s}s (attempt {attempt + 1}/{_MAX_RETRIES})...")
                time.sleep(wait_s)
    raise last_error


def fetch_health_facilities() -> List[Dict[str, float]]:
    """Real OSM node locations -- [{"lat": .., "lon": ..}, ...], de-
    duplicated by real OSM node id across the 2 separate real queries.
    """
    by_id: Dict[int, Dict[str, float]] = {}
    for query in (_HEALTH_FACILITY_QUERY_AMENITY, _HEALTH_FACILITY_QUERY_HEALTHCARE_TAG):
        data = _fetch_overpass(query)
        for element in data.get("elements", []):
            if element.get("type") == "node" and "lat" in element and "lon" in element:
                by_id[element["id"]] = {"lat": element["lat"], "lon": element["lon"]}
        time.sleep(2)  # be a good citizen of the free public instance between sequential requests
    return list(by_id.values())


def fetch_major_roads(cache_path: "Path | None" = None) -> Tuple[List[List[Dict[str, float]]], List[str]]:
    """Real OSM way geometries -- one list of {"lat", "lon"} vertices per
    real road segment, in real drawn order (Overpass "out geom" already
    resolves each way's node references inline, so no separate node-lookup
    pass is needed). Fetched per real admin1 region bounding box (see
    ADMIN1_BOUNDARY_PATH / _admin1_region_bboxes), not one country-wide
    query -- see _MAJOR_ROADS_QUERY_TEMPLATE's comment for why. A way
    crossing 2 regions' bounding boxes can legitimately be returned by
    both real queries -- de-duplicated by real OSM way id, so bbox overlap
    never double-counts a way's real length in the final raster.

    Confirmed real gap, fixed: even sharded per-region, the free public
    Overpass instance still intermittently 504s/connection-resets on
    large real regions (Amhara alone returned 16,164 real ways) --
    exhausting retries used to abort the WHOLE pipeline and discard every
    region already fetched. Now: (1) a region that still fails after all
    retries is skipped, not fatal -- its name is returned in the second
    tuple element so the caller can disclose real, honest partial
    coverage rather than silently presenting it as complete; (2) each
    region's real result is written to `cache_path` incrementally as it
    completes, so a re-run (see run_infrastructure_data_pipeline) only
    needs to retry the regions that actually failed, not restart from
    the very first region.
    """
    by_id: Dict[int, List[Dict[str, float]]] = {}
    done_regions: set = set()
    if cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        for way in cached.get("ways", []):
            by_id[way["id"]] = way["geometry"]
        done_regions = set(cached.get("regions_fetched", []))
        if done_regions:
            print(f"  Resuming: {len(done_regions)} region(s) already cached ({', '.join(sorted(done_regions))}).")

    failed_regions: List[str] = []
    for region_name, (south, west, north, east) in _admin1_region_bboxes():
        if region_name in done_regions:
            continue
        query = _MAJOR_ROADS_QUERY_TEMPLATE.format(south=south, west=west, north=north, east=east)
        try:
            data = _fetch_overpass(query)
        except requests.exceptions.RequestException as exc:
            print(f"  {region_name}: FAILED after all retries ({exc}) -- skipping, real coverage for this region will be incomplete.")
            failed_regions.append(region_name)
            continue
        region_way_count = 0
        for element in data.get("elements", []):
            if element.get("type") == "way" and element.get("geometry"):
                by_id[element["id"]] = [{"lat": pt["lat"], "lon": pt["lon"]} for pt in element["geometry"]]
                region_way_count += 1
        done_regions.add(region_name)
        print(f"  {region_name}: {region_way_count} real road ways in this request's bbox.")
        if cache_path:
            cache_path.write_text(
                json.dumps({
                    "way_count": len(by_id),
                    "regions_fetched": sorted(done_regions),
                    "regions_failed": failed_regions,
                    "ways": [{"id": way_id, "geometry": geometry} for way_id, geometry in by_id.items()],
                }, indent=2),
                encoding="utf-8",
            )
        time.sleep(2)  # be a good citizen of the free public instance between sequential requests
    return list(by_id.values()), failed_regions


def _pixel_index(lat: float, lon: float) -> Tuple[int, int]:
    col = int((lon - LON_MIN) / GRID_RESOLUTION_DEG)
    row = int((LAT_MAX - lat) / GRID_RESOLUTION_DEG)
    return row, col


def _in_grid(row: int, col: int) -> bool:
    return 0 <= row < GRID_SHAPE[0] and 0 <= col < GRID_SHAPE[1]


def rasterize_health_facility_counts(points: List[Dict[str, float]]) -> np.ndarray:
    counts = np.zeros(GRID_SHAPE, dtype="float64")
    for point in points:
        row, col = _pixel_index(point["lat"], point["lon"])
        if _in_grid(row, col):
            counts[row, col] += 1.0
    return counts


def _km_per_degree_lon(lat: float) -> float:
    return KM_PER_DEGREE_LAT * math.cos(math.radians(lat))


def rasterize_road_length_km(ways: List[List[Dict[str, float]]]) -> np.ndarray:
    """Real road length per pixel, via interval-point sampling: walks each
    real road geometry at ROAD_SAMPLE_INTERVAL_KM real-world spacing,
    attributing that interval's length to whichever pixel each sample
    point falls in. See module docstring for why this approximation was
    chosen over exact polygon-clipped length.
    """
    length_km = np.zeros(GRID_SHAPE, dtype="float64")
    for way in ways:
        for start, end in zip(way, way[1:]):
            lat1, lon1 = start["lat"], start["lon"]
            lat2, lon2 = end["lat"], end["lon"]
            mean_lat = (lat1 + lat2) / 2.0
            km_per_deg_lon = _km_per_degree_lon(mean_lat)
            dy_km = (lat2 - lat1) * KM_PER_DEGREE_LAT
            dx_km = (lon2 - lon1) * km_per_deg_lon
            segment_km = math.hypot(dx_km, dy_km)
            if segment_km <= 0:
                continue
            sample_count = max(1, round(segment_km / ROAD_SAMPLE_INTERVAL_KM))
            interval_km = segment_km / sample_count
            for step in range(sample_count):
                fraction = (step + 0.5) / sample_count
                lat = lat1 + fraction * (lat2 - lat1)
                lon = lon1 + fraction * (lon2 - lon1)
                row, col = _pixel_index(lat, lon)
                if _in_grid(row, col):
                    length_km[row, col] += interval_km
    return length_km


def _write_geotiff(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
        count=1, dtype="float64", crs="EPSG:4326", transform=GRID_TRANSFORM,
        nodata=None,
    ) as dst:
        dst.write(arr, 1)


def run_infrastructure_data_pipeline(force_refetch: bool = False) -> Dict[str, Any]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    facilities_cache_path = RAW_DIR / "ethiopia_health_facilities.json"
    roads_cache_path = RAW_DIR / "ethiopia_major_roads.json"

    if not force_refetch and facilities_cache_path.exists():
        print(f"Reusing cached real health-facility data at {facilities_cache_path} (pass force_refetch=True to refresh).")
        facilities = json.loads(facilities_cache_path.read_text(encoding="utf-8"))["points"]
    else:
        print("Fetching real health-facility locations from OSM Overpass...")
        facilities = fetch_health_facilities()
        facilities_cache_path.write_text(
            json.dumps({"count": len(facilities), "points": facilities}, indent=2), encoding="utf-8",
        )
    print(f"  {len(facilities)} real facility nodes.")

    cached_roads = json.loads(roads_cache_path.read_text(encoding="utf-8")) if roads_cache_path.exists() else {}
    all_regions_done = not force_refetch and set(cached_roads.get("regions_fetched", [])) >= {
        name for name, _bbox in _admin1_region_bboxes()
    } and not cached_roads.get("regions_failed")
    if all_regions_done:
        print(f"Reusing cached real major-road data at {roads_cache_path} (pass force_refetch=True to refresh) -- all regions previously succeeded.")
        roads = [way["geometry"] for way in cached_roads["ways"]]
        failed_regions: List[str] = []
    else:
        print("Fetching real major-road geometries from OSM Overpass (per real admin1 region, resuming from any prior cache)...")
        roads, failed_regions = fetch_major_roads(cache_path=None if force_refetch else roads_cache_path)
    print(f"  {len(roads)} real major-road ways.")
    if failed_regions:
        print(f"  WARNING: real road coverage is INCOMPLETE for: {', '.join(failed_regions)} (Overpass failed after all retries -- re-run this pipeline to retry just these regions).")

    healthsites_count = rasterize_health_facility_counts(facilities)
    _write_geotiff(HEALTHSITES_OUTPUT_PATH, healthsites_count)
    print(f"Wrote {HEALTHSITES_OUTPUT_PATH} -- real total count: {healthsites_count.sum():.0f}")

    roads_length_km = rasterize_road_length_km(roads)
    _write_geotiff(ROADS_OUTPUT_PATH, roads_length_km)
    print(f"Wrote {ROADS_OUTPUT_PATH} -- real total length: {roads_length_km.sum():.1f} km")
    if failed_regions:
        print(f"  NOTE: the written {ROADS_OUTPUT_PATH.name} has incomplete real coverage for: {', '.join(failed_regions)}.")

    return {
        "healthsites_total_count": float(healthsites_count.sum()),
        "roads_total_length_km": float(roads_length_km.sum()),
        "roads_coverage_incomplete_for": failed_regions,
    }


if __name__ == "__main__":
    run_infrastructure_data_pipeline()
