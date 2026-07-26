import { useEffect, useMemo, useReducer, useState } from "react";
import {
  GeoJSON,
  ImageOverlay,
  LayersControl,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiUrl } from "../config.js";
import { BASEMAP_OPTIONS } from "../constants/basemaps.js";
import {
  ALL_SEASONAL_PERIODS,
  CLIMATE_INDICATORS,
  CLIMATE_SCALES,
  SEASONAL_PRODUCTS,
  SEASONAL_PRODUCT_ORDER,
} from "../constants/climateIndicators.js";
import "../styles/mapSwitcher.css";

const OPTIONS = {
  forecast_scales: [
    { value: "subseasonal", label: "Subseasonal" },
    { value: "seasonal", label: "Seasonal" },
  ],
  leads: [
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
  ],
  layers: [
    { value: "hazard", label: "Hazard Map" },
    { value: "risk_score", label: "Risk Score Map" },
    { value: "hazard_probability", label: "Hazard Probability Map" },
    { value: "exposure", label: "Exposure Map" },
    { value: "vulnerability", label: "Vulnerability Map" },
  ],
};

// The Hazard/Risk Layers panel no longer has its own Forecast window / Lead
// selectors -- it reuses whatever forecast window + time period is already
// selected in the Seasonal Climate Indices panel, so the two panels stay in
// sync instead of asking the user to pick the same thing twice. The two
// panels use different period vocabularies though (seasonal climate periods
// are calendar months / "JJAS"; hazard leads are "month_1".."month_6"), so
// this maps one onto the other. JJAS is a 4-month aggregate with no single
// hazard lead equivalent, and week_1_3/week_2_4 don't exist in the hazard
// lead list either -- both fall back to the nearest lead.
const SEASONAL_PERIOD_TO_HAZARD_LEAD = {
  june: "month_1",
  july: "month_2",
  august: "month_3",
  september: "month_4",
  jjas: "month_1",
};

const SUBSEASONAL_PERIOD_TO_HAZARD_LEAD = {
  week_1: "week_1",
  week_2: "week_2",
  week_3: "week_3",
  week_4: "week_4",
  week_1_2: "week_1_2",
  week_2_3: "week_2_3",
  week_3_4: "week_3_4",
  week_1_3: "week_1_2",
  week_2_4: "week_2_3",
};

function deriveHazardLeadFromSeasonal(scale, period) {
  const periodKey = String(period).toLowerCase();
  if (scale === "subseasonal") {
    return {
      forecastScale: "subseasonal",
      lead: SUBSEASONAL_PERIOD_TO_HAZARD_LEAD[periodKey] || "week_1",
    };
  }
  return {
    forecastScale: "seasonal",
    lead: SEASONAL_PERIOD_TO_HAZARD_LEAD[periodKey] || "month_1",
  };
}

const FALLBACK_SEASONAL_OPTIONS = {
  indicators: CLIMATE_INDICATORS,
  periods: ALL_SEASONAL_PERIODS,
  products: SEASONAL_PRODUCTS,
  scales: CLIMATE_SCALES,
  available: [],
};

const PRODUCT_ORDER = SEASONAL_PRODUCT_ORDER;

// Hidden from the Climate indicator dropdown for now -- removed by request,
// not because the data is missing. rainfall_percentile was previously hidden
// here too, but is no longer: it now has real forecast + climatology rasters
// (see data/maps/geotiff/*_percentile_median.tif / *_percentile_climatology_mean.tif),
// not just the single forecast-only netcdf/csv it used to have.
const HIDDEN_CLIMATE_INDICATORS = new Set([
  "dryspell_prob_5d",
  "dryspell_prob_7d",
  "dryspell_prob_9d",
]);

const INITIAL_SEASONAL_STATE = {
  options: FALLBACK_SEASONAL_OPTIONS,
  scale: "seasonal",
  indicator: "rainfall_total",
  period: "June",
  product: "forecast",
  view: "single",
  selectedMap: null,
  compareMaps: {},
  compareProducts: PRODUCT_ORDER,
  loading: false,
  errorMessage: "",
};

// Given the scale/indicator/period/product combinations the backend actually
// has data for, return the closest valid combination to what was requested.
// Prefers staying within the requested scale, then falls back to
// indicator+period match, then indicator match, then anything.
function pickValidSeasonalCombo(available, scale, indicator, period, product) {
  if (!available.length) {
    return { scale, indicator, period, product };
  }

  const scoped = available.filter(
    (item) => (item.scale || "seasonal") === scale,
  );
  const pool = scoped.length ? scoped : available;

  const periodLower = String(period).toLowerCase();
  const isValid = pool.some(
    (item) =>
      item.indicator === indicator &&
      String(item.period).toLowerCase() === periodLower &&
      item.product === product,
  );

  if (isValid) {
    return { scale, indicator, period, product };
  }

  const next =
    pool.find(
      (item) =>
        item.indicator === indicator &&
        String(item.period).toLowerCase() === periodLower,
    ) ||
    pool.find((item) => item.indicator === indicator) ||
    pool[0];

  return {
    scale: next.scale || scale,
    indicator: next.indicator,
    period: next.period,
    product: next.product,
  };
}

// Consolidates the climate indicator section's selection, fetched data, and
// load status into one reducer. Keeping scale/indicator/period/product
// validation here (rather than in a useEffect that corrects an
// already-rendered invalid selection on a later pass) means the state is
// never invalid in the first place, instead of a separate "auto-correct"
// effect chasing every setter.
function seasonalReducer(state, action) {
  switch (action.type) {
    case "SET_OPTIONS": {
      const available = Array.isArray(action.options.available)
        ? action.options.available
        : [];
      const picked = pickValidSeasonalCombo(
        available,
        state.scale,
        state.indicator,
        state.period,
        state.product,
      );
      return { ...state, options: action.options, ...picked };
    }
    case "SET_SCALE": {
      const available = Array.isArray(state.options.available)
        ? state.options.available
        : [];
      const picked = pickValidSeasonalCombo(
        available,
        action.value,
        state.indicator,
        state.period,
        state.product,
      );
      return { ...state, ...picked };
    }
    case "SET_INDICATOR": {
      const available = Array.isArray(state.options.available)
        ? state.options.available
        : [];
      const picked = pickValidSeasonalCombo(
        available,
        state.scale,
        action.value,
        state.period,
        state.product,
      );
      return { ...state, ...picked };
    }
    case "SET_PERIOD": {
      const available = Array.isArray(state.options.available)
        ? state.options.available
        : [];
      const picked = pickValidSeasonalCombo(
        available,
        state.scale,
        state.indicator,
        action.value,
        state.product,
      );
      return { ...state, ...picked };
    }
    case "SET_PRODUCT":
      return { ...state, product: action.value };
    case "SET_VIEW":
      return { ...state, view: action.value };
    case "FETCH_START":
      return { ...state, loading: true, errorMessage: "" };
    case "FETCH_SUCCESS":
      return {
        ...state,
        loading: false,
        selectedMap: action.selectedMap,
        compareMaps: action.compareMaps,
        compareProducts: action.compareProducts,
        errorMessage: action.errorMessage || "",
      };
    case "FETCH_ERROR":
      return {
        ...state,
        loading: false,
        selectedMap: null,
        compareMaps: {},
        compareProducts: PRODUCT_ORDER,
        errorMessage: action.errorMessage,
      };
    default:
      return state;
  }
}

