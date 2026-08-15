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

    evidence = {
        "climate_indicators": {"spi": {"national": {"mean": -1.2}, "regional": [], "category": "moderately_dry"}},
        "priority_scores": {"population_r_drought": []},
        "priority_area_justifications": [{"justification_id": "Afar::drought", "area": "Afar", "rank": 1}],
    }
    system_prompt, user_prompt, stage_images = report_stages.build_stage1_prompt(_request(), evidence)

    assert stage_images == curated
    assert captured_args["evidence"] is evidence
    assert "Stage 1" in user_prompt
    assert "priority_scores" not in user_prompt
    # Confirmed real gap, fixed: the old raw evidence spread's exclusion
    # list named priority_scores but not priority_area_justifications --
    # the already-ranked priority-area list, an even more direct violation
    # of "Stage 1 cannot decide which areas matter" than priority_scores
    # itself. See _evidence_interpretation_packet's docstring.
    assert "priority_area_justifications" not in user_prompt
    assert "justification_id" not in user_prompt
    # Confirmed real gap, fixed: the old design spread the ENTIRE raw
    # climate_indicators/hazard_risk_layers/categorical_layers dicts on top
    # of the already-compact real_layer_summaries/real_indicator_summaries
    # derived from that same data -- pure redundancy that caused real
    # truncation (see _evidence_interpretation_packet's docstring). The raw
    # top-level key itself must no longer appear; only the derived,
    # compact summary (which DOES carry this SPI entry's real data through)
    # should.
    assert "climate_indicators" not in user_prompt
    assert "real_layer_summaries" in user_prompt
    assert "real_indicator_summaries" in user_prompt
    assert '"indicator": "spi"' in user_prompt
    assert "moderately_dry" in user_prompt


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
    # Confirmed real gap, fixed (see _evidence_interpretation_packet's
    # docstring): the OLD design spread the full raw climate_indicators/
    # hazard_risk_layers/categorical_layers dicts into this prompt, and
    # THAT raw per-region bulk (confirmed live: ~136k real chars) was what
    # real truncation used to cut through on every real run. Those raw
    # dumps are gone now, replaced by the already-compact real_layer_
    # summaries/real_indicator_summaries -- so a bulky climate_indicators
    # input no longer produces a bulky prompt at all (this is itself the
    # fix, not a regression: build_structured_indicator_summaries only
    # ever extracts a national mean/signal + top-2/bottom-2 area names per
    # indicator, never the raw per-region array).
    #
    # The one real field left in the new packet that still scales directly
    # with region count is cross_indicator_findings (one entry per real
    # admin1 region, included in full, not summarized) -- this reproduces
    # real truncation via THAT field instead, confirming population_
    # exposure_summary/risk_definition (placed earlier in the packet) still
    # survive it.
    monkeypatch.setattr(report_stages, "select_curated_stage1_images", lambda request, evidence, period: [])

    bulky_cross_indicator_findings = [
        {
            "area": f"Region {i}",
            "signal": "strong_drought",
            "agreement_score": 0.8,
            "confidence": "high",
            "supporting_indicators": ["spi", "cdd_anomaly", "rainfall_percentile"],
            "contradicting_indicators": [],
        }
        for i in range(400)
    ]
    evidence = {"cross_indicator_findings": bulky_cross_indicator_findings}

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
    assert "justification_id" in user_prompt
    # priority_score is deliberately excluded from Stage 2's own compact
    # packet (see _stage2_priority_area_view) -- it's banned from citation
    # anyway, so removing it from the evidence itself is the stronger fix.
    # rank, a legitimate ordinal signal, stays.
    assert "0.9" not in user_prompt
    assert '"rank": 1' in user_prompt
    # Real community ground-truth evidence is embedded and attributed by area.
    assert "COMMUNITY GROUND-TRUTH" in user_prompt
    assert "emerging_ground_signal" in user_prompt
    assert "pasture_stress" in user_prompt


