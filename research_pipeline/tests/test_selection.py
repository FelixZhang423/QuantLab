import pandas as pd

from research_pipeline.research_system.selection import (
    equal_weight_portfolio,
    run_selection,
    score_categories,
    select_factors,
)


def test_score_categories_prefers_the_stronger_state_specific_group():
    metrics = pd.DataFrame(
        {
            "factor_id": ["f1", "f2", "f3"],
            "state_id": ["bull", "bull", "bull"],
            "rank_ic_mean": [0.10, 0.08, 0.02],
            "icir": [1.0, 0.7, 0.3],
            "sample_count": [20, 20, 20],
        }
    )
    catalog = pd.DataFrame({"factor_id": ["f1", "f2", "f3"], "category": ["trend", "trend", "reversal"]})

    result = score_categories(metrics, catalog, state_id="bull")

    assert result.iloc[0]["category"] == "trend"
    assert result.iloc[0]["factor_count"] == 2


def test_score_categories_uses_conditional_category_and_requested_split():
    metrics = pd.DataFrame(
        {
            "factor_id": ["f1", "f1"],
            "category": ["trend", "trend"],
            "state_id": ["bull", "bull"],
            "split": ["train", "test"],
            "rank_ic_mean": [0.10, 0.90],
            "icir": [1.0, 9.0],
            "sample_count": [20, 20],
        }
    )
    catalog = pd.DataFrame({"factor_id": ["f1"], "category": [None]})

    result = score_categories(metrics, catalog, state_id="bull", split="train")

    assert result.to_dict("records") == [{
        "category": "trend",
        "score": 0.37,
        "factor_count": 1,
        "mean_rank_ic": 0.10,
        "mean_icir": 1.0,
    }]


def test_select_factors_logs_highly_correlated_candidate_and_normalizes_weights():
    metrics = pd.DataFrame(
        {
            "factor_id": ["f1", "f2"],
            "category": ["trend", "trend"],
            "state_id": ["bull", "bull"],
            "rank_ic_mean": [0.10, 0.09],
            "icir": [1.0, 0.9],
            "sample_count": [20, 20],
        }
    )
    dates = pd.date_range("2024-01-01", periods=4)
    values = pd.DataFrame(
        [
            {"date": date, "code": code, "factor_id": factor, "value": float(index)}
            for date in dates
            for code, index in [("000001", 1), ("000002", 2), ("000003", 3)]
            for factor in ["f1", "f2"]
        ]
    )
    values.loc[values["factor_id"] == "f2", "value"] *= 2

    result = select_factors(metrics, state_id="bull", category="trend", factor_values=values, top_n=2, correlation_threshold=0.95)
    portfolio = equal_weight_portfolio(result["selected"])

    assert [item["factor_id"] for item in result["selected"]] == ["f1"]
    assert result["rejections"][0]["reason"] == "mutual_correlation"
    assert portfolio == {"f1": 1.0}


def test_run_selection_chooses_category_from_training_split_and_writes_audit(tmp_path):
    data_root = tmp_path / "research_data"
    snapshot = data_root / "snapshots" / "snap"
    snapshot.mkdir(parents=True)
    pd.DataFrame({"factor_id": ["f1", "f2"], "category": [None, None]}).to_parquet(
        snapshot / "factor_catalog.parquet", index=False
    )
    (data_root / "current.txt").write_text("snap\n", encoding="utf-8")

    conditional_run = tmp_path / "conditional"
    conditional_run.mkdir()
    pd.DataFrame(
        {
            "factor_id": ["f1", "f1", "f2", "f2"],
            "category": ["trend", "trend", "price", "price"],
            "state_id": ["bull"] * 4,
            "split": ["train", "test", "train", "test"],
            "rank_ic_mean": [0.10, 0.01, 0.05, 0.05],
            "icir": [1.0, 0.1, 0.5, 0.5],
            "sample_count": [20] * 4,
        }
    ).to_parquet(conditional_run / "conditional_metrics.parquet", index=False)

    result = run_selection(
        data_root,
        conditional_run,
        tmp_path / "runs",
        snapshot_id="snap",
        state_id="bull",
        split="train",
        top_n=1,
    )

    assert result["category"] == "trend"
    assert result["portfolio"] == {"f1": 1.0}
    assert (tmp_path / "runs" / result["run_id"] / "selection.json").exists()
