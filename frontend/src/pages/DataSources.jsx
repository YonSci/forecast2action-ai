import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";

const SOURCE_URL =
  "https://yonsci.github.io/hydroclimatic-risk-mapping/docs/data_provenance.html";

function DataSources() {
  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> Data provenance
          </span>
          <h1>Every layer, traced to a real source</h1>
          <p className="lp-hero-sub">
            Forecast2Action AI doesn't blend anonymous "satellite data" every
            hazard, exposure, and vulnerability layer is a named, versioned
            dataset from a specific provider. This page mirrors the project's
            own published data provenance record.
          </p>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Pipeline philosophy</h2>
          <div className="lp-prose">
            <p>
              The underlying risk formula is{" "}
              <code>R = 100 × P × S × E × V</code> (Risk = Probability ×
              Sensitivity × Exposure × Vulnerability). Every input dataset is
              documented with embedded tags in its GeoTIFF file, and
              consolidated here alongside its acquisition module and
              configuration.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Hazard / probability inputs</h2>
          <p className="lp-prose" style={{ marginBottom: 18 }}>
            Sourced from a separate upstream sibling project (
            <code style={{ color: "var(--lp-teal)" }}>
              extremes-climate-indices
            </code>
            ).
          </p>
          <div className="lp-data-table-wrap">
            <table className="lp-data-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Content</th>
                  <th>Coverage</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <code>corrected_1993_2025.nc</code>
                  </td>
                  <td>
                    (ECMWF SEAS5) Bias-corrected ensemble precipitation (mm/day)
                  </td>
                  <td>1993–2025, May 2 – Oct 31 annually</td>
                  <td>
                    Ragged ensemble only the first 25 of up to 51 realization
                    slots are valid
                  </td>
                </tr>
                <tr>
                  <td>
                    <code>corrected_2026.nc</code>
                  </td>
                  <td>(ECMWF SEAS5 Forecast initialization, same schema</td>
                  <td>2026, May 2 – Oct 31</td>
                  <td>25 / 25 clean realizations</td>
                </tr>
                <tr>
                  <td>
                    <code>et_chirps_pr_r25_1993_2025.nc</code>
                  </td>
                  <td>CHIRPS observational precipitation</td>
                  <td>1993–2025 daily</td>
                  <td>No ensemble dimension</td>
                </tr>
                <tr>
                  <td>Derived indicators</td>
                  <td>Rainfall total, SPI, CDD, CWD, Rx1day, Rx5day</td>
                  <td>5 periods (Jun/Jul/Aug/Sep/JJAS) × 2026</td>
                  <td>SPI capped to ±3.09 at consumption time</td>
                </tr>
                <tr>
                  <td>
                    <code>eth_admin{"{0-3}"}.shp</code>
                  </td>
                  <td>Ethiopia administrative boundaries</td>
                  <td>National</td>
                  <td>EPSG:4326, zero invalid geometries</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Exposure datasets</h2>
          <p className="lp-prose" style={{ marginBottom: 18 }}>
            All resampled to the same 0.25° analysis grid; released under CC-BY
            4.0 or ODbL licenses.
          </p>
          <div className="lp-data-table-wrap">
            <table className="lp-data-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Source</th>
                  <th>License</th>
                  <th>Output file</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="lp-td-strong">Population</td>
                  <td>WorldPop</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_population.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">
                    Cropland (total / irrigated / rainfed)
                  </td>
                  <td>ESA WorldCover 10m 2021 v200</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_cropland.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">
                    Livestock (cattle / sheep / goats)
                  </td>
                  <td>FAO Gridded Livestock of the World v4 (2020)</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_livestock_{"{cattle,sheep,goats}"}.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Built-up surface</td>
                  <td>JRC GHSL GHS-BUILT-S R2023A</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_ghs_built.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Health facilities</td>
                  <td>Global Healthsites Mapping Project (via HDX)</td>
                  <td>ODbL</td>
                  <td>
                    <code>ethiopia_healthsites.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Roads, buildings</td>
                  <td>OpenStreetMap (via Geofabrik)</td>
                  <td>ODbL</td>
                  <td>
                    <code>ethiopia_roads.tif</code>,{" "}
                    <code>ethiopia_buildings.tif</code>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Vulnerability datasets</h2>
          <div className="lp-data-table-wrap" style={{ marginBottom: 18 }}>
            <table className="lp-data-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Role</th>
                  <th>Source</th>
                  <th>License</th>
                  <th>Output file</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="lp-td-strong">Relative Wealth Index</td>
                  <td>Drought + wet sensitivity</td>
                  <td>Meta Data for Good</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_poverty_rwi.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Aridity Index</td>
                  <td>Drought sensitivity</td>
                  <td>CGIAR-CSI Global Aridity v3.1</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_aridity.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Irrigation (% area)</td>
                  <td>Drought adaptive capacity</td>
                  <td>FAO/Bonn Global Map of Irrigation Areas v5</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_irrigation_gmia.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Electrification no-access</td>
                  <td>Drought + wet adaptive capacity</td>
                  <td>IIASA / Falchetta et al. GDESSA</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_gdessa_no_access.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Health facility count</td>
                  <td>Wet adaptive capacity</td>
                  <td>Global Healthsites Mapping Project</td>
                  <td>ODbL</td>
                  <td>
                    <code>ethiopia_healthsites.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Elevation</td>
                  <td>Wet sensitivity</td>
                  <td>NOAA ETOPO 2022 (30 arcsec)</td>
                  <td>Public domain</td>
                  <td>
                    <code>ethiopia_elevation.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Slope</td>
                  <td>Wet sensitivity</td>
                  <td>NOAA ETOPO 2022, derived</td>
                  <td>Public domain</td>
                  <td>
                    <code>ethiopia_slope.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">Topsoil clay content</td>
                  <td>Wet sensitivity</td>
                  <td>ISRIC SoilGrids 2.0 (0–5cm)</td>
                  <td>CC-BY 4.0</td>
                  <td>
                    <code>ethiopia_soil_clay.tif</code>
                  </td>
                </tr>
                <tr>
                  <td className="lp-td-strong">River / water-body distance</td>
                  <td>Wet sensitivity</td>
                  <td>OpenStreetMap waterways + polygons</td>
                  <td>ODbL</td>
                  <td>
                    <code>ethiopia_river_distance.tif</code>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="lp-article-section"></section>
    </SubPageLayout>
  );
}

export default DataSources;
