"""Flags (does not block) LLM-generated advisory text that violates the
project's scientific-integrity rules, when checked against a real Decision
Context Envelope.

Phase-1 is detect-and-flag, not block-and-fail: the underlying LLM
providers are free-tier and already unreliable, so forcing a retry loop on
every heuristic violation risks empty responses more often than it catches
a real problem. Violations are surfaced in report["_metadata"]["validation_flags"]
for the frontend to show, never silently dropped.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

if TYPE_CHECKING:
    from app.context.schemas import DecisionContextEnvelope

# Deliberately narrow to ASSERTIVE past-tense/perfect-aspect claims that a
# hazard event already happened -- NOT bare presence of words like
# "confirm"/"observed" on their own, since hedged/instructive phrasing
# ("confirm whether X is becoming observed impact") legitimately uses those
# words without asserting anything has occurred. Caught via manual
# end-to-end testing: the rule-based fallback's own template text
# ("...to confirm whether forecast risk is becoming observed impact")
# was a false positive under the looser bare-word version of this pattern.
CONFIRMED_LANGUAGE_PATTERN = re.compile(
    r"\b(has (?:already )?occurred|was (?:already )?observed|has been confirmed|"
    r"is confirmed|drought has occurred|flooding has occurred)\b",
    re.IGNORECASE,
)

# Updated for steps 6/7: compound_hazard_interpretation/data_quality_notes/
# agro_pastoral_advisory didn't exist when this list was first written and
# were silently never scanned for hallucinated content until now.
TEXT_FIELDS = [
    "executive_summary", "national_spatial_overview", "layer_by_layer_summary",
    "indicator_by_indicator_summary", "compound_hazard_interpretation", "data_quality_notes",
    "priority_area_justification", "farmer_advisory", "agro_pastoral_advisory",
    "humanitarian_priorities", "sms_summary",
]


def _join_sentences(parts: List[str]) -> str:
    """Joins text fragments for regex scanning, ensuring each fragment ends
    with sentence-terminal punctuation before the next one starts. Plain
    " ".join() was confirmed live to produce false positives: recommended_
    intervention_type strings ("...response") don't end in a period, so
    joining item[0]'s intervention_type directly against item[1]'s
    differentiator ("...response Ranks #2 for drought risk...") hid the
    real sentence boundary from _extract_candidate_place_names's sentence-
    start check, letting "Ranks" through as a false-positive place name.
    """
    normalized = []
    for part in parts:
        text = str(part).rstrip()
        if not text:
            continue
        if text[-1] not in ".!?":
            text += "."
        normalized.append(text)
    return " ".join(normalized)


def _item_narrative_text(item: Any) -> str:
    """Coerces one TEXT_FIELDS list item to plain text for scanning. Most
    array items are strings, but some are OBJECTS with a mix of real,
    already-validated fields and LLM-authored narrative -- only the
    narrative keys are scanned, not a raw Python dict repr of the whole
    object. Covers both known object shapes: priority_area_justification
    (differentiator/recommended_intervention_type -- see app.context.
    statistical_evidence.build_priority_area_justifications) and the
    Phase 3 #17 structured layer_by_layer_summary/indicator_by_indicator_
    summary objects (interpretation -- see build_structured_layer_
    summaries/build_structured_indicator_summaries). A dict missing a given
    key simply contributes nothing for that key, so this works for either
    shape without needing to know which one it's looking at.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        narrative_keys = ("differentiator", "recommended_intervention_type", "interpretation")
        return _join_sentences([item[key] for key in narrative_keys if item.get(key)])
    return str(item)


def _all_text(report: Dict[str, Any]) -> str:
    parts = []
    for key in TEXT_FIELDS:
        value = report.get(key)
        if isinstance(value, dict):
            # farmer_advisory/agro_pastoral_advisory/humanitarian_priorities
            # (step 7 items 6/7) are now timescale/category objects, not flat
            # arrays -- flatten each sub-list the same way the list branch
            # below does, so this field isn't silently skipped entirely.
            for sub_value in value.values():
                if isinstance(sub_value, list):
                    parts.extend(_item_narrative_text(item) for item in sub_value)
                elif isinstance(sub_value, str):
                    parts.append(sub_value)
        elif isinstance(value, list):
            parts.extend(_item_narrative_text(item) for item in value)
        elif isinstance(value, str):
            parts.append(value)
    return " ".join(parts)


