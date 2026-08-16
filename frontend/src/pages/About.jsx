import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";

function About() {
  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> About
          </span>
          <h1>Why Forecast2Action AI exists</h1>
          <p className="lp-hero-sub">
            Built in response to interconnected regional challenges from climate
            extremes and food insecurity to health and humanitarian crises
            Forecast2Action AI bridges the gap between raw geospatial
            intelligence and frontline decision-making.
          </p>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>The problem</h2>
          <div className="lp-prose">
            <p>
              Across East Africa, drought and excess-rainfall risk rarely arrive
              as a single, isolated hazard they compound with food insecurity,
              health system strain, and displacement. The forecast data to
              anticipate this already exists, but it usually stays locked in raw
              ensemble grids and technical formats that a district-level
              responder has no practical way to act on before conditions worsen.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Our approach</h2>
          <div className="lp-prose">
            <p>
              Rather than asking an AI model to interpret raw maps directly,
              Forecast2Action AI computes everything that can be computed hazard
              indices, exposure, vulnerability, priority ranking
              deterministically first, from named, real datasets. AI
              interpretation is layered on top only at the last step, to
              translate already-validated evidence into plain-language
              advisories, and every generated report is cross-checked against
              that same evidence before it reaches anyone.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <div className="lp-callout">
            <h4>Checked against real history</h4>
            <p>
              Every SPI drought threshold this platform uses is checked
              against real CHIRPS rainfall (1997-2025) compared to real
              GLIDE-recorded drought events for Ethiopia, region by region
              not just asserted.{" "}
              <Link to="/track-record" style={{ color: "var(--lp-teal)" }}>
                See the real numbers, honest caveats included →
              </Link>
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Who it's for</h2>
          <div className="lp-prose">
            <p>
              Local responders, humanitarian agencies, and regional
              decision-makers who need to know not just that risk exists
              somewhere in the country, but exactly which regions, zones, and
              woredas need attention first and why, in terms they can verify and
              act on.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Technology stack</h2>
          <p className="lp-prose" style={{ marginBottom: 18 }}>
            The real, currently-installed dependencies this platform runs on not
            an aspirational list.
          </p>
          <div className="lp-feature-grid lp-tech-grid">
            <div className="lp-feature-card">
              <h3 style={{ fontSize: "1.02rem" }}>Frontend</h3>
              <ul className="lp-tool-list">
                <li>
                  <span className="lp-tool-name">React 19</span>
                  <span className="lp-tool-desc">
                    The UI library the dashboard and every page on this site are
                    built with.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">React Router 7</span>
                  <span className="lp-tool-desc">
                    Client-side routing between pages Home, Dashboard, Docs, and
                    every page you're navigating right now.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">Vite</span>
                  <span className="lp-tool-desc">
                    Dev server and production build tool.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">Leaflet / react-leaflet</span>
                  <span className="lp-tool-desc">
                    Renders the interactive forecast, hazard/risk, and
                    priority-area maps.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">Recharts</span>
                  <span className="lp-tool-desc">
                    Chart rendering elsewhere in the dashboard.
                  </span>
                </li>
              </ul>
            </div>
            <div className="lp-feature-card">
              <h3 style={{ fontSize: "1.02rem" }}>Backend &amp; API</h3>
              <ul className="lp-tool-list">
                <li>
                  <span className="lp-tool-name">Python</span>
                  <span className="lp-tool-desc">The backend language.</span>
                </li>
                <li>
                  <span className="lp-tool-name">FastAPI</span>
                  <span className="lp-tool-desc">
                    Serves every <code>/api</code> endpoint the frontend calls.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">Uvicorn</span>
                  <span className="lp-tool-desc">
                    The ASGI server that actually runs FastAPI.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">Pydantic</span>
                  <span className="lp-tool-desc">
                    Validates request/response data and schemas.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">pytest</span>
                  <span className="lp-tool-desc">
                    Runs the backend's automated test suite.
                  </span>
                </li>
              </ul>
            </div>
            <div className="lp-feature-card">
              <h3 style={{ fontSize: "1.02rem" }}>
                Geospatial &amp; data processing
              </h3>
              <ul className="lp-tool-list">
                <li>
                  <span className="lp-tool-name">rasterio</span>
                  <span className="lp-tool-desc">
                    Reads and writes the GeoTIFF hazard, exposure, and
                    vulnerability raster layers.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">rioxarray / xarray</span>
                  <span className="lp-tool-desc">
                    Labeled multi-dimensional arrays for the ensemble forecast
                    data.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">netCDF4 / h5netcdf</span>
                  <span className="lp-tool-desc">
                    Reads the raw ensemble forecast (<code>.nc</code>) files.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">geopandas</span>
                  <span className="lp-tool-desc">
                    Handles region/zone/woreda administrative boundary geometry.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">NumPy / pandas / SciPy</span>
                  <span className="lp-tool-desc">
                    Numerical computation, tabular data, and statistics e.g. the
                    gamma-distribution fit behind SPI.
                  </span>
                </li>
              </ul>
            </div>
            <div className="lp-feature-card">
              <h3 style={{ fontSize: "1.02rem" }}>AI &amp; language models</h3>
              <p>
                A context-engineered, evidence-grounded LLM pipeline with
                RAG-based action guidance not a single freeform prompt.
              </p>
              <ul className="lp-tool-list">
                <li>
                  <span className="lp-tool-name">Google Gemini</span>
                  <span className="lp-tool-desc">
                    Primary AI provider for report interpretation and advisory
                    generation.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">OpenRouter</span>
                  <span className="lp-tool-desc">
                    Fallback multi-model routing provider.
                  </span>
                </li>
                <li>
                  <span className="lp-tool-name">OpenAI-compatible API</span>
                  <span className="lp-tool-desc">
                    Shared client interface used to call all three providers
                    above.
                  </span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>An ILRI product</h2>
          <div className="lp-callout">
            <h4>Developed at ILRI</h4>
            <p>
              Forecast2Action AI is developed at the International Livestock
              Research Institute (ILRI). The forecast, exposure, and
              vulnerability data pipelines are real (see{" "}
              <Link to="/data-sources" style={{ color: "var(--lp-teal)" }}>
                Data sources
              </Link>
              ), computed deterministically from named, real datasets before any
              AI interpretation is layered on top.
            </p>
          </div>
        </div>
      </section>
    </SubPageLayout>
  );
}

export default About;
