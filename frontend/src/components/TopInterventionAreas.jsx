import { useEffect, useState } from "react";
import { apiUrl } from "../config.js";

const RANKING_LAYERS = [
  { value: "risk_score", label: "Risk Score" },
  { value: "hazard_probability", label: "Hazard Probability" },
  { value: "exposure", label: "Exposure" },
  { value: "vulnerability", label: "Vulnerability" },
];

const ADMIN_LEVELS = [
  { value: "admin1", label: "Regions" },
  { value: "admin2", label: "Zones" },
  { value: "admin3", label: "Woredas" },
];

const TOP_OPTIONS = [
  { value: 3, label: "Top 3" },
  { value: 5, label: "Top 5" },
  { value: 10, label: "Top 10" },
];

const DEFAULT_THRESHOLDS = {
  risk_score: 0.6,
  hazard_probability: 0.6,
  exposure: 0.7,
  vulnerability: 0.7,
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

function formatNumber(value, digits = 3) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "N/A";
  }

  return numberValue.toFixed(digits);
}

function getPriorityClass(priorityLevel) {
  if (priorityLevel === "trigger" || priorityLevel === "high") {
    return "priority-high";
  }

  if (priorityLevel === "warning" || priorityLevel === "moderate") {
    return "priority-medium";
  }

  if (priorityLevel === "watch") {
    return "priority-watch";
  }

  return "priority-low";
}

function getOptionLabel(options, value) {
  const match = options.find((item) => item.value === value);
  return match?.label || titleCase(value);
}

function isRankingLayer(value) {
  return RANKING_LAYERS.some((item) => item.value === value);
}

function isSamePriorityArea(a, b) {
  if (!a || !b) {
    return false;
  }

  return (
    a.admin_level === b.admin_level &&
    a.region_id === b.region_id &&
    a.zone_id === b.zone_id &&
    a.woreda_id === b.woreda_id &&
    a.area_name === b.area_name
  );
}

function getReadableAdminLevel(adminLevel) {
  if (adminLevel === "admin1") return "Region";
  if (adminLevel === "admin2") return "Zone";
  if (adminLevel === "admin3") return "Woreda";

  return titleCase(adminLevel);
}

function buildBoundaryGeojsonFromItem(item, selectedArea) {
  if (!item?.boundary_feature) {
    return null;
  }

  return {
    type: "FeatureCollection",
    metadata: {
      source: "priority_intervention_area",
      level: selectedArea.admin_level,
      area_name: selectedArea.area_name,
      region_id: selectedArea.region_id,
      zone_id: selectedArea.zone_id,
      woreda_id: selectedArea.woreda_id,
      feature_count: 1,
    },
    features: [item.boundary_feature],
  };
}

