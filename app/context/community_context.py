"""Builds CommunityContext from real, persisted community reports.

Reads via app.api.community_reports_store (not app.api.main directly --
see that module's docstring for why) so this always reflects whatever
users have actually submitted through POST /api/community-reports, not a
separate client-side-only copy.
"""

from typing import List

from app.api.community_reports_store import canonical_report_type, load_reports, summarize_reports
from app.context.schemas import CommunityContext

MAX_RECENT_REPORTS = 5


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
