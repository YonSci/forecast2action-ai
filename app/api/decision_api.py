"""Decision Engine API -- deterministic trigger evaluation + task creation.
The LLM never touches these decisions; this router only exposes what
app.decision.trigger_engine/action_selector already computed.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.context.repository import get_repository
from app.decision import trigger_engine
from app.decision.action_selector import build_tasks_from_context, select_actions
from app.decision.policy_engine import load_policy_for_hazard
from app.decision.task_store import add_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/decision", tags=["Decision Engine"])


class DecisionTriggerRequest(BaseModel):
    context_id: str
    district: str
    create_tasks: bool = True


@router.post("/trigger")
async def decision_trigger_endpoint(request: DecisionTriggerRequest) -> Dict[str, Any]:
    envelope = get_repository().get(request.context_id)
    if not envelope:
        raise HTTPException(status_code=404, detail=f"Context '{request.context_id}' not found.")

    result = trigger_engine.evaluate(envelope)

    tasks = []
    if result["triggered"] and request.create_tasks:
        policy = load_policy_for_hazard(envelope.hazard_evidence.hazard_type or "any", "ethiopia")
        actions = select_actions(envelope, policy)
        tasks = build_tasks_from_context(envelope, actions, request.district)
        add_tasks(tasks)
        logger.info(
            "action_created context_id=%s district=%s task_count=%d",
            request.context_id, request.district, len(tasks),
        )

    return {**result, "tasks": tasks}
