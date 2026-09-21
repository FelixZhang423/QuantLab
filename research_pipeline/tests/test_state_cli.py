import json

import pandas as pd

from research_pipeline.research_system.research_run import run_state_analysis


def test_run_state_analysis_consumes_snapshot_and_writes_state_table(tmp_path):
    data_root = tmp_path / "research_data"
    snapshot = data_root / "snapshots" / "snap"
    snapshot.mkdir(parents=True)
    market = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]),
            "code": ["000001", "000002", "000001", "000002"],
            "close": [10.0, 10.0, 11.0, 9.0],
        }
    )
    market.to_parquet(snapshot / "market.parquet", index=False)
    (data_root / "current.txt").write_text("snap\n", encoding="utf-8")
    (snapshot / "manifest.json").write_text(json.dumps({"snapshot_id": "snap"}), encoding="utf-8")

    result = run_state_analysis(data_root, tmp_path / "runs", snapshot_id="snap", volatility_window=2)

    assert result["snapshot_id"] == "snap"
    assert (tmp_path / "runs" / result["run_id"] / "market_states.parquet").exists()
    assert result["state_count"] == 2
