import { useEffect, useMemo, useState } from "react";
import html2canvas from "html2canvas";
import { apiUrl } from "../config.js";
import "../styles/aiMapInterpretation.css";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHE_VERSION = "v11-multi-provider-model-select";

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
  fr: "French",
  ar: "Arabic",
};

const FALLBACK_AI_PROVIDER_OPTIONS = [
  {
    value: "free_auto",
    label: "Automatic free-provider chain",
    description: "NVIDIA NIM → Gemini → Groq if screenshot is off → OpenRouter → OpenAI → fallback",
    supports_screenshot: true,
    models: [{ value: "auto", label: "Automatic model per provider chain" }],
  },
  {
    value: "nvidia",
    label: "NVIDIA NIM",
    description: "Best for map screenshot + structured JSON summaries.",
    supports_screenshot: true,
    models: [
      { value: "nvidia/llama-3.1-nemotron-nano-vl-8b-v1", label: "NVIDIA Llama 3.1 Nemotron Nano VL 8B" },
      { value: "meta/llama-3.2-11b-vision-instruct", label: "Meta Llama 3.2 11B Vision Instruct" },
      { value: "meta/llama-3.2-90b-vision-instruct", label: "Meta Llama 3.2 90B Vision Instruct" },
      { value: "custom", label: "Custom NVIDIA NIM model ID" },
    ],
  },
  {
    value: "gemini",
    label: "Google Gemini",
    description: "Multimodal option for screenshot + text summaries.",
    supports_screenshot: true,
    models: [
      { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
      { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash-Lite" },
      { value: "custom", label: "Custom Gemini model ID" },
    ],
  },
  {
    value: "groq",
    label: "Groq",
    description: "Fast text-only mode. Turn screenshot off before using Groq.",
    supports_screenshot: false,
    models: [
      { value: "openai/gpt-oss-120b", label: "GPT-OSS 120B on Groq" },
      { value: "llama-3.3-70b-versatile", label: "Llama 3.3 70B Versatile on Groq" },
      { value: "custom", label: "Custom Groq model ID" },
    ],
  },
  {
    value: "openrouter",
    label: "OpenRouter",
    description: "Free-model router / fallback route.",
    supports_screenshot: true,
    models: [
      { value: "openrouter/free", label: "OpenRouter free model router" },
      { value: "custom", label: "Custom OpenRouter model ID" },
    ],
  },
  {
    value: "openai",
    label: "OpenAI",
    description: "Paid fallback if API billing is available.",
    supports_screenshot: true,
    models: [
      { value: "gpt-5", label: "GPT-5" },
      { value: "gpt-4.1", label: "GPT-4.1" },
      { value: "gpt-4o", label: "GPT-4o" },
      { value: "custom", label: "Custom OpenAI model ID" },
    ],
  },
];

function getProviderConfig(providerOptions, providerValue) {
  return (
    providerOptions.find((item) => item.value === providerValue) ||
    providerOptions.find((item) => item.value === "free_auto") ||
    providerOptions[0]
  );
}

function getDefaultModelForProvider(providerOptions, providerValue) {
  const config = getProviderConfig(providerOptions, providerValue);
  return config?.models?.[0]?.value || "auto";
}

function getModelLabel(providerConfig, modelValue, customModel) {
  if (modelValue === "custom") {
    return customModel?.trim() || "Custom model ID";
  }

  return providerConfig?.models?.find((item) => item.value === modelValue)?.label || modelValue || "Automatic";
}

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

function buildCacheKey({
  forecastSelection,
  adminSelection,
  normalizedLanguage,
  useScreenshot,
  selectedProvider,
  selectedModel,
}) {
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
    aiProvider: selectedProvider || "free_auto",
    aiModel: selectedModel || "auto",
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

async function fetchRanking({ forecastSelection, adminSelection, layer, indicator, topN = 2500 }) {
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

function quantile(sortedValues, q) {
  if (!sortedValues.length) {
    return null;
  }

  const position = (sortedValues.length - 1) * q;
  const base = Math.floor(position);
  const rest = position - base;

  if (sortedValues[base + 1] !== undefined) {
    return sortedValues[base] + rest * (sortedValues[base + 1] - sortedValues[base]);
  }

  return sortedValues[base];
}

function summarizeByRegion(items, valueKey) {
  const groups = new Map();

  items.forEach((item) => {
    const value = Number(item?.[valueKey]);
    if (!Number.isFinite(value)) {
      return;
    }

    const region = item?.region || "Unknown region";
    if (!groups.has(region)) {
      groups.set(region, {
        region,
        count: 0,
        sum: 0,
        min: value,
        max: value,
        examples: [],
      });
    }

    const group = groups.get(region);
    group.count += 1;
    group.sum += value;
    group.min = Math.min(group.min, value);
    group.max = Math.max(group.max, value);

    if (group.examples.length < 5) {
      group.examples.push(normalizeArea(item));
    }
  });

  const summaries = Array.from(groups.values()).map((group) => ({
    region: group.region,
    count: group.count,
    mean: group.sum / group.count,
    min: group.min,
    max: group.max,
    examples: group.examples,
  }));

  return {
    top_regions_by_mean: [...summaries]
      .sort((a, b) => b.mean - a.mean)
      .slice(0, 5),
    bottom_regions_by_mean: [...summaries]
      .sort((a, b) => a.mean - b.mean)
      .slice(0, 5),
  };
}

function summarizeHazardCategories(items) {
  const counts = {};

  items.forEach((item) => {
    const hazard = item?.hazard || "Unclassified";
    const riskLevel = item?.risk_level || "Unclassified";
    const key = `${hazard} / ${riskLevel}`;
    counts[key] = (counts[key] || 0) + 1;
  });

  return Object.entries(counts)
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
}

function summarizeRanking(items, valueKey) {
  const validItems = items
    .map((item) => ({ ...normalizeArea(item), _value: Number(item?.[valueKey]) }))
    .filter((item) => Number.isFinite(item._value));

  const values = validItems.map((item) => item._value).sort((a, b) => a - b);
  const highToLow = [...validItems].sort((a, b) => b._value - a._value);
  const lowToHigh = [...validItems].sort((a, b) => a._value - b._value);

  if (values.length === 0) {
    return {
      value_key: valueKey,
      count: items.length,
      national_summary_note:
        "No numeric values were available for this layer or indicator. Interpret using available hazard/risk categories and map screenshot.",
      highest_value_areas: items.slice(0, 8).map(normalizeArea),
      lowest_value_areas: [],
      hotspot_regions: [],
      low_value_regions: [],
      hazard_risk_categories: summarizeHazardCategories(items),
    };
  }

  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  const regional = summarizeByRegion(validItems, valueKey);

  return {
    value_key: valueKey,
    count: values.length,
    min: values[0],
    max: values[values.length - 1],
    mean,
    q10: quantile(values, 0.10),
    q25: quantile(values, 0.25),
    median: quantile(values, 0.50),
    q75: quantile(values, 0.75),
    q90: quantile(values, 0.90),
    highest_value_areas: highToLow.slice(0, 8).map(({ _value, ...item }) => ({ ...item, value: _value })),
    lowest_value_areas: lowToHigh.slice(0, 8).map(({ _value, ...item }) => ({ ...item, value: _value })),
    hotspot_regions: regional.top_regions_by_mean,
    low_value_regions: regional.bottom_regions_by_mean,
    hazard_risk_categories: summarizeHazardCategories(items),
    interpretation_hint:
      "Use highest_value_areas, lowest_value_areas, hotspot_regions, and low_value_regions to describe spatial distribution across Ethiopia, not only priority intervention areas.",
  };
}

async function buildAllLayerSummaries(forecastSelection, adminSelection) {
  const entries = await Promise.all(
    MAP_LAYERS.map(async (layer) => {
      const ranking = await fetchRanking({
        forecastSelection,
        adminSelection,
        layer: layer.rankingLayer,
        indicator: forecastSelection.indicator || "spi",
        topN: 2500,
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
        topN: 2500,
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
    "Layer-by-layer map summary",
    ...(report.layer_by_layer_summary || []).map((item) => `- ${item}`),
    "",
    "Indicator-by-indicator summary",
    ...(report.indicator_by_indicator_summary || []).map((item) => `- ${item}`),
    "",
    "Executive summary",
    report.executive_summary || "",
    "",
    "Ethiopia-wide spatial overview",
    ...(report.national_spatial_overview || []).map((item) => `- ${item}`),
    "",
    "Why priority areas were selected",
    ...(report.priority_area_justification || []).map((item) => `- ${item}`),
    "",
    "Farmer advisory",
    ...(report.farmer_advisory || []).map((item) => `- ${item}`),
    "",
    "Humanitarian priorities",
    ...(report.humanitarian_priorities || []).map((item) => `- ${item}`),
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
  const [providerOptions, setProviderOptions] = useState(FALLBACK_AI_PROVIDER_OPTIONS);
  const [selectedProvider, setSelectedProvider] = useState("free_auto");
  const [selectedModel, setSelectedModel] = useState("auto");
  const [customModel, setCustomModel] = useState("");
  const [providerStatus, setProviderStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [statusMessage, setStatusMessage] = useState("");

  const normalizedLanguage = useMemo(
    () => normalizeLanguageCode(selectedLanguage),
    [selectedLanguage]
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
        const options = Array.isArray(data?.providers) && data.providers.length > 0 ? data.providers : FALLBACK_AI_PROVIDER_OPTIONS;
        setProviderOptions(options);
        setProviderStatus(data);
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

  const resolvedSelectedModel = useMemo(() => {
    return selectedModel === "custom" ? customModel.trim() : selectedModel;
  }, [selectedModel, customModel]);

  const selectedModelLabel = useMemo(() => {
    return getModelLabel(selectedProviderConfig, selectedModel, customModel);
  }, [selectedProviderConfig, selectedModel, customModel]);

  const cacheKey = useMemo(() => {
    return buildCacheKey({
      forecastSelection,
      adminSelection,
      normalizedLanguage,
      useScreenshot,
      selectedProvider,
      selectedModel: resolvedSelectedModel || selectedModel,
    });
  }, [forecastSelection, adminSelection, normalizedLanguage, useScreenshot, selectedProvider, selectedModel, resolvedSelectedModel]);

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
      provider: selectedProviderConfig?.label || selectedProvider,
      model: selectedModelLabel,
    };
  }, [forecastSelection, adminSelection, normalizedLanguage, selectedProviderConfig, selectedProvider, selectedModelLabel]);

  function handleProviderChange(event) {
    const nextProvider = event.target.value;
    setSelectedProvider(nextProvider);
    setSelectedModel(getDefaultModelForProvider(providerOptions, nextProvider));
    setCustomModel("");
  }

  function handleModelChange(event) {
    setSelectedModel(event.target.value);
  }

  async function handleGenerateReport({ forceRefresh = false } = {}) {
    setLoading(true);
    setErrorMessage("");
    setStatusMessage("");

    try {
      if (!forceRefresh) {
        const cached = getCachedReport(cacheKey);
        if (cached) {
          setReport(cached);
          setStatusMessage(`Loaded saved ${getLanguageLabel(normalizedLanguage)} advisory. No new AI provider API call was made.`);
          setLoading(false);
          return;
        }
      }

      if (selectedProvider === "groq" && useScreenshot) {
        setUseScreenshot(false);
        throw new Error("Groq is configured as text-only in this workflow. Turn off 'Use current map screenshot' or select NVIDIA, Gemini, OpenRouter, OpenAI, or Automatic.");
      }

      if (selectedModel === "custom" && !customModel.trim()) {
        throw new Error("Please enter a custom model ID, or choose a model from the list.");
      }

      setStatusMessage("Preparing Ethiopia-wide spatial summaries for all map layers and climate indicators...");

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
            topN: 2500,
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
      const providerLabel = selectedProviderConfig?.label || selectedProvider;
      const modelLabel = selectedModelLabel || resolvedSelectedModel || "Automatic";
      setStatusMessage(`Generating ${languageLabel} Ethiopia-wide spatial interpretation using ${providerLabel} / ${modelLabel}...`);

      const payload = {
        forecast_selection: forecastSelection,
        admin_selection: adminSelection,
        map_context: {
          metric_type: "Ethiopia-wide summaries for all hazard/risk/exposure/vulnerability layers and all climate indicators",
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
        requested_provider: selectedProvider,
        requested_model: resolvedSelectedModel || "auto",
        requested_model_label: selectedModelLabel,
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
      const provider = data?._metadata?.provider || selectedProviderConfig?.label || "AI provider";
      const model = data?._metadata?.model || selectedModelLabel || "selected model";
      setStatusMessage(`Generated and saved ${languageLabel} advisory using ${provider} / ${model} (${engine}).`);
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
            Interprets Ethiopia-wide spatial distribution for all hazard/risk layers and climate indicators,
            explains why priority areas were selected, and generates focused farmer and humanitarian advisories
            in the selected community message language.
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
        <div>
          <span>AI provider</span>
          <strong>{contextSummary.provider}</strong>
        </div>
        <div>
          <span>AI model</span>
          <strong>{contextSummary.model}</strong>
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
        <div className="ai-provider-selectors">
          <label>
            <span>AI provider</span>
            <select value={selectedProvider} onChange={handleProviderChange} disabled={loading}>
              {providerOptions.map((provider) => (
                <option key={provider.value} value={provider.value}>
                  {provider.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Model</span>
            <select value={selectedModel} onChange={handleModelChange} disabled={loading}>
              {(selectedProviderConfig?.models || [{ value: "auto", label: "Automatic" }]).map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </select>
          </label>

          {selectedModel === "custom" && (
            <label className="ai-custom-model-field">
              <span>Custom model ID</span>
              <input
                type="text"
                value={customModel}
                onChange={(event) => setCustomModel(event.target.value)}
                placeholder="provider/model-id"
                disabled={loading}
              />
            </label>
          )}
        </div>

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

      {selectedProviderConfig?.description && (
        <div className="ai-provider-note">
          <strong>{selectedProviderConfig.label}:</strong> {selectedProviderConfig.description}
          {selectedProvider === "groq" && useScreenshot ? " Groq is text-only in this app, so disable the screenshot toggle before generating." : ""}
          {providerStatus?.configured && selectedProvider !== "free_auto" && providerStatus.configured[selectedProvider] === false ? " API key is not configured for this provider, so the backend will fall back if you generate." : ""}
        </div>
      )}

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
            another AI provider API call.
          </p>
        </div>
      )}

      {report && (
        <div className="ai-report-card">
          <div className="ai-report-title-row">
            <div>
              <h3>{report.title || "AI Map Interpretation & Advisory"}</h3>
              <p>
                Engine: <strong>{report?._metadata?.ai_engine || "AI provider / fallback"}</strong>
                {report?._metadata?.provider ? ` · Provider: ${report._metadata.provider}` : ""}
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

          <div className="ai-first-output-grid">
            <ReportList title="Layer-by-layer map summary" items={report.layer_by_layer_summary} />
            <ReportList title="Indicator-by-indicator summary" items={report.indicator_by_indicator_summary} />
          </div>

          <div className="ai-executive-summary">
            <h4>Executive summary</h4>
            <p className="ai-executive-meta">
              <strong>Forecast window:</strong> {contextSummary.forecastScale} · {" "}
              <strong>Lead / horizon:</strong> {contextSummary.lead} · {" "}
              <strong>Admin scope:</strong> {contextSummary.adminScope} · {" "}
              <strong>Active map layer:</strong> {contextSummary.activeLayer} · {" "}
              <strong>Active climate indicator:</strong> {contextSummary.activeIndicator} · {" "}
              <strong>Output language:</strong> {contextSummary.language}
            </p>
            <p>{report.executive_summary}</p>
          </div>

          <div className="ai-report-grid ai-focused-report-grid">
            <ReportList title="Ethiopia-wide spatial overview" items={report.national_spatial_overview} />
            <ReportList title="Why priority areas were selected" items={report.priority_area_justification} />
            <ReportList title="Farmer and agro-pastoral advisory" items={report.farmer_advisory} />
            <ReportList title="Humanitarian priorities" items={report.humanitarian_priorities} />
          </div>

          {report.sms_summary && (
            <div className="ai-sms-summary ai-sms-summary-wide">
              <h4>SMS summary</h4>
              <p>{report.sms_summary}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default AIMapInterpretation;
