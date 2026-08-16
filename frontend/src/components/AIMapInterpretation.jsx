import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";
import {
  CLIMATE_INDICATORS,
  getCurrentSeasonalPeriod,
} from "../constants/climateIndicators.js";
import ContextAuditDrawer from "./context/ContextAuditDrawer.jsx";
import ContextQualityBadge from "./context/ContextQualityBadge.jsx";
import PriorityAreaJustificationList from "./context/PriorityAreaJustificationList.jsx";
import ValidationFlagsList from "./context/ValidationFlagsList.jsx";
import TimescaledAdvisoryList from "./context/TimescaledAdvisoryList.jsx";
import CategorizedHumanitarianList from "./context/CategorizedHumanitarianList.jsx";
import SmsMessageCard from "./context/SmsMessageCard.jsx";
import WhatsAppMessageCard from "./context/WhatsAppMessageCard.jsx";
import RetrievalDebugPanel from "./context/RetrievalDebugPanel.jsx";
import "../styles/aiMapInterpretation.css";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHE_VERSION = "v17-context-fingerprint";

const MAP_LAYERS = [
  { key: "hazard", label: "Hazard map", rankingLayer: "risk_score" },
  { key: "risk_score", label: "Risk score map", rankingLayer: "risk_score" },
  {
    key: "hazard_probability",
    label: "Hazard probability map",
    rankingLayer: "hazard_probability",
  },
  { key: "exposure", label: "Exposure map", rankingLayer: "exposure" },
  {
    key: "vulnerability",
    label: "Vulnerability map",
    rankingLayer: "vulnerability",
  },
];

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
  June: "June",
  July: "July",
  August: "August",
  September: "September",
  JJAS: "JJAS",
  june: "June",
  july: "July",
  august: "August",
  september: "September",
  jjas: "JJAS",
};

const FORECAST_SCALE_LABELS = {
  subseasonal: "Subseasonal",
  seasonal: "Seasonal",
};

const LANGUAGE_LABELS = {
  en: "English",
  am: "Amharic",
  om: "Oromifa / Afaan Oromo",
  ti: "Tigrinya",
  so: "Somali",
  fr: "French",
  ar: "Arabic",
};

// The 5 languages the backend's report pipeline actually supports (see
// get_language_instruction in app/api/ai_map_interpretation.py) -- this
// selector also drives SelectedAreaAdvisory's SMS/WhatsApp text and
// SelectedAreaCommunityReports' submission language (shared Dashboard-level
// state), not just this panel, which is why it lives here as the single
// control rather than duplicated per-section.
const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "am", label: "Amharic" },
  { value: "om", label: "Oromifa / Afaan Oromo" },
  { value: "ti", label: "Tigrinya" },
  { value: "so", label: "Somali" },
];

const STAGE_LABELS = {
  stage1: "Evidence Interpretation",
  stage2: "Integrated Risk Synthesis",
  stage3: "Action Translation",
};

const FALLBACK_AI_PROVIDER_OPTIONS = [
  {
    value: "free_auto",
    label: "Automatic (recommended)",
    description:
      "Tries Gemini first, then automatically fails over to OpenRouter and OpenAI if Gemini is unavailable -- the most resilient option.",
    models: [],
  },
  {
    value: "gemini",
    label: "Google Gemini",
    description:
      "Fastest and most reliable with the full comprehensive map set (all 32 images). No automatic failover if Gemini itself is unavailable -- pick Automatic for resilience.",
    models: [
      {
        value: "gemini-flash-lite-latest",
        label: "Gemini Flash-Lite (latest, fastest)",
      },
      {
        value: "gemini-3.5-flash-lite",
        label: "Gemini 3.5 Flash-Lite (1M context)",
      },
      { value: "gemini-flash-latest", label: "Gemini Flash (latest)" },
    ],
  },
  {
    value: "openrouter",
    label: "OpenRouter",
    description:
      "All models below confirmed to handle the full comprehensive map set (all 32 images).",
    models: [
      {
        value: "google/gemini-2.5-flash-lite",
        label: "Gemini 2.5 Flash-Lite (1M context)",
      },
      {
        value: "openai/gpt-5.6-luna",
        label: "GPT-5.6 Luna (vision, 1M context)",
      },
      {
        value: "meta-llama/llama-4-scout",
        label: "Llama 4 Scout (vision, 1.3M context)",
      },
      {
        value: "openai/gpt-5.6-terra",
        label: "GPT-5.6 Terra (vision, 1M context)",
      },
      {
        value: "z-ai/glm-4.6v",
        label: "GLM-4.6V (vision, 131K context)",
      },
    ],
  },
];

function getProviderConfig(providerOptions, providerValue) {
  return (
    providerOptions.find((item) => item.value === providerValue) ||
    providerOptions[0]
  );
}

function getDefaultModelForProvider(providerOptions, providerValue) {
  const config = getProviderConfig(providerOptions, providerValue);
  return config?.models?.[0]?.value || "auto";
}

function getModelLabel(providerConfig, modelValue) {
  return (
    providerConfig?.models?.find((item) => item.value === modelValue)?.label ||
    modelValue ||
    "Automatic"
  );
}

function normalizeLanguageCode(value) {
  const text = String(value || "en")
    .trim()
    .toLowerCase();

  if (["am", "amh", "amharic", "am-et", "አማርኛ"].includes(text)) {
    return "am";
  }

  if (
    [
      "om",
      "orm",
      "oromo",
      "oromifa",
      "afaan oromo",
      "afan oromo",
      "or",
    ].includes(text)
  ) {
    return "om";
  }

  if (["ti", "tir", "tig", "tigrinya", "tigrigna", "ትግርኛ"].includes(text)) {
    return "ti";
  }

  if (
    ["so", "som", "somali", "af-soomaali", "af soomaali", "soomaali"].includes(
      text,
    )
  ) {
    return "so";
  }

  if (["sw", "swa", "swahili", "kiswahili"].includes(text)) {
    return "sw";
  }

  if (["fr", "fre", "fra", "french", "français", "francais"].includes(text)) {
    return "fr";
  }

  if (["ar", "ara", "arabic", "العربية"].includes(text)) {
    return "ar";
  }

  if (["en", "eng", "english", "en-us", "en-gb"].includes(text)) {
    return "en";
  }

  return text || "en";
}

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

