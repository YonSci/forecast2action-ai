from app.advisory.response_validator import _all_text, validate_against_evidence

REAL_EVIDENCE = {
    "priority_area_justifications": [
        # rank/risk_class/action_status/hazard_probability included (not
        # just priority_score/risk_score) because repair_item_scoped_
        # violations' fallback narrative (_fallback_single_priority_area_
        # narrative) reads all of these -- a real priority_area_
        # justifications entry always has them (see build_priority_area_
        # justifications), and an incomplete fixture here previously let a
        # literal "None" leak into repaired text ("Ranks #None nationally"),
        # which _check_invented_locations_evidence then flagged as an
        # invented place name -- a fixture gap, not a real product bug.
        {"justification_id": "Harari::drought", "area": "Harari", "hazard_type": "drought", "rank": 1, "priority_score": 0.599, "risk_score": 23.6, "risk_class": "Low", "action_status": "preparedness", "hazard_probability": 0.787},
        {"justification_id": "Afar::wet", "area": "Afar", "hazard_type": "wet", "rank": 2, "priority_score": 0.42, "risk_score": 12.1, "risk_class": "Very low", "action_status": "monitor_only", "hazard_probability": 0.3},
    ],
}


def _report(priority_area_justification, **extra_fields):
    report = {
        "priority_area_justification": priority_area_justification,
        "executive_summary": "",
        "national_spatial_overview": [],
        "farmer_advisory": [],
        "humanitarian_priorities": [],
        "sms_messages": [],
    }
    report.update(extra_fields)
    return report