// Exposure/Vulnerability ship one static file that applies to every period
// (see app/api/hazard_risk_catalog_shared.py's STATIC_PERIOD) -- the period
// dropdown is disabled whenever the selected layer falls in one of these
// categories, since changing it would have no effect.
const HAZARD_RISK_STATIC_CATEGORIES = new Set(["exposure", "vulnerability"]);

const FALLBACK_HAZARD_RISK_OPTIONS = {
  categories: [],
  periods: [],
  layers: [],
};

const INITIAL_HAZARD_RISK_STATE = {
  options: FALLBACK_HAZARD_RISK_OPTIONS,
  category: "risk",
  layerValue: "population_r_drought",
  period: "JJAS",
  selectedMap: null,
  loading: false,
  errorMessage: "",
};

function hazardRiskReducer(state, action) {
  switch (action.type) {
    case "SET_OPTIONS": {
      const layers = action.options.layers || [];
      const stillValid = layers.some((item) => item.value === state.layerValue);
      const fallbackLayer =
        layers.find((item) => item.category === state.category) || layers[0];
      return {
        ...state,
        options: action.options,
        layerValue: stillValid
          ? state.layerValue
          : fallbackLayer?.value || state.layerValue,
        category: stillValid
          ? state.category
          : fallbackLayer?.category || state.category,
      };
    }
    case "SET_CATEGORY": {
      const firstLayerInCategory = state.options.layers.find(
        (item) => item.category === action.value,
      );
      return {
        ...state,
        category: action.value,
        layerValue: firstLayerInCategory?.value || state.layerValue,
      };
    }
    case "SET_LAYER": {
      const layerMeta = state.options.layers.find(
        (item) => item.value === action.value,
      );
      return {
        ...state,
        layerValue: action.value,
        category: layerMeta?.category || state.category,
      };
    }
    case "SET_PERIOD":
      return { ...state, period: action.value };
    case "FETCH_START":
      return { ...state, loading: true, errorMessage: "" };
    case "FETCH_SUCCESS":
      return {
        ...state,
        loading: false,
        selectedMap: action.selectedMap,
        errorMessage: action.errorMessage || "",
      };
    case "FETCH_ERROR":
      return {
        ...state,
        loading: false,
        selectedMap: null,
        errorMessage: action.errorMessage,
      };
    default:
      return state;
  }
}

const INDICATOR_LEGENDS = {
  rainfall_total: {
    title: "Rainfall total",
    lowLabel: "Low rainfall",
    highLabel: "High rainfall",
    items: [
      { label: "Low", color: "#F79009" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#0E9384" },
      { label: "Very high", color: "#1570EF" },
    ],
  },
  spi: {
    title: "SPI",
    lowLabel: "Dry / negative SPI",
    highLabel: "Wet / positive SPI",
    items: [
      { label: "Severe dry", color: "#B42318" },
      { label: "Moderate dry", color: "#F79009" },
      { label: "Near normal", color: "#12B76A" },
      { label: "Wet", color: "#1570EF" },
    ],
  },
  rainfall_percentile: {
    title: "Rainfall percentile",
    lowLabel: "Low percentile",
    highLabel: "High percentile",
    items: [
      { label: "Very low", color: "#B42318" },
      { label: "Low", color: "#F79009" },
      { label: "Normal", color: "#12B76A" },
      { label: "High", color: "#1570EF" },
    ],
  },
  rx1day: {
    title: "Rx1day (max 1-day rainfall)",
    lowLabel: "Low max 1-day rainfall",
    highLabel: "High max 1-day rainfall",
    items: [
      { label: "Low", color: "#F79009" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#0E9384" },
      { label: "Very high", color: "#1570EF" },
    ],
  },
  rx5day: {
    title: "Rx5day (max 5-day rainfall)",
    lowLabel: "Low max 5-day rainfall",
    highLabel: "High max 5-day rainfall",
    items: [
      { label: "Low", color: "#F79009" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#0E9384" },
      { label: "Very high", color: "#1570EF" },
    ],
  },
  cdd: {
    title: "Consecutive dry days",
    lowLabel: "Few dry days",
    highLabel: "Long dry spell",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#F79009" },
      { label: "Very high", color: "#B42318" },
    ],
  },
  cwd: {
    title: "Consecutive wet days",
    lowLabel: "Few wet days",
    highLabel: "Long wet spell",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#0E9384" },
      { label: "High", color: "#1570EF" },
      { label: "Very high", color: "#1849A9" },
    ],
  },
  dryspell_prob_5d: {
    title: "Dry spell probability ≥5 days",
    lowLabel: "Low probability",
    highLabel: "High probability",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#F79009" },
      { label: "Very high", color: "#B42318" },
    ],
  },
  dryspell_prob_7d: {
    title: "Dry spell probability ≥7 days",
    lowLabel: "Low probability",
    highLabel: "High probability",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#F79009" },
      { label: "Very high", color: "#B42318" },
    ],
  },
  dryspell_prob_9d: {
    title: "Dry spell probability ≥9 days",
    lowLabel: "Low probability",
    highLabel: "High probability",
    items: [
      { label: "Low", color: "#12B76A" },
      { label: "Moderate", color: "#FEC84B" },
      { label: "High", color: "#F79009" },
      { label: "Very high", color: "#B42318" },
    ],
  },
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

function formatValue(value, digits = 2) {
  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return "N/A";
  }

  return numberValue.toFixed(digits);
}

// Hazard/risk raster units (see app/api/hazard_risk_catalog_shared.py's
// LAYER_DEFINITIONS) aren't readable appended raw the way climate indicator
// units are (e.g. "mm", "days") -- "1.57 score" reads as noise, not a
// unit. This only remaps hazard/risk's own vocabulary; every other units
// string (climate indicators) still appends as before.
const HAZARD_RISK_UNIT_SUFFIXES = {
  score: " / 100",
  probability: "",
  index: "",
  normalized: "",
  code: "",
  class: "",
};

function formatUnitsSuffix(units) {
  if (!units) {
    return "";
  }
  if (Object.prototype.hasOwnProperty.call(HAZARD_RISK_UNIT_SUFFIXES, units)) {
    return HAZARD_RISK_UNIT_SUFFIXES[units];
  }
  return ` ${units}`;
}

