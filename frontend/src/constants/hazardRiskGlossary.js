// Brief, human-readable definitions for the Priority Intervention Areas
// ranking metrics, keyed by the real hazard/risk raster layer value (see
// app/api/hazard_risk_catalog_shared.py's LAYER_DEFINITIONS) so the glossary
// panel can look up a definition for whichever metric is currently active
// under each category, in either drought or wet mode.
export const HAZARD_RISK_TERM_DEFINITIONS = {
  h_dry_mean:
    "Mean drought hazard intensity (0-1), combining SPI, rainfall percentile, and consecutive dry days.",
  h_wet_mean:
    "Mean wetness hazard intensity (0-1), combining SPI, rainfall percentile, and consecutive wet days.",
  p_drought:
    "Modeled probability (%) that drought conditions occur this period.",
  p_wet:
    "Modeled probability (%) that above-normal wet conditions occur this period.",
  v_drought:
    "Relative susceptibility to drought impact (0-1), based on livelihood and socioeconomic factors.",
  v_wet:
    "Relative susceptibility to flood / excess-wetness impact (0-1).",
  population_r_drought:
    "Composite drought risk score (0-100) = Probability x Severity x Exposure x Vulnerability.",
  population_r_wet:
    "Composite wet/flood risk score (0-100) = Probability x Severity x Exposure x Vulnerability.",
  population_risk_class:
    "Categorical risk level (Very low to Very high), derived from the dominant hazard's risk score.",
};

export const EXPOSURE_TERM_DEFINITION =
  "Normalized exposure (0-1) of this sector's population/assets in the area.";

export const PRIORITY_SCORE_DEFINITION =
  "Composite 0-1 score blending the ranked metric's area mean, peak value, and share of the area above threshold.";

export const POPULATION_EXPOSED_DEFINITION =
  "Real WorldPop 2020 population count (people) living within the part of the area where the ranked metric exceeds its threshold, and that as a % of the area's total population.";

export const AREA_EXTENT_DEFINITION =
  "Real ground area (km²), and % of the area's total, where the ranked metric exceeds its threshold.";

export const CROPLAND_EXTENT_DEFINITION =
  "% of the area's total land where the cropland exposure index exceeds its threshold. Shown as a percentage only -- the source raster is a coarse, unitless 0-1 index with no documented real-world hectare/km² basis.";

export function getTermDefinition(layerValue) {
  return HAZARD_RISK_TERM_DEFINITIONS[layerValue] || "";
}