_CAPITALIZED_PHRASE_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2})\b(?!-)")

# Confirmed via live testing (step 11): once priority_area_justification's
# "text" became free-form LLM-authored differentiator prose (step 7) rather
# than a fixed-pattern description, a bare capitalized-word regex flagged
# ordinary sentence-initial words ("Distinguished by...", "Highest
# priority...") as invented place names -- a real false-positive rate this
# module didn't have when it only ever scanned the old, narrower single-
# sentence-per-area text.
_GENERIC_CAPITALIZED_WORDS = {
    "risk", "priority", "executive", "summary", "forecast", "exposure", "vulnerability", "hazard",
    "water", "drought", "flood", "recommended", "cross", "distinguished", "characterized", "marked",
    "identified", "highlighted", "captures", "presents", "combines", "enters", "highest", "lowest",
    "mid", "multi", "top", "compound", "overall", "national", "regional", "ranks", "holds",
    # Real Ethiopian season names (Kiremt = main rainy season Jun-Sep,
    # Belg = short rains Feb-May, Bega = dry season Oct-Jan) -- legitimate
    # domain vocabulary the LLM correctly uses, not an invented place.
    "kiremt", "belg", "bega",
}


def _extract_candidate_place_names(text: str) -> List[str]:
    """Extracts capitalized-phrase candidates from free-form narrative text,
    excluding the two confirmed sources of false positives: sentence-
    initial words (any capitalized word can start a sentence; that alone
    says nothing about whether it's a place name) and the first half of a
    hyphenated compound word (e.g. "Multi-hazard" incorrectly yielding
    "Multi" as a standalone match, since the regex's character class stops
    at the hyphen).
    """
    candidates = []
    for match in _CAPITALIZED_PHRASE_PATTERN.finditer(text):
        preceding = text[: match.start()].rstrip()
        is_sentence_start = not preceding or preceding[-1] in ".!?"
        if is_sentence_start:
            continue
        candidates.append(match.group(1))
    return candidates


def _filter_unmatched_names(candidates: List[str], known_names_lower: List[str]) -> List[str]:
    return [
        name for name in candidates
        if name.lower() not in _GENERIC_CAPITALIZED_WORDS
        and not any(name.lower() in known or known in name.lower() for known in known_names_lower)
    ]


# validate_against_context (envelope-scoped invented-locations/modified-
# risk-values/forecast-vs-observed checks) was removed here: every one of
# its checks was fully superseded by the "_evidence" versions below, which
# run unconditionally for every staged report (validate_against_evidence)
# against the REAL evidence the report was actually generated from
# (evidence["priority_area_justifications"], covering every real priority
# area) -- not an envelope's single selected area plus a separately-built
# top_admin_areas list. Since a context_id is sent on every real request,
# validate_against_context always ran too, and its narrower reference data
# produced confirmed false positives (e.g. flagging Harari's real, legitimately-
# cited priority_score as "not found in the supplied context" purely because
# the envelope was built around a different area). Removed rather than fixed
# in place, since fixing it would have just reimplemented the "_evidence"
# checks a second time for no benefit -- generate_ai_map_interpretation no
# longer calls it at all, only using the envelope for evidence_citations now.


# Step 11 -- generalizes the checks above to run for EVERY staged report,
# not just context-aware (envelope) ones. Uses the real `evidence` object
# app.context.statistical_evidence already computes for every report (see
# app.api.report_stages.run_staged_report_generation) instead of requiring
# a Decision Context Envelope. Same detect-and-flag convention -- see
# module docstring.


