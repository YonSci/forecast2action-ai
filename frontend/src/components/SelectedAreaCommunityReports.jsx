import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";
import {
  REPORT_TYPES,
  getReportTypeLabel,
  getSeverityClass,
  getSignalSummary,
} from "../constants/communityReports.js";

const LEAD_LABELS = {
  week_1: "Week 1",
  week_2: "Week 2",
  week_3: "Week 3",
  week_4: "Week 4",
  week_1_2: "Week 1-2",
  week_2_3: "Week 2-3",
  week_3_4: "Week 3-4",
  month_1: "Month 1",
  month_2: "Month 2",
  month_3: "Month 3",
  month_4: "Month 4",
  month_5: "Month 5",
  month_6: "Month 6",
};

const LANGUAGE_LABELS = {
  en: "English",
  am: "Amharic",
  sw: "Swahili",
};

const SEVERITY_OPTIONS = [
  { value: "low", label: "Low" },
  { value: "moderate", label: "Moderate" },
  { value: "high", label: "High" },
  { value: "severe", label: "Severe" },
];

const CONFIDENCE_OPTIONS = [
  { value: "low", label: "Low confidence" },
  { value: "medium", label: "Medium confidence" },
  { value: "high", label: "High confidence" },
];

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

function getLeadLabel(value) {
  return LEAD_LABELS[value] || titleCase(value || "week_1");
}

function getAdminLevelLabel(level) {
  if (level === "admin1") return "Region";
  if (level === "admin2") return "Zone";
  if (level === "admin3") return "Woreda";
  return titleCase(level);
}

function getStorageKey(area, forecastSelection) {
  const parts = [
    area?.admin_level || "admin",
    area?.region_id || "region",
    area?.zone_id || "zone",
    area?.woreda_id || area?.area_name || "area",
    area?.hazard || "hazard",
    area?.risk_level || "risk",
    forecastSelection?.forecastScale || "scale",
    forecastSelection?.lead || "lead",
  ];

  return `forecast2action-ground-truth-${parts.join("-")}`;
}

function getInitialForm(area) {
  return {
    reporter_role: "community_focal_point",
    location_detail: area?.area_name || "",
    report_type: "water_shortage",
    severity: "moderate",
    confidence: "medium",
    description: "",
    contact: "",
  };
}

