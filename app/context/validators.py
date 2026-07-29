"""Context validation and quality scoring.

Phase-1 quality scoring is deliberately binary per dimension (present/absent,
no fuzzy partial credit) to keep this bounded and testable -- see the
project's approved implementation plan for why a fuzzier formula was
explicitly deferred.
"""

from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from app.context.schemas import DecisionContextEnvelope

QUALITY_WEIGHTS = {
    "hazard_evidence": 0.35,
    "impact": 0.25,
    "community": 0.15,
    "knowledge": 0.15,
    "geography": 0.10,
}


def _hazard_evidence_present(envelope: "DecisionContextEnvelope") -> bool:
    return envelope.hazard_evidence.rank_value is not None and envelope.hazard_evidence.priority_score is not None


def _impact_present(envelope: "DecisionContextEnvelope") -> bool:
    impact = envelope.impact
    return any([
        impact.population_total is not None,
        impact.area_total_km2 is not None,
    ])


def _community_present(envelope: "DecisionContextEnvelope") -> bool:
    return envelope.community.total_reports > 0


def _knowledge_present(envelope: "DecisionContextEnvelope") -> bool:
    return len(envelope.knowledge.retrieved_items) > 0


def _geography_present(envelope: "DecisionContextEnvelope") -> bool:
    return bool(envelope.geography.area_name)


def compute_quality_score(envelope: "DecisionContextEnvelope") -> Tuple[float, List[str]]:
    """Returns (quality_score in [0,1], list of quality_flags describing
    what's missing). A flag is added for every dimension that scored 0,
    so a caller/UI can explain WHY the score is low, not just the number.
    """
    checks = {
        "hazard_evidence": (_hazard_evidence_present(envelope), "no_hazard_evidence"),
        "impact": (_impact_present(envelope), "no_impact_data"),
        "community": (_community_present(envelope), "no_community_reports"),
        "knowledge": (_knowledge_present(envelope), "no_knowledge_match"),
        "geography": (_geography_present(envelope), "no_geographic_context"),
    }

    score = 0.0
    flags: List[str] = []

    for dimension, weight in QUALITY_WEIGHTS.items():
        present, flag = checks[dimension]
        if present:
            score += weight
        else:
            flags.append(flag)

    return round(score, 3), flags


def validate_context(envelope: "DecisionContextEnvelope") -> dict:
    """Returns {"is_valid": bool, "quality_score": float, "warnings": [...],
    "errors": [...], "missing_fields": [...]} -- the shape the project spec
    asks for. is_valid is False only for hard errors (missing hazard
    evidence, the one truly required piece); everything else is a warning.
    """
    quality_score, flags = compute_quality_score(envelope)

    errors = []
    if not _hazard_evidence_present(envelope):
        errors.append("Missing hazard evidence -- cannot build a defensible context without it.")

    warnings = [flag.replace("_", " ") for flag in flags if flag != "no_hazard_evidence"]

    return {
        "is_valid": len(errors) == 0,
        "quality_score": quality_score,
        "warnings": warnings,
        "errors": errors,
        "missing_fields": flags,
    }
