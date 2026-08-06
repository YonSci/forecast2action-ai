from app.api import report_stages
from app.api.ai_map_interpretation import (
    STAGE1_SCHEMA,
    STAGE2_SCHEMA,
    STAGE3_SCHEMA,
    AIMapInterpretationRequest,
)


def _request():
    return AIMapInterpretationRequest()


def test_context_header_excludes_ui_state_and_states_national_scope():
    request = AIMapInterpretationRequest(
        forecast_selection={"forecastScale": "seasonal", "lead": "month_2", "layer": "risk_score"},
        map_context={"active_map_group": "Hazard/Risk Layers", "displayed_map": "Drought Risk", "admin_scope": "South Ethiopia"},
    )
    header = report_stages._context_header(request)

    assert "Report scope: National" in header
    assert "Admin scope" not in header
    assert "Active map group" not in header
    assert "Displayed map" not in header
    assert "Active map layer" not in header
    assert "Active climate indicator" not in header
    # South Ethiopia (a dashboard admin_scope value) must never leak into the
    # prompt as if the report were scoped to it -- every staged report is
    # national, see REPORT_SCOPE_LABEL's docstring.
    assert "South Ethiopia" not in header


def test_round_floats_rounds_nested_structures_without_mutating_input():
    original = {"a": 1.123456789, "b": [{"c": 2.987654321}], "d": "text", "e": 3}
    rounded = report_stages._round_floats(original, ndigits=2)

    assert rounded == {"a": 1.12, "b": [{"c": 2.99}], "d": "text", "e": 3}
    assert original["a"] == 1.123456789  # input untouched


def test_national_population_exposure_summary_sums_real_regional_counts():
    evidence = {
        "exposure": {
            "population_r_drought": {
                "population_exposed_by_region": [
                    {"area_name": "Afar", "total": 1000.0, "exposed": 400.0},
                    {"area_name": "Somali", "total": 2000.0, "exposed": 600.0},
                ],
            },
            "population_r_wet": {"population_exposed_by_region": []},
        },
    }
    summary = report_stages._national_population_exposure_summary(evidence)

    assert summary["drought"]["total_population"] == 3000
    assert summary["drought"]["exposed_population"] == 1000
    assert summary["drought"]["exposed_population_pct"] == round(1000 / 3000 * 100, 1)
    assert summary["wet"]["total_population"] == 0
    assert summary["wet"]["exposed_population_pct"] is None


def test_compact_community_reports_collapses_empty_and_keeps_real_data():
    assert report_stages._compact_community_reports(report_stages._NO_COMMUNITY_REPORTS) == {"available": False}
    assert report_stages._compact_community_reports(None) == {"available": False}

    real = {"total_reports": 3, "feedback_signal": "emerging_ground_signal", "by_severity": {"high": 3}, "by_type": {"water_shortage": 3}}
    compacted = report_stages._compact_community_reports(real)
    assert compacted["available"] is True
    assert compacted["reports"] == 3
    assert compacted["feedback_signal"] == "emerging_ground_signal"


def test_build_stage1_prompt_uses_curated_images_and_excludes_priority_scores(monkeypatch):
    curated = [{"map_id": "risk_july_population_r_drought", "label": "Drought Risk", "data_url": "data:image/png;base64,x"}]
    captured_args = {}

    def fake_select(request, evidence, period):
        captured_args["evidence"] = evidence
        captured_args["period"] = period
        return curated

    monkeypatch.setattr(report_stages, "select_curated_stage1_images", fake_select)

    evidence = {"climate_indicators": {"spi": {}}, "priority_scores": {"population_r_drought": []}}
    system_prompt, user_prompt, stage_images = report_stages.build_stage1_prompt(_request(), evidence)

    assert stage_images == curated
    assert captured_args["evidence"] is evidence
    assert "Stage 1" in user_prompt
    assert "priority_scores" not in user_prompt
    assert "climate_indicators" in user_prompt
    assert "real_layer_summaries" in user_prompt


def test_wet_signal_is_significant_only_for_strong_wet_or_mixed_national_signal():
    assert report_stages._wet_signal_is_significant(
        {"cross_indicator_findings": [{"area": "National", "signal": "strong_wet"}]},
    ) is True
    assert report_stages._wet_signal_is_significant(
        {"cross_indicator_findings": [{"area": "National", "signal": "mixed"}]},
    ) is True
    # partial_wet is real, meaningful (>= CROSS_INDICATOR_MIXED_THRESHOLD)
    # agreement -- must count as significant too, or a real partial wet
    # signal would be silently excluded from the curated image set.
    assert report_stages._wet_signal_is_significant(
        {"cross_indicator_findings": [{"area": "National", "signal": "partial_wet"}]},
    ) is True
    assert report_stages._wet_signal_is_significant(
        {"cross_indicator_findings": [{"area": "National", "signal": "strong_drought"}]},
    ) is False
    assert report_stages._wet_signal_is_significant({"cross_indicator_findings": []}) is False


