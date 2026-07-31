from app.api import report_stages
from app.api.ai_map_interpretation import (
    STAGE1_SCHEMA,
    STAGE2_SCHEMA,
    STAGE3_SCHEMA,
    AIMapInterpretationRequest,
)


def _request():
    return AIMapInterpretationRequest()


def test_build_stage1_prompt_caps_images_and_excludes_priority_scores(monkeypatch):
    images = [
        {"map_id": f"img{i}", "label": f"img{i}", "data_url": f"data:image/png;base64,x{i}"}
        for i in range(32)
    ]
    monkeypatch.setattr(report_stages, "get_all_image_urls", lambda request: images)

    evidence = {"climate_indicators": {"spi": {}}, "priority_scores": {"population_r_drought": []}}
    system_prompt, user_prompt, stage_images = report_stages.build_stage1_prompt(_request(), evidence)

    assert len(stage_images) == report_stages.STAGE1_IMAGE_CAP
    assert "Stage 1" in user_prompt
    assert "priority_scores" not in user_prompt
    assert "climate_indicators" in user_prompt


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
    assert "fabricated numeric rate" in user_prompt
    assert "rainfall anomaly alone" in user_prompt


def test_all_three_stage_system_prompts_are_identical():
    # The user asked for 1 shared system prompt instead of 3 different
    # ones -- confirms build_system_prompt's own text (no per-stage
    # addition) is used verbatim by all 3 builders; stage-scoping now
    # lives entirely in each user prompt instead.
    request = _request()
    system1, _, _ = report_stages.build_stage1_prompt(request, {"priority_scores": {}})
    system2, _ = report_stages.build_stage2_prompt(request, {}, {}, {})
    system3, _ = report_stages.build_stage3_prompt(request, {}, {}, [])

    assert system1 == system2 == system3
    assert "Stage 1" not in system1
    assert "Stage 2" not in system1
    assert "Stage 3" not in system1


def test_run_staged_report_generation_merges_all_three_stages(monkeypatch):
    monkeypatch.setattr(
        report_stages,
        "build_national_region_evidence",
        lambda period, admin_level, use_cache: {
            "cross_indicator_findings": [],
            "priority_area_justifications": [
                {"justification_id": "Afar::drought", "area": "Afar", "rank": 1, "priority_score": 0.9},
            ],
        },
    )
    monkeypatch.setattr(
        report_stages,
        "build_community_evidence_by_region",
        lambda region_names: {
            "Afar": {"total_reports": 2, "feedback_signal": "limited_ground_signal", "by_severity": {"moderate": 2}, "by_type": {"water_shortage": 2}, "recent_reports": []},
        } if "Afar" in region_names else {},
    )
    monkeypatch.setattr(report_stages, "get_all_image_urls", lambda request: [])

    def fake_call(request, system_prompt, user_prompt, images, schema, model_tier="lite"):
        if schema is STAGE1_SCHEMA:
            return {
                "layer_by_layer_summary": ["l1"],
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
            return {
                "farmer_advisory": {"immediate": ["f1"], "near_term": [], "preparedness": []},
                "agro_pastoral_advisory": {"immediate": [], "near_term": ["a1"], "preparedness": []},
                "humanitarian_priorities": {"monitoring": ["h1"], "preparedness": [], "pre_positioning": [], "immediate_action": []},
                "sms_summary": "sms",
                "_metadata": {"provider": "gemini", "model": "m"},
            }
        raise AssertionError("unexpected schema")

    monkeypatch.setattr(report_stages, "call_configured_ai_provider_for_stage", fake_call)

    report = report_stages.run_staged_report_generation(_request(), [])

    assert report["layer_by_layer_summary"] == ["l1"]
    assert report["executive_summary"] == "exec"
    assert report["agro_pastoral_advisory"] == {"immediate": [], "near_term": ["a1"], "preparedness": []}
    assert report["humanitarian_priorities"]["monitoring"] == ["h1"]
    assert report["sms_summary"] == "sms"
    assert report["_metadata"]["ai_engine"] == "staged_workflow"
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
    monkeypatch.setattr(report_stages, "get_all_image_urls", lambda request: [])

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
        },
    )
    monkeypatch.setattr(report_stages, "build_community_evidence_by_region", lambda region_names: {})
    monkeypatch.setattr(report_stages, "get_all_image_urls", lambda request: [])

    def fake_call(request, system_prompt, user_prompt, images, schema, model_tier="lite"):
        if schema is STAGE1_SCHEMA:
            return {
                "layer_by_layer_summary": ["real-l1"],
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

    assert report["layer_by_layer_summary"] == ["real-l1"]
    assert report["farmer_advisory"] == {"immediate": ["real-f1"], "near_term": [], "preparedness": []}
    # Stage 2 failed -> deterministic fallback fields, not empty/missing.
    assert report["executive_summary"]
    assert report["_metadata"]["stages"]["stage2"]["ai_engine"] == "rule_based_fallback"
    assert report["_metadata"]["stages"]["stage1"]["provider"] == "gemini"

    # Even on Stage 2 failure, the real deterministic priority-area numbers
    # survive (merged with the fallback's own generic-but-grounded narrative)
    # -- never dropped just because the LLM call failed.
    justification = report["priority_area_justification"][0]
    assert justification["justification_id"] == "Afar::drought"
    assert justification["priority_score"] == 0.9
    assert justification["differentiator"]
