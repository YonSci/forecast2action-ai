import { useMemo, useState } from "react";

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

const MAP_LAYER_LABELS = {
  hazard: "Hazard Map",
  risk_score: "Risk Score Map",
  hazard_probability: "Hazard Probability Map",
  exposure: "Exposure Map",
  vulnerability: "Vulnerability Map",
};

const LANGUAGE_LABELS = {
  en: "English",
  am: "Amharic",
  sw: "Swahili",
};

const CLIMATE_INDICATORS = [
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

function getRiskClass(riskLevel) {
  if (riskLevel === "trigger") return "risk-trigger";
  if (riskLevel === "warning") return "risk-warning";
  if (riskLevel === "watch") return "risk-watch";
  return "risk-no_alert";
}

function getPriorityClass(priorityLevel) {
  if (priorityLevel === "trigger" || priorityLevel === "high") return "priority-high";
  if (priorityLevel === "warning" || priorityLevel === "moderate") return "priority-medium";
  if (priorityLevel === "watch") return "priority-watch";
  return "priority-low";
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

function getMapLayerLabel(value) {
  return MAP_LAYER_LABELS[value] || titleCase(value || "risk_score");
}

function getIndicatorConfig(indicatorKey) {
  return CLIMATE_INDICATORS.find((item) => item.key === indicatorKey) || CLIMATE_INDICATORS[0];
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
  return [area.area_name, area.region, area.zone].filter(Boolean).join(", ");
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
  if (hazard === "heavy_rainfall" || hazard === "wet_spell" || hazard === "flood") {
    return "avoid flood-prone areas, clear drainage, protect assets, and follow local warnings";
  }
  if (hazard === "heat_stress" || hazard === "heat") {
    return "reduce heat exposure, protect vulnerable people and livestock, and ensure water availability";
  }
  return "follow local authority guidance and report observed impacts";
}

function buildAdvisoryText(area, forecastSelection) {
  const areaName = area.area_name || "the selected area";
  const lead = getLeadLabel(forecastSelection.lead);
  const forecastScale = getForecastScaleLabel(forecastSelection.forecastScale);
  const mapLayer = getMapLayerLabel(forecastSelection.layer);
  const indicator = getIndicatorConfig(forecastSelection.indicator || area.selected_indicator || "spi");
  const hazard = titleCase(area.hazard);
  const riskLevel = titleCase(area.risk_level);
  const action = area.recommended_action || "Prioritize local verification, preparedness action, and coordination with responsible sectors.";

  return `${areaName} is identified as a ${riskLevel} priority area for ${lead} under the ${forecastScale} forecast window. The current map layer is ${mapLayer}, and the selected climate indicator is ${indicator.label}. The main hazard signal is ${hazard}, with a risk score of ${formatNumber(area.risk_score)}, hazard probability of ${formatNumber(area.hazard_probability)}, exposure of ${formatNumber(area.exposure)}, and vulnerability of ${formatNumber(area.vulnerability)}. ${action}`;
}

function buildKeyMessage(area, forecastSelection) {
  const areaName = area.area_name || "the selected area";
  const lead = getLeadLabel(forecastSelection.lead);
  const riskLevel = titleCase(area.risk_level);
  const hazard = titleCase(area.hazard);
  return `${areaName} requires ${riskLevel.toLowerCase()}-level attention for ${lead}, mainly due to ${hazard.toLowerCase()} risk combined with exposure and vulnerability conditions.`;
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

  if (hazard === "heavy_rainfall" || hazard === "wet_spell") {
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
  const lead = getLeadLabel(forecastSelection.lead);
  const riskLevel = titleCase(area.risk_level);
  const hazard = titleCase(area.hazard);
  const actionPhrase = getRiskActionPhrase(area.risk_level);
  const hazardAction = getHazardActionPhrase(area.hazard);
  const selectedIndicator = forecastSelection.indicator || area.selected_indicator || "spi";
  const indicatorConfig = getIndicatorConfig(selectedIndicator);
  const indicatorValue = formatIndicatorValue(getIndicatorSummary(area, selectedIndicator));

  if (language === "am") {
    return `ቅድመ ማስጠንቀቂያ: ${areaName}. ${lead} ውስጥ ${riskLevel} የ${hazard} አደጋ ምልክት ታይቷል. ${indicatorConfig.shortLabel}: ${indicatorValue}. ውሃን በጥንቃቄ ይጠቀሙ፣ እንስሳትን/ሰብልን ይከታተሉ፣ የአካባቢ መመሪያን ይከተሉ።`;
  }

  if (language === "sw") {
    return `TAHADHARI: ${areaName}. Hatari ya ${hazard} kiwango cha ${riskLevel} kwa ${lead}. ${indicatorConfig.shortLabel}: ${indicatorValue}. ${actionPhrase}; ${hazardAction}; fuata maelekezo ya mamlaka za eneo.`;
  }

  return `EARLY WARNING: ${areaName}. ${riskLevel}-level ${hazard} risk for ${lead}. ${indicatorConfig.shortLabel}: ${indicatorValue}. ${actionPhrase}; ${hazardAction}; follow local authority guidance.`;
}

function buildWhatsappMessage(area, forecastSelection, language = "en") {
  const areaName = getAreaDisplayName(area);
  const lead = getLeadLabel(forecastSelection.lead);
  const forecastScale = getForecastScaleLabel(forecastSelection.forecastScale);
  const mapLayer = getMapLayerLabel(forecastSelection.layer);
  const hazard = titleCase(area.hazard);
  const riskLevel = titleCase(area.risk_level);
  const selectedIndicator = forecastSelection.indicator || area.selected_indicator || "spi";
  const selectedIndicatorConfig = getIndicatorConfig(selectedIndicator);
  const selectedIndicatorValue = formatIndicatorValue(getIndicatorSummary(area, selectedIndicator));
  const actions = getSuggestedActions(area);

  if (language === "am") {
    return [
      "⚠️ የትንበያ-ወደ-ተግባር መልዕክት",
      "",
      `አካባቢ: ${areaName}`,
      `ጊዜ: ${lead} (${forecastScale})`,
      `አደጋ: ${hazard}`,
      `የአደጋ ደረጃ: ${riskLevel}`,
      `የተመረጠ አመልካች: ${selectedIndicatorConfig.label} = ${selectedIndicatorValue}`,
      `የካርታ ሽፋን: ${mapLayer}`,
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
      `Muda wa utabiri: ${lead} (${forecastScale})`,
      `Hatari: ${hazard}`,
      `Kiwango cha hatari: ${riskLevel}`,
      `Kiashiria kilichochaguliwa: ${selectedIndicatorConfig.label} = ${selectedIndicatorValue}`,
      `Tabaka la ramani: ${mapLayer}`,
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
    `Forecast window: ${lead} (${forecastScale})`,
    `Hazard: ${hazard}`,
    `Risk level: ${riskLevel}`,
    `Selected indicator: ${selectedIndicatorConfig.label} = ${selectedIndicatorValue}`,
    `Map layer: ${mapLayer}`,
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
  const hasSelectedArea = Boolean(selectedPriorityArea?.area_name);

  const selectedIndicator =
    forecastSelection.indicator || selectedPriorityArea?.selected_indicator || "spi";

  const forecastScale = getForecastScaleLabel(forecastSelection.forecastScale);
  const lead = getLeadLabel(forecastSelection.lead);
  const mapLayer = getMapLayerLabel(forecastSelection.layer);
  const selectedIndicatorConfig = getIndicatorConfig(selectedIndicator);
  const languageLabel = LANGUAGE_LABELS[selectedLanguage] || "English";

  const smsMessage = useMemo(() => {
    if (!hasSelectedArea) return "";
    return buildSmsMessage(selectedPriorityArea, forecastSelection, selectedLanguage);
  }, [hasSelectedArea, selectedPriorityArea, forecastSelection, selectedLanguage]);

  const whatsappMessage = useMemo(() => {
    if (!hasSelectedArea) return "";
    return buildWhatsappMessage(selectedPriorityArea, forecastSelection, selectedLanguage);
  }, [hasSelectedArea, selectedPriorityArea, forecastSelection, selectedLanguage]);

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

  const suggestedActions = getSuggestedActions(selectedPriorityArea);

  return (
    <section className="panel advisory-section selected-area-advisory">
      <div className="selected-advisory-hero">
        <div>
          <span className="advisory-kicker">Forecast-to-action advisory</span>
          <h2>{selectedPriorityArea.area_name}</h2>
          <p>
            {getAdminLevelLabel(selectedPriorityArea.admin_level)} · {selectedPriorityArea.region || "Ethiopia"}
            {selectedPriorityArea.zone ? ` · ${selectedPriorityArea.zone}` : ""}
          </p>
        </div>
        <div className="advisory-hero-badges">
          <span className={`risk-pill ${getRiskClass(selectedPriorityArea.risk_level)}`}>
            {titleCase(selectedPriorityArea.risk_level)}
          </span>
          <span className={`priority-score-pill ${getPriorityClass(selectedPriorityArea.priority_level)}`}>
            Priority {formatNumber(selectedPriorityArea.priority_score)}
          </span>
        </div>
      </div>

      <div className="advisory-key-message">
        <h3>Key message</h3>
        <p>{buildKeyMessage(selectedPriorityArea, forecastSelection)}</p>
      </div>

      <div className="advisory-section-block">
        <div className="advisory-block-heading">
          <h3>Forecast context</h3>
          <p>The advisory is linked to the current forecast map configuration.</p>
        </div>
        <div className="advisory-context-grid">
          <div><span>Forecast scale</span><strong>{forecastScale}</strong></div>
          <div><span>Lead / horizon</span><strong>{lead}</strong></div>
          <div><span>Selected map layer</span><strong>{mapLayer}</strong></div>
          <div><span>Selected climate indicator</span><strong>{selectedIndicatorConfig.label}</strong></div>
        </div>
      </div>

      <div className="advisory-section-block">
        <div className="advisory-block-heading">
          <h3>Impact-based risk evidence</h3>
          <p>Risk score combines hazard probability, exposure, vulnerability, and priority ranking for the selected administrative area.</p>
        </div>
        <div className="risk-driver-grid">
          <div className="risk-driver-card"><span>Hazard</span><strong>{titleCase(selectedPriorityArea.hazard)}</strong></div>
          <div className="risk-driver-card"><span>Risk score</span><strong>{formatNumber(selectedPriorityArea.risk_score)}</strong></div>
          <div className="risk-driver-card"><span>Hazard probability</span><strong>{formatNumber(selectedPriorityArea.hazard_probability)}</strong></div>
          <div className="risk-driver-card"><span>Exposure</span><strong>{formatNumber(selectedPriorityArea.exposure)}</strong></div>
          <div className="risk-driver-card"><span>Vulnerability</span><strong>{formatNumber(selectedPriorityArea.vulnerability)}</strong></div>
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
              area={selectedPriorityArea}
              indicator={indicator}
              selectedIndicator={selectedIndicator}
            />
          ))}
        </div>
      </div>

      <div className="advisory-two-column">
        <div className="advisory-card enhanced-advisory-card">
          <h3>Early action advisory</h3>
          <p>{buildAdvisoryText(selectedPriorityArea, forecastSelection)}</p>
        </div>
        <div className="advisory-card enhanced-advisory-card">
          <h3>Suggested immediate actions</h3>
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

      <div className="advisory-method-note">
        <strong>Operational interpretation:</strong> the advisory is generated from the selected forecast horizon, selected map layer, all available climate indicators, impact-based risk score, exposure, vulnerability, and administrative-area priority ranking.
      </div>
    </section>
  );
}

export default SelectedAreaAdvisory;
