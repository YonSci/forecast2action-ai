import { useEffect, useMemo, useState } from "react";

const STATUS_OPTIONS = [
  "Not started",
  "In progress",
  "Completed",
  "Verified",
  "Delayed",
];

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

function titleCase(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (text) => text.charAt(0).toUpperCase() + text.substring(1).toLowerCase());
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

function getDeadline(riskLevel, actionType) {
  if (actionType === "public_message") return "Within 24 hours";
  if (riskLevel === "trigger") return "Within 72 hours";
  if (riskLevel === "warning") return "Within 7 days";
  if (riskLevel === "watch") return "Within 14 days";
  return "Routine monitoring";
}

function getResponsibleSector(hazard, actionType) {
  if (actionType === "public_message") return "Local administration / DRM communication";
  if (actionType === "verification") return "Woreda DRM / kebele focal points / extension workers";
  if (actionType === "coordination") return "DRM, agriculture, water, health, livestock, and partners";

  if (actionType === "resource") {
    if (hazard === "drought" || hazard === "dry_spell") {
      return "Water, agriculture, livestock, DRM, and local administration";
    }
    if (hazard === "heavy_rainfall" || hazard === "wet_spell" || hazard === "flood") {
      return "DRM, roads, water, health, and local administration";
    }
    return "Sector offices and local administration";
  }

  return "DRM and local administration";
}

function buildGeneratedTasks(area, forecastSelection) {
  const areaName = area?.area_name || "Selected area";
  const riskLevel = area?.risk_level || "watch";
  const hazard = area?.hazard || "drought";
  const lead = getLeadLabel(forecastSelection?.lead);

  const tasks = [
    {
      id: "verify-local-conditions",
      action: `Verify local ${titleCase(hazard)} conditions in ${areaName}`,
      responsible_sector: getResponsibleSector(hazard, "verification"),
      deadline: getDeadline(riskLevel, "verification"),
      status: "Not started",
      progress_note: "",
      verification_source: "",
      evidence_required: "Field confirmation, kebele focal point report, or community feedback.",
    },
    {
      id: "send-community-message",
      action: `Send SMS / WhatsApp early warning message for ${lead}`,
      responsible_sector: getResponsibleSector(hazard, "public_message"),
      deadline: getDeadline(riskLevel, "public_message"),
      status: "Not started",
      progress_note: "",
      verification_source: "",
      evidence_required: "Screenshot, distribution log, partner confirmation, or message dispatch record.",
    },
    {
      id: "coordinate-early-action",
      action: "Coordinate early-action meeting with responsible sector offices",
      responsible_sector: getResponsibleSector(hazard, "coordination"),
      deadline: getDeadline(riskLevel, "coordination"),
      status: "Not started",
      progress_note: "",
      verification_source: "",
      evidence_required: "Meeting note, participant list, decision log, or coordination update.",
    },
    {
      id: "check-sector-impacts",
      action:
        hazard === "heavy_rainfall" || hazard === "wet_spell" || hazard === "flood"
          ? "Check flood-prone roads, drainage, water points, and vulnerable settlements"
          : "Check water points, pasture, livestock condition, and crop stress",
      responsible_sector: getResponsibleSector(hazard, "resource"),
      deadline: getDeadline(riskLevel, "resource"),
      status: "Not started",
      progress_note: "",
      verification_source: "",
      evidence_required: "Sector office update, field photo, observation checklist, or verified report.",
    },
    {
      id: "collect-ground-feedback",
      action: "Collect community ground-truth feedback and update advisory status",
      responsible_sector: "Extension workers / kebele focal points / community reporters",
      deadline: riskLevel === "trigger" ? "Within 7 days" : "Before next forecast update",
      status: "Not started",
      progress_note: "",
      verification_source: "",
      evidence_required: "Community report, field note, hotline report, or local partner confirmation.",
    },
  ];

  if (riskLevel === "trigger") {
    tasks.splice(3, 0, {
      id: "preposition-resources",
      action: "Prepare or pre-position priority resources for early action",
      responsible_sector: getResponsibleSector(hazard, "resource"),
      deadline: "Within 72 hours",
      status: "Not started",
      progress_note: "",
      verification_source: "",
      evidence_required: "Resource movement note, stock update, warehouse confirmation, or partner report.",
    });
  }

  return tasks;
}