function getLanguageLabel(value) {
  const code = normalizeLanguageCode(value);
  return LANGUAGE_LABELS[code] || titleCase(code || "English");
}

// JJAS is a 4-month aggregate (June-July-August-September), but the
// underlying `lead` value it maps to (see ForecastLayerMap.jsx's
// SEASONAL_PERIOD_TO_HAZARD_LEAD) is still just "month_1" -- there's no
// distinct "4-month" lead in the backend's fixed FORECAST_LEADS vocabulary,
// so that value has to stay "month_1" for /api/intervention-ranking to keep
// working. This only fixes what's DISPLAYED for that case, so it reads "4
// Months" instead of the misleading "Month 1".
function getLeadLabel(value, seasonalPeriod) {
  if (
    String(seasonalPeriod || "")
      .trim()
      .toLowerCase() === "jjas"
  ) {
    return "4 Months";
  }
  return LEAD_LABELS[value] || titleCase(value || "week_1");
}

function getForecastScaleLabel(value) {
  return FORECAST_SCALE_LABELS[value] || titleCase(value || "subseasonal");
}

function getLayerLabel(value) {
  return (
    MAP_LAYERS.find((item) => item.key === value)?.label ||
    titleCase(value || "risk_score")
  );
}


function getIndicatorLabel(value) {
  return (
    CLIMATE_INDICATORS.find((item) => item.value === value)?.label ||
    titleCase(value || "spi")
  );
}

// Both the climate indicator maps section and the hazard/risk layers section
// are always visible together on the dashboard (no tab switcher), so these
// always describe both. ForecastLayerMap normally sends activeMapGroup /
// activeMapLabel directly; these are only the fallback if that's missing.
function getMapGroupLabel(forecastSelection = {}) {
  if (forecastSelection?.activeMapGroup) {
    return forecastSelection.activeMapGroup;
  }

  return "Climate Indicator Maps and Hazard/Risk Layers";
}

function getDisplayedMapLabel(forecastSelection = {}) {
  if (forecastSelection?.activeMapLabel) {
    return forecastSelection.activeMapLabel;
  }

  const indicatorLabel = getIndicatorLabel(
    forecastSelection.seasonalIndicator || forecastSelection.indicator,
  );
  const layerLabel = getLayerLabel(forecastSelection.layer);
  return `${indicatorLabel} (climate indicator) and ${layerLabel} (hazard/risk)`;
}

function getAdminScope(adminSelection) {
  return (
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia"
  );
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }

  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
}

function simpleHash(text) {
  let hash = 5381;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 33) ^ text.charCodeAt(index);
  }
  return (hash >>> 0).toString(36);
}

function buildCacheKey({
  forecastSelection,
  adminSelection,
  normalizedLanguage,
  selectedProvider,
  selectedModel,
}) {
  const cacheIdentity = {
    cacheVersion: CACHE_VERSION,
    forecastScale: forecastSelection?.forecastScale || "subseasonal",
    lead: forecastSelection?.lead || "week_1",
    layer: forecastSelection?.layer || "risk_score",
    activeMapGroup: forecastSelection?.activeMapGroup || "",
    activeMapLabel: forecastSelection?.activeMapLabel || "",
    seasonalScale: forecastSelection?.seasonalScale || "seasonal",
    seasonalIndicator:
      forecastSelection?.seasonalIndicator ||
      forecastSelection?.indicator ||
      "",
    seasonalPeriod: forecastSelection?.seasonalPeriod || "",
    seasonalProduct: forecastSelection?.seasonalProduct || "",
    climateMapView: forecastSelection?.climateMapView || "",
    seasonalMapId: forecastSelection?.seasonalMap?.id || "",
    // Not just for display: switching the Hazard/Risk raster selection (or
    // the admin boundary scope) must bust the cached report, or a stale
    // advisory generated for a different layer/period/area would silently
    // get reused instead of regenerating.
    hazardRiskCategory: forecastSelection?.hazardRiskCategory || "",
    hazardRiskLayer: forecastSelection?.hazardRiskLayer || "",
    hazardRiskPeriod: forecastSelection?.hazardRiskPeriod || "",
    hazardRiskMapId: forecastSelection?.hazardRiskMap?.id || "",
    admin: {
      countryId: adminSelection?.countryId || "",
      boundaryLevel: adminSelection?.boundaryLevel || "",
      regionId: adminSelection?.regionId || "",
      zoneId: adminSelection?.zoneId || "",
      woredaId: adminSelection?.woredaId || "",
      regionLabel: adminSelection?.regionLabel || "",
      zoneLabel: adminSelection?.zoneLabel || "",
      woredaLabel: adminSelection?.woredaLabel || "",
    },
    targetLanguage: normalizedLanguage || "en",
    aiProvider: selectedProvider || "gemini",
    aiModel: selectedModel || "auto",
    layerMode: "all-map-layers",
    indicatorMode: "all-climate-indicators",
  };

  return `forecast2action-ai-map-report:${simpleHash(stableStringify(cacheIdentity))}`;
}

// `expectedFingerprint` is the backend-computed context_fingerprint (see
// POST /api/context/build) for the CURRENT forecast/community/knowledge/
// policy data. Passing it makes this a real invalidation check, not just a
// shallow "did the dropdown selections change" one -- a cached report is
// only reused when the fingerprint of what's actually stored matches
// what's true right now, so a new forecast run, a new community report, or
// an edited knowledge-base entry invalidates the cache even if the user's
// selections (forecastSelection/adminSelection) didn't change at all.
// Callers that don't have a fingerprint yet (the initial on-mount check,
// before any context has been built) omit it and get the old,
// identity-only behavior.
function getCachedReport(cacheKey, expectedFingerprint = null) {
  try {
    const raw = localStorage.getItem(cacheKey);
    if (!raw) {
      return null;
    }

    const record = JSON.parse(raw);
    if (!record?.createdAt || !record?.report) {
      return null;
    }

    if (Date.now() - record.createdAt > CACHE_TTL_MS) {
      localStorage.removeItem(cacheKey);
      return null;
    }

    if (expectedFingerprint && record.contextFingerprint !== expectedFingerprint) {
      return null;
    }

    return record.report;
  } catch (error) {
    console.warn("Could not read AI report cache", error);
    return null;
  }
}

