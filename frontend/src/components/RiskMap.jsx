import { useEffect, useMemo } from "react";
import {
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
  trigger: {
    color: "#D92D20",
    label: "Trigger",
    radius: 18,
  },
  warning: {
    color: "#C11574",
    label: "Warning",
    radius: 15,
  },
  watch: {
    color: "#F79009",
    label: "Watch",
    radius: 12,
  },
  no_alert: {
    color: "#12B76A",
    label: "No alert",
    radius: 10,
  },
};

function safeNumber(value, fallback = null) {
  const numberValue = Number(value);

  if (Number.isFinite(numberValue)) {
    return numberValue;
  }

  return fallback;
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

  const latitude = safeNumber(item.latitude, fallback.latitude);
  const longitude = safeNumber(item.longitude, fallback.longitude);

  return {
    ...item,
    latitude,
    longitude,
  };
}

function FitMapToRiskData({ riskData }) {
  const map = useMap();

  useEffect(() => {
    if (!riskData || riskData.length === 0) {
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
  }, [map, riskData]);

  return null;
}

function RiskMap({ riskData = [], selectedDistrict = "", onSelectDistrict }) {
  const validRiskData = useMemo(() => {
    return riskData.map(normalizeRiskItem).filter((item) => {
      return Number.isFinite(item.latitude) && Number.isFinite(item.longitude);
    });
  }, [riskData]);

  const selectedItem = validRiskData.find(
    (item) => item.district === selectedDistrict,
  );

  const mapCenter = selectedItem
    ? [selectedItem.latitude, selectedItem.longitude]
    : [5.5, 38.5];

  function handleSelectDistrict(district) {
    if (typeof onSelectDistrict === "function") {
      onSelectDistrict(district);
    }
  }

  return (
    <section className="panel map-panel">
      <div className="map-header">
        <div>
          <h2>Interactive Risk Map</h2>
          <p>
            District-level overview of impact-based early warning levels across
            the pilot areas.
          </p>
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

      {validRiskData.length === 0 ? (
        <div className="map-empty-state">
          <h3>No mappable risk data available</h3>
          <p>
            The backend did not return valid latitude and longitude values for
            the selected districts.
          </p>
        </div>
      ) : (
        <div className="map-wrapper">
          <MapContainer
            center={mapCenter}
            zoom={5}
            minZoom={4}
            maxZoom={11}
            scrollWheelZoom={false}
            className="risk-map"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            <FitMapToRiskData riskData={validRiskData} />

            {validRiskData.map((item) => {
              const riskStyle = getRiskStyle(item.risk_level);
              const isSelected = item.district === selectedDistrict;
              const radius = isSelected
                ? riskStyle.radius + 5
                : riskStyle.radius;

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
      )}
    </section>
  );
}

export default RiskMap;
