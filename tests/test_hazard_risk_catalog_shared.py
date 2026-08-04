from app.api.hazard_risk_catalog_shared import RISK_CLASS_BANDS, classify_risk_score


def test_classify_risk_score_matches_each_real_band():
    # One value from the middle of every real RISK_CLASS_BANDS range --
    # confirms the classifier agrees with the same bands the LLM prompts
    # are told to classify with (see _risk_definition_block in
    # app.api.report_stages), not a separately-drifted copy.
    assert classify_risk_score(10.0) == "Very low"
    assert classify_risk_score(30.0) == "Low"
    assert classify_risk_score(50.0) == "Moderate"
    assert classify_risk_score(70.0) == "High"
    assert classify_risk_score(90.0) == "Very high"


def test_classify_risk_score_handles_band_edges():
    for band in RISK_CLASS_BANDS:
        low, high = band["range"]
        assert classify_risk_score(low) == band["label"]
        assert classify_risk_score(high) == band["label"]


def test_classify_risk_score_returns_none_for_missing_score():
    # None ("no data") must not be silently classified as "Very low" --
    # those are not the same thing.
    assert classify_risk_score(None) is None
