import { useEffect, useMemo } from "react";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  Tooltip,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

const FALLBACK_COORDINATES = {
  Borena: { latitude: 4.95, longitude: 38.15 },
  "Afar Zone 1": { latitude: 12.15, longitude: 40.75 },
  Turkana: { latitude: 3.12, longitude: 35.6 },
  Garissa: { latitude: -0.45, longitude: 39.65 },
};

const RISK_STYLE = {
  trigger: { color: "#D92D20", label: "Trigger", radius: 18 },
  warning: { color: "#C11574", label: "Warning", radius: 15 },
  watch: { color: "#F79009", label: "Watch", radius: 12 },
  no_alert: { color: "#12B76A", label: "No alert", radius: 10 },
};

function safeNumber(value, fallback = null) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : fallback;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatText(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

  return String(value)
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (text) => {
      return text.charAt(0).toUpperCase() + text.substring(1).toLowerCase();
    });
}

function formatNumber(value, digits = 2) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "N/A";
  }

  return numberValue.toFixed(digits);
}

function getRiskStyle(riskLevel) {
  return RISK_STYLE[riskLevel] || RISK_STYLE.no_alert;
}

function normalizeRiskItem(item) {
  const fallback = FALLBACK_COORDINATES[item.district] || {};

  return {
    ...item,
    latitude: safeNumber(item.latitude, fallback.latitude),
    longitude: safeNumber(item.longitude, fallback.longitude),
  };
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

function getGeojsonBoundsObject(geojson) {
  const latLngs = getGeojsonLatLngs(geojson);

  if (latLngs.length === 0) {
    return null;
  }

  return { latLngs };
}

function filterRiskDataByBoundaryBoundingBox(riskData, boundaryGeojson) {
  if (!boundaryGeojson) {
    return riskData;
  }

  const latLngs = getGeojsonLatLngs(boundaryGeojson);

  if (latLngs.length === 0) {
    return riskData;
  }

  const lats = latLngs.map((item) => item[0]);
  const lons = latLngs.map((item) => item[1]);

  const south = Math.min(...lats);
  const north = Math.max(...lats);
  const west = Math.min(...lons);
  const east = Math.max(...lons);

  return riskData.filter((item) => {
    const lat = Number(item.latitude);
    const lon = Number(item.longitude);

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return false;
    }

    return lat >= south && lat <= north && lon >= west && lon <= east;
  });
}

function FitMapToBoundary({ boundaryGeojson, activeBoundaryKey }) {
  const map = useMap();

  useEffect(() => {
    const boundsObject = getGeojsonBoundsObject(boundaryGeojson);

    if (!boundsObject || boundsObject.latLngs.length === 0) {
      return;
    }

    map.fitBounds(boundsObject.latLngs, {
      padding: [35, 35],
      maxZoom: 10,
    });
  }, [map, boundaryGeojson, activeBoundaryKey]);

  return null;
}

function FitMapToRiskData({ riskData, enabled }) {
  const map = useMap();

  useEffect(() => {
    if (!enabled || !riskData || riskData.length === 0) {
      return;
    }

    const bounds = riskData.map((item) => [item.latitude, item.longitude]);

    if (bounds.length === 1) {
      map.setView(bounds[0], 7);
      return;
    }

    map.fitBounds(bounds, {
      padding: [45, 45],
      maxZoom: 7,
    });
  }, [map, riskData, enabled]);

  return null;
}

