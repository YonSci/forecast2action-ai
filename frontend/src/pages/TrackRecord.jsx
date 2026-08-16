import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";
import { apiUrl } from "../config.js";
import ethiopiaAdmin1 from "../data/ethiopiaAdmin1.json";

const THRESHOLD_ORDER = ["moderately_dry", "severely_dry", "extremely_dry"];
const THRESHOLD_LABELS = {
  moderately_dry: "Moderately dry",
  severely_dry: "Severely dry",
  extremely_dry: "Extremely dry",
};
const INDICATOR_ORDER = ["spi", "rainfall_total", "rainfall_percentile"];

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(value))
    return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function formatValue(value) {
  if (value === null || value === undefined) return "N/A";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function orderedThresholds(analysis) {
  const byLabel = Object.fromEntries(
    (analysis?.thresholds || []).map((t) => [t.threshold_label, t]),
  );
  return THRESHOLD_ORDER.map((label) => byLabel[label]).filter(Boolean);
}

function thresholdAt(analysis, label) {
  return (analysis?.thresholds || []).find((t) => t.threshold_label === label);
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
            <th>Threshold value</th>
            <th>Hit rate (event years below)</th>
            <th>False-alarm rate (no-event below)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.threshold_label}>
              <td>
                {THRESHOLD_LABELS[row.threshold_label] || row.threshold_label}
              </td>
              <td>{row.threshold_value}</td>
              <td className="lp-td-strong">{formatPct(row.hit_rate)}</td>
              <td>{formatPct(row.false_alarm_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IndicatorComparisonTable({ indicators }) {
  if (!indicators) return null;
  return (
    <div className="lp-data-table-wrap">
      <table className="lp-data-table">
        <thead>
          <tr>
            <th>Indicator</th>
            <th>Mean value, event years</th>
            <th>Mean value, no-event years</th>
            <th>Hit rate (moderately dry)</th>
            <th>False-alarm rate (moderately dry)</th>
          </tr>
        </thead>
        <tbody>
          {INDICATOR_ORDER.map((key) => {
            const analysis = indicators[key];
            if (!analysis) return null;
            const moderately = thresholdAt(analysis, "moderately_dry");
            return (
              <tr key={key}>
                <td className="lp-td-strong">{analysis.label}</td>
                <td>{formatValue(analysis.mean_value_event)}</td>
                <td>{formatValue(analysis.mean_value_no_event)}</td>
                <td className="lp-td-strong">
                  {formatPct(moderately?.hit_rate)}
                </td>
                <td>{formatPct(moderately?.false_alarm_rate)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const MAP_SIZE = 520;
const MAP_PADDING = 20;

function buildEthMapProjection(features, size, padding) {
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

function ethRingToPathD(ring, projection) {
  return (
    ring
      .map(([lon, lat], i) => {
        const [x, y] = projection.project(lon, lat);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ") + " Z"
  );
}

function ethGeometryToPathD(geometry, projection) {
  if (geometry.type === "Polygon") {
    return geometry.coordinates
      .map((ring) => ethRingToPathD(ring, projection))
      .join(" ");
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates
      .map((poly) =>
        poly.map((ring) => ethRingToPathD(ring, projection)).join(" "),
      )
      .join(" ");
  }
  return "";
}

// Real teal -> amber -> red scale (matches this site's own accent palette)
// driven by each region's real historical drought-event count -- not
// illustrative, unlike the landing page's stylized hero map.
function eventCountColor(count, maxCount) {
  if (!count) return "rgba(148,178,219,0.10)";
  const t = maxCount > 0 ? count / maxCount : 0;
  const stops = [
    [0, [53, 212, 199]],
    [0.5, [247, 144, 9]],
    [1, [239, 74, 61]],
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a0, aColor] = stops[i];
    const [b0, bColor] = stops[i + 1];
    if (t >= a0 && t <= b0) {
      const localT = (t - a0) / (b0 - a0 || 1);
      const c = aColor.map((ch, idx) =>
        Math.round(ch + (bColor[idx] - ch) * localT),
      );
      return `rgb(${c.join(",")})`;
    }
  }
  return "rgb(239,74,61)";
}

function DroughtEventMap({ regionSummary }) {
  const countByRegion = useMemo(() => {
    const map = {};
    for (const item of regionSummary || []) {
      map[item.region] = item;
    }
    return map;
  }, [regionSummary]);

  const maxCount = Math.max(
    1,
    ...(regionSummary || []).map((item) => item.event_count),
  );
  const projection = useMemo(
    () => buildEthMapProjection(ethiopiaAdmin1.features, MAP_SIZE, MAP_PADDING),
    [],
  );

  return (
    <svg
      viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
      role="img"
      aria-label="Map of real historical drought event counts by region"
      style={{
        width: "100%",
        maxWidth: 420,
        display: "block",
        margin: "0 auto",
      }}
    >
      {ethiopiaAdmin1.features.map((feat) => {
        const regionName = feat.properties.name;
        const summary = countByRegion[regionName];
        const count = summary?.event_count || 0;
        return (
          <path
            key={feat.properties.region_id}
            d={ethGeometryToPathD(feat.geometry, projection)}
            fill={eventCountColor(count, maxCount)}
            stroke="rgba(148,178,219,0.35)"
            strokeWidth="1"
          >
            <title>
              {regionName}: {count} real drought event{count === 1 ? "" : "s"}
              {summary ? ` (${summary.years.join(", ")})` : ""}
            </title>
          </path>
        );
      })}
    </svg>
  );
}

function formatAffected(value) {
  if (!value) return "0";
  return value.toLocaleString();
}

function formatCoord(value) {
  return value === null || value === undefined ? "N/A" : value.toFixed(3);
}

const MONTH_NAMES = [
  "",
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// JJAS = this app's real forecast window -- flagged here so it's obvious
// at a glance whether a real event's registered month falls inside or
// outside the season this whole page's analysis actually tests.
function formatMonth(month) {
  if (!month || month < 1 || month > 12) return "Unknown";
  const inSeason = month >= 6 && month <= 9;
  return `${MONTH_NAMES[month]}${inSeason ? " (JJAS)" : ""}`;
}

function formatDay(day) {
  return day ? String(day) : "Unknown";
}

function formatPercentile(value) {
  return value === null || value === undefined ? "N/A" : value.toFixed(1);
}

// Sortable event-table columns. "string" columns sort with localeCompare;
// everything else sorts numerically, with real nulls (e.g. no baseline for
// the 2026 event, or day=0 meaning GLIDE only reported month/year
// precision) always sorted to the end regardless of direction, so an
// unknown value never gets mistaken for a real 0/low value.
const EVENT_COLUMNS = [
  { key: "glidenumber", label: "GLIDE ID", type: "string" },
  { key: "region", label: "Region", type: "string" },
  { key: "year", label: "Year", type: "number" },
  { key: "month", label: "Month", type: "number" },
  { key: "day", label: "Day", type: "number" },
  { key: "latitude", label: "Latitude", type: "number" },
  { key: "longitude", label: "Longitude", type: "number" },
  { key: "affected", label: "Affected", type: "number" },
  { key: "spi", label: "SPI", type: "number" },
  { key: "rainfall_total_anomaly", label: "Rainfall Total anomaly", type: "number" },
  { key: "rainfall_percentile", label: "Rainfall Percentile", type: "number" },
];

function sortEvents(events, sortKey, sortDir) {
  const column = EVENT_COLUMNS.find((c) => c.key === sortKey);
  const dirMultiplier = sortDir === "asc" ? 1 : -1;
  return [...events].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    const aMissing = av === null || av === undefined || (sortKey === "day" && !av);
    const bMissing = bv === null || bv === undefined || (sortKey === "day" && !bv);
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    if (column?.type === "string") return av.localeCompare(bv) * dirMultiplier;
    return (av - bv) * dirMultiplier;
  });
}

function SortableEventTable({ events }) {
  const [sortKey, setSortKey] = useState("year");
  const [sortDir, setSortDir] = useState("asc");

  const sortedEvents = useMemo(
    () => sortEvents(events, sortKey, sortDir),
    [events, sortKey, sortDir],
  );

  function handleSort(key) {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <div className="lp-data-table-wrap">
      <table className="lp-data-table">
        <thead>
          <tr>
            {EVENT_COLUMNS.map((column) => (
              <th
                key={column.key}
                onClick={() => handleSort(column.key)}
                style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
                aria-sort={
                  sortKey === column.key ? (sortDir === "asc" ? "ascending" : "descending") : "none"
                }
              >
                {column.label}
                {sortKey === column.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedEvents.map((event) => (
            <tr key={`${event.glidenumber}-${event.region}`}>
              <td>
                <code>{event.glidenumber}</code>
              </td>
              <td className="lp-td-strong">{event.region}</td>
              <td>{event.year}</td>
              <td>{formatMonth(event.month)}</td>
              <td>{formatDay(event.day)}</td>
              <td>{formatCoord(event.latitude)}</td>
              <td>{formatCoord(event.longitude)}</td>
              <td>{formatAffected(event.affected)}</td>
              <td>{formatValue(event.spi)}</td>
              <td>{formatValue(event.rainfall_total_anomaly)}</td>
              <td>{formatPercentile(event.rainfall_percentile)}</td>
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
        const response = await fetch(
          apiUrl("/api/validation/historical-skill"),
        );
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

  const indicators = data?.indicators;
  const spi = indicators?.spi;
  const events = Array.isArray(data?.events) ? data.events : [];
  const regionSummary = Array.isArray(data?.region_summary)
    ? data.region_summary
    : [];
  const eventCount =
    data?.data_provenance?.drought_events_matched ?? events.length;

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
            GLIDE drought events for Ethiopia, a real diagnostic against real
            history, with the honest caveats included. Scoped to drought only
            for this first pass; flood/flash-flood validation needs a different
            real indicator and hasn't been attempted yet.
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
                For every real region-year where a real GLIDE drought event was
                registered, was that region's real JJAS (June–September)
                seasonal rainfall actually anomalously dry, using a real
                gamma-fit SPI? Droughts are accumulation phenomena, so a
                seasonal total is a more honest test than any single month.
              </p>
              <div className="lp-feature-grid" style={{ marginBottom: 18 }}>
                <div className="lp-feature-card">
                  <h3 style={{ fontSize: "1.02rem" }}>Real event years</h3>
                  <p
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 800,
                      margin: "8px 0 4px",
                      color: "var(--lp-teal)",
                    }}
                  >
                    {spi?.event_years ?? "N/A"}
                  </p>
                  <p style={{ margin: 0, color: "var(--lp-muted)" }}>
                    region-years with a real registered drought event
                  </p>
                </div>
                <div className="lp-feature-card">
                  <h3 style={{ fontSize: "1.02rem" }}>Mean SPI, event years</h3>
                  <p
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 800,
                      margin: "8px 0 4px",
                      color: "var(--lp-red, #ef4a3d)",
                    }}
                  >
                    {formatValue(spi?.mean_value_event)}
                  </p>
                  <p style={{ margin: 0, color: "var(--lp-muted)" }}>
                    vs {formatValue(spi?.mean_value_no_event)} for no-event
                    years
                  </p>
                </div>
                <div className="lp-feature-card">
                  <h3 style={{ fontSize: "1.02rem" }}>
                    Real drought events matched
                  </h3>
                  <p
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 800,
                      margin: "8px 0 4px",
                      color: "var(--lp-teal)",
                    }}
                  >
                    {eventCount}
                  </p>
                  <p style={{ margin: 0, color: "var(--lp-muted)" }}>
                    GLIDE events, 1997–2025, geocoded to a real admin1 region
                  </p>
                </div>
              </div>
              <p
                className="lp-prose"
                style={{ marginBottom: 10, fontWeight: 700 }}
              >
                Real SPI hit rate vs. false-alarm rate, this app's own real SPI
                classification bands:
              </p>
              <ThresholdTable analysis={spi} />
            </div>
          </section>

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>Which real indicator predicts best?</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                This app offers 7 real climate indicators. Three can be tested
                against real history using data already downloaded: Rainfall
                Total, SPI, and Rainfall Percentile. CDD, CWD, Rx1day, and
                Rx5day need real daily rainfall this repo hasn't downloaded yet,
                so they're not included here.
              </p>
              <IndicatorComparisonTable indicators={indicators} />
              <p
                className="lp-prose"
                style={{ marginTop: 14, fontSize: "0.9rem" }}
              >
                Real SPI and Rainfall Total perform almost identically at every
                threshold: a real gamma-distribution correction barely changes
                the classification at this sample size. Rainfall Percentile
                trails both on hit rate at the moderately-dry threshold.
              </p>
            </div>
          </section>

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>Real drought events, by region</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                Where the real matched GLIDE drought events actually happened,
                not a national average, but the real regional concentration.
              </p>
              <DroughtEventMap regionSummary={regionSummary} />
              <div className="lp-data-table-wrap" style={{ marginTop: 22 }}>
                <table className="lp-data-table">
                  <thead>
                    <tr>
                      <th>Region</th>
                      <th>Real events</th>
                      <th>Years</th>
                    </tr>
                  </thead>
                  <tbody>
                    {regionSummary.map((item) => (
                      <tr key={item.region}>
                        <td className="lp-td-strong">{item.region}</td>
                        <td>{item.event_count}</td>
                        <td>{item.years.join(", ")}</td>
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
              <h2>Every real event, by name</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                Not a summary statistic in isolation: each real GLIDE drought
                event this analysis matched, with its real reported date (month
                flagged when it falls inside JJAS, this app's real forecast
                season) and location, its real GLIDE "affected" figure (the only
                real severity signal GLIDE captures for drought most events
                report 0 killed, injured, or homeless), and its region's real
                value for all 3 comparable indicators that year. Click a
                column heading to sort by it.
              </p>
              <SortableEventTable events={events} />
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
                  . It's a real, honest finding a directionally consistent but
                  statistically limited signal, computed once from real data and
                  re-runnable, not a validated forecast-skill score and not
                  evidence for changing production thresholds on its own.
                </p>
              </div>
            </div>
          </section>

          <section className="lp-article-section">
            <div className="lp-wrap">
              {/* <p className="lp-meta-line">
                Rainfall source: {data.data_provenance?.rainfall_source} · Event source:{" "}
                {data.data_provenance?.event_source} · Baseline years:{" "}
                {data.data_provenance?.baseline_years} · Generated{" "}
                {data.generated_at ? new Date(data.generated_at).toISOString().slice(0, 10) : "N/A"}
              </p> */}
            </div>
          </section>
        </>
      )}
    </SubPageLayout>
  );
}

export default TrackRecord;
