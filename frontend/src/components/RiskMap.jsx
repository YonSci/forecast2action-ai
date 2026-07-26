import { useEffect } from "react";
import {
  GeoJSON,
  LayersControl,
  MapContainer,
  TileLayer,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { BASEMAP_OPTIONS } from "../constants/basemaps.js";

const ETHIOPIA_CENTER = [9, 40.5];

const ETHIOPIA_BOUNDS = [
  [3, 33],
  [15, 48],
];

const ETHIOPIA_MAX_BOUNDS = [
  [1.5, 31.5],
  [16.5, 49.5],
];

const RISK_STYLE = {
  trigger: { color: "#D92D20", label: "Trigger" },
  warning: { color: "#C11574", label: "Warning" },
  watch: { color: "#F79009", label: "Watch" },
  no_alert: { color: "#12B76A", label: "No alert" },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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

function getGeojsonLatLngs(geojson) {
  if (!geojson || !Array.isArray(geojson.features)) {
    return [];
  }

  const latLngs = [];

  geojson.features.forEach((feature) => {
    collectLatLngsFromCoordinates(feature.geometry?.coordinates, latLngs);
  });

  return latLngs;
}

function FitMapToEthiopiaDomain({ activeBoundaryKey }) {
  const map = useMap();

  useEffect(() => {
    map.fitBounds(ETHIOPIA_BOUNDS, {
      padding: [8, 8],
      animate: true,
      duration: 0.4,
    });

    map.setMaxBounds(ETHIOPIA_MAX_BOUNDS);
  }, [map, activeBoundaryKey]);

  return null;
}

function getBoundaryStyle(feature) {
  const level = feature.properties?.admin_level;

  if (level === "admin3") {
    return {
      color: "#7A5AF8",
      weight: 3.5,
      fillColor: "#7A5AF8",
      fillOpacity: 0.22,
    };
  }

  if (level === "admin2") {
    return {
      color: "#111827",
      weight: 2.8,
      fillColor: "#1570EF",
      fillOpacity: 0.12,
    };
  }

  return {
    color: "#111827",
    weight: 2.2,
    fillColor: "#1849A9",
    fillOpacity: 0.08,
  };
}

function onEachBoundaryFeature(feature, layer) {
  const props = feature.properties || {};

  const labelParts = [];

  if (props.region) {
    labelParts.push(
      `<p><strong>Region:</strong> ${escapeHtml(props.region)}</p>`,
    );
  }

  if (props.zone) {
    labelParts.push(`<p><strong>Zone:</strong> ${escapeHtml(props.zone)}</p>`);
  }

  if (props.woreda) {
    labelParts.push(
      `<p><strong>Woreda:</strong> ${escapeHtml(props.woreda)}</p>`,
    );
  }

  layer.bindPopup(`
    <div class="admin-boundary-popup">
      <h3>${escapeHtml(props.name || "Administrative boundary")}</h3>
      ${labelParts.join("")}
    </div>
  `);
}

function RiskMap({ adminSelection = {}, selectedPriorityArea = null }) {
  const hasPrioritySelection = Boolean(selectedPriorityArea?.area_name);
  const hasPriorityBoundary = Boolean(selectedPriorityArea?.boundaryGeojson);

  const activeBoundaryGeojson = hasPriorityBoundary
    ? selectedPriorityArea.boundaryGeojson
    : adminSelection?.boundaryGeojson || null;

  const activeBoundaryKey = hasPriorityBoundary
    ? `priority-${selectedPriorityArea.selected_at}-${selectedPriorityArea.area_name}-${selectedPriorityArea.boundary_feature_count}`
    : `shared-${adminSelection?.boundaryLevel}-${adminSelection?.regionId}-${adminSelection?.zoneId}-${adminSelection?.woredaId}`;

  const selectedAdminLabel =
    selectedPriorityArea?.area_name ||
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia administrative areas";

  const selectedAreaSource = hasPrioritySelection
    ? "Priority Intervention Areas"
    : "Administrative Area Selection";

  const boundaryFeatureCount = hasPriorityBoundary
    ? selectedPriorityArea?.boundary_feature_count
    : activeBoundaryGeojson?.metadata?.feature_count || 0;

  const selectedBoundaryPointCount = getGeojsonLatLngs(
    activeBoundaryGeojson,
  ).length;

  return (
    <section className="panel map-panel" id="interactive-risk-map">
      <div className="map-header">
        <div>
          <h2>Priority Intervention Area Layers</h2>
        </div>

        <div className="map-legend" aria-label="Risk legend">
          {Object.entries(RISK_STYLE).map(([key, item]) => (
            <span key={key}>
              <i
                className="legend-dot"
                style={{ backgroundColor: item.color }}
              />
              {item.label}
            </span>
          ))}
        </div>
      </div>
      {hasPrioritySelection && !hasPriorityBoundary && (
        <div className="error-banner">
          The selected priority area was received, but no boundary geometry was
          attached. Restart the backend after updating the ranking endpoint.
        </div>
      )}

      {activeBoundaryGeojson && selectedBoundaryPointCount === 0 && (
        <div className="error-banner">
          Boundary geometry was received, but it does not contain valid map
          coordinates.
        </div>
      )}

      <div className="map-wrapper">
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
          className="risk-map"
        >
          <LayersControl position="topright">
            {BASEMAP_OPTIONS.map((basemap, index) => (
              <LayersControl.BaseLayer
                key={basemap.value}
                name={basemap.label}
                checked={index === 0}
              >
                <TileLayer
                  attribution={basemap.attribution}
                  url={basemap.url}
                  maxZoom={basemap.maxZoom}
                />
              </LayersControl.BaseLayer>
            ))}
          </LayersControl>

          <FitMapToEthiopiaDomain activeBoundaryKey={activeBoundaryKey} />

          {activeBoundaryGeojson && (
            <GeoJSON
              key={activeBoundaryKey}
              data={activeBoundaryGeojson}
              style={getBoundaryStyle}
              onEachFeature={onEachBoundaryFeature}
            />
          )}
        </MapContainer>
      </div>
    </section>
  );
}

export default RiskMap;