function getBoundaryStyle(feature) {
  const level = feature.properties?.admin_level;

  if (level === "admin3") {
    return {
      color: "#7A5AF8",
      weight: 3.2,
      fillColor: "#7A5AF8",
      fillOpacity: 0.18,
    };
  }

  if (level === "admin2") {
    return {
      color: "#1570EF",
      weight: 2.6,
      fillColor: "#1570EF",
      fillOpacity: 0.11,
    };
  }

  return {
    color: "#1849A9",
    weight: 1.8,
    fillColor: "#1849A9",
    fillOpacity: 0.06,
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

function RiskMap({
  riskData = [],
  selectedDistrict = "",
  adminSelection = {},
  selectedPriorityArea = null,
  onSelectDistrict,
}) {
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

  const selectedAreaSource = hasPriorityBoundary
    ? "Priority Intervention Areas"
    : "Administrative Area Selection";

  const boundaryFeatureCount = hasPriorityBoundary
    ? selectedPriorityArea?.boundary_feature_count
    : activeBoundaryGeojson?.metadata?.feature_count || 0;

  const validRiskData = useMemo(() => {
    return riskData.map(normalizeRiskItem).filter((item) => {
      return Number.isFinite(item.latitude) && Number.isFinite(item.longitude);
    });
  }, [riskData]);

  const displayedRiskData = useMemo(() => {
    return filterRiskDataByBoundaryBoundingBox(
      validRiskData,
      activeBoundaryGeojson,
    );
  }, [validRiskData, activeBoundaryGeojson]);

  const selectedItem = validRiskData.find(
    (item) => item.district === selectedDistrict,
  );

  const mapCenter = selectedItem
    ? [selectedItem.latitude, selectedItem.longitude]
    : [8.5, 39.5];

  function handleSelectDistrict(district) {
    if (typeof onSelectDistrict === "function") {
      onSelectDistrict(district);
    }
  }

  return (
    <section className="panel map-panel" id="interactive-risk-map">
      <div className="map-header">
        <div>
          <h2>Interactive Administrative Risk Map</h2>

          <p>
            This map updates from the selected row in Priority Intervention
            Areas.
          </p>

          <p className="map-selected-area">
            Active area: <strong>{selectedAdminLabel}</strong>
          </p>

          <p className="map-selected-area">
            Selection source: <strong>{selectedAreaSource}</strong>
          </p>

          {hasPrioritySelection && (
            <p className="map-selected-area">
              Boundary features loaded: <strong>{boundaryFeatureCount}</strong>
            </p>
          )}
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

      <p className="map-admin-note">
        Clicking “View on map” in Priority Intervention Areas sends the selected
        boundary directly to this map.
      </p>

      {hasPrioritySelection && !hasPriorityBoundary && (
        <div className="error-banner">
          The selected priority area was received, but no boundary geometry was
          attached. Restart the backend after updating the ranking endpoint.
        </div>
      )}

      <div className="map-wrapper">
        <MapContainer
          center={mapCenter}
          zoom={6}
          minZoom={4}
          maxZoom={11}
          scrollWheelZoom={false}
          className="risk-map"
        >
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {activeBoundaryGeojson && (
            <>
              <GeoJSON
                key={activeBoundaryKey}
                data={activeBoundaryGeojson}
                style={getBoundaryStyle}
                onEachFeature={onEachBoundaryFeature}
              />

              <FitMapToBoundary
                boundaryGeojson={activeBoundaryGeojson}
                activeBoundaryKey={activeBoundaryKey}
              />
            </>
          )}

          {!activeBoundaryGeojson && (
            <FitMapToRiskData riskData={displayedRiskData} enabled={true} />
          )}

          {displayedRiskData.map((item) => {
            const riskStyle = getRiskStyle(item.risk_level);
            const isSelected = item.district === selectedDistrict;
            const radius = isSelected ? riskStyle.radius + 5 : riskStyle.radius;

            return (
              <CircleMarker
                key={`${item.country}-${item.district}`}
                center={[item.latitude, item.longitude]}
                radius={radius}
                pathOptions={{
                  color: riskStyle.color,
                  fillColor: riskStyle.color,
                  fillOpacity: isSelected ? 0.88 : 0.68,
                  weight: isSelected ? 4 : 2,
                }}
                eventHandlers={{
                  click: () => handleSelectDistrict(item.district),
                }}
              >
                <Tooltip
                  direction="top"
                  offset={[0, -8]}
                  opacity={1}
                  className="risk-tooltip"
                >
                  <strong>{item.district}</strong>
                  <br />
                  {riskStyle.label} · {formatText(item.hazard)}
                </Tooltip>

                <Popup className="risk-popup">
                  <div className="map-popup">
                    <div className="map-popup-header">
                      <h3>{item.district}</h3>
                      <span className={`risk-pill risk-${item.risk_level}`}>
                        {riskStyle.label}
                      </span>
                    </div>

                    <p className="map-popup-country">{item.country}</p>

                    <div className="map-popup-grid">
                      <div>
                        <span>Hazard</span>
                        <strong>{formatText(item.hazard)}</strong>
                      </div>

                      <div>
                        <span>Risk score</span>
                        <strong>{formatNumber(item.risk_score, 3)}</strong>
                      </div>

                      <div>
                        <span>Rainfall anomaly</span>
                        <strong>
                          {formatNumber(item.rainfall_anomaly_pct, 1)}%
                        </strong>
                      </div>

                      <div>
                        <span>SPI-like score</span>
                        <strong>{formatNumber(item.spi, 2)}</strong>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleSelectDistrict(item.district)}
                    >
                      View advisory
                    </button>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
    </section>
  );
}

export default RiskMap;
