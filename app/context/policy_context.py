"""Builds DecisionPolicyContext by delegating to app.decision.policy_engine
-- this module never loads a policy JSON file directly.
"""

from app.context.schemas import DecisionPolicyContext
from app.decision.policy_engine import evaluate_trigger_status, load_policy_for_hazard


def build_policy_context(
    hazard_type: str, priority_score: float, country: str = "ethiopia",
) -> DecisionPolicyContext:
    policy = load_policy_for_hazard(hazard_type or "any", country)
    trigger_status = evaluate_trigger_status(priority_score, policy.thresholds)

    return DecisionPolicyContext(
        policy_id=policy.policy_id,
        thresholds=policy.thresholds,
        trigger_status=trigger_status,
    )
