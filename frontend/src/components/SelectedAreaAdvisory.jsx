import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";
import { getCurrentSeasonalPeriod } from "../constants/climateIndicators.js";
import { getReportTypeLabel, getSignalSummary } from "../constants/communityReports.js";
import { getLevelInfo } from "../constants/priorityLevels.js";

// suffix/digits for formatting each real climate indicator fetched from
// /api/seasonal-raster/area-indicator-stats (see below) -- purely display
// formatting, not part of the real computed value.
const INDICATOR_DISPLAY_FORMAT = {
  rainfall_total: { suffix: " mm", digits: 1 },
  spi: { suffix: "", digits: 2 },
  rainfall_anomaly_pct: { suffix: "%", digits: 1 },
  rainfall_percentile: { suffix: "", digits: 1 },
  rx1day: { suffix: " mm", digits: 1 },
  rx5day: { suffix: " mm", digits: 1 },
  cdd: { suffix: " days", digits: 1 },
  cwd: { suffix: " days", digits: 1 },
};

const FORECAST_SCALE_LABELS = {
  subseasonal: "Subseasonal",
  seasonal: "Seasonal",
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

const LANGUAGE_LABELS = {
  en: "English",
  am: "Amharic",
  sw: "Swahili",
};

const CLIMATE_INDICATORS = [
  {
    key: "rainfall_total",
    shortLabel: "Rainfall total",
    label: "Rainfall total",
    description: "Total forecast rainfall for the period.",
  },
  {
    key: "spi",
    shortLabel: "SPI",
    label: "Standardized Precipitation Index",
    description: "Standardized rainfall deficit or surplus signal.",
  },
  {
    key: "rainfall_anomaly_pct",
    shortLabel: "Rainfall anomaly",
    label: "Rainfall anomaly",
    description: "Departure from normal rainfall conditions.",
  },
  {
    key: "rainfall_percentile",
    shortLabel: "Rainfall percentile",
    label: "Rainfall percentile",
    description: "How unusual the rainfall is compared with historical conditions.",
  },
  {
    key: "rx1day",
    shortLabel: "Rx1day",
    label: "Max 1-day rainfall",
    description: "Highest single-day rainfall total expected in the period.",
  },
  {
    key: "rx5day",
    shortLabel: "Rx5day",
    label: "Max 5-day rainfall",
    description: "Highest consecutive 5-day rainfall total expected in the period.",
  },
  {
    key: "cdd",
    shortLabel: "CDD",
    label: "Consecutive dry days",
    description: "Length of dry-spell persistence.",
  },
  {
    key: "cwd",
    shortLabel: "CWD",
    label: "Consecutive wet days",
    description: "Length of wet-spell persistence.",
  },
];

function titleCase(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (text) => text.charAt(0).toUpperCase() + text.substring(1).toLowerCase());
}

function formatNumber(value, digits = 3) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return "N/A";
  return numberValue.toFixed(digits);
}

function getAdminLevelLabel(level) {
  if (level === "admin1") return "Region";
  if (level === "admin2") return "Zone";
  if (level === "admin3") return "Woreda";
  return titleCase(level);
}

function getForecastScaleLabel(value) {
  return FORECAST_SCALE_LABELS[value] || titleCase(value || "subseasonal");
}

function getLeadLabel(value) {
  return LEAD_LABELS[value] || titleCase(value || "week_1");
}

// forecastSelection.lead is an internal engineering label (week_1, month_2,
// ...) derived from whichever real calendar period is actually selected in
// the Seasonal Climate Indices panel (ForecastLayerMap.jsx's
// deriveHazardLeadFromSeasonal) -- seasonalPeriod/seasonalPeriodLabel carry
// the real value (e.g. "July"), so prefer that for anything user-facing.
function getPeriodLabel(forecastSelection) {
  return (
    forecastSelection.seasonalPeriodLabel ||
    forecastSelection.seasonalPeriod ||
    getLeadLabel(forecastSelection.lead)
  );
}

