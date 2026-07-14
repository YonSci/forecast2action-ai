import { useEffect, useMemo, useState } from "react";
import html2canvas from "html2canvas";
import { apiUrl } from "../config.js";
import "../styles/aiMapInterpretation.css";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHE_VERSION = "v6-multilanguage-all-layers";

const MAP_LAYERS = [
  { key: "hazard", label: "Hazard map", rankingLayer: "risk_score" },
  { key: "risk_score", label: "Risk score map", rankingLayer: "risk_score" },
  { key: "hazard_probability", label: "Hazard probability map", rankingLayer: "hazard_probability" },
  { key: "exposure", label: "Exposure map", rankingLayer: "exposure" },
  { key: "vulnerability", label: "Vulnerability map", rankingLayer: "vulnerability" },
];

const CLIMATE_INDICATORS = [
  { key: "spi", label: "Standardized Precipitation Index" },
  { key: "rainfall_anomaly_pct", label: "Rainfall anomaly" },
  { key: "rainfall_percentile", label: "Rainfall percentile" },
  { key: "cdd", label: "Consecutive dry days" },
  { key: "cwd", label: "Consecutive wet days" },
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
  sw: "Swahili",
  fr: "French",
  ar: "Arabic",
};

function normalizeLanguageCode(value) {
  const text = String(value || "en").trim().toLowerCase();

  if (["am", "amh", "amharic", "am-et", "አማርኛ"].includes(text)) {
    return "am";
  }

  if (["om", "orm", "oromo", "oromifa", "afaan oromo", "afan oromo", "or"].includes(text)) {
    return "om";
  }

  if (["ti", "tir", "tig", "tigrinya", "tigrigna", "ትግርኛ"].includes(text)) {
    return "ti";
  }

  if (["so", "som", "somali", "af-soomaali", "af soomaali", "soomaali"].includes(text)) {
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

function getLeadLabel(value) {
  return LEAD_LABELS[value] || titleCase(value || "week_1");
}

function getForecastScaleLabel(value) {
  return FORECAST_SCALE_LABELS[value] || titleCase(value || "subseasonal");
}

function getLayerLabel(value) {
  return MAP_LAYERS.find((item) => item.key === value)?.label || titleCase(value || "risk_score");
}

function getIndicatorLabel(value) {
  return CLIMATE_INDICATORS.find((item) => item.key === value)?.label || titleCase(value || "spi");
}

function getAdminScope(adminSelection) {
  return (
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia"
  );
}

function getDefaultHazard(topAreas) {
  const first = Array.isArray(topAreas) ? topAreas[0] : null;
  return first?.hazard || "climate hazard";
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

function buildCacheKey({ forecastSelection, adminSelection, normalizedLanguage, useScreenshot }) {
  const cacheIdentity = {
    cacheVersion: CACHE_VERSION,
    forecastScale: forecastSelection?.forecastScale || "subseasonal",
    lead: forecastSelection?.lead || "week_1",
    admin: {
      regionId: adminSelection?.regionId || "",
      zoneId: adminSelection?.zoneId || "",
      woredaId: adminSelection?.woredaId || "",
      regionLabel: adminSelection?.regionLabel || "",
      zoneLabel: adminSelection?.zoneLabel || "",
      woredaLabel: adminSelection?.woredaLabel || "",
    },
    targetLanguage: normalizedLanguage || "en",
    useScreenshot: Boolean(useScreenshot),
    layerMode: "all-map-layers",
    indicatorMode: "all-climate-indicators",
  };

  return `forecast2action-ai-map-report:${simpleHash(stableStringify(cacheIdentity))}`;
}

function getCachedReport(cacheKey) {
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

    return record.report;
  } catch (error) {
    console.warn("Could not read AI report cache", error);
    return null;
  }
}

function saveCachedReport(cacheKey, report) {
  try {
    localStorage.setItem(
      cacheKey,
      JSON.stringify({
        createdAt: Date.now(),
        report,
      })
    );
  } catch (error) {
    console.warn("Could not save AI report cache", error);
  }
}

function normalizeArea(item = {}) {
  return {
    rank: item.rank,
    area_name: item.area_name,
    region: item.region,
    zone: item.zone,
    woreda: item.woreda,
    admin_level: item.admin_level,
    hazard: item.hazard,
    risk_level: item.risk_level,
    risk_score: item.risk_score,
    hazard_probability: item.hazard_probability,
    exposure: item.exposure,
    vulnerability: item.vulnerability,
    priority_score: item.priority_score,
    spi: item.spi,
    rainfall_anomaly_pct: item.rainfall_anomaly_pct,
    rainfall_percentile: item.rainfall_percentile,
    cdd: item.cdd,
    cwd: item.cwd,
  };
}

async function fetchRanking({ forecastSelection, adminSelection, layer, indicator, topN = 8 }) {
  const params = new URLSearchParams();

  params.set("forecast_scale", forecastSelection.forecastScale || "subseasonal");
  params.set("lead", forecastSelection.lead || "week_1");
  params.set("layer", layer || "risk_score");
  params.set("indicator", indicator || "spi");
  params.set("admin_level", "admin3");
  params.set("selection_mode", "top");
  params.set("top_n", String(topN));
  params.set("threshold", "0.6");

  if (adminSelection?.regionId) {
    params.set("region_id", adminSelection.regionId);
  }

  if (adminSelection?.zoneId) {
    params.set("zone_id", adminSelection.zoneId);
  }

  const response = await fetch(apiUrl(`/api/intervention-ranking?${params.toString()}`));

  if (!response.ok) {
    throw new Error(`Ranking request failed: ${response.status}`);
  }

  const data = await response.json();
  return Array.isArray(data?.ranking) ? data.ranking.map(normalizeArea) : [];
}

function summarizeRanking(items, valueKey) {
  const values = items
    .map((item) => Number(item?.[valueKey]))
    .filter((value) => Number.isFinite(value));

  const topAreas = items.slice(0, 8).map(normalizeArea);

  if (values.length === 0) {
    return { value_key: valueKey, count: items.length, top_areas: topAreas };
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const mean = values.reduce((total, value) => total + value, 0) / values.length;

  return { value_key: valueKey, count: items.length, min, max, mean, top_areas: topAreas };
}

async function buildAllLayerSummaries(forecastSelection, adminSelection) {
  const entries = await Promise.all(
    MAP_LAYERS.map(async (layer) => {
      const ranking = await fetchRanking({
        forecastSelection,
        adminSelection,
        layer: layer.rankingLayer,
        indicator: forecastSelection.indicator || "spi",
        topN: 8,
      });
      const valueKey = layer.key === "hazard" ? "risk_score" : layer.key;
      return [
        layer.key,
        {
          label: layer.label,
          ranking_layer_used: layer.rankingLayer,
          selected_indicator_used: forecastSelection.indicator || "spi",
          ...summarizeRanking(ranking, valueKey),
        },
      ];
    })
  );
  return Object.fromEntries(entries);
}

async function buildAllClimateIndicatorSummaries(forecastSelection, adminSelection) {
  const entries = await Promise.all(
    CLIMATE_INDICATORS.map(async (indicator) => {
      const ranking = await fetchRanking({
        forecastSelection,
        adminSelection,
        layer: "risk_score",
        indicator: indicator.key,
        topN: 8,
      });
      return [
        indicator.key,
        {
          label: indicator.label,
          ranking_layer_used: "risk_score",
          ...summarizeRanking(ranking, indicator.key),
        },
      ];
    })
  );
  return Object.fromEntries(entries);
}

async function captureForecastMap() {
  const target =
    document.querySelector("#forecast-risk-map") ||
    document.querySelector(".forecast-map-wrapper") ||
    document.querySelector(".forecast-map") ||
    document.querySelector(".leaflet-container");

  if (!target) {
    return null;
  }

  const canvas = await html2canvas(target, {
    useCORS: true,
    allowTaint: false,
    backgroundColor: null,
    scale: 0.7,
    logging: false,
  });

  return canvas.toDataURL("image/png", 0.72);
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

function copyReport(report) {
  const lines = [
    report.title || "AI Map Interpretation & Advisory",
    "",
    "Executive summary",
    report.executive_summary || "",
    "",
    "Spatial interpretation",
    ...(report.spatial_interpretation || []).map((item) => `- ${item}`),
    "",
    "Highest-risk areas",
    ...(report.highest_risk_areas || []).map((item) => `- ${item}`),
    "",
    "Climate indicator interpretation",
    ...(report.climate_indicator_interpretation || []).map((item) => `- ${item}`),
    "",
    "Cross-layer insights",
    ...(report.cross_layer_insights || []).map((item) => `- ${item}`),
    "",
    "Impact assessment",
    ...(report.impact_assessment || []).map((item) => `- ${item}`),
    "",
    "Farmer advisory",
    ...(report.farmer_advisory || []).map((item) => `- ${item}`),
    "",
    "Policy recommendations",
    ...(report.policy_recommendations || []).map((item) => `- ${item}`),
    "",
    "Humanitarian priorities",
    ...(report.humanitarian_priorities || []).map((item) => `- ${item}`),
    "",
    "Confidence note",
    report.confidence_note || "",
    "",
    "SMS summary",
    report.sms_summary || "",
  ];

  navigator.clipboard?.writeText(lines.join("\n"));
}

function downloadReport(report) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "ai_map_interpretation_report.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

function AIMapInterpretation({
  forecastSelection = {},
  adminSelection = {},
  selectedPriorityArea = null,
  selectedLanguage = "en",
}) {
  const [useScreenshot, setUseScreenshot] = useState(true);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [statusMessage, setStatusMessage] = useState("");

  const normalizedLanguage = useMemo(
    () => normalizeLanguageCode(selectedLanguage),
    [selectedLanguage]
  );

  const cacheKey = useMemo(() => {
    return buildCacheKey({
      forecastSelection,
      adminSelection,
      normalizedLanguage,
      useScreenshot,
    });
  }, [forecastSelection, adminSelection, normalizedLanguage, useScreenshot]);

  useEffect(() => {
    const cached = getCachedReport(cacheKey);
    setReport(cached);
    setErrorMessage("");
    setStatusMessage(
      cached
        ? `Loaded saved ${getLanguageLabel(normalizedLanguage)} advisory from this browser cache.`
        : ""
    );
  }, [cacheKey, normalizedLanguage]);

  const contextSummary = useMemo(() => {
    return {
      forecastScale: getForecastScaleLabel(forecastSelection.forecastScale),
      lead: getLeadLabel(forecastSelection.lead),
      activeLayer: getLayerLabel(forecastSelection.layer),
      activeIndicator: getIndicatorLabel(forecastSelection.indicator),
      adminScope: getAdminScope(adminSelection),
      language: getLanguageLabel(normalizedLanguage),
    };
  }, [forecastSelection, adminSelection, normalizedLanguage]);

  async function handleGenerateReport({ forceRefresh = false } = {}) {
    setLoading(true);
    setErrorMessage("");
    setStatusMessage("");

    try {
      if (!forceRefresh) {
        const cached = getCachedReport(cacheKey);
        if (cached) {
          setReport(cached);
          setStatusMessage(`Loaded saved ${getLanguageLabel(normalizedLanguage)} advisory. No new OpenAI API call was made.`);
          setLoading(false);
          return;
        }
      }

      setStatusMessage("Preparing all map layer and climate indicator summaries...");

      const rankingLayer =
        forecastSelection.layer && forecastSelection.layer !== "hazard"
          ? forecastSelection.layer
          : "risk_score";

      const [topAreas, allMapLayerSummaries, allClimateIndicatorSummaries] =
        await Promise.all([
          fetchRanking({
            forecastSelection,
            adminSelection,
            layer: rankingLayer,
            indicator: forecastSelection.indicator || "spi",
            topN: 8,
          }),
          buildAllLayerSummaries(forecastSelection, adminSelection),
          buildAllClimateIndicatorSummaries(forecastSelection, adminSelection),
        ]);

      let mapImageBase64 = null;
      if (useScreenshot) {
        try {
          setStatusMessage("Capturing current map screenshot...");
          mapImageBase64 = await captureForecastMap();
        } catch (captureError) {
          console.warn(captureError);
          mapImageBase64 = null;
        }
      }

      const languageLabel = getLanguageLabel(normalizedLanguage);
      setStatusMessage(`Generating ${languageLabel} advisory from all layers, all indicators, RAG guidance, and selected language...`);

      const payload = {
        forecast_selection: forecastSelection,
        admin_selection: adminSelection,
        map_context: {
          metric_type: "All hazard, risk, exposure, vulnerability, and climate indicator map summaries",
          seasonal_context: `${getForecastScaleLabel(forecastSelection.forecastScale)} ${getLeadLabel(forecastSelection.lead)}`,
          current_seasonal_context: `${getForecastScaleLabel(forecastSelection.forecastScale)} forecast for ${getLeadLabel(forecastSelection.lead)}`,
          hazard_type: selectedPriorityArea?.hazard || getDefaultHazard(topAreas),
          admin_scope: getAdminScope(adminSelection),
        },
        top_admin_areas: topAreas,
        all_map_layer_summaries: allMapLayerSummaries,
        all_climate_indicator_summaries: allClimateIndicatorSummaries,
        map_image_base64: mapImageBase64,
        use_screenshot: Boolean(mapImageBase64),
        target_language: normalizedLanguage,
        target_language_label: languageLabel,
        audience_focus:
          "farmers, rainfed agriculture, agro-pastoral communities, livestock, policymakers, DRM offices, and humanitarian organizations",
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
      saveCachedReport(cacheKey, data);

      const engine = data?._metadata?.ai_engine || "AI";
      setStatusMessage(`Generated and saved ${languageLabel} advisory using ${engine}.`);
    } catch (error) {
      console.error(error);
      setErrorMessage(error.message || "Could not generate AI map interpretation. Check backend endpoint and API key.");
    } finally {
      setLoading(false);
    }
  }

  function handleClearSavedReport() {
    localStorage.removeItem(cacheKey);
    setReport(null);
    setStatusMessage(`Saved ${getLanguageLabel(normalizedLanguage)} advisory cleared for the current parameters.`);
  }

  return (
    <section className="panel ai-map-interpretation-panel">
      <div className="ai-map-header">
        <div>
          <span className="ai-map-kicker">AI capability</span>
          <h2>AI Map Interpretation & Advisory</h2>
          <p>
            Interprets all hazard/risk layers and all climate indicators, uses
            RAG guidance and an optional map screenshot, then generates localized
            advice in the selected community message language.
          </p>
        </div>
      </div>

      <div className="ai-context-grid">
        <div>
          <span>Forecast window</span>
          <strong>{contextSummary.forecastScale}</strong>
        </div>
        <div>
          <span>Lead / horizon</span>
          <strong>{contextSummary.lead}</strong>
        </div>
        <div>
          <span>Active map layer</span>
          <strong>{contextSummary.activeLayer}</strong>
        </div>
        <div>
          <span>Active climate indicator</span>
          <strong>{contextSummary.activeIndicator}</strong>
        </div>
        <div>
          <span>Admin scope</span>
          <strong>{contextSummary.adminScope}</strong>
        </div>
        <div>
          <span>Output language</span>
          <strong>{contextSummary.language}</strong>
        </div>
      </div>

      <div className="ai-included-data">
        <div>
          <span>Map layers used</span>
          <strong>Hazard · Risk score · Hazard probability · Exposure · Vulnerability</strong>
        </div>
        <div>
          <span>Climate indicators used</span>
          <strong>SPI · Rainfall anomaly · Rainfall percentile · CDD · CWD</strong>
        </div>
      </div>

      <div className="ai-action-bar">
        <label className="ai-toggle">
          <input
            type="checkbox"
            checked={useScreenshot}
            onChange={(event) => setUseScreenshot(event.target.checked)}
          />
          Use current map screenshot
        </label>

        <button
          type="button"
          className="ai-generate-button"
          onClick={() => handleGenerateReport({ forceRefresh: false })}
          disabled={loading}
        >
          {loading ? "Generating..." : `Generate ${contextSummary.language} advisory`}
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
            Click <strong>Generate {contextSummary.language} advisory</strong>. The system will use all map
            layers, all climate indicators, local RAG guidance, the selected
            language, and an optional map screenshot. If the same request was
            already generated, it will load the saved advisory instead of making
            another OpenAI API call.
          </p>
        </div>
      )}

      {report && (
        <div className="ai-report-card">
          <div className="ai-report-title-row">
            <div>
              <h3>{report.title || "AI Map Interpretation & Advisory"}</h3>
              <p>
                Engine: <strong>{report?._metadata?.ai_engine || "OpenAI / fallback"}</strong>
                {report?._metadata?.model ? ` · Model: ${report._metadata.model}` : ""}
                {report?._metadata?.target_language ? ` · Language: ${report._metadata.target_language}` : report?.target_language ? ` · Language: ${report.target_language}` : ""}
              </p>
            </div>
            <div className="ai-report-buttons">
              <button type="button" className="ai-secondary-action" onClick={() => copyReport(report)}>
                Copy report
              </button>
              <button type="button" className="ai-secondary-action" onClick={() => downloadReport(report)}>
                Export JSON
              </button>
            </div>
          </div>

          <div className="ai-executive-summary">
            <h4>Executive summary</h4>
            <p>{report.executive_summary}</p>
          </div>

          <div className="ai-report-grid">
            <ReportList title="Spatial interpretation" items={report.spatial_interpretation} />
            <ReportList title="Highest-risk areas" items={report.highest_risk_areas} />
            <ReportList title="Climate indicator interpretation" items={report.climate_indicator_interpretation} />
            <ReportList title="Cross-layer insights" items={report.cross_layer_insights} />
            <ReportList title="Impact assessment" items={report.impact_assessment} />
            <ReportList title="Farmer and agro-pastoral advisory" items={report.farmer_advisory} />
            <ReportList title="Policy recommendations" items={report.policy_recommendations} />
            <ReportList title="Humanitarian priorities" items={report.humanitarian_priorities} />
          </div>

          <div className="ai-bottom-grid">
            <div className="ai-confidence-note">
              <h4>Confidence and caveats</h4>
              <p>{report.confidence_note}</p>
            </div>
            <div className="ai-sms-summary">
              <h4>SMS summary</h4>
              <p>{report.sms_summary}</p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export default AIMapInterpretation;