function saveCachedReport(cacheKey, report, contextFingerprint = null) {
  try {
    localStorage.setItem(
      cacheKey,
      JSON.stringify({
        createdAt: Date.now(),
        report,
        contextFingerprint,
      }),
    );
  } catch (error) {
    console.warn("Could not save AI report cache", error);
  }
}


function ReportList({ title, items }) {
  if (!Array.isArray(items) || items.length === 0) {
    return null;
  }
  return (
    <div className="ai-report-section">
      <h4>{title}</h4>
      <ul>
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

// layer_by_layer_summary/indicator_by_indicator_summary items are real
// structured objects (layer/indicator, national_signal, national_mean,
// highest_areas, lowest_areas, high_or_very_high_area_pct, interpretation,
// confidence -- see app/context/statistical_evidence.py's
// build_structured_layer_summaries/build_structured_indicator_summaries),
// not flat strings -- rendered as cards instead of ReportList's plain
// <li>{item}</li>, which would show "[object Object]" for a raw object.
function StructuredSummaryList({ title, items, keyField }) {
  if (!Array.isArray(items) || items.length === 0) {
    return null;
  }
  return (
    <div className="ai-report-section">
      <h4>{title}</h4>
      <div className="ai-structured-summary-list">
        {items.map((item, index) => {
          if (!item || typeof item !== "object") {
            // Defensive: a legacy cached report generated before this
            // change may still have plain strings here.
            return (
              <p className="ai-structured-summary-legacy" key={`${title}-${index}`}>
                {item}
              </p>
            );
          }
          const key = item[keyField];
          return (
            <div className="ai-structured-summary-item" key={key || index}>
              <div className="ai-structured-summary-head">
                <strong>{titleCase(key)}</strong>
                {item.national_signal && (
                  <span className="ai-structured-summary-signal">{titleCase(item.national_signal)}</span>
                )}
                {item.confidence && (
                  <span className={`ai-structured-summary-confidence confidence-${item.confidence}`}>
                    {item.confidence} confidence
                  </span>
                )}
              </div>
              {item.interpretation && <p>{item.interpretation}</p>}
              <div className="ai-structured-summary-stats">
                {item.national_mean !== null && item.national_mean !== undefined && (
                  <span>national mean {item.national_mean}</span>
                )}
                {item.high_or_very_high_area_pct !== null && item.high_or_very_high_area_pct !== undefined && (
                  <span>{item.high_or_very_high_area_pct}% high/very-high area</span>
                )}
                {Array.isArray(item.highest_areas) && item.highest_areas.length > 0 && (
                  <span>highest: {item.highest_areas.join(", ")}</span>
                )}
                {Array.isArray(item.lowest_areas) && item.lowest_areas.length > 0 && (
                  <span>lowest: {item.lowest_areas.join(", ")}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatStructuredSummaryForCopy(items, keyField) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.map((item) => {
    if (!item || typeof item !== "object") {
      return `- ${item}`;
    }
    const label = titleCase(item[keyField]);
    const signal = item.national_signal ? ` [${item.national_signal}]` : "";
    return `- ${label}${signal}: ${item.interpretation || ""}`;
  });
}

function formatAdvisoryBulletForCopy(item) {
  if (typeof item === "string") {
    return `  - ${item}`;
  }
  const areas = Array.isArray(item.area) ? item.area.filter(Boolean).join(", ") : item.area;
  const tags = [areas, item.trigger, item.cross_indicator_confidence ? `${item.cross_indicator_confidence} cross-indicator confidence` : null]
    .filter(Boolean)
    .join(" · ");
  return `  - ${item.action}${tags ? ` (${tags})` : ""}`;
}

function formatStructuredAdvisory(data, labels) {
  if (!data) {
    return [];
  }
  if (Array.isArray(data)) {
    return data.map((item) => formatAdvisoryBulletForCopy(item));
  }
  const lines = [];
  for (const key of Object.keys(labels)) {
    const items = data[key];
    if (Array.isArray(items) && items.length > 0) {
      lines.push(`  ${labels[key]}:`);
      lines.push(...items.map((item) => formatAdvisoryBulletForCopy(item)));
    }
  }
  return lines;
}

function formatSmsMessagesForCopy(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return ["(no actionable areas this period)"];
  }
  return messages.map(
    (item) => `- [${item.area} · ${item.hazard} · ${item.audience}] ${item.message}`,
  );
}

const TIMESCALE_LABELS_FOR_COPY = {
  immediate: "Immediate (next 7 days)",
  near_term: "Near-term (2-4 weeks)",
  preparedness: "Preparedness (remainder of forecast period)",
};

const HUMANITARIAN_LABELS_FOR_COPY = {
  monitoring: "Monitoring",
  preparedness: "Preparedness",
  pre_positioning: "Pre-positioning",
  immediate_action: "Immediate action",
};

function copyReport(report) {
  const highConfidencePriority = (report.priority_area_justification || []).filter(
    (item) => item.cross_indicator_confidence === "high",
  );

  const lines = [
    report.title || "AI Map Interpretation & Advisory",
    "",
    "Indicator-by-indicator summary",
    ...formatStructuredSummaryForCopy(report.indicator_by_indicator_summary, "indicator"),
    "",
    "Layer-by-layer hazard summary",
    ...formatStructuredSummaryForCopy(report.layer_by_layer_summary, "layer"),
    "",
    "Ethiopia-wide spatial overview",
    ...(report.national_spatial_overview || []).map((item) => `- ${item}`),
    "",
    "Compound-hazard interpretation",
    ...(report.compound_hazard_interpretation || []).map((item) => `- ${item}`),
    "",
    "Why priority areas were selected (high cross-indicator confidence areas only)",
    ...highConfidencePriority.map(
      (item) =>
        `- #${item.rank} ${item.area} (${item.hazard_type}): risk score ${item.risk_score} (${item.risk_class || "unclassified"}), hazard probability ${item.hazard_probability}, vulnerability ${item.vulnerability}, action status: ${item.action_status || "unknown"}. ${item.differentiator || ""} ${item.recommended_intervention_type ? `Recommended: ${item.recommended_intervention_type}` : ""}`,
    ),
    "",
    "Farmer advisory",
    ...formatStructuredAdvisory(report.farmer_advisory, TIMESCALE_LABELS_FOR_COPY),
    "",
    "Agro-pastoral advisory",
    ...formatStructuredAdvisory(report.agro_pastoral_advisory, TIMESCALE_LABELS_FOR_COPY),
    "",
    "Humanitarian priorities",
    ...formatStructuredAdvisory(report.humanitarian_priorities, HUMANITARIAN_LABELS_FOR_COPY),
    "",
    "Executive summary",
    report.executive_summary || "",
    "",
    "SMS messages (real actionable areas only)",
    ...formatSmsMessagesForCopy(report.sms_messages),
  ];

  navigator.clipboard?.writeText(lines.join("\n"));
}

function downloadReport(report) {
  const blob = new Blob([JSON.stringify(report, null, 2)], {
    type: "application/json;charset=utf-8;",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "ai_map_interpretation_report.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// Converts the same plain-text line arrays copyReport() already builds
// (from formatStructuredSummaryForCopy/formatStructuredAdvisory/etc, all
// real report fields, no fabricated content) into a bulletin-friendly HTML
// fragment -- sub-headings (lines ending in ":") become <p>, everything
// else becomes a bulleted <li>, so the bulletin never duplicates the
// field-extraction logic those helpers already got right.
function linesToBulletinHtml(lines) {
  if (!lines || lines.length === 0) {
    return "<p class=\"bulletin-empty\">Not available.</p>";
  }
  const parts = [];
  let openList = false;
  for (const raw of lines) {
    const trimmed = String(raw).trim();
    if (!trimmed) continue;
    if (trimmed.endsWith(":") && !trimmed.startsWith("-")) {
      if (openList) {
        parts.push("</ul>");
        openList = false;
      }
      parts.push(`<p class="bulletin-subhead">${escapeHtml(trimmed)}</p>`);
      continue;
    }
    if (!openList) {
      parts.push("<ul>");
      openList = true;
    }
    parts.push(`<li>${escapeHtml(trimmed.replace(/^-+\s*/, ""))}</li>`);
  }
  if (openList) parts.push("</ul>");
  return parts.join("") || "<p class=\"bulletin-empty\">Not available.</p>";
}

// Real, currently-generated report data (Stage 1-3 pipeline output already
// held in this component's `report` state) formatted as a standalone,
// printable HTML bulletin -- deliberately NOT calling the legacy
// GET /api/bulletin/{district} endpoint, which is wired to a stale
// hackathon-era prototype CSV (data/sample/hazard_indicators.csv) that
// doesn't contain any of this app's real current admin1 area names.
function buildBulletinHtml(report, context) {
  const generatedAt = `${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`;
  const highConfidencePriority = (report.priority_area_justification || []).filter(
    (item) => item.cross_indicator_confidence === "high",
  );

  const priorityRowsHtml = highConfidencePriority
    .map(
      (item) => `
      <tr>
        <td>#${escapeHtml(item.rank)}</td>
        <td>${escapeHtml(item.area)}</td>
        <td>${escapeHtml(titleCase(item.hazard_type))}</td>
        <td>${escapeHtml(titleCase(item.risk_class || "unclassified"))}</td>
        <td>${escapeHtml(Number.isFinite(Number(item.risk_score)) ? Number(item.risk_score).toFixed(1) : item.risk_score)}</td>
        <td>${escapeHtml(titleCase(item.action_status || "unknown"))}</td>
      </tr>`,
    )
    .join("");

  const spatialOverviewHtml = linesToBulletinHtml(
    (report.national_spatial_overview || []).map((item) => `- ${item}`),
  );
  const compoundHazardHtml = linesToBulletinHtml(
    (report.compound_hazard_interpretation || []).map((item) => `- ${item}`),
  );

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(report.title || "Forecast2Action AI Early Warning Bulletin")}</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; max-width: 820px; margin: 0 auto; padding: 40px 32px 80px; color: #16233a; line-height: 1.55; }
  h1 { font-size: 1.6rem; margin: 0 0 6px; color: #06204a; }
  h2 { font-size: 1.02rem; margin-top: 32px; margin-bottom: 10px; border-bottom: 2px solid #dbe7f7; padding-bottom: 6px; color: #1570ef; }
  .meta { color: #5d6b85; font-size: 0.84rem; margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 6px 18px; }
  .meta strong { color: #16233a; }
  .exec-summary { background: #f3f7fd; border: 1px solid #dbe7f7; border-radius: 12px; padding: 16px 18px; white-space: pre-wrap; }
  .bulletin-subhead { font-weight: 700; margin: 12px 0 4px; color: #16233a; }
  .bulletin-empty { color: #8492a6; font-style: italic; }
  ul { padding-left: 20px; margin: 4px 0; }
  li { margin-bottom: 6px; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; font-size: 0.84rem; }
  th, td { border: 1px solid #dbe7f7; padding: 6px 8px; text-align: left; }
  th { background: #f3f7fd; }
  .disclosure { margin-top: 44px; padding-top: 14px; border-top: 1px solid #dbe7f7; font-size: 0.74rem; color: #8492a6; }
  .print-hint { font-size: 0.78rem; color: #5d6b85; margin-bottom: 4px; }
  @media print { .print-hint { display: none; } body { padding: 0 8px; } }
</style>
</head>
<body>
  <p class="print-hint">Open the print dialog and choose "Save as PDF" to export this bulletin.</p>
  <h1>Forecast2Action AI Early Warning Bulletin</h1>
  <div class="meta">
    <span><strong>Area:</strong> ${escapeHtml(context.areaName)}${context.areaSubtitle ? ` (${escapeHtml(context.areaSubtitle)})` : ""}</span>
    <span><strong>Forecast:</strong> ${escapeHtml(context.forecastScaleLabel)} · ${escapeHtml(context.leadLabel)}</span>
    <span><strong>Language:</strong> ${escapeHtml(context.languageLabel)}</span>
    <span><strong>Generated:</strong> ${escapeHtml(generatedAt)}</span>
  </div>

  <section>
    <h2>Executive summary</h2>
    <div class="exec-summary">${escapeHtml(report.executive_summary || "Not available.")}</div>
  </section>

  ${
    priorityRowsHtml
      ? `<section>
    <h2>Priority areas (high cross-indicator confidence)</h2>
    <table>
      <thead><tr><th>Rank</th><th>Area</th><th>Hazard</th><th>Risk class</th><th>Risk score</th><th>Status</th></tr></thead>
      <tbody>${priorityRowsHtml}</tbody>
    </table>
  </section>`
      : ""
  }

  <section>
    <h2>Ethiopia-wide spatial overview</h2>
    ${spatialOverviewHtml}
  </section>

  <section>
    <h2>Compound-hazard interpretation</h2>
    ${compoundHazardHtml}
  </section>

  <section>
    <h2>Farmer advisory</h2>
    ${linesToBulletinHtml(formatStructuredAdvisory(report.farmer_advisory, TIMESCALE_LABELS_FOR_COPY))}
  </section>

  <section>
    <h2>Agro-pastoral advisory</h2>
    ${linesToBulletinHtml(formatStructuredAdvisory(report.agro_pastoral_advisory, TIMESCALE_LABELS_FOR_COPY))}
  </section>

  <section>
    <h2>Humanitarian priorities</h2>
    ${linesToBulletinHtml(formatStructuredAdvisory(report.humanitarian_priorities, HUMANITARIAN_LABELS_FOR_COPY))}
  </section>

  <section>
    <h2>SMS-ready messages</h2>
    ${linesToBulletinHtml(formatSmsMessagesForCopy(report.sms_messages))}
  </section>

  <div class="disclosure">
    Generated by Forecast2Action AI (${escapeHtml(report?._metadata?.ai_engine || "AI provider / fallback")}${report?._metadata?.provider ? ` · ${escapeHtml(report._metadata.provider)}` : ""}). Deterministic evidence is computed server-side from real climate and exposure data; narrative text is AI-generated and should be reviewed by a qualified officer before acting on it in the field.
  </div>
</body>
</html>`;
}

function downloadBulletin(report, context) {
  const html = buildBulletinHtml(report, context);
  const blob = new Blob([html], { type: "text/html;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const safeArea = String(context.areaName || "ethiopia")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  link.download = `forecast2action_bulletin_${safeArea || "ethiopia"}.html`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function AIMapInterpretation({
  forecastSelection = {},
  adminSelection = {},
  selectedPriorityArea = null,
  selectedLanguage = "en",
  onLanguageChange,
  onContextBuilt,
  onReportChange,
}) {
  const [providerOptions, setProviderOptions] = useState(
    FALLBACK_AI_PROVIDER_OPTIONS,
  );
  // Defaults to "free_auto" (Gemini -> OpenRouter -> OpenAI failover), not
  // a single fixed provider -- a transient outage on one provider used to
  // mean every stage silently dropped to the English-only rule-based
  // fallback with no retry. "auto" model = let the provider chain pick.
  const [selectedProvider, setSelectedProvider] = useState("free_auto");
  const [selectedModel, setSelectedModel] = useState("auto");
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [contextInfo, setContextInfo] = useState(null);

  const normalizedLanguage = useMemo(
    () => normalizeLanguageCode(selectedLanguage),
    [selectedLanguage],
  );

  useEffect(() => {
    let isActive = true;

    async function loadProviderOptions() {
      try {
        const response = await fetch(apiUrl("/api/ai/model-options"));
        if (!response.ok) {
          throw new Error(`Model options request failed: ${response.status}`);
        }
        const data = await response.json();
        if (!isActive) {
          return;
        }
        const options =
          Array.isArray(data?.providers) && data.providers.length > 0
            ? data.providers
            : FALLBACK_AI_PROVIDER_OPTIONS;
        setProviderOptions(options);
      } catch (error) {
        console.warn("Could not load AI model options", error);
        if (isActive) {
          setProviderOptions(FALLBACK_AI_PROVIDER_OPTIONS);
        }
      }
    }

    loadProviderOptions();

    return () => {
      isActive = false;
    };
  }, []);

  const selectedProviderConfig = useMemo(() => {
    return getProviderConfig(providerOptions, selectedProvider);
  }, [providerOptions, selectedProvider]);

  const resolvedSelectedModel = selectedModel;

  const selectedModelLabel = useMemo(() => {
    return getModelLabel(selectedProviderConfig, selectedModel);
  }, [selectedProviderConfig, selectedModel]);

  const cacheKey = useMemo(() => {
    return buildCacheKey({
      forecastSelection,
      adminSelection,
      normalizedLanguage,
      selectedProvider,
      selectedModel: resolvedSelectedModel || selectedModel,
    });
  }, [
    forecastSelection,
    adminSelection,
    normalizedLanguage,
    selectedProvider,
    selectedModel,
    resolvedSelectedModel,
  ]);

  useEffect(() => {
    const cached = getCachedReport(cacheKey);
    setReport(cached);
    setErrorMessage("");
    setStatusMessage(
      cached
        ? `Loaded saved ${getLanguageLabel(normalizedLanguage)} advisory from this browser cache.`
        : "",
    );
  }, [cacheKey, normalizedLanguage]);

  // Single sync point for every setReport(...) call above (cache load,
  // fresh generation, reset) instead of threading onReportChange through
  // each call site individually -- lets the Dashboard chat assistant see
  // the real, already-generated report narrative once one exists.
  useEffect(() => {
    if (typeof onReportChange === "function") {
      onReportChange(report);
    }
  }, [report, onReportChange]);

  const contextSummary = useMemo(() => {
    return {
      forecastScale: getForecastScaleLabel(forecastSelection.forecastScale),
      lead: getLeadLabel(
        forecastSelection.lead,
        forecastSelection.seasonalPeriod,
      ),
      seasonalPeriod:
        forecastSelection?.seasonalPeriodLabel ||
        forecastSelection?.seasonalPeriod ||
        getLeadLabel(forecastSelection.lead, forecastSelection.seasonalPeriod),
      seasonalMap: forecastSelection?.seasonalMap || null,
      adminScope: getAdminScope(adminSelection),
      language: getLanguageLabel(normalizedLanguage),
      provider: selectedProviderConfig?.label || selectedProvider,
      model: selectedModelLabel,
    };
  }, [
    forecastSelection,
    adminSelection,
    normalizedLanguage,
    selectedProviderConfig,
    selectedProvider,
    selectedModelLabel,
  ]);

  function handleProviderChange(event) {
    const nextProvider = event.target.value;
    setSelectedProvider(nextProvider);
    setSelectedModel(getDefaultModelForProvider(providerOptions, nextProvider));
  }

  function handleModelChange(event) {
    setSelectedModel(event.target.value);
  }

  async function handleGenerateReport({ forceRefresh = false } = {}) {
    setLoading(true);
    setErrorMessage("");
    setStatusMessage("");

    try {
      setStatusMessage(
        "Building real evidence context from the Hazard/Risk ranking data...",
      );

      // Real Decision Context Envelope -- grounds this report in the SAME
      // /api/hazard-risk/ranking data the Priority Intervention Areas table
      // renders on screen (population/area/priority-score), instead of the
      // old synthetic-grid /api/intervention-ranking system. The backend
      // fills top_admin_areas/all_map_layer_summaries/
      // all_climate_indicator_summaries from this envelope when this
      // request leaves them empty (see merge_envelope_into_request).
      let contextId = null;
      let contextFingerprint = null;
      let contextQuality = null;
      let contextHazardType = null;
      try {
        const contextResponse = await fetch(apiUrl("/api/context/build"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            rank_by: forecastSelection?.hazardRiskLayer || "population_r_drought",
            period: forecastSelection?.hazardRiskPeriod || getCurrentSeasonalPeriod(),
            admin_level: adminSelection?.boundaryLevel || "admin3",
            region_id: adminSelection?.regionId || "",
            zone_id: adminSelection?.zoneId || "",
            target_area_name: selectedPriorityArea?.area_name || null,
            audience: "disaster_manager",
            language: normalizedLanguage,
            requested_provider: selectedProvider,
            requested_model: resolvedSelectedModel || "auto",
            // prompt_version is deliberately never sent -- the backend's own
            // default (app/advisory/prompts) applies: v1 unless a context_id
            // causes merge_envelope_into_request (ai_map_interpretation.py)
            // to escalate to v2. No frontend control for this anymore.
          }),
        });
        if (contextResponse.ok) {
          const contextData = await contextResponse.json();
          contextId = contextData.context_id;
          contextFingerprint = contextData.context_fingerprint;
          contextQuality = {
            score: contextData.quality_score,
            flags: contextData.quality_flags,
          };
          contextHazardType = contextData.envelope?.hazard_evidence?.hazard_type || null;
          setContextInfo({ contextId, quality: contextQuality });
          if (typeof onContextBuilt === "function") {
            onContextBuilt({ contextId, contextFingerprint, contextQuality });
          }
        }
      } catch (contextError) {
        console.warn("Context build failed -- proceeding without it", contextError);
      }

      if (!forceRefresh) {
        const cached = getCachedReport(cacheKey, contextFingerprint);
        if (cached) {
          setReport(cached);
          setStatusMessage(
            `Loaded saved ${getLanguageLabel(normalizedLanguage)} advisory. No new AI provider API call was made.`,
          );
          setLoading(false);
          return;
        }
      }

      setStatusMessage(
        "Preparing Ethiopia-wide spatial summaries for all map layers and climate indicators...",
      );

      // Left empty (rather than fetched from the old /api/intervention-ranking
      // system) so the backend's merge_envelope_into_request fills them from
      // the real context envelope above when a context_id is present.
      const topAreas = [];
      const allMapLayerSummaries = {};
      const allClimateIndicatorSummaries = {};

      const languageLabel = getLanguageLabel(normalizedLanguage);
      const providerLabel = selectedProviderConfig?.label || selectedProvider;
      const modelLabel =
        selectedModelLabel || resolvedSelectedModel || "Automatic";
      setStatusMessage(
        `Generating ${languageLabel} Ethiopia-wide spatial interpretation using ${providerLabel} / ${modelLabel}...`,
      );

      const payload = {
        forecast_selection: forecastSelection,
        admin_selection: adminSelection,
        map_context: {
          metric_type: `Active map group: ${getMapGroupLabel(forecastSelection)}; displayed map: ${getDisplayedMapLabel(forecastSelection)}; Ethiopia-wide summaries for all hazard/risk/exposure/vulnerability layers and all climate indicators`,
          active_map_group: getMapGroupLabel(forecastSelection),
          displayed_map: getDisplayedMapLabel(forecastSelection),
          seasonal_scale: forecastSelection?.seasonalScale || "",
          seasonal_scale_label:
            forecastSelection?.seasonalScaleLabel ||
            titleCase(forecastSelection?.seasonalScale || "seasonal"),
          seasonal_indicator:
            forecastSelection?.seasonalIndicator ||
            forecastSelection?.indicator ||
            "",
          seasonal_indicator_label:
            forecastSelection?.seasonalIndicatorLabel ||
            getIndicatorLabel(forecastSelection?.indicator),
          seasonal_period:
            forecastSelection?.seasonalPeriod || forecastSelection?.lead || "",
          seasonal_period_label:
            forecastSelection?.seasonalPeriodLabel ||
            getLeadLabel(forecastSelection?.lead),
          seasonal_product: forecastSelection?.seasonalProduct || "",
          seasonal_product_label: forecastSelection?.seasonalProductLabel || "",
          climate_map_view: forecastSelection?.climateMapView || "",
          seasonal_map_metadata: forecastSelection?.seasonalMap || null,
          seasonal_compare_maps: forecastSelection?.seasonalCompareMaps || null,
          seasonal_context: `${getForecastScaleLabel(forecastSelection.forecastScale)} ${forecastSelection?.seasonalPeriodLabel || getLeadLabel(forecastSelection.lead)}`,
          current_seasonal_context: `${getForecastScaleLabel(forecastSelection.forecastScale)} forecast for ${forecastSelection?.seasonalPeriodLabel || getLeadLabel(forecastSelection.lead)}`,
          hazard_type:
            selectedPriorityArea?.hazard || contextHazardType || "climate hazard",
          admin_scope: getAdminScope(adminSelection),
          // The real, currently-displayed Hazard/Exposure/Vulnerability/Risk
          // raster layer -- category/layer/period plus that specific map's
          // own statistics (min/max/mean/valid_count) and legend, so the AI
          // can ground its interpretation in the actual layer on screen
          // rather than only the district-ranking summaries below.
          hazard_risk_category: forecastSelection?.hazardRiskCategory || "",
          hazard_risk_category_label:
            forecastSelection?.hazardRiskCategoryLabel || "",
          hazard_risk_layer: forecastSelection?.hazardRiskLayer || "",
          hazard_risk_layer_label:
            forecastSelection?.hazardRiskLayerLabel || "",
          hazard_risk_period: forecastSelection?.hazardRiskPeriod || "",
          hazard_risk_period_label:
            forecastSelection?.hazardRiskPeriodLabel || "",
          hazard_risk_map_units: forecastSelection?.hazardRiskMap?.units || "",
          hazard_risk_map_statistics:
            forecastSelection?.hazardRiskMap?.statistics || null,
          hazard_risk_map_legend:
            forecastSelection?.hazardRiskMap?.legend || null,
        },
        top_admin_areas: topAreas,
        all_map_layer_summaries: allMapLayerSummaries,
        all_climate_indicator_summaries: allClimateIndicatorSummaries,
        map_image_base64: null,
        use_screenshot: false,
        target_language: normalizedLanguage,
        target_language_label: languageLabel,
        audience_focus:
          "farmers, rainfed agriculture, agro-pastoral communities, livestock, policymakers, DRM offices, and humanitarian organizations",
        requested_provider: selectedProvider,
        requested_model: resolvedSelectedModel || "auto",
        requested_model_label: selectedModelLabel,
        // Without this, the backend never receives the real Decision
        // Context Envelope built above, so merge_envelope_into_request
        // never runs -- the LLM would get the empty top_admin_areas/
        // all_map_layer_summaries/all_climate_indicator_summaries set
        // right above instead of real data (a real gap caught via manual
        // end-to-end testing: the context/build call succeeded but its
        // result was silently never forwarded here).
        context_id: contextId,
        // prompt_version is deliberately never sent here either -- see the
        // matching note on the /context/build call above.
      };

      const response = await fetch(apiUrl("/api/ai/map-interpretation"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`AI interpretation request failed: ${response.status}`);
      }

      const data = await response.json();
      setReport(data);
      saveCachedReport(cacheKey, data, contextFingerprint);

      const engine = data?._metadata?.ai_engine || "AI";
      const provider =
        data?._metadata?.provider ||
        selectedProviderConfig?.label ||
        "AI provider";
      const model =
        data?._metadata?.model || selectedModelLabel || "selected model";
      setStatusMessage(
        `Generated and saved ${languageLabel} advisory using ${provider} / ${model} (${engine}).`,
      );
    } catch (error) {
      console.error(error);
      setErrorMessage(
        error.message ||
          "Could not generate AI map interpretation. Check backend endpoint and API key.",
      );
    } finally {
      setLoading(false);
    }
  }

  function handleClearSavedReport() {
    localStorage.removeItem(cacheKey);
    setReport(null);
    setStatusMessage(
      `Saved ${getLanguageLabel(normalizedLanguage)} advisory cleared for the current parameters.`,
    );
  }

  return (
    <section className="panel ai-map-interpretation-panel">
      <div className="ai-map-header">
        <div>
          <span className="ai-map-kicker">AI capability</span>
          <h2>AI Map Interpretation & Advisory</h2>
        </div>
      </div>

      <div className="ai-provider-selectors">
        <label>
          <span>AI provider</span>
          <select
            value={selectedProvider}
            onChange={handleProviderChange}
            disabled={loading}
          >
            {providerOptions.map((provider) => (
              <option key={provider.value} value={provider.value}>
                {provider.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Model</span>
          <select
            value={selectedModel}
            onChange={handleModelChange}
            disabled={loading}
          >
            {(
              selectedProviderConfig?.models?.length
                ? selectedProviderConfig.models
                : [{ value: "auto", label: "Automatic" }]
            ).map((model) => (
              <option key={model.value} value={model.value}>
                {model.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Output language</span>
          <select
            value={normalizedLanguage}
            onChange={(event) => onLanguageChange?.(event.target.value)}
            disabled={loading || typeof onLanguageChange !== "function"}
          >
            {LANGUAGE_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <ContextQualityBadge contextInfo={contextInfo} />
        <ContextAuditDrawer contextId={contextInfo?.contextId || null} />
        <RetrievalDebugPanel contextId={contextInfo?.contextId || null} />
      </div>

      <div className="ai-action-bar">
        <button
          type="button"
          className="ai-generate-button"
          onClick={() => handleGenerateReport({ forceRefresh: false })}
          disabled={loading}
        >
          {loading
            ? "Generating..."
            : `Generate ${contextSummary.language} advisory`}
        </button>

        <button
          type="button"
          className="ai-secondary-action"
          onClick={() => handleGenerateReport({ forceRefresh: true })}
          disabled={loading}
        >
          Force refresh
        </button>

        <button
          type="button"
          className="ai-secondary-action"
          onClick={handleClearSavedReport}
          disabled={loading}
        >
          Clear saved
        </button>
      </div>

      {statusMessage && <div className="ai-status-note">{statusMessage}</div>}
      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      {!report && !loading && (
        <div className="ai-empty-state">
          <h3>No AI interpretation generated yet</h3>
          <p>
            Click <strong>Generate {contextSummary.language} advisory</strong>.
            The system will use all map layers, all climate indicators, local
            RAG guidance, and the selected language. If the same request was
            already generated, it will load the saved advisory instead of
            making another AI provider API call.
          </p>
        </div>
      )}

      {report && (
        <div className="ai-report-card">
          <div className="ai-report-title-row">
            <div>
              <h3>{report.title || "AI Map Interpretation & Advisory"}</h3>
              <p>
                Engine:{" "}
                <strong>
                  {report?._metadata?.ai_engine || "AI provider / fallback"}
                </strong>
                {report?._metadata?.provider
                  ? ` · Provider: ${report._metadata.provider}`
                  : ""}
                {report?._metadata?.model
                  ? ` · Model: ${report._metadata.model}`
                  : ""}
                {report?._metadata?.target_language
                  ? ` · Language: ${report._metadata.target_language}`
                  : report?.target_language
                    ? ` · Language: ${report.target_language}`
                    : ""}
              </p>
              {Array.isArray(report?._metadata?.fallback_stages) &&
                report._metadata.fallback_stages.length > 0 && (
                  <p className="ai-fallback-warning">
                    ⚠{" "}
                    {report._metadata.fallback_stages
                      .map((name) => STAGE_LABELS[name] || name)
                      .join(", ")}{" "}
                    used the rule-based fallback (no live AI provider
                    completed).
                    {report?._metadata?.target_language_code &&
                    report._metadata.target_language_code !== "en"
                      ? ` That text is plain English, not ${report._metadata.target_language} -- the fallback path does not translate.`
                      : ""}
                  </p>
                )}
            </div>
            <div className="ai-report-buttons">
              <button
                type="button"
                className="ai-secondary-action"
                onClick={() => copyReport(report)}
              >
                Copy report
              </button>
              <button
                type="button"
                className="ai-secondary-action"
                onClick={() => downloadReport(report)}
              >
                Export JSON
              </button>
              <button
                type="button"
                className="ai-secondary-action ai-bulletin-action"
                onClick={() =>
                  downloadBulletin(report, {
                    areaName: selectedPriorityArea?.area_name || "Ethiopia (national)",
                    areaSubtitle: selectedPriorityArea?.zone
                      ? `${selectedPriorityArea.zone} · ${selectedPriorityArea.region}`
                      : selectedPriorityArea?.region || "",
                    forecastScaleLabel:
                      forecastSelection?.seasonalScaleLabel ||
                      getForecastScaleLabel(forecastSelection.forecastScale),
                    leadLabel:
                      forecastSelection?.seasonalPeriodLabel ||
                      getLeadLabel(forecastSelection.lead, forecastSelection.seasonalPeriod),
                    languageLabel: getLanguageLabel(normalizedLanguage),
                  })
                }
              >
                Download bulletin
              </button>
            </div>
          </div>

          <ValidationFlagsList flags={report?._metadata?.validation_flags} />

          {/* Split view: indicator-by-indicator (left) | layer-by-layer hazard (right) */}
          <div className="ai-split-view">
            <StructuredSummaryList
              title="Indicator-by-indicator summary"
              items={report.indicator_by_indicator_summary}
              keyField="indicator"
            />
            <StructuredSummaryList
              title="Layer-by-layer hazard summary"
              items={report.layer_by_layer_summary}
              keyField="layer"
            />
          </div>

          <div className="ai-report-grid ai-focused-report-grid">
            <ReportList
              title="Ethiopia-wide spatial overview"
              items={report.national_spatial_overview}
            />
            <ReportList
              title="Compound-hazard interpretation"
              items={report.compound_hazard_interpretation}
            />
          </div>

          <PriorityAreaJustificationList items={report.priority_area_justification} />

          <TimescaledAdvisoryList title="Farmer advisory" advisory={report.farmer_advisory} />
          <TimescaledAdvisoryList title="Agro-pastoral advisory" advisory={report.agro_pastoral_advisory} />
          <CategorizedHumanitarianList priorities={report.humanitarian_priorities} />

          {/* Executive summary sits directly above the SMS/WhatsApp messaging cards */}
          <div className="ai-executive-summary">
            <h4>Executive summary</h4>
            <p className="ai-executive-meta">
              <strong>Forecast window:</strong> {contextSummary.forecastScale} ·{" "}
              <strong>Lead / horizon:</strong> {contextSummary.lead} ·{" "}
              <strong>Admin scope:</strong> {contextSummary.adminScope} ·{" "}
              <strong>Seasonal period:</strong> {contextSummary.seasonalPeriod}{" "}
              · <strong>Output language:</strong> {contextSummary.language}
            </p>
            <p>{report.executive_summary}</p>
          </div>

          {/* One real message per real actionable priority area (see
              _finalize_sms_messages in app/api/report_stages.py) -- not a
              single national message, since the strongest real signals
              are highly localized and a national message risks being
              either too vague to act on or misleading for areas it
              didn't really apply to. */}
          {Array.isArray(report.sms_messages) && report.sms_messages.length > 0 ? (
            report.sms_messages.map((item, index) => (
              <div className="ai-messaging-group" key={`${item.area}-${item.hazard}-${index}`}>
                <div className="ai-messaging-group-label">
                  <strong>{item.area}</strong>
                  <span className="ai-advisory-tag ai-advisory-trigger">{item.hazard}</span>
                  <span className="ai-advisory-tag">{item.audience}</span>
                  {item.cross_indicator_confidence && (
                    <span className={`ai-advisory-tag ai-advisory-confidence confidence-${item.cross_indicator_confidence}`}>
                      {item.cross_indicator_confidence} cross-indicator confidence
                    </span>
                  )}
                </div>
                <div className="ai-messaging-row">
                  <SmsMessageCard text={item.message} languageCode={normalizedLanguage} />
                  <WhatsAppMessageCard text={item.message} />
                </div>
              </div>
            ))
          ) : (
            <p className="ai-messaging-empty">
              No area was actionable enough this period to warrant an SMS alert.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export default AIMapInterpretation;
