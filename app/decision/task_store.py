"""JSON-file storage for context-driven Action Tracker tasks.

Kept as a SEPARATE store from app.api.main's TASK_STATUS_PATH (the legacy
rag_engine-based tracker) by design, not as unreconciled debt: the two
task sources have different persistence lifecycles. Legacy tasks are
stateless and re-derived on every GET from the current RAG advisory
output (this store only ever persists status/updated_by); context tasks
are a fixed list persisted once at context-build time, tied to a specific
context_id and a policy-gated approval requirement. Merging the two
stores would force one of them to change lifecycle for no functional gain.
What IS reconciled is the response shape both are read back in --
see app.api.action_tracker_shape's canonicalize_legacy_task /
canonicalize_context_task, applied in app.api.main's get_action_tracker.

Lives in app/decision/ (not app/api/main.py) so both main.py and
app/api/decision_api.py can import it without a circular dependency
(main.py imports decision_api's router, so decision_api can't import
anything defined in main.py).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

CONTEXT_TASK_STATUS_PATH = Path("data/sample/context_task_status.json")


def load_context_tasks() -> Dict[str, Any]:
    if not CONTEXT_TASK_STATUS_PATH.exists():
        return {}
    try:
        data = json.loads(CONTEXT_TASK_STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data.get("tasks", {}) if isinstance(data, dict) else {}


def save_context_tasks(tasks: Dict[str, Any]) -> None:
    CONTEXT_TASK_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tasks": tasks, "updated_at": datetime.now(timezone.utc).isoformat()}
    CONTEXT_TASK_STATUS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def add_tasks(new_tasks: List[Dict[str, Any]]) -> None:
    tasks = load_context_tasks()
    for task in new_tasks:
        tasks[task["task_id"]] = task
    save_context_tasks(tasks)
