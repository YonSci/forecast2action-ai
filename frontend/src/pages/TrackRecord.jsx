import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";
import { apiUrl } from "../config.js";

const THRESHOLD_ORDER = ["moderately_dry", "severely_dry", "extremely_dry"];
const THRESHOLD_LABELS = {
  moderately_dry: "Moderately dry (SPI ≤ −1.0)",
  severely_dry: "Severely dry (SPI ≤ −1.5)",
  extremely_dry: "Extremely dry (SPI ≤ −2.0)",
};

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function formatAnomaly(value) {
  if (value === null || value === undefined) return "N/A";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function orderedThresholds(analysis) {
  const byLabel = Object.fromEntries((analysis?.thresholds || []).map((t) => [t.threshold_label, t]));
  return THRESHOLD_ORDER.map((label) => byLabel[label]).filter(Boolean);
}

function ThresholdTable({ analysis }) {
  const rows = orderedThresholds(analysis);
  if (rows.length === 0) return null;
  return (
    <div className="lp-data-table-wrap">
      <table className="lp-data-table">
        <thead>
          <tr>
            <th>Threshold</th>
            <th>Hit rate (event years below threshold)</th>
            <th>False-alarm rate (no-event below threshold)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.threshold_label}>
              <td>{THRESHOLD_LABELS[row.threshold_label] || row.threshold_label}</td>
              <td className="lp-td-strong">{formatPct(row.hit_rate)}</td>
              <td>{formatPct(row.false_alarm_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrackRecord() {
  const [data, setData] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(apiUrl("/api/validation/historical-skill"));
        if (!response.ok) {
          throw new Error(`Request failed: ${response.status}`);
        }
        const json = await response.json();
        if (!cancelled) setData(json);
      } catch {
        if (!cancelled) {
          setErrorMessage(
            "Could not load historical validation results. The backend may still be starting up (Render free tier) try refreshing in a moment.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const seasonal = data?.seasonal_analysis;
  const monthly = data?.monthly_analysis;
  const events = Array.isArray(data?.events) ? data.events : [];
  const eventCount = data?.data_provenance?.drought_events_matched ?? events.length;

  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> Track record
          </span>
          <h1>Does it actually work?</h1>
          <p className="lp-hero-sub">
            Real historical CHIRPS rainfall (1997–2025) compared against real
            GLIDE drought events for Ethiopia, admin1 by admin1 not a
            marketing claim, a real diagnostic against real history, with the
            honest caveats included. Scoped to drought only for this first
            pass; flood/flash-flood validation needs a different real
            indicator and hasn't been attempted yet.
          </p>
        </div>
      </section>

      {loading && (
        <section className="lp-article-section">
          <div className="lp-wrap">
            <div className="lp-callout">Loading real validation results...</div>
          </div>
        </section>
      )}

      {errorMessage && (
        <section className="lp-article-section">
          <div className="lp-wrap">
            <div className="lp-callout lp-callout-red">{errorMessage}</div>
          </div>
        </section>
      )}

      {data && (
        <>
          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>The headline signal</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                For every real region-year where a real GLIDE drought event
                was registered, was that region's real JJAS (June–September)
                seasonal rainfall actually anomalously dry droughts are
                accumulation phenomena, so a seasonal total is a more honest
                test than any single month.
              </p>
              <div className="lp-feature-grid" style={{ marginBottom: 18 }}>
                <div className="lp-feature-card">
                  <h3 style={{ fontSize: "1.02rem" }}>Real event years</h3>
                  <p style={{ fontSize: "1.8rem", fontWeight: 800, margin: "8px 0 4px", color: "var(--lp-teal)" }}>
                    {seasonal?.event_years ?? "N/A"}
                  </p>
                  <p style={{ margin: 0, color: "var(--lp-muted)" }}>
                    region-years with a real registered drought event
                  </p>
                </div>
                <div className="lp-feature-card">
                  <h3 style={{ fontSize: "1.02rem" }}>Mean anomaly, event years</h3>
                  <p style={{ fontSize: "1.8rem", fontWeight: 800, margin: "8px 0 4px", color: "var(--lp-red, #ef4a3d)" }}>
                    {formatAnomaly(seasonal?.mean_anomaly_event)}
                  </p>
                  <p style={{ margin: 0, color: "var(--lp-muted)" }}>
                    vs {formatAnomaly(seasonal?.mean_anomaly_no_event)} for no-event years
                  </p>
                </div>
                <div className="lp-feature-card">
                  <h3 style={{ fontSize: "1.02rem" }}>Real drought events matched</h3>
                  <p style={{ fontSize: "1.8rem", fontWeight: 800, margin: "8px 0 4px", color: "var(--lp-teal)" }}>
                    {eventCount}
                  </p>
                  <p style={{ margin: 0, color: "var(--lp-muted)" }}>
                    GLIDE events, 1997–2025, geocoded to a real admin1 region
                  </p>
                </div>
              </div>
              <p className="lp-prose" style={{ marginBottom: 10, fontWeight: 700 }}>
                Hit rate vs. false-alarm rate at this app's own real SPI thresholds:
              </p>
              <ThresholdTable analysis={seasonal} />
            </div>
          </section>

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>Single-month comparison</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                The same real comparison at single-month resolution a
                weaker, secondary check, since a single registered month
                doesn't capture a drought's real accumulation.
              </p>
              <div className="lp-meta-line" style={{ marginBottom: 12 }}>
                Real event months: <strong>{monthly?.event_months ?? "N/A"}</strong> · Mean
                anomaly: <strong>{formatAnomaly(monthly?.mean_anomaly_event)}</strong> vs{" "}
                <strong>{formatAnomaly(monthly?.mean_anomaly_no_event)}</strong> for no-event months
              </div>
              <ThresholdTable analysis={monthly} />
            </div>
          </section>

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>Every real event, by name</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                Not a summary statistic in isolation each real GLIDE drought
                event this analysis matched, with whether its region's real
                seasonal rainfall actually crossed the moderately-dry
                threshold that year.
              </p>
              <div className="lp-data-table-wrap">
                <table className="lp-data-table">
                  <thead>
                    <tr>
                      <th>GLIDE ID</th>
                      <th>Region</th>
                      <th>Year</th>
                      <th>Seasonal anomaly</th>
                      <th>Crossed moderately-dry?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => (
                      <tr key={`${event.glidenumber}-${event.region}`}>
                        <td>
                          <code>{event.glidenumber}</code>
                        </td>
                        <td className="lp-td-strong">{event.region}</td>
                        <td>{event.year}</td>
                        <td>{formatAnomaly(event.seasonal_anomaly)}</td>
                        <td>
                          {event.seasonal_hit_moderately_dry === null ||
                          event.seasonal_hit_moderately_dry === undefined
                            ? "No baseline"
                            : event.seasonal_hit_moderately_dry
                              ? "Yes"
                              : "No"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>What this isn't</h2>
              <div className="lp-prose">
                <p>{data.methodology?.summary}</p>
                <p>{data.methodology?.caveat}</p>
                <p>
                  This diagnostic does not change this app's live{" "}
                  <Link to="/docs" style={{ color: "var(--lp-teal)" }}>
                    SPI classification thresholds
                  </Link>
                  . It's a real, honest finding a directionally consistent
                  but statistically limited signal, computed once from real
                  data and re-runnable, not a validated forecast-skill score
                  and not evidence for changing production thresholds on its
                  own.
                </p>
              </div>
            </div>
          </section>

          <section className="lp-article-section">
            <div className="lp-wrap">
              <p className="lp-meta-line">
                Rainfall source: {data.data_provenance?.rainfall_source} · Event source:{" "}
                {data.data_provenance?.event_source} · Baseline years:{" "}
                {data.data_provenance?.baseline_years} · Generated{" "}
                {data.generated_at ? new Date(data.generated_at).toISOString().slice(0, 10) : "N/A"}
              </p>
            </div>
          </section>
        </>
      )}
    </SubPageLayout>
  );
}

export default TrackRecord;
