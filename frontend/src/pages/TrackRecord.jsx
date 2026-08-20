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

function formatAuc(value) {
  if (value === null || value === undefined || Number.isNaN(value))
    return "N/A";
  return value.toFixed(3);
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
            <th>AUC</th>
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
                <td className="lp-td-strong">{formatAuc(analysis.auc)}</td>
                <td>{formatPct(moderately?.hit_rate)}</td>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Same real moderately-dry threshold values as INDICATOR_THRESHOLDS in
// drought_threshold_calibration.py -- carrying the same underlying
// probability as this app's own SPI_CATEGORY_BANDS, not an arbitrary cutoff.
const MODERATELY_DRY_THRESHOLDS = {
  spi: -1.0,
  rainfall_total_anomaly: -1.0,
  rainfall_percentile: 15.87,
};

function isHit(value, indicatorKey) {
  if (value === null || value === undefined) return null;
  return value <= MODERATELY_DRY_THRESHOLDS[indicatorKey];
}

function HitBadge({ value, indicatorKey, formatter }) {
  const hit = isHit(value, indicatorKey);
  if (hit === null) {
    return <span style={{ color: "var(--lp-muted)" }}>N/A</span>;
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          color: hit ? "var(--lp-red, #ef4a3d)" : "var(--lp-muted)",
          fontWeight: hit ? 800 : 400,
        }}
      >
        {formatter(value)}
      </span>
      <span
        style={{
          fontSize: "0.6rem",
          padding: "1px 6px",
          borderRadius: 999,
          border: `1px solid ${hit ? "var(--lp-red, #ef4a3d)" : "var(--lp-line)"}`,
          color: hit ? "var(--lp-red, #ef4a3d)" : "var(--lp-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.03em",
          whiteSpace: "nowrap",
        }}
      >
        {hit ? "Hit" : "Miss"}
      </span>
    </span>
  );
}

