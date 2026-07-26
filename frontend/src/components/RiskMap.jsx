import { useEffect, useState } from "react";
import {
  GeoJSON,
  LayersControl,
  MapContainer,
  TileLayer,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiUrl } from "../config.js";
import { BASEMAP_OPTIONS } from "../constants/basemaps.js";
import { PRIORITY_LEVELS } from "../constants/priorityLevels.js";

const ETHIOPIA_CENTER = [9, 40.5];

const ETHIOPIA_BOUNDS = [
  [3, 33],
  [15, 48],
];

const ETHIOPIA_MAX_BOUNDS = [
  [1.5, 31.5],
  [16.5, 49.5],
];

const PRIORITY_COLOR_BY_LEVEL = Object.fromEntries(
  PRIORITY_LEVELS.map((item) => [item.level, item.color]),
);

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

// Subtle, non-interactive reference outline so a district near the border
// (e.g. Gambela, which genuinely borders South Sudan) doesn't look like it
// might be misplaced -- without this, RiskMap drew only the selected
// district with no visual cue for where Ethiopia's real border actually is,
// unlike the Hazard/Risk raster maps which are always clipped to the
// country border (see clip_array_to_country) and so never have this
// ambiguity.
function getCountryOutlineStyle() {
  return {
    color: "#0F172A",
    weight: 1.5,
    fillOpacity: 0,
    dashArray: "5 4",
  };
}

function getBoundaryStyle(feature) {
  const props = feature.properties || {};
  const priorityColor = PRIORITY_COLOR_BY_LEVEL[props.priority_level];

  // A priority-ranked area (has a priority_level from the Priority
  // Intervention Areas table) is colored by its Trigger/Warning/Watch/No
  // alert classification instead of the generic admin-level coloring, so
  // the map visually agrees with that table's own classification.
  if (priorityColor) {
    return {
      color: priorityColor,
      weight: 3.2,
      fillColor: priorityColor,
      fillOpacity: 0.28,
    };
  }

  const level = props.admin_level;

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

  // Enriched by TopInterventionAreas.jsx's buildBoundaryGeojsonFromItem when
  // this boundary came from a ranked priority area -- every column's current
  // value for this specific area, already labeled/formatted, so nothing
  // here needs its own copy of layer metadata.
  if (Array.isArray(props.metrics_display) && props.metrics_display.length) {
    if (props.priority_label) {
      labelParts.push(
        `<p><strong>Priority:</strong> ${escapeHtml(props.priority_label)}` +
          (Number.isFinite(props.priority_score)
            ? ` (${Number(props.priority_score).toFixed(2)})`
            : "") +
          `</p>`,
      );
    }

    if (props.rank) {
      labelParts.push(`<p><strong>Rank:</strong> ${escapeHtml(props.rank)}</p>`);
    }

    props.metrics_display.forEach((item) => {
      labelParts.push(
        `<p><strong>${escapeHtml(item.label)}:</strong> ${escapeHtml(item.value)}</p>`,
      );
    });
  }

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
  const [countryBoundary, setCountryBoundary] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    fetch(apiUrl("/api/admin-boundaries/geojson?level=admin0"), {
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) {
          setCountryBoundary(data);
        }
      })
      .catch(() => {});

    return () => controller.abort();
  }, []);

  const hasPrioritySelection = Boolean(selectedPriorityArea?.area_name);
  const hasPriorityBoundary = Boolean(selectedPriorityArea?.boundaryGeojson);

  const activeBoundaryGeojson = hasPriorityBoundary
    ? selectedPriorityArea.boundaryGeojson
    : adminSelection?.boundaryGeojson || null;

  const activeBoundaryKey = hasPriorityBoundary
    ? `priority-${selectedPriorityArea.selected_at}-${selectedPriorityArea.area_name}-${selectedPriorityArea.boundary_feature_count}`
    : `shared-${adminSelection?.boundaryLevel}-${adminSelection?.regionId}-${adminSelection?.zoneId}-${adminSelection?.woredaId}`;

  const selectedBoundaryPointCount = getGeojsonLatLngs(
    activeBoundaryGeojson,
  ).length;

  return (
    <section className="panel map-panel" id="interactive-risk-map">
      <div className="map-header">
        <div>
          <h2>Priority Intervention Area Layers</h2>
        </div>

        <div className="map-legend" aria-label="Priority legend">
          {PRIORITY_LEVELS.map((item) => (
            <span key={item.level}>
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
          preferCanvas
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

          {countryBoundary && (
            <GeoJSON
              key="ethiopia-country-outline"
              data={countryBoundary}
              style={getCountryOutlineStyle}
              interactive={false}
            />
          )}

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