def test_synthesis_evidence_packet_drops_fields_stage2_does_not_need():
    # Confirmed real gap, fixed: priority_score (banned from citation),
    # supporting_indicators/contradicting_indicators (duplicated per-area in
    # the separate cross-indicator block), and valid_cell_count (only the
    # boolean low_sample_size_warning is ever referenced by Stage 2's task)
    # used to be sent to Stage 2 in full, contributing real bulk toward the
    # blind character-count truncation this packet exists to prevent.
    stage1_result = {"layer_by_layer_summary": [], "indicator_by_indicator_summary": [], "data_quality_notes": ""}
    evidence = {
        "priority_area_justifications": [{
            "justification_id": "Harari::drought",
            "area": "Harari",
            "rank": 1,
            "priority_score": 0.599,
            "risk_score": 23.6,
            "risk_class": "Low",
            "action_status": "preparedness",
            "hazard_probability": 0.787,
            "supporting_indicators": [{"indicator": "spi", "value": -2.7}],
            "contradicting_indicators": [],
            "valid_cell_count": 3,
            "low_sample_size_warning": True,
            "cross_indicator_signal": "strong_drought",
        }],
    }

    packet = report_stages._synthesis_evidence_packet(stage1_result, evidence)
    area = packet["priority_areas"][0]

    assert "priority_score" not in area
    assert "supporting_indicators" not in area
    assert "contradicting_indicators" not in area
    assert "valid_cell_count" not in area
    # Real fields Stage 2's own task genuinely needs all stay.
    assert area["risk_score"] == 23.6
    assert area["risk_class"] == "Low"
    assert area["action_status"] == "preparedness"
    assert area["low_sample_size_warning"] is True
    assert area["cross_indicator_signal"] == "strong_drought"
    assert area["justification_id"] == "Harari::drought"


def test_synthesis_evidence_packet_compacts_classification_method_to_a_code():
    # Confirmed real gap, fixed: repeating the full ~30-95 char
    # classification_method sentence on every one of ~18 layer/indicator
    # entries added real, avoidable bulk -- the short code + one shared
    # legend (see CLASSIFICATION_METHOD_LEGEND) says the same thing once.
    # classification_breakpoints (a Stage-1 classification detail Stage 2's
    # own task never references) is dropped entirely.
    stage1_result = {
        "layer_by_layer_summary": [{
            "layer": "h_dry_mean",
            "national_mean": 0.5,
            "classification_method": "quintiles_of_current_period (no separate climatology exists for this layer)",
            "classification_breakpoints": [0.1, 0.3, 0.5, 0.7],
        }],
        "indicator_by_indicator_summary": [],
        "data_quality_notes": "",
    }
    evidence = {"priority_area_justifications": []}

    packet = report_stages._synthesis_evidence_packet(stage1_result, evidence)
    item = packet["layer_summaries"][0]

    assert item["classification_method"] == "quintile_period"
    assert "classification_breakpoints" not in item
    assert item["national_mean"] == 0.5  # untouched real value


def test_compact_indicator_criteria_bakes_units_into_keys_without_losing_values():
    # Confirmed real gap, fixed: supporting_indicators/contradicting_
    # indicators repeated the same {indicator, value, units, ...} object
    # shape on every one of up to ~16 real regions -- the "units" strings
    # were pure repeated boilerplate (rainfall_anomaly is ALWAYS "mm", spi
    # is ALWAYS "std dev", etc.), never varying per-region. Baking the unit
    # into the key removes that repetition with zero value loss.
    objects = [
        {"indicator": "rainfall_anomaly", "value": -28.27, "units": "mm", "value_pct": -53.74, "units_pct": "%"},
        {"indicator": "spi", "value": -1.12, "units": "std dev"},
        {"indicator": "cdd_anomaly", "value": 3.25, "units": "days"},
        {"indicator": "drought_probability", "value": 80.0, "units": "%"},
        {"indicator": "rainfall_percentile", "value": 10.0, "units": "percentile"},
        # The rx_anomaly wrapper's own indicator/value/units triplet is
        # redundant with its two real sibling values -- dropped in favor
        # of reporting both siblings directly.
        {"indicator": "rx5day_anomaly", "value": 7.92, "units": "mm", "rx1day_anomaly": 1.0, "rx5day_anomaly": 7.92},
    ]

    compact = report_stages._compact_indicator_criteria(objects)

    assert compact == {
        "rainfall_anomaly_mm": -28.27,
        "rainfall_anomaly_pct": -53.74,
        "spi_stddev": -1.12,
        "cdd_anomaly_days": 3.25,
        "drought_probability_pct": 80.0,
        "rainfall_percentile": 10.0,
        "rx1day_anomaly_mm": 1.0,
        "rx5day_anomaly_mm": 7.92,
    }
    # No "units"/"units_pct"/bare "indicator" wrapper keys leaked through.
    assert "units" not in str(compact.keys())