def _real_names_from_priority_justifications(
    evidence: Dict[str, Any], top_admin_areas: List[Dict[str, Any]],
) -> List[str]:
    names = set()
    for item in evidence.get("priority_area_justifications", []) or []:
        if item.get("area"):
            names.add(item["area"])
    for item in top_admin_areas:
        for key in ("area_name", "region", "zone", "woreda"):
            if item.get(key):
                names.add(item[key])
    return [name for name in names if name]


def _check_invented_locations_evidence(
    report: Dict[str, Any], evidence: Dict[str, Any], top_admin_areas: List[Dict[str, Any]],
) -> List[str]:
    """Same heuristic shape as _check_invented_locations, but checked
    against the real area names in evidence["priority_area_justifications"]
    (deterministic, see app.context.statistical_evidence) instead of an
    envelope's own narrower field set.
    """
    justification_text = _join_sentences([_item_narrative_text(item) for item in report.get("priority_area_justification", [])])
    known_names_lower = [name.lower() for name in _real_names_from_priority_justifications(evidence, top_admin_areas)]

    candidate_names = _extract_candidate_place_names(justification_text)
    unmatched = _filter_unmatched_names(candidate_names, known_names_lower)

    if unmatched:
        return [f"Mentioned name(s) not found in the computed evidence: {', '.join(sorted(set(unmatched))[:5])}"]
    return []


def _check_modified_scores_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """Same shape as _check_modified_risk_values, but real values come from
    evidence["priority_area_justifications"]'s real priority_score/
    risk_score fields -- richer than an envelope's single value, since it
    covers every real priority area, not just the one the envelope itself
    was built around.
    """
    text = " ".join(_item_narrative_text(item) for item in report.get("priority_area_justification", []))
    quoted_scores = re.findall(r"\b(?:priority[_ ]score|risk[_ ]score)[^\d]{0,10}(\d\.\d{1,3})\b", text, re.IGNORECASE)

    real_values = set()
    for item in evidence.get("priority_area_justifications", []) or []:
        if item.get("priority_score") is not None:
            real_values.add(round(float(item["priority_score"]), 2))
        if item.get("risk_score") is not None:
            real_values.add(round(float(item["risk_score"]), 2))

    flags = []
    for quoted in quoted_scores:
        if round(float(quoted), 2) not in real_values:
            flags.append(f"Quoted score {quoted} does not match any real score in the computed evidence")
    return flags


def _check_forecast_vs_observed_evidence(report: Dict[str, Any]) -> List[str]:
    """Every staged report is inherently a forecast -- unlike validate_
    against_context's version of this check, this doesn't need an
    envelope's evidence_status field, since it's always true for this
    app's report generation (there is no path that produces a report about
    a confirmed, already-observed event).
    """
    text = _all_text(report)
    if CONFIRMED_LANGUAGE_PATTERN.search(text):
        return ["Report uses confirmed/observed language, but this report describes a forecast, not a confirmed observation."]
    return []


def validate_against_evidence(
    report: Dict[str, Any],
    evidence: Dict[str, Any],
    top_admin_areas: List[Dict[str, Any]] | None = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Runs the same class of checks as validate_against_context, for
    EVERY staged report (called unconditionally from app.api.report_stages
    .run_staged_report_generation, regardless of whether a Decision
    Context Envelope is present) -- the default report-generation path
    previously received zero content validation, only JSON-shape
    validation. Same additive convention as validate_against_context:
    report["_metadata"]["validation_flags"] is appended to, never
    overwritten, so this can run alongside validate_against_context
    without either one clobbering the other's flags.
    """
    top_admin_areas = top_admin_areas or []

    violations: List[str] = []
    violations.extend(_check_invented_locations_evidence(report, evidence, top_admin_areas))
    violations.extend(_check_modified_scores_evidence(report, evidence))
    violations.extend(_check_forecast_vs_observed_evidence(report))

    metadata = report.setdefault("_metadata", {})
    existing_flags = metadata.get("validation_flags", [])
    metadata["validation_flags"] = existing_flags + violations

    return report, violations
