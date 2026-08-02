"""Tests app.context.policy_context.resolve_real_trigger_status -- the fix
for a real, confirmed bug: a context built by ranking on Exposure (no
hazard_type) used to come out trigger_status="trigger" via the generic
priority_score (trivially ~1.0 for whatever ranks #1 under any metric),
driving hazard-irrelevant RAG retrieval. This must now use the same real
drought_risk/wet_risk classification as the ranking table.
"""

from app.context.policy_context import resolve_real_trigger_status
from app.context.schemas import HazardEvidence


def _hazard_evidence(hazard_type, drought_risk=None, wet_risk=None):
    return HazardEvidence(
        layer_value="population_r_drought",
        layer_label="Drought Risk",
        hazard_type=hazard_type,
        category="risk",
        units="score",
        rank_value=30.2,
        priority_score=1.0,  # deliberately misleading -- must be ignored
        drought_risk=drought_risk,
        wet_risk=wet_risk,
    )


def test_drought_ranked_context_uses_real_drought_level():
    evidence = _hazard_evidence(
        "drought",
        drought_risk={"value": 30.2, "level": "watch"},
        wet_risk={"value": 1.1, "level": "no_alert"},
    )

    hazard, trigger_status = resolve_real_trigger_status(evidence)

    assert hazard == "drought"
    assert trigger_status == "watch"


def test_wet_ranked_context_uses_real_wet_level():
    evidence = _hazard_evidence(
        "wet",
        drought_risk={"value": 5.0, "level": "no_alert"},
        wet_risk={"value": 40.0, "level": "trigger"},
    )

    hazard, trigger_status = resolve_real_trigger_status(evidence)

    assert hazard == "wet"
    assert trigger_status == "trigger"


def test_exposure_ranked_context_falls_back_to_more_severe_hazard():
    # This is the exact bug scenario: hazard_type is None (ranked by
    # Population/Exposure), priority_score trivially 1.0 -- must resolve
    # from the real drought/wet levels instead, never trigger_status
    # "trigger" just because priority_score says so.
    evidence = _hazard_evidence(
        None,
        drought_risk={"value": 9.8, "level": "no_alert"},
        wet_risk={"value": 6.5, "level": "no_alert"},
    )

    hazard, trigger_status = resolve_real_trigger_status(evidence)

    assert hazard in ("drought", "wet")
    assert trigger_status == "no_alert"


def test_exposure_ranked_context_picks_the_worse_hazard():
    evidence = _hazard_evidence(
        None,
        drought_risk={"value": 20.0, "level": "watch"},
        wet_risk={"value": 40.0, "level": "trigger"},
    )

    hazard, trigger_status = resolve_real_trigger_status(evidence)

    assert hazard == "wet"
    assert trigger_status == "trigger"


def test_dominant_hazard_type_also_falls_back_to_worse_real_level():
    evidence = _hazard_evidence(
        "dominant",
        drought_risk={"value": 45.0, "level": "trigger"},
        wet_risk={"value": 5.0, "level": "no_alert"},
    )

    hazard, trigger_status = resolve_real_trigger_status(evidence)

    assert hazard == "drought"
    assert trigger_status == "trigger"


def test_missing_drought_and_wet_data_defaults_to_no_alert():
    evidence = _hazard_evidence(None, drought_risk=None, wet_risk=None)

    hazard, trigger_status = resolve_real_trigger_status(evidence)

    assert trigger_status == "no_alert"
