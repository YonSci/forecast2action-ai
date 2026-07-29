import numpy as np
from affine import Affine

import app.context.spatial_summary as spatial_summary
from app.context.spatial_summary import (
    CLIMATE_INDICATORS,
    HAZARD_RISK_LAYERS_FOR_REPORT,
    build_all_climate_indicator_summaries,
    build_all_layer_summaries,
    climate_indicator_region_breakdown,
)

REGION_A = {
    "type": "Feature",
    "properties": {"region": "Region A", "name": "Region A"},
    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]]},
}
REGION_B = {
    "type": "Feature",
    "properties": {"region": "Region B", "name": "Region B"},
    "geometry": {"type": "Polygon", "coordinates": [[[0, 2], [4, 2], [4, 4], [0, 4], [0, 2]]]},
}


def _make_array():
    arr = np.zeros((4, 4), dtype="float32")
    arr[0:2, :] = 10.0  # top half -- Region A
    arr[2:4, :] = 2.0  # bottom half -- Region B
    return arr


def test_climate_indicator_region_breakdown_ranks_by_mean(monkeypatch):
    monkeypatch.setattr(
        "app.api.hazard_risk_ranking.load_admin_features",
        lambda admin_level: (REGION_A, REGION_B),
    )

    arr = _make_array()
    result = climate_indicator_region_breakdown(arr, Affine.identity(), admin_level="admin1", top_n=2)

    assert result["top_areas"][0]["area_name"] == "Region A"
    assert result["top_areas"][0]["mean_value"] == 10.0
    assert result["bottom_areas"][0]["area_name"] == "Region B"
    assert result["bottom_areas"][0]["mean_value"] == 2.0


def test_climate_indicator_region_breakdown_no_features_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "app.api.hazard_risk_ranking.load_admin_features",
        lambda admin_level: tuple(),
    )

    result = climate_indicator_region_breakdown(_make_array(), Affine.identity())

    assert result == {"top_areas": [], "bottom_areas": []}


def test_hazard_risk_layers_for_report_has_exactly_the_requested_11():
    assert HAZARD_RISK_LAYERS_FOR_REPORT == [
        "h_dry_mean", "h_wet_mean",
        "p_drought", "p_wet",
        "population_normalized",
        "v_drought", "v_wet",
        "population_r_drought", "population_r_wet", "population_risk_class", "population_dominant_code",
    ]


def test_build_all_layer_summaries_covers_exactly_the_11_layers(monkeypatch):
    seen = []

    def fake_summarize(layer_value, period="JJAS", admin_level="admin1"):
        seen.append(layer_value)
        return {"layer_value": layer_value}

    monkeypatch.setattr(spatial_summary, "summarize_hazard_risk_layer", fake_summarize)

    summaries = build_all_layer_summaries("June")

    assert len(summaries) == 11
    assert seen == HAZARD_RISK_LAYERS_FOR_REPORT


def test_build_all_climate_indicator_summaries_covers_exactly_21_combos(monkeypatch):
    seen = []

    def fake_summarize(indicator, period="JJAS", product="forecast"):
        seen.append((indicator, product))
        return {"indicator": indicator, "product": product}

    monkeypatch.setattr(spatial_summary, "summarize_climate_indicator", fake_summarize)

    summaries = build_all_climate_indicator_summaries("June")

    assert len(summaries) == 21
    assert len(CLIMATE_INDICATORS) == 7
    spi_products = {product for indicator, product in seen if indicator == "spi"}
    assert spi_products == {"forecast", "drought_probability", "wet_probability"}
    non_spi_products = {product for indicator, product in seen if indicator != "spi"}
    assert non_spi_products == {"forecast", "climatology", "anomaly"}
