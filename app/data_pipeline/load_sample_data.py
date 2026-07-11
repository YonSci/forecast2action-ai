# try:
#     from app.data_pipeline.chirps_rainfall_pipeline import run_pipeline
# except ModuleNotFoundError:
#     import sys
#     from pathlib import Path

#     # Allow running this file directly: python app/data_pipeline/load_sample_data.py
#     repo_root = Path(__file__).resolve().parents[2]
#     if str(repo_root) not in sys.path:
#         sys.path.insert(0, str(repo_root))

#     from app.data_pipeline.chirps_rainfall_pipeline import run_pipeline


# if __name__ == "__main__":
#     run_pipeline()


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


if __name__ == "__main__":
    run_pipeline()
    run_ethiopia_forecast_grid_pipeline()