def test_build_stage2_prompt_compacts_cross_indicator_supporting_contradicting():
    evidence = {
        "priority_area_justifications": [],
        "cross_indicator_findings": [
            {
                "area": "National", "signal": "partial_drought", "agreement_score": 0.6, "confidence": "medium",
                "supporting_indicators": [{"indicator": "spi", "value": -1.12, "units": "std dev"}],
                "contradicting_indicators": [],
                "missing_indicators": ["cwd_anomaly"],
            },
        ],
    }
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert '"spi_stddev": -1.12' in user_prompt
    # Confirmed real gap, fixed: missing_indicators was never referenced by
    # any Stage 2 prompt instruction (confidence already reflects its
    # practical effect) -- dropped from the compact view as pure unused
    # weight, not silently lost information a task actually needed.
    assert "missing_indicators" not in user_prompt
    assert "cwd_anomaly" not in user_prompt


def test_build_stage2_prompt_includes_classification_method_legend_and_no_truncation_marker():
    # Regression guard for the confirmed real bug this packet replaced:
    # compact_json's blind character-count truncation was silently cutting
    # real Stage 1/priority-area evidence mid-object on real-sized data
    # (measured: ~12.2k/~12.0k real chars against 10k ceilings). The new
    # packet must fit comfortably under its higher ceilings without ever
    # emitting the "...TRUNCATED..." marker for a realistic real-sized
    # national report (18 layer/indicator entries, 10 priority areas).
    layer_summaries = [
        {
            "layer": f"layer_{i}",
            "national_signal": "moderate",
            "national_mean": 12.345,
            "highest_areas": ["Somali", "Afar"],
            "lowest_areas": ["Addis Ababa", "Harari"],
            "high_or_very_high_area_pct": 42.1,
            "classification_method": "quintiles_of_real_climatology",
            "classification_breakpoints": [1.0, 2.0, 3.0, 4.0],
            "interpretation": "A real, fairly detailed interpretation sentence describing this layer's national pattern in plain language for the report reader.",
            "confidence": "moderate",
        }
        for i in range(18)
    ]
    priority_areas = [
        {
            "justification_id": f"Area{i}::drought",
            "area": f"Area{i}",
            "rank": i + 1,
            "hazard_type": "drought",
            "risk_score": 23.622,
            "risk_class": "Low",
            "action_status": "preparedness",
            "hazard_probability": 0.787,
            "vulnerability": 0.551,
            "population_exposed": 240167.7,
            "population_exposed_pct": 84.86,
            "roads_exposed_pct": 35.97,
            "healthsites_exposed_pct": 100.0,
            "cropland_exposed_pct": 30.72,
            "supporting_indicators": [{"indicator": "spi", "value": -2.7, "units": "std dev"}] * 5,
            "contradicting_indicators": [],
            "cross_indicator_signal": "strong_drought",
            "confidence": "high",
            "valid_cell_count": 3,
            "low_sample_size_warning": True,
        }
        for i in range(10)
    ]
    stage1_result = {"layer_by_layer_summary": layer_summaries, "indicator_by_indicator_summary": [], "data_quality_notes": "notes"}
    evidence = {"priority_area_justifications": priority_areas, "cross_indicator_findings": []}

    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, stage1_result, {})

    assert "CLASSIFICATION_METHOD LEGEND" in user_prompt
    assert "quintile_climatology" in user_prompt
    assert "TRUNCATED" not in user_prompt


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
                "action_status": "action",  # actionable -- routes to actionable_areas, which carries risk_score
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
                "risk_class": "Low",
                "action_status": "action",
                "hazard_probability": 0.684,
                "vulnerability": 0.487,
                "cross_indicator_confidence": "high",
                "data_quality_confidence": "moderate",
                "differentiator": "Ranks #2 nationally for drought risk based on the real computed priority score (0.480), driven by a risk score of 16.81.",
                "recommended_intervention_type": "Drought / water-security response",
                "population_exposed": 29733,
                "population_exposed_pct": 6.1,
                "roads_exposed_pct": 56.9,
                "roads_length_total_km": 276.3,
                "roads_length_exposed_km": 70.6,
                "healthsites_exposed_pct": 50.0,
                "healthsites_total_count": 14,
                "healthsites_exposed_count": 4,
                "cropland_exposed_pct": 61.2,
                "livestock_exposed_pct": 43.1,
                "low_sample_size_warning": True,
                "cross_indicator_signal": "strong_drought",
                "supporting_indicators": [
                    {"indicator": "spi", "value": -1.5, "units": "std dev"},
                    {"indicator": "cdd_anomaly", "value": 5.0, "units": "days"},
                ],
                "community_reports": report_stages._NO_COMMUNITY_REPORTS,
            },
        ],
    }

    packet = report_stages._action_evidence_packet(stage1_result, stage2_result)

    assert packet["executive_summary"] == "National overview text."
    assert packet["data_quality_notes"] == ["low agreement in Somali"]
    assert packet["monitor_only_areas"] == []
    area = packet["actionable_areas"][0]
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
    # Confirmed real gap, fixed: livestock_exposed_pct (real GLW4
    # cattle-density raster) was already computed but never made it into
    # the Action Evidence Packet either -- same gap as cropland above.
    assert area["livestock_exposed_pct"] == 43.1
    # Confirmed real gap, fixed: real OSM-derived road-length/health-
    # facility denominators (see app.data_pipeline.infrastructure_data_
    # pipeline) were already computed but never made it into the Action
    # Evidence Packet either -- same gap, same fix.
    assert area["roads_length_total_km"] == 276.3
    assert area["roads_length_exposed_km"] == 70.6
    assert area["healthsites_total_count"] == 14
    assert area["healthsites_exposed_count"] == 4
    assert area["cross_indicator_confidence"] == "high"
    assert area["data_quality_confidence"] == "moderate"
    assert area["low_sample_size_warning"] is True
    assert area["recommended_intervention_type"] == "Drought / water-security response"
    assert area["livelihood_context"] == "not_available"
    assert area["ground_truth"] == {"available": False}
    # supporting_indicators is compacted (see _compact_indicator_criteria)
    # -- same verbose-object-to-{criterion: value} shape as Stage 2's
    # cross-indicator block, since it's literally the same real object.
    assert area["supporting_indicators"] == {"spi_stddev": -1.5, "cdd_anomaly_days": 5.0}
    # The whole point: differentiator (LLM prose restating these same
    # numbers) and the internal justification_id join key are NOT passed on.
    assert "differentiator" not in area
    assert "justification_id" not in area


