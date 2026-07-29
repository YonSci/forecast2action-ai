"""Pure, stateless task-inference helpers, extracted from app.api.main so
they can be imported by app/decision/action_selector.py without a circular
import (main.py will, after this refactor, import context_api/decision_api
routers, which depend on action_selector, which needs these functions --
importing them from main.py directly would create a cycle).

Moved verbatim -- no logic changes -- from app/api/main.py's
slugify/infer_responsible_sector/infer_task_priority/infer_deadline/
infer_task_basis. main.py now imports from here instead of defining these
inline.
"""

import re


def slugify(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")

    if not value:
        return "item"

    return value


def infer_responsible_sector(action: str, hazard: str) -> str:
    text = action.lower()

    if any(word in text for word in ["coordination", "coordinate", "activate"]):
        return "Disaster Risk Management / Coordination"

    if any(word in text for word in ["water", "water-point", "water trucking"]):
        return "Water Office / Disaster Risk Management"

    if any(word in text for word in ["livestock", "veterinary", "feed", "pasture"]):
        return "Livestock Office / Agriculture Extension"

    if any(word in text for word in ["crop", "farmer", "field", "fodder"]):
        return "Agriculture Extension"

    if any(word in text for word in ["message", "warning", "communication", "sms"]):
        return "Risk Communication / Local Administration"

    if any(word in text for word in ["cash", "voucher", "beneficiary", "support"]):
        return "Humanitarian Partners / Social Protection"

    if any(word in text for word in ["verify", "monitor", "report", "observations"]):
        return "Local Officers / Community Focal Persons"

    if hazard == "drought":
        return "DRM / Agriculture / Water / Livestock"

    if hazard == "heavy_rainfall":
        return "DRM / Water / Infrastructure"

    if hazard == "heat_stress":
        return "Health / Livestock / Local Administration"

    return "District Coordination Team"


def infer_task_priority(action: str, risk_level: str) -> str:
    text = action.lower()

    if risk_level == "trigger":
        if any(word in text for word in ["activate", "verify", "warning", "coordinate"]):
            return "Urgent"
        return "High"

    if risk_level == "warning":
        if any(word in text for word in ["monitor", "prepare", "brief", "verify"]):
            return "High"
        return "Medium"

    if risk_level == "watch":
        return "Medium"

    return "Routine"


def infer_deadline(action: str, risk_level: str) -> str:
    text = action.lower()

    if risk_level == "trigger":
        if any(word in text for word in ["activate", "coordinate", "warning", "message"]):
            return "Within 24 hours"
        if any(word in text for word in ["verify", "monitor", "report"]):
            return "Within 48 hours"
        return "Within 72 hours"

    if risk_level == "warning":
        if any(word in text for word in ["brief", "prepare", "message"]):
            return "Within 48 hours"
        return "Within 3–5 days"

    if risk_level == "watch":
        return "Within 7 days"

    return "Routine update cycle"


def infer_task_basis(action: str, hazard: str, risk_level: str) -> str:
    return (
        f"Generated from knowledge-guided advisory action for {hazard.replace('_', ' ')} "
        f"at {risk_level} level."
    )
