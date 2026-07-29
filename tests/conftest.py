"""Shared pytest fixtures for the context-engineering test suite."""

import pytest

from app.context.repository import ContextRepository
from app.context.schemas import (
    CommunityContext,
    DecisionContextEnvelope,
    DecisionPolicyContext,
    ForecastContext,
    GeographicContext,
    HazardEvidence,
    ImpactContext,
    KnowledgeContext,
    OperationalContext,
    ProvenanceContext,
)


@pytest.fixture
def sample_envelope() -> DecisionContextEnvelope:
    """A hand-built envelope (no real raster/community data involved) for
    fast, deterministic unit tests of validators/trigger logic/hashing.
    """
    return DecisionContextEnvelope(
        context_id="test-context-id-0001",
        forecast=ForecastContext(
            forecast_scale="subseasonal", lead="week_1", hazard_risk_period="JJAS",
            rank_by="population_r_drought", threshold=32.246,
        ),
        geography=GeographicContext(
            admin_level="admin3", area_name="Test Woreda", region="Test Region",
            zone="Test Zone", woreda="Test Woreda", region_id="test_region",
            zone_id="test_region_test_zone", woreda_id="test_region_test_zone_test_woreda",
        ),
        hazard_evidence=HazardEvidence(
            layer_value="population_r_drought", layer_label="Drought Risk",
            hazard_type="drought", category="risk", units="score",
            rank_value=53.7, priority_score=0.9, rank=1,
            metrics={"population_r_drought": 53.7}, observed_ceiling=53.7,
        ),
        impact=ImpactContext(
            population_total=47508, population_exposed=47508, population_exposed_pct=100.0,
            area_total_km2=754.0, area_extent_km2=754.0, area_extent_pct=100.0,
            cropland_extent_pct=0.0,
        ),
        community=CommunityContext(feedback_signal="no_ground_signal", total_reports=0),
        operational=OperationalContext(audience="disaster_manager", language="en"),
        policy=DecisionPolicyContext(
            policy_id="drought_ethiopia_v1",
            thresholds={"trigger": 0.80, "warning": 0.60, "watch": 0.35},
            trigger_status="trigger",
        ),
        knowledge=KnowledgeContext(retrieved_items=[]),
        provenance=ProvenanceContext(
            context_id="test-context-id-0001", created_at="2026-01-01T00:00:00+00:00",
            prompt_version="v1", context_fingerprint="testfingerprint0001",
        ),
        quality_score=0.6,
        quality_flags=["no_community_reports", "no_knowledge_match"],
    )


@pytest.fixture
def temp_repository(tmp_path) -> ContextRepository:
    return ContextRepository(base_dir=tmp_path / "context_runs")
