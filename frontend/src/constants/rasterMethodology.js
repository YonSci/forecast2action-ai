// Real, verbatim hazard/probability/exposure/vulnerability/risk index
// methodology for the Hazard/Exposure/Vulnerability/Risk Layers section.
// Source: https://yonsci.github.io/hydroclimatic-risk-mapping/docs/methodology.html
// (the project's own published methodology doc) -- NOT derived or guessed
// from code in this repo, since no generation script for these raster
// files exists here. Formulas were supplied directly by the methodology's
// author/doc and cross-checked against the source (e.g. the wet-hazard
// side uses different weights/signals than a simple mirror of the drought
// side, and exposure/vulnerability sub-components are only partially
// formula-specified in the source -- both gaps are disclosed explicitly
// below rather than papered over with an invented number.
export const RASTER_METHODOLOGY_SOURCE_URL =
  "https://yonsci.github.io/hydroclimatic-risk-mapping/docs/methodology.html";

const RISK_CLASS_TABLE = [
  ["0 – 19.9", "Very low"],
  ["20 – 39.9", "Low"],
  ["40 – 59.9", "Moderate"],
  ["60 – 79.9", "High"],
  ["80 – 100", "Very high"],
];

const DOMINANT_CODE_TABLE = [
  ["0", "Insignificant / no identified risk"],
  ["1", "Drought-dominated risk"],
  ["2", "Excess-wetness-dominated risk"],
  ["3", "Mixed / compound risk"],
];

