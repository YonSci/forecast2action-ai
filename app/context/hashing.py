"""Provenance hashing utilities.

Hashes are computed from the actual numeric EVIDENCE values pulled into a
context (rank_value, priority_score, metrics, population/area fields,
community counts), not from request parameters -- this is what makes the
resulting context_fingerprint meaningful for cache invalidation: if the
underlying rasters/community reports/knowledge base/policy haven't actually
changed, re-running the same query produces the same fingerprint even if
called at a different time.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict


def sha256_of(value: Any) -> str:
    """Stable SHA-256 hash of any JSON-serializable value."""
    serialized = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    """Hashes a file's mtime + content, so an edit is detected even if the
    edit doesn't change the file's byte length (mtime alone can be spoofed
    by some tools; content hash is the real guarantee).
    """
    if not path.exists():
        return sha256_of({"missing": str(path)})

    stat = path.stat()
    content = path.read_bytes()
    return sha256_of({"mtime": stat.st_mtime, "content_hash": hashlib.sha256(content).hexdigest()})


def hash_action_library(path: Path = Path("data/knowledge/action_library.json")) -> str:
    return hash_file(path)


def hash_policy_file(path: Path) -> str:
    return hash_file(path)


def compute_context_fingerprint(
    forecast_data_hash: str,
    community_data_hash: str,
    exposure_data_hash: str,
    knowledge_base_hash: str,
    decision_policy_hash: str,
    prompt_version: str,
) -> str:
    return sha256_of({
        "forecast_data_hash": forecast_data_hash,
        "community_data_hash": community_data_hash,
        "exposure_data_hash": exposure_data_hash,
        "knowledge_base_hash": knowledge_base_hash,
        "decision_policy_hash": decision_policy_hash,
        "prompt_version": prompt_version,
    })


def hash_forecast_evidence(hazard_evidence: Dict[str, Any]) -> str:
    return sha256_of({
        "layer_value": hazard_evidence.get("layer_value"),
        "rank_value": hazard_evidence.get("rank_value"),
        "priority_score": hazard_evidence.get("priority_score"),
        "metrics": hazard_evidence.get("metrics"),
    })


def hash_exposure_evidence(impact: Dict[str, Any]) -> str:
    return sha256_of({
        "population_total": impact.get("population_total"),
        "population_exposed": impact.get("population_exposed"),
        "area_extent_km2": impact.get("area_extent_km2"),
        "cropland_extent_pct": impact.get("cropland_extent_pct"),
    })


def hash_community_evidence(community: Dict[str, Any]) -> str:
    return sha256_of({
        "feedback_signal": community.get("feedback_signal"),
        "total_reports": community.get("total_reports"),
        "by_severity": community.get("by_severity"),
    })
