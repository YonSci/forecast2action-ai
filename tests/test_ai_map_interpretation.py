from app.api import ai_map_interpretation as aim
from app.api.ai_map_interpretation import AIMapInterpretationRequest, fallback_report, validate_stage_shape


def _request():
    return AIMapInterpretationRequest()


def test_retrieve_guidance_penalizes_non_actionable_hazard_when_evidence_given(monkeypatch):
    # Confirmed real bug, fixed: the query used to be built entirely from
    # dashboard UI state, not the real national signal -- flood/wet-hazard
    # guidance could be retrieved and reach Stage 3 even when the real
    # national wet signal was completely insignificant (every wet-ranked
    # area not_actionable). Real action_status (see build_priority_area_
    # justifications) must now penalize an off-topic document.
    monkeypatch.setattr(
        aim,
        "read_knowledge_base_documents",
        lambda: [
            {"title": "Flood Early Action", "path": "flood.md", "text": "Guidance for flood and wet hazard response, water levels."},
            {"title": "Drought Early Action", "path": "drought.md", "text": "Guidance for drought response, water conservation."},
        ],
    )
    evidence = {
        "priority_area_justifications": [
            {"hazard_type": "drought", "action_status": "action"},
            {"hazard_type": "wet", "action_status": "not_actionable"},
        ],
    }

    results = aim.retrieve_guidance(_request(), evidence=evidence, limit=5)
    titles = [item["title"] for item in results]

    assert "Drought Early Action" in titles
    assert "Flood Early Action" not in titles


def test_retrieve_guidance_without_evidence_keeps_old_behavior(monkeypatch):
    # Backward compatible: no evidence given (e.g. a caller that hasn't
    # been updated yet) -- no actionability penalty applied at all.
    monkeypatch.setattr(
        aim,
        "read_knowledge_base_documents",
        lambda: [{"title": "Flood Early Action", "path": "flood.md", "text": "Guidance for flood and wet hazard response."}],
    )

    results = aim.retrieve_guidance(_request(), limit=5)

    assert len(results) == 1


def test_validate_stage_shape_coerces_object_returned_for_a_string_field():
    # Real, confirmed live bug: Stage 2's prompt asks executive_summary to
    # "explicitly mention the forecast window, lead/horizon, report scope,
    # valid period, and output language" -- a real Gemini response
    # structured those as separate JSON keys instead of one flowing
    # string. executive_summary is declared type: "string", but the old
    # coercion only handled key-missing/None, never present-but-wrong-type,
    # so the raw object reached the frontend and crashed React ("Objects
    # are not valid as a React child (found: object with keys
    # {forecast_window, lead_horizon, report_scope, valid_period,
    # output_language, summary})").
    schema = {"properties": {"executive_summary": {"type": "string"}}}
    malformed = {
        "executive_summary": {
            "forecast_window": "Seasonal",
            "lead_horizon": "Month 2",
            "report_scope": "National (Ethiopia)",
            "valid_period": "July 2026",
            "output_language": "English",
            "summary": "Drought risk remains elevated across southern lowlands this period.",
        },
    }

    result = validate_stage_shape(malformed, schema)

    assert isinstance(result["executive_summary"], str)
    assert result["executive_summary"] == "Drought risk remains elevated across southern lowlands this period."


def test_validate_stage_shape_coerces_object_without_a_summary_key_for_a_string_field():
    # No "summary"/"description"/"text"/"value"/"label" sub-key present --
    # must still degrade to a real, readable string, never a raw object.
    schema = {"properties": {"executive_summary": {"type": "string"}}}
    malformed = {"executive_summary": {"forecast_window": "Seasonal", "lead_horizon": "Month 2"}}

    result = validate_stage_shape(malformed, schema)

    assert isinstance(result["executive_summary"], str)
    assert "Seasonal" in result["executive_summary"]
    assert "Month 2" in result["executive_summary"]


