from app.api.seasonal_catalog_shared import infer_init_date


def test_infer_init_date_extracts_real_date_token():
    assert infer_init_date("ethiopia_June_2026-05-01_cdd_anomaly") == "2026-05-01"


def test_infer_init_date_extracts_date_regardless_of_position():
    assert infer_init_date("2026-05-01_ethiopia_rainfall_total_forecast") == "2026-05-01"


def test_infer_init_date_returns_empty_string_when_absent():
    assert infer_init_date("ethiopia_rainfall_total_forecast") == ""