function TopInterventionAreas({
  adminSelection = {},
  forecastSelection = {},
  selectedPriorityArea = null,
  onPriorityAreaSelect,
}) {
  const forecastScale = forecastSelection.forecastScale || "subseasonal";
  const lead = forecastSelection.lead || "week_1";
  const selectedMapLayer = forecastSelection.layer || "risk_score";

  const [rankingLayer, setRankingLayer] = useState(
    isRankingLayer(selectedMapLayer) ? selectedMapLayer : "risk_score",
  );
  const [adminLevel, setAdminLevel] = useState("admin3");
  const [selectionMode, setSelectionMode] = useState("top");
  const [topN, setTopN] = useState(5);
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLDS.risk_score);
  const [rankingData, setRankingData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const selectedAreaLabel =
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia";

  const rankingItems = rankingData?.ranking || [];

  useEffect(() => {
    if (isRankingLayer(selectedMapLayer)) {
      setRankingLayer(selectedMapLayer);
      setThreshold(DEFAULT_THRESHOLDS[selectedMapLayer] || 0.6);
    }
  }, [selectedMapLayer]);

  useEffect(() => {
    setThreshold(DEFAULT_THRESHOLDS[rankingLayer] || 0.6);
  }, [rankingLayer]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadRanking() {
      setLoading(true);
      setErrorMessage("");

      try {
        const params = new URLSearchParams();

        params.set("forecast_scale", forecastScale);
        params.set("lead", lead);
        params.set("layer", rankingLayer);
        params.set("admin_level", adminLevel);
        params.set("selection_mode", selectionMode);
        params.set("top_n", String(topN));
        params.set("threshold", String(threshold));

        if (adminSelection?.regionId) {
          params.set("region_id", adminSelection.regionId);
        }

        if (adminSelection?.zoneId) {
          params.set("zone_id", adminSelection.zoneId);
        }

        const response = await fetch(
          apiUrl(`/api/intervention-ranking?${params.toString()}`),
          { signal: controller.signal },
        );

        if (!response.ok) {
          throw new Error(`Ranking request failed: ${response.status}`);
        }

        const data = await response.json();
        setRankingData(data);
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
          setRankingData(null);
          setErrorMessage("Could not load priority intervention ranking.");
        }
      } finally {
        setLoading(false);
      }
    }

    loadRanking();

    return () => controller.abort();
  }, [
    forecastScale,
    lead,
    rankingLayer,
    adminLevel,
    selectionMode,
    topN,
    threshold,
    adminSelection?.regionId,
    adminSelection?.zoneId,
  ]);

  function handleRankingLayerChange(event) {
    const nextLayer = event.target.value;

    setRankingLayer(nextLayer);
    setThreshold(DEFAULT_THRESHOLDS[nextLayer] || 0.6);
  }

  function handlePriorityAreaSelect(item) {
    const selectedArea = {
      ...item,
      selected_at: Date.now(),
      admin_level: item.admin_level || adminLevel,
      region_id: item.region_id || "",
      zone_id: item.zone_id || "",
      woreda_id: item.woreda_id || "",
      region: item.region || "",
      zone: item.zone || "",
      woreda: item.woreda || "",
      area_name:
        item.area_name ||
        item.woreda ||
        item.zone ||
        item.region ||
        "Selected area",
    };

    const boundaryGeojson = buildBoundaryGeojsonFromItem(item, selectedArea);

    const selectedAreaWithBoundary = {
      ...selectedArea,
      boundaryGeojson,
      boundary_feature_count: boundaryGeojson?.features?.length || 0,
      boundary_source: boundaryGeojson
        ? "ranking_item_embedded_geometry"
        : "missing_embedded_geometry",
    };

    console.log("Priority area selected for map:", selectedAreaWithBoundary);

    if (typeof onPriorityAreaSelect === "function") {
      onPriorityAreaSelect(selectedAreaWithBoundary);
    }

    setTimeout(() => {
      document.getElementById("interactive-risk-map")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 150);
  }

  return (
    <section className="panel intervention-panel">
      <div className="section-heading intervention-heading">
        <div>
          <h2>Priority Intervention Areas</h2>
          <p>
            Rank administrative areas needing early action. This section uses
            the forecast scale and lead selected in the Ethiopia Forecast Risk
            Layers map.
          </p>
          <p className="map-selected-area">
            Current administrative selection:{" "}
            <strong>{selectedAreaLabel}</strong>
          </p>
        </div>

        {loading && (
          <span className="admin-loading-badge">Updating ranking...</span>
        )}
      </div>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <div className="intervention-controls intervention-controls-compact">
        <div className="forecast-control">
          <label htmlFor="intervention-layer">Rank by</label>
          <select
            id="intervention-layer"
            value={rankingLayer}
            onChange={handleRankingLayerChange}
          >
            {RANKING_LAYERS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="intervention-admin-level">Administrative level</label>
          <select
            id="intervention-admin-level"
            value={adminLevel}
            onChange={(event) => setAdminLevel(event.target.value)}
          >
            {ADMIN_LEVELS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="intervention-mode">Display mode</label>
          <select
            id="intervention-mode"
            value={selectionMode}
            onChange={(event) => setSelectionMode(event.target.value)}
          >
            <option value="top">Top areas</option>
            <option value="threshold">Threshold-based</option>
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="intervention-top-n">Show</label>
          <select
            id="intervention-top-n"
            value={topN}
            onChange={(event) => setTopN(Number(event.target.value))}
            disabled={selectionMode === "threshold"}
          >
            {TOP_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="intervention-threshold">Threshold</label>
          <input
            id="intervention-threshold"
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={threshold}
            onChange={(event) => setThreshold(Number(event.target.value))}
          />
        </div>
      </div>

      <div className="intervention-summary-grid">
        <div>
          <span>Ranking layer</span>
          <strong>{getOptionLabel(RANKING_LAYERS, rankingLayer)}</strong>
        </div>

        <div>
          <span>Administrative level</span>
          <strong>{getOptionLabel(ADMIN_LEVELS, adminLevel)}</strong>
        </div>

        <div>
          <span>Display mode</span>
          <strong>
            {selectionMode === "top" ? `Top ${topN}` : "Threshold"}
          </strong>
        </div>

        <div>
          <span>Areas returned</span>
          <strong>{rankingItems.length}</strong>
        </div>
      </div>

      <div className="table-scroll">
        <table className="intervention-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Area</th>
              <th>Region</th>
              <th>Zone</th>
              <th>Mean</th>
              <th>Max</th>
              <th>Cells above threshold</th>
              <th>Priority score</th>
              <th>Map selection</th>
              <th>Intervention guidance</th>
            </tr>
          </thead>

          <tbody>
            {rankingItems.map((item) => {
              const isSelected = isSamePriorityArea(item, selectedPriorityArea);

              return (
                <tr
                  key={`${item.admin_level}-${item.region_id}-${item.zone_id}-${item.woreda_id}-${item.area_name}-${item.rank}`}
                  className={isSelected ? "selected-row" : ""}
                >
                  <td>
                    <span className="rank-badge">{item.rank}</span>
                  </td>

                  <td>
                    <strong>{item.area_name}</strong>
                    <br />
                    <small>{getReadableAdminLevel(item.admin_level)}</small>
                  </td>

                  <td>{item.region || "N/A"}</td>
                  <td>{item.zone || "N/A"}</td>
                  <td>{formatNumber(item.mean_value)}</td>
                  <td>{formatNumber(item.max_value)}</td>

                  <td>
                    {item.cells_above_threshold_pct}%{" "}
                    <small>
                      ({item.cells_above_threshold}/{item.cells_count})
                    </small>
                  </td>

                  <td>
                    <span
                      className={`priority-score-pill ${getPriorityClass(
                        item.priority_level,
                      )}`}
                    >
                      {formatNumber(item.priority_score)}
                    </span>
                  </td>

                  <td>
                    <button
                      type="button"
                      className="table-link-button"
                      onClick={() => handlePriorityAreaSelect(item)}
                    >
                      {isSelected ? "Selected" : "View on map"}
                    </button>
                  </td>

                  <td>{item.recommended_action}</td>
                </tr>
              );
            })}

            {rankingItems.length === 0 && (
              <tr>
                <td colSpan="10">
                  No areas matched the selected ranking configuration.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="intervention-method-note">
        Method: priority score combines mean value, maximum value, and the share
        of grid cells above threshold. Click “View on map” to update the
        Interactive Administrative Risk Map.
      </p>
    </section>
  );
}

export default TopInterventionAreas;
