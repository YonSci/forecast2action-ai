"""Builds CommunityContext from real, persisted community reports.

Reads via app.api.community_reports_store (not app.api.main directly --
see that module's docstring for why) so this always reflects whatever
users have actually submitted through POST /api/community-reports, not a
separate client-side-only copy.
"""

from typing import Any, Dict, List

from app.api.community_reports_store import (
    canonical_report_type,
    load_reports,
    summarize_reports,
    weighted_high_or_severe_count,
)
from app.context.schemas import CommunityContext

MAX_RECENT_REPORTS = 5
MAX_RECENT_REPORTS_PER_REGION = 3
DESCRIPTION_EXCERPT_CHARS = 200


def build_community_context(district: str) -> CommunityContext:
    summary = summarize_reports(district=district)

    matching_reports = [
        report
        for report in load_reports()
        if str(report.get("district", "")).lower() == district.lower()
    ]

    recent: List[dict] = []
    for report in matching_reports[:MAX_RECENT_REPORTS]:
        recent.append({
            "report_type": canonical_report_type(report.get("report_type", "other")),
            "severity": report.get("severity", "moderate"),
            "description": report.get("description", ""),
            "verification_status": report.get("verification_status", "unverified"),
            "created_at": report.get("created_at"),
        })

    return CommunityContext(
        feedback_signal=summary["feedback_signal"],
        total_reports=summary["total_reports"],
        by_severity=summary["by_severity"],
        by_type=summary["by_type"],
        recent_reports=recent,
    )


def build_community_evidence_by_region(region_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """Real per-region community ground-truth summary, restricted to the
    real admin1 region names the caller actually cares about (e.g. this
    period's priority_area_justifications) -- so a region with reports but
    no forecast evidence for this period never leaks in, and a region with
    zero reports is simply absent from the returned dict rather than padded
    with an empty entry (callers should treat "not in this dict" as "no
    reports", the same explicit-omission convention used elsewhere).

    Deliberately NOT cached (unlike build_national_region_evidence, which
    caches to disk since rasters only change per period) -- community
    reports are submitted in real time, so this must be recomputed fresh on
    every call or a report submitted minutes ago would stay invisible until
    the next raster-driven cache rebuild, which could be days away.

    Matches each report's real `region` field (falling back to `district`
    for older/malformed reports where `region` was never set) against the
    given region_names, case-insensitively -- no fuzzy matching, since a
    real mismatch (typo, a region renamed) should surface as "no reports"
    rather than a silently wrong match.
    """
    normalized_targets = {name.lower(): name for name in region_names}
    if not normalized_targets:
        return {}

    reports_by_region: Dict[str, List[dict]] = {}
    for report in load_reports():
        region_key = str(report.get("region") or report.get("district") or "").strip().lower()
        real_name = normalized_targets.get(region_key)
        if not real_name:
            continue
        reports_by_region.setdefault(real_name, []).append(report)

    evidence: Dict[str, Dict[str, Any]] = {}
    for region_name, region_reports in reports_by_region.items():
        by_severity: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for report in region_reports:
            severity = report.get("severity", "moderate")
            report_type = canonical_report_type(report.get("report_type", "other"))
            by_severity[severity] = by_severity.get(severity, 0) + 1
            by_type[report_type] = by_type.get(report_type, 0) + 1

        # Same thresholds AND verified-report weighting as summarize_reports
        # (server truth) -- not reinvented here.
        weighted_count = weighted_high_or_severe_count(region_reports)
        if weighted_count >= 3:
            feedback_signal = "strong_ground_signal"
        elif len(region_reports) >= 3:
            feedback_signal = "emerging_ground_signal"
        elif len(region_reports) > 0:
            feedback_signal = "limited_ground_signal"
        else:
            feedback_signal = "no_ground_signal"

        recent_sorted = sorted(
            region_reports, key=lambda item: item.get("created_at", ""), reverse=True,
        )
        recent_excerpts = [
            {
                "report_type": canonical_report_type(item.get("report_type", "other")),
                "severity": item.get("severity", "moderate"),
                "verification_status": item.get("verification_status", "unverified"),
                "description": (item.get("description") or "")[:DESCRIPTION_EXCERPT_CHARS],
            }
            for item in recent_sorted[:MAX_RECENT_REPORTS_PER_REGION]
        ]

        verified_count = sum(
            1 for report in region_reports if report.get("verification_status") == "verified"
        )

        evidence[region_name] = {
            "total_reports": len(region_reports),
            "by_severity": by_severity,
            "by_type": by_type,
            "feedback_signal": feedback_signal,
            "recent_reports": recent_excerpts,
            "verified_count": verified_count,
        }

    return evidence
