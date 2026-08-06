import numpy as np
from affine import Affine

from app.context.statistical_evidence import (
    _action_status,
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
                           rx1day_anomaly, rx5day_anomaly, drought_probability, wet_probability,
                           area_name="Region A", rainfall_anomaly_pct=None):
    def regional(mean):
        return [{"area_name": area_name, "mean": mean}]

    return {
        "climate_indicators": {
            "rainfall_total": {
                "departure": {
                    "national_anomaly": {"mean": rainfall_anomaly},
                    "regional_anomaly": regional(rainfall_anomaly),
                    "national_pct_anomaly": {"mean": rainfall_anomaly_pct},
                    "regional_pct_anomaly": regional(rainfall_anomaly_pct),
                },
            },
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

    # Real values, not just names -- e.g. rainfall_anomaly=-50.0 mm (NOT
    # "%" -- confirmed real bug: this is an absolute mm anomaly, fixed) and
    # drought_probability=0.8 (a real 0-1 fraction) reported as 80.0%.
    by_indicator = {item["indicator"]: item for item in supporting}
    assert by_indicator["rainfall_anomaly"]["value"] == -50.0
    assert by_indicator["rainfall_anomaly"]["units"] == "mm"
    assert by_indicator["drought_probability"] == {"indicator": "drought_probability", "value": 80.0, "units": "%"}
    assert by_indicator["cdd_anomaly"] == {"indicator": "cdd_anomaly", "value": 5.0, "units": "days"}


def test_rainfall_anomaly_carries_real_percentage_counterpart_not_just_mm(monkeypatch):
    # Confirmed real bug: Harari's real rainfall_anomaly was -62.29 (mm,
    # from regional_anomaly.mean) but labeled "%" everywhere -- the real
    # percentage figure (from a separate, previously nationally-only
    # regional_pct_anomaly raster aggregation) was never computed
    # regionally or surfaced at all. Now both real numbers are present,
    # correctly labeled, on the same criterion entry -- not double-scored
    # as two separate supporting/contradicting indicators.
    monkeypatch.setattr("app.context.statistical_evidence.default_threshold_for", lambda layer_value, period: 0.5)
    evidence = _evidence_with_region(
        rainfall_anomaly=-62.29, rainfall_anomaly_pct=-53.74, rainfall_percentile=10.0, spi=-1.5,
        cdd_anomaly=5.0, cwd_anomaly=-2.0, rx1day_anomaly=-3.0, rx5day_anomaly=-3.0,
        drought_probability=0.8, wet_probability=0.1,
    )

    findings = build_cross_indicator_findings(evidence, "july")
    region_a = next(item for item in findings if item["area"] == "Region A")
    rainfall_entry = next(item for item in region_a["supporting_indicators"] if item["indicator"] == "rainfall_anomaly")

    assert rainfall_entry["value"] == -62.29
    assert rainfall_entry["units"] == "mm"
    assert rainfall_entry["value_pct"] == -53.74
    assert rainfall_entry["units_pct"] == "%"

    # rainfall_anomaly_pct must never appear as its own scored criterion --
    # it would double-count the exact same signal rainfall_anomaly already
    # scores (identical sign, same underlying raster).
    supporting_names = {item["indicator"] for item in region_a["supporting_indicators"]}
    assert "rainfall_anomaly_pct" not in supporting_names


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
    # Confirmed real ambiguity, fixed: the reported "indicator" must be the
    # REAL name (rx1day_anomaly/rx5day_anomaly) that was actually selected,
    # never the generic "rx_anomaly" label, which is not a real field name
    # anywhere in the evidence -- and both real components must be visible.
    values = {"rx1day_anomaly": 2.0, "rx5day_anomaly": -6.0}
    objects = _indicator_evidence_objects(["rx_anomaly"], values)
    assert objects == [{
        "indicator": "rx5day_anomaly", "value": -6.0, "units": "mm",
        "rx1day_anomaly": 2.0, "rx5day_anomaly": -6.0,
    }]

    empty = _indicator_evidence_objects(["rx_anomaly"], {})
    assert empty == [{"indicator": "rx_anomaly", "value": None, "units": "mm", "rx1day_anomaly": None, "rx5day_anomaly": None}]


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


def test_cross_indicator_findings_partial_drought_signal_not_lumped_with_no_clear_signal(monkeypatch):
    # Confirmed real bug reproduced exactly: 3 of 5 real drought indicators
    # met (0.6 fraction), zero wet indicators met, zero contradicting --
    # this used to fall into the SAME "no_clear_signal" bucket as a
    # genuinely weak/empty case, purely because 0.6 < CROSS_INDICATOR_
    # STRONG_THRESHOLD (0.8). partial_drought is the real, meaningful
    # middle category this was missing.
    monkeypatch.setattr("app.context.statistical_evidence.default_threshold_for", lambda layer_value, period: 0.5)
    evidence = _evidence_with_region(
        rainfall_anomaly=-10.0, rainfall_percentile=15.0, spi=-0.5, cdd_anomaly=3.0, cwd_anomaly=-2.0,
        rx1day_anomaly=-1.0, rx5day_anomaly=-1.0, drought_probability=0.3, wet_probability=0.1,
    )

    findings = build_cross_indicator_findings(evidence, "july")
    region_a = next(item for item in findings if item["area"] == "Region A")

    assert region_a["signal"] == "partial_drought"
    assert region_a["agreement_score"] == 0.6
    assert region_a["contradicting_indicators"] == []
    supporting_names = {item["indicator"] for item in region_a["supporting_indicators"]}
    assert supporting_names == {"rainfall_anomaly", "rainfall_percentile", "cdd_anomaly"}
    # spi and drought_probability were real, available, checked, and
    # simply didn't meet the threshold -- neither missing nor contradicting.
    assert "spi" not in region_a["missing_indicators"]


def test_cross_indicator_findings_reports_real_missing_indicators(monkeypatch):
    # Confirmed real gap, fixed: an indicator with genuinely no data (None)
    # used to silently lower confidence with no way for a reader to see
    # WHICH indicator was actually missing vs simply not met.
    monkeypatch.setattr("app.context.statistical_evidence.default_threshold_for", lambda layer_value, period: 0.5)
    evidence = _evidence_with_region(
        rainfall_anomaly=-10.0, rainfall_percentile=15.0, spi=-1.5, cdd_anomaly=None, cwd_anomaly=-2.0,
        rx1day_anomaly=-1.0, rx5day_anomaly=-1.0, drought_probability=0.8, wet_probability=0.1,
    )

    findings = build_cross_indicator_findings(evidence, "july")
    region_a = next(item for item in findings if item["area"] == "Region A")

    assert "cdd_anomaly" in region_a["missing_indicators"]


def test_action_status_recognizes_partial_signal_as_real_agreement():
    # partial_{hazard_type} must count as agreement the same as strong_
    # {hazard_type}/mixed -- a real partial signal must not be silently
    # treated as if it disagreed entirely.
    assert _action_status("Moderate", "partial_drought", "drought") == "action"
    assert _action_status("Low", "partial_wet", "wet") == "preparedness"


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
            "population_r_drought": {"regional": [
                {"area_name": "Region A", "mean": 20.0, "valid_count": 4},
                {"area_name": "Region B", "mean": 55.0, "valid_count": 348},
            ]},
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
                "cropland_exposed_by_region": [
                    {"area_name": "Region B", "exposed": 7.0, "exposed_pct": 55.5},
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
    # Confirmed real gap, fixed: cropland_exposed_by_region was already
    # computed in the evidence-building loop but never extracted here --
    # it never reached Stage 2/3 or the frontend at all.
    assert top["cropland_exposed_pct"] == 55.5
    # Confirmed real gap, fixed: valid_cell_count/low_sample_size_warning
    # are real, server-generated data-quality signals distinct from
    # `confidence` (cross-indicator agreement) -- Region B's real 348
    # cells is well above the threshold, so no warning.
    assert top["valid_cell_count"] == 348
    assert top["low_sample_size_warning"] is False
    assert top["supporting_indicators"] == ["spi", "cdd_anomaly"]
    assert top["confidence"] == "high"
    # Moderate risk_class + real agreeing cross-indicator signal -> action.
    assert top["action_status"] == "action"

    # Region A has no cross_indicator_findings entry and no exposure entry --
    # must degrade to None/[] gracefully, not crash or fabricate a value.
    second = by_area["Region A"]
    assert second["rank"] == 2
    assert second["risk_score"] == 20.0
    assert second["risk_class"] == "Low"  # real RISK_CLASS_BANDS classification of 20.0 (lower band edge)
    # Low risk_class + no cross-indicator finding at all -> monitor_only,
    # not the same forced-action treatment as a real, agreeing signal.
    assert second["action_status"] == "monitor_only"
    assert second["population_exposed_pct"] is None
    assert second["roads_exposed_pct"] is None
    assert second["healthsites_exposed_pct"] is None
    assert second["cropland_exposed_pct"] is None
    # Region A's real 4 cells (matching Addis Ababa's real count) is below
    # LOW_SAMPLE_CELL_COUNT_THRESHOLD -- a real, deterministic warning,
    # not something the LLM has to notice or guess at itself.
    assert second["valid_cell_count"] == 4
    assert second["low_sample_size_warning"] is True
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


def test_action_status_all_four_tiers():
    # High/Very high risk_class -> always "action", regardless of signal
    # agreement (a real high risk score is actionable on its own).
    assert _action_status("Very high", "no_clear_signal", "drought") == "action"
    assert _action_status("High", None, "wet") == "action"

    # Moderate risk_class -> "action" only with real agreement, else
    # softened to "preparedness".
    assert _action_status("Moderate", "strong_drought", "drought") == "action"
    assert _action_status("Moderate", "mixed", "drought") == "action"
    assert _action_status("Moderate", "no_clear_signal", "drought") == "preparedness"

    # Low risk_class -> "preparedness" with agreement, "monitor_only" without.
    assert _action_status("Low", "strong_wet", "wet") == "preparedness"
    assert _action_status("Low", "no_clear_signal", "wet") == "monitor_only"

    # Very low / unknown risk_class -> "monitor_only" with agreement,
    # "not_actionable" without -- this is the confirmed real bug's exact
    # scenario: a wet-ranked area with Very low risk_score whose own
    # cross-indicator evidence shows the OPPOSITE hazard's strong signal
    # must never be treated the same as a real actionable priority.
    assert _action_status("Very low", "mixed", "wet") == "monitor_only"
    assert _action_status("Very low", "strong_drought", "wet") == "not_actionable"
    assert _action_status("Very low", "no_clear_signal", "wet") == "not_actionable"
    assert _action_status(None, None, "wet") == "not_actionable"


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


def test_build_structured_layer_summaries_special_cases_population_as_exposure_not_hazard_signal():
    # Confirmed real schema mismatch, fixed: population_normalized used to
    # be forced through the same national_signal/national_mean schema as a
    # hazard layer, producing a meaningless "low signal" for population
    # DENSITY and (before the Stage 1 merge fix existed) an LLM-
    # hallucinated "national_mean: 103,776,516" -- a population TOTAL, not
    # a mean of anything. Population is exposure context, not a hazard
    # signal, so it must get real total/exposed population fields instead.
    evidence = {
        "hazard_risk_layers": {
            "population_normalized": {"national": {"mean": 0.193}, "regional": [], "class_area_pct": {}},
        },
        "categorical_layers": {},
        "exposure": {
            "population_r_drought": {
                "population_exposed_by_region": [
                    {"area_name": "Afar", "total": 1_000_000.0, "exposed": 100_000.0},
                    {"area_name": "Somali", "total": 2_000_000.0, "exposed": 300_000.0},
                ],
            },
            "population_r_wet": {
                "population_exposed_by_region": [
                    {"area_name": "Afar", "total": 1_000_000.0, "exposed": 20_000.0},
                ],
            },
        },
    }

    summaries = build_structured_layer_summaries(evidence)

    assert len(summaries) == 1
    item = summaries[0]
    assert item["layer"] == "population_normalized"
    assert "national_signal" not in item
    assert "national_mean" not in item
    assert item["total_population"] == 3_000_000
    assert item["drought_exposed_population"] == 400_000
    assert item["drought_exposed_pct"] == round(400_000 / 3_000_000 * 100, 1)
    assert item["wet_exposed_population"] == 20_000
    assert "population_exposure" in item["classification_method"]
    assert "3,000,000" in item["interpretation"]


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
                "class_scheme": "quintiles_of_current_period (no separate climatology exists for this layer)",
                "class_breakpoints": [0.1, 0.3, 0.5, 0.7],
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
    # Confirmed real gap, fixed: a reader must be able to tell this "moderate"
    # is relative to THIS period's own national quintiles, not a real fixed
    # severity threshold -- no such fixed threshold exists for hazard
    # intensity anywhere in this project's real data catalog.
    assert item["classification_method"] == "quintiles_of_current_period (no separate climatology exists for this layer)"
    assert item["classification_breakpoints"] == [0.1, 0.3, 0.5, 0.7]


def test_build_structured_layer_summaries_risk_scale_layer_uses_real_fixed_bands():
    evidence = {
        "hazard_risk_layers": {
            "population_r_drought": {
                "layer_label": "Drought Risk",
                "national": {"mean": 42.6},
                "regional": [{"area_name": "South Ethiopia", "mean": 60.0}],
                "class_area_pct": {"very_low": 10.0, "low": 10.0, "moderate": 50.0, "high": 20.0, "very_high": 10.0},
                "class_scheme": "risk_class_bands (real, upstream-defined -- same scheme as population_risk_class)",
                # Deliberately no class_breakpoints -- classify_by_risk_bands
                # uses the real fixed RISK_CLASS_BANDS, not a derived quintile.
            },
        },
        "categorical_layers": {},
    }

    summaries = build_structured_layer_summaries(evidence)
    item = summaries[0]

    assert item["classification_method"] == "risk_class_bands (real, upstream-defined -- same scheme as population_risk_class)"
    assert item["classification_breakpoints"] is None


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
    assert item["classification_method"] == "fixed_class_codes (real, upstream-defined -- the raster's pixel value already IS the class)"
    assert item["classification_breakpoints"] is None


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
