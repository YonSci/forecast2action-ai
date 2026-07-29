"""Loads and resolves the applicable Decision Policy for a given hazard.

Policy files live in data/policies/*.json (one per hazard type, plus
default_policy.json as the fallback). This module is the ONLY place that
resolves "which policy applies" -- app/context/policy_context.py and
app/decision/trigger_engine.py both depend on this, never load a policy
JSON file directly.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict

from app.decision.schemas import Policy

logger = logging.getLogger(__name__)

POLICY_DIR = Path("data/policies")

# app/api/hazard_risk_catalog_shared.py's LAYER_DEFINITIONS use hazard_type
# "drought"/"wet" (matching the raster catalog's own vocabulary); this
# app's policy files are named/keyed by the broader operational hazard name
# ("heavy_rainfall" for a wet-flavored event) -- this table is the single
# translation point between the two vocabularies.
CATALOG_HAZARD_TYPE_TO_POLICY_HAZARD = {
    "drought": "drought",
    "wet": "heavy_rainfall",
}


@lru_cache(maxsize=16)
def _load_policy_file(filename: str) -> Policy:
    path = POLICY_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    return Policy.model_validate(data)


def load_policy_for_hazard(hazard_type: str, country: str = "ethiopia") -> Policy:
    """Resolves data/policies/{hazard_type}_{country}.json, falling back to
    default_policy.json when no hazard-specific file exists or the hazard
    type is unrecognized. Never raises for an unknown hazard -- fails safely
    to the default policy instead, per the project's "fail safely" principle.
    """
    resolved_hazard = CATALOG_HAZARD_TYPE_TO_POLICY_HAZARD.get(hazard_type, hazard_type)
    filename = f"{resolved_hazard}_{country}.json"

    if (POLICY_DIR / filename).exists():
        return _load_policy_file(filename)

    logger.info(
        "No policy file for hazard_type=%s country=%s (looked for %s) -- using default_policy.json",
        hazard_type, country, filename,
    )
    return _load_policy_file("default_policy.json")


def evaluate_trigger_status(priority_score: float, thresholds: Dict[str, float]) -> str:
    """Classifies a 0-1 priority_score against a POLICY-supplied threshold
    dict. Deliberately does not import app.ml.risk_scoring.classify_risk
    directly (that function is hardwired to RISK_THRESHOLDS) -- this is what
    lets a future policy diverge per-hazard without touching risk_scoring.py.
    The default drought/heavy_rainfall policies use the exact same values as
    RISK_THRESHOLDS, so today's behavior is unchanged.
    """
    if priority_score >= thresholds["trigger"]:
        return "trigger"
    if priority_score >= thresholds["warning"]:
        return "warning"
    if priority_score >= thresholds["watch"]:
        return "watch"
    return "no_alert"
