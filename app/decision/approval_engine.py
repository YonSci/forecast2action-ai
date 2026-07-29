"""Simple approval state machine for actions/tasks that require human sign-off.

Approval status values are exactly: "Not required", "Pending", "Approved",
"Rejected" (spec §23). The LLM never sets these -- only this module and the
human-driven PATCH /api/action-tracker/approval endpoint do.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.decision.schemas import Policy

logger = logging.getLogger(__name__)

APPROVALS_PATH = Path("data/sample/context_task_approvals.json")


def determine_approval_status(action_category: str, policy: Policy) -> str:
    rule = policy.action_categories.get(action_category)
    return "Pending" if (rule and rule.approval_required) else "Not required"


def _load_approvals() -> Dict[str, Any]:
    if not APPROVALS_PATH.exists():
        return {}
    try:
        return json.loads(APPROVALS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Could not parse %s -- starting from an empty approvals store", APPROVALS_PATH)
        return {}


def _save_approvals(approvals: Dict[str, Any]) -> None:
    APPROVALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPROVALS_PATH.write_text(json.dumps(approvals, indent=2, ensure_ascii=False), encoding="utf-8")


def approve_task(task_id: str, approver: str) -> Dict[str, Any]:
    approvals = _load_approvals()
    record = {
        "task_id": task_id,
        "approval_status": "Approved",
        "approver": approver,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    approvals[task_id] = record
    _save_approvals(approvals)
    return record


def reject_task(task_id: str, approver: str, reason: str = "") -> Dict[str, Any]:
    approvals = _load_approvals()
    record = {
        "task_id": task_id,
        "approval_status": "Rejected",
        "approver": approver,
        "reason": reason,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    approvals[task_id] = record
    _save_approvals(approvals)
    return record


def get_approval_status(task_id: str, default: str = "Not required") -> str:
    approvals = _load_approvals()
    record = approvals.get(task_id)
    return record["approval_status"] if record else default
