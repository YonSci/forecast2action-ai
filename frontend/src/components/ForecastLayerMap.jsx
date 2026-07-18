import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiUrl } from "../config.js";
import "../styles/mapSwitcher.css";

const MAP_MODES = [
  {
    value: "hazard_layer",
    label: "Hazard Map Layer",
    shortLabel: "Hazard layers",
    description: "View forecast hazard, risk score, probability, exposure, and vulnerability layers.",
  },
  {
    value: "climate_indicator",
    label: "Climate Indicator",
    shortLabel: "Climate indicators",
    description: "View SPI, rainfall anomaly, rainfall percentile, CDD, and CWD indicator maps.",
  },
];

const OPTIONS = {
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

const ETHIOPIA_CENTER = [9, 40.5];

const ETHIOPIA_BOUNDS = [
  [3, 33],
  [15, 48],
];

const ETHIOPIA_MAX_BOUNDS = [
  [1.5, 31.5],
  [16.5, 49.5],
];

const HAZARD_COLORS = {
  drought: "#D92D20",
  dry_spell: "#F79009",
  heavy_rainfall: "#1570EF",
  wet_spell: "#0E9384",
  no_alert: "#12B76A",
};

const INDICATOR_LEGENDS = {
  spi: {
    title: "SPI",
    lowLabel: "Dry / negative SPI",
    highLabel: "Wet / positive SPI",
    items: [
      { label: "Severe dry", color: "#B42318" },
      { label: "Moderate dry", color: "#F79009" },
      { label: "Near normal", color: "#12B76A" },
      { label: "Wet", color: "#1570EF" },
    ],
  },
  rainfall_anomaly_pct: {
    title: "Rainfall anomaly",
    lowLabel: "Below normal",
    highLabel: "Above normal",
    items: [
      { label: "Very dry", color: "#B42318" },
      { label: "Below normal", color: "#F79009" },
      { label: "Near normal", color: "#12B76A" },
      { label: "Above normal", color: "#1570EF" },
    ],
  },
  rainfall_percentile: {
    title: "Rainfall percentile",
    lowLabel: "Low percentile",
    highLabel: "High percentile",
    items: [
      { label: "Very low", color: "#B42318" },
      { label: "Low", color: "#F79009" },
      { label: "Normal", color: "#12B76A" },
      { label: "High", color: "#1570EF" },
    ],
  },
  cdd: {
    title: "Consecutive dry days",
    lowLabel: "Few dry days",
    highLabel: "Long dry spell",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#F79009" },
      { label: "Very high", color: "#B42318" },
    ],
  },
  cwd: {
    title: "Consecutive wet days",
    lowLabel: "Few wet days",
    highLabel: "Long wet spell",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#0E9384" },
      { label: "High", color: "#1570EF" },
      { label: "Very high", color: "#1849A9" },
    ],
  },
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

function getOptionLabel(options, value, fallback = "") {
  const match = options.find((item) => item.value === value);
  return match?.label || fallback || titleCase(value);
}

function getMapModeLabel(mapMode) {
  return MAP_MODES.find((item) => item.value === mapMode)?.label || "Hazard Map Layer";
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

function getIndicatorColor(value, indicator) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "#CBD5E1";
  }

  if (indicator === "spi") {
    if (numberValue <= -1.5) return "#B42318";
    if (numberValue <= -1.0) return "#F79009";
    if (numberValue < -0.5) return "#FEC84B";
    if (numberValue <= 0.5) return "#12B76A";
    if (numberValue <= 1.0) return "#0E9384";
    return "#1570EF";
  }

  if (indicator === "rainfall_anomaly_pct") {
    if (numberValue <= -30) return "#B42318";
    if (numberValue <= -15) return "#F79009";
    if (numberValue <= -5) return "#FEC84B";
    if (numberValue < 5) return "#12B76A";
    if (numberValue < 30) return "#0E9384";
    return "#1570EF";
  }

  if (indicator === "rainfall_percentile") {
    if (numberValue <= 10) return "#B42318";
    if (numberValue <= 25) return "#F79009";
    if (numberValue <= 40) return "#FEC84B";
    if (numberValue <= 60) return "#12B76A";
    if (numberValue <= 75) return "#0E9384";
    return "#1570EF";
  }

  if (indicator === "cdd") {
    if (numberValue >= 20) return "#B42318";
    if (numberValue >= 14) return "#F79009";
    if (numberValue >= 7) return "#FEC84B";
    return "#12B76A";
  }

  if (indicator === "cwd") {
    if (numberValue >= 10) return "#1849A9";
    if (numberValue >= 5) return "#1570EF";
    if (numberValue >= 3) return "#0E9384";
    return "#12B76A";
  }

  return getNumericColor(numberValue, "indicator");
}

