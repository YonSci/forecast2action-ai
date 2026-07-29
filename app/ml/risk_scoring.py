from typing import Any, Dict, Optional

import pandas as pd

# Single source of truth for the weighted risk-score formula and its
# no_alert/watch/warning/trigger classification thresholds. Other modules
# (app/data_pipeline/ethiopia_forecast_grid_pipeline.py, app/api/main.py)
# previously duplicated these literals inline -- importing from here instead
# means a future re-tuning only has to happen in one place.
RISK_WEIGHTS = {
    "hazard_probability": 0.40,
    "exposure": 0.25,
    "vulnerability": 0.25,
    "confidence": 0.10,
}

RISK_THRESHOLDS = {
    "trigger": 0.80,
    "warning": 0.60,
    "watch": 0.35,
}


def classify_risk(score: float, thresholds: Optional[Dict[str, float]] = None) -> str:
    """
    Convert numeric risk score into operational alert level.

    `thresholds` defaults to RISK_THRESHOLDS so every existing call site
    (score_districts, app/data_pipeline/ethiopia_forecast_grid_pipeline.py)
    keeps producing identical results unless a caller explicitly opts into
    policy-supplied thresholds (see app/decision/policy_engine.py).
    """
    thresholds = thresholds or RISK_THRESHOLDS

    if score >= thresholds["trigger"]:
        return "trigger"

    if score >= thresholds["warning"]:
        return "warning"

    if score >= thresholds["watch"]:
        return "watch"

    return "no_alert"


def calculate_risk_score(
    hazard_probability: float,
    exposure: float,
    vulnerability: float,
    confidence: float = 1.0,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Weighted impact-based risk score.

    Score =
      40% hazard probability
      25% exposure
      25% vulnerability
      10% forecast confidence

    All input values should be normalized between 0 and 1.

    `weights` defaults to RISK_WEIGHTS so every existing call site keeps
    producing identical results unless a caller explicitly opts into
    policy-loaded weights (see config/risk_weights.yaml).
    """
    weights = weights or RISK_WEIGHTS

    score = (
        weights["hazard_probability"] * float(hazard_probability)
        + weights["exposure"] * float(exposure)
        + weights["vulnerability"] * float(vulnerability)
        + weights["confidence"] * float(confidence)
    )

    return round(min(max(score, 0.0), 1.0), 3)


def explain_risk_score(
    hazard_probability: float,
    exposure: float,
    vulnerability: float,
    confidence: float = 1.0,
    weights: Optional[Dict[str, float]] = None,
    thresholds: Optional[Dict[str, float]] = None,
    policy_version: str = "default",
) -> Dict[str, Any]:
    """Risk score plus a component-contribution breakdown and the policy
    version used, for traceable/explainable decision support. Validates
    inputs are within [0, 1] and flags any that aren't rather than silently
    clamping them without telling the caller.

    Does not change calculate_risk_score's own return type (still a bare
    float) -- this is an additive, separate entry point so no existing
    caller (score_districts, main.py) needs to change.
    """
    weights = weights or RISK_WEIGHTS
    thresholds = thresholds or RISK_THRESHOLDS

    inputs = {
        "hazard_probability": hazard_probability,
        "exposure": exposure,
        "vulnerability": vulnerability,
        "confidence": confidence,
    }
    warnings = [
        f"{name}={value} is outside the expected [0, 1] range"
        for name, value in inputs.items()
        if value is None or not (0.0 <= float(value) <= 1.0)
    ]

    score = calculate_risk_score(
        hazard_probability, exposure, vulnerability, confidence, weights=weights,
    )

    return {
        "risk_score": score,
        "risk_level": classify_risk(score, thresholds=thresholds),
        "components": {
            "hazard_probability_contribution": round(
                weights["hazard_probability"] * float(hazard_probability), 3
            ),
            "exposure_contribution": round(weights["exposure"] * float(exposure), 3),
            "vulnerability_contribution": round(
                weights["vulnerability"] * float(vulnerability), 3
            ),
            "confidence_contribution": round(weights["confidence"] * float(confidence), 3),
        },
        "weights_used": weights,
        "thresholds_used": thresholds,
        "policy_version": policy_version,
        "warnings": warnings,
    }


def score_districts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score all districts from input dataframe.

    Required columns:
    - hazard_probability
    - exposure
    - vulnerability
    - confidence
    """

    df = df.copy()

    df["risk_score"] = df.apply(
        lambda row: calculate_risk_score(
            row["hazard_probability"],
            row["exposure"],
            row["vulnerability"],
            row.get("confidence", 1.0),
        ),
        axis=1,
    )

    df["risk_level"] = df["risk_score"].apply(classify_risk)

    return df