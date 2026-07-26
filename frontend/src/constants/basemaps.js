// Shared basemap tile providers for every Leaflet map in the app (Seasonal
// Climate Indices, Hazard/Risk Layers, Priority Intervention Areas map).
// Rendered via react-leaflet's <LayersControl> so each map gets the same
// native Leaflet base-layer switcher UI. All four are free, no API key
// required.
export const BASEMAP_OPTIONS = [
  {
    value: "osm",
    label: "OpenStreetMap",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  },
  {
    value: "satellite",
    label: "Satellite",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution:
      "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    maxZoom: 19,
  },
  {
    value: "topographic",
    label: "Topographic",
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution:
      "Map data: &copy; OpenStreetMap contributors, SRTM &mdash; Map style: &copy; OpenTopoMap (CC-BY-SA)",
    maxZoom: 17,
  },
  {
    value: "dark",
    label: "Dark",
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    maxZoom: 19,
  },
];

export const DEFAULT_BASEMAP_VALUE = BASEMAP_OPTIONS[0].value;
