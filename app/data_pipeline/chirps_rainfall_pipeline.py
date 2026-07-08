from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


BASELINE_START_YEAR = 1991
BASELINE_END_YEAR = 2020
CURRENT_YEAR = 2026
SEASON = "MAM"

DATA_SAMPLE_DIR = Path("data/sample")
OUTPUT_TABLES_DIR = Path("outputs/tables")


DISTRICTS = [
    {
        "country": "Ethiopia",
        "district": "Borena",
        "latitude": 4.95,
        "longitude": 38.15,
        "baseline_mean_mm": 280,
        "baseline_std_mm": 55,
        "current_factor": 0.58,
        "exposure": 0.82,
        "vulnerability": 0.88,
    },
    {
        "country": "Ethiopia",
        "district": "Afar Zone 1",
        "latitude": 12.15,
        "longitude": 40.75,
        "baseline_mean_mm": 95,
        "baseline_std_mm": 28,
        "current_factor": 0.76,
        "exposure": 0.68,
        "vulnerability": 0.80,
    },
    {
        "country": "Kenya",
        "district": "Turkana",
        "latitude": 3.12,
        "longitude": 35.60,
        "baseline_mean_mm": 165,
        "baseline_std_mm": 45,
        "current_factor": 0.55,
        "exposure": 0.86,
        "vulnerability": 0.84,
    },
    {
        "country": "Kenya",
        "district": "Garissa",
        "latitude": -0.45,
        "longitude": 39.65,
        "baseline_mean_mm": 190,
        "baseline_std_mm": 48,
        "current_factor": 1.47,
        "exposure": 0.72,
        "vulnerability": 0.66,
    },
]


def ensure_directories() -> None:
    DATA_SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_TABLES_DIR.mkdir(parents=True, exist_ok=True)


def create_chirps_style_timeseries(
    districts: List[Dict],
    baseline_start: int = BASELINE_START_YEAR,
    baseline_end: int = BASELINE_END_YEAR,
    current_year: int = CURRENT_YEAR,
    season: str = SEASON,
) -> pd.DataFrame:
    """
    Create a CHIRPS-style district seasonal rainfall table.

    This is a realistic pipeline scaffold for the hackathon MVP:
    - historical baseline years are generated around district climatology;
    - current-year rainfall is forced using a scenario factor;
    - the same structure can later be replaced with real CHIRPS zonal statistics.

    Output columns:
    country, district, year, season, rainfall_mm, latitude, longitude
    """

    np.random.seed(42)

    rows = []
    years = list(range(baseline_start, baseline_end + 1)) + [current_year]

    for district in districts:
        baseline_mean = district["baseline_mean_mm"]
        baseline_std = district["baseline_std_mm"]

        for year in years:
            if year == current_year:
                rainfall_mm = baseline_mean * district["current_factor"]
            else:
                rainfall_mm = np.random.normal(
                    loc=baseline_mean,
                    scale=baseline_std,
                )

            rainfall_mm = max(float(rainfall_mm), 0.0)

            rows.append(
                {
                    "country": district["country"],
                    "district": district["district"],
                    "year": year,
                    "season": season,
                    "rainfall_mm": round(rainfall_mm, 2),
                    "latitude": district["latitude"],
                    "longitude": district["longitude"],
                }
            )

    return pd.DataFrame(rows)


def create_exposure_vulnerability_table(districts: List[Dict]) -> pd.DataFrame:
    """
    Create a district exposure/vulnerability table.

    In production, this should come from real population, livelihood,
    infrastructure, poverty, food security, livestock, crop, and access datasets.
    """

    rows = []

    for district in districts:
        rows.append(
            {
                "country": district["country"],
                "district": district["district"],
                "exposure": district["exposure"],
                "vulnerability": district["vulnerability"],
                "latitude": district["latitude"],
                "longitude": district["longitude"],
            }
        )

    return pd.DataFrame(rows)


def compute_rainfall_anomaly_indicators(
    rainfall_df: pd.DataFrame,
    exposure_df: pd.DataFrame,
    baseline_start: int = BASELINE_START_YEAR,
    baseline_end: int = BASELINE_END_YEAR,
    current_year: int = CURRENT_YEAR,
) -> pd.DataFrame:
    """
    Compute district-level seasonal rainfall anomaly and SPI-like z-score.

    SPI here is a simple standardized rainfall anomaly:
        SPI-like = (current rainfall - baseline mean) / baseline std

    For a prototype, this is sufficient to demonstrate the workflow.
    For an operational system, replace with gamma-distribution SPI or SPEI
    calculated from a longer verified rainfall record.
    """

    baseline = rainfall_df[
        (rainfall_df["year"] >= baseline_start)
        & (rainfall_df["year"] <= baseline_end)
    ]

    current = rainfall_df[rainfall_df["year"] == current_year].copy()

    climatology = (
        baseline.groupby(["country", "district"])
        .agg(
            baseline_mean_mm=("rainfall_mm", "mean"),
            baseline_std_mm=("rainfall_mm", "std"),
        )
        .reset_index()
    )

    summary = current.merge(
        climatology,
        on=["country", "district"],
        how="left",
    )

    summary["rainfall_anomaly_mm"] = (
        summary["rainfall_mm"] - summary["baseline_mean_mm"]
    )

    summary["rainfall_anomaly_pct"] = np.where(
        summary["baseline_mean_mm"] > 0,
        100.0 * summary["rainfall_anomaly_mm"] / summary["baseline_mean_mm"],
        0.0,
    )

    summary["spi"] = np.where(
        summary["baseline_std_mm"] > 0,
        summary["rainfall_anomaly_mm"] / summary["baseline_std_mm"],
        0.0,
    )

    summary = summary.merge(
        exposure_df[
            [
                "country",
                "district",
                "exposure",
                "vulnerability",
                "latitude",
                "longitude",
            ]
        ],
        on=["country", "district", "latitude", "longitude"],
        how="left",
    )

    summary["baseline_mean_mm"] = summary["baseline_mean_mm"].round(2)
    summary["baseline_std_mm"] = summary["baseline_std_mm"].round(2)
    summary["rainfall_anomaly_mm"] = summary["rainfall_anomaly_mm"].round(2)
    summary["rainfall_anomaly_pct"] = summary["rainfall_anomaly_pct"].round(1)
    summary["spi"] = summary["spi"].round(2)

    return summary