function getIndicatorSummary(area, indicatorKey) {
  const summary = area?.climate_indicators?.[indicatorKey];
  if (summary) return summary;

  if (area?.selected_indicator === indicatorKey || area?.selected_indicator_label === indicatorKey) {
    return {
      mean: area?.selected_indicator_value,
      min: area?.selected_indicator_min,
      max: area?.selected_indicator_max,
      suffix: area?.selected_indicator_suffix || "",
      digits: area?.selected_indicator_digits ?? 2,
      count: null,
    };
  }

  return { mean: null, min: null, max: null, suffix: "", digits: 2, count: null };
}

function formatIndicatorValue(summary) {
  if (!summary || summary.mean === null || summary.mean === undefined) return "N/A";
  const digits = Number.isFinite(Number(summary.digits)) ? Number(summary.digits) : 2;
  return `${formatNumber(summary.mean, digits)}${summary.suffix || ""}`;
}

function formatIndicatorRange(summary) {
  if (!summary || summary.min === null || summary.max === null) return "N/A";
  if (summary.min === undefined || summary.max === undefined) return "N/A";
  const digits = Number.isFinite(Number(summary.digits)) ? Number(summary.digits) : 2;
  const suffix = summary.suffix || "";
  return `${formatNumber(summary.min, digits)}${suffix} to ${formatNumber(summary.max, digits)}${suffix}`;
}

function interpretIndicator(indicatorKey, summary) {
  const value = Number(summary?.mean);
  if (!Number.isFinite(value)) return "No indicator value available for this selected area.";

  if (indicatorKey === "rainfall_total") {
    return "Absolute forecast rainfall amount for the period.";
  }

  if (indicatorKey === "rx1day") {
    return "Peak single-day rainfall intensity signal.";
  }

  if (indicatorKey === "rx5day") {
    return "Peak multi-day rainfall accumulation signal.";
  }

  if (indicatorKey === "spi") {
    if (value <= -2) return "Extreme dry signal.";
    if (value <= -1.5) return "Severe dry signal.";
    if (value <= -1) return "Moderate dry signal.";
    if (value >= 1.5) return "Strong wet signal.";
    if (value >= 1) return "Moderate wet signal.";
    return "Near-normal standardized rainfall signal.";
  }

  if (indicatorKey === "rainfall_anomaly_pct") {
    if (value <= -40) return "Very large rainfall deficit.";
    if (value <= -25) return "Strong rainfall deficit.";
    if (value <= -10) return "Moderate rainfall deficit.";
    if (value >= 25) return "Strong rainfall surplus.";
    if (value >= 10) return "Moderate rainfall surplus.";
    return "Near-normal rainfall anomaly.";
  }

  if (indicatorKey === "rainfall_percentile") {
    if (value <= 10) return "Very dry lower-tail rainfall condition.";
    if (value <= 20) return "Dry lower-tail rainfall condition.";
    if (value >= 90) return "Very wet upper-tail rainfall condition.";
    if (value >= 80) return "Wet upper-tail rainfall condition.";
    return "Middle-range rainfall percentile.";
  }

  if (indicatorKey === "cdd") {
    if (value >= 20) return "Long dry-spell persistence.";
    if (value >= 10) return "Moderate dry-spell persistence.";
    return "Limited dry-spell persistence.";
  }

  if (indicatorKey === "cwd") {
    if (value >= 10) return "Persistent wet-spell signal.";
    if (value >= 5) return "Moderate wet-spell signal.";
    return "Limited wet-spell persistence.";
  }

  return "Climate indicator evidence for the selected area.";
}

function getAreaDisplayName(area) {
  if (!area) return "selected area";
  const parts = [area.area_name, area.region, area.zone].filter(Boolean);
  const uniqueParts = parts.filter((part, index) => parts.indexOf(part) === index);
  return uniqueParts.join(", ");
}

function getRiskActionPhrase(riskLevel) {
  if (riskLevel === "trigger") return "Immediate early action is needed";
  if (riskLevel === "warning") return "Prepare for possible impacts and verify local conditions";
  if (riskLevel === "watch") return "Monitor conditions and stay alert for updates";
  return "Continue routine monitoring";
}