export const RASTER_METHODOLOGY = {
  hazard: {
    h_dry_mean: {
      title: "Drought hazard methodology",
      steps: [
        {
          title: "1. Standardize each indicator into a 0–1 dry score",
          formulas: [
            "S_rain_dry = clip((50 − P_rain) / 40, 0, 1)",
            "S_SPI_dry = clip(−SPI / 2, 0, 1)",
            "S_CDD_dry = clip((p_CDD − 50) / 40, 0, 1)",
            "S_CWD_dry = clip((50 − p_CWD) / 40, 0, 1)",
          ],
          note: "P_rain = rainfall percentile (0–100). p_CDD/p_CWD = each index's own percentile rank. All percentiles are calendar-period-specific (e.g. JJAS compared only against historical JJAS).",
        },
        {
          title: "2. Combine into the per-realization hazard index",
          formulas: [
            "H_drought = 0.35 × S_SPI_dry + 0.20 × S_rain_dry + 0.30 × S_CDD_dry + 0.15 × S_CWD_dry",
          ],
          note: "Computed independently for every year (historical) or ensemble member (forecast) — not yet collapsed.",
        },
        {
          title: "3. Collapse across realizations into probability and severity",
          formulas: [
            "P_drought = count(H_drought ≥ 0.60) / total_valid_realizations",
            "S_drought = mean(H_drought among realizations where H_drought ≥ 0.60)",
          ],
          note: "High-hazard threshold = 0.60 (default). With a 25-member ensemble, P_drought moves in steps of 1/25 = 0.04. See the Probability category for more detail on this step.",
        },
        {
          title: "4. Recombine into the Hazard term",
          formulas: ["Hazard_drought = P_drought × S_drought"],
          note: "This is the value shown on this map. The full risk score (Hazard × Exposure × Vulnerability) is shown under the Risk category.",
        },
      ],
    },
    h_wet_mean: {
      title: "Wetness hazard methodology",
      steps: [
        {
          title: "1. Standardize each indicator into a 0–1 wet score",
          formulas: [
            "S_rain_wet = clip((P_rain − 50) / 40, 0, 1)",
            "S_SPI_wet = clip(SPI / 2, 0, 1)",
            "S_CWD_wet = clip((p_CWD − 50) / 40, 0, 1)",
            "S_Rx1day_wet = clip((p_Rx1day − 50) / 40, 0, 1)",
            "S_Rx5day_wet = clip((p_Rx5day − 50) / 40, 0, 1)",
          ],
          note: "All percentiles are calendar-period-specific.",
        },
        {
          title: "2. Combine into the per-realization hazard index",
          formulas: [
            "H_wet = 0.20 × S_SPI_wet + 0.20 × S_rain_wet + 0.20 × S_CWD_wet + 0.15 × S_Rx1day_wet + 0.25 × S_Rx5day_wet",
          ],
          note: "Note this is a 5-signal combination (adds Rx1day/Rx5day), not a direct mirror of the drought-side weights.",
        },
        {
          title: "3. Collapse across realizations into probability and severity",
          formulas: [
            "P_wet = count(H_wet ≥ 0.60) / total_valid_realizations",
            "S_wet = mean(H_wet among realizations classified as wetness events)",
          ],
          note: "See the Probability category for more detail on this step.",
        },
        {
          title: "4. Recombine into the Hazard term",
          formulas: ["Hazard_wet = P_wet × S_wet"],
          note: "This is the value shown on this map. The full risk score (Hazard × Exposure × Vulnerability) is shown under the Risk category.",
        },
      ],
    },
  },

  probability: {
    p_drought: {
      title: "Drought probability methodology",
      steps: [
        {
          title: "1. Define realizations",
          formulas: [],
          note: "Input data has either year × lat × lon (historical) or ensemble_member × lat × lon (forecast) dimensions. Each realization gets its own H_drought value (see Hazard methodology, step 2).",
        },
        {
          title: "2. Probability = share of realizations that qualify as a drought event",
          formulas: [
            "P_drought = count(H_drought ≥ 0.60) / total_valid_realizations",
          ],
          note: "With a 25-member ensemble (this project's default), probability moves in increments of 1/25 = 0.04 = 4%.",
        },
        {
          title: "3. Severity = average intensity among qualifying realizations",
          formulas: [
            "S_drought = mean(H_drought among realizations where H_drought ≥ 0.60)",
          ],
          note: "Probability and severity are recombined into Hazard_drought = P_drought × S_drought, then into the final Risk score together with Exposure and Vulnerability.",
        },
      ],
    },
    p_wet: {
      title: "Wet probability methodology",
      steps: [
        {
          title: "1. Define realizations",
          formulas: [],
          note: "Input data has either year × lat × lon (historical) or ensemble_member × lat × lon (forecast) dimensions. Each realization gets its own H_wet value (see Hazard methodology, step 2).",
        },
        {
          title: "2. Probability = share of realizations that qualify as a wetness event",
          formulas: ["P_wet = count(H_wet ≥ 0.60) / total_valid_realizations"],
          note: "With a 25-member ensemble (this project's default), probability moves in increments of 1/25 = 0.04 = 4%.",
        },
        {
          title: "3. Severity = average intensity among qualifying realizations",
          formulas: [
            "S_wet = mean(H_wet among realizations classified as wetness events)",
          ],
          note: "Probability and severity are recombined into Hazard_wet = P_wet × S_wet, then into the final Risk score together with Exposure and Vulnerability.",
        },
      ],
    },
  },

  vulnerability: {
    v_drought: {
      title: "Drought vulnerability methodology",
      steps: [
        {
          title: "1. Combine sensitivity and adaptive-capacity deficit",
          formulas: [
            "V_drought = 0.60 × drought_sensitivity + 0.40 × adaptive_capacity_deficit",
          ],
          note: "Both terms are 0–1 composite indices. The methodology doc lists which real indicators feed each composite (below) but does not publish the individual weight of each indicator within it.",
        },
        {
          title: "2. Drought-sensitivity indicators",
          list: [
            "Rainfed-agriculture dependence",
            "Drought-sensitive crop area",
            "Historical yield variability",
            "Low soil water-holding capacity",
            "Land degradation",
            "Water scarcity",
            "Poverty",
            "Food insecurity",
            "Livestock dependence",
          ],
        },
        {
          title: "3. Adaptive-capacity indicators (drought)",
          list: [
            "Irrigation access",
            "Water storage",
            "Functional water points",
            "Climate-information access",
            "Agricultural extension access",
            "Drought-tolerant seed access",
            "Credit",
            "Insurance",
            "Livelihood diversification",
            "Market access",
            "Social protection",
          ],
          note: "adaptive_capacity_deficit is the inverse of adaptive capacity built from these indicators — higher deficit means less capacity to adapt.",
        },
      ],
    },
    v_wet: {
      title: "Wetness vulnerability methodology",
      steps: [
        {
          title: "1. Combine sensitivity and adaptive-capacity deficit",
          formulas: [
            "V_wet = 0.60 × wetness_sensitivity + 0.40 × adaptive_capacity_deficit",
          ],
          note: "Both terms are 0–1 composite indices. The methodology doc lists which real indicators feed each composite (below) but does not publish the individual weight of each indicator within it.",
        },
        {
          title: "2. Wetness-sensitivity indicators",
          list: [
            "Poorly drained soils",
            "Low-lying terrain",
            "Topographic wetness",
            "Proximity to rivers",
            "Waterlogging-sensitive crops",
            "Historical wetness losses",
            "Erosion susceptibility",
            "Landslide susceptibility",
            "Poor housing",
            "Unpaved-road dependence",
            "Weak sanitation",
          ],
        },
        {
          title: "3. Adaptive-capacity indicators (wetness)",
          list: [
            "Agricultural drainage",
            "Urban drainage",
            "Flood-protection structures",
            "All-weather roads",
            "Improved storage",
            "Short-range forecast access",
            "Emergency-response capacity",
            "Health-service access",
            "Crop insurance",
            "Disease surveillance",
          ],
          note: "adaptive_capacity_deficit is the inverse of adaptive capacity built from these indicators — higher deficit means less capacity to adapt.",
        },
      ],
    },
  },

  risk: {
    population_r_drought: {
      title: "Drought risk methodology",
      steps: [
        {
          title: "1. Combine hazard, exposure, and vulnerability",
          formulas: [
            "R_drought = 100 × P_drought × S_drought × E_drought × V_drought",
            "= 100 × Hazard_drought × E_drought × V_drought",
          ],
          note: "This is a relative 0–100 risk score, not a probability percentage. See the Hazard, Probability, Exposure, and Vulnerability categories for how each term is built.",
        },
        {
          title: "2. Classify",
          formulas: ["R_dominant = max(R_drought, R_wet)"],
          table: RISK_CLASS_TABLE,
        },
      ],
    },
    population_r_wet: {
      title: "Wet risk methodology",
      steps: [
        {
          title: "1. Combine hazard, exposure, and vulnerability",
          formulas: [
            "R_wet = 100 × P_wet × S_wet × E_wet × V_wet",
            "= 100 × Hazard_wet × E_wet × V_wet",
          ],
          note: "This is a relative 0–100 risk score, not a probability percentage. See the Hazard, Probability, Exposure, and Vulnerability categories for how each term is built.",
        },
        {
          title: "2. Classify",
          formulas: ["R_dominant = max(R_drought, R_wet)"],
          table: RISK_CLASS_TABLE,
        },
      ],
    },
    population_risk_class: {
      title: "Risk class methodology",
      steps: [
        {
          title: "1. Take the dominant hazard's risk score",
          formulas: ["R_dominant = max(R_drought, R_wet)"],
        },
        {
          title: "2. Classify into 5 bands",
          table: RISK_CLASS_TABLE,
        },
      ],
    },
    population_dominant_code: {
      title: "Dominant hazard code methodology",
      steps: [
        {
          title: "1. Identify which hazard dominates at each location",
          formulas: ["R_dominant = max(R_drought, R_wet)"],
        },
        {
          title: "2. Assign a category code",
          table: DOMINANT_CODE_TABLE,
        },
      ],
    },
  },

  exposure: {
    __default: {
      title: "Exposure methodology",
      steps: [
        {
          title: "1. Real layers used",
          list: [
            "Population",
            "Rainfed cropland",
            "Irrigated cropland",
            "Livestock (cattle)",
            "Built-up areas",
            "Buildings",
            "Roads",
            "Health facilities",
          ],
          note: "This is the subset of the methodology's full exposure layer list (which also includes crop production, water infrastructure, settlements, and economic assets) that has real raster data in this deployment.",
        },
        {
          title: "2. Two forms are maintained per layer",
          formulas: [],
          note: "Absolute exposure (people, hectares, livestock head, etc.) and a normalized exposure index (0–1), using robust 5th/95th-percentile normalization.",
        },
        {
          title: "3. No cross-layer combination formula",
          formulas: [],
          note: "Each exposure layer (Population, Cropland, Livestock, Built-up, Roads, Health Facilities) is shown and used on its own, not combined into a single index — the methodology explicitly avoids combining incompatible physical units into one composite score unless separately requested.",
        },
      ],
    },
  },
};

export function getMethodologyForLayer(category, layerValue) {
  const byCategory = RASTER_METHODOLOGY[category];
  if (!byCategory) {
    return null;
  }
  return byCategory[layerValue] || byCategory.__default || null;
}
