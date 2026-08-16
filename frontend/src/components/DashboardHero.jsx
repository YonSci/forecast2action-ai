import { Link } from "react-router-dom";
import "../styles/dashboardHeroFinal.css";

const DEFAULT_COUNTS = {
  trigger: 3,
  priorityInterventions: 3,
  communityReports: 1,
};

const LEAD_LABELS = {
  week_1: "Week 1",
  week_2: "Week 2",
  week_3: "Week 3",
  week_4: "Week 4",
  week_1_2: "Week 1-2",
  week_2_3: "Week 2-3",
  week_3_4: "Week 3-4",
  month_1: "Month 1",
  month_2: "Month 2",
  month_3: "Month 3",
  month_4: "Month 4",
  month_5: "Month 5",
  month_6: "Month 6",
};

const FORECAST_SCALE_LABELS = {
  subseasonal: "Subseasonal",
  seasonal: "Seasonal",
};

function titleCase(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

  return String(value)
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (text) => {
      return text.charAt(0).toUpperCase() + text.substring(1).toLowerCase();
    });
}

function getLeadLabel(value) {
  return LEAD_LABELS[value] || titleCase(value || "week_1");
}

function getForecastScaleLabel(value) {
  return FORECAST_SCALE_LABELS[value] || titleCase(value || "subseasonal");
}

function getCommunityReportCount(communityReports, fallbackValue) {
  if (Array.isArray(communityReports)) {
    return communityReports.length;
  }

  if (Number.isFinite(Number(communityReports))) {
    return Number(communityReports);
  }

  return fallbackValue;
}

function getPriorityCount(value) {
  if (Array.isArray(value)) {
    return value.length;
  }

  if (Number.isFinite(Number(value))) {
    return Number(value);
  }

  return DEFAULT_COUNTS.priorityInterventions;
}

function getSelectedAreaName(selectedPriorityArea, topRankedArea) {
  return (
    selectedPriorityArea?.area_name || topRankedArea?.area_name || "N/A"
  );
}

function getSelectedAreaSubtitle(selectedPriorityArea, topRankedArea) {
  const area = selectedPriorityArea?.area_name
    ? selectedPriorityArea
    : topRankedArea;

  if (!area?.area_name) {
    return "";
  }

  if (area.zone && area.region) {
    return `${area.zone} · ${area.region}`;
  }

  if (area.region) {
    return area.region;
  }

  return titleCase(area.admin_level || "selected area");
}

function IconLayers() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3 2.7 8.2 12 13.4l9.3-5.2L12 3Z" />
      <path d="m4.7 12.1 7.3 4.1 7.3-4.1" />
      <path d="m4.7 16.2 7.3 4.1 7.3-4.1" />
    </svg>
  );
}

function IconPin() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 21s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12Z" />
      <circle cx="12" cy="9" r="2.5" />
    </svg>
  );
}

function IconUsers() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2.5 21a6.5 6.5 0 0 1 13 0" />
      <path d="M17 10a3.3 3.3 0 1 0 0-6.6M16 14.2A5.8 5.8 0 0 1 21.5 20" />
    </svg>
  );
}

function IconGlobe() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.3 2.5 3.5 5.5 3.5 9S14.3 18.5 12 21M12 3c-2.3 2.5-3.5 5.5-3.5 9s1.2 6.5 3.5 9" />
    </svg>
  );
}

function IconCalendar() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 4h14a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" />
      <path d="M8 2v4M16 2v4M3 9h18" />
    </svg>
  );
}

function IconAlert() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3 22 20H2L12 3Z" />
      <path d="M12 9v5M12 17.5v.1" />
    </svg>
  );
}

function IconTarget() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </svg>
  );
}

function IconFileDown() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z" />
      <path d="M14 2v6h6" />
      <path d="M12 11v7M9 15l3 3 3-3" />
    </svg>
  );
}

function IconSparkle() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
      <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z" />
    </svg>
  );
}

function WorkflowPill({ icon, label, tone }) {
  return (
    <div className={`f2a-workflow-pill ${tone}`}>
      <span>{icon}</span>
      <strong>{label}</strong>
    </div>
  );
}

function KpiCard({ icon, label, value, subtitle, tone, trend }) {
  return (
    <article className={`f2a-kpi-card ${tone}`}>
      <div className="f2a-kpi-top">
        <span className="f2a-kpi-icon">{icon}</span>
        <i />
      </div>

      <span className="f2a-kpi-label">{label}</span>
      <strong className="f2a-kpi-value">{value}</strong>

      {subtitle && <p>{subtitle}</p>}
      {trend && <small>{trend}</small>}
    </article>
  );
}

function EthiopiaRiskImage() {
  return (
    <div className="f2a-ethiopia-risk-image" aria-hidden="true">
      <img src="/assets/ethiopia-risk-map.png" alt="" />
    </div>
  );
}