function getHazardActionPhrase(hazard) {
  if (hazard === "drought" || hazard === "dry_spell") {
    return "save water, protect livestock, monitor pasture and crops, and report emerging stress";
  }
  if (hazard === "wet" || hazard === "heavy_rainfall" || hazard === "wet_spell" || hazard === "flood") {
    return "avoid flood-prone areas, clear drainage, protect assets, and follow local warnings";
  }
  if (hazard === "heat_stress" || hazard === "heat") {
    return "reduce heat exposure, protect vulnerable people and livestock, and ensure water availability";
  }
  return "follow local authority guidance and report observed impacts";
}

function buildAdvisoryText(area, forecastSelection) {
  const areaName = area.area_name || "the selected area";
  const period = getPeriodLabel(forecastSelection);
  const forecastScale = getForecastScaleLabel(forecastSelection.forecastScale);
  const hazard = titleCase(area.hazard);
  const riskLevel = titleCase(area.risk_level);
  const action = area.recommended_action || "Prioritize local verification, preparedness action, and coordination with responsible sectors.";

  return `${areaName} is identified as a ${riskLevel} priority area for ${period} under the ${forecastScale} forecast window. The main hazard signal is ${hazard}, with a risk score of ${formatNumber(area.risk_score)}, hazard probability of ${formatNumber(area.hazard_probability)}, exposure of ${formatNumber(area.exposure)}, and vulnerability of ${formatNumber(area.vulnerability)}. ${action}`;
}

function buildKeyMessage(area, forecastSelection) {
  const areaName = area.area_name || "the selected area";
  const period = getPeriodLabel(forecastSelection);
  const riskLevel = titleCase(area.risk_level);
  const hazard = titleCase(area.hazard);
  return `${areaName} requires ${riskLevel.toLowerCase()}-level attention for ${period}, mainly due to ${hazard.toLowerCase()} risk combined with exposure and vulnerability conditions.`;
}

function getSuggestedActions(area) {
  const riskLevel = area?.risk_level || "watch";
  const hazard = area?.hazard || "drought";

  if (riskLevel === "trigger") {
    return [
      "Verify local conditions with woreda, kebele, and community focal points.",
      "Activate early-action coordination with disaster risk management and sector offices.",
      "Pre-position critical resources for water, agriculture, livestock, and health support.",
      "Prepare targeted public advisory messages for affected communities.",
    ];
  }

  if (riskLevel === "warning") {
    return [
      "Increase local monitoring and confirm forecast signals with field reports.",
      "Prepare sector-specific readiness actions and contingency resources.",
      "Alert local authorities and partners to possible escalation.",
    ];
  }

  if (hazard === "wet" || hazard === "heavy_rainfall" || hazard === "wet_spell") {
    return [
      "Monitor flood-prone locations, roads, drainage, and low-lying settlements.",
      "Prepare local warning messages for heavy rainfall and access disruption.",
      "Coordinate with water, health, and disaster risk management actors.",
    ];
  }

  return [
    "Maintain monitoring and update the advisory as forecast confidence changes.",
    "Collect community feedback to validate whether local impacts are emerging.",
    "Review exposure and vulnerability hotspots for preparedness planning.",
  ];
}

function buildSmsMessage(area, forecastSelection, language = "en") {
  const areaName = getAreaDisplayName(area);
  const period = getPeriodLabel(forecastSelection);
  const riskLevel = titleCase(area.risk_level);
  const hazard = titleCase(area.hazard);
  const actionPhrase = getRiskActionPhrase(area.risk_level);
  const hazardAction = getHazardActionPhrase(area.hazard);

  if (language === "am") {
    return `ቅድመ ማስጠንቀቂያ: ${areaName}. ${period} ውስጥ ${riskLevel} የ${hazard} አደጋ ምልክት ታይቷል. ውሃን በጥንቃቄ ይጠቀሙ፣ እንስሳትን/ሰብልን ይከታተሉ፣ የአካባቢ መመሪያን ይከተሉ።`;
  }

  if (language === "sw") {
    return `TAHADHARI: ${areaName}. Hatari ya ${hazard} kiwango cha ${riskLevel} kwa ${period}. ${actionPhrase}; ${hazardAction}; fuata maelekezo ya mamlaka za eneo.`;
  }

  return `EARLY WARNING: ${areaName}. ${riskLevel}-level ${hazard} risk for ${period}. ${actionPhrase}; ${hazardAction}; follow local authority guidance.`;
}

