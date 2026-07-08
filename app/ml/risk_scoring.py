import pandas as pd


def classify_risk(score: float) -> str:
    """
    Convert numeric risk score into operational alert level.
    """

    if score < 0.35:
        return "no_alert"

    if score < 0.60:
        return "watch"

    if score < 0.80:
        return "warning"

    return "trigger"


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
        0.40 * float(hazard_probability)
        + 0.25 * float(exposure)
        + 0.25 * float(vulnerability)
        + 0.10 * float(confidence)
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