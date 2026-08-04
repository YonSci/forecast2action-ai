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
            "differentiator": "Harari has the highest hazard probability and risk score of 23.6 nationally.",
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
    report = _report([
        {
            "justification_id": "Harari::drought", "area": "Harari", "priority_score": 0.599, "risk_score": 23.6,
            "differentiator": "Harari holds the highest drought priority score (0.600) nationally.",
            "recommended_intervention_type": "Drought / water-security response",
        },
    ])

    _, violations = validate_against_evidence(report, REAL_EVIDENCE)

    assert any("priority_score" in v for v in violations)


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


def test_all_text_extracts_interpretation_from_structured_layer_and_indicator_summaries():
    # Phase 3 #17 -- layer_by_layer_summary/indicator_by_indicator_summary
    # items are now real structured objects (layer/indicator, national_
    # signal, national_mean, highest_areas, lowest_areas, affected_area_pct,
    # interpretation, confidence), not flat strings. Before this fix,
    # _item_narrative_text's dict branch only recognized differentiator/
    # recommended_intervention_type, so interpretation (the ONLY LLM-
    # authored narrative field on these objects) would be silently dropped
    # from every scan -- confirmed_language detection included.
    report = _report(
        [],
        layer_by_layer_summary=[
            {"layer": "h_dry_mean", "national_signal": "high", "national_mean": 0.48, "highest_areas": ["Harari"], "lowest_areas": [], "affected_area_pct": 34.0, "interpretation": "unique layer interpretation text", "confidence": "moderate"},
        ],
        indicator_by_indicator_summary=[
            {"indicator": "spi", "national_signal": "severely_dry", "national_mean": -1.6, "highest_areas": [], "lowest_areas": ["Somali"], "affected_area_pct": None, "interpretation": "unique indicator interpretation text", "confidence": "moderate"},
        ],
    )

    text = _all_text(report)

    assert "unique layer interpretation text" in text
    assert "unique indicator interpretation text" in text
    assert "national_signal" not in text  # not a raw dict repr
