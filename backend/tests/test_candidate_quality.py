from custom_bt.factor_generation import _single_factor_root
_single_factor_root()
from dataclasses import replace
import json
import pytest
from single_factor.config import QualityConfig
from single_factor.evaluator import SegmentMetrics, SingleFactorEvaluator, SingleFactorMetrics
from single_factor.storage import FactorStorage


def evaluator():
    return SingleFactorEvaluator(None, 20)


def metrics(sign=1):
    return SegmentMetrics(ic=sign*0.06, rank_ic=sign*0.04, icir=sign*0.6, coverage=0.9, valid_days=30)


@pytest.mark.parametrize("sign", [1, -1])
def test_candidate_and_confirmed_thresholds_accept_both_aligned_directions(sign):
    e = evaluator()
    assert e._accept({"train": metrics(sign), "valid": metrics(sign)}) is None
    assert e.confirmation_rejection(sign*0.06, metrics(sign)) is None


@pytest.mark.parametrize("stage,field,value", [
    ("train", "coverage", .899), ("train", "ic", .049), ("train", "rank_ic", .029),
    ("train", "icir", .499), ("valid", "coverage", .899), ("valid", "ic", .029),
    ("valid", "rank_ic", .029), ("valid", "icir", .299),
    ("valid", "ic", -.04), ("valid", "rank_ic", -.04), ("valid", "icir", -.4),
    ("valid", "ic", float("nan")), ("train", "ic", 0)])
def test_candidate_rejection_names_stage_and_metric(stage, field, value):
    segments = {"train": metrics(), "valid": metrics()}
    segments[stage] = replace(segments[stage], **{field:value})
    reason = evaluator()._accept(segments)
    assert reason and stage in reason


@pytest.mark.parametrize("field,value", [("coverage",.899),("ic",.029),("rank_ic",.029),
    ("icir",.299),("ic",-.04),("rank_ic",-.04),("icir",-.4),("coverage",float("inf"))])
def test_test_confirmation_rejects_threshold_and_sign_failures(field,value):
    assert evaluator().confirmation_rejection(.06, replace(metrics(),**{field:value}))


def test_validation_is_required_and_test_never_substitutes():
    assert "valid" in evaluator()._accept({"train":metrics(),"test":metrics()})


def test_candidate_storage_and_freeze(tmp_path):
    storage=FactorStorage(tmp_path)
    record=SingleFactorMetrics("rank(close)",.06,.04,.6,.9,.5,True,None,{"train":metrics(),"valid":metrics()})
    assert storage.record(record)
    row=json.loads(storage.candidate_path.read_text())
    assert row["status"]=="candidate" and row["factor_id"].startswith("factor_0001_")
    assert not (tmp_path/"accepted_factors.jsonl").exists()
    assert storage.candidate_count==1
    (tmp_path/"confirmation_request.json").write_text("{}")
    with pytest.raises(ValueError,match="frozen"):
        storage.record(record)
    with pytest.raises(ValueError,match="frozen"):
        FactorStorage(tmp_path)


def test_atomic_state_failure_preserves_old_file(tmp_path,monkeypatch):
    storage=FactorStorage(tmp_path)
    storage.save_state({"attempts":1})
    def denied(*args):
        raise PermissionError("locked")
    monkeypatch.setattr("single_factor.storage.os.replace",denied)
    monkeypatch.setattr("single_factor.storage.time.sleep",lambda _:None)
    with pytest.raises(PermissionError):
        storage.save_state({"attempts":2})
    assert storage.load_state()=={"attempts":1}


def test_exact_ninety_percent_finite_coverage_passes_without_float32_rounding():
    import torch
    from types import SimpleNamespace
    values = torch.arange(10, dtype=torch.float32).repeat(2, 1)
    target = values.clone()
    values[:, 0] = float("nan")
    panel = SimpleNamespace(target=lambda _: target, max_backtrack_days=0)
    expression = SimpleNamespace(evaluate=lambda _: values)
    e = SingleFactorEvaluator(panel, 1, valid_panel=panel)
    metrics = e._segment_metrics(expression, panel)
    assert metrics.coverage == 0.9
    assert e._accept({"train": metrics, "valid": metrics}) is None


def test_confirmation_parser_understands_stored_canonical_operator_names():
    from single_factor.expression import SingleFactorParser
    from custom_bt.canonical_expression import serialize_alphagen_expression
    parser = SingleFactorParser(["close"])
    for expression in ("rank(close)", "ts_mean(close,2)", "add(ts_std(close,3),1.0)"):
        parsed = parser.parse(expression)
        assert serialize_alphagen_expression(parsed) == expression


def test_nested_history_budget_rejected_before_evaluation():
    from single_factor.expression import SingleFactorParser, required_history
    from single_factor.evaluator import SingleFactorEvaluator
    from types import SimpleNamespace
    parser = SingleFactorParser(["close"])
    expr = parser.parse("delay(ts_mean(close,20),90)")
    assert required_history(expr) == 109
    evaluator = SingleFactorEvaluator(SimpleNamespace(max_backtrack_days=100), 5)
    result = evaluator.evaluate(expr)
    assert not result.accepted
    assert "history budget exceeded" in result.reason
    assert required_history(parser.parse("add(close,1)")) == 0
    assert required_history(parser.parse("ts_mean(close,20)")) == 19
