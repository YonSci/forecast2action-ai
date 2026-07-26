"""Shared indicator/period/product catalog metadata for seasonal climate maps.

Both app/api/seasonal_maps.py (static PNG catalog) and
app/api/seasonal_raster_maps.py (interactive raster tile service) describe the
same set of climate indicators, seasonal periods, and map products. This
module is the single source of truth for that vocabulary so the two routers
(and the frontend, via the /options endpoints) stay in sync when a new
indicator/period/product is added.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INDICATORS = [
    {"value": "rainfall_total", "label": "Rainfall Total", "units": "mm"},
    {"value": "spi", "label": "SPI", "units": "standardized index"},
    {"value": "cdd", "label": "CDD", "units": "days"},
    {"value": "cwd", "label": "CWD", "units": "days"},
    {"value": "rx1day", "label": "Rx1day", "units": "mm"},
    {"value": "rx5day", "label": "Rx5day", "units": "mm"},
    {"value": "dryspell_prob_5d", "label": "Dry spell probability ≥5 days", "units": "probability"},
    {"value": "dryspell_prob_7d", "label": "Dry spell probability ≥7 days", "units": "probability"},
    {"value": "dryspell_prob_9d", "label": "Dry spell probability ≥9 days", "units": "probability"},
    {"value": "rainfall_percentile", "label": "Rainfall Percentile", "units": "percentile"},
]

PERIODS = [
    {"value": "June", "label": "June", "scale": "seasonal"},
    {"value": "July", "label": "July", "scale": "seasonal"},
    {"value": "August", "label": "August", "scale": "seasonal"},
    {"value": "September", "label": "September", "scale": "seasonal"},
    {"value": "JJAS", "label": "JJAS", "scale": "seasonal"},
]

# Subseasonal periods (weekly forecast windows). Filenames use tokens like
# "week1" / "week1_2" (see SUBSEASONAL_PERIOD_PATTERNS); canonical values use
# the "week_1" / "week_1_2" style already used for the hazard/risk lead options
# on the frontend, for a consistent naming convention across the app.
SUBSEASONAL_PERIODS = [
    {"value": "week_1", "label": "Week 1", "scale": "subseasonal"},
    {"value": "week_2", "label": "Week 2", "scale": "subseasonal"},
    {"value": "week_3", "label": "Week 3", "scale": "subseasonal"},
    {"value": "week_4", "label": "Week 4", "scale": "subseasonal"},
    {"value": "week_1_2", "label": "Week 1-2", "scale": "subseasonal"},
    {"value": "week_2_3", "label": "Week 2-3", "scale": "subseasonal"},
    {"value": "week_3_4", "label": "Week 3-4", "scale": "subseasonal"},
    {"value": "week_1_3", "label": "Week 1-3", "scale": "subseasonal"},
    {"value": "week_2_4", "label": "Week 2-4", "scale": "subseasonal"},
]

ALL_PERIODS = SUBSEASONAL_PERIODS + PERIODS

SCALES = [
    {"value": "subseasonal", "label": "Subseasonal"},
    {"value": "seasonal", "label": "Seasonal"},
]

PRODUCTS = [
    {"value": "forecast", "label": "Forecast"},
    {"value": "climatology", "label": "Climatology"},
    {"value": "anomaly", "label": "Anomaly"},
    {"value": "drought_probability", "label": "Drought Probability"},
    {"value": "wet_probability", "label": "Wet Probability"},
]

INDICATOR_BY_VALUE = {item["value"]: item for item in INDICATORS}
PERIOD_BY_VALUE = {item["value"].lower(): item for item in ALL_PERIODS}
PRODUCT_BY_VALUE = {item["value"]: item for item in PRODUCTS}
PRODUCT_ORDER = ["forecast", "climatology", "anomaly"]

# SPI's 3-map compare view shows different content than other indicators: the
# median forecast, P(SPI <= -1.0) drought probability, and P(SPI >= +1.0) wet
# probability, instead of Forecast/Climatology/Anomaly (SPI has no
# climatology/anomaly rasters at all -- it's a standardized index, not a raw
# quantity with a "normal" to compare against). Indicators not listed here
# keep the default Forecast/Climatology/Anomaly triplet.
INDICATOR_COMPARE_PRODUCTS = {
    "spi": ["forecast", "drought_probability", "wet_probability"],
}

PROBABILITY_PRODUCTS = {
    "drought_probability": {
        "cmap": "YlOrRd",
        "vmin": 0.0,
        "vmax": 1.0,
        "low_label": "Low drought probability",
        "high_label": "High drought probability",
    },
    "wet_probability": {
        "cmap": "Blues",
        "vmin": 0.0,
        "vmax": 1.0,
        "low_label": "Low wet probability",
        "high_label": "High wet probability",
    },
}


def compare_products_for_indicator(indicator: str) -> List[str]:
    return INDICATOR_COMPARE_PRODUCTS.get(indicator, PRODUCT_ORDER)

INDICATOR_PATTERNS = [
    ("dryspell_prob_9d", ["dryspell_prob_9d", "dryspellprob9d", "dryspell_9d", "dry_spell_9d", "9d_dryspell", "dryspell9"]),
    ("dryspell_prob_7d", ["dryspell_prob_7d", "dryspellprob7d", "dryspell_7d", "dry_spell_7d", "7d_dryspell", "dryspell7"]),
    ("dryspell_prob_5d", ["dryspell_prob_5d", "dryspellprob5d", "dryspell_5d", "dry_spell_5d", "5d_dryspell", "dryspell5"]),
    # "percent_anomaly"/"pctanomaly" are this app's naming for rainfall
    # percentile's Anomaly product (see the pre-existing static PNG catalog's
    # "..._percentile_pctanomaly.png" convention) -- it's the %-anomaly of
    # rainfall, shown as percentile's anomaly view, not a literal
    # "percentile of a percentile". Filenames like
    # "ethiopia_June_2026-05-01_percent_anomaly.tif" contain "percent" but
    # not "percentile", so they need their own token here.
    ("rainfall_percentile", ["rainfall_percentile", "rainfallpercentile", "rain_percentile", "rf_percentile", "percentile", "rpercentile", "percent_anomaly", "percentanomaly", "pctanomaly", "pct_anomaly"]),
    # spi must be checked before rainfall_total: rainfall_total's bare "pr"
    # substring pattern would otherwise false-match filenames like
    # "..._spi_prob_drought" (contains "pr" from "prob") and "..._spi_prob_wet".
    ("spi", ["spi"]),
    ("rainfall_total", ["rainfall_total", "rainfalltotal", "rain_total", "rf_total", "precip_total", "precipitation_total", "pr_total", "rainfall", "precip", "pr"]),
    ("cdd", ["cdd", "consecutive_dry_days"]),
    ("cwd", ["cwd", "consecutive_wet_days"]),
    # rx5day must be checked before rx1day: "rx1day" is not a substring of
    # "rx5day" so order doesn't strictly matter here, but keeping the more
    # specific/longer token first matches the convention used above (dryspell
    # 9d/7d/5d checked longest-first) in case similarly-named variants are
    # added later.
    ("rx5day", ["rx5day", "rx_5day", "rx5_day", "max_5day_rainfall", "max5day"]),
    ("rx1day", ["rx1day", "rx_1day", "rx1_day", "max_1day_rainfall", "max1day"]),
]

PERIOD_PATTERNS = [
    ("JJAS", ["jjas", "jun_jul_aug_sep", "june_july_august_september"]),
    ("September", ["september", "sept", "sep", "m09", "month09", "09"]),
    ("August", ["august", "aug", "m08", "month08", "08"]),
    ("July", ["july", "jul", "m07", "month07", "07"]),
    ("June", ["june", "jun", "m06", "month06", "06"]),
]

# Multi-week combinations must be listed before their single-week substrings
# (e.g. "week_1_2" before "week_1") since a filename like "..._week1_2_..."
# would otherwise also satisfy the single-week pattern.
SUBSEASONAL_PERIOD_PATTERNS = [
    ("week_1_2", ["week1_2", "week_1_2"]),
    ("week_2_3", ["week2_3", "week_2_3"]),
    ("week_3_4", ["week3_4", "week_3_4"]),
    ("week_1_3", ["week1_3", "week_1_3"]),
    ("week_2_4", ["week2_4", "week_2_4"]),
    ("week_1", ["week1", "week_1"]),
    ("week_2", ["week2", "week_2"]),
    ("week_3", ["week3", "week_3"]),
    ("week_4", ["week4", "week_4"]),
]

PRODUCT_PATTERNS = [
    ("climatology", ["historical_climatology", "climatology", "climatological", "hist_clim", "histclim", "clim", "normal"]),
    ("anomaly", ["anomaly", "anom", "difference", "departure"]),
    ("drought_probability", ["prob_drought", "drought_probability", "droughtprob", "prob_dry"]),
    ("wet_probability", ["prob_wet", "wet_probability", "wetprob"]),
    ("forecast", ["forecast", "fcst", "model", "prediction", "pred"]),
]


def normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def make_id(*parts: Any) -> str:
    return normalize_token("_".join(str(part) for part in parts if part)) or "seasonal_map"


def token_match(normalized_name: str, patterns: List[str]) -> bool:
    padded = f"_{normalized_name}_"
    for pattern in patterns:
        normalized_pattern = normalize_token(pattern)
        if f"_{normalized_pattern}_" in padded or normalized_pattern in normalized_name:
            return True
    return False


def token_match_strict(normalized_name: str, patterns: List[str]) -> bool:
    """Like token_match, but only the underscore-delimited (exact token) check.

    Period inference needs this stricter variant: filenames embed an init
    date like "2026-05-01" right next to the period token (e.g.
    "..._week1_2026-05-01_..."), and the plain substring check in
    token_match would let "week_1_2" (pattern "week1_2") false-match inside
    "week1_2026" (the "1" of "week1" plus the leading "2" of "2026"). The
    padded/boundary-only check does not have this problem.
    """
    padded = f"_{normalized_name}_"
    for pattern in patterns:
        normalized_pattern = normalize_token(pattern)
        if f"_{normalized_pattern}_" in padded:
            return True
    return False


def infer_indicator(stem: str) -> str:
    normalized = normalize_token(stem)
    for value, patterns in INDICATOR_PATTERNS:
        if token_match(normalized, patterns):
            return value
    return "spi"


def infer_period(stem: str) -> str:
    normalized = normalize_token(stem)
    for value, patterns in SUBSEASONAL_PERIOD_PATTERNS + PERIOD_PATTERNS:
        if token_match_strict(normalized, patterns):
            return value
    return "JJAS"


def infer_product(stem: str) -> str:
    normalized = normalize_token(stem)
    for value, patterns in PRODUCT_PATTERNS:
        if token_match(normalized, patterns):
            return value
    return "forecast"


def safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except Exception:
        return path.as_posix()


def is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except Exception:
        return False


def resolve_within(path_value: Any, allowed_roots: List[Path]) -> Optional[Path]:
    """Resolve a catalog-supplied path and confirm it stays under an allowed root.

    Catalog JSON files can name arbitrary paths for a map's image/source file.
    Without this check, a maliciously or accidentally crafted catalog entry
    could point outside the maps directory (e.g. "../../../.env") and have it
    served or read by the API. Returns None if the path is missing, does not
    exist, or resolves outside every allowed root.
    """
    if not path_value:
        return None
    candidate = Path(str(path_value))
    resolved = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
    resolved = resolved.resolve()
    if not any(is_within_directory(resolved, root) for root in allowed_roots):
        return None
    return resolved
