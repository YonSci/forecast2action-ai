"""Context Engineering API -- build, fetch, and audit Decision Context
Envelopes. Mounted in app.api.main alongside the existing 5 routers.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.context.context_builder import build_context
from app.context.repository import get_repository
from app.context.validators import validate_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/context", tags=["Context Engineering"])


class ContextBuildRequest(BaseModel):
    rank_by: str
    period: str = "JJAS"
    admin_level: str = "admin3"
    region_id: str = ""
    zone_id: str = ""
    top_n: int = 5
    selection_mode: str = "top"
    threshold: Optional[float] = None
    target_area_name: Optional[str] = None
    forecast_scale: str = "subseasonal"
    lead: str = ""
    audience: str = "disaster_manager"
    language: str = "en"
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    country: str = "ethiopia"
    prompt_version: str = "v1"
    task: str = "advisory_generation"


@router.post("/build")
async def build_context_endpoint(request: ContextBuildRequest) -> Dict[str, Any]:
    payload = request.model_dump()

    # Same normalization as GET /api/hazard-risk/ranking (hazard_risk_ranking.py)
    # -- compute_district_ranking's own admin GeoJSON lookup only knows
    # admin1/2/3. Callers can legitimately pass something else here (e.g.
    # the admin boundary selector's "admin0"/country-level value, which is
    # meaningful for map display but not a valid RANKING admin level) --
    # falling back to admin3 rather than 404ing, since building a context is
    # supposed to degrade gracefully, not require the caller to already know
    # this endpoint's internal admin-level vocabulary.
    if payload["admin_level"] not in {"admin1", "admin2", "admin3"}:
        logger.info(
            "admin_level=%s is not a valid ranking level -- defaulting to admin3",
            payload["admin_level"],
        )
        payload["admin_level"] = "admin3"

    try:
        envelope = build_context(**payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    validation = validate_context(envelope)

    return {
        "context_id": envelope.context_id,
        "context_fingerprint": envelope.provenance.context_fingerprint,
        "quality_score": envelope.quality_score,
        "quality_flags": envelope.quality_flags,
        "validation": validation,
        "envelope": envelope.model_dump(),
    }


@router.get("/{context_id}")
async def get_context_endpoint(context_id: str) -> Dict[str, Any]:
    envelope = get_repository().get(context_id)
    if not envelope:
        raise HTTPException(status_code=404, detail=f"Context '{context_id}' not found.")
    return envelope.model_dump()


@router.get("/{context_id}/audit")
async def get_context_audit_endpoint(context_id: str) -> Dict[str, Any]:
    envelope = get_repository().get(context_id)
    if not envelope:
        raise HTTPException(status_code=404, detail=f"Context '{context_id}' not found.")

    validation = validate_context(envelope)

    return {
        "context_id": context_id,
        "provenance": envelope.provenance.model_dump(),
        "source_endpoints": envelope.provenance.source_endpoints,
        "policy": envelope.policy.model_dump(),
        "quality_score": envelope.quality_score,
        "quality_flags": envelope.quality_flags,
        "validation": validation,
        "knowledge_items_count": len(envelope.knowledge.retrieved_items),
    }


@router.get("")
async def list_recent_contexts(limit: int = Query(default=20)) -> Dict[str, Any]:
    return {"contexts": get_repository().list_recent(limit=limit)}


@router.get("/statistical-evidence/{period}")
async def get_statistical_evidence_endpoint(period: str, admin_level: str = Query(default="admin1")) -> Dict[str, Any]:
    """Real, deterministic statistics (national + region) for one forecast
    period -- see app.context.statistical_evidence for what's actually
    computed vs. what's explicitly flagged as unavailable (no fabrication).
    Cached to disk; use POST .../refresh to force a rebuild.
    """
    from app.context.statistical_evidence import build_national_region_evidence

    try:
        return build_national_region_evidence(period, admin_level=admin_level, use_cache=True)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to build statistical evidence: {error}") from error


@router.post("/statistical-evidence/{period}/refresh")
async def refresh_statistical_evidence_endpoint(period: str, admin_level: str = Query(default="admin1")) -> Dict[str, Any]:
    from app.context.statistical_evidence import build_national_region_evidence

    try:
        return build_national_region_evidence(period, admin_level=admin_level, use_cache=False)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to rebuild statistical evidence: {error}") from error
