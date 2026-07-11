import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";

const FORECAST_SCALES = [
  { value: "subseasonal", label: "Subseasonal" },
  { value: "seasonal", label: "Seasonal" },
];

const FORECAST_LEADS = [
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
];

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

function TopInterventionAreas({ adminSelection = {} }) {
  const [forecastScale, setForecastScale] = useState("subseasonal");
  const [lead, setLead] = useState("week_1");
  const [rankingLayer, setRankingLayer] = useState("risk_score");
  const [adminLevel, setAdminLevel] = useState("admin1");
  const [selectionMode, setSelectionMode] = useState("top");
  const [topN, setTopN] = useState(5);
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLDS.risk_score);
  const [rankingData, setRankingData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const availableLeads = useMemo(() => {
    return FORECAST_LEADS.filter(
      (item) => item.forecast_scale === forecastScale,
    );
  }, [forecastScale]);

  const selectedAreaLabel =
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia";

  const rankingItems = rankingData?.ranking || [];

  useEffect(() => {
    const firstLead = FORECAST_LEADS.find(
      (item) => item.forecast_scale === forecastScale,
    );

    if (firstLead && !availableLeads.some((item) => item.value === lead)) {
      setLead(firstLead.value);
    }
  }, [forecastScale, lead, availableLeads]);

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

  function handleForecastScaleChange(event) {
    const nextScale = event.target.value;
    setForecastScale(nextScale);

    const firstLead = FORECAST_LEADS.find(
      (item) => item.forecast_scale === nextScale,
    );

    if (firstLead) {
      setLead(firstLead.value);
    }
  }

  function handleRankingLayerChange(event) {
    const nextLayer = event.target.value;
    setRankingLayer(nextLayer);
    setThreshold(DEFAULT_THRESHOLDS[nextLayer] || 0.6);
  }

  return (
    <section className="panel intervention-panel">
      <div className="section-heading intervention-heading">
        <div>
          <h2>Priority Intervention Areas</h2>
          <p>
            Rank administrative areas that need early action based on forecast
            risk score, hazard probability, exposure, or vulnerability.
          </p>
          <p className="map-selected-area">
            Current selection: <strong>{selectedAreaLabel}</strong>
          </p>
        </div>

        {loading && (
          <span className="admin-loading-badge">Updating ranking...</span>
        )}
      </div>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <div className="intervention-controls">
        <div className="forecast-control">
          <label htmlFor="intervention-scale">Forecast scale</label>
          <select
            id="intervention-scale"
            value={forecastScale}
            onChange={handleForecastScaleChange}
          >
            {FORECAST_SCALES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="intervention-lead">Lead / horizon</label>
          <select
            id="intervention-lead"
            value={lead}
            onChange={(event) => setLead(event.target.value)}
          >
            {availableLeads.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

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
          <span>Forecast horizon</span>
          <strong>{getOptionLabel(FORECAST_LEADS, lead)}</strong>
        </div>

        <div>
          <span>Admin level</span>
          <strong>{getOptionLabel(ADMIN_LEVELS, adminLevel)}</strong>
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
              <th>Intervention guidance</th>
            </tr>
          </thead>
          <tbody>
            {rankingItems.map((item) => (
              <tr key={`${item.admin_level}-${item.area_name}-${item.rank}`}>
                <td>
                  <span className="rank-badge">{item.rank}</span>
                </td>
                <td>
                  <strong>{item.area_name}</strong>
                  <br />
                  <small>{titleCase(item.admin_level)}</small>
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
                <td>{item.recommended_action}</td>
              </tr>
            ))}

            {rankingItems.length === 0 && (
              <tr>
                <td colSpan="9">
                  No areas matched the selected ranking configuration.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="intervention-method-note">
        Method: priority score combines mean value, maximum value, and the share
        of grid cells above threshold. Use Risk Score for primary intervention
        ranking; use Hazard Probability, Exposure, and Vulnerability as
        diagnostic layers.
      </p>
    </section>
  );
}

export default TopInterventionAreas;
