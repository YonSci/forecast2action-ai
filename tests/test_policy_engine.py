from app.decision.policy_engine import evaluate_trigger_status, load_policy_for_hazard

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


def test_evaluate_trigger_status_watch_boundary():
    assert evaluate_trigger_status(0.35, THRESHOLDS) == "watch"
    assert evaluate_trigger_status(0.349, THRESHOLDS) == "no_alert"


def test_evaluate_trigger_status_warning_boundary():
    assert evaluate_trigger_status(0.60, THRESHOLDS) == "warning"
    assert evaluate_trigger_status(0.599, THRESHOLDS) == "watch"


def test_evaluate_trigger_status_trigger_boundary():
    assert evaluate_trigger_status(0.80, THRESHOLDS) == "trigger"
    assert evaluate_trigger_status(0.799, THRESHOLDS) == "warning"


def test_evaluate_trigger_status_no_alert_below_watch():
    assert evaluate_trigger_status(0.0, THRESHOLDS) == "no_alert"
