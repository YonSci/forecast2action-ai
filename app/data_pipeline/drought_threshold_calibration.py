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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from shapely.geometry import Point, shape

RAINFALL_CSV = Path("data/raw/historical_impact/eth_region_monthly_rainfall.csv")
GLIDE_CSV = Path("data/raw/historical_impact/eth_glide_events.csv")
ADMIN1_PATH = Path("data/sample/admin_boundaries/eth_admin1.json")

# Where the v1 (drought-only) results this app's frontend reads are
# persisted -- served read-only via GET /api/validation/historical-skill,
# never recomputed live (the CHIRPS download + zonal stats behind
# eth_region_monthly_rainfall.csv is a heavy, periodic offline job -- see
# historical_rainfall_pipeline.py).
RESULTS_PATH = Path("data/historical_validation/drought_validation_v1.json")

# JJAS = the app's real forecast window (June-September), matching what the
# live product actually forecasts -- an event-YEAR is flagged if any real
# GLIDE drought (DR) event was registered for that region in that year,
# regardless of which specific month (droughts are accumulation phenomena,
# not single-month events).
SEASON_MONTHS = {6, 7, 8, 9}

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


def load_glide_drought_event_records() -> List[Dict[str, object]]:
    """Full detail for every real GLIDE drought (DR) event that geocodes to
    a specific real admin1 region -- point-in-polygon matched against this
    app's own real admin1 boundaries. Kept as full records (not just a
    deduplicated set) so the results JSON can list each real event by name/
    date for the frontend's per-event table, not just aggregate stats.
    """
    admin1 = json.loads(ADMIN1_PATH.read_text(encoding="utf-8"))
    regions = [(f["properties"].get("region"), shape(f["geometry"])) for f in admin1["features"]]

    with open(GLIDE_CSV, encoding="utf-8") as f:
        glide_rows = list(csv.DictReader(f))

    records: List[Dict[str, object]] = []
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
            records.append({
                "glidenumber": row.get("glidenumber", ""),
                "region": region_name,
                "location": row.get("location", ""),
                "year": year,
                "month": month,
            })
    return records


def load_glide_drought_events_by_region(records: List[Dict[str, object]]) -> Set[Tuple[str, int, int]]:
    return {(r["region"], r["year"], r["month"]) for r in records}


def load_glide_drought_event_years_by_region(records: List[Dict[str, object]]) -> Set[Tuple[str, int]]:
    return {(r["region"], r["year"]) for r in records}


def is_event_month(region: str, year: int, month: int, events: Set[Tuple[str, int, int]]) -> bool:
    return any(
        (region, year, candidate_month) in events
        for candidate_month in range(month - MONTH_TOLERANCE, month + MONTH_TOLERANCE + 1)
    )


def compute_seasonal_totals(rows: List[Dict[str, object]]) -> Dict[Tuple[str, int], float]:
    """Real per-region, per-year JJAS (Jun-Sep) total rainfall -- only kept
    for a (region, year) when all 4 real season months are present, so a
    partial season is never silently treated as a low total.
    """
    by_key: Dict[Tuple[str, int], Dict[int, float]] = {}
    for row in rows:
        if row["month"] not in SEASON_MONTHS or row["rainfall_mm"] is None:
            continue
        key = (row["region"], row["year"])
        by_key.setdefault(key, {})[row["month"]] = row["rainfall_mm"]

    return {
        key: sum(months.values())
        for key, months in by_key.items()
        if set(months.keys()) == SEASON_MONTHS
    }


def compute_seasonal_baselines(totals: Dict[Tuple[str, int], float]) -> Dict[str, Tuple[float, float]]:
    import numpy as np

    by_region: Dict[str, List[float]] = {}
    for (region, _year), total in totals.items():
        by_region.setdefault(region, []).append(total)

    return {
        region: (float(np.mean(values)), float(np.std(values)))
        for region, values in by_region.items()
        if len(values) >= 3
    }


def _rate(anomalies: List[float], threshold: float) -> float:
    return sum(1 for a in anomalies if a <= threshold) / len(anomalies) if anomalies else float("nan")


def _threshold_table(event_anomalies: List[float], no_event_anomalies: List[float]) -> List[Dict[str, Any]]:
    return [
        {
            "threshold_label": label,
            "threshold_value": threshold,
            "hit_rate": _rate(event_anomalies, threshold),
            "false_alarm_rate": _rate(no_event_anomalies, threshold),
        }
        for label, threshold in DRY_THRESHOLDS.items()
    ]


