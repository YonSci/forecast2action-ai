from unittest.mock import patch

from app.api.community_reports_store import canonical_report_type, summarize_reports


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