def test_select_curated_stage1_images_always_includes_drought_side_and_combined_layer(monkeypatch):
    def fake_hazard_record(layer_value, period):
        return {"id": f"hazard-{layer_value}-{period}"}

    def fake_seasonal_record(indicator, period, product):
        return {"id": f"seasonal-{indicator}-{product}-{period}"}

    monkeypatch.setattr(report_stages, "find_hazard_risk_record", fake_hazard_record)
    monkeypatch.setattr(report_stages, "find_seasonal_record", fake_seasonal_record)

    request = _request()
    request.map_images = [
        {"map_id": "hazard-population_r_drought-July", "label": "Drought Risk", "data_url": "x"},
        {"map_id": "hazard-p_drought-July", "label": "Drought Probability", "data_url": "x"},
        {"map_id": "hazard-h_dry_mean-July", "label": "Drought Hazard", "data_url": "x"},
        {"map_id": "seasonal-rainfall_total-anomaly-July", "label": "Rainfall Anomaly", "data_url": "x"},
        {"map_id": "seasonal-spi-forecast-July", "label": "SPI", "data_url": "x"},
        {"map_id": "seasonal-cdd-anomaly-July", "label": "CDD Anomaly", "data_url": "x"},
        {"map_id": "hazard-population_dominant_code-July", "label": "Dominant Hazard Code", "data_url": "x"},
        # Wet-side images exist in map_images too, but must be excluded
        # when the national signal isn't significantly wet.
        {"map_id": "hazard-population_r_wet-July", "label": "Wet Risk", "data_url": "x"},
    ]
    evidence = {"cross_indicator_findings": [{"area": "National", "signal": "strong_drought"}]}

    images = report_stages.select_curated_stage1_images(request, evidence, "July")
    labels = {image["label"] for image in images}

    assert labels == {"Drought Risk", "Drought Probability", "Drought Hazard", "Rainfall Anomaly", "SPI", "CDD Anomaly", "Dominant Hazard Code"}
    assert "Wet Risk" not in labels


def test_select_curated_stage1_images_adds_wet_side_when_signal_significant(monkeypatch):
    def fake_hazard_record(layer_value, period):
        return {"id": f"hazard-{layer_value}"}

    def fake_seasonal_record(indicator, period, product):
        return {"id": f"seasonal-{indicator}-{product}"}

    monkeypatch.setattr(report_stages, "find_hazard_risk_record", fake_hazard_record)
    monkeypatch.setattr(report_stages, "find_seasonal_record", fake_seasonal_record)

    request = _request()
    request.map_images = [
        {"map_id": "hazard-population_r_wet", "label": "Wet Risk", "data_url": "x"},
        {"map_id": "hazard-p_wet", "label": "Wet Probability", "data_url": "x"},
        {"map_id": "hazard-h_wet_mean", "label": "Wet Hazard", "data_url": "x"},
    ]
    evidence = {"cross_indicator_findings": [{"area": "National", "signal": "strong_wet"}]}

    images = report_stages.select_curated_stage1_images(request, evidence, "July")
    labels = {image["label"] for image in images}

    assert {"Wet Risk", "Wet Probability", "Wet Hazard"}.issubset(labels)


def test_select_curated_stage1_images_skips_missing_records_and_caps_total(monkeypatch):
    monkeypatch.setattr(report_stages, "find_hazard_risk_record", lambda layer_value, period: None)
    monkeypatch.setattr(report_stages, "find_seasonal_record", lambda indicator, period, product: None)

    request = _request()
    request.map_images = []

    images = report_stages.select_curated_stage1_images(request, {}, "July")

    assert images == []


def test_build_stage1_prompt_adds_population_exposure_summary_and_risk_definition_and_rounds_numbers(monkeypatch):
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    evidence = {
        "climate_indicators": {"spi": {"national": {"mean": 1.123456789}}},
        "exposure": {
            "population_r_drought": {
                "population_exposed_by_region": [{"area_name": "Afar", "total": 1000.0, "exposed": 250.0}],
            },
            "population_r_wet": {"population_exposed_by_region": []},
        },
    }
    _, user_prompt, _ = report_stages.build_stage1_prompt(_request(), evidence)

    assert "population_exposure_summary" in user_prompt
    assert "risk_definition" in user_prompt
    assert '"formula"' in user_prompt
    # SPI's raw 1.123456789 mean must not appear in full precision.
    assert "1.123456789" not in user_prompt
    assert "1.123" in user_prompt


def test_build_stage1_prompt_instructs_flagging_population_livestock_temporal_lag(monkeypatch):
    # Confirmed real gap, fixed: population is WorldPop 2020, livestock is
    # GLW4 2015, but a real forecast for e.g. 2026 could be 6/11 years
    # ahead -- "data completeness is robust" alone conflates real spatial
    # coverage with real temporal currency of these 2 static datasets.
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])
    _, user_prompt, _ = report_stages.build_stage1_prompt(_request(), {})

    assert "population_temporal_lag_years" in user_prompt
    assert "livestock_temporal_lag_years" in user_prompt


def test_build_stage1_prompt_excludes_raw_exposure_totals_phase4(monkeypatch):
    # Phase 4 -- evidence["exposure"]'s raw cropland/roads/healthsites
    # total/exposed sums are weighted sums of a unitless 0-1 normalized
    # index, NOT real hectares/road-segment/facility counts (only
    # exposed_pct is real and interpretable) -- unlike population_exposed_
    # by_region's total/exposed, which ARE real WorldPop people counts.
    # Stage 1 must never see the misleading raw sums; it already gets a
    # clean, correctly-labeled national aggregate via population_exposure_
    # summary, and per-area breakdowns are Stage 2's job.
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    evidence = {
        "exposure": {
            "population_r_drought": {
                "population_exposed_by_region": [{"area_name": "Afar", "total": 1000.0, "exposed": 250.0}],
                "cropland_exposed_by_region": [{"area_name": "Afar", "total": 987654.0, "exposed": 12345.0, "exposed_pct": 62.3}],
                "roads_exposed_by_region": [{"area_name": "Afar", "total": 55555.0, "exposed": 4444.0, "exposed_pct": 18.5}],
            },
            "population_r_wet": {"population_exposed_by_region": []},
        },
    }
    _, user_prompt, _ = report_stages.build_stage1_prompt(_request(), evidence)

    assert "cropland_exposed_by_region" not in user_prompt
    assert "987654" not in user_prompt
    assert "roads_exposed_by_region" not in user_prompt
    # population_exposure_summary (the safe, national, correctly-labeled
    # aggregate) is still present -- only the raw per-region exposure
    # section is excluded.
    assert "population_exposure_summary" in user_prompt