function getFillColor(properties, mapMode, layer, indicator) {
  if (mapMode === "climate_indicator") {
    return getIndicatorColor(properties[indicator], indicator);
  }

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

function getIndicatorValue(properties, indicator) {
  if (indicator === "rainfall_anomaly_pct") {
    return `${formatValue(properties[indicator], 1)}%`;
  }

  if (indicator === "rainfall_percentile") {
    return `${formatValue(properties[indicator], 1)} percentile`;
  }

  if (indicator === "cdd" || indicator === "cwd") {
    return `${formatValue(properties[indicator], 0)} days`;
  }

  return formatValue(properties[indicator], 2);
}

function getDisplayedValue(properties, mapMode, layer, indicator) {
  if (mapMode === "climate_indicator") {
    return getIndicatorValue(properties, indicator);
  }

  return getLayerValue(properties, layer);
}

function collectLatLngsFromCoordinates(coordinates, output = []) {
  if (!Array.isArray(coordinates)) {
    return output;
  }

  if (
    coordinates.length >= 2 &&
    typeof coordinates[0] === "number" &&
    typeof coordinates[1] === "number"
  ) {
    output.push([coordinates[1], coordinates[0]]);
    return output;
  }

  coordinates.forEach((item) => collectLatLngsFromCoordinates(item, output));
  return output;
}

function getGeojsonBoundsObject(geojson) {
  if (!geojson || !Array.isArray(geojson.features)) {
    return null;
  }

  const latLngs = [];

  geojson.features.forEach((feature) => {
    collectLatLngsFromCoordinates(feature.geometry?.coordinates, latLngs);
  });

  if (latLngs.length === 0) {
    return null;
  }

  const lats = latLngs.map((item) => item[0]);
  const lons = latLngs.map((item) => item[1]);

  return {
    south: Math.min(...lats),
    north: Math.max(...lats),
    west: Math.min(...lons),
    east: Math.max(...lons),
    latLngs,
  };
}

function filterGridByBoundaryBoundingBox(geojson, boundaryGeojson) {
  if (!geojson || !boundaryGeojson) {
    return geojson;
  }

  const bounds = getGeojsonBoundsObject(boundaryGeojson);

  if (!bounds) {
    return geojson;
  }

  const filteredFeatures = (geojson.features || []).filter((feature) => {
    const props = feature.properties || {};
    const lat = Number(props.lat_center);
    const lon = Number(props.lon_center);

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return false;
    }

    return (
      lat >= bounds.south &&
      lat <= bounds.north &&
      lon >= bounds.west &&
      lon <= bounds.east
    );
  });

  return {
    ...geojson,
    metadata: {
      ...geojson.metadata,
      feature_count: filteredFeatures.length,
      filtered_by_admin_selection: true,
    },
    features: filteredFeatures,
  };
}

function FitForecastMapToEthiopiaDomain({ viewKey }) {
  const map = useMap();

  useEffect(() => {
    map.fitBounds(ETHIOPIA_BOUNDS, {
      padding: [8, 8],
      animate: true,
      duration: 0.4,
    });

    map.setMaxBounds(ETHIOPIA_MAX_BOUNDS);
  }, [map, viewKey]);

  return null;
}