function buildWhatsappMessage(area, forecastSelection, language = "en") {
  const areaName = getAreaDisplayName(area);
  const period = getPeriodLabel(forecastSelection);
  const forecastScale = getForecastScaleLabel(forecastSelection.forecastScale);
  const hazard = titleCase(area.hazard);
  const riskLevel = titleCase(area.risk_level);
  const actions = getSuggestedActions(area);

  if (language === "am") {
    return [
      "⚠️ የትንበያ-ወደ-ተግባር መልዕክት",
      "",
      `አካባቢ: ${areaName}`,
      `ጊዜ: ${period} (${forecastScale})`,
      `አደጋ: ${hazard}`,
      `የአደጋ ደረጃ: ${riskLevel}`,
      "",
      `የስጋት ውጤት: ${formatNumber(area.risk_score)} | የአደጋ ዕድል: ${formatNumber(area.hazard_probability)}`,
      `ተጋላጭነት: ${formatNumber(area.exposure)} | ተጎጂነት: ${formatNumber(area.vulnerability)}`,
      "",
      "የሚመከሩ ተግባራት:",
      ...actions.map((item) => `• ${item}`),
      "",
      "ይህ መልዕክት በትንበያ ምልክቶች፣ የአደጋ ውጤት፣ ተጋላጭነት እና ተጎጂነት ላይ የተመሠረተ ነው።",
    ].join("\n");
  }

  if (language === "sw") {
    return [
      "⚠️ Ujumbe wa Tahadhari ya Mapema",
      "",
      `Eneo: ${areaName}`,
      `Muda wa utabiri: ${period} (${forecastScale})`,
      `Hatari: ${hazard}`,
      `Kiwango cha hatari: ${riskLevel}`,
      "",
      `Alama ya hatari: ${formatNumber(area.risk_score)} | Uwezekano wa hatari: ${formatNumber(area.hazard_probability)}`,
      `Mfiduo: ${formatNumber(area.exposure)} | Uathirikaji: ${formatNumber(area.vulnerability)}`,
      "",
      "Hatua zinazopendekezwa:",
      ...actions.map((item) => `• ${item}`),
      "",
      "Ujumbe huu unatokana na tabaka za utabiri, viashiria vya hali ya hewa, mfiduo, na uathirikaji.",
    ].join("\n");
  }

  return [
    "⚠️ Forecast-to-Action Advisory",
    "",
    `Area: ${areaName}`,
    `Forecast window: ${period} (${forecastScale})`,
    `Hazard: ${hazard}`,
    `Risk level: ${riskLevel}`,
    "",
    `Risk score: ${formatNumber(area.risk_score)} | Hazard probability: ${formatNumber(area.hazard_probability)}`,
    `Exposure: ${formatNumber(area.exposure)} | Vulnerability: ${formatNumber(area.vulnerability)}`,
    "",
    "Recommended actions:",
    ...actions.map((item) => `• ${item}`),
    "",
    "This advisory is based on forecast risk layers, climate indicators, exposure, and vulnerability for the selected administrative area.",
  ].join("\n");
}

function copyText(text, onCopied) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(() => onCopied());
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
  onCopied();
}