def test_action_evidence_packet_splits_monitor_only_areas_with_minimal_detail():
    # Confirmed real gap, fixed: every priority area used to get the SAME
    # full detail regardless of action_status, even though a real period
    # typically has far more monitor_only/not_actionable areas than
    # actionable ones (measured: July's real data, 1 of 10). Stage 3's own
    # TASK already forbids a real response recommendation for these areas,
    # so their full risk/exposure/indicator breakdown was unused weight.
    stage1_result = {}
    stage2_result = {
        "executive_summary": "x",
        "priority_area_justification": [
            {
                "justification_id": "Dire Dawa::drought", "area": "Dire Dawa", "hazard_type": "drought",
                "rank": 2, "risk_class": "Very low", "action_status": "monitor_only",
                "cross_indicator_signal": "strong_drought", "cross_indicator_confidence": "medium",
                # Full detail present in the real deterministic object, but
                # must NOT reach monitor_only_areas -- only the 7 minimal
                # fields below should.
                "risk_score": 12.1, "hazard_probability": 0.3, "vulnerability": 0.2,
                "data_quality_confidence": "low",
                "population_exposed_pct": 40.0, "supporting_indicators": [{"indicator": "spi", "value": -1.0, "units": "std dev"}],
            },
            {
                "justification_id": "Somali::drought", "area": "Somali", "hazard_type": "drought",
                "rank": 3, "risk_class": "Very low", "action_status": "not_actionable",
                "cross_indicator_signal": "no_clear_signal",
            },
        ],
    }

    packet = report_stages._action_evidence_packet(stage1_result, stage2_result)

    assert packet["actionable_areas"] == []
    assert len(packet["monitor_only_areas"]) == 2
    dire_dawa = next(item for item in packet["monitor_only_areas"] if item["area"] == "Dire Dawa")
    assert dire_dawa == {
        "area": "Dire Dawa", "hazard": "drought", "rank": 2, "risk_class": "Very low",
        "cross_indicator_signal": "strong_drought", "cross_indicator_confidence": "medium",
        "reason": "monitor_only",
    }
    somali = next(item for item in packet["monitor_only_areas"] if item["area"] == "Somali")
    assert somali["reason"] == "not_actionable"
    # Full-detail fields never leaked into the minimal monitor_only shape --
    # data_quality_confidence deliberately excluded too (see this
    # function's own docstring), unlike cross_indicator_confidence.
    assert "risk_score" not in dire_dawa
    assert "supporting_indicators" not in dire_dawa
    assert "data_quality_confidence" not in dire_dawa


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


