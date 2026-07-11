import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config.js";

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "am", label: "Amharic" },
  { value: "sw", label: "Swahili" },
];

function getBoundaryLevel(regionId, zoneId, woredaId) {
  if (woredaId) return "admin3";
  if (zoneId) return "admin3";
  if (regionId) return "admin2";
  return "admin1";
}

function findLabel(options, value) {
  const match = options.find((item) => item.value === value);
  return match?.label || "";
}

function AdminBoundarySelector({
  selectedLanguage = "en",
  onLanguageChange,
  onSelectionChange,
}) {
  const [adminOptions, setAdminOptions] = useState({
    regions: [],
    zones: [],
    woredas: [],
  });

  const [selectedRegionId, setSelectedRegionId] = useState("");
  const [selectedZoneId, setSelectedZoneId] = useState("");
  const [selectedWoredaId, setSelectedWoredaId] = useState("");
  const [boundaryLoading, setBoundaryLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const hasActiveSelection =
    selectedRegionId !== "" || selectedZoneId !== "" || selectedWoredaId !== "";

  const filteredZones = useMemo(() => {
    if (!selectedRegionId) return adminOptions.zones || [];

    return (adminOptions.zones || []).filter(
      (item) => item.region_id === selectedRegionId,
    );
  }, [adminOptions.zones, selectedRegionId]);

  const filteredWoredas = useMemo(() => {
    return (adminOptions.woredas || []).filter((item) => {
      if (selectedRegionId && item.region_id !== selectedRegionId) return false;
      if (selectedZoneId && item.zone_id !== selectedZoneId) return false;
      return true;
    });
  }, [adminOptions.woredas, selectedRegionId, selectedZoneId]);

  useEffect(() => {
    async function loadAdminOptions() {
      try {
        const response = await fetch(apiUrl("/api/admin-boundaries/options"));

        if (!response.ok) {
          throw new Error(`Admin options request failed: ${response.status}`);
        }

        const data = await response.json();

        setAdminOptions({
          regions: data.regions || [],
          zones: data.zones || [],
          woredas: data.woredas || [],
        });
      } catch (error) {
        console.error(error);
        setErrorMessage(
          "Could not load Ethiopia administrative boundary options.",
        );
      }
    }

    loadAdminOptions();
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadBoundary() {
      setBoundaryLoading(true);
      setErrorMessage("");

      try {
        const level = getBoundaryLevel(
          selectedRegionId,
          selectedZoneId,
          selectedWoredaId,
        );

        const params = new URLSearchParams();
        params.set("level", level);

        if (selectedRegionId) params.set("region_id", selectedRegionId);
        if (selectedZoneId) params.set("zone_id", selectedZoneId);
        if (selectedWoredaId) params.set("woreda_id", selectedWoredaId);

        const response = await fetch(
          apiUrl(`/api/admin-boundaries/geojson?${params.toString()}`),
          { signal: controller.signal },
        );

        if (!response.ok) {
          throw new Error(`Boundary request failed: ${response.status}`);
        }

        const boundaryGeojson = await response.json();

        const regionLabel = findLabel(adminOptions.regions, selectedRegionId);
        const zoneLabel = findLabel(adminOptions.zones, selectedZoneId);
        const woredaLabel = findLabel(adminOptions.woredas, selectedWoredaId);

        if (typeof onSelectionChange === "function") {
          onSelectionChange({
            regionId: selectedRegionId,
            zoneId: selectedZoneId,
            woredaId: selectedWoredaId,
            regionLabel,
            zoneLabel,
            woredaLabel,
            boundaryLevel: level,
            boundaryGeojson,
            boundaryLoading: false,
          });
        }
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
          setErrorMessage("Could not load selected boundary.");
        }
      } finally {
        setBoundaryLoading(false);
      }
    }

    loadBoundary();

    return () => controller.abort();
  }, [
    selectedRegionId,
    selectedZoneId,
    selectedWoredaId,
    adminOptions.regions,
    adminOptions.zones,
    adminOptions.woredas,
    onSelectionChange,
  ]);

  function handleRegionChange(event) {
    setSelectedRegionId(event.target.value);
    setSelectedZoneId("");
    setSelectedWoredaId("");
  }

  function handleZoneChange(event) {
    setSelectedZoneId(event.target.value);
    setSelectedWoredaId("");
  }

  function handleWoredaChange(event) {
    setSelectedWoredaId(event.target.value);
  }

  function handleLanguageChange(event) {
    if (typeof onLanguageChange === "function") {
      onLanguageChange(event.target.value);
    }
  }

  function handleResetSelection() {
    setSelectedRegionId("");
    setSelectedZoneId("");
    setSelectedWoredaId("");
    setErrorMessage("");
  }

  return (
    <section className="panel admin-selector-panel">
      <div className="admin-selector-header">
        <div>
          <h2>Administrative Area Selection</h2>
          <p>
            One shared Region, Zone and Woreda selector controls both the
            Forecast Risk Layers and the Interactive Administrative Risk Map.
          </p>
        </div>

        <div className="admin-selector-actions">
          {boundaryLoading && (
            <span className="admin-loading-badge">Loading boundary...</span>
          )}

          <button
            type="button"
            className="reset-map-button"
            onClick={handleResetSelection}
            disabled={!hasActiveSelection}
          >
            Reset Map View
          </button>
        </div>
      </div>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      <div className="map-admin-controls shared-admin-controls">
        <div className="map-control">
          <label htmlFor="shared-region-select">Select Region</label>
          <select
            id="shared-region-select"
            value={selectedRegionId}
            onChange={handleRegionChange}
          >
            <option value="">All regions</option>
            {adminOptions.regions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="map-control">
          <label htmlFor="shared-zone-select">Select Zone</label>
          <select
            id="shared-zone-select"
            value={selectedZoneId}
            onChange={handleZoneChange}
            disabled={!selectedRegionId}
          >
            <option value="">All zones</option>
            {filteredZones.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="map-control">
          <label htmlFor="shared-woreda-select">Select Woreda</label>
          <select
            id="shared-woreda-select"
            value={selectedWoredaId}
            onChange={handleWoredaChange}
            disabled={!selectedZoneId}
          >
            <option value="">All woredas</option>
            {filteredWoredas.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="map-control">
          <label htmlFor="shared-language-select">
            Community message language
          </label>
          <select
            id="shared-language-select"
            value={selectedLanguage}
            onChange={handleLanguageChange}
          >
            {LANGUAGE_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}

export default AdminBoundarySelector;
