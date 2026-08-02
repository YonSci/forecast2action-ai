from app.decision.policy_engine import load_policy_for_hazard

THRESHOLDS = {"trigger": 0.80, "warning": 0.60, "watch": 0.35}


def test_load_policy_for_known_hazard():
    policy = load_policy_for_hazard("drought", "ethiopia")
    assert policy.policy_id == "drought_ethiopia_v1"
    assert policy.thresholds == THRESHOLDS


def test_load_policy_translates_catalog_wet_to_heavy_rainfall():
    policy = load_policy_for_hazard("wet", "ethiopia")
    assert policy.policy_id == "heavy_rainfall_ethiopia_v1"


def test_load_policy_falls_back_to_default_for_unknown_hazard():
    policy = load_policy_for_hazard("some_unknown_hazard", "ethiopia")
    assert policy.policy_id == "default_policy_v1"
