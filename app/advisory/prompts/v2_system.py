"""v2 system prompt -- adds the context-envelope-specific "must not" rules
from the project's context engineering spec (§15), for use only when a
Decision Context Envelope (context_id) is supplied. NOT the default --
callers must explicitly request prompt_version="v2" (or supply a
context_id, which the endpoint treats as an implicit v2 request) to get
this behavior.

Step 10 revision: shares BASE_GROUNDING_RULES with v1_system.py (role
framing + universal grounding, no longer duplicated with drift risk) and
drops the same stale single-call procedural task description v1 had --
task instructions now live entirely in app.api.report_stages's per-stage
prompt builders. What remains here is genuinely envelope-specific: rules
that only make sense when a structured Decision Context Envelope (with
community evidence, retrieved knowledge, decision policy) is actually
present.

Phase 2 revision: shares the same stage-aware role-block swap as
v1_system.py's build_system_prompt_v1 -- see that module's docstring for
why the old "interpret Ethiopia-wide forecast map layers" claim was wrong
for Stage 2/3. Since every real dashboard-driven generation builds a
Decision Context Envelope first (app.api.ai_map_interpretation.merge_
envelope_into_request defaults prompt_version to "v2" whenever a context_id
is present and the caller didn't request a specific version), this is the
system prompt actually used in practice today, not v1 -- so this fix
matters here at least as much as in v1_system.py.
"""

from typing import Optional

from app.advisory.prompts.v1_system import (
    BASE_GROUNDING_RULES,
    LEGACY_ROLE_STATEMENT,
    ROLE_OPENING,
    STAGE_ROLE_BLOCKS,
)

_V2_ENVELOPE_NOTE = (
    "A structured Decision Context Envelope (forecast evidence, geographic context, hazard evidence, "
    "impact context, community evidence, decision policy, retrieved knowledge) may be folded into the "
    "evidence you are given -- treat it as an additional source of truth alongside that evidence, not a "
    "replacement for it."
)

_V2_ADDITIONAL_RULES = """
Additional rules that apply only because a Decision Context Envelope is supplied:
- Distinguish forecast signals, community-reported evidence, model-derived inferences, and recommended actions from one another explicitly in your language.
- Base every operational recommendation only on the retrieved knowledge items supplied in the context -- do not propose actions from general knowledge that aren't grounded in a retrieved item.
- When discussing priority-area targeting, state explicitly whether the empirical evidence (hazard, exposure, vulnerability, risk, and community evidence) substantiates that targeting.
""".strip()


def build_system_prompt_v2(stage: Optional[str] = None) -> str:
    role = STAGE_ROLE_BLOCKS.get(stage, LEGACY_ROLE_STATEMENT)
    return f"""
{ROLE_OPENING}

{role}

{_V2_ENVELOPE_NOTE}

{BASE_GROUNDING_RULES}

{_V2_ADDITIONAL_RULES}
""".strip()


# Backward-compat: the exact original (legacy, stage-agnostic) text, for
# anything that still imports this name directly instead of calling
# build_system_prompt_v2().
SYSTEM_PROMPT_V2 = build_system_prompt_v2()
