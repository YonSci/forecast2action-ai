import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";
import MethodologySteps from "../components/MethodologySteps.jsx";
import {
  RASTER_METHODOLOGY,
  RASTER_METHODOLOGY_SOURCE_URL,
} from "../constants/rasterMethodology.js";
import { CLIMATE_INDICATOR_METHODOLOGY } from "../constants/climateIndicatorMethodology.js";

const RASTER_CATEGORY_LABELS = {
  hazard: "Hazard",
  probability: "Probability",
  exposure: "Exposure",
  vulnerability: "Vulnerability",
  risk: "Risk",
};

const CLIMATE_INDICATOR_ORDER = [
  "rainfall_total",
  "spi",
  "rainfall_percentile",
  "cdd",
  "cwd",
  "rx1day",
  "rx5day",
];

function DocEntry({ methodology }) {
  return (
    <div className="lp-feature-card" style={{ marginBottom: 22 }}>
      <h3 style={{ marginBottom: 16 }}>{methodology.title}</h3>
      <MethodologySteps steps={methodology.steps} />
    </div>
  );
}

function TechnicalDocumentation() {
  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> Technical documentation
          </span>
          <h1>Every calculation, step by step</h1>
          <p className="lp-hero-sub">
            The complete, real formula set behind every layer on the dashboard
            climate indicators, hazard, probability, exposure, vulnerability,
            and risk exactly as shown in the map legends, consolidated here in
            one reference. Nothing on this page is simplified or paraphrased
            from what the app actually computes.
          </p>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Climate indicators</h2>
          <p className="lp-prose" style={{ marginBottom: 18 }}>
            Real definitions used by the Seasonal Climate Indices panel SPI,
            rainfall percentile, CDD/CWD, and Rx1day/Rx5day are all derived from
            the same underlying daily rainfall series.
          </p>
          {CLIMATE_INDICATOR_ORDER.map((key) => (
            <DocEntry
              key={key}
              methodology={CLIMATE_INDICATOR_METHODOLOGY[key]}
            />
          ))}
        </div>
      </section>

      <hr className="lp-article-divider" />

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Hazard, probability, exposure, vulnerability &amp; risk</h2>
          <p className="lp-prose" style={{ marginBottom: 18 }}>
            The full risk chain used by the Hazard / Exposure / Vulnerability /
            Risk Layers panel:{" "}
            <code style={{ color: "var(--lp-teal)" }}>
              Risk = 100 × Probability × Severity × Exposure × Vulnerability
            </code>
            . Sourced from the project's own published methodology,
            cross-checked rather than assumed the drought and wet sides use
            genuinely different signal weights, not mirrored copies of each
            other.
          </p>

          {Object.entries(RASTER_METHODOLOGY).map(([category, entries]) => (
            <div key={category} style={{ marginBottom: 34 }}>
              <h3
                style={{
                  fontSize: "1.05rem",
                  color: "var(--lp-muted)",
                  marginBottom: 14,
                }}
              >
                {RASTER_CATEGORY_LABELS[category] || category}
              </h3>
              {Object.entries(entries).map(([layerKey, methodology]) => (
                <DocEntry key={layerKey} methodology={methodology} />
              ))}
            </div>
          ))}

          <p className="lp-meta-line">
            <a
              href={RASTER_METHODOLOGY_SOURCE_URL}
              target="_blank"
              rel="noreferrer"
            >
              Full methodology reference ↗
            </a>{" "}
            · see also{" "}
            <Link to="/data-sources" style={{ color: "var(--lp-teal)" }}>
              Data sources
            </Link>{" "}
            for exactly which real datasets feed each of these formulas.
          </p>
        </div>
      </section>
    </SubPageLayout>
  );
}

export default TechnicalDocumentation;
