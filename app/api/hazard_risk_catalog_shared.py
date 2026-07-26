"""Shared layer/period vocabulary for the Ethiopia Hazard/Risk raster pipeline.

Plays the same role for the Hazard/Probability_Severity/Exposure/Vulnerability/Risk
GeoTIFFs under data/maps/{Hazard,Probability_Severity,Exposure,Vulnerability,Risk}/
that seasonal_catalog_shared.py plays for the climate indicator rasters: a single
source of truth for the vocabulary so app/api/hazard_risk_maps.py and the frontend
layer switcher stay in sync.

Unlike the climate indicator catalog, filenames here follow one fixed, fully
regular convention (confirmed by direct inspection of every file: identical grid,
identical "ethiopia_<period>_<init_date>_<layer>.tif" / "ethiopia_<layer>.tif"
shape), so layer/period parsing below is exact-match rather than fuzzy pattern
inference.
"""

import re
from typing import Any, Dict, List, Optional

from app.api.seasonal_catalog_shared import (
    PERIODS,
    PROJECT_ROOT,
    make_id,
    resolve_within,
    safe_read_json,
    safe_rel_path,
)

__all__ = [
    "PROJECT_ROOT",
    "make_id",
    "resolve_within",
    "safe_read_json",
    "safe_rel_path",
    "PERIODS",
    "PERIOD_BY_VALUE",
    "STATIC_PERIOD",
    "CATEGORIES",
    "CATEGORY_BY_VALUE",
    "LAYER_DEFINITIONS",
    "LAYER_BY_VALUE",
    "RISK_CLASS_BANDS",
    "RISK_CLASS_BY_CODE",
    "DOMINANT_HAZARD_CODE_THRESHOLD",
    "DOMINANT_HAZARD_CODE_BANDS",
    "DOMINANT_HAZARD_CODE_BY_CODE",
    "parse_hazard_risk_filename",
]

# Hazard/Risk data only ships monthly + JJAS seasonal aggregates -- no
# subseasonal week windows exist for these layers (unlike the climate
# indicator rasters) -- so this reuses seasonal_catalog_shared's PERIODS
# list as-is instead of ALL_PERIODS.
PERIOD_BY_VALUE = {item["value"].lower(): item for item in PERIODS}

# Synthetic period value for Exposure/Vulnerability layers, which ship one
# file total (no period/init_date token in the filename) and apply to every
# period. Deliberately excluded from PERIODS/PERIOD_BY_VALUE so it can never
# show up in a period dropdown -- it is only used internally to mark a
# record as period-invariant so `/map` can resolve it against whatever
# period the caller actually asked for.
STATIC_PERIOD = "static"

CATEGORIES = [
    {"value": "hazard", "label": "Hazard"},
    {"value": "probability", "label": "Probability"},
    {"value": "exposure", "label": "Exposure"},
    {"value": "vulnerability", "label": "Vulnerability"},
    {"value": "risk", "label": "Risk"},
]
CATEGORY_BY_VALUE = {item["value"]: item for item in CATEGORIES}

# One entry per literal filename suffix token. vmin/vmax are fixed by
# construction for every layer here (not data-driven percentiles like the
# climate catalog) so a given value reads as the same color across every
# period/map -- see risk's 0-100 score confirmation below.
LAYER_DEFINITIONS = [
    {"value": "h_dry_mean", "category": "hazard", "hazard_type": "drought", "label": "Drought Hazard (mean)", "units": "index", "vmin": 0.0, "vmax": 1.0, "cmap": "YlOrRd", "low_label": "Low hazard", "high_label": "High hazard", "is_categorical": False},
    {"value": "h_wet_mean", "category": "hazard", "hazard_type": "wet", "label": "Wetness Hazard (mean)", "units": "index", "vmin": 0.0, "vmax": 1.0, "cmap": "Blues", "low_label": "Low hazard", "high_label": "High hazard", "is_categorical": False},
    {"value": "p_drought", "category": "probability", "hazard_type": "drought", "label": "Drought Probability", "units": "probability", "vmin": 0.0, "vmax": 1.0, "cmap": "YlOrRd", "low_label": "Low probability", "high_label": "High probability", "is_categorical": False},
    {"value": "p_wet", "category": "probability", "hazard_type": "wet", "label": "Wet Probability", "units": "probability", "vmin": 0.0, "vmax": 1.0, "cmap": "Blues", "low_label": "Low probability", "high_label": "High probability", "is_categorical": False},
    {"value": "population_normalized", "category": "exposure", "hazard_type": None, "label": "Population Exposure", "units": "normalized", "vmin": 0.0, "vmax": 1.0, "cmap": "YlOrRd", "low_label": "Low exposure", "high_label": "High exposure", "is_categorical": False},
    {"value": "v_drought", "category": "vulnerability", "hazard_type": "drought", "label": "Drought Vulnerability", "units": "index", "vmin": 0.0, "vmax": 1.0, "cmap": "YlOrRd", "low_label": "Low vulnerability", "high_label": "High vulnerability", "is_categorical": False},
    {"value": "v_wet", "category": "vulnerability", "hazard_type": "wet", "label": "Wet Vulnerability", "units": "index", "vmin": 0.0, "vmax": 1.0, "cmap": "Blues", "low_label": "Low vulnerability", "high_label": "High vulnerability", "is_categorical": False},
    # Risk (r_drought/r_wet/r_dominant) = 100 * P * S_effective * E * V, so it
    # is a 0-100 relative score, NOT a 0-1 probability -- confirmed against
    # real data (max observed r_dominant so far is ~56.6).
    {"value": "population_r_drought", "category": "risk", "hazard_type": "drought", "label": "Drought Risk", "units": "score", "vmin": 0.0, "vmax": 100.0, "cmap": "YlOrRd", "low_label": "Low risk", "high_label": "High risk", "is_categorical": False},
    {"value": "population_r_wet", "category": "risk", "hazard_type": "wet", "label": "Wet Risk", "units": "score", "vmin": 0.0, "vmax": 100.0, "cmap": "Blues", "low_label": "Low risk", "high_label": "High risk", "is_categorical": False},
    {"value": "population_r_dominant", "category": "risk", "hazard_type": "dominant", "label": "Dominant Risk", "units": "score", "vmin": 0.0, "vmax": 100.0, "cmap": "RdPu", "low_label": "Low risk", "high_label": "High risk", "is_categorical": False},
    {"value": "population_risk_class", "category": "risk", "hazard_type": "dominant", "label": "Risk Class", "units": "class", "vmin": 0, "vmax": 4, "cmap": None, "low_label": "Very low", "high_label": "Very high", "is_categorical": True},
    # dominant_code = 0 if neither R_drought nor R_wet exceeds
    # DOMINANT_HAZARD_CODE_THRESHOLD, 1 if only R_drought does, 2 if only
    # R_wet does, 3 if both do simultaneously (see DOMINANT_HAZARD_CODE_BANDS).
    {"value": "population_dominant_code", "category": "risk", "hazard_type": "dominant", "label": "Dominant Hazard Code", "units": "dominant_code", "vmin": 0, "vmax": 3, "cmap": None, "low_label": "Insignificant", "high_label": "Mixed / compound", "is_categorical": True},
]
LAYER_BY_VALUE = {item["value"]: item for item in LAYER_DEFINITIONS}

