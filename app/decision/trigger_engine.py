"""Deterministic trigger evaluation. The LLM never touches this -- it only
explains/describes whatever this function already decided.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from app.context.policy_context import resolve_real_trigger_status

if TYPE_CHECKING:
    from app.context.schemas import DecisionContextEnvelope

# Watch is monitor-only; Warning and Trigger are actionable, matching the
# existing app convention (RISK_ORDER in rag_engine.py, the 4-level
# Trigger/Warning/Watch/No alert UI language already used throughout the
# frontend this session).
ACTIONABLE_STATUSES = {"warning", "trigger"}


def evaluate(envelope: "DecisionContextEnvelope") -> Dict[str, Any]:
    """Returns {"triggered": bool, "trigger_status": str, "policy_id": str,
    "reason": str, "reason_codes": [...], "approval_required": bool}.

    trigger_status/reason_codes are grounded in the REAL drought_risk/
    wet_risk classification (same as the ranking table and the context
    envelope's own policy.trigger_status -- see
    app.context.policy_context.resolve_real_trigger_status), never the
    generic priority_score, which is trivially ~1.0 for whatever area ranks
    #1 under ANY metric including Exposure and does not reflect real hazard
    severity (the same bug already fixed in policy_context.py).
    """
    trigger_status = envelope.policy.trigger_status
    triggered = trigger_status in ACTIONABLE_STATUSES

    effective_hazard_type, _ = resolve_real_trigger_status(envelope.hazard_evidence)
    real_risk = (
        envelope.hazard_evidence.drought_risk
        if effective_hazard_type == "drought"
        else envelope.hazard_evidence.wet_risk
    ) or {}
    real_value = real_risk.get("value")

    reason_codes = []
    if trigger_status in ("watch", "warning", "trigger"):
        reason_codes.append(f"{effective_hazard_type}_risk_above_watch_threshold")
    if trigger_status in ("warning", "trigger"):
        reason_codes.append(f"{effective_hazard_type}_risk_above_{trigger_status}_threshold")
    # Community signal is cited alongside the real trigger classification as
    # supporting evidence -- it never shifts trigger_status itself (an
    # explicit product decision, not an oversight).
    if envelope.community.feedback_signal in ("strong_ground_signal", "emerging_ground_signal"):
        reason_codes.append(f"community_signal_{envelope.community.feedback_signal}")
    if envelope.community.feedback_signal == "contradictory_ground_signal":
        reason_codes.append("contradictory_community_evidence")

    approval_required = trigger_status == "trigger"

    value_text = f"={real_value:.1f}" if real_value is not None else ""
    reason = (
        f"{effective_hazard_type}_risk{value_text} classifies as "
        f"'{trigger_status}' under policy {envelope.policy.policy_id} "
        f"(thresholds={envelope.policy.thresholds})."
    )

    return {
        "triggered": triggered,
        "trigger_status": trigger_status,
        "policy_id": envelope.policy.policy_id,
        "reason": reason,
        "reason_codes": reason_codes,
        "approval_required": approval_required,
    }