function getOptionLabel(options, value, fallback = "") {
  const match = options.find((item) => item.value === value);
  return match?.label || fallback || titleCase(value);
}

function normalizeUrl(url) {
  if (!url) {
    return "";
  }

  if (
    String(url).startsWith("http://") ||
    String(url).startsWith("https://") ||
    String(url).startsWith("data:")
  ) {
    return url;
  }

  return apiUrl(url);
}

function getBoundaryOverlayStyle(feature) {
  const level = feature.properties?.admin_level;

  if (level === "admin3") {
    return {
      color: "#111827",
      weight: 2.2,
      fillOpacity: 0,
    };
  }

  if (level === "admin2") {
    return {
      color: "#111827",
      weight: 1.9,
      fillOpacity: 0,
    };
  }

  return {
    color: "#111827",
    weight: 1.4,
    fillOpacity: 0,
  };
}

function IndicatorLegend({ indicator }) {
  const legend = INDICATOR_LEGENDS[indicator] || INDICATOR_LEGENDS.spi;

  return (
    <div className="forecast-indicator-legend">
      {legend.items.map((item) => (
        <span key={`${indicator}-${item.label}`}>
          <i style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
      <div className="forecast-gradient-labels forecast-indicator-range-labels">
        <span>{legend.lowLabel}</span>
        <span>{legend.highLabel}</span>
      </div>
    </div>
  );
}

function MetadataItem({ label, value }) {
  if (value === undefined || value === null || value === "") {
    return null;
  }

  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SeasonalMetadataGrid({ map }) {
  if (!map) {
    return null;
  }

  return (
    <div className="seasonal-map-metadata-grid">
      <MetadataItem label="Init date" value={map.init_date} />
      <MetadataItem label="Valid start" value={map.valid_start} />
      <MetadataItem label="Valid end" value={map.valid_end} />
      <MetadataItem label="Forecast source" value={map.forecast_source} />
      <MetadataItem
        label="System version"
        value={map.forecast_system_version}
      />
      <MetadataItem label="Ensemble members" value={map.n_ensemble_members} />
      <MetadataItem
        label="Observation dataset"
        value={map.observation_dataset}
      />
      <MetadataItem label="Climatology period" value={map.climatology_period} />
      <MetadataItem label="Units" value={map.units} />
    </div>
  );
}

function normalizeBounds(bounds) {
  let rawSouth = 3;
  let rawWest = 33;
  let rawNorth = 15;
  let rawEast = 48;

  if (Array.isArray(bounds) && bounds.length === 4) {
    rawWest = Number(bounds[0]);
    rawSouth = Number(bounds[1]);
    rawEast = Number(bounds[2]);
    rawNorth = Number(bounds[3]);
  } else if (bounds) {
    rawSouth = Number(bounds.south ?? bounds[1] ?? 3);
    rawWest = Number(bounds.west ?? bounds[0] ?? 33);
    rawNorth = Number(bounds.north ?? bounds[3] ?? 15);
    rawEast = Number(bounds.east ?? bounds[2] ?? 48);
  }

  return {
    south: Math.min(rawSouth, rawNorth),
    west: Math.min(rawWest, rawEast),
    north: Math.max(rawSouth, rawNorth),
    east: Math.max(rawWest, rawEast),
  };
}

function FitSeasonalRasterBounds({ map, viewKey }) {
  const leafletMap = useMap();

  useEffect(() => {
    const bounds = normalizeBounds(map?.bounds);

    if (
      Number.isFinite(bounds.south) &&
      Number.isFinite(bounds.west) &&
      Number.isFinite(bounds.north) &&
      Number.isFinite(bounds.east)
    ) {
      leafletMap.fitBounds(
        [
          [bounds.south, bounds.west],
          [bounds.north, bounds.east],
        ],
        {
          padding: [8, 8],
          animate: true,
          duration: 0.4,
        },
      );
    }
  }, [leafletMap, map?.id, viewKey]);

  return null;
}

function BasemapPaneOpacity({ opacity }) {
  const leafletMap = useMap();

  useEffect(() => {
    // Applying opacity via the TileLayer's own `opacity` prop fades each
    // tile <img> individually, which leaves faint seams visible along tile
    // edges (a well-known Leaflet/Chromium compositing quirk). Fading the
    // whole tile pane in one paint avoids that entirely.
    const pane = leafletMap.getPane("tilePane");
    if (pane) {
      pane.style.opacity = String(opacity);
    }
  }, [leafletMap, opacity]);

  return null;
}

function nearestIndex(values, target) {
  let bestIndex = 0;
  let bestDiff = Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const diff = Math.abs(values[i] - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = i;
    }
  }
  return bestIndex;
}

function nearestGridValue(grid, lat, lon) {
  if (!grid?.lats?.length || !grid?.lons?.length) {
    return null;
  }
  const row = grid.values[nearestIndex(grid.lats, lat)];
  const value = row ? row[nearestIndex(grid.lons, lon)] : null;
  return value === undefined ? null : value;
}

function RasterHoverHandler({ grid, onHover }) {
  useMapEvents({
    mousemove(event) {
      if (!grid) {
        return;
      }
      onHover({
        x: event.containerPoint.x,
        y: event.containerPoint.y,
        value: nearestGridValue(grid, event.latlng.lat, event.latlng.lng),
      });
    },
    mouseout() {
      onHover(null);
    },
  });

  return null;
}

function RasterValueClickHandler({ onClick }) {
  useMapEvents({
    click(event) {
      onClick({ lat: event.latlng.lat, lon: event.latlng.lng });
    },
  });

  return null;
}

// Tracks where a shared (possibly cross-map) inspected lat/lon falls on THIS
// particular map instance's screen, so the compare view's three independent
// Leaflet maps can each show their own tooltip at the same geographic point
// clicked on any one of them, not just the one the user actually clicked.
function RasterInspectPosition({ latlng, onPosition }) {
  const leafletMap = useMap();

  useEffect(() => {
    if (!latlng) {
      onPosition(null);
      return undefined;
    }

    const update = () => {
      const point = leafletMap.latLngToContainerPoint([latlng.lat, latlng.lon]);
      onPosition({ x: point.x, y: point.y });
    };

    update();
    leafletMap.on("move", update);
    leafletMap.on("zoom", update);

    return () => {
      leafletMap.off("move", update);
      leafletMap.off("zoom", update);
    };
  }, [leafletMap, latlng, onPosition]);

  return null;
}

function RasterLegend({ map, indicator }) {
  const legend = map?.legend;

  // Discrete class layers (e.g. hazard/risk's risk_class: Very low..Very
  // high) have no meaningful gradient between bands -- unlike every other
  // raster legend here, so they get their own fixed-swatch rendering
  // instead of the continuous gradient bar below.
  if (legend?.type === "categorical" && legend.items?.length) {
    return (
      <div className="forecast-hazard-legend">
        {legend.items.map((item) => (
          <span key={`${map.id}-categorical-legend-${item.value}`}>
            <i style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
    );
  }

  const legendItems = legend?.items || [];

  if (legendItems.length) {
    const gradient = `linear-gradient(to right, ${legendItems.map((item) => item.color).join(", ")})`;
    const tickIndexes = [
      0,
      Math.floor((legendItems.length - 1) / 2),
      legendItems.length - 1,
    ];
    const ticks = tickIndexes
      .map((index) => legendItems[index])
      .filter(Boolean);

    return (
      <div className="seasonal-continuous-legend">
        <div className="seasonal-continuous-legend-header">
          <strong>
            {map.legend.title || map.indicator_label || "Raster value"}
          </strong>
          {map.legend.units && <span>{map.legend.units}</span>}
        </div>
        <div
          className="seasonal-continuous-legend-bar"
          style={{ background: gradient }}
        />
        <div className="seasonal-continuous-legend-ticks">
          {ticks.map((item, index) => (
            <span key={`${map.id}-continuous-legend-${index}`}>
              {item.label}
            </span>
          ))}
        </div>
        <div className="forecast-gradient-labels forecast-indicator-range-labels seasonal-continuous-range-labels">
          <span>{map.legend.low_label || "Low"}</span>
          <span>{map.legend.high_label || "High"}</span>
        </div>
      </div>
    );
  }

  return <IndicatorLegend indicator={indicator} />;
}

function RasterStatsSummary({ map }) {
  const stats = map?.statistics;

  if (!stats) {
    return null;
  }

  return (
    <div className="seasonal-raster-stats-grid">
      <MetadataItem
        label="Min"
        value={stats.min !== undefined ? formatValue(stats.min, 2) : ""}
      />
      <MetadataItem
        label="Mean"
        value={stats.mean !== undefined ? formatValue(stats.mean, 2) : ""}
      />
      <MetadataItem
        label="Max"
        value={stats.max !== undefined ? formatValue(stats.max, 2) : ""}
      />
      <MetadataItem
        label="P10"
        value={stats.p10 !== undefined ? formatValue(stats.p10, 2) : ""}
      />
      <MetadataItem
        label="P90"
        value={stats.p90 !== undefined ? formatValue(stats.p90, 2) : ""}
      />
      <MetadataItem label="Valid cells" value={stats.valid_count} />
    </div>
  );
}

function SeasonalInteractiveMapCard({
  map,
  title,
  compact = false,
  emptyText = "Interactive map not found for this selection.",
  boundaryGeojson = null,
  boundaryKey = "all",
  inspectPoint = null,
  onInspectPoint = null,
  indicator = null,
  valueEndpointBase = "/api/seasonal-raster",
}) {
  const [clickedValue, setClickedValue] = useState(null);
  const [hoverInfo, setHoverInfo] = useState(null);
  const [valueGrid, setValueGrid] = useState(null);
  const [inspectMarkerPos, setInspectMarkerPos] = useState(null);
  const [rasterOpacity, setRasterOpacity] = useState(compact ? 0.74 : 0.68);
  const [basemapOpacity, setBasemapOpacity] = useState(0.86);
  const imageUrl = map?.image_url ? normalizeUrl(map.image_url) : "";
  const bounds = normalizeBounds(map?.bounds);
  const mapKey = `${map?.id || "missing"}-${title}`;
  const leafletBounds = [
    [bounds.south, bounds.west],
    [bounds.north, bounds.east],
  ];

  useEffect(() => {
    setValueGrid(null);
    if (!map?.id || !map?.grid_url) {
      return undefined;
    }

    let cancelled = false;
    fetch(apiUrl(map.grid_url))
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled && data) {
          setValueGrid({ ...data, units: map.units || data.units });
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [map?.id, map?.grid_url, map?.units]);

  // Re-reads this card's own raster whenever the shared inspect point moves,
  // so clicking any one of the compare-mode maps looks up and displays the
  // value at that same lat/lon on every map, not just the one clicked.
  useEffect(() => {
    if (!inspectPoint || !map?.id) {
      setClickedValue(null);
      return undefined;
    }

    let cancelled = false;
    setClickedValue({
      loading: true,
      message: "Reading raster value...",
      lat: inspectPoint.lat,
      lon: inspectPoint.lon,
    });

    const params = new URLSearchParams();
    params.set("lat", String(inspectPoint.lat));
    params.set("lon", String(inspectPoint.lon));

    fetch(apiUrl(`${valueEndpointBase}/value/${map.id}?${params.toString()}`))
      .then((response) =>
        response.ok
          ? response.json()
          : Promise.reject(new Error(`status ${response.status}`)),
      )
      .then((data) => {
        if (cancelled) return;
        setClickedValue({
          loading: false,
          lat: inspectPoint.lat,
          lon: inspectPoint.lon,
          value: data.value,
          formatted_value: data.formatted_value,
          units: data.units,
          message:
            data.formatted_value || "No value available at clicked point.",
        });
      })
      .catch(() => {
        if (cancelled) return;
        setClickedValue({
          loading: false,
          lat: inspectPoint.lat,
          lon: inspectPoint.lon,
          value: null,
          message: "Could not read raster value at this point.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [map?.id, inspectPoint, valueEndpointBase]);

  return (
    <article
      className={`seasonal-map-card seasonal-raster-card${compact ? " compact" : ""}`}
    >
      <div className="seasonal-map-card-header">
        <h3>{title || map?.product_label || "Seasonal map"}</h3>
        {map?.period && <span>{map.period}</span>}
      </div>

      {imageUrl ? (
        <div className="seasonal-raster-map-frame">
          <MapContainer
            center={[
              (bounds.south + bounds.north) / 2,
              (bounds.west + bounds.east) / 2,
            ]}
            zoom={compact ? 5.6 : 6.15}
            minZoom={4.75}
            maxZoom={10}
            zoomSnap={0.25}
            zoomDelta={0.25}
            maxBounds={leafletBounds}
            maxBoundsViscosity={0.55}
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
                    keepBuffer={4}
                  />
                </LayersControl.BaseLayer>
              ))}
            </LayersControl>
            <ImageOverlay
              key={`seasonal-raster-${mapKey}`}
              attribution={map?.attribution || "Seasonal climate raster"}
              url={imageUrl}
              bounds={leafletBounds}
              opacity={rasterOpacity}
              zIndex={420}
            />
            {boundaryGeojson && (
              <GeoJSON
                key={`seasonal-boundary-${mapKey}-${boundaryKey}`}
                data={boundaryGeojson}
                style={getBoundaryOverlayStyle}
              />
            )}
            <BasemapPaneOpacity opacity={basemapOpacity} />
            <FitSeasonalRasterBounds map={map} viewKey={mapKey} />
            <RasterValueClickHandler
              onClick={(latlng) => onInspectPoint?.(latlng)}
            />
            <RasterHoverHandler grid={valueGrid} onHover={setHoverInfo} />
            <RasterInspectPosition
              latlng={inspectPoint}
              onPosition={setInspectMarkerPos}
            />
          </MapContainer>

          {hoverInfo && Number.isFinite(hoverInfo.value) ? (
            <div
              className="seasonal-raster-hover-tooltip"
              style={{ left: hoverInfo.x, top: hoverInfo.y }}
            >
              {formatValue(hoverInfo.value, 2)}
              {formatUnitsSuffix(valueGrid?.units)}
            </div>
          ) : null}

          {inspectMarkerPos && (
            <>
              <div
                className="seasonal-raster-inspect-marker"
                style={{ left: inspectMarkerPos.x, top: inspectMarkerPos.y }}
              />
              {clickedValue &&
                !clickedValue.loading &&
                Number.isFinite(clickedValue.value) && (
                  <div
                    className="seasonal-raster-hover-tooltip seasonal-raster-inspect-tooltip"
                    style={{
                      left: inspectMarkerPos.x,
                      top: inspectMarkerPos.y,
                    }}
                  >
                    {clickedValue.formatted_value ||
                      `${formatValue(clickedValue.value, 2)}${formatUnitsSuffix(clickedValue.units)}`}
                  </div>
                )}
            </>
          )}

          <div className="seasonal-raster-map-badge">
            Hover or click map to inspect value
          </div>
          {!compact && (
            <div
              className="seasonal-raster-map-controls"
              aria-label="Map opacity controls"
            >
              <label>
                <span>Raster</span>
                <input
                  type="range"
                  min="0.35"
                  max="1"
                  step="0.05"
                  value={rasterOpacity}
                  onChange={(event) =>
                    setRasterOpacity(Number(event.target.value))
                  }
                />
              </label>
              <label>
                <span>Basemap</span>
                <input
                  type="range"
                  min="0.25"
                  max="1"
                  step="0.05"
                  value={basemapOpacity}
                  onChange={(event) =>
                    setBasemapOpacity(Number(event.target.value))
                  }
                />
              </label>
            </div>
          )}
        </div>
      ) : (
        <div className="seasonal-map-empty">{emptyText}</div>
      )}

      {clickedValue && (
        <div className="seasonal-raster-click-value">
          <span>Clicked value</span>
          <strong>{clickedValue.message}</strong>
          {Number.isFinite(clickedValue.lat) &&
            Number.isFinite(clickedValue.lon) && (
              <small>
                {formatValue(clickedValue.lat, 3)},{" "}
                {formatValue(clickedValue.lon, 3)}
              </small>
            )}
        </div>
      )}

      {map && (
        <>
          {compact && <RasterLegend map={map} indicator={indicator} />}
          <RasterStatsSummary map={map} />
          {!compact && <SeasonalMetadataGrid map={map} />}
        </>
      )}
    </article>
  );
}

function ForecastLayerMap({ adminSelection = {}, onForecastSelectionChange }) {
  // No longer user-selectable (the old grid-cell hazard/risk map dropdown was
  // removed in favor of the real-raster section below), but AIMapInterpretation
  // still reads `layer`/`layerLabel` off onForecastSelectionChange's payload
  // (see forecastSelection.layer usages there), so this stays fixed at its
  // original default rather than being deleted outright.
  const [layer] = useState("hazard");

  const [seasonalState, dispatchSeasonal] = useReducer(
    seasonalReducer,
    INITIAL_SEASONAL_STATE,
  );
  const {
    options: seasonalOptions,
    scale: seasonalScale,
    indicator: seasonalIndicator,
    period: seasonalPeriod,
    product: seasonalProduct,
    view: climateMapView,
    selectedMap: selectedSeasonalMap,
    compareMaps: compareSeasonalMaps,
    compareProducts: seasonalCompareProducts,
    loading: seasonalLoading,
    errorMessage: seasonalErrorMessage,
  } = seasonalState;

  const [hazardRiskState, dispatchHazardRisk] = useReducer(
    hazardRiskReducer,
    INITIAL_HAZARD_RISK_STATE,
  );
  const {
    options: hazardRiskOptions,
    category: hazardRiskCategory,
    layerValue: hazardRiskLayer,
    period: hazardRiskPeriod,
    selectedMap: selectedHazardRiskMap,
    loading: hazardRiskLoading,
    errorMessage: hazardRiskErrorMessage,
  } = hazardRiskState;
  const [hazardRiskInspectPoint, setHazardRiskInspectPoint] = useState(null);

  const boundaryGeojson = adminSelection?.boundaryGeojson || null;
  const [seasonalInspectPoint, setSeasonalInspectPoint] = useState(null);

  // Forecast window + Lead/horizon for the Hazard/Risk Layers panel are no
  // longer independently selectable -- they follow whatever is already
  // selected in the Seasonal Climate Indices panel above (see
  // deriveHazardLeadFromSeasonal for the period-vocabulary mapping).
  const { forecastScale, lead } = useMemo(
    () => deriveHazardLeadFromSeasonal(seasonalScale, seasonalPeriod),
    [seasonalScale, seasonalPeriod],
  );

  const selectedLayerLabel = getOptionLabel(OPTIONS.layers, layer);
  const selectedLeadLabel = getOptionLabel(OPTIONS.leads, lead);
  const selectedSeasonalScaleLabel = getOptionLabel(
    seasonalOptions.scales,
    seasonalScale,
  );
  const selectedSeasonalIndicatorLabel = getOptionLabel(
    seasonalOptions.indicators,
    seasonalIndicator,
  );
  const selectedSeasonalPeriodLabel = getOptionLabel(
    seasonalOptions.periods,
    seasonalPeriod,
  );
  const selectedSeasonalProductLabel = getOptionLabel(
    seasonalOptions.products,
    seasonalProduct,
  );

  const seasonalAvailableCombinations = Array.isArray(seasonalOptions.available)
    ? seasonalOptions.available
    : [];

  // Subseasonal climate-indicator maps are temporarily hidden until their
  // climatology/anomaly rasters are backfilled (see conversation with data
  // owner) -- only the seasonal scale is offered for now.
  const seasonalScaleOptions = useMemo(() => {
    return seasonalOptions.scales.filter(
      (item) => item.value !== "subseasonal",
    );
  }, [seasonalOptions.scales]);

  const seasonalIndicatorOptions = useMemo(() => {
    const visibleIndicators = seasonalOptions.indicators.filter(
      (item) => !HIDDEN_CLIMATE_INDICATORS.has(item.value),
    );
    const scoped = seasonalAvailableCombinations.filter(
      (item) => (item.scale || "seasonal") === seasonalScale,
    );
    const pool = scoped.length ? scoped : seasonalAvailableCombinations;
    if (!pool.length) {
      return visibleIndicators;
    }
    const values = new Set(pool.map((item) => item.indicator));
    return visibleIndicators.filter((item) => values.has(item.value));
  }, [
    seasonalOptions.indicators,
    seasonalAvailableCombinations,
    seasonalScale,
  ]);

  const seasonalPeriodOptions = useMemo(() => {
    const periodsForScale = seasonalOptions.periods.filter(
      (item) => (item.scale || "seasonal") === seasonalScale,
    );
    if (!seasonalAvailableCombinations.length) {
      return periodsForScale;
    }
    const values = new Set(
      seasonalAvailableCombinations
        .filter(
          (item) =>
            item.indicator === seasonalIndicator &&
            (item.scale || "seasonal") === seasonalScale,
        )
        .map((item) => String(item.period).toLowerCase()),
    );
    return periodsForScale.filter((item) =>
      values.has(String(item.value).toLowerCase()),
    );
  }, [
    seasonalOptions.periods,
    seasonalAvailableCombinations,
    seasonalIndicator,
    seasonalScale,
  ]);

  const seasonalProductOptions = useMemo(() => {
    if (!seasonalAvailableCombinations.length) {
      return seasonalOptions.products;
    }
    const values = new Set(
      seasonalAvailableCombinations
        .filter(
          (item) =>
            item.indicator === seasonalIndicator &&
            String(item.period).toLowerCase() ===
              String(seasonalPeriod).toLowerCase() &&
            (item.scale || "seasonal") === seasonalScale,
        )
        .map((item) => item.product),
    );
    return seasonalOptions.products.filter((item) => values.has(item.value));
  }, [
    seasonalOptions.products,
    seasonalAvailableCombinations,
    seasonalIndicator,
    seasonalPeriod,
    seasonalScale,
  ]);

  const displayedClimateMapLabel = `${selectedSeasonalIndicatorLabel} · ${selectedSeasonalPeriodLabel} · ${selectedSeasonalProductLabel}`;

  const selectedAdminLabel =
    adminSelection?.woredaLabel ||
    adminSelection?.zoneLabel ||
    adminSelection?.regionLabel ||
    "All Ethiopia administrative areas";

  const seasonalBoundaryKey = `${adminSelection?.regionId || "all"}-${adminSelection?.zoneId || "all"}-${adminSelection?.woredaId || "all"}`;

  // Both sections are always visible together (no tab switcher), so the
  // context sent to the AI interpretation workflow always describes both.
  const activeMapGroup = "Climate Indicator Maps and Hazard/Risk Layers";
  const activeMapLabel = `${displayedClimateMapLabel} (climate indicator) and ${selectedLayerLabel} (hazard/risk)`;

  useEffect(() => {
    if (typeof onForecastSelectionChange === "function") {
      onForecastSelectionChange({
        forecastScale,
        lead,
        leadLabel: selectedLeadLabel,
        layer,
        layerLabel: selectedLayerLabel,
        indicator: seasonalIndicator,
        activeMapGroup,
        activeMapLabel,
        seasonalScale,
        seasonalScaleLabel: selectedSeasonalScaleLabel,
        seasonalIndicator,
        seasonalIndicatorLabel: selectedSeasonalIndicatorLabel,
        seasonalPeriod,
        seasonalPeriodLabel: selectedSeasonalPeriodLabel,
        seasonalProduct,
        seasonalProductLabel: selectedSeasonalProductLabel,
        climateMapView,
        seasonalMap: selectedSeasonalMap,
        seasonalCompareMaps: compareSeasonalMaps,
      });
    }
  }, [
    forecastScale,
    lead,
    selectedLeadLabel,
    layer,
    selectedLayerLabel,
    seasonalIndicator,
    activeMapGroup,
    activeMapLabel,
    seasonalScale,
    selectedSeasonalScaleLabel,
    selectedSeasonalIndicatorLabel,
    seasonalPeriod,
    selectedSeasonalPeriodLabel,
    seasonalProduct,
    selectedSeasonalProductLabel,
    climateMapView,
    selectedSeasonalMap,
    compareSeasonalMaps,
    onForecastSelectionChange,
  ]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadSeasonalOptions() {
      try {
        const response = await fetch(apiUrl("/api/seasonal-raster/options"), {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(
            `Seasonal options request failed: ${response.status}`,
          );
        }

        const data = await response.json();
        dispatchSeasonal({
          type: "SET_OPTIONS",
          options: {
            indicators: data.indicators?.length
              ? data.indicators
              : FALLBACK_SEASONAL_OPTIONS.indicators,
            periods: data.periods?.length
              ? data.periods
              : FALLBACK_SEASONAL_OPTIONS.periods,
            products: data.products?.length
              ? data.products
              : FALLBACK_SEASONAL_OPTIONS.products,
            scales: data.scales?.length
              ? data.scales
              : FALLBACK_SEASONAL_OPTIONS.scales,
            available: Array.isArray(data.available) ? data.available : [],
          },
        });
      } catch (error) {
        if (error.name !== "AbortError") {
          console.warn(error);
          dispatchSeasonal({
            type: "SET_OPTIONS",
            options: FALLBACK_SEASONAL_OPTIONS,
          });
        }
      }
    }

    loadSeasonalOptions();

    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadSeasonalMap() {
      dispatchSeasonal({ type: "FETCH_START" });

      try {
        const selectedParams = new URLSearchParams();
        selectedParams.set("indicator", seasonalIndicator);
        selectedParams.set("period", seasonalPeriod);
        selectedParams.set("product", seasonalProduct);

        const compareParams = new URLSearchParams();
        compareParams.set("indicator", seasonalIndicator);
        compareParams.set("period", seasonalPeriod);

        const [selectedResponse, compareResponse] = await Promise.all([
          fetch(
            apiUrl(`/api/seasonal-raster/map?${selectedParams.toString()}`),
            {
              signal: controller.signal,
            },
          ),
          fetch(
            apiUrl(`/api/seasonal-raster/compare?${compareParams.toString()}`),
            {
              signal: controller.signal,
            },
          ),
        ]);

        if (!selectedResponse.ok) {
          throw new Error(
            `Selected seasonal map request failed: ${selectedResponse.status}`,
          );
        }

        const selectedData = await selectedResponse.json();
        const compareData = compareResponse.ok
          ? await compareResponse.json()
          : { maps: {}, products: [] };

        dispatchSeasonal({
          type: "FETCH_SUCCESS",
          selectedMap: selectedData.map || null,
          compareMaps: compareData.maps || {},
          compareProducts:
            Array.isArray(compareData.products) && compareData.products.length
              ? compareData.products
              : PRODUCT_ORDER,
          errorMessage: selectedData.map
            ? ""
            : selectedData.message ||
              `No raster map was found for ${seasonalIndicator} ${seasonalPeriod} ${seasonalProduct}. Check /api/seasonal-raster/options and /api/seasonal-raster/health.`,
        });
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
          dispatchSeasonal({
            type: "FETCH_ERROR",
            errorMessage:
              "Could not load the interactive seasonal raster map. Check files in data/maps/geotiff, data/maps/netcdf, or data/maps/csv and confirm /api/seasonal-raster is registered.",
          });
        }
      }
    }

    loadSeasonalMap();

    return () => controller.abort();
  }, [seasonalIndicator, seasonalPeriod, seasonalProduct]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadHazardRiskOptions() {
      try {
        const response = await fetch(apiUrl("/api/hazard-risk/options"), {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(
            `Hazard/risk options request failed: ${response.status}`,
          );
        }

        const data = await response.json();
        dispatchHazardRisk({
          type: "SET_OPTIONS",
          options: {
            categories: data.categories || [],
            periods: data.periods || [],
            layers: data.layers || [],
          },
        });
      } catch (error) {
        if (error.name !== "AbortError") {
          console.warn(error);
        }
      }
    }

    loadHazardRiskOptions();

    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadHazardRiskMap() {
      dispatchHazardRisk({ type: "FETCH_START" });

      try {
        const params = new URLSearchParams();
        params.set("layer", hazardRiskLayer);
        params.set("period", hazardRiskPeriod);

        const response = await fetch(
          apiUrl(`/api/hazard-risk/map?${params.toString()}`),
          { signal: controller.signal },
        );

        if (!response.ok) {
          throw new Error(`Hazard/risk map request failed: ${response.status}`);
        }

        const data = await response.json();
        dispatchHazardRisk({
          type: "FETCH_SUCCESS",
          selectedMap: data.map || null,
          errorMessage: data.map
            ? ""
            : data.message ||
              `No hazard/risk map was found for layer=${hazardRiskLayer} period=${hazardRiskPeriod}. Check /api/hazard-risk/options and /api/hazard-risk/health.`,
        });
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
          dispatchHazardRisk({
            type: "FETCH_ERROR",
            errorMessage:
              "Could not load the hazard/risk raster map. Check data/maps/{Hazard,Probability_Severity,Exposure,Vulnerability,Risk} and confirm /api/hazard-risk is registered.",
          });
        }
      }
    }

    loadHazardRiskMap();

    return () => controller.abort();
  }, [hazardRiskLayer, hazardRiskPeriod]);

  const compareProductOrder = seasonalCompareProducts?.length
    ? seasonalCompareProducts
    : PRODUCT_ORDER;
  const compareCards = compareProductOrder.map((product) => {
    const fallbackLabel = getOptionLabel(seasonalOptions.products, product);
    return {
      product,
      label: compareSeasonalMaps?.[product]?.product_label || fallbackLabel,
      map: compareSeasonalMaps?.[product] || null,
    };
  });

  const hazardRiskLayersByCategory = useMemo(() => {
    const groups = new Map();
    for (const item of hazardRiskOptions.layers) {
      if (!groups.has(item.category)) {
        groups.set(item.category, []);
      }
      groups.get(item.category).push(item);
    }
    return groups;
  }, [hazardRiskOptions.layers]);

  const isStaticHazardRiskLayer =
    HAZARD_RISK_STATIC_CATEGORIES.has(hazardRiskCategory);
  const selectedHazardRiskLayerLabel = getOptionLabel(
    hazardRiskOptions.layers,
    hazardRiskLayer,
  );
  const selectedHazardRiskPeriodLabel = isStaticHazardRiskLayer
    ? "All periods"
    : getOptionLabel(hazardRiskOptions.periods, hazardRiskPeriod);
  const selectedHazardRiskCategoryLabel = getOptionLabel(
    hazardRiskOptions.categories,
    hazardRiskCategory,
  );
  const hazardRiskBoundaryKey = `${adminSelection?.regionId || "all"}-${adminSelection?.zoneId || "all"}-${adminSelection?.woredaId || "all"}`;

  return (
    <>
      <section className="panel forecast-layer-section climate-indicator-section">
        <div className="forecast-layer-header">
          <div>
            <h2>Climate Indices</h2>
            <p className="map-selected-area">
              Selected area: <strong>{selectedAdminLabel}</strong>
            </p>
          </div>

          <div className="forecast-domain-badge">
            Seasonal maps · Ethiopia domain
          </div>
        </div>

        <div className="forecast-layer-controls">
          <div className="forecast-control">
            <label htmlFor="seasonal-scale">Forecast window</label>
            <select
              id="seasonal-scale"
              value={seasonalScale}
              onChange={(event) =>
                dispatchSeasonal({
                  type: "SET_SCALE",
                  value: event.target.value,
                })
              }
            >
              {seasonalScaleOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="forecast-control">
            <label htmlFor="seasonal-period">Time period</label>
            <select
              id="seasonal-period"
              value={seasonalPeriod}
              onChange={(event) =>
                dispatchSeasonal({
                  type: "SET_PERIOD",
                  value: event.target.value,
                })
              }
            >
              {seasonalPeriodOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="forecast-control forecast-control-primary">
            <label htmlFor="seasonal-indicator">Climate indicator</label>
            <select
              id="seasonal-indicator"
              value={seasonalIndicator}
              onChange={(event) =>
                dispatchSeasonal({
                  type: "SET_INDICATOR",
                  value: event.target.value,
                })
              }
            >
              {seasonalIndicatorOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="forecast-control">
            <label htmlFor="seasonal-product">Map product</label>
            <select
              id="seasonal-product"
              value={seasonalProduct}
              onChange={(event) =>
                dispatchSeasonal({
                  type: "SET_PRODUCT",
                  value: event.target.value,
                })
              }
              disabled={climateMapView === "compare"}
            >
              {seasonalProductOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="forecast-control forecast-control-primary forecast-control-active-only">
            <label htmlFor="climate-view-switch">View mode</label>
            <button
              id="climate-view-switch"
              type="button"
              role="switch"
              aria-checked={climateMapView === "compare"}
              className="seasonal-view-switch"
              onClick={() =>
                dispatchSeasonal({
                  type: "SET_VIEW",
                  value: climateMapView === "compare" ? "single" : "compare",
                })
              }
            >
              <span className="seasonal-view-switch-track">
                <span className="seasonal-view-switch-thumb" />
              </span>
              <span className="seasonal-view-switch-labels">
                <span className={climateMapView === "single" ? "active" : ""}>
                  Single map
                </span>
                <span className={climateMapView === "compare" ? "active" : ""}>
                  Compare (3 maps)
                </span>
              </span>
            </button>
          </div>
        </div>

        <div className="forecast-layer-summary">
          <div>
            <span>Forecast window</span>
            <strong>{selectedSeasonalScaleLabel}</strong>
          </div>

          <div>
            <span>Time period</span>
            <strong>{selectedSeasonalPeriodLabel}</strong>
          </div>

          <div>
            <span>Climate indicator</span>
            <strong>{selectedSeasonalIndicatorLabel}</strong>
          </div>

          <div>
            <span>Map product</span>
            <strong>{selectedSeasonalProductLabel}</strong>
          </div>
        </div>

        {seasonalErrorMessage && (
          <div className="error-banner">{seasonalErrorMessage}</div>
        )}

        <div className="seasonal-map-viewer">
          {seasonalLoading && (
            <div className="forecast-map-loading seasonal-loading">
              Loading seasonal climate map...
            </div>
          )}

          {climateMapView === "single" ? (
            <div id="forecast-risk-map" className="seasonal-single-map-layout">
              <SeasonalInteractiveMapCard
                map={selectedSeasonalMap}
                title={displayedClimateMapLabel}
                emptyText="No interactive raster map was found for this indicator, period, and product. Check data/maps/geotiff, data/maps/netcdf, data/maps/csv, or seasonal_raster_catalog.json."
                boundaryGeojson={boundaryGeojson}
                boundaryKey={seasonalBoundaryKey}
                inspectPoint={seasonalInspectPoint}
                onInspectPoint={setSeasonalInspectPoint}
              />

              <aside className="forecast-legend-card seasonal-info-card">
                <h3>Seasonal climate map</h3>
                <p className="forecast-legend-mode">
                  {selectedSeasonalIndicatorLabel}:{" "}
                  <strong>{selectedSeasonalPeriodLabel}</strong>
                </p>
                <RasterLegend
                  map={selectedSeasonalMap}
                  indicator={seasonalIndicator}
                />
                <SeasonalMetadataGrid map={selectedSeasonalMap} />
              </aside>
            </div>
          ) : (
            <div className="seasonal-compare-section">
              <div className="seasonal-compare-header">
                <div>
                  <h3>{compareCards.map((item) => item.label).join(" vs ")}</h3>
                  {/* <p>
                    {compareProductOrder.join(",") ===
                    PRODUCT_ORDER.join(",")
                      ? "Compare what the seasonal forecast says, the climatology for the same period, and how different the forecast is from normal."
                      : `Compare these three ${selectedSeasonalIndicatorLabel} views for the same period.`}
                  </p> */}
                </div>
                <span>
                  {selectedSeasonalIndicatorLabel} ·{" "}
                  {selectedSeasonalPeriodLabel}
                </span>
              </div>

              <div className="seasonal-compare-grid">
                {compareCards.map((item) => (
                  <SeasonalInteractiveMapCard
                    key={item.product}
                    map={item.map}
                    title={item.label}
                    compact
                    emptyText={`${item.label} interactive map is not available for ${selectedSeasonalIndicatorLabel} ${selectedSeasonalPeriodLabel}.`}
                    boundaryGeojson={boundaryGeojson}
                    boundaryKey={seasonalBoundaryKey}
                    inspectPoint={seasonalInspectPoint}
                    onInspectPoint={setSeasonalInspectPoint}
                    indicator={seasonalIndicator}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="panel forecast-layer-section hazard-risk-raster-section">
        <div className="forecast-layer-header">
          <div>
            <h2>Hazard / Exposure / Vulnerability / Risk Layers</h2>
            <p className="map-selected-area">
              Selected area: <strong>{selectedAdminLabel}</strong>
            </p>
          </div>
          <div className="forecast-domain-badge">Lat 3–15°N · Lon 33–48°E</div>
        </div>

        <div className="forecast-layer-controls">
          <div className="forecast-control">
            <label htmlFor="hazard-risk-category">Category</label>
            <select
              id="hazard-risk-category"
              value={hazardRiskCategory}
              onChange={(event) =>
                dispatchHazardRisk({
                  type: "SET_CATEGORY",
                  value: event.target.value,
                })
              }
            >
              {hazardRiskOptions.categories.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="forecast-control forecast-control-primary">
            <label htmlFor="hazard-risk-layer">Layer</label>
            <select
              id="hazard-risk-layer"
              value={hazardRiskLayer}
              onChange={(event) =>
                dispatchHazardRisk({
                  type: "SET_LAYER",
                  value: event.target.value,
                })
              }
            >
              {(hazardRiskLayersByCategory.get(hazardRiskCategory) || []).map(
                (item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ),
              )}
            </select>
          </div>

          <div className="forecast-control">
            <label htmlFor="hazard-risk-period">Period</label>
            <select
              id="hazard-risk-period"
              value={hazardRiskPeriod}
              disabled={isStaticHazardRiskLayer}
              onChange={(event) =>
                dispatchHazardRisk({
                  type: "SET_PERIOD",
                  value: event.target.value,
                })
              }
            >
              {isStaticHazardRiskLayer ? (
                <option value={hazardRiskPeriod}>All periods</option>
              ) : (
                hazardRiskOptions.periods.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>

        <div className="forecast-layer-summary">
          <div>
            <span>Category</span>
            <strong>{selectedHazardRiskCategoryLabel}</strong>
          </div>
          <div>
            <span>Layer</span>
            <strong>{selectedHazardRiskLayerLabel}</strong>
          </div>
          <div>
            <span>Period</span>
            <strong>{selectedHazardRiskPeriodLabel}</strong>
          </div>
        </div>

        {hazardRiskErrorMessage && (
          <div className="error-banner">{hazardRiskErrorMessage}</div>
        )}

        <div className="seasonal-map-viewer">
          {hazardRiskLoading && (
            <div className="forecast-map-loading seasonal-loading">
              Loading hazard/risk map...
            </div>
          )}

          <div className="seasonal-single-map-layout">
            <SeasonalInteractiveMapCard
              map={selectedHazardRiskMap}
              title={`${selectedHazardRiskLayerLabel} · ${selectedHazardRiskPeriodLabel}`}
              emptyText="No raster map was found for this layer/period. Check data/maps/{Hazard,Probability_Severity,Exposure,Vulnerability,Risk} and /api/hazard-risk/health."
              boundaryGeojson={boundaryGeojson}
              boundaryKey={hazardRiskBoundaryKey}
              inspectPoint={hazardRiskInspectPoint}
              onInspectPoint={setHazardRiskInspectPoint}
              valueEndpointBase="/api/hazard-risk"
            />

            <aside className="forecast-legend-card seasonal-info-card">
              <h3>Hazard/Risk layer</h3>
              <p className="forecast-legend-mode">
                {selectedHazardRiskLayerLabel}:{" "}
                <strong>{selectedHazardRiskPeriodLabel}</strong>
              </p>
              <RasterLegend map={selectedHazardRiskMap} />
            </aside>
          </div>
        </div>
      </section>
    </>
  );
}

export default ForecastLayerMap;
