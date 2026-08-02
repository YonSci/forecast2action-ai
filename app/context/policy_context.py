"""Builds DecisionPolicyContext by delegating to app.decision.policy_engine
-- this module never loads a policy JSON file directly.
"""

from typing import TYPE_CHECKING, Tuple

from app.context.schemas import DecisionPolicyContext
from app.decision.policy_engine import load_policy_for_hazard

if TYPE_CHECKING:
    from app.context.schemas import HazardEvidence

# Same severity ordering as the frontend's combineDroughtWetLevel
# (frontend/src/constants/priorityLevels.js) -- most severe first, so a tie
# between drought/wet resolves to whichever is worse.
_LEVEL_SEVERITY_ORDER = ["trigger", "warning", "watch", "no_alert"]


def resolve_real_trigger_status(hazard_evidence: "HazardEvidence") -> Tuple[str, str]:
    """Real (effective_hazard_type, trigger_status), using the SAME
    already-computed drought_risk/wet_risk classification as the Priority
    Intervention Areas table (app.api.hazard_risk_ranking.compute_district_
    ranking's raw_layer_classification_thresholds + classify_risk) -- never
    the generic priority_score, which is trivially ~1.0 for whatever area
    ranks #1 under ANY metric (including Exposure), and would misclassify
    an Exposure-ranked area as "trigger" regardless of real hazard severity.
    That was a real, confirmed bug: a context built by ranking on Population
    alone (hazard_type=None) still came out trigger_status="trigger" and
    drove drought-specific RAG retrieval for an area with no drought signal
    evaluated at all.

    When this context was built for a specific hazard (hazard_type is
    "drought" or "wet"), returns that hazard's own real level. Otherwise
    (Exposure ranking, or a "dominant"/compound risk layer) there is no
    single hazard to classify against, so this falls back to whichever of
    drought/wet is more severe for this specific area -- same rule as the
    frontend's combineDroughtWetLevel, so the two systems agree.
    """
    drought_level = (hazard_evidence.drought_risk or {}).get("level")
    wet_level = (hazard_evidence.wet_risk or {}).get("level")

    if hazard_evidence.hazard_type == "drought" and drought_level:
        return "drought", drought_level
    if hazard_evidence.hazard_type == "wet" and wet_level:
        return "wet", wet_level

    candidates = [
        (hazard, level)
        for hazard, level in (("drought", drought_level), ("wet", wet_level))
        if level
    ]
    if not candidates:
        return hazard_evidence.hazard_type or "unknown", "no_alert"

    candidates.sort(
        key=lambda pair: _LEVEL_SEVERITY_ORDER.index(pair[1])
        if pair[1] in _LEVEL_SEVERITY_ORDER
        else len(_LEVEL_SEVERITY_ORDER)
    )
    return candidates[0]


def build_policy_context(
    hazard_type: str, trigger_status: str, country: str = "ethiopia",
) -> DecisionPolicyContext:
    """hazard_type/trigger_status are expected to already be the REAL,
    resolved values from resolve_real_trigger_status -- this function only
    resolves which policy file's thresholds to report alongside them, it
    does not itself classify anything.
    """
    policy = load_policy_for_hazard(hazard_type or "any", country)

    return DecisionPolicyContext(
        policy_id=policy.policy_id,
        thresholds=policy.thresholds,
        trigger_status=trigger_status,
    )