def test_build_stage2_prompt_distinguishes_national_aggregate_signal_from_area_level_rollup():
    # Confirmed real gap, fixed: a real Gemini Stage 2 output wrote "a
    # strong national signal toward drought conditions" while the real
    # National cross_indicator_findings entry was only "partial_drought"
    # (agreement_score 0.6) -- it conflated "several areas are individually
    # strong" with "the national aggregate itself is strong". The prompt
    # must explicitly tell the model these are two separate statements.
    evidence = {"priority_area_justifications": [], "cross_indicator_findings": []}
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert "must never be conflated" in user_prompt
    assert "Never describe the national aggregate itself as \"strong\"" in user_prompt


def test_build_stage2_prompt_supplies_real_area_signal_tally_and_forbids_self_counting():
    # Confirmed real gap, fixed: a real Gemini Stage 2 output wrote "15
    # individual administrative zones independently display a strong
    # drought signal", naming only 8 of them, while the real
    # cross_indicator_findings for that run held exactly 6 real
    # strong_drought areas -- the model was counting the per-area rows
    # itself. The prompt must now hand it the real, pre-counted tally and
    # explicitly forbid counting the rows itself.
    evidence = {
        "priority_area_justifications": [],
        "cross_indicator_findings": [
            {"area": "National", "signal": "partial_drought", "agreement_score": 0.6},
            {"area": "Afar", "signal": "strong_drought", "agreement_score": 1.0},
            {"area": "Harari", "signal": "strong_drought", "agreement_score": 0.8},
        ],
    }
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert "REAL, ALREADY-COUNTED AREA SIGNAL TALLY" in user_prompt
    assert '"strong_drought": 2' in user_prompt
    assert "do not count the CROSS-INDICATOR AGREEMENT rows yourself" in user_prompt


