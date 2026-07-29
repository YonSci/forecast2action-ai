"""Tests app.context.forecast_context.build_hazard_geo_impact_context against
a MOCKED compute_district_ranking (not real rasters) -- fast and
deterministic, independent of whether the real GeoTIFF/admin-boundary data
files are present in the test environment.
"""

from unittest.mock import patch

import pytest

from app.context.forecast_context import build_hazard_geo_impact_context
from app.context.validators import compute_quality_score

FAKE_RANKING_RESULT = {
    "rank_by": "population_r_drought",
    "period": "JJAS",
    "admin_level": "admin3",
    "selection_mode": "top",
    "threshold": 32.246,
    "count": 2,
    "ranking": [
        {
            "admin_level": "admin3",
            "area_name": "Fake Woreda A",
            "region": "Fake Region",
            "zone": "Fake Zone",
            "woreda": "Fake Woreda A",
            "region_id": "fake_region",
            "zone_id": "fake_region_fake_zone",
            "woreda_id": "fake_region_fake_zone_fake_woreda_a",
            "metrics": {"population_r_drought": 53.7, "cropland_total_normalized": 0.5},
            "rank_value": 53.7,
            "priority_score": 0.9,
            "population_total": 47508,
            "population_exposed": 47508,
            "population_exposed_pct": 100.0,
            "area_total_km2": 754.0,
            "area_extent_km2": 754.0,
            "area_extent_pct": 100.0,
            "cropland_extent_pct": 0.0,
            "rank": 1,
            "boundary_feature": None,
        },
        {
            "admin_level": "admin3",
            "area_name": "Fake Woreda B",
            "region": "Fake Region",
            "zone": "Fake Zone",
            "woreda": "Fake Woreda B",
            "region_id": "fake_region",
            "zone_id": "fake_region_fake_zone",
            "woreda_id": "fake_region_fake_zone_fake_woreda_b",
            "metrics": {"population_r_drought": 30.0},
            "rank_value": 30.0,
            "priority_score": 0.4,
            "population_total": 1000,
            "population_exposed": 0,
            "population_exposed_pct": 0.0,
            "area_total_km2": 100.0,
            "area_extent_km2": 0.0,
            "area_extent_pct": 0.0,
            "cropland_extent_pct": 10.0,
            "rank": 2,
            "boundary_feature": None,
        },
    ],
}


@patch("app.context.forecast_context.compute_district_ranking", return_value=FAKE_RANKING_RESULT)
@patch("app.context.forecast_context._observed_ceiling", return_value=53.7)
def test_build_hazard_geo_impact_context_uses_top_ranked_item(mock_ceiling, mock_ranking):
    forecast, geography, hazard_evidence, impact = build_hazard_geo_impact_context(
        rank_by="population_r_drought", period="JJAS", admin_level="admin3", top_n=5,
    )

    assert geography.area_name == "Fake Woreda A"
    assert hazard_evidence.priority_score == 0.9
    assert hazard_evidence.rank_value == 53.7
    assert impact.population_exposed == 47508
    assert forecast.rank_by == "population_r_drought"


@patch("app.context.forecast_context.compute_district_ranking", return_value=FAKE_RANKING_RESULT)
@patch("app.context.forecast_context._observed_ceiling", return_value=53.7)
def test_build_hazard_geo_impact_context_selects_named_area(mock_ceiling, mock_ranking):
    _, geography, hazard_evidence, _ = build_hazard_geo_impact_context(
        rank_by="population_r_drought", period="JJAS", admin_level="admin3", top_n=5,
        target_area_name="Fake Woreda B",
    )

    assert geography.area_name == "Fake Woreda B"
    assert hazard_evidence.priority_score == 0.4


@patch("app.context.forecast_context.compute_district_ranking", return_value={**FAKE_RANKING_RESULT, "ranking": []})
def test_build_hazard_geo_impact_context_raises_on_empty_ranking(mock_ranking):
    with pytest.raises(ValueError):
        build_hazard_geo_impact_context(rank_by="population_r_drought", period="JJAS")


def test_build_hazard_geo_impact_context_rejects_unknown_layer():
    with pytest.raises(ValueError):
        build_hazard_geo_impact_context(rank_by="not_a_real_layer", period="JJAS")


def test_quality_score_full_envelope_scores_higher_than_empty(sample_envelope):
    score, flags = compute_quality_score(sample_envelope)
    assert 0.0 <= score <= 1.0
    assert "no_hazard_evidence" not in flags
    assert "no_community_reports" in flags  # sample_envelope has total_reports=0
