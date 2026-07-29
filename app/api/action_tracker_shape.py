"""Reconciles the response shape of the two Action Tracker task sources
(app.api.main's legacy rag_engine-based tasks and
app.decision.action_selector's context-driven tasks) at the read boundary,
without merging their storage or write paths -- those have genuinely
different lifecycles (see app.decision.task_store's module docstring).

Pure, dependency-free dict-in/dict-out functions so they're unit-testable
without FastAPI/pydantic, matching the extraction pattern already used by
app.api.task_inference and app.api.community_reports_store.
"""

from typing import Any, Dict


def canonicalize_legacy_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Adds context-task-shaped mirror keys to a legacy task, additively."""
    task.setdefault("task_id", task.get("id"))
    task.setdefault("deadline", task.get("suggested_deadline"))
    task.setdefault("context_id", None)
    task.setdefault("approval_status", "Not required")
    task.setdefault("evidence_basis", [])
    task.setdefault("knowledge_source_ids", [])
    task.setdefault("outcome_status", None)
    task.setdefault("completed_at", None)
    task["source"] = "legacy"
    return task


def canonicalize_context_task(task: Dict[str, Any], audience: str = "") -> Dict[str, Any]:
    """Adds legacy-task-shaped mirror keys to a context task, additively."""
    task.setdefault("id", task.get("task_id"))
    task.setdefault("suggested_deadline", task.get("deadline"))
    task.setdefault("audience", audience)
    task.setdefault("country", "")
    task.setdefault("rank", None)
    task.setdefault("updated_by", "")
    task["source"] = "context"
    return task
