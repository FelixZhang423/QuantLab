import json

import pandas as pd
import pytest

from research_pipeline.research_system.exporter import ExportSources, export_snapshot


def _write_fixture_sources(tmp_path):
    panel_path = tmp_path / "panel.parquet"
    pd.DataFrame(
        {
            "timestamps": ["2024-01-02", "2024-01-03", "2024-01-02"],
            "code": [1, 1, 2],
            "open": [10, 11, 20],
            "close": [11, 12, 19],
            "high": [11, 12, 20],
            "low": [9, 10, 18],
            "vol": [100, 110, 200],
            "amount": [1000, 1200, 3800],
        }
    ).to_parquet(panel_path, index=False)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    (pool_dir / "codes.txt").write_text("000001\n000002\n", encoding="utf-8")
    (pool_dir / "manifest.json").write_text(
        json.dumps({
            "pool_id": "demo_pool",
            "source_signature": "sig-1",
            "selection_end": "2024-01-01",
        }),
        encoding="utf-8",
    )

    factor_dir = tmp_path / "factor_runs" / "run-1"
    factor_dir.mkdir(parents=True)
    (factor_dir / "factor_run.json").write_text(
        json.dumps({"pool_id": "demo_pool", "source_signature": "sig-1"}),
        encoding="utf-8",
    )
    (factor_dir / "accepted_factors.jsonl").write_text(
        json.dumps({
            "factor_id": "f1",
            "expression": "rank(close)",
            "accepted": True,
            "ic": 0.08,
            "rank_ic": 0.1,
            "icir": 0.9,
            "coverage": 0.99,
        }) + "\n",
        encoding="utf-8",
    )

    backtest_dir = tmp_path / "backtests" / "run-1"
    backtest_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "factor_id": ["f1"],
            "expression": ["rank(close)"],
            "pool_id": ["demo_pool"],
            "accepted": [True],
            "backtest_sharpe": [1.2],
            "backtest_max_drawdown": [-0.2],
        }
    ).to_csv(backtest_dir / "factor_backtest_summary.csv", index=False)

    return ExportSources(
        market_panel=panel_path,
        pool_dir=pool_dir,
        factor_runs_root=tmp_path / "factor_runs",
        backtests_root=tmp_path / "backtests",
    )


def test_export_snapshot_writes_independent_tables_and_manifest(tmp_path):
    target = tmp_path / "research_data"
    result = export_snapshot(_write_fixture_sources(tmp_path), target, snapshot_id="demo")
    snapshot = target / "snapshots" / "demo"

    assert result["snapshot_id"] == "demo"
    assert (snapshot / "market.parquet").exists()
    assert (snapshot / "universe.csv").exists()
    assert (snapshot / "factor_catalog.parquet").exists()
    assert (snapshot / "factor_metrics.parquet").exists()
    assert (snapshot / "backtest_metrics.parquet").exists()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["valid"] is True
    assert all("sha256" in item and "rows" in item for item in manifest["files"])
    assert (target / "current.txt").read_text(encoding="utf-8") == "demo\n"
    assert list(pd.read_csv(snapshot / "backtest_runs.csv").columns) == ["backtest_run_id", "source_path"]


def test_export_snapshot_does_not_overwrite_existing_snapshot(tmp_path):
    sources = _write_fixture_sources(tmp_path)
    target = tmp_path / "research_data"
    export_snapshot(sources, target, snapshot_id="demo")

    with pytest.raises(FileExistsError):
        export_snapshot(sources, target, snapshot_id="demo")
