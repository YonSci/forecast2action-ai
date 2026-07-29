"""Backward-compatibility adapter for the extended action_library.json schema.

data/knowledge/action_library.json's 9 entries were migrated in-place to
include authority_status/approval_status/version/valid_from/valid_to/
source_organization/source_url/source_date/language/tags/countries/regions/
livelihood_zones/agroecological_zones/risk_levels. This adapter fills in the
same defaults for any entry a future hand-edit adds without every new field,
so app/retrieval/metadata_filters.py never has to special-case a missing key.

app.advisory.rag_engine.load_action_library() itself is left untouched --
this is applied only by the NEW retrieval pipeline (app.retrieval.
hybrid_retriever), not the old rule-based /api/advisory/{district} path.
"""

from typing import Any, Dict

_DEFAULTS = {
    "authority_status": "approved",
    "approval_status": "not_required",
    "version": "1.0.0",
    "valid_from": "2025-01-01",
    "valid_to": None,
    "source_organization": "Forecast2Action AI",
    "source_url": None,
    "source_date": "2025-01-01",
    "language": "en",
    "tags": [],
    "countries": ["ethiopia"],
    "regions": [],
    "livelihood_zones": [],
    "agroecological_zones": [],
}


def ensure_new_fields(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Returns a copy of `entry` with any missing new-schema field filled in."""
    result = dict(entry)

    for key, default in _DEFAULTS.items():
        result.setdefault(key, default)

    result.setdefault("risk_levels", [result.get("risk_level", "any")])

    return result
