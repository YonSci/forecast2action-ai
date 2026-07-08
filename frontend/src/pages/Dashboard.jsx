import { useEffect, useState } from "react";
import RiskMap from "../components/RiskMap";

function Dashboard() {
  const [riskData, setRiskData] = useState([]);
  const [selectedDistrict, setSelectedDistrict] = useState("");
  const [selectedAudience, setSelectedAudience] = useState("disaster_manager");
  const [selectedLanguage, setSelectedLanguage] = useState("en");
  const [advisory, setAdvisory] = useState(null);
  const [communityReports, setCommunityReports] = useState([]);
  const [feedbackSummary, setFeedbackSummary] = useState(null);
  const [reportTypes, setReportTypes] = useState([]);
  const [priorityActions, setPriorityActions] = useState([]);
  const [actionTracker, setActionTracker] = useState(null);
  const [taskStatuses, setTaskStatuses] = useState({});
  const [loading, setLoading] = useState(true);

  const audiences = [
    { id: "disaster_manager", label: "Disaster Risk Manager" },
    { id: "ngo_planner", label: "NGO / Anticipatory Action Planner" },
    {
      id: "extension_officer",
      label: "Agriculture and Livestock Extension Officer",
    },
    { id: "community", label: "Community Member" },
  ];

  const languages = [
    { id: "en", label: "English" },
    { id: "am", label: "Amharic" },
    { id: "sw", label: "Swahili" },
  ];

  function displayValue(value, suffix = "") {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "—";
    }

    return `${value}${suffix}`;
  }

  function titleCase(value) {
    if (!value) {
      return "";
    }

    return String(value)
      .replaceAll("_", " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    return response.json();
  }

  async function loadAdvisory(district, audience, language) {
    const data = await fetchJson(
      `/api/advisory/${encodeURIComponent(
        district,
      )}?audience=${audience}&language=${language}`,
    );

    setAdvisory(data);
  }

  async function loadCommunityFeedback(district) {
    const reports = await fetchJson(
      `/api/community-reports?district=${encodeURIComponent(
        district,
      )}&limit=20`,
    );

    const summary = await fetchJson(
      `/api/community-feedback-summary?district=${encodeURIComponent(district)}`,
    );

    setCommunityReports(reports.reports || []);
    setFeedbackSummary(summary);
  }

  async function loadPriorityActions() {
    const data = await fetchJson("/api/priority-actions");
    setPriorityActions(data);
  }

  async function loadActionTracker(district, audience, language) {
    const data = await fetchJson(
      `/api/action-tracker/${encodeURIComponent(
        district,
      )}?audience=${audience}&language=${language}`,
    );

    setActionTracker(data);

    const nextStatuses = {};
    data.tasks?.forEach((task) => {
      nextStatuses[task.id] = task.status || "Not started";
    });

    setTaskStatuses(nextStatuses);
  }

  async function loadDashboard() {
    try {
      const risks = await fetchJson("/api/risk");
      setRiskData(risks);

      const types = await fetchJson("/api/report-types");
      setReportTypes(types);

      await loadPriorityActions();

      if (risks.length > 0) {
        const firstDistrict = risks[0].district;
        setSelectedDistrict(firstDistrict);

        await Promise.all([
          loadAdvisory(firstDistrict, selectedAudience, selectedLanguage),
          loadCommunityFeedback(firstDistrict),
          loadActionTracker(firstDistrict, selectedAudience, selectedLanguage),
        ]);
      }
    } catch (error) {
      console.error("Dashboard loading error:", error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleDistrictChange(event) {
    const district = event.target.value;
    setSelectedDistrict(district);

    await Promise.all([
      loadAdvisory(district, selectedAudience, selectedLanguage),
      loadCommunityFeedback(district),
      loadActionTracker(district, selectedAudience, selectedLanguage),
    ]);
  }

  async function handleMapDistrictSelect(district) {
    setSelectedDistrict(district);

    await Promise.all([
      loadAdvisory(district, selectedAudience, selectedLanguage),
      loadCommunityFeedback(district),
      loadActionTracker(district, selectedAudience, selectedLanguage),
    ]);
  }

  async function handleAudienceChange(event) {
    const audience = event.target.value;
    setSelectedAudience(audience);

    await Promise.all([
      loadAdvisory(selectedDistrict, audience, selectedLanguage),
      loadActionTracker(selectedDistrict, audience, selectedLanguage),
    ]);
  }

  async function handleLanguageChange(event) {
    const language = event.target.value;
    setSelectedLanguage(language);

    await Promise.all([
      loadAdvisory(selectedDistrict, selectedAudience, language),
      loadActionTracker(selectedDistrict, selectedAudience, language),
    ]);
  }

  async function handleTaskStatusChange(task, status) {
    setTaskStatuses((previousStatuses) => ({
      ...previousStatuses,
      [task.id]: status,
    }));

    try {
      const payload = {
        task_id: task.id,
        status,
        district: task.district,
        country: task.country,
        hazard: task.hazard,
        risk_level: task.risk_level,
        audience: selectedAudience,
        action: task.action,
        responsible_sector: task.responsible_sector,
        priority: task.priority,
        suggested_deadline: task.suggested_deadline,
        updated_by: selectedAudience,
      };

      const result = await fetchJson("/api/action-tracker/status", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!result.success) {
        alert(result.message || "Failed to save task status.");
      }

      await loadActionTracker(
        selectedDistrict,
        selectedAudience,
        selectedLanguage,
      );
    } catch (error) {
      console.error("Task status update error:", error);
      alert("Failed to save task status.");
    }
  }

  async function handleReportSubmit(event) {
    event.preventDefault();

    const formData = new FormData(event.target);

    const selectedRisk = riskData.find(
      (item) => item.district === selectedDistrict,
    );

    const payload = {
      country: selectedRisk?.country || "",
      district: selectedDistrict,
      report_type: formData.get("report_type"),
      severity: formData.get("severity"),
      description: formData.get("description"),
      reported_by: formData.get("reported_by") || "anonymous",
      contact: formData.get("contact") || "",
      latitude: formData.get("latitude")
        ? Number(formData.get("latitude"))
        : null,
      longitude: formData.get("longitude")
        ? Number(formData.get("longitude"))
        : null,
    };

    await fetchJson("/api/community-reports", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    event.target.reset();

    await Promise.all([
      loadCommunityFeedback(selectedDistrict),
      loadAdvisory(selectedDistrict, selectedAudience, selectedLanguage),
      loadPriorityActions(),
      loadActionTracker(selectedDistrict, selectedAudience, selectedLanguage),
    ]);
  }

  async function handleDownloadBulletin(outputFormat = "html") {
    const response = await fetch(
      `/api/bulletin/${encodeURIComponent(
        selectedDistrict,
      )}?audience=${selectedAudience}&language=${selectedLanguage}&output_format=${outputFormat}`,
    );

    if (!response.ok) {
      alert("Failed to generate bulletin.");
      return;
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);

    const safeDistrict = selectedDistrict.replaceAll(" ", "_");
    const extension = outputFormat === "markdown" ? "md" : "html";

    const link = document.createElement("a");
    link.href = url;
    link.download = `forecast2action_bulletin_${safeDistrict}.${extension}`;
    document.body.appendChild(link);
    link.click();
    link.remove();

    window.URL.revokeObjectURL(url);
  }

  async function handleDownloadActionTrackerCsv() {
    const response = await fetch(
      `/api/action-tracker/${encodeURIComponent(
        selectedDistrict,
      )}/csv?audience=${selectedAudience}&language=${selectedLanguage}`,
    );

    if (!response.ok) {
      alert("Failed to export action tracker CSV.");
      return;
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);

    const safeDistrict = selectedDistrict.replaceAll(" ", "_");
    const safeAudience = selectedAudience.replaceAll(" ", "_");

    const link = document.createElement("a");
    link.href = url;
    link.download = `forecast2action_action_tracker_${safeDistrict}_${safeAudience}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();

    window.URL.revokeObjectURL(url);
  }

  const triggers = riskData.filter(
    (item) => item.risk_level === "trigger",
  ).length;

  const warnings = riskData.filter(
    (item) => item.risk_level === "warning",
  ).length;

  const hazards = new Set(riskData.map((item) => item.hazard)).size;
  const countries = new Set(riskData.map((item) => item.country)).size;

  const climateEvidence = advisory?.climate_evidence || {};
  const inputIndicators = advisory?.input_indicators || {};
  const knowledgeSources = advisory?.knowledge_sources || [];
  const trackerTasks = actionTracker?.tasks || [];

  const completedTasks = trackerTasks.filter(
    (task) => taskStatuses[task.id] === "Completed",
  ).length;

  const inProgressTasks = trackerTasks.filter(
    (task) => taskStatuses[task.id] === "In progress",
  ).length;

  const blockedTasks = trackerTasks.filter(
    (task) => taskStatuses[task.id] === "Blocked",
  ).length;

  if (loading) {
    return <div className="loading">Loading Forecast2Action AI...</div>;
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h2>Forecast2Action AI</h2>
          <p>Smarter early warning, stronger communities</p>
        </div>
      </header>

      <main className="container">
        <section className="hero">
          <div>
            <p className="eyebrow">IGAD Hackathon 2026 Prototype</p>

            <h1>
              Forecast2Action
              <br />
              AI
            </h1>

            <p>
              Explainable AI copilot for impact-based early warning, last-mile
              anticipatory action and community ground-truth reporting.
            </p>
          </div>

          <div className="selector-stack">
            <label>
              Select district
              <select value={selectedDistrict} onChange={handleDistrictChange}>
                {riskData.map((item) => (
                  <option key={item.district} value={item.district}>
                    {item.district}, {item.country}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Select audience
              <select value={selectedAudience} onChange={handleAudienceChange}>
                {audiences.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Community message language
              <select value={selectedLanguage} onChange={handleLanguageChange}>
                {languages.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="metrics-grid">
          <div className="risk-card">
            <p>Countries</p>
            <h3>{countries}</h3>
          </div>

          <div className="risk-card">
            <p>Hazards</p>
            <h3>{hazards}</h3>
          </div>

          <div className="risk-card">
            <p>Warnings</p>
            <h3>{warnings}</h3>
          </div>

          <div className="risk-card">
            <p>Triggers</p>
            <h3>{triggers}</h3>
          </div>
        </section>

        <RiskMap
          riskData={riskData}
          selectedDistrict={selectedDistrict}
          onSelectDistrict={handleMapDistrictSelect}
        />

        <section className="panel priority-section">
          <div className="priority-header">
            <div>
              <h2>Priority Action Queue</h2>
              <p>
                Automatically ranks districts by risk score, rainfall evidence,
                and community ground-truth signal.
              </p>
            </div>
          </div>

          <div className="priority-list">
            {priorityActions.map((item) => (
              <div className="priority-item" key={item.district}>
                <div className="priority-rank">{item.rank}</div>

                <div className="priority-main">
                  <div className="priority-title-row">
                    <h3>
                      {item.district}, {item.country}
                    </h3>

                    <span className={`badge badge-${item.risk_level}`}>
                      {item.risk_level}
                    </span>
                  </div>

                  <p>
                    <strong>{item.hazard_label}</strong> · Risk score:{" "}
                    <strong>{item.risk_score}</strong> · Priority score:{" "}
                    <strong>{item.priority_score}</strong> · Community reports:{" "}
                    <strong>{item.community_reports}</strong>
                  </p>

                  <p>
                    Rainfall anomaly:{" "}
                    <strong>
                      {displayValue(item.rainfall_anomaly_pct, "%")}
                    </strong>{" "}
                    · SPI-like score: <strong>{displayValue(item.spi)}</strong>
                  </p>

                  <p className="priority-label">{item.priority_label}</p>

                  <p className="priority-step">{item.recommended_next_step}</p>

                  <p className="priority-feedback">
                    Ground signal:{" "}
                    <strong>{item.feedback_signal.replaceAll("_", " ")}</strong>
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="content-grid">
          <div className="panel">
            <h2>Impact-Based Risk Scores</h2>

            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>District</th>
                    <th>Country</th>
                    <th>Hazard</th>
                    <th>Rainfall Anomaly</th>
                    <th>SPI</th>
                    <th>Score</th>
                    <th>Level</th>
                  </tr>
                </thead>

                <tbody>
                  {riskData.map((item) => (
                    <tr key={item.district}>
                      <td>{item.district}</td>
                      <td>{item.country}</td>
                      <td>{item.hazard?.replaceAll("_", " ")}</td>
                      <td>{displayValue(item.rainfall_anomaly_pct, "%")}</td>
                      <td>{displayValue(item.spi)}</td>
                      <td>{item.risk_score}</td>
                      <td>
                        <span className={`badge badge-${item.risk_level}`}>
                          {item.risk_level}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <h2>Forecast-to-Action Advisory</h2>

            {advisory ? (
              <>
                <p>
                  <strong>{advisory.district}</strong>, {advisory.country}
                </p>

                <p>
                  <span className={`badge badge-${advisory.risk_level}`}>
                    {advisory.risk_level}
                  </span>{" "}
                  {advisory.hazard_label}
                </p>

                <h3>Climate evidence</h3>
                <div className="climate-evidence-grid">
                  <div className="climate-card">
                    <span>Season</span>
                    <strong>
                      {displayValue(climateEvidence.season)}{" "}
                      {displayValue(climateEvidence.year)}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>Seasonal rainfall</span>
                    <strong>
                      {displayValue(climateEvidence.rainfall_mm, " mm")}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>Baseline mean</span>
                    <strong>
                      {displayValue(climateEvidence.baseline_mean_mm, " mm")}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>Rainfall anomaly</span>
                    <strong>
                      {displayValue(climateEvidence.rainfall_anomaly_mm, " mm")}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>Anomaly percent</span>
                    <strong>
                      {displayValue(climateEvidence.rainfall_anomaly_pct, "%")}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>SPI-like score</span>
                    <strong>{displayValue(climateEvidence.spi)}</strong>
                  </div>
                </div>

                <p className="evidence-note">
                  Source:{" "}
                  {climateEvidence.indicator_source ||
                    "Prototype rainfall evidence"}
                </p>

                <h3>Impact-risk inputs</h3>
                <div className="climate-evidence-grid compact-grid">
                  <div className="climate-card">
                    <span>Hazard probability</span>
                    <strong>
                      {displayValue(inputIndicators.hazard_probability)}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>Exposure</span>
                    <strong>{displayValue(inputIndicators.exposure)}</strong>
                  </div>

                  <div className="climate-card">
                    <span>Vulnerability</span>
                    <strong>
                      {displayValue(inputIndicators.vulnerability)}
                    </strong>
                  </div>

                  <div className="climate-card">
                    <span>Confidence</span>
                    <strong>{displayValue(inputIndicators.confidence)}</strong>
                  </div>
                </div>

                <h3>Why this alert?</h3>
                <p>{advisory.why_this_alert}</p>

                <h3>Community ground-truth signal</h3>
                <p>{advisory.ground_truth_note}</p>

                <h3>Recommended early actions</h3>
                <ul>
                  {advisory.recommended_actions?.map((action, index) => (
                    <li key={index}>{action}</li>
                  ))}
                </ul>

                <h3>Role-specific advisory</h3>
                <p>{advisory.role_specific_advisory}</p>

                <h3>Knowledge-guided advisory basis</h3>
                <p className="evidence-note">
                  {advisory.retrieval_summary ||
                    "No knowledge retrieval summary available."}
                </p>

                {knowledgeSources.length > 0 && (
                  <div className="report-list">
                    {knowledgeSources.map((source) => (
                      <div key={source.id} className="report-item">
                        <strong>{source.title}</strong>
                        <p>
                          Sector: {source.sector} · Retrieval score:{" "}
                          {source.retrieval_score}
                        </p>
                        <small>{source.source_note}</small>
                      </div>
                    ))}
                  </div>
                )}

                <h3>SMS / WhatsApp message</h3>
                <p className="sms-box">{advisory.community_message}</p>

                <p className="mode-note">
                  Advisory mode: <strong>{advisory.mode}</strong>
                </p>

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
            ) : (
              <p>No advisory available.</p>
            )}
          </div>
        </section>

        <section className="panel full-width-section action-tracker-section">
          <div className="tracker-header">
            <div>
              <h2>Action Implementation Tracker</h2>
              <p>
                Converts recommended early actions into operational tasks with
                responsible sectors, priorities, deadlines and saved
                implementation status.
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
              <strong>{actionTracker?.summary?.total_tasks ?? 0}</strong>
            </div>

            <div>
              <span>Urgent</span>
              <strong>{actionTracker?.summary?.urgent_tasks ?? 0}</strong>
            </div>

            <div>
              <span>High priority</span>
              <strong>
                {actionTracker?.summary?.high_priority_tasks ?? 0}
              </strong>
            </div>

            <div>
              <span>In progress</span>
              <strong>{inProgressTasks}</strong>
            </div>

            <div>
              <span>Completed</span>
              <strong>{completedTasks}</strong>
            </div>

            <div>
              <span>Blocked</span>
              <strong>{blockedTasks}</strong>
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
                {trackerTasks.map((task) => (
                  <tr key={task.id}>
                    <td>{task.rank}</td>
                    <td>
                      <strong>{task.action}</strong>
                      <p className="task-basis">{task.basis}</p>
                      {task.updated_at && (
                        <p className="task-basis">
                          Last updated by {task.updated_by || "dashboard_user"}{" "}
                          at {task.updated_at}
                        </p>
                      )}
                    </td>
                    <td>{task.responsible_sector}</td>
                    <td>
                      <span
                        className={`priority-pill priority-${task.priority.toLowerCase()}`}
                      >
                        {task.priority}
                      </span>
                    </td>
                    <td>{task.suggested_deadline}</td>
                    <td>
                      <select
                        className="status-select"
                        value={taskStatuses[task.id] || task.status}
                        onChange={(event) =>
                          handleTaskStatusChange(task, event.target.value)
                        }
                      >
                        <option value="Not started">Not started</option>
                        <option value="In progress">In progress</option>
                        <option value="Completed">Completed</option>
                        <option value="Blocked">Blocked</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel full-width-section">
          <h2>Community Ground-Truth Reports</h2>

          <div className="feedback-summary">
            <div>
              <span>Total reports</span>
              <strong>{feedbackSummary?.total_reports ?? 0}</strong>
            </div>

            <div>
              <span>Ground signal</span>
              <strong>
                {titleCase(
                  feedbackSummary?.feedback_signal || "no_ground_signal",
                )}
              </strong>
            </div>
          </div>

          <form className="feedback-form" onSubmit={handleReportSubmit}>
            <div className="form-grid">
              <label>
                Report type
                <select name="report_type" defaultValue="water_shortage">
                  {reportTypes.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Severity
                <select name="severity" defaultValue="medium">
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </label>
            </div>

            <label>
              Field observation
              <textarea
                name="description"
                rows="4"
                required
                placeholder="Example: Main water point is drying and livestock movement has increased."
              />
            </label>

            <div className="form-grid">
              <label>
                Reported by
                <input name="reported_by" placeholder="Community volunteer" />
              </label>

              <label>
                Contact, optional
                <input name="contact" placeholder="+251..." />
              </label>
            </div>

            <div className="form-grid">
              <label>
                Latitude, optional
                <input name="latitude" placeholder="4.95" />
              </label>

              <label>
                Longitude, optional
                <input name="longitude" placeholder="38.15" />
              </label>
            </div>

            <button type="submit" className="primary-button">
              Submit community report
            </button>
          </form>

          <h3>Latest reports</h3>

          {communityReports.length === 0 ? (
            <p>No community reports yet for this district.</p>
          ) : (
            <div className="report-list">
              {communityReports.map((report) => (
                <div key={report.id} className="report-item">
                  <strong>{report.report_type?.replaceAll("_", " ")}</strong>
                  <p>{report.description}</p>
                  <small>
                    Severity: {report.severity} · Reported by:{" "}
                    {report.reported_by} · {report.created_at}
                  </small>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default Dashboard;
