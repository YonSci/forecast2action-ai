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


def classify_risk(score: float) -> str:
    """
    Convert numeric risk score into operational alert level.
    """

    if score >= RISK_THRESHOLDS["trigger"]:
        return "trigger"

    if score >= RISK_THRESHOLDS["warning"]:
        return "warning"

    if score >= RISK_THRESHOLDS["watch"]:
        return "watch"

    return "no_alert"


def calculate_risk_score(
    hazard_probability: float,
    exposure: float,
    vulnerability: float,
    confidence: float = 1.0,
) -> float:
    """
    Weighted impact-based risk score.

    Score =
      40% hazard probability
      25% exposure
      25% vulnerability
      10% forecast confidence

    All input values should be normalized between 0 and 1.
    """

    score = (
        RISK_WEIGHTS["hazard_probability"] * float(hazard_probability)
        + RISK_WEIGHTS["exposure"] * float(exposure)
        + RISK_WEIGHTS["vulnerability"] * float(vulnerability)
        + RISK_WEIGHTS["confidence"] * float(confidence)
    )

    return round(min(max(score, 0.0), 1.0), 3)


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