def test_build_stage1_prompt_survives_truncation_of_bulky_evidence(monkeypatch):
    # compact_json truncates at a fixed character count (see its own
    # implementation) -- if population_exposure_summary/risk_definition
    # were appended AFTER a large evidence dict instead of placed first,
    # truncation would silently drop them entirely before ever reaching
    # the model. This reproduces that exact scenario with an evidence dict
    # large enough to trigger real truncation.
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    bulky_regional_stats = [
        {"area_name": f"Region {i}", "min": 0.01, "max": 0.99, "mean": 0.5, "median": 0.5, "std": 0.1}
        for i in range(400)
    ]
    evidence = {
        "climate_indicators": {
            indicator: {"national": {"mean": 0.5}, "regional": bulky_regional_stats}
            for indicator in ["rainfall_total", "spi", "cdd", "cwd", "rx1day", "rx5day", "rainfall_percentile"]
        },
        "exposure": {
            "population_r_drought": {
                "population_exposed_by_region": [{"area_name": "Afar", "total": 1000.0, "exposed": 400.0}],
            },
            "population_r_wet": {"population_exposed_by_region": []},
        },
    }

    _, user_prompt, _ = report_stages.build_stage1_prompt(_request(), evidence)

    assert "...TRUNCATED..." in user_prompt  # confirms this test actually exercises truncation
    assert '"population_exposure_summary"' in user_prompt
    assert '"risk_definition"' in user_prompt
    assert '"formula"' in user_prompt


def test_build_stage2_prompt_includes_priority_area_justifications_and_cross_indicator_findings():
    evidence = {
        "priority_area_justifications": [
            {"justification_id": "Afar::drought", "area": "Afar", "priority_score": 0.9, "rank": 1},
        ],
        "cross_indicator_findings": [{"area": "Afar", "signal": "strong_drought"}],
    }
    stage1_result = {"layer_by_layer_summary": ["x"], "indicator_by_indicator_summary": ["y"], "data_quality_notes": []}
    community_evidence = {
        "Afar": {"total_reports": 3, "feedback_signal": "emerging_ground_signal", "by_severity": {"severe": 1}, "by_type": {"pasture_stress": 3}, "recent_reports": []},
    }

    system_prompt, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, stage1_result, community_evidence)

    assert "Stage 2" in user_prompt
    assert "strong_drought" in user_prompt
    assert "Afar::drought" in user_prompt
    assert "0.9" in user_prompt
    assert "justification_id" in user_prompt
    # Real community ground-truth evidence is embedded and attributed by area.
    assert "COMMUNITY GROUND-TRUTH" in user_prompt
    assert "emerging_ground_signal" in user_prompt
    assert "pasture_stress" in user_prompt


def test_build_stage2_prompt_differentiator_example_uses_placeholders_not_a_real_falsifiable_claim():
    # Regression test: the prompt's own contrastive GOOD example once
    # claimed, as a specific real fact, that "Harari... has the highest
    # hazard probability of any drought area" -- real evidence showed
    # South Ethiopia's hazard_probability (0.8369) was actually higher
    # than Harari's (0.7867) that same period. A wrong "real-looking"
    # example can actively teach the model to contradict its own evidence,
    # and any hardcoded real claim risks going stale as data changes
    # across periods regardless. The example must use abstract
    # placeholders instead of a specific, verifiable real area/fact.
    evidence = {"priority_area_justifications": [], "cross_indicator_findings": []}
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert "Harari" not in user_prompt
    assert "Area A" in user_prompt
    assert "abstract placeholders" in user_prompt


def test_build_stage2_prompt_compacts_zero_report_community_evidence():
    evidence = {"priority_area_justifications": [], "cross_indicator_findings": []}
    stage1_result = {}
    # A region with genuinely zero reports would never actually appear in
    # community_evidence (build_community_evidence_by_region omits it
    # entirely) -- but if one somehow did (e.g. total_reports=0), Stage 2's
    # prompt must still compact it, not spell out empty containers.
    community_evidence = {"Somali": {"total_reports": 0, "by_severity": {}, "by_type": {}, "feedback_signal": "no_ground_signal", "recent_reports": []}}

    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, stage1_result, community_evidence)

    assert '"available": false' in user_prompt.lower()
    assert "no_ground_signal" not in user_prompt
    assert "recent_reports" not in user_prompt


def test_build_stage3_prompt_compacts_empty_ground_truth_and_rounds_stage2_numbers():
    stage1_result = {}
    stage2_result = {
        "executive_summary": "y",
        "priority_area_justification": [
            {
                "justification_id": "Dire Dawa::drought",
                "risk_score": 16.812663291529855,
                "community_reports": report_stages._NO_COMMUNITY_REPORTS,
            },
        ],
    }
    _, user_prompt = report_stages.build_stage3_prompt(_request(), stage1_result, stage2_result, [])

    assert "16.813" in user_prompt or "16.81" in user_prompt
    assert "16.812663291529855" not in user_prompt
    assert '"available": false' in user_prompt.lower()
    assert "no_ground_signal" not in user_prompt


