import { useEffect, useMemo, useState } from "react";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiUrl } from "../config.js";

const DEFAULT_OPTIONS = {
  forecast_scales: [
    { value: "subseasonal", label: "Subseasonal" },
    { value: "seasonal", label: "Seasonal" },
  ],
  leads: [
    { value: "week_1", label: "Week 1", forecast_scale: "subseasonal" },
    { value: "week_2", label: "Week 2", forecast_scale: "subseasonal" },
    { value: "week_3", label: "Week 3", forecast_scale: "subseasonal" },
    { value: "week_4", label: "Week 4", forecast_scale: "subseasonal" },
    { value: "week_1_2", label: "Week 1-2", forecast_scale: "subseasonal" },
    { value: "week_2_3", label: "Week 2-3", forecast_scale: "subseasonal" },
    { value: "week_3_4", label: "Week 3-4", forecast_scale: "subseasonal" },
    { value: "month_1", label: "Month 1", forecast_scale: "seasonal" },
    { value: "month_2", label: "Month 2", forecast_scale: "seasonal" },
    { value: "month_3", label: "Month 3", forecast_scale: "seasonal" },
    { value: "month_4", label: "Month 4", forecast_scale: "seasonal" },
    { value: "month_5", label: "Month 5", forecast_scale: "seasonal" },
    { value: "month_6", label: "Month 6", forecast_scale: "seasonal" },
  ],
  layers: [
    { value: "hazard", label: "Hazard Map" },
    { value: "risk_score", label: "Risk Score Map" },
    { value: "hazard_probability", label: "Hazard Probability Map" },
    { value: "exposure", label: "Exposure Map" },
    { value: "vulnerability", label: "Vulnerability Map" },
  ],
  indicators: [
    { value: "spi", label: "Standardized Precipitation Index" },
    { value: "rainfall_anomaly_pct", label: "Rainfall anomaly" },
    { value: "rainfall_percentile", label: "Rainfall percentile" },
    { value: "cdd", label: "Consecutive dry days" },
    { value: "cwd", label: "Consecutive wet days" },
  ],
};

const ETHIOPIA_BOUNDS = [
  [3, 33],
  [15, 48],
];

const HAZARD_COLORS = {
  drought: "#D92D20",
  dry_spell: "#F79009",
  heavy_rainfall: "#1570EF",
  wet_spell: "#0E9384",
  no_alert: "#12B76A",
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

function formatValue(value, digits = 2) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "N/A";
  }

  return numberValue.toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getNumericColor(value, layer) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "#CBD5E1";
  }

  if (layer === "risk_score") {
    if (numberValue >= 0.8) return "#D92D20";
    if (numberValue >= 0.6) return "#C11574";
    if (numberValue >= 0.35) return "#F79009";
    return "#12B76A";
  }

  if (numberValue >= 0.8) return "#7F1D1D";
  if (numberValue >= 0.65) return "#B42318";
  if (numberValue >= 0.5) return "#F79009";
  if (numberValue >= 0.35) return "#FEC84B";
  return "#12B76A";
}

function getFillColor(properties, layer) {
  if (layer === "hazard") {
    return HAZARD_COLORS[properties.hazard] || "#94A3B8";
  }

  return getNumericColor(properties[layer], layer);
}

function getLayerValue(properties, layer) {
  if (layer === "hazard") {
    return titleCase(properties.hazard);
  }

  if (layer === "risk_score") {
    return formatValue(properties.risk_score, 3);
  }

  if (layer === "hazard_probability") {
    return formatValue(properties.hazard_probability, 3);
  }

  if (layer === "exposure") {
    return formatValue(properties.exposure, 3);
  }

  if (layer === "vulnerability") {
    return formatValue(properties.vulnerability, 3);
  }

  return "N/A";
}

function getIndicatorLabel(indicator) {
  const match = DEFAULT_OPTIONS.indicators.find((item) => item.value === indicator);
  return match?.label || titleCase(indicator);
}

function getIndicatorValue(properties, indicator) {
  if (indicator === "rainfall_anomaly_pct") {
    return `${formatValue(properties[indicator], 1)}%`;
  }

  if (indicator === "rainfall_percentile") {
    return `${formatValue(properties[indicator], 1)} percentile`;
  }

  if (indicator === "cdd") {
    return `${formatValue(properties[indicator], 0)} days`;
  }

  if (indicator === "cwd") {
    return `${formatValue(properties[indicator], 0)} days`;
  }

  return formatValue(properties[indicator], 2);
}

