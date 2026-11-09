import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from custom_bt.factor_generation import run_factor_generation
from custom_bt.factor_confirmation import confirm_factor_run
from repositories import company_source
from repositories.factor_run_store import read_jsonl, confirmed_records


@pytest.fixture
def generated(tmp_path, monkeypatch):
    dates = pd.date_range("2024-01-01", "2024-06-30")
    rates = [-0.02, -0.01, 0.01, 0.02]
    rows = []
    for i, day in enumerate(dates):
        for j, rate in enumerate(rates):
            close = 100 * (1 + rate) ** i
            rows.append(dict(date=day, code=f"{j+1:06d}", close=close, open=close,
                             signal=rate, unstable=rate if day.month < 6 else -rate,
                             Ifsuspend=0, if_up=0, if_down=0))
    frame = pd.DataFrame(rows)

    def writer(codes, fields, path, start, end):
        frame.loc[(frame.date >= start) & (frame.date <= end), ["date", "code", *fields]].to_parquet(path, index=False)
    monkeypatch.setattr(company_source, "write_pool_panel", writer)

    def ppo(**options):
        from single_factor.storage import FactorStorage
        from single_factor.expression import SingleFactorParser
        storage = FactorStorage(options["output_dir"], metadata=options["storage_metadata"])
        parser = SingleFactorParser(options["feature_names"])
        for text in ("CSRank($signal)", "Add($unstable,0)"):
            metrics = options["evaluator"].evaluate(parser.parse(text))
            assert metrics.accepted, metrics.reason
            storage.record(metrics)
        return SimpleNamespace(accepted_count=2, attempts=2, target_reached=True, attempts_exhausted=False)
    run = run_factor_generation(
        pools_root=tmp_path / "pools", pool_id="p", runtime_root=tmp_path / "runtime",
        factor_runs_root=tmp_path / "runs", fields=["signal", "unstable"],
        splits={"train": {"cache_start": "2024-01-01", "cache_end": "2024-01-30"},
                "valid": {"cache_start": "2024-03-15", "cache_end": "2024-04-15"},
                "test": {"cache_start": "2024-06-01", "cache_end": "2024-06-30"}},
        max_backtrack_days=2, target_horizon=1, max_future_days=1,
        generation_config={"target_factor_count": 2, "max_attempts": 2}, ppo_runner=ppo,
        pool_manifest={"pool_id": "p", "data_source": "clickhouse", "source_signature": company_source.source_signature()},
        pool_codes=[f"{j+1:06d}" for j in range(4)], snapshot_root=tmp_path / "snapshots")
    return Path(run["factor_run_dir"]), tmp_path / "snapshots"


def test_post_ppo_confirmation_persists_all_results_and_reuses_without_test(generated):
    root, snapshots = generated
    assert len(read_jsonl(root / "candidate_factors.jsonl")) == 2
    assert not (root / "confirmed_factors.jsonl").exists()
    assert not (root / "accepted_factors.jsonl").exists()
    first = confirm_factor_run(root, snapshots)
    assert first["confirmed_count"] == 1
    assert first["rejected_count"] == 1
    evaluations = read_jsonl(root / "test_evaluations.jsonl")
    assert len(evaluations) == 2
    assert all(item["test"] is not None for item in evaluations)
    assert len(confirmed_records(root)) == 1
    assert "test" in confirmed_records(root)[0]["segments"]
    from single_factor.evaluator import SingleFactorEvaluator
    with patch.object(SingleFactorEvaluator, "evaluate_holdout", side_effect=AssertionError("must not repeat")):
        assert confirm_factor_run(root, snapshots) == first


def test_confirmation_freezes_candidate_set_and_thresholds(generated):
    root, snapshots = generated
    confirm_factor_run(root, snapshots)
    run = json.loads((root / "factor_run.json").read_text(encoding="utf-8"))
    run["hyperparameters"]["quality"]["min_test_ic"] = 0.04
    (root / "factor_run.json").write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(ValueError, match="门槛已变化"):
        confirm_factor_run(root, snapshots)


def test_generation_already_freezes_thresholds_before_first_confirmation(generated):
    root, snapshots = generated
    from single_factor.storage import FactorStorage
    with pytest.raises(ValueError, match="frozen"):
        FactorStorage(root)
    run = json.loads((root / "factor_run.json").read_text(encoding="utf-8"))
    run["hyperparameters"]["quality"]["min_test_ic"] = 0.01
    (root / "factor_run.json").write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(ValueError, match="门槛已变化"):
        confirm_factor_run(root, snapshots)
    assert not (root / "test_evaluations.jsonl").exists()


def test_confirmation_resume_does_not_reevaluate_durable_candidates(generated):
    root, snapshots = generated
    def interrupted(progress):
        raise RuntimeError("interrupted after durable journal append")
    with pytest.raises(RuntimeError, match="interrupted"):
        confirm_factor_run(root, snapshots, progress_callback=interrupted)
    assert len(read_jsonl(root / "test_evaluations.jsonl")) == 1
    with (root / "test_evaluations.jsonl").open("ab") as handle:
        handle.write(b'{"partial')
    from single_factor.evaluator import SingleFactorEvaluator
    original = SingleFactorEvaluator.evaluate_holdout
    calls = []
    def evaluate(self, expr):
        calls.append(str(expr))
        return original(self, expr)
    with patch.object(SingleFactorEvaluator, "evaluate_holdout", evaluate):
        result = confirm_factor_run(root, snapshots)
    assert len(calls) == 1
    assert result["candidate_count"] == 2


def test_finished_confirmation_repairs_summary_after_publish_crash(generated):
    root, snapshots = generated
    from custom_bt import factor_confirmation as module
    original = module.atomic_write_json
    def fail_run_summary(path, value):
        if path.name == "factor_run.json":
            raise PermissionError("summary write interrupted")
        return original(path, value)
    with patch.object(module, "atomic_write_json", fail_run_summary):
        with pytest.raises(PermissionError):
            confirm_factor_run(root, snapshots)
    assert json.loads((root / "factor_run.json").read_text(encoding="utf-8"))["confirmed_count"] == 0
    from single_factor.evaluator import SingleFactorEvaluator
    with patch.object(SingleFactorEvaluator, "evaluate_holdout", side_effect=AssertionError("no repeated test")):
        final = confirm_factor_run(root, snapshots)
    assert final["confirmed_count"] == 1
    assert json.loads((root / "factor_run.json").read_text(encoding="utf-8"))["confirmed_count"] == 1
