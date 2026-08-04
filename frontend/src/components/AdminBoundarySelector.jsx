import { useEffect, useMemo, useRef, useState } from "react";
import { apiUrl } from "../config.js";

// This app only ever covers Ethiopia, so there's exactly one Country option
// -- it exists as its own tier (rather than folded into "no selection") so
// it can carry the same explicit-intent behavior as "All zones"/"All
// woredas": picking it means "show the whole-country admin0 boundary",
// synchronized with Region/Zone/Woreda via the same selectedLevel mechanism
// (see getBoundaryLevel below).
const COUNTRY_OPTIONS = [{ value: "ethiopia", label: "Ethiopia" }];
const DEFAULT_COUNTRY_ID = COUNTRY_OPTIONS[0].value;

// Region/Zone/Woreda need THREE distinct states, not two: genuinely
// unselected (blank placeholder, "" -- the true default, doesn't turn the
// tier on), explicitly "All regions/zones/woredas" (a real, deliberate
// choice that DOES turn the tier on, showing every area at that level), and
// a specific area. Reusing "" for both "unselected" and "All X" (the old
// behavior) made the dropdown look pre-selected by default even though
// nothing had been chosen -- this sentinel gives "All X" its own value so
// "" can mean only "nothing chosen yet".
const ALL_VALUE = "__all__";

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

// Which selector the user most recently interacted with -- NOT the same as
// which IDs are currently set. Picking "All zones" from the Zone dropdown
// still leaves selectedZoneId === "" (same as never having touched it), so
// deriving the admin level purely from ID presence can't tell "show
// zone-level detail for everything" apart from "nothing chosen yet, stay at
// region level". Tracking intent explicitly lets "All zones"/"All woredas"
// mean what they say: admin2/admin3 boundaries for whatever region/zone
// scope is (or isn't) set, rather than silently falling back to admin1.
function getBoundaryLevel(selectedLevel) {
  if (selectedLevel === "woreda") {
    return "admin3";
  }

  if (selectedLevel === "zone") {
    return "admin2";
  }

  if (selectedLevel === "country") {
    return "admin0";
  }

  return "admin1";
}

function findLabel(options, value) {
  const match = options.find((item) => item.value === value);
  return match?.label || "";
}