function IndicatorCard({ area, indicator, selectedIndicator }) {
  const summary = getIndicatorSummary(area, indicator.key);
  const isSelected = indicator.key === selectedIndicator;

  return (
    <div className={`indicator-evidence-card ${isSelected ? "selected-indicator-card" : ""}`}>
      <div className="indicator-card-header">
        <span>{indicator.shortLabel}</span>
        {isSelected && <strong>Selected</strong>}
      </div>
      <h4>{formatIndicatorValue(summary)}</h4>
      <p>{indicator.description}</p>
      <div className="indicator-card-meta">
        <span>Range: <strong>{formatIndicatorRange(summary)}</strong></span>
        <span>{interpretIndicator(indicator.key, summary)}</span>
      </div>
    </div>
  );
}

function MessageBox({ title, subtitle, text, copiedLabel, onCopy, copied }) {
  return (
    <div className="message-ready-card">
      <div className="message-ready-header">
        <div>
          <h4>{title}</h4>
          <p>{subtitle}</p>
        </div>
        <button type="button" className="copy-message-button" onClick={onCopy}>
          {copied ? copiedLabel : "Copy"}
        </button>
      </div>
      <pre>{text}</pre>
    </div>
  );
}

function SelectedAreaAdvisory({
  selectedPriorityArea = null,
  forecastSelection = {},
  selectedLanguage = "en",
}) {
  const [copiedMessage, setCopiedMessage] = useState("");
  const [climateIndicatorStats, setClimateIndicatorStats] = useState(null);
  const [communityReports, setCommunityReports] = useState([]);
  const hasSelectedArea = Boolean(selectedPriorityArea?.area_name);

  const climatePeriod = forecastSelection.seasonalPeriod || getCurrentSeasonalPeriod();
  const selectedAdminLevel = selectedPriorityArea?.admin_level || "admin1";
  const selectedAreaName = selectedPriorityArea?.area_name || "";

  // Real per-area climate indicator stats (SPI/rainfall anomaly/rainfall
  // percentile/CDD/CWD) -- see app/api/seasonal_raster_maps.py::
  // get_area_indicator_stats. The ranking table selection itself only
  // carries hazard/risk/exposure/vulnerability metrics, not climate
  // indicators, so this is a separate real data source, fetched here.
  // No guard-branch state reset is needed: Dashboard.jsx only mounts this
  // component at all once an area is selected (see the "activates on
  // click" behavior), so selectedAreaName is always real by the time this
  // effect can run; if it's ever missing, just skip fetching.
  useEffect(() => {
    if (!selectedAreaName) {
      return undefined;
    }

    const controller = new AbortController();
    fetch(
      apiUrl(
        `/api/seasonal-raster/area-indicator-stats?admin_level=${encodeURIComponent(selectedAdminLevel)}&area_name=${encodeURIComponent(selectedAreaName)}&period=${encodeURIComponent(climatePeriod)}`,
      ),
      { signal: controller.signal },
    )
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => setClimateIndicatorStats(data?.indicators || null))
      .catch(() => setClimateIndicatorStats(null));

    return () => controller.abort();
  }, [selectedAdminLevel, selectedAreaName, climatePeriod]);

  // Same real GET /api/community-reports?district=<area_name> endpoint
  // SelectedAreaCommunityReports.jsx already uses -- read here too so the
  // advisory card can surface a compact ground-truth signal for the
  // selected area without duplicating the full submission form/list, which
  // stays the single place reports are actually authored.
  useEffect(() => {
    if (!selectedAreaName) {
      return undefined;
    }

    const controller = new AbortController();
    fetch(
      apiUrl(`/api/community-reports?district=${encodeURIComponent(selectedAreaName)}`),
      { signal: controller.signal },
    )
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        const items = Array.isArray(data) ? data : data?.reports || [];
        setCommunityReports(items);
      })
      .catch(() => setCommunityReports([]));

    return () => controller.abort();
  }, [selectedAreaName]);

  const communitySignal = useMemo(
    () => getSignalSummary(communityReports),
    [communityReports],
  );

  const area = useMemo(() => {
    if (!selectedPriorityArea || !climateIndicatorStats) {
      return selectedPriorityArea;
    }
    const climate_indicators = {};
    for (const [key, stats] of Object.entries(climateIndicatorStats)) {
      const format = INDICATOR_DISPLAY_FORMAT[key] || { suffix: "", digits: 2 };
      climate_indicators[key] = { mean: stats.mean, min: stats.min, max: stats.max, ...format, count: null };
    }
    return { ...selectedPriorityArea, climate_indicators };
  }, [selectedPriorityArea, climateIndicatorStats]);

  const selectedIndicator =
    forecastSelection.indicator || area?.selected_indicator || "spi";

  const languageLabel = LANGUAGE_LABELS[selectedLanguage] || "English";

  const smsMessage = useMemo(() => {
    if (!hasSelectedArea) return "";
    return buildSmsMessage(area, forecastSelection, selectedLanguage);
  }, [hasSelectedArea, area, forecastSelection, selectedLanguage]);

  const whatsappMessage = useMemo(() => {
    if (!hasSelectedArea) return "";
    return buildWhatsappMessage(area, forecastSelection, selectedLanguage);
  }, [hasSelectedArea, area, forecastSelection, selectedLanguage]);

  function handleCopy(messageType, text) {
    copyText(text, () => {
      setCopiedMessage(messageType);
      window.setTimeout(() => setCopiedMessage(""), 1800);
    });
  }

  if (!hasSelectedArea) {
    return (
      <section className="panel advisory-section selected-area-advisory">
        <div className="section-heading">
          <h2>Forecast-to-Action Advisory for Selected Area</h2>
          <p>
            Select an area from the Priority Intervention Areas table to generate
            an advisory based on the active forecast layer and climate indicators.
          </p>
        </div>
        <div className="advisory-empty-state">
          <h3>No active intervention area selected</h3>
          <p>
            Click <strong>View on map</strong> in the Priority Intervention Areas
            table. The advisory will then update using the selected area,
            forecast scale, lead, map layer, climate indicators, risk score,
            exposure, and vulnerability.
          </p>
        </div>
      </section>
    );
  }

  const suggestedActions = getSuggestedActions(area);

  return (
    <section className="panel advisory-section selected-area-advisory">
      <div className="selected-advisory-hero">
        <div>
          <span className="advisory-kicker">Forecast-to-action advisory</span>
          <h2>{area.area_name}</h2>
          <p>
            {getAdminLevelLabel(area.admin_level)} · {area.region || "Ethiopia"}
            {area.zone ? ` · ${area.zone}` : ""}
          </p>
        </div>
        <div className="advisory-hero-badges">
          {/* Ranking by Drought Risk (or Wet Risk) specifically already
              makes that hazard the point of this advisory -- showing the
              other, unrelated hazard's badge alongside it is redundant.
              Only collapses to one badge when the area was actually ranked
              by one of these two (see selected_map_layer, set from rankBy
              at selection time in TopInterventionAreas.jsx). */}
          {area.drought_risk && area.selected_map_layer !== "population_r_wet" && (
            <span className={`priority-score-pill ${getLevelInfo(area.drought_risk.level).className}`}>
              {area.selected_map_layer !== "population_r_drought" ? "Drought: " : ""}
              {getLevelInfo(area.drought_risk.level).label} ({area.drought_risk.value.toFixed(1)})
            </span>
          )}
          {area.wet_risk && area.selected_map_layer !== "population_r_drought" && (
            <span className={`priority-score-pill ${getLevelInfo(area.wet_risk.level).className}`}>
              {area.selected_map_layer !== "population_r_wet" ? "Wet: " : ""}
              {getLevelInfo(area.wet_risk.level).label} ({area.wet_risk.value.toFixed(1)})
            </span>
          )}
        </div>
      </div>

      <div className="advisory-key-message">
        <h3>Key message</h3>
        <p>{buildKeyMessage(area, forecastSelection)}</p>
      </div>

      <div className="advisory-section-block">
        <div className="advisory-block-heading">
          <h3>Impact-based risk evidence</h3>
          <p>Every real hazard, probability, vulnerability, risk, exposure, and extent metric computed for the selected area and its currently active map layers.</p>
        </div>
        <div className="risk-driver-grid">
          {(Array.isArray(area.metrics_display) && area.metrics_display.length > 0
            ? area.metrics_display
            : [
                { label: "Hazard", value: titleCase(area.hazard) },
                { label: "Risk score", value: formatNumber(area.risk_score) },
                { label: "Hazard probability", value: formatNumber(area.hazard_probability) },
                { label: "Exposure", value: formatNumber(area.exposure) },
                { label: "Vulnerability", value: formatNumber(area.vulnerability) },
              ]
          ).map((item) => (
            <div className="risk-driver-card" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      </div>

      <div className="advisory-section-block">
        <div className="advisory-block-heading">
          <h3>Climate indicator evidence</h3>
          <p>All available climate indicators are shown for the selected area. The currently selected indicator is highlighted.</p>
        </div>
        <div className="indicator-evidence-grid">
          {CLIMATE_INDICATORS.map((indicator) => (
            <IndicatorCard
              key={indicator.key}
              area={area}
              indicator={indicator}
              selectedIndicator={selectedIndicator}
            />
          ))}
        </div>
      </div>

      <div className="advisory-section-block">
        <div className="advisory-block-heading">
          <h3>Community ground truth</h3>
          <p>Real field observations submitted for this area, used to check whether the forecast risk above is showing up as an actual impact yet.</p>
        </div>
        <div className="community-signal-row">
          <div className={`ground-signal-badge ${communitySignal.className}`}>
            <span>{communitySignal.signal}</span>
            <strong>{communitySignal.total} {communitySignal.total === 1 ? "report" : "reports"}</strong>
          </div>
          <div className="risk-driver-grid">
            <div className="risk-driver-card">
              <span>High / severe reports</span>
              <strong>{communitySignal.highOrSevere}</strong>
            </div>
            <div className="risk-driver-card">
              <span>Latest observation</span>
              <strong>{communitySignal.latest ? getReportTypeLabel(communitySignal.latest.report_type) : "N/A"}</strong>
            </div>
            <div className="risk-driver-card">
              <span>Latest severity</span>
              <strong>{communitySignal.latest ? titleCase(communitySignal.latest.severity) : "N/A"}</strong>
            </div>
          </div>
        </div>
        <a href="#community-ground-truth" className="advisory-ground-truth-link">
          {communitySignal.total > 0 ? "View all reports for this area" : "Submit a ground-truth report for this area"} ↓
        </a>
      </div>

      <div className="advisory-two-column">
        <div className="advisory-card enhanced-advisory-card">
          <h3><span aria-hidden="true">📋</span> Early action advisory</h3>
          <p>{buildAdvisoryText(area, forecastSelection)}</p>
        </div>
        <div className="advisory-card enhanced-advisory-card">
          <h3><span aria-hidden="true">✅</span> Suggested immediate actions</h3>
          <ul className="advisory-action-list">
            {suggestedActions.map((action) => <li key={action}>{action}</li>)}
          </ul>
        </div>
      </div>

      <div className="advisory-section-block community-message-block">
        <div className="advisory-block-heading">
          <h3>SMS / WhatsApp-ready community message</h3>
          <p>
            Message language: <strong>{languageLabel}</strong>. These messages translate the technical advisory into a communication-ready format.
          </p>
        </div>
        <div className="message-ready-grid">
          <MessageBox
            title="SMS-ready message"
            subtitle="Short format for SMS or bulk text alerts."
            text={smsMessage}
            copied={copiedMessage === "sms"}
            copiedLabel="Copied"
            onCopy={() => handleCopy("sms", smsMessage)}
          />
          <MessageBox
            title="WhatsApp-ready message"
            subtitle="Longer format for WhatsApp groups and partner coordination."
            text={whatsappMessage}
            copied={copiedMessage === "whatsapp"}
            copiedLabel="Copied"
            onCopy={() => handleCopy("whatsapp", whatsappMessage)}
          />
        </div>
      </div>
    </section>
  );
}

export default SelectedAreaAdvisory;
