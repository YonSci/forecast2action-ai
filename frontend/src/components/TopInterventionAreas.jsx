import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";
import { getPriorityLevel } from "../constants/priorityLevels.js";

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

const CATEGORY_OPTIONS = [
  { value: "hazard", label: "Hazard" },
  { value: "probability", label: "Probability" },
  { value: "exposure", label: "Exposure" },
  { value: "vulnerability", label: "Vulnerability" },
  { value: "risk", label: "Risk" },
];

// Which layer each category starts on, and what stays remembered per
// category as the user switches "Rank by" back and forth. Risk defaults to
// the drought score (not Risk Class) so the initial hazard-type sync below
// has something concrete to lock onto.
const DEFAULT_SELECTED_BY_CATEGORY = {
  hazard: "h_dry_mean",
  probability: "p_drought",
  exposure: "population_normalized",
  vulnerability: "v_drought",
  risk: "population_r_drought",
};

const RISK_CLASS_LABELS = ["Very low", "Low", "Moderate", "High", "Very high"];

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

function formatMetricValue(value, layerMeta) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "N/A";
  }

  if (!layerMeta) {
    return numberValue.toFixed(2);
  }

  if (layerMeta.units === "score") {
    return `${numberValue.toFixed(1)} / 100`;
  }

  if (layerMeta.units === "probability") {
    return `${(numberValue * 100).toFixed(1)}%`;
  }

  if (layerMeta.is_categorical) {
    const index = Math.max(
      0,
      Math.min(RISK_CLASS_LABELS.length - 1, Math.round(numberValue)),
    );
    return `${RISK_CLASS_LABELS[index]} (avg ${numberValue.toFixed(2)})`;
  }

  return numberValue.toFixed(2);
}


function getOptionLabel(options, value) {
  const match = options.find((item) => item.value === value);
  return match?.label || titleCase(value);
}

// A single shared "hazard type" (drought/wet) applies across Hazard,
// Probability, Vulnerability, and Risk (when Risk isn't on the
// hazard-type-agnostic Risk Class option) -- picking any drought- or
// wet-flavored metric in one category re-points all the others at their
// matching drought/wet layer too, instead of leaving them on whatever they
// were previously set to.
function applyHazardTypeSync(current, hazardType) {
  const next = { ...current };
  next.hazard = hazardType === "drought" ? "h_dry_mean" : "h_wet_mean";
  next.probability = hazardType === "drought" ? "p_drought" : "p_wet";
  next.vulnerability = hazardType === "drought" ? "v_drought" : "v_wet";
  if (next.risk !== "population_risk_class") {
    next.risk =
      hazardType === "drought" ? "population_r_drought" : "population_r_wet";
  }
  return next;
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
  if (adminLevel === "admin1") {
    return "Region";
  }

  if (adminLevel === "admin2") {
    return "Zone";
  }

  if (adminLevel === "admin3") {
    return "Woreda";
  }

  return titleCase(adminLevel);
}

function SortableColumnHeader({ column, label, sortColumn, sortDirection, onSort }) {
  const isActive = sortColumn === column;

  return (
    <th aria-sort={isActive ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        className="sortable-column-header"
        onClick={() => onSort(column)}
      >
        {label}
        <span className="sort-indicator">
          {isActive ? (sortDirection === "asc" ? " ▲" : " ▼") : ""}
        </span>
      </button>
    </th>
  );
}

function buildBoundaryGeojsonFromItem(item, selectedArea) {
  if (!item?.boundary_feature) {
    return null;
  }

  // Carrying metrics_display/priority_* onto the feature's own properties
  // (not just the top-level selectedArea object) means RiskMap.jsx's popup
  // can show every ranked metric for the clicked area directly off the
  // GeoJSON feature, with no separate lookup or knowledge of layer labels
  // /formatting required on its side.
  const enrichedFeature = {
    ...item.boundary_feature,
    properties: {
      ...item.boundary_feature.properties,
      rank: item.rank,
      metrics_display: selectedArea.metrics_display,
      priority_level: selectedArea.priority_level,
      priority_label: selectedArea.priority_label,
      priority_score: selectedArea.priority_score,
    },
  };

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
    features: [enrichedFeature],
  };
}