def test_build_stage2_prompt_labels_forecast_vs_climatology_roles():
    # Confirmed real gap, fixed: a real Gemini Stage 2 output wrote
    # "Climatologically, total rainfall averages 101.429 mm against a
    # baseline of 129.697 mm" -- 101.429 was the real FORECAST mean, not
    # the climatology baseline; the word "climatology" was pointed at the
    # wrong real number even though both were correctly present.
    _, user_prompt = report_stages.build_stage2_prompt(_request(), {"priority_area_justifications": [], "cross_indicator_findings": []}, {}, {})

    assert "FORECAST VS CLIMATOLOGY LABELING" in user_prompt
    assert "must always introduce climatology_mean's own value, never forecast_mean's" in user_prompt


def test_build_stage2_prompt_forbids_attributing_vulnerability_to_climate_drivers():
    # Confirmed real gap, fixed: a real Gemini Stage 2 output wrote
    # "drought vulnerability is classified as very high nationally ...
    # driven by severe rainfall deficits" -- vulnerability (v_drought/
    # v_wet) is a real, independently-sourced baseline food-security/
    # livelihood layer (FEWS NET IPC phase data), not something forecast
    # rainfall/SPI/hazard probability causes.
    _, user_prompt = report_stages.build_stage2_prompt(_request(), {"priority_area_justifications": [], "cross_indicator_findings": []}, {}, {})

    assert "VULNERABILITY CAUSALITY RULE" in user_prompt
    assert 'Never use "driven by"/"because of"/"due to"/"caused by" to connect a vulnerability statement to a climate/hazard value' in user_prompt


def test_build_stage2_prompt_requires_real_superlative_flags_for_comparative_claims():
    # Confirmed real gap, fixed: a real Gemini Stage 2 differentiator
    # claimed a top-ranked area held "the highest hazard probability among
    # drought areas" -- a DIFFERENT real area in the same real batch
    # actually had a higher value. The model cannot correctly compare raw
    # numbers across areas itself; it must use the real, deterministic
    # highest_among_group/lowest_among_group fields instead (see
    # app.context.statistical_evidence._superlative_flags).
    _, user_prompt = report_stages.build_stage2_prompt(_request(), {"priority_area_justifications": [], "cross_indicator_findings": []}, {}, {})

    assert "SUPERLATIVE WORDS" in user_prompt
    assert "highest_among_group" in user_prompt and "lowest_among_group" in user_prompt
    assert "You cannot correctly compare raw numbers across areas yourself" in user_prompt


def test_build_stage3_prompt_now_allows_real_road_and_healthsite_counts():
    # Confirmed real gap, fixed: roads_exposed_pct/healthsites_exposed_pct
    # used to come ONLY from a normalized 0-1 DENSITY index with no real
    # denominator -- the old grounding note explicitly forbade phrasing
    # them as "N of N facilities" for exactly that reason. Real OSM-derived
    # counts (roads_length_total_km/healthsites_total_count etc., see
    # app.data_pipeline.infrastructure_data_pipeline) now exist, so the
    # note must explicitly ALLOW real-count phrasing for these two
    # specifically, while still forbidding it for cropland/livestock
    # (which genuinely still have no real hectare/headcount data).
    _, user_prompt = report_stages.build_stage3_prompt(_request(), {}, {}, [])

    assert "roads_length_total_km" in user_prompt and "healthsites_total_count" in user_prompt
    assert "You MAY now phrase these as real counts" in user_prompt
    assert "motorway/trunk/primary/secondary/tertiary" in user_prompt
    # cropland/livestock still have no real count -- the ban stays for them.
    assert 'never phrase THOSE two as "N hectares of cropland" or "N head of livestock"' in user_prompt


