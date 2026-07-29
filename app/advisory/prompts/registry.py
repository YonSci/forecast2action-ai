"""Prompt version registry.

Every generated advisory should record which prompt_version produced it
(see ProvenanceContext.prompt_version). Prompts are NOT embedded directly
inside large Python functions -- each version lives in its own file here.
"""

from typing import Dict

from app.advisory.prompts.v1_system import SYSTEM_PROMPT_V1
from app.advisory.prompts.v2_system import SYSTEM_PROMPT_V2

DEFAULT_PROMPT_VERSION = "v1"

PROMPT_VERSIONS: Dict[str, str] = {
    "v1": SYSTEM_PROMPT_V1,
    "v2": SYSTEM_PROMPT_V2,
}


def get_system_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    return PROMPT_VERSIONS.get(version, PROMPT_VERSIONS[DEFAULT_PROMPT_VERSION])