function TopInterventionAreas({
  adminSelection = {},
  forecastSelection = {},
  selectedPriorityArea = null,
  onPriorityAreaSelect,
  onRankingContextChange,
}) {
  const period = forecastSelection.seasonalPeriod || "JJAS";

  const [rankingLayers, setRankingLayers] = useState([]);
  const [category, setCategory] = useState("risk");
  const [selectedByCategory, setSelectedByCategory] = useState(
    DEFAULT_SELECTED_BY_CATEGORY,
  );
  const [adminLevel, setAdminLevel] = useState("admin3");
  const [selectionMode, setSelectionMode] = useState("top");
  const [topN, setTopN] = useState(5);
  const [threshold, setThreshold] = useState(null);
  const [rankingData, setRankingData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  // Client-side secondary sort on top of the backend's rank_by ordering --
  // null means "no override, show the backend's own order". Each item's own
  // `rank` (its position under the actual rank_by metric) is left untouched
  // when sorting by a different column; only the row order changes.
  const [sortColumn, setSortColumn] = useState(null);
  const [sortDirection, setSortDirection] = useState("desc");

  const rankingItems = rankingData?.ranking || [];

  const layerMetaByValue = useMemo(() => {
    return Object.fromEntries(rankingLayers.map((item) => [item.value, item]));
  }, [rankingLayers]);

  const metricsForCategory = useMemo(() => {
    return rankingLayers.filter((item) => item.category === category);
  }, [rankingLayers, category]);

  const rankBy = selectedByCategory[category];

  // Load the real Hazard/Risk raster catalog's ranking-eligible layers once
  // (this is the single source of truth for the category/metric vocabulary
  // -- see the earlier "dryspell" display-text drift bug for why this isn't
  // hardcoded a second time here).
  useEffect(() => {
    const controller = new AbortController();

    async function loadRankingOptions() {
      try {
        const response = await fetch(
          apiUrl("/api/hazard-risk/ranking-options"),
          { signal: controller.signal },
        );

        if (!response.ok) {
          throw new Error(`Ranking options request failed: ${response.status}`);
        }

        const data = await response.json();
        setRankingLayers(
          Array.isArray(data.ranking_layers) ? data.ranking_layers : [],
        );
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
        }
      }
    }

    loadRankingOptions();

    return () => controller.abort();
  }, []);

  // Reset the threshold to the newly-selected rank-by layer's own default
  // whenever it changes -- each layer has a different natural scale (0-1
  // index/probability/normalized vs. 0-100 score vs. 0-4 class).
  useEffect(() => {
    const meta = layerMetaByValue[rankBy];
    if (meta) {
      setThreshold(meta.default_threshold);
    }
  }, [rankBy, layerMetaByValue]);

  useEffect(() => {
    if (threshold === null || !rankingLayers.length) {
      return undefined;
    }

    const controller = new AbortController();

    async function loadRanking() {
      setLoading(true);
      setErrorMessage("");

      try {
        const metricsList = Array.from(
          new Set(Object.values(selectedByCategory)),
        );

        const params = new URLSearchParams();
        params.set("rank_by", rankBy);
        params.set("metrics", metricsList.join(","));
        params.set("period", period);
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
          apiUrl(`/api/hazard-risk/ranking?${params.toString()}`),
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
          setErrorMessage(
            "Could not load priority intervention ranking. Check the backend /api/hazard-risk/ranking endpoint.",
          );
        }
      } finally {
        setLoading(false);
      }
    }

    loadRanking();

    return () => controller.abort();
  }, [
    rankBy,
    selectedByCategory,
    period,
    adminLevel,
    selectionMode,
    topN,
    threshold,
    rankingLayers.length,
    adminSelection?.regionId,
    adminSelection?.zoneId,
  ]);

  function handleCategoryChange(event) {
    setCategory(event.target.value);
  }

  function handleMetricChange(event) {
    const nextValue = event.target.value;
    const meta = layerMetaByValue[nextValue];

    setSelectedByCategory((previous) => {
      const updated = { ...previous, [category]: nextValue };
      if (meta?.hazard_type === "drought" || meta?.hazard_type === "wet") {
        return applyHazardTypeSync(updated, meta.hazard_type);
      }
      return updated;
    });
  }

  function handleSortClick(column) {
    if (sortColumn === column) {
      setSortDirection((previous) => (previous === "desc" ? "asc" : "desc"));
    } else {
      setSortColumn(column);
      setSortDirection("desc");
    }
  }

  function handlePriorityAreaSelect(item) {
    const priorityInfo = getPriorityLevel(item.priority_score);

    // All five category columns' current values for this specific area, with
    // their real labels/formatting already resolved -- so RiskMap.jsx's popup
    // can show everything about the clicked area without needing its own
    // copy of layer metadata or formatting logic.
    const metricsDisplay = [
      {
        label: hazardLayerMeta?.label || "Hazard",
        value: formatMetricValue(
          item.metrics[selectedByCategory.hazard],
          hazardLayerMeta,
        ),
      },
      {
        label: probabilityLayerMeta?.label || "Probability",
        value: formatMetricValue(
          item.metrics[selectedByCategory.probability],
          probabilityLayerMeta,
        ),
      },
      {
        label: exposureLayerMeta?.label || "Exposure",
        value: formatMetricValue(
          item.metrics[selectedByCategory.exposure],
          exposureLayerMeta,
        ),
      },
      {
        label: vulnerabilityLayerMeta?.label || "Vulnerability",
        value: formatMetricValue(
          item.metrics[selectedByCategory.vulnerability],
          vulnerabilityLayerMeta,
        ),
      },
      {
        label: riskLayerMeta?.label || "Risk",
        value: formatMetricValue(
          item.metrics[selectedByCategory.risk],
          riskLayerMeta,
        ),
      },
    ];

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
      selected_map_layer: rankBy,
      selected_period: period,
      metrics_display: metricsDisplay,
      priority_level: priorityInfo.level,
      priority_label: priorityInfo.label,
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

  const hazardLayerMeta = layerMetaByValue[selectedByCategory.hazard];
  const probabilityLayerMeta = layerMetaByValue[selectedByCategory.probability];
  const exposureLayerMeta = layerMetaByValue[selectedByCategory.exposure];
  const vulnerabilityLayerMeta =
    layerMetaByValue[selectedByCategory.vulnerability];
  const riskLayerMeta = layerMetaByValue[selectedByCategory.risk];

  // Reports the currently-active layer for each category up to Dashboard.jsx
  // (which passes it to RiskMap.jsx) so its "Key terms" glossary panel can
  // describe the same drought/wet-flavored metrics this table is showing,
  // instead of needing its own separate copy of this selection state.
  useEffect(() => {
    if (typeof onRankingContextChange === "function") {
      onRankingContextChange({
        hazardLayerMeta,
        probabilityLayerMeta,
        exposureLayerMeta,
        vulnerabilityLayerMeta,
        riskLayerMeta,
      });
    }
  }, [
    onRankingContextChange,
    hazardLayerMeta,
    probabilityLayerMeta,
    exposureLayerMeta,
    vulnerabilityLayerMeta,
    riskLayerMeta,
  ]);

  const sortColumnGetters = {
    hazard: (item) => item.metrics[selectedByCategory.hazard],
    probability: (item) => item.metrics[selectedByCategory.probability],
    exposure: (item) => item.metrics[selectedByCategory.exposure],
    vulnerability: (item) => item.metrics[selectedByCategory.vulnerability],
    risk: (item) => item.metrics[selectedByCategory.risk],
    priority_score: (item) => item.priority_score,
  };

  const sortedItems = useMemo(() => {
    if (!sortColumn) {
      return rankingItems;
    }

    const getValue = sortColumnGetters[sortColumn];
    if (!getValue) {
      return rankingItems;
    }

    return [...rankingItems].sort((a, b) => {
      const aValue = Number(getValue(a));
      const bValue = Number(getValue(b));
      const aValid = Number.isFinite(aValue);
      const bValid = Number.isFinite(bValue);

      if (!aValid && !bValid) {
        return 0;
      }
      // Rows missing this column's value sort to the bottom regardless of
      // direction, rather than jumping to the top on ascending sort.
      if (!aValid) {
        return 1;
      }
      if (!bValid) {
        return -1;
      }

      return sortDirection === "asc" ? aValue - bValue : bValue - aValue;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rankingItems, sortColumn, sortDirection, selectedByCategory]);

  return (
    <section className="panel intervention-panel">
      <div className="section-heading intervention-heading">
        <div>
          <h2>Priority Intervention Areas</h2>
        </div>

        {loading && (
          <span className="admin-loading-badge">Updating ranking...</span>
        )}
      </div>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <div className="intervention-controls intervention-controls-compact">
        <div className="forecast-control">
          <label htmlFor="intervention-category">Rank by</label>
          <select
            id="intervention-category"
            value={category}
            onChange={handleCategoryChange}
          >
            {CATEGORY_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="forecast-control">
          <label htmlFor="intervention-metric">Metric</label>
          <select
            id="intervention-metric"
            value={rankBy}
            onChange={handleMetricChange}
          >
            {metricsForCategory.map((item) => (
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
            value={threshold ?? ""}
            onChange={(event) => setThreshold(Number(event.target.value))}
          />
        </div>
      </div>

      <div className="intervention-summary-grid">
        <div>
          <span>Ranking layer</span>
          <strong>{riskLayerMeta?.label && rankBy === selectedByCategory.risk ? riskLayerMeta.label : getOptionLabel(metricsForCategory, rankBy)}</strong>
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
        <table className="intervention-table intervention-action-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Location</th>
              <SortableColumnHeader
                column="hazard"
                label={hazardLayerMeta?.label || "Hazard"}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="probability"
                label={probabilityLayerMeta?.label || "Probability"}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="exposure"
                label={exposureLayerMeta?.label || "Exposure"}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="vulnerability"
                label={vulnerabilityLayerMeta?.label || "Vulnerability"}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="risk"
                label={riskLayerMeta?.label || "Risk"}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="priority_score"
                label="Priority score"
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <th>Map</th>
            </tr>
          </thead>

          <tbody>
            {sortedItems.map((item) => {
              const isSelected = isSamePriorityArea(item, selectedPriorityArea);
              const priorityInfo = getPriorityLevel(item.priority_score);

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
                    <small>
                      {getReadableAdminLevel(item.admin_level)}
                      {item.region ? ` · ${item.region}` : ""}
                      {item.zone ? ` · ${item.zone}` : ""}
                    </small>
                  </td>

                  <td>
                    {formatMetricValue(
                      item.metrics[selectedByCategory.hazard],
                      hazardLayerMeta,
                    )}
                  </td>
                  <td>
                    {formatMetricValue(
                      item.metrics[selectedByCategory.probability],
                      probabilityLayerMeta,
                    )}
                  </td>
                  <td>
                    {formatMetricValue(
                      item.metrics[selectedByCategory.exposure],
                      exposureLayerMeta,
                    )}
                  </td>
                  <td>
                    {formatMetricValue(
                      item.metrics[selectedByCategory.vulnerability],
                      vulnerabilityLayerMeta,
                    )}
                  </td>
                  <td>
                    {formatMetricValue(
                      item.metrics[selectedByCategory.risk],
                      riskLayerMeta,
                    )}
                  </td>

                  <td>
                    <span
                      className={`priority-score-pill ${priorityInfo.className}`}
                    >
                      {priorityInfo.label} ({Number(item.priority_score).toFixed(2)})
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
                </tr>
              );
            })}

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
    </section>
  );
}

export default TopInterventionAreas;
