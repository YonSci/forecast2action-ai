import { useEffect, useMemo, useState } from "react";
import RiskMap from "../components/RiskMap.jsx";
import { apiUrl } from "../config.js";

const AUDIENCES = [
  { value: "disaster_manager", label: "Disaster Risk Manager" },
  { value: "ngo_planner", label: "NGO / Anticipatory Action Planner" },
  {
    value: "extension_officer",
    label: "Agriculture & Livestock Extension Officer",
  },
  { value: "community", label: "Community Member" },
];

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "am", label: "Amharic" },
  { value: "sw", label: "Swahili" },
];

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
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

  return String(value)
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (text) => {
      return text.charAt(0).toUpperCase() + text.substring(1).toLowerCase();
    });
}

function displayValue(value, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

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
  if (!Array.isArray(values) || values.length === 0) {
    return DEFAULT_REPORT_TYPES;
  }

  return values.map((item) => {
    if (typeof item === "string") {
      return {
        value: item,
        label: titleCase(item),
      };
    }

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

  if (Array.isArray(feedbackSummary.summaries)) {
    return (
      feedbackSummary.summaries.find((item) => item.district === district) ||
      null
    );
  }

  if (Array.isArray(feedbackSummary.data)) {
    return (
      feedbackSummary.data.find((item) => item.district === district) || null
    );
  }

  if (feedbackSummary.district === district) return feedbackSummary;

  return null;
}

function getAdvisoryPayload(advisory) {
  if (!advisory) return {};

  return (
    advisory.rag_advisory ||
    advisory.advisory ||
    advisory.local_rag ||
    advisory.generated_advisory ||
    advisory
  );
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
  const [selectedAudience, setSelectedAudience] = useState("disaster_manager");
  const [selectedLanguage, setSelectedLanguage] = useState("en");

  const [advisory, setAdvisory] = useState(null);
  const [communityReports, setCommunityReports] = useState([]);
  const [feedbackSummary, setFeedbackSummary] = useState(null);
  const [reportTypes, setReportTypes] = useState(DEFAULT_REPORT_TYPES);
  const [priorityActions, setPriorityActions] = useState([]);
  const [actionTracker, setActionTracker] = useState(null);

  const [loading, setLoading] = useState(true);
  const [advisoryLoading, setAdvisoryLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const [reportForm, setReportForm] = useState({
    report_type: "water_shortage",
    severity: "medium",
    description: "",
    reporter_name: "",
    contact: "",
    latitude: "",
    longitude: "",
  });

  const selectedRisk = useMemo(() => {
    return riskData.find((item) => item.district === selectedDistrict) || null;
  }, [riskData, selectedDistrict]);

  const selectedFeedback = useMemo(() => {
    return getFeedbackForDistrict(feedbackSummary, selectedDistrict);
  }, [feedbackSummary, selectedDistrict]);

  const selectedDistrictReports = useMemo(() => {
    return communityReports.filter(
      (report) => report.district === selectedDistrict,
    );
  }, [communityReports, selectedDistrict]);

  const selectedFeedbackSignal =
    selectedFeedback?.feedback_signal ||
    (selectedDistrictReports.length > 0
      ? "limited_ground_signal"
      : "no_ground_signal");

  const selectedFeedbackTotalReports =
    selectedFeedback?.total_reports ?? selectedDistrictReports.length;

  const advisoryPayload = useMemo(() => {
    return getAdvisoryPayload(advisory);
  }, [advisory]);

  const recommendedActions =
    advisory?.recommended_actions ||
    advisoryPayload?.recommended_actions ||
    advisoryPayload?.actions ||
    [];

  const knowledgeSources =
    advisory?.knowledge_sources || advisoryPayload?.knowledge_sources || [];

  const retrievedGuidance =
    advisory?.retrieved_guidance || advisoryPayload?.retrieved_guidance || [];

  const roleSpecificAdvisory =
    advisory?.role_specific_advisory ||
    advisoryPayload?.role_specific_advisory ||
    advisory?.advisory_text ||
    advisoryPayload?.advisory_text ||
    "";

  const retrievalSummary =
    advisory?.retrieval_summary || advisoryPayload?.retrieval_summary || "";

  const communityMessage =
    advisory?.community_message ||
    advisory?.sms_message ||
    advisoryPayload?.community_message ||
    advisoryPayload?.sms_message ||
    "";

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

    if (!selectedDistrict && items.length > 0) {
      setSelectedDistrict(items[0].district);
    }

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
      const reports = safeArray(response, ["reports", "data", "items"]);
      setCommunityReports(reports);
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

  async function loadPriorityActions() {
    try {
      const response = await fetchJson("/api/priority-actions");
      const items = safeArray(response, [
        "priority_actions",
        "actions",
        "data",
        "items",
      ]);
      setPriorityActions(items);
    } catch (error) {
      console.error(error);
      setPriorityActions([]);
    }
  }

  async function loadAdvisory(
    district = selectedDistrict,
    audience = selectedAudience,
    language = selectedLanguage,
  ) {
    if (!district) return;

    setAdvisoryLoading(true);

    try {
      const path = `/api/advisory/${encodeURIComponent(
        district,
      )}?audience=${encodeURIComponent(audience)}&language=${encodeURIComponent(language)}`;

      const response = await fetchJson(path);
      setAdvisory(response);
    } catch (error) {
      console.error(error);
      setAdvisory(null);
      setErrorMessage("Could not load advisory from the backend API.");
    } finally {
      setAdvisoryLoading(false);
    }
  }

  async function loadActionTracker(
    district = selectedDistrict,
    audience = selectedAudience,
    language = selectedLanguage,
  ) {
    if (!district) return;

    try {
      const path = `/api/action-tracker/${encodeURIComponent(
        district,
      )}?audience=${encodeURIComponent(audience)}&language=${encodeURIComponent(language)}`;

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
        loadPriorityActions(),
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

    loadAdvisory(selectedDistrict, selectedAudience, selectedLanguage);
    loadActionTracker(selectedDistrict, selectedAudience, selectedLanguage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDistrict, selectedAudience, selectedLanguage]);

  function handleDistrictChange(event) {
    setSelectedDistrict(event.target.value);
  }

  function handleMapDistrictSelect(district) {
    setSelectedDistrict(district);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleAudienceChange(event) {
    setSelectedAudience(event.target.value);
  }

  function handleLanguageChange(event) {
    setSelectedLanguage(event.target.value);
  }

  function handleReportInputChange(event) {
    const { name, value } = event.target;

    setReportForm((previous) => ({
      ...previous,
      [name]: value,
    }));
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
        headers: {
          "Content-Type": "application/json",
        },
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
        loadPriorityActions(),
        loadAdvisory(selectedDistrict, selectedAudience, selectedLanguage),
        loadActionTracker(selectedDistrict, selectedAudience, selectedLanguage),
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
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task_id: task.task_id,
          status,
          updated_by: "dashboard_user",
        }),
      });

      await loadActionTracker(
        selectedDistrict,
        selectedAudience,
        selectedLanguage,
      );
    } catch (error) {
      console.error(error);
      setErrorMessage("Could not update task status.");
    }
  }

  async function handleDownloadBulletin(outputFormat) {
    if (!selectedDistrict) return;

    const path = `/api/bulletin/${encodeURIComponent(
      selectedDistrict,
    )}?audience=${encodeURIComponent(
      selectedAudience,
    )}&language=${encodeURIComponent(
      selectedLanguage,
    )}&output_format=${encodeURIComponent(outputFormat)}`;

    try {
      const response = await fetch(apiUrl(path));

      if (!response.ok) {
        throw new Error(`Bulletin export failed: ${response.status}`);
      }

      const blob = await response.blob();
      const extension = outputFormat === "markdown" ? "md" : "html";
      const filename = `forecast2action_bulletin_${selectedDistrict
        .replaceAll(" ", "_")
        .toLowerCase()}.${extension}`;

      downloadBlob(blob, filename);
    } catch (error) {
      console.error(error);
      setErrorMessage("Could not download bulletin.");
    }
  }

  async function handleDownloadActionTrackerCsv() {
    if (!selectedDistrict) return;

    const path = `/api/action-tracker/${encodeURIComponent(
      selectedDistrict,
    )}/csv?audience=${encodeURIComponent(
      selectedAudience,
    )}&language=${encodeURIComponent(selectedLanguage)}`;

    try {
      const response = await fetch(apiUrl(path));

      if (!response.ok) {
        throw new Error(`CSV export failed: ${response.status}`);
      }

      const blob = await response.blob();
      const filename = `forecast2action_action_tracker_${selectedDistrict
        .replaceAll(" ", "_")
        .toLowerCase()}.csv`;

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
          <p className="eyebrow">IGAD Hackathon 2026 Prototype</p>
          <h1>Forecast2Action AI</h1>
          <p className="hero-text">Loading dashboard data...</p>
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

        <div className="selector-card">
          <div className="selector-field">
            <label htmlFor="district-select">Select district</label>
            <select
              id="district-select"
              value={selectedDistrict}
              onChange={handleDistrictChange}
            >
              {riskData.length === 0 && (
                <option value="">No districts loaded</option>
              )}
              {riskData.map((item) => (
                <option key={item.district} value={item.district}>
                  {item.district}
                </option>
              ))}
            </select>
          </div>

          <div className="selector-field">
            <label htmlFor="audience-select">Select audience</label>
            <select
              id="audience-select"
              value={selectedAudience}
              onChange={handleAudienceChange}
            >
              {AUDIENCES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="selector-field">
            <label htmlFor="language-select">Community message language</label>
            <select
              id="language-select"
              value={selectedLanguage}
              onChange={handleLanguageChange}
            >
              {LANGUAGES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
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

      <RiskMap
        riskData={riskData}
        selectedDistrict={selectedDistrict}
        onSelectDistrict={handleMapDistrictSelect}
      />

      <section className="panel priority-section">
        <div className="section-heading">
          <h2>Priority Action Queue</h2>
          <p>
            Districts are ranked using risk score, alert level, and community
            ground-truth feedback.
          </p>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>District</th>
                <th>Hazard</th>
                <th>Risk level</th>
                <th>Risk score</th>
                <th>Priority score</th>
                <th>Community signal</th>
              </tr>
            </thead>
            <tbody>
              {priorityActions.map((item, index) => (
                <tr key={`${item.district}-${index}`}>
                  <td>{displayValue(item.rank || index + 1)}</td>
                  <td>
                    <button
                      type="button"
                      className="table-link-button"
                      onClick={() => setSelectedDistrict(item.district)}
                    >
                      {item.district}
                    </button>
                  </td>
                  <td>{titleCase(item.hazard)}</td>
                  <td>
                    <span className={`risk-pill risk-${item.risk_level}`}>
                      {titleCase(item.risk_level)}
                    </span>
                  </td>
                  <td>{displayValue(item.risk_score)}</td>
                  <td>{displayValue(item.priority_score)}</td>
                  <td>
                    {titleCase(item.feedback_signal || item.community_signal)}
                  </td>
                </tr>
              ))}

              {priorityActions.length === 0 && (
                <tr>
                  <td colSpan="7">No priority actions available.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>Impact-Based Risk Scores</h2>
          <p>
            Risk score combines hazard probability, exposure, vulnerability, and
            confidence.
          </p>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>District</th>
                <th>Country</th>
                <th>Hazard</th>
                <th>Risk level</th>
                <th>Risk score</th>
                <th>Hazard probability</th>
                <th>Exposure</th>
                <th>Vulnerability</th>
              </tr>
            </thead>
            <tbody>
              {riskData.map((item) => (
                <tr
                  key={item.district}
                  className={
                    item.district === selectedDistrict ? "selected-row" : ""
                  }
                >
                  <td>
                    <button
                      type="button"
                      className="table-link-button"
                      onClick={() => setSelectedDistrict(item.district)}
                    >
                      {item.district}
                    </button>
                  </td>
                  <td>{item.country}</td>
                  <td>{titleCase(item.hazard)}</td>
                  <td>
                    <span className={`risk-pill risk-${item.risk_level}`}>
                      {titleCase(item.risk_level)}
                    </span>
                  </td>
                  <td>{displayValue(item.risk_score)}</td>
                  <td>{displayValue(item.hazard_probability)}</td>
                  <td>{displayValue(item.exposure)}</td>
                  <td>{displayValue(item.vulnerability)}</td>
                </tr>
              ))}

              {riskData.length === 0 && (
                <tr>
                  <td colSpan="8">No risk data loaded from the API.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel advisory-section">
        <div className="section-heading">
          <h2>Forecast-to-Action Advisory</h2>
          <p>
            Audience-specific advisory generated from climate evidence, risk
            score, community reports, and local knowledge retrieval.
          </p>
        </div>

        {!selectedRisk && <p>No district selected.</p>}

        {selectedRisk && (
          <>
            <div className="advisory-header">
              <div>
                <h3>{selectedRisk.district}</h3>
                <p>
                  {selectedRisk.country} · {titleCase(selectedRisk.hazard)} ·{" "}
                  {titleCase(selectedRisk.risk_level)}
                </p>
              </div>

              <span className={`risk-pill risk-${selectedRisk.risk_level}`}>
                {titleCase(selectedRisk.risk_level)}
              </span>
            </div>

            <div className="climate-evidence-grid">
              <div className="climate-card">
                <span>Rainfall anomaly</span>
                <strong>
                  {displayValue(selectedRisk.rainfall_anomaly_pct, "%")}
                </strong>
              </div>

              <div className="climate-card">
                <span>SPI-like score</span>
                <strong>{displayValue(selectedRisk.spi)}</strong>
              </div>

              <div className="climate-card">
                <span>Baseline rainfall</span>
                <strong>
                  {displayValue(selectedRisk.baseline_mean_mm, " mm")}
                </strong>
              </div>

              <div className="climate-card">
                <span>Observed / forecast rainfall</span>
                <strong>{displayValue(selectedRisk.rainfall_mm, " mm")}</strong>
              </div>
            </div>

            <div className="climate-evidence-grid compact-grid">
              <div className="climate-card">
                <span>Risk score</span>
                <strong>{displayValue(selectedRisk.risk_score)}</strong>
              </div>

              <div className="climate-card">
                <span>Hazard probability</span>
                <strong>{displayValue(selectedRisk.hazard_probability)}</strong>
              </div>

              <div className="climate-card">
                <span>Exposure</span>
                <strong>{displayValue(selectedRisk.exposure)}</strong>
              </div>

              <div className="climate-card">
                <span>Vulnerability</span>
                <strong>{displayValue(selectedRisk.vulnerability)}</strong>
              </div>
            </div>

            <p className="evidence-note">
              Prototype climate evidence is based on CHIRPS-style seasonal
              rainfall anomaly and SPI-like standardized rainfall score.
            </p>

            {advisoryLoading && <p>Loading advisory...</p>}

            {!advisoryLoading && (
              <>
                <div className="advisory-card">
                  <h3>Role-specific advisory</h3>
                  <p>
                    {roleSpecificAdvisory ||
                      "No role-specific advisory returned by the backend."}
                  </p>
                </div>

                <div className="advisory-card">
                  <h3>Recommended early actions</h3>

                  {recommendedActions.length > 0 ? (
                    <ol>
                      {recommendedActions.map((action, index) => (
                        <li key={`${action}-${index}`}>{action}</li>
                      ))}
                    </ol>
                  ) : (
                    <p>No recommended actions available.</p>
                  )}
                </div>

                <div className="advisory-card">
                  <h3>Knowledge-guided advisory basis</h3>

                  {retrievalSummary ? (
                    <p>{retrievalSummary}</p>
                  ) : (
                    <p>No retrieval summary available.</p>
                  )}

                  {knowledgeSources.length > 0 && (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Title</th>
                            <th>Sector</th>
                            <th>Source</th>
                            <th>Score</th>
                          </tr>
                        </thead>
                        <tbody>
                          {knowledgeSources.map((source, index) => (
                            <tr key={`${source.id || source.title}-${index}`}>
                              <td>{source.title}</td>
                              <td>{source.sector}</td>
                              <td>
                                {source.source_title || source.source_note}
                              </td>
                              <td>{displayValue(source.retrieval_score)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {knowledgeSources.length === 0 &&
                    retrievedGuidance.length > 0 && (
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Title</th>
                              <th>Sector</th>
                              <th>Score</th>
                            </tr>
                          </thead>
                          <tbody>
                            {retrievedGuidance.map((item, index) => (
                              <tr key={`${item.id || item.title}-${index}`}>
                                <td>{item.title}</td>
                                <td>{item.sector}</td>
                                <td>{displayValue(item.retrieval_score)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                </div>

                <div className="advisory-card">
                  <h3>SMS / WhatsApp-ready message</h3>
                  <p>{communityMessage || "No community message available."}</p>
                </div>

                <div className="button-row">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => handleDownloadBulletin("html")}
                  >
                    Download HTML Bulletin
                  </button>

                  <button
                    type="button"
                    className="secondary-button secondary-button-light"
                    onClick={() => handleDownloadBulletin("markdown")}
                  >
                    Download Markdown Bulletin
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </section>

      <section className="panel action-tracker-section">
        <div className="tracker-header">
          <div>
            <h2>Action Implementation Tracker</h2>
            <p>
              Converts recommendations into practical tasks with responsible
              sectors, deadlines, priorities, and implementation status.
            </p>
          </div>

          <button
            type="button"
            className="secondary-button tracker-export-button"
            onClick={handleDownloadActionTrackerCsv}
          >
            Export Tracker CSV
          </button>
        </div>

        <div className="tracker-summary">
          <div>
            <span>Total tasks</span>
            <strong>
              {displayValue(actionSummary.total_tasks || actionTasks.length)}
            </strong>
          </div>
          <div>
            <span>Not started</span>
            <strong>{displayValue(actionSummary.not_started || 0)}</strong>
          </div>
          <div>
            <span>In progress</span>
            <strong>{displayValue(actionSummary.in_progress || 0)}</strong>
          </div>
          <div>
            <span>Completed</span>
            <strong>{displayValue(actionSummary.completed || 0)}</strong>
          </div>
          <div>
            <span>Blocked</span>
            <strong>{displayValue(actionSummary.blocked || 0)}</strong>
          </div>
          <div>
            <span>District</span>
            <strong>{selectedDistrict || "N/A"}</strong>
          </div>
        </div>

        <div className="table-scroll">
          <table className="tracker-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Action</th>
                <th>Responsible sector</th>
                <th>Priority</th>
                <th>Deadline</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {actionTasks.map((task, index) => (
                <tr key={task.task_id || index}>
                  <td>{displayValue(task.rank || index + 1)}</td>
                  <td>
                    <strong>{task.action}</strong>
                    <p className="task-basis">{task.basis}</p>
                  </td>
                  <td>{task.responsible_sector}</td>
                  <td>
                    <span
                      className={`priority-pill priority-${String(
                        task.priority || "routine",
                      ).toLowerCase()}`}
                    >
                      {titleCase(task.priority)}
                    </span>
                  </td>
                  <td>{task.suggested_deadline}</td>
                  <td>
                    <select
                      className="status-select"
                      value={task.status || "Not started"}
                      onChange={(event) =>
                        handleTaskStatusChange(task, event.target.value)
                      }
                    >
                      {STATUS_OPTIONS.map((status) => (
                        <option key={status} value={status}>
                          {status}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}

              {actionTasks.length === 0 && (
                <tr>
                  <td colSpan="6">No action tracker tasks available.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel community-section">
        <div className="section-heading">
          <h2>Community Ground-Truth Reports</h2>
          <p>
            Community observations help confirm whether forecast impacts are
            emerging on the ground.
          </p>
        </div>

        <div className="community-grid">
          <form className="report-form" onSubmit={handleReportSubmit}>
            <h3>Submit community report</h3>

            <div className="report-form-grid">
              <div className="form-field">
                <label htmlFor="report-type">Report type</label>
                <select
                  id="report-type"
                  name="report_type"
                  value={reportForm.report_type}
                  onChange={handleReportInputChange}
                >
                  {reportTypes.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-field">
                <label htmlFor="severity">Severity</label>
                <select
                  id="severity"
                  name="severity"
                  value={reportForm.severity}
                  onChange={handleReportInputChange}
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>

              <div className="form-field form-field-full">
                <label htmlFor="description">Description</label>
                <textarea
                  id="description"
                  name="description"
                  value={reportForm.description}
                  onChange={handleReportInputChange}
                  placeholder="Describe what is being observed locally..."
                  rows="4"
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="reporter-name">Reporter name</label>
                <input
                  id="reporter-name"
                  name="reporter_name"
                  value={reportForm.reporter_name}
                  onChange={handleReportInputChange}
                  placeholder="Optional"
                />
              </div>

              <div className="form-field">
                <label htmlFor="contact">Contact</label>
                <input
                  id="contact"
                  name="contact"
                  value={reportForm.contact}
                  onChange={handleReportInputChange}
                  placeholder="Optional"
                />
              </div>

              <div className="form-field">
                <label htmlFor="latitude">Latitude</label>
                <input
                  id="latitude"
                  name="latitude"
                  type="number"
                  step="any"
                  value={reportForm.latitude}
                  onChange={handleReportInputChange}
                  placeholder="Optional"
                />
              </div>

              <div className="form-field">
                <label htmlFor="longitude">Longitude</label>
                <input
                  id="longitude"
                  name="longitude"
                  type="number"
                  step="any"
                  value={reportForm.longitude}
                  onChange={handleReportInputChange}
                  placeholder="Optional"
                />
              </div>
            </div>

            <button type="submit" className="primary-button">
              Submit Report
            </button>
          </form>

          <div className="community-summary">
            <h3>Ground signal for {selectedDistrict || "selected district"}</h3>

            <div className="climate-evidence-grid compact-grid">
              <div className="climate-card">
                <span>Feedback signal</span>
                <strong>{titleCase(selectedFeedbackSignal)}</strong>
              </div>

              <div className="climate-card">
                <span>Total reports</span>
                <strong>{displayValue(selectedFeedbackTotalReports)}</strong>
              </div>
            </div>

            <h3>Latest district reports</h3>

            {selectedDistrictReports.length > 0 ? (
              <div className="report-list">
                {selectedDistrictReports.slice(0, 6).map((report, index) => (
                  <article className="report-card" key={report.id || index}>
                    <strong>
                      {titleCase(report.report_type)} ·{" "}
                      {titleCase(report.severity)}
                    </strong>
                    <p>{report.description}</p>
                    <small>
                      {report.district} · {report.reporter_name || "Anonymous"}
                    </small>
                  </article>
                ))}
              </div>
            ) : (
              <p>No community reports yet for this district.</p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

export default Dashboard;
