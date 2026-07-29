def test_save_and_get_round_trip(temp_repository, sample_envelope):
    temp_repository.save(sample_envelope)

    fetched = temp_repository.get(sample_envelope.context_id)

    assert fetched is not None
    assert fetched.context_id == sample_envelope.context_id
    assert fetched.geography.area_name == sample_envelope.geography.area_name


def test_get_returns_none_for_unknown_context_id(temp_repository):
    assert temp_repository.get("does-not-exist") is None


def test_list_recent_returns_saved_contexts(temp_repository, sample_envelope):
    temp_repository.save(sample_envelope)

    recent = temp_repository.list_recent(limit=10)

    assert len(recent) == 1
    assert recent[0]["context_id"] == sample_envelope.context_id
    assert recent[0]["trigger_status"] == sample_envelope.policy.trigger_status


def test_list_recent_respects_limit(temp_repository, sample_envelope):
    for index in range(3):
        envelope = sample_envelope.model_copy(deep=True)
        envelope.context_id = f"test-context-id-{index:04d}"
        envelope.provenance.context_id = envelope.context_id
        temp_repository.save(envelope)

    recent = temp_repository.list_recent(limit=2)
    assert len(recent) == 2
