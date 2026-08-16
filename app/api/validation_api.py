"""Serves precomputed historical validation results (real GLIDE drought
events vs real CHIRPS rainfall anomalies, see app.data_pipeline.
drought_threshold_calibration). Read-only: the underlying analysis is a
heavy, periodic offline job, never recomputed per request.
"""

import json
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/validation", tags=["Historical Validation"])

RESULTS_PATH = Path("data/historical_validation/drought_validation_v1.json")


@router.get("/historical-skill")
def get_historical_skill() -> Dict[str, Any]:
    if not RESULTS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No historical validation results found. Run "
                "python -m app.data_pipeline.drought_threshold_calibration to generate them."
            ),
        )
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