def test_action_evidence_packet_drops_differentiator_keeps_intervention_type_adds_livelihood_context():
    stage1_result = {"data_quality_notes": ["low agreement in Somali"]}
    stage2_result = {
        "executive_summary": "National overview text.",
        "priority_area_justification": [
            {
                "justification_id": "Dire Dawa::drought",
                "area": "Dire Dawa",
                "rank": 2,
                "hazard_type": "drought",
                "risk_score": 16.81,
                "hazard_probability": 0.684,
                "vulnerability": 0.487,
                "confidence": "high",
                "differentiator": "Ranks #2 nationally for drought risk based on the real computed priority score (0.480), driven by a risk score of 16.81.",
                "recommended_intervention_type": "Drought / water-security response",
                "population_exposed": 29733,
                "population_exposed_pct": 6.1,
                "roads_exposed_pct": 56.9,
                "healthsites_exposed_pct": 50.0,
                "cropland_exposed_pct": 61.2,
                "low_sample_size_warning": True,
                "cross_indicator_signal": "strong_drought",
                "supporting_indicators": ["spi", "cdd_anomaly"],
                "community_reports": report_stages._NO_COMMUNITY_REPORTS,
            },
        ],
    }

    packet = report_stages._action_evidence_packet(stage1_result, stage2_result)

    assert packet["executive_summary"] == "National overview text."
    assert packet["data_quality_notes"] == ["low agreement in Somali"]
    area = packet["priority_areas"][0]
    assert area["area"] == "Dire Dawa"
    assert area["rank"] == 2
    assert area["hazard"] == "drought"
    assert area["risk_score"] == 16.81
    assert area["hazard_probability_pct"] == 68.4
    # Confirmed real gap, fixed: cropland_exposed_pct was already computed
    # deterministically but never made it into the Action Evidence Packet
    # Stage 3 actually receives -- despite being the most operationally
    # relevant exposure metric for the farmer_advisory audience.
    assert area["cropland_exposed_pct"] == 61.2
    assert area["low_sample_size_warning"] is True
    assert area["recommended_intervention_type"] == "Drought / water-security response"
    assert area["livelihood_context"] == "not_available"
    assert area["ground_truth"] == {"available": False}
    # The whole point: differentiator (LLM prose restating these same
    # numbers) and the internal justification_id join key are NOT passed on.
    assert "differentiator" not in area
    assert "justification_id" not in area


def test_build_stage3_prompt_uses_compact_action_packet_not_full_stage1_stage2_dump():
    stage1_result = {
        "layer_by_layer_summary": ["a very long layer-by-layer bullet Stage 3 no longer needs"],
        "indicator_by_indicator_summary": ["a very long indicator bullet Stage 3 no longer needs"],
        "data_quality_notes": ["low agreement"],
    }
    stage2_result = {
        "executive_summary": "exec",
        "national_spatial_overview": ["a very long national overview paragraph Stage 3 no longer needs"],
        "compound_hazard_interpretation": ["a very long compound-hazard paragraph Stage 3 no longer needs"],
        "priority_area_justification": [
            {"justification_id": "Afar::drought", "area": "Afar", "differentiator": "should not appear in the prompt"},
        ],
    }
    _, user_prompt = report_stages.build_stage3_prompt(_request(), stage1_result, stage2_result, [])

    assert "ACTION EVIDENCE PACKET" in user_prompt
    assert "STAGE 1 VALIDATED EVIDENCE INTERPRETATION" not in user_prompt
    assert "STAGE 2 VALIDATED SYNTHESIS" not in user_prompt
    assert "layer-by-layer bullet Stage 3 no longer needs" not in user_prompt
    assert "national overview paragraph Stage 3 no longer needs" not in user_prompt
    assert "should not appear in the prompt" not in user_prompt
    assert "not_available" in user_prompt
    assert "not invent specific crops" in user_prompt


def test_build_stage2_prompt_ties_recommended_intervention_to_real_action_status():
    # Regression test for the confirmed real bug: a wet-ranked area with
    # Very low risk_score and cross-indicator evidence showing the
    # OPPOSITE hazard's strong signal (real example: an area ranked #2 for
    # wet risk while its own evidence said strong_drought) was still given
    # a full "Flood / wet-hazard mitigation response" label just because
    # it was in the top 5 -- rank alone was standing in for actionability.
    evidence = {"priority_area_justifications": [], "cross_indicator_findings": []}
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert "action_status" in user_prompt
    assert "not currently actionable" in user_prompt
    assert "do not treat a top-5 rank as proof that real action is warranted" in user_prompt.lower()


def test_build_stage3_prompt_does_not_overclaim_roads_healthsites_as_real_counts():
    # Confirmed real issue: roads_exposed_pct/healthsites_exposed_pct come
    # from a normalized 0-1 DENSITY index -- no real road-length or
    # facility-count dataset exists anywhere in this pipeline -- but the
    # old grounding note called them "the real share of road/health-
    # facility infrastructure exposed", which reads as a literal count
    # claim (e.g. "N of N facilities"). The note must say plainly this is
    # a density index, not a count, and flag small-area imprecision.
    _, user_prompt = report_stages.build_stage3_prompt(_request(), {}, {}, [])

    assert "NOT a real count" in user_prompt
    assert "never phrase them as" in user_prompt


def test_build_stage2_prompt_instructs_using_real_low_sample_size_warning():
    # Confirmed real gap, fixed: "data completeness is robust" used to be
    # the only real signal reaching a reader, even for areas like Harari
    # (3 cells) or Addis Ababa (4 cells) -- the model must now use the
    # real, already-computed low_sample_size_warning flag explicitly.
    evidence = {"priority_area_justifications": [], "cross_indicator_findings": []}
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert "low_sample_size_warning" in user_prompt
    assert "coarser estimate" in user_prompt


