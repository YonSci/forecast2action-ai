from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.community_reports_store import VerifyReportRequest
from app.api.main import verify_community_report


def test_verify_community_report_sets_status_and_reviewer():
    fake_reports = [
        {"id": "abc123", "district": "Test District", "verification_status": "unverified"},
    ]
    with patch("app.api.main.load_reports", return_value=fake_reports), \
         patch("app.api.main.save_reports") as mock_save:
        result = verify_community_report(
            "abc123", VerifyReportRequest(verified_by="Woreda focal point", status="verified"),
        )

    assert result["success"] is True
    assert result["report"]["verification_status"] == "verified"
    assert result["report"]["verified_by"] == "Woreda focal point"
    assert result["report"]["verified_at"] is not None
    mock_save.assert_called_once()


def test_verify_community_report_supports_dispute_status():
    fake_reports = [{"id": "abc123", "verification_status": "unverified"}]
    with patch("app.api.main.load_reports", return_value=fake_reports), \
         patch("app.api.main.save_reports"):
        result = verify_community_report(
            "abc123", VerifyReportRequest(verified_by="NGO partner", status="disputed"),
        )

    assert result["report"]["verification_status"] == "disputed"


def test_verify_community_report_rejects_unknown_status():
    with pytest.raises(HTTPException) as exc_info:
        verify_community_report("abc123", VerifyReportRequest(verified_by="x", status="bogus"))

    assert exc_info.value.status_code == 400


def test_verify_community_report_404s_for_unknown_id():
    with patch("app.api.main.load_reports", return_value=[]):
        with pytest.raises(HTTPException) as exc_info:
            verify_community_report(
                "does-not-exist", VerifyReportRequest(verified_by="x", status="verified"),
            )

    assert exc_info.value.status_code == 404
