from app.context.hashing import compute_context_fingerprint, sha256_of


def test_sha256_of_is_stable_for_same_input():
    value = {"a": 1, "b": [1, 2, 3]}
    assert sha256_of(value) == sha256_of(value)


def test_sha256_of_ignores_key_order():
    assert sha256_of({"a": 1, "b": 2}) == sha256_of({"b": 2, "a": 1})


def test_sha256_of_changes_with_value():
    assert sha256_of({"a": 1}) != sha256_of({"a": 2})


def _base_fingerprint_kwargs():
    return dict(
        forecast_data_hash="f1", community_data_hash="c1", exposure_data_hash="e1",
        knowledge_base_hash="k1", decision_policy_hash="p1", prompt_version="v1",
    )


def test_fingerprint_same_inputs_same_fingerprint():
    kwargs = _base_fingerprint_kwargs()
    assert compute_context_fingerprint(**kwargs) == compute_context_fingerprint(**kwargs)


def test_fingerprint_changes_when_forecast_hash_changes():
    kwargs = _base_fingerprint_kwargs()
    original = compute_context_fingerprint(**kwargs)
    kwargs["forecast_data_hash"] = "f2"
    assert compute_context_fingerprint(**kwargs) != original


def test_fingerprint_changes_when_community_hash_changes():
    kwargs = _base_fingerprint_kwargs()
    original = compute_context_fingerprint(**kwargs)
    kwargs["community_data_hash"] = "c2"
    assert compute_context_fingerprint(**kwargs) != original


def test_fingerprint_changes_when_knowledge_base_hash_changes():
    kwargs = _base_fingerprint_kwargs()
    original = compute_context_fingerprint(**kwargs)
    kwargs["knowledge_base_hash"] = "k2"
    assert compute_context_fingerprint(**kwargs) != original


def test_fingerprint_changes_when_policy_hash_changes():
    kwargs = _base_fingerprint_kwargs()
    original = compute_context_fingerprint(**kwargs)
    kwargs["decision_policy_hash"] = "p2"
    assert compute_context_fingerprint(**kwargs) != original


def test_fingerprint_changes_when_prompt_version_changes():
    kwargs = _base_fingerprint_kwargs()
    original = compute_context_fingerprint(**kwargs)
    kwargs["prompt_version"] = "v2"
    assert compute_context_fingerprint(**kwargs) != original