function getBoundaryOverlayStyle(feature) {
  const level = feature.properties?.admin_level;

  if (level === "admin3") {
    return {
      color: "#111827",
      weight: 2.2,
      fillOpacity: 0,
    };
  }

  if (level === "admin2") {
    return {
      color: "#111827",
      weight: 1.9,
      fillOpacity: 0,
    };
  }

  return {
    color: "#111827",
    weight: 1.4,
    fillOpacity: 0,
  };
}

function IndicatorLegend({ indicator }) {
  const legend = INDICATOR_LEGENDS[indicator] || INDICATOR_LEGENDS.spi;

  return (
    <div className="forecast-indicator-legend">
      {legend.items.map((item) => (
        <span key={`${indicator}-${item.label}`}>
          <i style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
      <div className="forecast-gradient-labels forecast-indicator-range-labels">
        <span>{legend.lowLabel}</span>
        <span>{legend.highLabel}</span>
      </div>
    </div>
  );
}

function ForecastLayerMap({ adminSelection = {}, onForecastSelectionChange }) {
  const [mapMode, setMapMode] = useState("hazard_layer");
  const [forecastScale, setForecastScale] = useState("subseasonal");
  const [lead, setLead] = useState("week_1");
  const [layer, setLayer] = useState("hazard");
  const [indicator, setIndicator] = useState("spi");
  const [geojson, setGeojson] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const boundaryGeojson = adminSelection?.boundaryGeojson || null;

  const filteredLeadOptions = useMemo(() => {
    return OPTIONS.leads.filter((item) => item.forecast_scale === forecastScale);
  }, [forecastScale]);

  const displayedGeojson = useMemo(() => {
    return filterGridByBoundaryBoundingBox(geojson, boundaryGeojson);
  }, [geojson, boundaryGeojson]);

  const selectedLayerLabel = getOptionLabel(OPTIONS.layers, layer);
  const selectedLeadLabel = getOptionLabel(OPTIONS.leads, lead);
  const selectedIndicatorLabel = getOptionLabel(OPTIONS.indicators, indicator);
  const selectedMapModeLabel = getMapModeLabel(mapMode);
  const displayedMapLabel =
    mapMode === "climate_indicator" ? selectedIndicatorLabel : selectedLayerLabel;

  const selectedAdminLabel =
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia administrative areas";

  const viewKey = `${forecastScale}-${lead}-${mapMode}-${layer}-${indicator}-${adminSelection?.regionId || "all"}-${adminSelection?.zoneId || "all"}-${adminSelection?.woredaId || "all"}`;

  useEffect(() => {
    if (typeof onForecastSelectionChange === "function") {
      onForecastSelectionChange({
        forecastScale,
        lead,
        layer,
        indicator,
        mapMode,
        activeMapGroup: selectedMapModeLabel,
        activeMapLabel: displayedMapLabel,
        activeDisplayKey: mapMode === "climate_indicator" ? indicator : layer,
      });
    }
  }, [forecastScale, lead, layer, indicator, mapMode, selectedMapModeLabel, displayedMapLabel, onForecastSelectionChange]);

  useEffect(() => {
    const leadsForScale = OPTIONS.leads.filter(
      (item) => item.forecast_scale === forecastScale
    );

    if (
      leadsForScale.length > 0 &&
      !leadsForScale.some((item) => item.value === lead)
    ) {
      setLead(leadsForScale[0].value);
    }
  }, [forecastScale, lead]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadLayer() {
      setLoading(true);
      setErrorMessage("");

      try {
        const params = new URLSearchParams();
        params.set("forecast_scale", forecastScale);
        params.set("lead", lead);
        params.set("layer", layer);
        params.set("indicator", indicator);
        params.set("map_mode", mapMode);

        const response = await fetch(
          apiUrl(`/api/map-layers/ethiopia?${params.toString()}`),
          { signal: controller.signal }
        );

        if (!response.ok) {
          throw new Error(`Layer request failed: ${response.status}`);
        }

        const data = await response.json();
        setGeojson(data);
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
          setGeojson(null);
          setErrorMessage(
            "Could not load Ethiopia forecast map layer. Check the backend /api/map-layers/ethiopia endpoint."
          );
        }
      } finally {
        setLoading(false);
      }
    }

    loadLayer();

    return () => controller.abort();
  }, [forecastScale, lead, layer, indicator, mapMode]);

  function handleForecastScaleChange(event) {
    const nextScale = event.target.value;
    setForecastScale(nextScale);

    const firstLeadForScale = OPTIONS.leads.find(
      (item) => item.forecast_scale === nextScale
    );

    if (firstLeadForScale) {
      setLead(firstLeadForScale.value);
    }
  }

  function styleFeature(feature) {
    const properties = feature.properties || {};
    const fillColor = getFillColor(properties, mapMode, layer, indicator);

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
        <p><strong>Selected area:</strong> ${escapeHtml(selectedAdminLabel)}</p>
        <p><strong>Lead:</strong> ${escapeHtml(properties.lead_label || selectedLeadLabel)}</p>
        <p><strong>Map group:</strong> ${escapeHtml(selectedMapModeLabel)}</p>
        <p><strong>Displayed map:</strong> ${escapeHtml(displayedMapLabel)}</p>
        <p><strong>Displayed value:</strong> ${escapeHtml(getDisplayedValue(properties, mapMode, layer, indicator))}</p>
        <hr />
        <p><strong>Hazard:</strong> ${escapeHtml(titleCase(properties.hazard))}</p>
        <p><strong>Risk level:</strong> ${escapeHtml(titleCase(properties.risk_level))}</p>
        <p><strong>Risk score:</strong> ${escapeHtml(formatValue(properties.risk_score, 3))}</p>
        <p><strong>Hazard probability:</strong> ${escapeHtml(formatValue(properties.hazard_probability, 3))}</p>
        <p><strong>Exposure:</strong> ${escapeHtml(formatValue(properties.exposure, 3))}</p>
        <p><strong>Vulnerability:</strong> ${escapeHtml(formatValue(properties.vulnerability, 3))}</p>
        <hr />
        <p><strong>SPI:</strong> ${escapeHtml(formatValue(properties.spi, 2))}</p>
        <p><strong>Rainfall anomaly:</strong> ${escapeHtml(formatValue(properties.rainfall_anomaly_pct, 1))}%</p>
        <p><strong>Rainfall percentile:</strong> ${escapeHtml(formatValue(properties.rainfall_percentile, 1))}</p>
        <p><strong>CDD:</strong> ${escapeHtml(formatValue(properties.cdd, 0))} days</p>
        <p><strong>CWD:</strong> ${escapeHtml(formatValue(properties.cwd, 0))} days</p>
      </div>
    `;

    leafletLayer.bindPopup(popupHtml);
  }

  return (
    <section className="panel forecast-layer-section">
      <div className="forecast-layer-header">
        <div>
          <h2>Ethiopia Forecast Map Explorer</h2>
          <p>
            Switch between hazard/risk layers and climate indicator maps for Ethiopia.
            The selected tab controls what is displayed on the map and what is passed to the AI interpretation workflow.
          </p>
          <p className="map-selected-area">
            Selected area: <strong>{selectedAdminLabel}</strong>
          </p>
        </div>

        <div className="forecast-domain-badge">Lat 3–15°N · Lon 33–48°E</div>
      </div>

      <div className="map-mode-switcher" role="tablist" aria-label="Map type switcher">
        {MAP_MODES.map((mode) => {
          const isActive = mapMode === mode.value;
          return (
            <button
              key={mode.value}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`map-mode-tab${isActive ? " active" : ""}`}
              onClick={() => setMapMode(mode.value)}
            >
              <span>{mode.label}</span>
              <small>{mode.description}</small>
            </button>
          );
        })}
      </div>

      <div className="forecast-layer-controls forecast-layer-controls-with-tabs">
        <div className="forecast-control">
          <label htmlFor="forecast-scale">Forecast window</label>
          <select
            id="forecast-scale"
            value={forecastScale}
            onChange={handleForecastScaleChange}
          >
            {OPTIONS.forecast_scales.map((item) => (
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

        {mapMode === "hazard_layer" ? (
          <div className="forecast-control forecast-control-primary forecast-control-active-only">
            <label htmlFor="forecast-layer">Hazard map layer</label>
            <select
              id="forecast-layer"
              value={layer}
              onChange={(event) => setLayer(event.target.value)}
            >
              {OPTIONS.layers.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <small className="forecast-control-hint">
              Climate indicator selector is hidden because this tab displays hazard/risk layers.
            </small>
          </div>
        ) : (
          <div className="forecast-control forecast-control-primary forecast-control-active-only">
            <label htmlFor="forecast-indicator">Climate indicator map</label>
            <select
              id="forecast-indicator"
              value={indicator}
              onChange={(event) => setIndicator(event.target.value)}
            >
              {OPTIONS.indicators.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <small className="forecast-control-hint">
              Hazard layer selector is hidden because this tab displays climate indicator maps.
            </small>
          </div>
        )}
      </div>

      <div className="forecast-layer-summary">
        <div>
          <span>Active map group</span>
          <strong>{selectedMapModeLabel}</strong>
        </div>

        <div>
          <span>Displayed map</span>
          <strong>{displayedMapLabel}</strong>
        </div>

        <div>
          <span>Forecast horizon</span>
          <strong>{selectedLeadLabel}</strong>
        </div>

        <div>
          <span>Grid cells shown</span>
          <strong>{displayedGeojson?.metadata?.feature_count || 0}</strong>
        </div>
      </div>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <div className="forecast-map-layout">
        <div id="forecast-risk-map" className="forecast-map-wrapper forecast-map-wrapper-switcher">
          <MapContainer
            center={ETHIOPIA_CENTER}
            zoom={6.25}
            minZoom={5.75}
            maxZoom={9}
            zoomSnap={0.25}
            zoomDelta={0.25}
            maxBounds={ETHIOPIA_MAX_BOUNDS}
            maxBoundsViscosity={1.0}
            scrollWheelZoom={false}
            className="forecast-map"
          >
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            <FitForecastMapToEthiopiaDomain viewKey={viewKey} />

            {displayedGeojson && (
              <GeoJSON
                key={`forecast-grid-${viewKey}`}
                data={displayedGeojson}
                style={styleFeature}
                onEachFeature={onEachFeature}
              />
            )}

            {boundaryGeojson && (
              <GeoJSON
                key={`forecast-boundary-${viewKey}`}
                data={boundaryGeojson}
                style={getBoundaryOverlayStyle}
              />
            )}
          </MapContainer>

          {loading && (
            <div className="forecast-map-loading">Loading map layer...</div>
          )}
        </div>

        <div className="forecast-legend-card">
          <h3>Legend</h3>
          <p className="forecast-legend-mode">
            {selectedMapModeLabel}: <strong>{displayedMapLabel}</strong>
          </p>

          {mapMode === "hazard_layer" && layer === "hazard" ? (
            <div className="forecast-hazard-legend">
              <span>
                <i style={{ background: HAZARD_COLORS.drought }} />
                Drought
              </span>
              <span>
                <i style={{ background: HAZARD_COLORS.dry_spell }} />
                Dry spell
              </span>
              <span>
                <i style={{ background: HAZARD_COLORS.heavy_rainfall }} />
                Heavy rainfall
              </span>
              <span>
                <i style={{ background: HAZARD_COLORS.wet_spell }} />
                Wet spell
              </span>
              <span>
                <i style={{ background: HAZARD_COLORS.no_alert }} />
                No alert
              </span>
            </div>
          ) : mapMode === "hazard_layer" ? (
            <div className="forecast-gradient-legend">
              <div className="forecast-gradient-bar" />
              <div className="forecast-gradient-labels">
                <span>Low</span>
                <span>Moderate</span>
                <span>High</span>
              </div>
            </div>
          ) : (
            <IndicatorLegend indicator={indicator} />
          )}

          <p>
            The selected administrative boundary is used to filter the displayed
            forecast grid. The active tab determines whether users are viewing a
            hazard/risk layer or a climate indicator map.
          </p>
        </div>
      </div>
    </section>
  );
}

export default ForecastLayerMap;