# risk_class breakpoints, straight from the upstream pipeline's
# config/thresholds.yaml (that file lives outside this repo -- these values
# were confirmed directly against the data: e.g. this dataset's risk_class=2
# cells all have r_dominant in [40.2, 56.6], inside the Moderate band).
RISK_CLASS_BANDS = [
    {"code": 0, "label": "Very low", "range": (0.0, 19.9), "color": "#1a9850"},
    {"code": 1, "label": "Low", "range": (20.0, 39.9), "color": "#91cf60"},
    {"code": 2, "label": "Moderate", "range": (40.0, 59.9), "color": "#fee08b"},
    {"code": 3, "label": "High", "range": (60.0, 79.9), "color": "#fc8d59"},
    {"code": 4, "label": "Very high", "range": (80.0, 100.0), "color": "#d73027"},
]
RISK_CLASS_BY_CODE = {band["code"]: band for band in RISK_CLASS_BANDS}

# dominant_code's 4-value scheme: 0 if neither R_drought nor R_wet exceeds
# DOMINANT_HAZARD_CODE_THRESHOLD, 1 if only R_drought does (drought-dominated),
# 2 if only R_wet does (wet-dominated), 3 if both do simultaneously
# (mixed/compound). Colors intentionally echo this app's existing drought=red
# / wet=blue convention (see h_dry_mean/h_wet_mean's cmaps above), with a
# neutral gray for "insignificant" and a distinct purple for "mixed".
DOMINANT_HAZARD_CODE_THRESHOLD = 19.9

DOMINANT_HAZARD_CODE_BANDS = [
    {"code": 0, "label": "Insignificant", "color": "#94A3B8"},
    {"code": 1, "label": "Drought-dominated", "color": "#D92D20"},
    {"code": 2, "label": "Wet-dominated", "color": "#1570EF"},
    {"code": 3, "label": "Mixed / compound", "color": "#7C3AED"},
]
DOMINANT_HAZARD_CODE_BY_CODE = {band["code"]: band for band in DOMINANT_HAZARD_CODE_BANDS}

_INIT_DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


def parse_hazard_risk_filename(stem: str) -> Optional[Dict[str, str]]:
    """Parse "ethiopia_<period>_<init_date>_<layer>" / "ethiopia_<layer>" stems.

    Returns None if the stem doesn't start with "ethiopia_" or its remaining
    layer token isn't one of LAYER_BY_VALUE's known suffixes -- callers treat
    that as "not a hazard/risk raster" rather than guessing at intent, since
    (unlike the climate indicator catalog) this vocabulary is fully closed.
    """
    prefix = "ethiopia_"
    if not stem.startswith(prefix):
        return None
    rest = stem[len(prefix):]

    period_value = STATIC_PERIOD
    for period_key, period_meta in PERIOD_BY_VALUE.items():
        token = f"{period_key}_"
        if rest.lower().startswith(token):
            period_value = period_meta["value"]
            rest = rest[len(token):]
            break

    init_date = ""
    match = _INIT_DATE_PATTERN.match(rest)
    if match:
        init_date = match.group(1)
        rest = rest[match.end():]

    if rest not in LAYER_BY_VALUE:
        return None

    return {"layer": rest, "period": period_value, "init_date": init_date}
