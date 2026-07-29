from app.api.action_tracker_shape import (
    canonicalize_context_task,
    canonicalize_legacy_task,
)


def test_canonicalize_legacy_task_adds_context_shaped_mirrors():
    task = {
        "id": "borena_disaster_manager_task_1",
        "suggested_deadline": "Within 14 days",
        "status": "Not started",
    }

    result = canonicalize_legacy_task(task)

    assert result["task_id"] == "borena_disaster_manager_task_1"
    assert result["deadline"] == "Within 14 days"
    assert result["context_id"] is None
    assert result["approval_status"] == "Not required"
    assert result["evidence_basis"] == []
    assert result["knowledge_source_ids"] == []
    assert result["outcome_status"] is None
    assert result["completed_at"] is None
    assert result["source"] == "legacy"


def test_canonicalize_legacy_task_never_clobbers_existing_keys():
    task = {"id": "task_1", "approval_status": "Pending", "evidence_basis": ["x"]}

    result = canonicalize_legacy_task(task)

    assert result["approval_status"] == "Pending"
    assert result["evidence_basis"] == ["x"]


def test_canonicalize_context_task_adds_legacy_shaped_mirrors():
    task = {
        "task_id": "erer_hr_ctx_abc12345_task_1",
        "deadline": "Within 24 hours",
        "status": "Not started",
    }

    result = canonicalize_context_task(task, audience="disaster_manager")

    assert result["id"] == "erer_hr_ctx_abc12345_task_1"
    assert result["suggested_deadline"] == "Within 24 hours"
    assert result["audience"] == "disaster_manager"
    assert result["country"] == ""
    assert result["rank"] is None
    assert result["updated_by"] == ""
    assert result["source"] == "context"


def test_canonicalize_context_task_never_clobbers_existing_keys():
    task = {"task_id": "task_1", "rank": 3, "country": "ethiopia", "updated_by": "tester"}

    result = canonicalize_context_task(task, audience="disaster_manager")

    assert result["rank"] == 3
    assert result["country"] == "ethiopia"
    assert result["updated_by"] == "tester"