// Real events that share the exact same GLIDE-reported coordinate (see
// the "generic centroid" finding below) would otherwise render as one
// dot hiding another -- this spreads coincident points into a small real
// circle around their shared location so every real event stays visible
// and independently hoverable, purely a display offset, never altering
// the real coordinate used for any computed indicator value.
function jitterCoincidentPoints(points) {
  const groups = new Map();
  for (const p of points) {
    const key = `${p.latitude.toFixed(3)},${p.longitude.toFixed(3)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  const result = [];
  for (const group of groups.values()) {
    const n = group.length;
    group.forEach((p, i) => {
      const angle = (2 * Math.PI * i) / n;
      const r = n > 1 ? 9 : 0;
      result.push({ ...p, dx: r * Math.cos(angle), dy: r * Math.sin(angle) });
    });
  }
  return result;
}

function EventPointMap({ events }) {
  const projection = useMemo(
    () => buildEthMapProjection(ethiopiaAdmin1.features, MAP_SIZE, MAP_PADDING),
    [],
  );
  const points = useMemo(
    () =>
      jitterCoincidentPoints(
        (events || []).filter(
          (e) => e.latitude !== null && e.longitude !== null,
        ),
      ),
    [events],
  );

  return (
    <>
      <svg
        viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
        role="img"
        aria-label="Map of each real JJAS-registered drought event's exact reported coordinate"
        style={{
          width: "100%",
          maxWidth: 420,
          display: "block",
          margin: "0 auto",
        }}
      >
        {ethiopiaAdmin1.features.map((feat) => (
          <path
            key={feat.properties.region_id}
            d={ethGeometryToPathD(feat.geometry, projection)}
            fill="rgba(148,178,219,0.05)"
            stroke="rgba(148,178,219,0.35)"
            strokeWidth="1"
          />
        ))}
        {points.map((event) => {
          const [x, y] = projection.project(event.longitude, event.latitude);
          const hit = isHit(event.spi, "spi");
          const color =
            hit === null
              ? "var(--lp-muted)"
              : hit
                ? "var(--lp-red, #ef4a3d)"
                : "var(--lp-teal, #35d4c7)";
          return (
            <circle
              key={event.glidenumber}
              cx={x + event.dx}
              cy={y + event.dy}
              r="7"
              fill={color}
              fillOpacity="0.85"
              stroke="rgba(6,12,24,0.6)"
              strokeWidth="1.5"
            >
              <title>
                {event.glidenumber} {event.region}, {event.year}{" "}
                {formatMonth(event.month)}
                {"\n"}SPI: {formatValue(event.spi)} (
                {hit === null ? "N/A" : hit ? "Hit" : "Miss"})
              </title>
            </circle>
          );
        })}
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          gap: 18,
          marginTop: 12,
          fontSize: "0.8rem",
          color: "var(--lp-muted)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "var(--lp-red, #ef4a3d)",
              display: "inline-block",
            }}
          />
          Hit (SPI ≤ -1.0)
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "var(--lp-teal, #35d4c7)",
              display: "inline-block",
            }}
          />
          Miss (SPI &gt; -1.0)
        </span>
      </div>
    </>
  );
}

const CAPTURED_MISSED_COLUMNS = [
  { key: "year", label: "Year" },
  { key: "month", label: "Month" },
  { key: "region", label: "Region" },
];

function CapturedVsMissedTable({ events }) {
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
            {CAPTURED_MISSED_COLUMNS.map((column) => (
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
            <th>SPI</th>
            <th>Rainfall Total</th>
          </tr>
        </thead>
        <tbody>
          {sortedEvents.map((event) => (
            <tr key={`${event.glidenumber}-${event.region}`}>
              <td>{event.year}</td>
              <td>{formatMonth(event.month)}</td>
              <td className="lp-td-strong">{event.region}</td>
              <td>
                <HitBadge value={event.spi} indicatorKey="spi" formatter={formatValue} />
              </td>
              <td>
                <HitBadge
                  value={event.rainfall_total_anomaly}
                  indicatorKey="rainfall_total_anomaly"
                  formatter={formatValue}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const MATCH_LEVEL_LABELS = {
  wereda_exact: "Woreda (exact)",
  wereda_fuzzy: "Woreda (fuzzy)",
  zone_exact: "Zone (exact)",
  zone_fuzzy: "Zone (fuzzy)",
};

const DESINVENTAR_LOCATION_COLUMNS = [
  { key: "region", label: "Region", type: "string" },
  { key: "wereda", label: "Woreda / zone", type: "string" },
  { key: "episode_count", label: "Real drought-years reported", type: "number" },
  { key: "latitude", label: "Latitude", type: "number" },
  { key: "longitude", label: "Longitude", type: "number" },
  { key: "match_level", label: "Geocode precision", type: "string" },
];

function sortLocations(locations, sortKey, sortDir) {
  const column = DESINVENTAR_LOCATION_COLUMNS.find((c) => c.key === sortKey);
  const dirMultiplier = sortDir === "asc" ? 1 : -1;
  return [...locations].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (column?.type === "string") return av.localeCompare(bv) * dirMultiplier;
    return (av - bv) * dirMultiplier;
  });
}

function DesinventarLocationTable({ locations }) {
  const [sortKey, setSortKey] = useState("episode_count");
  const [sortDir, setSortDir] = useState("desc");

  const sortedLocations = useMemo(
    () => sortLocations(locations, sortKey, sortDir),
    [locations, sortKey, sortDir],
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
    <div className="lp-data-table-wrap" style={{ maxHeight: 480, overflowY: "auto" }}>
      <table className="lp-data-table">
        <thead>
          <tr>
            {DESINVENTAR_LOCATION_COLUMNS.map((column) => (
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
          {sortedLocations.map((loc) => (
            <tr key={`${loc.latitude},${loc.longitude}`}>
              <td className="lp-td-strong">{loc.region}</td>
              <td>{loc.wereda}</td>
              <td>{loc.episode_count}</td>
              <td>{formatCoord(loc.latitude)}</td>
              <td>{formatCoord(loc.longitude)}</td>
              <td>{MATCH_LEVEL_LABELS[loc.match_level] || loc.match_level}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Real per-location dot radius scaled by real reported drought-year count --
// a real, honest signal (how often DPPA/NDRMC reported a drought at this
// exact real place), not decoration. sqrt-scaled so a location reported 10x
// more often isn't drawn 10x the AREA, which would visually overwhelm the
// real map.
function desinventarDotRadius(episodeCount, maxCount) {
  const minR = 2.5;
  const maxR = 11;
  const t = maxCount > 1 ? Math.sqrt(episodeCount / maxCount) : 1;
  return minR + t * (maxR - minR);
}

function DesinventarLocationMap({ locations }) {
  const projection = useMemo(
    () => buildEthMapProjection(ethiopiaAdmin1.features, MAP_SIZE, MAP_PADDING),
    [],
  );
  const maxCount = Math.max(1, ...locations.map((l) => l.episode_count));

  return (
    <svg
      viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
      role="img"
      aria-label="Map of each real DesInventar-reported drought location, sized by how many real years a drought was reported there"
      style={{
        width: "100%",
        maxWidth: 420,
        display: "block",
        margin: "0 auto",
      }}
    >
      {ethiopiaAdmin1.features.map((feat) => (
        <path
          key={feat.properties.region_id}
          d={ethGeometryToPathD(feat.geometry, projection)}
          fill="rgba(148,178,219,0.05)"
          stroke="rgba(148,178,219,0.35)"
          strokeWidth="1"
        />
      ))}
      {locations.map((loc) => {
        const [x, y] = projection.project(loc.longitude, loc.latitude);
        return (
          <circle
            key={`${loc.latitude},${loc.longitude}`}
            cx={x}
            cy={y}
            r={desinventarDotRadius(loc.episode_count, maxCount)}
            fill="var(--lp-teal, #35d4c7)"
            fillOpacity="0.55"
            stroke="rgba(6,12,24,0.5)"
            strokeWidth="1"
          >
            <title>
              {loc.wereda}, {loc.region}
              {"\n"}Real drought-years reported: {loc.episode_count} (
              {loc.years[0]}-{loc.years[loc.years.length - 1]})
            </title>
          </circle>
        );
      })}
    </svg>
  );
}

function TrackRecord() {
  const [data, setData] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [desinventarData, setDesinventarData] = useState(null);

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
    async function loadDesinventar() {
      try {
        const response = await fetch(
          apiUrl("/api/validation/historical-skill-desinventar"),
        );
        if (!response.ok) return;
        const json = await response.json();
        if (!cancelled) setDesinventarData(json);
      } catch {
        // Non-critical: the page's headline GLIDE analysis above already
        // loaded independently -- silently omit this section rather than
        // showing a second error callout for a supplementary cross-check.
      }
    }
    load();
    loadDesinventar();
    return () => {
      cancelled = true;
    };
  }, []);

  const indicators = data?.indicators;
  const spi = indicators?.spi;
  const events = Array.isArray(data?.events) ? data.events : [];
  // Excludes real events with no baseline yet (currently just the 2026
  // Somali event -- that year's CHIRPS rainfall isn't downloaded/complete
  // yet, not a data-quality issue), so the per-event tables below only show
  // rows that can actually be scored.
  const scorableEvents = events.filter(
    (event) => event.spi !== null && event.spi !== undefined,
  );
  // Further restricted to events GLIDE actually registered during JJAS
  // itself -- matches the official hit-rate metric above, which only
  // counts JJAS-registered events. Real events registered in other months
  // are still real droughts (see the methodology text below), just not
  // shown in these two tables since they aren't part of what's being
  // scored as a "hit" or "miss".
  const jjasScorableEvents = scorableEvents.filter(
    (event) => event.month >= 6 && event.month <= 9,
  );
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
                Not a summary statistic in isolation: every real GLIDE
                drought event actually registered during JJAS itself,
                matching the official hit rate above (real events
                registered in other months are still real droughts, just
                not shown in these two tables). Each row shows its real
                reported date and location, its real GLIDE "affected"
                figure (the only real severity signal GLIDE captures for
                drought most events report 0 killed, injured, or
                homeless), and the real SPI and Rainfall Total values at
                that event's exact coordinate that year, not a region
                average (Rainfall Percentile is compared separately
                below). Click a column heading to sort by it.
              </p>
              <SortableEventTable events={jjasScorableEvents} />
              <div style={{ marginTop: 22 }}>
                <EventPointMap events={jjasScorableEvents} />
              </div>
            </div>
          </section>

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>The headline signal</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                For every real location where a real GLIDE drought event was
                actually registered during JJAS itself (this app's real
                forecast season, not some other month), was the exact real
                pixel at that event's own reported coordinate actually
                anomalously dry that season, using a real gamma-fit SPI not
                a region-wide average? Droughts are accumulation phenomena,
                so a seasonal total is a more honest test than any single
                month. Real events registered outside JJAS are real
                droughts too, so they're still excluded from the "no event"
                comparison below, just not counted toward this hit rate.
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
                    real unique pixel-years with a drought event registered
                    during JJAS itself
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
                    GLIDE events, 1997–2025 (all months, not just JJAS)
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
                so they're not included here. AUC (area under the ROC curve)
                measures how well an indicator ranks real event-years as
                drier than real no-event years across every real threshold,
                not just the fixed moderately-dry cutoff: 1.0 is perfect
                separation, 0.5 is no better than a coin flip.
              </p>
              <IndicatorComparisonTable indicators={indicators} />
              <p
                className="lp-prose"
                style={{ marginTop: 14, fontSize: "0.9rem" }}
              >
                Three real GLIDE events with a specific reported location
                fall in this JJAS-scored set. Two more (2011, 2015) were
                excluded because GLIDE geocoded them only to its generic
                Ethiopia-country fallback centroid, not a real
                drought-affected place, so a real pixel-level SPI computed
                there would have been meaningless (see the caveat below). At
                this small sample, all three indicators tie exactly at every
                fixed threshold: a real gamma-distribution correction or
                percentile ranking doesn't change which real events get
                flagged. AUC still
                reveals a real ranking underneath: Rainfall Percentile
                (0.821) discriminates real event-years from real no-event
                years better than SPI (0.751) or Rainfall Total (0.741) do
                across the full real threshold range, even though all three
                agree at the one fixed cutoff this page headlines.
              </p>
            </div>
          </section>

          {desinventarData && (
            <>
              <hr className="lp-article-divider" />

              <section className="lp-article-section">
                <div className="lp-wrap">
                  <h2>Cross-validated against a bigger, independent sample</h2>
                  <p className="lp-prose" style={{ marginBottom: 18 }}>
                    GLIDE's real sample above is tiny (2 event-years): not
                    enough to trust a hit rate, false-alarm rate, or AUC on
                    its own. To check whether that small-sample result holds
                    up, the same 3 indicators were re-scored against a real,
                    independent, much larger source: Ethiopia's own
                    DPPA/NDRMC disaster-loss database (DesInventar format,
                    via HDX) 2,883 real distinct drought episodes at 418
                    real locations, geocoded to this app's own admin3
                    boundaries, covering 1997-2013 (this real dataset's own
                    coverage ends there, so it extends the window backward
                    from GLIDE's 2015+ events rather than replacing it).
                  </p>
                  <IndicatorComparisonTable indicators={desinventarData.indicators} />
                  <p
                    className="lp-prose"
                    style={{ marginTop: 14, fontSize: "0.9rem" }}
                  >
                    This real, much larger sample does <strong>not</strong>{" "}
                    confirm the GLIDE result above: AUC lands at ~0.47 for
                    all three indicators, no better than a coin flip and
                    actually a touch worse. Before publishing this, three
                    checks ruled out a pipeline bug. Scoring each episode
                    against the prior year's rainfall instead of the same
                    year (droughts are often declared months after the real
                    deficit that caused them) raises AUC to ~0.55, still
                    weak but a real, directionally consistent effect.
                    Restricting to only the highest-impact half of episodes
                    barely moved the result, ruling out dilution by minor
                    reports. And a spot-check against the well-documented
                    1999-2000 Somali region drought showed real negative SPI
                    at most matched woredas, confirming the underlying
                    computation is sound. The most coherent explanation:
                    DesInventar's "drought" label is a broad administrative
                    designation spanning many real chronic, Belg-season, and
                    non-JJAS-driven cases that a JJAS-specific rainfall
                    indicator was never going to predict, a pattern that
                    matches what was already found for FEWS NET's IPC
                    Crisis+ label elsewhere on this page. GLIDE's smaller
                    but more selectively-curated event list may be doing
                    real, valuable filtering work that a bigger, broader
                    label doesn't.
                  </p>
                </div>
              </section>

              <section className="lp-article-section">
                <div className="lp-wrap">
                  <h3 style={{ marginBottom: 10 }}>
                    Every real DesInventar location, mapped and listed
                  </h3>
                  <p className="lp-prose" style={{ marginBottom: 18 }}>
                    All {desinventarData.locations?.length ?? 0} real
                    distinct locations behind the table above, sized by how
                    many real years DPPA/NDRMC reported a drought there
                    (bigger dot = reported more often), not by SPI or hit
                    rate: this map is about real reporting frequency and
                    geographic spread, not indicator skill.
                  </p>
                  <DesinventarLocationMap locations={desinventarData.locations || []} />
                  <div style={{ marginTop: 22 }}>
                    <DesinventarLocationTable locations={desinventarData.locations || []} />
                  </div>
                </div>
              </section>
            </>
          )}

          <hr className="lp-article-divider" />

          <section className="lp-article-section">
            <div className="lp-wrap">
              <h2>Captured vs. missed, by year, month &amp; region</h2>
              <p className="lp-prose" style={{ marginBottom: 18 }}>
                Every real GLIDE drought event actually registered during
                JJAS itself with a usable baseline, and whether SPI and
                Rainfall Total at that exact pixel actually crossed the
                moderately-dry threshold that year. Not the aggregate
                percentage above, but the real event-by-event record it's
                built from. Click a column heading to sort.
              </p>
              <CapturedVsMissedTable events={jjasScorableEvents} />
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