def test_build_stage3_prompt_does_not_claim_livestock_exposure_evidence_that_does_not_exist():
    # Confirmed real contradiction: this grounding note used to say
    # "grounded in the real livestock exposure... already given", but
    # _action_evidence_packet's packet_areas has no livestock field at
    # all -- only population/roads/healthsites exposure. Telling the model
    # to ground its answer in evidence that was never actually supplied
    # invites exactly the kind of unsupported claim this app's grounding
    # rules exist to prevent.
    _, user_prompt = report_stages.build_stage3_prompt(_request(), {}, {}, [])

    assert "no real per-area livestock exposure metric exists" in user_prompt
    assert "grounded in the real livestock exposure" not in user_prompt


def test_merge_priority_area_justifications_matches_by_id_and_degrades_gracefully():
    deterministic = [
        {"justification_id": "Afar::drought", "area": "Afar", "priority_score": 0.9},
        {"justification_id": "Somali::drought", "area": "Somali", "priority_score": 0.7},
    ]
    narrative = [
        {"justification_id": "Afar::drought", "differentiator": "highest exposure", "recommended_intervention_type": "Water security"},
        {"justification_id": "does-not-exist::drought", "differentiator": "should be ignored"},
    ]
    community_evidence = {
        "Afar": {"total_reports": 4, "feedback_signal": "emerging_ground_signal", "by_severity": {}, "by_type": {}, "recent_reports": []},
    }

    merged = report_stages._merge_priority_area_justifications(deterministic, narrative, community_evidence)
    by_id = {item["justification_id"]: item for item in merged}

    assert len(merged) == 2  # always one entry per deterministic area, never dropped or duplicated
    assert by_id["Afar::drought"]["differentiator"] == "highest exposure"
    assert by_id["Afar::drought"]["priority_score"] == 0.9  # real number preserved unchanged
    assert by_id["Afar::drought"]["recommended_intervention_type"] == "Water security"
    # No matching narrative for Somali -- degrades to empty strings, not a crash or missing entry.
    assert by_id["Somali::drought"]["differentiator"] == ""
    assert by_id["Somali::drought"]["recommended_intervention_type"] == ""

    # Real community evidence is attached by area name...
    assert by_id["Afar::drought"]["community_reports"]["total_reports"] == 4
    assert by_id["Afar::drought"]["community_reports"]["feedback_signal"] == "emerging_ground_signal"
    # ...and an area with no submitted reports gets the explicit zero-report
    # shape, not a missing key.
    assert by_id["Somali::drought"]["community_reports"] == report_stages._NO_COMMUNITY_REPORTS


def test_merge_priority_area_justifications_defaults_community_reports_when_omitted():
    deterministic = [{"justification_id": "Afar::drought", "area": "Afar", "priority_score": 0.9}]

    merged = report_stages._merge_priority_area_justifications(deterministic, [])

    assert merged[0]["community_reports"] == report_stages._NO_COMMUNITY_REPORTS


def test_build_stage3_prompt_references_prior_stages_and_agro_pastoral():
    stage1_result = {"layer_by_layer_summary": ["x"]}
    stage2_result = {"executive_summary": "y"}
    retrieved_guidance = [{"title": "Drought early action guidance", "text": "z"}]
    system_prompt, user_prompt = report_stages.build_stage3_prompt(
        _request(), stage1_result, stage2_result, retrieved_guidance,
    )

    assert "Stage 3" in user_prompt
    assert "agro_pastoral_advisory" in user_prompt
    assert "Drought early action guidance" in user_prompt
    # Step 7 items 6/7 -- structured timescale/category task instructions
    # and real-number/no-fabrication grounding notes.
    assert "immediate" in user_prompt and "near_term" in user_prompt and "preparedness" in user_prompt
    assert "monitoring" in user_prompt and "pre_positioning" in user_prompt and "immediate_action" in user_prompt
    assert "FEWS NET IPC" in user_prompt
    assert "roads_exposed_pct" in user_prompt and "healthsites_exposed_pct" in user_prompt
    assert "fabricated livestock exposure number or mortality rate" in user_prompt
    assert "rainfall anomaly alone" in user_prompt


def test_build_stage3_prompt_includes_real_context_header_and_scale_aware_temporal_framing():
    # Confirmed real gap, fixed: build_stage3_prompt never called
    # _context_header (unlike Stage 1/2), so Stage 3 had no way to know
    # whether this report's real forecast window/lead was Subseasonal
    # (week-level, where "next 7 days" framing is genuinely accurate) or
    # Seasonal (month-level, where day-specific "immediate" bullets would
    # overstate a seasonal signal as a short-range weather forecast).
    request = report_stages.AIMapInterpretationRequest(
        forecast_selection={"forecastScale": "seasonal", "lead": "month_2"},
    )
    _, user_prompt = report_stages.build_stage3_prompt(request, {}, {}, [])

    assert "CONTEXT:" in user_prompt
    assert "Forecast window: Seasonal" in user_prompt
    assert "never phrased as predicting weather on specific days" in user_prompt


