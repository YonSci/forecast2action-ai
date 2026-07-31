// Shared community-ground-truth-report helpers -- used by both
// SelectedAreaCommunityReports.jsx (the full submission form + list) and
// SelectedAreaAdvisory.jsx (a compact read-only summary for the same
// selected area). Moved out of the component file because co-locating
// plain functions in a component file breaks Vite Fast Refresh
// (react-refresh/only-export-components) -- same reasoning as
// rankingMetricFormatters.js.

// Kept in sync with the backend's canonical CANONICAL_REPORT_TYPES
// (app/api/community_reports_store.py) -- the backend aliases a few older
// stored values (pasture_poor/flooded_road/disease_concern/
// market_disruption) onto these canonical ones at read time, so this list
// only needs the canonical set.
export const REPORT_TYPES = [
  { value: "water_shortage", label: "Water shortage / water point stress" },
  { value: "crop_wilting", label: "Crop wilting / crop stress" },
  { value: "pasture_stress", label: "Pasture stress" },
  { value: "livestock_stress", label: "Livestock stress" },
  { value: "flooding", label: "Flooding / water logging" },
  { value: "river_overflow", label: "River overflow" },
  { value: "road_disruption", label: "Road or access disruption" },
  { value: "unusual_heat", label: "Unusual heat" },
  { value: "health_or_disease", label: "Health or disease concern" },
  { value: "food_price_increase", label: "Food or livestock price pressure" },
  { value: "no_impact_observed", label: "No impact observed yet" },
  { value: "other", label: "Other local observation" },
];

function reportTitleCase(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

  return String(value)
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (text) => {
      return text.charAt(0).toUpperCase() + text.substring(1).toLowerCase();
    });
}

export function getReportTypeLabel(value) {
  return REPORT_TYPES.find((item) => item.value === value)?.label || reportTitleCase(value);
}

export function getSeverityClass(severity) {
  if (severity === "severe") return "severity-severe";
  if (severity === "high") return "severity-high";
  if (severity === "moderate") return "severity-moderate";
  return "severity-low";
}

// Same "3+ high/severe = strong, 1-2 = emerging, 0 = low" thresholds
// already used server-side (feedback_boost in app/api/main.py's
// get_priority_actions) -- kept consistent rather than inventing separate
// client-side cutoffs.
export function getSignalSummary(reports) {
  const total = reports.length;

  if (total === 0) {
    return {
      total,
      highOrSevere: 0,
      latest: null,
      signal: "No ground reports yet",
      className: "ground-signal-none",
    };
  }

  const highOrSevere = reports.filter((report) =>
    ["high", "severe"].includes(report.severity),
  ).length;

  const latest = reports[0];

  if (highOrSevere >= 3) {
    return {
      total,
      highOrSevere,
      latest,
      signal: "Strong ground signal",
      className: "ground-signal-strong",
    };
  }

  if (highOrSevere >= 1) {
    return {
      total,
      highOrSevere,
      latest,
      signal: "Emerging ground signal",
      className: "ground-signal-emerging",
    };
  }

  return {
    total,
    highOrSevere,
    latest,
    signal: "Low ground signal",
    className: "ground-signal-low",
  };
}
