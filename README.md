# Forecast2Action AI

**Forecast2Action AI** is an impact-based early warning and anticipatory action in Ethiopia. It turns a seasonal/subseasonal climate forecast into a ranked list of priority areas, an AI-generated integrated risk report, and audience-specific advisories (farmer, agro-pastoral, humanitarian, SMS/WhatsApp) with every number in the report computed deterministically before any AI model sees it.

## Live Demo

- Frontend: https://forecast2action-ai.vercel.app
- Backend API: https://forecast2action-ai.onrender.com
- API docs (OpenAPI/Swagger): https://forecast2action-ai.onrender.com/docs

---

## 1. What it does

Forecast2Action AI covers Ethiopia at the national scale (admin1/admin2/admin3), across seasonal and subseasonal forecast windows. For any selected period it:

- computes hazard indices, exposure, and vulnerability per region from real, named datasets;
- ranks regions into a priority queue using a deterministic, auditable formula;
- classifies each region into an alert level (Trigger / Warning / Watch / No alert);
- generates an AI-interpreted integrated risk report executive summary, national spatial overview, compound hazard interpretation, and per-area justifications;
- produces audience-specific advisories (Disaster Risk Manager, NGO/Anticipatory Action Planner, Agriculture & Livestock Extension Officer, Community Member) and SMS/WhatsApp-ready community messages in English, Amharic, Oromifa/Afaan Oromo, Tigrinya, and Somali;
- accepts community ground-truth reports that corroborate or contradict the forecast signal;
- tracks recommended actions through to implementation, with CSV export.