def test_stage_system_prompts_share_grounding_rules_but_differ_by_stage_role():
    # Phase 2 revision: the 3 stages' system prompts are deliberately no
    # longer identical -- each gets its own stage-specific role framing
    # (task leakage fix: Stage 3 used to be told, via the shared prompt,
    # that its job was to "interpret Ethiopia-wide forecast map layers",
    # which is false -- Stage 3 receives zero images and zero raw evidence).
    # They still share the same BASE_GROUNDING_RULES verbatim.
    request = _request()
    system1, _, _ = report_stages.build_stage1_prompt(request, {"priority_scores": {}})
    system2, _ = report_stages.build_stage2_prompt(request, {}, {}, {})
    system3, _ = report_stages.build_stage3_prompt(request, {}, {}, [])

    assert system1 != system2
    assert system2 != system3
    assert system1 != system3

    from app.advisory.prompts.v1_system import BASE_GROUNDING_RULES
    assert BASE_GROUNDING_RULES in system1
    assert BASE_GROUNDING_RULES in system2
    assert BASE_GROUNDING_RULES in system3

    assert "EVIDENCE INTERPRETATION" in system1
    assert "INTEGRATED RISK SYNTHESIS" in system2
    assert "ACTION TRANSLATION" in system3

    # The specific bug being fixed: Stage 3 must not claim to interpret map
    # layers -- it receives no images and no raw evidence.
    assert "interpret Ethiopia-wide forecast map layers" not in system3


def test_merge_structured_summaries_keeps_real_fields_and_takes_only_llm_interpretation():
    # Regression test for the confirmed live bug: a real Gemini response
    # once returned national_mean: 42.61 for a layer whose real,
    # deterministic value was 3.409, used an invented label instead of the
    # real "layer" identifier, and reclassified national_signal. This
    # merge must make that impossible -- every field except interpretation
    # always comes from `deterministic`, regardless of what `narrative`
    # (the raw LLM response) claims for those same fields.
    deterministic = [
        {
            "layer": "population_r_drought", "national_signal": "very_low", "national_mean": 3.409,
            "highest_areas": ["Harari", "Dire Dawa"], "lowest_areas": ["Somali"], "affected_area_pct": 0.0,
            "interpretation": "template interpretation", "confidence": "moderate",
        },
        {
            "layer": "h_wet_mean", "national_signal": "low", "national_mean": 0.1,
            "highest_areas": [], "lowest_areas": [], "affected_area_pct": 2.0,
            "interpretation": "template interpretation 2", "confidence": "low",
        },
    ]
    narrative = [
        {
            "layer": "population_r_drought", "interpretation": "real LLM interpretation",
            # A real LLM attempting to also return these must not succeed --
            # they are silently ignored, not merged over the real values.
            "national_mean": 42.61, "national_signal": "Moderate", "affected_area_pct": 21.3,
        },
        {"layer": "does-not-exist", "interpretation": "should be ignored"},
    ]

    merged = report_stages._merge_structured_summaries(deterministic, narrative, "layer")
    by_layer = {item["layer"]: item for item in merged}

    assert len(merged) == 2  # always one entry per deterministic item, never dropped or duplicated
    assert by_layer["population_r_drought"]["interpretation"] == "real LLM interpretation"
    assert by_layer["population_r_drought"]["national_mean"] == 3.409  # real value, NOT the LLM's 42.61
    assert by_layer["population_r_drought"]["national_signal"] == "very_low"  # real value, NOT "Moderate"
    assert by_layer["population_r_drought"]["affected_area_pct"] == 0.0  # real value, NOT 21.3
    assert by_layer["population_r_drought"]["highest_areas"] == ["Harari", "Dire Dawa"]

    # No matching narrative entry -- degrades to the deterministic object's
    # own template interpretation (already grounded in real numbers), not
    # a blank string.
    assert by_layer["h_wet_mean"]["interpretation"] == "template interpretation 2"


def test_merge_structured_summaries_ignores_empty_or_blank_llm_interpretation():
    deterministic = [{"layer": "spi", "interpretation": "template", "national_mean": -1.1}]
    narrative = [{"layer": "spi", "interpretation": "   "}]

    merged = report_stages._merge_structured_summaries(deterministic, narrative, "layer")

    assert merged[0]["interpretation"] == "template"