def test_fallback_report_layer_and_indicator_summaries_are_structured_objects_from_real_evidence():
    # Phase 3 #17 -- fallback_report used to build these 2 fields from
    # request.all_map_layer_summaries/all_climate_indicator_summaries (an
    # older, separate data source) as flat "Label: text" strings. It now
    # uses the SAME real `evidence` Stage 1's real LLM call receives, in
    # the same structured-object shape STAGE1_SCHEMA now requires, so the
    # deterministic fallback is never shape- or data-source-inconsistent
    # with a real report.
    evidence = {
        "hazard_risk_layers": {
            "h_dry_mean": {
                "layer_label": "Drought Hazard (mean)",
                "national": {"mean": 0.482},
                "regional": [
                    {"area_name": "South Ethiopia", "mean": 0.82},
                    {"area_name": "Addis Ababa", "mean": 0.1},
                ],
                "class_area_pct": {"very_low": 10.0, "low": 20.0, "moderate": 30.0, "high": 25.0, "very_high": 15.0},
            },
        },
        "categorical_layers": {},
        "climate_indicators": {
            "spi": {
                "national": {"mean": -1.6},
                "regional": [{"area_name": "Somali", "mean": -2.1}],
                "category": "severely_dry",
            },
        },
    }

    report = fallback_report(_request(), retrieved_guidance=[], evidence=evidence)

    assert isinstance(report["layer_by_layer_summary"], list)
    layer_item = report["layer_by_layer_summary"][0]
    assert isinstance(layer_item, dict)
    assert layer_item["layer"] == "h_dry_mean"
    assert layer_item["national_mean"] == 0.482
    assert "South Ethiopia" in layer_item["interpretation"]

    indicator_item = report["indicator_by_indicator_summary"][0]
    assert isinstance(indicator_item, dict)
    assert indicator_item["indicator"] == "spi"
    assert indicator_item["national_signal"] == "severely_dry"


def test_fallback_report_handles_missing_evidence_gracefully():
    report = fallback_report(_request(), retrieved_guidance=[], evidence=None)

    assert report["layer_by_layer_summary"] == []
    assert report["indicator_by_indicator_summary"] == []
    assert report["_metadata"]["ai_engine"] == "rule_based_fallback"


_EVIDENCE_WITH_ONE_ACTIONABLE_AREA = {
    "priority_area_justifications": [
        {
            "justification_id": "Afar::drought", "area": "Afar", "rank": 1, "hazard_type": "drought",
            "risk_score": 65.0, "risk_class": "High", "action_status": "action",
            "hazard_probability": 0.8, "confidence": "high", "supporting_indicators": [],
        },
    ],
}


def test_fallback_report_english_request_has_no_mismatch_note():
    # target_language defaults to "en" -- the fallback's real English content
    # matches what was requested, so no mismatch disclosure is needed.
    report = fallback_report(_request(), retrieved_guidance=[], evidence=_EVIDENCE_WITH_ONE_ACTIONABLE_AREA)

    assert report["_metadata"]["content_language_code"] == "en"
    assert report["_metadata"]["target_language_code"] == "en"
    assert "shown in English" not in report["executive_summary"]
    assert len(report["sms_messages"]) == 1
    assert "[EN fallback" not in report["sms_messages"][0]["message"]
    assert not any("shown in English" in note for note in report["data_quality_notes"])


def test_fallback_report_non_english_request_discloses_it_is_actually_english():
    # This function never translates -- it used to silently stamp
    # "target_language": "Amharic" on hardcoded English sentences, which
    # falsely implied the request had been honored. It must now say plainly,
    # in every user-facing field, that the content is English.
    request = _request()
    request.target_language = "am"

    report = fallback_report(request, retrieved_guidance=[], evidence=_EVIDENCE_WITH_ONE_ACTIONABLE_AREA)

    assert report["_metadata"]["target_language_code"] == "am"
    assert report["_metadata"]["content_language_code"] == "en"
    assert "shown in English, not Amharic" in report["executive_summary"]
    assert any("shown in English, not Amharic" in note for note in report["data_quality_notes"])
    assert report["sms_messages"][0]["message"].startswith("[EN fallback] ")