Every generated report is validated against the same evidence it was built from before it reaches a user see [§4 The response validator](#4-the-response-validator).

---

## 2. How it works

The pipeline is deterministic-first: nothing an AI model can hallucinate is left for it to guess.

1. **Ingest forecast data** a 25-member seasonal ensemble (ECMWF SEAS5) and CHIRPS observational rainfall are pulled in at 0.25° resolution, alongside exposure layers (population, cropland, livestock, roads, health facilities) and vulnerability layers, all resampled to the same analysis grid.
2. **Compute hazard indices** seven climate indicators (SPI, rainfall percentile, CDD, CWD, Rx1day, Rx5day, rainfall total) are each standardized and combined into a per-realization hazard index, preserving the ensemble dimension so probability and severity are measured separately: `Hazard = Probability × Severity`.
3. **Rank & classify** hazard is combined with real exposure and vulnerability layers into a 0–100 risk score per area (`Risk = 100 × Hazard Probability × Severity × Exposure × Vulnerability`), classified into alert bands, and ranked by a deterministic priority formula.
4. **Deliver the advisory** a staged AI pipeline (see below) turns the already-ranked, already-classified evidence into language, and every generated report is cross-checked against that same evidence before being delivered.

### The 3-stage AI report pipeline

Each stage sees only what it needs never raw ensemble data, never an invented ranking:

- **Stage 1 Evidence interpretation** (fast model tier): interprets already-computed layer/indicator summaries into plain-language sentences. Never computes, reclassifies, or invents a number.
- **Stage 2 Integrated risk synthesis** (strong model tier): synthesizes Stage 1's findings with the real, already-computed priority ranking and cross-indicator agreement into a national narrative. Explains the ranking never reorders or invents it.
- **Stage 3 Action translation** (fast model tier): translates the validated findings into farmer, agro-pastoral, and humanitarian advisories and SMS/WhatsApp messages, split by whether an area is actually actionable this period.

AI providers: Google Gemini (primary), OpenRouter and an OpenAI-compatible API (fallback), selected automatically with per-stage model tiering.

---

## 3. Real data sources

Every hazard, exposure, and vulnerability layer traces to a named, versioned dataset not anonymous "satellite data." Highlights:

| Category         | Examples                                                                                                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Climate / hazard | ECMWF SEAS5 (25-member bias-corrected ensemble), CHIRPS observational precipitation                                                                                            |
| Exposure         | WorldPop population, ESA WorldCover cropland, FAO Gridded Livestock of the World v4 (cattle/sheep/goats), JRC GHSL built-up surface, OpenStreetMap roads and health facilities |
| Vulnerability    | Baseline food-security/livelihood sensitivity (FEWS NET IPC phase classification) and related sensitivity/adaptive-capacity indicators                                         |
| Boundaries       | Ethiopia admin0–admin3 administrative boundaries                                                                                                                               |

The full, versioned provenance table dataset, coverage, license, output file is published in-app on the [Data sources](https://forecast2action-ai.vercel.app/data-sources) page.

---

## 4. The response validator

Every AI-generated report goes through **generate → validate → repair → validate again** before display:

- Deterministically repaired in place: invented place names, fabricated scores, forbidden internal-score citations, and forecast-safe language violations (e.g. describing a forecast hazard as already "confirmed", "observed", or "ongoing").
- Detected and flagged (no safe automatic rewrite exists): a national aggregate signal overstated from an area-level rollup, an area-level signal count disagreeing with the real per-area tally, a forecast value mislabeled as a climatology baseline (or vice versa), a relative quintile classification stated as an absolute severity claim, vulnerability attributed to a climate/hazard driver, and unsupported cross-area superlative claims ("the highest X").

Nothing here is an LLM re-prompt loop every repair is a deterministic Python transformation, so it always succeeds even against unreliable free-tier providers.

---

## 5. Dashboard features

- Interactive Leaflet maps: hazard/risk layers and seasonal climate indicator rasters (Forecast / Climatology / Anomaly, with a side-by-side compare view), pannable and zoomable, not static images.
- Admin1/2/3 boundary selector.
- Priority intervention area ranking, reproducible and auditable.
- AI-generated integrated report with per-area justification, confidence, and infrastructure/exposure denominators.
- Community ground-truth reporting (water shortage, crop wilting, pasture condition, livestock stress, flooding, disease concern, and more).
- Action implementation tracker with CSV export.
- Multilingual SMS/WhatsApp-ready community messages.
- Downloadable HTML/Markdown bulletins.

---

## 6. Technology stack

### Frontend

- React 19, React Router 7, Vite
- Leaflet / react-leaflet (interactive maps)
- Recharts (charts)

### Backend & API

- Python, FastAPI, Uvicorn, Pydantic
- pytest (automated test suite)

### Geospatial & data processing

- rasterio, rio-tiler, rioxarray / xarray, netCDF4 / h5netcdf
- geopandas, pyogrio
- NumPy, pandas, SciPy

### AI & language models

- Google Gemini (primary), OpenRouter, OpenAI-compatible API
- A context-engineered, evidence-grounded LLM pipeline with RAG-based action guidance not a single freeform prompt

---

## 7. Project Structure

```text
forecast2action-ai/
│
├── app/
│   ├── api/
│   │   ├── main.py                          # FastAPI app, CORS, bulletin export
│   │   ├── report_stages.py                 # 3-stage AI report pipeline
│   │   ├── ai_map_interpretation.py         # AI provider calls, schemas
│   │   ├── hazard_risk_maps.py              # hazard/risk raster tile service
│   │   ├── hazard_risk_ranking.py           # priority ranking engine
│   │   ├── seasonal_raster_maps.py          # interactive climate indicator raster service
│   │   ├── seasonal_maps.py                 # static seasonal PNG map catalog
│   │   └── context_api.py                   # context engineering endpoints
│   │
│   ├── advisory/
│   │   ├── response_validator.py            # generate -> validate -> repair -> validate again
│   │   ├── rag_engine.py                    # RAG-based action guidance
│   │   └── advisory_generator.py
│   │
│   ├── context/
│   │   ├── statistical_evidence.py          # deterministic hazard/exposure/vulnerability/priority engine
│   │   ├── context_builder.py
│   │   └── ...
│   │
│   ├── data_pipeline/
│   │   ├── ethiopia_forecast_grid_pipeline.py
│   │   ├── exposure_data_pipeline.py
│   │   ├── vulnerability_data_pipeline.py
│   │   ├── infrastructure_data_pipeline.py  # real OSM roads / health-facility counts
│   │   ├── historical_rainfall_pipeline.py
│   │   └── ethiopia_admin_boundary_pipeline.py
│   │
│   ├── retrieval/                           # RAG retrieval
│   └── decision/                            # decision-trigger engine
│
├── data/                                     # sample data, knowledge base, raster/map catalogs
│
├── frontend/
│   ├── src/
│   │   ├── pages/                            # Landing, Dashboard, Platform, HowItWorks,
│   │   │                                     # DataSources, TechnicalDocumentation, About, Contact
│   │   ├── components/                       # ForecastLayerMap, AIMapInterpretation, RiskMap, ...
│   │   └── App.jsx                           # routes
│   ├── package.json
│   └── vite.config.js
│
├── tests/                                    # pytest suite
├── docs/                                     # architecture notes
├── requirements.txt
└── README.md
```

---

## 8. Setup Instructions

### 8.1 Clone the project

```cmd
git clone https://github.com/YonSci/forecast2action-ai.git
cd forecast2action-ai
```

### 8.2 Create and activate the Python environment

```cmd
python -m venv .venv
.venv\Scripts\activate
```

### 8.3 Install backend dependencies

```cmd
pip install -r requirements.txt
```

### 8.4 Configure environment variables

Create a `.env` file in the project root with at least one AI provider key:

```text
GEMINI_API_KEY=your_key_here
# or
OPENROUTER_API_KEY=your_key_here
# or
OPENAI_API_KEY=your_key_here
```

### 8.5 Start the backend

```cmd
uvicorn app.api.main:app --reload
```

Backend runs at `http://127.0.0.1:8000` (API docs at `/docs`).

### 8.6 Install and start the frontend

```cmd
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5174` and proxies `/api` requests to the backend on port 8000. If port 8000 is already in use by another local project, override the proxy target:

```cmd
set VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:8001
npm run dev
```

### 8.7 Run the test suite

```cmd
pytest
```

---

## 9. Key API Endpoints

| Endpoint                                                                                                 | Description                                                          |
| -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `POST /api/ai/map-interpretation`                                                                        | Runs the 3-stage AI report pipeline and returns the validated report |
| `GET /api/ai/model-options` / `GET /api/ai/provider-status`                                              | Lists configured AI providers/models                                 |
| `GET /api/hazard-risk/catalog` / `GET /api/hazard-risk/map`                                              | Hazard/risk raster layer catalog and tiles                           |
| `GET /api/hazard-risk/ranking`                                                                           | Deterministic priority-area ranking                                  |
| `GET /api/seasonal-raster/options` / `GET /api/seasonal-raster/map` / `GET /api/seasonal-raster/compare` | Interactive Forecast/Climatology/Anomaly climate indicator maps      |
| `GET /api/seasonal-maps/catalog`                                                                         | Static seasonal PNG map catalog                                      |
| `GET /api/admin-boundaries/options` / `GET /api/admin-boundaries/geojson`                                | Admin1/2/3 boundary selection                                        |
| `GET/POST /api/community-reports`                                                                        | Submit or list community ground-truth reports                        |
| `GET /api/community-feedback-summary`                                                                    | Summarizes ground-truth reports                                      |
| `GET /api/priority-actions`                                                                              | Ranked priority action queue                                         |
| `GET /api/action-tracker/{district}` / `.../csv`                                                         | Action implementation tracker + CSV export                           |
| `GET /api/bulletin/{district}`                                                                           | HTML or Markdown bulletin export                                     |
| `GET/POST /api/context/*`                                                                                | Context-engineering / decision-context endpoints                     |

Full interactive documentation is available at `/docs` on the running backend.

---

## 10. Contact

- **Dr. Teferi Demissie** T.Demissie@cgiar.org · teferidem@grace-resilience.com
- **Yonas Mersha** Y.Mersha@cgiar.org
- GitHub: [github.com/YonSci](https://github.com/YonSci)
- Project repository: [github.com/YonSci/forecast2action-ai](https://github.com/YonSci/forecast2action-ai)

---

## 11. About

Forecast2Action AI is developed at the **International Livestock Research Institute (ILRI)**.
