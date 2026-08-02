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


def test_reason_codes_and_reason_cite_real_hazard_not_generic_priority_score(sample_envelope):
    # sample_envelope's hazard_type is "drought" -- reason_codes/reason must
    # name the real hazard being classified, never the generic
    # priority_score wording this replaced.
    envelope = _with_trigger_status(sample_envelope, "trigger")
    result = trigger_engine.evaluate(envelope)

    assert any("drought_risk_above" in code for code in result["reason_codes"])
    assert not any("priority_score" in code for code in result["reason_codes"])
    assert "priority_score" not in result["reason"]
    assert "drought_risk" in result["reason"]


def test_exposure_ranked_envelope_falls_back_to_more_severe_real_hazard(sample_envelope):
    # hazard_type=None (Exposure ranking) with real drought_risk/wet_risk on
    # the envelope -- must classify from whichever is actually more severe,
    # not the generic priority_score (this was the exact confirmed bug).
    envelope = sample_envelope.model_copy(deep=True)
    envelope.hazard_evidence.hazard_type = None
    envelope.hazard_evidence.drought_risk = {"value": 20.0, "level": "watch"}
    envelope.hazard_evidence.wet_risk = {"value": 40.0, "level": "trigger"}
    envelope.policy.trigger_status = "trigger"

    result = trigger_engine.evaluate(envelope)

    assert any("wet_risk_above" in code for code in result["reason_codes"])
    assert "wet_risk" in result["reason"]
    assert "40.0" in result["reason"]
