import { useEffect, useState } from "react";
import AdminBoundarySelector from "../components/AdminBoundarySelector.jsx";
import ChatWidget from "../components/ChatWidget.jsx";
import DashboardHero from "../components/DashboardHero.jsx";
import ForecastLayerMap from "../components/ForecastLayerMap.jsx";
import AIMapInterpretation from "../components/AIMapInterpretation.jsx";
import RiskMap from "../components/RiskMap.jsx";
import TopInterventionAreas from "../components/TopInterventionAreas.jsx";
import SelectedAreaAdvisory from "../components/SelectedAreaAdvisory.jsx";
import SelectedAreaCommunityReports from "../components/SelectedAreaCommunityReports.jsx";
import ActionImplementationTracker from "../components/ActionImplementationTracker.jsx";
import { apiUrl } from "../config.js";

function safeArray(response, keys = []) {
  if (Array.isArray(response)) return response;
  for (const key of keys) {
    if (Array.isArray(response?.[key])) return response[key];
  }
  return [];
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
  const [communityReports, setCommunityReports] = useState([]);
  const [selectedLanguage, setSelectedLanguage] = useState("en");
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
  // Matches ForecastLayerMap.jsx's own INITIAL_SEASONAL_STATE default
  // (indicator: "rainfall_total", the first entry in the canonical
  // CLIMATE_INDICATORS list) so the very first paint -- before
  // ForecastLayerMap's effect overwrites this via
  // onForecastSelectionChange -- already agrees with what the map and
  // SelectedAreaAdvisory's cards will show, instead of a momentarily
  // inconsistent placeholder.
  const [forecastSelection, setForecastSelection] = useState({
    forecastScale: "subseasonal",
    lead: "week_1",
    layer: "risk_score",
    indicator: "rainfall_total",
  });
  const [selectedPriorityArea, setSelectedPriorityArea] = useState(null);
  const [rankingContext, setRankingContext] = useState(null);
  // Lifted from AIMapInterpretation (via onReportChange) so the chat
  // assistant can see the real, already-generated report narrative once
  // one exists, instead of only the raw evidence it recomputes itself.
  const [aiReport, setAiReport] = useState(null);
  // Lifted from AIMapInterpretation (via onContextBuilt) so the action
  // tracker can serve real, context-linked tasks (see
  // /api/action-tracker/{district}?context_id=...) instead of falling back
  // to the legacy district-CSV path, which has no real current area names.
  const [contextId, setContextId] = useState(null);
  async function loadCommunityReports() {
    try {
      const response = await fetchJson("/api/community-reports");
      const items = safeArray(response, ["reports", "data", "items"]);
      setCommunityReports(items);
      return items;
    } catch (error) {
      console.error(error);
      setCommunityReports([]);
      return [];
    }
  }
  async function loadDashboardSummary() {
    setLoading(true);
    setErrorMessage("");
    try {
      await Promise.all([loadCommunityReports()]);
    } catch (error) {
      console.error(error);
      setErrorMessage(
        "Could not load dashboard summary data. Check that the backend URL is correct and reachable.",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    loadDashboardSummary();
  }, []);
  return (
    <main className="app-shell">
      <DashboardHero
        communityReports={communityReports}
        selectedPriorityArea={selectedPriorityArea}
        forecastSelection={forecastSelection}
        priorityInterventionCount={rankingContext?.rankingCount}
        triggerAlertCount={rankingContext?.triggerCount}
        topRankedArea={rankingContext?.topRankedArea}
      />
      {loading && (
        <div className="status-banner">Loading dashboard summary data...</div>
      )}
      {errorMessage && <div className="error-banner">{errorMessage}</div>}
      <AdminBoundarySelector
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
        onRankingContextChange={setRankingContext}
      />
      <RiskMap
        adminSelection={adminSelection}
        selectedPriorityArea={selectedPriorityArea}
        rankingContext={rankingContext}
      />
      {/* Only activates once an area is selected via "View on map" in the
          Priority Intervention Areas table above -- and sits above the AI
          Map Interpretation & Advisory section, not inside/below it. */}
      {selectedPriorityArea && (
        <SelectedAreaAdvisory
          selectedPriorityArea={selectedPriorityArea}
          forecastSelection={forecastSelection}
          selectedLanguage={selectedLanguage}
        />
      )}
      {/* Submitted here, right before AI Map Interpretation & Advisory, so
          it reads as feeding into that section -- and it genuinely does:
          run_staged_report_generation pulls real, fresh community reports
          into Stage 2 via build_community_evidence_by_region (see
          app/context/community_context.py), so a report submitted here is
          already part of the AI-generated advisory below on the next
          "Generate report" click. */}
      <SelectedAreaCommunityReports
        selectedPriorityArea={selectedPriorityArea}
        forecastSelection={forecastSelection}
        selectedLanguage={selectedLanguage}
      />
      <AIMapInterpretation
        forecastSelection={forecastSelection}
        adminSelection={adminSelection}
        selectedPriorityArea={selectedPriorityArea}
        selectedLanguage={selectedLanguage}
        onLanguageChange={setSelectedLanguage}
        onReportChange={setAiReport}
        onContextBuilt={({ contextId: builtContextId }) => setContextId(builtContextId)}
      />
      {selectedPriorityArea && (
        <ActionImplementationTracker
          selectedPriorityArea={selectedPriorityArea}
          forecastSelection={forecastSelection}
          contextId={contextId}
        />
      )}
      <ChatWidget
        forecastSelection={forecastSelection}
        selectedPriorityArea={selectedPriorityArea}
        selectedLanguage={selectedLanguage}
        aiReport={aiReport}
      />
    </main>
  );
}
export default Dashboard;