function RainRadar() {
  return (
    <div className="f2a-rain-radar" aria-hidden="true">
      <svg viewBox="0 0 64 64">
        <path d="M24 37h24a10 10 0 0 0 0-20 16 16 0 0 0-30-3A12 12 0 0 0 24 37Z" />
        <path d="M22 46v6M34 46v6M46 46v6" />
      </svg>
    </div>
  );
}

function HeroPanel({ title, children }) {
  return (
    <div className="f2a-hero-panel">
      <span>{title}</span>
      {children}
    </div>
  );
}

function DashboardHero({
  communityReports = [],
  communityReportCount = null,
  selectedPriorityArea = null,
  forecastSelection = {},
  priorityInterventionCount = DEFAULT_COUNTS.priorityInterventions,
  triggerAlertCount = null,
  topRankedArea = null,
}) {
  const triggerCount = Number.isFinite(Number(triggerAlertCount))
    ? Number(triggerAlertCount)
    : DEFAULT_COUNTS.trigger;

  const priorityCount = getPriorityCount(priorityInterventionCount);

  const reportsCount = getCommunityReportCount(
    communityReportCount ?? communityReports,
    DEFAULT_COUNTS.communityReports,
  );

  const selectedAreaName = getSelectedAreaName(
    selectedPriorityArea,
    topRankedArea,
  );
  const selectedAreaSubtitle = getSelectedAreaSubtitle(
    selectedPriorityArea,
    topRankedArea,
  );
  const forecastScale =
    forecastSelection.seasonalScaleLabel ||
    getForecastScaleLabel(forecastSelection.forecastScale);
  const lead =
    forecastSelection.seasonalPeriodLabel || getLeadLabel(forecastSelection.lead);

  return (
    <section className="f2a-dashboard-hero">
      <div className="f2a-hero-banner">
        <div className="f2a-hero-bg-grid" />
        <div className="f2a-hero-contours" />

        <div className="f2a-hero-copy">
          <Link to="/" className="f2a-back-link">
            ← Back to home
          </Link>

          <h1>Forecast2Action AI</h1>

          <p>
            Convert climate-risk signals into actionable insights. Latest
            enhancements deliver forecast risk layers, priority intervention
            areas, selected-area advisory, SMS-ready messages, action tracking,
            and community ground-truth reporting.
          </p>
        </div>

        <div className="f2a-hero-visual">
          <RainRadar />
          <EthiopiaRiskImage />

          <div className="f2a-hero-panels">
            <HeroPanel title="Risk signal">
              <div className="f2a-bars">
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
              </div>
            </HeroPanel>

            <HeroPanel title="Confidence">
              <strong>High</strong>
              <b>✓</b>
            </HeroPanel>

            <HeroPanel title="Updated">
              <strong>2h ago</strong>
              <b>◷</b>
            </HeroPanel>
          </div>
        </div>

        <div className="f2a-workflow-row">
          <WorkflowPill
            icon={<IconLayers />}
            label="Climate indicators"
            tone="blue"
          />
          <em>›</em>
          <WorkflowPill
            icon={<IconAlert />}
            label="Risk layers"
            tone="red"
          />
          <em>›</em>
          <WorkflowPill
            icon={<IconPin />}
            label="Priority areas"
            tone="green"
          />
          <em>›</em>
          <WorkflowPill
            icon={<IconUsers />}
            label="Ground-truth reports"
            tone="cyan"
          />
          <em>›</em>
          <WorkflowPill
            icon={<IconSparkle />}
            label="AI-based interpretation & advisory"
            tone="purple"
          />
          <em>›</em>
          <WorkflowPill
            icon={<IconFileDown />}
            label="Bulletin generation"
            tone="amber"
          />
        </div>
      </div>

      <div className="f2a-kpi-grid">
        <KpiCard
          icon={<IconGlobe />}
          label="Forecast domain"
          value="Ethiopia"
          subtitle="Lat 3–15°N · Lon 33–48°E"
          tone="blue"
        />

        <KpiCard
          icon={<IconCalendar />}
          label="Active horizon"
          value={forecastScale}
          subtitle={`• ${lead}`}
          tone="blue"
        />

        <KpiCard
          icon={<IconAlert />}
          label="Trigger alerts"
          value={triggerCount}
          subtitle="Areas above trigger threshold"
          tone="red"
        />

        <KpiCard
          icon={<IconPin />}
          label="Priority intervention areas"
          value={priorityCount}
          subtitle="Top ranked areas"
          tone="purple"
        />

        <KpiCard
          icon={<IconTarget />}
          label="Selected active area"
          value={selectedAreaName}
          subtitle={selectedAreaSubtitle}
          tone="blue"
        />

        <KpiCard
          icon={<IconUsers />}
          label="Community reports"
          value={reportsCount}
          subtitle="New submissions"
          tone="green"
        />
      </div>
    </section>
  );
}

export default DashboardHero;
