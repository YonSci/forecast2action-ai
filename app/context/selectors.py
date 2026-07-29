"""Task-based context selection -- not every field of a Decision Context
Envelope needs to reach the LLM for every task type. Trimmed from the
project spec's 4 task types to the two this app actually generates
(advisory_generation, sms_summary), since map_interpretation/bulletin
budgets would currently have no distinct consumer.
"""

from typing import Any, Dict

from app.context.schemas import DecisionContextEnvelope

TASK_BUDGETS = {
    "advisory_generation": {"knowledge_items": 5, "community_reports": 5},
    "sms_summary": {"knowledge_items": 2, "community_reports": 2},
}

DEFAULT_TASK = "advisory_generation"


def select_for_task(envelope: DecisionContextEnvelope, task: str = DEFAULT_TASK) -> Dict[str, Any]:
    """Returns a plain dict (not a re-validated envelope) trimmed to the
    given task's budget -- the LLM-facing payload, not a new stored context.
    """
    budget = TASK_BUDGETS.get(task, TASK_BUDGETS[DEFAULT_TASK])
    data = envelope.model_dump()

    data["knowledge"]["retrieved_items"] = data["knowledge"]["retrieved_items"][: budget["knowledge_items"]]
    data["community"]["recent_reports"] = data["community"]["recent_reports"][: budget["community_reports"]]

    return data
