import { useEffect, useMemo, useRef, useState } from "react";
import { apiUrl } from "../config.js";

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "am", label: "Amharic" },
  { value: "om", label: "Oromifa / Afaan Oromo" },
  { value: "ti", label: "Tigrinya" },
  { value: "so", label: "Somali" },
];

function normalizeOption(item, fallbackPrefix = "") {
  if (typeof item === "string") {
    return {
      value: item,
      label: item,
    };
  }

  return {
    ...item,
    value:
      item.value ||
      item.id ||
      item.code ||
      item.region_id ||
      item.zone_id ||
      item.woreda_id ||
      item.name ||
      `${fallbackPrefix}-${Math.random()}`,
    label:
      item.label ||
      item.name ||
      item.region ||
      item.zone ||
      item.woreda ||
      item.value ||
      item.id ||
      "Unnamed",
  };
}

function normalizeOptions(values, fallbackPrefix = "") {
  if (!Array.isArray(values)) {
    return [];
  }

  return values.map((item) => normalizeOption(item, fallbackPrefix));
}

function getOptionsList(data, key) {
  if (Array.isArray(data?.[key])) {
    return data[key];
  }

  if (Array.isArray(data?.options?.[key])) {
    return data.options[key];
  }

  if (Array.isArray(data?.data?.[key])) {
    return data.data[key];
  }

  return [];
}

function getBoundaryLevel(regionId, zoneId, woredaId) {
  if (woredaId) {
    return "admin3";
  }

  if (zoneId) {
    return "admin2";
  }

  if (regionId) {
    return "admin1";
  }

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
  onClearPrioritySelection,
}) {
  const onSelectionChangeRef = useRef(onSelectionChange);
  const onClearPrioritySelectionRef = useRef(onClearPrioritySelection);

  const [adminOptions, setAdminOptions] = useState({
    regions: [],
    zones: [],
    woredas: [],
  });

  const [optionsLoaded, setOptionsLoaded] = useState(false);
  const [selectedRegionId, setSelectedRegionId] = useState("");
  const [selectedZoneId, setSelectedZoneId] = useState("");
  const [selectedWoredaId, setSelectedWoredaId] = useState("");
  const [boundaryLoading, setBoundaryLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const hasActiveSelection =
    selectedRegionId !== "" || selectedZoneId !== "" || selectedWoredaId !== "";

  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);

  useEffect(() => {
    onClearPrioritySelectionRef.current = onClearPrioritySelection;
  }, [onClearPrioritySelection]);

  const filteredZones = useMemo(() => {
    if (!selectedRegionId) {
      return adminOptions.zones || [];
    }

    return (adminOptions.zones || []).filter((item) => {
      return (
        item.region_id === selectedRegionId ||
        item.regionId === selectedRegionId
      );
    });
  }, [adminOptions.zones, selectedRegionId]);

  const filteredWoredas = useMemo(() => {
    return (adminOptions.woredas || []).filter((item) => {
      const itemRegionId = item.region_id || item.regionId || "";
      const itemZoneId = item.zone_id || item.zoneId || "";

      if (selectedRegionId && itemRegionId !== selectedRegionId) {
        return false;
      }

      if (selectedZoneId && itemZoneId !== selectedZoneId) {
        return false;
      }

      return true;
    });
  }, [adminOptions.woredas, selectedRegionId, selectedZoneId]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadAdminOptions() {
      setErrorMessage("");

      try {
        const response = await fetch(apiUrl("/api/admin-boundaries/options"), {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Admin options request failed: ${response.status}`);
        }

        const data = await response.json();

        setAdminOptions({
          regions: normalizeOptions(getOptionsList(data, "regions"), "region"),
          zones: normalizeOptions(getOptionsList(data, "zones"), "zone"),
          woredas: normalizeOptions(getOptionsList(data, "woredas"), "woreda"),
        });

        setOptionsLoaded(true);
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error(error);
          setErrorMessage(
            "Could not load Ethiopia administrative boundary options. Check the backend /api/admin-boundaries/options endpoint.",
          );
          setOptionsLoaded(false);
        }
      }
    }

    loadAdminOptions();

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!optionsLoaded) {
      return;
    }

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

        if (selectedRegionId) {
          params.set("region_id", selectedRegionId);
        }

        if (selectedZoneId) {
          params.set("zone_id", selectedZoneId);
        }

        if (selectedWoredaId) {
          params.set("woreda_id", selectedWoredaId);
        }

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

        if (typeof onSelectionChangeRef.current === "function") {
          onSelectionChangeRef.current({
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
          setErrorMessage(
            "Could not load selected administrative boundary. Check the backend /api/admin-boundaries/geojson endpoint.",
          );
        }
      } finally {
        setBoundaryLoading(false);
      }
    }

    loadBoundary();

    return () => controller.abort();
  }, [
    optionsLoaded,
    selectedRegionId,
    selectedZoneId,
    selectedWoredaId,
    adminOptions.regions,
    adminOptions.zones,
    adminOptions.woredas,
  ]);

  function clearPrioritySelection() {
    if (typeof onClearPrioritySelectionRef.current === "function") {
      onClearPrioritySelectionRef.current();
    }
  }

  function handleRegionChange(event) {
    setSelectedRegionId(event.target.value);
    setSelectedZoneId("");
    setSelectedWoredaId("");
    clearPrioritySelection();
  }

  function handleZoneChange(event) {
    setSelectedZoneId(event.target.value);
    setSelectedWoredaId("");
    clearPrioritySelection();
  }

  function handleWoredaChange(event) {
    setSelectedWoredaId(event.target.value);
    clearPrioritySelection();
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
    clearPrioritySelection();
  }

  return (
    <section className="panel admin-selector-panel">
      <div className="admin-selector-header">
        <div>
          <h2>Administrative Area Selection</h2>
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
