from app.advisory.response_validator import _all_text, validate_against_evidence

REAL_EVIDENCE = {
    "priority_area_justifications": [
        {"justification_id": "Harari::drought", "area": "Harari", "hazard_type": "drought", "priority_score": 0.599, "risk_score": 23.6},
        {"justification_id": "Afar::wet", "area": "Afar", "hazard_type": "wet", "priority_score": 0.42, "risk_score": 12.1},
    ],
}


def _report(priority_area_justification, **extra_fields):
    report = {
        "priority_area_justification": priority_area_justification,
        "executive_summary": "",
        "national_spatial_overview": [],
        "farmer_advisory": [],
        "humanitarian_priorities": [],
        "sms_summary": "",
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
            "differentiator": "Harari has the highest priority score of 0.599 and risk score of 23.6 nationally.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert violations == []


def test_validate_against_evidence_flags_invented_area_name():
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

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert any("Wollega" in v for v in violations)


def test_validate_against_evidence_flags_fabricated_score():
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

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert any("0.999" in v for v in violations)


def test_validate_against_evidence_flags_confirmed_observed_language_unconditionally():
    report = _report([], executive_summary="The drought has already occurred across the southern lowlands.")

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert any("confirmed/observed" in v for v in violations)


def test_validate_against_evidence_is_additive_not_overwriting():
    report = _report([], executive_summary="Normal conditions expected.")
    report["_metadata"] = {"validation_flags": ["a pre-existing flag from another validator"]}

    validate_against_evidence(report, REAL_EVIDENCE)

    assert "a pre-existing flag from another validator" in report["_metadata"]["validation_flags"]


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
            "differentiator": "Distinguished by the highest priority score. Multi-hazard exposure compounds the risk. Enters a high-confidence drought regime.",
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
            "differentiator": "Holds the highest priority score during the Kiremt season.",
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
