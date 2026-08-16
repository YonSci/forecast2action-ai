import { useMemo } from "react";
import { Link } from "react-router-dom";
import ethiopiaAdmin1 from "../data/ethiopiaAdmin1.json";
import "../styles/landing.css";

const ETH_MAP_SIZE = 640;
const ETH_MAP_PADDING = 34;

// Illustrative per-region hazard shading -- deterministic pseudo-data (stable
// seed) so it reads as structured hazard data rather than noise. The shape
// itself is real (simplified real Ethiopia admin1 boundaries), but the fill
// values are NOT live risk data -- see EthiopiaRiskMap below.
function seededRandom(seed) {
  let s = seed;
  return function next() {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

function colorForValue(v) {
  const stops = [
    [0, [6, 20, 38]],
    [0.35, [40, 70, 60]],
    [0.55, [247, 144, 9]],
    [0.78, [225, 26, 28]],
    [1, [128, 0, 38]],
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (v >= a[0] && v <= b[0]) {
      const t = (v - a[0]) / (b[0] - a[0] || 1);
      const c = a[1].map((ch, idx) => Math.round(ch + (b[1][idx] - ch) * t));
      return `rgb(${c.join(",")})`;
    }
  }
  return "rgb(6,20,38)";
}

// Builds a real, aspect-ratio-preserving equirectangular projection (with a
// cos(latitude) correction) from the real lon/lat bounds of the supplied
// features, so the true shape of Ethiopia is never distorted.
function buildProjection(features, size, padding) {
  let lonMin = Infinity;
  let lonMax = -Infinity;
  let latMin = Infinity;
  let latMax = -Infinity;
  for (const feat of features) {
    const rings =
      feat.geometry.type === "Polygon"
        ? feat.geometry.coordinates
        : feat.geometry.coordinates.flat();
    for (const ring of rings) {
      for (const [lon, lat] of ring) {
        if (lon < lonMin) lonMin = lon;
        if (lon > lonMax) lonMax = lon;
        if (lat < latMin) latMin = lat;
        if (lat > latMax) latMax = lat;
      }
    }
  }
  const avgLatRad = ((latMin + latMax) / 2) * (Math.PI / 180);
  const cosLat = Math.cos(avgLatRad);
  const lonSpan = (lonMax - lonMin) * cosLat;
  const latSpan = latMax - latMin;
  const inner = size - padding * 2;
  const scale = Math.min(inner / lonSpan, inner / latSpan);
  const drawnW = lonSpan * scale;
  const drawnH = latSpan * scale;
  const offsetX = padding + (inner - drawnW) / 2;
  const offsetY = padding + (inner - drawnH) / 2;
  return {
    project(lon, lat) {
      return [
        offsetX + (lon - lonMin) * cosLat * scale,
        offsetY + (latMax - lat) * scale,
      ];
    },
  };
}

function ringToPathD(ring, projection) {
  return (
    ring
      .map(([lon, lat], i) => {
        const [x, y] = projection.project(lon, lat);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ") + " Z"
  );
}

function geometryToPathD(geometry, projection) {
  if (geometry.type === "Polygon") {
    return geometry.coordinates
      .map((ring) => ringToPathD(ring, projection))
      .join(" ");
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates
      .map((poly) =>
        poly.map((ring) => ringToPathD(ring, projection)).join(" "),
      )
      .join(" ");
  }
  return "";
}

// A handful of real drought-corridor regions get a deterministic boost so
// the map reliably reads as "several regions currently elevated," echoing
// the trigger chip -- still illustrative shading, not a live query.
const ETH_MAP_HOT_REGIONS = new Set([
  "somali",
  "afar",
  "south_ethiopia",
  "oromia",
  "sidama",
]);

// Real, simplified Ethiopia admin1 boundaries rendered as SVG, shaded with
// illustrative (not live) per-region hazard values -- replaces the old
// abstract grid with the country's actual shape while keeping the same
// "honestly disclosed as illustrative" approach.
function EthiopiaRiskMap() {
  const regionFeatures = useMemo(
    () =>
      ethiopiaAdmin1.features.filter(
        (feat) => feat.properties.region_id !== "contested",
      ),
    [],
  );
  const contestedFeature = useMemo(
    () =>
      ethiopiaAdmin1.features.find(
        (feat) => feat.properties.region_id === "contested",
      ),
    [],
  );
  const projection = useMemo(
    () =>
      buildProjection(ethiopiaAdmin1.features, ETH_MAP_SIZE, ETH_MAP_PADDING),
    [],
  );
  const regionValues = useMemo(() => {
    const rand = seededRandom(1337);
    const byId = {};
    for (const feat of regionFeatures) {
      let value = 0.2 + rand() * 0.55;
      if (ETH_MAP_HOT_REGIONS.has(feat.properties.region_id)) {
        value = Math.min(1, value + 0.32);
      }
      byId[feat.properties.region_id] = value;
    }
    return byId;
  }, [regionFeatures]);

  return (
    <svg
      className="lp-eth-map"
      viewBox={`0 0 ${ETH_MAP_SIZE} ${ETH_MAP_SIZE}`}
      role="presentation"
      aria-hidden="true"
    >
      {contestedFeature ? (
        <path
          d={geometryToPathD(contestedFeature.geometry, projection)}
          className="lp-eth-region lp-eth-contested"
        />
      ) : null}
      {regionFeatures.map((feat) => {
        const value = regionValues[feat.properties.region_id] ?? 0.3;
        const isHot = value > 0.82;
        return (
          <path
            key={feat.properties.region_id}
            d={geometryToPathD(feat.geometry, projection)}
            className={`lp-eth-region${isHot ? " lp-eth-hot" : ""}`}
            style={{ fill: colorForValue(value) }}
          >
            <title>{feat.properties.name}</title>
          </path>
        );
      })}
    </svg>
  );
}

function LaunchDashboardIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M4 10h12M12 5l5 5-5 5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Landing() {
  return (
    <div className="lp-root">
      <div className="lp-bg-field" />

      <nav className="lp-nav">
        <div className="lp-wrap lp-nav-row">
          <a href="#lp-top" className="lp-brand">
            <svg
              className="lp-brand-mark"
              viewBox="0 0 32 32"
              fill="none"
              aria-hidden="true"
            >
              <circle
                cx="16"
                cy="16"
                r="14.5"
                stroke="#35d4c7"
                strokeWidth="1.4"
                opacity="0.5"
              />
              <path
                d="M16 3v6M16 23v6M3 16h6M23 16h6"
                stroke="#35d4c7"
                strokeWidth="1.4"
                opacity="0.5"
              />
              <circle cx="16" cy="16" r="6.5" fill="#35d4c7" opacity="0.16" />
              <circle
                cx="16"
                cy="16"
                r="6.5"
                stroke="#35d4c7"
                strokeWidth="1.6"
              />
              <circle cx="20" cy="12" r="2.4" fill="#f79009" />
            </svg>
            Forecast2Action <span style={{ color: "#35d4c7" }}>AI</span>
          </a>
          <div className="lp-nav-links">
            <Link to="/platform">Platform</Link>
            <Link to="/how-it-works">How it works</Link>
            <Link to="/data-sources">Data sources</Link>
            <Link to="/docs">Docs</Link>
            <Link to="/track-record">Track record</Link>
            <Link to="/about">About</Link>
          </div>
          <Link to="/dashboard" className="lp-btn lp-btn-ghost lp-btn-small">
            Launch Dashboard
          </Link>
        </div>
      </nav>

      <main id="lp-top">
        <section className="lp-hero">
          <div className="lp-wrap lp-hero-grid">
            <div>
              <span className="lp-eyebrow">
                <span className="lp-dot" /> Live ensemble forecasting · Ethiopia
              </span>
              <h1>
                Forecast2Action AI{" "}
                <em>Hydroclimatic Risk & Early Warning System Dashboard</em>
              </h1>
              <p className="lp-hero-sub">
                Forecast2Action AI fuses seasonal ensemble forecasts, satellite
                exposure data, and AI-generated interpretation into one
                early-warning system turning raw climate signals into ranked,
                actionable alerts for the regions that need them first.
              </p>
              <div className="lp-hero-cta-row">
                <Link to="/dashboard" className="lp-btn lp-btn-primary">
                  Launch Dashboard
                  <LaunchDashboardIcon />
                </Link>
                <a href="#lp-workflow" className="lp-btn lp-btn-ghost">
                  See how it works
                </a>
              </div>
              <div className="lp-hero-highlights">
                <div className="lp-hl-item">
                  <span className="lp-hl-icon">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M3 17l5-6 4 4 6-8 3 3"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  <span className="lp-hl-text">
                    <strong>Predictive modeling</strong>
                    25-member ensemble seasonal forecasts
                  </span>
                </div>
                <div className="lp-hl-item">
                  <span className="lp-hl-icon">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                      />
                      <circle
                        cx="12"
                        cy="12"
                        r="3.2"
                        stroke="currentColor"
                        strokeWidth="1.8"
                      />
                    </svg>
                  </span>
                  <span className="lp-hl-text">
                    <strong>Real-time alerts</strong>
                    Trigger-level SMS &amp; WhatsApp advisories
                  </span>
                </div>
                <div className="lp-hl-item">
                  <span className="lp-hl-icon">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M3 10.5L12 4l9 6.5M5 9.5V19a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V9.5"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  <span className="lp-hl-text">
                    <strong>Hazard tracking</strong>
                    Region → zone → woreda drill-down
                  </span>
                </div>
              </div>
            </div>

            <div
              className="lp-hero-visual"
              role="img"
              aria-label="Stylized map of Ethiopia's real administrative regions with illustrative pulsing high-risk zones, representing the platform's geospatial risk mapping."
            >
              <EthiopiaRiskMap />
              <div className="lp-eth-scan" aria-hidden="true" />
              <span className="lp-hv-frame-label">
                SEASONAL · <b>JJAS 2026</b> · DROUGHT RISK
              </span>
              <div
                className="lp-hv-chip lp-a"
                style={{ top: "19%", left: "10%" }}
              >
                SPI <b>−1.8</b>
                <span className="lp-chip-sub">Severe dry signal</span>
              </div>
              <div
                className="lp-hv-chip lp-b lp-trigger"
                style={{ top: "42%", right: "9%" }}
              >
                Trigger <b>· 5 regions</b>
                <span className="lp-chip-sub">Above threshold</span>
              </div>
              <div
                className="lp-hv-chip lp-c"
                style={{ bottom: "22%", left: "14%" }}
              >
                <b>83.7%</b> hazard prob.
                <span className="lp-chip-sub">Drought · ensemble mean</span>
              </div>
              <div className="lp-hv-legend">
                <span>0.0</span>
                <span className="lp-hv-legend-bar" />
                <span>1.0</span>
              </div>
            </div>
          </div>
        </section>
        {/* 
        <section className="lp-trust" id="lp-trust">
          <div className="lp-wrap lp-trust-row">
            <span className="lp-trust-label">Built on</span>
            <div className="lp-trust-items">
              <span className="lp-trust-item">
                <svg viewBox="0 0 24 24" fill="none">
                  <path
                    d="M4 12a8 8 0 1016 0 8 8 0 00-16 0z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <path
                    d="M4 12h16M12 4a12 12 0 010 16 12 12 0 010-16z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                </svg>
                ECMWF SEAS5 · 25-member ensemble
              </span>
              <span className="lp-trust-item">
                <svg viewBox="0 0 24 24" fill="none">
                  <circle
                    cx="12"
                    cy="9"
                    r="3"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <path
                    d="M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                </svg>
                WorldPop population exposure
              </span>
              <span className="lp-trust-item">
                <svg viewBox="0 0 24 24" fill="none">
                  <path
                    d="M3 20h18M5 20V9l7-5 7 5v11M9 20v-6h6v6"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                  />
                </svg>
                FEWS NET food-security vulnerability
              </span>
              <span className="lp-trust-item">
                <svg viewBox="0 0 24 24" fill="none">
                  <path
                    d="M4 18c1.5-6 4-9 8-9s6.5 3 8 9"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                  <circle
                    cx="12"
                    cy="6"
                    r="2"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                </svg>
                GLW4 livestock density
              </span>
              <span className="lp-trust-item">
                <svg viewBox="0 0 24 24" fill="none">
                  <rect
                    x="3"
                    y="3"
                    width="7"
                    height="7"
                    rx="1"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <rect
                    x="14"
                    y="3"
                    width="7"
                    height="7"
                    rx="1"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <rect
                    x="3"
                    y="14"
                    width="7"
                    height="7"
                    rx="1"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <rect
                    x="14"
                    y="14"
                    width="7"
                    height="7"
                    rx="1"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                </svg>
                0.25° grid resolution
              </span>
            </div>
          </div>
        </section> */}

        <section className="lp-section" id="lp-mission">
          <div className="lp-wrap">
            <div className="lp-mission-head">
              <p className="lp-section-kicker">Why Forecast2Action AI</p>
              <h2>Transforming Complex Risks into Timely Community Action</h2>
              <p>
                Built in response to interconnected regional challenges from
                climate extremes and food insecurity to health and humanitarian
                crises Forecast2Action AI bridges the gap between raw geospatial
                intelligence and frontline decision-making.
              </p>
            </div>
            <div className="lp-feature-grid">
              <div className="lp-feature-card">
                <div className="lp-feature-icon lp-fi-teal">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                    <circle
                      cx="12"
                      cy="12"
                      r="4"
                      stroke="currentColor"
                      strokeWidth="1.8"
                    />
                  </svg>
                </div>
                <h3>Anticipate Complex Hazards</h3>
                <p>
                  Fuses ensemble forecasts, food-security vulnerability (FEWS
                  NET), and livestock/population exposure layers into a single
                  predictive risk model to catch compounding crises before they
                  escalate.
                </p>
              </div>
              <div className="lp-feature-card">
                <div className="lp-feature-icon lp-fi-amber">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M4 4v11a2 2 0 002 2h4l3 3 3-3h2a2 2 0 002-2V4"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M8 9h8M8 12.5h5"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <h3>Reimagine Early Action</h3>
                <p>
                  Replaces static reports with automated, AI-interpreted
                  advisories delivered through accessible communication channels
                  (SMS, WhatsApp, web dashboards) for immediate operational
                  readiness.
                </p>
              </div>
              <div className="lp-feature-card">
                <div className="lp-feature-icon lp-fi-red">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M12 21s-6.5-4.35-9-9.1C1.4 8.02 3.3 4.5 6.9 4.5c1.94 0 3.44 1.06 4.1 2.4a4.6 4.6 0 014.1-2.4c3.6 0 5.5 3.52 3.9 7.4-2.5 4.75-9 9.1-9 9.1z"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <h3>Strengthen Community Resilience</h3>
                <p>
                  Empowers local responders, humanitarian agencies, and regional
                  decision-makers across East Africa with cited, evidence-based
                  alerts to deploy resources where they are needed most.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section" id="lp-features">
          <div className="lp-wrap">
            <div className="lp-section-head">
              <p className="lp-section-kicker">Platform</p>
              <h2>One system, from raw forecast to field-ready advisory</h2>
              <p>
                Three capabilities work together quantitative modeling,
                automated alerting, and spatial ranking so every advisory is
                grounded in real, cited evidence.
              </p>
            </div>
            <div className="lp-feature-grid">
              <div className="lp-feature-card">
                <div className="lp-feature-icon lp-fi-teal">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M3 17l5-6 4 4 6-8 3 3"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M3 21h18"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <h3>Predictive modeling</h3>
                <p>
                  Standardized Precipitation Index, consecutive dry/wet spells,
                  and rainfall percentiles are combined into a probability ×
                  severity hazard index across every ensemble member not a
                  single point estimate.
                </p>
                <div className="lp-feature-tags">
                  <span className="lp-feature-tag">SPI</span>
                  <span className="lp-feature-tag">CDD / CWD</span>
                  <span className="lp-feature-tag">Rx1day / Rx5day</span>
                </div>
              </div>
              <div className="lp-feature-card">
                <div className="lp-feature-icon lp-fi-amber">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M12 8v5"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                    <circle cx="12" cy="16" r="0.9" fill="currentColor" />
                  </svg>
                </div>
                <h3>Real-time alerts</h3>
                <p>
                  Trigger / Warning / Watch / No-alert classification runs
                  automatically against every ranked region, generating SMS- and
                  WhatsApp-ready advisories the moment a threshold is crossed.
                </p>
                <div className="lp-feature-tags">
                  <span className="lp-feature-tag">Trigger thresholds</span>
                  <span className="lp-feature-tag">SMS-ready</span>
                  <span className="lp-feature-tag">WhatsApp-ready</span>
                </div>
              </div>
              <div className="lp-feature-card">
                <div className="lp-feature-icon lp-fi-red">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M3 10.5L12 4l9 6.5M5 9.5V19a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V9.5"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <h3>Regional hazard tracking</h3>
                <p>
                  Every region, zone, and woreda is ranked by real exposure
                  population, cropland, livestock, roads, health facilities and
                  vulnerability, so intervention priority is never guessed from
                  a map alone.
                </p>
                <div className="lp-feature-tags">
                  <span className="lp-feature-tag">Admin 1 / 2 / 3</span>
                  <span className="lp-feature-tag">Exposure-weighted</span>
                  <span className="lp-feature-tag">Priority ranking</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section
          className="lp-section"
          id="lp-workflow"
          style={{ paddingTop: 0 }}
        >
          <div className="lp-wrap">
            <div className="lp-flow">
              <div className="lp-flow-step">
                <span className="lp-flow-num">01</span>
                <h4>Ingest forecast data</h4>
                <p>
                  Seasonal ensemble members and satellite exposure layers are
                  pulled in at 0.25° resolution.
                </p>
              </div>
              <div className="lp-flow-step">
                <span className="lp-flow-num">02</span>
                <h4>Compute hazard indices</h4>
                <p>
                  Deterministic statistics never a guess turn raw indicators
                  into a probability-weighted hazard score.
                </p>
              </div>
              <div className="lp-flow-step">
                <span className="lp-flow-num">03</span>
                <h4>Rank &amp; classify</h4>
                <p>
                  Regions are ranked by real risk and vulnerability, then
                  classified into Trigger / Warning / Watch bands.
                </p>
              </div>
              <div className="lp-flow-step">
                <span className="lp-flow-num">04</span>
                <h4>Deliver the advisory</h4>
                <p>
                  AI-interpreted, citation-backed advisories reach responders as
                  SMS, WhatsApp, or full dashboard reports.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section" style={{ paddingTop: 0 }}>
          <div className="lp-wrap">
            <div className="lp-final-cta" id="lp-get-started">
              <h2>Ready to see the current risk picture?</h2>
              <p>
                Open the live dashboard to explore forecast layers, ranked
                intervention areas, and AI-generated advisories for every
                region.
              </p>
              <Link to="/dashboard" className="lp-btn lp-btn-primary">
                Launch Dashboard
                <LaunchDashboardIcon />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <div className="lp-ribbon">
        {/* <span className="lp-ribbon-tag">An ILRI product</span> */}
        <p>
          "Reimagining the future of early warning and early action for safer,
          more resilient communities across the region."
        </p>
      </div>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer-row">
          <a href="#lp-top" className="lp-brand">
            <svg
              className="lp-brand-mark"
              viewBox="0 0 32 32"
              fill="none"
              aria-hidden="true"
              style={{ width: "22px", height: "22px" }}
            >
              <circle
                cx="16"
                cy="16"
                r="14.5"
                stroke="#35d4c7"
                strokeWidth="1.4"
                opacity="0.5"
              />
              <circle cx="16" cy="16" r="6.5" fill="#35d4c7" opacity="0.16" />
              <circle
                cx="16"
                cy="16"
                r="6.5"
                stroke="#35d4c7"
                strokeWidth="1.6"
              />
            </svg>
            Forecast2Action AI
          </a>
          <Link to="/contact" className="lp-footer-contact-link">
            Contact us
          </Link>
          <span className="lp-footer-meta">
            CLIMATE RISK &amp; EARLY WARNING
          </span>
        </div>
      </footer>
    </div>
  );
}

export default Landing;
