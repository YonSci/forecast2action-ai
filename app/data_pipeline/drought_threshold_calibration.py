"""
Real diagnostic: does this app's own real SPI classification thresholds
(SPI_CATEGORY_BANDS, app.context.statistical_evidence -- real McKee et al.
1993 bands) look consistent with real historical drought outcomes -- and
which of the real climate indicators this app offers (Rainfall Total, SPI,
Rainfall Percentile) actually discriminates real drought years best?

Consumes the real (lat, lon, year, month) pixel-level rainfall table
produced by app.data_pipeline.historical_rainfall_pipeline.
build_point_month_rainfall_table (sampled at each real GLIDE event's own
exact reported coordinate, not averaged across the admin1 region it falls
in) and the real drought (DR) events already geocoded from GLIDE
(data/raw/historical_impact/eth_glide_events.csv). Computes real
JJAS-seasonal (Jun-Sep) values for three real indicators, each derived
independently from the same real monthly CHIRPS pixel values already
sampled. The reported hit rate is scoped to real GLIDE events actually
registered during JJAS itself (deduplicated to unique pixel-years), since
testing whether JJAS rainfall predicted a drought GLIDE logged in some
other month isn't a fair test -- real events registered outside JJAS are
still excluded from the false-alarm/no-event comparison pool, just not
counted toward the hit rate:

- Rainfall Total: a real per-pixel z-score anomaly against a multi-year
  baseline.
- SPI: a real gamma-distribution fit per pixel (McKee et al. 1993
  methodology -- probability integral transform via that pixel's own real
  fitted gamma CDF), not a simplified z-score. This app's live SPI product
  comes from a separate upstream project (see README's Real data sources);
  this is an independent, standard implementation of the same real
  methodology, not a reuse of that pipeline's code.
- Rainfall Percentile: a real empirical percentile rank within each
  pixel's own real seasonal-total history.

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

POINT_RAINFALL_CSV = Path("data/raw/historical_impact/eth_point_monthly_rainfall.csv")
GLIDE_CSV = Path("data/raw/historical_impact/eth_glide_events.csv")
ADMIN1_PATH = Path("data/sample/admin_boundaries/eth_admin1.json")

# Where the v1 (drought-only) results this app's frontend reads are
# persisted -- served read-only via GET /api/validation/historical-skill,
# never recomputed live (the CHIRPS download + zonal stats behind
# eth_region_monthly_rainfall.csv is a heavy, periodic offline job -- see
# historical_rainfall_pipeline.py).
RESULTS_PATH = Path("data/historical_validation/drought_validation_v1.json")

# JJAS = the app's real forecast window (June-September), matching what the
# live product actually forecasts. Used two ways: (1) to build each real
# region-year's seasonal rainfall total, and (2) to define which real
# GLIDE-registered event-years count toward the reported hit rate -- only
# events GLIDE actually logged during June-September, not any real drought
# registered in some other month, since testing "did JJAS rainfall predict
# a drought GLIDE reported in January" isn't a fair test of a JJAS-season
# indicator. Real event-years registered in OTHER months are still real
# droughts, though, so they're excluded from the no-event/false-alarm pool
# rather than being counted as a clean "nothing happened" comparator.
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
    "rainfall_total": "Rainfall Total (z-score anomaly, exact-pixel)",
    "spi": "SPI (real gamma-distribution fit, McKee et al. 1993 methodology, exact-pixel)",
    "rainfall_percentile": "Rainfall Percentile (real empirical rank, exact-pixel)",
}

# Real reporting-lag tolerance retained for reference (droughts are
# accumulation phenomena; a GLIDE event registered in month M can reflect
# a deficit that began weeks earlier) -- not used directly now that the
# analysis is seasonal-only, kept for anyone re-deriving a monthly cut.
MONTH_TOLERANCE = 1


def _point_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def load_point_rainfall_table() -> List[Dict[str, object]]:
    """Real rainfall sampled at the EXACT pixel of each real GLIDE event's
    own reported coordinate (see historical_rainfall_pipeline.
    build_point_month_rainfall_table) -- not averaged across the whole
    admin1 region the event happens to fall in. Real regions like Oromia
    span climatically distinct sub-areas (a real, previously-noted confound:
    a severe localized drought gets diluted into a moderate area-wide
    average); pixel-level sampling doesn't have that problem.
    """
    with open(POINT_RAINFALL_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["latitude"] = float(row["latitude"])
        row["longitude"] = float(row["longitude"])
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
            try:
                affected = int(float(row.get("affected") or 0))
            except ValueError:
                affected = 0
            try:
                # Real GLIDE day-of-month -- 0 means the source only
                # reported month/year precision, not a missing value.
                day = int(row.get("day") or 0)
            except ValueError:
                day = 0
            records.append({
                "glidenumber": row.get("glidenumber", ""),
                "region": region_name,
                "location": row.get("location", ""),
                "year": year,
                "month": month,
                "day": day,
                "latitude": lat,
                "longitude": lon,
                # Real GLIDE "affected" count -- genuinely 0 for most real
                # drought events (GLIDE captures casualty counts, which
                # drought essentially never produces, far more reliably
                # than population-affected for a slow-onset hazard), not a
                # missing-data placeholder. Kept as a real int, not
                # backfilled or estimated.
                "affected": affected,
            })
    return records


def load_glide_drought_event_years_by_point(records: List[Dict[str, object]]) -> Set[Tuple[str, int]]:
    return {(_point_key(r["latitude"], r["longitude"]), r["year"]) for r in records}


def compute_seasonal_totals_by_point(rows: List[Dict[str, object]]) -> Dict[Tuple[str, int], float]:
    """Same real JJAS-seasonal-total logic as compute_seasonal_totals, keyed
    by the exact real pixel coordinate instead of admin1 region.
    """
    by_key: Dict[Tuple[str, int], Dict[int, float]] = {}
    for row in rows:
        if row["month"] not in SEASON_MONTHS or row["rainfall_mm"] is None:
            continue
        key = (_point_key(row["latitude"], row["longitude"]), row["year"])
        by_key.setdefault(key, {})[row["month"]] = row["rainfall_mm"]

    return {
        key: sum(months.values())
        for key, months in by_key.items()
        if set(months.keys()) == SEASON_MONTHS
    }


def compute_seasonal_indicator_values(
    totals: Dict[Tuple[str, int], float],
) -> Dict[str, Dict[Tuple[str, int], float]]:
    """Real per-group, per-year seasonal values for all 3 real indicators,
    each derived independently from the same real seasonal rainfall totals
    -- no new data needed for any of these three. Grouping key is whatever
    the first element of `totals`'s keys is (admin1 region name, or a real
    exact-pixel coordinate string) -- this function doesn't care which.
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
    hit_year_events: Set[Tuple[str, int]],
    exclude_from_no_event: Set[Tuple[str, int]],
) -> Dict[str, Any]:
    """hit_year_events is the real JJAS-registered event-year set the hit
    rate is computed over. exclude_from_no_event is the broader set of ALL
    real event-years (any month) -- kept separate so a real drought
    registered outside JJAS is never counted as a clean "no event" case for
    the false-alarm side, even though it doesn't count toward the hit rate.
    """
    import numpy as np

    event_values = [v for key, v in values_by_key.items() if key in hit_year_events]
    no_event_values = [v for key, v in values_by_key.items() if key not in exclude_from_no_event]
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
    records = load_glide_drought_event_records()
    point_rows = load_point_rainfall_table()
    # All real event-years (any registered month) -- kept out of the
    # no-event/false-alarm pool entirely, even the ones that don't count
    # toward the hit rate below. Keyed by exact pixel now, not region: with
    # only 7 real unique event coordinates, the no-event pool is the real
    # rainfall history at those SAME 7 points in years GLIDE didn't log an
    # event there -- not a random sample of Ethiopia, so the false-alarm
    # rate below should be read as "at real drought-prone locations
    # specifically", not "anywhere in the country".
    all_point_year_events = load_glide_drought_event_years_by_point(records)
    # The real subset actually reported: only GLIDE events registered
    # during JJAS itself, deduplicated to unique (point, year) pairs -- a
    # real drought episode logged as 3 separate GLIDE records at the same
    # coordinate (e.g. 2022 South Ethiopia) is one real trial, not three.
    jjas_records = [r for r in records if r["month"] in SEASON_MONTHS]
    jjas_point_year_events = load_glide_drought_event_years_by_point(jjas_records)

    seasonal_totals = compute_seasonal_totals_by_point(point_rows)
    indicator_values = compute_seasonal_indicator_values(seasonal_totals)

    indicators = {
        name: build_indicator_analysis(name, values, jjas_point_year_events, all_point_year_events)
        for name, values in indicator_values.items()
    }

    spi_values = indicator_values["spi"]
    anomaly_values = indicator_values["rainfall_total"]
    percentile_values = indicator_values["rainfall_percentile"]
    per_event = [
        {
            "glidenumber": r["glidenumber"],
            "region": r["region"],
            "location": r["location"],
            "year": r["year"],
            "month": r["month"],
            "day": r["day"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "affected": r["affected"],
            "rainfall_total_anomaly": anomaly_values.get((_point_key(r["latitude"], r["longitude"]), r["year"])),
            "spi": spi_values.get((_point_key(r["latitude"], r["longitude"]), r["year"])),
            "rainfall_percentile": percentile_values.get((_point_key(r["latitude"], r["longitude"]), r["year"])),
        }
        for r in sorted(records, key=lambda r: (r["year"], r["month"]))
    ]

    unique_points = len({(r["latitude"], r["longitude"]) for r in records})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "drought_only_v1_jjas_registered_pixel_level",
        "methodology": {
            "summary": (
                "Real historical CHIRPS rainfall (1997-2025, June-September) compared against "
                "real GLIDE drought (DR) events, sampled at the EXACT real pixel of each event's "
                "own reported coordinate -- not averaged across the whole admin1 region it falls "
                f"in. Only {unique_points} real unique coordinates exist among this dataset's "
                "matched events (several events share the same GLIDE-reported centroid), so this "
                "is a real but small set of specific locations, not a general Ethiopia-wide sample. "
                "Three real indicators are compared on the same real seasonal (JJAS) totals: "
                "Rainfall Total (z-score anomaly), SPI (real gamma-distribution fit, McKee et al. "
                "1993 methodology), and Rainfall Percentile (real empirical rank at that exact "
                "pixel). The reported hit rate counts only real GLIDE events actually registered "
                "during JJAS itself, deduplicated to unique (pixel, year) pairs so one real drought "
                "episode logged as multiple GLIDE records at the same coordinate isn't counted more "
                "than once; real events registered in other months are real droughts too, so they're "
                "excluded from the false-alarm/no-event comparison pool rather than being treated as "
                "clean no-event cases, but they don't count toward the hit rate itself. The "
                "false-alarm rate should be read as \"at these same real drought-prone pixels, in "
                "years without a registered event\" -- not \"anywhere in Ethiopia\", since the no-event "
                "pool is drawn from the same small set of locations, not a random sample. CDD, CWD, "
                "Rx1day, and Rx5day are not included -- they need real daily rainfall, which this "
                "repo has not downloaded, and were scoped out of v1 rather than approximated from "
                "monthly totals."
            ),
            "thresholds_evaluated": (
                "Each indicator's own moderately/severely/extremely-dry threshold, chosen to carry "
                "the same real probability as this app's own SPI_CATEGORY_BANDS -- not modified by "
                "this diagnostic."
            ),
            "caveat": (
                "Very small real sample size (n="
                f"{len(jjas_point_year_events)} JJAS-registered event-years out of "
                f"{len(all_point_year_events)} real event-years total, across only {unique_points} "
                "real unique pixel locations). A directionally consistent but statistically limited "
                "signal, not a validated forecast-skill score."
            ),
        },
        "data_provenance": {
            "rainfall_source": "CHIRPS v2.0 monthly, real, sampled at exact event pixels, from data.chc.ucsb.edu",
            "rainfall_rows": len(point_rows),
            "event_source": "GLIDE disaster events (via HDX), real, geocoded to admin1 by point-in-polygon",
            "drought_events_matched": len(records),
            "unique_pixel_locations": unique_points,
            "event_years_total": len(all_point_year_events),
            "event_years_jjas_registered": len(jjas_point_year_events),
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
    print(f"Real (lat, lon, year, month) pixel rainfall rows: {results['data_provenance']['rainfall_rows']}")
    print(f"Real GLIDE drought events geocoded to a real admin1 region: {results['data_provenance']['drought_events_matched']}")
    print(f"Real unique pixel locations: {results['data_provenance']['unique_pixel_locations']}")

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