function downloadReportsCsv(area, forecastSelection, reports) {
  const headers = [
    "Area",
    "Admin level",
    "Period",
    "Hazard",
    "Risk level",
    "Report type",
    "Severity",
    "Confidence",
    "Reporter role",
    "Location detail",
    "Description",
    "Contact",
    "Submitted at",
  ];

  const escapeCsv = (value) => {
    const text = String(value ?? "");
    return `"${text.replaceAll('"', '""')}"`;
  };

  const rows = reports.map((report) => [
    area.area_name,
    getAdminLevelLabel(area.admin_level),
    forecastSelection.hazardRiskPeriodLabel || getLeadLabel(forecastSelection.lead),
    titleCase(area.hazard),
    titleCase(area.risk_level),
    getReportTypeLabel(report.report_type),
    titleCase(report.severity),
    titleCase(report.confidence),
    titleCase(report.reporter_role),
    report.location_detail,
    report.description,
    report.contact,
    report.submitted_at,
  ]);

  const csv = [
    headers.map(escapeCsv).join(","),
    ...rows.map((row) => row.map(escapeCsv).join(",")),
  ].join("\n");

  const blob = new Blob([csv], {
    type: "text/csv;charset=utf-8;",
  });

  const safeArea = String(area.area_name || "selected-area")
    .replaceAll(" ", "_")
    .toLowerCase();

  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `ground_truth_reports_${safeArea}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function SelectedAreaCommunityReports({
  selectedPriorityArea = null,
  forecastSelection = {},
  selectedLanguage = "en",
}) {
  const hasSelectedArea = Boolean(selectedPriorityArea?.area_name);
  const storageKey = useMemo(() => {
    if (!hasSelectedArea) {
      return "";
    }

    return getStorageKey(selectedPriorityArea, forecastSelection);
  }, [hasSelectedArea, selectedPriorityArea, forecastSelection]);

  const [reports, setReports] = useState([]);
  const [form, setForm] = useState(getInitialForm(selectedPriorityArea));
  const [usingLocalFallback, setUsingLocalFallback] = useState(false);

  // Real backend is now the primary read/write path (POST/GET
  // /api/community-reports) so submitted reports actually feed the
  // server-side feedback_signal used elsewhere in the app, instead of being
  // invisible to everything but this one browser. localStorage is kept only
  // as an offline fallback (same defensive try/catch pattern already used
  // in Dashboard.jsx's fetchJson), not the primary store.
  useEffect(() => {
    setForm(getInitialForm(selectedPriorityArea));

    if (!hasSelectedArea) {
      setReports([]);
      return;
    }

    let cancelled = false;

    async function loadReports() {
      try {
        const response = await fetch(
          apiUrl(`/api/community-reports?district=${encodeURIComponent(selectedPriorityArea.area_name)}`),
        );
        if (!response.ok) {
          throw new Error(`Request failed ${response.status}`);
        }
        const data = await response.json();
        const items = Array.isArray(data) ? data : data.reports || [];
        if (!cancelled) {
          setReports(items.map((item) => ({ ...item, submitted_at: item.submitted_at || item.created_at })));
          setUsingLocalFallback(false);
        }
      } catch (error) {
        console.error(error);
        if (cancelled) {
          return;
        }
        setUsingLocalFallback(true);
        try {
          const savedReports = JSON.parse(localStorage.getItem(storageKey) || "[]");
          setReports(Array.isArray(savedReports) ? savedReports : []);
        } catch {
          setReports([]);
        }
      }
    }

    loadReports();

    return () => {
      cancelled = true;
    };
  }, [hasSelectedArea, selectedPriorityArea, storageKey]);

  const signalSummary = getSignalSummary(reports);

  function updateField(field, value) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function handleSubmit(event) {
    event.preventDefault();

    const payload = {
      country: "Ethiopia",
      district: selectedPriorityArea.area_name,
      report_type: form.report_type,
      severity: form.severity,
      description: form.description,
      reported_by: form.reporter_role || "anonymous",
      contact: form.contact,
      reporter_role: form.reporter_role,
      location_detail: form.location_detail,
      confidence: form.confidence,
      admin_level: selectedPriorityArea.admin_level,
      region: selectedPriorityArea.region || "",
      zone: selectedPriorityArea.zone || "",
      woreda: selectedPriorityArea.woreda || "",
      region_id: selectedPriorityArea.region_id || "",
      zone_id: selectedPriorityArea.zone_id || "",
      woreda_id: selectedPriorityArea.woreda_id || "",
      hazard: selectedPriorityArea.hazard || "",
      risk_level: selectedPriorityArea.risk_level || "",
      priority_score: selectedPriorityArea.priority_score ?? null,
    };

    try {
      const response = await fetch(apiUrl("/api/community-reports"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(`Request failed ${response.status}`);
      }
      const data = await response.json();
      const savedReport = { ...data.report, submitted_at: data.report.created_at };
      setReports((currentReports) => [savedReport, ...currentReports]);
      setUsingLocalFallback(false);
    } catch (error) {
      console.error(error);
      setUsingLocalFallback(true);
      const localReport = {
        id: `report-${Date.now()}`,
        ...form,
        ...payload,
        area_name: selectedPriorityArea.area_name,
        submitted_at: new Date().toISOString(),
        lead: forecastSelection.lead || "",
        forecast_scale: forecastSelection.forecastScale || "",
        language: selectedLanguage,
      };
      setReports((currentReports) => {
        const next = [localReport, ...currentReports];
        if (storageKey) {
          localStorage.setItem(storageKey, JSON.stringify(next));
        }
        return next;
      });
    }

    setForm(getInitialForm(selectedPriorityArea));
  }

  // Delete/Clear only affect this local view (and the local fallback cache,
  // if active) -- there is no backend delete endpoint for submitted
  // community reports, intentionally: real field reports are meant to be an
  // append-only record, matching standard humanitarian ground-truth
  // reporting practice, not silently erasable.
  function handleDeleteReport(reportId) {
    setReports((currentReports) => {
      const next = currentReports.filter((report) => report.id !== reportId);
      if (usingLocalFallback && storageKey) {
        localStorage.setItem(storageKey, JSON.stringify(next));
      }
      return next;
    });
  }

  // Verification is a real server-side action (PATCH /api/community-reports/
  // {id}/verify) -- unlike delete/clear above, it updates the actual stored
  // report, since a verified report is weighted higher in
  // weighted_high_or_severe_count (app/api/community_reports_store.py),
  // which feeds both the community-evidence signal shown here AND Stage 2
  // of the AI report (build_community_evidence_by_region). Not available
  // for locally-cached (backend-unreachable) reports -- there's nothing on
  // the server yet to verify.
  async function handleVerifyReport(reportId, status) {
    if (usingLocalFallback) {
      return;
    }
    const verifiedBy = window.prompt(
      status === "verified"
        ? "Verifying as (name, role, or organization):"
        : "Disputing as (name, role, or organization):",
      "",
    );
    if (!verifiedBy) {
      return;
    }

    try {
      const response = await fetch(apiUrl(`/api/community-reports/${reportId}/verify`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verified_by: verifiedBy, status }),
      });
      if (!response.ok) {
        throw new Error(`Request failed ${response.status}`);
      }
      const data = await response.json();
      setReports((currentReports) =>
        currentReports.map((report) =>
          report.id === reportId ? { ...report, ...data.report } : report,
        ),
      );
    } catch (error) {
      console.error(error);
      window.alert("Could not update verification status -- check the backend connection.");
    }
  }

  function handleClearReports() {
    setReports([]);
    if (storageKey) {
      localStorage.removeItem(storageKey);
    }
  }

  if (!hasSelectedArea) {
    return (
      <section className="panel ground-truth-panel" id="community-ground-truth">
        <div className="section-heading">
          <h2>Community Ground-Truth Reports</h2>
          <p>
            Select a priority intervention area to collect local verification
            reports for the active forecast advisory.
          </p>
        </div>

        <div className="ground-truth-empty-state">
          <h3>No selected area</h3>
          <p>
            Click <strong>View on map</strong> in the Priority Intervention Areas
            table. Community reports will then be linked to that selected area,
            hazard, risk level, and forecast lead.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel ground-truth-panel" id="community-ground-truth">
      <div className="ground-truth-header">
        <div>
          <h2>Community Ground-Truth Reports</h2>
          <p>
            Collect local field observations to verify whether forecast impacts
            are emerging in the selected priority area.
          </p>
          <p className="map-selected-area">
            Active area:{" "}
            <strong>
              {selectedPriorityArea.area_name} ·{" "}
              {forecastSelection.hazardRiskPeriodLabel || getLeadLabel(forecastSelection.lead)} ·{" "}
              {titleCase(selectedPriorityArea.hazard)}
            </strong>
          </p>
        </div>

        <div className={`ground-signal-badge ${signalSummary.className}`}>
          <span>{signalSummary.signal}</span>
          <strong>{signalSummary.total} reports</strong>
        </div>
      </div>

      <div className="ground-truth-summary-grid">
        <div>
          <span>Administrative level</span>
          <strong>{getAdminLevelLabel(selectedPriorityArea.admin_level)}</strong>
        </div>

        <div>
          <span>Risk level</span>
          <strong>{titleCase(selectedPriorityArea.risk_level)}</strong>
        </div>

        <div>
          <span>High / severe reports</span>
          <strong>{signalSummary.highOrSevere}</strong>
        </div>

        <div>
          <span>Message language</span>
          <strong>{LANGUAGE_LABELS[selectedLanguage] || "English"}</strong>
        </div>
      </div>

      <div className="ground-truth-layout">
        <form className="ground-truth-form" onSubmit={handleSubmit}>
          <h3>Submit local observation</h3>

          <div className="report-form-grid">
            <div className="form-field">
              <label htmlFor="ground-reporter-role">Reporter role</label>
              <select
                id="ground-reporter-role"
                value={form.reporter_role}
                onChange={(event) => updateField("reporter_role", event.target.value)}
              >
                <option value="community_focal_point">Community focal point</option>
                <option value="extension_worker">Extension worker</option>
                <option value="kebele_official">Kebele official</option>
                <option value="woreda_sector_office">Woreda sector office</option>
                <option value="ngo_partner">NGO / partner</option>
                <option value="other">Other</option>
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="ground-location-detail">Location detail</label>
              <input
                id="ground-location-detail"
                value={form.location_detail}
                onChange={(event) => updateField("location_detail", event.target.value)}
                placeholder="Kebele, village, water point, road segment..."
              />
            </div>

            <div className="form-field">
              <label htmlFor="ground-report-type">Observation type</label>
              <select
                id="ground-report-type"
                value={form.report_type}
                onChange={(event) => updateField("report_type", event.target.value)}
              >
                {REPORT_TYPES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="ground-severity">Observed severity</label>
              <select
                id="ground-severity"
                value={form.severity}
                onChange={(event) => updateField("severity", event.target.value)}
              >
                {SEVERITY_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="ground-confidence">Report confidence</label>
              <select
                id="ground-confidence"
                value={form.confidence}
                onChange={(event) => updateField("confidence", event.target.value)}
              >
                {CONFIDENCE_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="ground-contact">Contact or source</label>
              <input
                id="ground-contact"
                value={form.contact}
                onChange={(event) => updateField("contact", event.target.value)}
                placeholder="Optional phone, name, office, or partner"
              />
            </div>
          </div>

          <div className="form-field">
            <label htmlFor="ground-description">Observation description</label>
            <textarea
              id="ground-description"
              value={form.description}
              onChange={(event) => updateField("description", event.target.value)}
              placeholder="Describe what is happening locally and what evidence is available..."
              required
            />
          </div>

          <button type="submit" className="primary-button">
            Submit ground-truth report
          </button>
        </form>

        <div className="ground-truth-list">
          <div className="ground-truth-list-header">
            <div>
              <h3>Recent reports</h3>
              <p>
                {usingLocalFallback
                  ? "Backend unreachable -- reports are stored locally in this browser until the connection is restored."
                  : "Reports are stored on the server for this district and feed the app's community-evidence signal."}
              </p>
            </div>

            <div className="ground-truth-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() =>
                  downloadReportsCsv(selectedPriorityArea, forecastSelection, reports)
                }
                disabled={reports.length === 0}
              >
                Export CSV
              </button>

              <button
                type="button"
                className="secondary-button"
                onClick={handleClearReports}
                disabled={reports.length === 0}
              >
                Clear
              </button>
            </div>
          </div>

          {reports.length === 0 ? (
            <div className="ground-truth-empty-list">
              No reports submitted yet for this selected area.
            </div>
          ) : (
            <div className="ground-truth-report-cards">
              {reports.map((report) => (
                <article key={report.id} className="ground-truth-report-card">
                  <div className="ground-report-card-header">
                    <div>
                      <h4>{getReportTypeLabel(report.report_type)}</h4>
                      <p>
                        {report.location_detail || selectedPriorityArea.area_name} ·{" "}
                        {new Date(report.submitted_at).toLocaleString()}
                      </p>
                    </div>

                    <span className={`severity-pill ${getSeverityClass(report.severity)}`}>
                      {titleCase(report.severity)}
                    </span>
                  </div>

                  <p>{report.description}</p>

                  <div className="ground-report-meta">
                    <span>Reporter: {titleCase(report.reporter_role)}</span>
                    <span>Confidence: {titleCase(report.confidence)}</span>
                    {report.contact && <span>Source: {report.contact}</span>}
                    <span className={`verification-pill verification-${report.verification_status || "unverified"}`}>
                      {report.verification_status === "verified" &&
                        `Verified${report.verified_by ? ` by ${report.verified_by}` : ""}`}
                      {report.verification_status === "disputed" &&
                        `Disputed${report.verified_by ? ` by ${report.verified_by}` : ""}`}
                      {(!report.verification_status || report.verification_status === "unverified") &&
                        "Unverified"}
                    </span>
                  </div>

                  <div className="ground-report-card-actions">
                    {!usingLocalFallback && report.verification_status !== "verified" && (
                      <button
                        type="button"
                        className="table-link-button"
                        onClick={() => handleVerifyReport(report.id, "verified")}
                      >
                        Mark verified
                      </button>
                    )}
                    {!usingLocalFallback && report.verification_status !== "disputed" && (
                      <button
                        type="button"
                        className="table-link-button"
                        onClick={() => handleVerifyReport(report.id, "disputed")}
                      >
                        Dispute
                      </button>
                    )}
                    <button
                      type="button"
                      className="table-link-button"
                      onClick={() => handleDeleteReport(report.id)}
                    >
                      Delete report
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>

      <p className="intervention-method-note">
        Ground-truth reports are used to validate whether forecast risks are
        becoming real impacts. A production version can synchronize these reports
        with SMS, WhatsApp, Kobo, ODK, DHIS2, CRM, or partner field-reporting
        systems.
      </p>
    </section>
  );
}

export default SelectedAreaCommunityReports;
