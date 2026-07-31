// Priority Intervention Areas' priority_score (0-1, from
// app/api/hazard_risk_ranking.py) classified into the same
// Trigger/Warning/Watch/No alert vocabulary and thresholds as
// app/ml/risk_scoring.py's RISK_THRESHOLDS, for consistency with the rest of
// the app's alerting language. Shared here (not duplicated per component) so
// TopInterventionAreas.jsx's table and RiskMap.jsx's legend/fill color always
// agree on what each level means and looks like.
export const PRIORITY_THRESHOLDS = {
  trigger: 0.8,
  warning: 0.6,
  watch: 0.35,
};

export const PRIORITY_LEVELS = [
  { level: "trigger", label: "Trigger", color: "#D92D20", className: "priority-high" },
  { level: "warning", label: "Warning", color: "#C11574", className: "priority-medium" },
  { level: "watch", label: "Watch", color: "#F79009", className: "priority-watch" },
  { level: "no_alert", label: "No alert", color: "#12B76A", className: "priority-low" },
];

export function getPriorityLevel(score) {
  const value = Number(score);

  if (!Number.isFinite(value)) {
    return PRIORITY_LEVELS[3];
  }

  if (value >= PRIORITY_THRESHOLDS.trigger) {
    return PRIORITY_LEVELS[0];
  }

  if (value >= PRIORITY_THRESHOLDS.warning) {
    return PRIORITY_LEVELS[1];
  }

  if (value >= PRIORITY_THRESHOLDS.watch) {
    return PRIORITY_LEVELS[2];
  }

  return PRIORITY_LEVELS[3];
}

const LEVEL_ORDER = ["trigger", "warning", "watch", "no_alert"];
const LEVEL_INFO_BY_LEVEL = Object.fromEntries(
  PRIORITY_LEVELS.map((entry) => [entry.level, entry]),
);

// Looks up display info (label/color/className) for a level string the
// backend already classified -- used for drought_risk.level/wet_risk.level
// (app/api/hazard_risk_ranking.py's raw_layer_classification_thresholds),
// which replaced priority_score as the real Trigger/Warning/Watch/No alert
// criterion. Same 4-level vocabulary as PRIORITY_LEVELS, so the visual
// language (colors, labels) stays identical -- only the input changed from
// a normalized composite score to each hazard's own raw risk value.
export function getLevelInfo(level) {
  return LEVEL_INFO_BY_LEVEL[level] || PRIORITY_LEVELS[3];
}

// Single combined level for UI slots that only have room for one status
// (the advisory hero pill, the dashboard's trigger-count KPI) -- the more
// severe of drought_risk.level/wet_risk.level, since an area facing either
// a drought or a wet-hazard trigger is genuinely at trigger level overall.
// The Priority Intervention Areas table itself shows both badges
// separately rather than collapsing them (more informative when there's
// room for two columns).
export function combineDroughtWetLevel(item) {
  const droughtLevel = item?.drought_risk?.level || "no_alert";
  const wetLevel = item?.wet_risk?.level || "no_alert";

  const droughtRank = LEVEL_ORDER.indexOf(droughtLevel);
  const wetRank = LEVEL_ORDER.indexOf(wetLevel);
  const bestRank = Math.min(
    droughtRank === -1 ? LEVEL_ORDER.length : droughtRank,
    wetRank === -1 ? LEVEL_ORDER.length : wetRank,
  );

  return getLevelInfo(LEVEL_ORDER[bestRank] || "no_alert");
}
