import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
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

function getOptionLabel(options, value, fallback = "") {
  const match = options.find((item) => item.value === value);
  return match?.label || fallback || titleCase(value);
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

  const filteredFeatures = geojson.features.filter((feature) => {
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

function FitForecastMapToSelection({ boundaryGeojson }) {
  const map = useMap();

  useEffect(() => {
    const boundsObject = getGeojsonBoundsObject(boundaryGeojson);

    if (boundsObject && boundsObject.latLngs.length > 0) {
      map.fitBounds(boundsObject.latLngs, {
        padding: [28, 28],
        maxZoom: 8,
      });
      return;
    }

    map.fitBounds(ETHIOPIA_BOUNDS, {
      padding: [20, 20],
    });
  }, [map, boundaryGeojson]);

  return null;
}

function getBoundaryOverlayStyle(feature) {
  const level = feature.properties?.admin_level;

  if (level === "admin3") {
    return {
      color: "#111827",
      weight: 2,
      fillOpacity: 0,
    };
  }

  if (level === "admin2") {
    return {
      color: "#111827",
      weight: 1.8,
      fillOpacity: 0,
    };
  }

  return {
    color: "#111827",
    weight: 1.4,
    fillOpacity: 0,
  };
}

function ForecastLayerMap({ adminSelection = {} }) {
  const [options, setOptions] = useState(DEFAULT_OPTIONS);
  const [forecastScale, setForecastScale] = useState("subseasonal");
  const [lead, setLead] = useState("week_1");
  const [layer, setLayer] = useState("hazard");
  const [indicator, setIndicator] = useState("spi");
  const [geojson, setGeojson] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const boundaryGeojson = adminSelection?.boundaryGeojson || null;

  const filteredLeadOptions = useMemo(() => {
    return options.leads.filter(
      (item) => item.forecast_scale === forecastScale,
    );
  }, [options.leads, forecastScale]);

  const displayedGeojson = useMemo(() => {
    return filterGridByBoundaryBoundingBox(geojson, boundaryGeojson);
  }, [geojson, boundaryGeojson]);

  const selectedLayerLabel = getOptionLabel(options.layers, layer);
  const selectedLeadLabel = getOptionLabel(options.leads, lead);
  const selectedIndicatorLabel = getOptionLabel(options.indicators, indicator);

  const selectedAdminLabel =
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia administrative areas";

  useEffect(() => {
    async function loadOptions() {
      try {
        const response = await fetch(apiUrl("/api/map-layers/options"));

        if (!response.ok) {
          throw new Error(`Options request failed: ${response.status}`);
        }

        const data = await response.json();

        setOptions({
          forecast_scales:
            data.forecast_scales || DEFAULT_OPTIONS.forecast_scales,
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
      (item) => item.forecast_scale === forecastScale,
    );

    if (
      leadsForScale.length > 0 &&
      !leadsForScale.some((item) => item.value === lead)
    ) {
      setLead(leadsForScale[0].value);
    }
  }, [forecastScale, lead, options.leads]);

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

        const response = await fetch(
          apiUrl(`/api/map-layers/ethiopia?${params.toString()}`),
          { signal: controller.signal },
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
          setErrorMessage("Could not load Ethiopia forecast map layer.");
        }
      } finally {
        setLoading(false);
      }
    }

    loadLayer();

    return () => controller.abort();
  }, [forecastScale, lead, layer, indicator]);

  function handleForecastScaleChange(event) {
    const nextScale = event.target.value;
    setForecastScale(nextScale);

    const firstLeadForScale = options.leads.find(
      (item) => item.forecast_scale === nextScale,
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
        <p><strong>Selected area:</strong> ${escapeHtml(selectedAdminLabel)}</p>
        <p><strong>Lead:</strong> ${escapeHtml(properties.lead_label)}</p>
        <p><strong>Map layer:</strong> ${escapeHtml(selectedLayerLabel)}</p>
        <p><strong>Layer value:</strong> ${escapeHtml(getLayerValue(properties, layer))}</p>
        <p><strong>Hazard:</strong> ${escapeHtml(titleCase(properties.hazard))}</p>
        <p><strong>Risk level:</strong> ${escapeHtml(titleCase(properties.risk_level))}</p>
        <p><strong>${escapeHtml(selectedIndicatorLabel)}:</strong> ${escapeHtml(
          getIndicatorValue(properties, indicator),
        )}</p>
        <hr />
        <p><strong>SPI:</strong> ${escapeHtml(formatValue(properties.spi, 2))}</p>
        <p><strong>Rainfall anomaly:</strong> ${escapeHtml(
          formatValue(properties.rainfall_anomaly_pct, 1),
        )}%</p>
        <p><strong>Rainfall percentile:</strong> ${escapeHtml(
          formatValue(properties.rainfall_percentile, 1),
        )}</p>
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
          <h2>Ethiopia Forecast Risk Layers</h2>
          <p>
            Prototype gridded subseasonal and seasonal forecast layers for
            Ethiopia. This map uses the same shared Region, Zone and Woreda
            selection as the administrative risk map.
          </p>
          <p className="map-selected-area">
            Selected area: <strong>{selectedAdminLabel}</strong>
          </p>
        </div>

        <div className="forecast-domain-badge">Lat 3–15°N · Lon 33–48°E</div>
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
          <strong>{selectedIndicatorLabel}</strong>
        </div>

        <div>
          <span>Grid cells shown</span>
          <strong>{displayedGeojson?.metadata?.feature_count || 0}</strong>
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
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            <FitForecastMapToSelection boundaryGeojson={boundaryGeojson} />

            {displayedGeojson && (
              <GeoJSON
                key={`forecast-grid-${forecastScale}-${lead}-${layer}-${indicator}-${
                  adminSelection?.regionId || "all"
                }-${adminSelection?.zoneId || "all"}-${
                  adminSelection?.woredaId || "all"
                }`}
                data={displayedGeojson}
                style={styleFeature}
                onEachFeature={onEachFeature}
              />
            )}

            {boundaryGeojson && (
              <GeoJSON
                key={`forecast-boundary-${adminSelection?.regionId || "all"}-${
                  adminSelection?.zoneId || "all"
                }-${adminSelection?.woredaId || "all"}`}
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

          {layer === "hazard" ? (
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
            The selected administrative boundary is used to spatially filter the
            forecast grid using the boundary extent. This is a fast MVP
            approach. A production version should use exact polygon clipping or
            vector tiles.
          </p>
        </div>
      </div>
    </section>
  );
}

export default ForecastLayerMap;
