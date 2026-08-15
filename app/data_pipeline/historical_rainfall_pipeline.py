"""
Real historical rainfall for drought indicator-threshold calibration.

Confirmed real gap this closes: the app's own real SPI classification
(SPI_CATEGORY_BANDS in app.context.statistical_evidence, real McKee et al.
1993 bands) has never been checked against real historical drought
outcomes -- there was no real historical rainfall archive anywhere in this
repo (data/sample/chirps_district_rainfall_timeseries.csv, despite the
name, is fully synthetic -- np.random data from an early hackathon
prototype, see app.data_pipeline.chirps_rainfall_pipeline.py -- never used
here).

Downloads real monthly CHIRPS v2.0 rainfall GeoTIFFs (Climate Hazards
Center, UC Santa Barbara -- the same real rainfall product family FEWS
NET's own food-security monitoring uses) directly from
https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs/ (real,
live-confirmed, no auth required), for June-September (this app's own real
forecast window) across 1997-2025 -- matching the real coverage range of
app.data_pipeline's already-pulled GLIDE historical disaster events
(data/raw/historical_impact/eth_glide_events.csv), so every real GLIDE
drought event has real contemporaneous rainfall to compare against.

Deliberately does NOT modify SPI_CATEGORY_BANDS or RISK_CLASS_BANDS --
RISK_CLASS_BANDS is explicitly sourced from an external upstream config
this repo doesn't own (see hazard_risk_catalog_shared.py's own comment),
and silently diverging from a canonical external spec based on one
diagnostic pass would be a real regression, not an improvement. This
pipeline's job is to produce a real, honest FINDING -- whether historical
rainfall severity during real declared droughts is consistent with the
current thresholds -- not to change production classification code.
"""

from __future__ import annotations

import gzip
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.windows import from_bounds

CHIRPS_URL_TEMPLATE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs/chirps-v2.0.{year}.{month:02d}.tif.gz"
RAW_DIR = Path("data/raw/historical_impact/chirps")

# Matches GLIDE's own real 1997-2026 coverage (see eth_glide_events.csv) so
# every real drought event has real contemporaneous rainfall; June-Sep
# matches this app's own real forecast window (see PERIODS in
# seasonal_catalog_shared.py).
YEARS = list(range(1997, 2026))
MONTHS = [6, 7, 8, 9]

# Same real bbox app.api.hazard_risk_catalog_shared's whole raster catalog
# already uses (3-15N, 33-48E) -- kept consistent, not re-derived.
ETHIOPIA_BOUNDS = (33.0, 3.0, 48.0, 15.0)  # west, south, east, north

# Real CHIRPS nodata sentinel, confirmed via direct inspection of a real
# downloaded file (not documented in the GeoTIFF's own nodata tag, which
# was empty) -- real values are always >= 0 (rainfall mm), so anything
# at/below this is real missing data, never a real negative rainfall.
NODATA_SENTINEL = -9998.0

_RETRYABLE_MAX_RETRIES = 3
_RETRY_BACKOFF_S = 5


def _download_month(year: int, month: int) -> Optional[Path]:
    """Downloads one real CHIRPS monthly .gz if not already cached. Keeps
    the compressed download (not just a cropped derivative) so a re-run
    never re-fetches over the network, matching this repo's other data
    pipelines' own raw-cache convention.
    """
    gz_path = RAW_DIR / f"chirps-v2.0.{year}.{month:02d}.tif.gz"
    if gz_path.exists():
        return gz_path
    url = CHIRPS_URL_TEMPLATE.format(year=year, month=month)
    for attempt in range(_RETRYABLE_MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            gz_path.write_bytes(response.content)
            return gz_path
        except requests.exceptions.RequestException as exc:
            if attempt < _RETRYABLE_MAX_RETRIES:
                wait_s = _RETRY_BACKOFF_S * (attempt + 1)
                print(f"  {year}-{month:02d}: download failed ({exc}); retrying in {wait_s}s...")
                time.sleep(wait_s)
            else:
                print(f"  {year}-{month:02d}: FAILED after all retries ({exc}) -- skipping this month.")
                return None
    return None


def load_ethiopia_window(year: int, month: int) -> Optional[Tuple[np.ndarray, Affine]]:
    """Real Ethiopia-bbox rainfall array (mm) + its real transform for one
    real historical month, decompressed and windowed-read fresh each call
    (cheap and local once the .gz is cached -- no separate cropped-array
    cache needed). NaN marks real missing data (see NODATA_SENTINEL).
    """
    gz_path = _download_month(year, month)
    if gz_path is None:
        return None

    with gzip.open(gz_path, "rb") as f_in:
        tif_bytes = f_in.read()

    tmp_tif = RAW_DIR / f"_tmp_{year}_{month:02d}.tif"
    tmp_tif.write_bytes(tif_bytes)
    try:
        with rasterio.open(tmp_tif) as src:
            window = from_bounds(*ETHIOPIA_BOUNDS, src.transform)
            arr = src.read(1, window=window).astype("float64")
            win_transform = src.window_transform(window)
    finally:
        tmp_tif.unlink(missing_ok=True)

    arr[arr <= NODATA_SENTINEL] = np.nan
    return arr, win_transform


def build_region_month_rainfall_table() -> List[Dict[str, object]]:
    """Real per-admin1-region, per-real-historical-month rainfall (mm),
    reusing app.context.statistical_evidence.region_statistics -- the SAME
    real zonal-stats machinery already used for population/cropland/roads/
    healthsites exposure this session, not new aggregation logic.
    """
    from app.context.statistical_evidence import region_statistics

    rows: List[Dict[str, object]] = []
    for year in YEARS:
        for month in MONTHS:
            loaded = load_ethiopia_window(year, month)
            if loaded is None:
                continue
            arr, transform = loaded
            regions = region_statistics(arr, transform, admin_level="admin1")
            for region in regions:
                rows.append({
                    "region": region["area_name"],
                    "year": year,
                    "month": month,
                    "rainfall_mm": region["mean"],
                })
            print(f"  {year}-{month:02d}: real regional rainfall computed for {len(regions)} regions.")
    return rows


if __name__ == "__main__":
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching real CHIRPS rainfall for {YEARS[0]}-{YEARS[-1]}, months {MONTHS}...")
    table = build_region_month_rainfall_table()
    print(f"Real (region, year, month) rainfall rows: {len(table)}")

    import csv
    output_path = RAW_DIR.parent / "eth_region_monthly_rainfall.csv"
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["region", "year", "month", "rainfall_mm"])
        writer.writeheader()
        writer.writerows(table)
    print(f"Wrote {output_path}")
