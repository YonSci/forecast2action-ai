"""
Real diagnostic: does this app's own real SPI classification thresholds
(SPI_CATEGORY_BANDS, app.context.statistical_evidence -- real McKee et al.
1993 bands) look consistent with real historical drought outcomes?

Consumes the real (region, year, month) rainfall table produced by
app.data_pipeline.historical_rainfall_pipeline and the real drought (DR)
events already geocoded from GLIDE (data/raw/historical_impact/
eth_glide_events.csv, see the session's earlier admin1 point-in-polygon
matching). Computes a real simplified standardized rainfall anomaly
(z-score against each region's own real per-calendar-month baseline -- NOT
the full McKee gamma-distribution SPI this app's real upstream SPI product
uses; disclosed as a simplification, not presented as exact), then
compares real "event month" vs real "no-event month" anomalies at each of
the app's own real SPI band thresholds -- a hit-rate/false-alarm-rate
style comparison, the closest achievable analog to proper forecast-skill
scoring given that no historical hazard-raster archive exists in this repo.

Deliberately produces a FINDING, not a code change: does not modify
SPI_CATEGORY_BANDS or RISK_CLASS_BANDS (RISK_CLASS_BANDS mirrors an
external upstream config this repo doesn't own -- see hazard_risk_
catalog_shared.py's own comment).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple

from shapely.geometry import Point, shape

RAINFALL_CSV = Path("data/raw/historical_impact/eth_region_monthly_rainfall.csv")
GLIDE_CSV = Path("data/raw/historical_impact/eth_glide_events.csv")
ADMIN1_PATH = Path("data/sample/admin_boundaries/eth_admin1.json")

# Same real bands this app's own real SPI classification already uses --
# see app.context.statistical_evidence.SPI_CATEGORY_BANDS. Only the dry
# side matters for a drought diagnostic.
DRY_THRESHOLDS = {
    "moderately_dry": -1.0,
    "severely_dry": -1.5,
    "extremely_dry": -2.0,
}

# Real reporting-lag tolerance: a real GLIDE event's registered month is
# often a few weeks after real onset, so a drought event registered in
# month M may have its real rainfall deficit show up in month M-1 or M.
MONTH_TOLERANCE = 1


def load_rainfall_table() -> List[Dict[str, object]]:
    with open(RAINFALL_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["year"] = int(row["year"])
        row["month"] = int(row["month"])
        row["rainfall_mm"] = float(row["rainfall_mm"]) if row["rainfall_mm"] not in ("", "nan") else None
    return rows


def compute_baselines(rows: List[Dict[str, object]]) -> Dict[Tuple[str, int], Tuple[float, float]]:
    """Real per-region, per-calendar-month baseline mean/std, across all
    real downloaded years -- the reference every real year's anomaly is
    computed against.
    """
    import numpy as np

    by_key: Dict[Tuple[str, int], List[float]] = {}
    for row in rows:
        if row["rainfall_mm"] is None:
            continue
        key = (row["region"], row["month"])
        by_key.setdefault(key, []).append(row["rainfall_mm"])

    return {
        key: (float(np.mean(values)), float(np.std(values)))
        for key, values in by_key.items()
        if len(values) >= 3  # too few real years for a meaningful baseline otherwise
    }


def load_glide_drought_events_by_region() -> Set[Tuple[str, int, int]]:
    """Real (region, year, month) tuples for every real GLIDE drought (DR)
    event that geocodes to a specific real admin1 region -- same point-in-
    polygon matching already done earlier this session, redone here so
    this script is self-contained and reproducible on its own.
    """
    admin1 = json.loads(ADMIN1_PATH.read_text(encoding="utf-8"))
    regions = [(f["properties"].get("region"), shape(f["geometry"])) for f in admin1["features"]]

    with open(GLIDE_CSV, encoding="utf-8") as f:
        glide_rows = list(csv.DictReader(f))

    events: Set[Tuple[str, int, int]] = set()
    for row in glide_rows:
        if row["event"] != "DR":
            continue
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            year, month = int(row["year"]), int(row["month"])
        except ValueError:
            continue
        point = Point(lon, lat)
        region_name = next((name for name, geom in regions if geom.contains(point)), None)
        if region_name:
            events.add((region_name, year, month))
    return events


def is_event_month(region: str, year: int, month: int, events: Set[Tuple[str, int, int]]) -> bool:
    return any(
        (region, year, candidate_month) in events
        for candidate_month in range(month - MONTH_TOLERANCE, month + MONTH_TOLERANCE + 1)
    )


def run_diagnostic() -> None:
    rows = load_rainfall_table()
    baselines = compute_baselines(rows)
    events = load_glide_drought_events_by_region()
    print(f"Real (region, year, month) rainfall rows: {len(rows)}")
    print(f"Real GLIDE drought events geocoded to a real admin1 region: {len(events)}")

    event_anomalies: List[float] = []
    no_event_anomalies: List[float] = []

    for row in rows:
        if row["rainfall_mm"] is None:
            continue
        key = (row["region"], row["month"])
        if key not in baselines:
            continue
        mean, std = baselines[key]
        if std == 0:
            continue
        anomaly = (row["rainfall_mm"] - mean) / std

        if is_event_month(row["region"], row["year"], row["month"], events):
            event_anomalies.append(anomaly)
        else:
            no_event_anomalies.append(anomaly)

    import numpy as np

    print()
    print(f"Real event months: {len(event_anomalies)} | Real no-event months: {len(no_event_anomalies)}")
    print(f"Mean anomaly (event months):    {np.mean(event_anomalies):+.2f}")
    print(f"Median anomaly (event months):  {np.median(event_anomalies):+.2f}")
    print(f"Mean anomaly (no-event months): {np.mean(no_event_anomalies):+.2f}")
    print(f"Median anomaly (no-event months): {np.median(no_event_anomalies):+.2f}")
    print()
    print("Real hit-rate / false-alarm-rate at each of this app's own real SPI band thresholds:")
    print(f"{'threshold':18s} {'label':16s} {'hit rate (event months below)':32s} {'false-alarm rate (no-event months below)':42s}")
    for label, threshold in DRY_THRESHOLDS.items():
        hit_rate = sum(1 for a in event_anomalies if a <= threshold) / len(event_anomalies) if event_anomalies else float("nan")
        false_alarm_rate = sum(1 for a in no_event_anomalies if a <= threshold) / len(no_event_anomalies) if no_event_anomalies else float("nan")
        print(f"{threshold:<18.1f} {label:16s} {hit_rate:<32.1%} {false_alarm_rate:<42.1%}")


if __name__ == "__main__":
    run_diagnostic()
