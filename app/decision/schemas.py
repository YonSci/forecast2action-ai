"""Pydantic models for the deterministic decision/policy/trigger engine.

Separate from app/context/schemas.py's DecisionPolicyContext -- that model
is the compact, envelope-embedded VIEW of a policy decision; these models
are the full policy DEFINITION loaded from data/policies/*.json.
"""

from typing import Dict, Optional

from pydantic import BaseModel


class ActionCategoryRule(BaseModel):
    approval_required: bool = False


class Policy(BaseModel):
    policy_id: str
    hazard_type: str
    country: str = "ethiopia"
    thresholds: Dict[str, float]
    rank_by_default: Optional[str] = None
    action_categories: Dict[str, ActionCategoryRule]
    version: str
    valid_from: str


class TriggerResult(BaseModel):
    triggered: bool
    trigger_status: str
    policy_id: str
    reason: str
    reason_codes: list[str] = []
    approval_required: bool = False
