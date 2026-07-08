import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  Tooltip,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

const fallbackCoordinates = {
  Borena: { latitude: 4.95, longitude: 38.15 },
  "Afar Zone 1": { latitude: 12.15, longitude: 40.75 },
  Turkana: { latitude: 3.12, longitude: 35.6 },
  Garissa: { latitude: -0.45, longitude: 39.65 },
};

function getRiskColor(riskLevel) {
  if (riskLevel === "trigger") {
    return "#b42318";
  }

  if (riskLevel === "warning") {
    return "#c01048";
  }

  if (riskLevel === "watch") {
    return "#b54708";
  }

  return "#027a48";
}

function getRiskRadius(riskLevel) {
  if (riskLevel === "trigger") {
    return 18;
  }

  if (riskLevel === "warning") {
    return 15;
  }

  if (riskLevel === "watch") {
    return 12;
  }

  return 9;
}

function formatText(value) {
  if (!value) {
    return "";
  }

  return String(value).replaceAll("_", " ");
}

function RiskMap({ riskData, selectedDistrict, onSelectDistrict }) {
  const mapCenter = [5.5, 38.5];

  const validRiskData = riskData
    .map((item) => {
      const fallback = fallbackCoordinates[item.district] || {};

      return {
        ...item,
        latitude: Number(item.latitude ?? fallback.latitude),
        longitude: Number(item.longitude ?? fallback.longitude),
      };
    })
    .filter(
      (item) => !Number.isNaN(item.latitude) && !Number.isNaN(item.longitude),
    );

  return (
    <section className="panel map-panel">
      <div className="map-header">
        <div>
          <h2>Risk Map</h2>
          <p>
            Spatial overview of impact-based early warning levels across the
            pilot areas.
          </p>
        </div>

        <div className="map-legend">
          <span>
            <i className="legend-dot legend-trigger"></i> Trigger
          </span>
          <span>
            <i className="legend-dot legend-warning"></i> Warning
          </span>
          <span>
            <i className="legend-dot legend-watch"></i> Watch
          </span>
          <span>
            <i className="legend-dot legend-no-alert"></i> No alert
          </span>
        </div>
      </div>

      <div className="map-wrapper">
        <MapContainer
          center={mapCenter}
          zoom={5}
          scrollWheelZoom={false}
          className="risk-map"
        >
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {validRiskData.map((item) => {
            const color = getRiskColor(item.risk_level);
            const isSelected = item.district === selectedDistrict;

            return (
              <CircleMarker
                key={item.district}
                center={[item.latitude, item.longitude]}
                radius={
                  isSelected
                    ? getRiskRadius(item.risk_level) + 5
                    : getRiskRadius(item.risk_level)
                }
                pathOptions={{
                  color,
                  fillColor: color,
                  fillOpacity: isSelected ? 0.88 : 0.65,
                  weight: isSelected ? 4 : 2,
                }}
                eventHandlers={{
                  click: () => onSelectDistrict(item.district),
                }}
              >
                <Tooltip direction="top" offset={[0, -6]} opacity={1}>
                  <strong>{item.district}</strong>
                  <br />
                  {formatText(item.risk_level)} · {formatText(item.hazard)}
                </Tooltip>

                <Popup>
                  <div className="map-popup">
                    <h3>{item.district}</h3>
                    <p>{item.country}</p>

                    <p>
                      <strong>Hazard:</strong> {formatText(item.hazard)}
                    </p>

                    <p>
                      <strong>Risk level:</strong> {formatText(item.risk_level)}
                    </p>

                    <p>
                      <strong>Risk score:</strong> {item.risk_score}
                    </p>

                    <button
                      type="button"
                      onClick={() => onSelectDistrict(item.district)}
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