function FitToEthiopiaDomain() {
  const map = useMap();

  useEffect(() => {
    map.fitBounds(ETHIOPIA_BOUNDS, {
      padding: [20, 20],
    });
  }, [map]);

  return null;
}

function ForecastLayerMap() {
  const [options, setOptions] = useState(DEFAULT_OPTIONS);
  const [forecastScale, setForecastScale] = useState("subseasonal");
  const [lead, setLead] = useState("week_1");
  const [layer, setLayer] = useState("hazard");
  const [indicator, setIndicator] = useState("spi");
  const [geojson, setGeojson] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const filteredLeadOptions = useMemo(() => {
    return options.leads.filter((item) => item.forecast_scale === forecastScale);
  }, [options.leads, forecastScale]);

  useEffect(() => {
    async function loadOptions() {
      try {
        const response = await fetch(apiUrl("/api/map-layers/options"));

        if (!response.ok) {
          throw new Error(`Options request failed: ${response.status}`);
        }

        const data = await response.json();
        setOptions({
          forecast_scales: data.forecast_scales || DEFAULT_OPTIONS.forecast_scales,
          leads: data.leads || DEFAULT_OPTIONS.leads,
          layers: data.layers || DEFAULT_OPTIONS.layers,
          indicators: data.indicators || DEFAULT_OPTIONS.indicators,
        });
      } catch (error) {
        console.error(error);
        setOptions(DEFAULT_OPTIONS);
      }
    }

    loadOptions();
  }, []);

  useEffect(() => {
    const leadsForScale = options.leads.filter(
      (item) => item.forecast_scale === forecastScale
    );

    if (leadsForScale.length > 0 && !leadsForScale.some((item) => item.value === lead)) {
      setLead(leadsForScale[0].value);
    }
  }, [forecastScale, lead, options.leads]);

  useEffect(() => {
    async function loadLayer() {
      setLoading(true);
      setErrorMessage("");

      try {
        const path = `/api/map-layers/ethiopia?forecast_scale=${encodeURIComponent(
          forecastScale
        )}&lead=${encodeURIComponent(lead)}&layer=${encodeURIComponent(
          layer
        )}&indicator=${encodeURIComponent(indicator)}`;

        const response = await fetch(apiUrl(path));

        if (!response.ok) {
          throw new Error(`Layer request failed: ${response.status}`);
        }

        const data = await response.json();
        setGeojson(data);
      } catch (error) {
        console.error(error);
        setGeojson(null);
        setErrorMessage("Could not load Ethiopia forecast map layer.");
      } finally {
        setLoading(false);
      }
    }

    loadLayer();
  }, [forecastScale, lead, layer, indicator]);

  function handleForecastScaleChange(event) {
    const nextScale = event.target.value;
    setForecastScale(nextScale);

    const firstLeadForScale = options.leads.find(
      (item) => item.forecast_scale === nextScale
    );

    if (firstLeadForScale) {
      setLead(firstLeadForScale.value);
    }
  }

  function styleFeature(feature) {
    const properties = feature.properties || {};
    const fillColor = getFillColor(properties, layer);

    return {
      color: "#ffffff",
      weight: 0.45,
      fillColor,
      fillOpacity: 0.72,
    };
  }

  function onEachFeature(feature, leafletLayer) {
    const properties = feature.properties || {};

    const popupHtml = `
      <div class="forecast-popup">
        <h3>Ethiopia Forecast Grid Cell</h3>
        <p><strong>Lead:</strong> ${escapeHtml(properties.lead_label)}</p>
        <p><strong>Map layer:</strong> ${escapeHtml(titleCase(layer))}</p>
        <p><strong>Layer value:</strong> ${escapeHtml(getLayerValue(properties, layer))}</p>
        <p><strong>Hazard:</strong> ${escapeHtml(titleCase(properties.hazard))}</p>
        <p><strong>Risk level:</strong> ${escapeHtml(titleCase(properties.risk_level))}</p>
        <p><strong>${escapeHtml(getIndicatorLabel(indicator))}:</strong> ${escapeHtml(
      getIndicatorValue(properties, indicator)
    )}</p>
        <hr />
        <p><strong>SPI:</strong> ${escapeHtml(formatValue(properties.spi, 2))}</p>
        <p><strong>Rainfall anomaly:</strong> ${escapeHtml(
          formatValue(properties.rainfall_anomaly_pct, 1)
        )}%</p>
        <p><strong>Rainfall percentile:</strong> ${escapeHtml(
          formatValue(properties.rainfall_percentile, 1)
        )}</p>
        <p><strong>CDD:</strong> ${escapeHtml(formatValue(properties.cdd, 0))} days</p>
        <p><strong>CWD:</strong> ${escapeHtml(formatValue(properties.cwd, 0))} days</p>
      </div>
    `;

    leafletLayer.bindPopup(popupHtml);
  }

  const selectedLayerLabel =
    options.layers.find((item) => item.value === layer)?.label || titleCase(layer);

  const selectedLeadLabel =
    options.leads.find((item) => item.value === lead)?.label || titleCase(lead);

  return (
    <section className="panel forecast-layer-section">
      <div className="forecast-layer-header">
        <div>
          <h2>Ethiopia Forecast Risk Layers</h2>
          <p>
            Prototype gridded subseasonal and seasonal forecast layers for Ethiopia
            covering 3°N–15°N and 33°E–48°E.
          </p>
        </div>

        <div className="forecast-domain-badge">
          Lat 3–15°N · Lon 33–48°E
        </div>
      </div>

      <div className="forecast-layer-controls">
        <div className="forecast-control">
          <label htmlFor="forecast-scale">Forecast scale</label>
          <select
            id="forecast-scale"
            value={forecastScale}
            onChange={handleForecastScaleChange}
          >
            {options.forecast_scales.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="forecast-lead">Lead / horizon</label>
          <select
            id="forecast-lead"
            value={lead}
            onChange={(event) => setLead(event.target.value)}
          >
            {filteredLeadOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="forecast-layer">Map layer</label>
          <select
            id="forecast-layer"
            value={layer}
            onChange={(event) => setLayer(event.target.value)}
          >
            {options.layers.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="forecast-indicator">Climate indicator</label>
          <select
            id="forecast-indicator"
            value={indicator}
            onChange={(event) => setIndicator(event.target.value)}
          >
            {options.indicators.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="forecast-layer-summary">
        <div>
          <span>Current layer</span>
          <strong>{selectedLayerLabel}</strong>
        </div>

        <div>
          <span>Forecast horizon</span>
          <strong>{selectedLeadLabel}</strong>
        </div>

        <div>
          <span>Climate indicator</span>
          <strong>{getIndicatorLabel(indicator)}</strong>
        </div>

        <div>
          <span>Grid cells</span>
          <strong>{geojson?.metadata?.feature_count || 0}</strong>
        </div>
      </div>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <div className="forecast-map-layout">
        <div className="forecast-map-wrapper">
          <MapContainer
            center={[9, 40.5]}
            zoom={6}
            minZoom={5}
            maxZoom={9}
            scrollWheelZoom={false}
            className="forecast-map"
          >
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            <FitToEthiopiaDomain />

            {geojson && (
              <GeoJSON
                key={`${forecastScale}-${lead}-${layer}-${indicator}`}
                data={geojson}
                style={styleFeature}
                onEachFeature={onEachFeature}
              />
            )}
          </MapContainer>

          {loading && <div className="forecast-map-loading">Loading map layer...</div>}
        </div>

        <div className="forecast-legend-card">
          <h3>Legend</h3>

          {layer === "hazard" ? (
            <div className="forecast-hazard-legend">
              <span><i style={{ background: HAZARD_COLORS.drought }} />Drought</span>
              <span><i style={{ background: HAZARD_COLORS.dry_spell }} />Dry spell</span>
              <span><i style={{ background: HAZARD_COLORS.heavy_rainfall }} />Heavy rainfall</span>
              <span><i style={{ background: HAZARD_COLORS.wet_spell }} />Wet spell</span>
              <span><i style={{ background: HAZARD_COLORS.no_alert }} />No alert</span>
            </div>
          ) : (
            <div className="forecast-gradient-legend">
              <div className="forecast-gradient-bar" />
              <div className="forecast-gradient-labels">
                <span>Low</span>
                <span>Moderate</span>
                <span>High</span>
              </div>
            </div>
          )}

          <p>
            This layer is a prototype visualization. Operational deployment should
            replace it with real subseasonal and seasonal ensemble forecast data,
            hindcast calibration, bias correction, and administrative boundary summaries.
          </p>
        </div>
      </div>
    </section>
  );
}

export default ForecastLayerMap;