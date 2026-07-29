// Canonical seasonal climate indicator / period / product vocabulary.
//
// This mirrors app/api/seasonal_catalog_shared.py on the backend. Both
// ForecastLayerMap (map explorer + fallback options) and AIMapInterpretation
// (ranking summaries + report labels) need the same set of indicator values,
// so it lives here once instead of being hand-copied into each component.
// The backend's /api/seasonal-raster/options endpoint is still the source of
// truth for what's actually *available* on disk -- this list is only the
// fallback/default vocabulary used before that call resolves (or if it fails).

export const CLIMATE_INDICATORS = [
  { value: "rainfall_total", label: "Rainfall Total" },
  { value: "spi", label: "SPI" },
  { value: "cdd", label: "CDD" },
  { value: "cwd", label: "CWD" },
  { value: "rx1day", label: "Rx1day" },
  { value: "rx5day", label: "Rx5day" },
  { value: "dryspell_prob_5d", label: "Dry spell probability ≥5 days" },
  { value: "dryspell_prob_7d", label: "Dry spell probability ≥7 days" },
  { value: "dryspell_prob_9d", label: "Dry spell probability ≥9 days" },
  { value: "rainfall_percentile", label: "Rainfall Percentile" },
];

// Hidden from the Climate indicator dropdown (ForecastLayerMap) and excluded
// from the AI report's Ethiopia-wide indicator summaries (AIMapInterpretation)
// until their climatology/anomaly rasters are backfilled -- removed by
// request, not because the data is missing. Shared here (not duplicated per
// file) so both stay in sync with what's actually offered -- a hardcoded
// duplicate of this set is exactly how the "Climate indicators used" display
// text previously drifted out of sync (still mentioned dryspell probabilities
// after Rx1day/Rx5day replaced them as the actually-visible indicators).
export const HIDDEN_CLIMATE_INDICATORS = new Set([
  "dryspell_prob_5d",
  "dryspell_prob_7d",
  "dryspell_prob_9d",
]);

export const VISIBLE_CLIMATE_INDICATORS = CLIMATE_INDICATORS.filter(
  (item) => !HIDDEN_CLIMATE_INDICATORS.has(item.value),
);

export const SEASONAL_PERIODS = [
  { value: "June", label: "June", scale: "seasonal" },
  { value: "July", label: "July", scale: "seasonal" },
  { value: "August", label: "August", scale: "seasonal" },
  { value: "September", label: "September", scale: "seasonal" },
  { value: "JJAS", label: "JJAS", scale: "seasonal" },
];

export const SUBSEASONAL_PERIODS = [
  { value: "week_1", label: "Week 1", scale: "subseasonal" },
  { value: "week_2", label: "Week 2", scale: "subseasonal" },
  { value: "week_3", label: "Week 3", scale: "subseasonal" },
  { value: "week_4", label: "Week 4", scale: "subseasonal" },
  { value: "week_1_2", label: "Week 1-2", scale: "subseasonal" },
  { value: "week_2_3", label: "Week 2-3", scale: "subseasonal" },
  { value: "week_3_4", label: "Week 3-4", scale: "subseasonal" },
  { value: "week_1_3", label: "Week 1-3", scale: "subseasonal" },
  { value: "week_2_4", label: "Week 2-4", scale: "subseasonal" },
];

export const ALL_SEASONAL_PERIODS = [
  ...SUBSEASONAL_PERIODS,
  ...SEASONAL_PERIODS,
];

// The seasonal vocabulary only covers June-September (+ the JJAS
// aggregate) -- confirmed against what actually has real raster data on
// disk (data/maps/geotiff etc. only ever have June/July/August/September
// files, never October-May). Resolving "today" to the current calendar
// month only works for 4 months of the year; the other 8 fall back to
// JJAS (the whole-season aggregate) rather than picking an arbitrary
// nearest month, since JJAS is already a valid, real, selectable period
// and doesn't imply false precision about which specific month applies.
export function getCurrentSeasonalPeriod() {
  const monthName = new Date().toLocaleString("en-US", { month: "long" });
  const inVocabulary = SEASONAL_PERIODS.some((item) => item.value === monthName);
  return inVocabulary ? monthName : "JJAS";
}

export const CLIMATE_SCALES = [
  { value: "subseasonal", label: "Subseasonal" },
  { value: "seasonal", label: "Seasonal" },
];

export const SEASONAL_PRODUCTS = [
  { value: "forecast", label: "Forecast" },
  { value: "climatology", label: "Climatology" },
  { value: "anomaly", label: "Anomaly" },
  { value: "drought_probability", label: "Drought Probability" },
  { value: "wet_probability", label: "Wet Probability" },
];

export const SEASONAL_PRODUCT_ORDER = SEASONAL_PRODUCTS.map(
  (item) => item.value,
);
