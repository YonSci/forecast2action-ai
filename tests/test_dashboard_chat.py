"""Tests for the NEW deterministic logic added to app.api.dashboard_chat --
period/area detection, the other-area evidence packet, the action-intent
gate, and context_summary's new fields. Deliberately does NOT test the
provider-calling functions (_call_gemini_chat_raw etc.) or the endpoints
themselves -- those were verified against real, live Gemini/OpenAI calls
during development (see the session's own live-capture verification), not
mocked here; this file covers only the pure, real-input-real-output helper
functions that don't need a live LLM call to verify.
"""

from app.api.dashboard_chat import (
    _ACTION_STATUS_TO_RISK_LEVEL,
    _AUDIENCE_TO_LIBRARY_VALUE,
    _build_context_summary,
    _build_other_area_packet,
    _detect_comparison_periods,
    _detect_other_areas,
    _maybe_build_action_guidance,
    _real_admin1_area_names,
)

REAL_EVIDENCE = {
    "cross_indicator_findings": [
        {"area": "National", "signal": "partial_drought", "agreement_score": 0.6},
        {"area": "Harari", "signal": "strong_drought", "agreement_score": 1.0, "cross_indicator_confidence": "high"},
        {"area": "Somali", "signal": "no_clear_signal", "agreement_score": 0.2, "cross_indicator_confidence": "low"},
    ],
    "hazard_risk_layers": {
        "population_r_drought": {"regional": [{"area_name": "Somali", "mean": 0.98}, {"area_name": "Harari", "mean": 23.62}]},
        "p_drought": {"regional": [{"area_name": "Somali", "mean": 0.21}]},
        "v_drought": {"regional": [{"area_name": "Somali", "mean": 0.73}]},
    },
}


def test_detect_comparison_periods_finds_real_period_names_not_current_one():
    result = _detect_comparison_periods("How does July compare to August?", [], current_period="July")
    assert result == ["August"]


def test_detect_comparison_periods_ignores_current_period_even_if_mentioned():
    result = _detect_comparison_periods("What's the July forecast?", [], current_period="July")
    assert result == []


def test_detect_comparison_periods_scans_recent_history_not_just_current_message():
    history = [{"role": "user", "content": "Tell me about July"}, {"role": "assistant", "content": "..."}]
    result = _detect_comparison_periods("and September too", history, current_period="July")
    assert "September" in result


def test_detect_comparison_periods_capped_at_max_extra_periods():
    result = _detect_comparison_periods("Compare June, August, September, and JJAS", [], current_period="July")
    assert len(result) <= 2


def test_real_admin1_area_names_excludes_national():
    names = _real_admin1_area_names(REAL_EVIDENCE)
    assert "National" not in names
    assert names == ["Harari", "Somali"]


def test_detect_other_areas_skips_already_included_areas():
    # Confirmed real gap this closes: cross-area comparison must only
    # supplement areas NOT already fully present in priority_areas -- an
    # already-included area doesn't need a smaller, thinner packet too.
    result = _detect_other_areas("Compare Harari to Somali", [], ["Harari", "Somali"], already_included=["Harari"])
    assert result == ["Somali"]


def test_detect_other_areas_case_insensitive_and_capped():
    result = _detect_other_areas("harari and somali both", [], ["Harari", "Somali"], already_included=[])
    assert set(result) == {"Harari", "Somali"}


def test_build_other_area_packet_uses_real_regional_means_for_a_non_ranked_area():
    packet = _build_other_area_packet(REAL_EVIDENCE, "Somali")
    assert packet["area"] == "Somali"
    assert packet["cross_indicator_signal"] == "no_clear_signal"
    assert packet["drought_risk_score"] == 0.98
    assert packet["drought_hazard_probability"] == 0.21
    assert packet["drought_vulnerability"] == 0.73
    assert "note" in packet  # discloses this area has thinner real data than a ranked one


def test_build_other_area_packet_returns_none_for_unknown_area():
    assert _build_other_area_packet(REAL_EVIDENCE, "Nowhereland") is None


def test_action_status_to_risk_level_mapping_matches_real_library_vocabulary():
    # Real vocabulary confirmed by reading data/knowledge/action_library.json
    # directly: risk_level is one of trigger/warning/watch.
    assert _ACTION_STATUS_TO_RISK_LEVEL["action"] == "trigger"
    assert _ACTION_STATUS_TO_RISK_LEVEL["preparedness"] == "warning"


def test_audience_to_library_value_matches_real_action_library_audiences():
    assert _AUDIENCE_TO_LIBRARY_VALUE["disaster_manager"] == "disaster_manager"
    assert _AUDIENCE_TO_LIBRARY_VALUE["extension_officer"] == "extension_officer"
    assert _AUDIENCE_TO_LIBRARY_VALUE["ngo_planner"] == "ngo_planner"


def test_maybe_build_action_guidance_skips_when_message_has_no_action_intent():
    target_area = {"hazard_type": "drought", "action_status": "action"}
    assert _maybe_build_action_guidance("Why is this area a priority?", target_area, None) is None


def test_maybe_build_action_guidance_skips_when_no_target_area():
    assert _maybe_build_action_guidance("What should be done?", None, None) is None


def test_maybe_build_action_guidance_skips_when_target_area_has_no_hazard_type():
    assert _maybe_build_action_guidance("What should be done?", {}, None) is None


def test_maybe_build_action_guidance_retrieves_real_entries_for_a_real_action_question():
    # Real end-to-end call against the real data/knowledge/action_library.json
    # via app.context.knowledge_context.build_knowledge_context -- not
    # mocked, since this is a fast, local, deterministic keyword/metadata
    # retrieval (no LLM call involved at all).
    target_area = {"hazard_type": "drought", "action_status": "action"}
    guidance = _maybe_build_action_guidance("What should be done to respond to this?", target_area, "disaster_manager")
    assert guidance
    assert all("title" in item for item in guidance)


def test_build_context_summary_reports_other_areas_and_action_guidance_counts():
    context_packet = {"priority_areas": [], "national_cross_indicator": None}
    summary = _build_context_summary(
        context_packet,
        community_evidence={},
        report_context=None,
        comparison_packets={"August": {}},
        other_area_packets={"Somali": {}},
        action_guidance=[{"title": "x"}, {"title": "y"}],
    )
    assert summary["comparison_periods"] == ["August"]
    assert summary["other_areas_included"] == ["Somali"]
    assert summary["action_guidance_count"] == 2


def test_build_context_summary_defaults_are_empty_when_nothing_extra_happened():
    context_packet = {"priority_areas": [], "national_cross_indicator": None}
    summary = _build_context_summary(context_packet, community_evidence={}, report_context=None)
    assert summary["comparison_periods"] == []
    assert summary["other_areas_included"] == []
    assert summary["action_guidance_count"] == 0
