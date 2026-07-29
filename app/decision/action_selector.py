"""Selects candidate actions for a Decision Context Envelope and builds
canonical-schema Action Tracker tasks from them.

Action retrieval goes through app.retrieval.hybrid_retriever (never directly
to the knowledge base) so metadata filtering/reranking/citation-building
stay centralized in one place.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List

from app.api.task_inference import (
    infer_deadline,
    infer_responsible_sector,
    infer_task_basis,
    infer_task_priority,
    slugify,
)
from app.decision.approval_engine import determine_approval_status
from app.decision.schemas import Policy
from app.ml.risk_scoring import classify_risk
from app.retrieval.citation_builder import build_citation
from app.retrieval.hybrid_retriever import retrieve

if TYPE_CHECKING:
    from app.context.schemas import DecisionContextEnvelope

# Keyword buckets mapping a candidate action's text to one of the policy's
# action_categories keys (verification/public_message/coordination/
# resource_preposition/cash_or_voucher/activation) -- same keyword-bucket
# style already used by infer_responsible_sector in task_inference.py.
ACTION_CATEGORY_KEYWORDS = {
    "activation": ["activate", "activation"],
    "resource_preposition": ["preposition", "pre-position", "resource", "stockpile"],
    "cash_or_voucher": ["cash", "voucher", "beneficiary"],
    "public_message": ["message", "warning", "sms", "communication", "advisory"],
    "verification": ["verify", "monitor", "observations", "report"],
    "coordination": ["coordinate", "coordination", "meeting"],
}


def _classify_action_category(action_text: str) -> str:
    text = action_text.lower()
    for category, keywords in ACTION_CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "coordination"


def select_actions(
    envelope: "DecisionContextEnvelope",
    policy: Policy,
    max_actions: int = 7,
) -> List[Dict[str, Any]]:
    """Retrieves candidate knowledge items, expands their action lists, and
    classifies + approval-gates each resulting action against the policy.
    """
    query = {
        "hazard": envelope.hazard_evidence.hazard_type or "",
        "risk_level": envelope.policy.trigger_status,
        "audience": envelope.operational.audience,
        "feedback_signal": envelope.community.feedback_signal,
    }
    retrieved_items = retrieve(query, top_k=5, country=envelope.geography.country)

    actions: List[Dict[str, Any]] = []
    seen_texts = set()

    for item in retrieved_items:
        for action_text in item.get("actions", []):
            normalized = action_text.strip().lower()
            if not normalized or normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            category = _classify_action_category(action_text)
            rule = policy.action_categories.get(category)
            approval_required = rule.approval_required if rule else False

            actions.append({
                "action_id": f"{slugify(item.get('id', 'action'))}_{len(actions) + 1}",
                "action_text": action_text.strip(),
                "action_category": category,
                "sector": infer_responsible_sector(action_text, envelope.hazard_evidence.hazard_type or ""),
                "approval_required": approval_required,
                "approval_status": determine_approval_status(category, policy),
                "evidence_basis": [
                    f"priority_score={envelope.hazard_evidence.priority_score:.3f}",
                    f"trigger_status={envelope.policy.trigger_status}",
                ],
                "knowledge_source_ids": [item.get("id", "")],
                "citation": build_citation(item),
            })

            if len(actions) >= max_actions:
                return actions

    return actions


def build_tasks_from_context(
    envelope: "DecisionContextEnvelope",
    actions: List[Dict[str, Any]],
    district: str,
) -> List[Dict[str, Any]]:
    """Canonical-schema tasks (spec §23) for the new context-driven Action
    Tracker path. Kept separate from app.api.main.build_action_tasks_from_advisory
    (the legacy rag_engine-based builder), which is untouched.
    """
    now = datetime.now(timezone.utc).isoformat()
    risk_level = envelope.policy.trigger_status
    district_slug = slugify(district)
    tasks = []

    for index, action in enumerate(actions, start=1):
        action_text = action["action_text"]
        tasks.append({
            "task_id": f"{district_slug}_ctx_{envelope.context_id[:8]}_task_{index}",
            "context_id": envelope.context_id,
            "action_id": action["action_id"],
            "district": district,
            "country": envelope.geography.country,
            "audience": envelope.operational.audience,
            "rank": index,
            "hazard": envelope.hazard_evidence.hazard_type or "",
            "risk_level": classify_risk(envelope.hazard_evidence.priority_score),
            "trigger_status": risk_level,
            "responsible_sector": action["sector"],
            "action": action_text,
            "priority": infer_task_priority(action_text, risk_level),
            "deadline": infer_deadline(action_text, risk_level),
            "status": "Not started",
            "approval_status": action["approval_status"],
            "evidence_basis": action["evidence_basis"],
            "knowledge_source_ids": action["knowledge_source_ids"],
            "created_at": now,
            "updated_at": now,
            "updated_by": "",
            "completed_at": None,
            "outcome_status": None,
            "outcome_note": "",
            "basis": infer_task_basis(action_text, envelope.hazard_evidence.hazard_type or "", risk_level),
        })

    return tasks
