"""Deterministic trigger evaluation. The LLM never touches this -- it only
explains/describes whatever this function already decided.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

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
    """
    trigger_status = envelope.policy.trigger_status
    triggered = trigger_status in ACTIONABLE_STATUSES

    reason_codes = []
    if envelope.hazard_evidence.priority_score >= envelope.policy.thresholds.get("watch", 0.35):
        reason_codes.append("priority_score_above_watch_threshold")
    if trigger_status in ("warning", "trigger"):
        reason_codes.append(f"priority_score_above_{trigger_status}_threshold")
    if envelope.community.feedback_signal in ("strong_ground_signal", "emerging_ground_signal"):
        reason_codes.append(f"community_signal_{envelope.community.feedback_signal}")
    if envelope.community.feedback_signal == "contradictory_ground_signal":
        reason_codes.append("contradictory_community_evidence")

    approval_required = trigger_status == "trigger"

    reason = (
        f"priority_score={envelope.hazard_evidence.priority_score:.3f} classifies as "
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
