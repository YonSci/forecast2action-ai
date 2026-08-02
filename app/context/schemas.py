"""Pydantic models for the Decision Context Envelope.

Every AI interpretation/advisory this app generates should be traceable to
one of these envelopes. Fields this app cannot actually populate from real
data are Optional and left unset (never fabricated) -- absence shows up in
DecisionContextEnvelope.quality_flags via app.context.validators, not as a
silently-guessed value.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ForecastContext(BaseModel):
    """Distinguishes forecast metadata from the evidence values themselves
    (see HazardEvidence) -- this is "when/what forecast", not "what it says".
    """

    forecast_scale: str = "subseasonal"  # "subseasonal" | "seasonal"
    lead: str = ""  # week_1..month_6 (subseasonal) or June/July/August/September/JJAS (seasonal)
    hazard_risk_period: str = "JJAS"  # the literal `period` value sent to compute_district_ranking
    rank_by: str
    admin_selection_mode: str = "top"
    top_n: int = 5
    threshold: float
    # observed_condition | forecast_signal | model_projection | community_report | derived_risk
    evidence_status: str = "forecast_signal"


class GeographicContext(BaseModel):
    country: str = "ethiopia"
    admin_level: str  # admin1 | admin2 | admin3
    area_name: str
    region: str = ""
    zone: str = ""
    woreda: str = ""
    region_id: str = ""
    zone_id: str = ""
    woreda_id: str = ""
    boundary_version: str = "eth_admin_boundary_pipeline_v1"
    boundary_feature: Optional[Dict[str, Any]] = None


class HazardEvidence(BaseModel):
    """The single ranked metric this context is built around -- one row from
    app.api.hazard_risk_ranking.compute_district_ranking's real ranking data.
    """

    layer_value: str
    layer_label: str
    hazard_type: Optional[str] = None  # "drought" | "wet" | "dominant" | None
    category: str  # hazard | probability | exposure | vulnerability | risk
    units: str
    rank_value: float  # zonal mean of layer_value for this area
    priority_score: float  # REAL priority_score from compute_district_ranking
    rank: Optional[int] = None
    metrics: Dict[str, float] = Field(default_factory=dict)  # other computed layers for this area
    observed_ceiling: Optional[float] = None  # get_map_statistics_cached(...)["max"], the real normalization ceiling
    # Real, always-computed {"value": float, "level": "trigger"|"warning"|"watch"|"no_alert"}
    # from app.api.hazard_risk_ranking.compute_district_ranking, regardless of
    # what rank_by/layer_value this context was actually built for -- see
    # app.context.policy_context.resolve_real_trigger_status, the single
    # source of truth for trigger classification (never the generic
    # priority_score above, which is trivially ~1.0 for whatever area ranks
    # #1 under ANY metric, including Exposure, and does not reflect real
    # drought/wet severity).
    drought_risk: Optional[Dict[str, Any]] = None
    wet_risk: Optional[Dict[str, Any]] = None


class ImpactContext(BaseModel):
    population_total: Optional[int] = None
    population_exposed: Optional[int] = None
    population_exposed_pct: Optional[float] = None
    area_total_km2: Optional[float] = None
    area_extent_km2: Optional[float] = None
    area_extent_pct: Optional[float] = None
    cropland_extent_pct: Optional[float] = None


class CommunityContext(BaseModel):
    feedback_signal: str = "no_ground_signal"
    total_reports: int = 0
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_type: Dict[str, int] = Field(default_factory=dict)
    recent_reports: List[Dict[str, Any]] = Field(default_factory=list)


class OperationalContext(BaseModel):
    audience: str = "disaster_manager"
    language: str = "en"
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None


class DecisionPolicyContext(BaseModel):
    policy_id: str
    thresholds: Dict[str, float]
    trigger_status: str  # trigger | warning | watch | no_alert
    approval_rules_version: str = "v1"


class KnowledgeContext(BaseModel):
    retrieved_items: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_mode: str = "keyword_metadata"  # future: "hybrid"


class ProvenanceContext(BaseModel):
    context_id: str
    context_version: str = "v1"
    created_at: str
    prompt_version: str = "v1"
    context_fingerprint: str
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    source_endpoints: List[str] = Field(default_factory=list)


class DecisionContextEnvelope(BaseModel):
    context_id: str
    forecast: ForecastContext
    geography: GeographicContext
    hazard_evidence: HazardEvidence
    impact: ImpactContext
    community: CommunityContext
    operational: OperationalContext
    policy: DecisionPolicyContext
    knowledge: KnowledgeContext
    provenance: ProvenanceContext

    quality_score: float = 0.0
    quality_flags: List[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "DecisionContextEnvelope":
        return cls.model_validate_json(raw)