function AdminBoundarySelector({
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
  const [selectedCountryId, setSelectedCountryId] =
    useState(DEFAULT_COUNTRY_ID);
  const [selectedRegionId, setSelectedRegionId] = useState("");
  const [selectedZoneId, setSelectedZoneId] = useState("");
  const [selectedWoredaId, setSelectedWoredaId] = useState("");
  // "country" | "region" | "zone" | "woreda" -- see getBoundaryLevel above
  // for why this is tracked separately from the selected IDs themselves.
  // Defaults to "country" (not "region") so the initial view -- before the
  // user has touched Region/Zone/Woreda at all -- matches what the Country
  // selector already shows ("Ethiopia"): just the national outline, not
  // every region's boundary at once. Region/Zone/Woreda only take over
  // (become "active") once the user actually changes one of them.
  const [selectedLevel, setSelectedLevel] = useState("country");
  const [boundaryLoading, setBoundaryLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const hasActiveSelection =
    selectedRegionId !== "" ||
    selectedZoneId !== "" ||
    selectedWoredaId !== "" ||
    selectedLevel !== "country";

  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);

  useEffect(() => {
    onClearPrioritySelectionRef.current = onClearPrioritySelection;
  }, [onClearPrioritySelection]);

  const filteredZones = useMemo(() => {
    if (!selectedRegionId || selectedRegionId === ALL_VALUE) {
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

      if (
        selectedRegionId &&
        selectedRegionId !== ALL_VALUE &&
        itemRegionId !== selectedRegionId
      ) {
        return false;
      }

      if (
        selectedZoneId &&
        selectedZoneId !== ALL_VALUE &&
        itemZoneId !== selectedZoneId
      ) {
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
        const level = getBoundaryLevel(selectedLevel);

        const params = new URLSearchParams();
        params.set("level", level);

        if (selectedRegionId && selectedRegionId !== ALL_VALUE) {
          params.set("region_id", selectedRegionId);
        }

        if (selectedZoneId && selectedZoneId !== ALL_VALUE) {
          params.set("zone_id", selectedZoneId);
        }

        if (selectedWoredaId && selectedWoredaId !== ALL_VALUE) {
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

        const countryLabel = findLabel(COUNTRY_OPTIONS, selectedCountryId);
        const regionLabel = findLabel(adminOptions.regions, selectedRegionId);
        const zoneLabel = findLabel(adminOptions.zones, selectedZoneId);
        const woredaLabel = findLabel(adminOptions.woredas, selectedWoredaId);

        if (typeof onSelectionChangeRef.current === "function") {
          onSelectionChangeRef.current({
            countryId: selectedCountryId,
            regionId: selectedRegionId,
            zoneId: selectedZoneId,
            woredaId: selectedWoredaId,
            countryLabel,
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
    selectedCountryId,
    selectedRegionId,
    selectedZoneId,
    selectedWoredaId,
    selectedLevel,
    adminOptions.regions,
    adminOptions.zones,
    adminOptions.woredas,
  ]);

  function clearPrioritySelection() {
    if (typeof onClearPrioritySelectionRef.current === "function") {
      onClearPrioritySelectionRef.current();
    }
  }

  function handleCountryChange(event) {
    setSelectedCountryId(event.target.value);
    setSelectedRegionId("");
    setSelectedZoneId("");
    setSelectedWoredaId("");
    setSelectedLevel("country");
    clearPrioritySelection();
  }

  function handleRegionChange(event) {
    const value = event.target.value;
    setSelectedRegionId(value);
    setSelectedZoneId("");
    setSelectedWoredaId("");
    // Picking the blank placeholder again clears Region back to "not
    // chosen", which falls back to the Country-level view -- any other
    // value (a specific region, or the explicit "All regions" option) turns
    // Region on.
    setSelectedLevel(value === "" ? "country" : "region");
    clearPrioritySelection();
  }

  function handleZoneChange(event) {
    const value = event.target.value;
    setSelectedZoneId(value);
    setSelectedWoredaId("");
    // Same clear-vs-choose logic as Region, but falls back to Region-level
    // (using whatever Region is currently set to) instead of Country.
    setSelectedLevel(value === "" ? "region" : "zone");
    clearPrioritySelection();
  }

  function handleWoredaChange(event) {
    const value = event.target.value;
    setSelectedWoredaId(value);
    setSelectedLevel(value === "" ? "zone" : "woreda");
    clearPrioritySelection();
  }

  function handleResetSelection() {
    setSelectedCountryId(DEFAULT_COUNTRY_ID);
    setSelectedRegionId("");
    setSelectedZoneId("");
    setSelectedWoredaId("");
    setSelectedLevel("country");
    setErrorMessage("");
    clearPrioritySelection();
  }

  return (
    <section className="panel admin-selector-panel">
      <div className="admin-selector-header">
        <div>
          <h2>Administrative Area</h2>
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
          <label htmlFor="shared-country-select">Select Country</label>
          <select
            id="shared-country-select"
            value={selectedCountryId}
            onChange={handleCountryChange}
          >
            {COUNTRY_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="map-control">
          <label htmlFor="shared-region-select">Select Region</label>
          <select
            id="shared-region-select"
            value={selectedRegionId}
            onChange={handleRegionChange}
          >
            <option value=""></option>
            <option value={ALL_VALUE}>All regions</option>
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
          >
            <option value=""></option>
            <option value={ALL_VALUE}>All zones</option>
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
          >
            <option value=""></option>
            <option value={ALL_VALUE}>All woredas</option>
            {filteredWoredas.map((item) => (
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
