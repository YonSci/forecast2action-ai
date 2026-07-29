"""JSON-file storage for Decision Context Envelopes.

ContextRepository's interface (save/get/list_recent) is the one seam a
future PostgreSQL/PostGIS implementation would replace -- context_builder.py
and the API routers depend on this interface via get_repository(), never on
the JSON-file class directly, so swapping backends later means changing one
factory function, not every call site.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.context.schemas import DecisionContextEnvelope

logger = logging.getLogger(__name__)

CONTEXT_RUNS_DIR = Path("data/context_runs")


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return value or "item"


class ContextRepository:
    """JSON-file-backed implementation. Volumes are small in phase 1, so
    `get`/`list_recent` do a simple linear directory scan rather than
    maintaining a separate id->filename index -- a real index (or a
    database) is a Phase-2 concern once request volume justifies it.
    """

    def __init__(self, base_dir: Path = CONTEXT_RUNS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, envelope: DecisionContextEnvelope) -> Path:
        created_compact = envelope.provenance.created_at.replace(":", "").replace("-", "").split(".")[0]
        area_slug = _slug(envelope.geography.area_name)
        lead_slug = _slug(envelope.forecast.lead or envelope.forecast.hazard_risk_period)
        # The FULL context_id (not a truncated prefix -- a prefix isn't
        # guaranteed unique when two context_ids only differ near the end,
        # e.g. UUIDs sharing a common prefix, which is exactly what a test
        # caught) guarantees uniqueness even when two envelopes share the
        # same created_at/area/lead (e.g. two contexts built within the
        # same second for the same area and lead).
        context_id_slug = _slug(envelope.context_id)
        return self.base_dir / f"ctx_{created_compact}_{area_slug}_{lead_slug}_{context_id_slug}.json"

    def save(self, envelope: DecisionContextEnvelope) -> Path:
        path = self._path_for(envelope)
        path.write_text(envelope.to_json(), encoding="utf-8")
        return path

    def get(self, context_id: str) -> Optional[DecisionContextEnvelope]:
        for path in self.base_dir.glob("ctx_*.json"):
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue

            if f'"context_id": "{context_id}"' not in raw:
                continue

            try:
                return DecisionContextEnvelope.from_json(raw)
            except Exception:
                logger.exception("Failed to parse stored context at %s", path)
                return None

        return None

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        paths = sorted(
            self.base_dir.glob("ctx_*.json"), key=lambda p: p.stat().st_mtime, reverse=True,
        )[:limit]

        summaries = []
        for path in paths:
            try:
                envelope = DecisionContextEnvelope.from_json(path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Failed to parse stored context at %s", path)
                continue

            summaries.append({
                "context_id": envelope.context_id,
                "area_name": envelope.geography.area_name,
                "hazard_type": envelope.hazard_evidence.hazard_type,
                "trigger_status": envelope.policy.trigger_status,
                "created_at": envelope.provenance.created_at,
            })

        return summaries


_repository_instance: Optional[ContextRepository] = None


def get_repository() -> ContextRepository:
    global _repository_instance
    if _repository_instance is None:
        _repository_instance = ContextRepository()
    return _repository_instance
