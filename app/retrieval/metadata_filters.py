"""Stage 1 of hybrid retrieval: metadata filtering over the knowledge base.

Applies BEFORE keyword scoring so keyword_retriever.py never even sees an
entry that is the wrong country/language, not yet valid, expired, or not in
an operationally-acceptable approval/authority state -- see
data/knowledge/action_library.json's migrated schema (app/advisory/
knowledge_compat.py) for the fields this reads.
"""

from datetime import date
from typing import Any, Dict, List, Optional

ACCEPTABLE_AUTHORITY_STATUSES = {
    "official",
    "peer_reviewed",
    "institutional",
    "expert_validated",
    "approved",  # this app's own migrated default -- treated as institutionally accepted
}

ACCEPTABLE_APPROVAL_STATUSES = {"approved", "not_required"}


def _entry_is_valid_now(entry: Dict[str, Any], valid_at: Optional[str]) -> bool:
    valid_from = entry.get("valid_from")
    valid_to = entry.get("valid_to")

    if not valid_from and not valid_to:
        return True

    reference = valid_at or date.today().isoformat()

    if valid_from and reference < valid_from:
        return False

    if valid_to and reference > valid_to:
        return False

    return True


def filter_by_metadata(
    library: List[Dict[str, Any]],
    *,
    country: Optional[str] = None,
    language: Optional[str] = None,
    valid_at: Optional[str] = None,
    require_approved: bool = True,
) -> List[Dict[str, Any]]:
    """Returns only entries acceptable for operational recommendations.

    Prototype/unverified guidance is excluded by default (require_approved=True)
    per the spec's "only retrieve items with acceptable approval and validity
    status for operational recommendations" rule. Pass require_approved=False
    to surface prototype guidance explicitly labeled as such (not done by
    this phase's callers, but supported for future UI use).
    """
    results = []

    for entry in library:
        if country and entry.get("countries") and country.lower() not in {
            value.lower() for value in entry["countries"]
        }:
            continue

        if language and entry.get("language") and entry["language"].lower() != language.lower():
            continue

        if not _entry_is_valid_now(entry, valid_at):
            continue

        if require_approved:
            if entry.get("authority_status", "approved") not in ACCEPTABLE_AUTHORITY_STATUSES:
                continue
            if entry.get("approval_status", "not_required") not in ACCEPTABLE_APPROVAL_STATUSES:
                continue

        results.append(entry)

    return results
