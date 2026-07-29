from app.decision import trigger_engine


def _with_trigger_status(envelope, status):
    envelope = envelope.model_copy(deep=True)
    envelope.policy.trigger_status = status
    return envelope


def test_trigger_status_triggered_for_trigger(sample_envelope):
    envelope = _with_trigger_status(sample_envelope, "trigger")
    result = trigger_engine.evaluate(envelope)
    assert result["triggered"] is True
    assert result["approval_required"] is True


def test_trigger_status_triggered_for_warning(sample_envelope):
    envelope = _with_trigger_status(sample_envelope, "warning")
    result = trigger_engine.evaluate(envelope)
    assert result["triggered"] is True
    assert result["approval_required"] is False


def test_trigger_status_not_triggered_for_watch(sample_envelope):
    envelope = _with_trigger_status(sample_envelope, "watch")
    result = trigger_engine.evaluate(envelope)
    assert result["triggered"] is False


def test_trigger_status_not_triggered_for_no_alert(sample_envelope):
    envelope = _with_trigger_status(sample_envelope, "no_alert")
    result = trigger_engine.evaluate(envelope)
    assert result["triggered"] is False


def test_reason_codes_include_community_signal(sample_envelope):
    envelope = sample_envelope.model_copy(deep=True)
    envelope.community.feedback_signal = "strong_ground_signal"
    result = trigger_engine.evaluate(envelope)
    assert "community_signal_strong_ground_signal" in result["reason_codes"]


def test_policy_id_reflects_envelope_policy(sample_envelope):
    result = trigger_engine.evaluate(sample_envelope)
    assert result["policy_id"] == sample_envelope.policy.policy_id
