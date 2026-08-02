"""Main entry point for building a Decision Context Envelope.

Orchestrates the specialized context modules (forecast/geographic/impact,
community, policy, knowledge, operational, provenance), then validates and
persists the result. No single function does everything itself -- each
piece is delegated to its own module, per the project's context-engineering
plan.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.context.forecast_context import build_hazard_geo_impact_context
from app.context.community_context import build_community_context
from app.context.hashing import (
    compute_context_fingerprint,
    hash_action_library,
    hash_community_evidence,
    hash_exposure_evidence,
    hash_forecast_evidence,
    hash_policy_file,
)
from app.context.knowledge_context import build_knowledge_context
from app.context.operational_context import build_operational_context
from app.context.policy_context import build_policy_context, resolve_real_trigger_status
from app.context.repository import get_repository
from app.context.schemas import DecisionContextEnvelope, ProvenanceContext
from app.context.validators import compute_quality_score
from app.decision.policy_engine import POLICY_DIR, CATALOG_HAZARD_TYPE_TO_POLICY_HAZARD

logger = logging.getLogger(__name__)


def _policy_file_path(hazard_type: str, country: str) -> Path:
    resolved = CATALOG_HAZARD_TYPE_TO_POLICY_HAZARD.get(hazard_type, hazard_type or "any")
    candidate = POLICY_DIR / f"{resolved}_{country}.json"
    return candidate if candidate.exists() else POLICY_DIR / "default_policy.json"


def build_context(
    *,
    rank_by: str,
    period: str = "JJAS",
    admin_level: str = "admin3",
    region_id: str = "",
    zone_id: str = "",
    top_n: int = 5,
    selection_mode: str = "top",
    threshold: Optional[float] = None,
    target_area_name: Optional[str] = None,
    forecast_scale: str = "subseasonal",
    lead: str = "",
    audience: str = "disaster_manager",
    language: str = "en",
    requested_provider: Optional[str] = None,
    requested_model: Optional[str] = None,
    country: str = "ethiopia",
    prompt_version: str = "v1",
    task: str = "advisory_generation",
    persist: bool = True,
) -> DecisionContextEnvelope:
    """Builds, validates, and (by default) persists a full Decision Context
    Envelope for one real ranked area. Raises ValueError if no real hazard
    evidence could be resolved (see build_hazard_geo_impact_context) --
    there is no meaningful fallback for a completely missing evidence base.
    """
    forecast, geography, hazard_evidence, impact = build_hazard_geo_impact_context(
        rank_by=rank_by, period=period, admin_level=admin_level,
        region_id=region_id, zone_id=zone_id, top_n=top_n,
        selection_mode=selection_mode, threshold=threshold,
        target_area_name=target_area_name, forecast_scale=forecast_scale, lead=lead,
    )
    geography.country = country

    community = build_community_context(geography.area_name)

    # Real trigger_status from the same drought_risk/wet_risk classification
    # the ranking table uses -- NOT hazard_evidence.priority_score, which is
    # trivially ~1.0 for whatever ranks #1 under ANY metric (see
    # resolve_real_trigger_status's docstring for the exact bug this fixes).
    # effective_hazard_type can differ from hazard_evidence.hazard_type when
    # this context was built by ranking on Exposure (hazard_type is None) --
    # it resolves to whichever real hazard is more severe for this area, so
    # policy/knowledge retrieval below is never driven by an empty hazard.
    effective_hazard_type, trigger_status = resolve_real_trigger_status(hazard_evidence)
    policy = build_policy_context(effective_hazard_type, trigger_status, country=country)

    knowledge_query = {
        "hazard": effective_hazard_type or "",
        "risk_level": policy.trigger_status,
        "audience": audience,
        "feedback_signal": community.feedback_signal,
    }
    knowledge = build_knowledge_context(knowledge_query, top_k=5, country=country)

    operational = build_operational_context(
        audience=audience, language=language,
        requested_provider=requested_provider, requested_model=requested_model,
    )

    forecast_data_hash = hash_forecast_evidence(hazard_evidence.model_dump())
    exposure_data_hash = hash_exposure_evidence(impact.model_dump())
    community_data_hash = hash_community_evidence(community.model_dump())
    knowledge_base_hash = hash_action_library()
    decision_policy_hash = hash_policy_file(_policy_file_path(effective_hazard_type or "any", country))

    fingerprint = compute_context_fingerprint(
        forecast_data_hash=forecast_data_hash,
        community_data_hash=community_data_hash,
        exposure_data_hash=exposure_data_hash,
        knowledge_base_hash=knowledge_base_hash,
        decision_policy_hash=decision_policy_hash,
        prompt_version=prompt_version,
    )

    context_id = str(uuid.uuid4())
    provenance = ProvenanceContext(
        context_id=context_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        prompt_version=prompt_version,
        context_fingerprint=fingerprint,
        ai_provider=requested_provider,
        ai_model=requested_model,
        source_endpoints=[
            "app.api.hazard_risk_ranking.compute_district_ranking",
            "app.api.community_reports_store.summarize_reports",
            "app.decision.policy_engine.load_policy_for_hazard",
            "app.retrieval.hybrid_retriever.retrieve",
        ],
    )

    envelope = DecisionContextEnvelope(
        context_id=context_id,
        forecast=forecast,
        geography=geography,
        hazard_evidence=hazard_evidence,
        impact=impact,
        community=community,
        operational=operational,
        policy=policy,
        knowledge=knowledge,
        provenance=provenance,
    )

    quality_score, quality_flags = compute_quality_score(envelope)
    envelope.quality_score = quality_score
    envelope.quality_flags = quality_flags

    if persist:
        get_repository().save(envelope)
        logger.info(
            "context_built context_id=%s area=%s ranked_by_hazard=%s effective_hazard=%s trigger_status=%s quality_score=%.2f",
            context_id, geography.area_name, hazard_evidence.hazard_type, effective_hazard_type, policy.trigger_status, quality_score,
        )

    return envelope
