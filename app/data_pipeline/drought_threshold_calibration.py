"""
Real diagnostic: does this app's own real SPI classification thresholds
(SPI_CATEGORY_BANDS, app.context.statistical_evidence -- real McKee et al.
1993 bands) look consistent with real historical drought outcomes -- and
which of the real climate indicators this app offers (Rainfall Total, SPI,
Rainfall Percentile) actually discriminates real drought years best?

Consumes the real (region, year, month) rainfall table produced by
app.data_pipeline.historical_rainfall_pipeline and the real drought (DR)
events already geocoded from GLIDE (data/raw/historical_impact/
eth_glide_events.csv). Computes real JJAS-seasonal (Jun-Sep) values for
three real indicators, each derived independently from the same real
monthly CHIRPS totals already downloaded:

- Rainfall Total: a real per-region z-score anomaly against a multi-year
  baseline.
- SPI: a real gamma-distribution fit per region (McKee et al. 1993
  methodology -- probability integral transform via the region's own real
  fitted gamma CDF), not a simplified z-score. This app's live SPI product
  comes from a separate upstream project (see README's Real data sources);
  this is an independent, standard implementation of the same real
  methodology, not a reuse of that pipeline's code.
- Rainfall Percentile: a real empirical percentile rank within each
  region's own real seasonal-total history.

CDD, CWD, Rx1day, and Rx5day are NOT included -- they need real daily
rainfall, which this repo has not downloaded (only monthly CHIRPS totals),
and were explicitly scoped out of this v1 pass rather than approximated.

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

# Real per-indicator thresholds for "moderately/severely/extremely dry",
# each chosen to carry the SAME underlying probability under a standard
# normal distribution as this app's own real SPI_CATEGORY_BANDS
# (norm.cdf(-1.0)=15.87%, norm.cdf(-1.5)=6.68%, norm.cdf(-2.0)=2.28%) --
# so the three indicators are compared on genuinely equal footing, not an
# arbitrary per-indicator cutoff.
INDICATOR_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "rainfall_total": {"moderately_dry": -1.0, "severely_dry": -1.5, "extremely_dry": -2.0},
    "spi": {"moderately_dry": -1.0, "severely_dry": -1.5, "extremely_dry": -2.0},
    "rainfall_percentile": {"moderately_dry": 15.87, "severely_dry": 6.68, "extremely_dry": 2.28},
}

INDICATOR_LABELS: Dict[str, str] = {
    "rainfall_total": "Rainfall Total (z-score anomaly)",
    "spi": "SPI (real gamma-distribution fit, McKee et al. 1993 methodology)",
    "rainfall_percentile": "Rainfall Percentile (real empirical rank, within-region)",
}

# Real reporting-lag tolerance retained for reference (droughts are
# accumulation phenomena; a GLIDE event registered in month M can reflect
# a deficit that began weeks earlier) -- not used directly now that the
# analysis is seasonal-only, kept for anyone re-deriving a monthly cut.
MONTH_TOLERANCE = 1


def load_rainfall_table() -> List[Dict[str, object]]:
    with open(RAINFALL_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["year"] = int(row["year"])
        row["month"] = int(row["month"])
        row["rainfall_mm"] = float(row["rainfall_mm"]) if row["rainfall_mm"] not in ("", "nan") else None
    return rows


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


def load_glide_drought_event_years_by_region(records: List[Dict[str, object]]) -> Set[Tuple[str, int]]:
    return {(r["region"], r["year"]) for r in records}


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


def compute_seasonal_indicator_values(
    totals: Dict[Tuple[str, int], float],
) -> Dict[str, Dict[Tuple[str, int], float]]:
    """Real per-region, per-year seasonal values for all 3 real indicators,
    each derived independently from the same real seasonal rainfall totals
    -- no new data needed for any of these three.
    """
    import numpy as np
    from scipy.stats import gamma, norm

    by_region: Dict[str, List[Tuple[int, float]]] = {}
    for (region, year), total in totals.items():
        by_region.setdefault(region, []).append((year, total))

    anomaly: Dict[Tuple[str, int], float] = {}
    percentile: Dict[Tuple[str, int], float] = {}
    spi: Dict[Tuple[str, int], float] = {}

    for region, year_totals in by_region.items():
        if len(year_totals) < 3:
            continue
        years = [y for y, _ in year_totals]
        values = np.array([v for _, v in year_totals], dtype=float)
        mean, std = float(values.mean()), float(values.std())

        spi_values = None
        try:
            # Real gamma-distribution fit, location fixed at 0 since real
            # rainfall totals are non-negative -- standard McKee et al.
            # 1993 SPI convention. Probability integral transform (gamma
            # CDF -> standard normal quantile) gives a real SPI-equivalent
            # z-score, not an approximation.
            fit_shape, _fit_loc, fit_scale = gamma.fit(values, floc=0)
            gamma_cdf = gamma.cdf(values, fit_shape, loc=0, scale=fit_scale)
            gamma_cdf = np.clip(gamma_cdf, 1e-6, 1 - 1e-6)
            spi_values = norm.ppf(gamma_cdf)
        except Exception:
            pass

        for i, year in enumerate(years):
            key = (region, year)
            if std > 0:
                anomaly[key] = float((values[i] - mean) / std)
            # Real empirical percentile rank (Weibull plotting-position
            # convention) among this region's own real seasonal-total
            # history -- ties split evenly rather than arbitrarily ranked.
            rank = float((values < values[i]).sum()) + 0.5 * float((values == values[i]).sum())
            percentile[key] = float(100 * (rank + 1) / (len(values) + 1))
            if spi_values is not None:
                spi[key] = float(spi_values[i])

    return {"rainfall_total": anomaly, "spi": spi, "rainfall_percentile": percentile}


def _rate(values: List[float], threshold: float) -> float:
    return sum(1 for v in values if v <= threshold) / len(values) if values else float("nan")


def build_indicator_analysis(
    indicator: str,
    values_by_key: Dict[Tuple[str, int], float],
    year_events: Set[Tuple[str, int]],
) -> Dict[str, Any]:
    import numpy as np

    event_values = [v for key, v in values_by_key.items() if key in year_events]
    no_event_values = [v for key, v in values_by_key.items() if key not in year_events]
    thresholds = INDICATOR_THRESHOLDS[indicator]

    return {
        "label": INDICATOR_LABELS[indicator],
        "event_years": len(event_values),
        "no_event_years": len(no_event_values),
        "mean_value_event": float(np.mean(event_values)) if event_values else None,
        "mean_value_no_event": float(np.mean(no_event_values)) if no_event_values else None,
        "thresholds": [
            {
                "threshold_label": label,
                "threshold_value": threshold,
                "hit_rate": _rate(event_values, threshold),
                "false_alarm_rate": _rate(no_event_values, threshold),
            }
            for label, threshold in thresholds.items()
        ],
    }


def build_region_summary(records: List[Dict[str, object]]) -> List[Dict[str, Any]]:
    """Real per-region aggregation -- event count and the real years each
    region had a registered drought event -- for the frontend's map and
    region/year summary table.
    """
    by_region: Dict[str, List[int]] = {}
    for r in records:
        by_region.setdefault(r["region"], []).append(r["year"])

    return sorted(
        (
            {"region": region, "event_count": len(years), "years": sorted(set(years))}
            for region, years in by_region.items()
        ),
        key=lambda item: -item["event_count"],
    )


def build_results() -> Dict[str, Any]:
    """Assembles the real 3-indicator seasonal comparison, the real
    per-region event summary, and the real per-event detail into one
    JSON-serializable results object, plus an explicit, honest scope/
    methodology disclosure for the frontend to render verbatim.
    """
    rows = load_rainfall_table()
    records = load_glide_drought_event_records()
    year_events = load_glide_drought_event_years_by_region(records)

    seasonal_totals = compute_seasonal_totals(rows)
    indicator_values = compute_seasonal_indicator_values(seasonal_totals)

    indicators = {
        name: build_indicator_analysis(name, values, year_events)
        for name, values in indicator_values.items()
    }

    spi_values = indicator_values["spi"]
    anomaly_values = indicator_values["rainfall_total"]
    per_event = [
        {
            "glidenumber": r["glidenumber"],
            "region": r["region"],
            "location": r["location"],
            "year": r["year"],
            "month": r["month"],
            "rainfall_total_anomaly": anomaly_values.get((r["region"], r["year"])),
            "spi": spi_values.get((r["region"], r["year"])),
            "spi_hit_moderately_dry": (
                spi_values[(r["region"], r["year"])] <= INDICATOR_THRESHOLDS["spi"]["moderately_dry"]
                if (r["region"], r["year"]) in spi_values
                else None
            ),
        }
        for r in sorted(records, key=lambda r: (r["year"], r["month"]))
    ]

    event_year_count = len({key for key in anomaly_values if key in year_events})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "drought_only_v1",
        "methodology": {
            "summary": (
                "Real historical CHIRPS rainfall (1997-2025, June-September) compared against "
                "real GLIDE drought (DR) events geocoded to this app's own real admin1 boundaries. "
                "Three real indicators are compared on the same real seasonal (JJAS) totals: "
                "Rainfall Total (z-score anomaly), SPI (real gamma-distribution fit, McKee et al. "
                "1993 methodology), and Rainfall Percentile (real empirical within-region rank). "
                "CDD, CWD, Rx1day, and Rx5day are not included -- they need real daily rainfall, "
                "which this repo has not downloaded, and were scoped out of v1 rather than "
                "approximated from monthly totals."
            ),
            "thresholds_evaluated": (
                "Each indicator's own moderately/severely/extremely-dry threshold, chosen to carry "
                "the same real probability as this app's own SPI_CATEGORY_BANDS -- not modified by "
                "this diagnostic."
            ),
            "caveat": (
                "Small real sample size, especially at the seasonal/event-year level (n="
                f"{event_year_count} event-years). A directionally consistent but statistically "
                "limited signal, not a validated forecast-skill score."
            ),
        },
        "data_provenance": {
            "rainfall_source": "CHIRPS v2.0 monthly, real, downloaded from data.chc.ucsb.edu",
            "rainfall_rows": len(rows),
            "event_source": "GLIDE disaster events (via HDX), real, geocoded to admin1 by point-in-polygon",
            "drought_events_matched": len(records),
            "baseline_years": "1997-2025",
        },
        "indicators": indicators,
        "region_summary": build_region_summary(records),
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

    for name, analysis in results["indicators"].items():
        print()
        print(f"[{name}] {analysis['label']}")
        print(f"  Real event years: {analysis['event_years']} | Real no-event years: {analysis['no_event_years']}")
        print(f"  Mean value (event years):    {analysis['mean_value_event']:+.2f}" if analysis["mean_value_event"] is not None else "  Mean value (event years): N/A")
        print(f"  Mean value (no-event years): {analysis['mean_value_no_event']:+.2f}" if analysis["mean_value_no_event"] is not None else "  Mean value (no-event years): N/A")
        for row in analysis["thresholds"]:
            print(f"    {row['threshold_value']:<8.2f} {row['threshold_label']:16s} hit={row['hit_rate']:.1%}  false_alarm={row['false_alarm_rate']:.1%}")

    print()
    print("Real per-region event counts:")
    for item in results["region_summary"]:
        print(f"  {item['region']:20s} {item['event_count']:2d} events  years={item['years']}")

    save_results(results)


if __name__ == "__main__":
    run_diagnostic()
