import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";

function Platform() {
  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> Platform
          </span>
          <h1>Five real capabilities</h1>
          <p className="lp-hero-sub">
            Forecast2Action AI isn't a single model it's a pipeline of
            deterministic statistics, a real formula-driven risk score, and AI
            interpretation layered on top, in that order. Nothing that can be
            calculated is left for an AI model to guess.
          </p>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Predictive modeling</h2>
          <div className="lp-prose">
            <p>
              Every region's hazard signal is built from a 25-member seasonal
              ensemble (ECMWF SEAS5) plus CHIRPS observational rainfall, at
              0.25° spatial resolution. Seven real indicators feed the model:
              Rainfall Total, SPI (SPI-3, McKee et al. 1993), CDD, CWD, Rx1day,
              Rx5day, and rainfall percentile each standardized into a 0–1 dry
              or wet score and combined into a per-realization hazard index.
            </p>
            <p>
              The ensemble dimension is preserved through that step, not
              collapsed early: <strong>Probability</strong> is the share of
              realizations that cross the hazard threshold, and{" "}
              <strong>Severity</strong> is the average intensity among those
              that do. Only then are they recombined{" "}
              <code style={{ color: "var(--lp-teal)" }}>
                Hazard = Probability × Severity
              </code>
              so a rare-but-extreme signal and a common-but-mild one are never
              confused with each other.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Real-time alerts</h2>
          <div className="lp-prose">
            <p>
              Every ranked region is classified into one of four operational
              alert levels <strong>Trigger</strong> (≥ 0.80),{" "}
              <strong>Warning</strong> (≥ 0.60), <strong>Watch</strong> (≥
              0.35), or <strong>No alert</strong> against the same
              priority-score scale used across the whole platform, so the table,
              the map, and every generated advisory always agree on what a given
              area's status means.
            </p>
            <p>
              Crossing a threshold automatically generates a ready-to-send SMS
              (real GSM-7 segment counting) and a WhatsApp-formatted advisory
              the same underlying evidence reformatted for each channel, not two
              separately-written messages.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Regional hazard tracking</h2>
          <div className="lp-prose">
            <p>
              Rankings drill down through region → zone → woreda (admin 1/2/3),
              weighted by real exposure population (WorldPop), cropland (ESA
              WorldCover), livestock (FAO GLW4), built-up area, roads, and
              health facilities and by vulnerability built from real sensitivity
              and adaptive-capacity indicators, not a single opaque score.
            </p>
            <p>
              Priority ranking itself is a deterministic formula (weighted mean,
              peak severity, and share of area above threshold), so the "top 5"
              list a responder sees is reproducible and auditable, not an LLM's
              impression of the map.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>AI-interpreted advisories</h2>
          <div className="lp-prose">
            <p>
              This is context engineering in practice: an evidence-grounded LLM
              pipeline with RAG-based action guidance, not a single freeform
              prompt.
            </p>
            <p>
              A three-stage pipeline turns the numbers into language: Stage 1
              interprets the raw evidence, Stage 2 synthesizes an integrated
              risk narrative using a stronger model tier, and Stage 3 translates
              that into farmer, agro-pastoral, and humanitarian advisories each
              stage seeing only what it needs to do its job, never allowed to
              invent a priority ranking the statistics didn't produce.
            </p>
            <p>
              Every generated report is checked against the same evidence it was
              built from invented place names, fabricated statistics, and
              forecast-vs-observed confusion are flagged automatically, not just
              trusted.
            </p>
            <p>
              The report generator's provider is selectable per run{" "}
              <strong>Automatic</strong> (Gemini first, then OpenRouter/OpenAI
              on failure), <strong>Google Gemini</strong> (Gemini Flash-Lite,
              Gemini 3.5 Flash-Lite, Gemini Flash), or{" "}
              <strong>OpenRouter</strong> (Gemini 2.5 Flash-Lite, GPT-5.6 Luna,
              Llama 4 Scout, GPT-5.6 Terra, GLM-4.6V) each option confirmed via
              live testing to handle the full comprehensive map payload sent
              with every report. The dashboard chat assistant runs its own
              separate, faster provider chain (Gemini's lite tier, then OpenAI,
              then OpenRouter).
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Grounded assistant, tracking &amp; reporting</h2>
          <div className="lp-prose">
            <p>
              A streaming dashboard chat assistant answers follow-up questions,
              such as area-level indicator values, cross-period comparisons, or
              methodology, against the same real evidence and generated report,
              never a freeform re-query of the model. Responses are tuned to
              who's asking (Disaster manager, Extension officer, NGO planner, or
              General) and can pull in RAG-retrieved action guidance when the
              question calls for it.
            </p>
            <p>
              An action implementation tracker turns each area's recommended
              actions into real, trackable tasks (status, approval, CSV export),
              and a one-click bulletin export packages the full generated
              advisory alongside all 7 climate-indicator, 8 risk-layer, and 2
              priority-area maps, each with its own real colorbar/legend and
              region-boundary overlay, into a single self-contained HTML file
              built entirely from data already on screen.
            </p>
          </div>
        </div>
      </section>
    </SubPageLayout>
  );
}

export default Platform;
