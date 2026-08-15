"""Flags LLM-generated advisory text that violates the project's
scientific-integrity rules, and deterministically repairs what it can in
place before the report is returned.

Never an LLM retry loop: the underlying LLM providers are free-tier and
already unreliable, so forcing a re-prompt/retry on every heuristic
violation risks empty responses more often than it catches a real problem.
Every repair here is a plain deterministic Python transformation (swap a
flagged area's text for its real evidence-grounded fallback narrative, or
rewrite a closed set of confirmed-language/observational-present idioms to
their forecast-safe equivalent) -- it always succeeds, never calls a model.
What CAN'T be repaired this way (currently: national-signal overstatement;
a wrong area-level signal count paired with a named area list; a forecast/
climatology value swapped in prose; a RELATIVE quintile classification
stated as a bare absolute "high"/"very high"; vulnerability attributed to a
climate/hazard driver; and an unsupported cross-area superlative claim
("the highest X") -- all whole-sentence framing problems with no
fixed-phrase substitution) stays detect-and-flag only. Either way,
violations are surfaced in
report["_metadata"]["validation_flags"] (what's still wrong in the
displayed report) and repairs in report["_metadata"]["auto_repaired"]
(what was fixed and why) -- never silently dropped.
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
#
# has/have, was/were, is/are cover both singular and plural subjects --
# confirmed real gap, caught while live-testing repair against real
# evidence: a singular-only version of this pattern silently let "were
# observed" and "are confirmed" (plural subjects, e.g. "local water
# sources were observed to run dry") through untouched.
CONFIRMED_LANGUAGE_PATTERN = re.compile(
    r"\b((?:has|have) (?:already )?occurred|(?:was|were) (?:already )?observed|"
    r"(?:has|have) been confirmed|(?:is|are) confirmed|drought has occurred|flooding has occurred)\b",
    re.IGNORECASE,
)

# Confirmed real false positive, caught while building auto-repair for this
# check: real Stage 3 output correctly advises "delay planting until
# reliable seasonal onset is confirmed" -- an instruction to wait for a
# FUTURE, LOCAL confirmation before acting, not a claim that confirmation
# has already happened. CONFIRMED_LANGUAGE_PATTERN's "is confirmed" branch
# can't tell these apart on its own, since the words are identical either
# way -- only the surrounding clause disambiguates. A match is excluded
# when its own clause (back to the nearest sentence boundary) starts with
# a conditional/future-gating word like "until"/"before"/"once"/"when".
_CONDITIONAL_LEAD_WORD_PATTERN = re.compile(r"\b(until|before|once|when)\b", re.IGNORECASE)


def _is_conditional_future_confirmation(text: str, match_start: int) -> bool:
    preceding = text[:match_start]
    last_boundary = max(preceding.rfind("."), preceding.rfind("!"), preceding.rfind("?"))
    clause = preceding[last_boundary + 1:]
    return bool(_CONDITIONAL_LEAD_WORD_PATTERN.search(clause))


def _find_confirmed_language_matches(text: str) -> List["re.Match[str]"]:
    """CONFIRMED_LANGUAGE_PATTERN matches, filtered for the conditional-
    future false positive above -- the single source both detection
    (_check_forecast_vs_observed_evidence) and repair (repair_confirmed_
    language_violations) use, so the two can never disagree about what
    counts as a real violation.
    """
    return [
        match for match in CONFIRMED_LANGUAGE_PATTERN.finditer(text)
        if not _is_conditional_future_confirmation(text, match.start())
    ]


# Deterministic forecast-safe substitution for each real CONFIRMED_LANGUAGE_
# PATTERN alternative -- one-to-one, so every possible match has a real
# replacement (no silent no-op fallback needed). Chosen to be drop-in
# grammatical replacements (same subject, swapped verb phrase) rather than
# generic hedge words, so the surrounding sentence still reads naturally.
_CONFIRMED_LANGUAGE_REPLACEMENTS = {
    "has already occurred": "is forecast to occur",
    "have already occurred": "are forecast to occur",
    "has occurred": "is forecast to occur",
    "have occurred": "are forecast to occur",
    "was already observed": "is projected",
    "were already observed": "are projected",
    "was observed": "is projected",
    "were observed": "are projected",
    "has been confirmed": "is indicated by the forecast",
    "have been confirmed": "are indicated by the forecast",
    "is confirmed": "is indicated by the forecast",
    "are confirmed": "are indicated by the forecast",
    "drought has occurred": "drought is forecast to occur",
    "flooding has occurred": "flooding is forecast to occur",
}


def _repair_confirmed_language_in_text(text: str) -> Tuple[str, bool]:
    """Rewrites every real (non-conditional-future) CONFIRMED_LANGUAGE_
    PATTERN match in `text` to its forecast-safe equivalent, in place.
    Returns (possibly-repaired text, whether anything actually changed) --
    the caller only needs to touch the report when the second value is
    True, avoiding a no-op write into every untouched field.
    """
    matches = _find_confirmed_language_matches(text)
    if not matches:
        return text, False
    pieces = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor:match.start()])
        matched_text = match.group(0)
        replacement = _CONFIRMED_LANGUAGE_REPLACEMENTS[matched_text.lower()]
        # Preserve sentence-initial capitalization -- the replacement map
        # is lowercase, but a match at the start of a sentence needs its
        # first letter capitalized to stay grammatical.
        if matched_text[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        pieces.append(replacement)
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces), True


# Confirmed real gap, caught via live testing: a real captured Stage 3
# advisory bullet wrote "protect the 30.72% exposed cropland from ONGOING
# rainfall deficits" -- this report is always a Month-2 SEASONAL FORECAST
# (see this module's own docstring: "there is no path that produces a
# report about a confirmed, already-observed event"), so describing a
# deficit as "ongoing" (a present-tense claim that it is ALREADY
# manifesting) is the same class of error CONFIRMED_LANGUAGE_PATTERN
# catches for past-tense claims, just in present tense instead. Deliberately
# narrow to a real lead phrase immediately followed by a real hazard noun
# (lookahead, not consumed -- so the match/replacement is just the lead
# phrase, leaving the noun's own grammatical form untouched) -- a bare
# "ongoing" alone is legitimate in plenty of contexts this report actually
# uses ("ongoing monitoring", "ongoing preparedness activities"), so this
# must not fire on the word alone.
OBSERVATIONAL_PRESENT_PATTERN = re.compile(
    r"\b(ongoing|currently experiencing|presently affected by|currently affected by)\b"
    r"(?=\s+(?:rainfall deficits?|drought|dry conditions?|dryness|wet conditions?|flood(?:ing)?|flood conditions?)\b)",
    re.IGNORECASE,
)

_OBSERVATIONAL_PRESENT_REPLACEMENTS = {
    "ongoing": "forecast",
    "currently experiencing": "forecast to experience",
    "presently affected by": "forecast to be affected by",
    "currently affected by": "forecast to be affected by",
}


def _repair_observational_present_in_text(text: str) -> Tuple[str, bool]:
    """Same deterministic in-place rewrite pattern as _repair_confirmed_
    language_in_text, for OBSERVATIONAL_PRESENT_PATTERN instead -- a
    separate, self-contained pair (not folded into CONFIRMED_LANGUAGE_
    PATTERN) because it catches a different grammatical class (present-
    tense "already manifesting" claims, not past-tense/perfect-aspect
    "already happened" ones), and keeping each pattern's own real-world
    story attached to its own name matters more here than avoiding a
    little structural duplication.
    """
    matches = list(OBSERVATIONAL_PRESENT_PATTERN.finditer(text))
    if not matches:
        return text, False
    pieces = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor:match.start()])
        matched_text = match.group(0)
        replacement = _OBSERVATIONAL_PRESENT_REPLACEMENTS[matched_text.lower()]
        if matched_text[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        pieces.append(replacement)
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces), True


def _check_observational_present_language(report: Dict[str, Any]) -> List[str]:
    if OBSERVATIONAL_PRESENT_PATTERN.search(_all_text(report)):
        return ["Report describes a forecast hazard as already ONGOING/current (e.g. \"ongoing rainfall deficits\"), but this report describes a forecast, not an already-manifesting condition."]
    return []


def repair_observational_present_violations(report: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Walks the same TEXT_FIELDS structure repair_confirmed_language_
    violations does, rewriting OBSERVATIONAL_PRESENT_PATTERN matches in
    place -- same "not an LLM re-prompt" reasoning as that function.
    """
    audit_notes: List[str] = []

    def repair_and_track(text: str, location: str) -> str:
        repaired, changed = _repair_observational_present_in_text(text)
        if changed:
            audit_notes.append(f"Auto-repaired observational-present language in {location}: forecast-safe phrasing substituted in place.")
        return repaired

    def repair_item(item: Dict[str, Any], location: str) -> None:
        for narrative_key in _NARRATIVE_TEXT_KEYS:
            if item.get(narrative_key):
                item[narrative_key] = repair_and_track(item[narrative_key], f"{location}.{narrative_key}")

    for key in TEXT_FIELDS:
        value = report.get(key)
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, list):
                    for item in sub_value:
                        if isinstance(item, dict):
                            repair_item(item, f"{key}.{sub_key} ({item.get('area')})")
                elif isinstance(sub_value, str):
                    value[sub_key] = repair_and_track(sub_value, f"{key}.{sub_key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    value[index] = repair_and_track(item, f"{key}[{index}]")
                elif isinstance(item, dict):
                    repair_item(item, f"{key} ({item.get('area') or item.get('justification_id') or item.get('layer') or item.get('indicator')})")
        elif isinstance(value, str):
            report[key] = repair_and_track(value, key)

    return report, audit_notes


# Confirmed real gap, caught via live testing: a real captured Stage 2
# executive_summary wrote "drought vulnerability is classified as very high
# nationally ... driven by severe rainfall deficits" -- vulnerability
# (v_drought/v_wet) is a real, independently-sourced baseline food-security/
# livelihood layer (FEWS NET IPC phase data, confirmed by reading
# app.data_pipeline.vulnerability_data_pipeline directly -- no rainfall or
# climate input anywhere in it), NOT something forecast rainfall/SPI/CDD/
# hazard probability causes. The real risk formula (100 x hazard_probability
# x severity x exposure x vulnerability, see report_stages._risk_definition_
# block) treats them as separate multiplicative factors, never one driving
# the other.
#
# Confirmed real false positive, caught while live-testing THIS check: an
# earlier, looser version also matched vulnerability appearing anywhere
# after the causal phrase, which fired on "Harari ranks first for drought
# ... driven by a very high hazard probability combined with moderate
# pre-existing vulnerability" -- there "driven by" governs the RANKING
# (hazard_probability and vulnerability listed together as co-factors of
# RISK, exactly per the real risk formula), not a claim that vulnerability
# itself was caused by hazard_probability. Narrowed to require
# "vulnerability" be immediately followed by a real linking verb (is/was/
# register(s)/exhibit(s)/show(s)/remain(s)) -- i.e. actually the
# grammatical SUBJECT of the causal clause, not merely co-mentioned nearby
# -- which the false-positive sentence never has (vulnerability is the
# LAST word there, followed by nothing).
_VULNERABILITY_CAUSAL_PATTERN = re.compile(
    r"\bvulnerabilit(?:y|ies)\b[^.!?]{0,20}\b(?:is|was|are|were|register(?:s|ed)?|exhibit(?:s|ed)?|show(?:s|ed)?|"
    r"remain(?:s|ed)?)\b[^.!?]{0,80}\b(?:driven by|because of|due to|caused by|results? from|attributable to)\b"
    r"[^.!?]{0,60}\b(?:rainfall|precipitation|spi|cdd|cwd|rx1day|rx5day|drought probability|wet probability|"
    r"hazard probability|anomal(?:y|ies))\b",
    re.IGNORECASE,
)


def _check_vulnerability_causality_evidence(report: Dict[str, Any]) -> List[str]:
    """Not auto-repaired, same reasoning as the other whole-sentence framing
    checks: reattributing a causal claim to the correct pair of factors
    isn't a fixed-phrase substitution. Detect-and-flag only.
    """
    if _VULNERABILITY_CAUSAL_PATTERN.search(_all_text(report)):
        return [
            "Report attributes a vulnerability value to a climate/hazard driver (e.g. rainfall, SPI, hazard "
            "probability) using causal language (\"driven by\"/\"because of\"/\"due to\") -- vulnerability is a "
            "real, separate, baseline food-security/livelihood factor, not something climate indicators cause."
        ]
    return []


# Confirmed real gap, caught via live testing: Stage 2's own real evidence
# gives it BOTH the National cross-indicator entry's own real, independently-
# computed signal (e.g. "partial_drought", agreement_score 0.6) AND several
# individual areas' real "strong_drought"/"strong_wet" signals -- a real
# Gemini response wrote "a strong national signal toward drought conditions"
# by counting how many areas were individually strong, silently overstating
# the actual national aggregate (which was only partial_drought). Narrow to
# "strong" + "national" + drought/wet within the same sentence (no period in
# between) specifically, matching CONFIRMED_LANGUAGE_PATTERN's own
# deliberately-narrow style -- broader phrasing risks the same false-
# positive class already found 3 times in this module (see
# _extract_candidate_place_names's history).
_NATIONAL_SIGNAL_STRENGTH_PATTERN = re.compile(
    r"\bstrong\b[^.!?]{0,60}\bnational\b[^.!?]{0,60}\b(drought|wet)\b|"
    r"\bnational\b[^.!?]{0,60}\bstrong\b[^.!?]{0,60}\b(drought|wet)\b",
    re.IGNORECASE,
)

# Updated for steps 6/7: compound_hazard_interpretation/data_quality_notes/
# agro_pastoral_advisory didn't exist when this list was first written and
# were silently never scanned for hallucinated content until now.
TEXT_FIELDS = [
    "executive_summary", "national_spatial_overview", "layer_by_layer_summary",
    "indicator_by_indicator_summary", "compound_hazard_interpretation", "data_quality_notes",
    "priority_area_justification", "farmer_advisory", "agro_pastoral_advisory",
    "humanitarian_priorities", "sms_messages",
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
        # "action" is the new structured advisory-bullet shape's real text
        # (see _ADVISORY_ITEM_SCHEMA); "message" is sms_messages' real SMS
        # text -- both were confirmed silently unscanned before being added.
        narrative_keys = ("differentiator", "recommended_intervention_type", "interpretation", "action", "message")
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
    # Real risk-class labels (see RISK_CLASS_BANDS / _risk_definition_block
    # in app.api.report_stages) -- Stage 2 is explicitly instructed to
    # classify risk_score using these 5 real classes ("Very low"/"Low"/
    # "Moderate"/"High"/"Very high"), so this is expected, correct
    # vocabulary, not an invented place. Confirmed live: "Very High, up
    # from Low" was being flagged as unmatched place names "Very High" /
    # "Low" before this was added.
    "very", "low", "moderate", "high",
    # Real climate-indicator vocabulary (see VISIBLE_CLIMATE_INDICATORS /
    # CLIMATE_INDICATOR_LABELS in app.api.ai_map_interpretation) that can
    # appear as standalone capitalized fragments mid-sentence -- "Rx" is
    # the confirmed live false positive ("the Rx anomaly", "Rx1day" itself
    # never matches the phrase regex since the trailing digit breaks the
    # word boundary, but the standalone "Rx" reference does); the rest are
    # added defensively for the same reason (each word/acronym of "Rx1day
    # (Daily Rainfall)", "Rx5day (5-Day Rainfall)", "Rainfall Total",
    # "Standardized Precipitation Index", "Consecutive dry/wet days",
    # "Rainfall percentile").
    "rx", "rainfall", "total", "daily", "standardized", "precipitation", "index",
    "consecutive", "dry", "wet", "days", "percentile", "anomaly", "spi", "cdd", "cwd",
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


def _is_generic_phrase(name: str) -> bool:
    """True when EVERY word in a (possibly multi-word) candidate is a known
    generic/domain word -- not just the whole phrase as one literal string.
    Catches real combinations like "Very High"/"Very Low" (risk-class
    labels) without needing every 2-word pairing enumerated in
    _GENERIC_CAPITALIZED_WORDS individually; a single generic word alone
    ("Low", "Rx") is also covered since a 1-word phrase trivially satisfies
    "every word is generic".
    """
    words = name.lower().split()
    return bool(words) and all(word in _GENERIC_CAPITALIZED_WORDS for word in words)


def _filter_unmatched_names(candidates: List[str], known_names_lower: List[str]) -> List[str]:
    return [
        name for name in candidates
        if not _is_generic_phrase(name)
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


def _add_repair_target(repair_targets: Dict[str, List[str]], justification_id: Any, message: str) -> None:
    if justification_id:
        repair_targets.setdefault(justification_id, []).append(message)


def _check_invented_locations_evidence(
    report: Dict[str, Any], evidence: Dict[str, Any], top_admin_areas: List[Dict[str, Any]],
) -> Tuple[List[str], Dict[str, List[str]]]:
    """Same heuristic shape as _check_invented_locations, but checked
    against the real area names in evidence["priority_area_justifications"]
    (deterministic, see app.context.statistical_evidence) instead of an
    envelope's own narrower field set.

    Scans each priority_area_justification item SEPARATELY (not one joined
    blob, like before) so a violation is always attributable to exactly one
    real area's justification_id -- required for repair_item_scoped_
    violations to know which single item to fix, without touching any
    other area's real LLM text. _extract_candidate_place_names's sentence-
    start exemption is position-relative to whatever text it's given, so
    scanning per-item (each item's own first sentence correctly exempted)
    is at least as accurate as the old joined-text approach, not less.
    """
    known_names_lower = [name.lower() for name in _real_names_from_priority_justifications(evidence, top_admin_areas)]

    messages: List[str] = []
    repair_targets: Dict[str, List[str]] = {}
    for item in report.get("priority_area_justification", []) or []:
        if not isinstance(item, dict):
            continue
        candidate_names = _extract_candidate_place_names(_item_narrative_text(item))
        unmatched = _filter_unmatched_names(candidate_names, known_names_lower)
        if unmatched:
            message = f"Mentioned name(s) not found in the computed evidence: {', '.join(sorted(set(unmatched))[:5])}"
            messages.append(message)
            _add_repair_target(repair_targets, item.get("justification_id"), message)
    return messages, repair_targets


def _check_modified_scores_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> Tuple[List[str], Dict[str, List[str]]]:
    """Same shape as _check_modified_risk_values, but real values come from
    evidence["priority_area_justifications"]'s real priority_score/
    risk_score fields -- richer than an envelope's single value, since it
    covers every real priority area, not just the one the envelope itself
    was built around. Scanned per-item (see _check_invented_locations_
    evidence) so a fabricated score is attributable to the one real area
    whose differentiator quoted it.
    """
    real_values = set()
    for item in evidence.get("priority_area_justifications", []) or []:
        if item.get("priority_score") is not None:
            real_values.add(round(float(item["priority_score"]), 2))
        if item.get("risk_score") is not None:
            real_values.add(round(float(item["risk_score"]), 2))

    messages: List[str] = []
    repair_targets: Dict[str, List[str]] = {}
    for item in report.get("priority_area_justification", []) or []:
        if not isinstance(item, dict):
            continue
        text = _item_narrative_text(item)
        quoted_scores = re.findall(r"\b(?:priority[_ ]score|risk[_ ]score)[^\d]{0,10}(\d\.\d{1,3})\b", text, re.IGNORECASE)
        for quoted in quoted_scores:
            if round(float(quoted), 2) not in real_values:
                message = f"Quoted score {quoted} does not match any real score in the computed evidence"
                messages.append(message)
                _add_repair_target(repair_targets, item.get("justification_id"), message)
    return messages, repair_targets


_PRIORITY_SCORE_MENTION_PATTERN = re.compile(r"\bpriority[_ ]score\b", re.IGNORECASE)


def _check_priority_score_cited_evidence(report: Dict[str, Any]) -> Tuple[List[str], Dict[str, List[str]]]:
    """priority_score is an internal ranking composite (see
    build_priority_area_justifications) with no standalone meaning to a
    reader -- unlike risk_score (has a real Very low..Very high class),
    hazard_probability, or vulnerability. build_stage2_prompt's
    differentiator rules explicitly forbid citing it, but a free-tier model
    doesn't always follow that instruction (confirmed live: Gemini Flash-
    Lite repeatedly wrote "priority score (0.600)" despite the rule) --
    detect-and-flag it the same way _check_modified_scores_evidence catches
    fabricated numbers, rather than trusting compliance silently. Scanned
    per-item (see _check_invented_locations_evidence) for the same
    single-area repair-attribution reason.
    """
    messages: List[str] = []
    repair_targets: Dict[str, List[str]] = {}
    for item in report.get("priority_area_justification", []) or []:
        if not isinstance(item, dict):
            continue
        if _PRIORITY_SCORE_MENTION_PATTERN.search(_item_narrative_text(item)):
            message = "Differentiator text cites priority_score, which the prompt explicitly forbids -- it has no standalone meaning to a reader; it should explain ranking via risk_score's class, hazard_probability, vulnerability, or exposure instead."
            messages.append(message)
            _add_repair_target(repair_targets, item.get("justification_id"), message)
    return messages, repair_targets


def _check_forecast_vs_observed_evidence(report: Dict[str, Any]) -> List[str]:
    """Every staged report is inherently a forecast -- unlike validate_
    against_context's version of this check, this doesn't need an
    envelope's evidence_status field, since it's always true for this
    app's report generation (there is no path that produces a report about
    a confirmed, already-observed event).
    """
    text = _all_text(report)
    if _find_confirmed_language_matches(text):
        return ["Report uses confirmed/observed language, but this report describes a forecast, not a confirmed observation."]
    return []


def _real_national_cross_indicator_signal(evidence: Dict[str, Any]) -> str | None:
    for item in evidence.get("cross_indicator_findings") or []:
        if isinstance(item, dict) and item.get("area") == "National":
            return item.get("signal")
    return None


def _check_national_signal_overstated_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """Confirmed real gap, caught via live testing (see
    _NATIONAL_SIGNAL_STRENGTH_PATTERN's own comment): the real National
    cross_indicator_findings entry is its own independently-computed
    aggregate (e.g. "partial_drought", agreement_score 0.6), separate from
    how many individual areas independently show a real "strong_drought"/
    "strong_wet" signal -- narrative text describing the NATIONAL picture as
    "strong" conflates the two. Skips entirely when no real National entry
    exists (nothing to validate against, same graceful-degradation
    convention as every other check here) or when the real signal actually
    IS strong (no overstatement possible).
    """
    real_signal = _real_national_cross_indicator_signal(evidence)
    if real_signal is None or real_signal in ("strong_drought", "strong_wet"):
        return []
    if _NATIONAL_SIGNAL_STRENGTH_PATTERN.search(_all_text(report)):
        return [
            f'Report describes a "strong" national drought/wet signal, but the real, independently-computed '
            f'National cross-indicator signal is "{real_signal}" -- national aggregate strength must be stated '
            f"from the National entry's own real signal, not inferred from how many individual areas are strong."
        ]
    return []


# Confirmed real gap, caught via live testing: Stage 2's real evidence
# gives it the per-area cross_indicator_findings list (see
# app.context.statistical_evidence.build_cross_indicator_findings) but was
# previously left to COUNT how many areas show a real "strong_drought"/
# "strong_wet" signal itself when narrating the area-level rollup -- a real
# captured run's cross_indicator_findings held exactly 6 real strong_drought
# areas, but the real Gemini response wrote "15 individual administrative
# zones independently display a strong drought signal (including Afar, Dire
# Dawa, Gambela, Harari, Oromia, Sidama, South Ethiopia, South West Ethiopia,
# and Tigray)" -- naming only 8 of the 15 it claimed. report_stages.
# build_stage2_prompt now hands Stage 2 the real, pre-counted tally (see
# app.context.statistical_evidence.area_signal_counts) with an explicit
# "use this exactly, do not count yourself" instruction -- the primary fix.
# This check is the backstop for when a real response still states a wrong
# number anyway. Deliberately narrow (number, then areas/zones/regions,
# then strong/partial + drought/wet + signal, all within one sentence) --
# same hand-tuned, false-positive-averse style as _NATIONAL_SIGNAL_
# STRENGTH_PATTERN above.
_AREA_SIGNAL_COUNT_PATTERN = re.compile(
    r"\b(\d+)\s+(?:individual\s+)?(?:administrative\s+)?(?:areas|zones|regions)\b"
    r"[^.!?]{0,60}\b(strong|partial)\b[^.!?]{0,20}\b(drought|wet)\b[^.!?]{0,20}\bsignal\b",
    re.IGNORECASE,
)


def _check_area_signal_count_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """Not auto-repaired, unlike _check_national_signal_overstated_evidence's
    sibling fix: fixing the stated number alone would still leave a real
    wrong/incomplete area-name list attached to it in the same sentence (see
    this check's own module-level comment -- the real captured violation
    named only 8 of its own claimed 15), and there's no safe fixed-phrase
    substitution for a named list an LLM invented. Detect-and-flag only,
    same reasoning already documented for the National-signal-strength
    check above.
    """
    from app.context.statistical_evidence import area_signal_counts

    real_counts = area_signal_counts(evidence.get("cross_indicator_findings") or []).get("counts", {})
    violations: List[str] = []
    for match in _AREA_SIGNAL_COUNT_PATTERN.finditer(_all_text(report)):
        stated_n = int(match.group(1))
        strength, hazard = match.group(2).lower(), match.group(3).lower()
        real_signal = f"{strength}_{hazard}"
        real_n = real_counts.get(real_signal, 0)
        if stated_n != real_n:
            violations.append(
                f'Report states {stated_n} areas show a "{real_signal}" signal, but the real, deterministic '
                f"count from cross_indicator_findings is {real_n} -- area-level counts must come from the "
                f"real per-area data, not be tallied by the model."
            )
    return violations


# Confirmed real gap, caught via live testing: report_stages.build_stage2_
# prompt already tells the model that forecast_mean/climatology_mean/
# anomaly_mean/anomaly_pct are four DIFFERENT real numbers and that the
# word "climatology"/"climatologically" must always introduce climatology_
# mean's own value (see the FORECAST VS CLIMATOLOGY LABELING prompt block).
# A real captured Stage 2 response still wrote "Climatologically, total
# rainfall averages 101.429 mm against a baseline of 129.697 mm" -- 101.429
# was the real FORECAST mean, not the climatology baseline; the sentence
# mislabels which real value the word "climatology" governs even though
# both real numbers were correctly present. Deliberately compares only to
# 1 decimal place (real prose rounds differently than the 3-decimal
# evidence, e.g. "101.4 mm" vs "101.429 mm") -- a coarser match is the
# right tradeoff here, same "narrow but real" precedent as the checks
# above.
_CLIMATOLOGY_LABEL_PATTERN = re.compile(
    r"\bclimatolog(?:y|ically)?\b[^.!?\d]{0,40}?(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _check_forecast_climatology_role_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """Not auto-repaired: the mislabel is which real number a sentence's
    surrounding words point at, not a fixed phrase -- there's no safe
    generic rewrite for a role-reversal buried inside otherwise-normal
    prose. Detect-and-flag only, same reasoning as the checks above.
    """
    from app.context.statistical_evidence import build_structured_indicator_summaries, build_structured_layer_summaries

    entries = build_structured_layer_summaries(evidence) + build_structured_indicator_summaries(evidence)
    forecast_values = {
        round(entry["forecast_mean"], 1)
        for entry in entries
        if isinstance(entry.get("forecast_mean"), (int, float)) and isinstance(entry.get("climatology_mean"), (int, float))
    }
    if not forecast_values:
        return []

    violations: List[str] = []
    for match in _CLIMATOLOGY_LABEL_PATTERN.finditer(_all_text(report)):
        stated = round(float(match.group(1)), 1)
        if stated in forecast_values:
            violations.append(
                f'Report uses "climatolog..." to introduce {stated}, but {stated} matches a real FORECAST mean, '
                f"not a real climatology baseline -- forecast_mean and climatology_mean must not be swapped in prose."
            )
    return violations


# Confirmed real gap, caught via live testing: a real captured Stage 2
# response wrote "wet probability registers a high national signal ... of
# 0.099" -- the real underlying classification_method for wet probability
# is quintiles_of_current_period (RELATIVE -- highest quintile THIS
# period, see CLASSIFICATION_METHOD_LEGEND in report_stages.py), and 0.099
# is only ~10% in absolute terms. report_stages.build_stage2_prompt already
# tells the model a RELATIVE "High" must read as "one of the highest
# nationally this period", not an absolute severity claim (see the
# CLASSIFICATION_METHOD LEGEND prompt block) -- this is the backstop for
# when a real response still states a bare "high"/"very high" next to a
# quintile-classified layer/indicator's own name with no qualifying word.
_RELATIVE_QUALIFIER_PATTERN = re.compile(
    r"\brelative(?:ly)?\b|\bamong the (?:higher|highest|lower|lowest)\b|"
    r"\bcompared (?:with|to) other\b|\b(?:current|this)[\s-]period(?:'s)? distribution\b",
    re.IGNORECASE,
)


def _check_relative_classification_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """Not auto-repaired, same reasoning as the checks above: inserting a
    qualifier into an LLM-authored sentence at the right grammatical spot
    isn't a fixed-phrase substitution. Detect-and-flag only.
    """
    from app.context.statistical_evidence import build_structured_indicator_summaries, build_structured_layer_summaries

    entries = build_structured_layer_summaries(evidence) + build_structured_indicator_summaries(evidence)
    text = _all_text(report)
    violations: List[str] = []
    for entry in entries:
        class_scheme = str(entry.get("classification_method") or "")
        if not class_scheme.startswith("quintiles_of"):
            continue
        signal = str(entry.get("national_signal") or "").strip().lower()
        if signal not in ("high", "very high"):
            continue
        name = entry.get("layer") or entry.get("indicator")
        if not name:
            continue
        display_name = re.escape(str(name).replace("_", " "))
        window_pattern = re.compile(
            rf"\b{display_name}\b[^.!?]{{0,80}}\b(?:high|very high)\b[^.!?]{{0,80}}[.!?]|"
            rf"\b(?:high|very high)\b[^.!?]{{0,80}}\b{display_name}\b[^.!?]{{0,80}}[.!?]",
            re.IGNORECASE,
        )
        for match in window_pattern.finditer(text):
            if not _RELATIVE_QUALIFIER_PATTERN.search(match.group(0)):
                violations.append(
                    f'Report describes "{name}" as "{signal}" with no relative qualifier, but its real '
                    f"classification_method ({class_scheme}) is quintile-based -- RELATIVE to this period's own "
                    f'distribution, not a fixed severity threshold. Must read as e.g. "one of the highest '
                    f'nationally this period", not a bare absolute "{signal}".'
                )
                break  # one flag per entry is enough signal; avoid duplicate noise per extra sentence match
    return violations


# Confirmed real gap, caught via live testing: a real captured Stage 2
# priority_area_justification differentiator claimed a top-ranked area was
# "driven by the highest hazard probability among drought areas" -- the
# real per-area data (hazard_probability across the same real top-5 drought
# batch) showed a DIFFERENT area actually had the higher value. The LLM was
# doing its own cross-area comparison instead of using the real,
# deterministic app.context.statistical_evidence.area_signal_counts-style
# tally now computed for exactly this (see _superlative_flags in
# statistical_evidence.py -- highest_among_group/lowest_among_group per
# area, per _SUPERLATIVE_METRICS). Gated on that field actually being
# PRESENT on the real evidence item (not just empty) -- an older evidence
# shape that never computed it means "no real ground truth to check
# against here", not "everything is unsupported"; skipping in that case
# avoids retroactively flagging evidence this check has no real basis to
# judge.
_SUPERLATIVE_METRIC_PHRASES = {
    "hazard_probability": re.compile(r"\bhazard probability\b", re.IGNORECASE),
    "vulnerability": re.compile(r"\bvulnerabilit(?:y|ies)\b", re.IGNORECASE),
    "population_exposed_pct": re.compile(r"\b(?:population exposed|exposed population|population exposure)\b", re.IGNORECASE),
    "risk_score": re.compile(r"\brisk score\b", re.IGNORECASE),
}
_HIGH_SUPERLATIVE_WORDS = ("highest", "largest", "greatest", "maximum")
_LOW_SUPERLATIVE_WORDS = ("lowest", "smallest", "least", "minimum")
_SUPERLATIVE_WINDOW_CHARS = 40


def _check_unsupported_superlative_claims_evidence(report: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """Not auto-repaired: real LLM phrasing of a superlative claim varies
    too much for a safe fixed-phrase substitution (unlike OBSERVATIONAL_
    PRESENT_PATTERN's closed lead-phrase set) -- detect-and-flag only, same
    reasoning as the other whole-sentence framing checks in this module.
    """
    real_by_id = {
        item.get("justification_id"): item
        for item in evidence.get("priority_area_justifications") or []
        if isinstance(item, dict)
    }
    violations: List[str] = []
    for report_item in report.get("priority_area_justification", []) or []:
        if not isinstance(report_item, dict):
            continue
        justification_id = report_item.get("justification_id")
        real_item = real_by_id.get(justification_id)
        if real_item is None or real_item.get("highest_among_group") is None:
            continue
        text = report_item.get("differentiator") or ""
        if not text:
            continue
        highest_ok = set(real_item.get("highest_among_group") or [])
        lowest_ok = set(real_item.get("lowest_among_group") or [])
        for metric, phrase_pattern in _SUPERLATIVE_METRIC_PHRASES.items():
            for phrase_match in phrase_pattern.finditer(text):
                window = text[max(0, phrase_match.start() - _SUPERLATIVE_WINDOW_CHARS):phrase_match.end()]
                claims_high = any(re.search(rf"\b{word}\b", window, re.IGNORECASE) for word in _HIGH_SUPERLATIVE_WORDS)
                claims_low = any(re.search(rf"\b{word}\b", window, re.IGNORECASE) for word in _LOW_SUPERLATIVE_WORDS)
                if claims_high and metric not in highest_ok:
                    violations.append(
                        f'{justification_id}: differentiator claims the highest real "{metric}" of this batch, '
                        f"but the real, deterministic comparison across this area's own real peer group does not "
                        f"support that (real highest_among_group for this area: {sorted(highest_ok) or 'none'})."
                    )
                if claims_low and metric not in lowest_ok:
                    violations.append(
                        f'{justification_id}: differentiator claims the lowest real "{metric}" of this batch, '
                        f"but the real, deterministic comparison across this area's own real peer group does not "
                        f"support that (real lowest_among_group for this area: {sorted(lowest_ok) or 'none'})."
                    )
    return violations


def repair_item_scoped_violations(
    report: Dict[str, Any],
    evidence: Dict[str, Any],
    repair_targets: Dict[str, List[str]],
) -> Tuple[Dict[str, Any], List[str]]:
    """Deterministic repair, not an LLM re-prompt: for each real area whose
    LLM-authored differentiator/recommended_intervention_type violated a
    scientific-integrity rule (invented location, fabricated score, or a
    forbidden priority_score citation), overwrites just THAT ONE item's
    text with the existing, already-real, evidence-grounded fallback
    narrative (see _fallback_single_priority_area_narrative in
    ai_map_interpretation.py -- the same text already used when a whole
    stage fails, now applied surgically to one flagged area). Every other
    area's real LLM narrative is left completely untouched.

    Deliberately NOT an LLM retry loop: this module's own docstring already
    documents why forcing a retry on this app's free-tier providers risks
    an empty response more often than it fixes a real problem -- a
    deterministic swap has no such failure mode and always succeeds.
    """
    if not repair_targets:
        return report, []

    from app.api.ai_map_interpretation import _fallback_single_priority_area_narrative

    fallback_by_id = {
        item["justification_id"]: _fallback_single_priority_area_narrative(item)
        for item in evidence.get("priority_area_justifications", []) or []
        if item.get("justification_id") in repair_targets
    }

    audit_notes: List[str] = []
    for item in report.get("priority_area_justification", []) or []:
        if not isinstance(item, dict):
            continue
        justification_id = item.get("justification_id")
        fallback = fallback_by_id.get(justification_id)
        if fallback is None:
            continue
        item["differentiator"] = fallback["differentiator"]
        item["recommended_intervention_type"] = fallback["recommended_intervention_type"]
        reasons = "; ".join(repair_targets[justification_id])
        audit_notes.append(f"Auto-repaired {justification_id}: replaced LLM narrative with deterministic fallback text after: {reasons}")

    return report, audit_notes


# Same 5 narrative keys _item_narrative_text scans (differentiator/
# recommended_intervention_type/interpretation/action/message) -- kept as
# its own name here since this walker MUTATES those keys in place, not
# just reads them for scanning.
_NARRATIVE_TEXT_KEYS = ("differentiator", "recommended_intervention_type", "interpretation", "action", "message")


def repair_confirmed_language_violations(report: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Deterministic repair for _check_forecast_vs_observed_evidence,
    unlike repair_item_scoped_violations: there's no single real area
    object to swap out here (a confirmed-language phrase can appear in
    ANY of TEXT_FIELDS's many differently-shaped fields), so this walks
    the SAME structure _all_text scans (mirroring its dict-of-lists /
    list-of-strings / list-of-dicts-with-narrative-keys branches) and
    rewrites each real violating phrase in place via _repair_confirmed_
    language_in_text, rather than swapping a whole field's text.

    Still not an LLM re-prompt -- see repair_item_scoped_violations'
    docstring for why this module avoids that. A closed, real set of
    confirmed-language idioms (see _CONFIRMED_LANGUAGE_REPLACEMENTS) maps
    to a deterministic forecast-safe replacement, so no LLM call is needed
    here either.
    """
    audit_notes: List[str] = []

    def repair_and_track(text: str, location: str) -> str:
        repaired, changed = _repair_confirmed_language_in_text(text)
        if changed:
            audit_notes.append(f"Auto-repaired confirmed/observed language in {location}: forecast-safe phrasing substituted in place.")
        return repaired

    def repair_item(item: Dict[str, Any], location: str) -> None:
        for narrative_key in _NARRATIVE_TEXT_KEYS:
            if item.get(narrative_key):
                item[narrative_key] = repair_and_track(item[narrative_key], f"{location}.{narrative_key}")

    for key in TEXT_FIELDS:
        value = report.get(key)
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, list):
                    for item in sub_value:
                        if isinstance(item, dict):
                            repair_item(item, f"{key}.{sub_key} ({item.get('area')})")
                elif isinstance(sub_value, str):
                    value[sub_key] = repair_and_track(sub_value, f"{key}.{sub_key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    value[index] = repair_and_track(item, f"{key}[{index}]")
                elif isinstance(item, dict):
                    repair_item(item, f"{key} ({item.get('area') or item.get('justification_id') or item.get('layer') or item.get('indicator')})")
        elif isinstance(value, str):
            report[key] = repair_and_track(value, key)

    return report, audit_notes


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

    Phase 2: the 3 checks scoped to one priority_area_justification item
    (invented location, fabricated score, forbidden priority_score
    citation) are deterministically repaired in place via repair_item_
    scoped_violations before the FINAL validation_flags are computed --
    generate -> validate -> repair -> validate again -> return, not
    generate -> validate -> show the violation anyway.

    Phase 3: confirmed-language ("has occurred"/"is confirmed"/etc, see
    CONFIRMED_LANGUAGE_PATTERN) is ALSO now repaired, via repair_confirmed_
    language_violations -- a real closed set of idioms, each with a
    deterministic forecast-safe replacement, so no LLM re-prompt is needed
    here either even though (unlike the 3 item-scoped checks) there's no
    single area object to swap out; it rewrites the matched phrase in
    place wherever in TEXT_FIELDS it appears. repair_observational_present_
    violations (a real "ongoing rainfall deficits"-style present-tense
    already-manifesting claim, distinct from CONFIRMED_LANGUAGE_PATTERN's
    past-tense/perfect-aspect class) is repaired the same way, right after
    it. national-signal-overstatement, area-signal-count mismatch,
    forecast/climatology role reversal, unqualified relative-classification
    wording, vulnerability-causality mislabeling, and unsupported
    cross-area superlative claims are the remaining detect-and-flag-only
    checks -- all are whole-sentence framing problems (which parts of a
    sentence describe which real value, aggregate, or comparison), not a
    fixed-phrase substitution, so no safe deterministic rewrite exists for
    any of them yet.

    A separate, additive report["_metadata"]["auto_repaired"] audit trail
    records what was fixed and why, kept distinct from validation_flags
    (which reflects what's still wrong in the report actually being
    displayed) so a repair is visible without being conflated with an
    unresolved problem.
    """
    top_admin_areas = top_admin_areas or []

    invented_location_messages, invented_location_targets = _check_invented_locations_evidence(report, evidence, top_admin_areas)
    modified_score_messages, modified_score_targets = _check_modified_scores_evidence(report, evidence)
    priority_score_messages, priority_score_targets = _check_priority_score_cited_evidence(report)

    repair_targets: Dict[str, List[str]] = {}
    for targets in (invented_location_targets, modified_score_targets, priority_score_targets):
        for justification_id, messages in targets.items():
            repair_targets.setdefault(justification_id, []).extend(messages)

    report, auto_repaired = repair_item_scoped_violations(report, evidence, repair_targets)
    report, confirmed_language_repairs = repair_confirmed_language_violations(report)
    report, observational_present_repairs = repair_observational_present_violations(report)
    auto_repaired = auto_repaired + confirmed_language_repairs + observational_present_repairs

    # Re-run only the 3 item-scoped checks against the now-repaired report
    # -- "validate again", not an assumption that the deterministic swap
    # worked. Expected to always come back empty (the fallback narrative is
    # known-clean), but confirming beats assuming.
    item_scoped_violations: List[str] = []
    if repair_targets:
        item_scoped_violations.extend(_check_invented_locations_evidence(report, evidence, top_admin_areas)[0])
        item_scoped_violations.extend(_check_modified_scores_evidence(report, evidence)[0])
        item_scoped_violations.extend(_check_priority_score_cited_evidence(report)[0])
    else:
        item_scoped_violations = invented_location_messages + modified_score_messages + priority_score_messages

    # _check_forecast_vs_observed_evidence runs AFTER repair_confirmed_
    # language_violations above, on the already-repaired report -- the
    # same "validate again" discipline, just without needing a separate
    # explicit re-run block since there was no pre-repair count to compare.
    violations = (
        item_scoped_violations
        + _check_forecast_vs_observed_evidence(report)
        + _check_observational_present_language(report)
        + _check_national_signal_overstated_evidence(report, evidence)
        + _check_area_signal_count_evidence(report, evidence)
        + _check_forecast_climatology_role_evidence(report, evidence)
        + _check_relative_classification_evidence(report, evidence)
        + _check_vulnerability_causality_evidence(report)
        + _check_unsupported_superlative_claims_evidence(report, evidence)
    )

    metadata = report.setdefault("_metadata", {})
    existing_flags = metadata.get("validation_flags", [])
    metadata["validation_flags"] = existing_flags + violations
    existing_repaired = metadata.get("auto_repaired", [])
    metadata["auto_repaired"] = existing_repaired + auto_repaired

    return report, violations
