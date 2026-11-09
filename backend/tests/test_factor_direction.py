from custom_bt.factor_direction import direction_metadata, orient_expression


def test_direction_uses_training_only_and_is_idempotent():
    record = {"ic": 0.8, "segments": {"train": {"ic": -0.2}, "valid": {"ic": 0.9}, "test": {"ic": 1}}}
    effective, metadata = orient_expression("close", record)
    assert effective == "-(close)"
    assert metadata["training_ic"] == -0.2
    assert orient_expression(effective, {**record, **metadata})[0] == effective


def test_legacy_positive_zero_and_missing_training_ic():
    assert direction_metadata({"ic": -0.1})["direction"] == -1
    assert orient_expression("close", {"ic": 0.1})[0] == "close"
    assert direction_metadata({"ic": 0})["direction_source"] == "zero_train_ic_preserve_expression"
    result = direction_metadata({"segments": {"valid": {"ic": -1}}})
    assert result["direction"] == 1
    assert result["training_ic"] is None
    assert result["direction_source"] == "missing_train_ic_preserve_expression"


def test_composition_orients_expression_and_signed_metrics_together():
    from custom_bt.factor_composition import load_composition_candidates
    record = {"expression": "close", "pool_id": "p", "ic": -0.2,
              "rank_ic": -0.3, "icir": -0.5, "segments": {"valid": {"ic": 0.8}}}
    candidate = load_composition_candidates([record], pool_id="p", min_ic=0.1)[0]
    assert candidate.canonical_expression == "close"
    assert candidate.backtest_expression == "-(close)"
    assert candidate.metric("ic") == 0.2
    assert candidate.raw["direction"] == -1
    assert candidate.raw["ic"] == -0.2


def test_composition_uses_segment_train_ic_instead_of_stale_top_metric():
    from custom_bt.factor_composition import load_composition_candidates
    candidate = load_composition_candidates([
        {"expression": "close", "ic": 0.8, "segments": {"train": {"ic": -0.2}}}], pool_id=None)[0]
    assert candidate.metric("ic") == 0.2
    assert candidate.backtest_expression == "-(close)"
