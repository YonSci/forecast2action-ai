import numpy as np
from affine import Affine

from app.context.statistical_evidence import (
    _indicator_evidence_objects,
    area_weighted_statistics,
    build_cross_indicator_findings,
    build_priority_area_justifications,
    build_structured_indicator_summaries,
    build_structured_layer_summaries,
    class_area_percentages,
    classify_by_quintiles,
    classify_by_risk_bands,
    spi_category,
    weighted_exposure_by_region,
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


def test_area_weighted_statistics_weights_by_real_pixel_area():
    # A north-up transform where pixel area shrinks toward higher latitude
    # (transform.f = north edge, pixel size 1 degree) -- top row (higher
    # latitude, smaller real area) is all 100s, bottom row (lower latitude,
    # larger real area) is all 0s. An UNWEIGHTED mean would be exactly 50;
    # the area-weighted mean must be pulled toward the bottom row's larger
    # real-world footprint, i.e. below 50.
    arr = np.array([[100.0, 100.0], [0.0, 0.0]])
    transform = Affine(1.0, 0.0, 33.0, 0.0, -1.0, 15.0)

    result = area_weighted_statistics(arr, transform)

    assert result["valid_count"] == 4
    assert result["mean"] < 50.0
    assert result["weighting"] == "area_km2"


def test_classify_by_quintiles_produces_five_classes():
    reference = np.linspace(0, 100, 100)
    arr = np.array([5.0, 25.0, 50.0, 75.0, 95.0])

    class_arr, breakpoints = classify_by_quintiles(arr, reference)

    assert len(breakpoints) == 4
    assert sorted(set(class_arr.tolist())) == [0, 1, 2, 3, 4]


def test_classify_by_risk_bands_matches_real_upstream_scheme():
    arr = np.array([10.0, 30.0, 50.0, 70.0, 90.0])

    class_arr = classify_by_risk_bands(arr)

    assert class_arr.tolist() == [0, 1, 2, 3, 4]


def test_class_area_percentages_sums_to_100():
    class_arr = np.array([[0, 1], [2, 4]])
    transform = Affine(1.0, 0.0, 33.0, 0.0, -1.0, 15.0)

    percentages = class_area_percentages(class_arr, transform)

    assert abs(sum(percentages.values()) - 100.0) < 0.01
    assert percentages["moderate"] > 0
    assert percentages["high"] == 0.0


def test_spi_category_boundaries():
    assert spi_category(2.5) == "extremely_wet"
    assert spi_category(0.0) == "near_normal"
    assert spi_category(-2.5) == "extremely_dry"
    assert spi_category(-1.2) == "moderately_dry"


def _evidence_with_region(rainfall_anomaly, rainfall_percentile, spi, cdd_anomaly, cwd_anomaly,
                           rx1day_anomaly, rx5day_anomaly, drought_probability, wet_probability, area_name="Region A"):
    def regional(mean):
        return [{"area_name": area_name, "mean": mean}]

    return {
        "climate_indicators": {
            "rainfall_total": {"departure": {"national_anomaly": {"mean": rainfall_anomaly}, "regional_anomaly": regional(rainfall_anomaly)}},
            "rainfall_percentile": {"national": {"mean": rainfall_percentile}, "regional": regional(rainfall_percentile)},
            "spi": {"national": {"mean": spi}, "regional": regional(spi)},
            "cdd": {"departure": {"national_anomaly": {"mean": cdd_anomaly}, "regional_anomaly": regional(cdd_anomaly)}},
            "cwd": {"departure": {"national_anomaly": {"mean": cwd_anomaly}, "regional_anomaly": regional(cwd_anomaly)}},
            "rx1day": {"departure": {"national_anomaly": {"mean": rx1day_anomaly}, "regional_anomaly": regional(rx1day_anomaly)}},
            "rx5day": {"departure": {"national_anomaly": {"mean": rx5day_anomaly}, "regional_anomaly": regional(rx5day_anomaly)}},
        },
        "hazard_risk_layers": {
            "p_drought": {"national": {"mean": drought_probability}, "regional": regional(drought_probability)},
            "p_wet": {"national": {"mean": wet_probability}, "regional": regional(wet_probability)},
        },
    }


def test_cross_indicator_findings_strong_drought_signal(monkeypatch):
    monkeypatch.setattr("app.context.statistical_evidence.default_threshold_for", lambda layer_value, period: 0.5)
    evidence = _evidence_with_region(
        rainfall_anomaly=-50.0, rainfall_percentile=10.0, spi=-1.5, cdd_anomaly=5.0, cwd_anomaly=-2.0,
        rx1day_anomaly=-3.0, rx5day_anomaly=-3.0, drought_probability=0.8, wet_probability=0.1,
    )

    findings = build_cross_indicator_findings(evidence, "july")
    by_area = {item["area"]: item for item in findings}

    assert by_area["National"]["signal"] == "strong_drought"
    assert by_area["National"]["agreement_score"] == 1.0
    assert by_area["National"]["confidence"] == "high"
    assert by_area["Region A"]["signal"] == "strong_drought"
    supporting = by_area["Region A"]["supporting_indicators"]
    supporting_names = {item["indicator"] for item in supporting}
    assert supporting_names == {
        "rainfall_anomaly", "rainfall_percentile", "spi", "cdd_anomaly", "drought_probability",
    }
    assert by_area["Region A"]["contradicting_indicators"] == []

    # Real values, not just names -- e.g. rainfall_anomaly=-50.0% and
    # drought_probability=0.8 (a real 0-1 fraction) reported as 80.0%.
    by_indicator = {item["indicator"]: item for item in supporting}
    assert by_indicator["rainfall_anomaly"] == {"indicator": "rainfall_anomaly", "value": -50.0, "units": "%"}
    assert by_indicator["drought_probability"] == {"indicator": "drought_probability", "value": 80.0, "units": "%"}
    assert by_indicator["cdd_anomaly"] == {"indicator": "cdd_anomaly", "value": 5.0, "units": "days"}


def test_cross_indicator_findings_strong_wet_signal(monkeypatch):
    monkeypatch.setattr("app.context.statistical_evidence.default_threshold_for", lambda layer_value, period: 0.5)
    evidence = _evidence_with_region(
        rainfall_anomaly=50.0, rainfall_percentile=90.0, spi=1.5, cdd_anomaly=-5.0, cwd_anomaly=3.0,
        rx1day_anomaly=4.0, rx5day_anomaly=4.0, drought_probability=0.1, wet_probability=0.8,
    )

    findings = build_cross_indicator_findings(evidence, "july")
    by_area = {item["area"]: item for item in findings}

    assert by_area["Region A"]["signal"] == "strong_wet"
    assert by_area["Region A"]["confidence"] == "high"


def test_indicator_evidence_objects_rx_anomaly_picks_larger_real_magnitude():
    # rx_anomaly has no single real value of its own -- it's met if either
    # rx1day or rx5day anomaly is positive -- so the reported value must be
    # whichever real component has the larger magnitude, never fabricated.
    values = {"rx1day_anomaly": 2.0, "rx5day_anomaly": -6.0}
    objects = _indicator_evidence_objects(["rx_anomaly"], values)
    assert objects == [{"indicator": "rx_anomaly", "value": -6.0, "units": "mm"}]

    assert _indicator_evidence_objects(["rx_anomaly"], {}) == [{"indicator": "rx_anomaly", "value": None, "units": "mm"}]


def test_cross_indicator_findings_mixed_signal_reports_contradictions(monkeypatch):
    monkeypatch.setattr("app.context.statistical_evidence.default_threshold_for", lambda layer_value, period: 0.5)
    # SPI says dry, but CWD/rainfall percentile say wet -- genuine disagreement.
    evidence = _evidence_with_region(
        rainfall_anomaly=20.0, rainfall_percentile=85.0, spi=-1.2, cdd_anomaly=1.0, cwd_anomaly=4.0,
        rx1day_anomaly=-1.0, rx5day_anomaly=-1.0, drought_probability=0.2, wet_probability=0.2,
    )

    findings = build_cross_indicator_findings(evidence, "july")
    by_area = {item["area"]: item for item in findings}

    assert by_area["Region A"]["signal"] == "mixed"
    assert by_area["Region A"]["contradicting_indicators"]


def test_build_priority_area_justifications_extracts_real_fields_and_ranks_by_priority_score():
    evidence = {
        "priority_scores": {
            # Deliberately NOT sorted by priority_score, to confirm the
            # function re-sorts by priority_score itself rather than
            # trusting incoming list order.
            "population_r_drought": [
                {"area_name": "Region A", "priority_score": 0.4},
                {"area_name": "Region B", "priority_score": 0.9},
            ],
            "population_r_wet": [],
        },
        "hazard_risk_layers": {
            "p_drought": {"regional": [{"area_name": "Region A", "mean": 0.3}, {"area_name": "Region B", "mean": 0.8}]},
            "population_r_drought": {"regional": [{"area_name": "Region A", "mean": 20.0}, {"area_name": "Region B", "mean": 55.0}]},
            "v_drought": {"regional": [{"area_name": "Region A", "mean": 0.5}, {"area_name": "Region B", "mean": 0.7}]},
        },
        "exposure": {
            "population_r_drought": {
                "population_exposed_by_region": [
                    {"area_name": "Region B", "exposed": 12345.0, "exposed_pct": 62.3},
                ],
                "roads_exposed_by_region": [
                    {"area_name": "Region B", "exposed": 42.0, "exposed_pct": 18.5},
                ],
                "healthsites_exposed_by_region": [
                    {"area_name": "Region B", "exposed": 3.0, "exposed_pct": 40.0},
                ],
            },
        },
        "cross_indicator_findings": [
            {"area": "Region B", "signal": "strong_drought", "supporting_indicators": ["spi", "cdd_anomaly"], "contradicting_indicators": [], "confidence": "high"},
        ],
    }

    justifications = build_priority_area_justifications(evidence, top_n=5)
    by_area = {item["area"]: item for item in justifications}

    assert list(by_area.keys()) == ["Region B", "Region A"]  # sorted by priority_score desc, not list order
    top = by_area["Region B"]
    assert top["rank"] == 1
    assert top["hazard_type"] == "drought"
    assert top["justification_id"] == "Region B::drought"
    assert top["priority_score"] == 0.9
    assert top["risk_score"] == 55.0
    assert top["risk_class"] == "Moderate"  # real RISK_CLASS_BANDS classification of 55.0
    assert top["hazard_probability"] == 0.8
    assert top["vulnerability"] == 0.7
    assert top["population_exposed_pct"] == 62.3
    assert top["roads_exposed_pct"] == 18.5
    assert top["healthsites_exposed_pct"] == 40.0
    assert top["supporting_indicators"] == ["spi", "cdd_anomaly"]
    assert top["confidence"] == "high"

    # Region A has no cross_indicator_findings entry and no exposure entry --
    # must degrade to None/[] gracefully, not crash or fabricate a value.
    second = by_area["Region A"]
    assert second["rank"] == 2
    assert second["risk_score"] == 20.0
    assert second["risk_class"] == "Low"  # real RISK_CLASS_BANDS classification of 20.0 (lower band edge)
    assert second["population_exposed_pct"] is None
    assert second["roads_exposed_pct"] is None
    assert second["healthsites_exposed_pct"] is None
    assert second["supporting_indicators"] == []
    assert second["confidence"] is None


def test_build_priority_area_justifications_respects_top_n():
    evidence = {
        "priority_scores": {
            "population_r_drought": [{"area_name": f"Region {i}", "priority_score": float(i)} for i in range(10)],
            "population_r_wet": [],
        },
        "hazard_risk_layers": {},
        "exposure": {},
        "cross_indicator_findings": [],
    }

    justifications = build_priority_area_justifications(evidence, top_n=3)

    assert len(justifications) == 3
    assert [item["rank"] for item in justifications] == [1, 2, 3]
    assert justifications[0]["area"] == "Region 9"  # highest priority_score


def test_weighted_exposure_by_region_matches_hand_computed_sum(monkeypatch):
    monkeypatch.setattr(
        "app.context.statistical_evidence.load_admin_features",
        lambda admin_level: (REGION_A, REGION_B),
    )

    # REGION_A spans rows 0-1 (y 0-2), REGION_B spans rows 2-3 (y 2-4), same
    # 4x4 grid + identity transform already verified in test_spatial_summary
    # .py. Source hazard array: Region A (top half) above threshold, Region
    # B (bottom half) below.
    source_arr = np.full((4, 4), 10.0)
    source_arr[2:4, :] = 1.0
    # Weight array (e.g. population) on the SAME grid for simplicity.
    weight_arr = np.full((4, 4), 5.0)
    weight_arr[2:4, :] = 3.0
    transform = Affine.identity()

    results = weighted_exposure_by_region(
        source_arr, transform, weight_arr, transform, admin_level="admin1", threshold=5.0,
    )

    by_name = {item["area_name"]: item for item in results}
    assert by_name["Region A"]["total"] == 40.0
    assert by_name["Region A"]["exposed"] == 40.0
    assert by_name["Region A"]["exposed_pct"] == 100.0
    assert by_name["Region B"]["exposed"] == 0.0


def test_build_structured_layer_summaries_continuous_layer():
    evidence = {
        "hazard_risk_layers": {
            "h_dry_mean": {
                "layer_label": "Drought Hazard (mean)",
                "national": {"mean": 0.482},
                "regional": [
                    {"area_name": "South Ethiopia", "mean": 0.82},
                    {"area_name": "Harari", "mean": 0.79},
                    {"area_name": "Somali", "mean": 0.55},
                    {"area_name": "Amhara", "mean": 0.4},
                    {"area_name": "Addis Ababa", "mean": 0.1},
                ],
                "class_area_pct": {"very_low": 10.0, "low": 20.0, "moderate": 30.0, "high": 25.0, "very_high": 15.0},
            },
        },
        "categorical_layers": {},
    }

    summaries = build_structured_layer_summaries(evidence)

    assert len(summaries) == 1
    item = summaries[0]
    assert item["layer"] == "h_dry_mean"
    assert item["national_mean"] == 0.482
    assert item["highest_areas"] == ["South Ethiopia", "Harari"]
    assert item["lowest_areas"] == ["Amhara", "Addis Ababa"]
    assert item["affected_area_pct"] == 40.0  # high + very_high
    assert item["national_signal"] == "moderate"  # dominant class by area %
    assert "South Ethiopia" in item["interpretation"]
    assert item["confidence"] == "moderate"


def test_build_structured_layer_summaries_categorical_layer():
    evidence = {
        "hazard_risk_layers": {},
        "categorical_layers": {
            "population_risk_class": {
                "layer_label": "Risk Class",
                "class_area_pct": {"very_low": 70.0, "low": 15.0, "moderate": 10.0, "high": 4.0, "very_high": 1.0},
            },
        },
    }

    summaries = build_structured_layer_summaries(evidence)

    assert len(summaries) == 1
    item = summaries[0]
    assert item["layer"] == "population_risk_class"
    assert item["national_signal"] == "very_low"
    assert item["national_mean"] is None
    assert item["highest_areas"] == []
    assert item["affected_area_pct"] == 5.0  # high + very_high
    assert "Very Low" in item["interpretation"]


def test_build_structured_indicator_summaries_uses_real_spi_category_not_quintiles():
    evidence = {
        "climate_indicators": {
            "spi": {
                "national": {"mean": -1.6},
                "regional": [
                    {"area_name": "Somali", "mean": -2.1},
                    {"area_name": "Afar", "mean": -1.8},
                    {"area_name": "Amhara", "mean": -0.5},
                    {"area_name": "Harari", "mean": 0.0},
                    {"area_name": "Addis Ababa", "mean": 0.15},
                ],
                "category": "severely_dry",
                # Deliberately no class_area_pct -- SPI never has one (see
                # INDICATORS_WITH_CLIMATOLOGY's docstring).
            },
        },
    }

    summaries = build_structured_indicator_summaries(evidence)

    assert len(summaries) == 1
    item = summaries[0]
    assert item["indicator"] == "spi"
    assert item["national_signal"] == "severely_dry"  # real McKee category, not a quintile label
    # highest_areas/lowest_areas stay direction-consistent with every other
    # indicator (highest = numerically largest) -- the driest (most
    # negative) real areas are in lowest_areas, not a flipped "driest_areas".
    assert item["highest_areas"] == ["Addis Ababa", "Harari"]
    assert item["lowest_areas"] == ["Afar", "Somali"]
    assert item["affected_area_pct"] is None
