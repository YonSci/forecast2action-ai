import { useEffect, useMemo, useState } from "react";
import AdminBoundarySelector from "../components/AdminBoundarySelector.jsx";
import ForecastLayerMap from "../components/ForecastLayerMap.jsx";
import RiskMap from "../components/RiskMap.jsx";
import TopInterventionAreas from "../components/TopInterventionAreas.jsx";
import SelectedAreaAdvisory from "../components/SelectedAreaAdvisory.jsx";
import { apiUrl } from "../config.js";
import ActionImplementationTracker from "../components/ActionImplementationTracker.jsx";
import SelectedAreaCommunityReports from "../components/SelectedAreaCommunityReports.jsx";

const DEFAULT_AUDIENCE = "disaster_manager";

const DEFAULT_REPORT_TYPES = [
  { value: "water_shortage", label: "Water shortage / water point drying" },
  { value: "crop_wilting", label: "Crop wilting" },
  { value: "pasture_stress", label: "Pasture stress" },
  { value: "livestock_stress", label: "Livestock stress" },
  { value: "flooded_road", label: "Flooded road" },
  { value: "market_disruption", label: "Market disruption" },
  { value: "disease_concern", label: "Disease concern" },
  { value: "other", label: "Other" },
];

const STATUS_OPTIONS = ["Not started", "In progress", "Completed", "Blocked"];

function titleCase(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  return String(value)
    .replaceAll("_", " ")
    .replace(
      /\w\S*/g,
      (text) => text.charAt(0).toUpperCase() + text.substring(1).toLowerCase(),
    );
}

function displayValue(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "N/A";
  return `${value}${suffix}`;
}

function safeArray(response, keys = []) {
  if (Array.isArray(response)) return response;
  for (const key of keys) {
    if (Array.isArray(response?.[key])) return response[key];
  }
  return [];
}

function normalizeReportTypes(values) {
  if (!Array.isArray(values) || values.length === 0)
    return DEFAULT_REPORT_TYPES;
  return values.map((item) => {
    if (typeof item === "string")
      return { value: item, label: titleCase(item) };
    return {
      value:
        item.value ||
        item.id ||
        item.report_type ||
        item.key ||
        item.name ||
        "other",
      label:
        item.label ||
        item.name ||
        item.title ||
        titleCase(
          item.value || item.id || item.report_type || item.key || "other",
        ),
    };
  });
}

function getReportTypes(response) {
  const values = safeArray(response, ["report_types", "types", "data"]);
  return normalizeReportTypes(values);
}

function getFeedbackForDistrict(feedbackSummary, district) {
  if (!feedbackSummary || !district) return null;
  if (feedbackSummary[district]) return feedbackSummary[district];
  if (feedbackSummary.by_district?.[district])
    return feedbackSummary.by_district[district];
  if (Array.isArray(feedbackSummary.summaries))
    return (
      feedbackSummary.summaries.find((item) => item.district === district) ||
      null
    );
  if (Array.isArray(feedbackSummary.data))
    return (
      feedbackSummary.data.find((item) => item.district === district) || null
    );
  if (feedbackSummary.district === district) return feedbackSummary;
  return null;
}