def classify_rainfall_hazard(row: pd.Series) -> str:
    """
    Classify rainfall-driven hazard type from anomaly and SPI-like score.
    """

    spi = float(row["spi"])
    anomaly_pct = float(row["rainfall_anomaly_pct"])

    if spi <= -0.8 or anomaly_pct <= -20:
        return "drought"

    if spi >= 0.8 or anomaly_pct >= 20:
        return "heavy_rainfall"

    return "rainfall_watch"


def estimate_hazard_probability(row: pd.Series) -> float:
    """
    Convert rainfall anomaly/SPI severity into a normalized hazard probability.

    Drought probability increases as SPI becomes more negative.
    Heavy rainfall probability increases as SPI becomes more positive.
    """

    hazard = row["hazard"]
    spi = float(row["spi"])
    anomaly_pct = float(row["rainfall_anomaly_pct"])

    if hazard == "drought":
        spi_component = min(abs(spi) / 2.0, 1.0)
        anomaly_component = min(abs(min(anomaly_pct, 0.0)) / 60.0, 1.0)
        probability = 0.35 + 0.45 * spi_component + 0.20 * anomaly_component

    elif hazard == "heavy_rainfall":
        spi_component = min(max(spi, 0.0) / 2.0, 1.0)
        anomaly_component = min(max(anomaly_pct, 0.0) / 60.0, 1.0)
        probability = 0.35 + 0.45 * spi_component + 0.20 * anomaly_component

    else:
        probability = 0.35

    return round(min(max(probability, 0.0), 1.0), 3)


def estimate_confidence(row: pd.Series) -> float:
    """
    Confidence proxy based on anomaly strength.

    Stronger anomalies get higher confidence in this MVP.
    """

    abs_spi = abs(float(row["spi"]))

    if abs_spi >= 1.5:
        return 0.84

    if abs_spi >= 1.0:
        return 0.78

    if abs_spi >= 0.5:
        return 0.70

    return 0.62


def build_hazard_indicator_table(summary_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert rainfall anomaly table into the hazard_indicators.csv format
    consumed by the FastAPI backend and React dashboard.
    """

    df = summary_df.copy()

    df["hazard"] = df.apply(classify_rainfall_hazard, axis=1)
    df["hazard_probability"] = df.apply(estimate_hazard_probability, axis=1)
    df["confidence"] = df.apply(estimate_confidence, axis=1)

    df["indicator_source"] = "CHIRPS-style seasonal rainfall anomaly and SPI-like z-score"
    df["data_note"] = (
        "Prototype district-level rainfall indicators. Replace with real CHIRPS "
        "zonal statistics for operational use."
    )

    columns = [
        "country",
        "district",
        "hazard",
        "hazard_probability",
        "exposure",
        "vulnerability",
        "confidence",
        "latitude",
        "longitude",
        "year",
        "season",
        "rainfall_mm",
        "baseline_mean_mm",
        "baseline_std_mm",
        "rainfall_anomaly_mm",
        "rainfall_anomaly_pct",
        "spi",
        "indicator_source",
        "data_note",
    ]

    return df[columns]


def run_pipeline() -> pd.DataFrame:
    """
    Run the full CHIRPS-style rainfall anomaly pipeline and write outputs.
    """

    ensure_directories()

    rainfall_df = create_chirps_style_timeseries(DISTRICTS)
    exposure_df = create_exposure_vulnerability_table(DISTRICTS)

    summary_df = compute_rainfall_anomaly_indicators(
        rainfall_df=rainfall_df,
        exposure_df=exposure_df,
    )

    hazard_df = build_hazard_indicator_table(summary_df)

    rainfall_path = DATA_SAMPLE_DIR / "chirps_district_rainfall_timeseries.csv"
    exposure_path = DATA_SAMPLE_DIR / "exposure_vulnerability.csv"
    hazard_path = DATA_SAMPLE_DIR / "hazard_indicators.csv"
    summary_path = OUTPUT_TABLES_DIR / "chirps_anomaly_summary.csv"

    rainfall_df.to_csv(rainfall_path, index=False)
    exposure_df.to_csv(exposure_path, index=False)
    hazard_df.to_csv(hazard_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    print("CHIRPS-style rainfall pipeline completed.")
    print(f"Rainfall time series: {rainfall_path}")
    print(f"Exposure/vulnerability: {exposure_path}")
    print(f"Hazard indicators: {hazard_path}")
    print(f"Anomaly summary: {summary_path}")

    return hazard_df


if __name__ == "__main__":
    output = run_pipeline()
    print()
    print(output)