function getStorageKey(area, forecastSelection) {
  return [
    "forecast2action-tracker",
    area?.admin_level || "admin",
    area?.region_id || "region",
    area?.zone_id || "zone",
    area?.woreda_id || area?.area_name || "area",
    area?.risk_level || "risk",
    area?.hazard || "hazard",
    forecastSelection?.forecastScale || "scale",
    forecastSelection?.lead || "lead",
  ].join("-");
}

function mergeSavedTasks(generatedTasks, savedTasks) {
  if (!Array.isArray(savedTasks) || savedTasks.length === 0) return generatedTasks;

  return generatedTasks.map((task) => {
    const saved = savedTasks.find((item) => item.id === task.id);
    if (!saved) return task;
    return {
      ...task,
      status: saved.status || task.status,
      progress_note: saved.progress_note || "",
      verification_source: saved.verification_source || "",
      last_updated: saved.last_updated || "",
    };
  });
}

function getStatusClass(status) {
  if (status === "Verified") return "tracker-status-verified";
  if (status === "Completed") return "tracker-status-completed";
  if (status === "In progress") return "tracker-status-progress";
  if (status === "Delayed") return "tracker-status-delayed";
  return "tracker-status-not-started";
}

function getCompletionSummary(tasks) {
  const total = tasks.length;
  const completed = tasks.filter((task) => ["Completed", "Verified"].includes(task.status)).length;
  const verified = tasks.filter((task) => task.status === "Verified").length;
  const delayed = tasks.filter((task) => task.status === "Delayed").length;
  return { total, completed, verified, delayed, percent: total > 0 ? Math.round((completed / total) * 100) : 0 };
}