def test_run_staged_report_generation_merges_all_three_stages(monkeypatch):
    monkeypatch.setattr(
        report_stages,
        "build_national_region_evidence",
        lambda period, admin_level, use_cache: {
            "cross_indicator_findings": [],
            "priority_area_justifications": [
                {"justification_id": "Afar::drought", "area": "Afar", "rank": 1, "priority_score": 0.9},
            ],
            # Real hazard_risk_layers entry -- so build_structured_layer_
            # summaries has something real to merge Stage 1's interpretation
            # onto; national_mean=0.5 is the value that must survive
            # regardless of what the fake LLM response below tries to claim.
            "hazard_risk_layers": {
                "h_dry_mean": {"national": {"mean": 0.5}, "regional": [], "class_area_pct": {}},
            },
            "categorical_layers": {},
            "climate_indicators": {},
        },
    )
    monkeypatch.setattr(
        report_stages,
        "build_community_evidence_by_region",
        lambda region_names: {
            "Afar": {"total_reports": 2, "feedback_signal": "limited_ground_signal", "by_severity": {"moderate": 2}, "by_type": {"water_shortage": 2}, "recent_reports": []},
        } if "Afar" in region_names else {},
    )
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    def fake_call(request, system_prompt, user_prompt, images, schema, model_tier="lite"):
        if schema is STAGE1_SCHEMA:
            return {
                # Real, current shape: the LLM only ever returns {layer,
                # interpretation} -- never national_mean/national_signal/
                # highest_areas/lowest_areas/affected_area_pct/confidence,
                # which are merged in server-side from the deterministic
                # evidence regardless of what's returned here. Also
                # includes a fabricated national_mean to prove it's ignored.
                "layer_by_layer_summary": [
                    {"layer": "h_dry_mean", "interpretation": "custom interpretation from LLM", "national_mean": 999.0},
                ],
                "indicator_by_indicator_summary": ["i1"],
                "data_quality_notes": ["d1"],
                "_metadata": {"provider": "gemini", "model": "m"},
            }
        if schema is STAGE2_SCHEMA:
            return {
                "executive_summary": "exec",
                "national_spatial_overview": ["n1"],
                "compound_hazard_interpretation": ["c1"],
                "priority_area_justification": [
                    {"justification_id": "Afar::drought", "differentiator": "diff", "recommended_intervention_type": "Water security"},
                ],
                "_metadata": {"provider": "gemini", "model": "m"},
            }
        if schema is STAGE3_SCHEMA:
            advisory_item = {"area": ["Afar"], "action": "f1", "trigger": "strong_drought", "evidence": ["spi"], "confidence": "high"}
            return {
                "farmer_advisory": {"immediate": [advisory_item], "near_term": [], "preparedness": []},
                "agro_pastoral_advisory": {"immediate": [], "near_term": [{**advisory_item, "action": "a1"}], "preparedness": []},
                "humanitarian_priorities": {"monitoring": [{**advisory_item, "action": "h1"}], "preparedness": [], "pre_positioning": [], "immediate_action": []},
                # Afar matches a real priority area (in priority_area_
                # justifications above) -- must survive _finalize_sms_
                # messages' real-area filter. character_count is NOT
                # provided here, proving it's always computed server-side.
                "sms_messages": [
                    {"area": "Afar", "audience": "general", "hazard": "drought", "valid_period": "July", "confidence": "high", "message": "sms"},
                    {"area": "Invented Place", "audience": "general", "hazard": "drought", "valid_period": "July", "confidence": "high", "message": "should be dropped"},
                ],
                "_metadata": {"provider": "gemini", "model": "m"},
            }
        raise AssertionError("unexpected schema")

    monkeypatch.setattr(report_stages, "call_configured_ai_provider_for_stage", fake_call)

    report = report_stages.run_staged_report_generation(_request(), [])

    # The real, deterministic national_mean (0.5) survives regardless of
    # what the LLM claimed (999.0) -- proves the merge, not the LLM, is
    # authoritative for every field except interpretation.
    layer_summary = report["layer_by_layer_summary"][0]
    assert layer_summary["layer"] == "h_dry_mean"
    assert layer_summary["national_mean"] == 0.5
    assert layer_summary["interpretation"] == "custom interpretation from LLM"
    assert report["executive_summary"] == "exec"
    assert report["agro_pastoral_advisory"]["near_term"][0]["action"] == "a1"
    assert report["agro_pastoral_advisory"]["near_term"][0]["area"] == ["Afar"]
    assert report["humanitarian_priorities"]["monitoring"][0]["action"] == "h1"
    # Real, server-side finalization: character_count is always computed
    # (never trusted from the model), and the message for "Invented Place"
    # (not a real priority area) is dropped entirely.
    assert len(report["sms_messages"]) == 1
    assert report["sms_messages"][0]["area"] == "Afar"
    assert report["sms_messages"][0]["message"] == "sms"
    assert report["sms_messages"][0]["character_count"] == len("sms")
    assert report["_metadata"]["ai_engine"] == "staged_workflow"
    assert report["_metadata"]["fallback_stages"] == []
    assert set(report["_metadata"]["stages"].keys()) == {"stage1", "stage2", "stage3"}

    # priority_area_justification is the MERGED real object (deterministic
    # fields + LLM narrative), not the LLM's narrative-only output verbatim.
    justification = report["priority_area_justification"][0]
    assert justification["justification_id"] == "Afar::drought"
    assert justification["rank"] == 1
    assert justification["priority_score"] == 0.9
    assert justification["differentiator"] == "diff"
    assert justification["recommended_intervention_type"] == "Water security"
    # Real community evidence flows all the way through to the final
    # merged, user-facing report -- not just the Stage 2 prompt.
    assert justification["community_reports"]["total_reports"] == 2
    assert justification["community_reports"]["feedback_signal"] == "limited_ground_signal"


def test_run_staged_report_generation_uses_strong_model_tier_only_for_stage2(monkeypatch):
    monkeypatch.setattr(
        report_stages,
        "build_national_region_evidence",
        lambda period, admin_level, use_cache: {"cross_indicator_findings": [], "priority_area_justifications": []},
    )
    monkeypatch.setattr(report_stages, "build_community_evidence_by_region", lambda region_names: {})
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    tiers_seen = {}

    def fake_call(request, system_prompt, user_prompt, images, schema, model_tier="lite"):
        if schema is STAGE1_SCHEMA:
            tiers_seen["stage1"] = model_tier
            return {"layer_by_layer_summary": [], "indicator_by_indicator_summary": [], "data_quality_notes": [], "_metadata": {}}
        if schema is STAGE2_SCHEMA:
            tiers_seen["stage2"] = model_tier
            return {
                "executive_summary": "x", "national_spatial_overview": [], "compound_hazard_interpretation": [],
                "priority_area_justification": [], "_metadata": {},
            }
        if schema is STAGE3_SCHEMA:
            tiers_seen["stage3"] = model_tier
            return {"farmer_advisory": [], "agro_pastoral_advisory": [], "humanitarian_priorities": [], "sms_summary": "", "_metadata": {}}
        raise AssertionError("unexpected schema")

    monkeypatch.setattr(report_stages, "call_configured_ai_provider_for_stage", fake_call)

    report_stages.run_staged_report_generation(_request(), [])

    assert tiers_seen == {"stage1": "lite", "stage2": "strong", "stage3": "lite"}


