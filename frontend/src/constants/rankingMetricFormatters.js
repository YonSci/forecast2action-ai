// Shared display-formatting helpers for a Priority Intervention Areas
// ranking `item` (see app/api/hazard_risk_ranking.py's compute_district_
// ranking). Used by both TopInterventionAreas.jsx's table/popup metrics
// and RiskMap.jsx's ranked-area marker tooltips, so the two stay
// consistent -- moved out of TopInterventionAreas.jsx (a component file)
// into its own module because co-locating plain functions in a component
// file breaks Vite Fast Refresh (react-refresh/only-export-components).

const RISK_CLASS_LABELS = ["Very low", "Low", "Moderate", "High", "Very high"];

export function formatMetricValue(value, layerMeta) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "N/A";
  }

  if (!layerMeta) {
    return numberValue.toFixed(2);
  }

  if (layerMeta.units === "score") {
    return `${numberValue.toFixed(1)} / 100`;
  }

  if (layerMeta.units === "probability") {
    return `${(numberValue * 100).toFixed(1)}%`;
  }

  if (layerMeta.is_categorical) {
    const index = Math.max(
      0,
      Math.min(RISK_CLASS_LABELS.length - 1, Math.round(numberValue)),
    );
    return `${RISK_CLASS_LABELS[index]} (avg ${numberValue.toFixed(2)})`;
  }

  return numberValue.toFixed(2);
}

// Real WorldPop-derived person count within the area where the currently
// ranked metric exceeds its threshold, not a per-pixel index -- see
// app/api/hazard_risk_ranking.py's population_stats_for_all_districts.
export function formatPopulationExposed(item) {
  if (!Number.isFinite(Number(item.population_exposed))) {
    return "N/A";
  }

  const count = Number(item.population_exposed).toLocaleString();
  const pct = Number.isFinite(Number(item.population_exposed_pct))
    ? `${Number(item.population_exposed_pct).toFixed(1)}%`
    : "N/A";

  return `${count} (${pct})`;
}

// Real ground area (km^2, area-weighted for latitude) where the currently
// ranked metric exceeds its threshold.
export function formatAreaExtent(item) {
  if (!Number.isFinite(Number(item.area_extent_km2))) {
    return "N/A";
  }

  const area = `${Number(item.area_extent_km2).toLocaleString()} km²`;
  const pct = Number.isFinite(Number(item.area_extent_pct))
    ? `${Number(item.area_extent_pct).toFixed(1)}%`
    : "N/A";

  return `${area} (${pct})`;
}

// % of district area only (not km^2) -- the only real source for this
// layer is a coarse (0.25-degree) normalized 0-1 index with no documented
// real-world units, so a literal cropland hectare/km^2 figure would be a
// guess dressed up as precision. See getTermDefinition/CROPLAND_EXTENT
// entry in hazardRiskGlossary.js.
export function formatCroplandExtentPct(item) {
  if (!Number.isFinite(Number(item.cropland_extent_pct))) {
    return "N/A";
  }

  return `${Number(item.cropland_extent_pct).toFixed(1)}%`;
}

// Same reasoning/precision caveat as formatCroplandExtentPct -- livestock
// (GLW4 cattle density), built-up (WorldPop/GHSL-derived), and roads
// (OSM-derived) are all coarse normalized 0-1 indices too, so these stay a
// % of district area, not a fabricated head-count/km^2 figure.
export function formatLivestockExtentPct(item) {
  if (!Number.isFinite(Number(item.livestock_extent_pct))) {
    return "N/A";
  }

  return `${Number(item.livestock_extent_pct).toFixed(1)}%`;
}

export function formatBuiltUpExtentPct(item) {
  if (!Number.isFinite(Number(item.built_up_extent_pct))) {
    return "N/A";
  }

  return `${Number(item.built_up_extent_pct).toFixed(1)}%`;
}

export function formatRoadsExtentPct(item) {
  if (!Number.isFinite(Number(item.roads_extent_pct))) {
    return "N/A";
  }

  return `${Number(item.roads_extent_pct).toFixed(1)}%`;
}