function downloadCsv(filename, rows) {
  const headers = [
    "Area", "Admin level", "Lead", "Hazard", "Risk level", "Action",
    "Responsible sector", "Deadline", "Status", "Progress note",
    "Verification source", "Evidence required", "Last updated",
  ];

  const escapeCsv = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;

  const csv = [
    headers.map(escapeCsv).join(","),
    ...rows.map((row) => [
      row.area, row.admin_level, row.lead, row.hazard, row.risk_level,
      row.action, row.responsible_sector, row.deadline, row.status,
      row.progress_note, row.verification_source, row.evidence_required,
      row.last_updated,
    ].map(escapeCsv).join(",")),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function ActionImplementationTracker({ selectedPriorityArea = null, forecastSelection = {} }) {
  const hasSelectedArea = Boolean(selectedPriorityArea?.area_name);

  const generatedTasks = useMemo(() => {
    if (!hasSelectedArea) return [];
    return buildGeneratedTasks(selectedPriorityArea, forecastSelection);
  }, [hasSelectedArea, selectedPriorityArea, forecastSelection]);

  const storageKey = useMemo(() => {
    if (!hasSelectedArea) return "";
    return getStorageKey(selectedPriorityArea, forecastSelection);
  }, [hasSelectedArea, selectedPriorityArea, forecastSelection]);

  const [tasks, setTasks] = useState([]);

  useEffect(() => {
    if (!hasSelectedArea) {
      setTasks([]);
      return;
    }

    let savedTasks = [];
    try {
      savedTasks = JSON.parse(localStorage.getItem(storageKey) || "[]");
    } catch {
      savedTasks = [];
    }

    setTasks(mergeSavedTasks(generatedTasks, savedTasks));
  }, [hasSelectedArea, generatedTasks, storageKey]);

  useEffect(() => {
    if (!hasSelectedArea || !storageKey) return;
    localStorage.setItem(storageKey, JSON.stringify(tasks));
  }, [hasSelectedArea, storageKey, tasks]);

  const summary = getCompletionSummary(tasks);

  function updateTask(taskId, field, value) {
    setTasks((currentTasks) => currentTasks.map((task) => {
      if (task.id !== taskId) return task;
      return { ...task, [field]: value, last_updated: new Date().toISOString() };
    }));
  }

  function handleResetTasks() {
    setTasks(generatedTasks);
    if (storageKey) localStorage.removeItem(storageKey);
  }

  function handleExportCsv() {
    const rows = tasks.map((task) => ({
      area: selectedPriorityArea.area_name,
      admin_level: getAdminLevelLabel(selectedPriorityArea.admin_level),
      lead: getLeadLabel(forecastSelection.lead),
      hazard: titleCase(selectedPriorityArea.hazard),
      risk_level: titleCase(selectedPriorityArea.risk_level),
      ...task,
    }));

    const safeArea = String(selectedPriorityArea.area_name || "selected-area").replaceAll(" ", "_").toLowerCase();
    downloadCsv(`action_tracker_${safeArea}.csv`, rows);
  }

  if (!hasSelectedArea) {
    return (
      <section className="panel action-tracker-panel">
        <div className="section-heading">
          <h2>Action Implementation Tracker</h2>
          <p>Select a priority intervention area to generate and track early-action tasks.</p>
        </div>
        <div className="tracker-empty-state">
          <h3>No active action plan yet</h3>
          <p>
            Click <strong>View on map</strong> in the Priority Intervention Areas table.
            The tracker will generate tasks for the selected area, forecast lead, hazard, and risk level.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel action-tracker-panel">
      <div className="tracker-header">
        <div>
          <h2>Action Implementation Tracker</h2>
          <p>Tracks whether recommended early actions for the selected priority area are being implemented and verified.</p>
          <p className="map-selected-area">
            Active plan: <strong>{selectedPriorityArea.area_name} · {getLeadLabel(forecastSelection.lead)} · {titleCase(selectedPriorityArea.hazard)}</strong>
          </p>
        </div>
        <div className="tracker-actions">
          <button type="button" className="secondary-button" onClick={handleResetTasks}>Reset tasks</button>
          <button type="button" className="primary-button" onClick={handleExportCsv}>Export CSV</button>
        </div>
      </div>

      <div className="tracker-summary-grid">
        <div><span>Total tasks</span><strong>{summary.total}</strong></div>
        <div><span>Completed / verified</span><strong>{summary.completed}</strong></div>
        <div><span>Verified</span><strong>{summary.verified}</strong></div>
        <div><span>Delayed</span><strong>{summary.delayed}</strong></div>
        <div><span>Implementation progress</span><strong>{summary.percent}%</strong></div>
      </div>

      <div className="tracker-progress-bar"><span style={{ width: `${summary.percent}%` }} /></div>

      <div className="table-scroll">
        <table className="implementation-tracker-table">
          <thead>
            <tr>
              <th>Action</th>
              <th>Responsible sector</th>
              <th>Deadline</th>
              <th>Status</th>
              <th>Progress note</th>
              <th>Verification source</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td><strong>{task.action}</strong><br /><small>{task.evidence_required}</small></td>
                <td>{task.responsible_sector}</td>
                <td>{task.deadline}</td>
                <td>
                  <select
                    className={`tracker-status-select ${getStatusClass(task.status)}`}
                    value={task.status}
                    onChange={(event) => updateTask(task.id, "status", event.target.value)}
                  >
                    {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                </td>
                <td>
                  <textarea
                    value={task.progress_note}
                    placeholder="Add progress note..."
                    onChange={(event) => updateTask(task.id, "progress_note", event.target.value)}
                  />
                </td>
                <td>
                  <textarea
                    value={task.verification_source}
                    placeholder="Field report, photo, meeting note, message log..."
                    onChange={(event) => updateTask(task.id, "verification_source", event.target.value)}
                  />
                  {task.last_updated && <small>Updated: {new Date(task.last_updated).toLocaleString()}</small>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="intervention-method-note">
        Tracker logic: tasks are generated from the selected administrative area, forecast lead, hazard, and risk level. “Completed” records reported implementation; “Verified” requires supporting evidence from field reports, community feedback, partner confirmation, or dispatch records.
      </p>
    </section>
  );
}

export default ActionImplementationTracker;
