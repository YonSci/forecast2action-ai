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