def test_call_configured_ai_provider_for_stage_orders_gemini_models_by_tier(monkeypatch):
    from app.api import ai_map_interpretation as aim

    attempted_models = []

    def fake_try_provider(label, func, errors):
        attempted_models.append(label)
        return None  # simulate every attempt failing, to observe the FULL order tried

    monkeypatch.setattr(aim, "try_provider", fake_try_provider)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = AIMapInterpretationRequest(requested_provider="free_auto")

    try:
        aim.call_configured_ai_provider_for_stage(request, "sys", "user", [], STAGE1_SCHEMA, model_tier="lite")
    except aim.ProviderError:
        pass
    lite_order = list(attempted_models)

    attempted_models.clear()
    try:
        aim.call_configured_ai_provider_for_stage(request, "sys", "user", [], STAGE2_SCHEMA, model_tier="strong")
    except aim.ProviderError:
        pass
    strong_order = list(attempted_models)

    assert lite_order[0] == f"Gemini {aim.GEMINI_MODEL_TIERS['lite'][0]}"
    assert strong_order[0] == f"Gemini {aim.GEMINI_MODEL_TIERS['strong'][0]}"
    # The two tiers try Gemini's models in opposite order.
    assert aim.GEMINI_MODEL_TIERS["lite"][0] == aim.GEMINI_MODEL_TIERS["strong"][1]
    assert aim.GEMINI_MODEL_TIERS["lite"][1] == aim.GEMINI_MODEL_TIERS["strong"][0]


def test_run_staged_report_generation_falls_back_for_failed_stage_only(monkeypatch):
    monkeypatch.setattr(
        report_stages,
        "build_national_region_evidence",
        lambda period, admin_level, use_cache: {
            "cross_indicator_findings": [],
            "priority_area_justifications": [
                {"justification_id": "Afar::drought", "area": "Afar", "rank": 1, "priority_score": 0.9, "hazard_type": "drought", "risk_score": 45.0, "hazard_probability": 0.7},
            ],
            "hazard_risk_layers": {
                "h_dry_mean": {"national": {"mean": 0.5}, "regional": [], "class_area_pct": {}},
            },
            "categorical_layers": {},
            "climate_indicators": {},
        },
    )
    monkeypatch.setattr(report_stages, "build_community_evidence_by_region", lambda region_names: {})
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    def fake_call(request, system_prompt, user_prompt, images, schema, model_tier="lite"):
        if schema is STAGE1_SCHEMA:
            return {
                "layer_by_layer_summary": [{"layer": "h_dry_mean", "interpretation": "real-l1"}],
                "indicator_by_indicator_summary": ["real-i1"],
                "data_quality_notes": ["real-d1"],
                "_metadata": {"provider": "gemini", "model": "m"},
            }
        if schema is STAGE2_SCHEMA:
            raise RuntimeError("all providers exhausted")
        if schema is STAGE3_SCHEMA:
            return {
                "farmer_advisory": {"immediate": ["real-f1"], "near_term": [], "preparedness": []},
                "agro_pastoral_advisory": {"immediate": ["real-a1"], "near_term": [], "preparedness": []},
                "humanitarian_priorities": {"monitoring": ["real-h1"], "preparedness": [], "pre_positioning": [], "immediate_action": []},
                "sms_summary": "real-sms",
                "_metadata": {"provider": "gemini", "model": "m"},
            }
        raise AssertionError("unexpected schema")

    monkeypatch.setattr(report_stages, "call_configured_ai_provider_for_stage", fake_call)

    report = report_stages.run_staged_report_generation(_request(), [])

    assert report["layer_by_layer_summary"][0]["layer"] == "h_dry_mean"
    assert report["layer_by_layer_summary"][0]["interpretation"] == "real-l1"
    assert report["farmer_advisory"] == {"immediate": ["real-f1"], "near_term": [], "preparedness": []}
    # Stage 2 failed -> deterministic fallback fields, not empty/missing.
    assert report["executive_summary"]
    assert report["_metadata"]["stages"]["stage2"]["ai_engine"] == "rule_based_fallback"
    assert report["_metadata"]["stages"]["stage1"]["provider"] == "gemini"
    # Partial fallback (stage2 only) must be visible at the top level, not
    # just buried in "stages" -- this is what lets the UI honestly warn that
    # part of the report is untranslated rule-based English text.
    assert report["_metadata"]["fallback_stages"] == ["stage2"]
    assert report["_metadata"]["ai_engine"] == "staged_workflow_partial_fallback"

    # Even on Stage 2 failure, the real deterministic priority-area numbers
    # survive (merged with the fallback's own generic-but-grounded narrative)
    # -- never dropped just because the LLM call failed.
    justification = report["priority_area_justification"][0]
    assert justification["justification_id"] == "Afar::drought"
    assert justification["priority_score"] == 0.9
    assert justification["differentiator"]


def test_run_staged_report_generation_flags_full_fallback(monkeypatch):
    monkeypatch.setattr(
        report_stages,
        "build_national_region_evidence",
        lambda period, admin_level, use_cache: {"cross_indicator_findings": [], "priority_area_justifications": []},
    )
    monkeypatch.setattr(report_stages, "build_community_evidence_by_region", lambda region_names: {})
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])
    monkeypatch.setattr(
        report_stages,
        "call_configured_ai_provider_for_stage",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("all providers exhausted")),
    )

    report = report_stages.run_staged_report_generation(_request(), [])

    assert set(report["_metadata"]["fallback_stages"]) == {"stage1", "stage2", "stage3"}
    assert report["_metadata"]["ai_engine"] == "staged_workflow_full_fallback"
