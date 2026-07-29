import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  GeoJSON,
  LayersControl,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiUrl } from "../config.js";
import { BASEMAP_OPTIONS } from "../constants/basemaps.js";
import { PRIORITY_LEVELS, getPriorityLevel } from "../constants/priorityLevels.js";
import {
  AREA_EXTENT_DEFINITION,
  CROPLAND_EXTENT_DEFINITION,
  EXPOSURE_TERM_DEFINITION,
  POPULATION_EXPOSED_DEFINITION,
  PRIORITY_SCORE_DEFINITION,
  getTermDefinition,
} from "../constants/hazardRiskGlossary.js";
import "../styles/mapSwitcher.css";

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

// Bounding-box center of a ranked area's own boundary geometry (already
// embedded per-item as item.boundary_feature by the ranking API) -- used to
// place a point marker for that area. A bounding-box center is a simpler,
// more visually stable choice than a raw vertex average for the irregular
// (sometimes concave) admin boundaries this app renders.
function getBoundaryFeatureCenter(boundaryFeature) {
  if (!boundaryFeature) {
    return null;
  }

  const latLngs = collectLatLngsFromCoordinates(boundaryFeature.geometry?.coordinates);
  if (!latLngs.length) {
    return null;
  }

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLng = Infinity;
  let maxLng = -Infinity;

  latLngs.forEach(([lat, lng]) => {
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
  });

  return [(minLat + maxLat) / 2, (minLng + maxLng) / 2];
}

function getRankedAreaName(item) {
  return item.area_name || item.woreda || item.zone || item.region || "Selected area";
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

function RiskMap({
  adminSelection = {},
  selectedPriorityArea = null,
  rankingContext = null,
}) {
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

  // Brief definitions for whichever drought/wet-flavored metrics the
  // Priority Intervention Areas table is currently ranking by, so this map's
  // "Key terms" panel always describes the same terms that table is
  // showing (Drought Hazard vs. Wetness Hazard, etc.) instead of a fixed,
  // possibly-stale set.
  const glossaryEntries = useMemo(() => {
    if (!rankingContext) {
      return [];
    }

    const {
      hazardLayerMeta,
      probabilityLayerMeta,
      exposureLayerMeta,
      vulnerabilityLayerMeta,
      riskLayerMeta,
    } = rankingContext;

    return [
      hazardLayerMeta && {
        label: hazardLayerMeta.label,
        definition: getTermDefinition(hazardLayerMeta.value),
      },
      probabilityLayerMeta && {
        label: probabilityLayerMeta.label,
        definition: getTermDefinition(probabilityLayerMeta.value),
      },
      exposureLayerMeta && {
        label: `Exposure: ${exposureLayerMeta.label}`,
        definition: EXPOSURE_TERM_DEFINITION,
      },
      vulnerabilityLayerMeta && {
        label: vulnerabilityLayerMeta.label,
        definition: getTermDefinition(vulnerabilityLayerMeta.value),
      },
      riskLayerMeta && {
        label: riskLayerMeta.label,
        definition: getTermDefinition(riskLayerMeta.value),
      },
      { label: "Priority score", definition: PRIORITY_SCORE_DEFINITION },
      { label: "Population exposed", definition: POPULATION_EXPOSED_DEFINITION },
      { label: "Area extent", definition: AREA_EXTENT_DEFINITION },
      { label: "Cropland extent", definition: CROPLAND_EXTENT_DEFINITION },
    ].filter(Boolean);
  }, [rankingContext]);

  // One point per ranked area from the Priority Intervention Areas table
  // (already sized by that table's own Top 3/5/10 selector) -- clicking a
  // point calls the SAME selection handler the table's "View on map" button
  // uses, so it activates SelectedAreaAdvisory identically.
  const rankedAreaMarkers = useMemo(() => {
    const items = Array.isArray(rankingContext?.rankingItems)
      ? rankingContext.rankingItems
      : [];

    return items
      .map((item) => ({
        item,
        center: getBoundaryFeatureCenter(item.boundary_feature),
      }))
      .filter((entry) => Boolean(entry.center));
  }, [rankingContext]);

  return (
    <section className="panel map-panel" id="interactive-risk-map">
      <div className="map-header">
        <div>
          <h2>Priority Intervention Area Layers</h2>
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

      <div className="seasonal-single-map-layout">
        <div className="seasonal-raster-map-frame">
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
            className="seasonal-raster-map"
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

            {rankedAreaMarkers.map(({ item, center }) => {
              const priorityInfo = getPriorityLevel(item.priority_score);
              const isActive =
                hasPrioritySelection &&
                getRankedAreaName(item) === selectedPriorityArea.area_name;
              const color = PRIORITY_COLOR_BY_LEVEL[priorityInfo.level] || "#1849A9";

              return (
                <CircleMarker
                  key={`${item.admin_level}-${item.region_id}-${item.zone_id}-${item.woreda_id}-${item.area_name}-${item.rank}`}
                  center={center}
                  radius={isActive ? 13 : 9}
                  pathOptions={{
                    color: "#111827",
                    weight: isActive ? 3 : 1.5,
                    fillColor: color,
                    fillOpacity: isActive ? 0.95 : 0.85,
                  }}
                  eventHandlers={{
                    click: () => rankingContext?.selectArea?.(item),
                  }}
                >
                  <Tooltip direction="top" offset={[0, -6]} opacity={1}>
                    <strong>#{item.rank}</strong> {getRankedAreaName(item)}
                    <br />
                    {priorityInfo.label} ({Number(item.priority_score).toFixed(2)})
                  </Tooltip>
                </CircleMarker>
              );
            })}
          </MapContainer>
        </div>

        <aside className="forecast-legend-card">
          {rankedAreaMarkers.length > 0 && (
            <p className="risk-map-marker-hint">
              Points show the {rankedAreaMarkers.length} ranked areas from the
              Priority Intervention Areas table. Click a point to open its
              Forecast-to-Action Advisory.
            </p>
          )}
          {glossaryEntries.length > 0 ? (
            <div className="risk-map-glossary">
              {glossaryEntries.map((entry) => (
                <div key={entry.label} className="risk-map-glossary-item">
                  <strong>{entry.label}</strong>
                  <p>{entry.definition}</p>
                </div>
              ))}
            </div>
          ) : (
            <p>
              Select a ranking metric in Priority Intervention Areas to see
              its definition here.
            </p>
          )}
        </aside>
      </div>
    </section>
  );
}

export default RiskMap;