def test_validate_against_evidence_does_not_flag_real_area_names_and_scores():
    report = _report([
        {
            "justification_id": "Harari::drought",
            "area": "Harari",
            "priority_score": 0.599,
            "risk_score": 23.6,
            "differentiator": "Harari has the highest hazard probability and risk score of 23.6 nationally.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_validate_against_evidence_auto_repairs_invented_area_name():
    # Confirmed real gap, fixed: the violation used to just sit in
    # validation_flags while "Wollega" reached the displayed report
    # unchanged. It's now deterministically repaired -- the report's own
    # differentiator no longer contains the invented name, violations is
    # clean (the DISPLAYED text is what's being validated), and the repair
    # is recorded separately in auto_repaired for transparency.
    report = _report([
        {
            "justification_id": "Harari::drought",
            "area": "Harari",
            "priority_score": 0.599,
            "risk_score": 23.6,
            "differentiator": "Ranks highest, alongside neighboring Wollega Province which shows similar stress.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert "Wollega" not in repaired_report["priority_area_justification"][0]["differentiator"]
    assert any("Auto-repaired Harari::drought" in note and "Wollega" in note for note in repaired_report["_metadata"]["auto_repaired"])


def test_validate_against_evidence_auto_repairs_fabricated_score():
    report = _report([
        {
            "justification_id": "Harari::drought",
            "area": "Harari",
            "priority_score": 0.599,
            "risk_score": 23.6,
            "differentiator": "This area has a priority score of 0.999, the highest ever recorded.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert "0.999" not in repaired_report["priority_area_justification"][0]["differentiator"]
    assert any("Auto-repaired Harari::drought" in note and "0.999" in note for note in repaired_report["_metadata"]["auto_repaired"])


def test_validate_against_evidence_auto_repairs_only_the_offending_area():
    # Two real areas -- only Harari's differentiator violates a rule.
    # Afar's real LLM narrative must be left completely untouched.
    report = _report([
        {
            "justification_id": "Harari::drought",
            "area": "Harari",
            "priority_score": 0.599,
            "risk_score": 23.6,
            "differentiator": "This area cites a priority score of 0.999.",
            "recommended_intervention_type": "Drought / water-security response",
        },
        {
            "justification_id": "Afar::wet",
            "area": "Afar",
            "priority_score": 0.42,
            "risk_score": 12.1,
            "differentiator": "Afar shows the highest wet-hazard exposure among ranked areas this period.",
            "recommended_intervention_type": "Flood / wet-hazard mitigation response",
        },
    ])

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    by_id = {item["justification_id"]: item for item in repaired_report["priority_area_justification"]}
    assert "0.999" not in by_id["Harari::drought"]["differentiator"]
    assert by_id["Afar::wet"]["differentiator"] == "Afar shows the highest wet-hazard exposure among ranked areas this period."
    assert len(repaired_report["_metadata"]["auto_repaired"]) == 1


def test_validate_against_evidence_auto_repairs_priority_score_citation():
    report = _report([
        {
            "justification_id": "Harari::drought",
            "area": "Harari",
            "priority_score": 0.599,
            "risk_score": 23.6,
            "differentiator": "Harari holds the highest priority score nationally.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert "priority score" not in repaired_report["priority_area_justification"][0]["differentiator"].lower()
    assert any("Auto-repaired Harari::drought" in note for note in repaired_report["_metadata"]["auto_repaired"])


def test_validate_against_evidence_auto_repairs_confirmed_observed_language():
    # Confirmed real gap, fixed: this used to just sit in validation_flags
    # while the confirmed/observed phrasing reached the displayed report
    # unchanged. It's now deterministically rewritten to its forecast-safe
    # equivalent (see _CONFIRMED_LANGUAGE_REPLACEMENTS) -- violations is
    # clean (the DISPLAYED text is what's being validated), and the repair
    # is recorded separately in auto_repaired for transparency.
    report = _report([], executive_summary="The drought has already occurred across the southern lowlands.")

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["executive_summary"] == "The drought is forecast to occur across the southern lowlands."
    assert any("confirmed/observed" in note for note in repaired_report["_metadata"]["auto_repaired"])


def test_validate_against_evidence_auto_repairs_confirmed_language_in_advisory_bullets_and_sms():
    # Confirmed the repair walker covers the OTHER real TEXT_FIELDS shapes,
    # not just a bare top-level string like executive_summary: farmer_
    # advisory is a dict-of-lists-of-objects (timescale -> bullets), and
    # sms_messages is a flat list of objects -- both have their own
    # narrative key ("action"/"message") that must be rewritten in place.
    report = _report(
        [],
        farmer_advisory={
            "immediate": [{
                "area": ["Harari"], "action": "The drought has already occurred; conserve water now.",
                "trigger": "strong_drought", "evidence": ["spi"], "cross_indicator_confidence": "high",
            }],
            "near_term": [], "preparedness": [],
        },
        sms_messages=[{
            "area": "Harari", "audience": "general", "hazard": "drought", "valid_period": "July 2026",
            "cross_indicator_confidence": "high", "message": "Flooding has occurred in Harari -- seek higher ground.",
        }],
    )

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["farmer_advisory"]["immediate"][0]["action"] == "The drought is forecast to occur; conserve water now."
    assert repaired_report["sms_messages"][0]["message"] == "Flooding is forecast to occur in Harari -- seek higher ground."
    assert len(repaired_report["_metadata"]["auto_repaired"]) == 2


def test_validate_against_evidence_auto_repairs_plural_confirmed_observed_language():
    # Confirmed real gap, caught via live testing against real evidence:
    # the original pattern only matched singular auxiliary verbs ("is
    # confirmed", "was observed") -- a real plural subject ("local water
    # sources were observed to run dry") slipped through untouched.
    report = _report(
        [],
        executive_summary="Local water sources were observed to run dry, and impacts are confirmed nationwide.",
    )

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["executive_summary"] == "Local water sources are projected to run dry, and impacts are indicated by the forecast nationwide."


def test_validate_against_evidence_does_not_repair_conditional_future_confirmation():
    # Confirmed real false positive, caught while building this repair:
    # "delay planting until reliable seasonal onset is confirmed" is an
    # instruction to wait for a FUTURE, LOCAL confirmation -- not a claim
    # that confirmation has already happened. Rewriting it would silently
    # change legitimate advice's meaning. Must be left completely untouched.
    text = "Delay planting until reliable seasonal onset is confirmed, given elevated CDD anomalies."
    report = _report([], executive_summary=text)

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["executive_summary"] == text
    assert repaired_report["_metadata"]["auto_repaired"] == []


def test_validate_against_evidence_national_signal_overstatement_stays_flag_only_not_repaired():
    # Confirmed scoping decision (see repair_item_scoped_violations'
    # docstring): national-signal overstatement is a whole-sentence framing
    # problem, not a fixed-phrase substitution -- no safe deterministic
    # rewrite exists for it, so it must remain detect-and-flag only. Reuses
    # EVIDENCE_WITH_PARTIAL_NATIONAL_SIGNAL (defined below, module-level --
    # resolved at call time, not definition order).
    report = _report(
        [],
        compound_hazard_interpretation=["A strong national signal toward drought conditions is evident."],
    )

    repaired_report, violations = validate_against_evidence(report, EVIDENCE_WITH_PARTIAL_NATIONAL_SIGNAL)

    assert any("partial_drought" in v for v in violations)
    assert repaired_report["_metadata"]["auto_repaired"] == []


def test_validate_against_evidence_is_additive_not_overwriting():
    report = _report([], executive_summary="Normal conditions expected.")
    report["_metadata"] = {
        "validation_flags": ["a pre-existing flag from another validator"],
        "auto_repaired": ["a pre-existing repair note from another validator"],
    }

    validate_against_evidence(report, REAL_EVIDENCE)

    assert "a pre-existing flag from another validator" in report["_metadata"]["validation_flags"]
    assert "a pre-existing repair note from another validator" in report["_metadata"]["auto_repaired"]


# Confirmed real gap, caught via live testing: a real Gemini Stage 2 output
# wrote "a strong national signal toward drought conditions" while the real
# National cross_indicator_findings entry was only "partial_drought" (0.6)
# -- the narrative conflated "several areas are individually strong" with
# "the national aggregate is strong". These 4 tests cover the new check.
EVIDENCE_WITH_PARTIAL_NATIONAL_SIGNAL = {
    **REAL_EVIDENCE,
    "cross_indicator_findings": [
        {"area": "National", "signal": "partial_drought", "agreement_score": 0.6},
        {"area": "Harari", "signal": "strong_drought", "agreement_score": 1.0},
    ],
}

EVIDENCE_WITH_STRONG_NATIONAL_SIGNAL = {
    **REAL_EVIDENCE,
    "cross_indicator_findings": [
        {"area": "National", "signal": "strong_drought", "agreement_score": 0.9},
    ],
}


def test_validate_against_evidence_flags_national_signal_overstated_as_strong():
    report = _report(
        [],
        compound_hazard_interpretation=[
            "Cross-indicator agreement analysis demonstrates a strong national signal toward drought conditions, "
            "with seven administrative areas achieving maximum agreement.",
        ],
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_PARTIAL_NATIONAL_SIGNAL)

    assert any("partial_drought" in v for v in violations)


def test_validate_against_evidence_does_not_flag_when_national_signal_really_is_strong():
    report = _report(
        [],
        compound_hazard_interpretation=["A strong national signal toward drought conditions is evident."],
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_STRONG_NATIONAL_SIGNAL)

    assert violations == []


def test_validate_against_evidence_does_not_flag_area_level_strong_language_without_national_claim():
    # "strong" and "drought" both appear, describing AREAS, not a national
    # aggregate claim -- "national" never appears in the same sentence, so
    # this must not be flagged.
    report = _report(
        [],
        compound_hazard_interpretation=[
            "Seven administrative areas show strong drought agreement, including Harari and Afar.",
        ],
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_PARTIAL_NATIONAL_SIGNAL)

    assert violations == []


def test_validate_against_evidence_skips_national_signal_check_when_no_national_entry():
    evidence_without_national = {**REAL_EVIDENCE, "cross_indicator_findings": [{"area": "Harari", "signal": "strong_drought"}]}
    report = _report(
        [],
        compound_hazard_interpretation=["A strong national signal toward drought conditions is evident."],
    )

    _, violations = validate_against_evidence(report, evidence_without_national)

    assert violations == []


# Confirmed real gap, caught via live testing: a real captured Stage 2
# response wrote "15 individual administrative zones independently display a
# strong drought signal (including Afar, Dire Dawa, ...)" naming only 8 of
# its own claimed 15, while the real cross_indicator_findings for that run
# held exactly 6 real strong_drought areas -- Gemini counted the per-area
# rows itself instead of using the real, deterministic tally. These tests
# cover the new backstop check (area_signal_counts is the primary fix, in
# report_stages.build_stage2_prompt).
EVIDENCE_WITH_SIX_STRONG_DROUGHT_AREAS = {
    **REAL_EVIDENCE,
    "cross_indicator_findings": [
        {"area": "National", "signal": "partial_drought", "agreement_score": 0.6},
        {"area": "Afar", "signal": "strong_drought", "agreement_score": 1.0},
        {"area": "Dire Dawa", "signal": "strong_drought", "agreement_score": 0.9},
        {"area": "Gambela", "signal": "strong_drought", "agreement_score": 0.85},
        {"area": "Harari", "signal": "strong_drought", "agreement_score": 0.8},
        {"area": "Oromia", "signal": "strong_drought", "agreement_score": 0.8},
        {"area": "Tigray", "signal": "strong_drought", "agreement_score": 0.8},
        {"area": "Amhara", "signal": "partial_drought", "agreement_score": 0.5},
    ],
}


def test_validate_against_evidence_flags_wrong_area_signal_count():
    report = _report(
        [],
        compound_hazard_interpretation=[
            "Regionally, 15 individual administrative zones independently display a strong drought signal.",
        ],
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_SIX_STRONG_DROUGHT_AREAS)

    assert any("6" in v and "strong_drought" in v for v in violations)


def test_validate_against_evidence_does_not_flag_correct_area_signal_count():
    report = _report(
        [],
        compound_hazard_interpretation=[
            "Regionally, 6 individual administrative zones independently display a strong drought signal.",
        ],
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_SIX_STRONG_DROUGHT_AREAS)

    assert violations == []


def test_validate_against_evidence_area_signal_count_stays_flag_only_not_repaired():
    # Same scoping decision as national-signal overstatement: fixing the
    # number alone would still leave a wrong/incomplete named area list
    # attached to it, so this is detect-and-flag only, never rewritten.
    text = "Regionally, 15 individual administrative zones independently display a strong drought signal."
    report = _report([], compound_hazard_interpretation=[text])

    repaired_report, violations = validate_against_evidence(report, EVIDENCE_WITH_SIX_STRONG_DROUGHT_AREAS)

    assert violations != []
    assert repaired_report["compound_hazard_interpretation"] == [text]
    assert repaired_report["_metadata"]["auto_repaired"] == []


# Confirmed real gap, caught via live testing: a real captured Stage 2
# response wrote "Climatologically, total rainfall averages 101.429 mm
# against a baseline of 129.697 mm" -- 101.429 was the real FORECAST mean
# (this period's value), not the real climatology baseline (129.697); the
# real underlying evidence was correct, only the prose swapped which value
# the word "climatology" points at. Real numbers reused directly from the
# same fixture as test_build_structured_indicator_summaries_exposes_
# explicit_anomaly_fields in tests/test_statistical_evidence.py.
EVIDENCE_WITH_RAINFALL_DEPARTURE = {
    **REAL_EVIDENCE,
    "climate_indicators": {
        "rainfall_total": {
            "national": {"mean": 101.429},
            "regional": [{"area_name": "Somali", "mean": 80.0}],
            "class_area_pct": {"very_low": 20.0, "low": 20.0, "moderate": 20.0, "high": 20.0, "very_high": 20.0},
            "class_scheme": "quintiles_of_real_climatology",
            "class_breakpoints": [50.0, 80.0, 110.0, 140.0],
            "departure": {
                "national_anomaly": {"mean": -28.268},
                "national_climatology_mean": 129.697,
                "national_pct_anomaly": {"mean": -53.74, "median": -50.0},
            },
        },
    },
}


def test_validate_against_evidence_flags_forecast_labeled_as_climatology():
    report = _report(
        [],
        executive_summary="Climatologically, total rainfall averages 101.429 mm against a baseline of 129.697 mm.",
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_RAINFALL_DEPARTURE)

    assert any("101.4" in v for v in violations)


def test_validate_against_evidence_does_not_flag_correct_forecast_climatology_roles():
    report = _report(
        [],
        executive_summary=(
            "Forecast rainfall averages 101.429 mm, compared with a climatological baseline of 129.697 mm, "
            "a departure of -28.268 mm (-53.74%)."
        ),
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_RAINFALL_DEPARTURE)

    assert violations == []


def test_validate_against_evidence_skips_climatology_role_check_without_departure_data():
    report = _report(
        [],
        executive_summary="Climatologically, total rainfall averages 101.429 mm against a baseline of 129.697 mm.",
    )

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


# Confirmed real gap, caught via live testing: a real captured Stage 2
# response wrote "wet probability registers a high national signal ... of
# 0.099" -- wet probability's real classification_method is quintiles_of_
# current_period (RELATIVE -- highest quintile THIS period, see
# CLASSIFICATION_METHOD_LEGEND in report_stages.py), and 0.099 is only ~10%
# in absolute terms, so a bare "high" misleadingly reads as an absolute
# severity claim.
EVIDENCE_WITH_QUINTILE_WET_PROBABILITY = {
    **REAL_EVIDENCE,
    "hazard_risk_layers": {
        "wet_probability": {
            "layer_label": "Wet Probability",
            "national": {"mean": 0.099},
            "regional": [{"area_name": "Somali", "mean": 0.2}],
            "class_area_pct": {"very_low": 10.0, "low": 10.0, "moderate": 12.0, "high": 58.3, "very_high": 9.7},
            "class_scheme": "quintiles_of_current_period (no separate climatology exists for this layer)",
            "class_breakpoints": [0.05, 0.08, 0.1, 0.15],
        },
    },
    "categorical_layers": {},
}


def test_validate_against_evidence_flags_unqualified_relative_high_signal():
    report = _report(
        [],
        executive_summary="Wet probability registers a high national signal with a mean of 0.099.",
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_QUINTILE_WET_PROBABILITY)

    assert any("wet_probability" in v for v in violations)


def test_validate_against_evidence_does_not_flag_qualified_relative_high_signal():
    report = _report(
        [],
        executive_summary=(
            "Wet probability falls within the relatively high class compared with other locations this period, "
            "although the national mean probability itself is only about 10%."
        ),
    )

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_QUINTILE_WET_PROBABILITY)

    assert violations == []


def test_validate_against_evidence_does_not_flag_sentence_initial_words_or_compound_prefixes():
    # Regression test for a real false-positive confirmed via live testing:
    # free-form LLM differentiator prose naturally starts sentences with
    # capitalized words ("Distinguished by...") and uses hyphenated
    # compounds ("Multi-hazard...") that a bare capitalized-word regex
    # incorrectly flagged as invented place names.
    report = _report([
        {
            "justification_id": "Harari::drought",
            "area": "Harari",
            "priority_score": 0.599,
            "risk_score": 23.6,
            "differentiator": "Distinguished by the highest hazard probability. Multi-hazard exposure compounds the risk. Enters a high-confidence drought regime.",
            "recommended_intervention_type": "Multi-hazard agricultural and flood advisory",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_validate_against_evidence_does_not_flag_real_season_names_or_cross_item_boundaries():
    # Regression test for two real false positives confirmed via live
    # testing: "Kiremt" (Ethiopia's real main rainy season name, not a
    # place) and "Ranks" (a false positive caused by joining one area's
    # recommended_intervention_type -- no trailing period -- directly
    # against the next area's differentiator, hiding the sentence
    # boundary from the sentence-start heuristic).
    report = _report([
        {
            "justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "risk_score": 23.6,
            "differentiator": "Holds the highest hazard probability during the Kiremt season.",
            "recommended_intervention_type": "Drought / water-security response",
        },
        {
            "justification_id": "Afar::wet", "area": "Afar", "priority_score": 0.42, "risk_score": 12.1,
            "differentiator": "Ranks second for wet risk with strong cross-indicator alignment.",
            "recommended_intervention_type": "Flood / wet-hazard mitigation response",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_validate_against_evidence_flags_priority_score_citation():
    # priority_score is an internal ranking composite with no standalone
    # meaning to a reader (unlike risk_score, which has a real class) --
    # build_stage2_prompt's differentiator rules explicitly forbid citing
    # it, but a free-tier model doesn't always comply (confirmed live).
    # This is now auto-repaired (see test_validate_against_evidence_auto_
    # repairs_priority_score_citation) rather than only flagged -- the
    # auto_repaired audit note is where the original reason now surfaces.
    report = _report([
        {
            "justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "risk_score": 23.6,
            "differentiator": "Harari holds the highest drought priority score (0.600) nationally.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert any("priority_score" in note for note in repaired_report["_metadata"]["auto_repaired"])


def test_validate_against_evidence_does_not_flag_real_risk_classes_or_indicator_vocabulary():
    # Regression test for 2 real false positives confirmed via live
    # dashboard use: Stage 2 is explicitly instructed (see
    # _risk_definition_block in app.api.report_stages) to classify
    # risk_score using the real "Very low/Low/Moderate/High/Very high"
    # classes, and Stage 1/2 both legitimately discuss the real Rx1day/
    # Rx5day climate indicators ("Rx" surfaces standalone since the digit
    # in "Rx1day" breaks the phrase regex's own word boundary). Neither is
    # an invented place name.
    report = _report([
        {
            "justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "risk_score": 23.6,
            "differentiator": (
                "Classified as Very High, up from Low last period, corroborated by the Rx anomaly "
                "and a Moderate hazard probability."
            ),
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_all_text_extracts_narrative_from_priority_area_justification_objects_not_dict_repr():
    report = _report([
        {"justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "differentiator": "unique differentiator text"},
    ])

    text = _all_text(report)

    assert "unique differentiator text" in text
    assert "justification_id" not in text  # not a raw dict repr


def test_all_text_flattens_timescale_and_category_structured_advisory_fields():
    # Step 7 items 6/7 -- farmer_advisory/agro_pastoral_advisory/
    # humanitarian_priorities are now timescale/category objects, not flat
    # arrays. A dict value was previously silently skipped by _all_text
    # (neither list nor str), meaning these fields would never be scanned
    # for hallucinated content at all.
    report = _report(
        [],
        farmer_advisory={"immediate": ["conserve water now"], "near_term": [], "preparedness": ["prepare for dry spell"]},
        humanitarian_priorities={"monitoring": [], "preparedness": [], "pre_positioning": ["pre-position supplies"], "immediate_action": []},
    )

    text = _all_text(report)

    assert "conserve water now" in text
    assert "prepare for dry spell" in text
    assert "pre-position supplies" in text


def test_all_text_extracts_action_from_structured_advisory_items_and_message_from_sms():
    # Real current shape (see _ADVISORY_ITEM_SCHEMA/_SMS_ITEM_SCHEMA in
    # app.api.ai_map_interpretation): each timescale/category bullet is now
    # a real structured object {area, action, trigger, evidence,
    # confidence}, not a bare string, and sms_messages is a top-level array
    # of {area, audience, hazard, valid_period, confidence, message}
    # objects, not a single sms_summary string. Confirmed real gap this
    # closes: before "action"/"message" were added to _item_narrative_
    # text's narrative_keys, this content was silently unscanned entirely.
    report = _report(
        [],
        farmer_advisory={
            "immediate": [{"area": ["Harari"], "action": "conserve water now", "trigger": "strong_drought", "evidence": ["spi"], "cross_indicator_confidence": "high"}],
            "near_term": [], "preparedness": [],
        },
        sms_messages=[
            {"area": "Harari", "audience": "general", "hazard": "drought", "valid_period": "July 2026", "cross_indicator_confidence": "high", "message": "early warning for Harari"},
        ],
    )

    text = _all_text(report)

    assert "conserve water now" in text
    assert "early warning for Harari" in text


def test_all_text_extracts_interpretation_from_structured_layer_and_indicator_summaries():
    # Phase 3 #17 -- layer_by_layer_summary/indicator_by_indicator_summary
    # items are now real structured objects (layer/indicator, national_
    # signal, national_mean, highest_areas, lowest_areas, high_or_very_high_area_pct,
    # interpretation, confidence), not flat strings. Before this fix,
    # _item_narrative_text's dict branch only recognized differentiator/
    # recommended_intervention_type, so interpretation (the ONLY LLM-
    # authored narrative field on these objects) would be silently dropped
    # from every scan -- confirmed_language detection included.
    report = _report(
        [],
        layer_by_layer_summary=[
            {"layer": "h_dry_mean", "national_signal": "high", "national_mean": 0.48, "highest_areas": ["Harari"], "lowest_areas": [], "high_or_very_high_area_pct": 34.0, "interpretation": "unique layer interpretation text", "confidence": "moderate"},
        ],
        indicator_by_indicator_summary=[
            {"indicator": "spi", "national_signal": "severely_dry", "national_mean": -1.6, "highest_areas": [], "lowest_areas": ["Somali"], "high_or_very_high_area_pct": None, "interpretation": "unique indicator interpretation text", "confidence": "moderate"},
        ],
    )

    text = _all_text(report)

    assert "unique layer interpretation text" in text
    assert "unique indicator interpretation text" in text
    assert "national_signal" not in text  # not a raw dict repr


# Confirmed real gap, caught via live testing: a real captured Stage 3
# advisory bullet wrote "protect the 30.72% exposed cropland from ONGOING
# rainfall deficits" -- this report always describes a Month-2 seasonal
# FORECAST, so an already-manifesting present-tense claim is the same class
# of error as CONFIRMED_LANGUAGE_PATTERN's past-tense claims, just phrased
# differently.
def test_validate_against_evidence_auto_repairs_ongoing_language():
    report = _report([], executive_summary="Farmers should protect cropland from ongoing rainfall deficits this season.")

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["executive_summary"] == "Farmers should protect cropland from forecast rainfall deficits this season."
    assert any("observational-present" in note for note in repaired_report["_metadata"]["auto_repaired"])


def test_validate_against_evidence_auto_repairs_currently_experiencing_and_presently_affected_by():
    report = _report(
        [],
        executive_summary=(
            "Areas currently experiencing drought should prioritize water storage, and villages presently "
            "affected by flooding should relocate livestock."
        ),
    )

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["executive_summary"] == (
        "Areas forecast to experience drought should prioritize water storage, and villages forecast to be "
        "affected by flooding should relocate livestock."
    )


def test_validate_against_evidence_does_not_repair_bare_ongoing_with_no_hazard_noun():
    # "ongoing" alone is legitimate in plenty of contexts this report
    # actually uses (monitoring, preparedness activities) -- must not fire
    # on the word alone, only when immediately followed by a real hazard
    # noun this pattern recognizes.
    text = "Continue ongoing monitoring and preparedness activities in the meantime."
    report = _report([], executive_summary=text)

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
    assert repaired_report["executive_summary"] == text
    assert repaired_report["_metadata"]["auto_repaired"] == []


# Confirmed real gap, caught via live testing: a real captured Stage 2
# executive_summary wrote "drought vulnerability is classified as very high
# nationally ... driven by severe rainfall deficits" -- vulnerability
# (v_drought/v_wet) is a real, independently-sourced baseline food-security/
# livelihood layer (FEWS NET IPC phase data, confirmed by reading
# app.data_pipeline.vulnerability_data_pipeline directly), not something
# forecast rainfall/SPI/hazard probability causes.
def test_validate_against_evidence_flags_vulnerability_attributed_to_rainfall():
    report = _report(
        [],
        executive_summary="Drought vulnerability is classified as very high nationally, driven by severe rainfall deficits.",
    )

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert any("vulnerability" in v.lower() and "climate/hazard driver" in v for v in violations)


def test_validate_against_evidence_does_not_flag_correctly_separated_vulnerability_and_hazard():
    report = _report(
        [],
        executive_summary=(
            "Drought vulnerability is very high nationally, reflecting baseline food-security sensitivity, "
            "coinciding with a separate forecast rainfall deficit."
        ),
    )

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_validate_against_evidence_does_not_flag_vulnerability_listed_as_ranking_co_factor():
    # Confirmed real false positive, caught while live-testing this check
    # against a real fresh Gemini run: "driven by" here governs the RANKING
    # (hazard_probability and vulnerability listed together as co-factors
    # of risk, matching the real risk formula), not a claim that
    # vulnerability itself was caused by hazard_probability -- vulnerability
    # is never the grammatical subject of a causal clause in this sentence.
    report = _report([{
        "justification_id": "Harari::drought", "area": "Harari",
        "priority_score": 0.599, "risk_score": 23.6,
        "differentiator": (
            "Harari ranks first for drought with a risk score falling in the Low class, driven by a very "
            "high hazard probability combined with moderate pre-existing vulnerability."
        ),
        "recommended_intervention_type": "Drought preparedness monitoring",
    }])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_validate_against_evidence_vulnerability_causality_stays_flag_only_not_repaired():
    text = "Drought vulnerability is classified as very high nationally, driven by severe rainfall deficits."
    report = _report([], executive_summary=text)

    repaired_report, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations != []
    assert repaired_report["executive_summary"] == text
    assert repaired_report["_metadata"]["auto_repaired"] == []


# Confirmed real gap, caught via live testing: a real captured Stage 2
# differentiator claimed a top-ranked area was "driven by the highest
# hazard probability among drought areas" -- a DIFFERENT real area in the
# same real batch actually had a higher value. highest_among_group/
# lowest_among_group (see app.context.statistical_evidence._superlative_
# flags) are the real, deterministic ground truth this check validates
# against.
EVIDENCE_WITH_SUPERLATIVE_GROUND_TRUTH = {
    **REAL_EVIDENCE,
    "priority_area_justifications": [
        {
            "justification_id": "Harari::drought", "area": "Harari", "hazard_type": "drought", "rank": 1,
            "priority_score": 0.599, "risk_score": 23.6, "risk_class": "Low", "action_status": "preparedness",
            "hazard_probability": 0.787, "highest_among_group": ["population_exposed_pct"], "lowest_among_group": [],
        },
        {
            "justification_id": "South Ethiopia::drought", "area": "South Ethiopia", "hazard_type": "drought", "rank": 2,
            "priority_score": 0.5, "risk_score": 20.0, "risk_class": "Low", "action_status": "monitor_only",
            "hazard_probability": 0.837, "highest_among_group": ["hazard_probability"], "lowest_among_group": [],
        },
    ],
}


def test_validate_against_evidence_flags_unsupported_superlative_claim():
    report = _report([
        {
            "justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "risk_score": 23.6,
            "differentiator": "Ranks first for drought, driven by the highest hazard probability among drought areas.",
            "recommended_intervention_type": "Drought preparedness monitoring",
        },
    ])

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_SUPERLATIVE_GROUND_TRUTH)

    assert any("Harari::drought" in v and "hazard_probability" in v for v in violations)


def test_validate_against_evidence_does_not_flag_supported_superlative_claim():
    report = _report([
        {
            "justification_id": "South Ethiopia::drought", "area": "South Ethiopia", "priority_score": 0.5, "risk_score": 20.0,
            "differentiator": "Ranks second for drought, driven by the highest hazard probability among drought areas.",
            "recommended_intervention_type": "Monitoring only -- not currently actionable this period",
        },
    ])

    _, violations = validate_against_evidence(report, EVIDENCE_WITH_SUPERLATIVE_GROUND_TRUTH)

    assert violations == []


def test_validate_against_evidence_does_not_flag_superlative_when_ground_truth_absent():
    # Older evidence shape that never computed highest_among_group/
    # lowest_among_group -- "no real ground truth to check against" must
    # not be treated as "everything is unsupported" (REAL_EVIDENCE's
    # fixture entries have no highest_among_group key at all).
    report = _report([
        {
            "justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "risk_score": 23.6,
            "differentiator": "Ranks first for drought, driven by the highest hazard probability among drought areas.",
            "recommended_intervention_type": "Drought preparedness monitoring",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []
