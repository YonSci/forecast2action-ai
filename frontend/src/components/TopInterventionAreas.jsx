import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";
import { getCurrentSeasonalPeriod } from "../constants/climateIndicators.js";
import { combineDroughtWetLevel, getLevelInfo } from "../constants/priorityLevels.js";
import {
  formatAreaExtent,
  formatBuiltUpExtentPct,
  formatCroplandExtentPct,
  formatLivestockExtentPct,
  formatMetricValue,
  formatPopulationExposed,
  formatRoadsExtentPct,
} from "../constants/rankingMetricFormatters.js";

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

// Hazard/Probability/Vulnerability are deliberately NOT offered here as
// their own "Rank by" categories -- applyHazardTypeSync (below) always
// keeps all four in lockstep with whichever drought/wet metric is active,
// so their columns are shown regardless of which one you'd rank by; the
// only thing choosing among them would change is sort order/threshold,
// and Risk (their real composite, and what drives the Trigger/Warning/
// Watch badges) is the operationally meaningful one to rank by instead.
const CATEGORY_OPTIONS = [
  { value: "risk", label: "Risk" },
  { value: "exposure", label: "Exposure" },
];

// Which layer each category starts on, and what stays remembered per
// category as the user switches "Rank by" back and forth.
const DEFAULT_SELECTED_BY_CATEGORY = {
  hazard: "h_dry_mean",
  probability: "p_drought",
  exposure: "population_normalized",
  vulnerability: "v_drought",
  risk: "population_r_drought",
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

function getOptionLabel(options, value) {
  const match = options.find((item) => item.value === value);
  return match?.label || titleCase(value);
}

// A single shared "hazard type" (drought/wet) applies across Hazard,
// Probability, Vulnerability, and Risk -- picking any drought- or
// wet-flavored metric in one category re-points all the others at their
// matching drought/wet layer too, instead of leaving them on whatever they
// were previously set to.
function applyHazardTypeSync(current, hazardType) {
  const next = { ...current };
  next.hazard = hazardType === "drought" ? "h_dry_mean" : "h_wet_mean";
  next.probability = hazardType === "drought" ? "p_drought" : "p_wet";
  next.vulnerability = hazardType === "drought" ? "v_drought" : "v_wet";
  next.risk = hazardType === "drought" ? "population_r_drought" : "population_r_wet";
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
  // hazardRiskPeriod (from the "Hazard/Risk Layers" viewer's own June/July/
  // August/September/JJAS selector), NOT seasonalPeriod -- that's a
  // completely separate control belonging to the unrelated Seasonal climate
  // indicator map (SPI/rainfall/CDD/CWD rasters). This table ranks the same
  // Hazard/Risk catalog the Hazard/Risk Layers viewer shows, so it needs to
  // follow that viewer's own period control, not the climate map's.
  const period = forecastSelection.hazardRiskPeriod || getCurrentSeasonalPeriod();

  const [rankingLayers, setRankingLayers] = useState([]);
  const [category, setCategory] = useState("risk");
  const [selectedByCategory, setSelectedByCategory] = useState(
    DEFAULT_SELECTED_BY_CATEGORY,
  );
  const [adminLevel, setAdminLevel] = useState("admin1");
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

  // Memoized so this stays referentially stable across renders while
  // rankingData is null (e.g. still loading) -- otherwise `|| []` mints a
  // brand-new empty array every render, and this value is a dependency of
  // the onRankingContextChange effect below, which would then re-fire (and
  // re-trigger a parent re-render) every single render, an infinite loop
  // that only becomes visible once a request is slow enough to keep
  // rankingData null for more than a few render cycles.
  const rankingItems = useMemo(() => rankingData?.ranking || [], [rankingData]);

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
    const priorityInfo = combineDroughtWetLevel(item);

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
      {
        label: `Population exposed (to ${rankByLabel})`,
        value: formatPopulationExposed(item),
      },
      {
        label: `Area extent (of ${rankByLabel})`,
        value: formatAreaExtent(item),
      },
      { label: "Cropland extent", value: formatCroplandExtentPct(item) },
      { label: "Livestock extent", value: formatLivestockExtentPct(item) },
      { label: "Built-up extent", value: formatBuiltUpExtentPct(item) },
      { label: "Roads extent", value: formatRoadsExtentPct(item) },
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
      // Real hazard_type ("drought"/"wet"/"dominant"/null) of whatever
      // layer was actually ranked by -- lets SelectedAreaAdvisory.jsx apply
      // the same drought/wet badge-redundancy rule as this table, keyed off
      // the layer's real metadata instead of guessing from rankBy's string.
      selected_map_layer_hazard_type: layerMetaByValue[rankBy]?.hazard_type,
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
      // Real values for SelectedAreaAdvisory.jsx's "Impact-based risk
      // evidence" cards -- these were previously never set under the field
      // names that component reads (risk_score/hazard_probability/exposure
      // /vulnerability/hazard/risk_level), so every card showed "N/A" even
      // though item.metrics/priorityInfo already carried the real values.
      hazard: hazardLayerMeta?.hazard_type || "",
      hazard_probability: item.metrics[selectedByCategory.probability],
      exposure: item.metrics[selectedByCategory.exposure],
      vulnerability: item.metrics[selectedByCategory.vulnerability],
      risk_score: item.metrics[selectedByCategory.risk],
      risk_level: priorityInfo.level,
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

  // Population Exposed/Area Extent are computed against whichever metric is
  // currently ranked by (rankBy) -- NOT the Exposure category's own selected
  // metric (e.g. the "Population" normalized-density column can read 1.00
  // while ranking by Drought Risk, so "Population exposed: 64,073 (94.1%)"
  // would otherwise look like a second view of that same 1.00, when it's
  // really "94.1% of this area's people live where Drought Risk clears its
  // threshold" -- naming the column headers after rankBy's own label avoids
  // that mix-up.
  const rankByLabel = layerMetaByValue[rankBy]?.label || titleCase(rankBy);

  // Ranking by ANY drought-specific layer (Drought Hazard, Drought
  // Probability, Drought Vulnerability, Drought Risk -- not just Drought
  // Risk itself) already makes drought the point of this ranking, so an
  // unrelated Wet Risk badge alongside it is redundant, and vice versa.
  // Keyed off the layer's own real hazard_type metadata (LAYER_DEFINITIONS
  // in app/api/hazard_risk_catalog_shared.py), not a literal layer-value
  // string match -- that's what missed Drought Probability/Vulnerability
  // before.
  //
  // Ranking by Exposure (Population, Cropland, Livestock, etc.) has NO
  // hazard_type at all (it's null in LAYER_DEFINITIONS) -- that's a
  // genuinely different case from "redundant", it's "not what this view is
  // about", so the whole column is hidden rather than collapsed to one
  // badge or shown as both.
  const rankByHazardType = layerMetaByValue[rankBy]?.hazard_type;
  const showRiskColumn = Boolean(rankByHazardType);
  const showDroughtBadge = rankByHazardType !== "wet";
  const showWetBadge = rankByHazardType !== "drought";
  const droughtWetColumnLabel =
    showDroughtBadge && showWetBadge
      ? "Drought / Wet Risk"
      : showDroughtBadge
        ? "Drought Risk"
        : "Wet Risk";

  // Reports the currently-active layer for each category, plus the real
  // ranking result itself (count + how many are Trigger-level + the current
  // #1 area), up to Dashboard.jsx. RiskMap.jsx's "Key terms" glossary panel
  // uses the layer metadata; DashboardHero's KPI tiles use the counts/area
  // -- both read live off this table's own real ranking instead of each
  // keeping a separate, possibly-stale copy of this state.
  useEffect(() => {
    if (typeof onRankingContextChange === "function") {
      const triggerCount = rankingItems.filter(
        (item) => combineDroughtWetLevel(item).level === "trigger",
      ).length;

      onRankingContextChange({
        hazardLayerMeta,
        probabilityLayerMeta,
        exposureLayerMeta,
        vulnerabilityLayerMeta,
        riskLayerMeta,
        rankBy,
        rankByHazardType,
        rankingCount: rankingItems.length,
        triggerCount,
        topRankedArea: rankingItems[0] || null,
        // Real ranked items (already sized by this table's own Top
        // 3/5/10 selector) plus the SAME selection handler the "View on
        // map" button uses -- so RiskMap.jsx can plot these areas as
        // points and, on click, activate SelectedAreaAdvisory exactly as
        // if the table's own button had been clicked, with zero
        // duplicated selection-building logic.
        rankingItems,
        selectArea: handlePriorityAreaSelect,
      });
    }
    // handlePriorityAreaSelect is a fresh closure every render, but every
    // real value it reads (hazardLayerMeta/etc, rankBy, period, adminLevel)
    // is already listed below, so the effect still re-fires exactly when
    // its behavior would actually change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    onRankingContextChange,
    hazardLayerMeta,
    probabilityLayerMeta,
    exposureLayerMeta,
    vulnerabilityLayerMeta,
    riskLayerMeta,
    rankingItems,
    rankBy,
    rankByHazardType,
    period,
    adminLevel,
  ]);

  const sortColumnGetters = {
    hazard: (item) => item.metrics[selectedByCategory.hazard],
    probability: (item) => item.metrics[selectedByCategory.probability],
    vulnerability: (item) => item.metrics[selectedByCategory.vulnerability],
    risk: (item) => item.metrics[selectedByCategory.risk],
    priority_score: (item) => item.priority_score,
    population_exposed: (item) => item.population_exposed,
    area_extent_km2: (item) => item.area_extent_km2,
    cropland_extent_pct: (item) => item.cropland_extent_pct,
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
              {showRiskColumn && (
                <SortableColumnHeader
                  column="priority_score"
                  label={droughtWetColumnLabel}
                  sortColumn={sortColumn}
                  sortDirection={sortDirection}
                  onSort={handleSortClick}
                />
              )}
              <SortableColumnHeader
                column="population_exposed"
                label={`Population exposed (to ${rankByLabel})`}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="area_extent_km2"
                label={`Area extent (of ${rankByLabel})`}
                sortColumn={sortColumn}
                sortDirection={sortDirection}
                onSort={handleSortClick}
              />
              <SortableColumnHeader
                column="cropland_extent_pct"
                label="Cropland extent"
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
              const droughtInfo = getLevelInfo(item.drought_risk?.level);
              const wetInfo = getLevelInfo(item.wet_risk?.level);

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

                  {showRiskColumn && (
                    <td>
                      <div className="drought-wet-risk-pills">
                        {showDroughtBadge && (
                          <span className={`priority-score-pill ${droughtInfo.className}`}>
                            {showWetBadge ? "Drought: " : ""}
                            {droughtInfo.label}
                            {item.drought_risk ? ` (${item.drought_risk.value.toFixed(1)})` : ""}
                          </span>
                        )}
                        {showWetBadge && (
                          <span className={`priority-score-pill ${wetInfo.className}`}>
                            {showDroughtBadge ? "Wet: " : ""}
                            {wetInfo.label}
                            {item.wet_risk ? ` (${item.wet_risk.value.toFixed(1)})` : ""}
                          </span>
                        )}
                      </div>
                    </td>
                  )}

                  <td>{formatPopulationExposed(item)}</td>
                  <td>{formatAreaExtent(item)}</td>
                  <td>{formatCroplandExtentPct(item)}</td>

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
                <td colSpan={showRiskColumn ? 11 : 10}>
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