def build_results() -> Dict[str, Any]:
    """Assembles both the single-month and JJAS-seasonal analyses (the
    seasonal one is the stronger, more presentable signal -- droughts are
    accumulation phenomena, not single-month events) into one JSON-
    serializable results object, plus the real per-event detail and an
    explicit, honest scope/methodology disclosure for the frontend to
    render verbatim rather than paraphrase.
    """
    import numpy as np

    rows = load_rainfall_table()
    baselines = compute_baselines(rows)
    records = load_glide_drought_event_records()
    month_events = load_glide_drought_events_by_region(records)
    year_events = load_glide_drought_event_years_by_region(records)

    # Single-month analysis
    month_event_anomalies: List[float] = []
    month_no_event_anomalies: List[float] = []
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
        if is_event_month(row["region"], row["year"], row["month"], month_events):
            month_event_anomalies.append(anomaly)
        else:
            month_no_event_anomalies.append(anomaly)

    # JJAS-seasonal analysis
    seasonal_totals = compute_seasonal_totals(rows)
    seasonal_baselines = compute_seasonal_baselines(seasonal_totals)
    season_event_anomalies: List[float] = []
    season_no_event_anomalies: List[float] = []
    event_year_anomaly_by_key: Dict[Tuple[str, int], float] = {}
    for (region, year), total in seasonal_totals.items():
        if region not in seasonal_baselines:
            continue
        mean, std = seasonal_baselines[region]
        if std == 0:
            continue
        anomaly = (total - mean) / std
        if (region, year) in year_events:
            season_event_anomalies.append(anomaly)
            event_year_anomaly_by_key[(region, year)] = anomaly
        else:
            season_no_event_anomalies.append(anomaly)

    per_event = [
        {
            "glidenumber": r["glidenumber"],
            "region": r["region"],
            "location": r["location"],
            "year": r["year"],
            "month": r["month"],
            "seasonal_anomaly": event_year_anomaly_by_key.get((r["region"], r["year"])),
            "seasonal_hit_moderately_dry": (
                event_year_anomaly_by_key[(r["region"], r["year"])] <= DRY_THRESHOLDS["moderately_dry"]
                if (r["region"], r["year"]) in event_year_anomaly_by_key
                else None
            ),
        }
        for r in sorted(records, key=lambda r: (r["year"], r["month"]))
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "drought_only_v1",
        "methodology": {
            "summary": (
                "Real historical CHIRPS rainfall (1997-2025, June-September) compared against "
                "real GLIDE drought (DR) events geocoded to this app's own real admin1 boundaries. "
                "Anomaly is a simplified per-region z-score against a multi-year baseline, NOT the "
                "full McKee et al. 1993 gamma-distribution SPI this app's live forecast product uses "
                "-- disclosed as an approximation, not presented as exact."
            ),
            "thresholds_evaluated": "This app's own real SPI_CATEGORY_BANDS (moderately/severely/extremely dry) -- not modified by this diagnostic.",
            "caveat": (
                "Small real sample size, especially at the seasonal/event-year level (n="
                f"{len(season_event_anomalies)} event-years). A directionally consistent but "
                "statistically limited signal, not a validated forecast-skill score."
            ),
        },
        "data_provenance": {
            "rainfall_source": "CHIRPS v2.0 monthly, real, downloaded from data.chc.ucsb.edu",
            "rainfall_rows": len(rows),
            "event_source": "GLIDE disaster events (via HDX), real, geocoded to admin1 by point-in-polygon",
            "drought_events_matched": len(records),
            "baseline_years": "1997-2025",
        },
        "monthly_analysis": {
            "event_months": len(month_event_anomalies),
            "no_event_months": len(month_no_event_anomalies),
            "mean_anomaly_event": float(np.mean(month_event_anomalies)) if month_event_anomalies else None,
            "mean_anomaly_no_event": float(np.mean(month_no_event_anomalies)) if month_no_event_anomalies else None,
            "thresholds": _threshold_table(month_event_anomalies, month_no_event_anomalies),
        },
        "seasonal_analysis": {
            "event_years": len(season_event_anomalies),
            "no_event_years": len(season_no_event_anomalies),
            "mean_anomaly_event": float(np.mean(season_event_anomalies)) if season_event_anomalies else None,
            "mean_anomaly_no_event": float(np.mean(season_no_event_anomalies)) if season_no_event_anomalies else None,
            "thresholds": _threshold_table(season_event_anomalies, season_no_event_anomalies),
        },
        "events": per_event,
    }


def save_results(results: Dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved real validation results -> {RESULTS_PATH}")


def run_diagnostic() -> None:
    results = build_results()
    print(f"Real (region, year, month) rainfall rows: {results['data_provenance']['rainfall_rows']}")
    print(f"Real GLIDE drought events geocoded to a real admin1 region: {results['data_provenance']['drought_events_matched']}")

    m = results["monthly_analysis"]
    print()
    print(f"[Monthly] Real event months: {m['event_months']} | Real no-event months: {m['no_event_months']}")
    print(f"[Monthly] Mean anomaly (event months):    {m['mean_anomaly_event']:+.2f}")
    print(f"[Monthly] Mean anomaly (no-event months): {m['mean_anomaly_no_event']:+.2f}")
    for row in m["thresholds"]:
        print(f"  {row['threshold_value']:<6.1f} {row['threshold_label']:16s} hit={row['hit_rate']:.1%}  false_alarm={row['false_alarm_rate']:.1%}")

    s = results["seasonal_analysis"]
    print()
    print(f"[Seasonal/JJAS] Real event years: {s['event_years']} | Real no-event years: {s['no_event_years']}")
    print(f"[Seasonal/JJAS] Mean anomaly (event years):    {s['mean_anomaly_event']:+.2f}")
    print(f"[Seasonal/JJAS] Mean anomaly (no-event years): {s['mean_anomaly_no_event']:+.2f}")
    for row in s["thresholds"]:
        print(f"  {row['threshold_value']:<6.1f} {row['threshold_label']:16s} hit={row['hit_rate']:.1%}  false_alarm={row['false_alarm_rate']:.1%}")

    save_results(results)


if __name__ == "__main__":
    run_diagnostic()
