from app.decision.action_selector import _classify_action_category, build_tasks_from_context
from app.decision.approval_engine import determine_approval_status
from app.decision.schemas import ActionCategoryRule, Policy

POLICY = Policy(
    policy_id="test_policy_v1",
    hazard_type="drought",
    country="ethiopia",
    thresholds={"trigger": 0.80, "warning": 0.60, "watch": 0.35},
    rank_by_default="population_r_drought",
    action_categories={
        "activation": ActionCategoryRule(approval_required=True),
        "verification": ActionCategoryRule(approval_required=False),
    },
    version="1.0.0",
    valid_from="2025-01-01",
)


def test_classify_action_category_activation():
    assert _classify_action_category("Activate a district coordination meeting.") == "activation"


def test_classify_action_category_verification():
    assert _classify_action_category("Verify water-point status in the field.") == "verification"


def test_determine_approval_status_required():
    assert determine_approval_status("activation", POLICY) == "Pending"


def test_determine_approval_status_not_required():
    assert determine_approval_status("verification", POLICY) == "Not required"


def test_determine_approval_status_unknown_category_defaults_to_not_required():
    assert determine_approval_status("some_unknown_category", POLICY) == "Not required"


def test_build_tasks_from_context_produces_canonical_schema(sample_envelope):
    actions = [{
        "action_id": "act_1",
        "action_text": "Activate a district coordination meeting.",
        "sector": "Disaster Risk Management / Coordination",
        "approval_status": "Pending",
        "evidence_basis": ["priority_score=0.900"],
        "knowledge_source_ids": ["drought_trigger_disaster_manager_001"],
    }]

    tasks = build_tasks_from_context(sample_envelope, actions, "Test Woreda")

    assert len(tasks) == 1
    task = tasks[0]
    for field in (
        "task_id", "context_id", "action_id", "district", "hazard", "risk_level",
        "trigger_status", "responsible_sector", "action", "priority", "deadline",
        "status", "approval_status", "evidence_basis", "knowledge_source_ids",
        "created_at", "updated_at", "updated_by", "completed_at", "outcome_status",
        "outcome_note", "rank", "country", "audience",
    ):
        assert field in task
    assert task["context_id"] == sample_envelope.context_id
    assert task["status"] == "Not started"
    assert task["rank"] == 1
    assert task["country"] == sample_envelope.geography.country
    assert task["audience"] == sample_envelope.operational.audience
