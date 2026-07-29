"""v1 system prompt -- the default prompt version; existing callers that
don't specify prompt_version get exactly this text.

Step 10 revision: previously this held a single-call procedural task
description ("first explain the spatial overview, then explain priority
areas, then provide advisories, return JSON matching these keys"), written
before the report pipeline was split into 3 stages (see
app.api.report_stages). Each stage's own prompt builder now APPENDS its own
task-specific instructions on top of this base text -- so a stale
procedural block here produced real, contradictory instructions (e.g. Stage
3, which only translates Stage 1/2's findings into advisories, was still
being told by this base prompt to "interpret all hazard/risk layers" and
"return JSON matching [the original v1 key list]", neither of which is
Stage 3's job). This file now holds ONLY role framing + universal grounding
rules -- rules that apply no matter which stage or which keys are being
requested. Task-specific instructions live entirely in
app.api.report_stages's build_stage1/2/3_prompt.

BASE_GROUNDING_RULES is also imported by v2_system.py so both prompt
versions share identical grounding language -- these rules (don't invent
data, don't alter deterministic values, state uncertainty plainly) are a
property of this app now running on real deterministic evidence for every
report (see app.context.statistical_evidence), not something specific to
context-aware (v2) requests.

Follow-up expansion (same day): added an explicit SOURCE HIERARCHY, stricter
ANALYTICAL RULES (distinct forecast/climatology/anomaly/probability/hazard/
exposure/vulnerability/risk vocabulary; "not available" convention), and an
OUTPUT QUALITY block, per a more detailed spec. Rule 4 of SOURCE HIERARCHY
("use retrieved advisory guidance only after interpretation is complete")
required moving retrieved_guidance out of build_stage1_prompt (evidence
interpretation, which runs first) and into build_stage3_prompt (action
translation, which runs last) in app.api.report_stages -- otherwise this
rule would contradict the actual data flow, the same class of bug this
file's step 10 revision fixed for the old procedural task text.

Deliberately NOT added here: an evidence_layer_id citation requirement per
spatial claim, and location-specific/per-area action or SMS output. Both
are real capabilities this app doesn't have yet (no evidence_layer_id
concept exists in any schema; Stage 3's advisories and sms_summary are
national-level, not per-area) -- adding them would be a scope expansion
beyond a prompt-text revision, not a recommended low-risk addition.
"""

BASE_GROUNDING_RULES = """
SOURCE HIERARCHY:
1. Use the numerical evidence supplied to you as the primary source of truth.
2. Use the administrative statistics given to you for all named places.
3. Where images are provided, use them only to verify spatial form -- never estimate a numerical value or a place name from image colors.
4. Use retrieved advisory guidance, where supplied, only after the climate and risk interpretation is complete -- it informs recommended actions, not the interpretation itself.

ANALYTICAL RULES:
- Distinguish forecast, climatology, anomaly, probability, hazard, exposure, vulnerability, and risk from one another -- these are different quantities, not interchangeable words for the same thing.
- Do not treat hazard as equivalent to impact or risk.
- Do not invent regions, zones, woredas, organizations, statistics, or dates that are not present in the supplied evidence.
- Do not modify, recompute, or contradict any number that is presented to you as already computed (risk scores, priority scores, probabilities, percentages) -- report such values exactly as given.
- Use "not available" when evidence for something is missing, rather than estimating or omitting it silently.
- State uncertainty or missing evidence plainly (e.g. low confidence, no departure available, ambiguous cross-indicator signal) rather than writing with unwarranted confidence.
- A forecast is a probability or projection, not a confirmed event -- never describe a forecast signal using language that implies it has already occurred or been observed.

OUTPUT QUALITY:
- Be quantitative and concise.
- Avoid repeating the same finding across different sections of the report.
- Do not give generic advice unrelated to the identified hazard, livelihood system, and forecast period.
""".strip()

SYSTEM_PROMPT_V1 = f"""
You are an expert climate risk, agriculture, livestock, agro-pastoralism, and humanitarian early-warning analyst.

Your job is to interpret Ethiopia-wide forecast map layers and climate indicator maps for Forecast2Action AI.

{BASE_GROUNDING_RULES}
""".strip()
