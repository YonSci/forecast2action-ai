"""Prompt version registry.

Every generated advisory should record which prompt_version produced it
(see ProvenanceContext.prompt_version). Prompts are NOT embedded directly
inside large Python functions -- each version lives in its own file here.
"""

from typing import Callable, Dict, Optional

from app.advisory.prompts.v1_system import build_system_prompt_v1
from app.advisory.prompts.v2_system import build_system_prompt_v2

DEFAULT_PROMPT_VERSION = "v1"

PROMPT_BUILDERS: Dict[str, Callable[[Optional[str]], str]] = {
    "v1": build_system_prompt_v1,
    "v2": build_system_prompt_v2,
}


def get_system_prompt(version: str = DEFAULT_PROMPT_VERSION, stage: Optional[str] = None) -> str:
    """`stage` is one of "stage1"/"stage2"/"stage3" (see app.api.report_
    stages) to get that stage's own role framing, or None for the legacy,
    stage-agnostic framing (app.api.ai_map_interpretation's single-call
    provider functions, which still interpret everything in one call).
    """
    builder = PROMPT_BUILDERS.get(version, PROMPT_BUILDERS[DEFAULT_PROMPT_VERSION])
    return builder(stage)
