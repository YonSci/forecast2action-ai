"""Community report model + JSON storage, extracted from app.api.main.

Moved out of main.py so app/context/community_context.py can import
load_reports/summarize_reports without importing the 2500+ line main.py
module (which mounts FastAPI routes at import time) -- that import would
risk a circular dependency once main.py itself imports app.api.context_api/
decision_api, which depend on app/context.

main.py imports CommunityReport/REPORTS_PATH/load_reports/save_reports/
summarize_reports from here instead of defining them inline; no behavior
change for existing callers.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

REPORTS_PATH = Path("data/sample/community_reports.json")

# Canonical report_type vocabulary (union of the old backend's 10-value list
# and the frontend's 10-value list, semantically aliased -- see
# LEGACY_REPORT_TYPE_ALIASES below for the mapping). GET /api/report-types
# returns this list; already-stored reports using an old value are NOT
# rewritten in place, they're aliased at read time.
CANONICAL_REPORT_TYPES = [
    {"id": "water_shortage", "label": "Water shortage / water point stress"},
    {"id": "crop_wilting", "label": "Crop wilting / crop stress"},
    {"id": "pasture_stress", "label": "Pasture stress"},
    {"id": "livestock_stress", "label": "Livestock stress"},
    {"id": "flooding", "label": "Flooding / water logging"},
    {"id": "river_overflow", "label": "River overflow"},
    {"id": "road_disruption", "label": "Road or access disruption"},
    {"id": "unusual_heat", "label": "Unusual heat"},
    {"id": "health_or_disease", "label": "Health or disease concern"},
    {"id": "food_price_increase", "label": "Food or livestock price pressure"},
    {"id": "no_impact_observed", "label": "No impact observed yet"},
    {"id": "other", "label": "Other observation"},
]

# Old stored values (from either the pre-upgrade backend or frontend) that
# now map onto a canonical value above. Applied at READ time only --
# data/sample/community_reports.json's already-stored records are never
# mutated by this mapping.
LEGACY_REPORT_TYPE_ALIASES = {
    "pasture_poor": "pasture_stress",
    "flooded_road": "flooding",
    "disease_concern": "health_or_disease",
    "market_disruption": "food_price_increase",
}

# Canonical severity scale (the frontend's 4-value scale becomes the source
# of truth going forward; the old backend default of "medium" still parses
# fine since severity is a free string, just no longer the recommended
# default for new reports).
CANONICAL_SEVERITIES = ["low", "moderate", "high", "severe"]


class CommunityReport(BaseModel):
    country: str
    district: str
    report_type: str
    severity: str = "moderate"
    description: str = ""
    reported_by: str = "anonymous"
    contact: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # --- new, additive fields (spec §9 / frontend reconciliation) ---
    reporter_role: Optional[str] = None
    location_detail: Optional[str] = ""
    confidence: Optional[str] = None
    admin_level: Optional[str] = None
    region: Optional[str] = ""
    zone: Optional[str] = ""
    woreda: Optional[str] = ""
    region_id: Optional[str] = ""
    zone_id: Optional[str] = ""
    woreda_id: Optional[str] = ""
    hazard: Optional[str] = None
    risk_level: Optional[str] = None
    priority_score: Optional[float] = None

    # --- verification fields (spec §9) ---
    verification_status: Optional[str] = "unverified"
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    location_accuracy: Optional[str] = None
    supporting_evidence: Optional[str] = None
    duplicate_group_id: Optional[str] = None
    report_confidence: Optional[float] = None


def ensure_reports_file() -> None:
    REPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not REPORTS_PATH.exists():
        REPORTS_PATH.write_text("[]", encoding="utf-8")


def load_reports() -> List[Dict[str, Any]]:
    ensure_reports_file()
    try:
        return json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Could not parse %s -- returning an empty report list", REPORTS_PATH)
        return []


def save_reports(reports: List[Dict[str, Any]]) -> None:
    ensure_reports_file()
    REPORTS_PATH.write_text(
        json.dumps(reports, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def canonical_report_type(raw_report_type: str) -> str:
    return LEGACY_REPORT_TYPE_ALIASES.get(raw_report_type, raw_report_type)


def summarize_reports(district: Optional[str] = None) -> Dict[str, Any]:
    reports = load_reports()

    if district:
        reports = [
            report
            for report in reports
            if str(report.get("district", "")).lower() == district.lower()
        ]

    by_severity: Dict[str, int] = {}
    by_type: Dict[str, int] = {}

    for report in reports:
        severity = report.get("severity", "moderate")
        report_type = canonical_report_type(report.get("report_type", "other"))

        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_type[report_type] = by_type.get(report_type, 0) + 1

    # "high" OR "severe" both count toward the strong-signal threshold --
    # matches SelectedAreaCommunityReports.jsx's own client-side
    # getSignalSummary() highOrSevere logic, so frontend- and
    # backend-computed signals finally agree.
    high_or_severe_count = by_severity.get("high", 0) + by_severity.get("severe", 0)

    if high_or_severe_count >= 3:
        feedback_signal = "strong_ground_signal"
    elif len(reports) >= 3:
        feedback_signal = "emerging_ground_signal"
    elif len(reports) > 0:
        feedback_signal = "limited_ground_signal"
    else:
        feedback_signal = "no_ground_signal"

    return {
        "district": district,
        "total_reports": len(reports),
        "by_severity": by_severity,
        "by_type": by_type,
        "feedback_signal": feedback_signal,
    }
