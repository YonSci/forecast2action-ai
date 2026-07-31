from unittest.mock import patch

from app.api.community_reports_store import canonical_report_type, summarize_reports
from app.context.community_context import build_community_evidence_by_region


def test_legacy_pasture_poor_aliases_to_pasture_stress():
    assert canonical_report_type("pasture_poor") == "pasture_stress"


def test_legacy_flooded_road_aliases_to_flooding():
    assert canonical_report_type("flooded_road") == "flooding"


def test_already_canonical_value_passes_through():
    assert canonical_report_type("water_shortage") == "water_shortage"


def test_summarize_reports_counts_high_and_severe_together():
    fake_reports = [
        {"district": "Test District", "severity": "high", "report_type": "water_shortage"},
        {"district": "Test District", "severity": "severe", "report_type": "crop_wilting"},
        {"district": "Test District", "severity": "severe", "report_type": "livestock_stress"},
    ]
    with patch("app.api.community_reports_store.load_reports", return_value=fake_reports):
        summary = summarize_reports(district="Test District")

    assert summary["total_reports"] == 3
    assert summary["feedback_signal"] == "strong_ground_signal"  # 1 high + 2 severe >= 3


def test_summarize_reports_emerging_signal_for_three_low_severity_reports():
    fake_reports = [
        {"district": "Test District", "severity": "low", "report_type": "water_shortage"}
        for _ in range(3)
    ]
    with patch("app.api.community_reports_store.load_reports", return_value=fake_reports):
        summary = summarize_reports(district="Test District")

    assert summary["feedback_signal"] == "emerging_ground_signal"


def test_summarize_reports_no_signal_for_empty_reports():
    with patch("app.api.community_reports_store.load_reports", return_value=[]):
        summary = summarize_reports(district="Nonexistent District")

    assert summary["feedback_signal"] == "no_ground_signal"
    assert summary["total_reports"] == 0


def test_build_community_evidence_by_region_matches_by_region_field():
    fake_reports = [
        {"region": "Afar", "district": "Zone 1", "severity": "severe", "report_type": "pasture_stress", "created_at": "2026-01-01"},
        {"region": "Afar", "district": "Zone 2", "severity": "moderate", "report_type": "water_shortage", "created_at": "2026-01-02"},
        {"region": "Somali", "district": "Somali", "severity": "low", "report_type": "livestock_stress", "created_at": "2026-01-01"},
    ]
    with patch("app.context.community_context.load_reports", return_value=fake_reports):
        evidence = build_community_evidence_by_region(["Afar", "Oromia"])

    # Only regions actually passed in are returned -- Somali (not requested)
    # and Oromia (requested but zero matching reports) are both absent.
    assert set(evidence.keys()) == {"Afar"}
    assert evidence["Afar"]["total_reports"] == 2
    assert evidence["Afar"]["by_severity"] == {"severe": 1, "moderate": 1}
    assert evidence["Afar"]["by_type"] == {"pasture_stress": 1, "water_shortage": 1}
    assert len(evidence["Afar"]["recent_reports"]) == 2


def test_build_community_evidence_by_region_falls_back_to_district_when_region_missing():
    fake_reports = [
        {"region": "", "district": "Afar", "severity": "high", "report_type": "flooding", "created_at": "2026-01-01"},
    ]
    with patch("app.context.community_context.load_reports", return_value=fake_reports):
        evidence = build_community_evidence_by_region(["Afar"])

    assert evidence["Afar"]["total_reports"] == 1


def test_build_community_evidence_by_region_strong_signal_threshold():
    fake_reports = [
        {"region": "Afar", "severity": "severe", "report_type": "flooding", "created_at": "2026-01-01"}
        for _ in range(3)
    ]
    with patch("app.context.community_context.load_reports", return_value=fake_reports):
        evidence = build_community_evidence_by_region(["Afar"])

    assert evidence["Afar"]["feedback_signal"] == "strong_ground_signal"


def test_build_community_evidence_by_region_empty_region_list_returns_empty_dict():
    with patch("app.context.community_context.load_reports", return_value=[{"region": "Afar"}]):
        evidence = build_community_evidence_by_region([])

    assert evidence == {}


def test_summarize_reports_two_verified_high_severity_reports_reach_strong_signal():
    # 2 verified high/severe reports (weight 2 each = 4) clears the >=3
    # weighted threshold even though only 2 reports total exist -- 2
    # unverified reports would NOT (2 < 3), confirming verification status
    # actually changes the classification.
    fake_reports = [
        {"district": "Test District", "severity": "high", "report_type": "water_shortage", "verification_status": "verified"},
        {"district": "Test District", "severity": "severe", "report_type": "crop_wilting", "verification_status": "verified"},
    ]
    with patch("app.api.community_reports_store.load_reports", return_value=fake_reports):
        summary = summarize_reports(district="Test District")

    assert summary["feedback_signal"] == "strong_ground_signal"
    assert summary["verified_count"] == 2


def test_summarize_reports_two_unverified_high_severity_reports_stay_limited():
    # Same 2 reports as the verified test above, unverified -- weighted
    # count is 2 (< 3), and total report count is also 2 (< 3), so this
    # stays at "limited" rather than reaching "strong" like the verified
    # version does.
    fake_reports = [
        {"district": "Test District", "severity": "high", "report_type": "water_shortage"},
        {"district": "Test District", "severity": "severe", "report_type": "crop_wilting"},
    ]
    with patch("app.api.community_reports_store.load_reports", return_value=fake_reports):
        summary = summarize_reports(district="Test District")

    assert summary["feedback_signal"] == "limited_ground_signal"
    assert summary["verified_count"] == 0


def test_build_community_evidence_by_region_verified_reports_reach_strong_signal_sooner():
    fake_reports = [
        {"region": "Afar", "severity": "high", "report_type": "flooding", "verification_status": "verified", "created_at": "2026-01-01"},
        {"region": "Afar", "severity": "severe", "report_type": "flooding", "verification_status": "verified", "created_at": "2026-01-02"},
    ]
    with patch("app.context.community_context.load_reports", return_value=fake_reports):
        evidence = build_community_evidence_by_region(["Afar"])

    assert evidence["Afar"]["feedback_signal"] == "strong_ground_signal"
    assert evidence["Afar"]["verified_count"] == 2