def test_build_stage3_prompt_uses_language_aware_sms_character_budget():
    # Confirmed real gap, fixed: Amharic/Tigrinya render in Ethiopic script,
    # which forces UCS-2 SMS encoding (70 chars/segment) rather than GSM-7
    # (160 chars/segment) -- a single hardcoded 160-char target silently
    # doubles the real per-segment cost for those 2 languages.
    _, english_prompt = report_stages.build_stage3_prompt(_request(), {}, {}, [])
    assert "at most 155 characters" in english_prompt

    amharic_request = AIMapInterpretationRequest(target_language="am")
    _, amharic_prompt = report_stages.build_stage3_prompt(amharic_request, {}, {}, [])
    assert "at most 70 characters" in amharic_prompt


def test_build_stage2_prompt_instructs_using_real_low_sample_size_warning():
    # Confirmed real gap, fixed: "data completeness is robust" used to be
    # the only real signal reaching a reader, even for areas like Harari
    # (3 cells) or Addis Ababa (4 cells) -- the model must now use the
    # real, already-computed low_sample_size_warning flag explicitly.
    evidence = {"priority_area_justifications": [], "cross_indicator_findings": []}
    _, user_prompt = report_stages.build_stage2_prompt(_request(), evidence, {}, {})

    assert "low_sample_size_warning" in user_prompt
    assert "coarser estimate" in user_prompt


def test_build_stage3_prompt_grounds_livestock_risk_in_real_cattle_exposure_and_discloses_cattle_only_scope():
    # Confirmed real gap, fixed: livestock_exposed_pct (real GLW4
    # cattle-density raster, wired into build_priority_area_justifications
    # the same way cropland/roads/healthsites already were) now exists as
    # real per-area evidence -- the old grounding note claiming "no real
    # per-area livestock exposure metric exists in this pipeline at all"
    # would now be FALSE. It must instead ground livestock risk in this
    # real number while disclosing it is cattle-only (no sheep/goats
    # raster exists in this catalog) and still only a density share, not a
    # headcount or measured mortality rate.
    _, user_prompt = report_stages.build_stage3_prompt(_request(), {}, {}, [])

    assert "no real per-area livestock exposure metric exists" not in user_prompt
    assert "CATTLE ONLY" in user_prompt
    assert "never describe it as covering sheep, goats, or livestock generally" in user_prompt
    assert "livestock mortality risk has no real measured rate" in user_prompt


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
    assert "roads_exposed_pct" in user_prompt and "healthsites_exposed_pct" in user_prompt and "livestock_exposed_pct" in user_prompt
    assert "never a fabricated mortality number" in user_prompt
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
            "highest_areas": ["Harari", "Dire Dawa"], "lowest_areas": ["Somali"], "high_or_very_high_area_pct": 0.0,
            "interpretation": "template interpretation", "confidence": "moderate",
        },
        {
            "layer": "h_wet_mean", "national_signal": "low", "national_mean": 0.1,
            "highest_areas": [], "lowest_areas": [], "high_or_very_high_area_pct": 2.0,
            "interpretation": "template interpretation 2", "confidence": "low",
        },
    ]
    narrative = [
        {
            "layer": "population_r_drought", "interpretation": "real LLM interpretation",
            # A real LLM attempting to also return these must not succeed --
            # they are silently ignored, not merged over the real values.
            "national_mean": 42.61, "national_signal": "Moderate", "high_or_very_high_area_pct": 21.3,
        },
        {"layer": "does-not-exist", "interpretation": "should be ignored"},
    ]

    merged = report_stages._merge_structured_summaries(deterministic, narrative, "layer")
    by_layer = {item["layer"]: item for item in merged}

    assert len(merged) == 2  # always one entry per deterministic item, never dropped or duplicated
    assert by_layer["population_r_drought"]["interpretation"] == "real LLM interpretation"
    assert by_layer["population_r_drought"]["national_mean"] == 3.409  # real value, NOT the LLM's 42.61
    assert by_layer["population_r_drought"]["national_signal"] == "very_low"  # real value, NOT "Moderate"
    assert by_layer["population_r_drought"]["high_or_very_high_area_pct"] == 0.0  # real value, NOT 21.3
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
                # highest_areas/lowest_areas/high_or_very_high_area_pct/confidence,
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
