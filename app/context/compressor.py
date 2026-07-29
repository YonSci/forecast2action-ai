"""Structural context compression -- truncates with a clear marker rather
than silently cutting a JSON object in half. Reuses app.api.
ai_map_interpretation.compact_json (the exact truncation behavior already
used for the existing LLM prompt payload) rather than reimplementing it.
"""

from typing import Any, Dict

from app.api.ai_map_interpretation import compact_json

CONTEXT_LIMITS = {
    "advisory_generation": 16000,
    "sms_summary": 3000,
}

DEFAULT_TASK = "advisory_generation"


def compress_envelope(data: Dict[str, Any], task: str = DEFAULT_TASK) -> str:
    max_chars = CONTEXT_LIMITS.get(task, CONTEXT_LIMITS[DEFAULT_TASK])
    return compact_json(data, max_chars=max_chars)