function downloadBlob(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

async function fetchJson(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed ${response.status}: ${text}`);
  }
  return response.json();
}

function Dashboard() {
  const [riskData, setRiskData] = useState([]);
  const [selectedDistrict, setSelectedDistrict] = useState("");
  const [selectedLanguage, setSelectedLanguage] = useState("en");
  const [communityReports, setCommunityReports] = useState([]);
  const [feedbackSummary, setFeedbackSummary] = useState(null);
  const [reportTypes, setReportTypes] = useState(DEFAULT_REPORT_TYPES);
  const [actionTracker, setActionTracker] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const [adminSelection, setAdminSelection] = useState({
    regionId: "",
    zoneId: "",
    woredaId: "",
    regionLabel: "",
    zoneLabel: "",
    woredaLabel: "",
    boundaryLevel: "admin1",
    boundaryGeojson: null,
    boundaryLoading: false,
  });

  const [forecastSelection, setForecastSelection] = useState({
    forecastScale: "subseasonal",
    lead: "week_1",
    layer: "risk_score",
    indicator: "spi",
  });

  const [selectedPriorityArea, setSelectedPriorityArea] = useState(null);

  const [reportForm, setReportForm] = useState({
    report_type: "water_shortage",
    severity: "medium",
    description: "",
    reporter_name: "",
    contact: "",
    latitude: "",
    longitude: "",
  });

  const selectedRisk = useMemo(
    () => riskData.find((item) => item.district === selectedDistrict) || null,
    [riskData, selectedDistrict],
  );
  const selectedFeedback = useMemo(
    () => getFeedbackForDistrict(feedbackSummary, selectedDistrict),
    [feedbackSummary, selectedDistrict],
  );
  const selectedDistrictReports = useMemo(
    () =>
      communityReports.filter((report) => report.district === selectedDistrict),
    [communityReports, selectedDistrict],
  );

  const selectedFeedbackSignal =
    selectedFeedback?.feedback_signal ||
    (selectedDistrictReports.length > 0
      ? "limited_ground_signal"
      : "no_ground_signal");
  const selectedFeedbackTotalReports =
    selectedFeedback?.total_reports ?? selectedDistrictReports.length;
  const actionTasks = Array.isArray(actionTracker)
    ? actionTracker
    : actionTracker?.tasks || [];
  const actionSummary = actionTracker?.summary || {};

  async function loadRiskData() {
    const response = await fetchJson("/api/risk");
    const items = safeArray(response, [
      "risk_data",
      "data",
      "items",
      "districts",
    ]);
    setRiskData(items);
    if (!selectedDistrict && items.length > 0)
      setSelectedDistrict(items[0].district);
    return items;
  }

  async function loadReportTypes() {
    try {
      const response = await fetchJson("/api/report-types");
      setReportTypes(getReportTypes(response));
    } catch (error) {
      console.error(error);
      setReportTypes(DEFAULT_REPORT_TYPES);
    }
  }

  async function loadCommunityReports() {
    try {
      const response = await fetchJson("/api/community-reports");
      setCommunityReports(safeArray(response, ["reports", "data", "items"]));
    } catch (error) {
      console.error(error);
      setCommunityReports([]);
    }
  }

  async function loadCommunityFeedback() {
    try {
      const response = await fetchJson("/api/community-feedback-summary");
      setFeedbackSummary(response);
    } catch (error) {
      console.error(error);
      setFeedbackSummary(null);
    }
  }

  async function loadActionTracker(
    district = selectedDistrict,
    audience = DEFAULT_AUDIENCE,
    language = selectedLanguage,
  ) {
    if (!district) return;
    try {
      const path = `/api/action-tracker/${encodeURIComponent(district)}?audience=${encodeURIComponent(audience)}&language=${encodeURIComponent(language)}`;
      const response = await fetchJson(path);
      setActionTracker(response);
    } catch (error) {
      console.error(error);
      setActionTracker(null);
    }
  }

  async function loadDashboard() {
    setLoading(true);
    setErrorMessage("");
    try {
      await Promise.all([
        loadRiskData(),
        loadReportTypes(),
        loadCommunityReports(),
        loadCommunityFeedback(),
      ]);
    } catch (error) {
      console.error(error);
      setErrorMessage(
        "Could not load dashboard data. Check that the deployed backend URL is correct and reachable.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedDistrict) return;
    loadActionTracker(selectedDistrict, DEFAULT_AUDIENCE, selectedLanguage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDistrict, selectedLanguage]);

  function handleReportInputChange(event) {
    const { name, value } = event.target;
    setReportForm((previous) => ({ ...previous, [name]: value }));
  }

  async function handleReportSubmit(event) {
    event.preventDefault();
    if (!selectedRisk) {
      setErrorMessage(
        "Please select a district before submitting a community report.",
      );
      return;
    }

    const payload = {
      country: selectedRisk.country,
      district: selectedRisk.district,
      report_type: reportForm.report_type,
      severity: reportForm.severity,
      description: reportForm.description,
      reporter_name: reportForm.reporter_name,
      contact: reportForm.contact,
      latitude: reportForm.latitude === "" ? null : Number(reportForm.latitude),
      longitude:
        reportForm.longitude === "" ? null : Number(reportForm.longitude),
    };

    try {
      await fetchJson("/api/community-reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setReportForm({
        report_type: "water_shortage",
        severity: "medium",
        description: "",
        reporter_name: "",
        contact: "",
        latitude: "",
        longitude: "",
      });
      await Promise.all([
        loadCommunityReports(),
        loadCommunityFeedback(),
        loadActionTracker(selectedDistrict, DEFAULT_AUDIENCE, selectedLanguage),
      ]);
    } catch (error) {
      console.error(error);
      setErrorMessage("Community report submission failed.");
    }
  }

  async function handleTaskStatusChange(task, status) {
    try {
      await fetchJson("/api/action-tracker/status", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: task.task_id,
          status,
          updated_by: "dashboard_user",
        }),
      });
      await loadActionTracker(
        selectedDistrict,
        DEFAULT_AUDIENCE,
        selectedLanguage,
      );
    } catch (error) {
      console.error(error);
      setErrorMessage("Could not update task status.");
    }
  }

  async function handleDownloadActionTrackerCsv() {
    if (!selectedDistrict) return;
    const path = `/api/action-tracker/${encodeURIComponent(selectedDistrict)}/csv?audience=${encodeURIComponent(DEFAULT_AUDIENCE)}&language=${encodeURIComponent(selectedLanguage)}`;
    try {
      const response = await fetch(apiUrl(path));
      if (!response.ok)
        throw new Error(`CSV export failed: ${response.status}`);
      const blob = await response.blob();
      const filename = `forecast2action_action_tracker_${selectedDistrict.replaceAll(" ", "_").toLowerCase()}.csv`;
      downloadBlob(blob, filename);
    } catch (error) {
      console.error(error);
      setErrorMessage("Could not download action tracker CSV.");
    }
  }

  const triggerCount = riskData.filter(
    (item) => item.risk_level === "trigger",
  ).length;
  const warningCount = riskData.filter(
    (item) => item.risk_level === "warning",
  ).length;
  const watchCount = riskData.filter(
    (item) => item.risk_level === "watch",
  ).length;

  if (loading) {
    return (
      <main className="app-shell">
        <section className="hero">
          <div className="hero-content">
            <p className="eyebrow">IGAD Hackathon 2026 Prototype</p>
            <h1>Forecast2Action AI</h1>
            <p className="hero-text">Loading dashboard data...</p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div className="hero-content">
          <p className="eyebrow">IGAD Hackathon 2026 Prototype</p>
          <h1>Forecast2Action AI</h1>
          <p className="hero-text">
            Smarter early warning, stronger communities. Convert climate risk
            signals into explainable advisories, priority actions, community
            messages, implementation tasks, and operational exports.
          </p>
        </div>
      </section>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <section className="metrics-grid">
        <div className="metric-card">
          <span>Total pilot districts</span>
          <strong>{riskData.length}</strong>
        </div>
        <div className="metric-card">
          <span>Trigger alerts</span>
          <strong>{triggerCount}</strong>
        </div>
        <div className="metric-card">
          <span>Warning alerts</span>
          <strong>{warningCount}</strong>
        </div>
        <div className="metric-card">
          <span>Watch alerts</span>
          <strong>{watchCount}</strong>
        </div>
        <div className="metric-card">
          <span>Community reports</span>
          <strong>{communityReports.length}</strong>
        </div>
      </section>

      <AdminBoundarySelector
        selectedLanguage={selectedLanguage}
        onLanguageChange={setSelectedLanguage}
        onSelectionChange={setAdminSelection}
        onClearPrioritySelection={() => setSelectedPriorityArea(null)}
      />

      <ForecastLayerMap
        adminSelection={adminSelection}
        onForecastSelectionChange={setForecastSelection}
      />

      <TopInterventionAreas
        adminSelection={adminSelection}
        forecastSelection={forecastSelection}
        selectedPriorityArea={selectedPriorityArea}
        onPriorityAreaSelect={setSelectedPriorityArea}
      />

      <RiskMap
        adminSelection={adminSelection}
        selectedPriorityArea={selectedPriorityArea}
      />

      <SelectedAreaAdvisory
        selectedPriorityArea={selectedPriorityArea}
        forecastSelection={forecastSelection}
        selectedLanguage={selectedLanguage}
      />

      <ActionImplementationTracker
        selectedPriorityArea={selectedPriorityArea}
        forecastSelection={forecastSelection}
      />

      <SelectedAreaCommunityReports
        selectedPriorityArea={selectedPriorityArea}
        forecastSelection={forecastSelection}
        selectedLanguage={selectedLanguage}
      />
    </main>
  );
}

export default Dashboard;
