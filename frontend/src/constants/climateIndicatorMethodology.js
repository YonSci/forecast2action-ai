// Real, verbatim climate-indicator computation methodology for the
// Seasonal Climate Indices panel (rainfall_total, rainfall_percentile,
// spi, cdd, cwd, rx1day, rx5day). Supplied directly by the user (not
// derived from code in this repo or the raster-methodology source doc --
// no sourceUrl is attached here for that reason, unlike
// rasterMethodology.js's hazard/exposure/vulnerability/risk formulas).
export const CLIMATE_INDICATOR_METHODOLOGY = {
  rainfall_total: {
    title: "Rainfall total methodology",
    steps: [
      {
        title: "1. Sum daily rainfall over the period",
        formulas: [
          "Rainfall_total = Σ R_t   (sum over all days t in the period)",
        ],
      },
    ],
  },

  rainfall_percentile: {
    title: "Rainfall percentile methodology",
    steps: [
      {
        title: "1. Rank the current total against its historical distribution",
        formulas: [
          "P_rain = percentile_rank(Rainfall_total_current, {Rainfall_total_hist, 1993…2025})",
        ],
        note: "Ranked against the historical distribution of Rainfall_total for the same calendar period. Result: 0–100.",
      },
    ],
  },

  spi: {
    title: "SPI (Standardized Precipitation Index, SPI-3) methodology",
    steps: [
      {
        title:
          "1. Aggregate rainfall over the target timescale (3 months for SPI-3)",
        formulas: ["R_agg = Σ R_t   over the rolling/seasonal window"],
      },
      {
        title: "2. Fit a Gamma distribution to the historical R_agg series",
        formulas: [
          "G(x; α, β)   — shape α, scale β, fit via maximum likelihood",
        ],
        note: "Same calendar window, same grid cell, standard McKee et al. (1993) procedure.",
      },
      {
        title:
          "3. Convert the fitted cumulative probability to a standard normal deviate",
        formulas: ["SPI = Φ⁻¹( G(R_agg_current; α, β) )"],
        note: "Φ⁻¹ is the inverse standard normal CDF. Result: unitless, roughly −3 to +3, mean 0.",
      },
    ],
  },

  cdd: {
    title: "CDD (Consecutive Dry Days) methodology",
    steps: [
      {
        title: "1. Find the longest dry-day run",
        formulas: [
          "CDD = max run-length of consecutive days with R_t < 1 mm within the period",
        ],
      },
      {
        title: "2. Convert to a percentile",
        formulas: [
          "p_CDD = historical percentile rank of CDD at that cell, that calendar period",
        ],
      },
    ],
  },

  cwd: {
    title: "CWD (Consecutive Wet Days) methodology",
    steps: [
      {
        title: "1. Find the longest wet-day run",
        formulas: [
          "CWD = max run-length of consecutive days with R_t ≥ 1 mm within the period",
        ],
      },
      {
        title: "2. Convert to a percentile",
        formulas: [
          "p_CWD = historical percentile rank of CWD at that cell, that calendar period",
        ],
      },
    ],
  },

  rx1day: {
    title: "Rx1day (max 1-day rainfall) methodology",
    steps: [
      {
        title: "1. Take the single wettest day in the period",
        formulas: ["Rx1day = max( R_t )   over all days t in the period"],
      },
    ],
  },

  rx5day: {
    title: "Rx5day (max 5-day rainfall) methodology",
    steps: [
      {
        title: "1. Take the wettest rolling 5-day window in the period",
        formulas: [
          "Rx5day = max( Σ_{t=i}^{i+4} R_t )   over all valid 5-day windows i in the period",
        ],
      },
    ],
  },
};
