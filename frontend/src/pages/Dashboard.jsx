import { useEffect, useState } from "react";
import AdminBoundarySelector from "../components/AdminBoundarySelector.jsx";
import DashboardHero from "../components/DashboardHero.jsx";
import ForecastLayerMap from "../components/ForecastLayerMap.jsx";
import AIMapInterpretation from "../components/AIMapInterpretation.jsx";
import RiskMap from "../components/RiskMap.jsx";
import TopInterventionAreas from "../components/TopInterventionAreas.jsx";
import SelectedAreaAdvisory from "../components/SelectedAreaAdvisory.jsx";
import ActionImplementationTracker from "../components/ActionImplementationTracker.jsx";
import SelectedAreaCommunityReports from "../components/SelectedAreaCommunityReports.jsx";
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
  const [riskData, setRiskData] = useState([]);
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
  const [forecastSelection, setForecastSelection] = useState({
    forecastScale: "subseasonal",
    lead: "week_1",
    layer: "risk_score",
    indicator: "spi",
  });
  const [selectedPriorityArea, setSelectedPriorityArea] = useState(null);
  async function loadRiskData() {
    try {
      const response = await fetchJson("/api/risk");
      const items = safeArray(response, [
        "risk_data",
        "data",
        "items",
        "districts",
      ]);
      setRiskData(items);
      return items;
    } catch (error) {
      console.error(error);
      setRiskData([]);
      return [];
    }
  }
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
      await Promise.all([loadRiskData(), loadCommunityReports()]);
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
        riskItems={riskData}
        communityReports={communityReports}
        selectedPriorityArea={selectedPriorityArea}
        forecastSelection={forecastSelection}
        priorityInterventionCount={3}
      />
      {loading && (
        <div className="status-banner">Loading dashboard summary data...</div>
      )}
      {errorMessage && <div className="error-banner">{errorMessage}</div>}
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
      <AIMapInterpretation
        forecastSelection={forecastSelection}
        adminSelection={adminSelection}
        selectedPriorityArea={selectedPriorityArea}
        selectedLanguage={selectedLanguage}
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
