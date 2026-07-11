from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.data_pipeline.chirps_rainfall_pipeline import run_pipeline
from app.data_pipeline.ethiopia_forecast_grid_pipeline import (
    run_ethiopia_forecast_grid_pipeline,
)
from app.data_pipeline.ethiopia_admin_boundary_pipeline import (
    run_ethiopia_admin_boundary_pipeline,
)


if __name__ == "__main__":
    run_pipeline()
    run_ethiopia_forecast_grid_pipeline()

    try:
        run_ethiopia_admin_boundary_pipeline()
    except FileNotFoundError as error:
        print(f"WARNING: Ethiopia shapefile pipeline skipped: {error}")