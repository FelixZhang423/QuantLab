import json

import pandas as pd
import pytest

from research_pipeline.research_system.classification import infer_category
from research_pipeline.research_system.conditional_run import assign_time_splits, run_conditional_evaluation
from research_pipeline.research_system.cli import build_parser


def test_assign_time_splits_is_chronological_and_covers_all_dates():
    dates = pd.date_range("2024-01-01", periods=10)

    result = assign_time_splits(dates, train_ratio=0.6, valid_ratio=0.2)

    assert result.tolist() == ["train"] * 6 + ["valid"] * 2 + ["test"] * 2
    assert result.index.equals(pd.DatetimeIndex(dates))


def test_conditional_cli_exposes_time_split_ratios():
    args = build_parser().parse_args([
        "conditional",
        "--values-run", "values",
        "--state-run", "states",
        "--train-ratio", "0.7",
        "--valid-ratio", "0.1",
    ])

    assert args.train_ratio == 0.7
    assert args.valid_ratio == 0.1


def test_infer_category_uses_expression_field_families():
    assert infer_category("ts_mean(close,20)")["category"] == "trend"
    assert infer_category("ts_std(volume,20)")["category"] == "volatility"
    assert infer_category("log(volume)")["category"] == "liquidity"


def test_run_conditional_evaluation_reads_factor_partitions(tmp_path):
    data_root = tmp_path / "research_data"
    snapshot = data_root / "snapshots" / "snap"
    snapshot.mkdir(parents=True)
    dates = pd.date_range("2024-01-01", periods=4)
    market = pd.DataFrame(
        [
            {"date": date, "code": code, "close": value}
            for date, values in zip(dates, [[10, 11, 12], [10, 11, 12], [10, 11, 12], [10, 11, 12]])
            for code, value in zip(["000001", "000002", "000003"], values)
        ]
    )
    market.to_parquet(snapshot / "market.parquet", index=False)
    catalog = pd.DataFrame({"factor_id": ["f1"], "expression": ["close"], "accepted": [True]})
    catalog.to_parquet(snapshot / "factor_catalog.parquet", index=False)
    (data_root / "current.txt").write_text("snap\n", encoding="utf-8")

    value_run = tmp_path / "value_run"
    value_dir = value_run / "factor_values" / "factor_id=f1"
    value_dir.mkdir(parents=True)
    values = market.assign(factor_id="f1", value=market["close"])
    values[["date", "code", "factor_id", "value"]].to_parquet(value_dir / "values.parquet", index=False)
    (value_run / "factor_values_manifest.json").write_text(json.dumps({"snapshot_id": "snap"}), encoding="utf-8")

    states = pd.DataFrame({"date": dates, "state_id": ["bull", "bull", "bear", "bear"]})
    state_run = tmp_path / "state_run"
    state_run.mkdir()
    states.to_parquet(state_run / "market_states.parquet", index=False)

    result = run_conditional_evaluation(data_root, value_run, state_run, tmp_path / "runs", snapshot_id="snap", horizon=1)

    assert result["computed"] == 1
    output = pd.read_parquet(tmp_path / "runs" / result["run_id"] / "conditional_metrics.parquet")
    assert set(output["state_id"]) == {"bull", "bear"}
    assert output["category"].tolist() == ["price", "price"]


def test_run_conditional_evaluation_rejects_value_run_from_another_snapshot(tmp_path):
    data_root = tmp_path / "research_data"
    snapshot = data_root / "snapshots" / "snap"
    snapshot.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01"]),
            "code": ["000001"],
            "close": [10.0],
        }
    ).to_parquet(snapshot / "market.parquet", index=False)
    pd.DataFrame({"factor_id": ["f1"], "expression": ["close"]}).to_parquet(
        snapshot / "factor_catalog.parquet", index=False
    )
    (data_root / "current.txt").write_text("snap\n", encoding="utf-8")

    value_run = tmp_path / "value_run"
    value_dir = value_run / "factor_values" / "factor_id=f1"
    value_dir.mkdir(parents=True)
    pd.DataFrame(
        {"date": pd.to_datetime(["2024-01-01"]), "code": ["000001"], "value": [1.0]}
    ).to_parquet(value_dir / "values.parquet", index=False)
    (value_run / "factor_values_manifest.json").write_text(
        json.dumps({"snapshot_id": "other-snapshot"}), encoding="utf-8"
    )
    state_run = tmp_path / "state_run"
    state_run.mkdir()
    pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "state_id": ["bull"]}).to_parquet(
        state_run / "market_states.parquet", index=False
    )

    with pytest.raises(ValueError, match="snapshot mismatch"):
        run_conditional_evaluation(
            data_root,
            value_run,
            state_run,
            tmp_path / "runs",
            snapshot_id="snap",
            horizon=1,
        )
